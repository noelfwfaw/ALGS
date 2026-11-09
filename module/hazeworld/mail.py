from module.base.utils import crop
from module.hazeworld.assets import MAIL_BTN_CLAIM_ALL
from module.hazeworld.hazeworld_ui import HazeworldUI, page_mail
from module.hazeworld.page import page_main
from module.logger import logger

# 主界面右上角邮箱图标的红色菱形角标，只框顶栏内的角标本体
# (1148,12)-(1176,40)。顶栏外面是角色立绘，红色头发/背景会混进来。
MAIL_BADGE_AREA = (1148, 12, 1176, 40)
# 角标中心是高饱和亮红：R>200 / G<110 / B<110，真机三张有红点帧 41~46 像素，
# 三张无红点帧（含红色背景那张）全是 0。阈值 20 留一倍余量。
# ❗别用 `color_mask((200,70,60), threshold=70)` 那种宽松红色计数：
#   2026-10-26_12-32-12 那张无红点帧顶栏透出红背景，照样数出 226 像素。
MAIL_BADGE_MIN_PIXELS = 20

# The button reads as bright while there is mail to claim and dims once the box
# is empty, which is what ends the claim loop. Three presses is the ceiling, not
# an expectation: one press claims everything the box holds.
MAIL_CLAIM_MAX = 3

# The list is redrawn after a claim, and the result may come with a sheet of its
# own. Both are over before the page stops changing, so the settle is measured
# on the page instead of guessed - leaving on a frame that is still being drawn
# is what lets the back key land on a fade-in and be swallowed.
MAIL_SETTLE = 3


class HazeworldMail(HazeworldUI):
    """
    Claim every mail attachment.

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
        logger.hr('Mail claim', level=1)
        self.ui_ensure(page_main)
        self.device.screenshot()
        # ❗**没红点就是没有邮件可领**（用户 2026-11-10 确认），别再进邮箱页。
        #   「一键领取」按钮有/无邮件长得一样，空邮箱进去只会按亮度判据空点
        #   3 次、留一条 `Claim all clicked 3 times, stop` 的 WARNING
        #   （2026-11-10 05:09 真机复现），看着就像识别出错。
        if not self.mail_has_unread():
            logger.info('No red badge on the mail icon, no mail to claim, skip')
            self.config.task_delay(server_update=True)
            return

        self.ui_ensure(page_mail)

        if self.config.HazeworldMail_ClaimAll:
            self.mail_claim_all()

        self.ui_goto_main()

        # Daily task, run again after the game refreshes.
        self.config.task_delay(server_update=True)

    def mail_has_unread(self):
        """
        Whether the mail icon on page_main carries the red diamond badge.

        The badge has a bright red core inside a white/black diamond. Counting
        that core inside the dark top bar separates it from the red-haired
        artwork behind the bar, which a loose red mask cannot do.

        Returns:
            bool: If there is mail to claim.
        """
        area = crop(self.device.image, MAIL_BADGE_AREA).astype(int)
        pixels = int(((area[:, :, 0] > 200) & (area[:, :, 1] < 110)
                      & (area[:, :, 2] < 110)).sum())
        logger.info(f'Mail badge bright red pixels: {pixels}')
        return pixels >= MAIL_BADGE_MIN_PIXELS

    def mail_claim_all(self, skip_first_screenshot=True):
        """
        Press "claim all" on the mail page until the box is empty.

        The button carries the same label whether there is mail to claim or not,
        so the state is read from how bright that label is drawn rather than
        from a second asset: it dims once the box runs out, and `claim_all()`
        exits on that. `MAIL_CLAIM_MAX` is only a ceiling.

        The page is settled afterwards. A claim redraws the list and may raise a
        result sheet, and the caller leaves for the main page as soon as this
        returns - a back key sent into that redraw is swallowed, and the task
        then ends on a page it did not mean to be on.

        Pages:
            in: page_mail
            out: page_mail

        Returns:
            int: Times pressed.
        """
        # The mail page fades in, and ui_ensure() returns on that half drawn
        # frame. Settle it first, otherwise the color check point below reads
        # "no claim button" and the mailbox is silently skipped.
        if not self.wait_until_settled(MAIL_BTN_CLAIM_ALL, timeout=3, skip_first_screenshot=skip_first_screenshot):
            logger.warning('Claim all button not found, mailbox skipped')
            return 0

        count = self.claim_all(MAIL_BTN_CLAIM_ALL, max_click=MAIL_CLAIM_MAX)
        if count:
            self.wait_until_still(MAIL_BTN_CLAIM_ALL.area, timeout=MAIL_SETTLE)
            # A result sheet, if the game raised one, sits under the back key.
            for _ in range(MAIL_CLAIM_MAX):
                if not self.handle_reward():
                    break
                self.wait_until_still(MAIL_BTN_CLAIM_ALL.area, timeout=MAIL_SETTLE)
            logger.info(f'Mail claimed, {count} press(es)')
        else:
            logger.info('Mailbox is already empty')

        return count
