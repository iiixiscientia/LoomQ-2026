#!/usr/bin/env python3
"""在本源悟空真机上跑一遍电路，产出符合大赛统一 Schema 的 result.json。

这是"真机接入证据"要求提交的原始产物，跟 adapter.py 的 run() 是两条独立
路径——题面写了 L1 正式评测默认禁止网络，run() 必须离线可跑；真机证据是
单独提交的文件，不走 evaluator.py，也不会被自动评分公式调用。

准备工作：
    1. 注册 https://qcloud.originqc.com.cn/ ，工作台 -> 个人账号中心，
       申请/查看 api_token，确认账号已开通算力权限
       （文档原话："需要确保用户已经开通相关权限，并且有足够的算力资源"）。
    2. export ORIGINQ_API_TOKEN="你的 token"

用法：
    python3 real_hardware/run_originq_real.py circuits/bell.qasm \
        --shots 1000 --out real_hardware/results/originq_bell.json

⚠️ 两个待你实测确认的点：
    1. 位序：跟本地模拟器一样，真机返回的 counts key 顺序未必是大赛约定的
       "最右侧是 c[0]"，先用 bell.qasm（对称态，测不出方向）跑一次确认能连
       上，再用 circuits/coverage/swap_basic.qasm（非对称态）跑一次，把
       结果跟这份文件里的理想分布 {"10": 1.0} 比一下，不一致就在下面
       `# TODO: 位序` 那行加反转。
    2. job_id：pyqpanda 文档里 `real_chip_measure` 本身不直接返回任务 ID，
       如果这里留空或者不好确认，去 https://qcloud.originqc.com.cn/ 工作台
       按提交时间 + task_name 核对任务记录，把真实 job_id 手动填回
       result.json 再提交——题面写了"评测组将抽样登录平台复核 job_id"，
       缺这个字段等于评委没法验证，比随便填个假值更麻烦。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils import now_iso, probabilities_to_counts  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("qasm_file")
    parser.add_argument("--shots", type=int, default=1000)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    token = os.environ.get("ORIGINQ_API_TOKEN")
    if not token:
        print('请先执行: export ORIGINQ_API_TOKEN="你的 api_token"', file=sys.stderr)
        return 1

    import pyqpanda as pq

    with open(args.qasm_file, encoding="utf-8") as handle:
        qasm = handle.read()

    qm = pq.QCloud()
    qm.init_qvm(token, False)
    try:
        prog, qreg, creg = pq.convert_qasm_string_to_qprog(qasm, qm)
        probabilities = qm.real_chip_measure(prog, args.shots, pq.real_chip_type.origin_72)
        counts = probabilities_to_counts(probabilities, args.shots)
        # TODO: 位序 —— 如果 swap_basic.qasm 测出方向反了，这里加
        #   counts = {k[::-1]: v for k, v in counts.items()}

        result = {
            "backend": "originq_wukong",
            "job_id": "TODO：去工作台按 task_name/提交时间核对后手动填入",
            "shots": args.shots,
            "counts": counts,
            "bit_order": "little",
            "timestamp": now_iso(),
            "meta": {"chip": "origin_72", "source_file": args.qasm_file},
        }
    finally:
        qm.finalize()

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(f"已写入 {args.out}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
