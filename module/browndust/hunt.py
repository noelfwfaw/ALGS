"""
快速狩猎 (Brown Dust II).

Flow observed in game (2026-10-28, screenshots in `screenshots/browndust/`):

    page_main  --右上角「快速狩猎」图标-->  page_hunt（落在上次看的那一页）
    page_hunt  左侧四个页签：狩猎场 / 金币 / 史莱姆 / 圣石洞穴
    page_hunt  右下「快速狩猎」--> 面板（MIN/-10/+10/MAX + 滑块 + −/+）--> 点「狩猎」
    ...        战斗动画 -> REWARD 结算（「点击画面即可返回」）-> 回到同一个页签
    page_main  左上角箭头回去

Two separate daily budgets, and that is the whole reason this task has a config
gate at all:

- 狩猎场 / 金币 / 史莱姆 share one stamina bar (⚔ 90, 6 per run) -> at most 15
  runs a day between the three of them.
- 圣石洞穴 burns 火把 instead (🔥 60, 6 per run) -> at most 10 runs, split
  between its five caves (火 / 水 / 风 / 光 / 暗).

Both caps are exactly `resource / 6`. The config is rejected up front rather
than clamped, because "I asked for 8+8 and silently got 15" is the kind of
surprise that makes people distrust the scheduler.

The config is only a daily *budget* though - what the bar actually holds right
now is another matter (the task can run at 22:00 with 11 runs left, or right
after a manual session with 3). The game does not say a word about that: no
warning, no disabled button, the stepper just stops moving at the number the
resource pays for. So the cap is detected by walking the stepper up, and an
empty bar is detected by 「狩猎」 failing to close the panel. Both outcomes are
logged with the real number, and both stop the rest of that resource's targets
instead of letting them each re-run the whole dialog / fight / reward wait
until the task timeout - that slow grind is what "stuck" looks like here.

Per tab:

- 狩猎场 / 金币 / 史莱姆 each have exactly **one** selectable node on the map
  (野猪洞穴 / 哥布林遗迹 / 史莱姆王国); the rest are greyed out. Switching the
  tab is the whole job.
- 圣石洞穴 has five nodes listed top to bottom on the left edge. They have to be
  clicked explicitly: the game remembers the last one, and that is not
  necessarily the first (it opened on 风 after a manual session).

Nothing is decided by a tab's or a node's **icon**. The icons are tinted by the
current theme and a template of them scores 0.93~1.00 on *every* tab, selected
or not. What separates selected from not is the label's brightness - the game
draws the selected label white and the rest grey. Measured: 190~346 pixels
above luma 200 when selected, **0** when not.
"""
import numpy as np

from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import crop
from module.browndust.assets import HUNT_BUTTON, HUNT_REWARD, HUNT_START
from module.browndust.browndust_ui import BrowndustUI, page_hunt
from module.exception import RequestHumanTakeover
from module.logger import logger

# ---------------------------------------------------------------------------
# 左侧四个页签。`label` 只用来数白像素（选中态），`point` 是图标中心（点击区）。
# 文字行和图标必须分开：图标本身是白色线稿，选中与否都亮，混在一起就分不开。
# ---------------------------------------------------------------------------
HUNT_TAB_LABELS = {
    'field': (100, 143, 185, 160),
    'coin': (100, 219, 185, 237),
    'slime': (100, 296, 185, 314),
    'cave': (100, 374, 185, 390),
}
HUNT_TAB_POINTS = {
    'field': (138, 130),
    'coin': (138, 218),
    'slime': (138, 300),
    'cave': (138, 380),
}
HUNT_TAB_NAMES = {
    'field': '狩猎场',
    'coin': '金币',
    'slime': '史莱姆',
    'cave': '圣石洞穴',
}

