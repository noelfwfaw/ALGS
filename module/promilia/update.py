"""Promilia client resource-update handling."""

import numpy as np

from module.base.timer import Timer
from module.base.utils import crop
from module.exception import GameStuckError
from module.logger import logger
from module.promilia.assets import (UPDATE_BACKGROUND_DOWNLOAD,
                                     UPDATE_DOWNLOADING, UPDATE_NOTICE_CONFIRM,
                                     UPDATE_NOTICE_EXIT, UPDATE_NOTICE_TITLE,
                                     UPDATE_RESOURCE_CHECK)
from module.promilia.page import page_main


UPDATE_BOOT_TIMEOUT = 240
UPDATE_DOWNLOAD_TIMEOUT = 60 * 60
UPDATE_DOWNLOAD_STALL = 5 * 60

# The percentage above the bar and the speed/size text below it change every
# frame. This band contains only the progress bar, so pixel movement is enough
# to detect progress without OCR or putting dynamic numbers in a template.
UPDATE_DOWNLOAD_PROGRESS_AREA = (350, 557, 1000, 589)
UPDATE_DOWNLOAD_PROGRESS_DIFF = 0.10


class PromiliaUpdate:
    """Handle the update prompt and wait out the client's resource download.

    Mixed into ``PromiliaUI``. The framework supplies ``appear()``,
    ``appear_then_click()`` and ``device``.
    """

    def app_start(self):
        """
        Launch the game and walk through update, login and loading to the main page.

        Pages:
            in: any
            out: page_main
        """
        super().app_start()
        self.handle_app_boot()

    def update_notice_visible(self):
        """Return whether any static part of the update notice is visible."""
        return any(self.appear(button, offset=(20, 20)) for button in (
            UPDATE_NOTICE_TITLE, UPDATE_NOTICE_EXIT, UPDATE_NOTICE_CONFIRM))

    def update_notice_appear(self):
        """Require the title and both dialog buttons before accepting the notice."""
        return (self.appear(UPDATE_NOTICE_TITLE, offset=(20, 20))
                and self.appear(UPDATE_NOTICE_EXIT, offset=(20, 20))
                and self.appear(UPDATE_NOTICE_CONFIRM, offset=(20, 20))
                and self._update_confirm_has_check())

    def _update_confirm_has_check(self):
        """Reject dark-background matches that lack the confirm button's green check."""
        x1, y1, _, _ = UPDATE_NOTICE_CONFIRM.button
        # Measured from the 1280x720 source: the check occupies x=807..828,
        # y=461..475 inside the confirm template whose origin is (782, 442).
        patch = crop(self.device.image, (x1 + 27, y1 + 18, x1 + 47, y1 + 34))
        red, green, blue = patch[:, :, 0], patch[:, :, 1], patch[:, :, 2]
        check = (green > 55) & (green > red * 1.2) & (green > blue * 1.05)
        return np.count_nonzero(check) >= 8

    def handle_update_notice(self):
        """
        Confirm the resource-update notice, never pressing 「退出」.

        Pages:
            in: any
            out: any

        Returns:
            bool: Whether this frame belongs to the update notice.
        """
        if not self.update_notice_appear():
            return False

        if self.appear_then_click(UPDATE_NOTICE_CONFIRM, offset=(20, 20), interval=3):
            logger.info('Promilia needs a resource update, press 确定')
        return True

    def update_downloading_appear(self):
        """Require both static download labels, excluding all dynamic numbers."""
        return (self.appear(UPDATE_DOWNLOADING, offset=(20, 20), similarity=0.90)
                and self.appear(UPDATE_BACKGROUND_DOWNLOAD, offset=(20, 20), similarity=0.90))

    def handle_update_downloading(self, skip_first_screenshot=True):
        """
        Wait for the resource download to finish without clicking.

        Pages:
            in: update notice or download screen
            out: any screen after the download

        Returns:
            bool: Whether a download was observed.

        Raises:
            GameStuckError: If progress stalls or the download exceeds its limit.
        """
        if not self.update_downloading_appear():
            return False

        logger.hr('Download Promilia resources', level=2)
        timeout = Timer(UPDATE_DOWNLOAD_TIMEOUT, count=3).start()
        stall = Timer(UPDATE_DOWNLOAD_STALL, count=3).start()
        report = Timer(30, count=2).start()
        last = self._download_progress()

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # The client drives this process and receives no clicks. Keep the
            # framework watchdog silent; the timers below own the real limits.
            self.device.stuck_record_clear()
            if not self.update_downloading_appear():
                logger.info('Promilia resource download finished')
                return True

            current = self._download_progress()
            difference = np.abs(current.astype(np.int16) - last.astype(np.int16)).mean()
            if difference > UPDATE_DOWNLOAD_PROGRESS_DIFF:
                stall.reset()
            last = current

            if report.reached_and_reset():
                logger.info('Waiting for Promilia resource download')
            if stall.reached():
                logger.warning('Promilia download progress stalled')
                raise GameStuckError('蓝色星原：旅谣 的资源下载五分钟没有进展，请检查网络。')
            if timeout.reached():
                logger.warning('Promilia download timeout')
                raise GameStuckError('蓝色星原：旅谣 的资源下载超过一小时仍未结束。')

    def _download_progress(self):
        """Return a copy of the dynamic progress-bar band for frame comparison."""
        return crop(self.device.image, UPDATE_DOWNLOAD_PROGRESS_AREA).copy()

    def handle_app_boot(self, skip_first_screenshot=True):
        """
        Walk through update, login and loading until the main page is visible.

        Pages:
            in: any
            out: page_main

        Raises:
            GameStuckError: If the client never reaches the main page.
        """
        logger.hr('App boot', level=2)
        timeout = Timer(UPDATE_BOOT_TIMEOUT, count=3).start()

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
                if not self.device.has_cached_image:
                    self.device.screenshot()
            else:
                self.device.screenshot()

            self.device.stuck_record_clear()

            if self.ui_page_appear(page_main):
                logger.info('Promilia reached page_main')
                return True
            if timeout.reached():
                logger.warning('Wait Promilia boot timeout')
                raise GameStuckError('Game did not reach page_main after launch')
            if self.handle_update_notice():
                continue
            if self.handle_update_downloading():
                # Download time has its own ceiling and must not consume the
                # ordinary boot allowance once the client moves on.
                timeout.reset()
                continue
            if self.appear(UPDATE_RESOURCE_CHECK, offset=(20, 20), similarity=0.90):
                continue
            if self.handle_login():
                continue
            if self.handle_loading():
                continue
