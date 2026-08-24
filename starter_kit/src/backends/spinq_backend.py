"""量旋 SpinQit 后端执行封装 —— subprocess 桥接版。

**为什么不直接 import spinqit**：spinqit 需要旧格式（ATN version 3）的
`antlr4-python3-runtime==4.9.2`，而 `amazon-braket-default-simulator`（braket
后端的依赖）强制要求 `4.13.2`——这两个版本互斥，同一个 Python 环境装不全，
实测已经验证过（装 4.9.2 时 spinq 能跑但 braket 报 `KeyError` / `TypeError`
崩溃，装回 4.13.2 则 spinq 报 `Could not deserialize ATN with version 3
(expected 4)`）。

解决办法：给 spinqit 单独建一个虚拟环境 `spinq_env/`（装 spinqit +
`antlr4-python3-runtime==4.9.2`，见 `requirements-spinq.txt`），这里通过
`subprocess` 调用那个环境里的 `spinq_runner.py` 执行，用 stdin/stdout 传
JSON。契约里"非 Python 技术栈可以在 adapter.py 里用 subprocess 调用自己的
CLI/二进制"是同一个思路，只是这里是解决 Python 内部的依赖冲突，不是跨语言。

本地建 spinq_env（提交前 Docker 里也要建，见 Dockerfile）：
    python3.10 -m venv spinq_env
    spinq_env/bin/pip install -r requirements-spinq.txt
"""
from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Dict

from ..utils import now_iso

_SUBMISSION_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SPINQ_VENV_PYTHON = os.path.join(_SUBMISSION_ROOT, "spinq_env", "bin", "python3")
_RUNNER_SCRIPT = os.path.join(_SUBMISSION_ROOT, "spinq_runner.py")


def run_native_qasm2(native_qasm2: str, shots: int) -> Dict[str, Any]:
    """执行由 codegen.to_spinq_qasm2() 生成的 OpenQASM 2.0 文本（子进程隔离）。"""
    if not os.path.exists(_SPINQ_VENV_PYTHON):
        raise RuntimeError(
            f"找不到 spinq 专用虚拟环境: {_SPINQ_VENV_PYTHON}\n"
            "先建好它: python3.10 -m venv spinq_env && "
            "spinq_env/bin/pip install -r requirements-spinq.txt"
        )

    payload = json.dumps({"qasm": native_qasm2, "shots": shots})
    try:
        proc = subprocess.run(
            [_SPINQ_VENV_PYTHON, _RUNNER_SCRIPT],
            input=payload,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("spinq_runner.py 子进程超时（60s）") from exc

    if proc.returncode != 0:
        raise RuntimeError(f"spinq_runner.py 子进程失败（stderr）:\n{proc.stderr}")

    try:
        raw = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"spinq_runner.py 输出不是合法 JSON: {proc.stdout!r}"
        ) from exc

    # ⚠️ 位序反转：实测 spinqit 原生返回的 key 是"最左侧字符是 q[0]"，跟大赛
    # 约定（最右侧字符是 c[0]，Qiskit 风格）正好相反——用 swap_basic.qasm /
    # ccx_one_on.qasm 这种非对称态测出来的（Bell/GHZ 这类对称态反转前后一样，
    # 测不出这个 bug）。braket 那边也有同一个问题，见 braket_backend.py。
    counts = {key[::-1]: value for key, value in raw["counts"].items()}

    return {
        "backend": "spinq_taurus_simulator",
        "job_id": raw["job_id"],
        "shots": shots,
        "counts": counts,
        "bit_order": "little",
        "timestamp": now_iso(),
        "meta": {"qubits_count": raw["qubits_count"]},
    }
