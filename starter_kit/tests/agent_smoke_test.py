#!/usr/bin/env python3
"""L2 判定用例的自测脚本——照着 problem_statement.md 第五节"L2 判定"里给的
三个示例 prompt 写的（正式评测用的是未公开的同类变体，这里只是自己先摸底，
不代表就是评测原题）。

⚠️ 2026-08-01 题面定稿后协议改成 OpenAI-compatible chat completions，模型
固定为 DeepSeek deepseek-v4-flash，配置只从环境变量读取（见下），没配置
好这个脚本跑不起来（会在 adapter.agent_chat() 里直接抛 AgentError）。

用法（本地用自己的 DeepSeek key 调试；正式评测这几个变量由组委会注入）：
    export LOOMQ_LLM_BASE_URL="https://api.deepseek.com"
    export LOOMQ_LLM_API_KEY="<你的 DeepSeek key>"
    export LOOMQ_LLM_MODEL="deepseek-v4-flash"
    python3 tests/agent_smoke_test.py
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import adapter  # noqa: E402
from src.qasm_parser import parse_qasm2  # noqa: E402
from src.reference_simulator import ideal_distribution  # noqa: E402

FIDELITY_THRESHOLD = 0.97
_QASM_TAGGED_BLOCK = re.compile(r"```qasm\s*\n(.*?)```", re.DOTALL)
_ANY_BLOCK = re.compile(r"```\w*\s*\n(.*?)```", re.DOTALL)


def hellinger_fidelity(observed, expected) -> float:
    import math

    states = set(observed) | set(expected)
    distance = math.sqrt(
        sum((math.sqrt(observed.get(s, 0.0)) - math.sqrt(expected.get(s, 0.0))) ** 2 for s in states)
    ) / math.sqrt(2.0)
    return max(0.0, min(1.0, 1.0 - distance))


def extract_qasm(text: str) -> str | None:
    # 优先取显式标了 ```qasm 的代码块——不能简单"取最后一个代码块"，因为
    # 回复里经常还带一个 ASCII 条形图之类的可视化，也用 ``` 包裹，取最后一个
    # 反而会抓错（实测踩过这个坑：GHZ 生成那次真正的 QASM 是对的，但脚本抓到
    # 了后面的条形图代码块，误判成失败）。
    matches = _QASM_TAGGED_BLOCK.findall(text)
    if matches:
        return matches[-1].strip()
    # 没有显式 qasm 标签的话，退而求其次取第一个通用代码块。
    matches = _ANY_BLOCK.findall(text)
    if matches:
        return matches[0].strip()
    return None


def ghz_ideal(n: int) -> dict:
    zero = "0" * n
    one = "1" * n
    return {zero: 0.5, one: 0.5}


def bell_ideal() -> dict:
    return {"00": 0.5, "11": 0.5}


def case_intent_generation() -> bool:
    print("\n=== 用例1：意图生成（3比特GHZ态，全测量）===")
    prompt = "生成一个 3 比特的最大纠缠态 (GHZ 态)，并进行全测量"
    reply = adapter.agent_chat(prompt)
    print(reply)

    qasm = extract_qasm(reply)
    if not qasm:
        print("❌ 回复里没找到 ```qasm 代码块")
        return False

    try:
        circuit = parse_qasm2(qasm)
        observed = ideal_distribution(circuit)
    except Exception as exc:  # noqa: BLE001
        print(f"❌ 生成的电路解析/模拟失败: {exc}")
        return False

    expected = ghz_ideal(circuit.num_clbits)
    fidelity = hellinger_fidelity(observed, expected)
    print(f"理想分布(按{circuit.num_clbits}比特GHZ推断)={expected}")
    print(f"实际分布={observed}")
    print(f"fidelity={fidelity:.6f}")
    ok = fidelity >= FIDELITY_THRESHOLD
    print("✅ 通过" if ok else "❌ 未通过")
    return ok


def case_bug_fix() -> bool:
    print("\n=== 用例2：代码纠错（贝尔态，未定义寄存器+门名大小写错误）===")
    prompt = (
        "我想制备一个贝尔态，但这段代码报错了，帮我修好：\n"
        "H q[0]; CX q[0] q[1]"
    )
    reply = adapter.agent_chat(prompt)
    print(reply)

    qasm = extract_qasm(reply)
    if not qasm:
        print("❌ 回复里没找到 ```qasm 代码块")
        return False

    try:
        circuit = parse_qasm2(qasm)
        observed = ideal_distribution(circuit)
    except Exception as exc:  # noqa: BLE001
        print(f"❌ 修复后的电路解析/模拟失败: {exc}")
        return False

    fidelity = hellinger_fidelity(observed, bell_ideal())
    print(f"理想分布(贝尔态)={bell_ideal()}")
    print(f"实际分布={observed}")
    print(f"fidelity={fidelity:.6f}")
    ok = fidelity >= FIDELITY_THRESHOLD
    print("✅ 通过" if ok else "❌ 未通过")
    return ok


def case_backend_selection() -> bool:
    print("\n=== 用例3：智能选后端（15比特电路+零排队）===")
    prompt = "我需要运行一个 15 比特电路，且零排队等待，选哪个平台？"
    reply = adapter.agent_chat(prompt)
    print(reply)

    # 按 data/backend_capabilities.json 手动推导正确答案集：
    # max_qubits >= 15 且 queue == none -> 三个本地模拟器
    expected_ids = {"spinq_taurus_simulator", "originq_local_simulator", "braket_local_simulator"}
    hit = {bid for bid in expected_ids if bid in reply}
    print(f"回复里命中的规范标识: {hit}")
    ok = len(hit) > 0
    print("✅ 通过（至少命中一个正确答案）" if ok else "❌ 未通过，回复里没有任何正确的规范标识")
    return ok


def main() -> int:
    results = [case_intent_generation(), case_bug_fix(), case_backend_selection()]
    passed = sum(results)
    print(f"\n{passed}/3 通过")
    return 0 if passed == 3 else 1


if __name__ == "__main__":
    sys.exit(main())
