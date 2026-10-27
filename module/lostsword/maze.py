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

import datetime

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
# `maze_at_list_end()`): 0.74 when the card is there, 0.04 when it is not.
MAZE_CARD_SIMILARITY = 0.5


class LostswordMaze(MazeAutoRun, MazePriority, LostswordUI):
    def run(self):
        """
        Pages:
            in: page_main
            out: page_main
        """
        logger.hr('Maze', level=1)
        # Starting on the map of a cleared maze: the week is spent, there is
        # nothing to open and nothing to press.
        self.device.screenshot()
        if self.maze_finished():
            logger.info('The maze is already complete')
            self.maze_exit()
            self.ui_goto_main()
            self.maze_delay()
            return

        if not self.maze_settle():
            logger.warning('The game is on a screen the maze task cannot leave')
            self.maze_delay()
            return
        self.ui_ensure(page_battle)
        self.battle_goto_normal()
        if not self.maze_enter():
            logger.warning('Could not open the maze')
            self.ui_goto_main()
            self.maze_delay()
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

        self.maze_exit()
        self.ui_goto_main()
        self.maze_delay()

    def maze_delay(self):
        """
        Postpone the task to next Monday 00:00.

        The maze is a weekly mode, not a daily one: the reset is Sunday 11:00 in
        Korea, which is Monday 00:00 here, and the run spends everything the week
        allows - after it the map shows 「完成」 and the 「自动进行」 button does
        nothing until the reset.
        """
        now = datetime.datetime.now()
        days = (7 - now.weekday()) % 7 or 7
        target = (now + datetime.timedelta(days=days)).replace(
            hour=0, minute=0, second=0, microsecond=0)
        logger.attr('Maze next reset', str(target))
        self.config.task_delay(target=target)

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

    def maze_goto_last_card(self, tries=3):
        """
        Drag the card list to its end and check that the maze is in the last
        slot.

        Args:
            tries (int): How many rounds of drags may be spent.

        Returns:
            bool: If the maze card is in the last slot.
        """
        for _ in range(tries):
            self.battle_scroll(forward=True)
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
        Measured 0.74 with the list at its end and 0.04 anywhere else, so the
        threshold sits between them with room on both sides.

        Returns:
            bool: If the last slot holds the maze.
        """
        return match(self.device.image, MAZE_CARD,
                     (1040, 545, 1145, 640)) > MAZE_CARD_SIMILARITY

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

