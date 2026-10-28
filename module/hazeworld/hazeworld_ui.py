import cv2
from module.base.timer import Timer
from module.base.utils import get_color
from module.exception import GameStuckError
from module.hazeworld.assets import (LOADING_TEXT,
                                     EXIT_CONFIRM,
                                     LOGIN_ANNOUNCE,
                                     LOGIN_SIGN_CLOSE,
                                     LOGIN_SIGN_IN,
                                     LOGIN_TOUCH_START,
                                     REWARD_POPUP,
                                     SUPPORT_REWARD)
from module.logger import logger
from module.ui.ui import UI

from module.hazeworld.page import *  # noqa: F401,F403 - re-exported for the tasks



# The mission page and the battle pass do not only refresh at the daily reset:
# they hand out new missions while the player is in game, and a finished mission
# stays on the list until it is claimed. Checking once at the server update
# would leave a whole day of missions unclaimed, so both tasks go in on these
# four openings instead of on the daily one.
#
# The format is the one `Scheduler.ServerUpdate` uses, which makes
# `task_delay(server_update=CLAIM_TIMES)` pick the nearest of the four, roll
# over to the next day on its own and apply the server timezone.
CLAIM_TIMES = ['05:00', '12:00', '18:00', '23:00']


# The 「LOADING......」 line the game draws over the bottom bar while a page is
# coming up. It is plain white text on whatever the page behind it is, so the
# only stable thing about it is the glyphs themselves - a colour or mean-luma
# test would fire on every bright page. Matching the binary shape of the text
# scores 1.00 on the loading screen and 0.15~0.22 everywhere else (measured
# against other screens), which is why it is matched rather than OCR'd: the
# built-in OCR models read this font as 「L2ABIN」 / 「CLADINK」.
LOADING_REGION = (500, 640, 780, 715)


def match_loading(image, button, region):
    """
    Template match a button inside a region.

    `Button.match()` has its arguments the wrong way round (it searches the
    template for the screenshot), so it only works when both are the same size.
    This helper does it the right way and only looks at a narrow region.

    Args:
        image (np.ndarray): Screenshot.
        button (Button): Template to look for.
        region (tuple): (x1, y1, x2, y2) to search in.

    Returns:
        float: Similarity of the best match, 0 when the region is too small.
    """
    button.ensure_template()
    template = button.image
    x1, y1, x2, y2 = region
    patch = image[max(0, y1):min(image.shape[0], y2),
                  max(0, x1):min(image.shape[1], x2)]
    if patch.shape[0] < template.shape[0] or patch.shape[1] < template.shape[1]:
        return 0.0
    res = cv2.matchTemplate(patch, template, cv2.TM_CCOEFF_NORMED)
    return float(cv2.minMaxLoc(res)[1])


