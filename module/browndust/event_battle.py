"""
活动战斗 (Brown Dust II) —— 普通战斗 / 挑战战斗，共用一个每日次数。

Measured on the real device, 2026-10-29, season 「BROKEN BONDS」:

    page_event --底部「普通战斗」-->  关卡页
    page_event --底部「挑战战斗」-->  关卡页（同一个骨架，换一套关卡）
    关卡页 --右下「自动战斗」-->  次数面板 --「战斗 N」-->  连打 N 场
    连打结束 --> 结果页 --「返回」-->  关卡页

关于这一页有七件事是量出来的：

1. **两个模式共用同一个每日次数**：右上角那枚「N/5」在普通战斗和挑战战斗上是
   同一个数（实测 5/5，打完三场之后两边都显示 2/5）。所以这两个页签必须当成
   一个预算来花，先花哪个由 `BattleMode` 决定。

2. **「自动战斗」不是开关，是一个次数面板**：点开会弹「自动战斗 / 普通战斗N」，
   里面是「仅使用免费活动AP」（默认开）、`MIN / -10 / +10 / MAX`、一根滑块，
   以及一段说明：*将按照指定次数自动进行战斗。若战斗过程中未能通关，自动战斗
   将会结束。奖励将按照成功通关次数发放。通关时将自动进行下一场战斗。*
   最后那句是重点 —— 这里说的"下一场"是**下一关**，不是同一关再打一次。

3. **设 N 次就是连着开荒 N 关**：实测第 3 关设 2 次，打完弹的是「普通战斗4」的
   结果页，不是第 3 关的第二场。所以开荒不用自己一关一关点，设个次数就行。
   中途哪一关打不过就停在那里（说明里写了），这就是"开荒到打不动"的天然边界。

4. **面板里不显示次数，只有滑块**：唯一的读数是底部那枚按钮上的数字 ——
   「战斗 1」是打 1 场，「战斗 2」是 2 场（点 MAX 之后从 1 变成 2，因为当时
   只剩 2 张 AP）。所以次数只能拖出来再读回来，没法直接输入。

5. **连打中和大完之后，结果页底部的按钮不一样**：
   - 连打中：右下角是「✖ 结束自动战斗」，左下角还有一行「自动战斗进行中：
     第1次 / 共2次」；
   - 打完了：右下角换成「返回」+「前往下一个战斗」（还有下一关）或
     「重新挑战」（这一关已经通关过）。
   所以"打完了没有"不用数场次，认那颗「结束自动战斗」还在不在就行。

6. **已通关的关卡没有「自动战斗」入口**：底部只剩「角色」和「战斗 🎫1」。
   而同一天里还没通关的下一关是有「自动战斗」的。三种底部布局都实测过：
   - 未通关可打：`角色 | 战斗 🎫1 | 自动战斗`
   - 已通关：`角色 | 战斗 🎫1`
   - 还没解锁（第 5、10 关这种带 `»` 的）：`角色 | 快速战斗 | 战斗 🎫1`，都灰

7. **AP 用完时点「自动战斗」会弹「活动AP不足」**：说明是「活动AP不足，无法战斗。
   是否补充活动AP?」，按钮「取消 / 补充」。**绝不点「补充」** —— 那是拿货币买
   AP。这个弹窗同时也是"今天打完了"的信号。

还有一条不是陷阱但很容易看错：关卡列表会随选中项滚动，写死的 y 靠不住（实测
点 (200,118) 一点反应都没有，点 (220,181) 却选中了第 4 关）。这个任务不点列表
—— 游戏自己会把"下一关"选中，开荒顺着它走就行；全通关后扫荡也是打游戏当前
选中的那一关（玩家战力不足时会自己选上一关），脚本不替他选。

2026-11-10 补的三种画面（用户给了三张真机截图）：

8. **打完最后一关的结果页只剩「返回」(+「重新挑战」)**，整颗「返回」右移约
   90px 到 (914,636)。旧判据 `offset=(20,20)` 只有 0.640 —— `battle_wait_end()`
   认不出"这一轮打完了"，`battle_back()` 也认不出"返回在哪"，整条活动任务
   卡在结果页。现在统一用 `RESULT_BACK_OFFSET=(200,30)`，并让 `match()` 的
   偏移把点击点一起带过去。

9. **关卡页分两种状态**：有「自动战斗 OFF」开关 = 还没通关、能开荒；没有开关
   且「战斗」胶囊延长变白 = 已经全通关、只剩扫荡。用 `EVENT_AUTO_SWITCH` 和
   胶囊右端亮像素两条**正面**判据区分（`battle_level_state()`），别靠"点了开关
   没反应"反推 —— 那样既慢又会把点击被吞误判成已通关。

10. **GUI 选 Both 时普通已经全通关，要切到挑战战斗**：两个模式共用每天 5 次
    AP，普通没有首通可拿就不该在它身上点「战斗」把 AP 花光。`event_battle_run()`
    只给最后一个模式开 `allow_sweep`，并把没花掉的预算留给后一个模式。
"""
import re

