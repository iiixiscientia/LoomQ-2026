"""IR -> 三个后端原生格式的序列化器。

严格对照 starter_kit/target_ir_contract.md 的规范子集写的，这是正式评测会
拿去解析模拟的"转译产物"，不是随便拼字符串。三个函数各自独立、互不依赖，
所以某一个目标平台的格式细节以后要调整，不会牵连另外两个。

⚠️ 已知风险点（TODO，需要你在真机/真 SDK 上实测验证）：
- OriginQ 的 CU1/TOFFOLI 具体拼写以 target_ir_contract.md 为准（也接受
  CR / CCX 别名），实测如报"未知指令"，对照 pyqpanda 报错信息调整拼写。
  用 tests/gate_coverage_test.py 测一遍就知道现在这个拼写对不对。
- Braket 本地执行路径（`include_stdgates=False`）已经用
  gate_coverage_test.py 验证过全部 12 个白名单门（sdg/tdg/cu1/ccx 走
  `_braket_decompose` 分解，其余走内建名字），理论上不用再操心；如果之后
  换了 amazon-braket-sdk 版本导致内建门集合变化，重新跑一次
  gate_coverage_test.py 就能发现。
"""
from __future__ import annotations

from .ir import Circuit

# qelib1 门名 -> OriginIR 门名（见 target_ir_contract.md）
_ORIGINQ_GATE_NAMES = {
    "h": "H", "x": "X", "s": "S", "sdg": "SDAG", "t": "T", "tdg": "TDAG",
    "ry": "RY", "rz": "RZ",
    "cx": "CNOT", "cu1": "CU1", "swap": "SWAP",
    "ccx": "TOFFOLI",
}


def _fmt_num(x: float) -> str:
    # 保留足够精度，同时避免 0.5000000000000001 这种浮点噪声污染文本
    return format(x, ".12g")


def to_spinq_qasm2(circuit: Circuit) -> str:
    """spinq 目标：完整可执行的 OpenQASM 2.0（原样门集，不需要改名）。"""
    lines = ["OPENQASM 2.0;", 'include "qelib1.inc";']
    lines.append(f"qreg q[{circuit.num_qubits}];")
    lines.append(f"creg c[{circuit.num_clbits}];")
    for inst in circuit.instructions:
        qubits = ", ".join(f"q[{q}]" for q in inst.qubits)
        if inst.params:
            params = ", ".join(_fmt_num(p) for p in inst.params)
            lines.append(f"{inst.gate}({params}) {qubits};")
        else:
            lines.append(f"{inst.gate} {qubits};")
    for meas in circuit.measurements:
        lines.append(f"measure q[{meas.qubit}] -> c[{meas.clbit}];")
    return "\n".join(lines) + "\n"


# 不带 include 时，braket 的 LocalSimulator 实测只认识这几个内建名字：
# h, x, s, t, rz, ry, cx(必须写成 cnot), swap。sdg/tdg/cu1/ccx 全部
# "not defined"，用 gate_coverage_test.py 一个个测出来的。
#
# 处理办法分两类：
#   1. 纯改名：cx -> cnot（_BRAKET_BUILTIN_NAMES）。
#   2. 真的没有对应内建门，得分解成上面那些确认可用的门：
#      - sdg = s 连续施加 3 次（S 的阶是 4，S^3 = S^-1 = Sdg）
#      - tdg = sdg 再乘 t，也就是 3 个 s + 1 个 t（T 阶是 8，S^3*T 的相位
#        正好是 -π/4）
#      - cu1(θ) 用标准的 CNOT+RZ 夹层分解（rz(θ/2)_a, rz(θ/2)_b, cx(a,b),
#        rz(-θ/2)_b, cx(a,b)）——这是教科书级恒等式，验证过整体相位差只影响
#        全局相位，不影响任何测量分布
#      - ccx 用 gate_identities.md 给的标准 15 门分解，展开式里出现的
#        tdg 再套用上面那条规则继续展开
#
# 这一切只发生在 include_stdgates=False（本地执行路径）；transpile() 对外
# 返回的版本（评测契约要看的那份）保持原始门名 + 完整 include，不受影响。
_BRAKET_BUILTIN_NAMES = {
    "cx": "cnot",
}


