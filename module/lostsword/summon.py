from module.base.timer import Timer
from module.exception import GameStuckError
from module.logger import logger
from module.lostsword.assets import (SUMMON_CONFIRM, SUMMON_DOT, SUMMON_DRAW,
                                     SUMMON_FREE, SUMMON_POOL_CHAR,
                                     SUMMON_POOL_PET, SUMMON_SKIP,
                                     SUMMON_VIEW_ALL)
from module.lostsword.lostsword_ui import LostswordUI, page_summon

"""
Daily free summons (每日免费召唤), one for characters and one for pets.

Flow observed in game:

    page_main   --底栏「召唤」-->  page_summon
    page_summon  左列滚到底       -> 末尾两项「领取角色」「领取宠物」
    page_summon  点「领取角色」   -> 角色池（右侧标题变成「领取角色」）
    ...          点「召唤1次」    -> 过场动画 -> 「查看全部」-> 点 -> 「确认」-> 点
    page_summon  点「领取宠物」   -> 宠物池（标题「领取宠物」）
    ...          点「召唤1次」    -> 过场动画（右上角有 Skip）-> 「查看全部」->「确认」
    page_summon  关闭 X          -> page_main

The free pull is one per pool per day. Once it is used the same button reads a
ticket count instead of 「免费」, and a ticket costs diamonds, so the single rule
of this task is: a press on 「召唤1次」 only ever happens while the free marker is
on screen. Everything else waits, warns, or gives up.
"""

# The two free pools: log name, the heading that only exists once the pool is
# open, and the centre of its entry in the banner list.
#
# The entries flip between a light "selected" and a dark "idle" look, so one
# asset cannot recognise an entry in both states, and the two entries look alike
# anyway (0.57 against each other). The heading on the right panel is what tells
# them apart: 1.00 in its own pool, 0.57 in the other, and it does not change
# with the free pull being used.
#
# The click points are fixed once the list is scrolled to its end: the entries
# are 92 pixels apart and the last one covers y 638~713, measured on the
# screenshots of both pools.
SUMMON_POOLS = (
    ('character', SUMMON_POOL_CHAR, (123, 580)),
    ('pet', SUMMON_POOL_PET, (123, 675)),
)

# The banner list: a narrow column on the left, from under the heading to the
# bottom edge. Watched while it snaps, because a drag sent during the snap
# stacks the momentum and overshoots the end.
SUMMON_BANNER_LIST = (0, 90, 230, 700)
SUMMON_SCROLL_DRAGS = 3

# A draw plays a cutscene before the result page. The pet one can be skipped,
# the character one cannot, and the longest of the two runs about 12 seconds;
# 30 leaves room for a slow emulator.
SUMMON_RESULT_TIMEOUT = 30


