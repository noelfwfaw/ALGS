"""Bounded scrolling for Promilia's daily-activity task list.

The caller owns one ``PromiliaActivityScroll`` per task instance.  Movement
methods return ``False`` when the daily page or thumb is unknown, or when a
bounded verification does not observe a stable advance.  A caller must treat
that as a failed attempt, not as an empty list.  Only ``at_bottom()`` confirms
the end of the list.
"""

import numpy as np

from module.base.utils import random_rectangle_point
from module.promilia.assets import ACTIVITY_DAILY_ACTIVE
from module.ui.scroll import Scroll


ACTIVITY_SCROLL_TRACK = (1253, 134, 1256, 573)
ACTIVITY_SCROLL_OFFSET = (20, 20)
ACTIVITY_SCROLL_MIN_LENGTH = 80
ACTIVITY_SCROLL_MIN_TRAVEL = 60
ACTIVITY_SCROLL_EDGE = 0.03
ACTIVITY_SCROLL_PAGE = 0.75
ACTIVITY_SCROLL_RANDOM_RANGE = (-0.01, 0.01)
ACTIVITY_SCROLL_DURATION = (0.3, 0.5)
ACTIVITY_SCROLL_SETTLE_FRAMES = 2
ACTIVITY_SCROLL_STABLE_DISTANCE = 0.01
ACTIVITY_SCROLL_MIN_ADVANCE = 0.08


class PromiliaActivityScroll:
    """Scroll the daily list without inheriting ``Scroll.set()``'s unbounded wait."""

    def __init__(self, main, name='PROMILIA_ACTIVITY_SCROLL'):
        """
        Args:
            main (ModuleBase): Task owner providing the current screenshot loop.
            name (str): Device control name used for swipe bookkeeping.
        """
        self.main = main
        self.name = name
        self._scroll = Scroll(area=ACTIVITY_SCROLL_TRACK, color=(255, 255, 255), name=name)

    def _daily_selected(self):
        return self.main.appear(ACTIVITY_DAILY_ACTIVE, offset=ACTIVITY_SCROLL_OFFSET)

    def _valid_mask(self, mask):
        length = int(np.count_nonzero(mask))
        if length < ACTIVITY_SCROLL_MIN_LENGTH:
            return False
        if self._scroll.total - length < ACTIVITY_SCROLL_MIN_TRAVEL:
            return False
        indices = np.flatnonzero(mask)
        return bool(np.all(np.diff(indices) == 1))

    def position(self):
        """
        Returns:
            float | None: Current valid position in [0, 1], or None when the
                daily page/thumb cannot be recognized in the current frame.
        """
        if not self._daily_selected():
            return None
        mask = self._scroll.match_color(self.main)
        if not self._valid_mask(mask):
            return None
        return float(self._scroll.cal_position(self.main))

    def at_top(self):
        """Return whether a valid thumb is at the top edge."""
        position = self.position()
        return position is not None and position <= ACTIVITY_SCROLL_EDGE

    def at_bottom(self):
        """Return whether a valid thumb is at the bottom edge."""
        position = self.position()
        return position is not None and position >= 1 - ACTIVITY_SCROLL_EDGE

    def set_top(self, timeout=3):
        """Return to the top, verifying movement and stop; return False on failure."""
        return self._navigate(timeout, to_top=True)

    def next_page(self, timeout=3):
        """Advance less than one viewport, preserving overlap; return False on failure."""
        return self._navigate(timeout, to_top=False)

    def _navigate(self, timeout, to_top):
        """Wait for a valid thumb, move once, and verify within one timeout budget."""
        if timeout <= 0:
            return False
        current = None
        previous = None
        stable = 0
        target = 0.0
        required = 0.0
        for _ in self.main.loop(timeout=timeout):
            position = self.position()
            if position is None:
                previous = None
                stable = 0
                continue
            if current is None:
                current = position
                if to_top:
                    if current <= ACTIVITY_SCROLL_EDGE:
                        return True
                else:
                    if current >= 1 - ACTIVITY_SCROLL_EDGE:
                        return True
                    ratio = self._scroll.length / (self._scroll.total - self._scroll.length)
                    target = min(1.0, current + ACTIVITY_SCROLL_PAGE * ratio)

                random_range = ACTIVITY_SCROLL_RANDOM_RANGE
                if target <= ACTIVITY_SCROLL_EDGE:
                    random_range = (-0.5, -0.3)
                elif target >= 1 - ACTIVITY_SCROLL_EDGE:
                    random_range = (0.3, 0.5)
                p1 = random_rectangle_point(
                    self._scroll.position_to_screen(current, random_range=ACTIVITY_SCROLL_RANDOM_RANGE), n=1)
                p2 = random_rectangle_point(
                    self._scroll.position_to_screen(target, random_range=random_range), n=1)
                self.main.device.swipe(p1, p2, duration=ACTIVITY_SCROLL_DURATION, name=self.name)
                # Swipe does not refresh device.image; verification must start from a new frame.
                self.main.device.screenshot()
                previous = None
                stable = 0
                required = min(ACTIVITY_SCROLL_MIN_ADVANCE, abs(target - current) * 0.5)
                position = self.position()
                if position is None:
                    continue

            if previous is not None and abs(position - previous) <= ACTIVITY_SCROLL_STABLE_DISTANCE:
                stable += 1
            else:
                stable = 0
            previous = position
            if stable < ACTIVITY_SCROLL_SETTLE_FRAMES:
                continue
            if target > current:
                if current + required <= position <= target + ACTIVITY_SCROLL_EDGE:
                    return True
            elif target - ACTIVITY_SCROLL_EDGE <= position <= current - required:
                return True
        return False
