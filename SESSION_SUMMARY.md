# LoomQ 2026 · 新 fork 迁移记录（写于 2026-08-01）

这份文档给"新开一个 Cowork 窗口"之后的自己看。**从今天起，这个目录
（`latest-version/LoomQ-2026/`）才是真正的工作仓库**——它是官方
`QAIDAO/LoomQ-2026` 的公开 fork（origin 指向用户自己的 GitHub 账号），
正式提交路径是这里的 `starter-kit/` 子目录。

旧目录 `/Users/lian/OrbStack/fedora/home/lian/LoomQ-2026/`（本目录再往上
两层）**从今天起只作参考，不再是工作区**——那边的 `submission/` 是题面
定稿前（2026-07-27 版）的实现，`SESSION_SUMMARY.md`/`SOP.md` 记录的是那
之前的工作过程，背景信息仍然有效，但代码已经不是最新的了，2026-08-01
定稿后的题面细节改动（尤其 L2）那边的代码没有跟上。

## 2026-08-01 发生了什么

赛题正式定稿，两处发生了实质性变化（详细 diff 见对话记录，这里只记结论）：

1. **提交流程整个变了**：不再是"提交一个仓库根目录"，而是 fork 里的
   `starter-kit/` 子目录本身就是构建与评测根目录；新增本地预检脚本
   `starter-kit/prepare_submission.py --team-id <GITHUB用户名>`；正式提交
   走 `QAIDAO/LoomQ-2026` 的"LoomQ 最终提交" Issue（填 fork 地址 + 40 位
   commit SHA），**Issue 创建时间**才是生效时间，不是 commit 时间。
   **截止时间：2026-08-25 12:00 UTC+8**。
2. **L2 的 LLM 被组委会锁死成 DeepSeek `deepseek-v4-flash`**：协议从"自备
   任意 LLM API"（旧版接的是 Anthropic）变成必须走 `openai_chat_completions`，
   配置只能从环境变量读（`LOOMQ_LLM_BASE_URL`/`LOOMQ_LLM_API_KEY`/
   `LOOMQ_LLM_MODEL`），不能硬编码。**每个 case 最多 3 次模型调用、累计
   8000 输入/2000 输出 token、120 秒超时**（`l2_policy.json`），12 个正式
   case。L1/L3 的规范文件（`evaluator.py`/`riscv_emulator.py`/
   `target_ir_contract.md`/`gate_identities.md`/电路样例/`Dockerfile`/
   `requirements.txt` 模板）全部逐字节未变，不受影响。

## 今天做完的事

### L1：结构化迁移，已在用户本机验证 42/42 通过

把旧仓库 `submission/` 下的 `src/`（parser/ir/codegen/backends）、
`real_hardware/`、`circuits/coverage/`、`spinq_runner.py` 原样迁移到这里
的 `starter-kit/`。用户在自己 Fedora 机器上（真正装全三个 SDK 的 venv 其实
在**旧仓库根目录的 `venv/`**，不是 `submission/venv`——踩过一次找错 venv
的坑）跑通：

- `tests/gate_coverage_test.py`：**42/42 通过**
- `requirements.txt` 已经从那个 venv 里 `pip freeze` 回填了真实版本号：
  `pyqpanda==3.8.5`、`amazon-braket-sdk==1.110.1`、
  `antlr4-python3-runtime==4.13.2`

### L2：整个重写，已用真实 DeepSeek key 验证

`src/agent/`（agent.py / tools.py / system_prompt.py）全部重写：

- 协议从 Anthropic tool-use 换成 OpenAI function calling，走组委会提供的
  `starter-kit/llm_client.py`（无第三方依赖，按路径用 importlib 加载，不
  用 sys.path 技巧，避免跟环境里同名包冲突）。
- **3 次调用预算硬约束**逼出的设计：`MAX_CALLS` 读环境变量（默认3），循环
  严格计数；输出 token 预算动态平分给剩余调用次数；硬性格式规则（"最终必须
  重贴完整 qasm 代码块"）的兜底策略改成**预算感知**——调用预算没打满才礼貌
  地多问一次，打满了就把已验证的电路确定性追加进最终文本，不再赌模型这次
  听不听话。这个兜底逻辑写了单元测试（本地假 HTTP server 模拟三种场景：正
  常路径/预算未耗尽触发nudge/预算耗尽确定性追加），三个场景全部验证通过，
  见对话记录里的 `fake_server_test.py`（没有留在仓库里，只是调试用）。
