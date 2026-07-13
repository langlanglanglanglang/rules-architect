---
name: rules-architect
description: Self-improving Claude Code rule architecture - 5-layer memory model (L0 hook / L1 memory / L2 path-scoped / L3 CLAUDE.md / L5 team lessons) + 5-question placement SOP + 4 generic hooks + path-scoped rule-intake + team sync. Use when user asks "how to manage rules" / "rules keep getting forgotten" / "claude.md optimization" / "memory optimization" / "rules architect" / wants rule placement automation. L3 audit delegated to claude-md-management:claude-md-improver.
triggers:
  - rules architect
  - 自我改进规则
  - 规则归位
  - claude.md 优化
  - memory 优化
  - 规则容易忘
  - rule placement
  - memory optimization
---

# Rules Architect Skill

> **中文** | [English](SKILL.en.md)

Claude Code 的自我改进规则架构。安装 4 个 hook + 1 个 path-scoped rule + 维护文档，让规则归位变可靠，不再靠 CLAUDE.md 的 attention。

## 它解决的问题

Claude Code 默认行为：所有细节都被甩到 L1 memory（因为 memory 是最方便写入的层）。结果是：

- Memory 越堆越多，里面塞了大量本该放别处的规则
- 团队看不到你的 memory（私人）
- CLAUDE.md 在长会话里 attention 稀释
- 本来应该 hook 拦截的规则留在 memory，结果继续被忘

本 skill 在**规则写入瞬间**提供 **3 层拦截**，强制重新评估归位。

## 5 层记忆模型

| 层 | 是什么 | 触发 | token 开销 |
|---|---|---|---|
| **L0 hooks** | `~/.claude/hooks/*.py` + settings.json 配置 | 工具调用前/后，实时 | 启动 0，注入约 50-200 |
| **L1 memory** | `~/.claude/projects/.../memory/*.md` | 每 session 注入索引，明细按需读 | 索引约 3k |
| **L2 path-scoped** | `.claude/rules/*.md`，frontmatter 含 `paths:` | 编辑匹配文件时自动注入 | 启动 0 |
| **L3 CLAUDE.md** | `CLAUDE.md` + `@import` 链 | session 启动全量加载 | 40k+ |
| **L5 team lessons** | 仓库内 `docs/ai/lessons.md` | 人工或工作流触发读 | 0（按需） |

## 5 问归位 SOP

任何新规则**写入前**必走 5 问：

| # | 问题 | 选层 |
|---|---|---|
| 1 | 触发条件能用 tool/matcher 精确表达？（如 "git commit"、"编辑 .proto"） | **L0 hook** 或 **L2 path-scoped** |
| 2 | 只在编辑特定文件/目录时才用？ | **L2** `.claude/rules/` |
| 3 | 全团队都要遵守（含 codex/gemini 用户）？ | **L3** CLAUDE.md 或 **L5** lessons |
| 4 | 仅个人协作偏好，团队不需要知道？ | **L1** memory |
| 5 | 与已有规则重叠？grep 关键词 → 是 → 改现有，别新建 | — |

**禁止**：跳过 5 问直接默认落 L1 memory——这是泄漏的最大来源。

## 5 步执行流程（由主 agent 在 CC session 中编排）

本 skill 通过 `/rules-architect` 由用户触发。**主 agent**（你 CC session 里的 Claude）负责编排这 5 步——**不是**一个 Python 脚本一把梭。memory 升级需要语义判断，只有主 agent 能给。

### Step 1：诊断（不改文件）

```bash
python3 scripts/diagnose.py --json > /tmp/ra-before.json
```

把结构化报告展示给用户，包括 **memory 升级候选表**——每条候选附 `recommended_target` + `reason`。

### Step 2：展示 5 层模型 + 5 问 SOP

展示架构与 SOP。简要说明"把一条 memory 升 L0 hook 意味着什么"（持续拦截 vs L1 单纯建议）。

### Step 3：模式选择

| 模式 | 内容 |
|---|---|
| **D**. 仅诊断 | 不改文件（首次跑最安全） |
| **C**. 仅 path-scoped | 在当前项目加 `rule-intake.md` |
| **B**. 仅 hook | 装 3 个核心 hook（memory_intake / rule_intake / cleanup） |
| **A**. 全量安装 | B + rule-intake + §六 + 交互式 memory 升级 |
| **E**. 卸载 | 按 manifest 精准回滚 |

### Step 4：执行

#### 4a. 装 3 个核心 hook（模式 B / A）

```bash
python3 scripts/install_hooks.py --non-interactive
```

