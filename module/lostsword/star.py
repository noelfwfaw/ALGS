from module.base.timer import Timer
from module.base.utils import get_color
from module.exception import GameStuckError
from module.logger import logger
from module.lostsword.assets import (ARENA_BTN_CLOSE,
                                     BOSS_VICTORY,
                                     DUNGEON_CLEAR,
                                     STAR_BTN_CHALLENGE,
                                     STAR_BTN_ENTER,
                                     STAR_TAB_1,
                                     STAR_TAB_2,
                                     STAR_TAB_3)
from module.lostsword.lostsword_ui import (BOSS_RESULT_TAP, LostswordUI,
                                          page_battle, page_star)

"""
星辰轮回 (star cycle).

Flow observed in game:

    page_main  --底栏「战斗」-->  page_battle --「星辰轮回」卡-->  page_star
    page_star  --左侧选一个冒险区域-->  右侧变成那个区域的敌人与奖励
    page_star  --「挑战」-->  versus page（两队站桩 + 「进入」）
    versus page  --「进入」-->  战斗  --VICTORY（点屏幕）-->  （可能还有下一波）-->  page_star
    page_star  --右上圆 X-->  page_battle  --右上圆 X-->  page_main

Three areas are listed on the left - 星辰诞生 / 星辰痕迹 / 星辰轨迹 - and each one
gets challenged once. The panel opens on the first area (measured), and the
selected one is drawn on a cream card (mean 133) while the others stay on the
dark panel (26), so a brightness read decides which one is open.

**The battle page card list scrolls.** It holds five cards (领主突袭 / 竞技场 /
小队副本 / 星辰轮回 / 迷宫) and keeps the offset it was left at, so every card asset
is only valid at one scroll position: 星辰轮回 was cut with the list dragged to its
end (its card in the third slot), the other cards with the list at its start. That
is why `battle_scroll()` runs before walking in - and `battle_goto_normal()` puts
the list back to the start for every other battle task.

A challenge is not one fight: the first wave ends in VICTORY, tapping through it
starts a second one (measured: 26.8M then 2.4M, the area score ended at 30.06M).
So the wait loop taps every result screen it sees and only stops when the panel
is back.
"""

# Cards of the adventure area list: name, tap point, background strip used to
# tell whether this one is the open area.
STAR_TABS = (
    ('星辰诞生', STAR_TAB_1, (40, 120, 100, 145)),
    ('星辰痕迹', STAR_TAB_2, (40, 198, 100, 226)),
    ('星辰轨迹', STAR_TAB_3, (40, 276, 100, 305)),
)
# Open area 133, idle 26.
STAR_TAB_MEAN = 80
# One challenge is one or two waves plus the loading screens.
STAR_TIMEOUT = 600


