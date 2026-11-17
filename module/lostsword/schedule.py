"""When the weekly modes of this game come back.

The weekly modes (星辰轮回, 迷宫) reset on the game's own weekly clock, which the
framework does not know: `task_delay(server_update=True)` is a daily reset. So
the target is computed here and handed over as an absolute time.

This is the *fallback* clock. The 星辰轮回 panel prints its own `下次时间`
countdown, and on 2026-11-17 that landed on Sunday 23:10 local while this module
aims at Monday 00:00 - about an hour apart - so `star.py` schedules by the
countdown and only comes back here when the line cannot be read.
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
