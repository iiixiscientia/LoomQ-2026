# LoomQ 提交（starter_kit/）

这是我们队伍的正式提交。2026-08-01 题面定稿后，官方把 `starter_kit/` 定为
**构建与评测根目录**——这个目录本身就是提交内容，不再是"仓库根目录随便放一
个 submission/ 文件夹"那种结构。

## 目录结构

```text
starter_kit/
├── adapter.py                # 提交契约入口：transpile() / run() / agent_chat() / compile_hybrid()
├── submission.yaml            # 声明参赛 Level、运行时、L2 环境变量协议（l1/l2/l3 均为 true）
├── evaluator.py                 # 官方公开自测器（未改动，改了也不算数）
├── riscv_emulator.py             # L3 用的 RISC-V 模拟器（官方提供，未改动）
├── llm_client.py                  # 官方提供的 L2 传输层（无第三方依赖，未改动）
├── l2_policy.json                  # 官方机读版 L2 调用预算规则（未改动）
├── prepare_submission.py            # 官方本地提交预检脚本（未改动）
├── backend_capabilities.json/.md      # 官方后端能力表（L2 选后端唯一基准，未改动）
├── requirements.txt                    # 主环境依赖，精确锁版本
├── requirements-spinq.txt               # spinq_env/ 专用依赖（跟主环境 antlr4 版本互斥）
├── spinq_runner.py                       # 在 spinq_env/ 里跑的独立脚本，被 subprocess 调用
├── Dockerfile                             # 官方基线容器 + 建 spinq_env 的步骤
├── web_app.py                              # L2 Web 入口：零依赖单文件（绘本+两幕实验+电路实验室+自由对话）
├── evidence/README.md                      # 人工评分项申报入口（真机/L2交互/工程叙事/Bonus）
├── real_hardware/                           # 真机接入证据脚本
│   ├── run_originq_real.py / run_spinq_real.py / verify_result.py
│   └── results/                               # 跑出来的 result.json
├── src/
│   ├── ir.py / qasm_parser.py / codegen.py / reference_simulator.py / utils.py
│   ├── hybrid_compiler.py                        # L3：Hybrid-QASM classical{} -> RISC-V 编译器
│   ├── backends/                                # spinq/braket/originq 执行封装
│   └── agent/                                    # L2 Agent（agent.py / tools.py / system_prompt.py）
├── circuits/
│   ├── bell.qasm / ghz3.qasm                       # 官方公开测试电路
│   └── coverage/                                     # 12 门白名单覆盖测试电路（自己写的）
└── tests/
    ├── smoke_test.py / gate_coverage_test.py / originq_ir_roundtrip_test.py
    ├── hybrid_compiler_test.py                       # L3 穷举测试（自建，9 例）
    └── agent_smoke_test.py / agent_stress_test.py       # L2 自测
```

## 快速开始

```bash
# 0. parser + codegen 逻辑自测（不需要任何 SDK）
python3 tests/smoke_test.py

# 1. 主环境装好 braket + originq 之后，跑官方公开自测
python3 evaluator.py --target originq,braket

# 2. 另外建好 spinq_env/（见下）之后，三个平台都测
python3 evaluator.py --target spinq,originq,braket

# 3. 12 门白名单覆盖测试（自己写的，比官方公开集更细）
python3 tests/gate_coverage_test.py

# 4. L3 混合编译自测（不需要任何 SDK，纯 Python 标准库）
python3 tests/hybrid_compiler_test.py
python3 evaluator.py --level l3

# 5. L2 Web 交互入口（不需要 LLM key 也能体验前三幕，见下方「L2 智能体」）
python web_app.py
```

## 为什么 spinq 要单独一个 venv

`spinqit` 需要 `antlr4-python3-runtime==4.9.2`（旧的 ATN 序列化格式），而
`amazon-braket-default-simulator` 强制要求 `4.13.2`——这两个版本互斥，同一个
环境装不全（实测验证过：装哪个版本就是另一个报错）。解决办法是给 spinqit
单独建一个虚拟环境，`src/backends/spinq_backend.py` 通过 `subprocess` 调用
`spinq_env/` 里的 `spinq_runner.py`，用 stdin/stdout 传 JSON——跟契约里"非
Python 技术栈可以用 subprocess 调用自己的 CLI"是同一个思路，只是这里用来
解决 Python 内部的依赖冲突。

```bash
python3.10 -m venv spinq_env
spinq_env/bin/pip install -r requirements-spinq.txt
```

## L2 智能体

正式评分把 L2 客观测试的模型锁定为 DeepSeek `deepseek-v4-flash`，协议是
`openai_chat_completions`，配置**只从环境变量读取**，不能硬编码：

```bash
export LOOMQ_LLM_BASE_URL="https://api.deepseek.com"   # 本地调试用自己的 key；正式评测由组委会注入
export LOOMQ_LLM_API_KEY="<your-deepseek-key>"
export LOOMQ_LLM_MODEL="deepseek-v4-flash"
python3 tests/agent_smoke_test.py     # 照题面三个判定示例自测
python3 tests/agent_stress_test.py    # 自己设计的变体压力测试（换措辞/换约束/边界 case）
```

**架构**：`adapter.agent_chat(prompt)` → `src/agent/agent.py`，走标准 OpenAI
function calling 循环。两个工具（`src/agent/tools.py`）：
- `run_circuit`：本地精确态矢量模拟器，跟 L1 是同一份 `qasm_parser.py` +
  `reference_simulator.py`，纯 Python 无网络依赖，不占用模型调用预算。
