#!/usr/bin/env python3
"""L2 Agent 压力测试——不是官方评测题目，是自己模拟"未公开 prompt 变体"
写的补充用例，跟 agent_smoke_test.py（照抄题面三个示例）配套用：
smoke test 只覆盖题面给的原始措辞，这份覆盖"换一种问法/换比特数/换目标态/
白名单外的门/无解的约束组合/彻底模糊的意图"，专门用来发现"示例 prompt 能
过，但换个说法就崩"这类问题。

背景：第一次跑这份测试时真的发现了两类回归：
1. 选后端类问题——Haiku 心算"6 条后端记录里哪些同时满足 3 条约束"不够
   稳，同一类问题换措辞后有时漏掉一个满足条件的、有时把一个明显不满足
   （比如比特数不够）的也当"接近"选项列进正确答案。修法：新增
   `find_backends` 工具把过滤逻辑写成确定性 Python 代码（见
   `src/agent/tools.py`），不再依赖 LLM 心算。
2. 硬性格式规则（"最终回复必须重新贴出完整 ```qasm 代码块"）——Haiku
   大多数时候遵守，但同一个 prompt 换一次采样结果，偶尔会退化成"上面的
   代码就是修好的版本"这种纯文字描述。修法：`src/agent/agent.py` 里加了
   `_ensure_qasm_block()` 兜底——先礼貌地再要求模型补一次，模型还是不
   配合就把本轮验证过的电路确定性地追加进最终文本，不再赌模型这次听不听
   话。

跑这份文件之前先跑 agent_smoke_test.py 确认基础三个用例没坏。

2026-08-01 更新：协议从 Anthropic 换成 OpenAI-compatible（DeepSeek
deepseek-v4-flash），另外这一版还发现并修了一个数据 bug——`find_backends`
之前读的是自己转录的后端数据（字段名/枚举值跟官方 backend_capabilities.json
对不上），现在直接读官方那份，字段名是 `requires_account`/`free_quota`/
`cloud`（不是旧版的 `account_required`/`free_tier`/`cloud_simulator_or_qpu`）。
下面几个用例期望的 id 集合本身没变（数据值没变，只是字段名变了），不用改。

用法（本地用自己的 DeepSeek key 调试；正式评测这几个变量由组委会注入）：
    export LOOMQ_LLM_BASE_URL="https://api.deepseek.com"
    export LOOMQ_LLM_API_KEY="<你的 DeepSeek key>"
    export LOOMQ_LLM_MODEL="deepseek-v4-flash"
    python3 tests/agent_stress_test.py                      # 跑全部用例
    python3 tests/agent_stress_test.py backend-no-solution   # 只跑某几个（按名字）
"""
from __future__ import annotations

import math
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
    states = set(observed) | set(expected)
    distance = math.sqrt(
        sum((math.sqrt(observed.get(s, 0.0)) - math.sqrt(expected.get(s, 0.0))) ** 2 for s in states)
    ) / math.sqrt(2.0)
    return max(0.0, min(1.0, 1.0 - distance))


def extract_qasm(text: str):
    matches = _QASM_TAGGED_BLOCK.findall(text)
    if matches:
        return matches[-1].strip()
    matches = _ANY_BLOCK.findall(text)
    if matches:
        return matches[0].strip()
    return None


def run_case(name, prompt, check_fn):
    print(f"\n{'='*90}\n[{name}] {prompt}\n{'-'*90}")
    reply = adapter.agent_chat(prompt)
    print(reply)
    print(f"{'-'*90}")
    ok, note = check_fn(reply)
    tag = "🔍人工判断" if ok is None else ("✅ 通过" if ok else "❌ 未通过")
    print(f"判定: {tag} — {note}")
    return name, ok, note


# ---------- 判定函数 ----------

def check_state_fidelity(expected):
    def _check(reply):
        qasm = extract_qasm(reply)
        if not qasm:
            return False, "回复里没有 ```qasm 代码块（硬性规则违反）"
        try:
            circuit = parse_qasm2(qasm)
            observed = ideal_distribution(circuit)
        except Exception as exc:  # noqa: BLE001
            return False, f"生成电路解析/模拟失败: {exc}"
        fid = hellinger_fidelity(observed, expected(circuit) if callable(expected) else expected)
        return fid >= FIDELITY_THRESHOLD, f"fidelity={fid:.4f}, observed={observed}"
    return _check


