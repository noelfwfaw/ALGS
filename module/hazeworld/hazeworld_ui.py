import cv2
from module.base.timer import Timer
from module.base.utils import crop, get_color
from module.exception import GameStuckError
from module.hazeworld.assets import (LOADING_TEXT,
                                     EXIT_CONFIRM,
                                     LOGIN_ANNOUNCE,
                                     LOGIN_DOWNLOAD_CONFIRM,
                                     LOGIN_DOWNLOAD_NOTICE,
                                     LOGIN_SIGN_CLOSE,
                                     LOGIN_SIGN_IN,
                                     LOGIN_TOUCH_START,
                                     REWARD_POPUP,
                                     SUPPORT_REWARD)
from module.hazeworld.claim import Claim
from module.logger import logger
from module.ocr.ocr import Ocr
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


# A client update makes the game ask before it fills the disk:
#
#     「游戏需要下载额外2.38 GB资源」  [取消] [确认]
#
# 「取消」 drops back to the title screen and asks again on the next launch,
# so the only useful answer is 「确认」. Once it is pressed the dialog gives way
# to a download screen that says, over the bottom bar:
#
#     「正在下载资源…(1.04 GB/2.38 GB)」
#
# That line is the only thing that tells a download apart from a stalled
# loading screen: the background behind it is one of the rotating lore
# paintings and the progress bar at the left edge is drawn with the accent
# colour of the week. The numbers change every frame, so the line is OCR'd
# rather than matched - and since the model eats the ellipsis and the spaces
# ("正在下载资源(1.04GB/2.38GB)"), only "下载" and the two numbers are used.
BOOT_DOWNLOAD_AREA = (460, 675, 840, 710)
BOOT_DOWNLOAD_THRESHOLD = 140

# Downloading 2.38 GB took eight minutes on the test box (about 5 MB/s), so the
# 240 seconds of the boot loop are not enough. This is the download's own
# ceiling; the boot timer is reset once the download is over, so the time spent
# here does not count as a boot failure.
BOOT_DOWNLOAD_TIMEOUT = 60 * 60

# A progress number that does not move for this long means the connection died.
# The game does not retry on its own, so this raises instead of waiting forever.
BOOT_DOWNLOAD_STALL = 5 * 60


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