class LostswordSummon(LostswordUI):
    """
    Take the two free daily pulls.

    The lobby's summon entry carries a red dot while anything is free, so the
    whole task costs one screenshot when there is nothing to take.

    Pages:
        in: page_main
        out: page_main
    """

    def run(self):
        """
        Pages:
            in: page_main
            out: page_main
        """
        logger.hr('Daily free summon', level=1)
        if self.config.LostswordSummon_Draw:
            self.summon_free_pulls()
        else:
            logger.info('LostswordSummon.Draw is off, nothing to do')
        # Both pools reset with the daily server update.
        self.config.task_delay(server_update=True)

    def summon_free_pulls(self):
        """
        Open both pools and take whatever is free.

        Pages:
            in: page_main
            out: page_main

        Returns:
            int: Number of pulls made.
        """
        self.ui_goto_main()
        if not self.summon_entry_dotted():
            logger.info('No red dot on the summon entry, no free pull today')
            return 0

        self.ui_goto(page_summon)
        self.summon_scroll_to_pools()

        taken = 0
        for name, title, point in SUMMON_POOLS:
            if not self.summon_open_pool(name, title, point):
                continue
            if self.summon_take_free(name):
                taken += 1

        self.ui_goto_main()
        logger.info(f'Free summon done, {taken} pull(s) taken')
        return taken

    def summon_entry_dotted(self):
        """
        Whether the lobby's summon entry carries a red dot.

        The dot is the game's own "something is free here" mark, 22x22 in the
        corner of the button. As a template it is useless: the same corner
        without the dot scores 0.86 against it, above the 0.85 threshold, so
        matching cannot tell the two apart. Its mean colour can - (203, 90, 69)
        with the dot, (90, 57, 43) without - and that is the path `appear()`
        takes when it is called without an offset.

        Returns:
            bool: If the dot is there.
        """
        self.device.screenshot()
        return self.appear(SUMMON_DOT)

    def summon_scroll_to_pools(self):
        """
        Drag the banner list to its end, where the two free pools are.

        The list remembers the offset it was left at, and it is read through the
        pool headings on the right rather than the entries themselves (see
        `SUMMON_POOLS`). Dragging at the end does nothing, which is what makes a
        fixed number of drags safe instead of a loop with a check point.

        Pages:
            in: page_summon
            out: page_summon
        """
        for _ in range(SUMMON_SCROLL_DRAGS):
            # Slower than the battle page's card list: this one is a short
            # column with a snap of its own, and a fling drag overshoots it.
            self.device.swipe(p1=(115, 620), p2=(115, 280), duration=0.4)
            # The list snaps with an animation that has no check point of its
            # own; dragging into it stacks the momentum and overshoots.
            self.wait_until_still(SUMMON_BANNER_LIST, timeout=2)
        # A drag long enough to scroll is still a press for this game, and it
        # may open a pool on the way. Counting those towards "too many clicks
        # for a button" would stop the task halfway through a normal run.
        self.device.click_record_clear()

    def summon_open_pool(self, name, title, point):
        """
        Open one of the two free pools from the banner list.

        Pages:
            in: page_summon
            out: page_summon

        Args:
            name (str): For the log.
            title (Button): The pool heading drawn on the right panel.
            point (tuple): Centre of its entry in the banner list.

        Returns:
            bool: If the pool is open.
        """
        if self.appear(title, offset=(30, 30)):
            return True
        for _ in range(2):
            logger.info(f'Open the {name} pool')
            self.tap_point(*point)
            # Two frames, not one: the panel under the heading is a slide-in, and
            # the first frame it matches is not yet the one that accepts a press
            # on the draw button.
            if self.wait_until_appear(title, offset=(30, 30), timeout=8, settle=2):
                return True
            # The list may have snapped back while the previous pool ran.
            self.summon_scroll_to_pools()
        logger.warning(f'Cannot open the {name} pool')
        return False

    def summon_free_marker_up(self):
        """
        Whether the open pool still offers its free pull.

        The panel slides in and the marker is drawn with it, so on the first
        frames nothing matches - which is not the same as "this pool has
        nothing free". The panel is therefore watched until it stops moving and
        only then is the marker read; that is what turns a missing marker from a
        transition frame into a fact. This is the one place of the task where an
        absence is allowed to mean something.

        Pages:
            in: page_summon, a pool open
            out: page_summon

        Returns:
            bool: If the free marker is on screen.
        """
        self.wait_until_still(SUMMON_FREE.area, timeout=3)
        return self.appear(SUMMON_FREE, offset=(10, 10))

    def summon_take_free(self, name):
        """
        Draw once in the open pool, only while the free marker is on screen.

        The marker is checked before the press and by its disappearance after
        it. A press without the marker would spend a ticket, and a ticket is
        diamonds, so there is no retry on either check.

        Pages:
            in: page_summon, a pool open
            out: page_summon, the same pool with the free pull used

        Args:
            name (str): For the log.

        Returns:
            bool: If a pull was made.
        """
        if not self.summon_free_marker_up():
            logger.info(f'The {name} pool has no free pull left')
            return False

        logger.info(f'Free pull available in the {name} pool')
        self.tap_asset(SUMMON_DRAW)
        # The marker leaves the screen as soon as the pull starts. If it is
        # still there the press did not land, and pressing again could spend a
        # ticket - so this gives up instead of retrying.
        if not self.wait_until_disappear(SUMMON_FREE, offset=(10, 10), timeout=10, settle=2):
            raise GameStuckError(
                f'Pressed the free pull of the {name} pool but the marker stayed')

        self.summon_walk_result(name)
        return True

    def summon_wait_result(self):
        """
        Wait for the result screen, skipping the cutscene when there is one.

        The pet pool plays a cutscene with a Skip button in its top right
        corner; the character pool does not. One loop handles both because the
        press is guarded by a match, and the loop ends on the one thing the game
        draws either way: the 查看全部 button.

        Pages:
            in: page_summon_result, or the cutscene before it
            out: page_summon_result

        Returns:
            bool: If the result screen showed up.
        """
        timeout = Timer(SUMMON_RESULT_TIMEOUT).start()
        while 1:
            self.device.screenshot()
            if self.appear(SUMMON_VIEW_ALL, offset=(20, 20)):
                return True
            # One press per 1.5 seconds: the cutscene swallows presses sent
            # faster than its transitions, and a hold would not help either.
            if self.appear(SUMMON_SKIP, offset=(20, 20), interval=1.5):
                self.tap_asset(SUMMON_SKIP)
                continue
            if timeout.reached():
                logger.warning('Summon result did not show up')
                return False

    def summon_walk_result(self, name):
        """
        Walk the two result steps back to the pool.

        Pages:
            in: page_summon_result
            out: page_summon

        Args:
            name (str): For the log.
        """
        if not self.summon_wait_result():
            raise GameStuckError(f'The {name} pool never reached its result screen')

        # Both buttons sit in the same frame at the bottom, so the result page
        # has to stop moving before the first press or it lands on the frame.
        self.wait_until_still(SUMMON_VIEW_ALL.area, timeout=2)
        logger.info('Result: 查看全部')
        self.tap_asset(SUMMON_VIEW_ALL)
        if not self.wait_until_appear(SUMMON_CONFIRM, offset=(20, 20),
                                      timeout=SUMMON_RESULT_TIMEOUT, settle=2):
            raise GameStuckError('查看全部 did not open the result list')

        logger.info('Result: 确认')
        self.tap_asset(SUMMON_CONFIRM)
        if not self.wait_until_disappear(SUMMON_CONFIRM, offset=(20, 20), timeout=10, settle=2):
            raise GameStuckError('确认 did not close the result list')
