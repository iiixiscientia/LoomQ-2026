#!/usr/bin/env python3
"""验证 codegen.to_originq_ir() 生成的 OriginIR 文本能被 pyqpanda 真的执行，
而不只是"看起来像"OriginIR。

在把 adapter.py 的 originq 执行路径从 run_via_qasm 切到 run_via_originir
之前，先跑这个脚本确认：
  1. `convert_originir_str_to_qprog` 认得我们生成的门名拼写（H/X/S/SDAG/...），
     不会报"未知指令"；
  2. 跑出来的分布跟 reference_simulator 算出的理想分布形状一致（用本地
     CPU 模拟器，不需要真机/网络，也不需要等本源真机维护结束）。

用法：
    python3 tests/originq_ir_roundtrip_test.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.backends.originq_backend import run_via_originir  # noqa: E402
from src.codegen import to_originq_ir  # noqa: E402
from src.qasm_parser import parse_qasm2  # noqa: E402
from src.reference_simulator import ideal_distribution  # noqa: E402

_CIRCUITS = [
    "circuits/bell.qasm",
    "circuits/ghz3.qasm",
    "circuits/coverage/swap_basic.qasm",
]

_SHOTS = 4096
_TOP_K_EPS = 1e-6


def main() -> int:
    all_ok = True
    for path in _CIRCUITS:
        print(f"\n=== {path} ===")
        with open(path, encoding="utf-8") as handle:
            qasm = handle.read()
        circuit = parse_qasm2(qasm)
        originir = to_originq_ir(circuit)
        print("生成的 OriginIR:")
        print(originir)

        try:
            result = run_via_originir(originir, _SHOTS)
        except Exception as exc:  # noqa: BLE001 —— 就是想看到具体报什么错
            print(f"  ❌ 执行失败: {type(exc).__name__}: {exc}")
            all_ok = False
            continue

        counts = result["counts"]
        total = sum(counts.values())
        if total != _SHOTS:
            print(f"  ❌ counts 总和 {total} != shots {_SHOTS}")
            all_ok = False
            continue

        ideal = ideal_distribution(circuit)
        ideal_ranked = sorted(ideal.items(), key=lambda kv: kv[1], reverse=True)
        k = sum(1 for _, p in ideal_ranked if p > _TOP_K_EPS)
        ideal_top = {state for state, _ in ideal_ranked[:k]}

        actual_ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
        actual_top = {state for state, _ in actual_ranked[:k]}

        print(f"  实测 counts: {counts}")
        print(f"  理想 Top-{k}: {sorted(ideal_top)}  实测 Top-{k}: {sorted(actual_top)}")

        if actual_top == ideal_top:
            print("  ✅ OriginIR 路径可执行，且分布形状跟理想分布一致")
        else:
            print("  ❌ 分布对不上——可能是位序问题，也可能是门语义/拼写问题")
            all_ok = False

    print("\n" + ("✅ 全部通过，可以放心把 adapter.py 切到 run_via_originir" if all_ok else "❌ 有失败项，先别改 adapter.py"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
