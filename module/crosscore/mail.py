"""邮箱领取 of 交错战线 (Cross Core).

The mailbox is a full page opened from the envelope at the top right of the
lobby. Its 「一键领取」 sits at the bottom left; pressing it raises the global
「获得物品」 popup, which `CrosscoreUI.handle_item_popup()` already knows, and
greys the button out once every mail is claimed (2026-11-08 用户导出的
`邮箱页面.png` / `MAIL_CLAIM_DIM.png`).

The lit/greyed state is read from gold pixels, not from template matching: the
two states of the button are structurally almost identical (`TM_CCOEFF_NORMED`
matches them at 0.63 for the mail button and 0.85 for the task one, because it
compares structure and ignores colour). Measured gold pixels inside the button:
1436 when lit, 0 when grey, so `CLAIM_GOLD_PIXELS` separates them with a wide
margin.

Mail arrives a few times a day, so the task schedules itself on the next server
update, like the mail tasks of the other games in this repository.
"""

from module.crosscore.assets import (MAIL_CLAIM, MAIL_CLAIM_DIM, MAIN_MAIL)
from module.crosscore.crosscore_ui import CrosscoreUI
from module.crosscore.page import page_main
from module.crosscore.utils import CLAIM_GOLD_PIXELS, gold_pixels
from module.logger import logger


class CrosscoreMail(CrosscoreUI):
    """
    Claim every mail and go back to the lobby.

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
        logger.hr('交错邮箱', level=1)
        self.ui_ensure(page_main)

        if not self.mail_enter():
            self.config.task_delay(minute=15)
            return

        claimed = self.mail_claim()
        self.back_to_main()
        logger.info(f'Mail claimed, {claimed} time(s)')
        # Mail arrives a few times a day, once per game day is enough.
        self.config.task_delay(server_update=True)

    def mail_enter(self):
        """
        Open the mailbox from the lobby.

        Returns:
            bool: If the mailbox is on screen.
        """
        for _ in self.loop(timeout=30):
            if self.handle_item_popup():
                continue
            if self.handle_lobby_popup():
                continue
            if self.mail_page_appear():
                # The list fades in, and a button mid-fade reads as grey: the
                # first answer has to come from a still frame, otherwise an
                # empty mailbox is reported while mails are still on screen.
                self.wait_until_still(MAIL_CLAIM.area, timeout=3)
                return True
            # 3 秒一次：邮箱页要加载两秒多，2 秒的间隔会在页面画出来之前再点一次
            # 信封（2026-11-08 真机日志：20:11:30 点开，20:11:32 又点了一次）。
            if self.appear(MAIN_MAIL, offset=(20, 20), interval=3):
                logger.info('Open the mailbox')
                self.device.click(MAIN_MAIL)

        logger.warning('Cannot open the mailbox')
        return False

    def mail_page_appear(self):
        """
        Whether the mailbox is drawn, in either state of its claim button.

        Neither state alone is enough: `MAIL_CLAIM` is the lit button and does
        not match the greyed one (0.63), while `MAIL_CLAIM_DIM` is the greyed
        one and does not match the lit one (0.67). Together they cover the page,
        and neither of them matches the lobby or the task page at this position.
        """
        return self.appear(MAIL_CLAIM, offset=(20, 20)) \
            or self.appear(MAIL_CLAIM_DIM, offset=(20, 20))

    def mail_claim(self, max_click=3):
        """
        Press 「一键领取」 until the button turns grey.

        The reward popup is handled before the button is read: it is drawn on
        top of the page and the button behind it is dimmed by the overlay, which
        would look exactly like "nothing left to claim".

        Args:
            max_click (int): Safety limit, the claim is idempotent anyway.

        Returns:
            int: Times clicked.
        """
        logger.hr('领取邮件', level=2)
        claimed = 0

        for _ in self.loop(timeout=60):
            if self.handle_item_popup():
                continue

            if gold_pixels(self.device.image, MAIL_CLAIM.area) <= CLAIM_GOLD_PIXELS:
                logger.info('No claimable mail left')
                break

            if claimed >= max_click:
                logger.warning(f'Claim all pressed {claimed} times, give up')
                break

            # interval keeps one click per 3 seconds: the popup takes a moment
            # to show up and the button is still lit in the frames before it.
            if self.appear(MAIL_CLAIM, offset=(20, 20), interval=3):
                logger.info(f'Claim all, {claimed + 1} time(s)')
                self.device.click(MAIL_CLAIM)
                claimed += 1

        return claimed
