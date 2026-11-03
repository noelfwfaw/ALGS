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

# The priority cells of that panel that can actually be set, with the value each
# one is set to. The value comes from the event guide: 女神的祝福 is the one that
# always helps (revive + heal), BOSS rooms carry the 玉玺 drop, chests drop gear
# and gifts, the winged cell revives a fallen unit, 死神的试炼 trades HP for
# power, and 特殊事件 "basically never has anything good".
#
#     行1: 宝箱(3)       BOSS(2)
#     行2: 死神的试炼(5) 特殊事件(6)
#     行3: 女神的祝福(1) 复活(1, default)
#
# The third row is not in the list on purpose: its dropdown never opens at
# 1280x720 - the press is acknowledged (the cell sparkles) but no option list
# renders, on adb tap, minitouch and input swipe alike, at any point of the cell
# (measured 2026-11-04 on V1.610.1, the list would have to reach past the screen
# bottom). Both of its cells stay on the game default 优先级1, which is exactly
# what 女神的祝福 wants anyway; only 复活 misses its 4, and a revive room early
# is no harm. Every retry here cost ~24 s a week for nothing.
#
# Row centres re-measured on V1.610.1 (2026-11-04): the rows moved apart -
# 315/378 sat in the dead space between cells and those presses opened nothing.
MAZE_PRIORITY_CELLS = (
    ((541, 250), 3),   # 宝箱
    ((925, 250), 2),   # BOSS
    ((541, 343), 5),   # 死神的试炼
    ((925, 343), 6),   # 特殊事件
)
# The option list of an opened dropdown is anchored to the cell that opened it:
# the first line sits 46 px below the cell centre and the six lines are 44 px
# apart (measured 2026-11-04 on V1.610.1). Free band detection broke on the same
# day: the highlighted option is drawn as a solid cream bar about 37 px tall and
# the last line merges with the bright panel button behind it, so the old
# 8~24 px band rule rejected exactly those two and read six lines as four.
MAZE_PRIO_FIRST = 46
MAZE_PRIO_STEP = 44
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
            # it renders in well under a second and the scan is cheap. The grid
            # has to agree twice in a row - during the drop animation the rows
            # are already bright but not where they end up, and a pick pressed
            # on a moving row is eaten (measured 2026-11-04).
            lines = []
            previous = None
            timeout = Timer(3).start()
            while 1:
                self.device.stuck_record_clear()
                self.device.screenshot()
                lines = self.maze_priority_lines(x, y)
                if len(lines) >= 6 and lines == previous:
                    break
                previous = lines
                if timeout.reached():
                    break
            if len(lines) < 6:
                continue

            target = lines[:6][level - 1]
            self.tap_point(x, target)
            timeout = Timer(8).start()
            retry = Timer(2).start()
            while 1:
                self.device.stuck_record_clear()
                self.device.screenshot()
                if len(self.maze_priority_lines(x, y)) < 6:
                    logger.info(f'Cell ({x}, {y}) -> 优先级{level} at y={target}')
                    return True
                # The pick is repeated while the list stays open: a press eaten
                # by the animation is harmless here, the row is still there.
                if retry.reached():
                    retry.reset()
                    self.tap_point(x, target)
                if timeout.reached():
                    logger.warning(f'Cell ({x}, {y}): the list did not close')
                    break
        logger.warning(f'Cell ({x}, {y}): the option list did not open')
        return False

    def maze_priority_lines(self, x, y):
        """
        The six option lines of an opened dropdown, anchored to its cell.

        The lines are not detected freely: the highlighted option is a solid
        cream bar about 37 px tall, the last line sits on the panel's own bright
        button, and both are rejected by any sane band-height rule (measured
        2026-11-04, six lines read as four). Instead the expected grid - first
        line 46 px under the cell centre, 44 px apart - is laid over the bright
        rows and a line counts as there when some brightness surrounds it,
        whether that is a text line (about 13 px of white) or the bar of the
        highlighted option (about 37 px of cream). A closed dropdown confirms
        about two of the six positions from page noise, an opened one all six.

        Args:
            x (int): Centre x of the dropdown.
            y (int): Centre y of the dropdown.

        Returns:
            list: y centres of the lines, top to bottom; fewer than six when
            the list is not open.
        """
        x1, x2 = x - 100, x + 100
        y1 = y + 20
        y2 = min(715, y + MAZE_PRIO_SCAN[1])
        region = self.device.image[y1:y2, x1:x2].astype(np.int16)
        mask = ((region[:, :, 0] > 195) & (region[:, :, 1] > 185)
                & (region[:, :, 2] > 170))
        counts = mask.sum(axis=1)
        lines = []
        for k in range(6):
            pos = y + MAZE_PRIO_FIRST + k * MAZE_PRIO_STEP
            i = pos - y1
            lo, hi = max(0, i - 14), min(len(counts), i + 14)
            if lo < hi and counts[lo:hi].max() > 3:
                lines.append(pos)
        return lines

