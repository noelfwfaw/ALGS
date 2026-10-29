"""
魔兽追踪者 (Brown Dust II) —— 从最低难度往上推，打到打不动为止。

Measured on the real device, 2026-10-29, season 「BROKEN BONDS」:

    page_event --底部「魔兽追踪者」-->  魔兽页 --「去战斗」-->  战斗 --结算-->  魔兽页

关于这一页有七件事是量出来的：

1. **难度一共 5 档**：EASY / NORMAL / HARD / VERY HARD / CHALLENGE，左右箭头切换，
   推到 CHALLENGE 之后右箭头变灰。难度条本身的底色是固定的 —— 实测中位数
   银 (156,156,156) / 绿 (112,194,66) / 蓝 (52,151,217) / 紫 (128,97,191) /
   红 (218,89,100)。所以判"现在在第几档"读底色，比 OCR 稳：这五档里有绿底黑字
   也有银底灰字，OCR 要换两套 letter 才读得出来。

2. **难度不锁**：EASY 没通关也能直接去打 CHALLENGE，游戏不拦。所以"从最低开始"
   是脚本自己的规矩，不是游戏的要求。

3. **队伍靠「推荐部署」抄别人的**：编辑队伍页底部那颗按钮弹出别人的阵型（最多 10
   条，按最高伤害量排序），每条右边是「阵形信息」和「使用」。点第一条的「使用」
   会填进**队伍1**；实测点第二条、第三条也一样只填队伍1，队伍2/3 永远是空的。
   所以这个任务只保证主队有人，其余两队交给用户自己编。
   点「使用」还会弹「未拥有服装」确认框（队伍里已经有人时要替换），确认在
   (707,431)，不点它队伍一点没换。

4. **战斗默认是手动回合制**：右上角一排圆钮里，"圆圈里一个播放三角 + 循环箭头"
   那颗就是自动战斗开关 (1017,42)。开启后整个图标泛蓝光，所以判"开没开"读
   (1001,26)-(1033,58) 的蓝色占比 —— 手动 0.000，自动 0.55。
   **点下去的瞬间图标也会亮一下（按下反馈）**，只看一帧就会把"点到了"当成
   "打开了"，然后整场停在第 1 回合等玩家出手。要连续三帧都读到才算开。
   已经开着的再点一次会关掉，所以点之前必须先看颜色，不能闭眼点两下 —— 反过来
   "关掉了"也要连续三帧都读不到才算数：队伍交接、放大招的时候这一角会黑一下。
   它会自己掉回手动（实测一场里掉过一次），所以等着的时候要定期回看。

5. **结算页有两种，而且两种的按钮不一样**：把 BOSS 打死写 **VICTORY**，底部是
   [返回][挑战下一个难度]；没打死写 **BATTLE END**，底部是 [重新挑战][返回]。
   「返回」的位置两边不同 —— VICTORY 在 x 925~1060，BATTLE END 在 x 1022~1189
   而且低 8 像素。所以"这一档过没过"看标题就够了，不用去比"伤害量 ≥ 血量"。
   **更不要写死一个返回坐标**：实测 (1090,672) 在 VICTORY 页落在「挑战下一个
   难度」上，直接又开了一场。
   顺带：「返回」这两个字在战斗画面里只有 0.450、在结算页上 0.944，所以它同时是
   "这一场打完了没有"的判据，比每帧去 OCR 伤害量可靠 —— 战斗画面那块地方全是
   跳动的伤害数字，OCR 出来是一堆 `|a.` 碎片，凑巧拼出四位数字就会被当成打完了。

6. **血量那个数字不要 OCR**：它是 9~13 位的大数，cnocr 在这套字体上会丢数字
   （`1,031,000` 读成 `1ogiooo`、`22,811,200` 读成 `22,81,200`、
   `9,000,000,013,200` 读成 `9,000,00q,013,200`），比错一次就会把没打过的一档
   记成打过了。

7. **打穿过的那一档，面板上写着「完成讨伐」**：这一档的「最高伤害量」会从数字
   变成「完成讨伐」（`WB_CLEARED` (853,199,909,222)，打穿 1.000 / 没打穿
   0.44~0.64），右上角两颗奖励也打上勾。这种难度下**「去战斗」按下去什么都不
   发生** —— 实测两次点击都石沉大海，白等两次 30 秒超时，还触发卡死检测。
   所以进度就是读这四个字：不用本地账本，换期也不用另外判断。

用户的原话：「这个可以无限打（但是奖励只拿一次，设置成每天打一次就行，如果奖励
没有拿就要从最低难度开始打。直到打不过的难度）编辑队伍的时候点推荐部署用别人的
队伍就行，打动最高那关就行了。」

也就是说：一关一关往上推，打不穿就停在那儿，剩下的明天再来。所以这里**不**跳过
"打不过"的那一关 —— 它是下一次的起点。
"""
import re

