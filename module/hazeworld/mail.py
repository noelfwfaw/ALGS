from module.hazeworld.assets import MAIL_BTN_CLAIM_ALL
from module.hazeworld.hazeworld_ui import HazeworldUI, page_mail
from module.logger import logger

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
        self.ui_ensure(page_mail)

        if self.config.HazeworldMail_ClaimAll:
            self.mail_claim_all()

        self.ui_goto_main()

        # Daily task, run again after the game refreshes.
        self.config.task_delay(server_update=True)

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
