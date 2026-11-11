"""
Mailbox claim (Trickcal).

Flow read off the exported frames (2026-11-11, `screenshots/trickcal/`):

    page_main  --right-top envelope (1161,30)-(1197,62)-->  page_mail
    page_mail  --bottom-right 「一鍵領取」-->  「確認領取」 reward popup
    page_mail  claimed: the button is drawn grey, the counter drops to 0/200
    page_main  <--right-top X (1044,80)-(1076,110)--

Three things here are not what they look like:

1. **The popup is a translucent overlay.** 「一鍵領取」 keeps 0.925 of its
   template score while the reward popup covers it, so a template match cannot
   be used to decide "the mailbox is back". `RewardPopup` is asked first on
   every frame; only then is the button looked at.

2. **"Is there mail left" is a colour question, not a template one.** The
   button keeps its shape when the box is empty, it is only drawn grey. The
   bright state measures mean luma 182 (3665 pixels above 200), the dimmed one
   90 (0 pixels above 200). `appear()` without `offset` compares the area mean
   against the colour stored in assets.py, which is exactly that distinction;
   `appear(..., offset=...)` matches in both states and would loop forever.

3. **The mailbox is an overlay, not a page of its own.** The lobby stays
   visible around it - `MAIL_ENTRY` still scores 0.997 through the panel - so
   only `MAIL_CLOSE` (the X, 1.000 here / <=0.61 elsewhere) is unique to this
   screen. That is what `page_mail` is checked with.

Verified offline: 34-frame matrix (see `.workbuddy/memory/2026-11-11.md`).
"""

from module.logger import logger
from module.trickcal.assets import MAIL_CLAIM_ALL
from module.trickcal.page import page_mail, page_main
from module.trickcal.trickcal_ui import TrickcalUI

MAIL_OFFSET = (20, 20)
# 一次点击之后等弹窗（或按钮变灰）。实测弹窗 0.3s 内出来，10 秒是防网络卡。
MAIL_CLAIM_TIMEOUT = 10
# 领一次就领空是常态，多给两次是防"结算时又落了新邮件"。
MAIL_CLAIM_TRIES = 3
# 点掉弹窗之后等它淡出。
MAIL_POPUP_FADE = 3


class TrickcalMail(TrickcalUI):
    """
    Claim everything in the mailbox.

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
        self.mail_claim()
        self.config.task_delay(server_update=True)

    def mail_claim(self):
        """
        Open the mailbox, claim everything, come back to the lobby.

        Pages:
            in: page_main
            out: page_main
        """
        logger.hr('Mail claim', level=2)
        self.ui_ensure(page_mail)
        claimed = self.mail_claim_all()
        logger.info(f'[Mail claimed] {claimed}')
        self.ui_goto_main()

    def mail_claim_available(self):
        """
        Whether 「一鍵領取」 is drawn in its enabled (bright) colour.

        The button keeps its shape when the box is empty and only goes grey,
        so this is a colour check by design - do not add `offset` here.

        Returns:
            bool: True if there is mail to claim.
        """
        return self.appear(MAIL_CLAIM_ALL)

    def mail_claim_all(self):
        """
        Press 「一鍵領取」 until the box is empty.

        Pages:
            in: page_mail
            out: page_mail

        Returns:
            int: How many batches went through.
        """
        claimed = 0
        for i in range(MAIL_CLAIM_TRIES):
            if not self.mail_claim_available():
                logger.info('No mail to claim')
                break
            logger.info(f'Claim all the mail ({i + 1})')
            # 上面的 mail_claim_available() 就是这次点击的判据（亮＝还有邮件），
            # 点完由 mail_wait_claimed() 验收：弹窗出现或按钮变灰。
            self.device.click(MAIL_CLAIM_ALL)  # alas-lint: allow
            if not self.mail_wait_claimed():
                logger.warning('The claim neither showed a reward popup nor greyed the button')
                break
            claimed += 1
        return claimed

    def mail_wait_claimed(self, timeout=MAIL_CLAIM_TIMEOUT):
        """
        Sit through the reward popup of one claim.

        A batch counts as claimed as soon as the popup appeared: the
        attachments are in the bag by then, even if the panel is still fading.

        Pages:
            in: page_mail
            out: page_mail

        Args:
            timeout (int): Upper bound owned by this loop.

        Returns:
            bool: False only if the claim left no trace at all.
        """
        for _ in self.loop(timeout=timeout):
            # 这里必须 interval=0：连领两批时，上一批的弹窗节流还没到期，
            # 会把"弹窗在后面"误读成"按钮变灰了"，然后把一整批当成领完。
            # 弹窗的落点是全屏遮罩，连点没有副作用，吞了就下一帧再点。
            popup = self.handle_reward_popup(interval=0)
            if popup:
                self.wait_until_disappear(popup, offset=MAIL_OFFSET, timeout=MAIL_POPUP_FADE)
                return True
            if self.reward_popup_appear():
                # 弹窗还在，只是这一帧没点成，别急着判"领完"。
                continue
            if not self.mail_claim_available():
                # 纯货币邮件不弹结算页，按钮直接变灰。
                logger.info('No reward popup, the button went grey')
                return True
        logger.warning('The claim gave no sign of life')
        return False
