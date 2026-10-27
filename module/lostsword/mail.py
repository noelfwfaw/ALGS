from module.base.timer import Timer
from module.logger import logger
from module.lostsword.assets import MAIL_BTN_CLAIM_ALL, REWARD_POPUP_TITLE
from module.lostsword.lostsword_ui import LostswordUI, page_mail

"""
邮箱 (mailbox).

Flow observed in game:

    page_main  --右上角汉堡-->  page_menu  --右侧信封图标-->  page_mail
    page_mail  --一键领取-->  已获得道具。弹窗（点触继续，见 LostswordUI）
    page_mail  --右上角 X-->  page_main

The "claim all" button looks the same whether there is something to claim or
not: the mean colour of its area is identical to the last digit in both states,
and it stays on screen after the mailbox is emptied. So the button can not tell
whether the mailbox is empty. The only thing that changes is the red badge at
the right edge of every unclaimed row, which is counted with
`image_color_count()`.

Closing the reward popup also closes the mailbox behind it, one click being
consumed by both layers, so the mailbox has to be re-ensured instead of assumed.
"""

# The red badge column of the mail list. Kept narrow on purpose: the mail titles
# are orange-red as well and a wider area would count them.
MAIL_UNREAD_AREA = (510, 60, 560, 620)
MAIL_UNREAD_COLOR = (216, 80, 60)
# One badge is about 330 pixels at threshold 30, so 100 still detects a single
# unclaimed mail while reading 0 on every other page of this game.
MAIL_UNREAD_PIXELS = 100


class LostswordMail(LostswordUI):
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
        logger.hr('Mail claim', level=1)
        self.ui_ensure(page_mail)

        count = 0
        for _ in range(3):
            count += self.mail_claim_all()
            # Dismissing the reward popup closes the mailbox with it, so walk
            # back in rather than assuming the page survived.
            self.ui_ensure(page_mail)
            if not self.mail_unread():
                break

        logger.info(f'Mail claimed, {count} time(s)')
        self.ui_goto_main()
        # Mail arrives a few times a day, once per game day is enough.
        self.config.task_delay(server_update=True)

    def mail_claim_all(self, skip_first_screenshot=True, max_click=5):
        """
        Press "claim all" until no unclaimed mail is left.

        Pages:
            in: page_mail
            out: any

        Args:
            skip_first_screenshot (bool):
            max_click (int): Safety limit, to avoid clicking forever.

        Returns:
            int: Times clicked.
        """
        logger.hr('Mail claim all', level=2)
        count = 0
        timeout = Timer(90).start()

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
                if not self.device.has_cached_image:
                    self.device.screenshot()
            else:
                self.device.screenshot()

            # The popup covers the whole screen, the badge column included, so
            # it is handled before the badge is counted.
            if self.appear(REWARD_POPUP_TITLE, offset=30):
                self.handle_reward_popup()
                continue

            if not self.mail_unread():
                logger.info('No unclaimed mail left')
                break

            if count >= max_click:
                logger.warning(f'Claim all clicked {count} times, give up')
                break

            if self.appear_then_click(MAIL_BTN_CLAIM_ALL, offset=(20, 20), interval=3):
                count += 1
                logger.info(f'Claim all, {count} time(s)')
                continue

            if timeout.reached():
                logger.warning('Claim all timeout')
                break

        return count

    def mail_unread(self):
        """
        Whether the mailbox still holds unclaimed mail.

        Returns:
            bool: If there is at least one unclaimed mail.
        """
        return self.image_color_count(MAIL_UNREAD_AREA, color=MAIL_UNREAD_COLOR,
                                      threshold=30, count=MAIL_UNREAD_PIXELS)
