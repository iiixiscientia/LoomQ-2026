#!/usr/bin/env python3
"""Bonus · 自定义量子 RISC-V 扩展指令。

这是 `riscv_emulator.py`（官方提供、L3 判定用，未改动）的 **fork**，不是对
官方文件的修改——两者是完全独立的模拟器，互不影响。`TinyRISCVEmulator`
的经典指令语义（`li/add/sub/addi/beq/bne/j`，含"x0 恒为 0"这条规则）在这里
原样复刻，新增的量子指令共享**同一份寄存器堆**，所以 `qmeasure` 的结果可以
直接被 `beq`/`bne` 这些经典分支指令读取——这是它跟 L3 的
`compile_hybrid`（经典块读"已经测量好"的输入）不同的地方：这里的测量是在
程序运行**过程中**真实发生的，量子门和经典控制流可以互相驱动、真正交替执行。

## 指令编码规格（详见 docs/quantum_riscv_isa.md）

复用标准 RISC-V R-type 字段布局，opcode 固定用 RISC-V 官方手册保留给
"custom-0" 扩展的 `0001011`（十进制 11），不会跟任何标准指令冲突：

```
位:    31........25  24....20  19....15  14..12  11.....7  6......0
字段:  funct7         rs2       rs1       funct3  rd        opcode
```

funct3 选指令类别：
  000 QINIT    — rs1 = 量子位数 n（0-31），(重新)初始化 n 比特寄存器为 |0...0>
  001 QGATE1   — rs1 = 目标量子位；funct7 低 3 位 = 门 id（0=h 1=x 2=s 3=sdg 4=t 5=tdg）
  010 QGATE2   — rs1/rs2 = 两个量子位；funct7 低 2 位 = 门 id（0=cx 1=swap）
  011 QGATE3   — rs1/rs2 = 两个控制位，rd = 目标位（ccx，唯一门，funct7=0）
  100 QMEASURE — rs1 = 量子位，rd = 目标经典寄存器（0-31，直接对应 x0-x31）

参数门（rz/ry/cu1）需要连续取值的角度，7 位 funct7 塞不下任意精度浮点数，
这里**没有**把它们纳入二进制编码范围（只留在文本汇编层面，见下）——这是一个
明确记录的取舍，不是遗漏：真实 ISA 遇到这种情况通常也是走"立即数太大就从
寄存器/常量表取"这条路，不在几十比特的定长指令里硬塞浮点数。
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Tuple

from .reference_simulator import (
    _GATE_MATRICES,
    _apply_cx,
    _apply_ccx,
    _apply_single_qubit,
    _apply_swap,
)

# ── 1. 二进制编码 ────────────────────────────────────────────────────────────

OPCODE_CUSTOM0 = 0b0001011  # RISC-V 手册保留给 custom-0 扩展的 opcode，7 位

FUNCT3 = {"qinit": 0b000, "qgate1": 0b001, "qgate2": 0b010, "qgate3": 0b011, "qmeasure": 0b100}
FUNCT3_REV = {v: k for k, v in FUNCT3.items()}

GATE1_ID = {"qh": 0, "qx": 1, "qs": 2, "qsdg": 3, "qt": 4, "qtdg": 5}
GATE1_ID_REV = {v: k for k, v in GATE1_ID.items()}
GATE1_TO_MATRIX_KEY = {"qh": "h", "qx": "x", "qs": "s", "qsdg": "sdg", "qt": "t", "qtdg": "tdg"}

GATE2_ID = {"qcx": 0, "qswap": 1}
GATE2_ID_REV = {v: k for k, v in GATE2_ID.items()}


def _bits(value: int, width: int, name: str) -> int:
    if not (0 <= value < (1 << width)):
        raise ValueError(f"{name}={value} 超出 {width} 位无符号范围 [0, {(1 << width) - 1}]")
    return value


def encode_instruction(mnemonic: str, args: Dict[str, int]) -> int:
    """把一条量子指令编码成 32 位无符号整数（R-type 字段布局）。

    args 按指令类别取用：
      qinit:    {"n": 量子位数}
      qh/qx/qs/qsdg/qt/qtdg: {"q": 量子位下标}
      qcx/qswap: {"q1": 量子位下标, "q2": 量子位下标}
      qccx:     {"c1": ..., "c2": ..., "t": 目标量子位}
      qmeasure: {"q": 量子位下标, "rd": 目标经典寄存器下标 0-31}
    """
    opcode = OPCODE_CUSTOM0
    if mnemonic == "qinit":
        funct3, rd, rs1, rs2, funct7 = FUNCT3["qinit"], 0, _bits(args["n"], 5, "n"), 0, 0
    elif mnemonic in GATE1_ID:
        funct3 = FUNCT3["qgate1"]
        rd, rs1, rs2 = 0, _bits(args["q"], 5, "q"), 0
        funct7 = GATE1_ID[mnemonic]
    elif mnemonic in GATE2_ID:
        funct3 = FUNCT3["qgate2"]
        rd = 0
        rs1, rs2 = _bits(args["q1"], 5, "q1"), _bits(args["q2"], 5, "q2")
        funct7 = GATE2_ID[mnemonic]
    elif mnemonic == "qccx":
        funct3 = FUNCT3["qgate3"]
        rd = _bits(args["t"], 5, "t")
        rs1, rs2 = _bits(args["c1"], 5, "c1"), _bits(args["c2"], 5, "c2")
        funct7 = 0
    elif mnemonic == "qmeasure":
        funct3 = FUNCT3["qmeasure"]
        rd = _bits(args["rd"], 5, "rd")
        rs1, rs2 = _bits(args["q"], 5, "q"), 0
        funct7 = 0
    else:
        raise ValueError(f"未知量子指令: {mnemonic!r}")

    word = (funct7 << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode
    return word & 0xFFFFFFFF


def decode_instruction(word: int) -> Tuple[str, Dict[str, int]]:
    """把 32 位整数解码回 (mnemonic, args)。跟 encode_instruction 严格互逆
    ——tests/quantum_riscv_test.py 里对每条指令都做了编码再解码的往返断言。
    """
    opcode = word & 0x7F
    if opcode != OPCODE_CUSTOM0:
        raise ValueError(f"opcode={opcode:#09b} 不是本扩展使用的 custom-0 ({OPCODE_CUSTOM0:#09b})")
    rd = (word >> 7) & 0x1F
    funct3 = (word >> 12) & 0x7
    rs1 = (word >> 15) & 0x1F
    rs2 = (word >> 20) & 0x1F
    funct7 = (word >> 25) & 0x7F

    kind = FUNCT3_REV.get(funct3)
    if kind is None:
        raise ValueError(f"funct3={funct3:#05b} 不是已定义的指令类别")

    if kind == "qinit":
        return "qinit", {"n": rs1}
    if kind == "qgate1":
        mnemonic = GATE1_ID_REV.get(funct7 & 0x7)
        if mnemonic is None:
            raise ValueError(f"QGATE1 funct7={funct7} 不是已定义的门 id")
        return mnemonic, {"q": rs1}
    if kind == "qgate2":
        mnemonic = GATE2_ID_REV.get(funct7 & 0x3)
        if mnemonic is None:
            raise ValueError(f"QGATE2 funct7={funct7} 不是已定义的门 id")
        return mnemonic, {"q1": rs1, "q2": rs2}
    if kind == "qgate3":
        return "qccx", {"c1": rs1, "c2": rs2, "t": rd}
    if kind == "qmeasure":
        return "qmeasure", {"q": rs1, "rd": rd}
    raise AssertionError("unreachable")  # pragma: no cover


# ── 2. 文本汇编 <-> 编码参数字典 的相互转换（复用同一套 encode/decode 语义） ──

def _parse_qreg(token: str) -> int:
    token = token.strip()
    if not token.startswith("q"):
        raise ValueError(f"量子位参数应该形如 'q3'，实际是 {token!r}")
    return int(token[1:])


def _parse_creg(token: str) -> int:
    token = token.strip()
    if not (token.startswith("x") or token.startswith("X")):
        raise ValueError(f"经典寄存器参数应该形如 'x10'，实际是 {token!r}")
    return int(token[1:])


def assemble_line(mnemonic: str, raw_args: List[str]) -> int:
    """文本助记符 + 参数 -> 32 位编码。给 `load_quantum_program` 内部用，
    也单独导出给测试直接调用，验证"文本写法"和"二进制编码"是同一件事。
    """
    if mnemonic == "qinit":
        return encode_instruction("qinit", {"n": int(raw_args[0])})
    if mnemonic in GATE1_ID:
        return encode_instruction(mnemonic, {"q": _parse_qreg(raw_args[0])})
    if mnemonic in GATE2_ID:
        return encode_instruction(mnemonic, {"q1": _parse_qreg(raw_args[0]), "q2": _parse_qreg(raw_args[1])})
    if mnemonic == "qccx":
        return encode_instruction(
            "qccx",
            {"c1": _parse_qreg(raw_args[0]), "c2": _parse_qreg(raw_args[1]), "t": _parse_qreg(raw_args[2])},
        )
    if mnemonic == "qmeasure":
        return encode_instruction("qmeasure", {"q": _parse_qreg(raw_args[0]), "rd": _parse_creg(raw_args[1])})
    raise ValueError(f"未知量子指令: {mnemonic!r}")


# ── 3. 扩展模拟器：fork 自 riscv_emulator.TinyRISCVEmulator ─────────────────
# 下面这部分是 riscv_emulator.py 原始逻辑的复刻（经典指令语义完全一致），
# 加上量子指令的处理——按 Bonus 规则要求"fork 官方模拟器增加指令支持"，
# 是独立文件，不修改官方那份，两边可以分别验证互不影响。

class QuantumRISCVEmulator:
    def __init__(self):
        self.registers = [0] * 32  # 跟经典部分共用同一份寄存器堆（x0 恒为 0）
        self.pc = 0
        self.labels: Dict[str, int] = {}
        self.instructions: List[Tuple[str, List[str]]] = []
        self.max_steps = 2000

        self.qstate: List[complex] = [1 + 0j]  # 默认 0 比特量子寄存器（qinit 会重设）
        self.num_qubits = 0
        self.measurement_log: List[Tuple[int, int]] = []  # [(qubit, outcome), ...] 供测试/调试查看

    # -- 寄存器堆：跟官方 riscv_emulator.py 的行为完全一致 --------------------
    def set_register(self, reg: str, value: int):
        idx = self._parse_reg_idx(reg)
        if idx != 0:
            self.registers[idx] = value

    def get_register(self, reg: str) -> int:
        return self.registers[self._parse_reg_idx(reg)]

    def _parse_reg_idx(self, reg: str) -> int:
        reg = reg.strip().replace(",", "")
        if not reg.startswith("x") and not reg.startswith("X"):
            raise ValueError(f"无效的寄存器名称: {reg}")
        idx = int(reg[1:])
        if idx < 0 or idx > 31:
            raise ValueError(f"寄存器索引超出范围 (x0-x31): {reg}")
        return idx

    # -- 载入程序：文本汇编（跟官方语法完全兼容，额外认识 q* 系列助记符） -----
    def load_program(self, asm_code: str):
        self.instructions = []
        self.labels = {}
        self.pc = 0
        self.registers = [0] * 32
        self.qstate = [1 + 0j]
        self.num_qubits = 0
        self.measurement_log = []

        temp_instructions: List[Tuple[str, List[str]]] = []
        for line in asm_code.split("\n"):
            line = line.strip()
            if not line or line.startswith("#") or line.startswith(";"):
                continue
            if "#" in line:
                line = line.split("#")[0].strip()
            if line.endswith(":"):
                self.labels[line[:-1].strip()] = len(temp_instructions)
                continue
            if ":" in line:
                label_name, line = line.split(":", 1)
                self.labels[label_name.strip()] = len(temp_instructions)
                line = line.strip()
            tokens = line.replace(",", " ").split()
            op = tokens[0].lower()
            temp_instructions.append((op, tokens[1:]))
        self.instructions = temp_instructions

    def load_encoded_quantum_words(self, words: List[int]) -> List[Tuple[str, Dict[str, int]]]:
        """把一串 32 位编码字直接解码成 (mnemonic, args) 列表并返回——不经过
        文本汇编这一步，用来证明"二进制编码"本身是可独立执行的，不是只在
        文本层面兜圈子。调用方可以把返回值喂给 `run_decoded_quantum` 执行。
        """
        return [decode_instruction(w) for w in words]

    def run_decoded_quantum(self, decoded: List[Tuple[str, Dict[str, int]]]):
        """直接执行一串已解码的量子指令（不含经典分支/跳转，纯量子部分的
        最小执行路径）——用于端到端验证"编码 -> 解码 -> 真的能跑"这条链路。
        """
        for mnemonic, args in decoded:
            self._exec_quantum(mnemonic, args)

    # -- 执行 -----------------------------------------------------------------
    def execute(self) -> Dict[str, int]:
        steps = 0
        num_instr = len(self.instructions)
        while 0 <= self.pc < num_instr:
            steps += 1
            if steps > self.max_steps:
                raise RuntimeError("程序执行超出最大步数限制，疑似发生死循环")
            op, args = self.instructions[self.pc]
            next_pc = self.pc + 1

            if op == "li":
                self.set_register(args[0], int(args[1]))
            elif op == "add":
                self.set_register(args[0], self.get_register(args[1]) + self.get_register(args[2]))
            elif op == "sub":
                self.set_register(args[0], self.get_register(args[1]) - self.get_register(args[2]))
            elif op == "addi":
                self.set_register(args[0], self.get_register(args[1]) + int(args[2]))
            elif op == "beq":
                if self.get_register(args[0]) == self.get_register(args[1]):
                    next_pc = self._label(args[2])
            elif op == "bne":
                if self.get_register(args[0]) != self.get_register(args[1]):
                    next_pc = self._label(args[2])
            elif op == "j":
                next_pc = self._label(args[0])
            elif op in ("qinit",) or op in GATE1_ID or op in GATE2_ID or op in ("qccx", "qmeasure"):
                self._exec_quantum_text(op, args)
            else:
                raise ValueError(f"不支持的指令操作: {op}")

            self.pc = next_pc

        result = {}
        for idx, val in enumerate(self.registers):
            if val != 0:
                result[f"x{idx}"] = val
        return result

    def _label(self, name: str) -> int:
        if name not in self.labels:
            raise ValueError(f"未定义的跳转标签: {name}")
        return self.labels[name]

    def _exec_quantum_text(self, op: str, raw_args: List[str]):
        if op == "qinit":
            self._exec_quantum("qinit", {"n": int(raw_args[0])})
        elif op in GATE1_ID:
            self._exec_quantum(op, {"q": _parse_qreg(raw_args[0])})
        elif op in GATE2_ID:
            self._exec_quantum(op, {"q1": _parse_qreg(raw_args[0]), "q2": _parse_qreg(raw_args[1])})
        elif op == "qccx":
            self._exec_quantum(
                "qccx", {"c1": _parse_qreg(raw_args[0]), "c2": _parse_qreg(raw_args[1]), "t": _parse_qreg(raw_args[2])}
            )
        elif op == "qmeasure":
            self._exec_quantum("qmeasure", {"q": _parse_qreg(raw_args[0]), "rd": _parse_creg(raw_args[1])})
        else:
            raise ValueError(f"不支持的量子指令: {op}")

    def _exec_quantum(self, mnemonic: str, args: Dict[str, int]):
        if mnemonic == "qinit":
            n = args["n"]
            self.num_qubits = n
            self.qstate = [0j] * (2 ** n)
            self.qstate[0] = 1 + 0j
            return
        if mnemonic in GATE1_ID:
            matrix = _GATE_MATRICES[GATE1_TO_MATRIX_KEY[mnemonic]]
            self.qstate = _apply_single_qubit(self.qstate, args["q"], matrix)
            return
        if mnemonic in GATE2_ID:
            if mnemonic == "qcx":
                self.qstate = _apply_cx(self.qstate, args["q1"], args["q2"])
            else:
                self.qstate = _apply_swap(self.qstate, args["q1"], args["q2"])
            return
        if mnemonic == "qccx":
            self.qstate = _apply_ccx(self.qstate, args["c1"], args["c2"], args["t"])
            return
        if mnemonic == "qmeasure":
            outcome = self._measure(args["q"])
            self.measurement_log.append((args["q"], outcome))
            if args["rd"] != 0:  # x0 恒为 0，跟经典部分的规则保持一致
                self.registers[args["rd"]] = outcome
            return
        raise ValueError(f"未知量子指令: {mnemonic!r}")

    def _measure(self, qubit: int) -> int:
        """Born 规则采样 + 坍缩——真正的中途测量，不是等到最后才算分布。"""
        mask = 1 << qubit
        p1 = sum(abs(amp) ** 2 for i, amp in enumerate(self.qstate) if i & mask)
        p1 = min(max(p1, 0.0), 1.0)
        outcome = 1 if random.random() < p1 else 0
        keep_mask = mask if outcome == 1 else 0
        norm = math_sqrt(p1 if outcome == 1 else (1.0 - p1))
        new_state = [0j] * len(self.qstate)
        for i, amp in enumerate(self.qstate):
            if (i & mask) == keep_mask:
                new_state[i] = amp / norm
        self.qstate = new_state
        return outcome


def math_sqrt(x: float) -> float:
    # 避免因为浮点误差让 norm 变成 0（p 理论上不该是 0，但保底一下）
    return x ** 0.5 if x > 1e-15 else 1e-15 ** 0.5
