"""The event (活动) tab of the battle page.

Layout:

    战斗 --顶部「活动」页签--> 活动列表
    活动列表: a row of banners, each with a state label underneath
              (可进入 / 可扫荡 in gold, 探险完成 in red)
    活动列表 --banner--> 关卡选择页
              left: the stage list, right: 一键扫荡 / 扫荡 x/y / 选择
    关卡选择页 --「选择」--> 编队页 --「出发」--> 开荒
              story and battles are all automatic, a cleared stage sends the
              game to the next one 5 seconds later, and the run only ends when
              every stage is done or the team loses - either way the stage page
              comes back
    关卡选择页 --「一键扫荡」--> 「已获得道具。」--> 关掉 --> X 退出

The banners are found by their state labels rather than by fixed coordinates:
the list scrolls and the number of events changes. The label colour tells
whether an event is finished (red 探险完成, nothing to do) or still has stages
to clear or sweep (gold).
"""

import cv2
import numpy as np

from module.base.button import Button
from module.base.timer import Timer
from module.exception import GameStuckError
from module.logger import logger
from module.lostsword.assets import (COPY_BTN_SELECT_ALL, COPY_BTN_SWEEP_ALL,
                                     DUNGEON_BTN_BACK, DUNGEON_CLEAR,
                                     EVENT_BTN_OK, EVENT_BTN_SELECT,
                                     EVENT_BTN_SKIP, EVENT_BTN_START,
                                     EVENT_BTN_SWEEP_ALL, EVENT_TAB_SELECTED,
                                     REWARD_POPUP_TITLE)
from module.lostsword.lostsword_ui import (LostswordUI, page_battle, page_event,
                                           page_event_start, page_event_stage)

# The state label under a banner, in screen coordinates. The labels are the only
# thing in this band, so scanning it finds every banner whatever the scroll is.
BANNER_STATE_BAND = (600, 628)
BANNER_STATE_LUMA = 95
BANNER_STATE_GAP = 14
BANNER_STATE_MIN_WIDTH = 40
# 探险完成 is red (mean ~(218, 96, 66), R/G 2.27); 可进入 / 可扫荡 are gold
# (mean ~(185, 164, 81), R/G 1.12). 1.6 sits between them.
BANNER_STATE_RED_RATIO = 1.6
# The banners span the content area; the label is under them.
BANNER_PRESS_Y = 350

# The bottom right button of the stage page and of the sortie page: 「选择」 and
# 「出发」 are drawn in the same place, only the label changes. The asset of the
# label is centred on its left half, so the press goes to the plate itself.
STAGE_BUTTON_POINT = (1132, 658)
STAGE_BUTTON_REGION = (600, 610, 1280, 720)
STAGE_SELECT_REGION = (900, 610, 1280, 720)
STAGE_SWEEP_REGION = (600, 610, 900, 720)

# The result page of one cleared stage. The same art the squad dungeon uses; the
# 5 second auto advance of a mid-event stage is much shorter than this.
CLEAR_REGION = (450, 100, 850, 200)
CLEAR_HOLD = 8

# The cutscene skip button sits at the top right of every story scene.
SKIP_POINT = (1180, 37)
SKIP_REGION = (1100, 0, 1280, 80)
# Binary matching: the button is drawn on a translucent plate, so its
# background follows the scene and plain colour matching scores 0.65~0.72 on a
# story scene against 0.15~0.20 everywhere else.
SKIP_THRESHOLD = 150
SKIP_SIMILARITY = 0.50

# The 确认 button of the small notices of this game (nothing ticked, no tries,
# stage already cleared); they all use the same box in the middle of the screen.
EVENT_DIALOG_CONFIRM = (504, 450, 788, 486)
EVENT_DIALOG_OK = (644, 468)
# The 确认 label of that notice. Matching it is needed because a bright scene
# (a beach, a snow field) fools any colour test of the button plate.
EVENT_NOTICE_REGION = (480, 430, 810, 510)

# A clear run takes a minute or two per stage and an event can hold a dozen of
# them (measured: a half finished event went from stage 3 to stage 11 in one run
# of about 15 minutes).
EVENT_CLEAR_TIMEOUT = 3000


