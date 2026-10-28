"""
每日免费抽抽乐 (Brown Dust II).

Flow observed in game (2026-10-28, the screenshots are in `screenshots/browndust/`):

    page_main   --底栏「抽抽乐」-->  page_summon（落在服装页签）
    page_summon  左边一列卡片 = 这个分类下的所有卡池，每个卡池有**自己的**每日免费
    ...          卡片右上角带红「!」= 这个卡池今天还有免费
    ...          点卡片 -> 底部「抽1次」右上角也出现红「!」，下面写「免费1次」
    ...          点「抽1次」 -> 「确认抽抽乐」弹窗（正文写着「免费1次」）-> 点「购买」
    ...          抽卡动画 -> 结果页（角色/装备详情）-> 左上角「<」回卡池，红点消失
    page_summon  点左侧「装备」页签 -> 同一套版式，另一列卡池

**同一枚红「!」在三个地方出现，含义完全不同** —— 2026-10-28 在这里栽过一次：

| 位置 | 含义 | 能当判据吗 |
|---|---|---|
| 左侧页签（服装/装备） | 这个分类下**还有**免费没抽 | 不能，它只知道"有"，不知道"哪个" |
| 卡池卡片右上角 | **这个卡池**今天还有免费 | **就是这个** |
| 「抽1次」右上角 | 当前显示的卡池有免费 | 只能确认"这一池"，要先点进去 |

只按钮红点会把免费全跳过：页面默认打开的那张卡池往往恰好没有免费，于是
"按钮上没有红点"被读成"今天没免费"，而其实同一页另外几张卡片都亮着
（2026-10-28 20:27 实机：服装页 1 张卡片带红点、装备页 2 张，脚本一个都没抽）。
反过来，只看页签红点又永远点不完 —— 它要整列都抽干净才灭。

A press is then verified by three separate observations, in this order:

1. the confirm dialog appears (`SUMMON_CONFIRM_DIALOG`),
2. the dialog says 免费1次 (`SUMMON_CONFIRM_FREE`) - the only guard against
   spending paid currency if the badge was ever misread,
3. the banner page leaves and comes back (`SUMMON_BANNER`), which is what tells
   "the pull played" apart from "the press was swallowed".

Only after that is the badge read again: still there means the pull did not
happen and the next round retries, gone means it did.
"""
from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import color_mask
from module.browndust.assets import (SUMMON_BANNER, SUMMON_CONFIRM_BUY,
                                     SUMMON_CONFIRM_CANCEL,
                                     SUMMON_CONFIRM_DIALOG,
                                     SUMMON_CONFIRM_FREE)
from module.browndust.browndust_ui import BrowndustUI, page_main, page_summon
from module.logger import logger

import cv2
import numpy as np

# Where the game draws the "the banner on screen still has its free pull" badge:
# the top right corner of the 「抽1次」 button. 17x17 is the whole badge, which is
# why it is measured by colour instead of by template - a template this small
# matches half the screen (the same 「!」 sits on the two tabs and on every card
# of the list, all within 0.30 similarity of each other).
SUMMON_DOT = (976, 604, 993, 621)
# Mean of the 166 red pixels inside that box on 抽卡页面.png.
SUMMON_DOT_COLOR = (207, 71, 63)
# Per channel tolerance of `color_mask`, wide enough for the badge's shading.
SUMMON_DOT_THRESHOLD = 60
# 142~152 pixels when the badge is there, 0 on each of the other 31 screenshots
# of the game, so 40 sits on a 4x margin either way.
SUMMON_DOT_PIXELS = 40
# The badge is drawn **after** the button and after the banner artwork, so on
# the frame a tab opens the button is already there and the badge is not. Read
# once, that frame answers "no free pull" for a tab that has one - 2026-10-28
# 20:27 实机就是这么跳过两次免费的（切完页签 0.4 秒就判定）。So the badge is
# waited for instead of read once, and the answer "no" is only given after this
# many seconds of not seeing it.
SUMMON_DOT_TIMEOUT = 3
# The re-read after a pull sits on a page that is not loading anything, so it
# does not need the same patience - a badge that is still there is there at once.
SUMMON_DOT_RECHECK = 2

