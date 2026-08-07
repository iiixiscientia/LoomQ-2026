# LoomQ 提交仓库（开发中）

这是我们队伍自己的提交仓库草稿，基于 `../starter-kit`（v1.0.0）复制出的骨架构建。
`../`（LoomQ-2026 官方发布包）保持原样不动，方便随时 `git pull` 拉官方更新；
所有队伍自己的代码都在这个 `submission/` 目录里，将来单独 `git init` 成一个仓库提交。

## 目录结构

```text
submission/
├── adapter.py              # 提交契约入口：transpile() / run() / agent_chat() / compile_hybrid()
├── submission.yaml          # 声明参赛 Level、运行时
├── evaluator.py              # 官方公开自测器（不要改动逻辑，改了也不算数）
├── riscv_emulator.py          # L3 用的 RISC-V 模拟器（官方提供）
├── requirements.txt            # 主环境依赖（braket + originq），精确锁版本
├── requirements-spinq.txt       # spinq_env/ 专用依赖（跟主环境的 antlr4 版本互斥，见下）
├── spinq_runner.py                # 在 spinq_env/ 里跑的独立脚本，被 subprocess 调用
├── Dockerfile                      # 官方基线容器（已加了建 spinq_env 的步骤）
├── real_hardware/                   # 真机接入证据脚本，独立于 adapter.py（见下）
│   ├── run_originq_real.py
│   ├── run_spinq_real.py
│   └── results/                       # 跑出来的 result.json 放这里，提交时一起交
├── src/
│   ├── ir.py                       # 抽象 IR：Instruction / Circuit
│   ├── qasm_parser.py               # OpenQASM2.0 解析器（12 门白名单）
│   ├── codegen.py                    # IR -> 三个后端的原生格式文本
│   ├── reference_simulator.py         # 纯 Python 态矢量模拟器，算理想分布用
│   ├── utils.py                       # 公共小工具（时间戳等）
│   └── backends/
│       ├── spinq_backend.py            # subprocess 调用 spinq_env/ + spinq_runner.py
│       ├── braket_backend.py            # AWS Braket LocalSimulator 执行封装
│       └── originq_backend.py            # 本源 pyqpanda 执行封装
├── circuits/
│   ├── bell.qasm / ghz3.qasm           # 官方公开测试电路
│   └── coverage/                        # 12 门白名单覆盖测试电路（自己写的）
└── tests/
    ├── smoke_test.py                      # 不需要装 SDK 就能跑的 parser/codegen 自测
    └── gate_coverage_test.py                # 三后端对比参考模拟器算出的理想分布
```

## 快速开始

```bash
# 0. parser + codegen 逻辑自测（不需要任何 SDK）
python3 tests/smoke_test.py

# 1. 主环境装好 braket + originq 之后，跑官方公开自测（拿到入门档评奖资格线要求的门槛）
python3 evaluator.py --target originq,braket

# 2. 另外建好 spinq_env/（见下面"为什么 spinq 要单独一个 venv"）之后，三个平台都测
python3 evaluator.py --target spinq,originq,braket
```

详细的环境搭建步骤见仓库根目录的 `../SETUP_GUIDE.md`。

## 为什么 spinq 要单独一个 venv

`spinqit` 需要 `antlr4-python3-runtime==4.9.2`（旧的 ATN 序列化格式），而
`amazon-braket-default-simulator` 强制要求 `4.13.2`——这两个版本互斥，同一个
环境装不全（实测验证过：装哪个版本就是另一个报错）。解决办法是给 spinqit
单独建一个虚拟环境，`src/backends/spinq_backend.py` 通过 `subprocess` 调用
`spinq_env/` 里的 `spinq_runner.py`，用 stdin/stdout 传 JSON——跟契约里"非
Python 技术栈可以用 subprocess 调用自己的 CLI"是同一个思路，只是这里用来
解决 Python 内部的依赖冲突。

建 spinq_env（本地开发和提交前 Docker 验证都要做，Dockerfile 已经内置了这
一步）：

```bash
python3.10 -m venv spinq_env
spinq_env/bin/pip install -r requirements-spinq.txt
```

## 12 门白名单覆盖测试

```bash
python3 tests/gate_coverage_test.py               # 三平台全测
python3 tests/gate_coverage_test.py --target braket  # 只测一个
```

用 `src/reference_simulator.py`（纯 Python 态矢量模拟器，跟三个真实后端
完全独立）算出每个测试电路的理想分布做 ground truth，而不是三后端互相比——
互相比只能测出"一致"，测不出"三个都错但错得一样"。这个模拟器算出来的
Bell/GHZ 分布跟官方 `evaluator.py` 里硬编码的 `PUBLIC_DISTRIBUTIONS`
完全一致，作为它本身正确性的交叉验证。

已知限制：`s`/`sdg` 和 `t`/`tdg` 这两对门只用 Z 基测量的话，理论上测不出
符号差异（`cosθ` 是偶函数），`circuits/coverage/` 里对应的测试电路只能验证
"相位大小对不对"，验证不了"符号对不对"。这是信息论上的限制，不是测试没写
好；真要测符号需要额外做 Y 基测量，工作量换来的收益不高，先不做。

