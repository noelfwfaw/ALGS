"""Daily mail claiming for 雷索纳斯 (Resonance Solstice)."""

import numpy as np

from module.base.timer import Timer
from module.exception import GameStuckError
from module.logger import logger
from module.resonance import assets
from module.resonance.page import page_main, page_resonance_mail
from module.resonance.profile import MAIN_AVATAR_BTN
from module.resonance.resonance_ui import ResonanceUI

OFFSET = (5, 5)
# Right-hand mail list action column: unclaimed mails render a bright blue '领取' button,
# while claimed mails show grey '已领取' even though bottom '一键领取' stays yellow.
CLAIM_BTN_ROI = (1065, 70, 1215, 620)
CLAIM_BLUE_PIXEL_MIN = 500


def has_claimable_mail(image):
    """Return True if at least one unclaimed blue '领取' button appears in the mail list."""
    x1, y1, x2, y2 = CLAIM_BTN_ROI
    roi = image[y1:y2, x1:x2]
    r = roi[:, :, 0].astype(np.int16)
    g = roi[:, :, 1].astype(np.int16)
    b = roi[:, :, 2].astype(np.int16)
    blue_mask = (b > 170) & (b - r > 70) & (g > 90)
    return int(np.count_nonzero(blue_mask)) >= CLAIM_BLUE_PIXEL_MIN


class ResonanceMail(ResonanceUI):
    """Open mailbox from the main profile sidebar, claim all mail, and dismiss rewards."""

    def _prepare_mail_navigation(self):
        """Ensure mail, profile drawer, or main screen is ready before opening mailbox."""
        self.device.screenshot()
        if self.ui_page_appear(page_resonance_mail, offset=OFFSET):
            self.ui_current = page_resonance_mail
            return True
        if self.appear(assets.PROFILE_DRAWER_CHECK, offset=OFFSET):
            return False
        self.ui_ensure(page_main, skip_first_screenshot=True)
        return False

    def _open_mail(self):
        """Navigate from main screen via profile drawer to page_resonance_mail."""
        if self._prepare_mail_navigation():
            return
        avatar_retry = Timer(2)
        self.interval_clear(assets.MAIL_ENTRY)
        for _ in self.loop(timeout=15):
            if self.ui_page_appear(page_resonance_mail, offset=OFFSET):
                self.ui_current = page_resonance_mail
                return
            if self.appear(assets.PROFILE_DRAWER_CHECK, offset=OFFSET):
                self.appear_then_click(assets.MAIL_ENTRY, offset=OFFSET, interval=2)
                continue
            if self.ui_page_appear(page_main, offset=OFFSET) and avatar_retry.reached():
                self.device.click(MAIN_AVATAR_BTN)
                avatar_retry.reset()
        raise GameStuckError('Resonance mailbox did not open')

    def claim_all_mail(self):
        """Click '一键领取' when claimable mail exists, dismiss reward popups, and return True if claimed."""
        self.interval_clear(assets.MAIL_CLAIM_ALL)
        self.interval_clear(assets.LOGIN_REWARD)
        settle = Timer(1.2).start()
        clicks = 0
        claimed = False
        for _ in self.loop(timeout=30):
            if self.handle_reward_popup():
                claimed = True
                settle = Timer(1.5).start()
                continue
            if self.ui_page_appear(page_resonance_mail, offset=OFFSET):
                if has_claimable_mail(self.device.image):
                    if clicks >= 3:
                        return claimed
                    if self.appear_then_click(assets.MAIL_CLAIM_ALL, offset=OFFSET, interval=2):
                        clicks += 1
                        settle = Timer(3.0).start()
                else:
                    if clicks > 0:
                        claimed = True
                    if settle.reached():
                        return claimed
        return claimed

    def run(self):
        """Claim all mailbox attachments, return to main, and schedule next server update."""
        self._open_mail()
        claimed = self.claim_all_mail()
        logger.info('琐呐邮件领取完成 (claimed=%s)', claimed)
        self.ui_goto_main()
        self.config.task_delay(server_update=True)
