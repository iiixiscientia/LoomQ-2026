"""AWS Braket 后端执行封装（默认走免费本地模拟器，不需要 AWS 账号）。

改写自官方 starter-kit/examples/run_braket.py，执行的是
codegen.to_braket_qasm3(circuit, include_stdgates=False) 产出的文本——
这个版本已经把 sdg/tdg/cu1/ccx 分解成 LocalSimulator 认识的内建门
（h/x/s/t/rz/ry/cx→cnot/swap），12 个白名单门全部用
tests/gate_coverage_test.py 验证过语义正确（分解式产生的理想分布跟原始
门的理想分布逐位对上）。

安装：pip install amazon-braket-sdk==<锁定版本>。
"""
from __future__ import annotations

from typing import Any, Dict

from braket.devices import LocalSimulator
from braket.ir.openqasm import Program

from ..utils import now_iso


def run_native_qasm3(native_qasm3: str, shots: int) -> Dict[str, Any]:
    """执行由 codegen.to_braket_qasm3() 生成的 OpenQASM 3 文本。"""
    device = LocalSimulator()
    program = Program(source=native_qasm3)
    task = device.run(program, shots=shots)
    result = task.result()
    # ⚠️ 位序反转：实测 LocalSimulator 原生返回的 key 是"最左侧字符是 q[0]"，
    # 跟大赛约定（最右侧字符是 c[0]，Qiskit 风格）正好相反。这是拿
    # swap_basic.qasm 测出来的（用 x+swap 造出一个非对称、能分辨方向的态，
    # 结果发现算出来的分布跟理想分布左右镜像；对称态比如 Bell/GHZ 测不出这个
    # bug，因为反转前后长得一样）。直接把 key 字符串反转过来即可。
    counts = {str(k)[::-1]: int(v) for k, v in result.measurement_counts.items()}

    timestamp = now_iso()
    if hasattr(result, "additional_metadata") and hasattr(
        result.additional_metadata, "action"
    ):
        start = getattr(result.additional_metadata.action, "startTime", None)
        if start:
            timestamp = start

    return {
        "backend": "braket_local_simulator",
        "job_id": result.task_metadata.id,
        "shots": shots,
        "counts": counts,
        "bit_order": "little",
        "timestamp": timestamp,
        "meta": {"measured_qubits": len(result.measured_qubits)},
    }
