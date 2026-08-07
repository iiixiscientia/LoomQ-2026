"""L2 Agent 主循环：OpenAI-compatible chat completions + function calling。

正式评测统一使用 DeepSeek deepseek-v4-flash，通过 LOOMQ_LLM_* 环境变量
注入配置。本地调试可以用自己的 DeepSeek key 或其他 OpenAI-compatible 服务。

保留了之前 Anthropic 版本的核心设计：
- tool-use 循环（生成→用 run_circuit 工具自验→不对就重试）
- _ensure_qasm_block 程序化兜底（模型不贴代码块时确定性追加）
- find_backends 精确过滤（不让 LLM 心算后端选型）

改动点：
- Anthropic Messages API → OpenAI chat completions（/chat/completions）
- Anthropic tool_use 格式 → OpenAI function calling（tools + tool_choice）
- ANTHROPIC_API_KEY → LOOMQ_LLM_BASE_URL / LOOMQ_LLM_API_KEY / LOOMQ_LLM_MODEL
- 用标准库 urllib 发请求（同官方 llm_client.py），不依赖任何 SDK
- 每个 case 最多 3 次 LLM 调用（l2_policy.json 限制），要精打细算
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from .system_prompt import build_system_prompt
from .tools import TOOLS, execute_tool

_QASM_BLOCK_RE = re.compile(r"```qasm\s*\n.*?```", re.DOTALL)

# ── 环境变量配置 ──────────────────────────────────────────────────────────

_REQUIRED_ENV = ("LOOMQ_LLM_BASE_URL", "LOOMQ_LLM_API_KEY", "LOOMQ_LLM_MODEL")


def _get_config() -> Dict[str, Any]:
    """读取 LOOMQ_LLM_* 环境变量，缺失时立即报错（不含 key 内容）。"""
    missing = [k for k in _REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        raise RuntimeError(
            "缺少必需的 LoomQ L2 环境变量: " + ", ".join(missing)
            + "。正式评测由组委会统一注入；本地调试请自行 export。"
        )
    return {
        "base_url": os.environ["LOOMQ_LLM_BASE_URL"].rstrip("/"),
        "api_key": os.environ["LOOMQ_LLM_API_KEY"],
        "model": os.environ["LOOMQ_LLM_MODEL"],
        "timeout": float(os.environ.get("LOOMQ_LLM_TIMEOUT_SECONDS", "120")),
        "max_output": int(os.environ.get("LOOMQ_LLM_MAX_OUTPUT_TOKENS", "2000")),
        "max_calls": int(os.environ.get("LOOMQ_LLM_MAX_CALLS", "3")),
    }


# ── LLM 调用 ─────────────────────────────────────────────────────────────

def _chat_completion(
    config: Dict[str, Any],
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """发一次 OpenAI-compatible chat completion 请求，返回原始 JSON。"""
    payload: Dict[str, Any] = {
        "model": config["model"],
        "messages": messages,
        "stream": False,
        "temperature": 0,
        "max_tokens": config["max_output"],
    }
    # DeepSeek v4-flash 特殊参数：关闭 thinking
    if config["model"] == "deepseek-v4-flash":
        payload["thinking"] = {"type": "disabled"}
    if tools:
        payload["tools"] = tools

    request = urllib.request.Request(
        config["base_url"] + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + config["api_key"],
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config["timeout"]) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        raise RuntimeError(f"LoomQ L2 API HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LoomQ L2 API 不可达: {exc.reason}") from exc


# ── 辅助函数 ──────────────────────────────────────────────────────────────

def _extract_text(message: Dict[str, Any]) -> str:
    """从 OpenAI 格式的 assistant message 中提取纯文本。"""
    return (message.get("content") or "").strip()


def _has_tool_calls(message: Dict[str, Any]) -> bool:
    """判断 assistant message 是否包含 function calling。"""
    return bool(message.get("tool_calls"))


def _ensure_qasm_block(
    config: Dict[str, Any],
    messages: List[Dict[str, Any]],
    text: str,
    last_verified_qasm: Optional[str],
    calls_left: int,
) -> str:
    """程序化兜底：如果本轮对话验证过电路，但最终文本没有 ```qasm 代码块，
    先尝试再要求模型补一次（如果还有调用次数）；如果不行就确定性追加。
    """
    if last_verified_qasm is None or _QASM_BLOCK_RE.search(text):
        return text

    if calls_left > 0:
        try:
            nudge_messages = messages + [
                {"role": "assistant", "content": text},
                {
                    "role": "user",
                    "content": (
                        "你的回复里没有包含完整的 ```qasm 代码块，这是硬性格式要求。"
                        "请在保留你刚才的说明的基础上，把最后一次验证通过的完整电路"
                        "重新用 ```qasm 包裹贴出来。"
                    ),
                },
            ]
            resp = _chat_completion(config, nudge_messages)
            nudged_msg = resp["choices"][0]["message"]
            nudged_text = _extract_text(nudged_msg)
            if nudged_text and _QASM_BLOCK_RE.search(nudged_text):
                return nudged_text
        except Exception:
            pass

    # 确定性追加，保证硬性规则 100% 满足
    return f"{text}\n\n```qasm\n{last_verified_qasm}\n```"


