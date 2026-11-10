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
点 (200,118) 一点反应都没有，点 (220,181) 却选中了第 4 关）。**开荒阶段不点
列表** —— 游戏自己会把"下一关"选中，开荒顺着它走就行；全通关后扫荡也是打
游戏当前选中的那一关。只有战败降级扫荡时才点选中行的上一行，而且用蓝色光晕
动态定位（`selected_level_row()`），不写死 y（见第 11 条）。

2026-11-10 补的三种画面（用户给了三张真机截图）：

8. **打完最后一关的结果页只剩「返回」(+「重新挑战」)**，整颗「返回」右移约
   90px 到 (914,636)，战败页则左移到 (483,624)。旧判据 `offset=(20,20)`
   只有 0.640 —— `battle_wait_end()` 认不出"这一轮打完了"，整条活动任务
   卡在结果页。现在用 `RESULT_BACK_OFFSET` 这个 4-tuple 非对称搜索区同时
   罩住两个位置，并让 `match()` 的偏移把点击点一起带过去（第 12 条）。

9. **关卡页分两种状态**：有「自动战斗 OFF」开关 = 还没通关、能开荒；没有开关
   且「战斗」胶囊延长变白 = 已经全通关、只剩扫荡。用 `EVENT_AUTO_SWITCH` 和
   胶囊右端亮像素两条**正面**判据区分（`battle_level_state()`），别靠"点了开关
   没反应"反推 —— 那样既慢又会把点击被吞误判成已通关。

10. **GUI 选 Both 时普通已经全通关，要切到挑战战斗**：两个模式共用每天 5 次
    AP，普通没有首通可拿就不该在它身上点「战斗」把 AP 花光。`event_battle_run()`
    只给最后一个模式开 `allow_sweep`，并把没花掉的预算留给后一个模式。

11. **结果页分胜负，战败后不许接着开荒**（用户 2026-11-10 补充的战败截图）：
    DEFEAT 页是一条横贯全屏的红色横幅，红像素占比 0.592（VICTORY 0.176、
    关卡页 0.05），判据 `is_defeat()`。战败说明"这一关打不过"，而**只有通关
    过的关卡才能扫荡**，所以：
    - 开荒阶段一律不扫荡，先按页签顺序把每关往前推；
    - 任何一关战败就结束开荒，转 `battle_sweep()`；
    - 挑战战败回到**普通战斗**扫荡（普通更容易通关，奖励不浪费）；
    - 普通自己也战败时，点选中行的**上一行**（已通关的关）再扫荡，
      反复打它把剩余次数用完，绝不反复硬刚打不过的关。
    选中行靠它那枚亮白+蓝色光晕的数字定位（实测 361~581 个蓝像素，
    其它行 ≤120），不用写死 y —— 列表会随选中项滚动。

12. **「返回」的搜索区绝不能罩到战斗中的「✖ 结束自动战斗」**（11:09 真机）：
    两颗都是米白胶囊 + 图标 + 文字，`EVENT_RESULT_BACK` 的模板分不开它们。
    对称放大 offset 到 (500,60) 时搜索区是 (324,576,1450,750)，把右下角
    (1058,642)-(1182,682) 那颗也圈了进去 —— 开打 7 秒就误报
    "this round is over"，`battle_back()` 点 (1124,654) 关掉自动战斗，
    之后 `wait_until_still` 白等 30 秒、任务卡在战斗画面直到手动停。
    改用 4-tuple `(-350,-20,100,20)`：搜索区 (474,616,1050,710)，模板
    左上最多 x=924，同时罩住 483 / 914 却把 x≥1058 整颗排除。离线合成帧
    复现 1.000 → 0.000。❗推广：**按钮换位置要放大搜索区时，先看清放大后
    会不会把同版式的邻居框进来**，宁可用非对称 4-tuple 也别对称撑满屏幕底部。

