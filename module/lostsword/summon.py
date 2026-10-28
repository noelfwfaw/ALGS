import numpy as np

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
    ...          点「召唤1次」    -> 过场动画（右上角有 Skip）->「查看全部」->「确认」
    page_summon  关闭 X          -> page_main

The free pull is one per pool per day. Once it is used the same button reads a
ticket count instead of 「免费」, and a ticket costs diamonds, so the single rule
of this task is: a press on 「召唤1次」 only ever happens while the free marker is
on screen. Everything else waits, warns, or gives up.
"""

# The two free pools. The heading on the right panel is what tells them apart:
# 1.00 in its own pool, 0.57 in the other, and it does not change with the free
# pull being used. It is also how the caller learns which pool a press landed
# on, since the list entries themselves are alike (0.57 against each other) and
# flip between a light "selected" and a dark "idle" look.
SUMMON_POOLS = (
    ('character', SUMMON_POOL_CHAR),
    ('pet', SUMMON_POOL_PET),
)

# The banner list: a narrow column on the left, from under the heading to the
# bottom edge. Watched while it snaps, because a drag sent during the snap
# stacks the momentum and overshoots the end.
SUMMON_BANNER_LIST = (0, 90, 230, 700)
SUMMON_SCROLL_DRAGS = 3

# Where the game draws its red "something to take here" badge.
#
# Every entry that has something free right now carries one: a 23x24 blob with
# its outside corner cut, on the right edge of the card, mean colour about
# (233, 99, 77). The two free pools are two of those, so the badge is also what
# *locates* them, and a fixed y would be wrong the first time a limited banner
# above them expires - which is what the daily reset does, all of them read
# 「剩余1日」. Measured on 领取角色.png: badges at y 535~558 and 627~650, cards
# 533~615 and 632~700.
SUMMON_BADGE_COLUMN = (195, 60, 235, 715)
# R - max(G, B): 140~160 on the badge, 5~30 on the card it sits on.
SUMMON_BADGE_RED = 60
# Rows further apart than this belong to two badges.
SUMMON_BADGE_GAP = 6
# A badge is 24 rows tall. Below the minimum it is a stray red pixel; above the
# maximum it is not a badge at all but a piece of the artwork showing through
# while the list is still sliding - measured on a live run, a frame caught
# mid-scroll put 86 rows of red in that column and the scan took it for an
# entry.
SUMMON_BADGE_MIN_ROWS = 12
SUMMON_BADGE_MAX_ROWS = 40
# Badge centre -> card centre, and the x of the card body under it.
SUMMON_ENTRY_DROP = 30
SUMMON_ENTRY_X = 123

# A panel slides in after a press on an entry. The switch itself is quick
# (0.2~0.4 s measured), so this only has to be longer than the fade; it is paid
# twice in the worst case, see `summon_open_pool`.
SUMMON_POOL_TIMEOUT = 3

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

        entries = self.summon_marked_entries()
        if not entries:
            logger.warning('The lobby says something is free, but no entry in the '
                           'banner list carries a badge - nothing pressed')
            self.ui_goto_main()
            return 0
        logger.info(f'{len(entries)} marked entries in the banner list')

        taken = 0
        for point in entries:
            name = self.summon_open_pool(point)
            if name is None:
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

        The list remembers the offset it was left at, so the free entries are
        only in the same place when it is scrolled the same way. Dragging at the
        end does nothing, which is what makes a fixed number of drags safe
        instead of a loop with a check point.

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

    def summon_marked_entries(self):
        """
        Centres of the list entries that carry the game's red badge.

        Every entry with something to take is marked, so the badge both answers
        "which pool is free" and says where the entry is. It has to: the cards
        move as banners come and go (the column above them shrinks every time a
        limited one expires), and a hardcoded y was already wrong the day after
        it was measured.

        The badge is found by colour, not by template. It is a flat red blob,
        (233, 99, 77) mean, sitting on a list where nothing else in this column
        is red - the templates of the entries themselves are useless here, they
        look alike and change with the selection.

        Pages:
            in: page_summon, the list scrolled to its end and settled
            out: page_summon

        Returns:
            list[tuple[int, int]]: (x, y) of each card, top to bottom.
        """
        x1, y1, x2, y2 = SUMMON_BADGE_COLUMN
        # A frame caught mid-scroll reads as badges in the wrong place, or as
        # none at all, so the column has to be standing still before it is read.
        if not self.wait_until_still(SUMMON_BANNER_LIST, timeout=2):
            logger.warning('The banner list is still moving, a badge may be missed')
        column = self.device.image[y1:y2, x1:x2].astype('int16')
        # Red minus the strongest of the other two channels: 140~160 on the
        # badge, 5~30 on the artwork it is drawn over. Comparing the channels
        # instead of the brightness keeps the dark cards and the bright panel
        # behind them out of it.
        red = column[:, :, 0] - np.maximum(column[:, :, 1], column[:, :, 2])
        rows = np.where(red.max(axis=1) > SUMMON_BADGE_RED)[0]
        if not len(rows):
            return []

        groups = [[int(rows[0])]]
        for row in rows[1:]:
            if row - groups[-1][-1] <= SUMMON_BADGE_GAP:
                groups[-1].append(int(row))
            else:
                groups.append([int(row)])

        entries = []
        for group in groups:
            if not SUMMON_BADGE_MIN_ROWS <= len(group) <= SUMMON_BADGE_MAX_ROWS:
                logger.info(f'Ignored red blob y {group[0] + y1}~{group[-1] + y1}: '
                            f'{len(group)} rows is not a badge')
                continue
            # The badge hangs on the card's top right corner; the card body is
            # below it, and that is what has to be pressed.
            y = (group[0] + group[-1]) // 2 + y1 + SUMMON_ENTRY_DROP
            entries.append((SUMMON_ENTRY_X, y))
            logger.attr('Marked entry', f'badge y {group[0] + y1}~{group[-1] + y1}, '
                                        f'card centre {y}')
        return entries

    def summon_pool_shown(self):
        """
        Which of the two free pools the right panel is showing, if any.

        Returns:
            str: 'character', 'pet', or None.
        """
        for name, title in SUMMON_POOLS:
            if self.appear(title, offset=(30, 30)):
                return name
        return None

    def summon_open_pool(self, point):
        """
        Press a marked entry and say which pool came up.

        A press on an entry that is *already* the open one changes nothing, so
        waiting for "one of the two headings" would answer with the pool that
        was there before the press. The pool on screen is therefore read first,
        and what the press has to produce is the *other* one.

        That leaves "the panel did not move" meaning two things - the entry was
        already open, or the press was swallowed by an animation - so the press
        is repeated once before the second reading is believed. Measured on the
        live game: a press sent while the page was still opening did nothing at
        all and the panel stayed on the previous pool for the whole timeout.

        Pages:
            in: page_summon
            out: page_summon, a pool open

        Args:
            point (tuple): Centre of the card.

        Returns:
            str: 'character', 'pet', or None if the entry is not one of them.
        """
        before = self.summon_pool_shown()
        for attempt in (1, 2):
            logger.info(f'Open the marked entry (currently: {before or "unknown"})')
            self.tap_point(*point)
            # Two frames, not one: the panel under the heading is a slide-in,
            # and the first frame it matches is not yet the one that accepts a
            # press on the draw button. `settle` is not available here because
            # the button being waited for is not known in advance - it is
            # whichever heading was not there before the press.
            for _ in self.loop(timeout=SUMMON_POOL_TIMEOUT):
                after = self.summon_pool_shown()
                if after is not None and after != before:
                    return after
            if attempt == 1:
                logger.info('The panel did not move, pressing again')

        # Nothing moved on either press, so the entry was the open one.
        if before is not None:
            logger.info(f'The {before} pool was already open')
            return before
        logger.warning('The marked entry is not one of the two free pools')
        return None

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