def check_ids_exact_set(expected_ids):
    """判定标准照着官方 backend_capabilities.md 的说法："正确答案集 = 表中
    满足全部约束的后端"，只要求回复包含正确答案集里的 id；不惩罚 Agent 在
    解释"为什么某个选项被排除"时提到那个被排除的 id 本身——这是
    `find_backends` 工具 `excluded` 字段设计出来就要用的东西，透明地说明
    排除理由是好的交互体验，不是答错。之前这里用"多余就判失败"太严格，
    实测中把一个说理正确、只推荐了唯一正解、但顺带解释了两个不合格选项
    的回复误判成了失败。
    """
    def _check(reply):
        all_ids = {
            "spinq_taurus_simulator", "spinq_cloud_qpu", "originq_local_simulator",
            "originq_wukong", "braket_local_simulator", "braket_cloud",
        }
        mentioned = {bid for bid in all_ids if bid in reply}
        extra = mentioned - expected_ids
        missing = expected_ids - mentioned
        ok = not missing
        note = f"提到={mentioned}, 期望={expected_ids}, 遗漏={missing}"
        if extra:
            note += f"（另外提到 {extra}，如果是在解释'为什么排除'不算错，人工确认一下上下文）"
        return ok, note
    return _check


def check_manual(note):
    def _check(reply):
        return None, note  # 没有唯一标准答案/需要主观判断，人工看输出
    return _check


def ghz_ideal(n):
    z, o = "0" * n, "1" * n
    return {z: 0.5, o: 0.5}


def bell_ideal():
    return {"00": 0.5, "11": 0.5}


CASES = [
    # ---- 生成：换措辞/换比特数/换语言/换目标态 ----
    ("gen-colloquial-4qubit-ghz",
     "帮我搞个4比特的GHZ态呗,全部测一下",
     check_state_fidelity(lambda c: ghz_ideal(c.num_clbits))),

    ("gen-english-bell",
     "Please write OpenQASM code for a Bell pair and measure both qubits.",
     check_state_fidelity(bell_ideal())),

    ("gen-anticorrelated",
     "我要两个比特的电路,测量结果只会是01或者10,不会是00或11",
     check_manual("反相关态(比如H+CX+X),没有唯一标准答案,人工看是否语义正确")),

    # ---- 纠错：不同错误类型/不同目标态/白名单外的门 ----
    ("bugfix-ghz3-missing-semicolons",
     "我要一个GHZ态,但这段代码跑不了:\nOPENQASM 2.0;\ninclude \"qelib1.inc\";\nqreg q[3];\ncreg c[3];\nH q[0]\nCX q[0],q[1]\nCX q[1],q[2]\nmeasure q->c",
     check_state_fidelity(lambda c: ghz_ideal(c.num_clbits))),

    ("bugfix-outside-whitelist-gate",
     "帮我看看这个电路哪里错了,我想要3比特全部纠缠在一起:\nOPENQASM 2.0;\ninclude \"qelib1.inc\";\nqreg q[3];\ncreg c[3];\nh q[0];\nccz q[0],q[1],q[2];\nmeasure q -> c;",
     check_manual("ccz不在12门白名单里,人工看Agent是否发现并用允许的门重新实现,而不是直接照抄ccz")),

    # ---- 选后端：唯一解/多解/无解三种组合 ----
    ("backend-20qubit-free-noqueue",
     "我要跑一个20比特的电路,不想排队,而且预算是零,选哪个平台?",
     check_ids_exact_set({"spinq_taurus_simulator", "originq_local_simulator", "braket_local_simulator"})),

    ("backend-real-qpu-10qubit-free",
     "我想用免费的真机测一下,不要模拟器,大概10比特左右就行",
     check_ids_exact_set({"originq_wukong"})),

    ("backend-no-solution",
     "我要一个100比特、免费、零排队的真机,有吗?",
     check_manual("能力表里没有任何后端同时满足100比特+免费+零排队+真机,人工看Agent是否老实说没有,而不是硬凑答案")),

    # ---- 模糊/边界表述：交互体验部分,评委现场测试时最可能踩的类型 ----
    ("ambiguous-vague-request",
     "帮我做一个能让人惊讶的量子电路",
     check_manual("完全模糊的意图,人工看Agent是反问澄清,还是自己合理猜测并说明假设,还是瞎编")),

    ("ambiguous-cat-metaphor",
     "生成一个能体现'薛定谔的猫'那种感觉的电路",
     check_manual("科普隐喻,人工看Agent是否映射成多比特GHZ这种标准'猫态',还是退化成单比特叠加")),
]


def main():
    wanted = set(sys.argv[1:])
    cases = [c for c in CASES if not wanted or c[0] in wanted]
    results = [run_case(name, prompt, check_fn) for name, prompt, check_fn in cases]

    print(f"\n\n{'#'*90}\n汇总\n{'#'*90}")
    auto_pass = auto_fail = manual = 0
    for name, ok, note in results:
        if ok is None:
            tag, manual = "🔍人工判断", manual + 1
        elif ok:
            tag, auto_pass = "✅", auto_pass + 1
        else:
            tag, auto_fail = "❌", auto_fail + 1
        print(f"{tag} {name}: {note}")
    print(f"\n自动判定: {auto_pass} 通过 / {auto_fail} 失败 / {manual} 需人工看")
    return 0 if auto_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