class LostswordStar(LostswordUI):
    """
    Challenge the three adventure areas of 星辰轮回, then leave.

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
        logger.hr('Star cycle', level=1)
        self.ui_ensure(page_battle)
        self.battle_goto_normal()
        # 星辰轮回 is the fourth card; its asset was cut with the list scrolled to
        # the end, so drag it there before walking in.
        self.battle_scroll(forward=True)
        self.ui_ensure(page_star)

        fought = 0
        for name, tab, strip in STAR_TABS:
            if self.star_fight(name, tab, strip):
                fought += 1

        logger.info(f'Star areas challenged: {fought}')
        self.ui_goto_main()
        # Three tries a day, refreshed at the daily reset of this game (00:00).
        self.config.task_delay(server_update=True)

    def star_fight(self, name, tab, strip):
        """
        Challenge one adventure area.

        Pages:
            in: page_star
            out: page_star

        Args:
            name (str): Area name, for the log.
            tab (Button): List entry of the area.
            strip (tuple): Background of that entry, for the selected state.

        Returns:
            bool: If a battle was fought to the end.
        """
        logger.hr(f'Area {name}', level=2)
        if not self.star_select_tab(name, tab, strip):
            return False

        # The right half (enemy, rewards, score) repaints after the switch, and a
        # tap that lands while it does is swallowed - measured: switching to
        # 星辰痕迹 and pressing 挑战 200ms later did nothing, twice in a row.
        # Watching the 挑战 plate until it stops changing is the same wait
        # without guessing how long the repaint takes.
        self.wait_until_still(STAR_BTN_CHALLENGE.area, timeout=3)

        for _ in range(2):
            if self.appear(STAR_BTN_CHALLENGE, offset=30):
                self.device.click(STAR_BTN_CHALLENGE)
            if self.wait_overlay(STAR_BTN_ENTER, timeout=8):
                break
            logger.info(f'{name}: versus page did not open, press 挑战 again')
        else:
            logger.warning(f'{name}: versus page did not open')
            return False

        if self.appear(STAR_BTN_ENTER, offset=30):
            self.device.click(STAR_BTN_ENTER)
        return self.star_battle(name)

    def star_select_tab(self, name, tab, strip, timeout=6):
        """
        Make sure the given area is the open one.

        Args:
            name (str): Area name, for the log.
            tab (Button): List entry of the area.
            strip (tuple): Background of that entry.
            timeout (int, float): Seconds.

        Returns:
            bool: If the area is open.
        """
        timeout = Timer(timeout).start()

        for _ in self.loop():
            # End - the strip behind this entry is the lit one.
            color = get_color(self.device.image, strip)
            if sum(color) / 3 > STAR_TAB_MEAN:
                return True

            # Click - the entry is always on screen, the strip colour above is
            # what decides, so the press is the interval throttled one.
            if self.appear_then_click(tab, offset=30, interval=1.5):
                continue

            if timeout.reached():
                logger.warning(f'{name} did not open')
                return False

    def star_battle(self, name, timeout=STAR_TIMEOUT):
        """
        Wait out the waves of one challenge and come back to the panel.

        Pages:
            in: versus page
            out: page_star

        Args:
            name (str): Area name, for the log.
            timeout (int, float): Seconds.

        Returns:
            bool: If the panel is back.

        Raises:
            GameStuckError: If the battle does not end in time.
        """
        timeout = Timer(timeout).start()
        report = Timer(30).start()
        waves = 0
        # One area is one battle: the click counter exists to catch a task
        # hammering a button while it is stuck, and it holds the last 15 presses
        # with no notion of time. The two or three presses of three battles
        # spread over minutes would otherwise add up to the same 12 that the
        # throttle below is meant to stay away from.
        self.device.click_record_clear()

        for _ in self.loop():
            # A battle is a live scene that barely changes for minutes, which
            # reads as a frozen game to the stuck detector.
            self.device.stuck_record_clear()

            if self.appear(page_star.check_button, offset=30):
                logger.info(f'{name}: back at the panel, {waves} wave(s)')
                return True

            if self.appear(BOSS_VICTORY, offset=30) or self.appear(DUNGEON_CLEAR, offset=30):
                waves += 1
                logger.info(f'{name}: wave {waves} cleared')
                self.star_dismiss_result()
                continue

            if report.reached():
                report.reset()
                logger.info(f'{name}: still fighting, {int(timeout.current_time())}s elapsed')
            if timeout.reached():
                logger.warning(f'{name}: battle did not end in time')
                raise GameStuckError('Star cycle battle did not end in time')

    def star_dismiss_result(self, timeout=10):
        """
        Tap the result page away and wait until it is really off screen.

        The page matches from its first fading frame and keeps matching for
        several frames after a tap has been taken, so one press per state loop
        iteration turns into a dozen presses on the same spot within a second.
        The click record counts those as one button hammered and kills the task:
        measured 2026-10-28, the second area died with
        `GameTooManyClickError: Too many click for a button: BOSS_RESULT_TAP`
        after 12 presses, and the first area got away with 11.

        The press is therefore throttled and repeated until the artwork is
        gone, which also makes the wave counter mean what it says: one result
        page, one wave.

        Returns:
            bool: If the result page is gone.
        """
        timeout = Timer(timeout).start()
        # Not started on purpose: a timer that was never started is reached on
        # the first call, so the first press goes out at once and only the
        # repeats are throttled.
        retry = Timer(1)
        for _ in self.loop():
            # A result page is a still scene, which reads as a frozen game.
            self.device.stuck_record_clear()

            if self.appear(BOSS_VICTORY, offset=30) or self.appear(DUNGEON_CLEAR, offset=30):
                # Click - anywhere on the artwork advances it, and the next wave
                # starts right after the loading screen.
                if retry.reached():
                    retry.reset()
                    self.device.click(BOSS_RESULT_TAP)
            else:
                # End - the artwork is off screen, so the next wave is loading or
                # the panel is coming back.
                return True

            if timeout.reached():
                logger.warning('The result page does not leave')
                return False

    def star_close(self):
        """
        Leave the panel through its own X.

        Pages:
            in: page_star
            out: page_battle
        """
        if self.appear(page_star.check_button, offset=30):
            self.device.click(ARENA_BTN_CLOSE)
            self.wait_overlay_gone(page_star.check_button, timeout=8)