# ── 主入口 ────────────────────────────────────────────────────────────────

def agent_chat(prompt: str) -> str:
    """`adapter.py` 的 agent_chat() 直接调用这个函数。

    输入：用户的自然语言请求。
    输出：纯文本，涉及电路时内含 ```qasm 代码块；涉及后端选型时内含规范 id。

    正式评测每个 case 最多 3 次 LLM 调用、8000 输入 token、2000 输出 token。
    策略：第 1 次带工具定义让模型决定要不要调用工具；如果模型请求了工具，
    在本地执行后把结果喂回去，第 2 次让模型给最终答案（不带工具，强制收尾）；
    留第 3 次给 _ensure_qasm_block 补救。
    """
    config = _get_config()
    max_calls = config["max_calls"]
    calls_used = 0

    system_prompt = build_system_prompt()
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    last_verified_qasm: Optional[str] = None

    # ── 第 1 次调用：带工具，让模型自己决定 ──
    resp = _chat_completion(config, messages, tools=TOOLS)
    calls_used += 1
    assistant_msg = resp["choices"][0]["message"]

    if not _has_tool_calls(assistant_msg):
        # 模型直接给了最终答案，不需要工具
        text = _extract_text(assistant_msg)
        if not text:
            text = "（Agent 没有给出文本回复，请重试或换一种问法。）"
        return _ensure_qasm_block(
            config, messages, text, last_verified_qasm,
            max_calls - calls_used,
        )

    # ── 模型请求了工具调用：本地执行全部工具 ──
    # 把 assistant 的 tool_calls 消息加入历史
    messages.append({
        "role": "assistant",
        "content": assistant_msg.get("content") or None,
        "tool_calls": assistant_msg["tool_calls"],
    })

    # 执行每个工具调用，把结果作为 tool message 加入历史
    for tc in assistant_msg["tool_calls"]:
        fn_name = tc["function"]["name"]
        try:
            fn_args = json.loads(tc["function"]["arguments"])
        except (json.JSONDecodeError, KeyError):
            fn_args = {}

        result_text = execute_tool(fn_name, fn_args)

        # 跟踪验证通过的电路
        if fn_name == "run_circuit":
            try:
                parsed = json.loads(result_text)
            except ValueError:
                parsed = {}
            if parsed.get("ok") and fn_args.get("qasm"):
                last_verified_qasm = fn_args["qasm"]

        messages.append({
            "role": "tool",
            "tool_call_id": tc["id"],
            "content": result_text,
        })

    # ── 第 2 次调用：不带工具，强制模型给最终答案 ──
    if calls_used < max_calls:
        resp2 = _chat_completion(config, messages)
        calls_used += 1
        assistant_msg2 = resp2["choices"][0]["message"]
        text = _extract_text(assistant_msg2)
        if not text:
            text = "（Agent 在工具调用后未给出最终答案。）"
        return _ensure_qasm_block(
            config, messages, text, last_verified_qasm,
            max_calls - calls_used,
        )

    # 调用次数已用完，用已有工具结果拼一个基本回复
    if last_verified_qasm:
        return f"电路已验证通过：\n\n```qasm\n{last_verified_qasm}\n```"
    return "（调用次数已达上限，未能生成完整回复。）"