from module.base.button import Button
from module.base.timer import Timer
from module.browndust.assets import (BATTLE_PANEL, EVENT_AP_SHORT, EVENT_AUTO_STOP,
                                     EVENT_AUTO_SWITCH, EVENT_AUTO_TITLE,
                                     EVENT_RESULT_BACK, EVENT_TAB_CHALLENGE,
                                     EVENT_TAB_NORMAL)
from module.browndust.browndust_ui import page_event
from module.logger import logger
from module.ocr.ocr import Ocr

# 关卡页右下角的「自动战斗」开关。它画的是一颗齿轮 + `OFF`/`ON` 加一行白字，
# 那个 OFF 会随状态变，所以不拿它做模板 —— 只借位置，判据是点完之后弹出来的是
# 次数面板还是 AP 不足。点在空白处（已通关的关卡没有这个开关）游戏不会有任何
# 反应，正好用来区分那三种底部布局。
AUTO_SWITCH = Button(area=(1068, 618, 1252, 676), color=(0, 0, 0),  # alas-lint: allow - the switch has two states and its label sits on the level art, so only the location is used
                     button=(1102, 647, 1102, 647), name='AUTO_SWITCH')

# 关卡页中间那枚「✖ 战斗 🎫1」。已通关的关卡没有「自动战斗」，只能点它打一场。
LEVEL_FIGHT = Button(area=(860, 630, 1040, 670), color=(0, 0, 0),  # alas-lint: allow - the label carries the AP cost, and this is only reached when the auto panel did not open
                     button=(950, 647, 950, 647), name='LEVEL_FIGHT')

# 次数面板。位置都在面板自己的固定位置上。
AUTO_SLIDER_X = (466, 806)
AUTO_SLIDER_Y = 348
AUTO_START = Button(area=(600, 560, 810, 610), color=(0, 0, 0),  # alas-lint: allow - the label carries the count 「战斗 N」, which is read with OCR right before the tap
                    button=(704, 584, 704, 584), name='AUTO_START')

# 面板底部那枚按钮上的「战斗 N」。N 就是这一次要连打几场，也是设定次数的唯一读数。
AUTO_START_LABEL = (640, 568, 790, 602)
AUTO_START_THRESHOLD = 170

# AP 不足弹窗的「取消」。弹窗居中在 (423,195)-(816,510)，两枚按钮并排在最下面：
# 取消 (509,463)-(630,498)、补充 (645,463)-(766,498)。**只点左边那枚。**
AP_CANCEL = Button(area=(500, 455, 640, 506), color=(0, 0, 0),  # alas-lint: allow - white 取消 on the system dialog, the dialog itself is matched as EVENT_AP_SHORT
                   button=(569, 480, 569, 480), name='AP_CANCEL')

# 结果页右下角的「返回」。连打中它不存在，所以"看到它"= 这一轮打完了。
#
# ❗它**不是固定在 (824,636)** 的：普通/挑战打完最后一关时，结果页没有
#   「前往下一个战斗」，只剩「返回」（+「重新挑战」），整颗按钮右移约 90px
#   到 (914,636)。模板 `EVENT_RESULT_BACK` 还是同一颗按钮，用大 offset 让
#   `match()` 自己找到它；命中后 `Button.button` 会一起偏移，直接
#   `device.click(EVENT_RESULT_BACK)` 就点在真实位置上，**不要再写死坐标**
#   （旧的点 (886,669) 在最后一关结果页上会落在旁边的统计圆按钮）。
#   2026-11-10 三张真机帧实测：offset=(20,20) 只有 0.640（认不出，卡在结果页），
#   (120,20) 起 0.980@(914,636)；关卡页 / 结果页其它帧最高 0.588，不会假阳性。
RESULT_BACK_OFFSET = (200, 30)