13. **三套关卡页布局，「战斗」按钮不是同一个位置**（11:28 真机 + 三张裁图）：
    - 开荒「角色 | 战斗 🎫1 | ⚙OFF 自动战斗」：「战斗」x 772~1055
    - 已通关·无快速战斗「角色 | 战斗 🎫1」：「战斗」x 772~1155
    - 已通关·有快速战斗「角色 | 快速战斗 | 战斗 🎫1」：「战斗」x 970~1155
    旧写死的 (950,647) 只在头两套有效，第三套里正落在「快速战斗」右缘缝隙
    —— 点击被吞，脚本停在关卡页干等结果页，而 `battle_wait_end()` 在单场
    扫荡时一行日志都不打，用户只看到「停了没有下一步」。取三者交集
    x 970~1055 的中点 (1010,650)，三套都落得住、又碰不到开荒页 x≥1068
    的自动战斗开关；再加「关卡面板消失」正面验收 + 最多 3 次补按
    （硬约束 153）和 15 秒心跳日志。
    ❗同理，关卡列表会滚到最后一关：11:28 帧选中「15」在 y≈680，
    `LEVEL_DIGIT_AREA` 下界必须从 620 放到 700，否则退关定位看不到它。

14. **单场扫荡会多一页「布阵页」**（11:41 真机，第三次「卡住」）：
    点「战斗 🎫1」→ 关卡面板消失，但游戏落到 `« TURN.1 »` 编队画面，
    右下角还有一颗 `TURN.1 BATTLE`（约 (1020,618)-(1220,672)），
    **必须再按一次才真开打**；自动连打（`AUTO_START`）会跳过这页，
    所以只有 `battle_single()` 这条单场路会撞上。`battle_wait_end()`
    原来只等结果页，于是从 11:41:51 白等 585 秒，心跳日志打了一屏。
    ❗判据不能只看「关卡面板消失」—— 那只证明离开了关卡页，不证明开打。
    新增 `EVENT_PREP_BATTLE` 模板（布阵页 1.000 / VICTORY 0.133 /
    DEFEAT 0.074 / 关卡页 ≤0），在 `battle_wait_end()` 循环里 2 秒节流
    补按；判别力够高，不会误点结果页的「重新挑战」。
    ❗推广：**自动连打和单场战斗是两条不同的进入路径**，
    不能拿连打的画面序列去推断单场的画面序列。
