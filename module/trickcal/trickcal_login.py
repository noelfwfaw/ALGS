"""TrickcalLogin: 登录 - assets and task name from the page-card spec by
dev_tools/spec_build.py; the task body is a local replacement (2026-11-11).

The launch and the whole cold-start flow now live in `TrickcalUI.app_start()`
and `TrickcalUI.handle_app_boot()` (see that module). `alas.py:start()` calls
`game_ui().app_start()` when switching games, so a launch reaches the lobby
instead of just restarting the process. This task only has to cover the cases
where that did not happen: `--no-boot`, the client sitting in the background,
or the client left in the middle of the login flow.

Why the generated chain is not used:

`dev_tools.asset_check --module trickcal --shots dev_tools/samples/trickcal_login`
showed two cross-page collisions on the 7 exported frames:

    E_5_2 (sign-in page X)  1.00 on page_3 / page_4 / page_5  -> resident key
    E_3_1 (claim button)    0.99 on page_4 (reward popup)

A chain only orders the buttons. Once a press is swallowed, the resident X
wins the next frame and closes the sign-in page before the reward popup is
handled (hard rule 183). The spec's three `action: other` cards were also
dropped by the chain generator and its `exits` were all empty, so page-card
mode would have had no link to follow either.

spec_build never overwrites an existing task file, so regenerating from the
spec keeps this file. What DOES come from the spec: the 10 buttons in
assets.py, the `Trickcal` menu group, SCHEDULER_PRIORITY and algs.py.
"""

from module.exception import TaskFailed
from module.logger import logger
from module.trickcal.trickcal_ui import TrickcalUI


class TrickcalLogin(TrickcalUI):
    """登录."""

    def run(self):
        """
        Pages:
            in: any
            out: page_main
        """
        logger.hr('Trickcal login', level=1)
        # 调度器 start() / run_task 不带 --no-boot 时已经走过
        # app_start() + handle_app_boot()。这里补 --no-boot、游戏在后台、
        # 以及停在登录流程中间页三种情况；已在大厅时 boot 首帧即返回。
        if not self.device.app_is_running():
            logger.info('Game is not in the foreground, launch it')
            reached = self.app_start()
        else:
            reached = self.handle_app_boot()
        if not reached:
            # 这次没做成：按失败间隔早点重试，并让 run() 记 Reason: Error、
            # 推一条失败，不能当成正常跑完再排到次日。
            self.config.task_delay(success=False)
            raise TaskFailed('Trickcal did not reach the lobby')
        self.config.task_delay(server_update=True)