# 关卡页右下角「战斗」胶囊的右端。开荒态这块被「自动战斗 OFF」开关占着（深色），
# 已通关态没有开关、胶囊延长到 x≈1150 变成整片米白。用亮像素占比作**已通关**
# 的正面判据，和 `EVENT_AUTO_SWITCH`（开荒的正面判据）互证 —— 两条都不成立就是
# 转场帧，等下一帧，别用 `if not appear()` 去猜（硬约束 R5）。
# 实测亮像素占比：已通关 0.978、开荒 0.149、结果页 0.314，阈值 0.5 余量充足。
LEVEL_CAPSULE_END = (1040, 630, 1150, 670)
LEVEL_CAPSULE_BRIGHT = 0.5
# 开关模板的搜索余量。
AUTO_SWITCH_OFFSET = (20, 20)
# 关卡详情面板（读关卡号用）。标题在面板顶部，白字压在深色底上。
LEVEL_TITLE = (700, 88, 880, 122)
LEVEL_THRESHOLD = 170
# 顶部那枚「N/5」。压在金色背景上，但数字本身是纯白，左边的 AP 图标是紫金两色，
# 所以框要贴紧数字：宽一点就会把背景的金色叶子带进来，cnocr 会读成 `0/5\``。
AP_AREA = (1144, 28, 1178, 52)
AP_THRESHOLD = 170

# 一轮连打的上限。5 张 AP、每场 20~30 秒，加上转场三分钟足够；给 15 分钟是留给
# 模拟器卡顿和某一关卡住。
BATTLE_TIMEOUT = 900
# 点「自动战斗」之后等面板或者 AP 不足弹窗。都是本地绘制，3 秒还没出来就是没点中。
AUTO_PANEL_TIMEOUT = 3
# 设定次数之后读回「战斗 N」。字立刻就在，读不到就再读一帧。
AUTO_TIMES_TIMEOUT = 3
# 点页签进战斗页、点「返回」回关卡列表，两个都会重载一次游戏（BROWN DUST II 的
# 跑马灯，右下角还有加载百分比），实测 14~17 秒，给 30 秒。
BATTLE_ENTER_TIMEOUT = 30
RESULT_BACK_TIMEOUT = 30
# 「战斗 N」按下去之后，次数面板还亮着多久算"开打被挡了"。正常开打一两秒就进
# 转场；被「支付失败」挡住时面板会一直亮。2026-11-04 实机。
EVENT_PANEL_REPRESS = 5
# 关卡列表的面积，用来等重载画完。
LEVEL_PANEL_AREA = (490, 70, 1010, 600)