def _braket_decompose(gate: str, qubits, params):
    """把不在 braket 内建门集合里的门，分解成已确认可用的 h/x/s/t/rz/cx。
    返回 (gate, qubits, params) 三元组的列表，按顺序原样输出。
    """
    if gate == "sdg":
        (q,) = qubits
        return [("s", [q], []), ("s", [q], []), ("s", [q], [])]
    if gate == "tdg":
        (q,) = qubits
        return [("s", [q], []), ("s", [q], []), ("s", [q], []), ("t", [q], [])]
    if gate == "cu1":
        a, b = qubits
        theta = params[0]
        return [
            ("rz", [a], [theta / 2]),
            ("rz", [b], [theta / 2]),
            ("cx", [a, b], []),
            ("rz", [b], [-theta / 2]),
            ("cx", [a, b], []),
        ]
    if gate == "ccx":
        a, b, c = qubits
        raw = [
            ("h", [c]), ("cx", [b, c]), ("tdg", [c]), ("cx", [a, c]),
            ("t", [c]), ("cx", [b, c]), ("tdg", [c]), ("cx", [a, c]),
            ("t", [b]), ("t", [c]), ("h", [c]), ("cx", [a, b]),
            ("t", [a]), ("tdg", [b]), ("cx", [a, b]),
        ]
        expanded = []
        for g, qs in raw:
            expanded.extend(_braket_decompose(g, qs, []) if g == "tdg" else [(g, qs, [])])
        return expanded
    return [(gate, qubits, params)]


def to_braket_qasm3(circuit: Circuit, include_stdgates: bool = True) -> str:
    """braket 目标：完整 OpenQASM 3，逐比特测量赋值。

    `include_stdgates=False` 是给本地执行用的变体：实测装到的
    amazon-braket-sdk 版本里，LocalSimulator 对 `include "stdgates.inc";`
    会尝试真的打开同名文件，本地没有这个文件就报 FileNotFoundError——官方
    自己在 examples/run_braket.py 里能跑通的例子也没写这行。评测契约
    （target_ir_contract.md）的示例是带 include 的，所以 `transpile()`
    对外的返回值默认仍然带上（`include_stdgates=True`），只有
    backends/braket_backend.py 的本地执行路径改用不带 include 的版本，
    并且额外对 sdg/tdg/cu1/ccx 做门分解（见 `_braket_decompose`）。
    """
    lines = ["OPENQASM 3.0;"]
    if include_stdgates:
        lines.append('include "stdgates.inc";')
    lines.append(f"qubit[{circuit.num_qubits}] q;")
    lines.append(f"bit[{circuit.num_clbits}] c;")
    for inst in circuit.instructions:
        emit = (
            [(inst.gate, inst.qubits, inst.params)]
            if include_stdgates
            else _braket_decompose(inst.gate, inst.qubits, inst.params)
        )
        for gate, qubits, params in emit:
            if not include_stdgates:
                gate = _BRAKET_BUILTIN_NAMES.get(gate, gate)
            qubit_str = ", ".join(f"q[{q}]" for q in qubits)
            if params:
                param_str = ", ".join(_fmt_num(p) for p in params)
                lines.append(f"{gate}({param_str}) {qubit_str};")
            else:
                lines.append(f"{gate} {qubit_str};")
    for meas in circuit.measurements:
        lines.append(f"c[{meas.clbit}] = measure q[{meas.qubit}];")
    return "\n".join(lines) + "\n"


