"""战斗训练（模擬 → 戰鬥訓練）：每天把体力刷掉。

页面关系（都是实机量出来的，2026-10-30）：

    主界面 --右侧竖排菜单「模擬」--> 模擬（四张卡）
        四张卡：戰鬥訓練 / 超空間的流域 / 哀嚎螺旋塔 / 全力戰，本轮只做第一张
    模擬 --第一张卡--> 戰鬥訓練
        左侧六个页签：成長 / 戰鬥員 / 夥伴 / 潛力 / 記憶碎片 / 挑戰
        右侧关卡列表，一屏四行，每行右边写着单场体力（20，記憶碎片是 60）
    戰鬥訓練 --列表第 N 行--> 配置隊伍
        右侧：難度 1-6（点数字选）、戰鬥效率 1-6（拖滑条）、雙倍獎勵次数
        底部：進入 + 体力数字（= 单场体力 × 效率）
    配置隊伍 --進入--> 确认框（可能两个）--> 战斗 --> 结算 --> 確認 --> 配置隊伍

几个必须记下来的坑：

1. **顶栏的体力「+」和战斗页右上角是同一个位置**。战斗页右上角是两个圆钮
   （白 ✕ = 退出，另一个 = 自动战斗），但在战斗结束、结算页出来以后，那个
   位置就变成体力「+」了，点下去会弹出「補充埃忒耳」。所以点自动战斗必须在
   「确实在战斗页」的判断里面做。
2. **自动战斗按钮只有颜色变**：同一个图标，开是亮金色、关是白/灰色（2026-11-09
   改版；旧版开是青色，按青色像素数判会永远读到 0）。实测金色像素 113 对 0，
   按数量判（`ui_gold_count`），不判形状。
3. **难度选择器是滑动窗口**：只显示 4 个数字，选完就缩回去，位置随窗口漂。
   所以"设难度"这个选项没做成"点某个固定坐标"，见 `sim_set_difficulty()`。
4. **列表/页签/卡片的图案每期都换**（活动皮肤连按钮配色都换），这些都是固定
   坐标点击点，判断交给"页面标题在不在"。
"""

import numpy as np

from module.base.timer import Timer
from module.chaoszero.assets import (BATTLE_AUTO, BATTLE_EXIT, DIALOG_ENTER,
                                     RESULT_CONFIRM, SIM_PAGE, TEAM_ENTER,
                                     TEAM_TITLE, TRAINING_TABS, TRAINING_TITLE)
from module.chaoszero.chaoszero_ui import ChaoszeroUI, page_main
from module.exception import GameStuckError
from module.logger import logger

# 主界面右侧竖排菜单第三项「模擬」的图标中心。
SIM_ENTRY = (1218, 260)
# 模擬页第一张卡「戰鬥訓練」。
SIM_CARD_TRAINING = (150, 320)

# 左侧六个页签：(配置项后缀, 中文名, 点的 y)。x 固定在文字上，避开左侧那排
# 限时的「X2」双倍标记 —— 标记是活动期间才画的，框进去活动一结束就全错。
SIM_TABS = (
    ('TrainingGrowth', '成長', 124),
    ('TrainingMember', '戰鬥員', 200),
    ('TrainingPartner', '夥伴', 284),
    ('TrainingPotential', '潛力', 360),
    ('TrainingMemory', '記憶碎片', 439),
    ('TrainingChallenge', '挑戰', 521),
)
SIM_TAB_X = 160

# 右侧关卡列表：一屏四行，滚到顶时四行的中心（实机量的 223 / 361 / 499 / 637）。
# 点行的中间偏右，避开行尾的体力数字。
SIM_ROWS = (223, 361, 499, 637)
SIM_ROW_X = 1000
# 行高 —— 也是「往下滚一行」要拖的距离。`device.drag(hold_duration=0.3)`
# 不带惯性，实测拖 138px 正好走一行，连拖五次位置一个像素都不漂。
SIM_ROW_PITCH = 138
# 滚回顶部：一次往下拖 480px（3.5 行），拖三次。最长的页签（記憶碎片）11 行，
# 从底部回到顶部只需要 6.7 行，三次绰绰有余，多拖的那几下会被顶部夹住。
# 别把拖动终点拖出屏幕（试过拖到 732，手势被系统当成返回，直接退出这一页）。
SIM_SCROLL_DOWN_TIMES = 3
# 判"滚没滚"用的那块：一行标题的横向范围和半高。
SIM_TITLE_X0 = 780
SIM_TITLE_X1 = 1010
SIM_TITLE_HALF = 15

