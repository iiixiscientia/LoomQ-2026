"""极简 OpenQASM 2.0 解析器，只覆盖本题需要的子集。

支持：版本行、include、qreg/creg 声明、12 门白名单的门调用（可带一个
括号参数列表）、measure（整寄存器或逐比特）。
不支持：循环、条件、自定义 gate 定义、多个寄存器——题面语法本来就没有这些。
"""
from __future__ import annotations

import math
import re
from typing import List, Optional

from .ir import Circuit, Instruction, Measurement

WHITELIST_GATES = {
    "h", "x", "s", "sdg", "t", "tdg",   # 单比特无参
    "rz", "ry",                          # 单比特带参
    "cx", "cu1", "swap",                 # 两比特
    "ccx",                                # 三比特
}

_SAFE_EVAL_NAMES = {"pi": math.pi}


class QasmParseError(ValueError):
    """解析失败时抛出，message 里带上原始语句方便定位。"""


def _eval_param(expr: str) -> float:
    expr = expr.strip()
    try:
        # 只开放 pi 这一个名字，__builtins__ 清空，避免 eval 变成任意代码执行。
        return float(eval(expr, {"__builtins__": {}}, _SAFE_EVAL_NAMES))
    except Exception as exc:  # noqa: BLE001 - 转成统一的解析异常
        raise QasmParseError(f"无法求值参数 '{expr}': {exc}") from exc


def _strip_comments(qasm_str: str) -> str:
    lines = []
    for raw in qasm_str.splitlines():
        line = re.sub(r"//.*", "", raw).strip()
        if line:
            lines.append(line)
    return " ".join(lines)


def parse_qasm2(qasm_str: str) -> Circuit:
    text = _strip_comments(qasm_str)
    statements = [s.strip() for s in text.split(";") if s.strip()]

    num_qubits = 0
    num_clbits: Optional[int] = None
    instructions: List[Instruction] = []
    measurements: List[Measurement] = []
    seen_qreg = False

    for stmt in statements:
        if stmt.startswith("OPENQASM") or stmt.startswith("include"):
            continue

        m = re.match(r"qreg\s+\w+\[(\d+)\]$", stmt)
        if m:
            num_qubits = int(m.group(1))
            seen_qreg = True
            continue

        m = re.match(r"creg\s+\w+\[(\d+)\]$", stmt)
        if m:
            num_clbits = int(m.group(1))
            continue

        m = re.match(r"measure\s+\w+(\[(\d+)\])?\s*->\s*\w+(\[(\d+)\])?$", stmt)
        if m:
            q_idx, c_idx = m.group(2), m.group(4)
            if q_idx is not None and c_idx is not None:
                measurements.append(Measurement(int(q_idx), int(c_idx)))
            elif q_idx is None and c_idx is None:
                # 整寄存器测量：measure q -> c;  按下标顺序一一对应
                for i in range(num_qubits):
                    measurements.append(Measurement(i, i))
            else:
                raise QasmParseError(f"measure 两侧必须同为整寄存器或同为单比特: {stmt}")
            continue

        m = re.match(r"(\w+)(\(([^)]*)\))?\s+(.+)$", stmt)
        if not m:
            raise QasmParseError(f"无法识别的语句: {stmt}")
        gate, _, param_str, qubit_str = m.groups()
        gate = gate.lower()
        if gate not in WHITELIST_GATES:
            raise QasmParseError(f"门 '{gate}' 不在题面 12 门白名单内: {stmt}")

        params = [_eval_param(p) for p in param_str.split(",")] if param_str else []

        qubits: List[int] = []
        for token in qubit_str.split(","):
            qm = re.match(r"\s*\w+\[(\d+)\]\s*$", token)
            if not qm:
                raise QasmParseError(f"无法识别的 qubit 操作数: '{token}' (语句: {stmt})")
            qubits.append(int(qm.group(1)))
        instructions.append(Instruction(gate=gate, qubits=qubits, params=params))

    if not seen_qreg:
        raise QasmParseError("缺少 qreg 声明")

    return Circuit(
        num_qubits=num_qubits,
        num_clbits=num_clbits if num_clbits is not None else num_qubits,
        instructions=instructions,
        measurements=measurements,
    )