# The card list on the left of the page. Each banner is one card, and a card
# still holding its daily free pull carries a red 「!」 on its top right corner
# (the same badge as on 「抽1次」, and the same colour).
#
# Only the right edge is scanned. `SUMMON_CARD_LIST` is the x band the badge
# lives in: cards end at x=360 and the badge is 20x19 at x=339~359, so its
# centre is x≈349 for every card. Scanning the whole card turned the first
# card's red-haired character into a "badge" - the artwork is full of reds.
SUMMON_CARD_LIST = (325, 75, 372, 520)
# Badge centre to press point: 45 px left and 28 px down is the middle of the
# card, clear of the list's scroll bar on the left and of the page on the right.
SUMMON_CARD_CLICK = (-45, 28)
# Shape filter for a badge: `color_mask` + dilation gives ~150~330 px in a
# 14~20 px box. Artwork fragments are either huge or a single pixel.
SUMMON_BADGE_MIN_AREA = 60
SUMMON_BADGE_MAX_AREA = 700
SUMMON_BADGE_MIN_SIZE = 10
SUMMON_BADGE_MAX_SIZE = 30
# A card press repaints the banner artwork and the button; the badge on the
# button is drawn last. 5 s is the same "did the press land" budget as a tab.
SUMMON_CARD_TIMEOUT = 5

# The 「抽1次」 button: 833~1011 x 606~652. The click point is the lower left of
# the badge on purpose - the badge hangs over the button's rounded top right
# corner, where a press is as likely to land on the panel behind it.
SUMMON_PULL1 = Button(area=(833, 606, 1011, 652), color=(0, 0, 0),  # alas-lint: allow - a click point; the button's label turns into a ticket price after the free pull, so there is nothing stable to match
                      button=(900, 620, 960, 640), name='SUMMON_PULL1')

# The two tabs of the page, left edge. `button` is the click point, `area` is
# the tab's **label**, and the label is what says which tab is open: the game
# draws the open tab's text in pure white and the other one in grey.
#
# Not the page title. The title (「服装抽抽乐」/「装备抽抽乐」) sits on a
# semi-transparent band over the banner artwork, and that artwork changes with
# every pickup, so the same title scored 0.83~0.90 against its own template and
# 0.73~0.74 against the wrong one - too close to call (2026-10-28 17:38 实机：
# 装备页签切过去成功了，标题模板却在 10 秒里一次都没过 0.85)。
#
# Not the icon either: the icon takes the theme colour of the pickup (orange on
# the costume banner, pale blue on the weapon one), so its brightness is not a
# stable "selected" signal. The label's colour is.
SUMMON_TAB_COSTUME = Button(area=(138, 188, 208, 218), color=(0, 0, 0),  # alas-lint: allow - a click point plus a brightness reading, there is no shape to match
                            button=(124, 155, 160, 190), name='SUMMON_TAB_COSTUME')
SUMMON_TAB_EQUIP = Button(area=(140, 282, 210, 310), color=(0, 0, 0),  # alas-lint: allow - a click point plus a brightness reading, there is no shape to match
                          button=(124, 249, 160, 285), name='SUMMON_TAB_EQUIP')

# Pixels above this luma inside the label box = the tab is the open one.
# Measured on the five banner screenshots of the game: open tab 72~96, closed
# tab 0~13, and 0 while the confirm dialog dims the page. 40 sits in between.
SUMMON_TAB_LABEL_LUMA = 230
SUMMON_TAB_LABEL_PIXELS = 40

