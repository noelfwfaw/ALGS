import datetime
import re

from module.base.timer import Timer
from module.base.utils import get_color
from module.exception import GameStuckError
from module.logger import logger
from module.lostsword.assets import (ARENA_BTN_CLOSE,
                                     BOSS_VICTORY,
                                     DUNGEON_CLEAR,
                                     EVENT_BTN_OK,
                                     STAR_BTN_CHALLENGE,
                                     STAR_BTN_ENTER,
                                     STAR_CARD,
                                     STAR_TAB_1,
                                     STAR_TAB_2,
                                     STAR_TAB_3)
from module.lostsword.lostsword_ui import (BOSS_RESULT_TAP, LostswordUI,
                                          page_star)
from module.lostsword.schedule import next_week_reset
from module.ocr.ocr import Ocr

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

**The battle page card list scrolls.** It holds six cards (领主突袭 / 世界领主 /
竞技场 / 星辰轮回 / 小队副本 / 迷宫) and keeps the offset it was left at, so
`battle_goto_card()` searches the row dynamically instead of relying on a fixed
slot. That also keeps navigation resilient when new cards are inserted or
reordered.

A challenge is not one fight: the first wave ends in VICTORY, tapping through it
starts a second one (measured: 26.8M then 2.4M, the area score ended at 30.06M).
So the wait loop taps every result screen it sees and only stops when the panel
is back.

**Scheduled by the countdown the panel prints.** The middle of the panel shows
`下次时间` with a `HHH:MM:SS` countdown, and that is the weekly clock this game
really uses: measured 2026-11-17 05:43, `137:27:04`, which lands on Sunday 23:10
local - while the clock `next_week_reset()` computes (Monday 00:00 local) is about
an hour off. `run()` therefore reads the countdown before leaving the panel and
hands `now + countdown` to `config.task_delay()`, keeping the weekly fallback only
for the runs where the line stays unreadable.

**The cycle also has closed hours.** Outside its window the game answers the
press on 「挑战」 with a dialog - 「当前非星辰轮回进入时间。」 - and a 确认 plate
(measured 2026-11-17 06:00, all three areas). The task presses 挑战 once per area,
recognizes that dialog, closes it and goes straight to the countdown; retrying is
what used to end in `GameTooManyClickError` on a panel that cannot open.
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
# The `下次时间` countdown under the middle of the panel, `137:27:04`.
STAR_NEXT_TIME_AREA = (530, 470, 770, 528)
# The digits are a warm white (245, 235, 215); the background behind them is dark.
STAR_NEXT_TIME_LETTER = (245, 235, 215)
# All three thresholds read the whole three-digit hour on every frame measured
# (2026-11-17, three frames); 65 dropped the 7 (`13:18:38`) on one of them and 85
# upwards drops the leading 1, and both still parse, so the reading is only
# accepted when every threshold agrees.
STAR_NEXT_TIME_THRESHOLDS = (70, 75, 80)
STAR_NEXT_TIMES = [
    Ocr(STAR_NEXT_TIME_AREA, letter=STAR_NEXT_TIME_LETTER, threshold=threshold,
        alphabet='0123456789:', name=f'STAR_NEXT_TIME_{threshold}')
    for threshold in STAR_NEXT_TIME_THRESHOLDS
]
STAR_NEXT_TIME_PATTERN = re.compile(r'^(\d{1,3}):(\d{2}):(\d{2})$')
# A weekly reset is at most seven days away; a reading under a minute is taken
# as noise (the countdown is already running when the task leaves the panel).
STAR_NEXT_TIME_MIN = 60
STAR_NEXT_TIME_MAX = 8 * 24 * 3600
# The countdown is cross-checked against the weekly clock: a read that drops the
# leading hour digit (`137:27:04` -> `37:27:04`) is still a valid countdown, so
# the shape alone cannot catch it. The two clocks measured one hour apart, and a
# dropped digit is about four days apart.
STAR_NEXT_TIME_CROSSCHECK = 24 * 3600
# The new week is applied a moment after the countdown reaches zero.
STAR_RESET_MARGIN = 60


