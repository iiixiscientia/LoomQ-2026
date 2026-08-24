# 自定义量子 RISC-V 扩展指令集（Bonus）

三份材料按赛题手册要求配齐：

1. **指令编码规格文档**：本文件。
2. **模拟器扩展实现**：`src/quantum_riscv_emulator.py`（fork 自官方
   `riscv_emulator.py`，独立文件，官方那份未做任何改动）。
3. **端到端测试**：`tests/quantum_riscv_test.py`。

## 设计目标

`riscv_emulator.py`（L3 用，官方提供）只认识纯经典指令。这个扩展给它加一套
"量子指令"，量子测量的结果**直接写进同一份经典寄存器堆**，所以经典的
`beq`/`bne`/`j` 可以在程序运行过程中，对着刚刚测量出来的量子结果做分支——
量子门和经典控制流是真正交替执行的，不是"先算完量子部分再套经典部分"。这跟
L3 的 `compile_hybrid`（编译期就知道 classical 块要读的是"已经测量好"的
输入）是互补的两个层次：L3 是"电路描述语言 -> 经典汇编"的编译器，这个 Bonus
是"给经典 ISA 本身加量子指令"，量子部分直接在同一个执行流里跑。

## 编码格式

复用标准 RISC-V R-type 指令的字段切法（不是随便发明的位布局，是官方手册规定
的 32 位指令通用切法），opcode 固定使用 RISC-V 指令集手册第 **Chapter
"RV32/64G Instruction Set Listings"** 里明确保留给"custom-0"扩展、允许厂商/
研究者自定义语义的操作码 `0001011`（十进制 11）——不会跟任何标准整数/浮点/
压缩指令冲突。

```
位:     31 ────────── 25  24 ──── 20  19 ──── 15  14 ── 12  11 ───── 7  6 ────── 0
字段:      funct7          rs2         rs1       funct3     rd         opcode
宽度:        7               5           5          3         5          7
```

`opcode` 恒为 `0001011`。`funct3` 决定这是哪一类量子指令：

| funct3 | 类别        | 语义                                                             |
|--------|-------------|------------------------------------------------------------------|
| `000`  | `QINIT`     | `rs1` = 量子位数 n（0-31），(重新)初始化 n 比特寄存器为 \|0...0⟩ |
| `001`  | `QGATE1`    | `rs1` = 目标量子位；`funct7` 低 3 位 = 门 id（见下表）            |
| `010`  | `QGATE2`    | `rs1`/`rs2` = 两个量子位；`funct7` 低 2 位 = 门 id（见下表）      |
| `011`  | `QGATE3`    | `rs1`/`rs2` = 两个控制位，`rd` = 目标位（唯一门：`ccx`）          |
| `100`  | `QMEASURE`  | `rs1` = 量子位，`rd` = 目标经典寄存器（0-31，直接对应 x0-x31）    |

`QGATE1` 门 id（`funct7` 低 3 位）：

| id | 门     | 矩阵来源                                   |
|----|--------|---------------------------------------------|
| 0  | `qh`   | `src/reference_simulator.py::_GATE_MATRICES['h']`   |
| 1  | `qx`   | `_GATE_MATRICES['x']`                        |
| 2  | `qs`   | `_GATE_MATRICES['s']`                        |
| 3  | `qsdg` | `_GATE_MATRICES['sdg']`                      |
| 4  | `qt`   | `_GATE_MATRICES['t']`                        |
| 5  | `qtdg` | `_GATE_MATRICES['tdg']`                      |

`QGATE2` 门 id（`funct7` 低 2 位）：

| id | 门      | 语义                     |
|----|---------|--------------------------|
| 0  | `qcx`   | CNOT（`rs1`=控制，`rs2`=目标）|
| 1  | `qswap` | 交换 `rs1`/`rs2` 两个量子位  |

## 已知取舍：参数门不进二进制编码

`rz(θ)`/`ry(θ)`/`cu1(θ)` 需要一个连续取值的浮点角度，`funct7` 只有 7 位，
塞不下任意精度的浮点数（这不是"忘了处理"，是明确评估后的取舍）。这三个门
**不在这次的二进制编码范围内**——量子门集合限定在无参的 6 个单比特门
（h/x/s/sdg/t/tdg）+ 2 个两比特门（cx/swap）+ 1 个三比特门（ccx）+
`qinit`/`qmeasure`，共 11 类可编码指令，`tests/quantum_riscv_test.py` 对
每一类都做了编码 → 解码往返断言。真实 ISA 遇到"立即数放不下"这种情况通常也是
换一条路径（例如从常量表/寄存器取值），不会为了凑单指令硬编码近似值，这里
选择直接不纳入二进制范围，是同一种工程判断。

## 文本汇编形式

模拟器的 `load_program()` 走的是跟官方 `riscv_emulator.py` 相同的纯文本行式
汇编（助记符 + 逗号分隔参数），额外认识下面这些量子助记符（跟上面的编码
字段一一对应，`assemble_line()` 就是这套文本到编码参数字典的转换器）：

```text
qinit <n>                  # 初始化 n 比特量子寄存器
qh q<i> / qx q<i> / qs q<i> / qsdg q<i> / qt q<i> / qtdg q<i>
qcx q<i>,q<j> / qswap q<i>,q<j>
qccx q<i>,q<j>,q<k>        # c1=i, c2=j, target=k
qmeasure q<i>, x<r>        # 测量量子位 i，坍缩，结果写入经典寄存器 x<r>
```

测量结果写进的是跟 `li/add/sub/addi/beq/bne/j` **同一份** `self.registers`
数组（`x0` 恒为 0 这条规则原样保留），所以可以紧接着用官方语法做经典分支：

```text
qinit 1
qx q0                  # 制备 |1>
qmeasure q0, x5        # 测量结果写进 x5（这里必然是 1）
beq x5, x0, WAS_ZERO
li x1, 999              # 走这条分支
j END
WAS_ZERO:
li x1, -1
END:
```

## 二进制编码入口

`encode_instruction(mnemonic, args) -> int`（32 位无符号整数）和
`decode_instruction(word) -> (mnemonic, args)` 严格互逆。
`QuantumRISCVEmulator.load_encoded_quantum_words(words)` 把一串编码字直接
解码执行，不经过文本汇编这一步，用来证明二进制编码本身是可独立执行的规格，
不是只停留在文本层面的装饰。
