---
alwaysApply: false
globs: "module/**/*.py,dev_tools/**/*.py,algs.py,alas.py"
---

# 改 Python 之前

1. 先加载项目技能 `alas-multigame-dev`，按 SKILL.md 里的「加载策略」表读对应的
   `references/source/*.md`。**别按直觉写线性 if-appear-click 链**。
2. 页面判据、识别不对、脚本卡住：先查 `references/hard-rules.md`（155 条，编号稳定）
   和 `references/asset-recognition.md`。
3. 同一页面上的几件事合成一个任务，mixin 各自 `event_*_run()`，每步自己 `ui_goto` 归位。
4. 新页面必须**同时**进 `page.py` 的 `link` 和 UI 类的 `pages` 元组，否则永远认不出。
5. 改完必跑 `toolkit/python.exe -m dev_tools.alas_lint --severity high`；
   新增任务必须同时进 `module/config/config_manual.py` 的 `SCHEDULER_PRIORITY`；
   `config/args.json` 是生成产物，重跑 `toolkit/python.exe -m module.config.config_updater`。