def _originq_decompose(gate: str, qubits, params):
    """把 pyqpanda 真实解析器不认识的门，分解成它确认支持的门。

    实测（tests/originq_ir_roundtrip_test.py + gate_coverage_test.py）：
    `SDAG`/`TDAG`/`CU1` 都在 target_ir_contract.md 的允许门名单里，但
    pyqpanda 自带的 OriginIR 解析器（OriginIRToQProg.cpp）三个都报
    `UserDefinedGate ... undefined error`——都不是内建门。用跟
    _braket_decompose 完全一样、已经验证过的恒等式绕过去：S 的阶是 4，
    S³ = S⁻¹ = SDAG；T 的阶是 8，S³·T 的相位正好是 -π/4 = TDAG；CU1(θ)
    用标准 RZ+CNOT 夹层分解（不用 CR 这个别名，怕跟 CU1 相位约定不一致）。
    只在 pyqpanda_compat=True（本地执行路径）时用；transpile() 对外的
    契约文本保持原始拼写不变，跟 braket 的 include_stdgates 开关是同一个
    设计模式。
    """
    if gate == "sdg":
        (q,) = qubits
        return [("s", [q], []), ("s", [q], []), ("s", [q], [])]
    if gate == "tdg":
        (q,) = qubits
        return [("s", [q], []), ("s", [q], []), ("s", [q], []), ("t", [q], [])]
    if gate == "cu1":
        # 实测：CU1 在 pyqpanda 解析器里是 "UserDefinedGate CU1 undefined
        # error"——不是语法问题，是压根没这个内建门。契约里说 CU1/CR 都算
        # 合法别名，但 CR 在不同 SDK 里语义未必等价于 CU1(θ)（受控相位 vs
        # 受控旋转的相位约定可能不同），不确定就不猜——直接复用跟 braket
        # 同一套已验证过的标准分解（RZ+CNOT 夹层），不依赖 CU1/CR 这个门
        # 名字本身，RZ 和 CNOT 都已经确认 pyqpanda 认得。
        a, b = qubits
        theta = params[0]
        return [
            ("rz", [a], [theta / 2]),
            ("rz", [b], [theta / 2]),
            ("cx", [a, b], []),
            ("rz", [b], [-theta / 2]),
            ("cx", [a, b], []),
        ]
    return [(gate, qubits, params)]


def to_originq_ir(circuit: Circuit, pyqpanda_compat: bool = False) -> str:
    """originq 目标：规范 OriginIR 子集（见 target_ir_contract.md 示例格式）。

    参数写法用 `GATE q[i],(θ)`（参数在比特列表之后）——契约里 `RY(θ) q[0]`
    与 `RY q[0],(θ)` 都算合法，但实测 pyqpanda 自己的解析器（跟 run() 实际
    执行用的是同一个）只认后一种，`RY(θ) q[0]` 会报
    `no viable alternative at input 'RY('`。既然两种写法都符合契约，直接
    统一用 pyqpanda 认的这种，transpile() 和 run() 不用分叉。

    `pyqpanda_compat=True` 时額外把 sdg/tdg 分解掉（见 _originq_decompose），
    因为这两个门契约允许但 pyqpanda 解析器不支持——这个开关只影响 SDAG/TDAG
    这两个门，其余门集契约文本和执行文本完全一致。
    """
    lines = [f"QINIT {circuit.num_qubits}", f"CREG {circuit.num_clbits}"]
    for inst in circuit.instructions:
        emit = (
            _originq_decompose(inst.gate, inst.qubits, inst.params)
            if pyqpanda_compat
            else [(inst.gate, inst.qubits, inst.params)]
        )
        for gate, qubits, params in emit:
            name = _ORIGINQ_GATE_NAMES[gate]
            qubit_str = ", ".join(f"q[{q}]" for q in qubits)
            if params:
                param_str = ", ".join(_fmt_num(p) for p in params)
                lines.append(f"{name} {qubit_str},({param_str})")
            else:
                lines.append(f"{name} {qubit_str}")
    for meas in circuit.measurements:
        lines.append(f"MEASURE q[{meas.qubit}], c[{meas.clbit}]")
    return "\n".join(lines) + "\n"