# 圣石洞穴的五个洞穴，从上到下。位置是按行统计亮像素量出来的（文字带
# 113-126 / 168-183 / 225-238 / 281-294 / 337-350），行距 **56**。
#
# 别照截图目测：缩略图看下来像 62.5，按那个排 light 差 14px、dark 差 28px，
# 标签框落到两行中间的空隙里，判据永远读不到白字，于是反复点同一个点直到超时
# （2026-10-28 实机栽过两次，第二次还是"修正"之后）。
HUNT_CAVE_LABELS = {
    'fire': (175, 111, 285, 127),
    'water': (175, 167, 285, 184),
    'wind': (175, 224, 285, 240),
    'light': (175, 280, 285, 296),
    'dark': (175, 336, 285, 352),
}
HUNT_CAVE_POINTS = {
    'fire': (210, 119),
    'water': (210, 176),
    'wind': (210, 232),
    'light': (210, 288),
    'dark': (210, 344),
}
# 整列五个洞穴（只框列表，不含右边地图，地图上有一直在动的动画）。
HUNT_CAVE_LIST_AREA = (160, 100, 300, 390)
HUNT_CAVE_NAMES = {
    'fire': '火之洞穴',
    'water': '水之洞穴',
    'wind': '风之洞穴',
    'light': '光之洞穴',
    'dark': '暗之洞穴',
}

# 选中态判据：白像素数。实测选中 190~346，未选中 0（最亮的灰字只有 149），
# 100 两边都留着 2 倍以上的余量。
HUNT_LABEL_LUMA = 200
HUNT_LABEL_PIXELS = 100

# 面板里的档位（MIN）和 +1 圆钮。纯坐标：它们只是文字和圆形，没有可匹配的图案，
# 而且只在「快速狩猎」面板里出现 —— 调用点由 HUNT_START 守住。
#
# 只留了 MIN 和 +1：-10 / +10 / -1 / MAX 都不需要。+10 从 1 跳到 10 而不是 11，
# 上限比 10 小时又会跳到那个上限，跳完当前值不可知（数字读不出来），补差额必然
# 差几次；-1 / -10 只在"配得比当前小"时才用得上，而每次都从 MIN 起步就不会超。
HUNT_TIMES_MIN = Button(area=(455, 325, 490, 350), color=(0, 0, 0),  # alas-lint: allow - a segment of the dialog's stepper, guarded by HUNT_START
                        button=(472, 337, 472, 337), name='HUNT_TIMES_MIN')
HUNT_TIMES_PLUS1 = Button(area=(843, 378, 868, 402), color=(0, 0, 0),  # alas-lint: allow - the round + of the dialog's slider, guarded by HUNT_START
                          button=(855, 390, 855, 390), name='HUNT_TIMES_PLUS1')

# 取消：面板左下那个浅色按钮的中心。
HUNT_TIMES_CANCEL = Button(area=(450, 541, 540, 571), color=(0, 0, 0),  # alas-lint: allow - the dialog's cancel button, guarded by HUNT_START
                           button=(495, 556, 495, 556), name='HUNT_TIMES_CANCEL')

# 「狩猎N次」整行。只用来回答"这一下按下去界面上有没有东西变"，不读数字 ——
# 数字的字符块随位数变宽，取哪个框都会和「狩猎」「次」粘在一起。
HUNT_COUNT_AREA = (598, 240, 690, 268)

# 结算页的点击点：底部那条「点击画面即可返回。」的正下方。
#
# 别点横幅的左边或右边 —— 实测（2026-10-28 21:47）点 (340~380, 375~400) 那片
# 蓝色 V 形条纹连点 10 次毫无反应，一直点到 `GameTooManyClickError`。只有底部
# 这条空白带上的一下才真的退出去，而且一下就够。
HUNT_REWARD_TAP = Button(area=(610, 580, 670, 620), color=(0, 0, 0),  # alas-lint: allow - the reward screen says 点击画面即可返回, there is no button to match
                         button=(610, 580, 670, 620), name='HUNT_REWARD_TAP')

