#!/usr/bin/env python3
"""L3 · src/hybrid_compiler.py 的自建穷举测试。

官方 evaluator.py 的 `l3:public-branch` 只测了一个最简单的 if/else 分支
（见 evaluator.py 里硬编码的那段 Hybrid-QASM）。这个文件补测隐藏用例可能
出现的其它语法组合：嵌套 if（含无 else 分支）、寄存器-寄存器比较、
!=、字面量在减法左边、多个测量位、多语句顺序执行——对每种情况穷举所有
测量值组合，用 riscv_emulator.py 实际跑一遍，跟 Python 里独立算出的
期望值比对，同时检查最终寄存器状态里没有意外残留的非零临时寄存器
（这是"整个程序末尾统一清零临时寄存器"这个设计能不能扛住嵌套的关键指标）。

用法：
    python3 tests/hybrid_compiler_test.py
"""
from __future__ import annotations

import itertools
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.hybrid_compiler import compile_hybrid_qasm  # noqa: E402
from riscv_emulator import TinyRISCVEmulator  # noqa: E402


def run(asm: str, injections: dict) -> dict:
    emu = TinyRISCVEmulator()
    emu.load_program(asm)
    for reg, val in injections.items():
        emu.set_register(reg, val)
    return emu.execute()


class HybridCompilerTest(unittest.TestCase):
    def _check(self, source, cases):
        """cases: list of (injections_dict, expected_regs_dict)。

        expected_regs_dict 只需要写非零的项——riscv_emulator 的 execute()
        本身也只返回非零寄存器。同时断言除了 injections 和 expected 提到的
        寄存器之外，没有别的寄存器意外非零（临时寄存器清零是否彻底）。
        """
        _, asm = compile_hybrid_qasm(source)
        for injections, expected in cases:
            state = run(asm, injections)
            for reg, val in expected.items():
                self.assertEqual(state.get(reg, 0), val,
                                  f"injections={injections} reg={reg} asm=\n{asm}")
            allowed = set(expected) | set(injections)
            leftover = {k: v for k, v in state.items() if k not in allowed}
            self.assertFalse(leftover,
                              f"意外残留的非零寄存器 {leftover}，injections={injections}\nasm=\n{asm}")

    def test_official_public_case(self):
        # 跟 evaluator.py 里 evaluate_l3() 硬编码的用例完全一致
        src = """OPENQASM 2.0;
include "qelib1.inc";
qreg q[1];
creg c[1];
measure q[0] -> c[0];
classical { if (c[0] == 1) { r1 = 7; } else { r1 = 3; } }
"""
        self._check(src, [({"x10": 0}, {"x1": 3}), ({"x10": 1}, {"x1": 7})])

    def test_rubric_manual_example(self):
        # 赛题手册第三节原样给出的例子：if/else 之后还有一条顺序语句
        src = """OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
creg c[2];
h q[0];
measure q[0] -> c[0];
classical {
  if (c[0] == 1) {
    r1 = 100;
  } else {
    r1 = 10;
  }
  r1 = r1 + 5;
}
cx q[0], q[1];
"""
        quantum_ops, _ = compile_hybrid_qasm(src)
        self.assertEqual(quantum_ops, ["h q[0];", "measure q[0] -> c[0];", "cx q[0], q[1];"])
        self._check(src, [({"x10": 0}, {"x1": 15}), ({"x10": 1}, {"x1": 105})])

    def test_nested_if_without_else(self):
        src = """OPENQASM 2.0;
include "qelib1.inc";
qreg q[2]; creg c[2];
measure q[0] -> c[0];
measure q[1] -> c[1];
classical {
  if (c[0] == 1) {
    if (c[1] == 1) {
      r1 = 11;
    }
    r2 = 2;
  } else {
    r1 = 0;
  }
}
"""
        cases = []
        for b0, b1 in itertools.product((0, 1), (0, 1)):
            if b0 == 1 and b1 == 1:
                exp = {"x1": 11, "x2": 2}
            elif b0 == 1:
                exp = {"x2": 2}
            else:
                exp = {}
            cases.append(({"x10": b0, "x11": b1}, exp))
        self._check(src, cases)

    def test_register_to_register_compare_and_add(self):
        src = """OPENQASM 2.0;
include "qelib1.inc";
qreg q[2]; creg c[2];
measure q[0] -> c[0];
measure q[1] -> c[1];
classical {
  if (c[0] != c[1]) {
    r3 = 9;
  } else {
    r3 = 1;
  }
  r4 = r3 + r3;
}
"""
        cases = []
        for b0, b1 in itertools.product((0, 1), (0, 1)):
            r3 = 9 if b0 != b1 else 1
            cases.append(({"x10": b0, "x11": b1}, {"x3": r3, "x4": r3 + r3}))
        self._check(src, cases)

    def test_literal_minus_register(self):
        src = """OPENQASM 2.0;
include "qelib1.inc";
qreg q[1]; creg c[1];
measure q[0] -> c[0];
classical {
  r5 = 20;
  if (c[0] == 0) {
    r5 = 3;
  }
  r6 = 20 - r5;
}
"""
        cases = []
        for b0 in (0, 1):
            r5 = 3 if b0 == 0 else 20
            exp = {"x6": 20 - r5}
            if r5 != 0:
                exp["x5"] = r5
            cases.append(({"x10": b0}, exp))
        self._check(src, cases)

    def test_three_sequential_independent_ifs(self):
        # 连续三个互不嵌套的 if，验证临时寄存器栈式分配在"用完就还"之后
        # 能被下一个 if 正确复用，不会无限增长撑爆 x20-x29 池子。
        src = """OPENQASM 2.0;
include "qelib1.inc";
qreg q[3]; creg c[3];
measure q[0] -> c[0];
measure q[1] -> c[1];
measure q[2] -> c[2];
classical {
  if (c[0] == 1) { r1 = 1; } else { r1 = 0; }
  if (c[1] == 1) { r2 = 1; } else { r2 = 0; }
  if (c[2] == 1) { r3 = 1; } else { r3 = 0; }
  r4 = r1 + r2;
  r4 = r4 + r3;
}
"""
        cases = []
        for b0, b1, b2 in itertools.product((0, 1), repeat=3):
            exp = {}
            if b0:
                exp["x1"] = 1
            if b1:
                exp["x2"] = 1
            if b2:
                exp["x3"] = 1
            total = b0 + b1 + b2
            if total:
                exp["x4"] = total
            cases.append(({"x10": b0, "x11": b1, "x12": b2}, exp))
        self._check(src, cases)

    def test_no_classical_block_is_legal(self):
        src = """OPENQASM 2.0;
include "qelib1.inc";
qreg q[1]; creg c[1];
h q[0];
measure q[0] -> c[0];
"""
        quantum_ops, asm = compile_hybrid_qasm(src)
        self.assertEqual(quantum_ops, ["h q[0];", "measure q[0] -> c[0];"])
        self.assertTrue(asm.strip())
        # 空经典块编译出的汇编不应该抛异常，跑起来也不应该产生任何非零寄存器
        state = run(asm, {})
        self.assertEqual(state, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
