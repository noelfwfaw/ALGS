"""TrickcalLogin: 登录 - assets and task name from the page-card spec by
dev_tools/spec_build.py; the task body is a local replacement (2026-11-11).

Why the generated chain is not used:

`dev_tools.asset_check --module trickcal --shots dev_tools/samples/trickcal_login`
showed two cross-page collisions on the 7 exported frames:

    E_5_2 (sign-in page X)  1.00 on page_3 / page_4 / page_5  -> resident key
    E_3_1 (claim button)    0.99 on page_4 (reward popup)

A chain only orders the buttons. Once a press is swallowed, the resident X
wins the next frame and closes the sign-in page before the reward popup is
handled (hard rule 183). This file therefore drives the flow with per-page
positive checks plus an explicit appearance/disappearance wait after each
press. The spec's three `action: other` cards were also dropped by the chain
generator, and its `exits` were all empty, so page-card mode would have had
no link to follow either.

spec_build never overwrites an existing task file, so regenerating from the
spec keeps this file. What DOES come from the spec: the 10 buttons in
assets.py, the `Trickcal` menu group, SCHEDULER_PRIORITY and algs.py.
"""

from module.exception import TaskFailed
from module.logger import logger
from module.trickcal.assets import (E_1_1, E_2_1, E_2_2, E_3_1, E_4_1,
                                    E_5_1, E_5_2, E_6_1, E_6_2, E_7_1)
from module.trickcal.trickcal_ui import TrickcalUI

OFFSET = (20, 20)


class TrickcalLogin(TrickcalUI):
    """登录."""

    def run(self):
        """
        Pages:
            in: any
            out: page_main
        """
        logger.hr('Trickcal login', level=1)
        if not self.login_flow():
            # 这次没做成：按失败间隔早点重试，并让 run() 记 Reason: Error、
            # 推一条失败，不能当成正常跑完再排到次日。
            self.config.task_delay(success=False)
            raise TaskFailed('Trickcal login did not reach the lobby')
        self.config.task_delay(server_update=True)

    def login_flow(self, timeout=300):
        """
        Walk from the title screen to the lobby.

        Each branch is a positive check on the current frame, and every press
        is followed by an explicit wait so a resident button cannot win the
        next frame. Branch order matters: the reward popup (`E_4_1`) must be
        tested before the claim button (`E_3_1`), which still scores 0.99 on
        the popup's frame.

        Args:
            timeout (int): Upper bound owned by this loop.

        Returns:
            bool: If the lobby (`E_7_1`) was reached.
        """
        for _ in self.loop(timeout=timeout):
            # logo / 加载 / 登录是游戏自己走的过程，可能几十秒没有任何判据。
            # 纯等待不归看门狗管（硬约束 152），上限交给本循环自己的 timeout。
            self.device.stuck_record_clear()

            # End: a clean lobby. The template scores only 0.13 through the
            # announcement popup, so this is a real end condition.
            if self.appear(E_7_1, offset=OFFSET):
                logger.info('Trickcal lobby reached')
                return True

            # Return-event panel: only on returning accounts, a normal login
            # goes straight to the sign-in page. Close it and claim nothing.
            if self.appear(E_2_1, offset=OFFSET) \
                    and self.appear(E_2_2, offset=OFFSET):
                logger.info('Return event panel, close it without claiming rewards')
                self.device.click(E_2_2)
                self.wait_until_disappear(E_2_1, offset=OFFSET, timeout=10, settle=2)
                continue

            # Reward popup after the claim. Must stay ahead of `E_3_1`.
            if self.appear(E_4_1, offset=OFFSET):
                logger.info('Sign-in reward popup, tap to continue')
                self.device.click(E_4_1)
                self.wait_until_disappear(E_4_1, offset=OFFSET, timeout=10, settle=2)
                continue

            # Announcement popup over the lobby.
            if self.appear(E_6_1, offset=OFFSET) \
                    and self.appear(E_6_2, offset=OFFSET):
                logger.info('Announcement, press its X')
                self.device.click(E_6_2)
                self.wait_until_disappear(E_6_2, offset=OFFSET, timeout=10, settle=2)
                continue

            # Title screen.
            if self.appear(E_1_1, offset=OFFSET):
                logger.info('Title screen, press to start')
                self.device.click(E_1_1)
                self.wait_until_disappear(E_1_1, offset=OFFSET, timeout=20, settle=2)
                continue

            # Sign-in page, claim. Explicitly wait for the reward popup so the
            # resident `E_5_2` cannot close this page in between.
            if self.appear(E_3_1, offset=OFFSET):
                logger.info('Sign-in page, claim')
                self.device.click(E_3_1)
                if not self.wait_until_appear(E_4_1, offset=OFFSET, timeout=15, settle=2):
                    logger.warning('Reward popup not seen after claim, keep waiting')
                continue

            # Sign-in finished: only `E_5_1` (greyed-out button, 1.00 on
            # page_5 and <=0.75 on page_3/4) proves the page may be closed.
            # `E_5_2` alone is a resident key and must never be pressed here.
            if self.appear(E_5_1, offset=OFFSET) \
                    and self.appear(E_5_2, offset=OFFSET):
                logger.info('Sign-in finished, close the page')
                self.device.click(E_5_2)
                self.wait_until_disappear(E_5_2, offset=OFFSET, timeout=10, settle=2)
                continue

        logger.warning('Trickcal login did not reach the lobby in time')
        return False