# 每日上限 = 资源 / 6（⚔90、🔥60）。用户配超了直接拒，见模块 docstring。
HUNT_TIMES_CAP_HUNT = 15
HUNT_TIMES_CAP_CAVE = 10

# 两条预算的名字，只用在日志里。
HUNT_BUDGET_NAMES = {
    'shared': '体力 (⚔)',
    'cave': '火把 (🔥)',
}

# `hunt_spend()` 的结果。游戏对"没资源"这件事一个提示都不给 —— 面板照开，
# 只是把次数截到资源允许的那一档，所以这三种状态必须自己分清楚：
HUNT_SPEND_OK = 'ok'          # 打满了配置的次数
HUNT_SPEND_CAPPED = 'capped'  # 次数被资源截断，打到了当前上限
HUNT_SPEND_NO_RUNS = 'no_runs'  # 一次都打不了
HUNT_SPEND_BROKEN = 'broken'  # 打出去了但回不到地图，屏幕状态不可知

# `hunt_open_dialog()` 的结果。
HUNT_DIALOG_OK = 'ok'
HUNT_DIALOG_NO_PAGE = 'no_page'    # 不在 map 页，点不到「快速狩猎」
HUNT_DIALOG_NO_DIALOG = 'no_dialog'  # 点了但面板不出来

# 按一下之后等「狩猎N次」那一行重画的时限。换数字是本地运算，一帧就够；
# 给 2 秒是因为模拟器偶尔会漏一帧截图。
HUNT_COUNT_TIMEOUT = 2
# 按空（被淡入吞掉）时的重试次数。
HUNT_PRESS_TRIES = 2
# 切页签 / 切洞穴之后等选中态画出来。进页签时地图还在加载，点下去会被吞，
# 实测连点 5 次全空过，所以给得比"一屏动画"宽。
HUNT_TAB_TIMEOUT = 20
# 切洞穴要重载整张地图（换一个关卡 = 重新拉地图），首次进某个洞穴实测能拖过
# 10 秒，期间点下去全被吞（2026-10-28 实机：连点 6 次全空）。给它单独一档。
HUNT_CAVE_TIMEOUT = 40
# 面板出现的时限。
HUNT_DIALOG_TIMEOUT = 6
# 战斗动画一直到结算页出现。这一段的画面上没有任何可识别的东西，只能等结算页。
HUNT_ANIMATION_TIMEOUT = 120
# 结算页要等一次点击，所以这个只框住"点掉它、等回地图"。
HUNT_RESULT_TIMEOUT = 60
# 结算页是"点一下才走"，节流一下，免得被框架判成连点。
HUNT_REWARD_INTERVAL = 2
# 15 次要按 14 下 +1，而框架在 15 次窗口内同键 12 次就报 GameTooManyClickError。
HUNT_CLICK_BURST = 5
# 整个任务的总时限。
#
# 每一个环节都是有界的，但把最坏情况乘起来就是"卡住"的形状：13 个目标，每个都可能
# 花 12 秒（面板打不开）+ 40 秒（切洞穴）+ 120 秒（等结算页）+ 60 秒（点不掉结算页），
# 加一起能磨掉一个多小时。资源见底的时候更是如此 —— 面板不说话，脚本就一个一个目标
# 地重走全套等待。给它一个硬上限，超了就带着已完成的次数收工。
# 正常打满 25 次（⚔15 + 🔥10）实测 8 分钟左右，30 分钟是 3 倍余量。
HUNT_TASK_TIMEOUT = 30 * 60
# 连续这么多个目标的页签都打不开，就认定页面已经不对劲了。
#
# 单次失败已经等满了 HUNT_TAB_TIMEOUT；那个超时是给"地图加载慢"的，不是给"页面崩了"
# 的。不设这条的话，页面一旦切到别处，13 个目标会各自老老实实等 20 秒再继续。
HUNT_TAB_FAILS_MAX = 2


