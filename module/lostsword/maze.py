"""The maze (迷宫) of the battle tab.

Layout:

    战斗 --滑到卡片列表末尾--> 「迷宫」卡
    迷宫卡 --点击--> 迷宫地图（标题「迷宫N层」，左下「自动进行」）
    「自动进行」--> 「自动进行迷宫」面板（六个节点类型的优先级 + 扫荡难度）
    面板底部「自动进行」--> 自动走到今天走不动为止，停在地图上，「自动进行」变灰

The maze plays itself once the panel is confirmed: no battle screen, no click -
the map just scrolls and the floors go up (measured: 1 层 to 16 层 in about
fifteen seconds). What is left to do is to wait until the map stops moving.
"""

from module.base.timer import Timer
from module.logger import logger
from module.lostsword.assets import ARENA_BTN_CLOSE, MAZE_BTN_AUTO, MAZE_CARD
from module.lostsword.lostsword_ui import LostswordUI, page_battle
from module.lostsword.maze_priority import MazePriority
from module.lostsword.maze_run import MazeAutoRun
from module.lostsword.utils import match

# The maze card once the list is dragged to its end.
MAZE_LAST_CARD = (1096, 416)
# The card art of that slot, used as a position check only (see
# `maze_at_list_end()`): 0.97 at the end, 0.39 with the cut-off 星辰轮回 card
# sitting in the window instead, 0.04 anywhere else.
MAZE_CARD_SIMILARITY = 0.65


