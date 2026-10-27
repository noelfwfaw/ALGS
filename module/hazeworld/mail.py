from module.hazeworld.assets import MAIL_BTN_CLAIM_ALL
from module.hazeworld.hazeworld_ui import HazeworldUI, page_mail
from module.logger import logger


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
        self.ui_ensure(page_mail)

        if self.config.HazeworldMail_ClaimAll:
            self.mail_claim_all()

        self.ui_goto_main()

        # Daily task, run again after the game refreshes.
        self.config.task_delay(server_update=True)

    def mail_claim_all(self, skip_first_screenshot=True):
        """
        Press "claim all" on the mail page.

        The button looks the same whether there is a mail to claim or not, so
        the number of presses is limited instead of waiting for a state.

        Pages:
            in: page_mail
            out: page_mail
        """
        # The mail page fades in, and ui_ensure() returns on that half drawn
        # frame. Settle it first, otherwise the color check point below reads
        # "no claim button" and the mailbox is silently skipped.
        if not self.wait_until_settled(MAIL_BTN_CLAIM_ALL, timeout=3, skip_first_screenshot=skip_first_screenshot):
            logger.warning('Claim all button not found, mailbox skipped')
            return 0
        return self.claim_all(MAIL_BTN_CLAIM_ALL, disabled=None, max_click=3)
