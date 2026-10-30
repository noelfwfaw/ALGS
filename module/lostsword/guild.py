import cv2

from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import color_mask
from module.logger import logger
from module.lostsword.assets import (GUILD_BTN_DONATE, GUILD_BTN_INVEST_GOLD,
                                     GUILD_BTN_INVEST_TOKEN, GUILD_BTN_SIGN,
                                     GUILD_DONATE_CLOSE, GUILD_DONATE_GOLD,
                                     GUILD_DONATE_TOKEN, REWARD_POPUP_TITLE)
from module.lostsword.lostsword_ui import (LostswordUI, page_guild,
                                           page_guild_donate, page_menu)

"""
公会日常 (guild dailies).

Flow observed in game:

    page_main        --右上角菜单-->      page_menu
    page_menu        --网格里的「公会」--> page_guild
    page_guild       --底部「捐献」-->     page_guild_donate
    page_guild_donate--「100000 捐献」-->  已获得道具。弹窗（点触继续）
    page_guild_donate--「10 捐献」× 3-->   同上，每次一个弹窗
    page_guild_donate--右上角 X-->         page_guild
    page_guild       --底部「签到」-->     已获得道具。弹窗
    page_guild       --右侧「50000 投资」--> 已获得道具。弹窗
    page_guild       --右侧「10 投资」-->    已获得道具。弹窗
    page_guild       --右上角 X-->         page_main

Every one of those steps is optional in the game's own terms: once it is done
for the day the button greys out and its red "!" badge disappears. That badge
is what this task reads, because it is the only thing that answers "is there
still something to do here" without OCR - and it is why a day with nothing to
do costs one visit to the menu instead of a tour through five panels.

The guild entry of the menu carries the same badge, so the task is one
screenshot away from ending when the guild has nothing at all.
"""

# Where the game draws the "!" badge, measured on the four screenshots of
# 2026-10-29 (every one of them reads 382~387 pixels of `GUILD_BADGE_COLORS` at
# threshold 30, and 0 anywhere else on the same frame):
#
#   page_menu            公会 entry      (922, 458, 943, 479)
#   page_guild           捐献 button     (590, 644, 614, 668)
#   page_guild           签到 button     (831, 644, 855, 668)
#   page_guild           投资 50000 gold (1217, 512, 1241, 536)
#   page_guild           投资 10 信物    (1217, 606, 1241, 630)
#   page_guild_donate    100000 捐献     (535, 589, 559, 613)
#   page_guild_donate    10 捐献         (975, 589, 999, 613)
GUILD_ENTRY_BADGE = (922, 458, 943, 479)
GUILD_DONATE_BADGE = (590, 644, 614, 668)
GUILD_SIGN_BADGE = (831, 644, 855, 668)
GUILD_INVEST_GOLD_BADGE = (1217, 512, 1241, 536)
GUILD_INVEST_TOKEN_BADGE = (1217, 606, 1241, 630)
GUILD_DONATE_GOLD_BADGE = (535, 589, 559, 613)
GUILD_DONATE_TOKEN_BADGE = (975, 589, 999, 613)

# The badge is a red disc with a white "!" in it, mean (223, 82, 58). The
# mailbox of this game taught that the hue is not a promise: the same disc came
# back blue one morning with position, size and glyph untouched. Both are
# counted, because silence here means "nothing to do" and would skip a day.
GUILD_BADGE_COLORS = ((223, 82, 58), (58, 82, 223))
GUILD_BADGE_THRESHOLD = 30
# One badge is ~380 pixels at threshold 30; 100 still sees a badge that is half
# covered by a panel edge, and no other spot of these pages reaches it.
GUILD_BADGE_PIXELS = 100

# The guild page fetches its data after the page itself is drawn: the badges pop
# in 0.8~1.2 s later (measured on the device, 2026-10-29 23:38: the 签到 badge
# shows up at 0.80 s, both 投资 badges at 1.00 s). Reading before that answers
# "done for today" on a page that had three things left, which is exactly what
# the first real run did. So the spots are polled until the answer holds for
# `GUILD_BADGE_SETTLE` frames - they arrive as a group - and the timeout is what
# a page with nothing left costs.
GUILD_BADGE_TIMEOUT = 3
GUILD_BADGE_SETTLE = 3

# Sorting the reward popups. The popup is dismissed by tapping a blank spot of
# whatever is underneath it, and the same tap is regularly consumed by both
# layers: on the guild page the default point of `REWARD_POPUP_CLOSE` (975~1025,
# 615~655) lies on the 「10 投资」 row, so a dismissed popup would invest once as
# a side effect. Both points below are blank: the empty 公告 list of the guild
# page, and the left margin of the donate dialog between its border and the
# 「100000 捐献」 button.
GUILD_TAP = Button(area=(580, 460, 640, 500), color=(0, 0, 0),  # alas-lint: allow - a click point alias
                   button=(580, 460, 640, 500), name='GUILD_TAP')
