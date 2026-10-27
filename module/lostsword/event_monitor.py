"""Page checks, waits and input of the event (活动) tab.

Every helper here answers a question about the current screenshot, or waits for
that answer to change. They live apart from the flow in `event.py` because the
flow is about *what* the task does, while this is about *how* the game shows it:
the regions, the binary skip template and the adb tap are all details of this
particular screen.

Pages of this task:

    page_battle -- 活动 tab --> banner list      (no page object)
    banner list -- banner --> stage list         (no page object)
    stage list -- 选择 --> sortie page           (page_event_start)
    stage list -- 一键扫荡 --> sweep panel

The banner list, the stage list and the sortie page have no page object of their
own: each is recognised by a label in a known corner, and the banner list scrolls
so its labels move. That is why the checks below take the region they search in
instead of matching at a fixed point.
"""

import cv2
import numpy as np

from module.base.timer import Timer
from module.logger import logger
from module.lostsword.assets import (DUNGEON_CLEAR, EVENT_BTN_OK,
                                     EVENT_BTN_SELECT, EVENT_BTN_SKIP,
                                     EVENT_BTN_START, EVENT_TAB_SELECTED)
from module.lostsword.utils import match

# The state label under a banner. The labels are the only thing in this band, so
# scanning it finds every banner whatever the scroll is.
BANNER_STATE_BAND = (600, 628)
BANNER_STATE_LUMA = 95
BANNER_STATE_GAP = 14
BANNER_STATE_MIN_WIDTH = 40
# 探险完成 is red (mean ~(218, 96, 66), R/G 2.27); 可进入 / 可扫荡 are gold
# (mean ~(185, 164, 81), R/G 1.12). 1.6 sits between them.
BANNER_STATE_RED_RATIO = 1.6

# The bottom right button of the stage page and of the sortie page: 「选择」 and
# 「出发」 are drawn in the same place, only the label changes.
STAGE_BUTTON_REGION = (600, 610, 1280, 720)
STAGE_SELECT_REGION = (900, 610, 1280, 720)
STAGE_SWEEP_REGION = (600, 610, 900, 720)

# The result page of one cleared stage.
CLEAR_REGION = (450, 100, 850, 200)

# The cutscene skip button sits at the top right of every story scene. Binary
# matching: the button is drawn on a translucent plate, so its background follows
# the scene and plain colour matching scores 0.65~0.72 on a story scene against
# 0.15~0.20 everywhere else.
SKIP_REGION = (1100, 0, 1280, 80)
SKIP_THRESHOLD = 150
SKIP_SIMILARITY = 0.50

# The 确认 label of the one-line notices of this game (nothing ticked, no tries,
# stage already cleared). Matching it is needed because a bright scene (a beach, a
# snow field) fools any colour test of the button plate.
EVENT_NOTICE_REGION = (480, 430, 810, 510)

# The 活动 tab of the battle page, in its selected state.
EVENT_TAB_REGION = (1100, 60, 1280, 140)

# A label of this size is a button label, not a fleck of background.
MATCH_THRESHOLD = 0.85


