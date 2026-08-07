#!/usr/bin/env python3
"""不依赖任何 SDK 的冒烟测试：只验证 parser + codegen 逻辑本身没写错。

装好三家 SDK 之前，先跑这个确认解析器和序列化器是对的：
    cd submission && python3 tests/smoke_test.py

装好 SDK 之后，再用 evaluator.py 做完整的 transpile+run+保真度自测：
    python3 evaluator.py --target spinq,originq,braket
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import adapter  # noqa: E402


def _load(name: str) -> str:
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "circuits")
    with open(os.path.join(base, name), encoding="utf-8") as handle:
        return handle.read()


def main() -> int:
    failures = 0
    for fname in ("bell.qasm", "ghz3.qasm"):
        qasm = _load(fname)
        for target in adapter.SUPPORTED_TARGETS:
            try:
                native = adapter.transpile(qasm, target)
                assert isinstance(native, str) and native.strip(), "transpile 返回空字符串"
                print(f"[PASS] transpile({fname}, {target})")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"[FAIL] transpile({fname}, {target}): {exc}")

    if failures:
        print(f"\n{failures} 个用例失败")
        return 1
    print("\n全部 parser + codegen 冒烟测试通过（尚未涉及真实 SDK 执行）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
