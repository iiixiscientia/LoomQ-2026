"""L2 Agent 暴露给 LLM 的工具（OpenAI-compatible function calling 格式）。

2026-08-01 题面正式定稿后重写：
1. 协议从 Anthropic tool-use 换成 OpenAI `tools`/function-calling 格式
   （`{"type": "function", "function": {"name", "description", "parameters"}}`），
   因为正式评分锁定 DeepSeek `deepseek-v4-flash`，走 `openai_chat_completions`
   协议，DeepSeek V4 系列支持标准 OpenAI 风格 function calling。
2. **修正了一个真实 bug**：上一版 `find_backends` 用的后端字段是自己转录的
   （`account_required`/`cost: free_tier`/`kind: cloud_simulator_or_qpu`），
   跟仓库里其实一直就有的官方 `starter-kit/backend_capabilities.json`
   （`requires_account`/`cost: free_quota`/`kind: cloud`）对不上——两份文件
   长得像但字段名和枚举值不一样。旧版system prompt 的说法"starter-kit 官方
   只给了 .md 没给机读版"是错的，json 从发布第一天就在，只是没人去核对内容
   一致性，自己又转录了一份不一致的。现在直接读官方那份，不再维护自己的
   副本，避免这类"两份数据长得像但不一致"的问题再犯。

只保留两个工具，不做"意图识别→分发专门工具"的硬编码分支——题面原话
"关键词匹配硬编码应答无法通过"：
- `run_circuit`：跑在 L1 同一套 parser + 精确态矢量模拟器上，纯本地计算，
  不占用 L2 每 case 最多 3 次的模型调用预算，可以随便调用自验。
- `find_backends`：对官方后端能力表做精确条件过滤——6 条记录、4 个字段
  交叉约束，压力测试证明这件事让 LLM 心算不够稳（漏看/错看），把过滤逻辑
  写成确定性 Python 代码，LLM 只需要把自然语言约束翻译成参数。
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.qasm_parser import QasmParseError, parse_qasm2  # noqa: E402
from src.reference_simulator import ideal_distribution  # noqa: E402

# 官方权威数据，就在 starter-kit 根目录，不再自己维护一份副本。
_BACKEND_CAPS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "backend_capabilities.json",
)


def _openai_tool(name: str, description: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}


RUN_CIRCUIT_TOOL = _openai_tool(
    "run_circuit",
    "在本地精确态矢量模拟器上解析并执行一段 OpenQASM 2.0 电路。返回语法/门"
    "白名单校验结果，通过时附带精确理论概率分布（无采样噪声）。生成或修改"
    "电路后、给出最终答案前必须调用一次确认；分布跟目标态对不上就修正后"
    "再调用，不要凭感觉判断电路是对的。",
    {
        "type": "object",
        "properties": {
            "qasm": {"type": "string", "description": "完整 OpenQASM 2.0 文本，含 OPENQASM 2.0;/qreg/creg/门/measure。"}
        },
        "required": ["qasm"],
    },
)

FIND_BACKENDS_TOOL = _openai_tool(
    "find_backends",
    "对官方《后端能力表》做精确条件过滤，返回真正同时满足全部约束的后端列表"
    "（matched）和被排除的后端及原因（excluded）。任何'选后端/推荐平台'问题都"
    "必须调用这个工具确定候选集，不要自己心算哪些后端满足条件。matched 里的"
    "id 才是可以推荐的答案，excluded 只用来解释'为什么某个选项不算数'。",
    {
        "type": "object",
        "properties": {
            "min_qubits": {
                "type": "integer",
                "description": "任务需要的最少比特数；只保留 max_qubits >= 此值的后端。不填表示不限制。",
            },
            "queue_in": {
                "type": "array",
                "items": {"type": "string", "enum": ["none", "minutes_to_hours", "hours"]},
                "description": "只保留 queue 属于此集合的后端。'零排队/不想等'填 [\"none\"]。",
            },
            "cost_in": {
                "type": "array",
                "items": {"type": "string", "enum": ["free", "free_quota", "paid"]},
                "description": "只保留 cost 属于此集合的后端。'免费/不想花钱'时 free 和 free_quota 都算，填两者。",
            },
            "kind_in": {
                "type": "array",
                "items": {"type": "string", "enum": ["simulator", "qpu", "cloud"]},
                "description": "只保留 kind 属于此集合的后端。'要真机/不要模拟器'填 [\"qpu\",\"cloud\"]；'只要模拟器'填 [\"simulator\"]。",
            },
        },
    },
)


def _load_backends() -> List[Dict[str, Any]]:
    try:
        with open(_BACKEND_CAPS_PATH, encoding="utf-8") as handle:
            return json.load(handle)["backends"]
    except Exception:  # noqa: BLE001
        return []


def find_backends(
    min_qubits: Optional[int] = None,
    queue_in: Optional[List[str]] = None,
    cost_in: Optional[List[str]] = None,
    kind_in: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """`FIND_BACKENDS_TOOL` 的实现，字段名跟官方 backend_capabilities.json 一致：
    `id`/`platform`/`name`/`kind`(simulator|qpu|cloud)/`max_qubits`/
    `queue`(none|minutes_to_hours|hours)/`cost`(free|free_quota|paid)/
    `requires_account`/`notes`。
    """
    backends = _load_backends()
    if not backends:
        return {"ok": False, "error": "backend_capabilities.json 加载失败，无法过滤，如实告知用户数据不可用"}

    matched, excluded = [], []
    for b in backends:
        reasons = []
        if min_qubits is not None and b["max_qubits"] < min_qubits:
            reasons.append(f"max_qubits={b['max_qubits']} < 需要的 {min_qubits}")
        if queue_in is not None and b["queue"] not in queue_in:
            reasons.append(f"queue={b['queue']!r} 不在允许集合 {queue_in}")
        if cost_in is not None and b["cost"] not in cost_in:
            reasons.append(f"cost={b['cost']!r} 不在允许集合 {cost_in}")
        if kind_in is not None and b["kind"] not in kind_in:
            reasons.append(f"kind={b['kind']!r} 不在允许集合 {kind_in}")

        entry = {
            "id": b["id"],
            "name": b["name"],
            "max_qubits": b["max_qubits"],
            "queue": b["queue"],
            "cost": b["cost"],
            "kind": b["kind"],
            "requires_account": b.get("requires_account"),
        }
        if reasons:
            entry["excluded_because"] = reasons
            excluded.append(entry)
        else:
            matched.append(entry)

    return {"ok": True, "matched": matched, "excluded": excluded}


def run_circuit(qasm: str) -> Dict[str, Any]:
    """`RUN_CIRCUIT_TOOL` 的实现。"""
    try:
        circuit = parse_qasm2(qasm)
    except QasmParseError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    if not circuit.measurements:
        return {
            "ok": False,
            "error": "电路里没有 measure 语句，测不出任何分布。至少要有一条 "
            "'measure q -> c;'（整寄存器）或逐比特 'measure q[i] -> c[i];'。",
        }

    try:
        dist = ideal_distribution(circuit)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"电路语法通过，但模拟执行失败：{type(exc).__name__}: {exc}"}

    ranked = sorted(dist.items(), key=lambda kv: kv[1], reverse=True)
    return {
        "ok": True,
        "num_qubits": circuit.num_qubits,
        "num_clbits": circuit.num_clbits,
        "ideal_distribution": {state: round(p, 6) for state, p in ranked},
        "note": "理论精确分布（无采样噪声），key 位序跟大赛约定一致：最右侧字符是 c[0]。",
    }


TOOLS = [RUN_CIRCUIT_TOOL, FIND_BACKENDS_TOOL]


def execute_tool(name: str, arguments: Dict[str, Any]) -> str:
    """工具分发，返回值是要塞进 `role: tool` 消息 content 的字符串。"""
    if name == "run_circuit":
        result = run_circuit(arguments.get("qasm", ""))
    elif name == "find_backends":
        result = find_backends(
            min_qubits=arguments.get("min_qubits"),
            queue_in=arguments.get("queue_in"),
            cost_in=arguments.get("cost_in"),
            kind_in=arguments.get("kind_in"),
        )
    else:
        result = {"ok": False, "error": f"未知工具: {name}"}
    return json.dumps(result, ensure_ascii=False)
