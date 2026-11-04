import cv2
from module.base.timer import Timer
from module.base.utils import crop
from module.exception import GameStuckError
from module.hazeworld.assets import (BOOT_INIT_LOADING,
                                     EXIT_CONFIRM,
                                     LOGIN_ANNOUNCE,
                                     LOGIN_DOWNLOAD_CONFIRM,
                                     LOGIN_DOWNLOAD_NOTICE,
                                     LOGIN_SIGN_CLOSE,
                                     LOGIN_SIGN_IN,
                                     LOGIN_TOUCH_START)
from module.hazeworld.page import page_main
from module.logger import logger
from module.ocr.ocr import Ocr


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

# The resource-initialisation screen, shown while the client prepares its files
# after a launch (measured 2026-11-04: it sat there for minutes while a restart
# waited on it). Its only fixed part is the line 「初始化游戏资源中...」 over the
# bottom bar - the lore painting and the hints above it change per launch.
# Matched like the loading line, not OCR'd: 1.000 on the screen itself,
# 0.338 on the lobby and on the live session frame, threshold 0.70.
INIT_LOADING_REGION = (500, 640, 800, 715)


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


class Boot:
    """
    Launching the game and walking it up to the lobby.

    Mixed into `HazeworldUI`. The framework supplies `self.appear()`,
    `self.device` and `self.ui_page_appear()`; `self.handle_reward()` comes
    from `HazeworldUI` itself.
    """

    # Ceiling of one wait-out of the resource-initialisation screen, so a game
    # that never leaves it ends in the watchdog instead of hiding every frame
    # from it forever. The screen sat for minutes on the test box (2026-11-04),
    # so the ceiling is generous.
    INIT_LOADING_WAIT = Timer(600)

    # Rate limit of the back key used to close the sign-in panel. The same key
    # opens "确认退出?" on the title screen, see handle_sign_in().
    SIGN_IN_BACK = Timer(2)

    def handle_app_boot(self, skip_first_screenshot=True):
        """
        Walk through the boot screens: loading, announcement, title, and the
        download flow an outdated client inserts between them. The announcement
        only closes on the back key, so the key is rate limited and the
        "确认退出?" dialog it raises on the title screen is cancelled at once.

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

            # A cold start is minutes of screens that are never pressed, and
            # `Device` reads "nothing clicked for 60 seconds" as a hang. The
            # silence is expected; `timeout` below ends a stuck boot (hard rule:
            # a game-driven process clears the watchdog).
            self.device.stuck_record_clear()

            if self.ui_page_appear(page_main):
                logger.info('Game is at page_main')
                return True

            # Before the title screen check: both dialogs stay readable through
            # the screens behind them.
            if self.handle_exit_confirm():
                continue
            if self.handle_reward():
                continue
            if self.handle_sign_in():
                continue
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

            # The client may pass through its resource-initialisation screen
            # here; it sits for minutes and presses nothing. Checked before the
            # download OCR below, which it would never match.
            if self.handle_init_loading():
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

    def boot_init_loading(self):
        """
        Whether the client is on its resource-initialisation screen.

        The screen appears after a launch while the client prepares its files,
        and a restart that hits it reads every page as unknown. Only the line
        「初始化游戏资源中...」 over the bottom bar is fixed; matched like the
        loading line - 1.000 on the screen itself, 0.338 on the lobby.

        Returns:
            bool: If the screen is up.
        """
        return match_loading(self.device.image, BOOT_INIT_LOADING,
                             INIT_LOADING_REGION) > 0.70

    def handle_init_loading(self):
        """
        Wait out the resource-initialisation screen.

        The game prepares its files on its own and moves on when done, so
        nothing is pressed: the frame is only declared handled, which tells the
        `ui_goto` loops and the boot loop to keep waiting instead of reading
        the screen as unknown. The watchdog is cleared while the screen is up -
        a process the game walks through itself - and the ceiling comes from
        `INIT_LOADING_WAIT`, so a game that never leaves the screen ends in the
        watchdog after all.

        Pages:
            in: any
            out: any

        Returns:
            bool: If the screen is up and its wait has not run out yet.
        """
        if not self.boot_init_loading():
            self.INIT_LOADING_WAIT.clear()
            return False
        self.INIT_LOADING_WAIT.start()
        if self.INIT_LOADING_WAIT.reached():
            return False
        self.device.stuck_record_clear()
        return True
