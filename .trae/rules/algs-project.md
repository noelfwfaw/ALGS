---
alwaysApply: true
---

# AlGS（AzurLaneAutoScript fork）

ALAS 框架底座改造成「一个模拟器装多个游戏、勾选任务按序跑完」的调度器。碧蓝航线业务代码已全部剥离。

## 开工前必读（这三份就是项目记忆）

1. `.workbuddy/memory/MEMORY.md` —— **权威记忆**：各游戏真机踩过的坑、用户硬性偏好、版本语义
2. `CODEBUDDY.md` —— CodeBuddy 项目入口：红线速查、运行命令、改完必做清单、发版流程。
   本机生成、不进 git、可能被重新生成；**与 MEMORY.md 冲突时一律以 MEMORY.md 为准**
3. `.workbuddy/memory/` 里最近 2~3 个日期文件 —— 当天实测细节

以上三份都不存在（新 clone、还没恢复本机资料）时：跳过，并在回复里说明；
**不要凭空发明项目约定**，先问用户。恢复步骤见 README「开发」一节。

按需再查 `.trae/skills/alas-multigame-dev/references/`：`hard-rules.md`（155 条，编号稳定）、
`framework-map.md`、`source/*.md`、`asset-recognition.md`。

## 技能

用项目技能 **`alas-multigame-dev`**（`.trae/skills/`，与 WorkBuddy / CodeBuddy 共用同一份文件）。

**不要使用全局技能 `alas-dev`**：那是碧蓝航线本体时代的旧技能，讲的 `campaign`、`module.combat`、
`module.handler`、上游 wiki 规范在本仓库已删除或已重写，照它写会 import 不存在的模块。

## 三条红线

- 每一次点击都要有判断，禁止 `sleep` 串联；等待只用 `loop(timeout=)` /
  `wait_until_appear` / `wait_until_disappear` / `wait_until_still`
- 没有 `file=` 的纯坐标 `Button` 永远不能进 `appear()` 家族（`Image.open(None)` → 直接 `exit(1)`）
- 改完过 `toolkit/python.exe -m dev_tools.alas_lint --severity high`

## 记忆写回

三个工具共用 `.workbuddy/memory/`：做完实质工作**追加**到 `YYYY-MM-DD.md`（只追加不覆盖），
长期约定改 `MEMORY.md`。**不要往 Trae 自己的记忆或 `~/.codebuddy/memories/` 写**，避免三处分叉。
