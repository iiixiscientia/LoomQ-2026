"""共享的抽象中间表示 (IR)。

三个后端的 codegen 都从这个 Circuit 对象出发生成各自的原生格式，
这样"转译器是不是真的通用"就落实在代码结构上：核心逻辑只写一份，
后端差异全部收敛到 src/backends/*.py 和 src/codegen/*.py 里。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class Instruction:
    gate: str                      # 小写门名，如 "h" "cx" "rz"
    qubits: List[int]              # 作用的 qubit 下标（q[k] 的 k）
    params: List[float] = field(default_factory=list)  # 角度参数，单位弧度


@dataclass
class Measurement:
    qubit: int
    clbit: int


@dataclass
class Circuit:
    num_qubits: int
    num_clbits: int
    instructions: List[Instruction] = field(default_factory=list)
    measurements: List[Measurement] = field(default_factory=list)

    def __post_init__(self) -> None:
        # 题面白名单固定为这 12 个门；解析阶段已经校验过，这里再兜底一次，
        # 防止未来手写 Circuit 时手滑传入白名单外的门。
        allowed = {
            "h", "x", "s", "sdg", "t", "tdg",
            "rz", "ry",
            "cx", "cu1", "swap",
            "ccx",
        }
        for inst in self.instructions:
            if inst.gate not in allowed:
                raise ValueError(f"gate '{inst.gate}' 不在题面 12 门白名单内")
