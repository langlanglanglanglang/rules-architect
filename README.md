# rules-architect

**中文** | [English](README.en.md)

> 另见：[与官方 claude-md-improver 的对比](docs/comparison-vs-claude-md-improver.md)

**一键装**：`curl -fsSL https://raw.githubusercontent.com/langlanglanglanglang/rules-architect/main/bootstrap.sh | bash` — 安装时可勾选 Claude Code、Codex 或两者，详见[一键安装](#一键安装)。

> Claude Code **及 Codex CLI** 的自我改进规则架构。安装 3 个核心 hook + 1 个 path-scoped rule，让规则归位变可靠，不再依赖 CLAUDE.md 的注意力。（Codex 一等公民支持见 [codex 支持](#codex-支持一等公民) 节。）

默认运行还会生成一份**只读规则分布建议**：按 Claude/Codex 的加载规则扫描当前项目候选来源中的
memory、CLAUDE、AGENTS、路径规则和已注册 Hook，按 Hook 强制规则 / 路径规则 /
团队基线 / 个人记忆 / 团队经验五组展示。报告不会自动迁移或覆盖规则。

## 安装包含什么

| 组件 | 用途 | 通用？ |
|---|---|---|
| 3 个核心 hook | SOP 注入 + 基础设施（memory_intake / rule_intake / cleanup） | ✅ 通用 |
| 1 个 path-scoped rule (`rule-intake.md`) | 编辑规则文件时注入 SOP | ✅ |
| 只读分布报告工具 | 扫描候选、校验分类、渲染五组建议 | ✅ |
| `CLAUDE-personal.md` §六 模板 | 升级 / 退役 / 团队同步 流程 | ✅ |
| `memory_sync.py` | 推送 memory → 团队 lessons（单向） | ✅ 参数化 |
| `examples/` | 项目特定规则示例（仅参考） | 不会安装 |

## 为什么需要它

CC 默认行为：所有细节都被塞进 **L1 memory**，因为它最方便。结果：
- memory 被本该放别处的规则塞爆
- 团队看不到你的 memory（用户私有）
- 长会话中 CLAUDE.md 被稀释
- 适合做 hook 的规则被留在 memory，反复忘掉

这套 skill 提供 **3 层规则写入瞬间的实时拦截**。


## 设计哲学：通用 vs 个人偏好

本 skill **只默认装 3 个核心 hook**，编码的是 skill 方法论（5 问 SOP 注入 + 基础设施），**不**编码个人工作流偏好。个人工作流 hook（如 `error_recovery_checkpoint` / `dangerous_branch_reminder`）放在 `examples/`，需要时 fork + 改。

**通用（默认装）**：
- `memory_intake_check.py` — 拦截 memory 写入，注入 5 问 SOP
- `rule_intake_reminder.py` — 拦截用户规则关键词，注入 5 问 SOP
- `cleanup_hook.py` — SessionStart 清理（lock TTL + audit 轮转）

**个人偏好（在 `examples/`，按需 fork）**：
- `error_recovery_checkpoint.py.example` — tool 错误时强制三行汇报
- `dangerous_branch_reminder.py.example` — `git checkout <受保护分支>` 提醒
- `mr_created_reminder.py.example` — codeup MCP MR 创建时输出汇总
- `extension-hook-skeleton.py` — 自定义 hook 起步模板

把你**自己已有**的 memory 规则升级到 hook，由 `install_hooks.py` 装好核心 3 hook 后的交互流程处理。

## 一键安装

```bash
curl -fsSL https://raw.githubusercontent.com/langlanglanglanglang/rules-architect/main/bootstrap.sh | bash
```

交互安装会让你选择：

```text
请选择安装目标（可多选）：
  [ ] 1. Claude Code（Skill + Hook）
  [ ] 2. Codex（Skill + Hook）
输入 1、2 或 1,2 [默认 1,2]：
```

安装器只保留一份仓库，并为所选平台创建 Skill 发现入口：

- Claude Code：`~/.claude/skills/rules-architect`
- Codex：`~/.agents/skills/rules-architect`

默认 mode B 同时安装所选平台的 3 个核心 Hook。无 TTY 时默认安装两者；
CI 可用 `--platforms` 明确指定。

更多控制：
```bash
# 非交互安装 Claude + Codex Skill 和 Hook
curl -fsSL https://raw.githubusercontent.com/langlanglanglanglang/rules-architect/main/bootstrap.sh | \
  bash -s -- --platforms claude,codex --non-interactive

# 只安装 Codex
curl -fsSL https://raw.githubusercontent.com/langlanglanglanglang/rules-architect/main/bootstrap.sh | \
  bash -s -- --platforms codex

# 仅诊断：临时 checkout，结束后清理，不安装 Skill/Hook/规则
curl -fsSL https://raw.githubusercontent.com/langlanglanglanglang/rules-architect/main/bootstrap.sh | bash -s -- --mode D

# 全装（hook + rule-intake + §六）
curl -fsSL https://raw.githubusercontent.com/langlanglanglanglang/rules-architect/main/bootstrap.sh | bash -s -- --mode A

# 自定义安装位置
curl -fsSL https://raw.githubusercontent.com/langlanglanglanglang/rules-architect/main/bootstrap.sh | bash -s -- --install-dir ~/workspace/rules-architect

# 指定 tag 版本
curl -fsSL https://raw.githubusercontent.com/langlanglanglanglang/rules-architect/main/bootstrap.sh | bash -s -- --tag v2.5.0
```

### 或者手动装 Claude Code（更透明）
```bash
git clone https://github.com/langlanglanglanglang/rules-architect.git ~/.claude/skills/rules-architect
python3 ~/.claude/skills/rules-architect/scripts/install_hooks.py
```

## 要求

- **Claude Code >= 1.5.0**（依赖 UserPromptSubmit hook）
- Python 3.7+
- macOS / Linux 完整支持；Windows 部分支持（见跨平台节）

## 5 分钟上手

```bash
# 1a. Claude Code 中触发
/rules-architect

# 1b. Codex 中触发
$rules-architect

# 2. 默认先看只读规则分布报告——不动任何规则文件

# 3. 看懂 5 层模型 + SOP 后：
#    明确要求安装并选择 mode A（全装）或 B / C（部分装）
```

### 只读规则分布报告

在 Claude Code 运行 `/rules-architect`，或在 Codex 运行
`$rules-architect`（也可从 `/skills` 选择）时，主代理默认：

1. 用 `scripts/rule_inventory.py` 建立当前项目候选清单
2. 同时扫描已注册、孤立、失效和本地修改过的 Hook，并识别所有权
3. 对每条候选选择唯一正文、加载适配器和 enforcement 模式
4. 先完成冲突与低置信度项的前置确认，再给出新增、复用、修改、禁用、删除或保留结论
5. 用 `recommendation_contract.py` 校验没有漏项、越权修改或旧报告
6. 用 `render_distribution.py` 输出五组建议和 Hook 实际状态

遇到冲突、低置信度或外部产物语义不明确时，会先集中询问用户。确认完成前不会
生成最终推荐或写操作；最终推荐中不会再出现“复核”，只保留已经确定的创建、
复用、迁移、修改、禁用、删除和保留动作。

对用户来说入口仍然只有一次 Skill 调用。语义分类由当前会话的主代理
完成；Python 工具只负责确定性扫描、校验和渲染，不声称能够脱离模型独立
理解规则。

Hook 会明确标注“阻断”（`block`）或“提醒”（`remind`）。
只有动作发生前能够确定性验证并阻断的 Hook 才会标成强制；现有
`additionalContext` Hook 属于提醒。

重复运行是预期用法：第一次通常以“创建”为主；之后会根据实际文件、Manifest
所有权和上次状态收敛为增删改建议。其他工具或用户创建的 Hook 会被纳入比较，
但不会自动改写；只有 rules-architect 托管且哈希未变化的产物才可进入安全应用。
报告默认只读，用户明确确认后才可用 `scripts/apply_reconciliation.py --yes` 执行。
最终报告提供全部执行、按操作 ID 部分执行、仅执行新增、调整方案、导出、重扫和
退出选项；没有可执行 operation 时不显示执行类选项。修改、禁用和删除在真正执行
前还会二次确认。部分执行只记录实际成功项；同一条推荐绑定的多个 operation
不可拆开选择，避免只安装半套 Hook。`move` 和应用器不支持的文档/记忆写入只给
人工操作。

schema 1.2 会逐一覆盖扫描候选，并把用户确认结果结构化绑定到最终 target、分组、
Hook 模式和动作；最终结论与 operation 必须双向引用且动作一致，不能出现报告说
“保留”但执行器实际“删除”的情况。
预览与应用执行相同的路径、配置、状态和哈希预检；旧 schema 只能查看，写入必须是
1.2 ready。自动 Hook 操作还会校验完整注册集合、enforcement 对应关系和生成内容
标记；阻断型 Hook 还必须包含受管 blocking 标记和实际 deny 协议输出，不能用
`return 0` 空实现冒充。删除 Hook/Path Rule 时会把文件本体移动到
`~/.claude/rules-architect-backups/`；更新、禁用和配置裁剪则先复制快照。
归档失败会拒绝变更。应用失败还会恢复本轮
触及的文件、配置、Manifest 和状态。

输出形态示例：

```text
Hook 强制规则（2）
H01 [R-main-push][高][创建] 禁止直接 push main
执行：claude / 阻断 / PreToolUse / Bash

路径规则（1）
P01 [R-proto-field][高][保留] Proto 字段编号必须递增

团队基线（3）
...
个人记忆（1）
...
团队经验（1）
...
```

## 各模式行为

| 模式 | 风险 | 改动文件 |
|---|---|---|
| D. 仅诊断 | 零持久化 | 仅使用自动清理的私有临时 checkout |
| C. 仅 path-scoped | 极低 | `.claude/rules/rule-intake.md` |
| B. 仅 hook | 低 | 所选平台的 Claude/Codex Hook 配置与脚本 |
| A. 全装 | 中 | B + 选择 Claude 时添加 path rule 与 `CLAUDE-personal.md` §六 |
| E. 卸载 | — | 按 manifest 精确回滚 |


## 内容保护保证

本 skill **从不修改**你已有的内容，除非明确同意且记录到 manifest：

| 你的数据 | 处理 |
|---|---|
| L1 memory 文件 | 默认扫描/安装不修改；仅在逐条确认、展示精确目录并备份后，升级脚本才把该条正文替换为 stub |
| CLAUDE.md | ✋ 从不动 |
| CLAUDE-personal.md（§一~§五 等） | ✋ 在 `<!-- rules-architect:section-6 BEGIN/END -->` markers **外**：从不动 |
| `~/.claude/settings.json` 已有 hook | ✋ deep-merge 含冲突检测，全部保留 |
| `~/.codex/hooks.json` 已有 hook | ✋ deep-merge 含冲突检测，全部保留 |
| 已有的 `.claude/rules/*.md` | ✋ 只加 `rule-intake.md`（mode C/A） |
| 你本地改过的文件 | ✋ hash 不一致 → 跳过（不覆盖、不删除） |

本 skill **加了什么**（全部跟踪到 `~/.claude/.rules-architect-manifest.json`）：
- `~/.claude/settings.json` 加 3 个 hook 入口（先备份 `.bak.<ts>`）
- `~/.claude/hooks/` 加 3 个 hook 脚本
- 选择 Codex 时：`~/.codex/hooks.json` 和 `~/.codex/hooks/` 加对应入口与脚本
- 所选平台的 Skill 发现目录指向同一份 rules-architect checkout
- 模式 C / A：`<project>/.claude/rules/rule-intake.md`
- 模式 A 独有：`<project>/CLAUDE-personal.md` 加 §六 节（marker 保护，便于精确移除）

**迁移 vs 修改**：`diagnose.py` **建议**哪些 memory 条目适合升级到其它层（如节奏类规则 → L0 hook），但**绝不自动迁移**。所有迁移由人工触发（见 §六 Upgrade 流程）。

卸载是精确的（按 manifest，hash 校验）：受管 Hook、Path Rule 等文件本体直接
移动到带 `index.json` 的恢复归档，不执行复制后删除；配置和文档裁剪前复制快照。
归档失败时不会移动或修改原文件。卸载也会移除 bootstrap 创建且仍指向原
checkout 的 Skill 链接；bootstrap 创建的 checkout 仅在 Git 工作区干净时删除。
你本地修改过的文件**从不**被覆盖或删除。

## 5 层记忆模型

| 层 | 内容 | 触发 |
|---|---|---|
| L0 hook | 实时脚本 | tool 调用前/后 |
| L1 memory | 私人笔记 | CC 平台自动管理 |
| L2 path-scoped | 项目规则 | 编辑匹配文件时 |
| L3 CLAUDE.md | 团队基线 | 会话起点 |
| L5 团队 lessons | 跨工具知识 | 手动 / 触发式 |

**关键洞察**：L0 + L2 能在更接近动作或文件的位置稳定触发，但触发不等于
强制遵守。阻断 Hook、提醒 Hook、path-scoped 注入和外部 CI 需要分别标注。
L3 在长会话中可能被稀释，因此本 skill 会建议把可局部化的规则下沉到 L0/L2。

## 本 skill 不做什么

- ❌ **不判断 CLAUDE.md 的事实正确性、命令时效性或写作质量** — 这些仍交给 `claude-md-management:claude-md-improver`
- ❌ **默认不自动应用分布建议** — 报告与安装/迁移流程分离
- ❌ **不是项目特定** — 业务 hook（`mr_created_reminder` 等）放 `examples/`
- ⚠️ **codex 一等公民，gemini 需 shim** — 一键安装器会为 Codex 同时安装 Skill + Hook；gemini 等无 hook 契约的工具见跨工具节

## 配置

安装后通过环境变量自定义：

| 变量 | 默认 | 含义 |
|---|---|---|
| `RULE_INTAKE_KEYWORDS` | `chinese` | `chinese` / `english` / 自定义正则 |
| `PROTECTED_BRANCHES` | `develop\|test\|master` | 管道分隔的分支名 |
| `LESSONS_PATH` | （无） | 团队 lessons.md 绝对路径 |
| `RA_TOKEN_EXTRA_PATHS` | （无） | diagnose token 估算时额外扫描的相对路径，逗号分隔 |

## 跨平台说明

- macOS / Linux：完整支持，遵循 `XDG_CACHE_HOME`
- Windows：hook 通过 Python 工作；缓存路径用 `%LOCALAPPDATA%\Claude\cache`
- WSL：按 Linux 处理

## codex 支持（一等公民）

推荐使用一键安装器并选择 Codex；它会同时安装 Codex Skill 和 Hook：

```bash
curl -fsSL https://raw.githubusercontent.com/langlanglanglanglang/rules-architect/main/bootstrap.sh | \
  bash -s -- --platforms codex
```

下面的命令只补装 Codex Hook，不安装 Skill：

```bash
python3 ~/.agents/skills/rules-architect/scripts/install_codex_hooks.py
```

版本检测只用于提示：Codex 桌面客户端可以运行 Skill，但不一定把独立 `codex`
CLI 暴露到当前 Shell 的 `PATH`。因此 CLI 缺失、执行失败或版本偏旧时，安装器会
警告后继续写入 Hook；这不代表客户端一定缺少 Hook 能力。CI 如需严格阻断，可加
`--strict-version-check`；`--skip-version-check` 会完全跳过检测。

把同样 3 个自包含 hook 写进 `~/.codex/hooks/`,deep-merge 进 `~/.codex/hooks.json`(保留已有条目)。差异全部由安装器处理:
- 文件编辑 matcher 是 `apply_patch`(不是 `Write|Edit`);`memory_intake_check.py` 双运行时,自动解析 patch 文本里的路径
- `UserPromptSubmit` 不吃 matcher;`SessionStart` matcher 是 `startup|resume`
- **信任步骤**:codex 要按 hash 授信,装完在 codex TUI 跑 `/hooks` 打开这 3 个 hook(或首次触发时确认)

卸载走同一个 `uninstall.py`(codex 产物记在 manifest 的 `codex_*` 键,精准回滚)。

安装后用 `$rules-architect` 调用 Skill，并通过 `/hooks` 审核新 Hook。

L1 memory 不跨工具(codex 有自己的私有 store)——按设计 L1 本就不承载团队规则。

## 跨工具（gemini 等无 hook 契约的工具）

对不发布 hook 契约的工具：
- L3 规则：放进 `AGENTS.md`（codex 读它；CC 通过 `@AGENTS.md` 读）
- L0 等价物：pre-commit / githook 做分支保护
- L5（团队 lessons）：纯 markdown，任何工具能读

详见 `examples/cross-tool-shim.md`。

## 卸载

```bash
# Claude 安装入口
python3 ~/.claude/skills/rules-architect/scripts/uninstall.py

# Codex-only 安装入口
python3 ~/.agents/skills/rules-architect/scripts/uninstall.py
```

卸载会读 `~/.claude/.rules-architect-manifest.json`：
1. 对每个已装文件做 hash 校验，然后把文件本体移动到恢复归档
2. 只删本 skill 添加的 hook 入口（保留你自己的其他 hook）
3. 按记录的 `config_path` 精确处理用户级或项目级 Hook 配置
4. 移除 bootstrap 创建且未变化的 Skill 入口；干净且由 bootstrap 创建的 checkout 一并删除
5. 仅在用户显式选择时才恢复 settings.json 备份

恢复归档默认写入 `~/.claude/rules-architect-backups/<时间>-uninstall-<随机 ID>/`，
其中 `index.json` 记录原路径、SHA-256、权限、`moved/copied` 类型和归档文件位置，
`manifest.before.json` 保存卸载前 Manifest。可用
`RULES_ARCHITECT_RECOVERY_DIR` 指定其他目录。

**会移入恢复归档**（作为 manifest 跟踪的已装文件，hash 校验）：
- 受管 Hook 脚本和项目级 `.claude/rules/rule-intake.md`
- 应用规则协调建议时被删除或替换的受管 Hook、Path Rule

**会直接清理的安装器资产**：
- bootstrap 创建、仍指向所记录 checkout 的 Skill 符号链接（仅删除入口）
- bootstrap 创建且 Git 工作区干净的完整 checkout（可从远程重新下载）

**不会删**：
- 你对装好文件的本地修改（hash 不一致 → 跳过并 warn）
- 任何 L1 memory 文件（属于你的）

## Q&A

**Q：hook 会拖慢 CC 吗？**
A：每个 hook ~10-20ms；3 个合计 < 100ms。dedupe 保证同 reminder 一个会话只发一次。

**Q：我已经装了别的 hook 怎么办？**
A：`install_hooks.py` 做 deep-merge 含冲突检测。同 matcher 下已有 Hook 时只允许
append 或 skip；不会替换第三方 Hook。

**Q：怎么知道 hook 在生效？**
A：看 `~/.cache/claude-hooks/audit.jsonl`：
```bash
jq -c 'select(.decision == "inject")' ~/.cache/claude-hooks/audit.jsonl | tail
```

**Q：如何升级到新版本？**
A：Claude Code 重跑 `/rules-architect`，Codex 重跑 `$rules-architect`。skill 会比对 manifest hash 显示会变化的内容。

**Q：能和别的 CLAUDE.md 工具配合吗？**
A：可以，特别推荐 `claude-md-management:claude-md-improver`（本 skill 把 L3 审计委托给它）。其它兼容工具见 SKILL.md。

## 问题反馈

Skill 位置：Claude Code 为 `~/.claude/skills/rules-architect/`，Codex 为
`~/.agents/skills/rules-architect/`。可复现测试用例见 `tests/`。

审计日志：`~/.cache/claude-hooks/audit.jsonl`
Manifest：`~/.claude/.rules-architect-manifest.json`
