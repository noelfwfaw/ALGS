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
        # `start()` / `run_task` already walked app_start() + handle_app_boot().
        # This covers --no-boot, a backgrounded client and a client left in the
        # middle of the login flow; on a clean lobby the boot loop returns on
        # its first frame.
        # Both return True on success; a stuck boot raises instead of returning
        # False, so the result is intentionally discarded.
        if not self.device.app_is_running():
            logger.info('Game is not in the foreground, launch it')
            _ = self.app_start()
        else:
            _ = self.handle_app_boot()
        # A boot that never reaches the lobby raises GameStuckError. That is
        # "the game did not come up", not "this run failed": GameScheduler.run()
        # catches it, archives the error, pushes a recoverable warning and calls
        # Restart. Turning it into TaskFailed here would double-report and skip
        # the restart (ladder in SKILL.md section 6.3).
        self.config.task_delay(server_update=True)
