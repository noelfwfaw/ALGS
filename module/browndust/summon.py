"""
每日免费抽抽乐 (Brown Dust II).

2026-11-08 换了一套流程，旧的红点版已经删掉：

    page_main --底栏「抽抽乐」-->  page_summon（落在服装页签）
    页签左下角一枚「所有免费抽抽乐」按钮
    -> 点它 -> 「确认抽抽乐」弹窗（正文「目前有 N 次免费……是否全部进行？」）
    -> 点「确认」-> 这一页签当天的免费一次抽完 -> 按钮消失
    -> 切到装备页签重复一遍

所以判据只有一个：**这枚按钮还在不在**。按钮消失了就是今天抽完了，
不用像旧版那样去每张卡池的右上角找红「!」、再逐池点「抽1次」。

实测（2026-11-08 的六张截图，`screenshots/browndust/`）：

| 读法 | 免费抽页面（服装 3 张卡池 + 装备） | 抽完后的页面 |
|---|---|---|
| 灰度匹配 | 0.900 / 0.908 / 0.925 / 1.000 | 0.185 / 0.234 |
| 固定二值（luma>210） | 0.952 / 0.976 / 0.977 / 1.000 | 0.19 / 0.19 |

按钮是**半透明**的：「所有免费抽抽乐」几个白字直接压在会动的立绘上，
背景一换灰度分就掉（同一张模板在四张图上差 0.10）。白字先过一遍二值，
背景被削掉，四张图收进 0.05 以内。这就是这里不用 `match()` 也不用
`match_binary()`（Otsu 的阈值跟着背景漂，四张图只剩 0.901~0.939）的原因。

「确认抽抽乐」弹窗上的「确认」是普通的不透明胶囊，灰度模板就够：两个页签
的弹窗都是 1.000，非弹窗画面（大厅、页签页、结果页）最高 0.327。

旧版（2026-10-28）逐张卡池找红「!」、按「抽1次」、再在弹窗里核对
「免费1次」—— 那套东西全部删掉了：新按钮一次把整个页签的免费做完，
次数由游戏在弹窗里写明。
"""
import cv2
import numpy as np

from module.base.button import Button
from module.base.timer import Timer
from module.browndust.assets import (SUMMON_BANNER, SUMMON_CONFIRM_OK,
                                     SUMMON_FREE_ALL)
from module.browndust.browndust_ui import BrowndustUI, page_main, page_summon
from module.logger import logger

# 「所有免费抽抽乐」按钮的二值匹配参数。搜索框 = 素材 area 四周各放 20 像素
# （跟 `appear(offset=(20, 20))` 同一个余量），模板是白字，所以阈值取 210
# （实测白字 230~255，立绘里的高光很少有整块越过 210 的）。
SUMMON_FREE_ALL_OFFSET = 20
SUMMON_FREE_ALL_LUMA = 210
# 四张免费抽页面 0.952~1.000，抽完后的页面 0.19，0.90 两边都留足。
SUMMON_FREE_ALL_SIMILARITY = 0.90
# 等按钮画出来的时间。页面刚进来、抽完刚回来都要等它重画；等不到就是没有了。
# 5 秒对"今天已经抽完"那次多花的等待来说不算长。
SUMMON_FREE_ALL_TIMEOUT = 5

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
# 2026-11-08 实测：服装页签打开 108、装备页签打开 94，另一边 10 / 0。
SUMMON_TAB_LABEL_LUMA = 230
SUMMON_TAB_LABEL_PIXELS = 40

# Leaving the result screen: the same circular 「<」 as the banner page's own
# back arrow, top left corner at (142, 34). A press in the middle of the screen
# does nothing there - the result screen is a full item/character sheet (name,
# rarity, element, CV, art), not a "tap anywhere" splash, and tapping its centre
# is what made the task hit `GameTooManyClickError` on 2026-10-28 20:37.
SUMMON_RESULT_BACK = Button(area=(126, 22, 160, 54), color=(0, 0, 0),  # alas-lint: allow - a click point on the result screen's own back arrow, guarded by the banner page being gone
                            button=(130, 24, 156, 48), name='SUMMON_RESULT_BACK')

