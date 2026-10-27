"""The 「自动进行迷宫」 panel of the maze.

Pressing 「自动进行」 on the map raises a panel with six priority dropdowns and a
sweep difficulty. The panel is the only thing this task configures, and the
reason it is worth configuring at all: the default puts every node type on
「优先级1」, which lets 特殊事件 (the one kind that "basically never has anything
good") sit above the rooms that carry the weekly rewards.

Setting one dropdown is a two step press - open it, then pick the line - and both
presses are routinely eaten, so each step waits for the panel to answer instead
of guessing a pause.
"""

import numpy as np

from module.base.timer import Timer
from module.logger import logger

# The six priority cells of that panel, top left to bottom right, with the value
# each one is set to. The value comes from the event guide: 女神的祝福 is the one
# that always helps (revive + heal), BOSS rooms carry the 玉玺 drop, chests drop
# gear and gifts, the winged cell revives a fallen unit, 死神的试炼 trades HP for
# power, and 特殊事件 "basically never has anything good".
#
#     行1: 宝箱          BOSS
#     行2: 死神的试炼    特殊事件
#     行3: 女神的祝福    复活
MAZE_PRIORITY_CELLS = (
    ((541, 254), 3),   # 宝箱
    ((925, 254), 2),   # BOSS
    ((541, 315), 5),   # 死神的试炼
    ((925, 315), 6),   # 特殊事件
    ((541, 378), 1),   # 女神的祝福
    ((925, 378), 4),   # 复活
)
# The option list of a dropdown, measured: six lines about 43 px apart, the
# first one a little under the cell that opened it.
MAZE_PRIO_STEP = 43
MAZE_PRIO_SCAN = (200, 380)


class MazePriority:
    """
    Configure the priority dropdowns of the auto run panel.

    Self-contained except for one thing: a dropdown is opened by pressing a point
    of the panel, and the buttons of this game ignore the minitouch tap, so the
    mixin calls `tap_point()` - provided by `LostswordUI`, which the composed
    `LostswordMaze` inherits.
    """

    def maze_set_priorities(self):
        """
        Set the six priority dropdowns of the panel.

        Every dropdown is opened, the option lines are found by their white
        text, and the wanted one is pressed. A dropdown whose list does not
        come up with six lines is left alone - the game default (everything on
        「优先级1」) is harmless, while guessing a position could put 特殊事件
        above the rooms that matter.

        Pages:
            in: page_maze (panel open)
            out: page_maze (panel open)

        Returns:
            int: How many cells were set.
        """
        logger.hr('Set priorities', level=2)
        done = 0
        for (x, y), level in MAZE_PRIORITY_CELLS:
            if self.maze_set_one(x, y, level):
                done += 1
        logger.info(f'Priorities set: {done}/{len(MAZE_PRIORITY_CELLS)}')
        return done

    def maze_set_one(self, x, y, level):
        """
        Open one dropdown and pick a level.

        The press that opens a dropdown is eaten now and then (measured: the
        same cell needs two or three presses), so it is repeated until the
        option list is readable, and the pick is confirmed by the list closing.

        Args:
            x (int): Centre x of the dropdown.
            y (int): Centre y of the dropdown.
            level (int): 1 to 6.

        Returns:
            bool: If the cell was set.
        """
        for attempt in range(4):
            self.tap_point(x, y)
            # Wait for the list to be readable instead of sleeping a fixed time:
            # it renders in well under a second and the scan is cheap.
            timeout = Timer(3).start()
            while 1:
                self.device.screenshot()
                lines = self.maze_priority_lines(x, y)
                if len(lines) >= 6:
                    break
                if timeout.reached():
                    break
            if len(lines) < 6:
                continue

            target = lines[:6][level - 1]
            self.tap_point(x, target)
            timeout = Timer(3).start()
            while 1:
                self.device.screenshot()
                if len(self.maze_priority_lines(x, y)) < 6:
                    logger.info(f'Cell ({x}, {y}) -> 优先级{level} at y={target}')
                    return True
                if timeout.reached():
                    logger.warning(f'Cell ({x}, {y}): the list did not close')
                    break
        logger.warning(f'Cell ({x}, {y}): the option list did not open')
        return False

    def maze_priority_lines(self, x, y):
        """
        Find the six option lines of an opened dropdown by their white text.

        Args:
            x (int): Centre x of the dropdown.
            y (int): Centre y of the dropdown.

        Returns:
            list: y centres of the lines, top to bottom.
        """
        x1, x2 = x - 100, x + 100
        y1, y2 = y + 20, min(715, y + MAZE_PRIO_SCAN[1])
        region = self.device.image[y1:y2, x1:x2].astype(np.int16)
        mask = ((region[:, :, 0] > 195) & (region[:, :, 1] > 185)
                & (region[:, :, 2] > 170))
        counts = mask.sum(axis=1)
        lines = []
        start = None
        for i, value in enumerate(counts):
            if value > 3 and start is None:
                start = i
            elif value <= 3 and start is not None:
                if 8 <= i - start <= 24:
                    lines.append(y1 + (start + i) // 2)
                start = None
        return lines