class EventMonitor:
    """
    Detection and waiting for the event tab.

    The narrowest of the mixins: it needs nothing from the task class. Every
    method reads the current `self.device.image`, and the waits go through
    `self.loop()` / `wait_until_*()`, so it never takes a screenshot of its own
    that the framework would not have taken anyway.

    `EventSweep` builds on it; the task itself (`LostswordEvent`) does the
    walking and hands the sweep what it found.
    """

    # ---------------------------------------------------------------- detection

    def event_banners(self, image=None):
        """
        Find the banners of the event list by their state label.

        Scanning the label band instead of using fixed coordinates keeps this
        working when the list is scrolled or when a new event shows up.

        Args:
            image (np.ndarray): Screenshot to read. Defaults to the current one.

        Returns:
            list: [(centre_x, finished)], left to right.
        """
        image = (image if image is not None else self.device.image).astype(np.int16)
        y1, y2 = BANNER_STATE_BAND
        band = image[y1:y2]
        mask = band.mean(axis=2) > BANNER_STATE_LUMA
        columns = mask.sum(axis=0)
        found = np.nonzero(columns > 0)[0]
        if not len(found):
            return []

        runs = []
        start = prev = found[0]
        for x in found[1:]:
            if x - prev > BANNER_STATE_GAP:
                runs.append((start, prev + 1))
                start = x
            prev = x
        runs.append((start, prev + 1))

        banners = []
        for a, b in runs:
            if b - a < BANNER_STATE_MIN_WIDTH:
                continue
            pixels = band[:, a:b][mask[:, a:b]]
            mean = pixels.mean(axis=0)
            finished = mean[0] > mean[1] * BANNER_STATE_RED_RATIO
            banners.append(((a + b) // 2, finished))
            logger.attr('Banner', f'x={(a + b) // 2} '
                                  f'rgb=({mean[0]:.0f},{mean[1]:.0f},{mean[2]:.0f}) '
                                  f'{"探险完成, skip" if finished else "open"}')
        return banners

    def event_notice_appear(self):
        """
        Whether one of the one-line notices of the game is on screen.

        Returns:
            bool: If the 确认 label is there.
        """
        return match(self.device.image, EVENT_BTN_OK,
                     EVENT_NOTICE_REGION) > MATCH_THRESHOLD

    def clear_appear(self):
        """
        Whether the CLEAR result page of a stage is on screen.

        Returns:
            bool: If the CLEAR art is there.
        """
        return match(self.device.image, DUNGEON_CLEAR, CLEAR_REGION) > MATCH_THRESHOLD

    def on_stage_page(self):
        """
        Whether the stage selection page is on screen.

        Returns:
            bool: If the 「选择」 label is in its usual place.
        """
        return match(self.device.image, EVENT_BTN_SELECT,
                     STAGE_SELECT_REGION) > MATCH_THRESHOLD

    def on_sortie_page(self):
        """
        Whether the sortie page of a stage is on screen.

        Returns:
            bool: If the 「出发」 label is in its usual place.
        """
        return match(self.device.image, EVENT_BTN_START,
                     STAGE_SELECT_REGION) > MATCH_THRESHOLD

    def on_event_page(self):
        """
        Whether the event list is on screen.

        Returns:
            bool: If the 活动 tab is the selected one.
        """
        return match(self.device.image, EVENT_TAB_SELECTED,
                     EVENT_TAB_REGION) > MATCH_THRESHOLD

    def skip_appear(self):
        """
        Whether a story scene with a skip button is on screen.

        Returns:
            bool: If 「Skip」 is there.
        """
        EVENT_BTN_SKIP.ensure_template()
        x1, y1, x2, y2 = SKIP_REGION
        patch = cv2.cvtColor(self.device.image[y1:y2, x1:x2], cv2.COLOR_RGB2GRAY)
        template = cv2.cvtColor(EVENT_BTN_SKIP.image, cv2.COLOR_RGB2GRAY)
        if patch.shape[0] < template.shape[0] or patch.shape[1] < template.shape[1]:
            return False
        patch = (patch > SKIP_THRESHOLD).astype(np.uint8) * 255
        template = (template > SKIP_THRESHOLD).astype(np.uint8) * 255
        res = cv2.matchTemplate(patch, template, cv2.TM_CCOEFF_NORMED)
        return float(cv2.minMaxLoc(res)[1]) > SKIP_SIMILARITY

    # ------------------------------------------------------------------ waiting

    def event_wait(self, predicate, timeout=10, settle=1):
        """
        Poll a page predicate until it answers.

        Args:
            predicate (callable): Returns bool for the current screenshot.
            timeout (int, float): Seconds.
            settle (int): Consecutive frames the predicate has to hold, for the
                checks whose target fades in.

        Returns:
            bool: If the predicate answered.
        """
        timeout = Timer(timeout).start()
        present = 0

        for _ in self.loop():
            if predicate():
                present += 1
                if present >= settle:
                    return True
            else:
                present = 0
            if timeout.reached():
                return False

    def event_wait_gone(self, button, region, timeout=15):
        """
        Wait until a label leaves its region.

        Args:
            button (Button): Label to watch.
            region (tuple): Region it sits in.
            timeout (int, float): Seconds.

        Returns:
            bool: If it is gone.
        """
        return self.event_wait(lambda: match(self.device.image, button, region) < 0.75,
                               timeout=timeout, settle=2)

    def event_wait_title(self, button, timeout=6):
        """
        Wait until a popup title shows up anywhere on the screen.

        Args:
            button (Button): Title template.
            timeout (int, float): Seconds.

        Returns:
            bool: If it showed up.
        """
        return self.event_wait(
            lambda: match(self.device.image, button, (0, 0, 1280, 720)) > MATCH_THRESHOLD,
            timeout=timeout)
