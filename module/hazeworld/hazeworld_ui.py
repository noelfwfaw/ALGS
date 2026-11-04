from module.base.utils import get_color
from module.config.deep import deep_get
from module.hazeworld.assets import LOADING_TEXT, REWARD_POPUP, SUPPORT_REWARD
from module.hazeworld.boot import Boot, match_loading
from module.hazeworld.claim import Claim
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


class HazeworldUI(Claim, Boot, UI):
    """
    Shared UI base of every Hazeworld task.

    Provides the reward popup handler and, through `Claim`, the "claim all"
    loop, so each task module only describes which page and which button it
    uses. Launching the game and the screens it shows on the way is in `Boot`.
    """

    page_main = page_main

    # Own pages, in the order they are declared above. The registry is shared
    # with every other game, and their check points only exist in their own
    # asset namespace.
    pages = (page_main, page_task, page_pass, page_friend, page_mail,
             page_expedition, page_room, page_exercise, page_profile,
             page_support, page_battle_resource, page_battle, page_core)

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

        A panel whose task is enabled in the scheduler is skipped here: the
        scheduled `HazeworldTask` / `HazeworldPass` run covers it on their own
        cadence (the four CLAIM_TIMES), and claiming it again at the end of
        every session would re-walk the same panels right after the scheduler
        just did. The hook only backs the panels up when the user has their
        tasks turned off - then there is nothing else that would claim them.

        A failure here is logged and swallowed: both panels are entered from the
        lobby again next session.

        Returns:
            bool: If both claims ran without an exception.
        """
        from module.hazeworld.battle_pass import HazeworldPass
        from module.hazeworld.task import HazeworldTask

        logger.hr('Session claims', level=2)
        ok = True
        if deep_get(self.config.data, 'HazeworldTask.Scheduler.Enable', default=False):
            logger.info('HazeworldTask is scheduled, session claim skips the mission list')
        else:
            try:
                claimed = HazeworldTask(config=self.config, device=self.device).task_claim()
                logger.info(f'Tasks claimed: {claimed}')
            except Exception as e:
                logger.warning(f'Task claim failed, ignored: {e}')
                ok = False
        if deep_get(self.config.data, 'HazeworldPass.Scheduler.Enable', default=False):
            logger.info('HazeworldPass is scheduled, session claim skips the battle pass')
        else:
            try:
                claimed = HazeworldPass(config=self.config, device=self.device).pass_claim()
                logger.info(f'Pass claimed: {claimed}')
            except Exception as e:
                logger.warning(f'Battle pass claim failed, ignored: {e}')
                ok = False
        return ok

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

        The resource-initialisation screen is checked last: it costs a template
        match on every frame of every task, and it only ever shows right after
        a launch (measured 2026-11-04: a `ui_goto` died on it 60 seconds in
        because the screen came up after the boot had already seen the lobby).

        Returns:
            bool: If handled.
        """
        if self.handle_exit_confirm():
            return True
        if self.handle_reward():
            return True
        return self.handle_init_loading()

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
