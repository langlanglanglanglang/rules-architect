# rules-architect

[English](README.md) | **中文**

> 另见：[与官方 claude-md-improver 的对比](docs/comparison-vs-claude-md-improver.zh.md)

> Claude Code 的自我改进规则架构。安装 4 个 hook + 1 个 path-scoped rule，让规则归位变可靠，不再依赖 CLAUDE.md 的注意力。

## 安装包含什么

| 组件 | 用途 | 通用？ |
|---|---|---|
| 3 个核心 hook | SOP 注入 + 基础设施（memory_intake / rule_intake / cleanup） | ✅ 通用 |
| 1 个 path-scoped rule (`rule-intake.md`) | 编辑规则文件时注入 SOP | ✅ |
| `CLAUDE-personal.md` §六 模板 | 升级 / 退役 / 团队同步 流程 | ✅ |
| `memory_sync.py` | 推送 memory → 团队 lessons（单向） | ✅ 参数化 |
| `cleanup_hook.py` | SessionStart 清理（lock TTL + audit 轮转） | ✅ |
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

## 要求

- **Claude Code >= 1.5.0**（依赖 UserPromptSubmit hook）
- Python 3.7+
- macOS / Linux 完整支持；Windows 部分支持（见跨平台节）

## 5 分钟上手

```bash
# 1. 任何 CC 会话中触发 skill
/rules-architect

# 2. 首次跑选 mode D（仅诊断）—— 最安全，不动任何文件

# 3. 看懂 5 层模型 + SOP 后：
#    重跑选 mode A（全装）或 B / C（部分装）
```

## 各模式行为

| 模式 | 风险 | 改动文件 |
|---|---|---|
| D. 仅诊断 | 零 | 无 |
| C. 仅 path-scoped | 极低 | `.claude/rules/rule-intake.md` |
| B. 仅 hook | 低 | `~/.claude/settings.json` + `~/.claude/hooks/*.py` |
| A. 全装 | 中 | B + 给你项目的 `CLAUDE-personal.md` 加 §六 |
| E. 卸载 | — | 按 manifest 精确回滚 |


## 内容保护保证

本 skill **从不修改**你已有的内容，除非明确同意且记录到 manifest：

| 你的数据 | 处理 |
|---|---|
| L1 memory 文件 | ✋ 从不动 |
| CLAUDE.md | ✋ 从不动 |
| CLAUDE-personal.md（§一~§五 等） | ✋ 在 `<!-- rules-architect:section-6 BEGIN/END -->` markers **外**：从不动 |
| `~/.claude/settings.json` 已有 hook | ✋ deep-merge 含冲突检测，全部保留 |
| 已有的 `.claude/rules/*.md` | ✋ 只加 `rule-intake.md`（mode C/A） |
| 你本地改过的文件 | ✋ hash 不一致 → 跳过（不覆盖、不删除） |

本 skill **加了什么**（全部跟踪到 `~/.claude/.rules-architect-manifest.json`）：
- `~/.claude/settings.json` 加 5 个 hook 入口（先备份 `.bak.<ts>`）
- `~/.claude/hooks/` 加 5 个 hook 脚本
- 模式 C / A：`<project>/.claude/rules/rule-intake.md`
- 模式 A 独有：`<project>/CLAUDE-personal.md` 加 §六 节（marker 保护，便于精确移除）

**迁移 vs 修改**：`diagnose.py` **建议**哪些 memory 条目适合升级到其它层（如节奏类规则 → L0 hook），但**绝不自动迁移**。所有迁移由人工触发（见 §六 Upgrade 流程）。

卸载是精确的（按 manifest，hash 校验）。你本地修改过的文件**从不**被覆盖或删除。

## 5 层记忆模型

| 层 | 内容 | 触发 |
|---|---|---|
| L0 hook | 实时脚本 | tool 调用前/后 |
| L1 memory | 私人笔记 | CC 平台自动管理 |
| L2 path-scoped | 项目规则 | 编辑匹配文件时 |
| L3 CLAUDE.md | 团队基线 | 会话起点 |
| L5 团队 lessons | 跨工具知识 | 手动 / 触发式 |