"""
import re

import numpy as np

from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import crop
from module.browndust.assets import (BATTLE_PANEL, EVENT_AP_SHORT, EVENT_AUTO_STOP,
                                     EVENT_AUTO_SWITCH, EVENT_AUTO_TITLE,
                                     EVENT_PREP_BATTLE, EVENT_RESULT_BACK,
                                     EVENT_TAB_CHALLENGE, EVENT_TAB_NORMAL)
from module.browndust.browndust_ui import page_event
from module.logger import logger
from module.ocr.ocr import Ocr

# 关卡页右下角的「自动战斗」开关。它画的是一颗齿轮 + `OFF`/`ON` 加一行白字，
# 那个 OFF 会随状态变，所以不拿它做模板 —— 只借位置，判据是点完之后弹出来的是
# 次数面板还是 AP 不足。点在空白处（已通关的关卡没有这个开关）游戏不会有任何
# 反应，正好用来区分那三种底部布局。
AUTO_SWITCH = Button(area=(1068, 618, 1252, 676), color=(0, 0, 0),  # alas-lint: allow - the switch has two states and its label sits on the level art, so only the location is used
                     button=(1102, 647, 1102, 647), name='AUTO_SWITCH')

# 关卡页右下那枚「✖ 战斗 🎫1」。❗三套底部布局，「战斗」胶囊位置都不同
# （2026-11-10 三张底部条裁图 + 11:28 真机帧）：
#   开荒（角色 | 战斗 | ⚙OFF 自动战斗）：        x 772~1055
#   已通关·无快速战斗（角色 | 战斗）：            x 772~1155
#   已通关·有快速战斗（角色 | 快速战斗 | 战斗）： x 970~1155
# 旧的 (950,647) 只在头两套有效，第三套里正落在「快速战斗」右缘的缝隙
# 上 —— 点击被吞，脚本停在关卡页死等结果页（用户报「又卡住了」）。取三者
# 交集 x 970~1055 的中点 1010：三套都落在「战斗」胶囊内，又不会碰到开荒页
# x≥1068 的自动战斗开关。纯坐标按钮只用来点，不进 appear()（硬约束 82）。
LEVEL_FIGHT = Button(area=(970, 630, 1040, 670), color=(0, 0, 0),  # alas-lint: allow - the label carries the AP cost, and this is only reached when the auto panel did not open
                     button=(1010, 650, 1010, 650), name='LEVEL_FIGHT')

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
# ❗它**不是固定在 (824,636)** 的，而且「返回」和战斗中的「✖ 结束自动战斗」
#   是同一类米白胶囊，模板本身分不太开。两套结果页布局（硬约束 169 / 172）：
#     VICTORY / 打完最后一关：(914, 636)
#     DEFEAT / 战败页：       (483, 624)
#   右下角战斗中那颗是 (1058,642)-(1182,682)，**绝不能命中它**。
# ❗所以用 4-tuple 非对称 offset —— `Button.match()` 把它直接当
#   (dx1,dy1,dx2,dy2) 加到 area 上，而不是对称放大：area=(824,636,950,690)
#   加 (-350,-20,100,20) 得搜索区 (474,616,1050,710)，模板宽 126 → 左上最多
#   落在 x=924，正好罩住 483 / 914，同时把 x≥1058 那颗整颗排除在视野外；
#   搜索区还全在屏幕内，没有越界补黑。
#   2026-11-10 11:09 真机事故：对称 offset=(500,60) 的搜索区是
#   (324,576,1450,750)，把「结束自动战斗」圈了进去 —— 开打 7 秒
#   `battle_wait_end()` 就报 "this round is over"，`battle_back()` 点
#   (1124,654) 关掉自动战斗，画面再也回不到关卡页。合成帧复现：旧 offset
#   **1.000@(1058,636)**、新 offset **0.000**。
#   四张真机帧实测：VICTORY 0.980@(914,636)、DEFEAT 0.938@(483,624)、
#   关卡页最高 0.588 不假阳性。❗`(200,30)` 也不行 —— 战败页会误命中
#   旁边的「重新挑战」(0.918)，点下去等于再打一次打不过的关。
# 命中后 `Button.button` 会一起偏移，直接 `device.click(EVENT_RESULT_BACK)`
# 就点在真实位置上，**不要再写死坐标**（旧的 (886,669) 会落在统计圆上）。
RESULT_BACK_OFFSET = (-350, -20, 100, 20)

# 战败判据：DEFEAT 结果页有一条横贯全屏的红色横幅 (y 285~380)，白字「DEFEAT」。
# 用户给的战败截图是 1080x608 的缩放图，插值过的文字不适合做模板，所以用红色
# 像素占比：战败 0.592 / VICTORY 0.176 / 关卡页 0.050~0.053，阈值 0.4。
DEFEAT_BANNER = (0, 285, 1280, 380)
DEFEAT_RED_RATIO = 0.4

# 关卡列表里选中关的数字是亮白 + 蓝色光晕，未选中的是灰色半透明。
# (190,60,245,700) 只框数字，避开右侧三颗星；40px 滑窗里选中行有 361~593
# 个蓝像素，其它行 0~120。用它定位「当前选中行」，往上一行就是已通关的
# 前一关 —— 战败后不能反复硬刚打不过的关。实测行距 80px。
# ❗下界必须到 700：列表会滚到最后一关，11:28 真机帧里选中「15」在 y≈680，
#   旧值 620 完全看不到它（blue=0），退关定位会白等 10 秒然后收工。
LEVEL_DIGIT_AREA = (190, 60, 245, 700)
LEVEL_ROW_WINDOW = 40
LEVEL_DIGIT_MIN_BLUE = 200
LEVEL_ROW_STEP = 80
LEVEL_LIST_TOP = 110
LEVEL_ROW_CLICK_X = 220
# 退到前一关最多补按 10 秒（2 秒一按，5 次以内，不会踩 click_record）。
LEVEL_FALLBACK_TIMEOUT = 10

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
# 点「自动战斗」之后等次数面板。面板是淡入的，`wait_until_appear` 还要求
# settle 连续 2 帧；2026-11-10 11:09 真机第一次点击后 3 秒整超时、脚本又补按了
# 一次开关（面板其实已经开了，紧接着 OCR 就读到「战斗 1」）。给 6 秒，避免
# 在开着的面板外面再按一下 —— 那一按可能落在遮罩上把面板关掉。
AUTO_PANEL_TIMEOUT = 6
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


def is_defeat(image):
    """
    Whether the result page shows DEFEAT.

    The DEFEAT page has a full-width red banner. VICTORY has a dark banner with
    a bit of red art in it, so the threshold sits well above that.

    Args:
        image (np.ndarray): Full 1280x720 RGB screenshot.

    Returns:
        bool:
    """
    patch = crop(image, DEFEAT_BANNER, copy=False).astype(np.int16)
    ratio = ((patch[:, :, 0] > 120) & (patch[:, :, 1] < 90)
             & (patch[:, :, 2] < 90)).mean()
    return ratio > DEFEAT_RED_RATIO


def selected_level_row(image):
    """
    Locate the selected row of the level list by its blue-glowing digit.

    Only the selected level draws its number in bright white with a blue halo;
    the others are translucent grey. A sliding window over the digit column
    finds the halo. The list scrolls with the selection, so no fixed y is used.

    Args:
        image (np.ndarray): Full 1280x720 RGB screenshot.

    Returns:
        int, None: Centre y of the selected digit, None on a transition frame.
    """
    patch = crop(image, LEVEL_DIGIT_AREA, copy=False).astype(np.int16)
    blue = ((patch[:, :, 2] - patch[:, :, 0] > 25)
            & (patch[:, :, 2] > 140))
    top, window = LEVEL_DIGIT_AREA[1], LEVEL_ROW_WINDOW
    best, best_y = 0, None
    for offset in range(0, patch.shape[0] - window + 1, 10):
        count = int(blue[offset:offset + window].sum())
        if count > best:
            best, best_y = count, top + offset + window // 2
    if best < LEVEL_DIGIT_MIN_BLUE:
        return None
    return best_y


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
        先开荒，开荒失败就去扫荡（用户 2026-11-10 定的总逻辑）。

        阶段一按页签顺序推进，非最后一个模式不扫荡，把共享的 5 次 AP 留给
        后面的开荒；阶段二只在**战败**时进：回到普通战斗扫荡，普通自己也
        战败就在同一页退到前一关再扫荡。绝不反复硬刚打不过的关。

        Pages:
            in: page_event
            out: page_event
        """
        self.ui_goto(page_event)
        pages = self.battle_pages()
        if not pages:
            return
        # 只开一个模式的时候把今天的次数全给它；两个都开就各按 `Times` 分，
        # 否则先打的那个会把 AP 吃光，后一个一场都打不了。
        budget = int(self.config.BrowndustEvent_Times) if len(pages) > 1 else 5
        defeat_index = None
        for index, (tab, name) in enumerate(pages):
            logger.hr(name, level=2)
            if not self.battle_enter(tab, name):
                continue
            # ❗普通已经全通关时，不要在它身上点「战斗」把共享 AP 花掉 ——
            #   GUI 选了 Both 就该切到挑战继续开荒（2026-11-10 真机）。
            #   只有最后一个模式允许在开荒阶段顺手扫荡。
            allow_sweep = index == len(pages) - 1
            used, outcome = self.battle_page(name, budget, allow_sweep=allow_sweep)
            budget = max(0, budget - used)
            if outcome == 'defeat':
                defeat_index = index
                break
            if used == 0 and index < len(pages) - 1:
                # 前一个模式一场没花（全通关跳过），共享 AP 全留给后一个模式开荒。
                budget = 5

        if defeat_index is None:
            # 全部开荒完成（或本来就全通关），最后一个模式已经把 AP 花掉了。
            return

        # 挑战战败 → 回普通战斗扫荡；普通自己也战败 → 就在这一页退到前一关。
        tab, name = pages[0]
        logger.hr(f'{name} fallback sweep', level=2)
        if defeat_index != 0 and not self.battle_enter(tab, name):
            logger.warning(f'[Event battle] cannot go back to {name} for sweeping')
            return
        self.battle_sweep(name, budget)
        # `battle_sweep()` 打完停在关卡列表上，回活动页交给外层下一步的 `ui_goto`。

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
        开荒阶段：把这一页的次数花在往前推关卡上，全通关了才顺手扫荡。

        战败是**硬停止**：这一关没通关就不能扫荡它，继续开荒只会反复打一场
        打不过的仗。战败结果交给 `event_battle_run()` 转扫荡阶段。

        Pages:
            in: page_event_battle
            out: page_event_battle，停在关卡列表上

        Args:
            name (str): 页签名，只用来打日志。
            budget (int): 这一页最多打几场（还要再过一遍剩下的 AP）。
            allow_sweep (bool): 全通关后要不要扫荡。Both 的普通战斗传 False，
                共享的 5 次 AP 才能留给挑战开荒。

        Returns:
            tuple: (int, str) 打了几场、'done' / 'defeat' / 'timeout'。
        """
        fought = 0
        outcome = 'done'
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
                    done, result = self.battle_single(name)
                else:
                    done, result = self.battle_auto(name, min(budget, ap_left), ap_left)

                if result == 'defeat':
                    # 连打设了 N 场但可能第一场就败了，实际消耗量读不出来。
                    # 按 1 场记账，剩下的次数交给 battle_ap_left() 实时读数，
                    # 宁可少算也不要漏掉还能扫荡的次数（用户：别浪费次数）。
                    logger.info(f'[Event battle] {name}: frontier fight lost, '
                                'stop clearing, switch to sweep')
                    fought += 1
                    outcome = 'defeat'
                    break
                if not done:
                    # 0 = 游戏说没 AP / 面板没打开 / 连「战斗」都点不动。
                    # 都得停下，不然记账不减、预算不减就成了空转。
                    logger.info(f'[Event battle] {name}: nothing more to fight')
                    break

                fought += done
                budget -= done
        else:
            logger.warning(f'The {name} did not finish in time')
            outcome = 'timeout'

        logger.info(f'[Event battle] {name}: {fought} fight(s), {outcome}')
        return fought, outcome

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
            tuple: (int, str) 设定了几场（0 = 没打成）、
                'victory' / 'defeat' / 'timeout' / 'ap_short' / 'panel_failed'。
        """
        for _ in range(3):
            self.device.click(AUTO_SWITCH)  # alas-lint: allow - battle_level_state() matched the switch, the panel below is the proof
            if self.wait_until_appear(EVENT_AUTO_TITLE, offset=(20, 20),
                                      timeout=AUTO_PANEL_TIMEOUT, settle=2):
                break
            if self.appear(EVENT_AP_SHORT, offset=(20, 20)):
                self.battle_ap_short()
                return 0, 'ap_short'
        else:
            logger.warning('[Event battle] the 自动战斗 panel did not open, stop')
            return 0, 'panel_failed'

        wanted = self.battle_set_times(times, ap_left)
        logger.info(f'[Event battle] {name}: auto fight x{wanted}')
        self.device.click(AUTO_START)  # alas-lint: allow - the panel title is matched above and the count was read off this very button
        result = self.battle_wait_end()
        self.battle_back()
        return wanted, result

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

        结果页右下角在连打中是「✖ 结束自动战斗」，打完之后换成「返回」。两颗
        胶囊长得很像，但**不能靠 `EVENT_AUTO_STOP` 反推状态**（它在结果页也可能
        命中）：判据是 `EVENT_RESULT_BACK` 在 `RESULT_BACK_OFFSET` 这个精确的
        非对称搜索区里命中 —— 该搜索区几何上排除了右下角 (1058,642) 那颗，
        所以战斗中不会被误判成"打完了"（模块 docstring 第 12 条）。

        看见「返回」之后还要分胜负：DEFEAT 页多一条红色横幅（`is_defeat()`），
        战败意味着这一关没通关、不能扫荡，上层必须停止开荒转去扫荡。

        ❗单场扫荡还多一页：点「战斗 🎫1」之后先进**布阵页**
        （`« TURN.1 »` + 右下 `TURN.1 BATTLE`），要再按一次才真开打。
        看见 `EVENT_PREP_BATTLE` 就按、按到页面消失为止，2 秒节流；
        自动连打跳过这页，所以只影响单场路（模块 docstring 第 14 条）。

        商店客户端什么时候想连就什么时候连，「支付失败 / GetProducts」弹窗开打
        那一刻最常见（2026-11-04 实机：按完「战斗 N」60 秒后弹出来，把开打挡住，
        面板原样停在弹窗后面）。所以这个循环里还要做两件事：先关弹窗；关完之后
        面板若还亮着，就是战斗没被接受，补按一次「战斗 N」——补按有 5 秒节流，
        正常开打的转场动画不会被判成"没打上"。

        Returns:
            str: 'victory' / 'defeat' / 'timeout'。
        """
        running = False
        # 面板连续可见的计时。进循环就启动：battle_auto 刚按完「战斗 N」面板
        # 还有一瞬在场上，靠它挡住补按；真正被弹窗挡住时面板会一直亮，5 秒后补。
        panel = Timer(EVENT_PANEL_REPRESS).start()
        # 单场扫荡既没有「✖ 结束自动战斗」也没有次数面板，等待期间一行日志都
        # 不会打；一场战斗要 70 秒（11:27 真机），用户会以为脚本卡死而手动停。
        # 每 15 秒报一次「还在等」，把"正常等待"和"真卡住"分开。
        heartbeat = Timer(15).start()
        waited = 0
        # 布阵页那颗 BATTLE 的补按节流（点一下没反应不等于失败，硬约束 153）。
        prep_press = Timer(2).start()
        for _ in self.loop(timeout=BATTLE_TIMEOUT):
            # 连打四场要好几分钟，中间一个按钮都不点。框架的看门狗把"60 秒没
            # 点击"当成卡死 —— 2026-10-30 实测，第 60 秒准时掐在连打中间，而
            # 那时游戏正打得好好的。这里等的是游戏自己打完，先说清楚（硬约束 13）；
            # 真卡住由上面的 BATTLE_TIMEOUT 收场。
            self.device.stuck_record_clear()
            if heartbeat.reached():
                waited += 15
                logger.info(f'[Event battle] still fighting, waited ~{waited}s')
                heartbeat.reset()
            # 「支付失败」不归结果页管，先认它：不关掉，返回键永远出不来。
            if self.handle_payment_error():
                panel.reset()
                continue
            # ❗单场扫荡点「战斗」后先落到**布阵页**（« TURN.1 » + 右下
            #   「TURN.1 BATTLE」），必须再按一次才真开打；自动连打不走这页。
            #   2026-11-10 11:41 真机就卡在这里，`battle_wait_end()` 白等
            #   585 秒。模板在布阵页 1.000、结果页 ≤0.133、关卡页 ≤0，
            #   不会误点结果页的「重新挑战」。
            if self.appear(EVENT_PREP_BATTLE, offset=(20, 20)):
                if prep_press.reached():
                    self.device.click(EVENT_PREP_BATTLE)  # alas-lint: allow - the TURN.1 BATTLE template was matched on this very frame
                    logger.info('[Event battle] formation page, press BATTLE')
                    prep_press.reset()
                continue
            # 「返回」有两套位置（VICTORY 右移 / DEFEAT 左移），但搜索区
            # 绝不能罩到右下角「✖ 结束自动战斗」，否则开打几秒就误判结束。
            if self.appear(EVENT_RESULT_BACK, offset=RESULT_BACK_OFFSET):
                if is_defeat(self.device.image):
                    logger.info('[Event battle] this round ended in DEFEAT')
                    return 'defeat'
                logger.info('[Event battle] this round is over')
                return 'victory'
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
        return 'timeout'

    def battle_back(self):
        """
        结果页点「返回」，等关卡列表回来。

        结果页有两套布局：VICTORY / 打完最后一关的「返回」右移到 (914,636)，
        DEFEAT 的「返回」左移到 (483,624)，旁边还有一枚很像的「重新挑战」。
        点的是模板匹配后的偏移位置，不是写死的坐标（见 `RESULT_BACK_OFFSET`）。

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
          能打到的最后一关；战力不足时玩家会自己选上一关）。这里不点左侧关卡
          列表：列表会随选中项滚动、写死的 y 靠不住；战败要退到前一关由调用方
          `battle_sweep()` 处理。

        这条路走完一定回到关卡列表，下一场由 `battle_page()` 的循环再来一次 ——
        每次都要重载一遍游戏（十几秒），但一天只在这条路上走几次，换来的是
        "一轮只做一件事"，出问题容易从日志里看出来。

        Returns:
            tuple: (int, str) 打了几场（0 或 1）、结果代码。
        """
        logger.info(f'[Event battle] {name}: single fight')
        # 检查点用关卡详情面板，不用那枚按钮 —— `LEVEL_FIGHT` 是纯坐标，没有模板，
        # 进 `appear()` 会在加载那一刻拿 None 去开图片（硬约束 82）。
        if self.wait_until_appear(BATTLE_PANEL, offset=(20, 20), timeout=3):
            # ❗点一下没反应不等于失败（硬约束 153）：按钮位置随关卡状态变，
            #   转场动画还会吞点击。用「关卡面板消失」作正面验收，最多补按 3 次
            #   （每次给 6 秒让它离场）。不验收就进 `battle_wait_end()` 的话，
            #   点击被吞时会停在关卡页干等 900 秒 —— 11:28 真机就卡在这里。
            for attempt in range(3):
                self.device.click(LEVEL_FIGHT)  # alas-lint: allow - the level panel was matched right above, the panel leaving is the proof it worked
                if self.wait_until_disappear(BATTLE_PANEL, offset=(20, 20),
                                            timeout=6, settle=2):
                    break
                logger.warning(f'[Event battle] {name}: 战斗 tap #{attempt + 1} '
                               'had no effect, retry')
            else:
                logger.warning(f'[Event battle] {name}: 战斗 was not accepted, stop')
                return 0, 'fight_not_accepted'
            if self.appear(EVENT_AP_SHORT, offset=(20, 20)):
                # 这一关也点得动，但 AP 不够 —— 今天到此为止。
                self.battle_ap_short()
                return 0, 'ap_short'
            result = self.battle_wait_end()
            self.battle_back()
            return 1, result

        logger.warning(f'[Event battle] {name}: not on the level page, cannot press 战斗')
        return 0, 'not_on_page'

    def battle_sweep(self, name, budget):
        """
        开荒失败后的扫荡：只打已通关的关卡，把剩下的次数用完。

        战败后游戏仍选中打不过的那一关（frontier），先点它的上一行；列表随
        选中项滚动，所以每帧重新定位，并用 `battle_level_state()` 变成
        'cleared' 作为**正面**验收（R5）。已经是最上面一关、或 10 秒内选不中
        前一关，就收工 —— 宁可不打，也不把次数耗在打不过的关上。

        Pages:
            in: page_event_battle
            out: page_event_battle，停在关卡列表上

        Args:
            name (str): 页签名，只用来打日志。
            budget (int): 最多再打几场；实际剩余由 `battle_ap_left()` 兜底。

        Returns:
            int: 扫荡了几场。
        """
        swept = 0
        press = Timer(2).start()
        fallback = None
        for _ in self.loop(timeout=BATTLE_TIMEOUT):
            if budget <= 0:
                logger.info(f'[Event battle] {name}: sweep budget used up')
                break
            if self.appear(BATTLE_PANEL, offset=(20, 20)):
                ap_left = self.battle_ap_left()
                if ap_left == 0:
                    logger.info(f'[Event battle] {name}: no AP left today')
                    break
                state = self.battle_level_state()
                if state == 'cleared':
                    done, result = self.battle_single(name)
                    if result == 'defeat' or not done:
                        logger.info(f'[Event battle] {name}: sweep stopped')
                        break
                    swept += done
                    budget -= done
                elif state == 'frontier':
                    if fallback is None:
                        fallback = Timer(LEVEL_FALLBACK_TIMEOUT).start()
                    if fallback.reached():
                        logger.warning('[Event battle] no cleared level to fall back to, stop')
                        break
                    if not self.battle_select_previous(press):
                        logger.info('[Event battle] already at the first level, stop')
                        break
                # None: transition frame, do nothing and wait for the next one
        else:
            logger.warning(f'The {name} sweep did not finish in time')

        logger.info(f'[Event battle] {name}: {swept} sweep(s)')
        return swept

    def battle_select_previous(self, press):
        """
        一帧一动作：点当前选中关的上一行（那是已通关的关，才能扫荡）。

        这是 `battle_sweep()` 的 handler，不自带状态循环（R7/R16）。选中行靠
        蓝色光晕定位，点完由外层的 `battle_level_state()` 验收；没变就按 2 秒
        节流补点 —— 动画期间的点击会被吞，点一下没反应不等于失败（40/153）。

        Args:
            press (Timer): 补按节流计时器。

        Returns:
            bool: False = 已经是最上面一关，没有可退的已通关关卡。
        """
        row = selected_level_row(self.device.image)
        if row is None:
            return True
        target = row - LEVEL_ROW_STEP
        if target < LEVEL_LIST_TOP:
            return False
        if press.reached():
            previous = Button(
                area=(LEVEL_ROW_CLICK_X - 20, target - 20,
                      LEVEL_ROW_CLICK_X + 20, target + 20),
                color=(0, 0, 0),
                button=(LEVEL_ROW_CLICK_X, target, LEVEL_ROW_CLICK_X, target),
                name='LEVEL_PREVIOUS_ROW')
            # 纯坐标 Button 没有 file=，只用来点，绝不进 appear()（硬约束 82）。
            self.device.click(previous)  # alas-lint: allow - BATTLE_PANEL and the glowing selected digit are both matched on this frame
            press.reset()
        return True

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