class LostswordMaze(MazeAutoRun, MazePriority, LostswordUI):
    def run(self):
        """
        Pages:
            in: page_main
            out: page_main
        """
        logger.hr('Maze', level=1)
        # There is no early 「完成」 check here on purpose: the OCR of that word
        # runs on whatever screen the game happens to show, and a false hit
        # would silently spend the whole week (the maze map itself is checked
        # after `maze_enter()`, where the word can only come from the map).
        if not self.maze_settle():
            logger.warning('The game is on a screen the maze task cannot leave')
            self.maze_retry_delay()
            return
        self.ui_ensure(page_battle)
        self.battle_goto_normal()
        if not self.maze_enter():
            logger.warning('Could not open the maze')
            self.ui_goto_main()
            self.maze_retry_delay()
            return

        if self.maze_finished():
            # The card says 探险完成, so the map opens without a run left: it
            # shows 「完成」 over the head of the maze and no 「自动进行」 button.
            # Everything below would be guessing at buttons that are not there.
            logger.info('The maze is already complete, nothing to do this week')
            self.maze_exit()
            self.ui_goto_main()
            self.maze_delay()
            return

        if self.maze_auto_start():
            self.maze_wait_finish()
        else:
            logger.info('The auto run is not available today')

        # The map decides before it is closed: 「完成」 = the week is spent,
        # anything else = the run is not confirmed and comes back in a few
        # hours (an auto run that stopped early can be continued the same way).
        spent = self.maze_finished()
        self.maze_exit()
        self.ui_goto_main()
        if spent:
            self.maze_delay()
        else:
            logger.warning('The maze run could not be confirmed as complete')
            self.maze_retry_delay()

    def maze_delay(self):
        """
        Postpone the task to next Monday 00:00.

        The maze is a weekly mode, not a daily one: the reset is Sunday 11:00 in
        Korea, which is Monday 00:00 here, and the run spends everything the week
        allows - after it the map shows 「完成」 and the 「自动进行」 button does
        nothing until the reset. The date arithmetic lives in
        `module/lostsword/schedule.py`, reached through
        `LostswordUI.delay_next_week()`, because 星辰轮回 runs on the same clock.

        Only call this once the week is really spent - a confirmed 「完成」 on
        the map. Entry failures go to `maze_retry_delay()`, or one bad night
        would cost the whole week (measured 2026-11-04: the entry check failed
        three times and the task booked itself off until the next reset without
        ever opening the maze).
        """
        self.delay_next_week(label='Maze next reset')

    def maze_retry_delay(self, minutes=180):
        """
        Postpone the task by a few hours when the maze could not be confirmed.

        A weekly task that delays a week on an unconfirmed run loses the week's
        rewards; a few hours keep it inside the same week in every case - even a
        failure on Sunday evening retries after the Monday reset, where the fresh
        week's maze simply runs. The map state then decides between this and
        `maze_delay()` again.

        Args:
            minutes (int): How long to stay away.
        """
        self.config.task_delay(minute=minutes)
        logger.info(f'Maze retry scheduled in {minutes} minutes')

    def maze_delay(self):
        """
        Postpone the task to next Monday 00:00.

        The maze is a weekly mode, not a daily one: the reset is Sunday 11:00 in
        Korea, which is Monday 00:00 here, and the run spends everything the week
        allows - after it the map shows 「完成」 and the 「自动进行」 button does
        nothing until the reset. The date arithmetic lives in
        `module/lostsword/schedule.py`, reached through
        `LostswordUI.delay_next_week()`, because 星辰轮回 runs on the same clock.
        """
        self.delay_next_week(label='Maze next reset')

    def maze_enter(self, timeout=15):
        """
        Open the maze from the battle tab.

        Two phases on purpose. The list is dragged to its end and checked
        first, and once the maze card is in the last slot the list is not
        touched again: the press opens the map through a six second loading
        screen, and dragging during that screen does nothing but fill the click
        record until "too many click for a button" kills the task (measured
        2026-10-27, the map was already open and the task kept swiping).

        Pages:
            in: page_battle
            out: page_maze

        Args:
            timeout (int, float): Seconds to wait for the map after one press.

        Returns:
            bool: If the map opened.
        """
        if not self.maze_goto_last_card():
            logger.warning('The maze card never reached the last slot')
            return False

        for attempt in range(2):
            self.tap_point(*MAZE_LAST_CARD)
            timer = Timer(timeout).start()
            while 1:
                self.device.stuck_record_clear()
                self.device.screenshot()
                # A cleared maze has no 「自动进行」 button any more, only 「完成」
                # over the map, so both count as "the maze opened".
                if self.maze_on_map() or self.maze_finished():
                    logger.info('Maze map opened')
                    return True
                if timer.reached():
                    break
            logger.info(f'The press did not open the maze, press again '
                        f'({attempt + 1}/2)')
        return False

    def maze_goto_last_card(self, tries=4):
        """
        Drag the card list to its end and check that the maze is in the last
        slot.

        The behaviour clamp of `battle_scroll()` can lie: a drag that the page
        eats during the tab switch reads as "no movement = at the end" while the
        list never left the start (2026-11-04: three rounds of exactly three
        drags each, and the first drag of the next round moved the list again -
        the maze was never opened and the task delayed itself a week). The card
        check is the only truth here, so every failed check buys one more raw
        drag; only `tries` rounds of both may be spent.

        Args:
            tries (int): How many rounds of drags may be spent.

        Returns:
            bool: If the maze card is in the last slot.
        """
        for _ in range(tries):
            self.battle_scroll(forward=True)
            if self.maze_at_list_end():
                return True
            # One drag that ignores the clamp verdict: harmless when the list
            # really is at its end, decisive when the clamp was a eaten drag.
            self.device.swipe(p1=(1000, 400), p2=(300, 400))
            self.wait_until_still((0, 140, 1280, 660), timeout=3)
            self.device.click_record_clear()
            if self.maze_at_list_end():
                return True
            logger.info('The maze card is not in the last slot yet')
        return False

    def maze_at_list_end(self):
        """
        Whether the card list sits at its end, i.e. the maze card is in the last
        slot.

        The card art is a position check only, never a state check: the game
        writes 可进入 / 探险完成 under it and neither is part of the template.
        The window is wider than the card on purpose - the whole row drifted
        about 30 px with V1.610.x and the best match inside the window sits on
        the card in every frame seen (0.971 at the end, 0.04 anywhere else).

        Returns:
            bool: If the last slot holds the maze.
        """
        return match(self.device.image, MAZE_CARD,
                     (990, 510, 1280, 690)) > MAZE_CARD_SIMILARITY

    def maze_on_map(self):
        """
        Whether the maze map is on screen.

        Returns:
            bool: If the 「自动进行」 button is in its corner.
        """
        return match(self.device.image, MAZE_BTN_AUTO,
                     (100, 600, 320, 700)) > 0.85

    def maze_exit(self, timeout=15):
        """
        Close the map and go back to whatever is behind it.

        The X of the map leads to the lobby through a loading screen (measured),
        which is why the wait below only asks for the map to be gone: the page
        behind it is found by `ui_goto_main()` anyway.

        Pages:
            in: page_maze
            out: page_main

        Returns:
            bool: If the map left.
        """
        timeout = Timer(timeout).start()
        retry = Timer(2, count=2).start()
        while 1:
            self.device.stuck_record_clear()
            self.device.screenshot()
            if not (self.maze_on_map() or self.maze_finished()):
                return True
            if retry.reached():
                retry.reset()
                if self.appear(ARENA_BTN_CLOSE, offset=30):
                    self.device.click(ARENA_BTN_CLOSE)
            if timeout.reached():
                logger.warning('The maze map did not close')
                return False

