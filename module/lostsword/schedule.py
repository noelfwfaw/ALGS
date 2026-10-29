"""When the weekly modes of this game come back.

星辰轮回 and 迷宫 both run on the weekly clock: Sunday 11:00 in Korea, which is
Monday 00:00 here. The framework only knows daily resets - `task_delay(
server_update=True)` - so the target of a weekly task is computed here and
handed over as an absolute time.
"""

import datetime


def next_week_reset():
    """
    The next Monday 00:00, never the one of today.

    `datetime.weekday()` is 0 on Monday, and by the time a task runs, today's
    00:00 is already behind it, so a Monday run has to aim a week ahead. The
    `or 7` is what does that; without it the target lands in the past, and
    `nearest_future()` only sorts - it does not push a past time forward - so the
    task would fire again in the same scheduler loop.

    Returns:
        datetime.datetime:
    """
    now = datetime.datetime.now()
    days = (7 - now.weekday()) % 7 or 7
    return (now + datetime.timedelta(days=days)).replace(
        hour=0, minute=0, second=0, microsecond=0)