只装 3 个通用 hook。带个人偏好的 workflow hook（error_recovery、dangerous_branch）放在 `examples/` 里供用户 fork。

#### 4b. memory 升级循环（模式 A；模式 B 可选）

从 Step 1 读 `upgrade_candidates`。**对每条候选**：

1. 问用户：*「升级 `<feedback_name>`？（建议目标：`<target>`，原因：`<reason>`）[y/N]」*
2. 若 yes：
   - **读** memory 全文
   - **提炼**简洁 reminder 文本（你——主 agent——做语义蒸馏：把动作/约束提取成拦截时注入的文本；< 500 字符，自包含，不引用外部文档）
   - **决定** hook 事件 + matcher：
     - 节奏关键词 + 无特定工具 → 通常 `UserPromptSubmit` + `*`
     - 绑定特定工具（commit / MR 等） → 该工具的 PostToolUse
     - 建议是「L3 CLAUDE.md」→ **跳过 hook**，建议用户写到 CLAUDE.md
   - **写** reminder 到 `/tmp/<feedback_name>-reminder.txt`
   - **装** hook：
     ```bash
     python3 scripts/install_hook_from_memory.py \
         --name <stem> \
         --event <event> \
         --matcher '<matcher>' \
         --reminder-file /tmp/<feedback_name>-reminder.txt \
         --description "<一句话>" \
         --feedback-source <feedback_name>
     ```
   - **标记 memory 已升级**（正文换 stub，frontmatter 与 git 历史保留）：
     ```bash
     python3 scripts/mark_memory_promoted.py \
         --feedback <feedback_name> \
         --target "L0 hook ~/.claude/hooks/<stem>.py"
     ```

#### 4c. 装 rule-intake.md（模式 C / A）

```bash
python3 scripts/install_rule_intake.py
```

#### 4d. 给 CLAUDE-personal.md 加 §六（仅模式 A）

```bash
python3 scripts/install_personal_md_section.py --create-if-missing
```

### Step 5：再诊断 + 前后对比

```bash
python3 scripts/diagnose.py --json > /tmp/ra-after.json
```

给用户展示结构化 diff：

- L0 hook 数量（前 → 后）
- L1 候选剩余（前 → 后，哪几条被升了）
- token 预估（前 → 后）
- 新增 / 修改 / 保留的文件
- 每条升级结果（"feedback_X → L0 hook ~/.claude/hooks/X.py"）

---

### 主 agent 红线

- **永远先跑 Step 1**，任何改动前
- **绝不**未经每条候选的明确用户同意就自动升级
- **reminder 精简**：< 500 字符、自包含、不引用外部章节
- **matcher 不确定**时：先给用户看草稿 + 问确认再装
- **Step 5 必须给前后对比**，让用户看到 impact

## 本 skill 提供什么

**3 个核心 hook（通用，默认装）**：

- `memory_intake_check.py` — 写入 memory 时 → 注入 5 问 SOP
- `rule_intake_reminder.py` — 用户消息含规则关键词 → 注入 5 问 SOP
- `cleanup_hook.py` — SessionStart 清理（lock TTL + audit 轮转）

**Opt-in hook（在 `examples/`，fork + 改造）**：

- `error_recovery_checkpoint.py.example` — 工具报错时强制 3 行汇报
- `dangerous_branch_reminder.py.example` — checkout 受保护分支时警告
- `mr_created_reminder.py.example` — codeup MCP MR → 汇总表
- 看 `examples/extension-hook-skeleton.py` 从零写自己的 hook

**1 个 path-scoped 规则**：

- `.claude/rules/rule-intake.md` — 编辑任何规则文件时 → 注入 5 问 SOP

**维护文档 + 脚本**：

- `CLAUDE-personal.md §六` 模板（升级 / 退役 / 团队同步流程）
- `memory_sync.py` — 单向 push memory → 团队 lessons.md
- `cleanup_hook.py` — SessionStart 清理（lock TTL + audit 轮转）

## 本 skill 不提供什么

- ❌ 项目特有 hook（如给 codeup MCP 用的 `mr_created_reminder`）— 看 `examples/`
- ❌ 业务 path-scoped 规则（proto / sql / release-notes / meta-md）— 看 `examples/`
- ❌ L3 CLAUDE.md 审计 — 委托给 `claude-md-management:claude-md-improver`
- ⚠️ codex 一等公民（`install_codex_hooks.py` 原生装 hook）；gemini 等无 hook 契约的工具见 README 「跨工具」节

## 内容保留承诺