class HazeworldUI(Claim, UI):
    """
    Shared UI base of every Hazeworld task.

    Provides the reward popup handler and, through `Claim`, the "claim all"
    loop, so each task module only describes which page and which button it
    uses.
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

        When the client has an update waiting, the game inserts two more screens
        between the loading screen and the title: 「游戏需要下载额外X GB资源」
        with 取消 / 确认, and then the download itself. See
        `handle_download_notice()` and `handle_downloading()`.

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

            # Also before the title screen: the dialog sits on top of it and the
            # title is still readable through the dimming.
            if self.handle_download_notice():
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

            # Last, because it costs an OCR call: none of the checks above can
            # match while a download is running (measured), so reaching this
            # point on a download screen means everything else was a miss.
            if self.handle_downloading():
                # The download took minutes; without this the loop would leave
                # on the next timeout check, right after a successful download.
                timeout.reset()
                continue

            if timeout.reached():
                logger.warning('Wait game boot timeout')
                raise GameStuckError('Game did not reach page_main after launch')

    def handle_download_notice(self):
        """
        Answer the 「游戏需要下载额外X GB资源」 dialog with 「确认」.

        「取消」 is never pressed: it goes back to the title screen and the same
        dialog waits there on the next launch, so nothing would ever get past
        it. The button is pressed at most once every three seconds; a press
        that the fade-in swallows is repeated on the next screenshot rather
        than by hammering.

        Pages:
            in: any
            out: any

        Returns:
            bool: If handled.
        """
        if self.appear(LOGIN_DOWNLOAD_NOTICE, offset=(20, 20)):
            if self.appear_then_click(LOGIN_DOWNLOAD_CONFIRM, offset=(20, 20), interval=3):
                logger.info('Client needs a resource pack, press 确认 to download it')
            return True

        return False

    def handle_downloading(self):
        """
        Wait out a resource download.

        Nothing is clicked here: once 「确认」 has been given the game downloads
        on its own and moves on by itself when the pack is complete. What is
        watched is the progress line - the loop ends the moment that line is
        gone, which is either the client restarting or the title screen coming
        up. Both are handled by the caller's boot loop.

        Pages:
            in: any
            out: any

        Returns:
            bool: If a download was running.
        """
        status = self.boot_download_status()
        if status is None:
            return False

        logger.hr('Download resources', level=2)
        done, total = status
        if total > 0:
            logger.info(f'Downloading resources, {done:.0f} MB of {total:.0f} MB')

        timeout = Timer(BOOT_DOWNLOAD_TIMEOUT, count=3).start()
        stall = Timer(BOOT_DOWNLOAD_STALL, count=3).start()
        report = Timer(30, count=2).start()
        last = done

        while 1:
            self.device.screenshot()
            # A download takes minutes and presses nothing, so the framework's
            # "nothing clicked for 60 seconds" watchdog fires on it. Say out
            # loud that the screen is being watched (hard rule 13).
            self.device.stuck_record_clear()

            status = self.boot_download_status()
            if status is None:
                logger.info('Download finished')
                return True

            done, total = status
            # The line is there but the numbers came back unreadable: still a
            # download, just one that cannot be told apart from a stalled one,
            # so only the overall timeout applies.
            if total > 0 and done > last:
                last = done
                stall.reset()

            if report.reached_and_reset():
                logger.info(f'Downloading resources, {done:.0f} MB of {total:.0f} MB')

            if stall.reached():
                logger.warning(f'Download has not moved for {BOOT_DOWNLOAD_STALL} seconds')
                raise GameStuckError(
                    '苍雾世界 卡在资源下载上，进度五分钟没动。游戏自己不会重试，'
                    '请检查模拟器网络，让它下完再重跑。')
            if timeout.reached():
                logger.warning('Download timeout')
                raise GameStuckError(
                    '苍雾世界 的资源下载超过一小时还没结束。'
                    '请手动让游戏下完，或者换个网络重跑。')

    def boot_download_status(self):
        """
        Read the download line the game draws over the bottom bar.

        「正在下载资源…(1.04 GB/2.38 GB)」 is OCR'd, not matched: the numbers
        change every frame. The model drops the ellipsis and the spaces, and it
        reads the G of GB as a 6 often enough to matter (measured:
        「正在下载资源(1.446B/2.38GB)」), so the text can only be recognised by
        the word 「下载」 and the sizes are parsed tolerantly.

        Returns:
            tuple[float, float] | None:
                (downloaded, total) in MB; `(0, 0)` when the line is there but
                its numbers are unreadable; None when there is no download
                line at all.
        """
        ocr = Ocr([], lang='cnocr', letter=(255, 255, 255),
                  threshold=BOOT_DOWNLOAD_THRESHOLD)
        ocr.SHOW_LOG = False
        text = ocr.ocr([crop(self.device.image, BOOT_DOWNLOAD_AREA)], direct_ocr=True)[0]
        if '下载' not in text:
            return None

        halves = text.split('(')[-1].split('/')
        if len(halves) != 2:
            return 0, 0

        done = self.boot_parse_size(halves[0])
        total = self.boot_parse_size(halves[1].rstrip(')'))
        if done is None or total is None:
            return 0, 0

        return done, total

    @staticmethod
    def boot_parse_size(note):
        """
        Read one size off the download line, in megabytes.

        「938.15MB」, 「2.38GB」 and the misread 「1.446B」 all end with two
        characters of unit and the number never does, so the last two are cut
        off instead of letting a regex decide where the digits stop - it would
        swallow the 6 of a misread G into the number.

        Args:
            note (str): Such as 「938.15MB」.

        Returns:
            float | None: Megabytes, or None when the unit is not recognised.
        """
        note = note.replace(' ', '').upper()
        if len(note) < 3:
            return None

        number, unit = note[:-2], note[-2:]
        try:
            value = float(number)
        except ValueError:
            return None

        if unit[0] in 'G6':
            return value * 1024
        if unit[0] == 'M':
            return value
        return None

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