class BrowndustHunt(BrowndustUI):
    """
    Daily 快速狩猎.

    Pages:
        in: Any page
        out: page_main
    """

    def hunt_label_selected(self, area):
        """
        Whether a tab/cave label is drawn in the selected (white) colour.

        Args:
            area (tuple): Label area.

        Returns:
            bool: True if selected.
        """
        return self.ui_bright_count(area, HUNT_LABEL_LUMA) >= HUNT_LABEL_PIXELS

    def run(self):
        """
        Pages:
            in: Any page
            out: page_main
        """
        plan = self.hunt_plan()
        if not plan:
            logger.info('Every 快速狩猎 target is 0, nothing to do')
            self.config.task_delay(server_update=True)
            return

        self.ui_goto(page_hunt)
        logger.info('Hunt plan: ' + ', '.join(
            HUNT_TAB_NAMES[tab] + (HUNT_CAVE_NAMES[cave] if cave else '') + f' x{times}'
            for tab, cave, times in plan))
        done = 0
        # 两条资源互不相干，一条见底不该把另一条也停掉（⚔ 用完时火把多半还有）。
        exhausted = set()
        tab_fails = 0
        timeout = Timer(HUNT_TASK_TIMEOUT).start()
        for tab, cave, times in plan:
            name = HUNT_TAB_NAMES[tab] + (HUNT_CAVE_NAMES[cave] if cave else '')
            budget = 'cave' if cave else 'shared'
            if budget in exhausted:
                logger.info(f'Skip {name} x{times}, no {HUNT_BUDGET_NAMES[budget]} left for it')
                continue
            if timeout.reached():
                logger.warning(f'The task took over {HUNT_TASK_TIMEOUT}s, give up the rest '
                               f'with {done} runs spent')
                break

            logger.hr(f'Hunt {name} x{times}', level=2)
            if not self.hunt_open_tab(tab):
                tab_fails += 1
                logger.warning(f'Skip {name}, the tab did not open ({tab_fails} in a row)')
                if tab_fails >= HUNT_TAB_FAILS_MAX:
                    logger.warning('The page is not where it is supposed to be, give up the '
                                   f'rest with {done} runs spent')
                    break
                continue
            tab_fails = 0
            if cave and not self.hunt_open_cave(cave):
                logger.warning(f'Skip {name}, the cave did not open')
                continue

            spent, reason = self.hunt_spend(times)
            done += spent
            if reason == HUNT_SPEND_OK:
                continue
            if reason == HUNT_SPEND_CAPPED:
                # 打到当前资源允许的上限了。每次固定 6 点，剩下的必然不足一次
                # （否则面板还能再 +1），所以同组后面几个目标不用再试。
                logger.warning(f'{name}: only {spent} of {times} runs, '
                               f'{HUNT_BUDGET_NAMES[budget]} ran out')
                exhausted.add(budget)
                continue
            if reason == HUNT_SPEND_NO_RUNS:
                logger.warning(f'{name}: not a single run went through, '
                               f'{HUNT_BUDGET_NAMES[budget]} cannot pay for even one')
                exhausted.add(budget)
                continue
            # BROKEN：次数已经花出去了，但结算页没回来。屏幕停在哪谁也说不准，
            # 继续点有把地图上的关卡点开的风险，整个任务就此收手。
            logger.warning(f'{name}: the screen did not come back, stop the task here')
            break

        logger.info(f'[Hunt runs spent] {done}')
        self.ui_goto_main()
        self.config.task_delay(server_update=True)

    def hunt_plan(self):
        """
        Turn the config into an ordered list of (tab, cave, times).

        Returns:
            list[tuple]: Only the entries with `times > 0`.

        Raises:
            RequestHumanTakeover: If one of the two budgets is over its cap.
        """
        field = self.config.BrowndustHunt_HuntField
        coin = self.config.BrowndustHunt_HuntCoin
        slime = self.config.BrowndustHunt_HuntSlime
        caves = [
            ('fire', self.config.BrowndustHunt_CaveFire),
            ('water', self.config.BrowndustHunt_CaveWater),
            ('wind', self.config.BrowndustHunt_CaveWind),
            ('light', self.config.BrowndustHunt_CaveLight),
            ('dark', self.config.BrowndustHunt_CaveDark),
        ]

        plan = [(tab, None, times) for tab, times in
                (('field', field), ('coin', coin), ('slime', slime)) if times > 0]
        plan += [('cave', cave, times) for cave, times in caves if times > 0]
        if not plan:
            return plan

        # 校验放在"排完计划之后"：全 0 表示今天不打，那不该弹配置错误。
        shared = field + coin + slime
        if shared > HUNT_TIMES_CAP_HUNT:
            logger.critical(f'狩猎场+金币+史莱姆 = {shared} runs, but they share one stamina bar '
                            f'that only allows {HUNT_TIMES_CAP_HUNT} a day')
            raise RequestHumanTakeover
        cave_total = sum(times for _, times in caves)
        if cave_total > HUNT_TIMES_CAP_CAVE:
            logger.critical(f'The five 圣石洞穴 add up to {cave_total} runs, but the daily '
                            f'limit is {HUNT_TIMES_CAP_CAVE}')
            raise RequestHumanTakeover
        return plan

    def hunt_open_tab(self, tab):
        """
        Switch the page to one of the four tabs.

        Pages:
            in: page_hunt
            out: page_hunt

        Args:
            tab (str): field / coin / slime / cave.

        Returns:
            bool: If the tab is open.
        """
        label = HUNT_TAB_LABELS[tab]
        if self.hunt_label_selected(label):
            logger.info(f'Already on the {tab} tab')
            return True

        logger.info(f'Open the {tab} tab')
        return self.hunt_wait_selected(label, HUNT_TAB_POINTS[tab], f'the {tab} tab')

    def hunt_open_cave(self, cave):
        """
        Pick one of the five caves of 圣石洞穴.

        Pages:
            in: page_hunt (cave tab)
            out: page_hunt (cave tab)

        Args:
            cave (str): fire / water / wind / light / dark.

        Returns:
            bool: If the cave is selected.
        """
        # 没在洞穴页的时候，下面那些点会落到地图上（可能直接开一关），所以先确认。
        if not self.hunt_label_selected(HUNT_TAB_LABELS['cave']):
            logger.warning('The cave tab is not open, cannot pick a cave')
            return False

        label = HUNT_CAVE_LABELS[cave]
        if self.hunt_label_selected(label):
            logger.info(f'Already on the {cave} cave')
            return True

        # 页签刚切过来时整列还在淡入，这时候点下去会被吞，白白丢掉一次。
        self.wait_until_still(HUNT_CAVE_LIST_AREA, timeout=3)
        logger.info(f'Open the {cave} cave')
        return self.hunt_wait_selected(label, HUNT_CAVE_POINTS[cave], f'the {cave} cave',
                                       timeout=HUNT_CAVE_TIMEOUT)

    def hunt_wait_selected(self, label, point, what, timeout=HUNT_TAB_TIMEOUT):
        """
        Press `point` until the label at `area` turns white.

        Pages:
            in: page_hunt
            out: page_hunt

        Args:
            label (tuple): Label area of the target tab/cave.
            point (tuple): Where to press.
            what (str): For the log.
            timeout (int): Seconds before giving up.

        Returns:
            bool: If the label turned white.
        """
        press = Timer(2)
        for _ in self.loop(timeout=timeout):
            if self.hunt_label_selected(label):
                # 切页时整列都在重画，一帧命中不算数：等它稳定，再确认一次。
                # 这一条不是保险，是必需 —— 实测 `hunt_open_tab('cave')` 报成功、
                # 实际还停在狩猎场页，后面的洞穴点击就全落到地图上了。
                self.wait_until_still(label, timeout=2)
                if self.hunt_label_selected(label):
                    return True
            if press.reached():
                press.reset()
                self.device.click_minitouch(point[0], point[1])  # alas-lint: allow - verified by the label's colour on the next round

        logger.warning(f'{what} did not open')
        return False

    def hunt_spend(self, times):
        """
        Spend up to `times` runs on whatever tab/cave is open right now.

        The panel never refuses anything: it silently caps the stepper at
        whatever the current resource allows (measured: ⚔ 66/90 -> the stepper
        stops at 11 and the button reads 「狩猎 ⚔66」). That silent cap is the
        only "out of stamina" signal the game gives, so it is what this method
        reports on - and it is reported, not assumed away: "asked for 15, got
        11" has to show up in the log, otherwise the total is a lie.

        Pages:
            in: page_hunt
            out: page_hunt

        Args:
            times (int):

        Returns:
            tuple: (runs spent, one of HUNT_SPEND_*).
        """
        opened = self.hunt_open_dialog()
        if opened != HUNT_DIALOG_OK:
            self.hunt_close_dialog()
            if opened == HUNT_DIALOG_NO_DIALOG:
                # 面板点不出来。两种可能：资源见底时游戏直接不给开，或者这一下被吞。
                # 前者会一直重复，所以按"打不了"处理。
                return 0, HUNT_SPEND_NO_RUNS
            # 不在 map 页 = 页面状态已经不对了，别再往下点。
            return 0, HUNT_SPEND_BROKEN

        reached, capped = self.hunt_set_times(times)
        if not reached:
            self.hunt_close_dialog()
            return 0, HUNT_SPEND_BROKEN

        started, finished = self.hunt_start()
        if not started:
            # 面板没散 = 「狩猎」按下去没用。资源不足时那个按钮就是不可点的，
            # 面板会一直停在那儿，所以两次重按都失败就没必要再耗。
            self.hunt_close_dialog()
            return 0, HUNT_SPEND_NO_RUNS
        if not finished:
            # 次数已经花出去了，只是没等到结算页。这个不能让调用方以为"没打成"，
            # 否则它会接着在未知页面上点。
            return reached, HUNT_SPEND_BROKEN

        if capped:
            return reached, HUNT_SPEND_CAPPED
        return reached, HUNT_SPEND_OK

    def hunt_open_dialog(self):
        """
        Press the bottom-right 「快速狩猎」 button and wait for the panel.

        Pages:
            in: page_hunt
            out: page_hunt (panel open)

        Returns:
            str: HUNT_DIALOG_OK / HUNT_DIALOG_NO_PAGE / HUNT_DIALOG_NO_DIALOG.
        """
        for i in range(HUNT_PRESS_TRIES):
            if self.appear(HUNT_START, offset=(20, 20)):
                return HUNT_DIALOG_OK
            if self.appear(HUNT_BUTTON, offset=(20, 20)):
                self.device.click(HUNT_BUTTON)  # alas-lint: allow - verified by wait_until_appear below, and the loop retries it
            else:
                logger.warning('Not on the map page, cannot open the hunt panel')
                return HUNT_DIALOG_NO_PAGE
            if self.wait_until_appear(HUNT_START, offset=(20, 20), timeout=HUNT_DIALOG_TIMEOUT, settle=2):
                # 面板是淡入的，第一帧按钮还在画。这时候按次数档位会被吞，
                # 而"按空一次"的结果是少算一次，比多等一秒贵得多。
                self.wait_until_still(HUNT_COUNT_AREA, timeout=3)
                return HUNT_DIALOG_OK
            logger.warning('The quick hunt panel did not open, press again')

        return HUNT_DIALOG_NO_DIALOG

    def hunt_set_times(self, target):
        """
        Set 「狩猎N次」 up to `target`, and report whether the resource capped it.

        The panel has no number field: MIN / -10 / +10 / MAX and two ±1 round
        buttons, that is it. Measured on the real device (2026-10-28):

            1 --+10--> 10 --+10--> 10    (10 is the cap here: 60 火把 / 6)
              --MAX--> 10
              --MIN-->  1
              -- +1 -->  2 --+1-->  3 -- -1 --> 2

        So the only path is MIN then +1. +10 is not used to shortcut it: it
        jumps 1 -> **10** (not 11), and when the cap is below 10 it jumps to
        that cap instead, after which the current value is unknown (the number
        cannot be read reliably - its character blobs merge with 狩猎/次). +1 is
        slower but every step is observed.

        Walking up one at a time is also the only way to *detect* the cap, and
        that is not a side effect worth losing: a +1 that stops redrawing the
        row means the stepper is already at the largest number the current
        resource pays for. Nothing else in the UI says so - no warning, no grey
        text, the button just stops moving.

        Args:
            target (int):

        Returns:
            tuple: (what the stepper is set to, whether the resource capped it).
                The count is 0 when the panel died mid-way.
        """
        if not self.hunt_reset_times():
            return 0, False
        if target <= 1:
            return 1, False

        reached = 1
        for i in range(target - 1):
            if i and i % HUNT_CLICK_BURST == 0:
                self.device.click_record_clear()
            if not self.hunt_press(HUNT_TIMES_PLUS1):
                if self.appear(HUNT_START, offset=(20, 20)):
                    # 面板还在、+1 却按不动，就是资源只够这么多次。
                    logger.warning(f'The stepper stopped at {reached}, the config asks for '
                                   f'{target}. Not enough resource for the rest')
                    return reached, True
                # 面板没了，不是到上限，是别的问题（页面被切走/游戏重载）。
                return 0, False
            reached += 1
        return reached, False

    def hunt_reset_times(self):
        """
        Press MIN until 「狩猎N次」 reads 1.

        MIN means "set to the minimum", so it is idempotent: one press that
        changes the row is enough, and a press that changes nothing means we
        were already there. The panel in fact opens at 1 every time (measured
        on six hunts in a row), so the usual cost is two no-op presses.

        `required=False` on purpose: at 1 the press is *supposed* to do nothing,
        and asking for a retry would double the clicks and log "did nothing,
        probably at the cap" - which is true of +1 but nonsense for MIN.

        Returns:
            bool: If we are at 1 with the panel still open.
        """
        for _ in range(2):
            if self.hunt_press(HUNT_TIMES_MIN, required=False):
                return True
            if self.appear(HUNT_START, offset=(20, 20)):
                continue
            logger.warning('The quick hunt panel is gone, nothing to press')
            return False
        return True

    def hunt_press(self, button, required=True):
        """
        Press one stepper button and wait until 「狩猎N次」 is redrawn.

        "Nothing changed" has two different meanings and they must not share a
        log line: at the cap, +1 is greyed out and the panel stays; when the
        panel is gone, there is nothing to press at all.

        Args:
            button (Button): One of the HUNT_TIMES_* points.
            required (bool): False to give up after one press (MIN on 1).

        Returns:
            bool: If the row changed.
        """
        if self.appear(HUNT_START, offset=(20, 20)):
            for _ in range(HUNT_PRESS_TRIES if required else 1):
                before = crop(self.device.image, HUNT_COUNT_AREA, copy=False).astype(np.int16)
                self.device.click(button)  # alas-lint: allow - verified by the row comparison right below, which retries
                for _ in self.loop(timeout=HUNT_COUNT_TIMEOUT):
                    after = crop(self.device.image, HUNT_COUNT_AREA, copy=False).astype(np.int16)
                    if np.abs(after - before).max() > 8:
                        self.wait_until_still(HUNT_COUNT_AREA, timeout=2)
                        return True
                if not required:
                    # MIN 在已经是最小值时按下去没有反应，那不是错。
                    return False
                # 面板还在就再按一次；不在就立刻收手，别把 +1 点到地图上去。
                if self.appear(HUNT_START, offset=(20, 20)):
                    continue
                logger.warning('The quick hunt panel is gone, nothing to press')
                return False
            logger.warning(f'{button.name} did nothing, probably at the cap')
        else:
            logger.warning('The quick hunt panel is gone, nothing to press')
        return False

    def hunt_start(self):
        """
        Press 「狩猎」, then sit through the fight until the map page is back.

        The order matters and it is the whole trick of this method. Right after
        the panel closes the screen is **still a clean map page for a moment** -
        and the map's check point (`HUNT_BUTTON`) scores 1.00 through the
        dialog, the fight and the reward banner alike, because all of them are
        translucent overlays. So "the map is visible again" is worthless as an
        "am I done" signal: asking it one frame after the press answers True
        while the fight has not even started yet.

        What is reliable is the reward banner: every hunt ends on it, and it
        waits for a tap instead of timing out. So this waits for `HUNT_REWARD`
        first, taps through it, and only then accepts the map page back.

        The two failure modes are returned separately because they cost
        different things. "The panel did not go away" means the 狩猎 button was
        not clickable - almost always an empty stamina bar - and nothing was
        spent. "The screen did not come back" means the runs *were* spent and we
        simply lost track of the screen, so the caller must not go on clicking
        whatever is in front of it.

        Pages:
            in: page_hunt (panel open)
            out: page_hunt

        Returns:
            tuple: (did the 狩猎 press go through, is the map page back).
        """
        if not self.appear(HUNT_START, offset=(20, 20)):  # alas-lint: allow - an early exit for "the caller already closed the panel", not a branch on a transition frame
            logger.warning('The panel is gone before pressing 狩猎')
            return False, False

        logger.info('Start the hunt')
        self.device.click(HUNT_START)  # alas-lint: allow - the panel being there is the guard, and the wait below re-presses if nothing happens

        # 按空时面板不会走，所以"面板消失"就是这一下生效的证据。重按一次兜底 ——
        # 面板还在的时候再按一下，最坏就是按到同一个按钮上。
        if not self.wait_until_disappear(HUNT_START, offset=(20, 20),
                                        timeout=HUNT_DIALOG_TIMEOUT, settle=2):
            logger.info('The panel is still there, press 狩猎 again')
            self.device.click(HUNT_START)  # alas-lint: allow - the same guard, the panel is verified to be on screen right above
            if not self.wait_until_disappear(HUNT_START, offset=(20, 20),
                                             timeout=HUNT_DIALOG_TIMEOUT, settle=2):
                logger.warning('The 狩猎 press was swallowed twice, the button is likely '
                               'disabled - out of stamina')
                return False, False

        if self.wait_until_appear(HUNT_REWARD, offset=(20, 20), timeout=HUNT_ANIMATION_TIMEOUT, settle=2):
            tap = Timer(HUNT_REWARD_INTERVAL).start()
            for _ in self.loop(timeout=HUNT_RESULT_TIMEOUT):
                if self.appear(HUNT_REWARD, offset=(20, 20)):
                    if tap.reached():
                        tap.reset()
                        logger.info('Reward screen, tap to go back')
                        self.device.click(HUNT_REWARD_TAP)  # alas-lint: allow - the reward screen has no button, it says 点击画面即可返回
                    continue
                if self.ui_page_appear(page_hunt, offset=(20, 20)):
                    return True, True
            logger.warning('The reward screen did not go away')
            return True, False

        if self.ui_page_appear(page_hunt, offset=(20, 20)):
            logger.warning('No reward banner, but the map page is back')
            return True, True

        logger.warning('Neither the reward banner nor the map page came back')
        return True, False

    def hunt_close_dialog(self):
        """
        Close the panel with 取消, if it is still there.

        Pages:
            in: page_hunt (panel open)
            out: page_hunt
        """
        if self.appear(HUNT_START, offset=(20, 20)):
            logger.info('Close the quick hunt panel')
            self.device.click(HUNT_TIMES_CANCEL)  # alas-lint: allow - 取消 is the only exit; the wait below verifies it
            self.wait_until_disappear(HUNT_START, offset=(20, 20), timeout=5, settle=2)
