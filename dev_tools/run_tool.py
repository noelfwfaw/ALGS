# -*- coding: utf-8 -*-
"""手动跑「工具」页的任务，和 WebUI 上点 Start 走同一条路。

`ProcessManager.run_process()` 对工具任务就是
`AlGS(config_name).run(inflection.underscore(task), skip_first_screenshot=True)`，
这里照抄一遍，方便在没有 GUI 的时候复现问题。

    python dev_tools/run_tool.py Starsavior2
    python dev_tools/run_tool.py Starsavior2 --reset    # 先把号重置回标题页
    python dev_tools/run_tool.py Starsavior2 --step settle   # 只跑某一段（卡住时复现）
    python dev_tools/run_tool.py Starsavior2 --config chaoszero

❗工具任务**不在** `SCHEDULER_PRIORITY` 里，所以 `dev_tools/run_task.py` 跑不了它。
"""
import os
import sys

import inflection

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from algs import AlGS  # noqa: E402


def main():
    args = [x for x in sys.argv[1:] if not x.startswith('--')]
    flags = [x for x in sys.argv[1:] if x.startswith('--')]
    if not args:
        print(__doc__)
        return 1

    task = args[0]
    config_name = 'alas'
    if '--config' in flags:
        config_name = args[1] if len(args) > 1 else 'alas'

    alas = AlGS(config_name)
    command = inflection.underscore(task)

    if '--reset' in flags:
        from module.config.server import set_server

        # ❗顺序：先建 Device（它按包名把命名空间设回 hazeworld），再切命名空间，
        #   最后才 import 游戏模块（`assets.py` 在导入时就展开 `Button.file`，
        #   命名空间不对会 `KeyError: 'hazeworld'`）。
        device = alas.device
        set_server('starsavior')

        from module.starsavior.starsavior2 import Starsavior2

        task_object = Starsavior2(config=alas.config, device=device)
        print('[tool] reset -> %s' % task_object.reset(), flush=True)

    if '--step' in flags:
        # 只跑某一段（`settle` / `claim` / `gacha` / `verify` / `guide` …），
        # 卡在某个画面时不用从登录重来。
        from module.config.server import set_server

        device = alas.device
        set_server('starsavior')

        from module.starsavior.starsavior2 import Starsavior2

        alas.config.bind('Starsavior2')
        task_object = Starsavior2(config=alas.config, device=device)
        task_object.load_plan()
        for step in args[1:]:
            received = getattr(task_object, step)()
            print('[tool] %s -> %s' % (step, received), flush=True)
        return 0

    ok = alas.run(command, skip_first_screenshot=True)
    print('[tool] %s -> %s' % (command, ok), flush=True)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