import numpy as np

from module.base.button import Button
from module.base.timer import Timer
from module.browndust.assets import (EVENT_ENTRY, EVENT_TAB_TRACKER, WB_CLEARED,
                                     WB_CONFIRM_DIALOG, WB_EDIT_TEAM, WB_RECOMMEND,
                                     WB_RECOMMEND_TITLE, WB_RESULT_BACK, WB_VICTORY)
from module.browndust.browndust_ui import BrowndustUI, page_event
from module.logger import logger
from module.ocr.ocr import Ocr

# 五档难度，从低到高。名字只用来打日志（定档靠底色，见 DIFF_EDGE）。
WORLDBOSS_NAMES = ['EASY', 'NORMAL', 'HARD', 'VERY HARD', 'CHALLENGE']

# 左右两颗箭头。纯坐标：它们画在难度条两边，图案是同一个"箭头 + 圆"，没有文字，
# 而且背景是每次都不一样的主视觉，抠不出稳定的模板。
DIFF_LEFT = Button(area=(725, 118, 772, 158), color=(0, 0, 0),  # alas-lint: allow - a plain left arrow over per-season art, the difficulty bar is read right after
                   button=(748, 137, 748, 137), name='WB_DIFF_LEFT')
DIFF_RIGHT = Button(area=(850, 118, 900, 158), color=(0, 0, 0),  # alas-lint: allow - a plain right arrow over per-season art, the difficulty bar is read right after
                    button=(875, 137, 875, 137), name='WB_DIFF_RIGHT')

# 难度条的纯底色。上下各 4 行是色块本体（中间被难度名占了），用来判第几档。
DIFF_EDGE = ((126, 130, 772, 854), (145, 149, 772, 854))

# 活动页底部第四块木牌「魔兽追踪者」。`EVENT_TAB_TRACKER` 只拿来做"到了活动页
# 并且木牌画出来了"的判据，点击点固定写死 —— `appear()` 匹配出来的位置会带
# 几像素偏移，实测点偏移后的 (723,660) 落在木牌下边缘，游戏一声不响，然后
# 任务在原地等满 30 秒超时，日志还写着"打开了"。
WORLD_BOSS_TAB = Button(area=(672, 643, 759, 666), color=(0, 0, 0),  # alas-lint: allow - the template is EVENT_TAB_TRACKER, this is only the click point
                        button=(716, 654, 716, 654), name='WB_TAB')
# 底部那排木牌的面积，用来等入场动画画完。
TRACKER_TAB_AREA = (600, 620, 830, 690)

# 编辑队伍页底部那枚「推荐部署」弹出来的面板，右上角第一条记录右边的「使用」。
# 面板按最高伤害量排序，第一条就是最强的那个；三条记录的「使用」在同一列上，
# 行距 120（253 / 373 / 492），所以只点第一条。
RECOMMEND_USE_FIRST = Button(area=(999, 213, 1069, 294), color=(0, 0, 0),  # alas-lint: allow - a check mark inside a beige button, the panel title is matched right before
                             button=(1034, 253, 1034, 253), name='WB_RECOMMEND_USE')
# 推荐面板的上半截（标题 + 头两条记录），等它画稳再点「使用」。
RECOMMEND_PANEL_AREA = (560, 110, 1160, 400)

# 点「使用」之后必弹的「未拥有服装」确认框里的「确认」。它盖在推荐面板上面，
# 不点这一下，队伍其实没换 —— 面板照样消失，日志也照样像成功了。
# 取消在左边 (571,431)，别点错。
CONFIRM_OK = Button(area=(645, 414, 770, 449), color=(0, 0, 0),  # alas-lint: allow - a beige capsule next to 取消, the dialog title is matched right before
                    button=(707, 431, 707, 431), name='WB_CONFIRM_OK')
# 确认框的标题那一行，用来等淡入画完（标题是整块一起淡进来的）。
CONFIRM_DIALOG_AREA = (560, 270, 720, 320)