def match(image, button, region):
    """
    Template match a button inside a region.

    `Button.match()` calls `cv2.matchTemplate(self.image, crop(image, ...))`,
    with the template and the screenshot the wrong way round, so it only works
    when both have the same size. This helper does it the right way round and
    searches a narrow region, which keeps a generic label such as 「选择」 from
    matching somewhere else on the screen.

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
    x1, y1 = max(0, int(x1)), max(0, int(y1))
    x2, y2 = min(image.shape[1], int(x2)), min(image.shape[0], int(y2))
    patch = image[y1:y2, x1:x2]
    if patch.shape[0] < template.shape[0] or patch.shape[1] < template.shape[1]:
        return 0.0
    res = cv2.matchTemplate(patch, template, cv2.TM_CCOEFF_NORMED)
    return float(cv2.minMaxLoc(res)[1])


class LostswordEvent(LostswordUI):
    def run(self):
        logger.hr('Event', level=1)
        self.ui_ensure(page_battle)
        self.battle_goto_normal()
        self.ui_ensure(page_event)

        banners = self.event_banners()
        if not banners:
            logger.warning('No event banner found')
            self.ui_goto_main()
            self.config.task_delay(server_update=True)
            return

        cleared = 0
        for x, finished in banners:
            if finished:
                continue
            if not self.event_enter(x):
                logger.warning(f'Banner at x={x}: could not open')
                continue
            if self.event_clear():
                cleared += 1
            else:
                # The event was cleared on an earlier day and the sortie page
                # refuses to start, so the stage page has to be walked into
                # again before the sweep buttons exist.
                self.event_back()
                if not self.event_enter(x):
                    continue
            self.event_sweep()
            self.event_back()

        logger.info(f'Event stages cleared: {cleared}')
        self.ui_goto_main()
        # The sweep tries reset at the daily reset of this game (00:00).
        self.config.task_delay(server_update=True)

    # ------------------------------------------------------------------ banner

    def event_banners(self):
        """
        Find the banners of the event list by their state label.

        Scanning the label band instead of using fixed coordinates keeps this
        working when the list is scrolled or when a new event shows up.

        Returns:
            list: [(centre_x, finished)], left to right.
        """
        image = self.device.image.astype(np.int16)
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

    def event_enter(self, x, timeout=10):
        """
        Open one event from the list.

        Pages:
            in: page_event
            out: page_event_stage

        Args:
            x (int): Centre x of the banner.
            timeout (int, float): Seconds to wait for the stage page.

        Returns:
            bool: If the stage page opened.
        """
        logger.hr(f'Event at x={x}', level=2)
        for attempt in range(3):
            self.tap_point(x, BANNER_PRESS_Y)
            if self.wait_page(page_event_stage, timeout=timeout):
                return True
            # The game remembers where the event was left: opening it again may
            # land on the sortie page of the last stage instead of its stage
            # list. One X is enough to go back down.
            self.device.screenshot()
            if match(self.device.image, EVENT_BTN_START,
                     STAGE_SELECT_REGION) > 0.85:
                logger.info('Landed on the sortie page, go back to the stage list')
                self.tap_point(1237, 32)
                self.device.sleep(2.5)
                if self.wait_page(page_event_stage, timeout=timeout):
                    return True
            logger.info('Stage page did not open, press the banner again')
            self.device.sleep(1)
        return False

    # ------------------------------------------------------------------- clear

    def event_clear(self):
        """
        Clear every stage of the open event.

        「选择」 opens the sortie page, 「出发」 starts the run. From there the
        game does everything itself: story, battle, and 5 seconds after a stage
        is cleared it moves on to the next one. The run ends when the stage page
        is back, either because every stage is done or because the team lost.

        Pages:
            in: page_event_stage
            out: page_event_stage

        Returns:
            bool: If the stage page is back.
        """
        logger.hr('Clear stages', level=2)
        if not self.press_until_gone(STAGE_BUTTON_POINT, page_event_start,
                                     EVENT_BTN_START, STAGE_SELECT_REGION, '选择'):
            return False

        self.tap_point(*STAGE_BUTTON_POINT)
        self.device.sleep(4)
        self.device.screenshot()
        if self.event_notice_appear():
            # The sortie never started, so the game answered the press with a
            # notice instead - 「已通关。」 when every stage of the event is
            # already cleared. There is nothing to clear then.
            logger.info('The sortie did not start, every stage of this event is done')
            self.tap_point(*EVENT_DIALOG_OK)
            self.device.sleep(1.5)
            self.tap_point(*EVENT_DIALOG_OK)
            self.device.sleep(1)
            return False
        if not self.wait_gone(EVENT_BTN_START, STAGE_SELECT_REGION, timeout=15):
            logger.warning('The sortie did not start')
            return False
        self.device.sleep(1)

        if not self.wait_stage_page():
            raise GameStuckError('Event clear did not end in time')
        return True

    def wait_stage_page(self, timeout=EVENT_CLEAR_TIMEOUT):
        """
        Wait until the stage selection page comes back.

        The whole story and battle run happens in between, so the only thing to
        do is to press 「Skip」 on the story scenes. A stage that is cleared
        sends the game to the next one by itself, so nothing else is pressed -
        the CLEAR page has a 「返回」 button right where a fight would end, and
        pressing it would leave the run.

        Returns:
            bool: If the stage page is back.
        """
        timeout = Timer(timeout).start()
        report = Timer(120).start()
        skip_retry = Timer(2).start()
        clear_hold = Timer(CLEAR_HOLD).start()
        while 1:
            self.device.stuck_record_clear()
            self.device.screenshot()

            if self.on_stage_page():
                logger.info('Back at the stage page, the run is over')
                return True

            # The last stage of an event does not advance by itself: it parks on
            # the CLEAR page, where only 「返回」 leaves. A mid-event stage leaves
            # that page 5 seconds later, so a page that is still up after 8
            # seconds is the end of the run.
            if self.clear_appear():
                if clear_hold.reached():
                    logger.info('CLEAR page is holding, press 返回')
                    self.tap_asset(DUNGEON_BTN_BACK)
                    clear_hold.reset()
                    self.device.sleep(2)
                    continue
            else:
                clear_hold.reset()

            if self.skip_appear():
                if skip_retry.reached():
                    skip_retry.reset()
                    self.tap_point(*SKIP_POINT)
                    logger.info('Skip the story')
            elif report.reached():
                report.reset()
                logger.info(f'Still clearing, {int(timeout.current_time())}s left')

            if timeout.reached():
                logger.warning('The clear run did not come back to the stage page')
                return False
            self.device.sleep(1.5)

    def press_until_gone(self, point, page, watch, region, name, timeout=15):
        """
        Press a point and wait for the page to change.

        Both taps of this flow are eaten when they land while the page is still
        sliding in, so each one is repeated.

        Args:
            point (tuple): (x, y) to press.
            page (Page, None): Page that should come up. None waits for `watch`
                to disappear instead.
            watch (Button): Button that tells whether the page changed.
            region (tuple): Region to look for `watch` in.
            name (str): For the log.
            timeout (int, float): Seconds per attempt.

        Returns:
            bool: If the page changed.
        """
        for attempt in range(2):
            self.tap_point(*point)
            if page is not None:
                moved = self.wait_page(page, timeout=timeout)
            else:
                moved = self.wait_gone(watch, region, timeout=timeout)
            if moved:
                self.device.sleep(1)
                self.device.screenshot()
                return True
            logger.info(f'{name}: nothing happened, press again')
            self.device.sleep(1)
        logger.warning(f'{name}: could not move on')
        return False

    def event_notice_appear(self):
        """
        Whether one of the one-line notices of the game is on screen.

        Returns:
            bool: If the 确认 label is there.
        """
        return match(self.device.image, EVENT_BTN_OK, EVENT_NOTICE_REGION) > 0.85

    def clear_appear(self):
        """
        Whether the CLEAR result page of a stage is on screen.

        Returns:
            bool: If the CLEAR art is there.
        """
        return match(self.device.image, DUNGEON_CLEAR, CLEAR_REGION) > 0.85

    def on_stage_page(self):
        """
        Whether the stage selection page is on screen.

        Returns:
            bool: If the 「选择」 button is in its usual place.
        """
        return match(self.device.image, EVENT_BTN_SELECT, STAGE_SELECT_REGION) > 0.85

    def skip_appear(self):
        """
        Whether a story scene with a skip button is on screen.

        Returns:
            bool: If 「Skip」 is there.
        """
        EVENT_BTN_SKIP.ensure_template()
        image = self.device.image
        x1, y1, x2, y2 = SKIP_REGION
        patch = cv2.cvtColor(image[y1:y2, x1:x2], cv2.COLOR_RGB2GRAY)
        template = cv2.cvtColor(EVENT_BTN_SKIP.image, cv2.COLOR_RGB2GRAY)
        if patch.shape[0] < template.shape[0] or patch.shape[1] < template.shape[1]:
            return False
        patch = (patch > SKIP_THRESHOLD).astype(np.uint8) * 255
        template = (template > SKIP_THRESHOLD).astype(np.uint8) * 255
        res = cv2.matchTemplate(patch, template, cv2.TM_CCOEFF_NORMED)
        return float(cv2.minMaxLoc(res)[1]) > SKIP_SIMILARITY

    # ------------------------------------------------------------------- sweep

    def event_sweep(self):
        """
        Sweep the event if it still has sweep tries.

        An event whose stages are all cleared may have no sweep at all, so the
        button decides: no 「一键扫荡」 means there is nothing to sweep here.
        The button does not tell whether tries are left - it looks the same with
        none - so the panel is opened and the sweep is tried; an empty sweep
        only raises a notice, which is dismissed.

        Pages:
            in: page_event_stage
            out: page_event_stage

        Returns:
            bool: If a sweep paid out.
        """
        self.device.screenshot()
        if not self.on_stage_page():
            return False
        if match(self.device.image, EVENT_BTN_SWEEP_ALL, STAGE_SWEEP_REGION) < 0.85:
            logger.info('No 一键扫荡 on this event, nothing to sweep')
            return False

        logger.hr('Sweep the event', level=2)
        state = self.sweep_panel_open()
        if state == 'empty':
            logger.info('The sweep has no tries left')
            return False
        if state != 'open':
            logger.warning('The sweep panel did not open')
            return False

        # The panel lists the stages with nothing ticked and refuses to sweep
        # that way, so everything is selected first.
        self.tap_asset(COPY_BTN_SELECT_ALL)
        self.device.sleep(0.8)
        self.device.screenshot()

        for attempt in range(2):
            self.tap_asset(COPY_BTN_SWEEP_ALL)
            if self.wait_page_title(REWARD_POPUP_TITLE, timeout=5):
                self.handle_reward_popup()
                logger.info('Swept the event')
                return True
            logger.info('No reward popup, press 一键扫荡 again')
            self.device.sleep(1)

        logger.info('The sweep paid nothing, no tries left')
        self.sweep_panel_dismiss()
        return False

    def sweep_panel_open(self, timeout=5):
        """
        Open the 「副本一键扫荡」 panel of the stage page.

        The press is routinely swallowed while the stage page is still settling,
        so it is repeated.

        Args:
            timeout (int, float): Seconds to wait for the panel per attempt.

        Returns:
            str: 'open', 'empty' when the game answers with a notice instead, or
                'failed' when nothing happened at all.
        """
        for attempt in range(3):
            self.tap_asset(EVENT_BTN_SWEEP_ALL)
            if self.wait_page_title(COPY_BTN_SWEEP_ALL, timeout=timeout):
                return 'open'
            self.device.screenshot()
            if self.event_notice_appear():
                self.tap_point(*EVENT_DIALOG_OK)
                self.device.sleep(1.5)
                return 'empty'
            self.device.sleep(1)
        return 'failed'

    def sweep_panel_dismiss(self):
        """
        Close the notice the game raises for an empty sweep, then the panel.

        A sweep without tries answers with a one-line notice and a single wide
        button in the middle of the screen. The panel closes itself together
        with the reward popup, so this is only needed when nothing came out.
        """
        self.device.screenshot()
        if match(self.device.image, COPY_BTN_SWEEP_ALL, (400, 560, 900, 720)) > 0.85:
            x1, y1, x2, y2 = EVENT_DIALOG_CONFIRM
            self.tap_point((x1 + x2) // 2, (y1 + y2) // 2)
            self.device.sleep(1.5)
            self.device.screenshot()
        if match(self.device.image, COPY_BTN_SWEEP_ALL, (400, 560, 900, 720)) > 0.85:
            self.tap_point(1146, 64)
            self.device.sleep(1.5)
            self.device.screenshot()

    # -------------------------------------------------------------------- exit

    def event_back(self):
        """
        Walk back to the event list.

        The X of the stage page does not close the event: it goes one level up
        to the sortie page, and a second X leaves the event altogether
        (measured). So the X is pressed until the event list is on screen.

        Pages:
            in: page_event_stage
            out: page_event

        Returns:
            bool: If the event list is back.
        """
        for _ in range(4):
            self.device.screenshot()
            if self.on_event_page():
                return True
            self.tap_point(1237, 32)
            self.device.sleep(3)
        self.device.screenshot()
        if self.on_event_page():
            return True
        logger.warning('Could not walk back to the event list')
        return False

    def on_event_page(self):
        """
        Whether the event list is on screen.

        Returns:
            bool: If the 活动 tab is the selected one.
        """
        return match(self.device.image, EVENT_TAB_SELECTED,
                     (1100, 60, 1280, 140)) > 0.85

    # ------------------------------------------------------------------- input

    def tap_point(self, x, y):
        """
        Press a point of this page.

        The buttons here ignore the shorter minitouch tap that
        `device.click()` sends, while `adb shell input tap` on the same
        coordinates works every time.

        Args:
            x (int): Pixel x.
            y (int): Pixel y.
        """
        self.device.adb_shell(['input', 'tap', str(int(x)), str(int(y))])

    def tap_asset(self, button):
        """
        Press the centre of a button.

        Args:
            button (Button): Target.
        """
        x1, y1, x2, y2 = button.button
        self.tap_point((x1 + x2) // 2, (y1 + y2) // 2)

    # -------------------------------------------------------------------- wait

    def wait_page(self, page, timeout=10):
        """
        Wait until one of the event pages is on screen.

        Args:
            page (Page): Page to look for.
            timeout (int, float): Seconds.

        Returns:
            bool: If it showed up.
        """
        timeout = Timer(timeout).start()
        while 1:
            self.device.screenshot()
            if page is page_event_stage:
                if self.on_stage_page():
                    return True
            elif page is page_event:
                if match(self.device.image, EVENT_TAB_SELECTED,
                         (1100, 60, 1280, 140)) > 0.85:
                    return True
            elif page is page_event_start:
                if match(self.device.image, EVENT_BTN_START,
                         STAGE_SELECT_REGION) > 0.85:
                    return True
            if timeout.reached():
                return False
            self.device.sleep(0.4)

    def wait_gone(self, button, region, timeout=15):
        """
        Wait until a button leaves the screen.

        Args:
            button (Button): Button to watch.
            region (tuple): Region it sits in.
            timeout (int, float): Seconds.

        Returns:
            bool: If it is gone.
        """
        timeout = Timer(timeout).start()
        while 1:
            self.device.screenshot()
            if match(self.device.image, button, region) < 0.75:
                return True
            if timeout.reached():
                return False
            self.device.sleep(0.4)

    def wait_page_title(self, button, timeout=6):
        """
        Wait until a popup title shows up.

        Args:
            button (Button): Title template.
            timeout (int, float): Seconds.

        Returns:
            bool: If it showed up.
        """
        timeout = Timer(timeout).start()
        while 1:
            self.device.screenshot()
            if match(self.device.image, button, (0, 0, 1280, 720)) > 0.85:
                return True
            if timeout.reached():
                return False
            self.device.sleep(0.4)
