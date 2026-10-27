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

The detection of these pages and the waits on them live in
`module/lostsword/event_monitor.py`; this file is the flow.

Two things about the flow are worth knowing before reading it:

- The banners are found by their state labels rather than by fixed coordinates,
  because the list scrolls and the number of events changes. A red 探险完成 means
  the event is finished and is skipped outright.
- 可扫荡 does not mean the stages are cleared: it means the sweep has tries left.
  An event that was cleared on an earlier day parks its stage page behind a
  「已通关。」 notice when the run is started, and that notice is the only way to
  know it is done - so the sweep has to be walked into from the stage page again.
"""

from module.base.timer import Timer
from module.exception import GameStuckError
from module.logger import logger
from module.lostsword.assets import DUNGEON_BTN_BACK, EVENT_BTN_SKIP
from module.lostsword.event_monitor import EventMonitor
from module.lostsword.event_sweep import EventSweep
from module.lostsword.lostsword_ui import LostswordUI, page_battle, page_event

# Where a banner is pressed: the middle of the artwork, above its label.
BANNER_PRESS_Y = 350

# The X of the stage page and of the sortie page. One press goes one level up:
# stage page -> sortie page -> event list (measured).
EVENT_CLOSE_POINT = (1237, 32)

# The bottom right button of the stage page and of the sortie page: 「选择」 and
# 「出发」 are drawn in the same place, only the label changes.
STAGE_BUTTON_POINT = (1132, 658)

# The result page of a cleared stage parks there for a while; a page that is
# still up after this long is the end of the run rather than a mid-event stage
# on its way to the next one.
CLEAR_HOLD = 8

# A clear run takes a minute or two per stage and an event can hold a dozen of
# them (measured: a half finished event went from stage 3 to stage 11 in one run
# of about 15 minutes).
EVENT_CLEAR_TIMEOUT = 3000


class LostswordEvent(EventSweep, EventMonitor, LostswordUI):
    """
    Clear and sweep the events of the 活动 tab.

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

    def event_enter(self, x, timeout=10):
        """
        Open one event from the list.

        Pages:
            in: page_event
            out: stage list of that event

        Args:
            x (int): Centre x of the banner.
            timeout (int, float): Seconds to wait for the stage list.

        Returns:
            bool: If the stage list opened.
        """
        logger.hr(f'Event at x={x}', level=2)
        for _ in range(3):
            self.tap_point(x, BANNER_PRESS_Y)
            if self.event_wait(self.on_stage_page, timeout=timeout):
                return True
            # The game remembers where the event was left: opening it again may
            # land on the sortie page of the last stage instead of its stage
            # list. One X is enough to go back down.
            if self.on_sortie_page():
                logger.info('Landed on the sortie page, go back to the stage list')
                self.tap_point(*EVENT_CLOSE_POINT)
                if self.event_wait(self.on_stage_page, timeout=timeout):
                    return True
            logger.info('Stage page did not open, press the banner again')
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
            in: stage list of the event
            out: stage list of the event

        Returns:
            bool: If a run was started and finished.
        """
        logger.hr('Clear stages', level=2)
        if not self.press_until_gone(STAGE_BUTTON_POINT, self.on_sortie_page, '选择'):
            return False

        state = self.press_start_until_running()
        if state == 'cleared':
            logger.info('The sortie did not start, every stage of this event is done')
            self.event_notice_dismiss()
            return False
        if state != 'running':
            logger.warning('The sortie did not start')
            return False

        if not self.wait_stage_page():
            raise GameStuckError('Event clear did not end in time')
        return True

    def press_until_gone(self, point, predicate, name, timeout=15):
        """
        Press a point until the page answers with a new one.

        Both taps of this flow are eaten when they land while the page is still
        sliding in, so each one is repeated while the predicate says the old page
        is still there.

        Args:
            point (tuple): (x, y) to press.
            predicate (callable): True while the old page is still up.
            name (str): For the log.
            timeout (int, float): Seconds.

        Returns:
            bool: If the page changed.
        """
        retry = Timer(1.5).start()

        for _ in self.loop(timeout=timeout):
            # End - the new page answered, which also means the press landed.
            if not predicate():
                return True

            # Click - the page is still the old one, so the press was swallowed.
            if retry.reached():
                retry.reset()
                self.tap_point(*point)
        else:
            logger.warning(f'{name}: could not move on')
            return False

    def press_start_until_running(self, timeout=20):
        """
        Press 「出发」 until the run starts or the game refuses to start it.

        Two answers are handled: the sortie page leaves (the run is on its way),
        or a one-line notice appears - 「已通关。」 when every stage of the event is
        already cleared, which is the only positive way to know the event is done.

        Returns:
            str: 'running', 'cleared' (the event is already done) or 'failed'.
        """
        retry = Timer(3).start()
        absent = 0

        for _ in self.loop(timeout=timeout):
            # End - the game answered with a notice instead of starting the run.
            if self.event_notice_appear():
                return 'cleared'

            # Click - 「出发」 was swallowed by the page sliding in. Slow retry:
            # the loading screen follows the press, and a burst of taps would
            # queue several runs.
            if self.on_sortie_page():
                absent = 0
                if retry.reached():
                    retry.reset()
                    self.tap_point(*STAGE_BUTTON_POINT)
                continue

            # End - two frames without the sortie page: the run is on its way.
            absent += 1
            if absent >= 2:
                return 'running'

        return 'failed'

    def wait_stage_page(self, timeout=EVENT_CLEAR_TIMEOUT):
        """
        Wait until the stage list comes back.

        The whole story and battle run happens in between, so the only things to
        do are to press 「Skip」 on the story scenes and to leave a CLEAR page that
        is holding.

        Returns:
            bool: If the stage list is back.
        """
        timeout = Timer(timeout).start()
        report = Timer(120).start()
        skip_retry = Timer(2).start()
        clear_hold = Timer(CLEAR_HOLD).start()

        for _ in self.loop():
            # A battle and a story scene are live scenes that barely change for
            # minutes, which reads as a frozen game to the stuck detector.
            self.device.stuck_record_clear()

            # End - back at the stage list, the run is over.
            if self.on_stage_page():
                logger.info('Back at the stage page, the run is over')
                return True

            # The last stage of an event does not advance by itself: it parks on
            # the CLEAR page, where only 「返回」 leaves. A mid-event stage leaves
            # that page 5 seconds later, so a page still up after 8 seconds is
            # the end of the run.
            if self.clear_appear():
                if clear_hold.reached():
                    logger.info('CLEAR page is holding, press 返回')
                    self.tap_asset(DUNGEON_BTN_BACK)
                    clear_hold.reset()
                continue
            clear_hold.reset()

            # Click - the story of a stage, which the game would otherwise play
            # out in full. One press per two seconds, otherwise a scene is left
            # several pages ahead.
            if self.skip_appear():
                if skip_retry.reached():
                    skip_retry.reset()
                    logger.info('Skip the story')
                    self.tap_point(*self.skip_point())
                continue

            if report.reached():
                report.reset()
                logger.info(f'Still clearing, {int(timeout.current_time())}s elapsed')

            if timeout.reached():
                logger.warning('The clear run did not come back to the stage page')
                return False

    def skip_point(self):
        """
        Centre of the 「Skip」 button of a story scene.

        Returns:
            tuple: (x, y).
        """
        x1, y1, x2, y2 = EVENT_BTN_SKIP.button
        return (x1 + x2) // 2, (y1 + y2) // 2

    # -------------------------------------------------------------------- exit

    def event_back(self, timeout=20):
        """
        Walk back to the event list.

        The X of the stage page does not close the event: it goes one level up to
        the sortie page, and a second X leaves the event altogether (measured).
        So the X is pressed until the event list is on screen.

        Pages:
            in: stage list or sortie page of an event
            out: page_event

        Args:
            timeout (int, float): Seconds.

        Returns:
            bool: If the event list is back.
        """
        retry = Timer(2.5).start()

        for _ in self.loop(timeout=timeout):
            # End - the event list is back.
            if self.on_event_page():
                return True

            # Click - one level up per press, the page check above is what
            # decides whether it landed.
            if retry.reached():
                retry.reset()
                self.tap_point(*EVENT_CLOSE_POINT)
        else:
            logger.warning('Could not walk back to the event list')
            return False