class HazeworldUI(UI):
    """
    Shared UI base of every Hazeworld task.

    Provides the reward popup handler and the "claim all" loop, so each task
    module only describes which page and which button it uses.
    """

    page_main = page_main

    # Own pages, in the order they are declared above. The registry is shared
    # with every other game, and their check points only exist in their own
    # asset namespace.
    pages = (page_main, page_task, page_pass, page_friend, page_mail,
             page_expedition, page_room, page_exercise, page_profile,
             page_support, page_battle_resource, page_battle, page_core)

    # Rate limit of the back key used to close the sign-in panel. The same key
    # opens "确认退出?" on the title screen, see handle_sign_in().
    SIGN_IN_BACK = Timer(2)

    def ui_loading_appear(self):
        """
        Whether the game is drawing its loading line.

        The threshold has to stay high: the template is white glyphs, so any
        bright page with fine light lines drifts towards it. Lowering it to 0.45
        to also catch a half faded line made the lobby read as loading (0.473),
        and every `ui_goto` then waited for a loading screen that never ended.
        A half faded line is not worth that trade - callers that need a repaint
        to finish wait for the popup that comes with it instead.

        Returns:
            bool: If 「LOADING......」 is over the bottom bar.
        """
        return match_loading(self.device.image, LOADING_TEXT,
                             LOADING_REGION) > 0.80

    def app_start(self):
        """
        Launch the game and walk through the boot screens until page_main.

        A running game must not be launched again: `am start` only brings it to
        front, so the boot loop below would wait for a title screen that never
        appears and die on a stuck check. If it runs but is not on any known
        page, it is stopped first so a cold boot is guaranteed.

        The mission rewards and the battle pass are *not* claimed here, see
        `handle_session_claim()`.

        Pages:
            in: any
            out: page_main
        """
        if self.device.app_is_running():
            if self.ui_any_page_appear():
                logger.info('Game is running, walk to page_main')
                self.ui_goto_main()
                return
            logger.info('Game is running on an unknown page, restart it')
            self.device.app_stop()

        self.device.app_start()
        self.handle_app_boot()

    def handle_session_claim(self):
        """
        Claim the mission rewards and the battle pass, once per game session.

        Called by the scheduler when the queue runs dry, i.e. after every queued
        task of this session has been run, never at launch: the two panels are
        worth nothing compared to the tasks the user queued, and claiming them
        first would park the whole session behind them.

        Both also keep a slot of their own in the scheduler, last in the
        priority list, which covers the long sessions where the queue never runs
        dry and this hook is not reached.

        A failure here is logged and swallowed: both panels are entered from the
        lobby again next session.

        Returns:
            bool: If both claims ran without an exception.
        """
        from module.hazeworld.battle_pass import HazeworldPass
        from module.hazeworld.task import HazeworldTask

        logger.hr('Session claims', level=2)
        ok = True
        try:
            claimed = HazeworldTask(config=self.config, device=self.device).task_claim()
            logger.info(f'Tasks claimed: {claimed}')
        except Exception as e:
            logger.warning(f'Task claim failed, ignored: {e}')
            ok = False
        try:
            claimed = HazeworldPass(config=self.config, device=self.device).pass_claim()
            logger.info(f'Pass claimed: {claimed}')
        except Exception as e:
            logger.warning(f'Battle pass claim failed, ignored: {e}')
            ok = False
        return ok

    def handle_app_boot(self, skip_first_screenshot=True):
        """
        Walk through the boot screens.

        A cold start shows a loading screen with lore text, then a full screen
        announcement that has to be dismissed, then the title screen waiting for
        a tap. Loading alone takes about 30 seconds, so the timeout is generous.

        The announcement only closes on the back key, but the back key on the
        title screen opens the "确认退出?" dialog, which logs the account out on
        the next launch when it is confirmed. So the key is sent at most once
        every two seconds and only while the announcement is on screen, and the
        dialog is cancelled the moment it shows up.

        Pages:
            in: any
            out: page_main

        Returns:
            bool: True if page_main is reached.

        Raises:
            GameStuckError: If the game does not reach page_main in time.
        """
        logger.hr('App boot', level=2)
        timeout = Timer(240, count=3).start()
        back = Timer(2)

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
                if not self.device.has_cached_image:
                    self.device.screenshot()
            else:
                self.device.screenshot()

            # End
            if self.ui_page_appear(page_main):
                logger.info('Game is at page_main')
                return True

            # Must come before the title screen check, the title stays readable
            # behind this dialog.
            if self.handle_exit_confirm():
                continue

            # Reward popups of the sign-in below, and of anything the game
            # decides to hand out on login.
            if self.handle_reward():
                continue

            # The monthly sign-in panel opens over the lobby on the first launch
            # of a day. Nothing else in this loop matches it, so without this the
            # boot dies on a stuck check 60 seconds in.
            if self.handle_sign_in():
                continue

            # Announcement is a modal over the title screen, back dismisses it.
            # Only pressed on the positive condition, never on the main page.
            if self.appear(LOGIN_ANNOUNCE, offset=(20, 20)):
                if back.reached_and_reset():
                    logger.info('Announcement popup, dismiss it')
                    self.device.adb_shell(['input', 'keyevent', '4'])
                continue

            if self.appear_then_click(LOGIN_TOUCH_START, offset=(20, 20), interval=3):
                logger.info('Title screen, touch to start')
                continue

            if timeout.reached():
                logger.warning('Wait game boot timeout')
                raise GameStuckError('Game did not reach page_main after launch')

    def handle_exit_confirm(self):
        """
        Cancel the "确认退出?" dialog, which the back key opens.

        Confirming it quits the game and the next launch asks for the account
        again, so only "取消" is ever clicked.

        Pages:
            in: any
            out: any

        Returns:
            bool: If handled.
        """
        if self.appear(EXIT_CONFIRM, offset=(20, 20)):
            logger.info('Exit confirm dialog, cancel it')
            self.device.click(EXIT_CONFIRM)
            return True

        return False

    def handle_sign_in(self):
        """
        Claim and close the monthly sign-in panel.

        The panel opens over the lobby on the first launch of a day and stays
        until it is dismissed. 「点击签到」 is clicked first: it turns into
        「已签到」 once the day is taken, so the close branch only runs after the
        claim, never instead of it.

        The panel draws a "◀" in its corner, but it is decoration and tapping it
        does nothing (verified). The back key closes the panel instead. It is
        only sent while the panel is on screen and it is rate limited, because
        on the title screen the same key opens "确认退出?", which logs the account
        out if confirmed; `handle_exit_confirm()` runs before this in the boot
        loop and cancels that dialog.

        Pages:
            in: any
            out: any

        Returns:
            bool: If handled.
        """
        if self.appear_then_click(LOGIN_SIGN_IN, offset=(20, 20), interval=3):
            logger.info('Monthly sign-in, claim it')
            return True

        if self.appear(LOGIN_SIGN_CLOSE, offset=(10, 10)):
            if self.SIGN_IN_BACK.reached_and_reset():
                logger.info('Monthly sign-in, close it')
                self.device.adb_shell(['input', 'keyevent', '4'])
            return True

        return False

    def handle_reward(self):
        """
        Close the "获得资源" popup, which asks to tap anywhere to exit.

        The popup is drawn the same way everywhere, but what is behind it is
        not: the room dims the whole page, the mission page draws the popup on
        a bright band, and the battle pass page has a light patch at the point
        that used to be compared. A mean colour check therefore fired on the
        pass page on every screenshot, so the title glyphs are matched instead.
        Measured: 0.996 to 1.0 with the popup, 0.19 to 0.51 without it.

        The tap lands on the title row. The items are drawn below it, and
        tapping an item opens its detail panel, which nothing would close.

        Pages:
            in: any
            out: any

        Returns:
            bool: If handled.
        """
        if self.appear(REWARD_POPUP, offset=(20, 20), similarity=0.9):
            logger.info('Reward popup, touch to exit')
            self.device.click(REWARD_POPUP)
            return True

        return False

    def handle_support_reward(self):
        """
        Close the reward popup of the support character panel.

        It is the same "获得资源" popup as `handle_reward()`, but the panel
        behind it draws a reward of its own at the same place, so it is checked
        before the generic one and tapped at its own blank corner.

        Pages:
            in: any
            out: any

        Returns:
            bool: If handled.
        """
        if self.appear(SUPPORT_REWARD, offset=(20, 20)):
            logger.info('Support reward popup, touch to exit')
            self.device.click(SUPPORT_REWARD)
            return True

        return False

    def ui_additional(self):
        """
        Popups that may appear on any page.

        Returns:
            bool: If handled.
        """
        if self.handle_exit_confirm():
            return True
        return self.handle_reward()

    def button_saturated(self, button, threshold=40):
        """
        Whether a button area is drawn in a strong colour.

        Hazeworld paints the same button in the theme colour of the context: the
        claim button of the mission page is orange on the daily tab and blue on
        the weekly one, the buttons of the expedition panel follow the selected
        expedition. No single colour in an asset covers them, but an active
        button is always saturated while a disabled one is plain grey.

        Args:
            button (Button): The button to measure.
            threshold (int): Colour spread of a saturated fill.

        Returns:
            bool: If the area is saturated.
        """
        color = get_color(self.device.image, button.area)
        return max(color) - min(color) > threshold

    def claim_all(self, claim, disabled=None, max_click=20, wait=0, available=None,
                  skip_first_screenshot=True):
        """
        Click the "claim all" button until there is nothing left to claim.

        Args:
            claim (Button): Claim all button, only matches when it is clickable.
            disabled (Button): The same button in disabled state, used as the
                positive exit condition. None to exit when `claim` disappears.
            max_click (int): Safety limit, to avoid clicking forever.
            wait (int, float): Seconds to keep looking for `claim` before the
                disabled state is accepted. Needed after a tab switch, see
                `HazeworldTask`.
            available (callable): Decides "there is something to claim" instead
                of `appear(claim)`. Needed when no single colour describes the
                button, see `HazeworldTask.task_claim_available`.
            skip_first_screenshot (bool):

        Returns:
            int: Times clicked.
        """
        count = 0
        # Just after a tab switch the button still shows the previous tab, so a
        # disabled button is only believed after `wait` seconds without the
        # clickable one showing up. Zero keeps the plain behaviour.
        settle = Timer(wait).start() if wait else None

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handle_reward():
                continue

            if disabled is not None and self.appear(disabled, offset=None):
                if settle is not None and not settle.reached():
                    continue
                logger.info('Nothing left to claim')
                break

            if available is not None:
                clickable = available()
            else:
                clickable = self.appear(claim, offset=None)

            if clickable:
                if count >= max_click:
                    logger.warning(f'Claim all clicked {count} times, stop')
                    break
                logger.info(f'Claim all ({count + 1})')
                # Only one of the two judgements may decide the press. When
                # `available` is given it already answered "the button is
                # there" with a measure the asset can support (a colour spread,
                # a label match). Asking the template afterwards is a second,
                # stricter opinion that some assets can never give: the stored
                # crop of `PASS_CLAIM_ALL` is its disabled look, so a match
                # refuses the very frame that says click me, and the loop then
                # counted twenty presses without sending one.
                if available is not None or self.appear(claim, offset=(20, 20)):
                    self.device.click(claim)
                count += 1
                # The page is obviously the right one now, no need to wait for
                # the disabled state any more.
                settle = None
                continue

            # Neither the clickable nor the disabled button is on screen. That
            # is not a verdict while the settle window is open: right after a
            # tab switch the list is still sliding and both states read as
            # absent, which used to end the loop after a single frame and skip
            # the whole tab. Keep looking until the window closes.
            if settle is not None and not settle.reached():
                continue
            break

        logger.info(f'Claim all finished, clicked {count} times')
        return count