**关键洞察**：L0 + L2 是 **100% 可靠**（无注意力稀释）。L3 在长会话中被忘记。本 skill 推动规则归位向 L0/L2 偏移。

## 本 skill 不做什么

- ❌ **不是 CLAUDE.md 审计器** — 用 `claude-md-management:claude-md-improver`（Anthropic 官方插件）做 L3 审计
- ❌ **不是项目特定** — 业务 hook（`mr_created_reminder` 等）放 `examples/`
- ❌ **不支持 codex / gemini** — CC 专属。codex / gemini 替代方案见跨工具节

## 配置

安装后通过环境变量自定义：

| 变量 | 默认 | 含义 |
|---|---|---|
| `RULE_INTAKE_KEYWORDS` | `chinese` | `chinese` / `english` / 自定义正则 |
| `PROTECTED_BRANCHES` | `develop\|test\|master` | 管道分隔的分支名 |
| `LESSONS_PATH` | （无） | 团队 lessons.md 绝对路径 |
| `MIN_CC_VERSION` | `1.5.0` | 低于此版本拒绝安装 |
| `RA_TOKEN_EXTRA_PATHS` | （无） | diagnose token 估算时额外扫描的相对路径，逗号分隔 |

## 跨平台说明

- macOS / Linux：完整支持，遵循 `XDG_CACHE_HOME`
- Windows：hook 通过 Python 工作；缓存路径用 `%LOCALAPPDATA%\Claude\cache`
- WSL：按 Linux 处理

## 跨工具（codex / gemini 等）

CC hook 不在 codex / gemini 上触发。对那些工作流：
- L3 规则：放进 `AGENTS.md`（codex 读它；CC 通过 `@AGENTS.md` 读）
- L0 等价物：pre-commit / githook 做分支保护
- L5（团队 lessons）：纯 markdown，任何工具能读

详见 `examples/cross-tool-shim.md`。

## 卸载

```bash
python3 ~/.claude/skills/rules-architect/scripts/uninstall.py
```

卸载会读 `~/.claude/.rules-architect-manifest.json`：
1. 移除每个已装文件（hash 校验）
2. 只删本 skill 添加的 hook 入口（保留你自己的其他 hook）
3. 仅在用户显式选择时才恢复 settings.json 备份

**不会删**：
- 你对装好文件的本地修改（hash 不一致 → 跳过并 warn）
- 项目级 `.claude/rules/rule-intake.md`（需手动删，避免误清理）
- 任何 L1 memory 文件（属于你的）

## Q&A

**Q：hook 会拖慢 CC 吗？**
A：每个 hook ~10-20ms；4 个合计 < 100ms。dedupe 保证同 reminder 一个会话只发一次。

**Q：我已经装了别的 hook 怎么办？**
A：`install_hooks.py` 做 deep-merge 含冲突检测。同 matcher 下已有 hook 时提示你选 append / skip / replace。

**Q：怎么知道 hook 在生效？**
A：看 `~/.cache/claude-hooks/audit.jsonl`：
```bash
jq -c 'select(.decision == "inject")' ~/.cache/claude-hooks/audit.jsonl | tail
```

**Q：如何升级到新版本？**
A：重跑 `/rules-architect`。skill 会比对 manifest hash 显示会变化的内容。

**Q：能和别的 CLAUDE.md 工具配合吗？**
A：可以，特别推荐 `claude-md-management:claude-md-improver`（本 skill 把 L3 审计委托给它）。其它兼容工具见 SKILL.md。

## 问题反馈

skill 位置：`~/.claude/skills/rules-architect/`。可复现测试用例见 `tests/`。

审计日志：`~/.cache/claude-hooks/audit.jsonl`
Manifest：`~/.claude/.rules-architect-manifest.json`
