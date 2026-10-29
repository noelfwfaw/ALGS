import numpy as np

from module.base.timer import Timer
from module.base.utils import color_mask
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
whether the mailbox is empty. The only thing that changes is the badge at the
right edge of every unclaimed row, which is counted with `image_color_count()` —
in whichever of the colours the game happens to draw it, see MAIL_UNREAD_COLORS.

Closing the reward popup also closes the mailbox behind it, one click being
consumed by both layers, so the mailbox has to be re-ensured instead of assumed.
"""

# The red badge column of the mail list. Kept narrow on purpose: the mail titles
# are orange-red as well and a wider area would count them.
MAIL_UNREAD_AREA = (510, 60, 560, 620)

# The badge colour is **not** stable. Measured 2026-10-27: every unclaimed row
# carried (225, 81, 57), a red disc. Measured 2026-10-29: the two new unclaimed
# rows carry (57, 81, 225), the same disc in blue — position, diameter and the
# white "!" inside are identical, only the hue flipped (red and blue are exactly
# swapped, so the game is encoding something the script does not need to know).
#
# Counting one hard coded colour therefore goes silent the day the game changes
# its mind, and silence here means "the mailbox is empty": the 00:26 run logged
# `Mail claimed, 0 time(s)` with two unclaimed mails on screen
# (`log/probe/lostsword_signin/mail_page_after_04.png`). Both observed colours
# are counted now.
MAIL_UNREAD_COLORS = ((225, 81, 57), (57, 81, 225))
MAIL_UNREAD_THRESHOLD = 30
# One badge is 380~430 pixels at threshold 30, so 100 still detects a single
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
            if not self.mail_unread_settled():
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

            # The list fades in every time the page opens, and a badge that is
            # still fading reads as absent. Absent ends the task, so the first
            # answer has to come from a still frame: the 00:26 run asked 0.4
            # seconds after "Page arrive: page_mail" and was told the box was
            # empty while two mails were on screen.
            if count == 0:
                self.wait_until_still(MAIL_UNREAD_AREA, timeout=3)

            red, blue = self.mail_badge_pixels()
            if red + blue <= MAIL_UNREAD_PIXELS:
                logger.info(f'No unclaimed mail left (badge pixels red={red} blue={blue})')
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

    def mail_badge_pixels(self):
        """
        Pixels of every known badge colour inside the badge column.

        Only meaningful on page_mail: the rest of this game is a colourful UI and
        the column does cross red and blue pixels elsewhere. The caller reads it
        after the mailbox has been ensured, which is where the numbers below
        were measured.

        Returns:
            tuple: Pixel count per colour in MAIL_UNREAD_COLORS, in that order.
        """
        image = self.image_crop(MAIL_UNREAD_AREA, copy=False)
        return tuple(
            int(np.count_nonzero(color_mask(image, color=color, threshold=MAIL_UNREAD_THRESHOLD)))
            for color in MAIL_UNREAD_COLORS
        )

    def mail_unread(self):
        """
        Whether the mailbox still holds unclaimed mail.

        Returns:
            bool: If there is at least one unclaimed mail.
        """
        return sum(self.mail_badge_pixels()) > MAIL_UNREAD_PIXELS

    def mail_unread_settled(self, timeout=3):
        """
        `mail_unread()` read from a frame the list has stopped moving in.

        The mailbox is re-opened behind the reward popup on every batch, and the
        rows fade in each time; a badge mid-fade is invisible to the colour count
        and "no badge" here means done.

        Args:
            timeout (int, float): Seconds to wait for the column to settle.

        Returns:
            bool: If there is at least one unclaimed mail.
        """
        self.wait_until_still(MAIL_UNREAD_AREA, timeout=timeout)
        return self.mail_unread()