**组合电路测试**（`ghz5.qasm` / `qft4_roundtrip.qasm` / `grover3.qasm`）：
上面那些都是孤立单门测试，测不出"门与门组合"的 bug（寄存器索引、编排顺序、
分解链路叠加误差）——而官方隐藏电路集里的 `GHZ-5`/`QFT-4`/`Grover-3` 正好
是这类结构。这三个是自己按标准构造写的，用来在提交前压一下这类风险：
- `ghz5.qasm`：5 比特寄存器，测大寄存器索引有没有问题。
- `qft4_roundtrip.qasm`：正向 QFT 接反向 QFT，应该精确复原成输入态
  （概率 1.0）——直接测 QFT 对全零输入是测不出 CU1 相位符号错误的（Z 基
  测量看不见相位，推导过程见 git log），往返测试才是真正敏感的验证。
- `grover3.qasm`：标记 `|101⟩`，2 次迭代（N=8 的最优次数），主峰理论概率
  94.5%，用 CCX 三明治（`H;CCX;H`）实现 CCZ 做 oracle/diffusion——这是
  唯一一个在真实叠加态下测 CCX 干涉的电路，之前的 `ccx_both_on`/`ccx_one_on`
  测的都是经典确定态，测不出这个。

## L2 智能体

```bash
export ANTHROPIC_API_KEY="sk-ant-..."     # 不要提交进 Git
python3 tests/agent_smoke_test.py           # 照题面三个判定用例自测
```

架构：`adapter.agent_chat(prompt)` -> `src/agent/agent.py` 的工具调用循环
（Anthropic tool-use）。只给了一个工具 `run_circuit`（`src/agent/tools.py`），
不按"生成/纠错/选后端"拆成三个专门工具——评测用未公开的 prompt 变体，靠
关键词分发到硬编码分支这个思路本身就是题面明确要避免的；让 LLM 自己判断
当前该做什么，反复调用同一个自验工具，比我们替它做判断更扛得住变体。

`run_circuit` 内部就是 `src/qasm_parser.py` + `src/reference_simulator.py`——
跟 L1 是同一份代码，不是另起一套。选它而不是走某个真实 SDK 后端：纯 Python
标准库，不依赖网络/子进程，L2 的稳定性不会被 L1 某个后端的偶发问题拖累；
无噪声精确分布，LLM 自验时不会被采样涨落干扰判断。

后端选型的知识库是 `data/backend_capabilities.json`——starter-kit 只给了
`backend_capabilities.md` 表格没给机读版（可能是发布包漏了），这份是照着
表格逐字转录的，直接嵌进 system prompt（`src/agent/system_prompt.py`），
不靠模型背答案。

⚠️ 还没跟真实 API 联调过（API key 还没申请下来）：工具调用循环是照着
Anthropic 官方文档标准模式写的，逻辑本身（`run_circuit` 工具、system
prompt 内容）已经在沙盒里独立验证过，但真正接上 API 之后的端到端效果、
以及不同 `anthropic` SDK 版本可能存在的字段名差异，需要拿到 key 之后跑一次
`tests/agent_smoke_test.py` 确认。

## 真机接入证据

```bash
export ORIGINQ_API_TOKEN="..."          # https://qcloud.originqc.com.cn/ 工作台获取
python3 real_hardware/run_originq_real.py circuits/bell.qasm --shots 1000 \
    --out real_hardware/results/originq_bell.json

export SPINQ_CLOUD_USERNAME="..."       # https://cloud.spinq.cn 注册，SSH 公钥认证
export SPINQ_CLOUD_KEYFILE="/path/to/.ssh/id_rsa"
# ⚠️ spinq 的真机脚本必须用 spinq_env 自己的解释器跑（跟主 venv 的
# antlr4 版本冲突，见 real_hardware/run_spinq_real.py 头部注释）：
spinq_env/bin/python3 real_hardware/run_spinq_real.py circuits/bell.qasm --shots 1000 \
    --platform gemini_vp \
    --out real_hardware/results/spinq_bell.json

# 拿到 result.json 之后，用这个脚本核对"主峰命中"（评分表对真机的判定标准）：
python3 real_hardware/verify_result.py real_hardware/results/*.json
```

跟 `adapter.run()` 是两条独立路径——契约要求 L1 正式评测默认禁止网络，
`run()` 必须离线可跑；真机证据是单独提交给评委核对 `job_id` 的文件，不经过
`evaluator.py`。

**已实测确认的坑（两个平台都踩过一遍了）**：
- spinq 云端**不接受电路里显式的 measure 门**，脚本会在编译前自动去掉
  （只对全比特测量、顺序对应的电路安全，我们所有测试电路都是这个模式）。
- spinq 本地模拟器和真机的 counts 位序都跟大赛约定相反，脚本里已经加了
  `key[::-1]` 反转（用 `swap_basic.qasm` 这种非对称电路测出来的，Bell/GHZ
  这种对称电路测不出方向）；originq 本地模拟器实测**不需要**反转。
- spinq 的 `job_id` 从 SDK 提交时打印的 "Task xxx has been submitted" 这行
  文字里截获，`res` 对象本身不带 id 属性。
- 真机是共享资源，`platform.available()` 可能返回 False（真机忙/离线），
  也可能报 "under maintenance"（服务端维护）——都不是代码问题，换个平台试
  或者等一会儿重试即可。
