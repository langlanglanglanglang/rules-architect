# rules-architect vs claude-md-improver

**中文** | [English](comparison-vs-claude-md-improver.md)

> 两个互补的 Claude Code skill，针对规则管理的不同侧面。

## 一句话对比

| Skill | 它回答什么问题 |
|---|---|
| **claude-md-improver**（Anthropic 官方） | 你的 CLAUDE.md 内容**写得好不好**？ |
| **rules-architect**（本仓） | 你的规则**应该写在哪一层**？ |

两者设计上**互补共存**。`rules-architect` 在 L3（CLAUDE.md 内容审计）层面**主动委托**给 `claude-md-improver`。

## 详细对比

| 维度 | claude-md-improver | rules-architect |
|---|---|---|
| **作用域** | CLAUDE.md 系列文件 | 5 层规则生态（L0 hook / L1 memory / L2 path-scoped / L3 CLAUDE.md / L5 团队 lessons） |
| **核心问题** | 内容质量 | 规则归位 |
| **输出** | 评分报告 + diff 审批后 Edit | 装 5 个 hook + path-scoped rule + 维护文档 + 维护脚本 |
| **机制** | 一次性 audit（人读报告 → 改） | 持续拦截（实时 hook 触发，不依赖 attention） |
| **改 settings.json** | 否 | 是（注册 hooks，含 manifest 精确回滚） |
| **L3 CLAUDE.md 内容审计** | ✅ 专长（6 项打分 A–F） | ❌ 明确委托给 claude-md-improver |
| **L1 memory 管理** | ❌ 不管 | ✅ 5 问 SOP / 升级 / 退役 / 团队同步 |
| **L0 hook 实时拦截** | ❌ 不做 | ✅ 4–5 个通用 hook |
| **L2 path-scoped 编辑触发** | ❌ 不做 | ✅ `rule-intake.md` |
| **L5 团队 lessons 同步** | ❌ 不管 | ✅ `memory_sync.py` |

## 实战场景对比

| 场景 | claude-md-improver | rules-architect |
|---|---|---|
| CLAUDE.md 里 build 命令过时 | ✅ 发现 + 提议修正 | ❌ 不关心内容对错 |
| 一条规则在 memory 写 3 次还在忘 | ❌ 不看 memory | ✅ 5 问 SOP → 升级 L0 hook |
| 开 MR 后总忘报五列汇总 | ❌ 完全不管 | ✅ `mr_created_reminder` hook 实时拦 |
| CLAUDE.md 太长，attention 稀释 | ⚠️ 给 conciseness 评分 | ✅ 5 问 SOP 推规则下沉到 L2 path-scoped |
| 个人 memory ↔ 团队 lessons 同步 | ❌ 不管 | ✅ `memory_sync.py` 单向 push（设计如此） |
| 完整审计 CLAUDE.md 体系 | ✅ **专长** | ❌ 委托 |
| 团队规则 codex/gemini 看不到 | ❌ 不管 | ✅ 5 问 SOP Q3 推升级到 L3/L5 |
| 规则放错时**自动**拦截 | ❌ 仅一次性 | ✅ 装上后**每次会话**实时 hook 拦 |

## 类比

- **claude-md-improver** = **校对员 / 编辑** — 看你写的内容质量好不好
- **rules-architect** = **图书馆员 / 架构师** — 决定每条规则该放哪一层"书架"

## 协同关系（内置）

`rules-architect` 的 `diagnose.py` 把 L3 委托给 claude-md-improver：

```python
def scan_l3_claude_md():
    return {
        "grade": "(delegated)",
        "delegated_to": "claude-md-management:claude-md-improver",
        "plugin_enabled": <检测>,
        "recommendation": (
            "运行 /claude-md-management:claude-md-improver 做 L3 审计"
            if 启用 else
            "先安装 claude-md-management 插件..."
        ),
    }
```

`install_hooks.py` 检测到 claude-md-improver 未启用时**主动提示**用户安装；可选 `--enable-claude-md-management` flag 在插件已缓存时**自动**启用。

## 最佳实践：两个都装

| 时机 | 用哪个 |
|---|---|
| 每月 / 定期 CLAUDE.md 质量 audit | `/claude-md-management:claude-md-improver` |
| 日常规则归位实时拦截 | `rules-architect` 装好的 hook 自动跑 |
| 新规则产生时归位评估 | `rules-architect` 的 5 问 SOP（hook + path-scoped 自动注入） |
| 把 memory 条目升级到团队 lessons | `rules-architect` 的 `memory_sync.py push` |

## 时机差异

- **claude-md-improver**：**反思型** — 你主动触发，看一次报告，应用修正。
- **rules-architect**：**预防型** — 装一次后，**每次写规则**都被自动拦截 + SOP 注入。

类比：claude-md-improver 是每年体检；rules-architect 是常驻保健医生 + 营养师配方。

## 风险敞口

| | claude-md-improver | rules-architect |
|---|---|---|
| 安装风险 | 极低（只启用 skill） | 中（deep-merge `settings.json`；manifest 支持精确回滚） |
| 误触发 | 不适用（人工调用） | 低（同会话 dedupe + 句尾 `?/？` 拒绝） |
| 撤销 | 禁用 plugin | `uninstall.py` 按 manifest 精确回滚 |
| CC 版本要求 | 无特殊 | ≥ 1.5.0（依赖 UserPromptSubmit hook） |

## 一张图总结

```
你的 CC 规则生态
│
├── 内容质量 ─────→ claude-md-improver（一次性审计 + 改）
│
└── 归位结构 ─→ rules-architect（建立拦截 + 持续生效）
                       │
                       └── L3 部分自动委托 ──→ claude-md-improver
```

两者**正交**，应**都装**。`rules-architect` 装的过程会主动引导你启用 `claude-md-improver`。