GUILD_DONATE_TAP = Button(area=(232, 596, 272, 636), color=(0, 0, 0),  # alas-lint: allow - a click point alias
                          button=(232, 596, 272, 636), name='GUILD_DONATE_TAP')

# How long the reward popup may take to show up after a press. The press plays
# an animation first, so a popup that is missing after 8 seconds did not come
# at all; that is the receipt this task relies on.
GUILD_REWARD_TIMEOUT = 8


class LostswordGuild(LostswordUI):
    """
    Take everything the guild has for the day.

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
        logger.hr('Guild daily', level=1)
        self.guild_daily()
        self.ui_goto_main()
        # Donations, the sign-in and both investments reset with the daily
        # server update.
        self.config.task_delay(server_update=True)

    def guild_daily(self):
        """
        Walk the guild page once and take whatever carries a badge.

        Pages:
            in: page_main
            out: page_guild
        """
        self.ui_goto_main()
        self.ui_goto(page_menu)
        # A badge is read as a colour, and a panel that is still fading in is
        # dimmer than the one the threshold was measured on. Template matching
        # does not mind (the correlation is scale free), so "the page matched"
        # does not mean "the panel is drawn".
        self.guild_settle(page_menu.check_button)

        if not self.guild_badged(GUILD_ENTRY_BADGE):
            logger.info('No badge on the guild entry, the guild has nothing today')
            return

        self.ui_goto(page_guild)
        # One read for the whole page: the four badges arrive together, and
        # each step below is told what it found instead of asking again - a
        # second read costs another 3 seconds on every spot that is done.
        donate, sign, invest_gold, invest_token = self.guild_badges(
            GUILD_DONATE_BADGE, GUILD_SIGN_BADGE,
            GUILD_INVEST_GOLD_BADGE, GUILD_INVEST_TOKEN_BADGE)
        self.guild_donate(badged=donate)
        self.guild_sign_in(badged=sign)
        self.guild_invest(gold=invest_gold, token=invest_token)
        self.ui_goto(page_guild)

    def guild_settle(self, button, timeout=4):
        """
        Wait until a panel is drawn *and* has stopped moving.

        `settle=` only proves the check point matched n times in a row, and a
        panel that slides in matches on every one of those frames - at a
        different offset each time. `Button.match()` writes that offset into the
        click point, so a press fired on a moving panel lands wherever the
        artwork happened to be on that frame: the guild entry was clicked 26 px
        to the left on the run of 2026-10-29 23:32, the tap fell beside the
        icon, the menu closed and the task walked back to the lobby.

        Args:
            button (Button): Check point of the panel.
            timeout (int, float): Seconds.

        Returns:
            bool: If the panel settled.
        """
        if not self.wait_until_appear(button, offset=30, timeout=timeout,
                                      settle=self.SETTLE_FRAMES):
            return False
        self.wait_until_still(button, timeout=timeout)
        return True

    def guild_badge_count(self, area, image=None):
        """
        Count the pixels of a "!" badge on one spot of a frame.

        The badge is a flat disc, so it is counted by colour rather than
        matched: as a template it is useless, its corner without the badge is
        the same artwork minus 24 pixels, which matches well above the 0.85
        threshold - exactly the trap `MENU_BTN_TASK` documents.

        Args:
            area (tuple): Area of the badge.
            image (np.ndarray): Frame to read, defaults to `device.image`.

        Returns:
            int: Pixels that look like the badge.
        """
        image = self.device.image if image is None else image
        x1, y1, x2, y2 = area
        region = image[y1:y2, x1:x2, :3]
        count = 0
        for color in GUILD_BADGE_COLORS:
            count = max(count, cv2.countNonZero(
                color_mask(region, color, threshold=GUILD_BADGE_THRESHOLD)))
        return count

    def guild_badged(self, area):
        """
        Whether the current frame draws the "!" badge on one spot.

        Only for spots that come with the artwork (the menu entry, the donate
        dialog). The guild page fetches its badges, so its spots are read with
        `guild_badges()` instead.

        Args:
            area (tuple): Area of the badge.

        Returns:
            bool: If the badge is there.
        """
        return self.guild_badge_count(area) > GUILD_BADGE_PIXELS

    def guild_badges(self, *areas, timeout=GUILD_BADGE_TIMEOUT):
        """
        Read several badges of the guild page, after its data has arrived.

        The page is drawn first and filled in afterwards: at 0.5 s it still has
        no 公会投资 panel at all, the sign-in badge appears at 0.8 s and the two
        investments at 1.0 s (measured on the device, 2026-10-29 23:38). A read
        in that window answers "done for today" for everything.

        So the spots are polled until the same answer holds for
        `GUILD_BADGE_SETTLE` frames, and at least one badge is there. A page
        where nothing is left never satisfies the second half, and pays the
        whole `timeout` - which is the price of not skipping a day.

        Args:
            *areas (tuple): Areas of the badges to read.
            timeout (int, float): Seconds to keep polling.

        Returns:
            list[bool]: One per area, in the order given.
        """
        timeout = Timer(timeout).start()
        previous = None
        agree = 0
        while 1:
            self.device.screenshot()
            current = tuple(self.guild_badge_count(area) > GUILD_BADGE_PIXELS
                            for area in areas)
            agree = agree + 1 if current == previous else 1
            previous = current
            if agree >= GUILD_BADGE_SETTLE and any(current):
                return list(current)
            if timeout.reached():
                return list(current)

    def guild_open_donate(self):
        """
        Make sure the 公会捐献 dialog is the open one.

        Dismissing a reward popup may take the panel underneath with it - the
        mailbox of this game closes exactly that way - so every press starts by
        asking whether the dialog survived the last popup instead of assuming
        it.

        Pages:
            in: page_guild, or anywhere below it
            out: page_guild_donate

        Returns:
            bool: If the dialog is open.
        """
        if self.ui_page_appear(page_guild_donate):
            self.guild_settle(page_guild_donate.check_button, timeout=2)
            return True

        self.ui_goto(page_guild)
        self.ui_click(click_button=GUILD_BTN_DONATE,
                      check_button=GUILD_DONATE_CLOSE,
                      skip_first_screenshot=True)
        self.guild_settle(page_guild_donate.check_button)
        # `ui_click()` returns nothing - it breaks once the check button
        # matches and retries forever otherwise - so the dialog is confirmed on
        # the frame it left in `device.image`.
        return self.ui_page_appear(page_guild_donate)

    def guild_donate_once(self, button, label):
        """
        Press one 捐献 button and close the reward popup it raises.

        Pages:
            in: page_guild_donate
            out: page_guild_donate

        Args:
            button (Button): The 捐献 button of one currency.
            label (str): For the log.

        Returns:
            bool: If the donation went through.
        """
        if not self.guild_open_donate():
            logger.warning(f'Donate {label}: the 公会捐献 dialog is not open')
            return False

        logger.info(f'Donate {label}')
        if self.wait_until_appear(button, offset=(30, 30), timeout=2):
            self.device.click(button)
        else:
            logger.warning(f'Donate {label}: the button is not on screen')
            return False
        # The popup is the receipt: without it the press did not land, and
        # pressing again could spend a second donation on the same day.
        if not self.wait_until_appear(REWARD_POPUP_TITLE, offset=30,
                                      timeout=GUILD_REWARD_TIMEOUT, settle=2):
            logger.warning(f'Donate {label}: no reward popup after the press')
            return False
        if not self.handle_reward_popup(button=GUILD_DONATE_TAP):
            logger.warning(f'Donate {label}: the reward popup stayed')
            return False
        return True

    def guild_close_donate(self):
        """
        Close the 公会捐献 dialog.

        `ui_goto(page_guild)` cannot do this: the dialog does not cover the
        page's title, so `page_guild` matches right through it and the
        navigation answers "already there". The dialog then stayed open over the
        sign-in and the investments on the first real run (23:36), and every
        press of those steps would have landed on it instead of on the page.

        Returns:
            bool: If the dialog is closed.
        """
        if self.ui_page_appear(page_guild_donate):
            logger.info('Close the 公会捐献 dialog')
            # The X is the dialog's own check point, so it has just matched -
            # but a press fired on the frame that opened the dialog is eaten by
            # its animation, and one tap is all this step gets.
            if self.wait_until_appear(GUILD_DONATE_CLOSE, offset=30, timeout=2):
                self.device.click(GUILD_DONATE_CLOSE)
            return self.wait_until_disappear(GUILD_DONATE_CLOSE, offset=30,
                                             timeout=5, settle=2)
        return True

    def guild_donate(self, badged):
        """
        Donate gold once and spirit coins three times.

        The daily allowance is written on the dialog itself (0/1 and 0/3) and
        the badge drops off the button once it is used up, so the loop stops on
        the badge rather than counting presses - a day that started half done
        (the user donated by hand) does not waste a press on a grey button.

        Pages:
            in: page_guild
            out: page_guild

        Args:
            badged (bool): If the 捐献 button carried a badge, read by
                `guild_badges()` together with the rest of the page.
        """
        logger.hr('Guild donate', level=2)
        if not badged:
            logger.info('Both donations are done for today')
            return

        self.ui_goto(page_guild)
        self.guild_settle(page_guild.check_button)
        if not self.guild_open_donate():
            logger.warning('Could not open the 公会捐献 dialog')
            return

        if self.guild_badged(GUILD_DONATE_GOLD_BADGE):
            self.guild_donate_once(GUILD_DONATE_GOLD, 'gold 100000')
        else:
            logger.info('The gold donation is done for today')

        made = 0
        for index in range(1, 4):
            if not self.guild_open_donate():
                break
            if not self.guild_badged(GUILD_DONATE_TOKEN_BADGE):
                break
            if not self.guild_donate_once(GUILD_DONATE_TOKEN, f'spirit coin {index}/3'):
                break
            made += 1
        logger.info(f'Spirit coin donations made: {made}')

        self.guild_close_donate()

    def guild_press(self, button, badge, label):
        """
        Press one badged row of the guild page and take the popup it raises.

        The popup is the receipt, but it is not proof either way: a press can go
        through and lose its popup when the client re-renders, which is what the
        second real run did - the spirit coin investment landed with no popup
        and the task reported it as missed (23:43). The row's own badge is the
        witness that survives that: a spent row drops it, a row whose press was
        eaten keeps it.

        Pages:
            in: page_guild
            out: page_guild

        Args:
            button (Button): The row to press.
            badge (tuple): Badge area of that row.
            label (str): For the log.

        Returns:
            bool: If the row is spent.
        """
        logger.info(f'Press {label}')
        if self.wait_until_appear(button, offset=(30, 30), timeout=2):
            self.device.click(button)
        else:
            logger.warning(f'{label}: the button is not on screen')
            return False

        if self.wait_until_appear(REWARD_POPUP_TITLE, offset=30,
                                  timeout=GUILD_REWARD_TIMEOUT, settle=2):
            self.handle_reward_popup(button=GUILD_TAP)
            return True

        logger.warning(f'{label}: no reward popup after the press')
        # The page blanks for a moment while the client talks to the server, and
        # a badge read on that frame would call a row spent that was never
        # touched - the one answer this task cannot afford to get wrong.
        if not self.guild_settle(page_guild.check_button):
            return False
        if not self.guild_badges(badge, timeout=1.5)[0]:
            logger.info(f'{label}: the badge is gone, the press went through')
            return True
        return False

    def guild_sign_in(self, badged):
        """
        Take the daily guild attendance reward.

        Pages:
            in: page_guild
            out: page_guild

        Args:
            badged (bool): If the 签到 button carried a badge.
        """
        logger.hr('Guild sign in', level=2)
        if not badged:
            logger.info('The guild is already signed in today')
            return

        for attempt in (1, 2):
            self.ui_goto(page_guild)
            self.guild_settle(page_guild.check_button)
            if self.guild_press(GUILD_BTN_SIGN, GUILD_SIGN_BADGE, '签到'):
                return
            logger.warning(f'Sign in: attempt {attempt} did not land')

    def guild_invest(self, gold, token):
        """
        Take both investments of the guild's 1 stage reward.

        The two rows are the same widget with a different currency, so they are
        driven by one loop; the badge on each row says whether it is still
        worth pressing.

        Pages:
            in: page_guild
            out: page_guild

        Args:
            gold (bool): If the 50000 gold row carried a badge.
            token (bool): If the 10 信物 row carried a badge.
        """
        logger.hr('Guild invest', level=2)

        for badged, badge, button, label in (
                (gold, GUILD_INVEST_GOLD_BADGE, GUILD_BTN_INVEST_GOLD, 'gold 50000'),
                (token, GUILD_INVEST_TOKEN_BADGE, GUILD_BTN_INVEST_TOKEN, 'spirit coin 10'),
        ):
            if not badged:
                logger.info(f'Invest {label} is done for today')
                continue

            # Re-entered every round: dismissing a reward popup may take the
            # panel underneath with it, and the press has to land on the guild
            # page, not on whatever replaced it. Twice at most - a second press
            # on a spent row cannot spend anything, the daily cap is per row.
            for attempt in (1, 2):
                self.ui_goto(page_guild)
                self.guild_settle(page_guild.check_button)
                if self.guild_press(button, badge, f'invest {label}'):
                    break
                logger.warning(f'Invest {label}: attempt {attempt} did not land')