# 编辑队伍页左上角的返回箭头。跟其它页的返回键同一个位置（游戏统一的左上角胶囊）。
TEAM_BACK = Button(area=(124, 24, 152, 56), color=(0, 0, 0),  # alas-lint: allow - a click point on the back arrow, there is no image to match
                   button=(124, 24, 152, 56), name='TEAM_BACK')

# 魔兽页底部那枚「去战斗」。它左边是「编辑队伍」，两颗都是米白胶囊 + 黑字，
# 单独抠其中一颗都会跟另一颗串（同色同形同高），所以只借位置，判据用上面的页面检查点。
FIGHT = Button(area=(941, 633, 1148, 679), color=(0, 0, 0),  # alas-lint: allow - same capsule as 编辑队伍, the boss page checkpoint is what proves the tap is safe
               button=(1043, 655, 1043, 655), name='WB_FIGHT')

# 战斗界面右上角那排圆钮里的自动战斗开关，以及它亮起来时的蓝光范围。
AUTO_BATTLE = Button(area=(995, 20, 1040, 64), color=(0, 0, 0),  # alas-lint: allow - the icon has two states told apart by colour, read before every tap
                     button=(1017, 42, 1017, 42), name='WB_AUTO_BATTLE')
AUTO_GLOW = (1001, 26, 1033, 58)
AUTO_GLOW_RATIO = 0.10

# 结算页右下角的「返回」（素材 `WB_RESULT_BACK`）。**不要写死坐标**：VICTORY 页是
# [返回][挑战下一个难度]，BATTLE END 页是 [重新挑战][返回]，两边的返回差着 97 像素、
# 还低 8 像素（见模块 docstring 第 5 条）。所以用「返回」这两个字的模板去对，横向
# 给 120 像素的搜索量。
RESULT_BACK_OFFSET = (120, 40)

# 结算页的「伤害量 N」。左边是「伤害量」三个字，右边接数字，最长的
# `9,000,000,013,200` 一直画到 x 869 —— 区域右边界必须留到 1060，实测切在
# 1024 会读成 `伤害量1,031.0`（丢最后两位）。
RESULT_DAMAGE = (872, 294, 1060, 320)
RESULT_DAMAGE_THRESHOLD = 170

# 魔兽页右上面板里的 BOSS 名字（四个汉字）。只用来认"换期了没有"：
# 血量那个 9~13 位的大数 OCR 会丢位，名字很稳。实测魔兽页 1.000、
# 战斗里读出来是乱码。
PANEL_BOSS = (733, 84, 860, 112)

# 点「去战斗」之后等魔兽页消失（进战斗会重载整个游戏，BROWN DUST II 的跑马灯）。
BATTLE_ENTER_TIMEOUT = 30
# 点下去之后多久算"根本没进去"。进战斗一两秒就黑屏，20 秒还没动静就是没进去，
# 这时要赶紧放手重试 —— 坐着等 30 秒，框架的卡死计时器（60 帧）早把人带走了。
FIGHT_TIMEOUT = 20
# 战斗画面的面积，用来等加载画完再点自动战斗。
BATTLE_HUD_AREA = (1000, 60, 1280, 130)
# 一整场（3 队轮着上）实测 3 分钟出头，给 15 分钟是留给模拟器卡顿。
BATTLE_TIMEOUT = 900
# 点「返回」之后等魔兽页回来，同样会重载。
RESULT_BACK_TIMEOUT = 30
# 魔兽页的面板面积，等重载画完。
BOSS_PANEL_AREA = (700, 70, 1200, 500)