def parse_next_time(text):
    """
    Turn the `下次时间` line into seconds.

    `Duration.parse_time()` only accepts one or two hour digits (`137:27:04`
    would be read as 37 hours), so the shape is checked here instead. A partial
    read from the OCR (see `STAR_NEXT_TIME_THRESHOLDS`) is rejected by the
    pattern, the minute/second range and the one-minute floor.

    Args:
        text (str): What the OCR returned, such as `137:27:04`.

    Returns:
        int: Seconds until the next reset, 0 when the text is not a countdown.
    """
    match = STAR_NEXT_TIME_PATTERN.match((text or '').strip())
    if not match:
        return 0
    hours, minutes, seconds = (int(group) for group in match.groups())
    if minutes > 59 or seconds > 59:
        return 0
    total = hours * 3600 + minutes * 60 + seconds
    if not STAR_NEXT_TIME_MIN <= total <= STAR_NEXT_TIME_MAX:
        return 0
    return total


class LostswordStar(LostswordUI):
    """
    Challenge the three adventure areas of 星辰轮回, then leave.

    Pages:
        in: page_main
        out: page_main
    """

    def run(self):  # alas-lint: allow - tasks weekly through star_schedule(), which hands the target to config.task_delay()
        """
        Pages:
            in: page_main
            out: page_main
        """
        logger.hr('Star cycle', level=1)
        self.battle_goto_card(STAR_CARD, page_star, label='Star cycle')

        fought = 0
        # Set by `star_fight()` when the game answers the press with
        # 「当前非星辰轮回进入时间。」: the cycle is between windows and no area
        # can be entered, so the remaining areas are skipped instead of pressing
        # a dead 挑战 three times per area (measured 2026-11-17: the retries
        # ended in GameTooManyClickError).
        self.star_closed = False
        for name, tab, strip in STAR_TABS:
            for attempt in (0, 1):
                if self.star_fight(name, tab, strip):
                    fought += 1
                    break
                if self.star_closed:
                    break
                # An area that could not be opened is usually the panel still
                # coming back from the previous battle, not a spent week (an
                # area can be challenged again, its score only adds up). Make
                # sure the panel is really there and walk this one once more -
                # measured 2026-11-14: 星辰轨迹 was left at 0 while the two
                # areas before it had been fought.
                if attempt == 0:
                    logger.info(f'{name}: area not taken, wait for the panel and retry it once')
                    self.star_wait_panel()
            if self.star_closed:
                break

        logger.info(f'Star areas challenged: {fought}')
        if self.star_closed:
            logger.warning('The star cycle is not open yet, no area was entered')
        elif not fought:
            # Nothing opened at all: the week is already spent, or a popup the
            # task has no asset for is sitting on top of the panel. Either way
            # the run is over - say it out loud instead of rescheduling
            # silently and letting the next week look the same.
            logger.warning('No area could be challenged this week')
        # The countdown is printed on the panel, so it has to be read before the
        # panel is left. It is also the only weekly clock the game itself shows.
        self.star_schedule()
        self.ui_goto_main()

    def star_schedule(self):
        """
        Put the task on the reset the panel itself announces.

        The panel printed `137:27:04` on 2026-11-17 05:43, which lands on Sunday
        23:10 local. The weekly clock in `next_week_reset()` (Monday 00:00 local)
        is about an hour later, so the countdown is what the task goes by; the
        weekly clock is only the fallback for a panel whose line cannot be read.

        Returns:
            datetime.datetime: The target time.
        """
        seconds = self.star_next_time()
        if seconds:
            target = datetime.datetime.now() + datetime.timedelta(
                seconds=seconds + STAR_RESET_MARGIN)
            expected = next_week_reset()
            drift = abs((target - expected).total_seconds())
            if drift <= STAR_NEXT_TIME_CROSSCHECK:
                logger.attr('Star next reset', str(target))
                self.config.task_delay(target=target)
                return target
            # A dropped leading hour digit still looks like a countdown, so a
            # reading that far from the weekly clock is treated as unreadable
            # instead of putting the task days early.
            logger.warning(f'The countdown points at {target}, '
                           f'{drift / 3600:.1f}h away from the weekly clock {expected}')

        # A popup on top, an old client or a new layout: still reschedule on the
        # weekly clock rather than the daily one, or the task runs every day.
        return self.delay_next_week(label='Star next reset (countdown unreadable)')

    def star_next_time(self, timeout=10):
        """
        Read the `下次时间` countdown in the middle of the panel.

        The line fades in later than the area list - `log/probe/lostsword_star/
        star_panel.png` caught the panel with the line still missing and the OCR
        returns an empty string there - so the read is retried until the digits
        appear instead of trusting one frame.

        Args:
            timeout (int, float): Seconds to keep trying.

        Returns:
            int: Seconds until the next reset, 0 when it stays unreadable.
        """
        timeout = Timer(timeout).start()
        for _ in self.loop():
            # Only the panel carries the line. Reading the area on another screen
            # could turn stray artwork into a number the task cannot trust.
            if self.appear(page_star.check_button, offset=30):
                readings = [parse_next_time(ocr.ocr(self.device.image))
                            for ocr in STAR_NEXT_TIMES]
                readings = [seconds for seconds in readings if seconds]
                # The thresholds either see the same countdown or the frame is
                # not read; a lone reading cannot tell a dropped digit from the
                # real thing, so it waits for the next frame instead.
                if len(readings) >= 2 and len(set(readings)) == 1:
                    logger.attr('Star next reset in', str(datetime.timedelta(seconds=readings[0])))
                    return readings[0]

            if timeout.reached():
                logger.warning('The 下次时间 countdown of the star panel could not be read')
                return 0

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
            if self.appear(EVENT_BTN_OK):
                # 「当前非星辰轮回进入时间。」 with a 确认 plate: the cycle is
                # between its open windows and this press went nowhere. Pressing
                # again cannot help and only stacks clicks on the same button.
                self.device.click(EVENT_BTN_OK)
                self.star_closed = True
                logger.warning(f'{name}: the panel says 当前非星辰轮回进入时间, '
                               f'the cycle is closed')
                return False
            logger.info(f'{name}: versus page did not open, press 挑战 again')
        else:
            logger.warning(f'{name}: versus page did not open')
            return False

        if self.appear(STAR_BTN_ENTER, offset=30):
            self.device.click(STAR_BTN_ENTER)
        return self.star_battle(name)

    def star_wait_panel(self, timeout=20):
        """
        Wait until the area list is on screen.

        The panel title is a flat dark strip that a loading screen matches too,
        so the list has to be what says "the panel is back". Any of the three
        names will do: the open one is drawn on a cream card and drops out of
        the template match, the other two are always on the dark panel.

        Args:
            timeout (int, float): Seconds.

        Returns:
            bool: If the panel is on screen.
        """
        timeout = Timer(timeout).start()

        for _ in self.loop():
            if any(self.appear(tab, offset=30) for _, tab, _ in STAR_TABS):
                return True

            if timeout.reached():
                logger.warning('The star panel did not come back')
                return False

    def star_select_tab(self, name, tab, strip, timeout=15):
        """
        Make sure the given area is the open one.

        Args:
            name (str): Area name, for the log.
            tab (Button): List entry of the area.
            strip (tuple): Background of that entry.
            timeout (int, float): Seconds. Long enough for the panel to finish
                fading in after the previous battle: measured 2026-11-14, the
                panel was still drawing six seconds after the result page went
                away, the old limit gave up on 星辰轨迹 and left it unplayed.

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
                logger.warning(f'{name} did not open, strip mean={sum(color) / 3:.1f}, '
                               f'page={self.ui_get_current_page()}')
                self.device.image_save(f'./log/star_{name}_did_not_open.png')
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

            # The panel's own title is a flat dark strip that also matches the
            # loading screen of the next scene, so it says nothing on its own:
            # measured 2026-11-14, the loop called this "back at the panel" six
            # seconds before the area list was on screen and the next area was
            # skipped. The area names in the list only exist on the panel.
            if self.appear(page_star.check_button, offset=30) \
                    and any(self.appear(tab, offset=30) for _, tab, _ in STAR_TABS):
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
