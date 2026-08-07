#!/usr/bin/env python3
"""在量旋云真机上跑一遍电路，产出符合大赛统一 Schema 的 result.json。

跟 run_originq_real.py 是同一个用途：L1"真机接入证据"要求提交的原始产物，
独立于 adapter.py 的 run()（那条路径必须离线可跑，不能依赖真机）。

⚠️⚠️ 必须用 spinq_env 的解释器执行，不能用主 venv！⚠️⚠️
    主 venv 装的是 braket 要求的 antlr4-python3-runtime==4.13.2，spinqit
    需要 4.9.2，两者互斥（跟 src/backends/spinq_backend.py 里 subprocess
    桥接要解决的是同一个冲突）。这个脚本没有走 subprocess 桥接，是直接
    `import spinqit`，所以只能用 spinq_env 自己的解释器跑：

        cd submission
        spinq_env/bin/python3 real_hardware/run_spinq_real.py circuits/bell.qasm \
            --platform superconductor_vp --shots 1000 \
            --out real_hardware/results/spinq_bell.json

    在主 venv 里跑会报 `Could not deserialize ATN with version 3 (expected 4)`。

准备工作（⚠️ 认证方式是 SSH key，不是简单的 API token，跟本源不一样）：
    1. 注册 https://cloud.spinq.cn ，在个人设置里上传你的 SSH 公钥
       （官方文档原话："register and add a public SSH key on
       https://cloud.spinq.cn"）。
    2. export SPINQ_CLOUD_USERNAME="你的用户名"
    3. export SPINQ_CLOUD_KEYFILE="/path/to/.ssh/id_rsa"（本地私钥路径，
       跟你上传的公钥配对）

用法：
    python3 real_hardware/run_spinq_real.py circuits/bell.qasm \
        --platform superconductor_vp --shots 1000 \
        --out real_hardware/results/spinq_bell.json

平台可选 gemini_vp（2 比特）/ triangulum_vp（3 比特）/ superconductor_vp
（8 比特，backend_capabilities.md 里对应"量旋云真机（超导／核磁，2–8比特）"）。

⚠️ 已实测确认的坑：
    0. SpinQ Cloud **不接受电路里显式的 measure 门**——`assemble()` 会直接
       抛 `CircuitOperationValidationError('SpinQ Cloud currently does not
       support explicit invocation of measure gates. A measure will be done
       automatically at the end of the circuit.')`。云端在电路末尾自动对
       全部比特做一次测量，所以这里编译前会把 QASM 里的 `measure ...;`
       行整段删掉再送去编译。**前提假设**：这只对"全比特测量、且
       q[i] 顺次对应 c[i]"的电路安全等价——bell/ghz3/coverage 里的电路
       都是这个模式；如果以后写了只测量部分比特、或者比特跟经典位不是
       自然顺序对应的电路，这个删除逻辑不再等价，需要另外处理。

⚠️ 三个待你实测确认的点（官方文档没写全，只能跑起来看）：
    1. 位序：跟本地模拟器一样先用 swap_basic.qasm 测一下方向对不对，见
       run_originq_real.py 同名注释。
    2. job_id：官方文档原话是"cloud backend 返回的结果只包含概率分布"，
       没提到返回值里带任务 ID——这里先假设拿不到，去
       https://cloud.spinq.cn 的任务记录里按 configure_task() 填的名字核对，
       手动把真实 job_id 填回 result.json。如果实测发现 `backend.execute()`
       返回的对象其实有 job_id/task_id 属性（`print(dir(res))` 看一眼），
       改这里直接读出来更省事。
    3. `get_compiler("qasm")` 这个编译方式是从本地模拟器例子照抄的，云真机
       官方示例用的是 `get_compiler("native")` + 手写 Circuit，没有确认
       QASM 编译出的 IR 能不能直接喂给云 backend——大概率可以（同一个
       compile() 产物），实测报错就是这里要改。
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils import now_iso, probabilities_to_counts  # noqa: E402

_MEASURE_LINE = re.compile(r"^\s*measure\b.*;\s*$", re.IGNORECASE | re.MULTILINE)


def _strip_measurements(qasm: str) -> str:
    """去掉显式 measure 行——SpinQ Cloud 不接受，会在电路末尾自动全比特测量。

    只对"全比特测量、q[i]->c[i] 顺序"的电路安全（见文件头部注释）。
    """
    return _MEASURE_LINE.sub("", qasm)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("qasm_file")
    parser.add_argument("--shots", type=int, default=1000)
    parser.add_argument(
        "--platform",
        default="superconductor_vp",
        choices=["gemini_vp", "triangulum_vp", "superconductor_vp"],
    )
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    username = os.environ.get("SPINQ_CLOUD_USERNAME")
    keyfile = os.environ.get("SPINQ_CLOUD_KEYFILE")
    if not username or not keyfile:
        print(
            "请先执行:\n"
            '  export SPINQ_CLOUD_USERNAME="你的用户名"\n'
            '  export SPINQ_CLOUD_KEYFILE="/path/to/.ssh/id_rsa"',
            file=sys.stderr,
        )
        return 1
    # 双引号包裹的 "~/..." 不会被 shell 展开，open() 也不认识 "~"——这里兜底展开，
    # 避免 FileNotFoundError: '~/.ssh/xxx'（已实测踩过这个坑）。
    keyfile = os.path.expanduser(keyfile)
    if not os.path.isfile(keyfile):
        print(f"密钥文件不存在: {keyfile}", file=sys.stderr)
        return 1

    from spinqit import SpinQCloudConfig, get_compiler, get_spinq_cloud

    with open(args.qasm_file, encoding="utf-8") as handle:
        qasm = handle.read()

    backend = get_spinq_cloud(username, keyfile)
    platform = backend.get_platform(args.platform)
    if not platform.available():
        print(f"{args.platform} 当前没有可用真机，稍后重试", file=sys.stderr)
        return 1

    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".qasm", delete=False, encoding="utf-8")
    try:
        tmp.write(_strip_measurements(qasm))
        tmp.close()
        compiler = get_compiler("qasm")
        ir = compiler.compile(tmp.name, 0)
    finally:
        os.unlink(tmp.name)

    config = SpinQCloudConfig()
    config.configure_platform(args.platform)
    config.configure_shots(args.shots)
    config.configure_task("loomq-real-hardware", "LoomQ submission evidence")

    # SDK 在提交时会 print 一行 "Task <ID> has been submitted successfully."——
    # 这是目前唯一能拿到真实 job_id 的地方（`res` 本身不带 id 属性，实测确认）。
    # 用 redirect_stdout 截获这行文字，同时原样转发给用户终端，不影响可见性。
    stdout_buffer = io.StringIO()
    with contextlib.redirect_stdout(stdout_buffer):
        res = backend.execute(ir, config)
    captured = stdout_buffer.getvalue()
    sys.stdout.write(captured)
    task_id_match = re.search(r"Task\s+([\w-]+)\s+has been submitted", captured)
    sdk_task_id = task_id_match.group(1) if task_id_match else None

    # 官方文档：cloud backend 的返回值就是概率分布字典本身，不是包了一层的对象
    probabilities = res if isinstance(res, dict) else dict(getattr(res, "probabilities", res))
    counts = probabilities_to_counts(probabilities, args.shots)
    # 位序反转——已用 swap_basic.qasm 在真机（gemini_vp, job G-260730-0004）实测
    # 确认：不反转时主峰在 "01"（707/1000），反转后主峰在 "10"（707/1000），
    # 跟理想态 {"10": 1.0} 对上。跟本地模拟器路径（spinq_backend.py）是同一个
    # 反转方向，同一个 SDK 底层位序，云端和本地一致，不是巧合。
    counts = {k[::-1]: v for k, v in counts.items()}

    job_id = (
        getattr(res, "job_id", None)
        or getattr(res, "task_id", None)
        or sdk_task_id
        or "TODO：去 cloud.spinq.cn 任务记录里按 task_name='loomq-real-hardware' 核对后手动填入"
    )

    result = {
        "backend": f"spinq_{args.platform}",
        "job_id": job_id,
        "shots": args.shots,
        "counts": counts,
        "bit_order": "little",
        "timestamp": now_iso(),
        "meta": {"platform": args.platform, "source_file": args.qasm_file},
    }

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(f"已写入 {args.out}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