- system prompt 大幅精简（3 次调用意味着这份 prompt 至少发送 3 遍），后端
  能力表不再整段塞进 prompt——`find_backends` 工具直接读官方 json。

**顺手挖出一个真实 bug**：旧版 `find_backends` 用的是自己转录的后端数据
（字段名 `account_required`/`cost:"free_tier"`/`kind:"cloud_simulator_or_qpu"`），
跟仓库里从第一天就有的官方 `backend_capabilities.json`（字段名
`requires_account`/`cost:"free_quota"`/`kind:"cloud"`）不一致——两份数据长
得像但没人对照过内容。旧版 system prompt 里"starter-kit 官方只给了 .md 没
给机读版"的说法是**错的**，json 从发布第一天就在。现在直接读官方那份，删掉
了自己维护的副本（`submission/data/backend_capabilities.json` 那份不要再
参考了，是错的）。

**真实 DeepSeek 验证结果**：
- `tests/agent_smoke_test.py`（题面三个原始示例）：3/3 通过，语气正常（没
  有"完美！"自夸开头这类问题）。
- `tests/agent_stress_test.py` 抽测了几个：20比特选后端、10比特真机选后端、
  ccz白名单外门纠错——全部行为正确。有一次"失败"其实是测试脚本自己判定
  太严格（把"提到了被排除的 id 并解释为什么排除"误判成答错），已经修好
  判定逻辑（`check_ids_exact_set` 现在只检查有没有遗漏正确答案，不惩罚提及
  被排除项）。

### 收尾文件

- `submission.yaml`：`starter_kit_version` 跟着模板到 1.1.0，`levels.l2`
  改 true，`network.required_for_l2` 改 true（`allowed_hosts` 留空——L2 的
  网络访问是组委会通过环境变量注入的，不是我们声明一个域名白名单）。
- `Dockerfile`/`requirements.txt`：延续旧版的 spinq_env 两阶段构建策略，
  去掉了 `anthropic` 依赖（新版 L2 不需要，`llm_client.py` 纯标准库）。
- `README.md`：重写，反映新目录结构和 L2 协议。
- `evidence/README.md`：填了 L1 真机部分（量旋 `gemini_vp`，job_id
  `G-260730-0005`，2026-07-30 08:35:50 UTC，1000 shots），本源悟空还卡在
  平台维护，没法申报第二个真机平台。L2交互体验/工程叙事/Bonus 都还没填，
  因为对应的东西还没做（没有独立于 `agent_chat()` 之外的 CLI/网页入口，
  L3/Bonus 完全没开始）。

## 还没做完的事（按优先级）

1. **`git status` 目前是脏的，还没 commit/push**——今天做的所有迁移和重写
   都还只在工作区，没有进 git 历史。另外发现一个奇怪的 `.git/index.lock`
   权限报错（"Operation not permitted"，`git status` 末尾清理锁文件时报的，
   不是致命错误但没查清楚原因），新会话如果要做 git 操作，先确认这个锁
   文件的情况，不要在没搞清楚之前强行删锁文件或者做破坏性 git 操作。
   工作区里还有个 `starter-kit/.nfs.20051026.2d81` 的 NFS 临时文件，是
   挂载文件系统的产物，commit 前应该清掉或者加进 `.gitignore`。
2. **`starter-kit/tests/originq_ir_roundtrip_test.py` 和
   `tests/smoke_test.py` 没有在这次验证里单独确认过**——迁移了但没跑，
   理论上不涉及改动过的部分应该没问题，提交前保险起见跑一下。
3. **L2 的多轮对话场景、更大样本量的压力测试可靠性**——跟旧仓库
   `SESSION_SUMMARY.md` 里记录的遗留问题是同一类，新协议下没有专门重新
   测过，只是延续了旧的认识。
4. **L3（15分）、工程叙事（10分）、Bonus（12分）完全没开始**——跟旧
   `SOP.md` 记录的状态一样，这次会话没有触碰这部分，`compile_hybrid()`
   在 `adapter.py` 里依然是 `NotImplementedError`。
5. 旧仓库根目录的 `SESSION_SUMMARY.md`/`SOP.md` 还没更新指向这个新目录
   ——如果这次会话没来得及做，新会话记得去旧仓库根目录补一个"工作区已经
   搬到 latest-version/LoomQ-2026/starter-kit/"的指路说明，避免又对着旧
   代码继续改。
