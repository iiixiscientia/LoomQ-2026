"""纯 Python 参考态矢量模拟器：只实现题面 12 门白名单的语义。

用途：给自己写的任意电路（不只是官方公开的 Bell/GHZ）算出"理论上应该是什么
分布"，作为 gate coverage 测试的 ground truth——而不是拿三个真实后端的结果
互相比。互相比只能测出"三个后端结果一致"，测不出"三个后端都实现错了、但错
得一样"；跟这份独立算出来的理想分布比，才是真的验证语义对不对。

不依赖 numpy、不依赖任何 SDK，纯标准库 `cmath`/`math`，本题电路最多 3
qubit（状态向量最多 8 个复数），性能完全不是问题。

约定跟 src/qasm_parser.py / src/ir.py 一致：qubit k 对应状态向量下标的第 k
个二进制位；跟大赛 counts key 的位序约定一致（最右侧字符是 c[0]）。
"""
from __future__ import annotations

import cmath
import math
from typing import Dict, List, Tuple

from .ir import Circuit

Complex = complex
Matrix2x2 = Tuple[Tuple[Complex, Complex], Tuple[Complex, Complex]]


def _apply_single_qubit(state: List[Complex], qubit: int, matrix: Matrix2x2) -> List[Complex]:
    n = len(state)
    new_state = [0j] * n
    mask = 1 << qubit
    (m00, m01), (m10, m11) = matrix
    for i in range(n):
        if i & mask:
            continue  # 只在 “这一位是 0” 的下标上成对处理，避免重复处理
        j = i | mask
        a, b = state[i], state[j]
        new_state[i] += m00 * a + m01 * b
        new_state[j] += m10 * a + m11 * b
    return new_state


_SQRT2_INV = 1 / math.sqrt(2)

# 无参单比特门的矩阵（标准 qelib1 定义）
_GATE_MATRICES: Dict[str, Matrix2x2] = {
    "h": ((_SQRT2_INV, _SQRT2_INV), (_SQRT2_INV, -_SQRT2_INV)),
    "x": ((0, 1), (1, 0)),
    "s": ((1, 0), (0, 1j)),
    "sdg": ((1, 0), (0, -1j)),
    "t": ((1, 0), (0, cmath.exp(1j * math.pi / 4))),
    "tdg": ((1, 0), (0, cmath.exp(-1j * math.pi / 4))),
}


def _rz_matrix(theta: float) -> Matrix2x2:
    return ((cmath.exp(-1j * theta / 2), 0), (0, cmath.exp(1j * theta / 2)))


def _ry_matrix(theta: float) -> Matrix2x2:
    c, s = math.cos(theta / 2), math.sin(theta / 2)
    return ((c, -s), (s, c))


def _apply_cx(state: List[Complex], control: int, target: int) -> List[Complex]:
    new_state = state[:]
    cmask, tmask = 1 << control, 1 << target
    for i in range(len(state)):
        if i & cmask:
            j = i ^ tmask
            if i < j:
                new_state[i], new_state[j] = state[j], state[i]
    return new_state


def _apply_swap(state: List[Complex], a: int, b: int) -> List[Complex]:
    new_state = state[:]
    amask, bmask = 1 << a, 1 << b
    for i in range(len(state)):
        abit, bbit = bool(i & amask), bool(i & bmask)
        if abit != bbit:
            j = i ^ amask ^ bmask
            if i < j:
                new_state[i], new_state[j] = state[j], state[i]
    return new_state


def _apply_ccx(state: List[Complex], c1: int, c2: int, target: int) -> List[Complex]:
    new_state = state[:]
    c1mask, c2mask, tmask = 1 << c1, 1 << c2, 1 << target
    for i in range(len(state)):
        if (i & c1mask) and (i & c2mask):
            j = i ^ tmask
            if i < j:
                new_state[i], new_state[j] = state[j], state[i]
    return new_state


def _apply_cu1(state: List[Complex], control: int, target: int, theta: float) -> List[Complex]:
    new_state = state[:]
    cmask, tmask = 1 << control, 1 << target
    phase = cmath.exp(1j * theta)
    for i in range(len(state)):
        if (i & cmask) and (i & tmask):
            new_state[i] = state[i] * phase
    return new_state


def simulate(circuit: Circuit) -> List[Complex]:
    """返回末态态矢量，长度 2**num_qubits，下标第 k 位对应 qubit k。"""
    n = circuit.num_qubits
    state: List[Complex] = [0j] * (2 ** n)
    state[0] = 1 + 0j
    for inst in circuit.instructions:
        gate = inst.gate
        if gate in _GATE_MATRICES:
            state = _apply_single_qubit(state, inst.qubits[0], _GATE_MATRICES[gate])
        elif gate == "rz":
            state = _apply_single_qubit(state, inst.qubits[0], _rz_matrix(inst.params[0]))
        elif gate == "ry":
            state = _apply_single_qubit(state, inst.qubits[0], _ry_matrix(inst.params[0]))
        elif gate == "cx":
            state = _apply_cx(state, inst.qubits[0], inst.qubits[1])
        elif gate == "swap":
            state = _apply_swap(state, inst.qubits[0], inst.qubits[1])
        elif gate == "ccx":
            state = _apply_ccx(state, inst.qubits[0], inst.qubits[1], inst.qubits[2])
        elif gate == "cu1":
            state = _apply_cu1(state, inst.qubits[0], inst.qubits[1], inst.params[0])
        else:
            raise ValueError(f"reference_simulator 不认识的门（不在 12 门白名单）: {gate}")
    return state


def ideal_distribution(circuit: Circuit) -> Dict[str, float]:
    """测量后的理想概率分布。key 位序跟大赛约定一致：最右侧字符是 c[0]。

    只处理"每个 qubit 唯一测量到一个 clbit"的情况——本题所有电路都是这样。
    """
    state = simulate(circuit)
    num_clbits = circuit.num_clbits
    qubit_to_clbit = {m.qubit: m.clbit for m in circuit.measurements}

    dist: Dict[str, float] = {}
    for i, amp in enumerate(state):
        prob = abs(amp) ** 2
        if prob < 1e-12:
            continue
        bits = ["0"] * num_clbits
        for qubit, clbit in qubit_to_clbit.items():
            if (i >> qubit) & 1:
                bits[num_clbits - 1 - clbit] = "1"
        key = "".join(bits)
        dist[key] = dist.get(key, 0.0) + prob
    return dist