- `find_backends`：对官方 `backend_capabilities.json` 做精确条件过滤——
  压力测试实测发现，让 LLM 自己心算"6 条记录同时满足 3 条约束"不够稳（换个
  问法就会漏看/错看），于是把过滤逻辑写成确定性 Python 代码，LLM 只需要把
  自然语言约束翻译成参数。

**预算硬约束**（`l2_policy.json`）：每个 case 最多 3 次模型调用、累计 8000
输入 / 2000 输出 token、120 秒超时。这直接决定了两个设计：
1. `src/agent/system_prompt.py` 刻意精简——system prompt 每次调用都要重发，
   3 次调用等于至少发送 3 遍，砍掉了所有非必要解释，后端能力表也不再整段
   塞进 prompt（`find_backends` 直接读官方 json，不需要在 prompt 里重复）。
2. 硬性格式规则（"最终回复必须重新贴出完整 ```qasm 代码块"）不是 100% 靠
   模型自觉遵守——`agent.py` 的 `_ensure_qasm_block()` 做了预算感知的兜底：
   调用预算还有剩余就礼貌地再问一次，预算打满就把本轮验证过的电路确定性地
   追加进最终文本，不再赌"这次模型听不听话"。

⚠️ **一个已经修过的真实 bug**：早期实现自己转录了一份后端能力数据，字段名
（`account_required`/`free_tier`/`cloud_simulator_or_qpu`）跟官方
`backend_capabilities.json`（`requires_account`/`free_quota`/`cloud`）不
一致——两份数据长得像但没对照过。现在 `find_backends` 直接读官方文件，不再
自己维护副本。

## L3 混合编译（Hybrid-QASM -> RISC-V）

```bash
python3 tests/hybrid_compiler_test.py   # 9 个自建用例，穷举所有测量值组合
python3 evaluator.py --level l3          # 官方公开自测（1 例）
```

**架构**：`adapter.compile_hybrid(hybrid_qasm_str)` → `src/hybrid_compiler.py`。
`split_hybrid_qasm()` 用花括号配对（而不是找第一个 `}`）把 `classical{}` 块
从源码里切出来，块外的量子指令按原始顺序原样返回；块内文本经手写 tokenizer
+ 递归下降 parser 生成 AST（支持 if/else 嵌套、+ - == != 、括号），再由
`CodeGen` 生成 RISC-V 汇编：`r1..r9 -> x1..x9`，`c[k] -> x(10+k)`。

⚠️ **一个已经修过的真实 bug**：临时寄存器池最初写死用 `x20-x29`，当电路测量
位数 ≥10 个时 `c[10]` 换算下来正好也是 `x20`，同一个 `c[10]` 被读两次会被
第一次比较悄悄覆盖掉。已经用 12 测量位、`c[10]` 重复读取的用例复现并修复——
临时寄存器改成根据实际 `creg` 大小动态从寄存器堆顶 `x31` 往下分配，永远
避开变量区（`x1-x9`）和测量位区（`x10..x(9+N)`）。见
`tests/hybrid_compiler_test.py::test_scratch_pool_avoids_measured_registers`。

另外手册给出的 Hybrid-QASM 示例里，`classical{}` 内部写了 `//` 行注释（纯粹
给人类读者看的），tokenizer 和花括号配对都做了防御性的注释跳过，不管隐藏
用例最终带不带注释都能编译。

## 真机接入证据

```bash
export ORIGINQ_API_TOKEN="..."          # https://qcloud.originqc.com.cn/ 工作台获取
python3 real_hardware/run_originq_real.py circuits/bell.qasm --shots 1000 \
    --out real_hardware/results/originq_bell.json

export SPINQ_CLOUD_USERNAME="..."       # https://cloud.spinq.cn 注册，SSH 公钥认证
export SPINQ_CLOUD_KEYFILE="/path/to/.ssh/id_rsa"
spinq_env/bin/python3 real_hardware/run_spinq_real.py circuits/bell.qasm --shots 1000 \
    --platform gemini_vp \
    --out real_hardware/results/spinq_bell.json

python3 real_hardware/verify_result.py real_hardware/results/*.json
```

跟 `adapter.run()` 是两条独立路径——L1 正式评测默认禁止网络，`run()` 必须
离线可跑；真机证据是单独提交给评委核对 `job_id` 的文件。申报真机人工分要
填 `evidence/README.md`。

**已实测确认的坑**：spinq 云端不接受电路里显式的 measure 门（脚本自动去
掉）；spinq 本地/真机 counts 位序跟大赛约定相反，脚本已加 `key[::-1]`
反转，originq 本地模拟器不需要反转；spinq 的 `job_id` 从 SDK 打印文字里
正则截获；真机偶发"忙/维护中"不是代码问题，换平台或重试即可。

## 最终提交流程

```bash
python3 prepare_submission.py --team-id <你的 GitHub 用户名>
```

通过后按输出提示，在 `QAIDAO/LoomQ-2026` 开"LoomQ 最终提交" Issue，填 fork
地址和 40 位 commit SHA。截止时间 **2026-08-25 12:00 UTC+8**，以 Issue 创建
时间为准，不是 commit 时间；更新代码后要重新开 Issue，截止前最后一次通过
校验的提交生效。
