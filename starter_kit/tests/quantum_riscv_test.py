#!/usr/bin/env python3
"""Bonus · 自定义量子 RISC-V 扩展指令的端到端测试。

覆盖三件事（对应 docs/quantum_riscv_isa.md 的三个主张）：
1. 每一类量子指令的二进制编码 <-> 解码严格互逆；
2. 文本汇编跑出来的量子行为在统计上正确（Bell 态完美关联、GHZ-3 只出现
   全 0/全 1）；
3. 量子测量结果真的能在运行时驱动经典分支（不是编译期就已知的假交互）。

用法：
    python3 tests/quantum_riscv_test.py
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.quantum_riscv_emulator import (  # noqa: E402
    QuantumRISCVEmulator,
    decode_instruction,
    encode_instruction,
)


class EncodeDecodeRoundtripTest(unittest.TestCase):
    def test_all_instruction_kinds_roundtrip(self):
        cases = [
            ("qinit", {"n": 3}),
            ("qinit", {"n": 0}),
            ("qinit", {"n": 31}),
            ("qh", {"q": 0}),
            ("qx", {"q": 31}),
            ("qs", {"q": 5}),
            ("qsdg", {"q": 5}),
            ("qt", {"q": 5}),
            ("qtdg", {"q": 5}),
            ("qcx", {"q1": 0, "q2": 1}),
            ("qswap", {"q1": 3, "q2": 7}),
            ("qccx", {"c1": 0, "c2": 1, "t": 2}),
            ("qmeasure", {"q": 4, "rd": 17}),
            ("qmeasure", {"q": 0, "rd": 0}),  # rd=0 合法（写入会被丢弃，跟 x0 恒零一致）
        ]
        for mnemonic, args in cases:
            word = encode_instruction(mnemonic, args)
            self.assertTrue(0 <= word <= 0xFFFFFFFF)
            got_mnemonic, got_args = decode_instruction(word)
            self.assertEqual(got_mnemonic, mnemonic)
            self.assertEqual(got_args, args)

    def test_opcode_is_fixed_custom0(self):
        word = encode_instruction("qh", {"q": 3})
        self.assertEqual(word & 0x7F, 0b0001011)

    def test_decode_rejects_foreign_opcode(self):
        # 把 opcode 位改成标准 RISC-V 的 ADDI（0010011），必须被拒绝，
        # 证明这套解码器不会误吞非本扩展的指令。
        addi_like = (0b0010011) | (1 << 12)
        with self.assertRaises(ValueError):
            decode_instruction(addi_like)


class QuantumExecutionTest(unittest.TestCase):
    def test_bell_state_perfect_correlation(self):
        asm = """
        qinit 2
        qh q0
        qcx q0,q1
        qmeasure q0,x10
        qmeasure q1,x11
        """
        trials = 300
        mismatches = 0
        seen_both_outcomes = set()
        for _ in range(trials):
            emu = QuantumRISCVEmulator()
            emu.load_program(asm)
            state = emu.execute()
            a, b = state.get("x10", 0), state.get("x11", 0)
            seen_both_outcomes.add((a, b))
            if a != b:
                mismatches += 1
        self.assertEqual(mismatches, 0, "贝尔态两个测量结果必须永远相同")
        # 300 次里两种结果 (0,0)/(1,1) 都应该出现过，不是模拟器把量子门当成了空操作
        self.assertTrue({(0, 0), (1, 1)} <= seen_both_outcomes)

    def test_ghz3_only_all_zero_or_all_one(self):
        asm = """
        qinit 3
        qh q0
        qcx q0,q1
        qcx q1,q2
        qmeasure q0,x10
        qmeasure q1,x11
        qmeasure q2,x12
        """
        outcomes = set()
        for _ in range(300):
            emu = QuantumRISCVEmulator()
            emu.load_program(asm)
            state = emu.execute()
            outcomes.add((state.get("x10", 0), state.get("x11", 0), state.get("x12", 0)))
        self.assertTrue(outcomes <= {(0, 0, 0), (1, 1, 1)})

    def test_deterministic_x_gate_then_measure(self):
        emu = QuantumRISCVEmulator()
        emu.load_program("qinit 1\nqx q0\nqmeasure q0,x5")
        state = emu.execute()
        self.assertEqual(state.get("x5", 0), 1)

    def test_measurement_drives_classical_branch_at_runtime(self):
        # 关键断言：量子测量的结果不是编译期已知的常量，而是运行时真的
        # 影响了经典分支的走向——qx 让结果确定为 1，beq 分支必须走 ELSE。
        asm = """
        qinit 1
        qx q0
        qmeasure q0,x5
        beq x5, x0, WAS_ZERO
        li x1, 999
        j END
        WAS_ZERO:
        li x1, -1
        END:
        """
        emu = QuantumRISCVEmulator()
        emu.load_program(asm)
        state = emu.execute()
        self.assertEqual(state.get("x5", 0), 1)
        self.assertEqual(state.get("x1", 0), 999)

    def test_ccx_toffoli_flips_target_only_when_both_controls_set(self):
        # |11>控制位 -> target 应该被翻转成 1；|10> 只有一个控制位 -> target 仍是 0
        asm_both = "qinit 3\nqx q0\nqx q1\nqccx q0,q1,q2\nqmeasure q2,x2"
        emu = QuantumRISCVEmulator()
        emu.load_program(asm_both)
        self.assertEqual(emu.execute().get("x2", 0), 1)

        asm_one = "qinit 3\nqx q0\nqccx q0,q1,q2\nqmeasure q2,x2"
        emu2 = QuantumRISCVEmulator()
        emu2.load_program(asm_one)
        self.assertEqual(emu2.execute().get("x2", 0), 0)

    def test_binary_encoded_program_runs_end_to_end(self):
        # 完全跳过文本汇编，直接从二进制编码字执行——证明"编码规格"不是
        # 只停留在文档和文本层面的装饰。
        words = [
            encode_instruction("qinit", {"n": 2}),
            encode_instruction("qh", {"q": 0}),
            encode_instruction("qcx", {"q1": 0, "q2": 1}),
            encode_instruction("qmeasure", {"q": 0, "rd": 10}),
            encode_instruction("qmeasure", {"q": 1, "rd": 11}),
        ]
        for _ in range(50):
            emu = QuantumRISCVEmulator()
            decoded = emu.load_encoded_quantum_words(words)
            emu.run_decoded_quantum(decoded)
            self.assertEqual(emu.registers[10], emu.registers[11])


if __name__ == "__main__":
    unittest.main(verbosity=2)