# 配置队伍右侧那块面板。
# 难度：1..6 排成一行，**数字 1 的中心在 x=877，每档 62**（实机量的
# 877 / 941 / 1003 / 1064 / 1127 / 1189），选中的那个套着橙色圆角框。
# 旧值 939 是把「重置」点在了 2 上、目标点点在了空白处 —— 难度其实一直没设对。
SIM_DIFFICULTY_X1 = 877
SIM_DIFFICULTY_STEP = 62
SIM_DIFFICULTY_Y = 207
# 橙色圆角框的搜索范围（判"选中了哪一个"）。
SIM_DIFFICULTY_AREA = (840, 178, 1240, 245)
# 战斗效率滑条：橙色圆点在 1 时位于 x=954、在 6 时位于 x=1185，每档 46。
# **必须从圆点上起手拖**：从左边那个「1」字上起手，滑条纹丝不动（实测拖完还是 1）。
SIM_EFFICIENCY_X1 = 954
SIM_EFFICIENCY_STEP = 44
SIM_EFFICIENCY_Y = 599
SIM_EFFICIENCY_AREA = (860, 575, 1240, 625)

# 战斗页自动战斗按钮那块区域（金色像素数就是这个框里的）。开=亮金环，关=白环。
SIM_AUTO_AREA = (1100, 10, 1150, 70)
# 金色像素超过这个数就算"自动战斗已开"：实测开 113，关 0。
SIM_AUTO_GOLD = 40

# 一次入口从进战斗到结算：效率 1 实测 40~46 秒，效率 6 是连着打 6 场，
# 所以要按 6 倍留量；单场 45 秒 × 6 ≈ 4 分半，留 10 分钟兜底。
SIM_FIGHT_TIMEOUT = 600