# Leaving the result screen: the same circular 「<」 as the banner page's own
# back arrow, top left corner at (142, 34). A press in the middle of the screen
# does nothing there - the result screen is a full item/character sheet (name,
# rarity, element, CV, art), not a "tap anywhere" splash, and tapping its centre
# is what made the task hit `GameTooManyClickError` on 2026-10-28 20:37.
SUMMON_RESULT_BACK = Button(area=(126, 22, 160, 54), color=(0, 0, 0),  # alas-lint: allow - a click point on the result screen's own back arrow, guarded by the banner page being gone
                            button=(130, 24, 156, 48), name='SUMMON_RESULT_BACK')

# A press on 抽1次 opens the dialog in well under a second; 6 leaves room for a
# slow emulator without sitting on a press that was swallowed.
SUMMON_DIALOG_TIMEOUT = 6
# A press right after the banner is switched is eaten by the page's own fade-in,
# so the press is repeated. Three tries is "one real press plus two that were
# swallowed" - a button that is still bare after that is not going to open.
SUMMON_PULL_TRIES = 3
# The pull animation takes over the screen right away; if the banner page is
# still there after this long, the pull did not start.
SUMMON_LEAVE_TIMEOUT = 30
# Animation + result screen + the way back. The result screen waits for a
# press, so this only bounds the animation itself.
SUMMON_RESULT_TIMEOUT = 120
# Seconds between two presses on the result screen's back arrow. The arrow is
# there from the first frame of the result screen, but pressing it while the
# character animation is still playing is wasted, so the first press waits this
# long and the rest are spaced the same.
SUMMON_RESULT_CLICK = 3
# Pressing a tab is only verified by its label turning white, so the press is
# repeated while that has not happened yet - a tab press right after the page
# opens is the one most likely to be eaten by the page's own fade-in.
SUMMON_TAB_TIMEOUT = 10
SUMMON_TAB_RETRY = 3
# One free pull per banner per day, and a tab holds several banners (the list
# fits four cards on screen). This is the number of rounds per tab, not a
# limit on pulls: a round only counts when a badge was actually spent, and the
# list is re-read every round, so the loop ends on the first tab without one.
SUMMON_MAX_PULLS = 8

# The two tabs, in the order the game opens them.
SUMMON_TABS = (
    ('服装', SUMMON_TAB_COSTUME),
    ('装备', SUMMON_TAB_EQUIP),
)