本 skill **绝不在未经明确同意时**修改你的现有内容。所有改动都记录到 `~/.claude/.rules-architect-manifest.json`，支持精准回滚。

**绝不动**：

- L1 memory 文件（你的私人笔记）
- CLAUDE.md 正文
- CLAUDE-personal.md 中 `<!-- rules-architect:section-6 BEGIN/END -->` 标记外的所有内容
- 你现有的 `~/.claude/settings.json` 条目（deep-merge 保留所有其它项）
- 其它 `.claude/rules/*.md` 文件
- 你本地改过的文件（hash 失配 → 跳过 + 警告）

**新增（经同意）**：

- `~/.claude/hooks/` 内至多 5 个 hook 脚本
- `~/.claude/settings.json` 内至多 5 个 hook 注册项（推送前先备份）
- 模式 C/A：`.claude/rules/rule-intake.md`
- 模式 A：`CLAUDE-personal.md` 的 §六 节（marker 保护）

**升级 vs 修改**：`diagnose.py` **建议**哪些 memory 可以升其它层（附 target + reason），但**不会自动移**。升级由人工触发，走 §六 升级流程。

## 最低环境要求

- Claude Code >= 1.5.0（要求 UserPromptSubmit hook）
- Python 3.7+
- macOS / Linux（Windows：部分支持，见 README）

## 文件布局

```
~/.claude/skills/rules-architect/
├── SKILL.md                              # 本文件（中文主版）
├── SKILL.en.md                           # 英文版
├── README.md                             # 5 分钟上手 + Q&A（中文）
├── README.en.md                          # 英文版
├── scripts/
│   ├── diagnose.py                       # 扫 L0-L5，--json 输出
│   ├── install_hooks.py                  # deep-merge 到 settings.json（CC）
│   ├── install_codex_hooks.py            # deep-merge 到 ~/.codex/hooks.json（codex）
│   ├── install_rule_intake.py            # 项目级 path-scoped 安装
│   ├── install_personal_md_section.py    # 加 §六 到 CLAUDE-personal.md
│   ├── install_hook_from_memory.py       # 从 memory 生成 hook
│   ├── mark_memory_promoted.py           # 标记 memory 已升级为 stub
│   ├── uninstall.py                      # 按 manifest 精准回滚
│   └── memory_sync.py                    # memory → 团队 lessons（仅 push）
├── templates/
│   ├── hooks/
│   │   ├── memory_intake_check.py.tmpl
│   │   ├── rule_intake_reminder.py.tmpl  # {{RULE_INTAKE_KEYWORDS}}
│   │   ├── cleanup_hook.py.tmpl
│   │   └── generated-hook-skeleton.py.tmpl
│   ├── rules/
│   │   └── rule-intake.md.tmpl
│   ├── personal-section-6.md.tmpl
│   └── settings-snippet.json.tmpl
├── examples/                             # 不会装
│   ├── README.md
│   ├── error_recovery_checkpoint.py.example
│   ├── dangerous_branch_reminder.py.example
│   ├── mr_created_reminder.py.example    # codeup MCP 专属
│   ├── path-scoped-rule-skeleton.md
│   ├── extension-hook-skeleton.py
│   └── cross-tool-shim.md
└── tests/
    ├── unit/
    ├── integration/
    │   └── sandbox_install.sh            # 隔离 $HOME 测试
    └── README.md
```

## Manifest

`~/.claude/.rules-architect-manifest.json` 记录每个装上的文件：

```json
{
  "skill_version": "1.0.0",
  "installed_at": "2026-06-12T...",
  "files": [
    {"path": "~/.claude/hooks/memory_intake_check.py",
     "hash": "sha256...", "owner": "rules-architect", "version": "1.0.0"}
  ],
  "settings_hooks_added": [
    {"event": "PreToolUse", "matcher": "Write|Edit|MultiEdit",
     "command": "python3 ~/.claude/hooks/memory_intake_check.py"}
  ]
}
```

`uninstall.py` **只删 manifest 里的项目**（精准回滚，**不是**全量备份还原）。

## 输出约定

每一步输出：

1. **将要做什么**（一行）
2. **结果**（成功/失败 + 详情）
3. **下一步动作**（失败时停下）

失败会通过 manifest 自动回滚。

## 引用

- `templates/` — 所有可装的产物
- `scripts/` — 安装 + 诊断 + 卸载 + 同步
- `examples/` — 非通用模板（**不会装**），供参考
- `tests/` — 单元 + sandbox 集成
- `README.md` — 5 分钟上手 + Q&A（中文）
- `README.en.md` — 英文版