class EventBattle:
    """
    Spend the event's shared 5-a-day AP on 普通战斗 / 挑战战斗.

    开荒和日常扫荡走的是两条路，因为游戏给它们的入口不一样（见模块 docstring
    第 6 条）：还没通关的那一关有「自动战斗」，可以一次设 N 场连着打；已经通关
    的关卡只剩「战斗」和「重新挑战」，只能一场一场来。

    Pages:
        in: page_event
        out: page_event
    """

    def event_battle_run(self):
        """
        Pages:
            in: page_event
            out: page_event
        """
        self.ui_goto(page_event)
        pages = self.battle_pages()
        # 只开一个模式的时候把今天的次数全给它；两个都开就各按 `Times` 分，
        # 否则先打的那个会把 AP 吃光，后一个一场都打不了。
        budget = int(self.config.BrowndustEvent_Times) if len(pages) > 1 else 5
        for index, (tab, name) in enumerate(pages):
            logger.hr(name, level=2)
            if not self.battle_enter(tab, name):
                continue
            # ❗普通已经全通关时，不要在它身上点「战斗」把共享 AP 花掉 ——
            #   GUI 选了 Both 就该切到挑战继续开荒（2026-11-10 真机）。
            #   只有最后一个模式允许扫荡：两个模式都全通关时才拿剩余次数反复打
            #   当前选中的最后一关。
            allow_sweep = index == len(pages) - 1
            used = self.battle_page(name, budget, allow_sweep=allow_sweep)
            if used == 0 and index < len(pages) - 1:
                # 前一个模式一场没花（全通关跳过），共享 AP 全留给后一个模式开荒。
                budget = 5
        # `battle_page()` 打完就停在关卡列表上，回活动页交给外层下一步的 `ui_goto`。

    def battle_pages(self):
        """
        按配置决定打哪几个页签，普通战斗在前（首通给抽卡资源）。

        Returns:
            list: [(Button, str)]，可能为空。
        """
        mode = self.config.BrowndustEvent_BattleMode
        if mode == 'Challenge':
            return [(EVENT_TAB_CHALLENGE, '挑战战斗')]
        if mode == 'Both':
            return [(EVENT_TAB_NORMAL, '普通战斗'), (EVENT_TAB_CHALLENGE, '挑战战斗')]
        return [(EVENT_TAB_NORMAL, '普通战斗')]

    def battle_enter(self, tab, name):
        """
        从活动页点页签进战斗页。

        两个页签共用 `page_event_battle` 一个页面（它们只有左上角那两个字不一样，
        模板互相能到 0.834，不值得用标题区分），所以切换模式不走页面图的 link，
        而是先回活动页再点页签。

        Pages:
            in: page_event
            out: page_event_battle

        Args:
            tab (Button): 「普通战斗」或「挑战战斗」那行白字。
            name (str): 日志用。

        Returns:
            bool: 有没有进去。
        """
        self.ui_goto(page_event)
        # 活动页有入场动画，底部那排木牌是最后画出来的；画之前点等于点在背景上，
        # 游戏一声不响（硬约束 40）。所以先等页签自己出现，再点它。
        if not self.wait_until_appear(tab, offset=(20, 20), timeout=10):
            logger.warning(f'[Event battle] the {name} tab did not show up')
            return False
        self.device.click(tab)  # alas-lint: allow - the tab was just matched, the level panel below is the proof
        # 进战斗页会重载一遍游戏（BROWN DUST II 的跑马灯 + 百分比），要十几秒。
        if self.wait_until_appear(BATTLE_PANEL, offset=(20, 20), timeout=BATTLE_ENTER_TIMEOUT):
            return True
        logger.warning(f'[Event battle] cannot open {name}')
        return False

    def battle_page(self, name, budget, allow_sweep=True):
        """
        把这一页的次数花掉：能开荒就开荒，全通关了才扫荡。

        Pages:
            in: page_event_battle
            out: page_event_battle，停在关卡列表上

        Args:
            name (str): 页签名，只用来打日志。
            budget (int): 这一页最多打几场（还要再过一遍剩下的 AP）。
            allow_sweep (bool): 全通关后要不要扫荡。Both 的普通战斗传 False，
                共享的 5 次 AP 才能留给挑战开荒。

        Returns:
            int: 打了几场。
        """
        fought = 0
        for _ in self.loop(timeout=BATTLE_TIMEOUT):
            if budget <= 0:
                logger.info(f'[Event battle] {name}: budget of {fought} used up')
                break
            # 进战斗页 / 点「返回」都会重载一遍游戏；只有关卡面板画出来了才
            # 往下读 AP / 判状态，否则 OCR 读到 0 会直接收工。用正面条件包住
            # 整个循环体，加载帧上什么都不做（硬约束 R5）。
            if self.appear(BATTLE_PANEL, offset=(20, 20)):
                ap_left = self.battle_ap_left()
                if ap_left == 0:
                    logger.info(f'[Event battle] {name}: no AP left today')
                    break

                state = self.battle_level_state()
                if state is None:
                    # 转场 / 淡入的过渡帧，两条正面判据都不成立，等下一帧再判。
                    continue
                if state == 'cleared':
                    if not allow_sweep:
                        logger.info(f'[Event battle] {name}: all levels cleared, '
                                    'leave the shared AP to the next mode')
                        break
                    logger.info(f'[Event battle] {name}: all levels cleared, '
                                'sweep the selected level')
                    done = self.battle_single(name)
                else:
                    done = self.battle_auto(name, min(budget, ap_left), ap_left)
                if not done:
                    # 0 = 游戏说没 AP / 面板没打开，None = 连「战斗」都点不动。
                    # 两种都得停下，不然记账不减、预算不减就成了空转。
                    logger.info(f'[Event battle] {name}: nothing more to fight')
                    break

                fought += done
                budget -= done
        else:
            logger.warning(f'The {name} did not finish in time')

        logger.info(f'[Event battle] {name}: {fought} fight(s)')
        return fought

    def battle_level_state(self):
        """
        当前选中的关卡是「还能开荒」还是「已经全通关，只剩扫荡」。

        两条都是**正面**判据，都没命中就是过渡帧（返回 None）：

        - `EVENT_AUTO_SWITCH`：开荒页右下角那颗齿轮 + `OFF` +「自动战斗」。
          已通关页没有它。实测 开荒 1.000 / 已通关 0.278 / 结果页 0.180。
        - 胶囊右端亮白：已通关页的「战斗」胶囊会变长、盖掉原本开关的位置，
          实测亮像素占比 0.978；开荒页那里是深色面板 0.149。

        Returns:
            str, None: 'frontier' / 'cleared' / None。
        """
        if self.appear(EVENT_AUTO_SWITCH, offset=AUTO_SWITCH_OFFSET):
            return 'frontier'
        patch = self.image_crop(LEVEL_CAPSULE_END, copy=False)
        if (patch.mean(axis=2) > 200).mean() > LEVEL_CAPSULE_BRIGHT:
            return 'cleared'
        return None

    def battle_auto(self, name, times, ap_left):
        """
        点「自动战斗」，设次数，开打，等这一轮连打结束。

        调用前 `battle_level_state()` 已确认这一关有开关，所以「面板没弹出来」
        只可能是点击被转场吞了（硬约束 40/153）：按 3 次重试，而不是当成
        「已通关」去点「战斗」把共享 AP 花掉。

        Args:
            name (str): 页签名，只用来打日志。
            times (int): 想连打几场。
            ap_left (int): 当前可用次数，也就是滑块最右端。

        Returns:
            int: 真的打了几场；0 表示这一轮没打成。
        """
        for _ in range(3):
            self.device.click(AUTO_SWITCH)  # alas-lint: allow - battle_level_state() matched the switch, the panel below is the proof
            if self.wait_until_appear(EVENT_AUTO_TITLE, offset=(20, 20),
                                      timeout=AUTO_PANEL_TIMEOUT, settle=2):
                break
            if self.appear(EVENT_AP_SHORT, offset=(20, 20)):
                self.battle_ap_short()
                return 0
        else:
            logger.warning('[Event battle] the 自动战斗 panel did not open, stop')
            return 0

        wanted = self.battle_set_times(times, ap_left)
        logger.info(f'[Event battle] {name}: auto fight x{wanted}')
        self.device.click(AUTO_START)  # alas-lint: allow - the panel title is matched above and the count was read off this very button
        self.battle_wait_end()
        self.battle_back()
        return wanted

    def battle_set_times(self, times, ap_left):
        """
        把滑块拖到想要的次数，读回「战斗 N」确认。

        面板里只有 `MIN / -10 / +10 / MAX` 和一根滑块，没有数字输入，所以次数
        只能拖出来再读回来。

        Args:
            times (int): 想设几场。
            ap_left (int): 当前可用次数，滑块最右端就是它。

        Returns:
            int: 实际设成几场（读不回来时按面板默认的 1 算）。
        """
        if times <= 1 or ap_left <= 1:
            # 面板打开时就是 1 场，不碰滑块。
            return self.battle_read_times()

        left, right = AUTO_SLIDER_X
        x = left + (right - left) * (times - 1) / (ap_left - 1)
        logger.attr('Event AP', f'{ap_left} left, want {times}')
        self.device.swipe((left, AUTO_SLIDER_Y), (x, AUTO_SLIDER_Y), duration=0.4)
        got = self.battle_read_times()
        if got != times:
            logger.warning(f'Slider gave {got} instead of {times}, take what it gave')
        return got

    def battle_read_times(self):
        """
        读面板底部「战斗 N」里的 N。

        Returns:
            int: 场次。读不出来时返回 1（面板的默认值），不会因为读错而多点几场。
        """
        ocr = Ocr(AUTO_START_LABEL, lang='cnocr', letter=(255, 255, 255),
                  threshold=AUTO_START_THRESHOLD, name='AUTO_TIMES')
        for _ in self.loop(timeout=AUTO_TIMES_TIMEOUT):
            text = str(ocr.ocr(self.device.image))
            match = re.search(r'(\d+)', text)
            if match:
                got = int(match.group(1))
                logger.info(f'[Event battle] times set to {got}')
                return got
        logger.warning('Could not read the times off the panel')
        return 1

    def battle_wait_end(self):
        """
        等这一轮连打全部打完。

        结果页右下角在连打中是「✖ 结束自动战斗」，打完之后换成「返回」。两颗不会
        同时在场，所以判据只有一条：**看见「返回」就是打完了**。战斗中、转场中
        两颗都不在，继续等。打完最后一关时「返回」会右移约 90px，判据用
        `RESULT_BACK_OFFSET` 放宽搜索区，别再写死 (20,20)。

        商店客户端什么时候想连就什么时候连，「支付失败 / GetProducts」弹窗开打
        那一刻最常见（2026-11-04 实机：按完「战斗 N」60 秒后弹出来，把开打挡住，
        面板原样停在弹窗后面）。所以这个循环里还要做两件事：先关弹窗；关完之后
        面板若还亮着，就是战斗没被接受，补按一次「战斗 N」——补按有 5 秒节流，
        正常开打的转场动画不会被判成"没打上"。

        Returns:
            bool: 有没有等到。
        """
        running = False
        # 面板连续可见的计时。进循环就启动：battle_auto 刚按完「战斗 N」面板
        # 还有一瞬在场上，靠它挡住补按；真正被弹窗挡住时面板会一直亮，5 秒后补。
        panel = Timer(EVENT_PANEL_REPRESS).start()
        for _ in self.loop(timeout=BATTLE_TIMEOUT):
            # 连打四场要好几分钟，中间一个按钮都不点。框架的看门狗把"60 秒没
            # 点击"当成卡死 —— 2026-10-30 实测，第 60 秒准时掐在连打中间，而
            # 那时游戏正打得好好的。这里等的是游戏自己打完，先说清楚（硬约束 13）；
            # 真卡住由上面的 BATTLE_TIMEOUT 收场。
            self.device.stuck_record_clear()
            # 「支付失败」不归结果页管，先认它：不关掉，返回键永远出不来。
            if self.handle_payment_error():
                panel.reset()
                continue
            # 「返回」会随结果页布局右移（最后一关没有「前往下一个战斗」），
            # 搜索区必须放宽，否则整轮连打结束也认不出、死等到 BATTLE_TIMEOUT。
            if self.appear(EVENT_RESULT_BACK, offset=RESULT_BACK_OFFSET):
                logger.info('[Event battle] this round is over')
                return True
            # 开打被弹窗挡住：次数面板还停在原地。补按一次，再给它 5 秒。
            if self.appear(EVENT_AUTO_TITLE, offset=(20, 20)) and panel.reached():
                logger.warning('The auto battle did not start, press 战斗 again')
                self.device.click(AUTO_START)  # alas-lint: allow - the panel title is matched right above, the panel leaving is the proof it worked
                panel.reset()
                continue
            # `running` 只喂日志，不参与判断 —— 连打中间那颗「结束自动战斗」在
            # 每一场的结算页上都会闪一下，拿它当"打完了"会提前收工。
            if not running and self.appear(EVENT_AUTO_STOP, offset=(20, 20)):
                running = True
                logger.info('[Event battle] auto battle accepted, at least one fight done')
        logger.warning('The auto battle did not finish in time')
        return False

    def battle_back(self):
        """
        结果页点「返回」，等关卡列表回来。

        最后一关的结果页上「返回」右移了，点的是模板匹配后的偏移位置，不是
        写死的坐标（见 `RESULT_BACK_OFFSET`）。

        实测会重载一次游戏（BROWN DUST II 的跑马灯），要十几秒，所以超时给得比
        别处长。

        Returns:
            bool: 回来了没有。
        """
        if self.wait_until_appear(EVENT_RESULT_BACK, offset=RESULT_BACK_OFFSET, timeout=3):
            # ❗用模板按钮自己点：`match()` 会把 `Button.button` 偏移到「返回」的
            #   真实位置。不能再点写死的 (886,669) —— 最后一关结果页上那里是
            #   旁边的统计圆按钮，点下去只会打开战报、卡在结果页。
            self.device.click(EVENT_RESULT_BACK)  # alas-lint: allow - matched right above, the offset carries the click point onto 返回
            self.wait_until_disappear(EVENT_RESULT_BACK, offset=RESULT_BACK_OFFSET,
                                      timeout=RESULT_BACK_TIMEOUT, settle=2)
            # 「返回」消失之后还在黑屏里重建场景，等关卡面板自己画完再往下走，
            # 否则下一步点「自动战斗」会点在加载画面上。
            self.wait_until_still(LEVEL_PANEL_AREA, timeout=RESULT_BACK_TIMEOUT)
            return True

        logger.warning('[Event battle] no 返回 on the result page')
        return False

    def battle_single(self, name):
        """
        扫荡：已经通关过的关卡没有「自动战斗」，只有一枚「战斗 🎫1」，打一场算一场。

        ❗打的是**游戏当前选中的关卡**（游戏自己记住上次选的哪一关，通常就是
          能打到的最后一关；战力不足时玩家会自己选上一关）。不点左侧关卡列表：
          列表会随选中项滚动、写死的 y 靠不住（模块 docstring 最后一条）。

        这条路走完一定回到关卡列表，下一场由 `battle_page()` 的循环再来一次 ——
        每次都要重载一遍游戏（十几秒），但一天只在这条路上走几次，换来的是
        "一轮只做一件事"，出问题容易从日志里看出来。

        Returns:
            int, None: 打了几场（0 或 1）；None 表示连「战斗」都点不动。
        """
        logger.info(f'[Event battle] {name}: single fight')
        # 检查点用关卡详情面板，不用那枚按钮 —— `LEVEL_FIGHT` 是纯坐标，没有模板，
        # 进 `appear()` 会在加载那一刻拿 None 去开图片（硬约束 82）。
        if self.wait_until_appear(BATTLE_PANEL, offset=(20, 20), timeout=3):
            self.device.click(LEVEL_FIGHT)  # alas-lint: allow - the level panel was matched right above
            if self.appear(EVENT_AP_SHORT, offset=(20, 20)):
                # 这一关也点得动，但 AP 不够 —— 今天到此为止。
                self.battle_ap_short()
                return 0
            self.battle_wait_end()
            self.battle_back()
            return 1

        logger.warning(f'[Event battle] {name}: not on the level page, cannot press 战斗')
        return None

    def battle_ap_short(self):
        """关掉「活动AP不足」。**点取消，绝不点补充** —— 那是拿货币买 AP。"""
        logger.info('[Event battle] out of event AP')
        self.device.click(AP_CANCEL)  # alas-lint: allow - the dialog is matched by the caller and has exactly one safe button
        self.wait_until_disappear(EVENT_AP_SHORT, offset=(20, 20), timeout=5)

    def battle_ap_left(self):
        """
        读顶部那枚「N/5」。

        Returns:
            int: 今天还剩几次。读不出来时返回 0（保守：不再动手）。
        """
        ocr = Ocr(AP_AREA, lang='cnocr', letter=(255, 255, 255),
                  threshold=AP_THRESHOLD, name='EVENT_AP')
        for _ in self.loop(timeout=3):
            text = str(ocr.ocr(self.device.image))
            match = re.search(r'(\d+)\s*/\s*(\d+)', text)
            if match:
                left = int(match.group(1))
                logger.attr('Event AP', f'{left}/{match.group(2)}')
                return left
        logger.warning('Could not read the event AP counter')
        return 0
