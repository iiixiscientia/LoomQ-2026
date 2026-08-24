#!/usr/bin/env python3
"""核对 real_hardware/results/*.json 是否满足官方"主峰命中"判定标准。

problem_statement.md 原话（L1 真机接入证据判定）：
    "counts 的 Top-K 主导态与理想分布一致（真机允许噪声，只查主峰命中）"

K 怎么定：默认取"理想分布里概率 > 1e-6 的态的个数"——确定性电路（如
swap_basic）理想分布只有一个态，K=1；对称纠缠态电路（如 bell、ghz3）理想
分布有 2 个等概率的态，K=2。可以用 --top-k 手动覆盖。

用法：
    python3 real_hardware/verify_result.py real_hardware/results/spinq_swap_basic.json \
        --qasm circuits/coverage/swap_basic.qasm

    # 批量核对某个目录下所有 result.json（--qasm 从 meta.source_file 读）：
    python3 real_hardware/verify_result.py real_hardware/results/*.json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.qasm_parser import parse_qasm2  # noqa: E402
from src.reference_simulator import ideal_distribution  # noqa: E402

_EPS = 1e-6


def _load_ideal(qasm_path: str) -> dict:
    with open(qasm_path, encoding="utf-8") as handle:
        qasm = handle.read()
    circuit = parse_qasm2(qasm)
    return ideal_distribution(circuit)


def verify_one(result_path: str, qasm_path: str | None, top_k: int | None) -> bool:
    with open(result_path, encoding="utf-8") as handle:
        result = json.load(handle)

    counts = result.get("counts", {})
    shots = result.get("shots")
    total = sum(counts.values())

    print(f"\n=== {result_path} ===")
    print(f"backend={result.get('backend')} job_id={result.get('job_id')} shots={shots}")

    ok = True

    # 1. Schema 基本合法性：counts 总和必须精确等于 shots
    if total != shots:
        print(f"  ❌ Schema 不合法：counts 总和 {total} != shots {shots}")
        ok = False
    else:
        print(f"  ✅ counts 总和精确等于 shots（{total}）")

    # 2. job_id 是否还是占位符（提交前必须清掉）
    job_id = str(result.get("job_id", ""))
    if job_id.startswith("TODO"):
        print(f"  ❌ job_id 还是占位符，未填真实值：{job_id}")
        ok = False
    else:
        print(f"  ✅ job_id 已填写：{job_id}（记得去平台控制台核对能溯源）")

    # 3. 主峰命中
    if not qasm_path:
        qasm_path = result.get("meta", {}).get("source_file")
    if not qasm_path or not os.path.isfile(qasm_path):
        print(f"  ⚠️ 找不到源电路文件（{qasm_path}），跳过主峰命中判定")
        return ok

    ideal = _load_ideal(qasm_path)
    ideal_ranked = sorted(ideal.items(), key=lambda kv: kv[1], reverse=True)
    k = top_k if top_k is not None else sum(1 for _, p in ideal_ranked if p > _EPS)
    ideal_top = {state for state, _ in ideal_ranked[:k]}

    actual_ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    actual_top = {state for state, _ in actual_ranked[:k]}

    print(f"  理想 Top-{k} 主导态: {sorted(ideal_top)}")
    print(f"  实测 Top-{k} 主导态: {sorted(actual_top)}")

    if actual_top == ideal_top:
        print(f"  ✅ 主峰命中（Top-{k} 一致）")
    else:
        print(f"  ❌ 主峰未命中——检查位序有没有反、电路是不是编译错了")
        ok = False

    return ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("result_json", nargs="+", help="一个或多个 result.json（支持通配符）")
    parser.add_argument("--qasm", help="源电路文件；不填则从 meta.source_file 读")
    parser.add_argument("--top-k", type=int, default=None, help="不填则按理想分布非零态个数自动推断")
    args = parser.parse_args()

    paths: list[str] = []
    for pattern in args.result_json:
        matched = glob.glob(pattern)
        paths.extend(matched if matched else [pattern])

    all_ok = True
    for path in paths:
        all_ok &= verify_one(path, args.qasm, args.top_k)

    print("\n" + ("✅ 全部通过" if all_ok else "❌ 有未通过项，见上面详情"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