# A press on the button opens the dialog in well under a second; 6 leaves room
# for a slow emulator without sitting on a press that was swallowed.
SUMMON_DIALOG_TIMEOUT = 6
# A press right after a tab is switched is eaten by the page's fade-in, so the
# press is repeated. Three tries is "one real press plus two that were
# swallowed" - a button that still opens nothing is not going to open.
SUMMON_FREE_TRIES = 3
# The pull animation takes over the screen right away; if the banner page is
# still there after this long, no pull started.
SUMMON_LEAVE_TIMEOUT = 30
# Animation + result screen + the way back. The result screen waits for a
# press, so this only bounds the animation itself.
SUMMON_RESULT_TIMEOUT = 120
# Seconds between two presses on the result screen's back arrow.
SUMMON_RESULT_CLICK = 3
# Pressing a tab is only verified by its label turning white, so the press is
# repeated while that has not happened yet.
SUMMON_TAB_TIMEOUT = 10
SUMMON_TAB_RETRY = 3
# One press takes every free pull of the tab (the dialog says so), so a second
# round only exists for the case where the game leaves the button up while it
# still has a free pull to give. Three rounds is already generous.
SUMMON_MAX_ROUNDS = 3

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
            int: Number of 「所有免费抽抽乐」 rounds taken.
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

        The tab's 「所有免费抽抽乐」 button is the whole answer: press it, confirm
        the dialog, the game plays every free pull at once, and the button is
        gone. See the module docstring for the measured scores.

        Pages:
            in: page_summon
            out: page_summon

        Args:
            name (str): 服装 / 装备, for the log.
            tab (Button): The tab, both its click point and its label box.

        Returns:
            int: Rounds taken on this tab.
        """
        if not self.summon_open_tab(name, tab):
            return 0

        taken = 0
        for _ in range(SUMMON_MAX_ROUNDS):
            if not self.summon_free_all_available():
                break
            if not self.summon_pull_all_free(name):
                break
            taken += 1

        if taken:
            logger.info(f'{name}: {taken} free round(s) taken')
        else:
            logger.info(f'{name}: no free pull left')
        return taken

    def summon_free_all_available(self, timeout=SUMMON_FREE_ALL_TIMEOUT):
        """
        Whether the tab still shows its 「所有免费抽抽乐」 button.

        The read is waited for, not taken once: right after the page fades in
        the button has not been drawn yet, and that frame must not be read as
        "no free pull left".

        Returns:
            bool: If the button is there.
        """
        for _ in self.loop(timeout=timeout):
            if self.summon_free_all_appear():
                return True
        return False

    def summon_free_all_appear(self):
        """
        Match the button on the current frame.

        A fixed-threshold binary match instead of `Button.match_binary()`: the
        button is translucent, so everything inside it takes the colour of the
        banner artwork behind it, and Otsu picks a different threshold on every
        banner. The white label survives any of them, so the label is what is
        matched - see the module docstring.

        Returns:
            bool: If the button is there.
        """
        x0, y0, x1, y1 = SUMMON_FREE_ALL.area
        area = (x0 - SUMMON_FREE_ALL_OFFSET, y0 - SUMMON_FREE_ALL_OFFSET,
                x1 + SUMMON_FREE_ALL_OFFSET, y1 + SUMMON_FREE_ALL_OFFSET)
        image = cv2.cvtColor(self.image_crop(area, copy=False), cv2.COLOR_RGB2GRAY)
        binary = (image > SUMMON_FREE_ALL_LUMA).astype(np.uint8) * 255

        SUMMON_FREE_ALL.ensure_template()
        template = cv2.cvtColor(SUMMON_FREE_ALL.image, cv2.COLOR_RGB2GRAY)
        template = (template > SUMMON_FREE_ALL_LUMA).astype(np.uint8) * 255

        result = cv2.matchTemplate(binary, template, cv2.TM_CCOEFF_NORMED)
        _, similarity, _, _ = cv2.minMaxLoc(result)
        return similarity > SUMMON_FREE_ALL_SIMILARITY

    def summon_pull_all_free(self, name):
        """
        Press the button, confirm the dialog and wait out the pulls.

        Pages:
            in: page_summon
            out: page_summon

        Args:
            name (str): 服装 / 装备, for the log.

        Returns:
            bool: If the pulls played and the banner page is back.
        """
        logger.info(f'{name}: press 所有免费抽抽乐')
        # 按钮刚被匹配到，这里不重复 appear；按下去要重试，刚切完页签的那一下
        # 会被页面淡入吃掉。判据是弹窗上的「确认」—— 它只在弹窗上出现，
        # 实测弹窗 1.000、其它画面最高 0.327。
        for i in range(SUMMON_FREE_TRIES):
            self.device.click(SUMMON_FREE_ALL)  # alas-lint: allow - matched right above, the dialog below is the proof
            if self.wait_until_appear(SUMMON_CONFIRM_OK, offset=(20, 20),
                                      timeout=SUMMON_DIALOG_TIMEOUT, settle=2):
                break
            logger.warning(f'The confirm dialog did not show up, press again ({i + 1}/{SUMMON_FREE_TRIES})')
        else:
            logger.info(f'{name}: the button opens nothing, no free pull left')
            return False

        logger.info('Confirm')
        self.device.click(SUMMON_CONFIRM_OK)  # alas-lint: allow - the dialog was just matched, this is its own button
        if not self.wait_until_disappear(SUMMON_CONFIRM_OK, offset=(20, 20),
                                         timeout=10, settle=2):
            logger.warning('The confirm dialog did not close')
            return False

        return self.summon_wait_banner()

    def summon_tab_open(self, tab):
        """
        Whether the given tab is the one the page is showing.

        The game draws the open tab's label in pure white and the other one in
        grey, so this is a brightness count - see `SUMMON_TAB_LABEL_LUMA`.

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
        after the page opens tends to be eaten by its fade-in. If no press is
        accepted within `SUMMON_TAB_TIMEOUT` the tab is skipped, which is the
        harmless way to fail - one tab costs at most one day's free pulls.

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

    def summon_wait_banner(self):
        """
        Wait out the pull animation and the result screen.

        The banner page has to be **seen leaving** first. It is still on screen
        while the confirm dialog is up (0.88~0.94 under the overlay), so a plain
        wait for it to come back would return on the frame the dialog closes -
        and the task would then read the button on a half drawn page.

        The result screen is a character/equipment sheet with a 「<」 in the top
        left corner, and that arrow is the only way back - a press in the middle
        of the screen does nothing. The press is throttled and only sent while
        the banner page is gone.

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
                return True
            if tap.reached():
                tap.reset()
                logger.info('Result screen, press the back arrow')
                self.device.click(SUMMON_RESULT_BACK)  # alas-lint: allow - only sent while the banner page is gone, which is the guard
                continue

        logger.warning('The banner page did not come back after the pull')
        return False
