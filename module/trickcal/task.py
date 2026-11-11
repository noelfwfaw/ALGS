"""
Daily / weekly task rewards (Trickcal).

Flow read off the exported frames (2026-11-11, `screenshots/trickcal/`):

    page_main  --right-top checklist icon (1212,167)-(1254,199)-->  page_task
    page_task  (每日任务 - the tab the game opens on)
    page_task  --bottom-right 「全部领取」 (1041,613)-(1216,667)-->  reward popup
    page_task  --bottom-left 「领取」      (62,643)-(198,698)   -->  reward popup
    page_task  --left 「收获满满的一周」   (63,206)-(174,256)   -->  page_task_weekly
    page_task_weekly  --same two buttons, same two positions--    reward popup
    page_main  <--top-left arrow (24,17)-(66,63)--

Two things here are not what they look like:

1. **Both buttons are greyed when there is nothing to claim**, exactly like the
   friend list. The exported assets are the dim state, so `appear()` (an RGB
   template match) would answer "is it still dim" and nothing else - the lit
   state is a repaint and drops out of `appear()`. Presence is a luma match,
   the state is `match_template_color()`, which compares the matched area
   against the colour stored **for that page**: the daily tab is mint, the
   weekly one is pink, and the same button has a different mean on each. That
   is why the two tabs get their own pair of assets instead of one shared pair.

2. **The popup is the generic reward panel.** It is translucent and its bottom
   edge stops right above the bottom bar, so the claim button keeps rendering
   underneath and "the button went dim" is still readable while the panel is
   up. That matters because the panel's header text differs per scene and this
   task does not have a screenshot of the task one: it never asks "which popup
   is this", it lets `handle_reward_popup()` close the ones it knows and treats
   the dim button as the receipt.

Both claims are idempotent, so running twice a day costs nothing: once the
rewards are taken the buttons are dim and both clicks are skipped.
"""

from module.logger import logger
from module.trickcal.assets import (TASK_CLAIM_ALL, TASK_CLAIM_POINTS,
                                   TASK_WEEKLY_CLAIM_ALL,
                                   TASK_WEEKLY_CLAIM_POINTS)
from module.trickcal.page import page_main, page_task, page_task_weekly
from module.trickcal.trickcal_ui import TrickcalUI

TASK_OFFSET = (20, 20)
# 一次点击之后等"按钮变灰"或弹窗。实测弹窗 0.3s 内出来，10 秒是防网络卡。
TASK_CLAIM_TIMEOUT = 10
# 素材存的是暗态；和暗态的颜色差超过这个值才算"亮起来了"。
TASK_DIM_THRESHOLD = 30


class TrickcalTask(TrickcalUI):
    """
    Claim the daily task rewards, switch to the weekly tab, claim those too.

    Pages:
        in: page_main
        out: page_main
    """

    def run(self):
        """
        Pages:
            in: page_main
            out: page_main
        """
        self.ui_ensure(page_main)
        self.task_claim()
        self.config.task_delay(server_update=True)

    def task_claim(self):
        """
        Open the task list, claim both tabs, come back to the lobby.

        Pages:
            in: page_main
            out: page_main
        """
        logger.hr('Task rewards', level=2)
        self.ui_ensure(page_task)
        self.task_claim_page(TASK_CLAIM_ALL, TASK_CLAIM_POINTS)
        self.ui_goto(page_task_weekly)
        self.task_claim_page(TASK_WEEKLY_CLAIM_ALL, TASK_WEEKLY_CLAIM_POINTS)
        self.ui_goto_main()

    def task_claim_page(self, claim_all, points):
        """
        Claim one tab: the bottom-right 「全部领取」 first, then the bottom-left
        point-track 「领取」 if it is lit.

        Pages:
            in: page_task / page_task_weekly
            out: same page

        Args:
            claim_all (Button): The 「全部领取」 of this tab.
            points (Button): The point-track 「领取」 of this tab.

        Returns:
            int: How many of the two buttons were clicked.
        """
        claimed = 0
        for button in (claim_all, points):
            if self.task_claim_rewards(button):
                claimed += 1
        logger.info(f'[Task claimed] {claimed}')
        return claimed

    def task_claim_rewards(self, button):
        """
        Click one claim button if it is lit, and sit through its popup.

        Pages:
            in: page_task / page_task_weekly
            out: same page

        Args:
            button (Button): One of the four claim buttons.

        Returns:
            bool: Whether a claim was clicked.
        """
        if not self.task_claim_available(button):
            logger.info(f'{button.name}: nothing to claim')
            return False
        logger.info(f'Claim {button.name}')
        # task_claim_available() 就是这一下的判据（亮＝有奖励可领），
        # 点完由 task_wait_claimed() 验收：按钮变灰，或弹窗出现。
        self.device.click(button)  # alas-lint: allow
        self.task_wait_claimed(button)
        return True

    def task_claim_available(self, button):
        """
        Whether the button is lit, i.e. there is a reward waiting.

        The exported asset is the dim state, so a colour match means "nothing to
        claim". The check is a luma template match (does the button exist at
        all) followed by the colour of the matched area, because the button
        keeps its shape and only repaints when it lights up.

        Args:
            button (Button): One of the four claim buttons.

        Returns:
            bool: True if the button is lit.
        """
        if not button.match_luma(self.device.image, offset=TASK_OFFSET):
            logger.info(f'{button.name} not on screen')
            return False
        if self.match_template_color(
                button, offset=TASK_OFFSET, threshold=TASK_DIM_THRESHOLD):
            # 形状在、颜色还是素材里的暗态 = 没得领。
            return False
        return True

    def task_wait_claimed(self, button, timeout=TASK_CLAIM_TIMEOUT):
        """
        Sit through the reward popup of one claim.

        A claim counts as done as soon as the button goes dim, popup or no
        popup: the panel is translucent and stops above the bottom bar, so the
        button is readable through it, and the rewards are in the bag anyway.

        Pages:
            in: page_task / page_task_weekly
            out: same page

        Args:
            button (Button): The button that was just clicked.
            timeout (int): Upper bound owned by this loop.

        Returns:
            bool: False if the button never went dim.
        """
        for _ in self.loop(timeout=timeout):
            # interval=0：连领两个奖励时，上一批的弹窗节流还没到期，
            # 会把"弹窗在里面"误读成"按钮变灰了"（mail.py 踩过同一个坑）。
            if self.handle_reward_popup(interval=0):
                continue
            if not self.task_claim_available(button):
                logger.info(f'{button.name} went dim, claimed')
                return True
        logger.warning(f'{button.name} is still lit after the claim')
        return False
