# Codex Skill Evolution

English version: [README.md](README.md)

这是一个面向 Codex 的、**先提案再落盘**的 skill 演进机制：检测 skill 使用，强制做 retrospective，把可复用经验变成 proposal，并且只有在人工批准后才真正写回规则文件。

## 这个项目为什么存在

真实使用 skill 时，经常会遇到两类问题：

- skill 被真正用起来后，才暴露出说明缺步骤、边界条件没写、失败模式没覆盖
- 任务结束时大家都知道“这里下次应该记住”，但没有一条安全、可审计、可回滚的路径把这个经验固化下来

这个项目就是为了补这条路径。它把“下次应该记住”变成一个明确的工作流：

- 检测 skill 使用
- 在结束前强制 retrospective
- 把可复用经验转成 proposal
- 经过人工审核后再写回长期规则

## 目前能做什么

- 从 hook 事件里检测 skill 使用
- 把当前 session 标记成“结束前必须 retrospective”
- 通过 `record` 生成 learning 和 proposal
- 把 proposal 放进 review queue，而不是直接改规则
- 只有明确 `approve` 之后才能 `apply`
- 支持 `rollback`
- 支持三类 skill 路径：
  - `.codex/skills/...`
  - `.agents/skills/...`
  - `.codex/skills/...` 指向 `.agents/skills/...` 的 symlink
- 提供一个公开可跑的 smoke check 来验证核心工作流是否活着

## 一个真实场景

假设某次任务里，agent 用了 `find-skills` 这个 skill。

任务过程中你发现一条可复用经验：

“如果一个 skill 仓库把 `SKILL.md` 放在 repo 根目录，安装时必须显式带 `--path . --name <skill-name>`，否则名字推导会出错。”

现在这套机制会这样工作：

1. hook 检测到这次 session 用了 `find-skills`
2. 当前 session 被标记成：结束前必须做 retrospective
3. 如果你认为这次没有可复用经验，就记录 `no_reusable_learning`
4. 如果你认为这次有可复用经验，就运行 `record`
5. 系统生成一条 proposal，状态是 `proposed`
6. proposal 不会自动落盘，必须先人工 `approve`
7. 之后才能 `apply`
8. 如果写回结果不对，可以 `rollback`

## 它不会做什么

- 不会自动编辑 `SKILL.md`
- 不会自动编辑 `AGENTS.md`
- 不会自动批准 proposal
- 不是一个通用记忆系统
- 不是一个完整的 conversation reflection 平台

## 核心流程

```text
skill 被使用
-> 当前 session 需要 retrospective
-> 记录 learning
-> 生成 proposal
-> 人工 review
-> approve / reject
-> apply
-> 必要时 rollback
```

## 当前源码布局

当前这个 workspace snapshot 里的实现还保留在 `.codex/` 下：

- 工作流 CLI：`.codex/scripts/skill_evolution.py`
- hook 检测器：`.codex/plugins/skill-evolution-hooks/scripts/posttooluse_skill_tracker.py`
- hook 配置：`.codex/plugins/skill-evolution-hooks/hooks.json`
- plugin 元数据：`.codex/plugins/skill-evolution-hooks/.codex-plugin/plugin.json`
- 公开 smoke check：`scripts/check_skill_evolution_smoke.py`

这些运行时产物应该视为数据，而不是源码：

- `.codex/skill-learnings/`
- `.codex/skill-proposals/`
- `.codex/skill-backups/`
- `.codex/skill-evolution-state/`
- `.codex/skill-change-log.jsonl`

## 安装前提

当前版本默认假设你有一个兼容 Codex 的运行环境，并且：

- 能运行 Python 3.12+
- 能执行 hook 脚本
- 提供有效的 `CODEX_HOME`

在当前 workspace 布局下，最小安装要素是：

1. 把 `skill_evolution.py` 放到运行时的 `scripts/` 目录
2. 把 `posttooluse_skill_tracker.py` 放到对应 plugin 的 `scripts/` 目录
3. 在同一个 plugin 目录里安装 `hooks.json` 和 plugin manifest
4. 安装后先跑一次：

```bash
python3 scripts/check_skill_evolution_smoke.py --json
```

## 日常命令

标记“这次没有可复用经验”：

```bash
python3 .codex/scripts/skill_evolution.py mark-retrospective --outcome no_reusable_learning
```

记录学习并生成 proposal：

```bash
python3 .codex/scripts/skill_evolution.py record \
  --skill-name <skill-name> \
  --skill-path <path-to-skill-md> \
  --trigger-scenario "<发生了什么>" \
  --problem "<这次暴露的问题>" \
  --problem-kind workflow-improvement \
  --reusable-rationale "<为什么这是可复用经验>" \
  --proposed-text "<建议更新文本>" \
  --risk "<风险说明>"
```

查看待审核 proposal：

```bash
python3 .codex/scripts/skill_evolution.py review --status proposed
```

批准 proposal：

```bash
python3 .codex/scripts/skill_evolution.py approve --proposal-id <proposal-id>
```

应用已批准 proposal：

```bash
python3 .codex/scripts/skill_evolution.py apply --proposal-id <proposal-id>
```

回滚已应用 proposal：

```bash
python3 .codex/scripts/skill_evolution.py rollback --proposal-id <proposal-id>
```

## 安全模型

- proposal 先进入 review queue，默认状态是 `proposed`
- 未批准 proposal 不能 `apply`
- `.system` 里的 skill 默认不直接自动写回
- 对追加型目标，rollback 优先按 marker 精确删除 proposal 插入块
- 如果 marker 无法可靠删除，仍然保留基于备份的恢复路径

## 当前版本已经覆盖到的能力

- skill 使用检测
- retrospective gating
- proposal queue
- approval-gated apply
- rollback
- 第三方 skill / symlink skill 兼容
- public smoke verification

## 当前版本还没有覆盖的能力

当前版本还不是 `claude-reflect` 的完整 Codex 对标版本。

目前还没有，或者暂时不在当前范围内的能力包括：

- skill 之外的通用 correction capture
- history scan / 历史 session 回扫
- 自动发现“这应该长成一个新 skill”
- 更完整的 confidence / dedupe / semantic clustering
- 完全独立于当前 `.codex/` workspace snapshot 的成品化 repo 结构

## 验证方式

先跑公开 smoke check：

```bash
python3 scripts/check_skill_evolution_smoke.py
python3 scripts/check_skill_evolution_smoke.py --json
```

当前自动化测试：

```bash
python3 -m unittest tests.test_skill_evolution_paths -v
python3 -m unittest tests.test_skill_evolution_cli -v
python3 -m unittest tests.test_skill_evolution_runtime -v
python3 -m unittest tests.test_skill_evolution_smoke -v
python3 - <<'PY'
import unittest
import tests.test_posttooluse_skill_tracker as t
suite = unittest.defaultTestLoader.loadTestsFromModule(t)
unittest.TextTestRunner(verbosity=2).run(suite)
PY
```

## Roadmap

当前重点：

- 把 skill-use-driven proposal workflow 做扎实
- 让外部 skill、symlink skill、rollback、安全边界都稳定
- 提供一个公开可跑的 smoke check

后续可能继续补：

- 更丰富的 reflection capture
- 历史任务回填
- 新 skill 候选发现
- 更干净的 standalone repo packaging