class BrowndustWorldBoss(BrowndustUI):
    """
    Clear the event's world boss from the lowest difficulty upward.

    一关一关往上推，打穿一档再上一档，打不穿就停在那儿 —— 它是明天的起点，
    所以**不跳过**那档。

    哪一档已经打穿了**看游戏自己的面板**：打完的那一档在「最高伤害量」那一行写的
    是「完成讨伐」，右上角奖励也打上勾。这时「去战斗」按下去了什么都不发生
    （实测两次都是这样，白白等满超时），所以必须靠这个标记跳过它。
    好处是换期不用另外判断：新一期的面板上没有任何一档写着「完成讨伐」。

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
        self.ui_goto_main()
        # 大厅右侧那面横幅是这一期的活动入口。它的模板分一直在抖（实测 0.85~0.94
        # 来回跳，横幅底下压着一层跟着大厅动画变的光），所以给 15 秒而不是 5 秒 ——
        # 这一步判错等于今天不打了，多等十秒很划算。
        if not self.wait_until_appear(EVENT_ENTRY, offset=(20, 20), timeout=15):
            logger.warning('The event banner is not on the lobby, nothing to fight')
            self.device.save_screenshot(genre='world_boss_no_banner')
            self.config.task_delay(server_update=True)
            return

        if not self.world_boss_enter():
            self.ui_goto_main()
            self.config.task_delay(server_update=True)
            return

        self.ensure_team()
        if not self.difficulty_to_lowest():
            logger.warning('Cannot go back to the lowest difficulty')
            self.ui_goto_main()
            self.config.task_delay(server_update=True)
            return

        logger.attr('Boss', self.read_boss_name())

        for level, name in enumerate(WORLDBOSS_NAMES):
            if level > 0 and not self.difficulty_next():
                logger.info(f'[World boss] {WORLDBOSS_NAMES[level - 1]} is the highest difficulty')
                break
            if self.read_cleared():
                logger.info(f'[World boss] {name}: 完成讨伐, skip')
                continue

            victory, damage = self.battle(name)
            if victory is None:
                # 打了、但没看到结算页。停在这儿，明天这一档还会再打一次，
                # 代价只是一场。
                logger.warning(f'[World boss] {name}: the fight left no result, stop here')
                break
            if victory:
                logger.info(f'[World boss] {name}: cleared, {damage} damage')
            else:
                logger.info(f'[World boss] {name}: only {damage} damage, not cleared — '
                            f'that is where today ends')
                break
        else:
            logger.info('[World boss] every difficulty is cleared, nothing left this season')

        self.ui_goto_main()
        self.config.task_delay(server_update=True)

    def world_boss_enter(self):
        """
        活动页点底部第四块木牌「魔兽追踪者」进页面。

        Pages:
            in: page_event
            out: page_world_boss

        Returns:
            bool: 有没有进去。
        """
        self.ui_goto(page_event)
        # 活动页有入场动画，底部那排木牌最后才画出来；画之前点等于点在背景上。
        if not self.wait_until_appear(EVENT_TAB_TRACKER, offset=(20, 20), timeout=10):
            logger.warning('[World boss] the 魔兽追踪者 tab did not show up')
            return False
        # 木牌从第一帧就能匹配到 1.00（淡入不改变模板匹配的分），但那时它还在淡入，
        # 点下去游戏不认。等这块真的画稳再点。
        self.wait_until_still(TRACKER_TAB_AREA, timeout=5)

        # 点一次没进去就再点一次 —— 木牌刚画完那一两帧仍然吃不住点击，
        # 而这一步失败会让整个任务空转一次排期。第一次给短超时，重试才给足。
        for timeout in (15, BATTLE_ENTER_TIMEOUT):
            self.device.click(WORLD_BOSS_TAB)  # alas-lint: allow - the tab was matched right above, the boss panel below is the proof
            if self.wait_until_appear(WB_EDIT_TEAM, offset=(20, 20), timeout=timeout):
                return True
            logger.info('[World boss] still on the event page, tap the tab again')

        logger.warning('[World boss] cannot open 魔兽追踪者')
        return False

    def ensure_team(self):
        """
        编辑队伍 → 推荐部署 → 用第一条 → 确认替换 → 返回。

        推荐部署只填队伍1（实测点第二条、第三条也一样），所以这里只管主队；
        打的时候游戏会按队伍1/2/3 的顺序上，空着的跳过。

        Pages:
            in: page_world_boss
            out: page_world_boss

        Returns:
            bool: 有没有配好。
        """
        # 编辑队伍页底部那颗「推荐部署」是这一页自己的检查点（1.000）；魔兽页上的
        # 「编辑队伍」在编辑队伍页只有 0.309，所以两页要靠不同的按钮分开认。
        if not self.wait_until_appear(WB_EDIT_TEAM, offset=(20, 20), timeout=5):
            logger.warning('[World boss] not on the boss page, cannot edit the team')
            return False
        self.device.click(WB_EDIT_TEAM)  # alas-lint: allow - matched right above
        if not self.wait_until_appear(WB_RECOMMEND, offset=(20, 20), timeout=10):
            logger.warning('[World boss] the team page did not open')
            return False

        self.device.click(WB_RECOMMEND)  # alas-lint: allow - matched right above
        if not self.wait_until_appear(WB_RECOMMEND_TITLE, offset=(20, 20), timeout=10):
            logger.warning('[World boss] the recommend panel did not open')
            self.team_back()
            return False
        # 面板是淡入的，标题在第一帧就能匹配到 1.00，可这一帧的「使用」还吃不住点击
        # —— 实测 2026-10-29 就是点了一下，面板毫无反应（5 秒后既没弹确认框也没关）。
        self.wait_until_still(RECOMMEND_PANEL_AREA, timeout=5)

        logger.info('[World boss] take the top recommended formation')
        if not self.recommend_use_top():
            logger.warning('[World boss] cannot apply the recommended formation')
            self.team_back()
            return False

        # 返回键第一下先关面板，第二下才离开编辑队伍页。分清楚再点。
        if not self.wait_until_disappear(WB_RECOMMEND_TITLE, offset=(20, 20), timeout=15, settle=1):
            logger.info('[World boss] the recommend panel is still open, close it first')
            self.device.click(TEAM_BACK)  # alas-lint: allow - the panel was matched right above
            self.wait_until_disappear(WB_RECOMMEND_TITLE, offset=(20, 20), timeout=10)

        return self.team_back()

    def recommend_use_top(self):
        """
        点第一条记录右边的「使用」，把别人的阵型填进队伍1。

        点完之后游戏有两种走向，都要认：
        - 队伍里已经有人 → 弹「未拥有服装」确认框（问要不要替换），要再点「确认」；
        - 队伍是空的 → 不弹框，面板直接收起。
        两种都没发生就是这一下点空了（面板还在淡入、或者点击被动画吃掉），重来。

        Returns:
            bool: 有没有真的应用上。
        """
        for _ in range(3):
            self.device.click(RECOMMEND_USE_FIRST)  # alas-lint: allow - the panel title was matched right above
            if self.wait_until_appear(WB_CONFIRM_DIALOG, offset=(20, 20), timeout=5):
                # 确认框是淡入的：标题第一帧就能匹配到，可这一帧的「确认」还没接上
                # 点击（实测按了没反应，10 秒后又弹回来）。等它画稳再按。
                self.wait_until_still(CONFIRM_DIALOG_AREA, timeout=3)
                logger.info('[World boss] confirm replacing the team members')
                self.device.click(CONFIRM_OK)  # alas-lint: allow - the dialog was matched right above
                if self.wait_until_disappear(WB_CONFIRM_DIALOG, offset=(20, 20), timeout=10):
                    return True
                logger.info('[World boss] the confirm dialog is still there, tap 使用 again')
                continue
            if self.wait_until_disappear(WB_RECOMMEND_TITLE, offset=(20, 20), timeout=5):
                logger.info('[World boss] the team was empty, the formation is applied')
                return True
            logger.info('[World boss] the panel did not react, tap 使用 again')

        return False

    def team_back(self):
        """
        退出编辑队伍页，回到魔兽页。

        Returns:
            bool: 回到魔兽页了没有。
        """
        self.device.click(TEAM_BACK)  # alas-lint: allow - leaving the team page, the boss page below confirms it
        if not self.wait_until_appear(WB_EDIT_TEAM, offset=(20, 20), timeout=10):
            logger.warning('[World boss] cannot leave the team page')
            return False
        return True

    def difficulty_read(self):
        """
        读难度条的底色，判断现在在第几档。

        五档的底色相差很远（见模块 docstring 第 1 条），用中位数取色块本体，
        三个通道的关系就能定档，不需要 OCR —— 这一页绿底黑字和银底灰字混着来，
        OCR 得换两套 letter 才读得出来。

        Returns:
            int, None: 0..4 对应 WORLDBOSS_NAMES，认不出来返回 None。
        """
        self.device.screenshot()
        image = np.array(self.device.image).astype(int)
        edges = np.concatenate([
            image[y0:y1, x0:x1].reshape(-1, 3) for y0, y1, x0, x1 in DIFF_EDGE
        ])
        r, g, b = np.median(edges, axis=0)

        if abs(r - g) < 20 and abs(g - b) < 20:
            return 0                    # EASY 银
        if r > g and r > b:
            return 4                    # CHALLENGE 红
        if b > r and b > g:
            return 2 if g > 120 else 3  # HARD 蓝 / VERY HARD 紫
        if g > r and g > b:
            return 1                    # NORMAL 绿
        return None

    def difficulty_goto(self, level):
        """
        从当前位置挪到第 `level` 档。往低走按左箭头，往高走按右箭头。

        Args:
            level (int): 0..4。

        Returns:
            bool: 到了没有。
        """
        for _ in range(8):
            current = self.difficulty_read()
            if current is None:
                logger.warning('[World boss] cannot read the difficulty bar')
                return False
            if current == level:
                return True
            button = DIFF_LEFT if current > level else DIFF_RIGHT
            self.device.click(button)  # alas-lint: allow - the bar was read right above and is read again next round
            # 切难度是本地绘制，等底色真的变了再读下一次，否则会连点两下跳过头。
            for _ in self.loop(timeout=3):
                if self.difficulty_read() != current:
                    break
        logger.warning(f'[World boss] cannot switch to difficulty {level}')
        return False

    def difficulty_to_lowest(self):
        """
        一路往低按到 EASY。到顶之后再按左箭头没有反应，所以按到读数不再变小为止。

        Returns:
            bool: 有没有停在最低档。
        """
        if not self.wait_until_appear(WB_EDIT_TEAM, offset=(20, 20), timeout=5):
            return False
        return self.difficulty_goto(0)

    def difficulty_next(self):
        """
        往上走一档。

        Returns:
            bool: 还有更高的档位。
        """
        current = self.difficulty_read()
        if current is None or current >= len(WORLDBOSS_NAMES) - 1:
            return False
        return self.difficulty_goto(current + 1)

    def battle(self, name):
        """
        在当前难度上打一场，读回结算结果。

        Pages:
            in: page_world_boss
            out: page_world_boss

        Args:
            name (str): 难度名，只用来打日志。

        Returns:
            (bool, int): (这一档过了没有，本场伤害)。
                过了是 True；结算页是 BATTLE END 是 False；连结算页都没看到是 None
                —— 两种情况要分开，没看见结算页时不能当成"打过了"。
        """
        if not self.wait_until_appear(WB_EDIT_TEAM, offset=(20, 20), timeout=5):
            logger.warning(f'[World boss] {name}: not on the boss page')
            return None, 0
        # 刚切过难度，面板正在重画（血量、通关奖励都换了一套）。这时候点「去战斗」
        # 会被动画吃掉 —— 实测 2026-10-29 点下去 30 秒都没反应。
        self.wait_until_still(BOSS_PANEL_AREA, timeout=10)

        # 进战斗会重载整个游戏，魔兽页整块消失；它消失就是"确实进了"。没消失就再点
        # 一次 —— 这一步失败等于这一档今天不打了，值得多试一下。
        # 按下去走 adb tap：这一颗实测不吃 minitouch 的短按（见 `tap_point`）。
        # 超时给 20 秒：进战斗的话一两秒内就黑屏了，20 秒还没动静就是真没进去，
        # 而这个页面是静止的，等太久会被框架判成卡死（60 帧没有点击）。
        for _ in range(2):
            self.tap_asset(FIGHT)
            if self.wait_until_disappear(WB_EDIT_TEAM, offset=(20, 20), timeout=FIGHT_TIMEOUT):
                break
            logger.info(f'[World boss] {name}: still on the boss page, tap 去战斗 again')
        else:
            logger.warning(f'[World boss] {name}: the fight did not start')
            self.device.save_screenshot(genre='world_boss_no_fight')
            return None, 0

        # 加载完之后血条还在画，等这块稳住再点自动战斗，否则会点在加载画面上。
        self.wait_until_still(BATTLE_HUD_AREA, timeout=BATTLE_ENTER_TIMEOUT)

        self.auto_battle_on()
        if not self.battle_wait_end():
            logger.warning(f'[World boss] {name}: the fight did not end in time')
            return None, 0

        # 伤害数字是从 0 滚上去的，结算页刚出来时读到的是中间某一帧。等它定住再读。
        self.wait_until_still(RESULT_DAMAGE, timeout=5)
        damage = self.read_damage()
        victory = self.appear(WB_VICTORY, offset=(20, 20))
        logger.attr(f'{name} result', ('VICTORY' if victory else 'BATTLE END') + f', {damage} damage')
        self.battle_back()
        return victory, damage

    def auto_battle_on(self):
        """
        确保自动战斗是开着的。

        这颗钮是切换式的：开着的再点一下会关掉。战斗默认是手动回合制，但也有
        开局就是自动的时候（第一次进这一页就是），所以每次都先看颜色再决定点不点。

        Returns:
            bool: 最后是不是开着的。
        """
        for _ in range(3):
            # 每一轮都先看颜色再决定点不点：这颗是切换式的，上一轮其实已经打开、
            # 只是那三帧没读到时，再点一下又会把它关掉。所以这里要的是"稳定关着"。
            if self.auto_battle_running(stable=True):
                logger.info('[World boss] auto battle on')
                return True
            # 打完了的那一页，右上角本来就没有蓝环 —— 这时候再点三下就是往结算页
            # 上乱点。实测 2026-10-29 一场，结算页早就出来了，脚本还在那儿点了三下
            # （每次白等 5 秒），整整晚 17 秒才认出"打完了"。
            if self.appear(WB_RESULT_BACK, offset=RESULT_BACK_OFFSET):
                logger.info('[World boss] this fight is over, no need to turn it on')
                return False
            self.device.click(AUTO_BATTLE)  # alas-lint: allow - the glow was read right above and is read again next round
            # 按下去的那一瞬间图标会亮一下（手指按住的反馈），只读一帧就会把"点到了"
            # 当成"打开了"——实测 2026-10-29 就是这么报了一句 auto battle on，然后整场
            # 停在第 1 回合等玩家出手，直到 5 分钟后被判成卡死。所以连续三帧都读到蓝光
            # 才算数。
            seen = 0
            for _ in self.loop(timeout=5):
                seen = seen + 1 if self.auto_battle_running() else 0
                if seen >= 3:
                    logger.info('[World boss] auto battle on')
                    return True
            logger.info('[World boss] the auto battle button did not react, tap it again')

        logger.warning('[World boss] cannot turn on auto battle')
        return False

    def auto_battle_running(self, stable=False):
        """
        读自动战斗那颗钮的蓝光。开着的时候图标外面套一圈蓝环，关着是纯白。

        实测（2026-10-29，1280x720）：开着 (1001,26)-(1033,58) 里 B-R>35 的像素占
        0.49~0.55，关着 0.000，中间没有任何过渡值。

        Args:
            stable (bool): 连续三帧都读到才算数。**判断"真的关掉了、该去点它"的时候
                必须用这个**：队伍交接、BOSS 放大招都会让这一角暗一下，只看一帧就会
                把"正好被特效盖住"当成"关掉了"，于是补点一下反而把开着的关掉 ——
                实测 2026-10-29 一场里就这么误判过一次。

        Returns:
            bool: 开着没有。
        """
        for _ in range(3 if stable else 1):
            self.device.screenshot()
            x0, y0, x1, y1 = AUTO_GLOW
            patch = np.array(self.device.image)[y0:y1, x0:x1].astype(int)
            ratio = ((patch[:, :, 2] - patch[:, :, 0]) > 35).mean()
            if ratio <= AUTO_GLOW_RATIO:
                return False
        return True

    def battle_wait_end(self):
        """
        等这一场打完。

        判据是结算页右下角那颗「返回」：战斗画面里它是 0.450，结算页上 0.944，
        两边离得很远。**不要每帧去 OCR「伤害量」**：战斗画面那块地方是满屏跳动的
        伤害数字和特效，cnocr 读出来的全是 `|a.` / `心全|` 这种碎片，万一哪一帧
        凑出四个数字就会被当成"打完了"（`read_damage` 只要 ≥1000 就算数）。
        换成模板匹配既便宜又不会误判。

        等待期间每 5 秒回头看一眼自动战斗 —— 它会莫名其妙掉回手动（实测队伍交接
        的时候掉过一次），掉了就重新打开，否则这一场会一直停在当前回合。

        Returns:
            bool: 有没有等到。
        """
        timer = Timer(5)
        for _ in self.loop(timeout=BATTLE_TIMEOUT):
            # 一场仗要打好几分钟，这期间一个点击都没有，框架的卡死计时器（60 帧没有
            # 一次点击就判卡死，硬约束 13）会把它当成卡死。这里明说"我在盯着屏幕"，
            # 真正的上限交给下面的 BATTLE_TIMEOUT。
            self.device.stuck_record_clear()
            if self.appear(WB_RESULT_BACK, offset=RESULT_BACK_OFFSET):
                logger.info('[World boss] this fight is over')
                return True
            if timer.reached():
                timer.reset()
                if not self.auto_battle_running(stable=True):
                    logger.info('[World boss] auto battle went off, turn it on again')
                    self.auto_battle_on()
        return False

    def battle_back(self):
        """
        结算页点「返回」，等魔兽页回来。

        VICTORY 和 BATTLE END 两个结算页的按钮位置不同，所以这里先按模板找到
        「返回」再点它 —— `appear()` 会把匹配到的偏移记在按钮上，`device.click()`
        点的就是匹配到的那个位置。

        Returns:
            bool: 回来了没有。
        """
        # 找不到就一下都不点。这一页上离它 30 像素就是「挑战下一个难度」，
        # 点错的代价是又开一场（实测）。
        if not self.wait_until_appear(WB_RESULT_BACK, offset=RESULT_BACK_OFFSET, timeout=10):
            logger.warning('[World boss] cannot find 返回 on the result page')
            self.device.save_screenshot(genre='world_boss_no_result_back')
            return False

        self.device.click(WB_RESULT_BACK)  # alas-lint: allow - matched right above
        if not self.wait_until_appear(WB_EDIT_TEAM, offset=(20, 20), timeout=RESULT_BACK_TIMEOUT):
            logger.warning('[World boss] did not get back to the boss page')
            return False
        self.wait_until_still(BOSS_PANEL_AREA, timeout=10)
        return True

    def read_cleared(self):
        """
        当前这一档是不是已经打穿了。

        打穿之后，面板上「最高伤害量」那一行的数值会被换成「完成讨伐」，右上角的
        通关奖励也打上勾，而「去战斗」按下去什么都不发生（实测两次都石沉大海，
        等于白等两次超时）。所以进度读这里，不读本地账本 —— 换期也不用另外判断，
        新一期的面板上没有任何一档写着这四个字。

        实测模板分：打穿的面板 1.000，没打穿的面板 0.44~0.64（那里是伤害数字）。

        Returns:
            bool: 打穿了没有。
        """
        return self.appear(WB_CLEARED, offset=(20, 20))

    def read_boss_name(self):
        """
        读面板上的 BOSS 名字，用来认"换期了没有"。

        Returns:
            str: 名字。读不出来返回空串。
        """
        ocr = Ocr(PANEL_BOSS, lang='cnocr', letter=(255, 255, 255),
                  threshold=RESULT_DAMAGE_THRESHOLD, name='WB_BOSS_NAME')
        self.device.screenshot()
        text = str(ocr.ocr(self.device.image))
        name = re.sub(r'[^0-9A-Za-z\u4e00-\u9fa5]', '', text)
        if len(name) < 2:
            logger.warning(f'[World boss] cannot read the boss name: {text!r}')
            return ''
        logger.attr('Boss', name)
        return name

    def read_damage(self):
        """
        读结算页上的「伤害量 N」。

        Returns:
            int: 伤害。不在结算页上（或者读不出来）返回 0。
        """
        ocr = Ocr(RESULT_DAMAGE, lang='cnocr', letter=(255, 255, 255),
                  threshold=RESULT_DAMAGE_THRESHOLD, name='WB_DAMAGE')
        self.device.screenshot()
        text = str(ocr.ocr(self.device.image))
        return self.parse_number(text)

    @staticmethod
    def parse_number(text):
        """
        把 cnocr 读出来的数字串转成整数。

        cnocr 对千分位逗号不太稳定，实测 `1,031,000` 会读成 `1031.000`、
        `22,811,200` 会读成 `22811.2002a`（把后面的 `/` 也读成了数字）。所以先按
        斜杠切掉后半段（那里是"当前/上限 (百分比)"），再从剩下的里面找第一段数字 ——
        「伤害量 11,700」这种带着中文前缀的也走同一条路。

        只用来读结算页的伤害量，**不要拿它读血量**：血量是 9~13 位的大数，这套字体
        上会丢数字（`22,811,200` 读成 `22,81,200`），而伤害量最多 8 位，实测都准。

        Args:
            text (str): OCR 原始输出。

        Returns:
            int: 数值。不足四位当作没读到，返回 0 —— 伤害不会小于一千。
        """
        head = re.split(r'[/／]', text)[0]
        match = re.search(r'[0-9][0-9,.\s]*', head)
        if not match:
            return 0
        digits = re.sub(r'\D', '', match.group(0))
        if not digits:
            return 0
        value = int(digits)
        return value if value >= 1000 else 0