class ChaoszeroSimulation(ChaoszeroUI):
    """
    Task: clear the daily stamina in 戰鬥訓練.
    """

    # 本轮已经确认打开的页签。`run()` 会重置，留一个类属性兜住"直接调某个方法"。
    sim_tab_active = None

    def run(self):
        """
        Pages:
            in: page_main
            out: page_main
        """
        logger.hr('Battle training', level=1)
        # 守卫（固定两行）：六个页签全关就不启动游戏，直接把任务关掉。
        if not any(getattr(self.config, f'ChaoszeroSimulation_{key}') for key, _, _ in SIM_TABS):
            logger.info('Every training tab is off')
            self.config.Scheduler_Enable = False
            self.config.task_stop()
        # 这一轮已经确认打开的页签；换页签时用它判断"要不要点"。
        self.sim_tab_active = None
        # 上一个任务可能把游戏停在模擬里（这一系列页面之间没有 link，`ui_goto`
        # 走不了），所以先自己退到主界面再说。
        if not self.ui_page_appear(page_main):  # alas-lint: allow - "not at the lobby" is the question; sim_quit() is bounded and ends at the boot loop
            self.sim_quit()

        if not self.sim_open():
            logger.warning('Cannot open 戰鬥訓練, try again later')
            self.config.task_delay(success=False)
            return

        for key, name, tab_y in SIM_TABS:
            if not getattr(self.config, f'ChaoszeroSimulation_{key}'):
                continue
            logger.hr(f'Training: {name}', level=2)
            self.sim_run_tab(name, tab_y)

        self.sim_quit()
        self.config.task_delay(server_update=True)

    # ------------------------------------------------------------------ 寻路

    def sim_training_appear(self):
        """
        Whether the 戰鬥訓練 stage list is on screen.

        Two anchors on purpose: the page title 「戰鬥訓練」 is the obvious one, but
        the same list was seen with 「模擬」 written in the title bar (2026-10-30),
        while the six-tab column never changed. Either hit counts.

        Returns:
            bool: If the stage list is there.
        """
        return self.appear(TRAINING_TITLE, offset=(20, 20)) \
            or self.appear(TRAINING_TABS, offset=(20, 20))

    def sim_open(self, timeout=60):
        """
        Walk from the lobby to the 戰鬥訓練 stage list.

        The three screens in between have no stable check point of their own
        (the 模擬 page is four full-screen cards whose art changes with the
        season), so this is a state loop with two questions: "am I on the stage
        list" and "am I on the 模擬 page". Anything else is the lobby, where the
        menu entry is pressed again on a timer.

        Pages:
            in: page_main
            out: page_training

        Args:
            timeout (int, float): Seconds.

        Returns:
            bool: If the stage list is on screen.
        """
        timeout = Timer(timeout, count=3).start()
        tap = Timer(3)
        attempts = 0

        for _ in self.loop(timeout=timeout):
            # End
            if self.sim_training_appear():
                return True

            if self.appear(SIM_PAGE, offset=(20, 20)):
                # 模擬页：点第一张卡。卡片要滑入，点太早会被吃掉，靠 `tap` 重试。
                if tap.reached():
                    tap.reset()
                    logger.info('模擬 page, open 戰鬥訓練')
                    self.tap_point(*SIM_CARD_TRAINING)
                continue

            # 还没进模擬：点主界面右侧的入口。
            if tap.reached():
                tap.reset()
                attempts += 1
                # 主界面被半透明弹窗盖着时照样"认得出"（模板匹配对压暗不敏感），
                # 于是点哪都不动 —— 教程/帮助那种白底弹窗只有返回键肯关。
                # 三次点不动就按一次返回，别在这儿把同一个点按满 12 次。
                if attempts % 3 == 0:
                    logger.info('Three taps without an answer, press back in case a dialog is up')
                    self.device.adb_shell(['input', 'keyevent', '4'])
                    continue
                self.device.click_record_clear()
                logger.info('Lobby, open 模擬')
                self.tap_point(*SIM_ENTRY)
        else:
            logger.warning('The stage list did not open')
            return False

    def sim_quit(self):
        """
        Walk back to the lobby.

        The body lives in `ChaoszeroUI.ui_quit_to_main()` because 政策室 and 咖啡廳
        need exactly the same walk and there must be only one copy of it.

        Pages:
            in: any
            out: page_main

        Returns:
            bool: True when the lobby is back.
        """
        return self.ui_quit_to_main()

    # -------------------------------------------------------------- 一个页签

    def sim_run_tab(self, name, tab_y):
        """
        Run one tab of the stage list from start to finish.

        Pages:
            in: page_training
            out: page_training

        Args:
            name (str): Tab name, for the log.
            tab_y (int): y of the tab in the left column.

        Returns:
            int: How many battles were fought.
        """
        if not self.sim_switch_tab(name, tab_y):
            return 0

        if not self.sim_training_appear():
            logger.warning(f'{name}: the stage list is gone')
            return 0
        if not self.sim_open_stage():
            logger.warning(f'{name}: cannot open the stage')
            return 0

        self.sim_configure()
        fought = self.sim_fight(name)

        # 战斗结束回配置队伍，退一行回列表，下一个页签接着点。
        self.device.adb_shell(['input', 'keyevent', '4'])
        if not self.wait_until_appear(TRAINING_TITLE, offset=(20, 20), timeout=10, settle=2):
            logger.warning(f'{name}: did not get back to the stage list after the battle')
        logger.info(f'{name}: {fought} round(s)')
        return fought

    def sim_switch_tab(self, name, tab_y, timeout=25):
        """
        Open one tab of the stage list — and make sure it really opened.

        页签这一下会被转场吃掉：实测点完「戰鬥訓練」那张卡 0.2 秒后就点页签，
        列表页根本还没出来，于是这一下点空，脚本接着在**上一个页签**的列表上
        点行 —— 配的是潛力，打出去的却是成長的第一个「單元幣」。所以点完必须
        比对第一行的标题，没换就再点，换到了才往下走。

        本轮第一个页签允许"点了没变"：游戏很可能本来就停在这个页签上，点它
        自然不会变。连点三次都没反应就当它本来就是开着的（点空三次的概率极低，
        而错误地跳过这个页签的代价是漏刷一整个页签）。

        Pages:
            in: page_training
            out: page_training

        Args:
            name (str): Tab name, for the log.
            tab_y (int): y of the tab in the left column.
            timeout (int, float): Seconds.

        Returns:
            bool: True when the list on screen belongs to that tab.
        """
        if self.sim_tab_active == name:
            return True

        # 列表可能还在滑进来，等它停稳再抓"点之前长什么样"。
        self.sim_list_settle()
        before = self.sim_title_strip(0)

        # 点一下先给两秒半：被吃掉的话列表纹丝不动，那时候再补点。最多点三次 ——
        # 本来就停在这个页签上的时候它是不会动的，别在这儿一直点下去。
        attempts = 1
        tap = Timer(2.5).start()
        self.device.click_record_clear()
        self.tap_point(SIM_TAB_X, tab_y, name=f'CHAOSZERO_TAB_{name}')

        for _ in self.loop(timeout=Timer(timeout, count=3)):
            if not self.sim_same_picture(before, self.sim_title_strip(0)):
                self.sim_tab_active = name
                return True
            if attempts >= 3:
                break
            if tap.reached():
                tap.reset()
                attempts += 1
                logger.info(f'{name}: the tab did not take, press it again')
                self.device.click_record_clear()
                self.tap_point(SIM_TAB_X, tab_y, name=f'CHAOSZERO_TAB_{name}')

        if self.sim_tab_active is None:
            logger.info(f'{name}: the list did not change, take it as already open')
            self.sim_tab_active = name
            return True

        logger.warning(f'Can not switch to the {name} tab, skip it')
        return False

    def sim_bright_rows(self):
        """
        The y of every row's stamina cost, top to bottom.

        每行右边那枚「单场体力」的数字（記憶碎片 60，其余 20）是列表里唯一跟着
        行走、又不会因为换皮肤而改样的东西。挑戰 页签不印体力，返回空列表。

        Returns:
            list[int]: Row centres.
        """
        image = self.image_crop((1170, 130, 1250, 720)).astype(int).mean(axis=2)
        bright = (image > 195).sum(axis=1)

        rows = []
        start = None
        for index, count in enumerate(bright):
            if count > 2 and start is None:
                start = index
            elif count <= 2 and start is not None:
                if index - start > 8:
                    rows.append(start + (index - start) // 2 + 130)
                start = None
        return rows

    def sim_title_strip(self, index):
        """
        The pixels of one row's title.

        行标题是静止的白字：列表不动的时候连拍两帧只差 4 个像素（实测），
        所以拿它判「滚没滚」比全屏比图可靠得多 —— 列表后面那张背景动画
        一直在动，`wait_until_still` 会白等到超时。

        Args:
            index (int): 0 = the first visible row, 1 = the second.

        Returns:
            np.ndarray: Cropped pixels.
        """
        y = SIM_ROWS[index]
        return self.image_crop((SIM_TITLE_X0, y - SIM_TITLE_HALF,
                                SIM_TITLE_X1, y + SIM_TITLE_HALF)).astype(int)

    @staticmethod
    def sim_same_picture(before, after):
        """
        Whether two title strips are the same row.

        Args:
            before (np.ndarray): Strip.
            after (np.ndarray): Strip.

        Returns:
            bool: True when nothing moved.
        """
        changed = (np.abs(before - after).max(axis=2) > 30).sum()
        return changed < 200

    def sim_list_settle(self, timeout=3):
        """
        Wait until the list stops moving.

        连拍两帧、隔半秒比一次，前两行的标题都没变才算停稳。间隔是必须
        的：回弹动画的尾巴每帧只挪几个像素，连拍两帧看着像静止，那时候去拖下一把
        会把列表拖歪（实测：拖完立刻再拖一次，列表停在歪着的位置，点哪都是错行）。

        Args:
            timeout (int, float): Seconds.

        Returns:
            bool: True when it settled.
        """
        previous = None
        gap = Timer(0.5, count=1)
        for _ in self.loop(timeout=Timer(timeout)):
            # 只比前两行：页签里的行数不一定够四行，第 4 行那里是背景动画，
            # 永远在变，拿来当判据会一直"没停"。
            current = (self.sim_title_strip(0), self.sim_title_strip(1))
            if previous is None:
                previous = current
                gap.reset()
                continue
            if not gap.reached():
                continue
            if self.sim_same_picture(previous[0], current[0]) \
                    and self.sim_same_picture(previous[1], current[1]):
                return True
            previous = current
            gap.reset()
        return False

    def sim_list_to_top(self):
        """
        Scroll the stage list back to its first row.

        往下拖会被顶部夹住，所以「第一行的标题拖完没变」就是到顶了。之所以每次
        开打前都要归位：这一屏的序号是「从上往下第几行」，不归位点到的就是别的
        关卡（实测踩过：滚到一半再点，开出来的是第 1 项）。

        Pages:
            in: page_training
            out: page_training

        Returns:
            bool: True when the first row is back at the top.
        """
        for _ in range(SIM_SCROLL_DOWN_TIMES + 1):
            # 往下一格就够验证了；拖远了会甩出橡皮筋，列表歪着半天回不来。
            before = self.sim_title_strip(0)
            self.device.click_record_clear()
            self.device.drag((SIM_ROW_X, 200), (SIM_ROW_X, 680),
                             point_random=(0, 0, 0, 0), hold_duration=0.2)
            self.sim_list_settle()
            if self.sim_same_picture(before, self.sim_title_strip(0)):
                return True

        logger.warning('The stage list did not scroll back to its first row')
        return False

    def sim_list_down(self, rows):
        """
        Scroll the stage list down by `rows` rows, one drag each.

        逐行拖而不是一把拖到底：实测一行 138px 是精确的（连拖五次一个像素都
        不漂），一次拖多行会因为惯性多走半行，行序号就对不上了。

        Args:
            rows (int): How many rows to scroll past.

        Returns:
            int: How many rows it actually scrolled. Less than `rows` means the
                list ran out.
        """
        moved = 0
        for _ in range(rows):
            before = self.sim_title_strip(0)
            self.device.click_record_clear()
            self.device.drag((SIM_ROW_X, 620), (SIM_ROW_X, 620 - SIM_ROW_PITCH),
                             point_random=(0, 0, 0, 0), hold_duration=0.3)
            self.sim_list_settle()
            if self.sim_same_picture(before, self.sim_title_strip(0)):
                break
            moved += 1
        return moved

    def sim_stage_locate(self, stage):
        """
        Put the configured row where the tap has to land.

        第 1-4 项：列表归位到顶部，直接点那一格。
        第 5 项往后：先归位，再往下滚 `stage - 4` 行，把目标顶到第 4 格 ——
        第 4 格（y=637）永远是整个列表里最稳的一格。

        列表滚到底会被夹住，行位置跟着错开，这一格公式就不成立了。那时候退回
        实测：滚过 `moved` 行，目标就是当前第 `stage - 1 - moved` 个数字所在的那
        一行。

        Pages:
            in: page_training
            out: page_training

        Args:
            stage (int): 1-based row index counted from the top of the list.

        Returns:
            int: The y to tap, 0 when this tab has fewer rows than `stage`.
        """
        if not self.sim_list_to_top():
            return 0

        if stage <= len(SIM_ROWS):
            return SIM_ROWS[stage - 1]

        wanted = stage - len(SIM_ROWS)
        moved = self.sim_list_down(wanted)
        if moved >= wanted:
            return SIM_ROWS[-1]

        rows = self.sim_bright_rows()
        slot = stage - 1 - moved
        if 0 <= slot < len(rows):
            logger.info(f'The list is at its end, row {stage} sits at y={rows[slot]}')
            return rows[slot]

        logger.warning(f'This tab has fewer than {stage} stage(s)')
        return 0

    def sim_open_stage(self, timeout=15):
        """
        Tap the configured row of the stage list and wait for 配置隊伍.

        Pages:
            in: page_training
            out: page_team

        Args:
            timeout (int, float): Seconds.

        Returns:
            bool: If the team page opened.
        """
        stage = max(int(self.config.ChaoszeroSimulation_TrainingStage), 1)
        y = self.sim_stage_locate(stage)
        if not y:
            return False

        retry = Timer(2)
        for _ in self.loop(timeout=timeout):
            if self.appear(TEAM_TITLE, offset=(20, 20)):
                return True
            # 刚切完页签的列表还在滑入，这一下会被吃掉；按节流补点，别判失败。
            if retry.reached():
                retry.reset()
                self.device.click_record_clear()
                self.tap_point(SIM_ROW_X, y, name=f'CHAOSZERO_STAGE_{stage}')
        else:
            return False

    def sim_configure(self):
        """
        Apply the difficulty and the battle efficiency.

        Pages:
            in: page_team
            out: page_team
        """
        difficulty = int(self.config.ChaoszeroSimulation_TrainingDifficulty)
        if 1 <= difficulty <= 6:
            if not self.sim_set_difficulty(difficulty):
                logger.warning('The difficulty may not be the configured one')
        else:
            logger.info('Difficulty left as the game has it')

        efficiency = int(self.config.ChaoszeroSimulation_TrainingEfficiency)
        if 1 <= efficiency <= 6:
            if not self.sim_set_efficiency(efficiency):
                logger.warning('The battle efficiency may not be the configured one')
        else:
            logger.info('Battle efficiency left as the game has it')

    def sim_orange_span(self, area):
        """
        The x range of the orange pixels inside one box.

        难度的选中框、战斗效率的滑钮和填充条都是橙色的。

        Args:
            area (tuple): x1, y1, x2, y2.

        Returns:
            tuple: (left, right), (0, 0) when nothing orange is found.
        """
        image = self.image_crop(area).astype(int)
        red, green, blue = image[:, :, 0], image[:, :, 1], image[:, :, 2]
        mask = (red > 200) & (green > 110) & (green < 200) & (blue < 110)
        columns = mask.sum(axis=0)
        hits = [index for index, count in enumerate(columns) if count >= 2]
        if not hits:
            return 0, 0
        return area[0] + hits[0], area[0] + hits[-1]

    def sim_knob_x(self):
        """
        The x of the 戰鬥效率 knob.

        滑条左边会填成橙色，光找橙色会找到一整条；**圆点比填充条厚**
        （实测 16px 对 10px），所以按"这一列橙色超过 12 像素"单独把圆点挑出来。

        Returns:
            int: Knob centre, 0 when it is not found.
        """
        area = SIM_EFFICIENCY_AREA
        image = self.image_crop(area).astype(int)
        red, green, blue = image[:, :, 0], image[:, :, 1], image[:, :, 2]
        mask = (red > 200) & (green > 110) & (green < 200) & (blue < 110)
        columns = mask.sum(axis=0)
        hits = [index for index, count in enumerate(columns) if count >= 12]
        if not hits:
            return 0
        return area[0] + (hits[0] + hits[-1]) // 2

    def sim_difficulty_state(self):
        """
        Read the 難度 carousel: (how many numbers, box centre, numbers right of it).

        这一排是个传送带：中间那格套着橙色框，点哪个数字，哪个数字就转到框里，
        并且**框左边的数字个数 = 选中值 - 1**（展开时）。框右边还剩几个数字，
        正好能反推选中了第几档 —— 这是不认字也能验的办法。

        Returns:
            tuple: (count, box, after).
        """
        area = SIM_DIFFICULTY_AREA
        image = self.image_crop(area).astype(int)
        gray = image.mean(axis=2)
        colored = (image.max(axis=2) - image.min(axis=2)) > 40
        mask = (gray < 150) & ~colored

        columns = mask.sum(axis=0)
        digits = []
        start = None
        for index, count in enumerate(columns):
            if count >= 3 and start is None:
                start = index
            elif count < 3 and start is not None:
                if index - start >= 4:
                    digits.append(area[0] + (start + index) // 2)
                start = None

        left, right = self.sim_orange_span(area)
        if not left:
            return len(digits), 0, 0
        box = (left + right) // 2
        after = len([x for x in digits if x > box + 20])
        return len(digits), box, after

    def sim_set_difficulty(self, difficulty):
        """
        Select one difficulty.

        1..6 排成一行、每档 62（展开时 1 在 x=877），选中的那个套着橙色框。
        点完用"框右边还剩几个数字"验证：展开时右边应该正好剩 `6 - difficulty` 个。
        以前是点两下就当设好了，实际两下都点在空白处，难度一直停在游戏原来的值。

        Pages:
            in: page_team
            out: page_team

        Args:
            difficulty (int): 1-6.

        Returns:
            bool: If that number ended up in the box.
        """
        x = SIM_DIFFICULTY_X1 + (difficulty - 1) * SIM_DIFFICULTY_STEP
        # 传送带在两头会少露两格：靠右时窗口是 [3..6]，靠左时是 [1..4]。
        # 所以"框右边还剩几个数字"要么是 6-d，要么是 4-d（后者只在 d<=2 时出现）。
        expected = {6 - difficulty}
        if difficulty <= 2:
            expected.add(4 - difficulty)
        press = Timer(1.5).start()

        for _ in self.loop(timeout=Timer(12, count=3)):
            count, box, after = self.sim_difficulty_state()
            if box and after in expected:
                logger.info(f'Difficulty: {difficulty}')
                return True
            if press.reached():
                press.reset()
                self.device.click_record_clear()
                self.tap_point(x, SIM_DIFFICULTY_Y, name=f'CHAOSZERO_DIFFICULTY_{difficulty}')

        logger.warning(f'Can not make sure the difficulty is {difficulty}')
        return False

    def sim_set_efficiency(self, efficiency):
        """
        Drag the 戰鬥效率 knob onto a value.

        **必须从橙色圆点上起手**：滑条只认"按住滑钮拖"，从左边那个「1」字上起手
        拖纹丝不动（实测拖完还是 1 —— 这就是"填了 6 还是一场一场打"的原因）。
        拖完再量一次圆点，没到就再拖。

        Pages:
            in: page_team
            out: page_team

        Args:
            efficiency (int): 1-6.

        Returns:
            bool: If the knob ended up on that value.
        """
        target = SIM_EFFICIENCY_X1 + (efficiency - 1) * SIM_EFFICIENCY_STEP
        drag = Timer(1.2).start()

        for _ in self.loop(timeout=Timer(15, count=3)):
            knob = self.sim_knob_x()
            if knob and abs(knob - target) <= 8:
                logger.info(f'Battle efficiency: {efficiency}')
                return True
            if knob and drag.reached():
                drag.reset()
                logger.info(f'Battle efficiency: {efficiency}, drag from {knob} to {target}')
                self.device.click_record_clear()
                self.device.drag((knob, SIM_EFFICIENCY_Y), (target, SIM_EFFICIENCY_Y),
                                 point_random=(0, 0, 0, 0), hold_duration=0.2)

        logger.warning(f'Can not set the battle efficiency to {efficiency}')
        return False

    # ---------------------------------------------------------------- 打一场

    def sim_fight(self, name):
        """
        Repeat one battle until the stamina or the daily attempts run out.

        Pages:
            in: page_team
            out: page_team

        Args:
            name (str): Tab name, for the log.

        Returns:
            int: How many battles were fought.
        """
        times = int(self.config.ChaoszeroSimulation_TrainingTimes)
        fought = 0
        limit = times if times > 0 else 99

        for _ in range(limit):
            if not self.sim_fight_once():
                logger.info(f'{name}: stop after {fought} round(s)')
                break
            fought += 1
            logger.info(f'{name}: round {fought} done')

            if times > 0:
                # 重新开始会立刻开下一场；次数用完了就退回列表。
                if fought >= times:
                    break
        return fought

    def sim_fight_once(self, timeout=SIM_FIGHT_TIMEOUT):
        """
        One round: press 進入, answer the dialogs, watch the battle, take the
        result.

        The battle is watched rather than waited out: the auto-battle button
        lives in the top right corner of the battle screen, and *the same spot*
        is the stamina 「+」 on every other screen - pressing it blind opens the
        refill dialog (measured). So the press only happens while the battle
        screen is positively identified.

        Pages:
            in: page_team
            out: page_team

        Returns:
            bool: If the round ran. False means the game did not start one -
                most likely the stamina or the daily attempts are gone.
        """
        # 配置队伍是滑进来的，这一下点击会被转场吃掉（实测 13:41 那次：
        # 点了 進入、三十秒什么都没发生），所以先等按钮那块停下来再点。
        self.wait_until_appear(TEAM_ENTER, offset=(20, 20), timeout=5, settle=2)
        self.wait_until_still(TEAM_ENTER.area, timeout=3)
        self.device.click_record_clear()
        self.device.click(TEAM_ENTER)  # alas-lint: allow - guarded by the wait_until_appear above

        timeout = Timer(timeout, count=3).start()
        started = Timer(12).start()
        pressed = 1
        auto = False

        for _ in self.loop():
            # 战斗是活的场景，几十秒不动很正常，别让看门狗以为卡死。
            self.device.stuck_record_clear()

            # End - 结算页
            if self.appear(RESULT_CONFIRM, offset=(20, 20)):
                logger.info('Battle finished')
                self.device.click(RESULT_CONFIRM)
                if not self.wait_until_disappear(RESULT_CONFIRM, offset=(20, 20),
                                                 timeout=15, settle=2):
                    logger.warning('The result page does not close')
                # 结算页退出要过一屏黑，回到配置队伍才算这一轮结束，
                # 否则下一轮开场就会找不到「進入」。
                if not self.wait_until_appear(TEAM_TITLE, offset=(20, 20), timeout=15, settle=2):
                    logger.warning('Did not get back to 配置隊伍 after the result')
                return True

            # 开战确认框：「確認準備戰鬥說明」和「更高難度已解鎖」。
            if self.appear(DIALOG_ENTER, offset=(20, 20)):
                if started.reached():
                    logger.warning('Still on the confirm dialog, press 進入 again')
                    started.reset()
                logger.info('Confirm dialog, press 進入')
                self.device.click(DIALOG_ENTER)
                continue

            # 战斗页：确认自动战斗开着。只判一次，之后按钮会随回合重绘。
            if self.ui_battle_appear():
                started.reset()
                if not auto:
                    auto = True
                    if self.ui_gold_count(SIM_AUTO_AREA) < SIM_AUTO_GOLD:
                        logger.info('Auto battle is off, turn it on')
                        # 开打的那一下常被转场吃掉（实测两点没亮），而且战斗会
                        # 一直等玩家出牌。金色圈亮起来才算成功，最多补点三次。
                        for attempt in range(3):
                            self.device.click_record_clear()
                            self.device.click(BATTLE_AUTO)  # alas-lint: allow - inside the ui_battle_appear() branch
                            lit = Timer(5, count=3).start()
                            while not lit.reached():
                                self.device.screenshot()
                                self.device.stuck_record_clear()
                                if self.ui_gold_count(SIM_AUTO_AREA) >= SIM_AUTO_GOLD:
                                    break
                            if self.ui_gold_count(SIM_AUTO_AREA) >= SIM_AUTO_GOLD:
                                logger.info('Auto battle is on')
                                break
                            logger.info(f'Auto battle did not light up, press again ({attempt + 1}/3)')
                        else:
                            # 金圈读不到时只记一笔，不把整场判死：战斗可能已经在
                            # 自动打，误判成"没开"反而会多点两下把它关掉。
                            logger.info('Auto battle light not detected, the battle decides')
                continue

            # 点了 進入 却没进战斗：先补点两下（转场会吃点击），三次都没反应
            # 才当成"体力不够 / 次数用完"。
            if started.reached():
                if pressed < 3:
                    pressed += 1
                    logger.info('The battle did not start, press 進入 again')
                    self.device.click_record_clear()
                    self.device.click(TEAM_ENTER)  # alas-lint: allow - the button was seen before the loop started
                    started.reset()
                    continue
                logger.warning('The battle did not start, out of stamina or attempts')
                return False

            if timeout.reached():
                logger.warning('The battle did not finish in time')
                raise GameStuckError('战斗打了五分钟还没结算，可能是自动战斗没开或者卡住了')
