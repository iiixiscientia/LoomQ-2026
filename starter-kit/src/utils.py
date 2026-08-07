"""跨后端共用的小工具，避免三份 backend 代码里各写一套。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict


def now_iso() -> str:
    """符合大赛 Schema 要求的 UTC 时间戳，如 2026-08-01T12:00:00Z。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def probabilities_to_counts(probabilities: Dict[str, float], shots: int) -> Dict[str, int]:
    """把 {态: 概率} 转成整数 counts，且总和精确等于 shots。

    真机接口（spinqit 的 cloud backend、pyqpanda 的 real_chip_measure）返回
    的都是概率分布，不是原始 counts；但大赛 Schema 要求
    `sum(counts.values()) == shots` 精确成立，直接 `round(p * shots)` 大概率
    会因为浮点误差差 1、2 个——用最大余数法（Largest Remainder Method）分配，
    保证总数精确对上。
    """
    raw = {state: p * shots for state, p in probabilities.items()}
    counts = {state: int(value) for state, value in raw.items()}
    remainder = shots - sum(counts.values())
    if remainder > 0:
        # 按小数部分从大到小，把没分完的 shots 补给余数最大的几个态
        order = sorted(raw, key=lambda state: raw[state] - counts[state], reverse=True)
        for state in order[:remainder]:
            counts[state] += 1
    return counts
