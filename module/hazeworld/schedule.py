"""When the weekly runs of this game come back.

The daily clock of 苍雾世界 is 05:00. The framework only knows daily resets -
`task_delay(server_update=True)` - so a task that should run once a week takes
its target from here and hands it over as an absolute time.

The exchange shop is the user of this clock: most of its goods reset monthly,
but some entries (精英演习券) restock weekly, so the shop is visited once a
week rather than once a month.
"""

import datetime


def next_week_refresh():
    """
    The next Monday 05:00, never the one of today.

    `datetime.weekday()` is 0 on Monday, and by the time a task runs, today's
    05:00 may already be behind it, so a Monday run has to aim a week ahead.
    The `or 7` is what does that; without it the target lands in the past, and
    `nearest_future()` only sorts - it does not push a past time forward - so
    the task would fire again in the same scheduler loop.

    Returns:
        datetime.datetime:
    """
    now = datetime.datetime.now()
    days = (7 - now.weekday()) % 7 or 7
    return (now + datetime.timedelta(days=days)).replace(
        hour=5, minute=0, second=0, microsecond=0)
