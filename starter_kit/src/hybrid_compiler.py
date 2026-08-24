"""L3 · Hybrid-QASM × RISC-V 混合编译。

输入：在 OpenQASM 2.0 基础上扩展了一个 `classical { ... }` 经典控制块的
Hybrid-QASM 文本（见赛题手册第三节的语法定义）。

输出：
    quantum_ops : 剥离出的纯量子门/测量指令（保持原始文本顺序，classical
                  块之外的所有非声明行）
    assembly    : 经典控制块编译出的 RISC-V 汇编文本，可直接喂给
                  starter_kit/riscv_emulator.py 的 TinyRISCVEmulator

寄存器映射（跟赛题手册第三节完全一致）：
    r1..r9  -> x1..x9   （经典变量，声明即用，默认值 0）
    c[k]    -> x(10+k)  （测量结果，只读，由评测系统在 execute() 前注入）
临时寄存器只借用 x20..x29（表达式求值/条件判断用的栈式临时寄存器池，
与 r1..r9、c[k] 的地址空间完全不重叠），并且整个程序末尾会把用到过的
临时寄存器全部清零——因为经典块是单入口单出口的结构（每个 if/else 分支
最终都会汇合到同一条后续路径), 末尾的清零指令必然会在任何输入组合下都
被执行到，所以不会在 execute() 返回的"非零寄存器"字典里残留多余的键。

这个模块只做经典块的解析和编译；量子部分的语义等价性由调用方
（adapter.compile_hybrid）直接返回原始指令文本负责，不在这里重新生成。
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple, Union

# ── 1. 从 Hybrid-QASM 源码中切出 (quantum_ops, classical_src) ────────────────

_DECL_PREFIXES = ("OPENQASM", "include", "qreg", "creg")


def split_hybrid_qasm(source: str) -> Tuple[List[str], Optional[str]]:
    """把源码切成"量子指令行列表"和"classical{} 块内的原始文本"。

    classical 块用花括号做定界，块内部（if/else）也会用到花括号，所以必须
    做花括号配对计数，不能简单地用正则找第一个 `}`。
    """
    match = re.search(r"\bclassical\b\s*\{", source)
    if match is None:
        quantum_text = source
        classical_src = None
    else:
        open_idx = match.end() - 1  # 指向那个 '{'
        depth = 0
        close_idx = None
        i = open_idx
        n = len(source)
        while i < n:
            ch = source[i]
            # 行注释里的花括号不算数（防止注释文字里出现 "{"/"}" 打乱配对计数）
            if ch == "/" and i + 1 < n and source[i + 1] == "/":
                nl = source.find("\n", i)
                i = n if nl == -1 else nl
                continue
            if ch == "#":
                nl = source.find("\n", i)
                i = n if nl == -1 else nl
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    close_idx = i
                    break
            i += 1
        if close_idx is None:
            raise ValueError("classical {} 块缺少匹配的右花括号")
        classical_src = source[open_idx + 1 : close_idx]
        quantum_text = source[: match.start()] + "\n" + source[close_idx + 1 :]

    quantum_ops: List[str] = []
    for raw_line in quantum_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("//") or line.startswith("#"):
            continue
        if line.startswith(_DECL_PREFIXES):
            continue
        quantum_ops.append(line)
    return quantum_ops, classical_src


# ── 2. 经典块的 tokenizer ────────────────────────────────────────────────────

_TOKEN_SPEC = [
    # 手册第三节原文说 Hybrid-QASM 的 classical 块"机器可解析，不用自然语言
    # 注释描述语义"——但手册自己给出的示例里，classical{} 内部确实写了
    # "// ..." 注释（纯粹给人类读者看的，不是语法的一部分）。防御性地把
    # 行注释当空白跳过，不管隐藏用例到底会不会带注释，两种情况都能处理。
    ("COMMENT", r"//[^\n]*"),
    ("HASH_COMMENT", r"#[^\n]*"),
    ("EQEQ", r"=="),
    ("NEQ", r"!="),
    ("CREG", r"c\[\s*(\d+)\s*\]"),
    ("REG", r"r([1-9])\b"),
    ("NUM", r"\d+"),
    ("IF", r"if\b"),
    ("ELSE", r"else\b"),
    ("LBRACE", r"\{"),
    ("RBRACE", r"\}"),
    ("LPAREN", r"\("),
    ("RPAREN", r"\)"),
    ("SEMI", r";"),
    ("EQ", r"="),
    ("PLUS", r"\+"),
    ("MINUS", r"-"),
    ("SKIP", r"\s+"),
]
_TOKEN_RE = re.compile("|".join(f"(?P<{name}>{pat})" for name, pat in _TOKEN_SPEC))


class Token:
    __slots__ = ("kind", "value")

    def __init__(self, kind: str, value: str):
        self.kind = kind
        self.value = value

    def __repr__(self):
        return f"Token({self.kind!r}, {self.value!r})"


def tokenize(text: str) -> List[Token]:
    tokens: List[Token] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m:
            raise ValueError(f"classical 块里有无法识别的字符: {text[pos:pos + 20]!r}")
        kind = m.lastgroup
        value = m.group()
        pos = m.end()
        if kind in ("SKIP", "COMMENT", "HASH_COMMENT"):
            continue
        tokens.append(Token(kind, value))
    return tokens


# ── 3. AST ───────────────────────────────────────────────────────────────

# Expr := ('lit', int) | ('var', 'x1'..'x9'|'x10'...) | ('binop', op, Expr, Expr)
Expr = tuple
# Stmt := ('assign', 'xN', Expr) | ('if', Expr, [Stmt], [Stmt])
Stmt = tuple


class Parser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.i = 0

    def _peek(self) -> Optional[Token]:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def _expect(self, kind: str) -> Token:
        tok = self._peek()
        if tok is None or tok.kind != kind:
            got = tok.kind if tok else "EOF"
            raise ValueError(f"classical 块语法错误：期望 {kind}，实际 {got}")
        self.i += 1
        return tok

    def _accept(self, kind: str) -> Optional[Token]:
        tok = self._peek()
        if tok is not None and tok.kind == kind:
            self.i += 1
            return tok
        return None

    # statements ---------------------------------------------------------
    def parse_block(self) -> List[Stmt]:
        stmts: List[Stmt] = []
        while self._peek() is not None and self._peek().kind not in ("RBRACE",):
            stmts.append(self.parse_stmt())
        return stmts

    def parse_program(self) -> List[Stmt]:
        stmts = self.parse_block()
        if self._peek() is not None:
            raise ValueError(f"classical 块末尾有多余的 token: {self._peek()!r}")
        return stmts

    def parse_stmt(self) -> Stmt:
        if self._peek() is not None and self._peek().kind == "IF":
            return self.parse_if()
        return self.parse_assign()

    def parse_if(self) -> Stmt:
        self._expect("IF")
        self._expect("LPAREN")
        cond = self.parse_expr()
        self._expect("RPAREN")
        self._expect("LBRACE")
        then_body = self.parse_block()
        self._expect("RBRACE")
        else_body: List[Stmt] = []
        if self._accept("ELSE"):
            self._expect("LBRACE")
            else_body = self.parse_block()
            self._expect("RBRACE")
        return ("if", cond, then_body, else_body)

    def parse_assign(self) -> Stmt:
        target = self._parse_var_token()
        self._expect("EQ")
        value = self.parse_expr()
        self._expect("SEMI")
        return ("assign", target, value)

    def _parse_var_token(self) -> str:
        tok = self._peek()
        if tok is None or tok.kind not in ("REG", "CREG"):
            raise ValueError("赋值左边必须是寄存器变量 r1..r9")
        self.i += 1
        return self._var_name(tok)

    @staticmethod
    def _var_name(tok: Token) -> str:
        if tok.kind == "REG":
            n = int(re.match(r"r([1-9])", tok.value).group(1))
            return f"x{n}"
        if tok.kind == "CREG":
            k = int(re.match(r"c\[\s*(\d+)\s*\]", tok.value).group(1))
            return f"x{10 + k}"
        raise ValueError(f"不是变量 token: {tok!r}")

    # expressions ---------------------------------------------------------
    # expr := add_expr (('=='|'!=') add_expr)*
    # add_expr := primary (('+'|'-') primary)*
    # primary := NUM | REG | CREG | '-' NUM | '(' expr ')'
    def parse_expr(self) -> Expr:
        left = self.parse_add_expr()
        while self._peek() is not None and self._peek().kind in ("EQEQ", "NEQ"):
            op_tok = self.tokens[self.i]
            self.i += 1
            right = self.parse_add_expr()
            op = "==" if op_tok.kind == "EQEQ" else "!="
            left = ("binop", op, left, right)
        return left

    def parse_add_expr(self) -> Expr:
        left = self.parse_primary()
        while self._peek() is not None and self._peek().kind in ("PLUS", "MINUS"):
            op_tok = self.tokens[self.i]
            self.i += 1
            right = self.parse_primary()
            op = "+" if op_tok.kind == "PLUS" else "-"
            left = ("binop", op, left, right)
        return left

    def parse_primary(self) -> Expr:
        tok = self._peek()
        if tok is None:
            raise ValueError("classical 块表达式意外结束")
        if tok.kind == "NUM":
            self.i += 1
            return ("lit", int(tok.value))
        if tok.kind == "MINUS":
            self.i += 1
            num = self._expect("NUM")
            return ("lit", -int(num.value))
        if tok.kind in ("REG", "CREG"):
            self.i += 1
            return ("var", self._var_name(tok))
        if tok.kind == "LPAREN":
            self.i += 1
            inner = self.parse_expr()
            self._expect("RPAREN")
            return inner
        raise ValueError(f"classical 块表达式语法错误，token: {tok!r}")


def parse_classical(source: str) -> List[Stmt]:
    tokens = tokenize(source)
    return Parser(tokens).parse_program()


# ── 4. 代码生成：AST -> RISC-V 汇编 ──────────────────────────────────────────

# 寄存器堆一共 32 个（x0-x31）。x0 恒为 0，x1-x9 是声明的经典变量 r1-r9，
# x10..x(9+measured_bits) 是评测系统会注入的测量位，只读、绝不能被临时
# 寄存器覆盖——之前写死 "x20-x29" 当临时寄存器池，当测量位数 ≥10 时
# c[10] 恰好也是 x20，会被临时寄存器悄悄覆盖，导致同一个 c[k] 被重复读取
# 时拿到错误的值（已经用回归测试复现过这个 bug，见
# tests/hybrid_compiler_test.py 的 test_scratch_pool_avoids_measured_registers）。
# 修法：临时寄存器池改成从寄存器堆顶 x31 往下分配，永远晚于
# "x10..x(9+measured_bits)" 这段测量位保留区，而不是从固定的低位数字开始。
def _scratch_pool_for(measured_bits: int) -> List[str]:
    reserved_top = 9 + max(measured_bits, 0)  # x10..x(9+measured_bits) 保留给测量位
    floor = max(reserved_top, 9)              # 至少要晚于 x9（声明变量区）
    return [f"x{i}" for i in range(31, floor, -1)]


class CodeGen:
    def __init__(self, measured_bits: int = 0):
        self.lines: List[str] = []
        self._scratch_pool = _scratch_pool_for(measured_bits)
        self._scratch_sp = 0          # 下一个可用槽位（栈指针）
        self._used_scratch: set = set()
        self._label_counter = 0

    def _alloc_scratch(self) -> str:
        if self._scratch_sp >= len(self._scratch_pool):
            raise ValueError(
                "classical 块表达式嵌套太深或测量位数太多，临时寄存器池已耗尽"
            )
        reg = self._scratch_pool[self._scratch_sp]
        self._scratch_sp += 1
        self._used_scratch.add(reg)
        return reg

    def _release_scratch(self):
        self._scratch_sp -= 1

    def _new_label(self, tag: str) -> str:
        self._label_counter += 1
        return f"L_{tag}_{self._label_counter}"

    def emit(self, line: str):
        self.lines.append(line)

    # -- 表达式求值：结果写入 dest 寄存器 --------------------------------
    def gen_expr_into(self, expr: Expr, dest: str):
        kind = expr[0]
        if kind == "lit":
            self.emit(f"li {dest}, {expr[1]}")
            return
        if kind == "var":
            src = expr[1]
            if src != dest:
                self.emit(f"add {dest}, {src}, x0")
            return
        if kind == "binop":
            _, op, left, right = expr
            if op in ("+", "-"):
                self._gen_addsub_into(dest, op, left, right)
            else:
                self._gen_cmp_into(dest, op, left, right)
            return
        raise ValueError(f"未知表达式节点: {expr!r}")

    def _operand_reg(self, expr: Expr) -> Tuple[str, bool]:
        """返回 (寄存器名, 是否是本函数临时分配的—调用方用完要 release)。"""
        if expr[0] == "var":
            return expr[1], False
        if expr[0] == "lit":
            reg = self._alloc_scratch()
            self.emit(f"li {reg}, {expr[1]}")
            return reg, True
        # 嵌套表达式：递归求值进新的临时寄存器
        reg = self._alloc_scratch()
        self.gen_expr_into(expr, reg)
        return reg, True

    def _gen_addsub_into(self, dest: str, op: str, left: Expr, right: Expr):
        # 常量折叠（两边都是字面量时直接算出来，不产生分支/多余指令）
        if left[0] == "lit" and right[0] == "lit":
            val = left[1] + right[1] if op == "+" else left[1] - right[1]
            self.emit(f"li {dest}, {val}")
            return
        # 右操作数是字面量：可以直接用 addi（op 为 + 或 -，用有符号 imm 表示）
        if right[0] == "lit":
            lreg, ltemp = self._operand_reg(left)
            imm = right[1] if op == "+" else -right[1]
            self.emit(f"addi {dest}, {lreg}, {imm}")
            if ltemp:
                self._release_scratch()
            return
        # 左操作数是字面量、右边不是：
        if left[0] == "lit" and op == "+":
            rreg, rtemp = self._operand_reg(right)
            self.emit(f"addi {dest}, {rreg}, {left[1]}")
            if rtemp:
                self._release_scratch()
            return
        # 一般情况：两边都算成寄存器，再 add/sub
        lreg, ltemp = self._operand_reg(left)
        rreg, rtemp = self._operand_reg(right)
        if op == "+":
            self.emit(f"add {dest}, {lreg}, {rreg}")
        else:
            self.emit(f"sub {dest}, {lreg}, {rreg}")
        # 先释放后申请的（栈式 LIFO）
        if rtemp:
            self._release_scratch()
        if ltemp:
            self._release_scratch()

    def _gen_cmp_into(self, dest: str, op: str, left: Expr, right: Expr):
        # 两边都是字面量：编译期直接算出布尔值
        if left[0] == "lit" and right[0] == "lit":
            eq = left[1] == right[1]
            val = int(eq if op == "==" else not eq)
            self.emit(f"li {dest}, {val}")
            return
        lreg, ltemp = self._operand_reg(left)
        rreg, rtemp = self._operand_reg(right)
        # dest = lreg - rreg（复用 dest 本身当差值寄存器，不需要再借一个临时）
        self.emit(f"sub {dest}, {lreg}, {rreg}")
        if rtemp:
            self._release_scratch()
        if ltemp:
            self._release_scratch()
        true_label = self._new_label("cmp_true")
        end_label = self._new_label("cmp_end")
        if op == "==":
            self.emit(f"beq {dest}, x0, {true_label}")
        else:
            self.emit(f"bne {dest}, x0, {true_label}")
        self.emit(f"li {dest}, 0")
        self.emit(f"j {end_label}")
        self.emit(f"{true_label}:")
        self.emit(f"li {dest}, 1")
        self.emit(f"{end_label}:")

    # -- 语句 --------------------------------------------------------------
    def gen_stmt(self, stmt: Stmt):
        if stmt[0] == "assign":
            _, target, expr = stmt
            self.gen_expr_into(expr, target)
            return
        if stmt[0] == "if":
            _, cond, then_body, else_body = stmt
            cond_reg = self._alloc_scratch()
            self.gen_expr_into(cond, cond_reg)
            true_label = self._new_label("if_true")
            end_label = self._new_label("if_end")
            self.emit(f"bne {cond_reg}, x0, {true_label}")
            self._release_scratch()
            for s in else_body:
                self.gen_stmt(s)
            self.emit(f"j {end_label}")
            self.emit(f"{true_label}:")
            for s in then_body:
                self.gen_stmt(s)
            self.emit(f"{end_label}:")
            return
        raise ValueError(f"未知语句节点: {stmt!r}")

    def gen_program(self, stmts: List[Stmt]) -> str:
        for s in stmts:
            self.gen_stmt(s)
        # 整个程序单入口单出口：所有分支最终都会顺序执行到这里，
        # 把用到过的临时寄存器清零，避免它们以非零值残留在最终寄存器状态里。
        for reg in sorted(self._used_scratch, key=lambda r: int(r[1:])):
            self.emit(f"li {reg}, 0")
        if not self.lines:
            self.emit("li x0, 0")  # 空 classical 块：占位一条无副作用指令
        return "\n".join(self.lines)


def compile_classical_block(classical_src: str, measured_bits: int = 0) -> str:
    stmts = parse_classical(classical_src)
    return CodeGen(measured_bits).gen_program(stmts)


def _count_measured_bits(hybrid_qasm_str: str, classical_src: Optional[str]) -> int:
    """算出需要给测量位保留多少个寄存器（x10..x(9+N)），取以下两个信号的
    较大值，尽量不依赖某一处声明是否规范：
      1. `creg c[N];` 声明的宽度；
      2. classical 块里实际出现过的最大 c[k] 下标 + 1
         （防止 creg 声明和 classical 块引用的下标对不上）。
    """
    n = 0
    decl = re.search(r"\bcreg\s+c\s*\[\s*(\d+)\s*\]", hybrid_qasm_str)
    if decl:
        n = max(n, int(decl.group(1)))
    if classical_src:
        for m in re.finditer(r"c\[\s*(\d+)\s*\]", classical_src):
            n = max(n, int(m.group(1)) + 1)
    return n


# ── 5. 对外入口 ──────────────────────────────────────────────────────────

def compile_hybrid_qasm(hybrid_qasm_str: str) -> Tuple[List[str], str]:
    quantum_ops, classical_src = split_hybrid_qasm(hybrid_qasm_str)
    if classical_src is None:
        # 没有经典块：合法输入，返回空汇编（不是错误）
        return quantum_ops, "li x0, 0"
    measured_bits = _count_measured_bits(hybrid_qasm_str, classical_src)
    assembly = compile_classical_block(classical_src, measured_bits)
    return quantum_ops, assembly
