from module.base.timer import Timer
from module.base.utils import get_color
from module.exception import GameStuckError
from module.logger import logger
from module.lostsword.assets import (ARENA_BTN_CLOSE, BOSS_VICTORY,
                                     DUNGEON_CLEAR, STAR_BTN_CHALLENGE,
                                     STAR_BTN_ENTER, STAR_CARD, STAR_TAB_1,
                                     STAR_TAB_2, STAR_TAB_3)
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
        self.device.sleep(1.2)
        self.device.screenshot()

        for attempt in range(2):
            self.device.click(STAR_BTN_CHALLENGE)
            if self.wait_overlay(STAR_BTN_ENTER, timeout=8):
                break
            if attempt == 0:
                logger.info(f'{name}: versus page did not open, press 挑战 again')
                self.device.sleep(1)

        else:
            logger.warning(f'{name}: versus page did not open')
            return False

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
        retry = Timer(1.5, count=3).start()
        while 1:
            self.device.screenshot()
            color = get_color(self.device.image, strip)
            if sum(color) / 3 > STAR_TAB_MEAN:
                return True
            if retry.reached():
                retry.reset()
                self.device.click(tab)
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

        while 1:
            self.device.stuck_record_clear()
            self.device.screenshot()

            if self.appear(page_star.check_button, offset=30):
                logger.info(f'{name}: back at the panel, {waves} wave(s)')
                return True

            if self.appear(BOSS_VICTORY, offset=30) or self.appear(DUNGEON_CLEAR, offset=30):
                waves += 1
                logger.info(f'{name}: wave {waves} cleared')
                self.device.click(BOSS_RESULT_TAP)
                self.device.sleep(2)
                continue

            if report.reached():
                report.reset()
                logger.info(f'{name}: still fighting, {int(timeout.current_time())}s elapsed')
            if timeout.reached():
                logger.warning(f'{name}: battle did not end in time')
                raise GameStuckError('Star cycle battle did not end in time')
            self.device.sleep(2)

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