class BrowndustSummon(BrowndustUI):
    """
    Take the free daily pull of both gacha tabs.

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
        logger.hr('Daily free gacha', level=1)
        if self.config.BrowndustSummon_Draw:
            taken = self.summon_free_pulls()
            logger.attr('Free pulls taken', taken)
        else:
            logger.info('BrowndustSummon.Draw is off, nothing to do')
        # Both tabs reset with the daily server update.
        self.config.task_delay(server_update=True)

    def summon_free_pulls(self):
        """
        Open the gacha page and take whatever is free on both tabs.

        Pages:
            in: page_main
            out: page_main

        Returns:
            int: Number of pulls taken.
        """
        self.ui_ensure(page_main)
        self.ui_ensure(page_summon)

        taken = 0
        for name, tab in SUMMON_TABS:
            taken += self.summon_take_free(name, tab)

        self.ui_goto_main()
        return taken

    def summon_take_free(self, name, tab):
        """
        Take every free pull of one tab.

        A tab is a **list** of banners and each banner has its own daily free
        pull, so the badge on 「抽1次」 only ever answers for the banner that is
        on screen. The card list on the left is what says where the free pulls
        are - measured 2026-10-28: the costume tab had one badge in its list and
        the weapon tab two, while the banner the page opens by default had none.
        Reading only the button skipped all three of them.

        Pages:
            in: page_summon
            out: page_summon

        Args:
            name (str): 服装 / 装备, for the log.
            tab (Button): The tab, both its click point and its label box.

        Returns:
            int: Pulls taken on this tab.
        """
        if not self.summon_open_tab(name, tab):
            return 0

        taken = 0
        for _ in range(SUMMON_MAX_PULLS):
            if not self.summon_pull_next(name):
                break
            taken += 1

        if taken:
            logger.info(f'{name}: {taken} free pull(s) taken')
        else:
            logger.info(f'{name}: no banner with a free pull left')
        return taken

    def summon_pull_next(self, name):
        """
        Take the free pull of the next banner that still has one.

        Two places to look, in this order:

        1. the banner already on screen - its 「抽1次」 button carries the badge.
           This is the banner the page opens with, or the one the previous
           round ended on.
        2. the card list - every banner that still holds a free pull has a red
           「!」 on the top right corner of its card. Open the top one, and its
           badge shows up on the button.

        A pull is never taken from a bare button, so a card that was misread as
        having a badge only costs one wasted press: `summon_open_card()` waits
        for the badge to appear before anything is pulled.

        Pages:
            in: page_summon
            out: page_summon

        Args:
            name (str): 服装 / 装备, for the log.

        Returns:
            bool: If a pull was taken.
        """
        if self.summon_free_available(timeout=SUMMON_DOT_RECHECK):
            return self.summon_pull_once()

        self.device.screenshot()
        badges = self.summon_card_badges()
        if not badges:
            return False

        if not self.summon_open_card(name, badges[0]):
            return False
        return self.summon_pull_once()

    def summon_open_card(self, name, badge):
        """
        Open the banner whose card still carries a 「!」.

        The press is verified by the badge appearing on 「抽1次」: a banner with
        no free pull leaves its button bare, so this also tells "the card press
        was swallowed" and "the badge belonged to another card" apart from a
        banner that really is free.

        Pages:
            in: page_summon
            out: page_summon

        Args:
            name (str): 服装 / 装备, for the log.
            badge (tuple[int, int]): Centre of the 「!」 on the card.

        Returns:
            bool: If the banner opened and offers a free pull.
        """
        point = (badge[0] + SUMMON_CARD_CLICK[0], badge[1] + SUMMON_CARD_CLICK[1])
        logger.info(f'{name}: open the banner at {point}')
        self.device.click_minitouch(point[0], point[1])  # alas-lint: allow - a card press, verified by the badge on the button below
        if not self.summon_free_available(timeout=SUMMON_CARD_TIMEOUT):
            return False
        # 红点出现不等于页面画完了：卡池立绘还在换图、按钮还在淡入，这时候按
        # 「抽1次」会被吞（见 `SUMMON_PULL_TRIES`）。等这块区域连续两帧不变。
        #
        # 这里一定会超时并打一条 "Area ... is still changing"：按钮上有循环
        # 播放的星点粒子，永远在动。那条 warning 不是故障，等 3 秒的收尾动作
        # 已经做完了（页面确实画完了），被吞的点击由下面的重试兜住。
        self.wait_until_still(SUMMON_PULL1.area, timeout=3)
        return True

    def summon_card_badges(self):
        """
        The red 「!」 marks of the card list, top to bottom.

        Only the right edge of the cards is read (`SUMMON_CARD_LIST`): the badge
        hangs on the top right corner at x≈349, while the artwork inside the
        cards is full of reds - the first card of the costume tab holds a
        red-haired character, and her hair was the first "badge" a full-width
        scan returned.

        Needs a fresh screenshot in `device.image`; the caller takes it.

        Returns:
            list[tuple[int, int]]: Centre of each badge, in screen coordinates.
        """
        mask = color_mask(self.image_crop(SUMMON_CARD_LIST, copy=False),
                          color=SUMMON_DOT_COLOR, threshold=SUMMON_DOT_THRESHOLD)
        # 淡入时「!」会碎成几块，先连起来再数。
        mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)
        _, _, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)

        x0, y0 = SUMMON_CARD_LIST[0], SUMMON_CARD_LIST[1]
        badges = []
        for i in range(1, len(stats)):
            _, _, w, h, area = stats[i]
            if not SUMMON_BADGE_MIN_AREA <= area <= SUMMON_BADGE_MAX_AREA:
                continue
            if not SUMMON_BADGE_MIN_SIZE <= w <= SUMMON_BADGE_MAX_SIZE:
                continue
            if not SUMMON_BADGE_MIN_SIZE <= h <= SUMMON_BADGE_MAX_SIZE:
                continue
            badges.append((int(centroids[i][0] + x0), int(centroids[i][1] + y0)))
        badges.sort(key=lambda b: b[1])
        return badges

    def summon_tab_open(self, tab):
        """
        Whether the given tab is the one the page is showing.

        The game draws the open tab's label in pure white and the other one in
        grey, so this is a brightness count - see `SUMMON_TAB_LABEL_LUMA` for
        why neither the page title nor the tab's icon can answer it.

        Args:
            tab (Button): The tab, `area` being its label box.

        Returns:
            bool: If this tab is open.
        """
        return self.ui_bright_count(tab, SUMMON_TAB_LABEL_LUMA) > SUMMON_TAB_LABEL_PIXELS

    def summon_open_tab(self, name, tab):
        """
        Switch the page to the given tab.

        The press is repeated until the label turns white, because a press right
        after the page opens tends to be eaten by its fade-in. What is *not*
        repeated is a read of the badge: if no press is accepted within
        `SUMMON_TAB_TIMEOUT` the tab is skipped, which is the harmless way to
        fail - skipping a tab costs one free pull, pressing blind on the wrong
        tab would read the other tab's badge.

        Pages:
            in: page_summon
            out: page_summon

        Args:
            name (str): 服装 / 装备, for the log.
            tab (Button): The tab.

        Returns:
            bool: If the tab is open.
        """
        # 正向条件（alas_lint R5）：转场帧两边都不匹配，`not appear` 会在任何
        # 不认识的画面上成立，于是"不在卡池页"成了默认答案。
        if self.appear(SUMMON_BANNER, offset=(20, 20)):
            if self.summon_tab_open(tab):
                logger.info(f'Already on the {name} tab')
                return True

            logger.info(f'Open the {name} tab')
            # 故意不 `.start()`：未启动的 Timer 第一次 `reached()` 就是 True，
            # 第一次点击不用白等一个间隔。
            click = Timer(SUMMON_TAB_RETRY)
            settle = 0
            for _ in self.loop(timeout=SUMMON_TAB_TIMEOUT):
                if self.summon_tab_open(tab):
                    # 切页签时中间帧整列都在重画，一帧命中不算数，连着两帧才算。
                    settle += 1
                    if settle >= 2:
                        return True
                else:
                    settle = 0
                    if click.reached():
                        click.reset()
                        self.device.click(tab)  # alas-lint: allow - a tab press is verified by its label on the next rounds

            logger.warning(f'The {name} tab did not open')
            return False

        logger.warning('Not on the gacha page, cannot switch tabs')
        return False

    def summon_free_available(self, timeout=SUMMON_DOT_TIMEOUT):
        """
        Whether the 「抽1次」 button still carries the free-pull badge.

        Not a single read: the game paints the badge a few frames after the
        button and the banner artwork, so right after a tab opens the honest
        answer is "not yet", not "no". See `SUMMON_DOT_TIMEOUT`.

        Args:
            timeout (int, float): Seconds to wait for the badge before saying no.

        Returns:
            bool: If a free pull is available.
        """
        for _ in self.loop(timeout=timeout):
            if self.image_color_count(SUMMON_DOT, color=SUMMON_DOT_COLOR,
                                      threshold=SUMMON_DOT_THRESHOLD,
                                      count=SUMMON_DOT_PIXELS):
                return True
        return False

    def summon_pull_once(self):
        """
        Press 抽1次, confirm the free dialog and wait out the pull.

        Pages:
            in: page_summon
            out: page_summon

        Returns:
            bool: If the pull played and the banner page is back.
        """
        logger.info('Free pull available, press the button')
        # 判据是上面那枚红点，所以这里不再 appear 一次：`SUMMON_PULL1` 是没有
        # 模板的点击点（按钮上的「免费1次」用掉后会变成票价，硬约束 82：纯坐标
        # 按钮不能进 appear 家族）。
        #
        # 按下去要重试：刚换完卡池的按钮还在淡入，第一下会被吞掉 —— 2026-10-28
        # 20:44 装备页就是这样，红点已经看见了，按下去却什么都没有。
        for i in range(SUMMON_PULL_TRIES):
            self.device.click(SUMMON_PULL1)  # alas-lint: allow - click point, guarded by summon_free_available() in the caller
            if self.wait_until_appear(SUMMON_CONFIRM_DIALOG, offset=(20, 20),
                                      timeout=SUMMON_DIALOG_TIMEOUT, settle=2):
                break
            logger.warning(f'The confirm dialog did not show up, press again ({i + 1}/{SUMMON_PULL_TRIES})')
        else:
            logger.warning('The press on 抽1次 was swallowed every time, skip this banner')
            return False

        # 「购买」也是「取消」的邻居，只有弹窗正文写着「免费1次」才允许按：
        # 万一红点是别的东西（比如折扣），这一条挡在扣钱之前。
        if self.appear(SUMMON_CONFIRM_FREE, offset=(20, 20)):
            if self.appear(SUMMON_CONFIRM_BUY, offset=(20, 20)):
                logger.info('Dialog says 免费1次, press 购买')
                self.device.click(SUMMON_CONFIRM_BUY)  # alas-lint: allow - same dialog, both checks above are the guard
            else:
                logger.warning('The dialog has no 购买 button')
                return False
        else:
            logger.warning('The dialog does not offer a free pull, press 取消')
            if self.appear(SUMMON_CONFIRM_CANCEL, offset=(20, 20)):
                self.device.click(SUMMON_CONFIRM_CANCEL)  # alas-lint: allow - the dialog was just matched, this is the way out of it
            return False

        if not self.wait_until_disappear(SUMMON_CONFIRM_DIALOG, offset=(20, 20),
                                         timeout=10, settle=2):
            logger.warning('The confirm dialog did not close')
            return False

        return self.summon_wait_banner()

    def summon_wait_banner(self):
        """
        Wait out the pull animation and the result screen.

        The banner page has to be **seen leaving** first. It is still on screen
        while the confirm dialog is up (0.93 under the overlay), so a plain wait
        for it to come back would return on the frame the dialog closes - and
        the task would then read the badge on a half drawn page and press the
        next tab while the animation is still playing.

        The result screen is a character sheet with a 「<」 in the top left
        corner, and that arrow is the only way back - a press in the middle of
        the screen does nothing. The press is throttled and only sent while the
        banner page is gone.

        Pages:
            in: page_summon
            out: page_summon

        Returns:
            bool: If the banner page is back.
        """
        if not self.wait_until_disappear(SUMMON_BANNER, offset=(20, 20),
                                         timeout=SUMMON_LEAVE_TIMEOUT, settle=2):
            logger.warning('The banner page stayed, the pull did not start')
            return False

        tap = Timer(SUMMON_RESULT_CLICK).start()
        for _ in self.loop(timeout=SUMMON_RESULT_TIMEOUT):
            if self.appear(SUMMON_BANNER, offset=(20, 20)):
                # The button's label is being redrawn from 免费1次 to a ticket
                # price while the page fades in; reading the badge before that
                # settles is reading a frame that is not the page yet.
                self.wait_until_still(SUMMON_PULL1.area, timeout=3)
                return True
            if tap.reached():
                tap.reset()
                logger.info('Result screen, press the back arrow')
                self.device.click(SUMMON_RESULT_BACK)  # alas-lint: allow - only sent while the banner page is gone, which is the guard
                continue

        logger.warning('The banner page did not come back after the pull')
        return False
