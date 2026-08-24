#!/usr/bin/env python3
"""12 门白名单覆盖测试：拿 src/reference_simulator.py 算出的理想分布做
ground truth，跑三个真实后端，算 Hellinger fidelity（跟官方 evaluator.py
同一套公式、同一个 0.97 阈值）。

跟 evaluator.py 的区别：evaluator.py 只公开了 Bell/GHZ 两个电路（只覆盖
h/cx），这个脚本用 circuits/coverage/ 下的电路把另外 10 个白名单门也测到——
x, s, sdg, t, tdg, rz, ry, swap, cu1, ccx。

用法：
    python3 tests/gate_coverage_test.py                    # 测全部三平台
    python3 tests/gate_coverage_test.py --target spinq      # 只测一个

需要真实 SDK 已装好（spinq 需要 spinq_env/ 已建好，见 README）。
"""
from __future__ import annotations

import argparse
import glob
import math
import os
import sys
from typing import Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import adapter  # noqa: E402
from src.qasm_parser import parse_qasm2  # noqa: E402
from src.reference_simulator import ideal_distribution  # noqa: E402

FIDELITY_THRESHOLD = 0.97
SHOTS = 8192


def hellinger_fidelity(observed: Dict[str, float], expected: Dict[str, float]) -> float:
    states = set(observed) | set(expected)
    distance = math.sqrt(
        sum(
            (math.sqrt(observed.get(s, 0.0)) - math.sqrt(expected.get(s, 0.0))) ** 2
            for s in states
        )
    ) / math.sqrt(2.0)
    return max(0.0, min(1.0, 1.0 - distance))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="spinq,originq,braket")
    parser.add_argument(
        "--circuits-dir",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "circuits", "coverage"),
    )
    args = parser.parse_args()
    targets = [t.strip() for t in args.target.split(",") if t.strip()]

    circuit_files = sorted(glob.glob(os.path.join(args.circuits_dir, "*.qasm")))
    if not circuit_files:
        print(f"没在 {args.circuits_dir} 找到任何 .qasm 文件")
        return 1

    total = 0
    passed = 0
    for path in circuit_files:
        name = os.path.basename(path)
        with open(path, encoding="utf-8") as handle:
            qasm = handle.read()

        try:
            ideal = ideal_distribution(parse_qasm2(qasm))
        except Exception as exc:  # noqa: BLE001
            print(f"[SKIP] {name}: 参考模拟器算理想分布失败: {exc}")
            continue

        for target in targets:
            total += 1
            label = f"{name}:{target}"
            try:
                result = adapter.run(qasm, target, SHOTS)
                observed = {k: v / SHOTS for k, v in result["counts"].items()}
                fidelity = hellinger_fidelity(observed, ideal)
                status = "PASS" if fidelity >= FIDELITY_THRESHOLD else "FAIL"
                if status == "PASS":
                    passed += 1
                print(f"[{status}] {label}: fidelity={fidelity:.6f} (理想分布={ideal}, 实测={observed})")
            except Exception as exc:  # noqa: BLE001
                print(f"[FAIL] {label}: {type(exc).__name__}: {exc}")

    print(f"\n{passed}/{total} 通过")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
