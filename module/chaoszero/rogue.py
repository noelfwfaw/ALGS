# -*- coding: utf-8 -*-
"""卡厄思梦境：肉鸽（卡厄思）自动刷档 —— 骨架版。

入口链路（2026-11-14 实机逐页走通，设备 16448，第 6 階段 霧之城市）：

    主界面右侧竖排「卡厄思」(1215,322)            ← ROGUE_MENU
      → 卡厄思页：左卡「卡厄思顯現」/ 右卡「零號系統」  ← ROGUE_MODE_ENTRY
      → 卡厄思顯現页：世界列表（五颗星球 + 右下「卡厄思規模」）← ROGUE_WORLD_LIST
      → 世界详情（右上「顯現」+ 右下紫色 `進入`）    ← ROGUE_WORLD_ENTER
      → 配置隊伍（`進入` 在 (1200,657)）            ← ROGUE_TEAM_ENTER
      → 确认框「確認準備戰鬥說明」→ 橙色 `進入` (885,600) ← DIALOG_ENTER
      → 黑屏加载约 8 秒 → 命运剧情 → 命运三卡 → 卡牌奖励 → 装备 → 地图
      → 若干节点（战斗 / 事件 / 灵光 / 宝箱 / 航点 / 商店 / 营地）
      → 中途結算（航点触发）→ 最终結算（本版未走到，见文件末尾 TODO）

❗这条链是**五页**，中间三页都没有橙色主按钮，所以入口不能像 v1 那样只等
`rogue_primary_point()`（会一直等到超时）。现在每页各有一个模板判据，逐个点过去；
模板的自检分数写在 `dev_tools/probe_rogue_crop.py` 的输出里（同页 1.000，
别的页 ≤0.72，默认 0.85 阈值两边都留得下余量）。

**战斗是自动的**（2026-11-13 实测，这条推翻了 P0-walk.md §8 的结论）：
游戏自己出牌，脚本在确认战斗页后检测并开启自动战斗、倍速，再等待结束。

判据全部按 1280x720 实机帧量的颜色量，不用模板：
客户端每期会换卡面立绘（灵光/命运/奖励的卡图全换），模板只会把"换了一期"
变成"认不出来"（硬约束 195）。这里只数色相与像素数，阈值都写了实测值。

❗左上角那条**绿血条每一页都有**（地图/事件/奖励都在），不能当战斗判据 ——
战斗页独有的只有底部「回合 x/10」+ EP 条那一带的蓝青色（实测 946 蓝 / 其余 0）。
"""

import collections
import hashlib
import json
import os
import re

import cv2
import numpy as np
from filelock import FileLock, Timeout

from deploy.atomic import atomic_read_bytes, atomic_write
from module.base.button import Button
from module.base.timer import Timer
from module.chaoszero import rogue_cards, rogue_equipment, rogue_events, rogue_fate, rogue_route
from module.chaoszero.assets import (DIALOG_ENTER,
                                     ROGUE_BATTLE_AUTO_OFF, ROGUE_BATTLE_SPEED_OFF,
                                     ROGUE_CHECKPOINT,
                                     ROGUE_BATTLE_COMPLETE,
                                     ROGUE_CARD_REWARD,
                                     ROGUE_ACQUIRE,
                                     ROGUE_FLASH_DETAIL,
                                     ROGUE_COPY_TITLE2,
                                     ROGUE_BEACON_PROMPT,
                                     ROGUE_BEACON_PROMPT2,
                                     ROGUE_BEACON_TITLE,
                                     ROGUE_CLICK_CLOSE,
                                     ROGUE_CONSULT, ROGUE_CURE_APPROVE,
                                     ROGUE_CURE_NONE,
                                     ROGUE_COPY, ROGUE_COPY_CARD_TITLE,
                                     ROGUE_FLASH_CARD_TITLE,
                                     ROGUE_GOD_CARD_TITLE,
                                    ROGUE_DECK, ROGUE_DETAIL,
                                     ROGUE_DICE, ROGUE_DICE_FAIL, ROGUE_DICE_TAP, ROGUE_DREAM_NOTICE,
                                     ROGUE_DREAM_OFF, ROGUE_DREAM_OK,
                                     ROGUE_DREAM_ON, ROGUE_EQUIP, ROGUE_EXPLORE_RESULT, ROGUE_FATE,
                                     ROGUE_FLASH,
                                     ROGUE_GOD, ROGUE_HERALD, ROGUE_INFO_MENU,
                                     ROGUE_ITEM,
                                     ROGUE_MAP_BTN, ROGUE_MEDITATE, ROGUE_MEDITATE_OFF,
                                     ROGUE_MEMBER, ROGUE_MENU,
                                     ROGUE_MODE_ENTRY, ROGUE_MODAL,
                                     ROGUE_PANEL,
                                     ROGUE_PROMPT, ROGUE_PREVIEW, ROGUE_REST, ROGUE_REST_SHOP,
                                     ROGUE_REMOVE, ROGUE_REMOVE_DONE, ROGUE_REMOVE_SKIP, ROGUE_RESUME,
                                    ROGUE_TRANSFORM,
                                     ROGUE_RETREAT,
                                     ROGUE_RETREAT_TITLE, ROGUE_REWARD_LEVEL, ROGUE_SAVE_TITLE, ROGUE_STORY,
                                     ROGUE_SHOP_REMOVE,
                                     ROGUE_TEAM_ENTER, ROGUE_TREASURE_CARD, ROGUE_TURN,
                                     ROGUE_WORLD_ENTER, ROGUE_WORLD_JIANGLIN,
                                     ROGUE_WORLD_LANHU, ROGUE_WORLD_LIST,
                                     ROGUE_WORLD_SHENPAN, ROGUE_WORLD_SHUANG,
                                     ROGUE_WORLD_WUZHI, ROGUE_ZOOM_IN,
                                     ROGUE_ZOOM_OUT, RESULT_CONFIRM, TEAM_TITLE)
from module.chaoszero.chaoszero_ui import CHAOSZERO_WAKE, ChaoszeroUI
from module.chaoszero.page import page_main
from module.config.utils import filepath_config
from module.exception import RequestHumanTakeover, TaskFailed
from module.log_retention import prune_diagnostics
from module.logger import logger
from module.ocr.ocr import Ocr

# ==================== 判据区（1280x720 实机量） ====================

# 肉鸽自动按钮与演算模式位置不同，不能共用 BATTLE_AUTO 点位。
BATTLE_SETTINGS = (
    ('speed', ROGUE_BATTLE_SPEED_OFF, (1148, 38)),
    ('auto', ROGUE_BATTLE_AUTO_OFF, (1064, 38)),
)
# 用户开/关截图：金色 111/129 vs 0/0，白色 0/0 vs 262/200。
BATTLE_SETTING_GOLD = 40
BATTLE_SETTING_WHITE = 80
BATTLE_SETTING_TRIES = 3

# 橙色主按钮：`確認` / `繼續進行` / `獲得` / `進入` 都画在这条带子上（实测 247x63，
# bbox (1013,633)-(1260,696)，中心 (1133,659)）。限定宽高是关键：事件选项卡、
# 卡面边框也在附近，但不是这个尺寸。
PRIMARY_AREA = (1013, 633, 1260, 696)
PRIMARY_WIDTH = (180, 280)
PRIMARY_HEIGHT = (45, 80)

# 底部那颗**白色**圆角按钮：`跳過` / `下一步`。删卡页、掷骰结果页、安全区域、
# 战斗奖励页都有它，位置比橙色主按钮靠左、靠上一点。
# 实测：奖励页 `跳過` (756,633)-(998,687) 242x54；掷骰页 `下一步` (651,620)-(1041,676)
# 390x56，中心 (847,647)。
SECONDARY_AREA = (620, 600, 1270, 700)
SECONDARY_WIDTH = (150, 450)
SECONDARY_HEIGHT = (40, 80)
# 实心程度与亮度：真按钮 fill 0.75~0.94 / brightness 200~244，选项卡上的亮块
# fill 0.04~0.05 / brightness 30~43（173 帧实测）。
SECONDARY_FILL = 0.6
SECONDARY_LIGHT = 180

# 二次确认对话框的橙色 `確認`：`跳過後將無法獲得獎勵` / 神闪提示 都放在画面中部
# (849,454)，尺寸 390x56 —— 不在底部主按钮那条带子上，所以单独找。
# 用同一个橙色系，g 的下限放宽到 105：这颗按钮实测 RGB (239,120,41)，
# 主按钮的 g>120 会差一点判空。173 帧里只有对话框那一帧命中，无假阳。
DIALOG_AREA = (640, 420, 1060, 510)
DIALOG_WIDTH = (250, 460)
DIALOG_HEIGHT = (40, 90)

# 「跳過 / 下一步」那颗白胶囊：位置在右下，随页面在 x 847~1240 之间浮动，
# 所以盒子放宽到 (620,600,1270,700)。❗判据必须验"实心 + 够亮"：事件页的三张
# 选项卡横在同一个区域里，卡面上的亮块也是白的，但填充率只有 0.04~0.05、
# 亮度 30~43；真按钮是实心圆角矩形，填充率 0.75~0.94、亮度 200~244（173 帧实测）。
# 事件页 / 战斗页右下角那颗粉色 ✕ 圈（安全区、商店、剧情页都没有）。
CHOICE_AREA = (1150, 545, 1265, 655)
CHOICE_PINK = 150

# 地图页的判据是左下那块**路线小地图面板**（见 rogue_map_appear），这一组
# 颜色常量只留下"点数"用途，别再拿去当页面判据。
NODE_AREA = (560, 40, 1268, 640)
MAP_CYAN = 6000

# 地图上点节点的总尝试次数上限。到顶就收工，别让框架的点击看门狗去重启客户端。
# ❗框架的看门狗是"15 次点击里 12 次同名就抛 GameTooManyClickError 并重启客户端"
# （2026-11-14 00:31 实测踩中），所以这里必须留在 12 以下。
MAP_TRIES = 6
NODE_ENTRY_WAIT = 4

# 层末只剩 Boss 平台时用的兜底点击点：平台本体（右列 380 行），立卡读不出来时点它
NODE_FALLBACK = (1020, 380)

# 路线读取：小地图面板右上角那颗 ⊕ 打开整屏 2D 预览，读完点左下角放大镜胶囊回 3D。
# 2026-11-14 20:02 实测：⊕ 点开是整屏预览，左下角是一枚带放大镜的胶囊（模板
# `ROGUE_PREVIEW`：预览帧 1.000，3D 地图帧 0.23~0.24）；预览刚打开时会有半秒
# 淡入，立刻截图会读到 0 个节点 —— 必须先等 `ROGUE_PREVIEW` 出现再读。
# 左下小地图面板右上角那颗圆圈 ⊕。实测 2026-11-15 17:38 真机帧（mu_map_camp.png，
# 面板展开状态）：圆心 (487, 470)，半径约 20。原来写的 (509, 470) **x 偏了 22px**，
# 正好落在图标右边缘外面 —— 这就是日志里「looks collapsed → 点展开 → 再点 ⊕ →
# 两次 wait_until_appear 超时、一次读图白等 22 秒」的真身。
ROUTE_OPEN_POINT = (487, 470)
ROUTE_CLOSE_POINT = (95, 672)
ROUTE_OPEN_TIMEOUT = 6
# 整张 2D 图比一屏宽，但**不要回卷到最左端**：打开预览时画面就停在队伍当前所在的
# 图钉处，左边已经走过的节点全是暗的，色相判据读不到（2026-11-14 21:12 就是回卷
# 到左侧空白区，连读 8 屏 0 节点，然后开/关预览循环了 8 分钟）。所以从当前位置
# 一路往右拖，每屏读一遍、按重合节点估位移拼起来。
# ❗拖动距离必须是**列间距的整数倍**（`rogue_route.TIER_SPACING = 164`）。
# 原来是 1100→400 = 700px，而 700/164 = 4.27 列 —— 位移永远不是 164 的整数倍，
# `estimate_shift()`（只在 164 的整数倍里挑）必然返回 None，拼图于是每屏错位，
# 同一批节点被反复当成新的：2026-11-15 16:52 一屏 18 个却累加到 139 个。
# 改成 656px = 4 列，位移可预测，估算也能对上。
ROUTE_SCROLL = ((1100, 400), (444, 400))
ROUTE_SCROLL_TIERS = 4
# 最多拖几屏。实测每屏稳定读 18 个节点、往右拖新增 4~5 个（2026-11-15 16:51），
# 原来 8 屏只累到 48 个就被上限截断；一张面走 16 个节点，整图比这宽得多。
# 拖不动时循环自己有"连续两屏没位移就收工"的保护，所以给大一点没有副作用。
# 只读**当前一屏**，不拖动拼图。
#
# ❗拖动拼图做不到稳定（2026-11-15 反复试）：`estimate_shift` 靠"两屏节点重叠"
# 估位移，但节点是等距网格，164/328/492 都能对上（实测三轮投票 164:13 / 328:9 /
# 492:7），无法区分；固定按 164 推进又会出现"拖动没生效但 offset 照加"，
# 拼出 30 层、gap 变成 81/73/92 的假地图（123 个重复节点）。
#
# 改用"分段读"：一屏能看到 7~8 列，一面固定 16 步 → 一面读 2 次正好覆盖。
# 计划用完就重读，不拼图也就没有拼图误差。
ROUTE_SCANS = 1
# 一张图读完就重复用，不每格都重读；用了这么多个节点之后重读一次。
# 读 2D 路线失败时最多重试几次。
ROUTE_RETRY = 2

# ❗一局只读两次（用户 2026-11-15 定义）：**一面 = 一张完整地图 + 末尾一个 BOSS**，
# 第一面打完进「核心」是第二张地图。所以只在"第一面开局"和"第二面开局"各读一次。
# 计划只覆盖当前预览里看得到的节点，超出后按实机可走节点评分。
# （曾经有过 `ROUTE_REFRESH_STEPS=6` 按步数重读，实测一局读了 4 次，违背"只读两次"，已删。）
ROUTE_READS = 2

# 认不出的页面按"选卡页"处理时的上限。框架的看门狗是 12 次，这里必须比它小。
CARD_TRIES = 4

# 地图有两个视角（2026-11-14 01:1x 实测）：
#   * 3D 视角：右下有 3D 盘面，点**盘面本体**就走（点盘面左侧那枚青色 ▶ 只是播动画，不走）；
#     左下角按钮是 ⊙（缩小 → 进 2D 预览）。
#   * 2D 全图：**只能预览，不能移动**（用户确认）。左下角按钮变成 ⊕（放大 → 回 3D）。
# 判据就用左下那颗按钮的两个形态（同一 `area`，图标不同，173 帧分得很干净）。
ZOOM_POINT = (100, 669)

# 三种卡位（都要按卡片中心点，别按卡面边缘）：
# 命运三卡贴着屏幕下缘（P0-walk §3.2）；灵光/塔罗在画面中部（§4、§5）。
# 下缘卡位往中间挪了一点：只剩两张卡时整排会居中重排，卡 1 的左沿实测到了 320
# （2026-11-13 23:2x 洞窟第三轮），原来点 295 会落到卡外面。
# 战斗中的灵光一闪三选一：同一张卡的三张不同闪形态，横向排在中部（实测卡面
# y 170~595，中心取 400）。这页**没有跳过**，必须选一张，否则战斗不会继续。
FLASH_POINTS = ((320, 400), (640, 400), (960, 400))
# 同一页上三张卡的列范围（含卡框），用来找神闪那张的品红描述区。三张卡宽度
# 实测 280/285/295，x 依次 180~460 / 495~780 / 810~1105。
FLASH_READS = 3
GOD_COLUMNS = ((180, 460), (495, 780), (810, 1105))
GOD_DESC = (350, 560)
GOD_MAGENTA_MIN = 0.02
GOD_MAGENTA_RATIO = 3.0
# 底部 `靈光一閃：<神名>` 这条标签：每个神的页面背景都不一样，模板一比就掉到
# 0.1~0.2（2026-11-15 00:50 金框维托那页卡死），所以这一行改用 OCR 判：
# 实测四页分别读出 `光一：維托` / `霾光一阴:尼希隆` / `霾光一阴:赛克瑞德` /
# `霾光阴凯阑肯`，非灵光页只读出 `|` 或空。要求同时含 `光` 和 `一/阴/閃`。
GOD_TEXT_AREA = (470, 612, 820, 662)
GOD_TEXT_THRESHOLD = 150
CARD_POINTS = ((325, 415), (640, 415), (958, 415))
TAROT_POINTS = ((322, 330), (640, 330), (958, 330))

# 底部选项卡下方的白色小圆点：每张卡正中一颗，点击点 = 圆点上方 70px。
# 紫色主按钮（层末 `探索結果` 的 `下一步`、整局结算的 `確認`）：bbox 999,634 246x54
PURPLE_AREA = (950, 600, 1270, 700)
PURPLE_WIDTH = (200, 300)
PURPLE_HEIGHT = (40, 75)
PURPLE_FILL = 0.7

# 治疗中心（角色崩溃后必须先治，一天只会崩一次）
# ❗真正的入口不在方舟都市：角色崩溃时游戏**自己**弹下面两种整屏页，页面上有一颗
# 绿色 `治療中心` 胶囊，点它就直接进 `諮商紀錄`（2026-11-15 实机逐步确认）：
#   ① `觸發精神異常`：绿色胶囊在 (740~990, 632~690)，右边紫色 `下一步`(1002~1253)
#   ② `夢境模式` 说明页（崩到三个人全崩时）：绿色胶囊在 (17~263, 632~690)，
#      右边紫色 `確認`(1005~1255)
# 所以判据是"底部有大块绿色 + 右侧有大块紫色"，绿色胶囊位置不固定，用色块质心点它。
CRASH_GREEN_AREA = (0, 628, 1270, 700)
CRASH_GREEN_MIN = 6000
CRASH_GREEN_WIDTH = (180, 340)
CRASH_GREEN_HEIGHT = (40, 75)
CRASH_PURPLE_AREA = (1000, 628, 1262, 700)
CRASH_PURPLE_MIN = 1500
# 諮商紀錄页：角色卡是 2 列网格（列心 x≈537 / 917，行心 y≈276 / 526），人数变化时
# 卡片会往前补位，所以逐格点、点完看 `消除記憶` 有没有变紫。
CURE_SLOTS = ((537, 276), (917, 276), (537, 526))
# `消除記憶` 按钮：没选人时是灰的（紫色 0 像素），选中后变紫并显示花费（紫色 ~12000）
CURE_ERASE_AREA = (620, 645, 930, 695)
CURE_ERASE_PURPLE = 3000
CURE_ERASE_POINT = (760, 669)
# 确认框（取消 435,505 / 橙色 `消除記憶` 845,505），橙色那颗正好落在 DIALOG_AREA 里
# 治疗过场的 `批准`(618,335,673,367) 和结尾的 ▼(1197,625)
CURE_APPROVE_POINT = (640, 351)
CURE_STORY_POINT = (1197, 625)
# 諮商紀錄/治療中心 左上角返回箭头，两页通用
CURE_BACK_POINT = (45, 37)

CARD_MARK_AREA = (100, 640, 1250, 695)
CARD_MARK_HEIGHT = 70
# 底部标记点要像一排卡：首尾间距至少这么多，否则当零散亮点，不点

# 事件选项卡（`搜索屍體` / `攝取` 这种）：每张卡的**下边框**是一条又宽又稀的亮线
# （实测 320x23 的连通域里只有 636 个亮像素，填充率 9%），而 `跳過` / `獲得` 胶囊是
# 242x32、填充率 60~90%。所以"宽 + 稀"就把选项卡和白按钮分开了：
# 216 帧实测只有 41 帧命中（全部是选项卡页：两张卡的 472/808、三张卡的 308/640/974），
# 地图/剧情/战斗/灵光/塔罗/奖励/骰子页一帧都没有。
# 点卡片的中心 = 下边框中心上方 87 px（实测 677 → 590）。
# 复制卡牌：在选人页按了 `確認` 之后多久内不许按白色 `跳過`。
# 选人页 → 选卡页是紧接着的，实测中间只有一次过场；12 秒足够，也不会把
# 万一没出选卡页时的 `跳過` 饿太久（超时自动失效）。
COPY_PENDING = 12

# 寶物倉庫（宝箱房）：三个箱位**固定**（用户给的 spec page_3/4/5 的 elements[].box），
# 箱子开掉后上方的猫头图标消失，所以"图标还在"就是"这个箱子还没开"。
# 实测同一模板在这三个位置：箱子还在 0.96~1.00，开掉 0.38~0.45（tr_2..tr_5 四帧），
# 阈值 0.85 分得很开。逐个点，一次一个；三个都没有就交给底部按钮。
TREASURE_SLOTS = ((645, 330, 698, 376), (849, 243, 897, 292), (997, 317, 1047, 366))
TREASURE_SIMILARITY = 0.85
TREASURE_PAD = 30

# spec page_2「宝物仓库事件2」底部那颗 ▼（进房后先点它才开始开箱）。
# 它在 y 656~700，比 `CLOSE_AREA`(618~652) 低，`rogue_close_appear()` 覆盖不到。
TREASURE_ENTER = (639, 678)

# ---- 航点（信标）场景：中间一座青色石柱 + 底部「啟用航點 / 獲得裝備[...]」提示卡 ----
# 用户 2026-11-15 指出这一页没有判据。实测：`ROGUE_PROMPT` 只有 0.509、
# `ROGUE_CHECKPOINT` 0.181、`ROGUE_EQUIP` 0.359，全都不中；而
# `rogue_option_points()` 会把这张提示卡**误认成事件选项卡**（返回 [(640,677)]），
# 于是脚本会去点 (640,590) 的空白处。
# 航点提示卡**两步**（2026-11-16 01:26 实机确认）：
#   ① 未展开 → 点卡片中心，卡片展开、底部露出橙黄色 ∨
#   ② 已展开 → 点那颗 ∨，才真正"啟用航點"
# 石柱 (860,300) 点 4 次没反应；卡片底下那颗白点实测在 (661,713) 贴着画面底边，都是空的。
BEACON_CARD_POINT = (640, 620)
BEACON_CONFIRM_POINT = (640, 681)
# 航点提示卡的标题行（「啟用航點 / 獲得裝備[...]」）。模板分数分不开航点和事件页
# （事件页 T1=0.595 > 航点过渡帧 0.501），只能靠 OCR：航点页一定含「航點」或「裝備」，
# 事件页读到的是选项名（'閉上眼睛' / '打破混亂'）。
BEACON_TITLE_AREA = (498, 556, 806, 596)

# 「請選擇1張欲觸發靈光一閃的卡牌。」页：先点第一张卡，再点底部橙色「靈光一閃」。
# 实测日志里未知页分支盲点用的就是这两个位置，这里固化下来（2026-11-16 02:40）。
# 战后「獲得卡牌」页右下那颗橙色「✓ 獲得」（实测 1280x720 上约 (1138, 670)）。
ACQUIRE_POINT = (1138, 670)
# 「靈光一閃」详情弹窗的关闭点：画面左侧暗区，避开卡面和底部按钮。
FLASH_DETAIL_CLOSE = (200, 400)

FLASH_CARD_POINT = (320, 400)
FLASH_CONFIRM_POINT = (1153, 666)

# ❗复制卡页**只复制这一张**（用户 2026-11-17：「复制卡牌设定为只复制一号位的剑雨」）。
# 认不出它（分数不够 / 领先不够）就点「跳過」，一张都不拿 —— 复制会直接把卡塞进
# 牌堆，认错一张就是往牌堆里加垃圾。
# ❗神闪选卡页（`請選擇1張要賦予神之靈光一閃的卡牌。`）优先选这张，
# 找不到就点第一张（用户 2026-11-17：「直接指定一个卡名，没有的时候就点第一个」）。
GOD_CARD_NAME = '劍之雨'
GOD_CARD_MATCH = 0.55

COPY_CARD_MATCH = 0.55      # 卡名相似度门槛（实测 科沃斯基爵士 0.96 / 決心墜飾 0.39）
COPY_CARD_MARGIN = 0.12     # 领先第二名多少才算"确定是这一张"
# ❗认不出时**先重试几次再跳過**：卡面文字在切页那 0.2 秒里 OCR 抖动极大
# （2026-11-17 05:11 实测同一张剑之雨：0.93 → 0.52 → 0.52 → 0.50 → 0.49），
# 用某一帧就判"没有"会白丢一次复制。每次 `press` 周期（1.2 秒）试一次，
# 试满 COPY_CARD_MISS 次还认不出才按「跳過」。
COPY_CARD_MISS = 4

# ❗卡牌奖励页现在**整页跳过**（用户 2026-11-17：「事件里获得一张中立卡，这种的要跳过」），
# 所以原来「点第 1 张卡 (344,370) → 点角色 (650,280) → 按確認」的两个坐标已删除。
# 真要恢复选卡时，注意这页有 10 张（2 行 x 5 列）和 3 张（单行大卡）两种布局，
# 固定坐标在两种布局上落到的是不同的卡。
# 点完「靈光一閃」后等页面切走的时间：这期间判据仍会命中，必须**只等不点**，
# 否则会「点卡→点确认→点卡→点确认」无限循环（2026-11-16 18:29 实测）。
FLASH_SUBMIT_WAIT = 5
# 同一页最多点几下（防死循环）。
BEACON_TRIES = 6

# spec page_1「宝物仓库事件」那张「進入傳送門內部 / 觸發【寶物倉庫內部】事件」紫卡。
# 它和事件选项卡是同一套交互（点卡选中 → 卡片上移 + 出 ▼ → 点 ▼ 提交），但整张卡
# 在 y 550~630，落在 `OPTION_BAND`(650~700) 之外，所以 `rogue_option_points()` 扫不到，
# 只能单独用模板认。模板取 tr_0.png 的 (491,551,778,626)。
TREASURE_CARD_AREA = (491, 551, 778, 626)
TREASURE_CARD_POINT = (634, 588)
TREASURE_CARD_SIMILARITY = 0.85

# ---- 休息点的「德朗商店」删卡（用户 2026-11-15 的 spec `chaoszero_卡牌移除`）----
# 商店内部右上那张「移除卡牌」卡（spec page_2 的 box (780,162)-(857,250)），
# 花 70~106 金删一张。营地页只有「德朗商店」标题、没有这张卡，两者分得开。
SHOP_REMOVE_AREA = (780, 162, 857, 250)
SHOP_REMOVE = (818, 206)
SHOP_REMOVE_SIMILARITY = 0.85

# 删过卡之后，商店右上那块会变成「售罄」黑面板（spec 里没有，2026-11-15 实机补的）。
# 实测 cv2 灰度匹配：售罄页 1.000 / 正常商店页 0.092~0.100。
SHOP_SOLD_AREA = (746, 124, 1102, 272)
SHOP_SOLD_SIMILARITY = 0.85
# 商店右下那颗玫红 `離開`（不是橙色，`rogue_primary_point` 和 `rogue_purple_point`
# 都认不出：它是 r≈200 / g≈50 / b≈110，purple 判据要 b>195）。
SHOP_LEAVE = (1136, 678)

# 一个休息点**只能删一次卡**：删完商店那张「移除卡牌」会变成「售罄」（2026-11-15 实测）。
# 两次进店之间隔这么久（秒）：营地里待的时间远小于它，下一个营地走过去要一分多钟。
SHOP_COOLDOWN = 120

# 点完「德朗商店」之后要等它加载：进店有一次黑屏过场，1.4 秒后画面还停在营地页，
# 于是 `# 4.7` 的休息分支当场就把「休息」点了 —— 2026-11-15 17:35 日志
#   `Click (466,93) @ ROGUE_REST_SHOP`  →1.4s→  `Rest at the safe area (1/3)`
# 商店的点击就这么被休息吞掉，一次卡都没删。这 8 秒里除了等什么都不做。
SHOP_LOAD = 8

# 同一个营地最多点几次「德朗商店」。点店有时会被吞掉（营地页还在淡入时点无效），
# 2026-11-15 18:06 实测点完 8.4 秒画面仍停在营地 —— 那时候不能再等，要能重试。
# ❗`SHOP_COOLDOWN` 从「点店时」挪到「**进店成功后**」（见 `# 4.6`），否则一次
# 点空就会被冷却 120 秒锁死，只能去休息。
SHOP_RETRY = 3

# 「請選擇欲複製的卡牌。」那页第一张卡的中心（2026-11-15 15:0x 实机帧 cp_cards2.png：
# 三张竖卡 x 178-462 / 507-792 / 836-1120、y 172-598，卡中心 y≈385）。
# ❗这页的卡在**画面中部**，`OPTION_BAND`(y 650-700) 根本扫不到，所以只能靠位置点；
# 而且**单击即生效**（点一张卡直接出「卡牌複製完成」，没有金色 ∨、也没有確認）。
COPY_CARD_POINT = (320, 385)

OPTION_BAND = (150, 650, 1150, 700)
OPTION_BORDER_TOP = 670  # Event borders start around y=677; battle effects can touch the scan band's top edge.
OPTION_LIGHT = 140
OPTION_WIDTH = (240, 470)
# ❗高度上限 40 → 30：实测真卡框是 316~320 宽 × **21~23 高**（填充率 0.09），
# 而战斗画面里被误判成"卡框"的亮块是 285x40 / 308x32（填充 0.11~0.22）。
# 2026-11-15 实机 9 页里有 2 页是战斗画面（技能特效 + CRI 数字），
# 被这个上限放进来当成事件页，结果 OCR 读到空、还差点点下去。
# ❗下限 15 → **8**：有的选项卡底部装饰线只有 11px 高
# （`unknown_081436` 沉睡的怪物那页实测 `148x11`），15 会把整排过滤掉。
# 上限仍是 30，配合"合并相邻段"和宽度 240~470，误检风险可控。
OPTION_HEIGHT = (8, 30)
OPTION_FILL = 0.30
# Straight event borders occupy most of one row; curved battle effects do not.
OPTION_FLAT_RATIO = 0.65
OPTION_LIFT = 87
# 选中之后卡片下缘正中会出现一枚**金色 ∨**，点它才是提交（用户 2026-11-14 实机确认：
# "点一次选项后，再点下面那个勾就行"）。它是 y 650~700 里唯一的小亮团：
# 实测 33x23 / 120 像素，未选中的同页没有（只剩两张卡各 318x21 的边框和 148x11 的虚线）。
OPTION_CHECK_LIGHT = 170
OPTION_CHECK_SIZE = ((18, 80), (10, 40), (80, 500))
OPTION_CHECK_OFFSET = 90

# 「選擇您的命運。」那页：三张竖版塔罗卡 + 右下 `確認`。塔罗卡是竖着的
# (y 65~590)，不是底部那一排，所以固定卡位在这里；`確認` 在 (1103,669)，
# 选中之前是灰的。判据用底部那行字（`ROGUE_FATE` 模板），173 帧里只在这页命中。
FATE_OK_POINT = (1103, 669)

# 装备页三行战斗员（y≈216/352/489），点行选中再点確認。
TEAM_POINTS = ((936, 216), (936, 352), (936, 489))

# 大厅右侧竖排菜单（故事 / 出征 / 模擬 / 卡厄思 / 方舟都市 / 戰鬥員 / 救援）里
# 「卡厄思」那一条的图标中心。2026-11-14 实机逐项对齐过：故事 122 / 出擊 200 /
# 模擬 262 / 卡厄思 322 / 方舟都市 390 / 戰鬥員 450 / 救援 520。
# ❗v1 写的是 (1200,400)，那一格是「方舟都市」，点下去会开政策室。
LOBBY_ROGUE = (1215, 322)

# 卡厄思顯現的世界列表里「霧之城市」那颗星球（列表共五颗，位置按当前赛季排布）。
# 只点一次就会进详情页，认不出详情页的 `進入` 就收工，不盲点第二下。
WORLD_CARD = (715, 470)

# 世界列表一共五个世界，横向排开，**列表可以被左右拖动**，而且位置是游戏记住的：
# 最右边的「降臨的混沌」默认在屏幕外，必须往右拖才看得见（用户 2026-11-14 确认）。
# 所以不写死坐标：每个世界的名字标签（含阵营图标）做模板，命中位置 + 固定的
# 「标签中心 → 星球中心」向量 = 点击点。星球直径约 180，差二三十像素照样点得中。
# 匹配分（216 帧以外的实测）：自己帧 1.000，同页别的世界 ≤0.61，
# 详情页/大厅/局内 ≤0.80（详情页右侧面板写着同名大字，但只在世界列表里搜）。
WORLD_LABELS = {
    '雙星之影': ROGUE_WORLD_SHUANG,
    '審判之沼': ROGUE_WORLD_SHENPAN,
    '藍壺': ROGUE_WORLD_LANHU,
    '霧之城市': ROGUE_WORLD_WUZHI,
    '降臨的混沌': ROGUE_WORLD_JIANGLIN,
}
WORLD_OFFSETS = {
    '雙星之影': (-206, -15),
    '審判之沼': (-209, 12),
    '藍壺': (-185, -6),
    '霧之城市': (-238, 1),
    '降臨的混沌': (-247, -21),
}
# 往右拖 = 露出右边的世界；先拖回最左做归一化，再一屏一屏往右找。
WORLD_SCROLL = ((1080, 400), (330, 400))
WORLD_SCROLL_BACK = ((330, 400), (1080, 400))
WORLD_REWINDS = 2
WORLD_SCANS = 3
# 队伍页和世界详情页的左上角返回箭头。
WORLD_BACK_POINT = (45, 37)

# 卡厄思（两卡）页左边的「卡厄思顯現」那张大卡片的中心。文字标签在
# (300,550)-(500,600)，但实测点文字命中率不稳定（点击落点会左右飘），
# 点卡片本体 (330,420) 才是这块大按钮的中心。
MODE_CARD = (330, 420)

# 「配置隊伍」页右上角的**梦境模式**开关（用户 2026-11-14 提供两态截图）。
# 开关本体 (940,14)-(1078,56)，点中心 (1010,35) 即可，两态同一个位置：
#   * 关：浅色页面，轨道右侧是浅灰，滑块暗紫在**左**，`儲存資料儲存上限 100pt`；
#   * 开：整页变紫，滑块亮白在**右**，上限 110pt（战利品更好，刷档要开）。
# 两态模板互斥（交叉分 0.485 / 0.496），自匹配 0.999/1.000；877 帧里按
# `area ± 20` 的局部窗口扫，`关` 只在队伍页命中 7 次（0.997~0.999），
# 次高 0.562；`开` 在旧素材里 0 命中（最高 0.658），等实机拨一遍确认。
DREAM_POINT = (1010, 35)
DREAM_TRIES = 4

# 开局「传令兵」的**三选一**（凯尔肯帐篷前那页，三张卡横排在底部 y 510-690）。
# 用户 2026-11-14 说明：默认选左边第一张 —— 它给「3 场一般战斗怪物 HP 变 1」的
# buff，前三场战斗基本等于白给；但每局这三张的内容是随机的（拾棄世俗 / 接受祝福
# 最大HP+20% / 甘受玷污 诅咒卡+灵光 / 獻上讚美 信用點數…），所以配置只能按**位置**。
# 判据：
#   * 场景美术 `(300,60)-(800,140)`（帐篷/神殿顶）做成模板，786 帧里只在同一幕
#     出现（22 帧），战斗/地图/事件/塔罗/奖励页 0 命中；
#   * 三张卡下方的亮 ∨ 就是"已选中 + 也就是提交键"（用户给的 命运确认1/2/3）。
HERALD_POINTS = ((305, 620), (640, 620), (974, 620))
HERALD_CHECK = ((305, 680), (640, 680), (974, 680))
HERALD_LIGHT = 140
HERALD_TRIES = 4

# 局内撤退：右上角 ☰ `(1209,22)-(1247,58)` 打开「卡厄思資訊」全屏面板，
# 面板右下角橙色 `撤退` `(1031,643)-(1245,693)`。786 帧里 `撤退` 只在面板页
# 命中 8 帧（含战斗里开的同一面板），无假阳。
INFO_MENU_POINT = (1228, 40)
RETREAT_TRIES = 3
MENU_TRIES = 4

# 演出帧：剧情文本/▼ 还没出来时整页没有按钮（2026-11-14 14:41 雨夜街道帧干等 13 分钟）。
# y≈300 是背景美术，没有卡片也没有按钮，点它只为推一句台词。
CUTSCENE_POINT = (640, 300)
# 剧情页右下那颗空心白 ▼ 的中心（`ROGUE_STORY` 的 area 是 (1188,608)-(1214,638)）。
# 点它推一句台词 —— 这是**有判据**的动作，不是以前那种"没有判据就点画面中部"的盲点。
STORY_POINT = (1201, 623)

# 卡牌页收集器两次存盘的最小间隔（秒）：卡片呼吸动画会让画面签名每帧都变。
CARD_PAGE_GATE = 3

# ---- 卡牌页收集器（2026-11-16 用户定：识别目标是"认出哪张卡 + 哪种灵光"，含神闪）----
# 纯**旁路**：只存图 + 记录当时的识别结果，一个字都不影响决策。
# 目的是攒样本离线评估 —— 没有样本，"OCR 到底多准 / 神闪到底能不能读"全是猜的。
#   log/rogue_card_pages/flash/   普通灵光三选一
#   log/rogue_card_pages/god/     神闪（底部有「靈光一閃：<神名>」）
#   log/rogue_card_pages/remove/  删卡页
#   log/rogue_card_pages/copy/    「請選擇欲複製的卡牌」
# 每页存 `HHMMSS.png`（整页）+ `HHMMSS.json`（三列 OCR / 识别到的卡 / 匹配列 / 分数）。
# 灵光页另外裁三列描述块 `HHMMSS_c1..c3.png`，方便直接看那一列到底是什么字。
CARD_PAGE_DIR = './log/rogue_card_pages'
# 灵光面板三列描述的裁剪区（和 `rogue_cards.COLUMNS` 一致，上下用 `DESC_AREA`）
CARD_PAGE_COLUMNS = rogue_cards.COLUMNS
CARD_PAGE_DESC = rogue_cards.DESC_AREA

# 选项卡上那枚金色 ∨（已选中标记）：33x24、面积 120~160、亮部 RGB≈(249,244,195)。
# 战斗页手牌小徽标最小 27x20/19x20，亮部 b≈236~253，所以用宽高+面积+「暖色」三重过滤。
OPTION_ANY_WIDTH = (28, 40)
OPTION_ANY_HEIGHT = (18, 28)
OPTION_ANY_AREA = (100, 180)
OPTION_ANY_BLUE = 215

# ❗**未知页盲点已全部删除**（用户 2026-11-16：「未知页盲点要删掉」）。
# 以前这里有两个兜底：`SCENE_PATCH`（按固定点位挨个试，用来开宝藏房的箱子）和
# 未知页里"点画面中部推剧情"。它们都是**没有判据的乱点** —— 既可能误触
# （战斗演出时点 (640,300) 会点在怪身上、弹出敌人详情把整场按暂停），
# 又掩盖了"这页根本没做判据"的事实。
# 现在未知页只做两件事：存帧到 `./log/rogue_pages/` + 等；真的不动了就
# `Unknown page and nothing to press, retreat and start over` 收工，等人给规则。
# 宝藏房要恢复，得先做出「認到寶物倉庫才点箱」的正面判据。

# 认不出的页面只有在"静了几秒"之后才点：战斗演出每帧都在变，点下去就是点在怪身上，
# 会把敌人详情面板点开、把整场战斗按暂停（2026-11-15 01:31 实测）。
SCENE_STILL = 4
# "静"的判定不能用逐字节比较（雾/粒子动画每帧都变），用缩略图均差：换页 30~60，
# 动画 < 3，所以 PAGE_CHANGE 放在 10。
PAGE_CHANGE = 10.0

# 敌人详情面板：战斗中点到怪身上弹出来的左半屏说明。再点一次战场上的怪就关掉它，
# 位置随敌人站位变，所以按候选位点轮流试，最多 PANEL_TRIES 次。
PANEL_POINTS = ((950, 300), (860, 430), (760, 250))
PANEL_TRIES = 4
# 卡牌详情覆盖层的「關閉」（橙色药丸，坐位 455-608 / 652-690）；右下 (1035,671) 的
# 「靈光一閃」不要点。
DETAIL_CLOSE_POINT = (530, 670)
# `所有牌堆` 牌堆列表覆盖层右上角的 ✕（(1177,18)-(1228,62)）。
DECK_CLOSE_POINT = (1203, 40)
# 客户端断线恢复弹窗：`撤退`(470,508) 会弃掉这一局，只点 `繼續進行`(815,508)。
RESUME_CONTINUE_POINT = (815, 508)
# 事件选项卡的标题行（相对卡片下沿检测点的偏移）：标题在奖励说明上面一行。
# 2026-11-15 实测：以 (472,677) 下沿为基准，y-125~y-95 读得出 `搜索尿體`/`攝取`，
# y-133~y-103 就只剩半个字了。
EVENT_TITLE = (-150, -125, 150, -95)
EVENT_CONFIRM_ATTEMPTS = 3
# Same-title numbers in the selector's fixed routes, by confirmed visit.
EVENT_GUIDED_VARIANTS = {
    'uk_300_s02_05a': ((1,), (2,)),
    'uk_302_s02_04c': ((3,), (4,), (5,)),
    'uk_401_s01_04a': ((1,), (2,), (3,)),
    'uk_401_s01_17a': ((3,), (4,)),
    **{f'uk_402_s01_11{variant}-{branch}': ((1,), (2,), (3,), (4,))
       for variant in 'abc' for branch in (1, 2)},
    'uk_403_s01_04a': ((3, 6), (4, 7), (5,)),
    'uk_403_s01_05a-2': ((1, 3, 6), (2, 4, 7), (5, 8)),
    'uk_403_s01_05b': ((2,), (3,), (4,), (5,)),
    'uk_403_s01_11a': ((2,), (3,), (4,)),
    'uk_403_s01_11c': ((4,), (8,)),
    'uk_403_s01_12a': ((1,), (2,), (3,)),
    'uk_900_s02_10c': ((1,), (2,)),
    'uk_900_s02_11a': ((1,), (2,), (3,), (4,)),
    'uk_900_s02_16a': ((3,), (3,), (4,)),
    'uk_904_s01_04a': ((2,), (2,), (3,)),
    'uk_904_s01_05a': ((8,), (6,), (7,)),
    'uk_904_s01_13a-1': ((4,), (5,), (6,), (7,)),
    'uk_904_s01_13b-1': ((4,), (5,), (6,), (7,)),
    'uk_905_s02_02a': ((4,), (5,), (6,), (7,)),
    'uk_905_s02_13a': ((), (3,), (4,), (5,), (6,)),
    'uk_905_s02_16a': ((1,), (2,), (3,)),
    'uk_905_s02_16c': ((2,), (3,), (4,)),
}

# 事件页识别记录（每页一份 JSON + 截图），用来统计识别正确率。
# 2026-11-15 用户要求"把整局的事件都匹配一遍，看看正确率"。
EVENT_LOG_DIR = './log/rogue_event_pages'

# 命运（塔罗）三选一的收集器目录。命运资料库里没有，只能穷举：
# 每次遇到就存图 + OCR 三个标题，攒够了再排优先级（用户 2026-11-16）。
# ❗**两面分开存**：第二面（核心）有自己的一批命运，和第一面**完全不重叠**
# （用户 2026-11-16：「第二面的命运不会在第一面出现，同理第一面也不会出现在第二面」）。
# 调试收集按识别到的命运卡池分目录：
#   ./log/rogue_fate_pages/main/   第一面
#   ./log/rogue_fate_pages/core/   第二面（核心）
FATE_LOG_DIR = './log/rogue_fate_pages'
# 三张卡的效果说明（多行）。用户 2026-11-16：光有标题判断不了哪个命运更好，
# 效果必须一起收 —— 例如「精英區域的裝備獎勵中必定出現傳說級別裝備（接下來2次）」
# 和「所有戰鬥員的顯現自我意識階段上升1」价值差很远。
FATE_DESC_AREAS = ((190, 415, 455, 520),
                   (520, 415, 780, 520),
                   (830, 415, 1085, 520))

# 相似页面的自动处理总开关。**2026-11-16 用户逐页给了规则，已放开**：
#   营地/休息        按原逻辑（需要删卡就删，删完回血）
#   冥想/灵光选择    绑定卡牌识别，还没做，实际不会触发
#   人物灵光选人     `RogueMember` = 1 号位
#   复制卡牌选人     优先配置的来源位次，默认跟随灵光优先位
#   命运三选一       按两面的命运优先级选择，无匹配时随机
#   传令兵三选一     `RogueHerald` = 最左（第 1 张偶尔附带转化/删卡/装备）
# **删卡 / 转卡**不靠这个开关：转卡页由 `# 2.015` 的专属模板判据直接跳过，
# 删卡页正常删（`RogueDelete`）。
AUTO_HANDLE_SIMILAR_PAGES = True

# 事件偏好选择器（`dev_tools/rogue_events/`）导出的 picks 放这里。
# 有了它，识别出事件后就直接照用户标的选，不再按奖励类型猜。
# ❗必须放在 `config/` 的**子目录**里：`module/config/utils.py` 的 `alas_instance()`
# 会把 `config/` 下所有 `*.json` 当成一个 Alas 配置实例
# （`splitext(name)[1] == '.json' and mod_name == ''`），`rogue_event_picks.json`
# 于是会被 GUI 列成一个配置、加载时格式不符就报错（用户 2026-11-15 指出）。
# 子目录的 splitext 结果是 `('rogue', '')`，扩展名不是 `.json`，会被跳过。
EVENT_PICKS_FILE = './config/rogue/rogue_event_picks.json'

# 「这局已经进第二面（核心）了」要**落盘**：`core_started` 只存内存时，
# 脚本一重启（`RUN TASK` 重新进来）就回到 False，第二面又按第一面的配置走
# （`style 均衡` 而不是固定的「优先事件」+ 避开精英）。
# 2026-11-16 01:39 实测：01:39:48 已经认出 BOSS 战利品页并置 True，
# 01:41:28 进程重启后 `Route nodes 18, style 均衡` —— 状态丢了。
# 放 `config/rogue/` 子目录，避免被 `alas_instance()` 当成 Alas 配置。
ROGUE_STATE_DIR = './config/rogue'

# ---- 第一面打完的「BOSS 战利品页」（複製卡牌 / 裝備 / 信用點數 + 獲得 N）----
# 用户 2026-11-15：这一页之后就是**第二面（核心）**，要在这里读第二张地图的路线。
# 判据用右上那颗**紫色「複製卡牌」大按钮**：实测该区域紫色像素 13708，
# 而同屏的装备行 / 信用點數行 / 左半屏分别是 0 / 0 / 267，分得非常干净。
# 不读「獲得 N」里的数字 —— ONNX 中文模型读单个数字返回空串（实测三种裁法都是 ''）。
LOOT_AREA = (900, 110, 1260, 215)
LOOT_PURPLE = 5000
# ❗步数门槛（一面 16 步、BOSS 在末尾）：不加的话开局某个紫色页面会被误判成
# BOSS 战利品页，`core_started` 提前置 True，整张第一面都按「优先事件」走
# （2026-11-16 02:28 实测 `BOSS loot page after 0 step(s)`）。
LOOT_MIN_STEP = 8
# ❗曾经用 `route_step >= 14` 兜"中途普通战利品页"，后来删了：
# 普通战利品页（只给信用點數 / 裝備）**没有那颗紫色「複製卡牌」**，实测紫色 0，
# 而步数门槛在"中途接管已开的局"时恒为 0，反而永远触发不了。靠 `core_started` 只触发一次。
# 老位置：曾经放在 config/ 根下，读不到新位置时兜底一次，避免用户白导一遍。
EVENT_PICKS_LEGACY = './config/rogue_event_picks.json'
# 整局结束时的 `存檔資料收集完成` 页：三个角色的存档卡并排，每张卡右边竖着
# ☆ / 🔒 / 垃圾桶（x 约 427 / 837 / 1237，y 约 474 / 528 / 582），右下紫色
# `下一步`(1120,662)。页面标题在 (460,58)-(830,104) —— 这一页和 `探索結果`
# 用同一种紫色主按钮，点击前先识别标题。
# ❗垃圾桶不是「点了就删」：点一下立刻显示 `分解完成` 并把存档分解成單元幣
# （实机 21650TB→488、23270TB→465），同时弹一层 `獲得道具` 白底弹窗盖住整页，
# 弹窗要按掉才会回到这一页。所以一次只删一张，删完等弹窗过去再看下一张。
SAVE_TITLE_AREA = (460, 58, 830, 104)
SAVE_TRASH = ((427, 582), (837, 582), (1237, 582))
# 垃圾桶图标所在的小框：图标在时亮像素 ~250-264，删掉后 0-6（2026-11-15 实测）。
SAVE_TRASH_BOX = ((417, 568, 447, 600), (827, 568, 857, 600), (1227, 568, 1257, 600))
SAVE_TRASH_LIGHT = 150
SAVE_TRASH_MIN = 100
SAVE_TITLE_WORDS = (u'存檔', u'存档', u'收集完成')
RESULT_TITLES = ('探索結果', '探索结果', '結算', '结算')

# 掷骰页：掷之前整页只有一个骰子和 `Tap 請點擊畫面查看骰子結果。`，点一下骰子就出结果。
# ❗`重新擲骰` (435,645) 要花骰子点数（每天固定 20 点，很珍贵），**永远不点**（用户
# 2026-11-15），只走免费的 `下一步`；骰子最多补点一次（DICE_TRIES=2），点多了也只是
# 看结果，不会重掷。
DICE_POINT = (640, 330)
DICE_TRIES = 2

# 安全区域（休息点）：`請選擇1種想要在安全區域使用的功能。`
# 用户 2026-11-15：休息免费；休息/冥想/训练 **三选一**，选一个另外两个就锁了；
# 训练是拿中立卡，默认不点；冥想只在「已经闪了但类型不对」时才用（类型判定还没做，
# 所以现在固定休息）；**不要点 `跳過`**，那等于把休息点浪费掉。商店和休息不冲突。
REST_POINTS = ((400, 540), (1085, 435))  # 休息 / 冥想
REST_CONFIRM_AREA = (700, 480, 1000, 545)  # 「休息」确认框的橙色確認 (845,512)
REST_TRIES = 3
REST_WAIT = 6
# 点完「冥想」但冥想页没开（画面还在过渡、点空了）时重试几次。
# 2026-11-17 用户定位：「进休息点，画面没稳定就点了冥想，于是失败了，
# 也没有重试就点休息了」。
MEDITATE_RETRY = 2

# 冥想（2026-11-15 实测）：
#   安全区域点冥想 → 说明框「從賦予靈光一閃的卡牌中選擇1張，重組靈光一閃。」，
#   橙色 `確認` 在 (845,483)（正好落在通用对话区里，`# 0.05` 分支会自动按掉）
#   → 选卡页「請選擇1張再次靈光一閃卡牌。」：左列是各个战斗员，右边是他们的
#     已闪卡网格（2 行 x 3 列），点一张卡 → 右下 `再次靈光一閃` 变橙 → 按下去
#   → **直接回到安全区域页**，没有三选一（重掷是随机的），`離開` 收尾。
#   ❗冥想格子真正能被点的位置是图标 (1120,428)；旧的 (1085,435) 落在两个格子的
#     缝里，点了毫无反应（2026-11-15 09:2x 实测四次都没弹说明框）。
MEDITATE_POINT = (1120, 428)
MEDITATE_CONFIRM_POINT = (845, 483)
MEDITATE_COLUMNS = (360, 567, 775)
MEDITATE_ROWS = (85, 385)
MEDITATE_NAME = (38, 8, 195, 44)  # 卡名条相对格子左上角
MEDITATE_SPREAD = (95, 135)  # 卡片中心相对格子左上角
# 「再次靈光一閃」实测中心 (1144, 671)（2026-11-17 07:45 截图，1080 显示宽 875~1055
# → 1280 上 1037~1250）。原来是 1173，偏右 29px，容易点到右侧空白。
MEDITATE_OK_POINT = (1144, 670)
MEDITATE_CANCEL_POINT = (916, 670)
# 卡名 OCR 在这张网格上实测只能认出 3~4/6（`決心墜飾`→`清公樂飾二於` 0.23、
# `劍之雨`→`劍多團是月` 0.29），所以宁可放弃也不猜：低于 MATCH 或者跟第二名
# 差不到 MARGIN 就取消冥想、回去休息（用户要求：只有确定不会认错才动手）。
MEDITATE_MATCH = 0.60
MEDITATE_MARGIN = 0.20
# 冥想页的判据和流程都实机验过了，可以放开。
MED_READY = True

# 人物灵光：`請選擇欲獲得【靈光一閃】的戰鬥員。`（三张大立绘 + 右下 `確認`）。
# 用户 2026-11-15：亮着的角色还有没闪出来的卡（选它 = 该角色随机一张没闪的卡灵光），
# 暗掉的角色卡已经闪完（选它 = 换成钱，商店用）；这种人物闪只出现在第一面。
# 认不出存档角色，所以按 RogueMember 的号位点，但号位若明显比别的暗、就改点最亮的那张。
MEMBER_POINTS = ((315, 360), (640, 360), (965, 360))  # 三张大立绘的身体
MEMBER_OK_POINT = (1135, 668)  # 右下 `確認`（选人之后才亮）
MEMBER_CONFIRM_AREA = (1010, 640, 1270, 696)  # 同上那颗按钮的橙色判据窗口
MEMBER_CONFIRM_SIZE = ((180, 300), (30, 80))  # 这颗只有 240x50，比对话框窄
MEMBER_WAIT = 3
MEMBER_TRIES = 3
# 删卡只按识别出的卡名挑选，顺序即优先级：劍幕 > 劍光。
REMOVE_TARGETS = ('劍幕', '劍光')
# 卡名相似度门槛。这页卡名只有 ~20px 繁体小字，OCR 常把 `劍之雨` 读成 `劍市`，
# 而 `劍市` 对 `劍光` 的相似度是 0.50、对 `劍之雨` 只有 0.40 —— 门槛低了必误删。
REMOVE_NAME_MATCH = 0.55

# 底部那两颗并排的按钮：左「取消」、右「移除」。只剩基础卡不值得删时点「取消」退出，
# 别让脚本在这一页干等到超时（实测 1280x720 帧上「取消」中心约 (913, 673)）。
REMOVE_CANCEL_POINT = (913, 673)
# 点过卡之后给多少秒"仍在删卡页"的宽限：整页会压暗、标题模板和橙色「移除」
# 同时失效 1~2 秒，判据全灭。没有这个窗口，`remove_stage` 会被打回 0、
# 反复点同一张卡，结果一张都删不成（2026-11-16 01:10 实测）。
REMOVE_WAIT = 6
# 一页里最多动几次：点卡(1) + 没选中重试(2) + 最终按「移除」(1)。
# 原来是 2，刚够"点卡 + 按移除"，没选中时连重试的机会都没有。
REMOVE_MAX_TRIES = 4

# 删卡页 / 转化页靠**顶部标题模板**区分（`ROGUE_REMOVE` vs `ROGUE_TRANSFORM`，
# 都是 (105,12)-(430,58)）。不再用 OCR 读标题 —— 模板在 0.93 阈值下互斥，
# 比 OCR（会认错字、每次 ~100ms）更快更准。
REMOVE_OK_AREA = (1000, 640, 1270, 700)  # 选中卡片后变橙的「移除」；左边「提煉」是深红

# 删卡页一屏只有 2 行 x 4 列 = 8 张；3 号位的卡在第 3 行（y≳690），被底部按钮条
# (y≈640~700) 挡死。右缘 x≈1254 是滚动条、卡片右缘≈1197，所以贴着卡区右侧 1220
# 慢拖（177：down 不落在卡上；用 drag 不用 swipe）。行距 ~300，拖 400 保证相邻两屏
# 有重叠、不漏行。找卡和归位都**固定拖满 3 次**（181：游戏记住滚动位置，且不能用
# 「画面没变」判到顶）；3 次 x 400 足够覆盖一局 3 个角色 x 8 张的多行内容。
REMOVE_SCROLL = ((1220, 600), (1220, 200))  # 往下翻，露出下面的行
REMOVE_HOME = ((1220, 200), (1220, 600))  # 拖回顶部
REMOVE_SCROLL_TIMES = 3

# 地图节点提示卡 `進入傳送門內部 / 觸發【…】事件`：点**卡身**才有反应，卡外的点击
# 会被卡吃掉。卡大约占 (478,528)-(802,700)，所以点 (640,600)。
# 第一次点卡身 → 卡片向右撑开、下方冒出一个大的白色 ∨（实测在 (640,690)）；
# 第二次点那个 ∨ 才真正进节点。2026-11-15 09:16 点 (640,680) 四次都没进，
# 人工点 (640,690) 一次就进去了 —— 所以第二点下移到 692。
PROMPT_POINTS = ((640, 600), (640, 692))  # 先点卡身展开，再点 ∨ 进入
PROMPT_TRIES = 4

# 队伍页右下角的 `進入`：位置固定 (1200,657)，但**不要用模板认它** ——
# 梦境模式开启后整页变紫，浅色页上量的按钮模板会失配。页面身份靠标题
# `配置隊伍`（TEAM_TITLE），按钮按坐标点。
TEAM_ENTER_POINT = (1200, 657)

# 认不出页面时最多唤醒几次：待机立绘点一下就回大厅；连点只会撞看门狗
# （12 次同名点击 = 客户端重启）。
WAKE_TRIES = 3

# 一局最长多久。实测单节点 30~90 秒，34 层的图大约 40 分钟，留到 3 小时。
ROGUE_TIMEOUT = 10800

# 同一画面静止多久判「在等玩家」（地图有雾气动画，永远在变，用不到这条）。
# 未知页"多久不动就收工"：20 → 40 秒。实测游戏切场景/加载能黑屏 20 秒以上
# （2026-11-16 19:19 一张全黑帧，HUD 还在、画面全黑），20 秒会把"正在加载"误判成卡死。
STAY_LIMIT = 40

# ---- 卡住 / 死循环检测（用户 2026-11-16：「卡住或者某处反复死循环先暂停脚本」）----
# 每 STUCK_PERIOD 秒采一次画面缩略签名，攒够 STUCK_SAMPLES 个（= STUCK_PERIOD*N 秒）
# 后，如果这些签名里**只有 ≤ STUCK_STATES 种**，就认定卡住或在两帧之间死循环。
# 60 秒 / 2 种：正常的战斗动画、粒子、载入都会不断产生新签名，不会误判；
# 而"点弹窗→弹窗关→再点"这种循环签名只在两帧间跳，正好被抓到。
STUCK_PERIOD = 5
STUCK_SAMPLES = 12
STUCK_STATES = 2


class ChaoszeroRogue(ChaoszeroUI):
    """卡厄思肉鸽：进本 → 推进到底 → 回主界面。"""

    # 卡牌形态库、逐行 OCR、事件库，第一次用到时才建（读 gzip + 加载模型都要时间）
    card_library = None
    card_reader = None
    event_library = None

    # ---------------------------------------------------------------- 颜色量

    def rogue_count(self, area, kind, threshold=None):
        """
        Count the pixels of one area that match a colour family.

        Args:
            area (tuple): x1, y1, x2, y2.
            kind (str): 'blue' / 'pink' / 'white' / 'cyan' / 'green' / 'purple'.
            threshold (int): For 'white', the min-channel floor.

        Returns:
            int: Pixel count.
        """
        # ❗先 astype(int)：uint8 相减/比较会回绕，任意颜色都能被算成目标色。
        part = self.image_crop(area).astype(int)
        r, g, b = part[:, :, 0], part[:, :, 1], part[:, :, 2]
        if kind == 'blue':
            return int(np.count_nonzero((b > 150) & (r < 110) & (g > 90) & (g < 190)))
        if kind == 'pink':
            return int(np.count_nonzero((r > 150) & (g < 120) & (b > 120)))
        if kind == 'white':
            floor = 235 if threshold is None else threshold
            return int(np.count_nonzero(part.min(axis=2) > floor))
        if kind == 'cyan':
            return int(np.count_nonzero((r < 140) & (g > 140) & (b > 140)))
        # 「觸發精神異常」页左下那颗绿色 `治療中心` 胶囊
        if kind == 'green':
            floor = 120 if threshold is None else threshold
            return int(np.count_nonzero((g > floor) & (r < 110) & (b < 140)))
        # 同一页右侧的紫色 `下一步`
        if kind == 'purple':
            return int(np.count_nonzero((b > 190) & (g < 150) & (r > 110)))
        raise ValueError(kind)

    # ---------------------------------------------------------------- 页面判据

    def rogue_battle_appear(self):
        """Returns: bool: 战斗页（右下蓝色大圆 ✓ 结束回合）。"""
        return self.appear(ROGUE_TURN, offset=(12, 12), similarity=0.85)

    def handle_rogue_battle_settings(self, press):
        """Enable visibly off battle controls, then verify their gold state."""
        if not self.rogue_battle_appear():
            return False
        for name, button, point in BATTLE_SETTINGS:
            area = button.area
            gold = self.ui_gold_count(area)
            if gold >= BATTLE_SETTING_GOLD:
                if self.battle_setting_tries.pop(name, 0):
                    logger.info('Rogue battle %s is enabled (gold=%s)' % (name, gold))
                continue
            if self.rogue_count(area, 'white', threshold=210) < BATTLE_SETTING_WHITE:
                continue
            # 战斗台词也有白字，必须同时认出关闭状态的图标。
            if self.appear(button, offset=(2, 2), similarity=0.85):
                if press.reached():
                    tries = self.battle_setting_tries.get(name, 0)
                    if tries >= BATTLE_SETTING_TRIES:
                        self.rogue_dump_unknown()
                        raise TaskFailed('Rogue battle %s could not be enabled, stop for review' % name)
                    press.reset()
                    self.battle_setting_tries[name] = tries + 1
                    logger.info('Rogue battle %s is off, enable it (try %s/%s)'
                                % (name, tries + 1, BATTLE_SETTING_TRIES))
                    self.tap_point(*point, name='ROGUE_BATTLE_%s_ON' % name.upper())
                return True
        return False

    def rogue_choice_appear(self):
        """Returns: bool: 事件页 / 战斗页（右下粉色 ✕ 圈）。"""
        return self.rogue_count(CHOICE_AREA, 'pink') > CHOICE_PINK

    def rogue_story_appear(self):
        """Returns: bool: 剧情页（右下那颗空心白 ▼）。"""
        return self.appear(ROGUE_STORY, offset=(8, 8), similarity=0.85)

    def rogue_close_appear(self):
        """
        Whether a 「點擊畫面可關閉視窗」 preview popup is up.

        判据换成底部那句提示文字的模板（`ROGUE_CLICK_CLOSE`），因为原来的"纯白像素"
        判据两边都错（2026-11-14 14:41 实测）：`精神異常` 说明弹窗的 ▼ 是**空心的**
        （最亮只有 146，一个纯白像素都没有，所以等了 13 分钟没人点），而战斗页
        底部的手牌区在那块框里能刷出 362 个纯白像素（于是战斗里狂点 (640,632)）。
        提示文字模板在 926 帧里只落在带这句话的页面上 —— 这句话本身就是"点一下就
        关"的语义，所以动作不变。
        """
        return self.appear(ROGUE_CLICK_CLOSE, offset=(20, 20), similarity=0.9)

    def rogue_item_appear(self):
        """
        Whether the `獲得道具` reward popup is up.

        删存档（点垃圾桶 = 分解）后会弹这一页：白底面板 + `獲得道具` + 一个道具图标
        + 底部 ▼ 与 `點擊畫面可關閉視窗。`。提示文字的位置在这里是 x 600~875，
        而 `ROGUE_CLICK_CLOSE` 框在 505~775，所以老判据认不出来 → 删档后卡在弹窗上
        （2026-11-15 13:5x 实机）。模板取标题 `(572,254)-(708,300)`：7 帧 1.0000
        （全是这一页），其余最高 0.5349。
        """
        return self.appear(ROGUE_ITEM, offset=(20, 20), similarity=0.85)

    def rogue_modal_appear(self):
        """
        Whether the `精神異常` explanation popup is up.

        它整页没有按钮（三个角色的压力词条 + 底部 `點擊畫面可關閉視窗。`），
        模板取标题+副标题 `(560,60)-(725,145)`，926 帧里 41 帧命中、全是真的这页。
        """
        return self.appear(ROGUE_MODAL, offset=(20, 20), similarity=0.9)

    def rogue_panel_appear(self):
        """
        Whether the enemy info panel is open (battle paused).

        战斗中点到怪身上会弹出左半屏说明（怪名 / 弱點 / 技能 / 士气 …），回合蓝 ✓
        还在，所以战斗判据照样成立，脚本会以为"战斗自己能打完"一直等 —— 其实全场
        被这个面板暂停了（2026-11-15 01:31 实测）。判据取面板里固定的 `ⓘ 弱點`
        小条 `(452,100)-(560,136)`：1008 帧里只有真开着面板的 6 帧 ≥0.995，
        其它页面最高 0.911，所以门槛用 0.95。
        """
        return self.appear(ROGUE_PANEL, offset=(20, 20), similarity=0.95)

    def rogue_dice_appear(self):
        """
        Whether the event dice page is up.

        判据是标题 `擲骰` `(600,92)-(690,125)`：926 帧里 37 帧命中，全是掷骰页
        （含掷完出结果、带 `下一步` 的那两帧）。掷骰页整页没有橙色按钮，掷之前
        只有一句 `Tap 請點擊畫面查看骰子結果。`，所以不认它就会干等
        （2026-11-14 15:12 实测 7 分钟没点）。
        2026-11-15 04:43 又撞到一次：没掷之前的标题是 `分析`（不是 `擲骰`），
        标题判据认不出，于是整页干等 16 分钟。补一条 `Tap` 字样判据
        （ROGUE_DICE_TAP，(588,432)-(696,472)）：掷骰页 ≥0.98，其它页最高 0.57。
        """
        if self.appear(ROGUE_DICE, offset=(20, 20), similarity=0.9):
            return True
        return self.appear(ROGUE_DICE_TAP, offset=(12, 10), similarity=0.9)

    def rogue_beacon_stage(self):
        """Return 1 to expand the waypoint card or 2 to press its confirmation arrow."""
        # Match only 「啟用航點」. The equipment name and rarity color change.
        if self.appear(ROGUE_BEACON_TITLE, offset=(10, 8)):
            return 2 if self.rogue_option_check_point(BEACON_CONFIRM_POINT[0]) else 0
        # The same title is 44 pixels lower before the card is expanded.
        if self.appear(ROGUE_BEACON_TITLE, offset=(-10, 36, 10, 52)):
            return 1
        return 0

    def rogue_beacon_transition(self):
        """
        Whether this is a 航点 frame whose stage cannot be told (装备图标弹窗).

        点卡片后会弹一下「獲得裝備[黑曜石劍]」的圆形图标盖在卡上，那几帧
        模板 1/2 都是 0.86/0.30 这种"半像不像"的分数。这时候**什么都别做**，
        等弹窗自己收起（约 1 秒后变成展开状态）。

        Returns:
            bool: If it looks like the beacon page but at an unclear stage.
        """
        # ❗**先排除事件选项卡**：实测事件页（三选一，底部三张卡带描述）的
        # T1 = 0.595，照样过 0.40 的门槛，会被当成"航点过渡"卡死在那里
        # （2026-11-16 01:33 实机：事件页一直刷 `Waypoint page in transition, wait`）。
        #
        # 两条排除条件，缺一不可：
        # ① 卡框 ≥ 2 —— 航点页只有 1 个（那张提示卡）。
        # ② **底部有金色 ✔** —— 卡片被点过之后会**抬起**，底边框离开检测带，
        #    `option_points` 只剩 1 个，① 就失效了；实测 01:53 两选一的事件页
        #    （已选中「靠近」、✔ 就摆在下面）因此又被判成航点过渡、卡死 40 秒。
        if len(self.rogue_option_points()) >= 2:
            return False
        if self.option_pending or self.rogue_option_check_any():
            return False

        # 0.40：弹装备图标那帧 T1=0.501 命中；地图页 0.181 / BOSS 页 0.092
        # 都远低于这个值，不会误判。
        hit = False
        for button in (ROGUE_BEACON_PROMPT, ROGUE_BEACON_PROMPT2):
            if self.appear(button, offset=(24, 16), similarity=0.40):
                hit = True
                break
        if not hit:
            return False

        # ❗最后一关：**OCR 底部那张卡的标题**。模板分数靠不住 ——
        # 事件页（三选一）的 T1 实测 0.595，比航点过渡帧(0.501)还高；
        # 石柱模板在过渡帧上只有 -0.036（相机位置变了）。只有文字是稳的：
        #   航点页   → '廠用航點一金' / '獲得裝備黑唯石財'
        #   事件页   → '閉上眼睛' / '打破混亂'（都是选项名）
        if self.card_reader is None:
            self.card_reader = rogue_cards.CardReader()
        try:
            text = self.card_reader.read_name(self.device.image, BEACON_TITLE_AREA)
        except Exception:
            text = ''
        if '航點' in text or '航点' in text or '裝備' in text or '装备' in text:
            return True
        return False

    def rogue_beacon_appear(self):
        """Whether the waypoint prompt is ready to expand or confirm."""
        return self.rogue_beacon_stage() > 0

    def rogue_dice_result_appear(self):
        """
        Whether a dice **result** page is up (失敗/成功 + 重新擲骰 / 下一步).

        ❗不能靠「下一步」按钮认这一页（用户 2026-11-15：「不要识别下一步，而是识别
        失败之类的独有特征」）—— 那等于回到已被删掉的通用跳过逻辑。
        也不能只靠「擲骰」标题：失败页的标题是**事件名**（实测是「騙術」），
        于是 `rogue_dice_appear()` 返回 False，整页干等到看门狗。

        判据用中间那个「失敗」大字（实测 1280x720 帧上约 (592,470)-(690,514)）：
        命中帧 1.000，其它页 0.319~0.434，阈值 0.85 很稳。

        Returns:
            bool: If the dice result page is on screen.
        """
        return self.appear(ROGUE_DICE_FAIL, offset=(30, 24), similarity=0.85)

    def rogue_prompt_appear(self):
        """
        Whether the map's node prompt card (`進入傳送門內部 / 觸發【…】事件`) is up.

        3D 地图上点一座平台只会**选中**它，随后画面正中下方弹出这张深色圆角卡，
        卡底那颗 ✛ 才是"进去"。整页没有橙色按钮、没有卡片边框、血量条又照常在，
        所以除了这张卡本身没有任何判据（2026-11-14 15:31 实测：光头卡上原地
        空点 (640,300) 点了 8 分钟）。
        模板取整张卡 `(478,528)-(802,700)`（含发光边框和 ✛）：927 帧里命中 21 帧，
        全是这张卡，其余最高 0.75 以下。
        """
        return self.appear(ROGUE_PROMPT, offset=(20, 20), similarity=0.9)
    def rogue_primary_point(self):
        """
        Locate the orange primary button of this frame.

        The button carries every 確認 / 繼續進行 / 獲得 / 進入 of the run, so
        finding it covers most of the flow. The size window is what separates
        it from the event cards and card frames that live in the same corner.

        Returns:
            tuple: (x, y) of the button centre, or None when there is no such
                button on screen.
        """
        part = self.image_crop(PRIMARY_AREA).astype(int)
        r, g, b = part[:, :, 0], part[:, :, 1], part[:, :, 2]
        # ❗`g > 120` → `g > 110`：卡牌奖励页那颗「確認」实测是 **(239, 120, 41)**，
        # g 正好等于 120，`>` 判 False → 整颗按钮检测不到 → 页面卡住
        # （2026-11-16 19:38 实测，日志停在 `pick the carrier` 之后不动）。
        mask = ((r > 200) & (g > 110) & (g < 200) & (b < 100)).astype('uint8')
        count, _, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
        best = None
        for i in range(1, count):
            width, height, area = stats[i][2], stats[i][3], stats[i][4]
            if not PRIMARY_WIDTH[0] <= width <= PRIMARY_WIDTH[1]:
                continue
            if not PRIMARY_HEIGHT[0] <= height <= PRIMARY_HEIGHT[1]:
                continue
            if best is None or area > best[0]:
                best = (area, int(centroids[i][0]) + PRIMARY_AREA[0],
                        int(centroids[i][1]) + PRIMARY_AREA[1])
        return (best[1], best[2]) if best else None

    def rogue_card_points(self):
        """
        Locate the option cards lined up along the bottom of the screen.

        每张卡正中下方有一颗白色小圆点，点圆点上方 70px 就是卡面中心。卡片数量
        从 2 到 3 张都会出现，位置随之居中重排，所以不能用固定坐标。

        Returns:
            list: Card centres, left to right (empty when there is no such row).
        """
        part = self.image_crop(CARD_MARK_AREA).astype(int)
        mask = (part.min(axis=2) > 170).astype('uint8')
        count, _, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
        points = []
        for i in range(1, count):
            width, height = stats[i][2], stats[i][3]
            if not 4 <= width <= 50:
                continue
            if not 3 <= height <= 35:
                continue
            points.append((int(centroids[i][0]) + CARD_MARK_AREA[0],
                           int(centroids[i][1]) + CARD_MARK_AREA[1] - CARD_MARK_HEIGHT))
        points.sort()
        return points

    def rogue_fate_appear(self):
        """
        Whether this is the 「選擇您的命運。」 tarot page.

        Returns:
            bool: If the caption at the bottom centre is on screen.
        """
        return self.appear(ROGUE_FATE, offset=(10, 6), similarity=0.9)

    def rogue_herald_appear(self):
        """
        Whether this is the 传令兵/凯尔肯 三选一 page (the run's opening blessing).

        判据是**场景美术**而不是卡片文字：三张卡的内容每局随机（拾棄世俗 / 接受祝福 /
        甘受玷污 / 獻上讚美…），文字既不能 OCR 也不该硬编码。帐篷顶那块
        `(300,60)-(800,140)` 是同一幕固定的，786 帧里只在传令兵这一幕命中
        （22 帧），战斗/地图/事件/塔罗/奖励/菜单页全部 ≤0.85。

        Returns:
            bool: If the herald scene is on screen.
        """
        return self.appear(ROGUE_HERALD, offset=(20, 20), similarity=0.9)

    def rogue_herald_selected(self):
        """
        Read which 传令兵 card is currently selected.

        选中的那张卡会整张上抬 ~12px，并在下缘出现一枚带光晕的亮 ∨（用户给的
        `命运确认1/2/3` 就是三张卡各自的那枚 ∨，它同时也是提交键）。
        ❗不能用这三张 ∨ 的模板判：选中时有光晕/粒子，模板匹配实测 0.7 上下、
        认不出来（2026-11-14 14:23）。用亮度更稳：选中那一格 mean ≈173~182，
        未选中 101~111（三张卡的窗口见 HERALD_CHECK）。

        Returns:
            int | None: 1/2/3 for the selected card, None when none is bright.
        """
        image = self.device.image
        best, bright = None, 0.0
        for index, (x, y) in enumerate(HERALD_CHECK, 1):
            window = image[y - 24:y + 20, x - 26:x + 26]
            if window.size == 0:
                continue
            score = float(window.mean())
            if score > bright:
                best, bright = index, score
        if bright > HERALD_LIGHT:
            return best
        return None

    def rogue_herald_index(self):
        """Returns: int: 传令兵那一页要选第几张（配置，默认 1 = 最左）。"""
        try:
            index = int(self.config.ChaoszeroRogue_RogueHerald)
        except (AttributeError, TypeError, ValueError):
            return 1
        return index if 1 <= index <= 3 else 1

    def rogue_dialog_point(self):
        """
        Locate the orange 確認 of a two-step confirm dialog.

        跳過 / 撤退 / 神闪提示 都会先弹一个只问一句的对话框，`確認` 在画面中部
        (849,454) 而不是底部按钮带，`rogue_primary_point()` 看不到它。看不见的
        后果是循环继续按被对话框挡住的 `跳過`，直到点量到看门狗（2026-11-14 实测）。

        Returns:
            tuple: (x, y) of the button centre, or None.
        """
        part = self.image_crop(DIALOG_AREA).astype(int)
        r, g, b = part[:, :, 0], part[:, :, 1], part[:, :, 2]
        mask = ((r > 195) & (g > 105) & (g < 205) & (b < 95)).astype('uint8')
        count, _, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
        best = None
        for i in range(1, count):
            width, height, area = stats[i][2], stats[i][3], stats[i][4]
            if not DIALOG_WIDTH[0] <= width <= DIALOG_WIDTH[1]:
                continue
            if not DIALOG_HEIGHT[0] <= height <= DIALOG_HEIGHT[1]:
                continue
            if best is None or area > best[0]:
                best = (area, int(centroids[i][0]) + DIALOG_AREA[0],
                        int(centroids[i][1]) + DIALOG_AREA[1])
        return (best[1], best[2]) if best else None

    def rogue_confirm_point(self, area, size=None):
        """
        Locate the orange 確認 inside an arbitrary area.

        安全区域的确认框 `確認(免費)` 在 (845,512)，比 `DIALOG_AREA` 的下沿还低一点，
        通用对话判据的高度过滤会把它切掉；人物灵光页的 `確認` 只有 240 px 宽，比通用
        对话框的 250 px 下限还窄。所以这里把窗口和尺寸都做成参数。

        Args:
            area (tuple): (x1, y1, x2, y2) of the search window.
            size (tuple): ((min_w, max_w), (min_h, max_h)), defaults to the dialog one.

        Returns:
            tuple: (x, y) of the button centre, or None.
        """
        width_limit, height_limit = size if size else (DIALOG_WIDTH, DIALOG_HEIGHT)
        part = self.image_crop(area).astype(int)
        r, g, b = part[:, :, 0], part[:, :, 1], part[:, :, 2]
        mask = ((r > 195) & (g > 105) & (g < 205) & (b < 95)).astype('uint8')
        count, _, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
        best = None
        for i in range(1, count):
            width, height, area_size = stats[i][2], stats[i][3], stats[i][4]
            if not width_limit[0] <= width <= width_limit[1]:
                continue
            if not height_limit[0] <= height <= height_limit[1]:
                continue
            if best is None or area_size > best[0]:
                best = (area_size, int(centroids[i][0]) + area[0],
                        int(centroids[i][1]) + area[1])
        return (best[1], best[2]) if best else None

    def rogue_secondary_point(self):
        """
        Locate the white 跳過 / 下一步 button of this frame.

        这三页的"不选就走"都是这颗白按钮：删卡页 `跳過`、掷骰结果的 `下一步`、
        安全区域的 `跳過`。它不在橙色主按钮那条带子上（更靠左、更靠上），
        所以单独找一块。

        ❗必须验"实心 + 够亮"：事件页的三张选项卡横在同一个区域里，卡面上的
        亮块也是白的，但填充率只有 0.04~0.05、亮度 30~43；真正的按钮是实心圆角
        矩形，填充率 0.75~0.94、亮度 200~244（2026-11-14 用 173 帧量）。不卡这两
        条就会在选项卡页面上一直点 (916,669)，12 次之后被点击看门狗重启客户端。

        Returns:
            tuple: (x, y) of the button centre, or None.
        """
        part = self.image_crop(SECONDARY_AREA).astype(int)
        mask = (part.min(axis=2) > 200).astype('uint8')
        count, _, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
        best = None
        for i in range(1, count):
            x, y, width, height, area = stats[i]
            if not SECONDARY_WIDTH[0] <= width <= SECONDARY_WIDTH[1]:
                continue
            if not SECONDARY_HEIGHT[0] <= height <= SECONDARY_HEIGHT[1]:
                continue
            if area / float(width * height) < SECONDARY_FILL:
                continue
            if float(part[y:y + height, x:x + width].min(axis=2).mean()) < SECONDARY_LIGHT:
                continue
            if best is None or area > best[0]:
                best = (area, int(centroids[i][0]) + SECONDARY_AREA[0],
                        int(centroids[i][1]) + SECONDARY_AREA[1])
        return (best[1], best[2]) if best else None

    def rogue_purple_point(self):
        """
        The purple capsule button of the settlement pages (`下一步` / `確認`).

        层末的 `探索結果` 页和整局结算页用的是同一颗紫胶囊（bbox 999,634 246x54，中心
        约 (1120,660)），只有里面的字不同（下一步 / 確認），所以不能用模板认字，只能
        按颜色和形状认：b>195、g<140、r>110，连通块宽 200~300、高 40~75、填充 ≥0.7。
        这一带背景是浅紫 (157,167,200)，g 很高，不会混进来。

        Returns:
            tuple[int] | None: (x, y) of the button centre, None if not found.
        """
        image = self.device.image
        x1, y1, x2, y2 = PURPLE_AREA
        part = image[y1:y2, x1:x2, :3].astype(int)
        mask = ((part[:, :, 2] > 195) & (part[:, :, 1] < 140) & (part[:, :, 0] > 110)).astype('uint8')
        count, _, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
        best = None
        for index in range(1, count):
            x, y, width, height, size = stats[index]
            if not PURPLE_WIDTH[0] <= width <= PURPLE_WIDTH[1]:
                continue
            if not PURPLE_HEIGHT[0] <= height <= PURPLE_HEIGHT[1]:
                continue
            if size < width * height * PURPLE_FILL:
                continue
            if best is None or size > best[0]:
                best = (size, int(cents[index][0]) + x1, int(cents[index][1]) + y1)
        if best:
            return best[1], best[2]
        return None

    def rogue_checkpoint_appear(self):
        """
        Whether this is the interim `結算` page right after activating a 航点.

        这一页是「这局已经有存档」的唯一信号：过了第一个航点，存档才开始计数
        （用户 2026-11-15：航点前退出只亏时间，航点后退出才有存档可留）。
        标题 `結算` 在右上 (1040,20)-(1140,62)，1151 帧里只有那一页命中 1.000，
        次高 0.52，阈值 0.85 很安全。

        Returns:
            bool:
        """
        return self.appear(ROGUE_CHECKPOINT, offset=(12, 10), similarity=0.85)

    def rogue_stop_reached(self):
        """
        Whether `RogueStopBeacon` says this run should be abandoned now.

        航点是「这局已经有存档」的唯一锚点，所以按航点计数来定停机点。
        0（或任何非法值）= 不停，一直打到这一局自然结束。

        Returns:
            bool: If the configured number of waypoints has been reached.
        """
        try:
            stop = int(self.config.ChaoszeroRogue_RogueStopBeacon)
        except (AttributeError, TypeError, ValueError):
            return False
        return 1 <= stop <= self.waypoints

    def rogue_step_reached(self, step):
        """
        Whether this run has already walked at least `step` nodes.

        ❗**这不是给用户用的功能**（用户 2026-11-15：\"计算步数是给脚本用的，
        让脚本知道错在了哪里。实际在用户使用的时候不需要走多少步停下的功能\"）。
        它只给开发期的探针用 —— 想让脚本"走到商店就停"来单独测某一段时，
        探针调它判断，生产配置里没有这个开关。

        Args:
            step (int): 目标步数（整面累计，和日志里的 `step N` 是同一个）。

        Returns:
            bool: If `route_step` has reached it.
        """
        return self.route_step >= step

    def rogue_settlement_page(self):
        """Identify the page before acting on its shared purple button."""
        if self.appear(ROGUE_SAVE_TITLE, offset=(18, 12), similarity=0.90):
            self.settlement_title_wait = None
            return 'save'
        if (self.appear(ROGUE_EXPLORE_RESULT, offset=(18, 12), similarity=0.90)
                or (self.appear(ROGUE_REWARD_LEVEL, offset=(18, 12), similarity=0.90)
                    and self.appear(RESULT_CONFIRM, offset=(18, 12), similarity=0.90))):
            self.settlement_title_wait = None
            return 'result'
        try:
            if self.card_reader is None:
                self.card_reader = rogue_cards.CardReader()
            text = rogue_cards.normalize(self.card_reader.read_name(self.device.image, SAVE_TITLE_AREA))
        except Exception as error:
            logger.debug('Can not read the settlement title: %s', error)
            text = ''
        if any(word in text for word in SAVE_TITLE_WORDS):
            self.settlement_title_wait = None
            return 'save'
        if text in RESULT_TITLES or self.rogue_crash_appear():
            self.settlement_title_wait = None
            return 'result'
        wait = getattr(self, 'settlement_title_wait', None)
        if wait is None:
            logger.warning('Unverified settlement title, wait for a readable frame')
            self.settlement_title_wait = Timer(12, count=3).start()
        elif wait.reached():
            self.rogue_dump_unknown()
            raise RequestHumanTakeover('Unable to distinguish the settlement and save pages')

    def rogue_save_trash_visible(self, slot):
        """
        Whether the trash icon of that save card is still there.

        删掉的那张卡会变灰、右边 ☆/🔒/🗑 整列消失，而旁边卡片的图标不会动，
        所以用小框里亮像素的个数判断（在时 ~250，删完 0-6，2026-11-15 实测）。

        Args:
            slot (int): 1-3，队伍位次。

        Returns:
            bool:
        """
        box = SAVE_TRASH_BOX[slot - 1]
        patch = self.device.image[box[1]:box[3], box[0]:box[2]].astype(int)
        bright = int((patch.min(axis=2) > SAVE_TRASH_LIGHT).sum())
        return bright > SAVE_TRASH_MIN

    def rogue_save_handle(self, next_point, *, discard_saves=False):
        """
        Trash one unwanted save, or press the purple `下一步` when nothing is left.

        `RogueSaveKeep`：1/2/3 = 只留该队伍位次的存档，另外两张点垃圾桶分解掉；
        0 或重刷撤退 = 三个全删。**一次只删一张**：点垃圾桶后会立刻弹 `獲得道具`（分解给的
        單元幣）盖住整页，弹窗由通用关闭分支按掉，下一帧再回到这一页继续删；
        等要删的都没了（或一张都不删）才点右下紫色 `下一步`（(1120,662)）。

        Args:
            next_point (tuple[int]): centre of the purple `下一步`.
            discard_saves (bool): Decompose all three saves from this run.
        """
        keep = 0
        if not discard_saves:
            try:
                keep = int(self.config.ChaoszeroRogue_RogueSaveKeep)
            except (AttributeError, TypeError, ValueError):
                pass
        if not 1 <= keep <= len(SAVE_TRASH):
            keep = 0
        for index, point in enumerate(SAVE_TRASH):
            slot = index + 1
            if slot == keep:
                continue
            if not self.rogue_save_trash_visible(slot):
                logger.info('The save of slot %s is already decomposed' % slot)
                continue
            logger.info('Delete the save of slot %s at (%s, %s)'
                        % (slot, point[0], point[1]))
            self.tap_point(point[0], point[1], name='ROGUE_SAVE_TRASH')
            return
        if keep:
            logger.info('Only the save of slot %s is kept' % keep)
        else:
            logger.info('All three saves are deleted')
        logger.info('Press 下一步 on the save page')
        self.tap_point(next_point[0], next_point[1], name='ROGUE_PURPLE')

    def rogue_flash_appear(self):
        """
        Whether this is the in-battle 灵光一闪 三选一 (`請選擇靈光一閃效果。`).

        和「靈光一閃卡牌」奖励页不是同一页：这页三张是**同一张卡的不同闪形态**，
        而且没有 `跳過`，不选战斗就不往下走（2026-11-14 01:37 实测被当成关闭弹窗
        误点了三次）。

        判据是标题 `請選擇靈光一閃效果。`（500,78,780,116），167 帧样本里
        只有这一页 1.000，其余最高 0.328。

        Returns:
            bool: If this frame is the flash chooser.
        """
        return self.appear(ROGUE_FLASH, offset=(10, 6), similarity=0.85)

    def rogue_god_text(self):
        """
        Read the bottom `靈光一閃：<神名>` label, returning '' when it is absent.

        Why OCR: the god art/背景 changes every time (user 2026-11-14: 神闪情况很多，
        背景也不一样), so the text template only scored 0.117 on the 金框维托 page and
        the run stalled there (2026-11-15 00:50). cnocr reads the band well enough to
        tell the page apart — it never has to be exact, only `光` plus `一/阴/閃`.

        Returns:
            str: Raw OCR text of the label band.
        """
        ocr = getattr(self, 'god_ocr', None)
        if ocr is None:
            ocr = Ocr(GOD_TEXT_AREA, lang='cnocr', letter=(255, 255, 255),
                      threshold=GOD_TEXT_THRESHOLD, name='GOD_TEXT')
            ocr.SHOW_LOG = False
            self.god_ocr = ocr
        return ocr.ocr(self.device.image)

    def rogue_god_appear(self):
        """
        Whether this frame is a flash chooser (灵光三选一) that needs a card picked.

        这条标签的模板靠不住：换背景就掉到 0.1x，所以判据是
        「`ROGUE_GOD` 模板命中」**或**「底部标签 OCR 到 `光` 且带 `一/阴/閃`」。
        2026-11-15 00:50 的金框维托页就是模板 0.117、脚本一个字都不点卡住的。

        Returns:
            bool: If this frame is a flash chooser.
        """
        if self.appear(ROGUE_GOD, offset=(20, 20), similarity=0.80):
            return True
        text = self.rogue_god_text().replace(' ', '')
        if len(text) >= 4 and '光' in text and ('一' in text or '阴' in text or '閃' in text or '闪' in text):
            logger.info('Flash chooser detected via OCR: %s' % text)
            return True
        return False

    def rogue_spark_filter(self):
        """
        Parse `RogueSparkFilter`: one card per line, `卡名 = 关键词1,关键词2`.

        灵光三选一的三个选项永远是**同一张卡**的不同形态（用户 2026-11-14），
        所以配置只能写「想要的效果词」，不能写卡名去选列。

        Returns:
            dict: {card name: [keyword, ...]}
        """
        # ❗`textarea` 类型的参数**没有** `ChaoszeroRogue_RogueSparkFilter` 属性
        # （`getattr` 永远拿到 `config_generated.py` 里的默认值 `None`），
        # 必须从 `config.data` 的嵌套 dict 里取：`data['ChaoszeroRogue']['ChaoszeroRogue']`
        # （`args.json` 里参数段本身也叫 `ChaoszeroRogue`）。
        # 2026-11-16 实测：配置文件里有 1435 字符，`getattr` 读到 None、规则 0 条。
        text = ''
        try:
            node = self.config.data.get('ChaoszeroRogue', {}) or {}
            node = node.get('ChaoszeroRogue') or node
            text = str(node.get('RogueSparkFilter') or '')
        except Exception as error:
            logger.warning('Failed to read RogueSparkFilter from config.data: %s' % error)
            text = str(getattr(self.config, 'ChaoszeroRogue_RogueSparkFilter', '') or '')
        table = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            name, words = line.split('=', 1)
            keywords = [word.strip() for word in re.split(r'[,，、;；\s]+', words) if word.strip()]
            if name.strip() and keywords:
                table[name.strip()] = keywords
        return table

    def rogue_event_index(self, points):
        """
        Match the current event to a configured option; never choose by position.

        无法识别事件、没有规则或当前页缺少配置选项时返回 None，由调用方保存并停机。

        Args:
            points (list[tuple]): Option card bottom-border centres from `rogue_option_points()`.

        Returns:
            int: 1-based card index, or None.
        """
        self.event_choice = None
        self.event_last_enc = None
        self.event_unknown = False
        self.event_missing_pick = None
        if not self.config.ChaoszeroRogue_RogueEventPick:
            self.event_unknown = True
            return None
        if self.event_library is None:
            self.event_library = rogue_events.EventLibrary()
        if self.card_reader is None:
            self.card_reader = rogue_cards.CardReader()

        world = self.config.ChaoszeroRogue_RogueWorld
        packs = rogue_events.packs_for_world(world)

        image = self.device.image
        texts = []
        for x, y in points:
            area = (max(0, x + EVENT_TITLE[0]), max(0, y + EVENT_TITLE[1]),
                    min(1280, x + EVENT_TITLE[2]), min(720, y + EVENT_TITLE[3]))
            texts.append(rogue_cards.normalize(self.card_reader.read_name(image, area)))
        self.event_texts = texts

        # 记录这一页的原始 OCR 文本与候选排名，用来统计识别正确率
        # （2026-11-15 用户：把整局的事件都匹配一遍看正确率）。
        self.rogue_event_record(points, texts, packs)

        # The pending selection protects a lifted card from re-identification.
        # A completed option clears the cache, even if the next page has the
        # same card positions. Do not lock a choice to an entire map node.
        manual = self.rogue_event_manual_index(texts, packs)
        if manual is not None:
            self.event_unknown = False
            return manual
        if self.event_missing_pick:
            return None

        # ③ 先确认这一页**到底是不是事件页**：一页里有 ≥1 张卡就对不上任何事件，
        # 说明多半不是事件选项卡 —— 复制卡牌页 / 选一张卡灵光 这类**卡牌网格**
        # 也会被 `rogue_option_points()` 检出卡框，以前会掉进 `RoguePick` 按位置乱选一张，
        # 等于把这些素材白给了（用户 2026-11-16：「就怕遇到了直接跳过了，那样永远
        # 拿不到这个素材」）。这里标出来，让调用方停住 + 存帧。
        ranked = self.event_library.candidates(texts, packs)
        if not ranked:
            self.event_unknown = True
            logger.warning('No event matches this page (%s card(s)), maybe a card grid. '
                           'Stop and save a frame instead of picking blindly.' % len(texts))
            return None
        self.event_unknown = True
        logger.warning('Event has candidates but no matching configured option; stop for review')
        return None

    def rogue_event_picks(self):
        """
        Load `config/rogue/rogue_event_picks.json`（选择器导出的那份），只读一次。

        Returns:
            dict: Event IDs mapped to visit sequences or same-page priority rules.
        """
        if self.event_picks is not None:
            return self.event_picks
        import json as json_module
        import os

        self.event_picks = {}
        path = EVENT_PICKS_FILE
        if not os.path.exists(path) and os.path.exists(EVENT_PICKS_LEGACY):
            path = EVENT_PICKS_LEGACY
            logger.warning('%s is deprecated and shows up as a bogus Alas config, '
                           'please move it to %s'
                           % (EVENT_PICKS_LEGACY, EVENT_PICKS_FILE))
        if not os.path.exists(path):
            logger.warning('No %s, event selection will stop for review' % path)
            return self.event_picks
        try:
            # ❗`utf-8-sig`：浏览器下载的 picks、PowerShell 手写的 json 都可能带 BOM，
            # 用 `utf-8` 读会抛 `Unexpected UTF-8 BOM`，整个 picks 静默失效。
            with open(path, encoding='utf-8-sig') as handle:
                payload = json_module.load(handle)
            picks = payload.get('picks') or payload
            # 值可以是**数字**（每次都用这张）或**数组**（第 1 次用 [0]、第 2 次用 [1]…，
            # 用完就一直用最后一个）。数组是为"反复事件"准备的 —— 比如虛無牧者要
            # "伸入深處 1 次 → 更深處 → 最深處 → 取出"，四个步骤是同一个事件的不同轮次。
            # 用户 2026-11-15：反复几次由**选择器**决定，脚本不做这个决策。
            # priority 对象在同一画面按偏好查找，而数组按事件访问轮次取值。
            self.event_picks = {}
            for key, value in picks.items():
                if isinstance(value, bool):
                    continue
                if isinstance(value, (int, float)):
                    self.event_picks[str(key)] = [int(value)]
                elif isinstance(value, (list, tuple)) and value:
                    self.event_picks[str(key)] = [int(item) for item in value]
                elif isinstance(value, dict) and value.keys() == {'priority'}:
                    orders = value['priority']
                    if (isinstance(orders, list) and orders
                            and all((type(key) is int and 0 < key < 9999)
                                    or (isinstance(key, str) and key and rogue_cards.normalize(key) == key)
                                    for key in orders)
                            and len(set(orders)) == len(orders)):
                        self.event_picks[str(key)] = value
            logger.info('Loaded %s event pick(s) from %s'
                        % (len(self.event_picks), path))
        except Exception as error:
            logger.warning('Failed to read %s: %s' % (path, error))
        return self.event_picks

    def rogue_event_identity(self, texts, packs):
        """Resolve the event from the page and confirmed continuation."""
        ranked = self.event_library.candidates(texts, packs, limit=None)
        if not ranked:
            return None
        strongest = [candidate for candidate in ranked if candidate[0] == ranked[0][0]]
        if self.event_followups:
            strongest = [candidate for candidate in strongest if candidate[1] in self.event_followups]
        if len(strongest) > 1:
            compatible = []
            for candidate in strongest:
                options = self.event_library.records[candidate[1]]['options']
                required = {rogue_cards.normalize(option.get('flavor')) for option in options
                            if option.get('select_type') == 'DEFAULT' and not option.get('appear_conditions')}
                if all(any(rogue_events.ratio(text, title) >= rogue_events.OPTION_MATCH for text in texts)
                       for title in required if title):
                    compatible.append(candidate)
            strongest = compatible
        if len(strongest) == 1:
            return strongest[0]
        if strongest:
            score, event_id, name, pack = strongest[0]
            shared = self.event_library.shared_choice_ids(event_id)
            if all(candidate[1] in shared for candidate in strongest):
                logger.info('Equivalent event pages for %s, use shared choice %s', name, shared[0])
                return score, shared[0], name, pack
        logger.warning('No unique event identity for %s (matches: %s, expected: %s)'
                       % (texts, [candidate[1] for candidate in strongest], self.event_followups))
        return None

    def rogue_event_manual_index(self, texts, packs):
        """Return a configured card only for a uniquely identified event."""
        self.event_choice = None
        self.event_last_enc = None
        self.event_missing_pick = None

        identity = self.rogue_event_identity(texts, packs)
        if identity is None:
            return None
        _, enc_id, name, _ = identity
        picks = self.rogue_event_picks()
        group = self.event_library.shared_choice_ids(enc_id)
        rules = [picks[key] for key in group if key in picks]
        rule = rules[0] if rules else None
        if any(other != rule for other in rules[1:]):
            logger.warning('Conflicting shared choices for %s; reselect this event in the selector', name)
            return None
        if not rule:
            self.event_missing_pick = (enc_id, name)
            return None
        round_index = self.event_visit.get(enc_id, 0)
        priority = isinstance(rule, dict)
        orders = rule['priority'] if priority else [rule[min(round_index, len(rule) - 1)]]
        options = self.event_library.records[enc_id]['options']
        titles = [rogue_cards.normalize(option.get('flavor')) for option in options]
        stages = EVENT_GUIDED_VARIANTS.get(enc_id, ())
        for key in orders:
            if isinstance(key, str):
                order, target = None, key
                matching = [option for option, title in zip(options, titles) if title == target]
                if len(matching) < 2:
                    continue
            else:
                order = key
                matches = [(option, title) for option, title in zip(options, titles)
                           if option.get('order') == order]
                if len(matches) != 1:
                    continue
                option, target = matches[0]
                guided_variant = not priority and round_index < len(stages) and order in stages[round_index]
                if titles.count(target) != 1 and not guided_variant:
                    logger.warning('Ambiguous event option %s for %s; reselect it in the event selector'
                                   % (order, enc_id))
                    continue
                matching = [option]
            if not target or any(option.get('order') == 9999
                                 or 'ATTACK' in (option.get('select_type'), option.get('option_type'))
                                 for option in matching):
                continue
            scores = [rogue_events.ratio(text, target) for text in texts]
            score = max(scores, default=0.0)
            if score < rogue_events.OPTION_MATCH or scores.count(score) != 1:
                continue
            position = scores.index(score)
            # Similar titles must compete against the whole encounter.
            if any(rogue_events.ratio(texts[position], title) >= score
                   for title in set(titles) if title != target):
                continue
            self.event_last_enc = enc_id
            self.event_choice = {
                'source': 'configured', 'id': enc_id, 'name': name,
                'round': round_index + 1, 'order': order, 'target': target,
                'position': position + 1, 'text': texts[position],
            }
            logger.info('Event %s (%s), round %s -> user pick option %s `%s` at card %s (%.2f)'
                        % (enc_id, name, round_index + 1, order, target, position + 1, score))
            return position + 1
        logger.warning('No verified configured option %s for event %s; stop for review' % (orders, enc_id))
        return None

    def rogue_event_confirmed(self):
        """Advance a configured sequence once, after the submitted checkmark clears."""
        choice = self.event_pending_choice
        self.event_followups = set()
        if choice is not None:
            enc_id = choice.get('id')
            if enc_id:
                self.event_visit[enc_id] = self.event_visit.get(enc_id, 0) + 1
                record = self.event_library.records.get(enc_id) or {}
                for option in record.get('options', []):
                    if choice['order'] is None:
                        matches = rogue_cards.normalize(option.get('flavor')) == choice['target']
                    else:
                        matches = option.get('order') == choice['order']
                    if matches:
                        for field in ('success_link_encounter_option_eff', 'fail_link_encounter_option_eff'):
                            child = (option.get('raw', {}).get(field) or {}).get('next_encounter')
                            if isinstance(child, str):
                                self.event_followups.add(child)
            logger.info('Event choice submitted: %s' % choice)
        self.event_pending_choice = None
        self.event_last_enc = None
        self.event_choice = None
        self.option_pending = None
        self.event_page = None
        self.event_index = None
        self.event_submit_wait = None
        self.event_submit_clear.clear()
        self.event_submit_attempts = 0

    def handle_rogue_event(self, press):
        """Select and submit one recognized event page, without stale positions."""
        if self.event_submit_wait is not None:
            x, _ = self.option_pending
            point = self.rogue_option_check_point(x)
            if point is None:
                if self.event_submit_clear.start().reached():
                    self.rogue_event_confirmed()
                    return True
            else:
                self.event_submit_clear.clear()
            if self.event_submit_wait.reached():
                self.rogue_dump_unknown()
                raise TaskFailed('Event confirmation did not leave the selected state; stop for review')
            if point and self.event_submit_attempts < EVENT_CONFIRM_ATTEMPTS and press.reached():
                press.reset()
                self.event_submit_attempts += 1
                logger.info('Retry the event confirmation (attempt %s)' % self.event_submit_attempts)
                self.tap_point(*point, name='ROGUE_OPTION_CONFIRM')
            return True
        if self.option_pending:
            x, wait = self.option_pending
            point = self.rogue_option_check_point(x)
            if point and press.reached():
                press.reset()
                logger.info('Confirm the selected option at (%s, %s)' % point)
                self.tap_point(*point, name='ROGUE_OPTION_CONFIRM')
                self.event_submit_wait = Timer(8, count=4).start()
                self.event_submit_attempts = 1
            elif wait.reached():
                logger.warning('The option card did not show the checkmark, retry without advancing')
                self.option_pending = None
                self.event_pending_choice = None
                self.event_page = None
                self.event_index = None
            return True
        points = self.rogue_option_points()
        if not points:
            self.event_page = None
            return False
        key = tuple(points)
        if key != self.event_page:
            self.event_page = key
            self.event_index = self.rogue_event_index(points)
        if self.event_unknown or self.event_index is None or self.event_choice is None:
            self.rogue_dump_unknown()
            if self.event_missing_pick:
                event_id, name = self.event_missing_pick
                world = self.config.ChaoszeroRogue_RogueWorld
                message = (
                    f'{world}「{name}」({event_id}) 缺少选择。'
                    f'请在事件选择器配置这个分支并导出到 {EVENT_PICKS_FILE}。')
                logger.warning(message)
                raise RequestHumanTakeover(message)
            raise TaskFailed('Event has no verified configured choice, stop for user review')
        check = self.rogue_option_check_any()
        if check:
            self.rogue_dump_unknown()
            raise TaskFailed('Event option was selected without a verified pending choice, stop for user review')
        if not press.reached():
            return True
        press.reset()
        index = self.event_index
        if not 1 <= index <= len(points):
            self.rogue_dump_unknown()
            raise TaskFailed('Event choice is outside the current page, stop for review')
        x, y = points[index - 1]
        self.event_pending_choice = self.event_choice
        logger.info('Select option %s of %s at (%s, %s), decision=%s'
                    % (index, len(points), x, y - OPTION_LIFT, self.event_pending_choice))
        self.tap_point(x, y - OPTION_LIFT, name='ROGUE_OPTION')
        self.option_pending = (x, Timer(6, count=1).start())
        return True

    def rogue_event_record(self, points, texts, packs):
        """
        Dump one event page for later accuracy review.

        ❗**只记录，不影响选卡**。每页存一条 JSON（OCR 文本、前 5 名候选事件、
        最终选中项）和一张截图，跑完一局就能逐页核对"识别对不对"。

        Args:
            points (list[tuple]): Card centres from `rogue_option_points()`.
            texts (list[str]): Normalized OCR titles, same length as `points`.
            packs (tuple[str]): Packs searched (this map + common).
        """
        import json as json_module
        import os
        import time

        try:
            if not os.path.exists(EVENT_LOG_DIR):
                os.makedirs(EVENT_LOG_DIR)
            stamp = time.strftime('%H%M%S')
            ranked = self.event_library.candidates(texts, packs)
            record = {
                'time': time.strftime('%Y-%m-%d %H:%M:%S'),
                'world': self.config.ChaoszeroRogue_RogueWorld,
                'packs': list(packs or ()),
                # ❗points 是 numpy 标量，`json.dump` 会在这一项直接抛异常，
                # 结果文件只写到一半（14 个记录全是断在 points 后面，
                # texts/candidates 全丢）。必须逐个转 int。
                'points': [[int(v) for v in point] for point in points],
                'texts': texts,
                'candidates': [
                    {'mean': round(mean, 3), 'id': key, 'name': name, 'pack': pack}
                    for mean, key, name, pack in ranked
                ],
            }
            base = os.path.join(EVENT_LOG_DIR, '%s_%s' % (stamp, len(texts)))
            # 先序列化成字符串再落盘：序列化失败时不会留下半截文件
            # （之前 14 个记录全是断在 points 处的坏 JSON，白跑一局）。
            payload = json_module.dumps(record, ensure_ascii=False, indent=1)
            with open(base + '.json', 'w', encoding='utf-8') as handle:
                handle.write(payload)
            cv2.imwrite(base + '.png',
                        cv2.cvtColor(self.device.image, cv2.COLOR_RGB2BGR))
            prune_diagnostics(EVENT_LOG_DIR, 'event')
            logger.info('Event page logged to %s.json (%s candidate(s))'
                        % (base, len(ranked)))
        except Exception as error:
            logger.warning('Failed to log the event page: %s' % error)

    def rogue_flash_column(self, scale=1.0):
        """
        Pick the flash form column that best fits the card.

        Args:
            scale (float): 提字前放大描述区的倍数。**神闪传 1.8**：
                离线复盘（2026-11-16，18 页有字样本）实测
                1.0 → 50.0% / 1.4 → 55.6% / **1.8 → 61.1%** / 2.2 → 55.6%。
                普通灵光放大没收益（1.0 与 1.8 都是 83.3%，2.2 掉到 75%），
                所以只有神闪分支传 1.8。

        面板三列永远是同一张卡的不同形态，描述是白字多行，所以要切行 OCR
        （框架的 Ocr 只喂单行模型），再用 `rogue_cards` 里的形态库当词典：
        先认出这张卡（余量不够就当没认出，绝不猜卡），再定目标形态，最后看哪
        一列的文本跟目标形态最像。实测四张卡 5/5 挑对列（0.76 / 0.53 / 0.62 / 0.78 / 0.64）。

        目标形态的来源（用户 2026-11-15：关键词由脚本自己写，只要不认错卡）：
            RogueSparkFilter 里写了这张卡 -> 用这些关键词筛形态
            没写（或整张表为空）      -> `CardLibrary.default_form()` 取数值最大的形态

        Returns:
            int: 1-based column, or None when nothing can be recognised.
        """
        self.spark_selected = None
        self.spark_visible_card = None
        table = self.rogue_spark_filter()
        # ❗配置读没读到自己看：`RogueSparkFilter` 是纯文本配置，
        # 写错格式（比如全角等号）就会静默解析成 0 条，行为退回"数值最大"。
        logger.info('Spark filter has %s rule(s)', len(table))
        if self.card_library is None:
            self.card_library = rogue_cards.CardLibrary()
        if self.card_reader is None:
            self.card_reader = rogue_cards.CardReader()
        card = None
        score = margin = 0
        texts = None
        # 面板会先淡入，第一帧常读到空文本（2026-11-15 06:33 读到 0.00 就直接按
        # RoguePick 点了第 1 张，下一帧才认出 1.00），所以先重读两帧再放弃。
        for attempt in range(FLASH_READS):
            if attempt:
                self.device.screenshot()
            texts = self.card_reader.read_all(self.device.image, scale=scale)
            if not any(texts):
                continue
            card, score, margin = self.card_library.identify(texts)
            if card:
                break
        if not any(texts or ()):
            return None
        if not card:
            logger.info('Flash card not recognised (%.2f, margin %.2f), keep RoguePick' % (score, margin))
            return None
        self.spark_visible_card = card
        # ❗**三列分别识别成了什么**（用户 2026-11-16 要求）：
        # 只有把每列的 OCR 和它匹配到的 `rspN` 都打出来，事后才能分清三种情况 ——
        #   ① 想要的灵闪根本没出现在这三列里（游戏没闪到）
        #   ② 出现了但没认出来（OCR/匹配失败）
        #   ③ 认出来了却没选它（选择逻辑的问题）
        logger.info('Flash card %s (score %.2f, margin %.2f)', card, score, margin)
        forms, _raw = self.card_library.forms(card)
        try:
            for column, ratio, index in self.card_library.read_columns(texts, card):
                logger.info('  col%s -> rsp%s (%.2f) %s'
                            % (column + 1, index + 1, ratio,
                               (forms[index] if index < len(forms) else '')[:34]))
            for column, text in enumerate(texts, 1):
                logger.info('  col%s OCR: %s' % (column, (text or '')[:38]))
        except Exception as error:
            logger.warning('Failed to dump the flash columns: %s' % error)

        if card in table:
            # ❗配置支持两种写法：
            #   卡名 = 2            按**编号**指定（游戏卡详情里 ①②③④⑤，对应 rsp1~rsp5）
            #   卡名 = 額外打擊      按**关键词**指定（老写法，向后兼容）
            # 编号优先。指定的形态**没闪出来**时 `pick_column` 返回 None，
            # 走下面的回退（随机/`RoguePick`）—— 这是用户要的「没闪到才随机」。
            rules = table[card]
            form_index = None
            if rules and rules[0].strip().isdigit():
                form_index = int(rules[0].strip()) - 1
                if not 0 <= form_index <= 4:
                    form_index = None
                if form_index is not None:
                    logger.info('  want: rsp%s (from RogueSparkFilter)', form_index + 1)
            picked = self.card_library.pick_column(
                texts, None if form_index is not None else rules, card, form_index)
            if picked:
                if card in self.meditate_pending:
                    self.meditate_pending.remove(card)
                    logger.info('Meditation target satisfied: %s; pending: %s'
                                % (card, self.meditate_pending))
            elif len(self.card_library.read_columns(texts, card)) == len(texts):
                # 认得清三列，但没有一列是想要的效果 -> 这张卡已经闪歪了，
                # 只在属于人物灵光优先位选定角色时才加入冥想重掷队列。
                if self._rogue_meditate_allows(card):
                    if card not in self.meditate_pending:
                        self.meditate_pending.append(card)
                    logger.info('Pending meditation cards: %s' % self.meditate_pending)
                else:
                    logger.info('Skip meditation queue for %s (not owned by RogueMember slot)' % card)
                # ❗这句是「闪到了但没闪出我要的那一种」，和上一条「没认出卡」要分开：
                # 前者说明识别正常、只是这次随机没给，不需要修；
                # 后者才是识别问题。
                logger.info('Flash card %s: wanted form is NOT among the three, '
                            'fall back to RoguePick (will reroll it at the next 冥想)' % card)
        else:
            picked = self.card_library.pick_column(texts, name=card)
        if not picked:
            logger.info('No flash form matches %s, keep RoguePick' % card)
            return None
        column, ratio, index, raw = picked
        if card in table and table[card] == getattr(self, 'spark_targets', {}).get(card):
            self.spark_selected = card
        logger.info('Flash card %s, take column %s (library form %s, %.2f) %s'
                    % (card, column + 1, index + 1, ratio, raw[:24]))
        return column + 1

    def rogue_choose_flash(self, god=False):
        column = self.rogue_flash_column(scale=1.8 if god else 1.0)
        if self.spark_pending:
            if self.spark_visible_card and self.spark_visible_card != self.spark_pending:
                self.rogue_spark_confirm()
            elif self.spark_selected != self.spark_pending:
                # An unreadable or unchanged chooser cannot confirm the previous choice.
                return
        index = column or (self.rogue_god_pick() if god else None) or self.rogue_pick_index()
        logger.info('Pick column %s on the %sflash page' % (index, 'god ' if god else ''))
        if self.rogue_pick(FLASH_POINTS, index) and self.spark_selected:
            self.spark_pending = self.spark_selected

    def rogue_spark_confirm(self):
        if self.spark_pending:
            self.spark_obtained.add(self.spark_pending)
            logger.info('Obtained target flash for %s' % self.spark_pending)
            self.spark_pending = None

    def rogue_spark_restart_on_core_map(self):
        if not self.spark_boss_pending:
            return False
        self.spark_boss_pending = False
        missing = self.spark_targets.keys() - self.spark_obtained
        self.spark_targets = {}
        if not missing:
            return False
        logger.info('Missing target flash after the first boss: %s' % ', '.join(sorted(missing)))
        if not self.rogue_quit(timeout=300, discard_saves=True):
            logger.warning('Spark reroll retreat did not reach the lobby or team, stop for review')
            self.stopped_by_stuck = True
        return True

    def rogue_god_pick(self):
        """
        Which of the three flash forms is the 神闪, by the magenta description box.

        神闪的卡面没有固定模板（用户 2026-11-14：神闪情况很多，背景也不一样），
        但这三张是同一张卡的三种形态，只有神闪那张的描述区带品红/紫底色，其余
        两张的文字直接压在立绘上。所以按描述区里品红文字的占比取最大者，并要求
        够高、够明显，否则返回 None 交给 `RoguePick`：
            drive_017 神闪=3 -> 0.0214 / 0.0034 / 0.0013（判定 3，实际 3）
            t14       神闪=1 -> 0.0012 / 0.0005 / 0.0005（不够明显，回退配置）

        Returns:
            int: 1-based index, or None when the cards cannot be told apart.
        """
        image = self.device.image.astype('int32')
        y1, y2 = GOD_DESC
        shares = []
        for x1, x2 in GOD_COLUMNS:
            patch = image[y1:y2, x1 + 15:x2 - 15]
            r, g, b = patch[:, :, 0], patch[:, :, 1], patch[:, :, 2]
            mask = (r > 150) & (b > 110) & (g < 120) & (r > g + 40)
            shares.append(float(mask.mean()))
        order = sorted(range(3), key=lambda i: shares[i], reverse=True)
        best, second = shares[order[0]], shares[order[1]]
        if best < GOD_MAGENTA_MIN or best < second * GOD_MAGENTA_RATIO:
            logger.info('God card not separable (magenta %s), fall back to RoguePick'
                        % ['%.4f' % value for value in shares])
            return None
        logger.info('God card looks like card %s (magenta %s)'
                    % (order[0] + 1, ['%.4f' % value for value in shares]))
        return order[0] + 1

    def rogue_option_points(self):
        """
        Locate the event option cards by the sparse light line under each card.

        Returns:
            list[tuple]: (x, y) badge-line centres, left to right (empty if this is
            not the option page).
        """
        image = self.device.image
        x1, y1, x2, y2 = OPTION_BAND
        band = image[y1:y2, x1:x2].astype(int)
        mask = (band.min(axis=2) > OPTION_LIGHT).astype('uint8')
        count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)

        raw = []
        for i in range(1, count):
            x, y, w, h, area = stats[i]
            if y + y1 < OPTION_BORDER_TOP:
                continue
            if not OPTION_HEIGHT[0] <= h <= OPTION_HEIGHT[1]:
                continue
            if area < 250 or area / float(w * h) > OPTION_FILL:
                continue
            if w < 80:
                continue
            raw.append((x + x1, y + y1, w, h))
        raw.sort()

        # ❗**先把被拆开的分段拼回去**：有的选项卡底部装饰线是断开的 ——
        # 实测 `unknown_081436`（沉睡的怪物/巨大的門 那页）是
        # `(314,681) 148x11 / (482,681) / (650,681) / (818,681)`，4 段每段只有 148 宽、
        # 段间空隙 20px，两段才是一张卡（316 宽）。旧逻辑直接拿单段去比
        # `OPTION_WIDTH = (240,470)`，**全被过滤 → 整页认不出 → 40 秒后停任务**。
        merged = []
        for item in raw:
            if merged:
                prev = merged[-1]
                gap = item[0] - (prev[0] + prev[2])
                width = item[0] + item[2] - prev[0]
                # ❗**合并后不能超过 OPTION_WIDTH 上限**：这页 4 段的宽度是
                # 169 / 149 / 169 / 149，段间空隙 0 / 18 / 0 —— 只看空隙会把
                # 两张卡（505 宽）也拼成一段，然后被宽度上限过滤掉。
                # 加上 `width <= 上限` 之后正好是"两段一张卡"（318 宽）。
                if gap <= 30 and width <= OPTION_WIDTH[1]:
                    merged[-1] = (prev[0], min(prev[1], item[1]),
                                  width, max(prev[3], item[3]))
                    continue
            merged.append(item)

        points = []
        for x, y, w, h in merged:
            if not OPTION_WIDTH[0] <= w <= OPTION_WIDTH[1]:
                continue
            sub = mask[y - y1:y - y1 + h, x - x1:x - x1 + w]
            if not sub.size or float(sub.sum(axis=1).max()) / float(w) < OPTION_FLAT_RATIO:
                continue
            points.append((x + w // 2, y))

        points.sort()
        # 1 张也要认：航点（`啟用航點 獲得裝備[...]`）就是单独一张卡，实测同样是
        # 320x21、填充率 9% 的边框。
        return points

    def rogue_option_check_point(self, x):
        """
        Locate the gold checkmark under the option card we just selected.

        Args:
            x (int): x of the selected card, the checkmark sits under the same column.

        Returns:
            tuple[int, int] | None: checkmark centre.
        """
        image = self.device.image
        y1, y2 = OPTION_BAND[1], OPTION_BAND[3]
        left = max(OPTION_BAND[0], x - OPTION_CHECK_OFFSET)
        right = min(OPTION_BAND[2], x + OPTION_CHECK_OFFSET)
        band = image[y1:y2, left:right].astype(int)
        mask = (band.min(axis=2) > OPTION_CHECK_LIGHT).astype('uint8')
        count, _, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
        (w_min, w_max), (h_min, h_max), (a_min, a_max) = OPTION_CHECK_SIZE

        for i in range(1, count):
            width, height, area = stats[i][2], stats[i][3], stats[i][4]
            if not w_min <= width <= w_max or not h_min <= height <= h_max:
                continue
            if not a_min <= area <= a_max:
                continue
            return int(centroids[i][0] + left), int(centroids[i][1] + y1)
        return None

    def rogue_remove_ready(self):
        """
        Locate the orange `移除` button once a card has been picked on the removal page.

        选中卡片会让整页压暗，`ROGUE_REMOVE` 标题模板可能掉到 0.93 以下（2026-11-15
        实机 03:53: 选中后判据变 False，`移除` 一次都没按下去）。橙色 `移除` 只在
        这一页出现（bbox 220x50、面积 ~10000，中心 1150,669），左侧那颗 `提煉` 是
        深红（g≈60），被 g>105 挡住，所以拿它当第二判据。

        Returns:
            tuple[int, int] | None: 移除 button centre.
        """
        image = self.device.image
        x1, y1, x2, y2 = REMOVE_OK_AREA
        band = image[y1:y2, x1:x2].astype(int)
        mask = ((band[:, :, 0] > 195) & (band[:, :, 1] > 105)
                & (band[:, :, 1] < 205) & (band[:, :, 2] < 95)).astype('uint8')
        count, _, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)

        for i in range(1, count):
            width, height, area = stats[i][2], stats[i][3], stats[i][4]
            if area < 2000 or not 140 <= width <= 320 or not 30 <= height <= 90:
                continue
            return int(centroids[i][0] + x1), int(centroids[i][1] + y1)
        return None

    def rogue_option_check_any(self):
        """
        Locate the gold checkmark anywhere under the option cards.

        选中的卡会上抬 ~12px，底边框离开 `OPTION_BAND`（682 → 652），所以「按边框
        找卡」会漏掉已经选中的那张（2026-11-15 实机 live_A 三张只认出两张）。金色 ∨
        本身是 33x24、面积 120~160 的暖白小块（亮部 RGB 249,244,195），战斗页手牌
        小徽标是 27x20 / 19x20、亮部 b≈236~253，所以加一道「暖色 b<215」的门槛。

        Returns:
            tuple[int, int] | None: checkmark centre.
        """
        image = self.device.image
        x1, y1, x2, y2 = OPTION_BAND
        band = image[y1:y2, x1:x2].astype(int)
        mask = (band.min(axis=2) > OPTION_CHECK_LIGHT).astype('uint8')
        count, _, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)

        for i in range(1, count):
            x, y, width, height, area = stats[i]
            if not OPTION_ANY_WIDTH[0] <= width <= OPTION_ANY_WIDTH[1]:
                continue
            if not OPTION_ANY_HEIGHT[0] <= height <= OPTION_ANY_HEIGHT[1]:
                continue
            if not OPTION_ANY_AREA[0] <= area <= OPTION_ANY_AREA[1]:
                continue
            patch = band[y:y + height, x:x + width].reshape(-1, 3)
            bright = patch[patch.min(axis=1) > 170]
            if not len(bright):
                continue
            mean = bright.mean(axis=0)
            if mean[2] >= OPTION_ANY_BLUE:
                continue
            return int(centroids[i][0] + x1), int(centroids[i][1] + y1)
        return None

    def rogue_route_style(self):
        """
        Route weight preset.

        ❗**第二面（核心）固定「优先事件」**，不看配置（用户 2026-11-15：
        「第 2 面固定事件优先，避开精英怪，这个是底层逻辑」）。理由：核心那张图
        打的是事件收益，战斗只会磨血；而且这一面是收尾，多打一场没有额外好处。

        Returns:
            str: one of rogue_route.ROUTE_STYLES.
        """
        if getattr(self, 'core_started', False):
            return rogue_route.ROUTE_EVENT
        value = getattr(self.config, 'ChaoszeroRogue_RogueRoute', None)
        if value in rogue_route.ROUTE_STYLES:
            return value
        return rogue_route.ROUTE_BALANCE

    def rogue_route_state(self):
        """
        Current run state used by the route scorer.

        Only what we can already read is filled in: the effort-dependent parts
        (junk cards to remove, whether the target card still needs its spark)
        stay False until the deck reader exists, so the plan is a pure node-type
        preference.

        Returns:
            dict: see rogue_route.score().
        """
        # ❗第二面（核心）**强制避开精英**，不看配置（用户 2026-11-15：
        # 「第 2 面固定事件优先，避开精英怪，这个是底层逻辑」）。
        return {
            'avoid_elite': (True if getattr(self, 'core_started', False)
                            else bool(getattr(self.config,
                                              'ChaoszeroRogue_RogueAvoidElite', True))),
            'meditate': bool(getattr(self.config, 'ChaoszeroRogue_RogueMeditate', True)),
            'junk': False,
            'need_spark': False,
            'credits': 0,
        }

    def rogue_route_read(self):
        """
        Read the whole route by dragging the 2D preview from the pin rightwards.

        打开预览时画面停在队伍当前的位置（图钉），左边是已经走过的暗节点，读不到，
        所以不再回卷一屏一屏往右拖：每一屏读一遍节点，用两屏重合的节点估出位移，
        拼成一张图（2026-11-14 21:1x 回卷版本在左端读到 0 节点，循环空转 8 分钟）。

        Returns:
            list[RouteNode]: the whole remaining map, already filed into tiers.
        """
        # 一次扫描要拖 10 次左右，框架的连点保护（15 次记录里同名 12 次就报错）会
        # 把整段读图判成卡死，这里读之前把记录清掉（2026-11-14 20:32 撞过）。
        self.device.click_record_clear()

        nodes = []
        edges = []
        offset = 0
        empty = 0
        for index in range(ROUTE_SCANS):
            self.device.screenshot()
            current = rogue_route.read_nodes(self.device.image)
            # 连线也要读：只有白线相通的格子才能走（用户 2026-11-15 指出）。
            # read_edges 返回的是**当前屏 nodes 的下标对**，等 merge_nodes 给出
            # mapping 之后再转成全局下标，避免依赖坐标（拖动位移有误差）。
            screen_edges = (rogue_route.read_edges(self.device.image, current)
                            if current else [])
            added = 0
            if current:
                added, mapping = rogue_route.merge_nodes(nodes, current, offset)
                for pair in screen_edges:
                    if (len(pair) == 2 and pair[0] < len(mapping)
                            and pair[1] < len(mapping)):
                        edges.append((mapping[pair[0]], mapping[pair[1]]))
            logger.info('Route screen %s: %s nodes, %s new, %s total'
                        % (index + 1, len(current), added, len(nodes)))
            if current:
                empty = 0
            else:
                # 空屏不等于到边：可能是过场/淡出，连着两屏空才收工。
                empty += 1
                if empty > 1:
                    break
            if current and added == 0 and index:
                # 这一屏没有新节点 = 已经拖到地图右端。
                logger.info('Reached the right end of the route, %s nodes' % len(nodes))
                break
            if index + 1 >= ROUTE_SCANS:
                break        # 只读一屏时不拖动（用户 2026-11-15：不滑动，分段读）
            self.device.swipe(ROUTE_SCROLL[0], ROUTE_SCROLL[1],
                              name='ROGUE_ROUTE_SCROLL')
            self.device.click_record_clear()
            self.wait_until_still(rogue_route.ROUTE_AREA, timeout=2)
            offset += rogue_route.TIER_SPACING

        nodes.sort(key=lambda node: (node.x, node.y))
        rogue_route.fill_grid(nodes)
        self.route_edges = edges
        logger.info('Route edges: %s' % len(edges))
        return nodes

    def rogue_route_plan(self):
        """
        Read the whole route once per floor and score every tier.

        Reading per node was wasted work (the plan cannot change between two
        nodes of the same tier) and cost a preview round trip every step, so the
        plan is read once and reused until it is used up or the map refuses a
        press. The 2D preview is read-only, so this is open preview -> scan ->
        score -> back to 3D.

        Returns:
            bool: If the route was read.
        """
        logger.hr('Route plan', level=2)
        if not self.rogue_map_preview_appear():
            self.tap_point(ROUTE_OPEN_POINT[0], ROUTE_OPEN_POINT[1], name='ROGUE_ROUTE_OPEN')
            if not self.wait_until_appear(ROGUE_PREVIEW, offset=(10, 8),
                                          timeout=ROUTE_OPEN_TIMEOUT, settle=1):
                # 小地图面板有时是收起的，面板里的 ⊕ (509,470) 就不存在，点空。
                # 先点左下角那块把面板展开，再点一次 ⊕（2026-11-15 06:32 / 06:36 两次点空）。
                logger.info('The minimap panel looks collapsed, open it first')
                self.tap_point(ZOOM_POINT[0], ZOOM_POINT[1], name='ROGUE_ROUTE_PANEL')
                self.tap_point(ROUTE_OPEN_POINT[0], ROUTE_OPEN_POINT[1], name='ROGUE_ROUTE_OPEN')
                if not self.wait_until_appear(ROGUE_PREVIEW, offset=(10, 8),
                                              timeout=ROUTE_OPEN_TIMEOUT, settle=1):
                    logger.warning('Can not open the 2D route preview')
                    self.route_plan = []
                    return False
        else:
            logger.info('Already in the 2D preview')

        nodes = self.rogue_route_read()
        style = self.rogue_route_style()
        self.route_nodes = nodes
        # 连线不足时不生成计划，等待重读或按 3D 节点评分。
        self.route_plan = rogue_route.plan(nodes, style, self.rogue_route_state(),
                                           getattr(self, 'route_edges', None))
        # ❗这里只归零**层内索引**，不动 `route_step`（那是整面累计的步数，
        # 日志里的 `step N` 就是它）。两者混用会让步数每层被清零、看不出走到哪。
        self.plan_index = 0
        self.route_mismatch = None
        logger.info('Route nodes %s, style %s' % (len(nodes), style))
        if nodes:
            count = {}
            for node in nodes:
                count[node.kind] = count.get(node.kind, 0) + 1
            logger.info('Route totals %s' % count)
            for line in rogue_route.describe(self.route_plan):
                logger.info(line)

        self.tap_point(ROUTE_CLOSE_POINT[0], ROUTE_CLOSE_POINT[1], name='ROGUE_ROUTE_CLOSE')
        self.wait_until_disappear(ROGUE_PREVIEW, offset=(10, 8), timeout=5, settle=1)
        return bool(self.route_plan)

    def rogue_route_entry(self):
        if self.route_plan and self.plan_index < len(self.route_plan):
            return self.route_plan[self.plan_index][0]
        return None

    def rogue_route_confirm_move(self):
        if self.node_pending is None:
            return False
        if self.rogue_map_appear() or self.rogue_map_preview_appear() or self.rogue_prompt_appear():
            return False
        if not (self.rogue_battle_appear() or self.rogue_rest_appear() or self.rogue_story_appear()
                or self.rogue_choice_appear() or self.rogue_beacon_stage()
                or self.rogue_treasure_card_appear() or self.rogue_dice_appear()
                or self.rogue_dice_result_appear() or self.rogue_card_reward_appear()
                or self.rogue_flash_appear() or self.rogue_god_appear()
                or self.rogue_option_points() or self.rogue_primary_point()):
            return False
        self.node_pending = None
        self.route_step += 1
        self.plan_index += 1
        self.route_mismatch = None
        self.node_tries = 0
        self.route_retry = 0
        self.event_page = None
        self.event_index = None
        self.event_unknown = False
        self.event_visit = {}
        self.event_followups = set()
        self.event_last_enc = None
        logger.info('Entered route node (step %s, plan index %s)' % (self.route_step, self.plan_index))
        return True

    def rogue_equip_appear(self):
        """
        Whether the screen is the equipment assignment page (``裝備``).

        Measured on the page that stalled the run for 9 minutes on 2026-11-14
        19:20: `裝備` title above the card, `請選擇戰鬥員。` on the right, an item
        card on the left with `提煉` (salvage, never press) and a `確認` pill.

        Returns:
            bool: If this frame is the equipment page.
        """
        # 阈值 0.9 → 0.85：同一页的不同帧实测 1.000 / 0.965 / 0.887
        # （卡面在淡入），0.9 会把中间那帧漏掉；其它页最高只有 0.363。
        return self.appear(ROGUE_EQUIP, offset=(20, 12), similarity=0.85)

    def rogue_rest_settled(self):
        if not self.rest_settling:
            self.rest_settling = True
            logger.info('Safe area just opened, wait %s s for it to settle' % REST_WAIT)
            self.rest_wait = Timer(REST_WAIT, count=1).start()
            return False
        return self.rest_wait.reached()

    def rogue_rest_appear(self):
        """
        Whether the screen is a 安全区域 (rest point).

        Judge: the `訓練` tile at the top right (1040,118,1180,186) — the tile is on
        every rest layout, while the bottom-right prompt moves with the page: the
        first version used that prompt (880,573,1210,610) and dropped to 0.206 on the
        2026-11-15 live page, where a second line `使用商店並不會消耗次數。` pushed the
        caption up. So the rest branch never fired, the white-pill branch pressed
        `跳過` instead, and the rest (plus 冥想) was skipped (user report, same day).
        Measured over 1097 frames: 20 hits on rest pages only (0.937~1.000), next
        best 0.751 (the 冥想 dialog over the page), so the threshold is 0.9.

        Returns:
            bool: If this frame is a rest point.
        """
        return self.appear(ROGUE_REST, offset=(20, 10), similarity=0.9)

    def rogue_visit_rest_shop(self, press):
        if (not self.shop_cooldown.reached() or self.shop_retry >= SHOP_RETRY
                or not (self.rogue_shop_remove_needed() or self.equipment.shop_target_slots())):
            return False
        if self.appear(ROGUE_REST_SHOP, offset=(20, 10), similarity=0.88):
            if press.reached():
                press.reset()
                self.shop_retry += 1
                self.shop_wait = Timer(SHOP_LOAD, count=1).start()
                logger.info('Visit 德朗商店 for equipment/removal (%s/%s removals used, try %s)'
                            % (self.remove_done, self.rogue_delete_times(), self.shop_retry))
                self.device.click(ROGUE_REST_SHOP)
            return True
        return False

    def rogue_resume_appear(self):
        """
        Whether the client is showing `卡厄思連線意外中斷。是否要繼續進行？`.

        The dialog appears after a client restart while a run was in progress:
        `撤退` at (470,508) and orange `繼續進行` at (815,508). Measured 1.000 on
        the resume frames (relaunch5~7, rl2_b~e) and at most 0.868 elsewhere, so
        the threshold is 0.92. The dialog ignores taps while the client is still
        frozen (2026-11-15 10:07), so pressing once per `press` is enough.

        Returns:
            bool: If this frame is the resume dialog.
        """
        return self.appear(ROGUE_RESUME, offset=(30, 30), similarity=0.92)

    def rogue_meditate_available(self):
        """
        Whether 冥想 can be used on this rest point.

        三件事都要成立：
            1. 这一页确实是安全区域（ROGUE_REST 命中捕语行）
            2. 没有打开「休息」的确认框（否则整页被压暗，冥想格子看不见）
            3. 冥想格子上没有 `無法使用`（ROGUE_MEDITATE_OFF）

        2026-11-15 实测坑：休息确认框弹出后整页变暗，`無法使用` 的字被判据错过，
        于是"看不见"被当成"能用"。所以必须先排除弹窗。

        Returns:
            bool: True if 冥想 is usable.
        """
        if not self.rogue_rest_appear():
            return False
        if self.rogue_confirm_point(REST_CONFIRM_AREA):
            return False
        if self.appear(ROGUE_MEDITATE_OFF, offset=(20, 10), similarity=0.9):
            return False
        return True

    def rogue_meditate_appear(self):
        """
        Whether the screen is the 冥想 card grid: `請選擇1張再次靈光一閃卡牌。`.

        判据是顶部那条橙色标题栏 (130,18,470,52)，取自 2026-11-15 09:2x 的实机帧：
        存盘里 1200+ 帧只有那一帧命中 1.000，其余都低于 0.6。

        Returns:
            bool: If this frame is the meditation card grid.
        """
        return self.appear(ROGUE_MEDITATE, offset=(20, 12), similarity=0.9)

    def rogue_member_spark_cards(self):
        """Return allowed spark-card names for `RogueMember`, or `None` if slots are unconfigured."""
        if not hasattr(self, 'config'):
            return None
        try:
            node = self.config.data.get('ChaoszeroRogue', {})
            node = node.get('ChaoszeroRogue') or node
            slot_cids = [
                str(node.get('RogueSlot1Member') or '').strip(),
                str(node.get('RogueSlot2Member') or '').strip(),
                str(node.get('RogueSlot3Member') or '').strip(),
            ]
            member = node.get('RogueMember', getattr(self.config, 'ChaoszeroRogue_RogueMember', 1))
        except Exception:
            slot_cids = [
                str(getattr(self.config, 'ChaoszeroRogue_RogueSlot1Member', '') or '').strip(),
                str(getattr(self.config, 'ChaoszeroRogue_RogueSlot2Member', '') or '').strip(),
                str(getattr(self.config, 'ChaoszeroRogue_RogueSlot3Member', '') or '').strip(),
            ]
            member = getattr(self.config, 'ChaoszeroRogue_RogueMember', 1)
        if not any(slot_cids):
            return None
        try:
            idx = int(member)
        except (TypeError, ValueError):
            idx = 1
        if not 1 <= idx <= len(slot_cids):
            idx = 1
        return rogue_cards.character_spark_cards(slot_cids[idx - 1])

    def _rogue_meditate_allows(self, card_name):
        allowed = self.rogue_member_spark_cards()
        if allowed is None:
            return True
        if card_name in allowed:
            return True
        norm = rogue_cards.normalize(card_name)
        return bool(norm) and norm in {rogue_cards.normalize(name) for name in allowed}

    def _next_meditate_target(self):
        for card in self.meditate_pending:
            if self._rogue_meditate_allows(card):
                return card
        return None

    def rogue_meditate_card(self):
        """
        Find the configured target card on the 冥想 grid.

        动态检测当前可见卡牌，只找已记录的闪歪目标，并且要求：
            最高分 >= MEDITATE_MATCH  且  领先第二名 >= MEDITATE_MARGIN
        认不准就返回 None —— 用户的要求是宁可不冥想，也不能认错卡去重掷。

        Returns:
            tuple: ((x, y), name, score) of the card to reroll, or None.
        """
        table = self.rogue_spark_filter()
        if not table:
            logger.info('RogueSparkFilter is empty, nothing to reroll')
            return None
        # 只按闪歪先后处理队首（仅限人物灵光优先位角色），不能从整个配置表里任意挑一张。
        target = self._next_meditate_target()
        if target:
            if target in table:
                names = [target]
            else:
                logger.info('Meditate target %s is not in RogueSparkFilter, skip' % target)
                return None
        else:
            logger.info('No pending meditation target, skip the grid')
            return None
        if self.card_reader is None:
            self.card_reader = rogue_cards.CardReader()
        # ❗**改成动态检测**：这一页从 3 列变成了 **4 列 x 2 行**
        # （2026-11-17 07:45 用户截图：第 1 行 劍之雨/一縷光芒/展開極光/萬人的英雄，
        #  第 2 行 劍之雨），而老的 `MEDITATE_COLUMNS = (360,567,775)` 只有 3 列、
        # 而且每列都偏左约 90px（真实中心 450/664/880/1099）——
        # 第 4 列根本读不到，前三列也全错位，于是永远 `No card to reroll`。
        # 灵光选卡页的检测器（中部亮色矩形）正好是同一套布局，直接复用。
        for page in range(4):
            points = self.rogue_flash_card_points(opening=11)
            scored = []
            for x, y, top, left, width, height in points:
                # 旧带下沿到 +40 会吃进卡框和描述首行，OCR 变乱码（0.29）；
                # 卡名只有 ~20px，放大 2 倍再读（同删卡网格）。
                area = (left + 10, top + 6, left + width - 10, top + 34)
                text = self.card_reader.read_name(self.device.image, area, scale=2)
                if text:
                    for name in names:
                        scored.append((rogue_cards.name_score(text, name), name, x, y, text))
            scored.sort(reverse=True)
            if scored:
                best = scored[0]
                second = scored[1][0] if len(scored) > 1 else 0.0
                logger.info('Meditation grid best %s (%.2f vs %.2f) %s'
                            % (best[1], best[0], second, best[4][:12]))
                if best[0] >= MEDITATE_MATCH:
                    if best[0] - second < MEDITATE_MARGIN:
                        return None
                    return (best[2], best[3]), best[1], best[0]
            if page == 3:
                break
            logger.info('Meditation target %s is not visible, scroll down (%s/3)' % (target, page + 1))
            self.device.swipe((1220, 550), (1220, 180), duration=0.5,
                              name='ROGUE_MEDITATE_SCROLL')
            if not self.wait_until_still((350, 80, 1250, 630), timeout=3,
                                         skip_first_screenshot=False):
                break
            if not self.rogue_meditate_appear():
                break
        return None

    def rogue_meditate_needed(self):
        """
        Whether 冥想 is worth using: the wanted card has already flashed, but with
        a type that is not the configured one.

        用户 2026-11-15：卡牌没闪之前不用冥想 —— 没闪过的时候冥想没有意义。
        `rogue_flash_column()` 会记：三列都认清了但一列都不含配置的关键词（这张卡
        已经闪歪了）时按先后加入队列，挑到目标形态只移除对应卡。

        冥想页（说明框 → 选卡网格 → `再次靈光一閃`）已实机走通，所以 `MED_READY`
        现在是 True；能不能选中目标卡由 `rogue_meditate_card()` 决定，认不准时
        那一步会取消冥想、照常休息。

        还要看配置 `RogueMeditate`：关掉时永远休息，不花那 80 点信用点。

        Returns:
            bool: If the card should be rerolled.
        """
        if not MED_READY:
            return False
        if not getattr(self.config, 'ChaoszeroRogue_RogueMeditate', True):
            return False
        return bool(self._next_meditate_target()) and self.meditate_step != self.route_step

    def rogue_member_appear(self):
        """
        Whether the screen is the 人物灵光 member picker.

        Judge: the bottom prompt `請選擇欲獲得【靈光一閃】的戰鬥員。` (430,650,855,685).
        Measured 1.000 on 32 in-run frames of that page and at most 0.315 on 921
        frames of every other page (2026-11-15 00:3x, frame drive_009.png).

        Returns:
            bool: If this frame is the member picker.
        """
        return self.appear(ROGUE_MEMBER, offset=(12, 8), similarity=0.85)

    def rogue_copy_appear(self):
        """
        Whether this frame is the 「複製卡牌」 member picker.

        每面结束的随机复制：先选一个战斗员 → 出他这个角色的 3 张随机可复制卡 → 选 1 张。
        立绘 / 右下 `確認` 的几何和人物灵光页一模一样，只有底部说明不同
        （「請選擇要複製卡牌的戰鬥員。」），所以单独做判据（(430,648,860,686)，
        955 帧里 19 帧 1.000 全在这一页，次高 0.406）。

        Returns:
            bool: If this frame is the copy picker.
        """
        return self.appear(ROGUE_COPY, offset=(12, 8), similarity=0.85)

    def rogue_detail_appear(self):
        """
        Whether this frame is the 「查看詳情」 card detail overlay.

        大卡 + 左右翻页箭头 + 底部橙色 `關閉` + 右下 `靈光一閃`。局内盲点会翻到这一页，
        之前没有判据就一路等到 `Unknown page and nothing to press, stop here`
        （2026-11-15 06:55 直接把整局停了）。模板取顶部标题 `查看詳情` (575,36)-(706,74)：
        live_K.png 与 drive_036.png 都是 1.000，次高 0.540，所以 0.85 稳。

        Returns:
            bool: If this frame is the card detail overlay.
        """
        return self.appear(ROGUE_DETAIL, offset=(20, 12), similarity=0.85)

    def rogue_deck_appear(self):
        """
        Whether this frame is the 「所有牌堆」 deck list overlay.

        局内盲点会翻到这一页（顶部 `所有牌堆` + `卡牌數量` + 右上角 ✕，整页卡片网格），
        它没有血条也没有主按钮，2026-11-15 07:00 就在这里把整局停住了。
        模板取标题 (145,16)-(346,60)：3 帧 1.000，次高 0.530。

        Returns:
            bool: If this frame is the deck list.
        """
        return self.appear(ROGUE_DECK, offset=(20, 12), similarity=0.85)

    def rogue_state_path(self):
        # The legacy rogue_state.json has no profile identity and cannot be assigned safely.
        profile = os.path.normcase(os.path.normpath(filepath_config(self.config.config_name)))
        key = hashlib.sha256(profile.encode('utf-8')).hexdigest()
        return os.path.join(ROGUE_STATE_DIR, f'{key}.json')

    @staticmethod
    def rogue_state_read(path):
        content = atomic_read_bytes(path)
        if not content:
            return {}
        try:
            # JSON edited on Windows may start with a UTF-8 BOM.
            payload = json.loads(content.decode('utf-8-sig'))
            if isinstance(payload, dict):
                return payload
            raise ValueError('expected a JSON object')
        except ValueError as error:
            logger.warning(f'Invalid Rogue state {path}: {error}')
            return {}

    def rogue_state_load(self, key, default=None):
        path = self.rogue_state_path()
        try:
            payload = self.rogue_state_read(path)
        except OSError as error:
            logger.warning(f'Failed to read {path}: {error}')
            return default
        if key in payload:
            logger.info(f'Restored `{key}` = {payload[key]} from {path}')
        return payload.get(key, default)

    def rogue_state_save(self, **kwargs):
        path = self.rogue_state_path()
        try:
            os.makedirs(ROGUE_STATE_DIR, exist_ok=True)
            with FileLock(f'{path}.lock', timeout=2):
                payload = self.rogue_state_read(path)
                payload.update(kwargs)
                atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=1))
        except (OSError, Timeout) as error:
            logger.warning(f'Failed to write {path}: {error}')

    def rogue_stuck_check(self):
        """
        Detect a frozen screen or a two-frame loop.

        用户 2026-11-16：「卡住或者某处反复死循环先暂停脚本，再等我处理。」
        每 `STUCK_PERIOD` 秒采一次画面签名，攒满 `STUCK_SAMPLES` 个后看有几种：
        ≤ `STUCK_STATES` 种就算卡住 —— 正常战斗/粒子/载入每帧都不一样，
        而"点弹窗 → 弹窗关 → 再点"这类死循环只在两帧之间来回。

        Returns:
            bool: True when the screen has been effectively unchanged for too long.
        """
        import time

        if not self.stuck_sample.reached():
            return False
        self.stuck_sample.reset()
        self.stuck_recent.append(self.device.image[::32, ::32].tobytes())
        if len(self.stuck_recent) < STUCK_SAMPLES:
            return False
        states = len(set(self.stuck_recent))
        if states > STUCK_STATES:
            return False
        logger.warning('Screen unchanged for %s+ seconds (%s distinct frame(s)): '
                       'stuck or looping. Stopping the task here, frame saved.'
                       % (STUCK_PERIOD * STUCK_SAMPLES, states))
        self.rogue_dump_unknown()
        self.stuck_recent.clear()
        return True

    def handle_rogue_fate(self, press):
        if not self.rogue_fate_appear():
            self.fate_tries = 0
            self.fate_index = None
            self.fate_wait.clear()
            return False
        if not self.fate_wait.start().reached() or not press.reached():
            return True

        if self.fate_index is None:
            if self.card_reader is None:
                self.card_reader = rogue_cards.CardReader()
            titles = rogue_fate.read_titles(self.device.image, self.card_reader)
            if titles is None:
                if self.fate_wait.current_time() >= 6:
                    self.rogue_dump_unknown()
                    raise TaskFailed('Fate cards did not finish revealing, stop for review')
                return True

            phase = rogue_fate.phase(titles, self.core_started)
            settings = self.config.data.get('ChaoszeroRogue', {}).get('ChaoszeroRogue', {})
            field = 'RogueFateCoreFilter' if phase == 'core' else 'RogueFateMainFilter'
            priorities = settings.get(field, getattr(self.config, 'ChaoszeroRogue_' + field))
            self.fate_index, matched = rogue_fate.pick(titles, priorities)
            logger.info('Fate [%s] %s: pick %s (%s)' % (
                phase, titles, self.fate_index, 'priority' if matched else 'random'))
            if settings.get('RogueFateCapture', self.config.ChaoszeroRogue_RogueFateCapture):
                self.rogue_fate_record(titles, phase)

        press.reset()
        self.fate_tries += 1
        if self.fate_tries % 2:
            self.rogue_pick(TAROT_POINTS, self.fate_index)
        else:
            self.tap_point(*FATE_OK_POINT, name='ROGUE_FATE_OK')
        return True

    def rogue_fate_record(self, titles, phase):
        """Save one full chooser and its effect crops for the debug catalog."""
        import json as json_module
        import os
        import time

        try:
            image = self.device.image
            folder = os.path.join(FATE_LOG_DIR, phase)
            if not os.path.exists(folder):
                os.makedirs(folder)
            stamp = time.strftime('%H%M%S')
            base = os.path.join(folder, stamp)
            cv2.imwrite(base + '.png', cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
            for index, area in enumerate(FATE_DESC_AREAS, 1):
                patch = image[area[1]:area[3], area[0]:area[2]]
                if patch.size:
                    cv2.imwrite('%s_effect%s.png' % (base, index),
                                cv2.cvtColor(patch, cv2.COLOR_RGB2BGR))
            payload = json_module.dumps(
                {'time': time.strftime('%Y-%m-%d %H:%M:%S'),
                 'phase': phase,
                 'titles': titles,
                 'note': '效果文字太小 OCR 读不出，看 _effect1/2/3.png'},
                ensure_ascii=False, indent=1)
            with open(base + '.json', 'w', encoding='utf-8') as handle:
                handle.write(payload)
            logger.info('Fate page logged [%s]: %s (effects saved as %s_effect1..3.png)'
                        % (phase, titles, stamp))
            prune_diagnostics(folder, 'fate')
        except Exception as error:
            logger.warning('Failed to log the fate page: %s' % error)

    def _pause_for_similar_page(self, name):
        """
        Stop auto-handling a "looks like a known page" screen.

        游戏里很多事件共用同一页面、只差一点点（删卡 vs 转卡、灵光选人 vs 复制选人…），
        靠状态机猜就会做错事（例如把普通卡转成中立卡）。这里统一**不猜**：
        存一帧、打一条日志、原地等，等用户看图给出规则。

        Args:
            name (str): 页面的中文名，出现在日志里方便用户对照截图。

        Returns:
            bool: True = 调用方应当 `continue`（本帧什么都不做）。
        """
        if AUTO_HANDLE_SIMILAR_PAGES:
            return False
        import time

        self.rogue_dump_unknown()
        # 日志节流：这个分支每帧都会进，不节流会把整局日志刷没（实测一秒 5 行）。
        key = (name, int(time.time()) // 5)
        if self.pause_logged != key:
            self.pause_logged = key
            logger.warning('Similar page `%s` is not auto-handled, waiting for a rule. '
                           'Frame saved under ./log/rogue_pages/' % name)
        return True

    def rogue_copy_card_points(self):
        """
        Card centres on the 「請選擇欲複製的卡牌」page, left to right.

        这一页摆着 2~3 张**大卡**（实测 285x393），背景很暗，用"中部亮色大矩形"
        就能稳稳检出（实测两张卡的 area 都是 89k/93k）。

        Returns:
            list[tuple]: (x, y) 卡中心，从左到右；空说明没检出。
        """
        image = self.device.image
        # ❗上边从 200 改到 **60**：这页有 8 张卡排两行，第一行在 y≈70~300，
        # 从 200 起切会把第一行截成一半、高度不够被过滤掉 ——
        # 实测 8 张只检出 3 张（只有第二行）。左边从 200 改到 280 避开角色栏。
        # ❗左边界 280 → **150**：三张大卡时第一张在 x≈184，280 会把它整张切掉；
        # 上边界 60、下 700 覆盖两种布局（大卡 y 154~604 / 小卡 y 70~560）。
        patch = image[60:700, 150:1180, :3]
        hsv = cv2.cvtColor(patch, cv2.COLOR_RGB2HSV)
        mask = (hsv[:, :, 2] > 80).astype('uint8')
        count, _, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
        points = []
        for index in range(1, count):
            width = int(stats[index][2])
            height = int(stats[index][3])
            area = int(stats[index][4])
            # ❗尺寸范围从 200~420 放宽到 140~300：这一页有 3 张大卡（205x255）
            # 也有 **8 张小卡**（约 170x255），只认大卡时会漏掉一半
            # （2026-11-16 19:20 实测 8 张只检出 1 张）。
            # ❗高度上限 340 → **480**：三张大卡实测 278x450，超过 340 会被整张过滤掉
            # （2026-11-16 19:55 实测：这页一直报 no card detected yet, wait）。
            if not (140 <= width <= 330 and 190 <= height <= 480):
                continue
            if area < width * height * 0.35:
                continue
            # 偏移跟着上面的裁剪区：x + 150、y + 60
            # ❗把卡框也带出去：要按卡名 OCR 找「劍之雨」，得知道卡名条在哪。
            points.append((int(cents[index][0]) + 150, int(cents[index][1]) + 60,
                           int(stats[index][0]) + 150, int(stats[index][1]) + 60,
                           width, height))
        # ❗**行优先**排序：8 张卡排两行，纯按 x 排会把上下两行混在一起
        # （实测顺序变成 (452,506)(662,206)(672,484)… 第 1 张跑到第二行去了）。
        points.sort(key=lambda item: (item[1] // 200, item[0]))
        return points

    def rogue_card_reward_appear(self):
        """
        Whether this is the 「卡牌獎勵」page, including single-card assignment.

        开局和战斗后都会出这一页：三张卡挑一张（致命射擊 / 睡眠果實 / 神聖一擊…），
        底部「跳過」+「確認」。以前**没有判据** —— 2026-11-16 18:06 实测开局第一帧
        就掉进未知页，连存 8 帧后 20 秒收工撤退，一整局白开。

        判据取标题「卡牌獎勵」`(560,62)-(730,116)`：命中帧 1.000（连续两帧都是），
        BOSS 房前 0.043、事件页 0.270、战利品页 0.318、地图页 0.105，阈值 0.85 很稳。

        Returns:
            bool: If the card reward picker is on screen.
        """
        return self.appear(ROGUE_CARD_REWARD, offset=(16, 12), similarity=0.85)

    def rogue_flash_card_appear(self):
        """
        Whether this is the 「請選擇1張欲觸發靈光一閃的卡牌。」page.

        ❗**和 `rogue_flash_appear()` 不是同一页**：
        - 这一页「請選擇**1張欲觸發靈光一閃的卡牌**」——先挑一张卡，再点底部
          「靈光一閃」才进形态选择；
        - `ROGUE_FLASH` 那页是「請選擇**靈光一閃效果**」——三张同卡不同形态。

        这页以前**没有判据**，落到"未知页"分支：先盲点画面中部、再点橙色主按钮
        `(1153,666)`，凑巧把「靈光一閃」按掉了（2026-11-16 02:40 实测，
        日志里是 `Unknown rogue page` + `Cutscene frame` + `ROGUE_PRIMARY`）。
        能用，但完全是碰运气的，一旦卡没被选中就白点。

        判据取顶部绿色标题 `(60,16)-(720,54)`：命中帧 1.000，
        形态选择页 0.049/0.110、事件页 0.145、BOSS 战利品 0.387，阈值 0.85 很稳。

        ❗**还有一版「神之靈光一閃」**（2026-11-17 06:50 实机截图）：
        `請選擇1張要賦予**神之靈光一閃**的卡牌。`，橙色标题条 `(130,18)-(900,60)`，
        布局和这一页一样（2 行 x 4 列 + 底部「跳過」/「選擇」），只是标题文字不同。
        两个模板都认：`ROGUE_FLASH_CARD_TITLE`（绿条）/ `ROGUE_GOD_CARD_TITLE`（橙条）。
        实测神闪那版：自身 1.000、灵光选卡页 0.610、其它页 ≤0.369，阈值 0.85 够。

        Returns:
            bool: If the flash-target card picker is on screen.
        """
        for button in (ROGUE_FLASH_CARD_TITLE, ROGUE_GOD_CARD_TITLE):
            if self.appear(button, offset=(16, 10), similarity=0.85):
                return True
        return False

    def rogue_god_card_appear(self):
        """Whether this is the **神之靈光一閃** variant of the card picker.

        `請選擇1張要賦予神之靈光一閃的卡牌。` —— 橙色标题条，和绿色那版（欲觸發）
        只差标题文字。两版共用一套"点卡 → 点底部橙色按钮"的流程，只有选哪张卡不同：
        神闪这版按 `GOD_CARD_NAME` 找指定卡，找不到点第一张。

        Returns:
            bool: If the god-flash card picker is on screen.
        """
        return self.appear(ROGUE_GOD_CARD_TITLE, offset=(16, 10), similarity=0.85)

    def rogue_god_card_pick(self):
        """Find `GOD_CARD_NAME` on the god-flash card picker.

        用户 2026-11-17：「直接指定一个卡名，没有的时候就点第一个」。
        所以这里只负责"找得到就返回它"，找不到返回 None，由调用方点第一张。

        Returns:
            tuple | None: (x, y, name, score)；None = 按第一张处理。
        """
        points = self.rogue_flash_card_points()
        if not points:
            return None
        if self.card_reader is None:
            self.card_reader = rogue_cards.CardReader()
        image = self.device.image
        best = None
        for x, y, top, left, width, height in points:
            area = (left + 20, top + 6, left + width - 10, top + 40)
            text = self.card_reader.read_name(image, area)
            if not text:
                continue
            score = rogue_cards.name_score(text, GOD_CARD_NAME)
            if best is None or score > best[3]:
                best = (x, y, GOD_CARD_NAME, score, text)
        if best is None or best[3] < GOD_CARD_MATCH:
            logger.info('God-card picker: no %s (best %.2f), use the first card'
                        % (GOD_CARD_NAME, best[3] if best else 0.0))
            return None
        logger.info('God-card picker: %s at (%s, %s) %.2f OCR=%r'
                    % (best[2], best[0], best[1], best[3], best[4][:12]))
        return best[0], best[1], best[2], best[3]


    def rogue_flash_card_points(self, opening=0):
        """
        Card centres on the 「請選擇1張欲觸發靈光一閃的卡牌。」page, row-major.

        ❗**不能用固定坐标**：这一页的布局不固定 ——
        - 4 张大卡（卡面高约 470，`(320,400)` 落在卡上）；
        - 6 张小卡排成 2 行（卡面只到 y≈300，(320,400) 点在**卡下方的空白**，
          点了等于没点，然后一直重试）。
        2026-11-16 18:30 实测就是第二种：点 (320,400) 五轮都没选中任何卡。

        判据："中部亮色矩形"（卡面彩绘比周围深色背景亮得多），宽 120~260、
        高 150~320、填充 ≥45%。实测能干净检出 188x280 那一排。

        Args:
            opening (int): Optional morphology kernel to separate glow-connected
                cards and remove particles protruding from card edges.

        Returns:
            list[tuple]: (x, y, top, left, width, height), row-major.
        """
        image = self.device.image
        # ❗右边界 1080 → **1200**：`請選擇1張要賦予神之靈光一閃的卡牌` 那页是 4 列，
        # 第 4 张卡在 x≈1001~1197，1080 会把它整张切掉（2026-11-17 06:50 截图实测）。
        patch = image[60:600, 280:1200, :3]
        if not patch.size:
            return []
        hsv = cv2.cvtColor(patch, cv2.COLOR_RGB2HSV)
        mask = (hsv[:, :, 2] > 90).astype('uint8')
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        if opening:
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
                                    np.ones((opening, opening), np.uint8))
        count, _, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
        points = []
        for index in range(1, count):
            width = int(stats[index][2])
            height = int(stats[index][3])
            area = int(stats[index][4])
            if not (120 <= width <= 260 and 150 <= height <= 320):
                continue
            if area < width * height * 0.45:
                continue
            # ❗带上卡框：神闪选卡页要按卡名找「劍之雨」，得知道卡名条在哪。
            points.append((int(cents[index][0]) + 280,
                           int(cents[index][1]) + 60,
                           int(stats[index][1]) + 60,
                           int(stats[index][0]) + 280,
                           width, height))
        points.sort(key=lambda item: (item[2] // 150, item[0]))
        return points

    def rogue_copy_card_pick(self):
        """
        Find the configured card on the 「請選擇欲複製的卡牌」page.

        Returns:
            tuple | None: (x, y, name, score), or None if the caller should retry.
        """
        target = self.config.ChaoszeroRogue_RogueCopyCard.strip()
        points = self.rogue_copy_card_points()
        if not points:
            return None
        if self.card_reader is None:
            self.card_reader = rogue_cards.CardReader()
        image = self.device.image
        # 卡名条相对卡框：左右各留 12，纵向从卡顶 +4 到 +46（实测 8 张小卡 280 高、
        # 3 张大卡 422 高，这个比例都能盖住名字）
        scored = []
        for x, y, left, top, width, height in points:
            area = (left + 12, top + 4, left + width - 12, top + 46)
            text = self.card_reader.read_name(image, area)
            if not text:
                continue
            scored.append((rogue_cards.name_score(text, target), target, x, y, text))
        if not scored:
            logger.info('Copy-card page, no card name readable')
            return None
        scored.sort(reverse=True)
        best = scored[0]
        second = scored[1][0] if len(scored) > 1 else 0.0
        logger.info('Copy-card page, best match %s (%.2f vs %.2f) OCR=%r'
                    % (best[1], best[0], second, best[4][:14]))
        if best[0] < COPY_CARD_MATCH or best[0] - second < COPY_CARD_MARGIN:
            return None
        return best[2], best[3], best[1], best[0]

    def rogue_copy_card_appear(self):
        """
        Whether this is the 「請選擇欲複製的卡牌」page (2 张卡 + 底部「跳過」).

        ❗和 BOSS 结算的「複製卡牌」不是一回事：那个是**先选角色**（`ROGUE_COPY`，
        三张大立绘），这个是**直接给两三张卡让你挑**，底部**没有「複製」按钮**，
        只有「跳過」。

        ❗以前没有判据，被 `rogue_meditate_appear()` 误吃：它按冥想页的逻辑去点
        `(134, 616)`（左下角图标区，不是卡），连点十几次没反应，还撞上
        `Too many presses of the same button`（2026-11-16 02:24 实测）。

        ❗**标题有两版布局**，要两个模板都认：
        - 居中版 `(500,58)-(790,112)`（02:24 那次，3 张卡）
        - 靠左版 `(110,16)-(730,64)`（2026-11-16 19:20 那次，8 张卡，标题顶在左上角）
        只认居中版时，靠左版命中 **False**，整页掉进未知页 → 40 秒后停任务。
        靠左版实测：命中帧 1.000、灵光选卡页 0.654（都是蓝白标题条但字不同）、
        其它页 ≤0.319，阈值 0.85 够。

        Returns:
            bool: If the copy-card picker is on screen.
        """
        for button in (ROGUE_COPY_CARD_TITLE, ROGUE_COPY_TITLE2):
            if self.appear(button, offset=(16, 10), similarity=0.85):
                return True
        return False

    def rogue_transform_appear(self):
        """
        Whether this is the 「請選擇 N 張欲**轉換**的卡牌」card-transform page.

        ❗和删卡页只差标题一个字，但两件事完全不同：
        - 删卡 → 卡片离开卡组（`RogueDelete` 想要的）
        - 转卡 → 普通卡变成**另一张卡**（「捨棄世俗」会把一般卡转成「致命射擊」），
          用户 2026-11-15 明确：**这一页要跳过**，不要选卡再点「轉換」。
        误判代价：卡组被塞进不想要的卡。

        判据用顶部标题模板（`ROGUE_TRANSFORM`，区域同 `ROGUE_REMOVE`）：
        转化页 1.000 / 删卡页 0.896；删卡模板反过来 0.895 / 0.999 ——
        阈值 0.93 下**两者互斥**，各管各的页面。

        Returns:
            bool: If the transform page is on screen.
        """
        return self.appear(ROGUE_TRANSFORM, offset=(12, 8), similarity=0.93)

    def rogue_remove_targets(self):
        """Return ordered card names still within their per-run removal quota."""
        counts = getattr(self, 'remove_counts', {}) or {}
        return [name for name, quota in self.rogue_delete_rules() if counts.get(name, 0) < quota]

    @staticmethod
    def _match_remove_name(raw_ocr, norm_ocr, target):
        """Match one card OCR result against a configured removal target."""
        if any(ord(ch) < 128 and ch.isalnum() for ch in target):
            norm_raw = re.sub(r'[^a-z0-9\u4e00-\u9fff]', '', (raw_ocr or '').lower())
            norm_tgt = re.sub(r'[^a-z0-9\u4e00-\u9fff]', '', target.lower())
            if not norm_raw or not norm_tgt:
                return 0.0
            if norm_tgt == norm_raw:
                return 1.0
            if len(norm_tgt) >= 3 and norm_tgt in norm_raw:
                return 0.85
            return 0.0
        norm_tgt = rogue_cards.normalize(target)
        if not norm_tgt or not norm_ocr:
            return 0.0
        if len(norm_tgt) == 1:
            return 1.0 if norm_ocr == norm_tgt else 0.0
        if len(norm_tgt) <= 2:
            # Two-character names must be readable in full: 劍市/劍之雨
            # must never become a removable basic card through fuzzy matching.
            if norm_tgt not in norm_ocr:
                return 0.0
            score = rogue_cards.name_score(norm_ocr, target)
            return score if score >= REMOVE_NAME_MATCH else 0.0
        shared = sum(1 for ch in norm_tgt if ch in norm_ocr)
        if shared < 2:
            return 0.0
        score = rogue_cards.name_score(norm_ocr, target)
        return score if score >= max(REMOVE_NAME_MATCH, 0.65) else 0.0

    def rogue_remove_to_top(self):
        """Drag the removal grid back to its first row before scanning.

        181: the game keeps the scroll position between visits and "the picture
        stopped changing" is not proof of the top, so every visit drags a fixed
        number of times. 140: drags are counted as clicks.
        """
        for _ in range(REMOVE_SCROLL_TIMES):
            self.device.click_record_clear()
            self.device.drag(REMOVE_HOME[0], REMOVE_HOME[1], name='ROGUE_REMOVE_HOME')
            self.wait_until_still((350, 80, 1250, 630), timeout=3,
                                  skip_first_screenshot=False)

    def rogue_remove_pick(self):
        """Return ((x, y), name, score, OCR) for the highest-priority removal target.

        Only detected card boxes with a readable target name are eligible.
        Read each box once so all configured targets use the same OCR result.
        The page holds 2 rows per screen, so scan, drag down and scan again at
        most REMOVE_SCROLL_TIMES times; stop early only when the grid is gone or
        a drag brings no new card name (bottom reached). Never pick by position.
        """
        targets = self.rogue_remove_targets()
        if not targets:
            return None
        if self.card_reader is None:
            self.card_reader = rogue_cards.CardReader()
        has_ascii = any(ord(ch) < 128 and ch.isalnum() for name in targets for ch in name)
        seen = set()
        points = []
        for page in range(REMOVE_SCROLL_TIMES + 1):
            # Removal captures 044408/204838: glow joins two rows into a 518px
            # component or shifts a card's left edge by 5px (劍幕 OCR becomes 劍墓).
            # An 11px opening separates the rows and restores the name crop.
            points = self.rogue_flash_card_points(opening=11)
            if not points:
                logger.info('Removal pick: no card boxes detected, do not pick by position')
                return None
            image = self.device.image
            candidates = {}
            names = set()
            for x, y, top, left, width, height in points:
                # 卡名只有 ~20px：旧带下沿 +40 吃进卡框/描述首行，3 字名读成半截；
                # 收窄到 +34 并放大 2 倍（与冥想页 2026-11-19 实测一致）。
                area = (left + 10, top + 6, left + width - 10, top + 34)
                raw = (self.card_reader.read_name(image, area, scale=2, raw=True)
                       if has_ascii else self.card_reader.read_name(image, area, scale=2))
                text = rogue_cards.normalize(raw)
                if text:
                    names.add(text)
                logger.info('Removal card at (%s,%s) OCR=%r'
                            % (x, y, raw if has_ascii else text))
                for name in targets:
                    score = self._match_remove_name(raw, text, name)
                    if score <= 0.0:
                        continue
                    best = candidates.get(name)
                    if best is None or score > best[2]:
                        candidates[name] = ((x, y), name, score, raw if has_ascii else text)
            for name in targets:
                if name in candidates:
                    best = candidates[name]
                    logger.info('Removal pick: at (%s,%s) -> %s (%.2f) OCR=%r'
                                % (best[0][0], best[0][1], best[1], best[2], best[3]))
                    return best
            if page == REMOVE_SCROLL_TIMES:
                break
            if names and names <= seen:
                logger.info('Removal pick: no new card name after scrolling, reached the end')
                break
            seen |= names
            logger.info('Removal target (%s) is not visible, scroll down (%s/%s)'
                        % (', '.join(targets), page + 1, REMOVE_SCROLL_TIMES))
            self.device.click_record_clear()
            self.device.drag(REMOVE_SCROLL[0], REMOVE_SCROLL[1], name='ROGUE_REMOVE_SCROLL')
            if not self.wait_until_still((350, 80, 1250, 630), timeout=3,
                                         skip_first_screenshot=False):
                break
            if not self.rogue_remove_appear():
                logger.info('Removal pick: the removal page is gone after scrolling')
                break
        logger.info('Removal pick: no configured target (%s) found on %s card(s)'
                    % (', '.join(targets), len(points)))
        return None

    def rogue_shop_remove_needed(self):
        return (self.remove_done < self.rogue_delete_times()
                and self.remove_skip_node != (self.core_started, self.route_step))

    def rogue_remove_reset(self):
        """Clear page-local state; preserve the run count and node skip."""
        self.remove_stage = 0
        self.remove_target = None
        self.remove_tries = 0
        self.remove_cancel_tries = 0
        self.remove_wait.clear()

    def rogue_remove_cancel(self, point=REMOVE_CANCEL_POINT, name='ROGUE_REMOVE_CANCEL'):
        """Leave a recognized removal page without spending the removal quota."""
        if self.remove_cancel_tries >= REMOVE_MAX_TRIES:
            self.rogue_dump_unknown()
            raise TaskFailed('Card removal page could not be skipped, stop for review')
        self.remove_cancel_tries += 1
        self.remove_skip_node = (self.core_started, self.route_step)
        self.remove_stage = 3
        self.remove_target = None
        self.remove_wait = Timer(REMOVE_WAIT, count=1).start()
        self.tap_point(*point, name=name)

    def rogue_remove_submit(self, point):
        """Submit the card selected by this handler; wait for explicit success."""
        logger.info('The card is picked, press 移除 for %s (confirmed %s/%s)'
                    % (self.remove_target[1], self.remove_done, self.rogue_delete_times()))
        self.remove_stage = 2
        self.remove_wait = Timer(REMOVE_WAIT, count=1).start()
        self.tap_point(*point, name='ROGUE_REMOVE_OK')

    def handle_rogue_remove(self, press):
        """Own selection, submission and completion before generic page handlers.

        Stages: 0 scan, 1 selected, 2 submitted, 3 completed/cancelled.
        Transition frames are consumed without clicks. Count only the explicit
        卡牌移除完成 banner, once, after submitting our recognized target.
        """
        if self.appear(ROGUE_REMOVE_DONE, offset=(12, 8), similarity=0.85):
            if self.remove_stage == 2 and self.remove_target is not None:
                self.remove_done += 1
                counts = getattr(self, 'remove_counts', None)
                if counts is None:
                    counts = self.remove_counts = {}
                counts[self.remove_target[1]] = counts.get(self.remove_target[1], 0) + 1
                self.rogue_state_save(remove_done=self.remove_done, remove_counts=counts)
                logger.info('Removal confirmed: %s (%s/%s used this run)'
                            % (self.remove_target[1], self.remove_done, self.rogue_delete_times()))
            if self.remove_stage != 3:
                self.remove_stage = 3
                self.remove_target = None
                self.remove_wait = Timer(REMOVE_WAIT, count=1).start()
            # Live 2026-11-17: this is a modal with 點擊畫面可關閉視窗,
            # not an automatic transition. Consume it without submitting again.
            if press.reached():
                press.reset()
                logger.info('Close the confirmed card-removal result')
                self.tap_point(*CUTSCENE_POINT, name='ROGUE_REMOVE_DONE')
            return True
        # Event removal uses 跳過, which opens a confirmation modal. Its
        # underlying title still matches ROGUE_REMOVE, so handle the exact
        # skip text before retrying the obscured bottom button (live 11:38).
        if (self.appear(ROGUE_REMOVE_SKIP, offset=(12, 8), similarity=0.90)
                and (self.remove_stage == 3 or self.rogue_remove_appear())):
            point = self.rogue_dialog_point()
            if point and press.reached():
                press.reset()
                logger.info('Confirm skipping the removal reward, quota unchanged (%s)'
                            % self.remove_done)
                self.rogue_remove_cancel(point, name='ROGUE_REMOVE_SKIP_CONFIRM')
            return True
        if self.remove_stage == 1:
            close = None
            if self.appear(ROGUE_FLASH_DETAIL, offset=(14, 10), similarity=0.85):
                close = FLASH_DETAIL_CLOSE
            elif self.rogue_detail_appear():
                close = DETAIL_CLOSE_POINT
            if close:
                if press.reached():
                    press.reset()
                    logger.info('Close the removal card detail before retrying selection')
                    self.tap_point(*close, name='ROGUE_REMOVE_DETAIL_CLOSE')
                    self.remove_wait = Timer(REMOVE_WAIT, count=1).start()
                return True
        remove = self.rogue_remove_appear()
        ready = self.rogue_remove_ready() if remove or self.remove_stage in (1, 2) else None
        if not remove and not (self.remove_stage in (1, 2) and ready):
            if self.remove_stage and not self.remove_wait.reached():
                return True
            if self.remove_stage == 2:
                # No known success page: stop rather than delete another card
                # against a count that may no longer match the game.
                self.rogue_dump_unknown()
                raise TaskFailed('Card removal result was not confirmed, stop for review')
            if self.remove_stage == 1:
                # Still no known page after selection: save and wait for the
                # run's stuck watchdog, never hand this frame to generic clicks.
                self.rogue_dump_unknown()
                return True
            self.rogue_remove_reset()
            return False
        if remove:
            self.rogue_card_page_record('remove')
        if not press.reached():
            return True
        press.reset()
        if self.remove_stage == 3:
            if self.remove_wait.reached():
                self.rogue_remove_cancel()
            return True
        if self.remove_done >= self.rogue_delete_times():
            logger.info('Removal quota reached (%s), leave the page' % self.remove_done)
            self.rogue_remove_cancel()
            return True
        if self.remove_stage == 2:
            if self.remove_wait.reached():
                if ready and self.remove_tries < REMOVE_MAX_TRIES:
                    self.remove_tries += 1
                    self.rogue_remove_submit(ready)
                else:
                    self.rogue_dump_unknown()
                    raise TaskFailed('Card removal result was not confirmed, stop for review')
            return True
        if self.remove_stage == 1:
            if ready:
                self.rogue_remove_submit(ready)
            elif self.remove_wait.reached():
                logger.info('Removal card was not selected, retry recognition')
                self.remove_stage = 0
                self.remove_target = None
            return True
        if ready or self.remove_tries >= REMOVE_MAX_TRIES:
            # An externally selected card has no verified identity or priority.
            logger.info('No verified removal target after %s tries, leave without removing'
                        % self.remove_tries)
            self.rogue_remove_cancel()
            return True
        if self.remove_tries == 0:
            # First scan of this page visit: the grid may still be scrolled from
            # a previous visit, so home it before looking (hard rule 181).
            self.rogue_remove_to_top()
        self.remove_tries += 1
        picked = self.rogue_remove_pick()
        if picked is None:
            logger.info('Removal recognition missed (%s/%s), quota unchanged'
                        % (self.remove_tries, REMOVE_MAX_TRIES))
            return True
        self.remove_target = picked
        self.remove_stage = 1
        self.remove_wait = Timer(REMOVE_WAIT, count=1).start()
        logger.info('Remove %s at %s, priority 劍幕 > 劍光' % (picked[1], picked[0]))
        self.tap_point(*picked[0], name='ROGUE_REMOVE_CARD')
        return True

    def rogue_remove_appear(self):
        """
        Whether this frame is the 「請選擇 N 張欲移除的卡牌」 card-removal page.

        顶部红色标题条 (105,12)-(430,58)：955 帧里 14 帧 ≥0.85（其中 12 帧 ≥0.999），
        次高 0.352；`rouge_dev_13/14/15` 的 0.895 是「轉換卡牌」页（标题只差一个字），
        所以这里用 0.93 把它们排除掉。

        Returns:
            bool: If this frame is the card-removal page.
        """
        return self.appear(ROGUE_REMOVE, offset=(12, 8), similarity=0.93)

    def rogue_member_index(self, preferred=None):
        """
        Which of the three portraits to pick.

        用户 2026-11-15：亮着的角色还有没闪出来的卡（选它 = 该角色随机一张没闪的卡
        灵光），暗掉的角色已经全闪完 —— 实测**暗的那张点不动**：点上去只弹一个灰色
        齿轮圈，牌面变灰，`確認` 还是灰的（00:3x 实机：只有中间那张能选）。

        先按指定号位（默认 `RogueMember`）；如果那一张的牌面对比度明显
        低于最花的那张，就改选对比度最高的（灰掉的牌面几乎是单色，std 差一倍以上）。

        Returns:
            int: 1-based index of the portrait to try first.
        """
        index = self.config.ChaoszeroRogue_RogueMember if preferred is None else preferred
        try:
            index = int(index)
        except (TypeError, ValueError):
            index = 1
        index = min(max(index, 1), len(MEMBER_POINTS))

        contrasts = []
        for x, y in MEMBER_POINTS:
            patch = self.image_crop((x - 60, y - 90, x + 60, y + 90)).astype(int)
            contrasts.append(float(patch.std()))
        best = max(range(len(contrasts)), key=lambda i: contrasts[i])
        if contrasts[index - 1] < contrasts[best] * 0.7:
            logger.info('Portrait %s looks flashed out (std %.0f vs %.0f), try %s instead'
                        % (index, contrasts[index - 1], contrasts[best], best + 1))
            index = best + 1
        return index

    def rogue_member_selected(self):
        """
        Whether a portrait has been accepted (the 確認 pill turns orange).

        Returns:
            tuple: (x, y) of the orange 確認, or None.
        """
        return self.rogue_confirm_point(MEMBER_CONFIRM_AREA, MEMBER_CONFIRM_SIZE)

    def rogue_template_score(self, path, area, pad=20):
        """
        Similarity of a grey-scaled template against a screen area.

        ❗**不要用 `appear()` / `Button.match()` 判这两个新素材。** 2026-11-15 实测：
        `ROGUE_SHOP_REMOVE.match(image, offset=(20,20), similarity=0.99)` 在**营地页
        也返回 True**（连同商店页、还试了 strict=0.99），而同一张图自己用 cv2 量出来是
        营地页 0.445 / 商店页 1.000 —— 这套 dict-area 的模板加载在这两个素材上不可靠。
        所以统一走自己的灰度匹配，分数直接可比。

        Args:
            path (str): Template png, relative to the repo root.
            area (tuple): x1, y1, x2, y2 to search around.
            pad (int): Extra margin around the area (the card moves when selected).

        Returns:
            float: 0.0 - 1.0, 0.0 when the template is missing.
        """
        import os

        # ❗这个缓存只在 `rogue_run()` 里初始化，而判据也会被 `rogue_quit()` 等
        # 别的入口调到，所以这里兜底建一次，别依赖初始化顺序。
        cache = getattr(self, 'template_cache', None)
        if cache is None:
            cache = {}
            self.template_cache = cache
        template = cache.get(path)
        if template is None:
            if not os.path.exists(path):
                logger.warning('Template %s is missing' % path)
                return 0.0
            image = cv2.imread(path)
            if image is None:
                return 0.0
            template = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            cache[path] = template
        grey = cv2.cvtColor(self.device.image, cv2.COLOR_RGB2GRAY)
        x1, y1, x2, y2 = area
        patch = grey[max(0, y1 - pad):y2 + pad, max(0, x1 - pad):x2 + pad]
        if patch.shape[0] < template.shape[0] or patch.shape[1] < template.shape[1]:
            return 0.0
        return float(cv2.matchTemplate(patch, template, cv2.TM_CCOEFF_NORMED).max())

    def rogue_shop_appear(self):
        """
        Whether the 德朗商店 interior page is up.

        判据是右上那张「移除卡牌」卡（用户 spec `chaoszero_卡牌移除` page_2 的
        box (780,162)-(857,250)：粉紫底 + `移除卡牌` 白字 + 价格）。
        实测 cv2 相似度：商店页 1.000，营地页 0.445，其余页 ≤0.524。

        Returns:
            bool: If the shop page is up.
        """
        return self.rogue_template_score(
            './assets/chaoszero/chaoszero/ROGUE_SHOP_REMOVE.png',
            SHOP_REMOVE_AREA, pad=20) >= SHOP_REMOVE_SIMILARITY

    def rogue_shop_sold_appear(self):
        """
        Whether the shop's card-removal service is already sold out.

        这个营地的删卡用掉之后，右上那块「移除卡牌」会变成「售罄」黑面板。
        实测 cv2 灰度：售罄页 1.000 / 正常商店页 0.092~0.100。

        Returns:
            bool: If the removal service is sold out.
        """
        return self.rogue_template_score(
            './assets/chaoszero/chaoszero/ROGUE_SHOP_SOLD.png',
            SHOP_SOLD_AREA, pad=40) >= SHOP_SOLD_SIMILARITY

    def rogue_loot_appear(self):
        """
        Whether this is the BOSS loot page (複製卡牌 / 裝備 / 信用點數 + 獲得 N).

        第一面打完就会出这一页，之后进「核心」（第二张地图）。判据用右上那颗
        **紫色「複製卡牌」大按钮**的颜色面积 —— 实测该区域紫色 13708 像素，
        而装备行 / 信用點數行都是 0，左半屏只有 267，非常干净。

        Returns:
            bool: If the loot page is on screen.
        """
        x1, y1, x2, y2 = LOOT_AREA
        patch = self.device.image[y1:y2, x1:x2, :3].astype(np.int32)
        red, green, blue = patch[:, :, 0], patch[:, :, 1], patch[:, :, 2]
        purple = (red > 140) & (blue > 140) & (green < 110)
        return int(purple.sum()) >= LOOT_PURPLE

    def rogue_treasure_card_stage(self):
        """
        傳送門 / 寶物倉庫入口卡的状态，0 = 不在，1 = 未选中，2 = 已选中。

        ❗这张卡有**两个外观**，必须分开认：
        - 未选中（spec page_1）：紫色细边、卡片偏下；
        - 已选中（spec page_2）：卡片上移 + 底部发光 + 下方 `∨` 变大。
        只用一个模板会认不出另一种状态 —— 2026-11-15 实测：同一个人看到的同一页，
        `treasure_bad.png`（未选中）匹配 **1.000**、`treasure_unknown.png`（已选中）
        只有 **0.480**，判据 False → `treasure_stage` 被重置 → 又去点卡 → 死循环，
        最后掉进未知页。两个模板对两帧分别是 1.000/0.512 和 0.480/1.000，互斥得很干净。

        Returns:
            int: 0 / 1 / 2。
        """
        first = self.rogue_template_score(
            './assets/chaoszero/chaoszero/ROGUE_TREASURE_CARD.png',
            TREASURE_CARD_AREA, pad=40)
        second = self.rogue_template_score(
            './assets/chaoszero/chaoszero/ROGUE_TREASURE_CARD2.png',
            TREASURE_CARD_AREA, pad=40)
        if max(first, second) < TREASURE_CARD_SIMILARITY:
            return 0
        return 1 if first >= second else 2

    def rogue_treasure_card_appear(self):
        """
        Whether the 傳送門 card that leads into 寶物倉庫 is on screen.

        Returns:
            bool: If the card is there (either state).
        """
        return self.rogue_treasure_card_stage() > 0

    def rogue_chest_template(self):
        """
        Grey-scaled template of the cat-head icon above a closed chest.

        用灰度而不是彩色：三个箱子的底色不一样（紫/蓝/黄），彩色匹配更脆；
        实测灰度在同一批帧上是 0.976 / 1.000 / 0.974（三箱都在）和 0.447 / 0.424 / 0.387
        （全开完），分得比彩色还开一点。

        Returns:
            np.ndarray | None: Template, or None when the asset is missing.
        """
        if self.chest_grey is None:
            import os
            path = './assets/chaoszero/chaoszero/ROGUE_CHEST.png'
            if not os.path.exists(path):
                logger.warning('ROGUE_CHEST.png is missing, treasure room is skipped')
                return None
            image = cv2.imread(path)
            if image is None:
                return None
            self.chest_grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        return self.chest_grey

    def rogue_treasure_slot(self):
        """
        Locate a chest that is still closed in the 寶物倉庫 room.

        三个箱位是固定的（用户 spec page_3/4/5 的 elements[].box），箱子开掉之后
        上方的猫头图标就没了 —— 所以「图标还在」= 「这个箱子还没开」。逐个返回，
        一次只点一个。

        Returns:
            tuple[int, int] | None: centre of the first closed chest, or None.
        """
        template = self.rogue_chest_template()
        if template is None:
            return None
        image = self.device.image
        grey = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        for x1, y1, x2, y2 in TREASURE_SLOTS:
            patch = grey[max(0, y1 - TREASURE_PAD):y2 + TREASURE_PAD,
                         max(0, x1 - TREASURE_PAD):x2 + TREASURE_PAD]
            if patch.shape[0] < template.shape[0] or patch.shape[1] < template.shape[1]:
                continue
            score = cv2.matchTemplate(patch, template, cv2.TM_CCOEFF_NORMED).max()
            if score >= TREASURE_SIMILARITY:
                logger.info('Closed chest at slot (%s, %s), score %.3f'
                            % ((x1 + x2) // 2, (y1 + y2) // 2, score))
                return (x1 + x2) // 2, (y1 + y2) // 2
        return None

    def rogue_map_appear(self):
        """
        Whether the screen is the map (and thus a node can be entered).

        The judge is the **zoom button on the route minimap panel** (bottom
        left). Only the button is stable: the panel body *is* the route graph and
        changes every floor, so the old panel-body template (22,452,212,520)
        scored 0.22 on today's maps — which is why the loop stopped treating the
        map as a map and stalled for 8 minutes (2026-11-14 01:06).

        Measured on the button patch instead: 1.000 / 0.978 on map frames (new and
        old), at most 0.150 on battle / story / event / fate / reward frames.

        The panel can also be collapsed (button hides in the bottom-left pill as
        ⊙, `ROGUE_ZOOM_OUT`), and the HUD disappears for a moment right after a
        node resolves — those frames match neither and are simply waited out.

        Returns:
            bool: If this frame looks like the map.
        """
        if self.appear(ROGUE_MAP_BTN, offset=(10, 10), similarity=0.9):
            return True
        return self.appear(ROGUE_ZOOM_OUT, offset=(8, 8), similarity=0.85)

    def rogue_map_preview_appear(self):
        """
        Whether the map is in the zoomed-out 2D preview.

        The 2D preview cannot move the party at all (confirmed by the user), it
        only shows the route. The same bottom-left button that opened it goes
        back: ⊙ zoom-out on the 3D map, ⊕ zoom-in inside the preview. The two
        templates sit on the same area and score 1.000 on their own state and at
        most 0.31 on every other saved frame.

        Returns:
            bool: If the screen is the 2D preview.
        """
        return self.appear(ROGUE_PREVIEW, offset=(10, 8), similarity=0.9)

    # ---------------------------------------------------------------- 动作

    def rogue_click_stuck(self):
        """
        Whether the recent presses are already inside the framework's watchdog.

        `click_record_check()` raises `GameTooManyClickError` (and the client is
        restarted) at 12 clicks of one button, or 6 + 6 of two buttons, inside a
        15-click window. Stopping one step earlier keeps the run and the client
        alive: what is left is a page we cannot read, and the next round can
        retry it with a better judge.

        Returns:
            bool: If the loop should stop.
        """
        count = collections.Counter(self.device.click_record).most_common(2)
        if count and count[0][1] >= 9:
            return True
        if len(count) >= 2 and count[0][1] >= 5 and count[1][1] >= 5:
            return True
        return False

    def rogue_pick(self, points, index):
        """
        Press one of a row of cards.

        Args:
            points (tuple): Card centres.
            index (int): 1-based card number.

        Returns:
            bool: If the press was issued.
        """
        if not 1 <= index <= len(points):
            index = 1
        x, y = points[index - 1]
        logger.info('Pick card %s at (%s, %s)' % (index, x, y))
        self.tap_point(x, y, name='ROGUE_CARD')
        return True

    def rogue_world_appear(self, world):
        """
        Locate one world name label on the 卡厄思顯現 world list.

        Args:
            world (str): 世界名，`WORLD_LABELS` 的键。

        Returns:
            tuple: 标签中心 (x, y)；没找到返回 None。
        """
        button = WORLD_LABELS.get(world)
        if button is None:
            return None
        # offset 放到近全屏：列表能被拖，标签的 y 只有两档（上排 220 / 下排 490），
        # x 随拖动在 60~1280 之间。0.85 的阈值下 216 帧里没有误命中。
        if self.appear(button, offset=(620, 340), similarity=0.85):
            x1, y1, x2, y2 = button.button
            return (x1 + x2) // 2, (y1 + y2) // 2
        return None

    def rogue_world_select(self, world, timeout=90):
        """
        Scroll the world list to the configured world and open its detail page.

        Pages:
            in:  卡厄思顯現 世界列表
            out: 目标世界的详情页（`ROGUE_WORLD_ENTER`）

        Args:
            world (str): 世界名，`WORLD_LABELS` 的键。

        Returns:
            bool: If the target world detail page is up.
        """
        logger.hr('Pick the world %s' % world, level=2)
        if world not in WORLD_LABELS:
            logger.warning('Unknown world %s, keep the one the game shows' % world)
            return True

        press = Timer(2, count=2)
        rewinds = 0
        scans = 0

        for _ in self.loop(timeout=timeout):
            self.device.stuck_record_clear()

            if self.appear(ROGUE_WORLD_ENTER, offset=(10, 10), similarity=0.92):
                logger.info('World detail page is up')
                return True

            center = self.rogue_world_appear(world)
            if center is not None:
                if press.reached():
                    press.reset()
                    dx, dy = WORLD_OFFSETS[world]
                    x, y = center[0] + dx, center[1] + dy
                    logger.info('Open the world %s at (%s, %s)' % (world, x, y))
                    self.tap_point(x, y, name='ROGUE_WORLD_PICK')
                continue

            # ❗列表的位置是游戏记住的：先统一拖回最左做归一化，再一屏一屏往右找，
            # 否则「上次停在第 5 个世界」时会永远找不到左边的世界。
            if rewinds < WORLD_REWINDS:
                if press.reached():
                    press.reset()
                    rewinds += 1
                    logger.info('Scroll the world list back (%s/%s)'
                                % (rewinds, WORLD_REWINDS))
                    self.device.swipe(WORLD_SCROLL_BACK[0], WORLD_SCROLL_BACK[1],
                                      name='ROGUE_WORLD_SCROLL')
                continue
            if scans < WORLD_SCANS:
                if press.reached():
                    press.reset()
                    scans += 1
                    logger.info('Scroll the world list right (%s/%s)'
                                % (scans, WORLD_SCANS))
                    self.device.swipe(WORLD_SCROLL[0], WORLD_SCROLL[1],
                                      name='ROGUE_WORLD_SCROLL')
                continue

            logger.warning('The world %s is not in the list' % world)
            return False

        logger.warning('Never got into the world %s' % world)
        return False

    def rogue_dream_state(self):
        """
        Read the 梦境模式 switch on the 「配置隊伍」 page.

        Returns:
            bool | None: True when on (purple page, knob right), False when off,
                None when the switch is not on screen (page still painting, or
                the mode is not unlocked yet).
        """
        if self.appear(ROGUE_DREAM_ON, offset=(20, 20), similarity=0.9):
            return True
        if self.appear(ROGUE_DREAM_OFF, offset=(20, 20), similarity=0.9):
            return False
        return None

    def rogue_dream_set(self, want, tries=DREAM_TRIES):
        """
        Turn 梦境模式 on or off and wait for the switch to show that state.

        Args:
            want (bool): True to enable, False to disable.
            tries (int): How many times to press the switch.

        Returns:
            bool: If the switch ends up in the wanted state.
        """
        press = Timer(2, count=2)

        for _ in self.loop(timeout=Timer(20, count=1)):
            self.device.stuck_record_clear()

            if self.appear(ROGUE_DREAM_NOTICE, offset=(20, 20), similarity=0.9):
                # 第一次开启梦境模式会弹一整页说明（精神異常 / 崩潰加劇 / 靈光一閃機率
                # 增加 / 存檔資料增加 + 紫色 `確認`）。不关掉它队伍页不会回来，开关
                # 也读不到（用户 2026-11-14 提供的截图）。
                if press.reached():
                    press.reset()
                    logger.info('Close the dream mode notice')
                    self.device.click(ROGUE_DREAM_OK)  # alas-lint: allow - guarded by the appear() above
                continue

            state = self.rogue_dream_state()
            if state is None:
                # 页面还在淡入，或者梦境模式还没解锁（没崩溃过时这页可能没有开关）。
                continue
            if state == want:
                logger.info('Dream mode is %s' % ('on' if want else 'off'))
                return True
            if not press.reached():
                continue

            press.reset()
            tries -= 1
            if tries <= 0:
                break
            logger.info('Turn dream mode %s' % ('on' if want else 'off'))
            self.tap_point(*DREAM_POINT, name='ROGUE_DREAM')

        logger.warning('Dream mode is still %s, continue anyway'
                       % ('off' if want else 'on'))
        return False

    def rogue_enter_team(self, timeout=180, reselect_world=True):
        """
        Walk from the lobby to the 「配置隊伍」 page of 卡厄思顯現 and stop there.

        入口是**五页**（2026-11-14 实机逐页量过）：大厅 → 卡厄思（两卡）→
        卡厄思顯現（世界列表）→ 世界详情 → 配置隊伍。每页一个模板判据，认出一页
        点一下就等它翻页；认不出就等（黑屏加载约 8 秒）。

        Args:
            timeout (int): Seconds to spend walking the chain.
            reselect_world (bool): Back out to the world list and pick
                `RogueWorld` again. False on the next run of a continuous
                session: the game already remembers the world just finished.

        Returns:
            bool: If the team page is on screen.
        """
        logger.hr('Walk to 卡厄思顯現 team', level=2)

        # 同一页 2 秒内只点一次：双击会把队伍页的 `進入` 在弹窗起来之后再点一次。
        last = None
        press = Timer(2, count=2)
        idle = Timer(5, count=2)
        # 配置指定了世界就必须自己选一遍：游戏会记住上次那个世界，进模式页可能直接
        # 落在上次的详情页或队伍页，先退到列表，选完再进来（`world_checked`）。
        # 例外（用户 2026-11-19）：刚打完一局的下一轮记住的就是刚刷的世界，队伍页/
        # 详情页直接沿用、不再退两次；只有真到了世界列表才仍然重选，防止刷错地图。
        world = self.config.ChaoszeroRogue_RogueWorld
        world_checked = world not in WORLD_LABELS
        wakes = 0

        for _ in self.loop(timeout=Timer(timeout, count=1)):
            self.device.stuck_record_clear()

            if self.appear(ROGUE_DREAM_NOTICE, offset=(20, 20), similarity=0.9):
                if press.reached():
                    press.reset()
                    logger.info('Close the dream mode notice')
                    self.device.click(ROGUE_DREAM_OK)  # alas-lint: allow - guarded by the appear() above
                continue

            # 客户端断线恢复弹窗：重开后第一屏就是它，点 `繼續進行` 保住这一局。
            if self.rogue_resume_appear():
                if press.reached():
                    press.reset()
                    logger.info('Client reconnected, continue the run')
                    self.tap_point(RESUME_CONTINUE_POINT[0], RESUME_CONTINUE_POINT[1],
                                   name='ROGUE_RESUME')
                continue

            page = None
            if self.rogue_team_appear():
                if world_checked or not reselect_world:
                    logger.info('Team page is up')
                    # 队伍页右上角就是梦境模式开关：开 = 整页变紫、上限 110pt，刷档要开。
                    mode = self.config.ChaoszeroRogue_RogueDreamMode
                    if mode == '開啟':
                        self.rogue_dream_set(True)
                    elif mode == '關閉':
                        self.rogue_dream_set(False)
                    return True
                page = 'team'
            elif self.ui_page_appear(page_main):
                page = 'lobby'
            elif self.appear(ROGUE_MODE_ENTRY, offset=(20, 20), similarity=0.92):
                page = 'mode'
            elif self.appear(ROGUE_WORLD_LIST, offset=(20, 20), similarity=0.92):
                page = 'world-list'
            elif self.appear(ROGUE_WORLD_ENTER, offset=(10, 10), similarity=0.92):
                page = 'world'

            if page != last:
                last = page
                press.reset()
                idle.reset()
                if page:
                    logger.info('Entry page: %s' % page)
            if page is None:
                # 黑屏加载 / 待机立绘：待机立绘上没有任何页面模板，点一下就能回大厅。
                # ❗这里不能连点：点完要等立绘淡出（约 1 秒），否则会点在空处。
                # ❗也不能一直点：认不出页面说明根本不在入口链上（局内 / 活动 / 弹窗），
                # 唤醒是没用的 —— 12 次同名点击会触发看门狗重启客户端（14:01 踩过）。
                if idle.reached():
                    idle.reset()
                    wakes += 1
                    if wakes > WAKE_TRIES:
                        logger.warning('The screen is not on the entry chain, stop walking')
                        return False
                    logger.info('No page recognized, wake the screen')
                    self.tap_point(*CHAOSZERO_WAKE, name='ROGUE_WAKE')
                continue
            if not press.reached():
                continue
            press.reset()

            if page == 'lobby':
                self.tap_point(*LOBBY_ROGUE, name='ROGUE_MENU')
            elif page == 'mode':
                # ❗点大卡片本体（左卡 = 卡厄思顯現），不点文字标签：标签在
                # (300,550)-(500,600)，模板匹配的落点会飘到标签上边缘 (344,540)。
                self.tap_point(*MODE_CARD, name='ROGUE_MODE')
            elif page == 'world-list':
                if world_checked:
                    self.tap_point(*WORLD_CARD, name='ROGUE_WORLD')
                elif self.rogue_world_select(world):
                    world_checked = True
            elif page == 'world' and (world_checked or not reselect_world):
                self.device.click(ROGUE_WORLD_ENTER)  # alas-lint: allow - guarded by the appear() that chose this branch
            elif page in ('team', 'world'):
                logger.info('Back from the %s page to pick %s' % (page, world))
                self.tap_point(*WORLD_BACK_POINT, name='ROGUE_WORLD_BACK')

        logger.warning('Never got to the team page, the entry chain moved')
        return False

    def rogue_enter(self, reselect_world=True):
        """
        Walk from the lobby into a run.

        Pages:
            in:  配置隊伍（`rogue_enter_team()` 走到这里）
            out: 局内（命运剧情 / 事件 / 地图）

        Args:
            reselect_world (bool): Passed to `rogue_enter_team()`.

        Returns:
            bool: If the run started.
        """
        if not self.rogue_enter_team(reselect_world=reselect_world):
            return False

        logger.info('Enter the run')
        last = None
        press = Timer(2, count=2)
        idle = Timer(5, count=2)
        wakes = 0

        for _ in self.loop(timeout=180):
            self.device.stuck_record_clear()

            # 梦境模式开着时，点 `進入` 会先弹一整页说明（四项效果 + 紫色 `確認`）。
            # 不认它就会被后面的判据当成局内页面（2026-11-14 14:04 实拍）。
            if self.appear(ROGUE_DREAM_NOTICE, offset=(20, 20), similarity=0.9):
                if press.reached():
                    press.reset()
                    logger.info('Close the dream mode notice')
                    self.device.click(ROGUE_DREAM_OK)  # alas-lint: allow - guarded by the appear() above
                continue

            if (self.rogue_primary_point() or self.rogue_story_appear()
                    or self.rogue_choice_appear() or self.rogue_battle_appear()
                    or self.rogue_herald_appear() or self.rogue_option_points()
                    or self.rogue_equip_appear() or self.rogue_rest_appear()
                    or self.rogue_copy_appear()
                    or self.rogue_remove_appear()
                    or self.rogue_map_appear()):
                logger.info('Run started')
                return True

            page = None
            if self.appear(DIALOG_ENTER, offset=(20, 20), similarity=0.92):
                page = 'dialog'
            elif self.rogue_team_appear():
                page = 'team'

            if page != last:
                last = page
                press.reset()
                idle.reset()
                if page:
                    logger.info('Entry page: %s' % page)
            if page is None:
                if idle.reached():
                    idle.reset()
                    wakes += 1
                    if wakes > WAKE_TRIES:
                        logger.warning('The screen is not on the entry chain, stop entering')
                        return False
                    logger.info('No page recognized, wake the screen')
                    self.tap_point(*CHAOSZERO_WAKE, name='ROGUE_WAKE')
                continue
            if not press.reached():
                continue
            press.reset()

            if page == 'team':
                self.tap_point(*TEAM_ENTER_POINT, name='ROGUE_TEAM_ENTER')
            else:
                self.device.click(DIALOG_ENTER)  # alas-lint: allow - guarded by the appear() that chose this branch

        logger.warning('Never got into a run, the entry chain moved')
        return False

    # ---------------------------------------------------------------- 治疗中心

    def rogue_cure_appear(self):
        """
        Whether this is the `諮商紀錄` page (the room list where a crashed operative
        is picked).

        判据是左下角那颗 `諮商紀錄` 胶囊上的文字（115,649,227,681）：实机帧上
        这一页 1.000，治疗中心房间页 0.078、方舟都市 0.055、局内 0.34。
        **不是点击目标**，只用来确认已经进了治疗中心（用户 2026-11-15 明确）。

        Returns:
            bool: If the consult page is on screen.
        """
        return self.appear(ROGUE_CONSULT, offset=(20, 10), similarity=0.9)

    def rogue_crash_cure_point(self):
        """
        The green `治療中心` pill on the crash page, as a click point.

        两种崩溃页的胶囊横坐标完全不同（`觸發精神異常` 在 740~990，`夢境模式` 在
        17~263），所以不写死坐标，按底部那条色带里的绿色连通块找质心
        （实机：宽 246x56 area 9239 / 219x52 area 6258）。

        Returns:
            tuple[int, int] | None: Pill centre, None if there is no such pill.
        """
        image = self.device.image
        x1, y1, x2, y2 = CRASH_GREEN_AREA
        part = image[y1:y2, x1:x2, :3].astype('int32')
        mask = ((part[:, :, 1] > 120) & (part[:, :, 0] < 110) & (part[:, :, 2] < 140)).astype('uint8')
        count, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 1)
        best = None
        for index in range(1, count):
            area = stats[index, cv2.CC_STAT_AREA]
            width = stats[index, cv2.CC_STAT_WIDTH]
            height = stats[index, cv2.CC_STAT_HEIGHT]
            if area < 1500:
                continue
            if not CRASH_GREEN_WIDTH[0] <= width <= CRASH_GREEN_WIDTH[1]:
                continue
            if not CRASH_GREEN_HEIGHT[0] <= height <= CRASH_GREEN_HEIGHT[1]:
                continue
            if best is None or area > best[0]:
                best = (area, centroids[index][0], centroids[index][1])
        if best is None:
            return None
        return int(best[1]) + x1, int(best[2]) + y1

    def rogue_crash_appear(self):
        """
        Whether the game is showing a crash page (an operative needs treatment).

        需要治疗时游戏**自己**弹（2026-11-15 用户），所以不用回大厅也不用每局去查：
        底部有大块绿色 `治療中心` + 右侧有大块紫色 `下一步`/`確認` 就是这两种崩溃页。
        `諮商紀錄` 页左下那颗绿胶囊（諮商紀錄）形状一样，所以先用页面判据排掉，
        否则治到一半会被当成崩溃页又去点一次。

        Returns:
            bool: If a crash page is on screen.
        """
        # ❗先排掉「BATTLE COMPLETE」结算大字：那一页底部也有绿/紫元素，
        # 三条判据（绿胶囊 + 右侧紫色 + 不在諮商頁）**全部通过**，于是被当成崩溃页，
        # 点了 (852,660) 进到错误流程，日志 `The treatment chain stopped on an
        # unknown page`（2026-11-16 03:00 实测）。这页是纯展示、会自己过去，什么都不用点。
        if self.appear(ROGUE_BATTLE_COMPLETE, offset=(20, 16), similarity=0.85):
            return False
        if self.rogue_cure_appear():
            return False
        if self.rogue_crash_cure_point() is None:
            return False
        return self.rogue_count(CRASH_PURPLE_AREA, 'purple') >= CRASH_PURPLE_MIN

    def rogue_crash_handle(self):
        """
        Press `治療中心` on the crash page and walk the treatment chain.

        以前这一页只会被当成普通页面，紫色的 `下一步` 被主按钮分支点掉，崩溃的角色
        一直治不了。治完继续刷就行，对产出没有影响（2026-11-15 用户确认）。

        Returns:
            bool: True if the treatment chain was handled.
        """
        point = self.rogue_crash_cure_point()
        logger.info('An operative crashed, open the treatment center at (%s, %s)' % point)
        self.tap_point(point[0], point[1], name='ROGUE_CRASH_CURE')
        return self.cure_run()

    def rogue_cure_none(self):
        """
        Whether the consult page says `等待中… / 無恢復中的幹員。` (nobody crashed).

        Returns:
            bool: If no operative is waiting for treatment.
        """
        return self.appear(ROGUE_CURE_NONE, offset=(20, 20), similarity=0.9)

    def rogue_erase_ready(self):
        """
        Whether the `消除記憶` button is lit (a card was picked).

        没选人时按钮是灰的，紫色像素 **0**；选中后变紫并显示花费，紫色 ~12000
        （实机 2026-11-15：cr_3 灰页 0 / cr_4 选中页 12122）。角色卡位置不固定，
        所以选人只能"点一格 -> 看按钮有没有变紫"，不靠角色卡的模板。

        Returns:
            bool: If the erase button is available.
        """
        image = self.device.image
        x1, y1, x2, y2 = CURE_ERASE_AREA
        part = image[y1:y2, x1:x2, :3].astype('int32')
        mask = ((part[:, :, 2] > 140) & (part[:, :, 0] > 90)
                & (part[:, :, 1] < 130) & (part[:, :, 2] > part[:, :, 1] + 40))
        return bool(mask.sum() > CURE_ERASE_PURPLE)

    def cure_run(self, timeout=600):
        """
        Treat every crashed operative on the `諮商紀錄` page.

        实机链（2026-11-15 逐步确认，从崩溃页点绿色 `治療中心` 进来）：
            諮商紀錄页（角色卡 2 列网格，人数变少会往前补位）
            → 点一格卡（选中后 `消除記憶` 从灰变紫并显示花费）
            → 按 `消除記憶` → 确认框（橙色 `消除記憶` + 花费，落在 DIALOG_AREA 里）
            → 治疗过场（黑色横幅上的 `批准`）→ `已消除記憶。` 的 ▼ → 回到諮商紀錄页
            → 还有人就再来一遍，直到 `等待中… / 無恢復中的幹員。`
            → 左上返回箭头 (45,37) 退出治疗中心

        治疗会销毁该角色的存档（确认框自己写着 `即將消滅的損壞資料 N`），用户已确认
        "治疗后继续刷就是了，没有任何影响"，所以这里不拦。崩溃一天一次，所以整条链
        只会在游戏自己弹出崩溃页时走。

        Args:
            timeout (int): Seconds to spend on the whole treatment.

        Returns:
            bool: True if the page was handled (including "nothing to do").
        """
        logger.hr('Treatment center', level=2)
        # 治过人就说明这一局有角色崩溃了：崩溃角色的存档在治疗后也会被销毁，
        # 等于这一局白打。调用方靠这个标记报警（2026-11-15 用户说明）。
        self.cure_treated = False
        press = Timer(2, count=2)
        # 页与页之间会有一帧黑场/过场，第一次认不出来不能直接放弃。
        # ❗必须 `.start()`：Alas 的 `Timer` 没 start 时 `reached()` 直接返回 True，
        # 于是第一帧就判「unknown page」放弃 —— 实测点完「治療中心」0.16 秒就退出了
        # （2026-11-16 03:06，`The treatment chain stopped on an unknown page`），
        # 崩溃角色一次都没治成。认可页面时会 `unknown.reset()` 重新计时。
        # ❗15 → 30 秒：按完「消除記憶」到「批准」黑横幅出现实测要 **16 秒**
        # （03:08:48 按 erase → 03:09:04 判死，而截图证明那一刻正是「批准」页），
        # 15 秒刚好卡在边界上，每次都会提前放弃。
        unknown = Timer(30, count=1).start()
        slot = 0

        for _ in self.loop(timeout=Timer(timeout, count=1)):
            self.device.stuck_record_clear()

            # ❗还停在崩溃页 = 刚才点「治療中心」没生效（那一下常常被入场动画吃掉）。
            #   这里重试，否则会干等 15 秒后放弃，崩溃角色白崩。
            if self.rogue_crash_appear():
                point = self.rogue_crash_cure_point()
                if point and press.reached():
                    press.reset()
                    logger.info('Still on the crash page, press 治療中心 again at (%s, %s)'
                                % point)
                    self.tap_point(point[0], point[1], name='ROGUE_CRASH_CURE')
                continue

            # 治疗过场：黑色横幅上的 `批准`
            if self.appear(ROGUE_CURE_APPROVE, offset=(12, 12), similarity=0.85):
                unknown.reset()
                if press.reached():
                    press.reset()
                    logger.info('Approve the memory wipe')
                    self.tap_point(*CURE_APPROVE_POINT, name='ROGUE_CURE_APPROVE')
                continue

            if self.rogue_cure_appear():
                unknown.reset()
                if self.rogue_cure_none():
                    logger.info('Nobody is waiting for treatment')
                    self.tap_point(*CURE_BACK_POINT, name='ROGUE_CURE_BACK')
                    return True
                if self.rogue_erase_ready():
                    if press.reached():
                        press.reset()
                        logger.info('Erase the memory of the picked operative')
                        self.cure_treated = True
                        self.tap_point(*CURE_ERASE_POINT, name='ROGUE_CURE_ERASE')
                    continue
                if slot < len(CURE_SLOTS) * 2:
                    if press.reached():
                        press.reset()
                        x, y = CURE_SLOTS[slot % len(CURE_SLOTS)]
                        slot += 1
                        logger.info('Pick the downed operative %s at (%s, %s)' % (slot, x, y))
                        self.tap_point(x, y, name='ROGUE_CURE_CARD')
                    continue
                logger.warning('No operative card could be picked, leave the treatment center')
                self.tap_point(*CURE_BACK_POINT, name='ROGUE_CURE_BACK')
                return False

            # 消除記憶 的确认框：橙色按钮落在 DIALOG_AREA 里
            point = self.rogue_dialog_point()
            if point:
                unknown.reset()
                if press.reached():
                    press.reset()
                    logger.info('Confirm the memory wipe at (%s, %s)' % point)
                    self.tap_point(point[0], point[1], name='ROGUE_CURE_CONFIRM')
                continue

            # 过场对话 / `已消除記憶。` 的 ▼
            if self.rogue_story_appear():
                unknown.reset()
                if press.reached():
                    press.reset()
                    logger.info('Advance the treatment story')
                    self.tap_point(*CURE_STORY_POINT, name='ROGUE_CURE_STORY')
                continue

            if press.reached():
                press.reset()
                if unknown.reached():
                    logger.warning('The treatment chain stopped on an unknown page')
                    return False

        logger.warning('Never finished the treatment center')
        return False

    # ---------------------------------------------------------------- 局内撤退

    def rogue_outside_appear(self):
        """Recognize the lobby and Rogue entry pages where no run is active."""
        return (self.ui_page_appear(page_main) or self.rogue_team_appear()
                or self.appear(ROGUE_MODE_ENTRY, offset=(20, 20), similarity=0.92))

    def rogue_quit(self, timeout=120, *, discard_saves=False):
        """
        Leave the current run: ☰ → 「卡厄思資訊」→ 橙色 `撤退` → 大厅.

        用户 2026-11-14 要求：第一页没闪到想要的卡时，要能中途退出重开一局。
        撤退后的落点实测（2026-11-14 14:26，雾之城市 第6阶段）：确认对话框的
        `確認` 一点，**直接回到队伍页 `配置队伍`**，既没有结算页也没有大厅 ——
        所以"撤退成功"要认队伍页，不能只认大厅；回队伍页后可以直接再点 `進入`
        开下一局（正是"第一面没闪到想要的卡就重开"要的行为）。

        面板本身是全屏的，`撤退` 又和底部橙色主按钮同色同尺寸，所以顺序是
        「先认面板 → 点撤退」，对话框/结算页的橙色按钮排在后面处理。

        Args:
            timeout (int): Seconds to spend getting out of the run.
            discard_saves (bool): Decompose this run's saves at settlement.

        Returns:
            bool: If a Rogue entry page or the lobby confirms the run ended.
        """
        logger.hr('Retreat from the run', level=2)
        press = Timer(2, count=2)
        tries = RETREAT_TRIES
        menus = MENU_TRIES
        retreat = False
        confirm_sent = False
        self.settlement_title_wait = None
        self.device.click_record_clear()
        self.device.stuck_record_clear()

        # ❗必须用 self.loop 而不是裸 while：裸循环不重新截图（会一直读同一帧、
        # 也不会给看门狗计数），而且 `Timer.reached()` 在没 start 过时第一次就返回
        # True —— 2026-11-14 14:08 实测裸写直接空跑一次就返回 False。
        for _ in self.loop(timeout=Timer(timeout, count=1)):
            if self.rogue_outside_appear():
                logger.info('Back at the lobby or a Rogue entry page, the run is over')
                return True
            if self.appear(TEAM_TITLE, offset=(20, 20), similarity=0.9):
                logger.warning('The team page is missing Rogue markers, stop retreat')
                return False

            # `獲得道具` 白底弹窗：删存档（点垃圾桶=分解）后立刻弹出来盖住整页。
            # 它没有任何按钮，提示是「點擊畫面可關閉視窗。」；不在这里点掉的话，
            # 存档页的垃圾桶/紫色 `下一步` 判据全灭，本循环只会空转到超时 ——
            # 2026-11-15 实机删完第一张就卡死在这一页（`RogueSaveKeep=0` 链路）。
            if self.rogue_item_appear():
                if press.reached():
                    press.reset()
                    logger.info('Close the reward popup over the save page')
                    self.tap_point(*CUTSCENE_POINT, name='ROGUE_ITEM')
                continue

            # 梦境模式的说明页会挡在撤退面板前面。
            if self.appear(ROGUE_DREAM_NOTICE, offset=(20, 20), similarity=0.9):
                if press.reached():
                    press.reset()
                    logger.info('Close the dream mode notice')
                    self.device.click(ROGUE_DREAM_OK)  # alas-lint: allow - guarded by the appear() above
                continue

            # 面板开着：`撤退` 在 (1031,643)-(1245,693)，和主按钮同一色系，先认它。
            if not retreat and self.appear(ROGUE_RETREAT, offset=(12, 12), similarity=0.9):
                if press.reached():
                    press.reset()
                    tries -= 1
                    if tries <= 0:
                        break
                    retreat = True
                    logger.info('Retreat from this run')
                    self.device.click(ROGUE_RETREAT)  # alas-lint: allow - guarded by the appear() above
                continue

            # 撤退的二次确认（`確認` 在画面中部，不在底部按钮带上）。
            point = self.rogue_dialog_point()
            if point:
                if press.reached():
                    press.reset()
                    logger.info('Confirm the retreat at (%s, %s)' % point)
                    self.tap_point(point[0], point[1], name='ROGUE_DIALOG')
                    confirm_sent = True
                continue

            # 撤退后的两页都是紫色按钮：`探索結果` 的 `下一步` 和整局结算的 `確認`
            # （2026-11-15 11:28 实测：确认撤退后落在 `探索結果`，只有紫色下一步，
            # 旧代码认不出它就一直点 ☰，最后 GameStuckError 把客户端重启了）。
            # ❗撤退同样会走到 `存檔資料收集完成`（过了第一个信标就有存档），
            # 那一页要先处理存档，再点紫色 `下一步`。
            point = self.rogue_purple_point()
            if point:
                page = self.rogue_settlement_page()
                if page == 'save':
                    if press.reached():
                        press.reset()
                        self.rogue_save_handle(point, discard_saves=discard_saves)
                elif page == 'result' and press.reached():
                    press.reset()
                    logger.info('Press the purple button at (%s, %s)' % point)
                    self.tap_point(point[0], point[1], name='ROGUE_PURPLE')
                continue
            self.settlement_title_wait = None

            # 撤退后的结算页：`繼續進行` / `暫時返回` 都是橙色主按钮。
            point = self.rogue_primary_point()
            if point:
                if press.reached():
                    press.reset()
                    logger.info('Press the primary button at (%s, %s)' % point)
                    self.tap_point(point[0], point[1], name='ROGUE_PRIMARY')
                continue

            # 还没开面板（或面板已经关掉）：点右上角 ☰。
            # 二次确认发出后，结算页加载期间只等待下一帧。
            # ❗有次数上限：认不出的页面上连点 12 次同一个按钮会触发框架看门狗
            # （GameTooManyClickError 直接重启客户端，2026-11-14 14:17 实测）。
            if menus > 0 and not confirm_sent:
                if press.reached():
                    press.reset()
                    menus -= 1
                    logger.info('Open the run menu')
                    self.tap_point(*INFO_MENU_POINT, name='ROGUE_INFO_MENU')

        logger.warning('Never got out of the run after retreat')
        return False

    # ---------------------------------------------------------------- 主循环

    def rogue_dump_unknown(self):
        """
        Save one frame per distinct unknown page, into `./log/rogue_pages/`.

        所有判据都不中的页面（商店之类还没写判据的）以前会被 `# 6.8` 的固定点位
        盲点混过去，既不知道到了哪一页，也可能点到商品买错东西。这里把画面按
        24px 采样去重后存一张，跑一局就能收齐「认不出来的页面」，之后再照真帧补判据。
        同一画面只存一次，一局几十张，不会撑爆磁盘。
        """
        import os
        import time

        image = self.device.image
        key = image[::24, ::24].tobytes()
        if key in self.unknown_frames:
            return
        self.unknown_frames.add(key)
        # 画面签名挡不住"会动"的页：战斗过场有粒子/特效，`key` 每帧都不同，
        # 实测一秒存了 5 张、日志刷出几百行（2026-11-15 22:36）。
        # 再加一道时间闸：同一个未知页最多 3 秒存一张。
        if not self.unknown_save.reached():
            return
        self.unknown_save.reset()
        if len(self.unknown_frames) > 300:
            self.unknown_frames.clear()
        folder = './log/rogue_pages'
        if not os.path.exists(folder):
            os.makedirs(folder)
        path = os.path.join(folder, time.strftime('unknown_%H%M%S.png'))
        cv2.imwrite(path, image[:, :, ::-1])
        prune_diagnostics(folder, 'unknown')
        logger.warning('Unknown rogue page, saved a frame to %s' % path)

    def rogue_card_page_record(self, kind):
        """
        Save one card page for offline analysis. **Never changes any decision.**

        用户 2026-11-16：识别目标是「认出是哪张卡、哪种灵光，**包括神闪**」，
        而且样本只能由脚本自己攒（他不手动打）。所以这里只做记录：

        - 整页 PNG
        - 灵光/神闪额外裁三列描述（`_c1..c3.png`），方便直接看那一列到底是什么字
        - JSON 里写**当时识别成了什么**：三列 OCR 文本、认到的卡名、相似度、
          匹配到的列/形态、神闪标签

        ❗记录"当时识别成了什么"是关键：复盘时才能把失败分成两类 ——
        **OCR 读错**（图里字清楚但读成乱码）和**库匹配错**（字读对了但选错列），
        这两类的修法完全不同。

        Args:
            kind (str): 'flash' / 'god' / 'remove' / 'copy'。
        """
        import json as json_module
        import os
        import time

        try:
            image = self.device.image
            ori = image[:, :, ::-1] if image.ndim == 3 else image
            # ❗**先过时间闸**：删卡页/灵光页的卡片会呼吸发光，`[::24,::24]` 的签名
            # 每帧都不一样，光靠签名去重等于没去重 —— 2026-11-16 19:51 实测
            # 一秒存 5 张、十几秒攒了 80 多个文件。
            if not self.card_page_gate.reached():
                return
            self.card_page_gate.reset()
            key = image[::24, ::24].tobytes()
            if key in self.card_pages:
                return
            self.card_pages.add(key)
            if len(self.card_pages) > 400:
                self.card_pages.clear()

            # ❗灵光/神闪面板会先淡入，**最先几帧三列全是空的**。以前照样存，
            # 结果离线复盘里一半样本是 `score=0.0` + OCR 全空 —— 那是"还没画出来"，
            # 不是识别失败，会把识别率统计拉低一半（2026-11-16 实测 flash 20 页里 8 页是空）。
            # 现在**读不到任何字就不存**，等下一帧（面板 1~2 帧内就会出字）。
            if kind in ('flash', 'god'):
                if self.card_reader is None:
                    self.card_reader = rogue_cards.CardReader()
                if self.card_library is None:
                    self.card_library = rogue_cards.CardLibrary()
                # ❗除了"全空"，还要挡掉"闪光动画中"的过曝帧：灵光一闪会先放
                # 1~2 秒的金色闪光，整页被白光淹没，这时 OCR 只吐 3~4 个乱码字
                # （实测 `崁一國中` / `一一二`），`any()` 判定为"有字"照样存下来，
                # 把识别率统计拉低。至少 8 个字才算这页画出来了。
                texts = self.card_reader.read_all(image)
                if sum(len(text or '') for text in texts) < 8:
                    return

            folder = os.path.join(CARD_PAGE_DIR, kind)
            if not os.path.exists(folder):
                os.makedirs(folder)
            stamp = time.strftime('%H%M%S')
            base = os.path.join(folder, stamp)
            cv2.imwrite(base + '.png', ori)

            payload = {'time': time.strftime('%Y-%m-%d %H:%M:%S'), 'kind': kind}

            if kind in ('flash', 'god'):
                # 三列描述单独裁出来：复盘时人眼一看就知道是"字太糊"还是"选错列"
                y1, y2 = CARD_PAGE_DESC
                for index, (x1, x2) in enumerate(CARD_PAGE_COLUMNS, 1):
                    patch = image[y1:y2, x1:x2, :3]
                    if patch.size:
                        cv2.imwrite('%s_c%s.png' % (base, index), patch[:, :, ::-1])
                texts = self.card_reader.read_all(image)
                payload['ocr'] = list(texts)
                card, score, margin = self.card_library.identify(texts)
                payload['card'] = card
                payload['score'] = round(float(score), 4)
                payload['margin'] = round(float(margin), 4)
                if card:
                    picked = self.card_library.pick_column(texts, name=card)
                    if picked:
                        column, ratio, index, raw = picked
                        payload['column'] = column + 1
                        payload['ratio'] = round(float(ratio), 4)
                        payload['form'] = raw[:40]

            if kind == 'god':
                try:
                    payload['god_text'] = self.rogue_god_text()
                except Exception:
                    pass

            with open(base + '.json', 'w', encoding='utf-8') as handle:
                handle.write(json_module.dumps(payload, ensure_ascii=False, indent=1))
            prune_diagnostics(folder, 'card')
            logger.info('Card page [%s] saved: %s (card=%s score=%s)'
                        % (kind, stamp, payload.get('card'), payload.get('score')))
        except Exception as error:
            logger.warning('Failed to record the card page: %s' % error)

    def rogue_run(self, fresh_run=False):
        """
        Drive one run from the first cutscene until the settlement shows up.

        Pages:
            in:  局内任意一页
            out: 局内任意一页（一局没打完就超时）
        """
        logger.hr('Rogue run', level=2)
        timeout = Timer(ROGUE_TIMEOUT, count=1).start()
        press = Timer(1.2, count=2)
        last_change = None
        still = Timer(STAY_LIMIT, count=1)
        # ❗不要按"画面变化"重置 node_tries：地图上有雾气动画，signature 每帧都变，
        # 一重置就永远只试第一个候选点（实测这么点出过 12 次 ROGUE_NODE）。
        self.node_tries = 0
        self.card_tries = 0
        # 刚在复制页选完角色、正等着「請選擇要複製的卡牌」：有效期内不按白色 `跳過`
        # （见 `# 6.1`）。Timer 到期会自动失效，所以那页万一不出现也不会把跳過饿死。
        self.copy_pending = None
        self.unknown_frames = set()
        # 未知页存帧的时间闸（画面在动时签名挡不住，见 `rogue_dump_unknown`）
        self.unknown_save = Timer(3, count=1).start()
        self.chest_grey = None
        self.settlement_title_wait = None
        self.shop_wait = Timer(1, count=1)
        self.shop_retry = 0
        self.shop_cooldown = Timer(1, count=1)
        self.template_cache = {}
        self.fate_tries = 0
        self.fate_index = None
        self.fate_wait = Timer(.8, count=1)
        self.herald_tries = 0
        self.herald_state = None
        self.dice_page = None
        self.dice_tries = 0
        self.dice_wait = Timer(8, count=1)
        self.rest_tries = 0
        self.rest_stage = 0
        self.rest_wait = Timer(REST_WAIT, count=1)
        # 点冥想没开页时的重试计数（见 `# 4.7`）
        self.meditate_retry = 0
        # 刚进安全区域"先等画面稳定"的一次性标志（见 `# 4.7`）。
        # 不用它的话，`rest_stage == 0 and rest_tries == 0` 在整个等待期都成立，
        # 会每帧重置计时器 → 死等（2026-11-17 07:56 实测刷了 200 行）。
        self.rest_settling = False
        # shortcut: 队列只保存在本局进程内；需要中断续跑保留时接入 rogue_state。
        self.meditate_pending = []
        self.meditate_step = -1
        # 复制卡页：认到的目标（一旦认到就锁定，别被后续帧的 OCR 抖动覆盖）
        self.copy_target = None
        self.copy_miss = 0
        self.meditate_stage = 0
        self.meditate_tries = 0
        self.member_stage = 0
        self.member_tries = 0
        self.member_order = []
        self.member_wait = Timer(MEMBER_WAIT, count=2)
        self.copy_stage = 0
        self.copy_tries = 0
        self.copy_order = []
        self.copy_wait = Timer(MEMBER_WAIT, count=2)
        self.remove_stage = 0
        self.remove_target = None
        # 相似页面等待日志的节流键（见 `_pause_for_similar_page`）
        self.pause_logged = None
        # 卡牌页收集器的去重键（同一页会连续命中很多帧）
        self.card_pages = set()
        # 卡牌页存帧的时间闸（卡片会呼吸发光，画面签名挡不住）
        self.card_page_gate = Timer(CARD_PAGE_GATE, count=1).start()
        # 这一页的卡**对不上任何事件**（多半是复制/灵光那种卡牌网格）→ 停住不选
        self.event_unknown = False
        # 卡住 / 死循环检测：定期采画面签名，长期只有 ≤2 种就停任务等人处理
        import collections

        self.stuck_sample = Timer(STUCK_PERIOD, count=1).start()
        self.stuck_recent = collections.deque(maxlen=STUCK_SAMPLES)
        # 航点页已经点了几下（防止在"点不动"的页面上空点到撤退）
        self.beacon_tries = 0
        # 灵光选卡页：0 = 还没选卡，1 = 已选卡、等着点「靈光一閃」
        self.flash_card_stage = 0
        self.flash_card_wait = Timer(1, count=1).start()
        # 卡牌奖励页：0 = 还没选卡，1 = 已选卡、等着按「確認」
        self.card_reward_wait = Timer(1, count=1).start()
        # ❗删卡次数**跨重启**保留：`RogueDelete=3` 是「这一局一共删 3 张」，
        # 不是「这个进程删 3 张」。只存内存时，脚本一重启（`RUN TASK` 重新进来）
        # 计数就归零，日志会反复出现 `(0/3 used)`，同一局能删到 4 张以上
        # （2026-11-16 实测：01:10 删 2 张 → 01:25 重启 → 01:38 又从 0 开始删）。
        # 新开一局时由 `rogue_enter()` 之后显式清零。
        self.remove_done = int(self.rogue_state_load('remove_done', 0) or 0)
        self.remove_counts = dict(self.rogue_state_load('remove_counts', {}) or {})
        self.remove_skip_node = None
        self.remove_tries = 0
        self.remove_cancel_tries = 0
        # 点过卡之后的宽限窗口（见 `REMOVE_WAIT`）
        self.remove_wait = Timer(1, count=1)
        self.prompt_tries = 0
        self.scene_wait = Timer(SCENE_STILL, count=1).start()
        self.last_thumb = None
        self.panel_tries = 0
        self.panel_stall = 0
        self.battle_setting_tries = {}
        self.option_pending = None
        self.event_page = None
        self.event_index = None
        # 反复事件（自环）已经点过几次：picks 是数组时按轮次取不同的 order。
        # 每点成功一次卡 +1（在 `# 6.5`），所以一轮恰好加一次。
        self.event_visit = {}
        self.event_followups = set()
        self.event_last_enc = None
        self.event_choice = None
        self.event_pending_choice = None
        self.event_submit_wait = None
        self.event_submit_clear = Timer(0.8, count=1)
        self.event_submit_attempts = 0
        self.equipment = rogue_equipment.Equipment(self)
        self.route_plan = None
        self.route_nodes = []
        # `route_step` = 整面走了几格（日志的 `step N`，只在进本/进新面时归零）；
        # `plan_index` = 当前计划内已确认进入的节点数（重读计划时归零）。
        # ❗这两个不能混用：混在一起会让"走满 N 步就停"永远达不到（每层都被清零）。
        self.route_step = 0
        self.plan_index = 0
        self.route_mismatch = None
        self.node_pending = None
        self.route_retry = 0
        self.route_reads = 0
        self.route_edges = []
        self.settlement_seen = False
        self.settle_wait = Timer(90, count=1).start()
        # 航点计数：过了几个信标，这一局就攒了几个存档，也是判断进度到哪的唯一锚点。
        self.waypoints = 0
        self.checkpoint_seen = False
        self.stopped_by_beacon = False
        # 本局是因为"卡住 / 死循环"主动收工的（外层据此不再开下一局）
        self.stopped_by_stuck = False
        # 第一面是否已经打完（BOSS 战利品页出现过）：之后就是「核心」第二面。
        # 「本局已进第二面」跨重启保留：只存内存的话，脚本一重启又按第一面走。
        self.core_started = self.rogue_state_load('core_started', False)
        # Only track complete runs started by this invocation.
        self.spark_targets = {}
        if fresh_run and getattr(self.config, 'ChaoszeroRogue_RogueSparkCheck', False):
            card = getattr(self.config, 'ChaoszeroRogue_RogueSparkCheckCard', '')
            if card and any(
                card in rogue_cards.character_spark_cards(
                    getattr(self.config, 'ChaoszeroRogue_RogueSlot%sMember' % slot, ''))
                for slot in (1, 2, 3)
            ):
                rules = self.rogue_spark_filter().get(card)
                if rules:
                    self.spark_targets[card] = rules
        self.spark_obtained = set()
        self.spark_pending = None
        self.spark_boss_pending = False
        self.card_library = None
        self.card_reader = None
        # 事件选择器导出的 picks（懒加载，`None` 表示还没读过）
        self.event_picks = None

        for _ in self.loop(timeout=timeout):
            # 战斗、加载、剧情都是游戏自己在走，把看门狗的清零交给我们自己的
            # 计时器（硬约束 152），否则一分钟没点击就被判成卡死。
            self.device.stuck_record_clear()

            if self.rogue_outside_appear():
                logger.info('Back at the lobby or a Rogue entry page, the run is over')
                return
            if self.appear(TEAM_TITLE, offset=(20, 20), similarity=0.9):
                logger.warning('The team page is missing Rogue markers, stop the run')
                self.stopped_by_stuck = True
                return

            # 卡住 / 死循环：画面长期只有 1~2 种状态就收工，**不撤退、不重开**，
            # 停在原地等人处理（用户 2026-11-16）。外层看到"还在局内"会直接
            # `break` 掉整个任务，所以这里只需要跳出本局循环。
            if self.rogue_stuck_check():
                self.stopped_by_stuck = True
                break

            # Verify the option before a successor handler can consume the current frame.
            if self.event_submit_wait is not None and self.handle_rogue_event(press):
                continue

            if self.node_pending is not None:
                self.rogue_route_confirm_move()

            if self.equipment.handle(press):
                continue

            # 只有"换页"才重置计时器：拿缩略图算均差，薄雾/粒子这类动画的差值很小，
            # 整页切换会差很多。用 bytes 直接比较的话，宝藏房这种一直在飘的画面每帧
            # 都算"变了"，scene_wait 永远到不了 4 秒，场景页一次都不点（2026-11-15
            # 05:22~05:47 就这样干等 25 分钟）。
            thumb = self.device.image[::16, ::16].astype(np.int16)
            signature = thumb.tobytes()
            if self.last_thumb is None:
                change = 255.0
            else:
                change = float(np.abs(thumb - self.last_thumb).mean())
            self.last_thumb = thumb
            if change > PAGE_CHANGE:
                last_change = signature
                still.reset()
                # 换页了就重新计"这页静了几秒"，场景页的点位才敢落下去。
                self.scene_wait.reset()
                self.prompt_tries = 0

            # 0.005 航点结算页（`結算` + 戰利品 + 白色 `暫時返回` + 橙色 `繼續進行`）：
            #       过了这里这局才开始有存档，是脚本唯一能确认「进度到哪」的锚点，
            #       所以只记数，不在这里点（继续走橙色主按钮那一支）。
            #       `RogueStopBeacon` 配了 N 就在第 N 个航点主动撤退（用户 2026-11-15
            #       抱怨「脚本没有识别到了哪关的能力，一路打到通关」）。
            if self.rogue_checkpoint_appear():
                if not self.checkpoint_seen:
                    self.checkpoint_seen = True
                    self.waypoints += 1
                    logger.info('Checkpoint %s reached, this run has a save now' % self.waypoints)
                    # ❗航点是**面内的存档点**（用户 2026-11-15：每个面只有一个，"打到一半
                    # 给你存下档"），不是面末 —— 所以这里**不动路线**。路线只在
                    # `探索結果`（面末 BOSS 后）作废，见下面的处置。
                    if self.rogue_stop_reached():
                        logger.info('Reached %s waypoint(s) as configured, retreat this run'
                                    % self.waypoints)
                        # 撤退链已经跑通（☰ → 撤退 → 结算 → 存档页 → 下一步 → 队伍页），
                        # 走不通就降级继续打，别把一局丢掉。
                        if self.rogue_quit(timeout=300):
                            # ❗记下来：`RogueStopBeacon` 是"打到第 N 个航点就停"，
                            # 只 return 的话 `run()` 会立刻开下一局，停机就白配了。
                            self.stopped_by_beacon = True
                            return
                        logger.warning('Retreat failed, keep playing this run')
            else:
                self.checkpoint_seen = False

            # 0.005 治疗过场（黑色横幅上的白字「批准」）：正常在 `cure_run` 里处理，
            #       但**脚本中途重启**时可能正停在这里，而 `cure_run` 已经不在栈上了 ——
            #       那就会掉进未知页、20 秒后撤退（2026-11-16 03:09 实测）。
            #       这里也认一次，纯白字模板 1.000，其它页远低于阈值。
            if self.config.ChaoszeroRogue_RogueCure and self.appear(
                    ROGUE_CURE_APPROVE, offset=(12, 12), similarity=0.85):
                if press.reached():
                    press.reset()
                    logger.info('Approve the memory wipe (outside cure_run)')
                    self.tap_point(*CURE_APPROVE_POINT, name='ROGUE_CURE_APPROVE')
                continue

            # 0.007 治疗中心里面（`諮商紀錄` 页）：脚本中途重启时可能停在这里。
            #       要么还有人在等治疗（跑一遍 `cure_run`），要么 `等待中… / 無恢復中的
            #       幹員。`（点左上返回箭头退出去）。缺这个分支的话，这一页会掉进未知页，
            #       等 20 秒后被判"nothing to press"撤退（2026-11-16 03:11 实测：
            #       批准之后其实已经治好了，但脚本没认出来，最后 `GameStuckError` 重启）。
            if self.config.ChaoszeroRogue_RogueCure and self.rogue_cure_appear():
                if press.reached():
                    press.reset()
                    if self.rogue_cure_none():
                        logger.info('Nobody is waiting for treatment, leave the center')
                        self.tap_point(*CURE_BACK_POINT, name='ROGUE_CURE_BACK')
                    else:
                        logger.info('Treatment center has a waiting operative, treat it')
                        self.cure_run()
                continue

            # 0.01 崩溃页（`觸發精神異常` / 全崩时的 `夢境模式` 变体）：游戏自己弹，
            #      点绿色 `治療中心` 进去把崩溃角色治掉，治完再回到这里继续。
            if self.config.ChaoszeroRogue_RogueCure and self.rogue_crash_appear():
                if press.reached():
                    press.reset()
                    self.rogue_crash_handle()
                continue

            # 0.02 客户端断线恢复弹窗（`卡厄思連線意外中斷。是否要繼續進行？`）：
            #      断线重开后才有，点 `繼續進行`(815,508) 保住这一局；点 `撤退` 会丢掉进度。
            #      客户端还冻着时这个弹窗点不动（2026-11-15 10:07），所以每 press 点一次就等。
            if self.rogue_resume_appear():
                if press.reached():
                    press.reset()
                    logger.info('Client reconnected, continue the run')
                    self.tap_point(RESUME_CONTINUE_POINT[0], RESUME_CONTINUE_POINT[1],
                                   name='ROGUE_RESUME')
                continue

            # 删卡拥有独立的选择/提交/完成链路；过渡帧不交给通用按钮或其他选卡分支。
            if self.handle_rogue_remove(press):
                continue

            # 0.05 梦境模式说明页（首次进本 / 每周一次）：挡住一切判据，先关掉。
            if self.appear(ROGUE_DREAM_NOTICE, offset=(20, 20), similarity=0.9):
                if press.reached():
                    press.reset()
                    logger.info('Close the dream mode notice')
                    self.device.click(ROGUE_DREAM_OK)  # alas-lint: allow - guarded by the appear() above
                continue

            # 0.055 冥想选卡网格（`請選擇1張再次靈光一閃卡牌。`）：
            #       说明框的橙色確認会被下面的 0.05 通用对话分支按掉，到这里已经是网格。
            #       只在 `RogueSparkFilter` 写到的卡里找目标；认不准就点 `取消` 回休息页，
            #       免得白花 80 点还把休息点用掉（用户：不要认错卡）。
            if self.rogue_meditate_appear():
                if self._pause_for_similar_page('冥想/灵光选择'):
                    continue
                # 这页也存一帧：网格坐标和卡名区是 2026-11-15 的老数据，
                # 布局一变就会"认不出卡"（`No card to reroll`），得靠真帧重切。
                self.rogue_card_page_record('meditate')
                if self.meditate_stage < 1 and press.reached():
                    press.reset()
                    picked = self.rogue_meditate_card()
                    if picked:
                        point, name, score = picked
                        logger.info('Reroll %s on the meditation grid (%.2f)' % (name, score))
                        self.meditate_stage = 1
                        self.tap_point(point[0], point[1], name='ROGUE_MEDITATE_CARD')
                    else:
                        logger.info('No card to reroll on the meditation grid, cancel it')
                        self.meditate_stage = 2
                        # ❗取消后**不要再回到"要不要冥想"的判断**：以前这里
                        # `rest_stage = 0` + `rest_tries = 0`，页面一刷新就又判一次
                        # `rogue_meditate_needed()`，于是同一个休息点连试 3 次、
                        # 3 次机会全废（2026-11-17 04:44 实测：16 秒内 1/3、2/3、3/3
                        # 全部 `No card to reroll`）。推到 2 这个休息点就只按「離開」。
                        self.rest_stage = 2
                        self.rest_tries = 0
                        self.tap_point(MEDITATE_CANCEL_POINT[0], MEDITATE_CANCEL_POINT[1],
                                       name='ROGUE_MEDITATE_CANCEL')
                elif self.meditate_stage == 1 and self.rest_wait.reached():
                    logger.info('Press 再次靈光一閃')
                    self.meditate_stage = 2
                    # 提交不清队列，等重闪确实选到目标形态后再移除对应卡。
                    self.tap_point(MEDITATE_OK_POINT[0], MEDITATE_OK_POINT[1], name='ROGUE_MEDITATE_OK')
                continue
            self.meditate_stage = 0

            # 0.045 `獲得道具` 奖励弹窗（白底 + 道具图标 + 底部 ▼）：点一下画面就关。
            #       删存档（垃圾桶 = 分解）之后会弹这一页，2026-11-15 13:5x 实机确认
            #       它的 `點擊畫面可關閉視窗。` 落在 x 600~875，而老的 `ROGUE_CLICK_CLOSE`
            #       模板框在 505~775，所以删完档会一直卡在弹窗上。
            if self.rogue_item_appear():
                if press.reached():
                    press.reset()
                    logger.info('Close the reward popup, tap the scene')
                    self.tap_point(*CUTSCENE_POINT, name='ROGUE_ITEM')
                continue

            # 0.06 整页说明弹窗（`精神異常` 等，提示「點擊畫面可關閉視窗」）：
            #      它是覆盖层，血量条/主按钮/卡片框全被压暗，判据会全灭 —— 必须在
            #      其它分支之前关掉。2026-11-14 14:41 就在这个弹窗上干等了 13 分钟。
            if self.rogue_modal_appear():
                if press.reached():
                    press.reset()
                    logger.info('Close the popup, tap the scene')
                    self.tap_point(*CUTSCENE_POINT, name='ROGUE_CLOSE')
                continue

            # 0.065 卡牌详情覆盖层（`查看詳情` + 大卡 + 左右箭头 + 橙色 `關閉`）：
            #       局内盲点会翻到这里，它没有血量条也没有主按钮，判据全灭，
            #       2026-11-15 06:55 就因此把整局判成 Unknown page 停掉。
            #       千万不能点右下角的 `靈光一閃`（会开五形态预览，只是多绕一圈）。
            if self.rogue_detail_appear():
                if press.reached():
                    press.reset()
                    logger.info('Close the card detail overlay')
                    self.tap_point(DETAIL_CLOSE_POINT[0], DETAIL_CLOSE_POINT[1],
                                   name='ROGUE_DETAIL')
                continue

            # 0.066 牌堆列表覆盖层（`所有牌堆` + 卡牌數量 + 右上角 ✕）：
            #       同样是盲点翻出来的整页说明，右上角 ✕ 关掉（2026-11-15 07:00 卡住）。
            if self.rogue_deck_appear():
                if press.reached():
                    press.reset()
                    logger.info('Close the deck list')
                    self.tap_point(DECK_CLOSE_POINT[0], DECK_CLOSE_POINT[1],
                                   name='ROGUE_DECK')
                continue

            # 0.07 敌人详情面板（战斗中点到怪身上弹出来的左半屏说明）：
            #      面板是覆盖层，战斗判据（回合蓝 ✓）还在，脚本以为"战斗自己会打完"
            #      就一直等 —— 其实整场被这个面板暂停了（2026-11-15 01:31 实测）。
            #      关法是再点一次战场上的怪，所以按候选位点轮流点，认不出就收手。
            if self.rogue_panel_appear():
                if press.reached() and self.panel_tries < PANEL_TRIES:
                    press.reset()
                    self.panel_tries += 1
                    x, y = PANEL_POINTS[(self.panel_tries - 1) % len(PANEL_POINTS)]
                    logger.info('Enemy info panel is up, close it (%s/%s) at (%s, %s)'
                                % (self.panel_tries, PANEL_TRIES, x, y))
                    self.tap_point(x, y, name='ROGUE_PANEL')
                continue
            self.panel_tries = 0

            # 0.1 已经在看门狗的边上了：先别急着收工。
            #     ❗直接 return 会把一局丢掉（实测 01:37 / 01:41 各丢一次）：大部分
            #     "同一个键连点"其实是转场/淡入那一两秒里判据全灭造成的盲点。
            #     这里的处理是：清掉自己的点击记录，然后**停手**等画面变；画面
            #     一直不变（真的点不动）才收工。
            if self.rogue_click_stuck():
                logger.warning('Too many presses of the same button, hold still for the page to change')
                self.device.click_record_clear()
                recover = Timer(15, count=1).start()
                changed = False
                for _ in self.loop(timeout=recover):
                    self.device.stuck_record_clear()
                    if self.device.image[::16, ::16].tobytes() != signature:
                        changed = True
                        break
                if not changed:
                    logger.warning('The page did not move either, stop here')
                    self.rogue_dump_unknown()
                    self.stopped_by_stuck = True
                    return
                last_change = None
                still.reset()
                self.card_tries = 0
                continue

            # 0.05 二次确认对话框的 `確認`（跳过奖励 / 撤退 / 神闪提示）。
            #      ❗必须排在灵光/战斗/主按钮之前：神闪确认框(`是否選擇該卡牌？`)是
            #      半透明覆盖层，底下的 `靈光一閃：<神名>` 标签还看得见，判据会把
            #      它当成灵光页一直重选同一张卡（2026-11-15 01:00 卡死在这里）。
            point = self.rogue_dialog_point()
            if point:
                if press.reached():
                    press.reset()
                    logger.info('Confirm the dialog at (%s, %s)' % point)
                    self.tap_point(point[0], point[1], name='ROGUE_DIALOG')
                continue

            # 1. 战斗页：先确保自动战斗、倍速已开，再等待游戏出牌。
            #    ❗但敌人详情面板（战斗中点到怪身上）会把整场按暂停，面板盖住左半屏、
            #    回合蓝 ✓ 照旧在，判据分不出来。画面连着 SCENE_STILL 秒一点没动 =
            #    多半被暂停了：点一下战场（y<450，没有手牌）把面板关掉再等。
            #    最多 PANEL_TRIES 次，点过之后一律不再动，避免变成"串击"。
            # A chooser can still cover the battle HUD after a flash selection.
            if self.rogue_battle_appear() and not (
                    self.spark_pending and (self.rogue_flash_appear() or self.rogue_god_appear())):
                self.rogue_spark_confirm()
                if self.handle_rogue_battle_settings(press):
                    continue
                if self.scene_wait.reached() and self.panel_stall < PANEL_TRIES:
                    self.panel_stall += 1
                    self.scene_wait.reset()
                    x, y = PANEL_POINTS[(self.panel_stall - 1) % len(PANEL_POINTS)]
                    logger.info('Battle looks paused, tap the enemy again (%s/%s) at (%s, %s)'
                                % (self.panel_stall, PANEL_TRIES, x, y))
                    self.tap_point(x, y, name='ROGUE_PANEL')
                continue
            self.panel_stall = 0

            # 1.4 带神闪的灵光三选一：底部有 `靈光一閃：<神名>`，标题可能没有。
            #     神闪卡面不固定（用户 2026-11-14），先按品红描述区猜，猜不出就按
            #     RoguePick；不点的话这页永远推不动（20:43 卡了整局）。
            if self.rogue_god_appear():
                self.rogue_card_page_record('god')
                if press.reached():
                    press.reset()
                    self.rogue_choose_flash(god=True)
                continue

            # 1.5 战斗中的灵光一闪三选一：同一张卡的不同闪形态，**必须选一个**。
            #     这页没有跳过，认不出来就会一直按关闭/卡片，战斗永远不结束。
            if self.rogue_flash_appear():
                self.rogue_card_page_record('flash')
                if press.reached():
                    press.reset()
                    self.rogue_choose_flash()
                continue

            # 「卡牌獎勵」页也有橙色「確認」，必须在通用主按钮之前处理。
            if self.rogue_card_reward_appear():
                self.rogue_card_page_record('reward')
                point = self.rogue_secondary_point()
                if point and press.reached():
                    press.reset()
                    self.card_tries = 0
                    logger.info('Card reward page, press 跳過 at (%s, %s)' % point)
                    self.tap_point(*point, name='ROGUE_SECONDARY')
                continue

            # 这一帧是不是「複製卡牌」的选人页：主按钮分支和 4.15 都要用，只算一次。
            copy_page = self.rogue_copy_appear()

            # 2.0 BOSS 战利品页 = 第一面结束的信号（用户 2026-11-15）：
            #     这页之后进「核心」，那是**第二张完整地图**，路线必须重读。
            #     ❗只标记、不改动作：点「獲得」还是交给下面的通用主按钮分支。
            # ❗**必须带步数门槛**：光靠紫色面积会在开局误判 —— 2026-11-16 02:28
            # 实测 `BOSS loot page after 0 step(s)`，刚进本（还在开局剧情/选角）就把
            # `core_started` 置成 True，整张第一面都按「优先事件」走。
            # 一面 16 步、BOSS 在末尾，所以走满 8 步之后遇到的战利品页才算面末。
            # "中途接管"不用担心：`core_started` 已经落盘，重启会读回来。
            if (not self.core_started and self.rogue_loot_appear()
                    and self.route_step >= LOOT_MIN_STEP):
                self.rogue_spark_confirm()
                self.spark_boss_pending = bool(self.spark_targets)
                self.core_started = True
                self.rogue_state_save(core_started=True)
                logger.info('BOSS loot page after %s step(s), the core map comes next, '
                            'the route will be read again' % self.route_step)
                # 第一面的路线作废：进核心后重新读一次
                self.route_plan = None
                self.route_nodes = []
                self.route_step = 0
                self.meditate_step = -1
                self.plan_index = 0
                self.route_reads = 0
                self.route_edges = []
                self.event_page = None
                self.event_index = None
                self.event_visit = {}
                self.event_followups = set()
                self.event_last_enc = None

            # 2. 橙色主按钮：確認 / 繼續進行 / 獲得 / 進入。
            # ❗必须排除「複製卡牌」的选人页：那一页的 `確認` **没选人也是橙的**
            # （2026-11-15 15:00 实机帧 cp_choose.png：bbox 1019,592-1244,658，w225 h66，
            # 正好落进主按钮判据），排在 `# 4.15` 前面就会先把「確認」按掉 ——
            # 人一个没选就确认，这次复制直接白给（用户报的「点了角色就直接跳过」）。
            point = self.rogue_primary_point()
            if point and not copy_page:
                if press.reached():
                    press.reset()
                    self.card_tries = 0   # 按到主按钮说明上一页已经过了
                    self.tap_point(point[0], point[1], name='ROGUE_PRIMARY')
                continue

            # 2.01 探索結果：紫色按钮也用于同一面的阶段结算。
            #      ❗整局结束时的 `存檔資料收集完成` 页也用同一种紫色 `下一步`，
            #      所以先认标题：认出来就先按这里配置的处理存档，再按下一步。
            point = self.rogue_purple_point()
            if point:
                page = self.rogue_settlement_page()
                if page == 'save':
                    if press.reached():
                        press.reset()
                        self.rogue_save_handle(point)
                elif page == 'result' and press.reached():
                    press.reset()
                    # 这个结算页**每走完几格就出现一次**（2026-11-15 18:51 实测：
                    # 每 5~6 格一次），所以它**不是面末信号** —— 不能在这里作废路线。
                    # 同一面的计划跟着队伍当前位置走，结算弹窗不会倒回路线。
                    self.route_retry = 0
                    self.node_tries = 0
                    logger.info('Settlement page, press the purple button')
                    self.settlement_seen = True
                    self.settle_wait.reset()
                    self.tap_point(point[0], point[1], name='ROGUE_PURPLE')
                continue
            self.settlement_title_wait = None

            # 2.0012 **「靈光一閃」单卡详情弹窗**（底部「點擊畫面可關閉視窗。」）：
            #        点画面左侧空白处关掉。
            #        ❗这页以前没有判据，落到未知页 → 40 秒后停任务
            #        （2026-11-17 00:08 实测，整局卡在这）。
            #        判据取底部那行提示 (550,672)-(850,716)：命中帧 1.000、
            #        地图 0.067 / BOSS 战 0.357 / 复制卡页 0.478，阈值 0.85 稳。
            if self.appear(ROGUE_FLASH_DETAIL, offset=(14, 10), similarity=0.85):
                if press.reached():
                    press.reset()
                    self.card_tries = 0
                    logger.info('Flash detail popup, tap the blank area at (%s, %s) to close'
                                % FLASH_DETAIL_CLOSE)
                    self.tap_point(FLASH_DETAIL_CLOSE[0], FLASH_DETAIL_CLOSE[1],
                                   name='ROGUE_FLASH_DETAIL')
                continue

            # 2.0015 **战后「獲得卡牌」页**（双手捧着一张卡 + 底部「跳過」/「✓ 獲得」）：
            #        点右下那颗橙色「✓ 獲得」把卡拿走。
            #        ❗这页以前没有判据，落到未知页 → 40 秒后停任务
            #        （2026-11-16 22:02 实测，整局就卡在这）。
            #        橙色主按钮也救不了：那颗按钮是**圆的+文字**，橙色块宽只有 75px，
            #        而 `PRIMARY_WIDTH` 要求 180~280，判据永远检不到。
            if self.appear(ROGUE_ACQUIRE, offset=(16, 12), similarity=0.85):
                if press.reached():
                    press.reset()
                    self.card_tries = 0
                    logger.info('Card acquire page, press 獲得 at (%s, %s)' % ACQUIRE_POINT)
                    self.tap_point(ACQUIRE_POINT[0], ACQUIRE_POINT[1], name='ROGUE_ACQUIRE')
                continue

            # 2.002 **「請選擇1張欲觸發靈光一閃的卡牌。」页**：先点第一张卡，
            #        再点底部橙色「靈光一閃」。以前没有判据，靠"未知页盲点 +
            #        橙色主按钮"碰巧按中（2026-11-16 02:40 实测）。
            if self.rogue_flash_card_appear():
                if self.flash_card_stage == 0:
                    # ❗坐标**动态检测**：这页有 4 张大卡 / 6 张小卡两种布局，
                    # 固定的 (320,400) 在 6 卡布局里落在卡下方空白处，
                    # 点五轮都选不中（2026-11-16 18:30 实测）。
                    points = self.rogue_flash_card_points()
                    if not points:
                        if press.reached():
                            press.reset()
                            logger.info('Flash-card picker, no card detected yet, wait')
                        continue
                    # ❗两版选卡页的"选哪张"不一样：
                    #   神之靈光一閃（要賦予）→ 按 `GOD_CARD_NAME` 找，找不到点第一张
                    #   欲觸發靈光一閃        → 按 `RoguePick` 号位
                    if self.rogue_god_card_appear():
                        target = self.rogue_god_card_pick()
                        if target is None:
                            target = points[0]
                        label = 'god-card'
                    else:
                        index = min(self.rogue_pick_index(), len(points))
                        target = points[index - 1]
                        label = 'flash-card'
                    if press.reached():
                        press.reset()
                        self.card_tries = 0
                        logger.info('%s picker, pick (%s, %s)', label, target[0], target[1])
                        self.tap_point(target[0], target[1], name='ROGUE_CARD')
                        self.flash_card_stage = 1
                        self.flash_card_wait = Timer(1, count=1).start()
                    continue
                if self.flash_card_stage == 1:
                    if self.flash_card_wait.reached() and press.reached():
                        press.reset()
                        # 底部按钮两页不同名字（「靈光一閃」/「選擇」），但都是橙色，
                        # 所以优先用通用主按钮检测，检不到才用固定坐标兜底。
                        point = self.rogue_primary_point() or FLASH_CONFIRM_POINT
                        logger.info('Press the orange button at (%s, %s)' % point)
                        self.tap_point(point[0], point[1], name='ROGUE_PRIMARY')
                        # ❗**不能立刻回 stage 0**：点完「靈光一閃」页面要 1~2 秒
                        # 才切走，这段过渡期判据仍然命中 —— 一回 0 就又去点卡，
                        # 而卡早就选好了，于是「点卡→点确认→点卡→点确认」无限兜圈
                        # （2026-11-16 18:29 实测刷了 5 轮，还触发连点保护）。
                        # 进 stage 2 只等不点，页面消失后由下面的 `= 0` 归位。
                        self.flash_card_stage = 2
                        self.flash_card_wait = Timer(FLASH_SUBMIT_WAIT, count=1).start()
                    continue
                # stage 2：已提交，等页面自己切走，一个字都不点
                continue
            self.flash_card_stage = 0

            # 2.005 **「請選擇欲複製的卡牌」页**：点卡就完成复制。
            #        ❗必须排在 `rogue_meditate_appear()`（4.7）之前：那一页会被冥想判据
            #        误吃，然后去点左下角图标区 (134,616)，连点十几次都不动
            #        （2026-11-16 02:24 实测，还触发了连点保护）。
            #        这页底部**没有「複製」按钮**，只有白色「跳過」胶囊。
            if self.rogue_copy_card_appear():
                self.rogue_card_page_record('copy')
                # ❗**点卡就是复制**（用户 2026-11-16：「不要点跳过，点那张卡就行了」）。
                # 这一页底部没有「複製」按钮，只有「跳過」，点一下卡就完成复制。
                # 先识别配置的目标卡。切页动画可能让卡名暂时读不出来：
                # 卡面文字在切页那几帧里 OCR 抖动极大（同一张剑之雨实测
                # 0.93 → 0.52 → 0.52 → 0.50 → 0.49），用某一帧判"没有"会白丢一次复制。
                # 所以：一旦认到就**锁定**（`copy_target`），不再被后续帧覆盖；
                # 没认到就每个 `press` 周期重试一次，试满 `COPY_CARD_MISS` 次才选第一张。
                if press.reached():
                    press.reset()
                    self.card_tries = 0
                    if self.copy_target is None:
                        self.copy_target = self.rogue_copy_card_pick()
                    if self.copy_target:
                        x, y, name, score = self.copy_target
                        logger.info('Copy-card page, pick %s at (%s, %s) score %.2f'
                                    % (name, x, y, score))
                        self.tap_point(x, y, name='ROGUE_COPY_CARD')
                        self.copy_target = None
                        self.copy_miss = 0
                    else:
                        self.copy_miss += 1
                        if self.copy_miss < COPY_CARD_MISS:
                            logger.info('Copy-card page, %s not found yet (%s/%s), retry'
                                        % (self.config.ChaoszeroRogue_RogueCopyCard, self.copy_miss, COPY_CARD_MISS))
                            continue
                        # ❗用户 2026-11-17 选 B：「认不出就点第一张，赌一把」。
                        # 跳過会把这次复制机会**永久丢掉**，而认不出的原因多半是
                        # OCR 抖动（同一张剑之雨实测 0.93/0.52/0.50/0.49），
                        # 赌一张比直接放弃划算。点之前把候选打印出来备查。
                        points = self.rogue_copy_card_points()
                        if points:
                            x, y = points[0][0], points[0][1]
                            logger.info('Copy-card page, %s still not found after %s tries,'
                                        ' fall back to the first card at (%s, %s)'
                                        % (self.config.ChaoszeroRogue_RogueCopyCard, self.copy_miss, x, y))
                            self.tap_point(x, y, name='ROGUE_COPY_CARD')
                        else:
                            logger.info('Copy-card page, no card detected at all, wait')
                        self.copy_miss = 0
                continue
            self.copy_target = None
            self.copy_miss = 0

            # 2.015 **卡牌轉換页**「請選擇 N 張欲轉換的卡牌」：**整页跳过**，一张都不选。
            #       ❗必须排在**所有**"会误命中这页"的判断之前（实测塔罗命运页的判据
            #       在这一页上就命中过，日志报的却是 `命运三选一（塔罗）`，
            #       于是被那个暂停分支拦住、根本不跳）。
            #       判据绑在这一页自己身上（用户 2026-11-16：「只判定这个页面的时候才跳过，
            #       不要把跳过做成通用状态机」）。`ROGUE_TRANSFORM` 与 `ROGUE_REMOVE`
            #       在阈值 0.93 下互斥（1.000/0.896 和 0.895/0.999）。
            #       为什么要跳过：转卡会把普通卡换成另一张（「捨棄世俗」→ 致命射擊）。
            if self.rogue_transform_appear():
                point = self.rogue_secondary_point()
                if point and press.reached():
                    press.reset()
                    self.card_tries = 0
                    logger.info('Card TRANSFORM page, skip it at (%s, %s)' % point)
                    self.tap_point(point[0], point[1], name='ROGUE_SECONDARY')
                continue

            # 2.02 塔罗命运页：先点一张卡，再点确认。
            #      必须排在 `跳過` 之前：那页右下有颗白色 ▶ 圆钮，正好落在跳过判据
            #      的盒子里，实测被判成"跳過"然后连点 8 次空坐标。
            if self.handle_rogue_fate(press):
                continue

            # 2.1 只有 `跳過` / `下一步` 的页面（卡牌转换、卡牌复制、灵光目标战斗员）：
            #     现在还认不出卡牌，跳过是最安全的动作 —— 不改变卡组，只是不要这一页的收益。
            # ❗原来这里还有一段"事件页：按粉色 ✕ 判据挨个点 (320,592)/(640,592)/(1000,592)"，
            #    已删除：那个粉色判据在 Boss 后的 `探索結果` 页、结算页上也会命中，脚本会
            #    对着空白处按一分钟（2026-11-14 22:07 实测按了 30 多次 (320,592)）。
            #    真正的事件选项卡由下面的 `rogue_option_points()`（浅色横线检测）负责。

            # 4. 剧情 ▼。**必须排在「传令兵」之前**：两个页面用的是同一张神殿立绘
            #    （实测 tarot 页 ROGUE_HERALD 也 0.999），但剧情帧有 ▼（ROGUE_STORY
            #    在剧情帧 0.955~1.000、在传令兵选择页只有 0.259），靠 ▼ 就能分开。
            if self.rogue_story_appear():
                if press.reached():
                    press.reset()
                    self.card_tries = 0
                    self.device.click(ROGUE_STORY)  # alas-lint: allow - guarded by rogue_story_appear() in this branch
                continue

            # 4.02 **剧情页**（右下那颗空心白 ▼）：点 ▼ 推一句台词。
            #      ❗这是**有判据**的（`ROGUE_STORY` 模板），不是盲点。
            #      以前剧情是靠 `# 6.8` 的未知页盲点（点画面中部）过的，
            #      盲点删掉之后必须显式处理，否则剧情会停在这里等到收工。
            if self.rogue_story_appear():
                if press.reached():
                    press.reset()
                    self.card_tries = 0
                    logger.info('Advance the story at (%s, %s)' % STORY_POINT)
                    self.tap_point(STORY_POINT[0], STORY_POINT[1], name='ROGUE_STORY')
                continue

            # 4.2 开局「传令兵」三选一：默认最左（3 场战斗怪物 HP=1），配置可改位置。
            #     三张卡的内容每局随机，位置由 `RogueHerald` 决定，不是三选一的 `RoguePick`；
            #     提交键是选中那张卡下面的亮 ∨（= 用户给的 命运确认N）。
            #     ❗这页的卡框量不出来（OPTION 判据实测返回空），所以用固定三点；
            #     页面判据是神殿立绘 + 没有 ▼。tries 兜底，避免一直点同一处触发看门狗。
            # ❗**不暂停**：用户 2026-11-16 定「依旧点第一个」。
            # 这一页和 BOSS 版的「凱爾肯的傳令兵」共用同一个场景判据（实测 0.999），
            # 两者都是三选一、都点最左，所以不需要区分。
            if self.rogue_herald_appear():
                if press.reached():
                    press.reset()
                    index = self.rogue_herald_index()
                    selected = self.rogue_herald_selected()
                    # 选中状态一变就把尝试次数清零：选中动画有延迟，第一下点完可能还
                    # 读成"未选中"而重复点同一张卡，硬性次数会把提交那一下饿掉。
                    if selected != self.herald_state:
                        self.herald_state = selected
                        self.herald_tries = 0
                    if self.herald_tries < HERALD_TRIES:
                        if selected == index:
                            logger.info('Confirm the herald blessing %s' % index)
                            x, y = HERALD_CHECK[index - 1]
                            self.tap_point(x, y, name='ROGUE_HERALD')
                        else:
                            logger.info('Pick the herald blessing %s' % index)
                            x, y = HERALD_POINTS[index - 1]
                            self.tap_point(x, y, name='ROGUE_HERALD')
                        self.herald_tries += 1
                continue

            # 4.5 地图 2D 全图：**只能预览，不能移动**（用户 2026-11-14 确认）。
            #     左下角按钮这时是 ⊕，点它回 3D 视角；不回去就会一直卡在预览里
            #     （实测 01:06~01:14 卡了 8 分钟，一次都没动）。
            if self.rogue_map_preview_appear():
                if press.reached():
                    press.reset()
                    self.node_tries = 0
                    logger.info('Back from the 2D preview to the 3D map')
                    self.tap_point(ZOOM_POINT[0], ZOOM_POINT[1], name='ROGUE_ZOOM')
                continue

            # 4.1 人物灵光（第一面的事件）：三张大立绘，选一个角色 → 他随机一张没闪
            #     的卡灵光；暗掉的角色会换成钱。点立绘 → 右下 `確認`，两下才提交。
            #     ❗只在判据不再命中（离开这一页）时清零，不看画面签名：立绘选中后
            #       会亮起来，签名每帧都变，stage 被打回 0 就会重复点立绘。
            member = self.rogue_member_appear()
            if not member:
                self.member_stage = 0
                self.member_tries = 0
                self.member_order = []
            if member:
                if self._pause_for_similar_page('人物灵光选人'):
                    continue
                if press.reached():
                    press.reset()
                    if self.member_stage == 0:
                        if self.rogue_member_selected():
                            # 进来时已经有一张选好了（截图/上个进程留下的），先确认。
                            self.member_stage = 2
                            logger.info('A combatant is already picked, confirm it')
                            self.tap_point(MEMBER_OK_POINT[0], MEMBER_OK_POINT[1],
                                           name='ROGUE_MEMBER_OK')
                            continue
                        first = self.rogue_member_index()
                        self.member_order = [first] + [i for i in (1, 2, 3) if i != first]
                        self.member_stage = 1
                        logger.info('Pick combatant %s for the flash' % first)
                        point = MEMBER_POINTS[first - 1]
                        self.tap_point(point[0], point[1], name='ROGUE_MEMBER_PICK')
                        self.member_wait = Timer(MEMBER_WAIT, count=2)
                    elif self.member_stage == 1:
                        # 暗掉的立绘点不动（只弹灰齿轮），所以点完等 3 秒看 確認
                        # 有没有变橙；没变就换下一张，三张都不行就照样点 確認。
                        if self.rogue_member_selected():
                            self.member_stage = 2
                            logger.info('Confirm the combatant')
                            self.tap_point(MEMBER_OK_POINT[0], MEMBER_OK_POINT[1],
                                           name='ROGUE_MEMBER_OK')
                        elif self.member_wait.reached():
                            self.member_tries += 1
                            self.member_wait = Timer(MEMBER_WAIT, count=2)
                            if self.member_tries < len(self.member_order):
                                index = self.member_order[self.member_tries]
                                logger.info('The portrait did not take it, try %s (%s/%s)'
                                            % (index, self.member_tries,
                                               len(self.member_order)))
                                point = MEMBER_POINTS[index - 1]
                                self.tap_point(point[0], point[1], name='ROGUE_MEMBER_PICK')
                            else:
                                self.member_stage = 2
                                logger.warning('No portrait could be picked, press 確認 anyway')
                                self.tap_point(MEMBER_OK_POINT[0], MEMBER_OK_POINT[1],
                                               name='ROGUE_MEMBER_OK')
                continue

            # 4.15 复制卡牌的选人页（每面结束的随机复制）：先选一个战斗员，之后出他
            #      这个角色的 3 张随机可复制卡。立绘 / `確認` 和人物灵光页同一套几何，
            #      暗掉的角色同样点不动。2026-11-15 01:48 这里没有判据，整段卡了 6 分钟。
            #      清零规则同 4.1：只看判据是否还在，不看画面签名。
            copy = copy_page
            if not copy:
                self.copy_stage = 0
                self.copy_tries = 0
                self.copy_order = []
            if copy:
                if self._pause_for_similar_page('复制卡牌选人'):
                    continue
                if press.reached():
                    press.reset()
                    if self.copy_stage == 0:
                        if self.rogue_member_selected():
                            self.copy_stage = 2
                            logger.info('A combatant is already picked for the copy, confirm it')
                            self.copy_pending = Timer(COPY_PENDING, count=1).start()
                            self.tap_point(MEMBER_OK_POINT[0], MEMBER_OK_POINT[1],
                                           name='ROGUE_COPY_OK')
                            continue
                        first = self.rogue_member_index(self.config.ChaoszeroRogue_RogueCopyMember or None)
                        self.copy_order = [first] + [i for i in (1, 2, 3) if i != first]
                        self.copy_stage = 1
                        logger.info('Pick combatant %s to copy cards from' % first)
                        point = MEMBER_POINTS[first - 1]
                        self.tap_point(point[0], point[1], name='ROGUE_COPY_PICK')
                        self.copy_wait = Timer(MEMBER_WAIT, count=2)
                    elif self.copy_stage == 1:
                        if self.rogue_member_selected():
                            self.copy_stage = 2
                            logger.info('Confirm the combatant to copy from')
                            self.copy_pending = Timer(COPY_PENDING, count=1).start()
                            self.tap_point(MEMBER_OK_POINT[0], MEMBER_OK_POINT[1],
                                           name='ROGUE_COPY_OK')
                        elif self.copy_wait.reached():
                            self.copy_tries += 1
                            self.copy_wait = Timer(MEMBER_WAIT, count=2)
                            if self.copy_tries < len(self.copy_order):
                                index = self.copy_order[self.copy_tries]
                                logger.info('The portrait did not take it, try %s (%s/%s)'
                                            % (index, self.copy_tries,
                                               len(self.copy_order)))
                                point = MEMBER_POINTS[index - 1]
                                self.tap_point(point[0], point[1], name='ROGUE_COPY_PICK')
                            else:
                                self.copy_stage = 2
                                logger.warning('No portrait could be picked, press 確認 anyway')
                                self.copy_pending = Timer(COPY_PENDING, count=1).start()
                                self.tap_point(MEMBER_OK_POINT[0], MEMBER_OK_POINT[1],
                                               name='ROGUE_COPY_OK')
                continue

            # 4.6 德朗商店：先检查指定装备，再按配额使用右上删卡服务。
            #     （按 劍幕 > 劍光 认卡、再按检测出的橙色 `移除`）。删完回到这一页会再点一次，
            #     `RogueDelete` 的配额用完以后就交给 primary 点右下橙色 `離開` 出店。
            shop = self.rogue_shop_appear()
            if shop or self.rogue_shop_sold_appear():
                if self.equipment.handle_shop(press):
                    continue
            if shop:
                # 真的进店了：重试计数归零，并开始 120 秒冷却（一个营地只删一次，
                # 删完这张卡会变成「售罄」，`# 4.61` 会把我们送出去）。
                self.shop_retry = 0
                self.shop_cooldown = Timer(SHOP_COOLDOWN, count=1).start()
                # ❗删卡配额用完就**别再点「移除卡牌」**，直接点「離開」出店。
                # 否则会死循环：点进入删卡页 → 那边发现配额满了点「取消」
                # → 回到商店又点进删卡页 ……（2026-11-16 01:58 实测转了 3 圈）。
                if not self.rogue_shop_remove_needed():
                    if press.reached():
                        press.reset()
                        logger.info('Skip shop removal for this node (%s confirmed removals)'
                                    % self.remove_done)
                        self.tap_point(SHOP_LEAVE[0], SHOP_LEAVE[1],
                                       name='ROGUE_SHOP_LEAVE')
                    continue
                if press.reached():
                    press.reset()
                    logger.info('Enter 移除卡牌 in the 德朗商店')
                    self.tap_point(SHOP_REMOVE[0], SHOP_REMOVE[1], name='ROGUE_SHOP_REMOVE')
                continue

            # 4.7 安全区域（休息点）：休息 / 冥想 / 训练 三选一，选一个另两个就锁死。
            #     用户 2026-11-15：休息免费；训练是拿中立卡，默认不点；冥想只在
            #     「已经闪了但类型不对」时才用（类型判定还没做，所以目前固定休息）；
            #     **绝不要落到 `跳過` 分支**，那等于把这个休息点浪费掉。
            #     ❗不能用画面签名判断"页面变了就重来"：篝火在烧，签名每帧都变，
            #       stage 永远被打回 0，脚本就一直点休息、从不走到确认框
            #       （2026-11-15 01:18 实测同一处点了 4 次、确认框一次都没点）。
            #       只在**离开这一页**（判据不再命中）时清零。
            # 4.61 商店的删卡已经用掉（右上变「售罄」）：点右下那颗玫红 `離開` 出店。
            #      ❗它既不是橙色主按钮（`primary`）也不是紫胶囊（`purple` 要 b>195，
            #      这颗是 r≈200/g≈50/b≈110），两个判据都认不出，所以只能给固定点 ——
            #      但**前提是售罄判据命中**，不是盲点。
            if self.rogue_shop_sold_appear():
                if press.reached():
                    press.reset()
                    logger.info('The shop card removal is sold out, leave the shop')
                    # ❗售罄页**不是**商店页（`rogue_shop_appear()` 为 False），所以永远走不到
                    # `# 4.6` —— 而 `shop_cooldown` 只在 `# 4.6` 里启动。不在这里补一刀，
                    # 冷却就一直 `reached()`，回营地又被 `# 4.75` 送进来：
                    #   Visit 德朗商店 → sold out → leave → Visit 德朗商店 → …… 死循环
                    # （2026-11-16 02:53 实测转了 6 圈，还触发连点保护）。
                    # 同时把 `shop_retry` 用满：这个营地的删卡名额已经没了，别再试。
                    self.shop_cooldown = Timer(SHOP_COOLDOWN, count=1).start()
                    self.shop_retry = SHOP_RETRY
                    self.tap_point(SHOP_LEAVE[0], SHOP_LEAVE[1], name='ROGUE_SHOP_LEAVE')
                continue

            rest = self.rogue_rest_appear()
            # 离开营地/商店：下一个营地重新给 3 次点店机会（售罄页 rest/shop 都是
            # False，会在这里清零 —— 但那边有 `SHOP_COOLDOWN` 120 秒兜着，不会回营地重进）。
            if not rest and not shop:
                self.shop_retry = 0

            # 第 2 步：休息/冥想点了之后会弹「HP恢復20% / …」的确认框，橙色確認在
            # (845,512)，比通用对话区（y 到 510）低一点，所以这里单独认、单独点。
            # ❗这一步**不能**放在 `if rest:` 里面：确认框一出来整页会被压暗，`訓練`
            #   磁贴的判据随之失效（2026-11-15 11:21 实测：点了休息、确认框弹出，
            #   判据转 False → stage 被打回 0 → 确认框一次都没点，60 秒后
            #   `GameStuckError` 把客户端重启）。所以确认框只看自己的橙色按钮。
            if self.rest_stage == 1:
                point = self.rogue_confirm_point(REST_CONFIRM_AREA)
                if point:
                    logger.info('Confirm the safe area option')
                    self.rest_stage = 2
                    self.tap_point(point[0], point[1], name='ROGUE_REST_OK')
                elif self.rest_wait.reached():
                    logger.info('The safe area confirm box did not show up')
                    self.rest_stage = 2
                continue

            # 先等入场/进店过场，避免三次进店重试都在按钮未生效时耗尽。
            if not self.shop_wait.reached():
                continue
            if rest and self.rest_stage == 0 and not self.rogue_rest_settled():
                continue

            # 4.75 识别到「德朗商店」入口才进店，点空后也要重新识别。
            if rest and self.rogue_visit_rest_shop(press):
                continue

            if rest:
                self.rogue_spark_confirm()
                # ❗只停这里（自动选休息/回血/冥想/看商店）。上面的"休息确认框"
                # 分支不能停 —— 那个一停就卡死在压暗的页面上。
                if self._pause_for_similar_page('营地/休息（回血 · 冥想 · 商店）'):
                    continue
                if self.rest_tries < REST_TRIES and self.rest_wait.reached():
                    if press.reached():
                        press.reset()
                        # ❗`rest_stage == 3` = 上一次点了冥想但冥想页没开：
                        # 先重试同一颗按钮，别急着降级去休息。
                        # （2026-11-17 用户定位：进休息点时画面还没稳定，冥想点空，
                        #   而且**没有重试**就直接点了休息，等于白白放弃一次重掷。）
                        if self.rest_stage == 3:
                            if self.meditate_retry < MEDITATE_RETRY:
                                self.meditate_retry += 1
                                logger.info('Meditation did not open, retry %s/%s at (%s, %s)'
                                            % (self.meditate_retry, MEDITATE_RETRY,
                                               MEDITATE_POINT[0], MEDITATE_POINT[1]))
                                self.tap_point(MEDITATE_POINT[0], MEDITATE_POINT[1],
                                               name='ROGUE_REST')
                                self.rest_wait = Timer(REST_WAIT, count=1).reset()
                            else:
                                logger.info('Meditation did not open after %s retries, '
                                            'fall back to rest' % MEDITATE_RETRY)
                                self.rest_stage = 1
                                self.meditate_retry = 0
                                self.tap_point(REST_POINTS[0][0], REST_POINTS[0][1],
                                               name='ROGUE_REST')
                                self.rest_wait = Timer(REST_WAIT, count=1).reset()
                            continue
                        self.rest_tries += 1
                        if self.rogue_meditate_needed() and self.rogue_meditate_available():
                            # 冥想这条路自己会把说明框和选卡页走完（见 `# 0.055`）。
                            self.meditate_tries += 1
                            # 失败仍保留目标；同一节点只发起一轮，下一营地再试。
                            self.meditate_step = self.route_step
                            # ❗用 3 而不是 2：2 表示"已用掉、去按離開"，
                            # 而 3 表示"等冥想页，没开就重试"。
                            self.rest_stage = 3
                            self.meditate_retry = 0
                            target = self._next_meditate_target()
                            logger.info('Meditate to reroll %s (attempt %s) at (%s, %s)'
                                        % (target, self.meditate_tries,
                                           MEDITATE_POINT[0], MEDITATE_POINT[1]))
                            point = MEDITATE_POINT
                        else:
                            self.rest_stage = 1
                            logger.info('Rest at the safe area (%s/%s)'
                                        % (self.rest_tries, REST_TRIES))
                            point = REST_POINTS[0]
                        self.tap_point(point[0], point[1], name='ROGUE_REST')
                        # ❗必须 .reset()：新建的 Timer 还没开始计时，`reached()` 第一次就
                        #   返回 True，确认框那一步会立刻判定「没弹出来」把 stage 推到 2
                        #   （2026-11-15 12:01 实测：点完休息 0.2 秒就放弃，确认框一直挂着）。
                        self.rest_wait = Timer(REST_WAIT, count=1).reset()
                # 只有 **stage 2**（休息/冥想已经用掉）才往下交给橙色主按钮按「離開」。
                # 其余状态都要停在这一页：
                #   0 = 还没动、1 = 点了休息等确认框、3 = 点了冥想等冥想页。
                if self.rest_stage != 2:
                    continue
            else:
                # 判据不再命中时，如果橙色确认框还挂着（比如进程重启后 stage 丢了），
                # 先把框按掉，别把整页干等成 GameStuckError。
                point = self.rogue_confirm_point(REST_CONFIRM_AREA)
                if point and self.rest_stage == 0:
                    logger.info('The safe area confirm box is still open, press it')
                    self.rest_stage = 2
                    self.tap_point(point[0], point[1], name='ROGUE_REST_OK')
                    continue
                # 只在**离开这一页**（判据不再命中、而且没有待确认的框）时清零
                self.rest_tries = 0
                self.rest_stage = 0
                self.meditate_retry = 0
                self.rest_settling = False

            # 4.8 地图节点提示卡（`進入傳送門內部 / 觸發【…】事件`）。
            #     这张卡会**吃掉卡外的点击**（2026-11-14 15:31 在卡外点了一百次、
            #     空等 8 分钟）。它其实是两步：先点卡身 (640,600) 展开，卡片下沿
            #     才会出现 ∨ (640,680)，再点 ∨ 才进节点（2026-11-15 06:05 手动实证）。
            #     所以两个点位交替点，最多 PROMPT_TRIES 次，之后交给场景/兜底分支。
            if self.rogue_prompt_appear() and self.prompt_tries < PROMPT_TRIES:
                if press.reached():
                    press.reset()
                    self.node_tries = 0
                    x, y = PROMPT_POINTS[self.prompt_tries % len(PROMPT_POINTS)]
                    self.prompt_tries += 1
                    logger.info('Press the node prompt card (%s/%s) at (%s, %s)'
                                % (self.prompt_tries, PROMPT_TRIES, x, y))
                    self.tap_point(x, y, name='ROGUE_PROMPT')
                continue

            # 5. 地图：核对 2D 计划分支与 3D 立卡后，点对应平台。
            if self.rogue_map_appear():
                self.rogue_spark_confirm()
                if self.rogue_spark_restart_on_core_map():
                    return
                if self.node_pending is not None and not self.node_pending.reached():
                    continue
                if press.reached():
                    press.reset()
                    self.card_tries = 0
                    self.node_tries += 1
                    if self.node_tries > MAP_TRIES:
                        if self.route_retry < 2:
                            self.route_retry += 1
                            self.node_tries = 0
                            self.route_plan = None
                            logger.warning('The map is not taking the node press, re-read the route (%s/2)'
                                           % self.route_retry)
                            continue
                        logger.warning('The map is not taking the node press after %s tries, stop'
                                       % MAP_TRIES)
                        self.rogue_dump_unknown()
                        self.stopped_by_stuck = True
                        return
                    # 只在本面缺少可用计划时读图，不按步数反复打开预览。
                    if not self.route_plan:
                        if self.route_reads >= ROUTE_READS:
                            # 本面的读图机会已用完，按当前可走节点的分数选择。
                            pass
                        elif self.route_retry < ROUTE_RETRY:
                            self.route_retry += 1
                            logger.info('Read the 2D route (%s/%s reads, try %s)'
                                        % (self.route_reads + 1, ROUTE_READS, self.route_retry))
                            if self.rogue_route_plan():
                                self.route_reads += 1
                                self.route_retry = 0
                            continue
                        else:
                            logger.warning('No route plan after %s tries, walk by card type only'
                                           % ROUTE_RETRY)
                    cards = rogue_route.read_cards(self.device.image)
                    if not cards:
                        self.route_mismatch = None
                        if self.rogue_route_entry():
                            logger.info('Planned branches are not visible yet, wait for the platforms')
                        elif self.node_tries >= 3:
                            # 层末只剩 Boss 平台：那张狼纹徽记的大卡跟平台的粉边连成
                            # 一片（实测 516x368 一整块），读卡永远读不出来，而这时候
                            # 已经没有别的格子可选，直接点平台本体
                            # （2026-11-14 21:53 在这空等到放弃，整轮结束）。
                            logger.info('Only the boss platform is left, press it')
                            self.node_pending = Timer(NODE_ENTRY_WAIT, count=1).start()
                            self.tap_point(NODE_FALLBACK[0], NODE_FALLBACK[1], name='ROGUE_NODE')
                        else:
                            logger.info('No node card on the map yet, wait for the platform')
                        continue
                    entry = self.rogue_route_entry()
                    card = rogue_route.planned_card(cards, entry) if entry else None
                    if entry and card is None:
                        kinds = tuple(item.kind for item in sorted(cards, key=lambda item: item.y))
                        if self.route_mismatch != kinds:
                            self.route_mismatch = kinds
                            continue
                        logger.warning('Route choices differ: plan %s, live %s; discard this plan'
                                       % (entry['choices'], kinds))
                        self.route_plan = None
                        if self.route_reads < ROUTE_READS:
                            continue
                    self.route_mismatch = None
                    if card is None:
                        card = rogue_route.best_card(cards, self.rogue_route_style(),
                                                     self.rogue_route_state())
                    x, y = card.platform_point()
                    # ❗把**每张卡的坐标和类型**都打出来：之前只打"走了什么"，
                    # 出现"游戏里实际是精英、日志却说战斗"时无从排查
                    # （2026-11-16 用户报「实际走了精英」，日志里全是 戰鬥）。
                    logger.info('Walk to %s (step %s), %s card(s) reachable: %s'
                                % (rogue_route.KIND_NAMES.get(card.kind, card.kind),
                                   self.route_step + 1, len(cards),
                                   [(rogue_route.KIND_NAMES.get(item.kind, item.kind),
                                     item.x, item.y,
                                     rogue_route.card_hue(self.device.image, item))
                                    for item in cards]))
                    self.node_pending = Timer(NODE_ENTRY_WAIT, count=1).start()
                    self.tap_point(x, y, name='ROGUE_NODE')
                continue

            # 走到这里说明已经不在地图上了，节点尝试次数清零（下一格重新给 10 次）。
            if self.node_pending is None:
                self.node_tries = 0
                self.route_retry = 0

            # 5.9 航点（信标）场景：中间一座青色石柱 + 底部「啟用航點 / 獲得裝備[...]」提示卡。
            #     ❗必须排在事件选项卡之前：`rogue_option_points()` 会把这个提示卡
            #     误认成卡框（实测返回 `[(640, 677)]`），然后去点 (640,590) 的空白处。
            beacon_stage = self.rogue_beacon_stage()
            if beacon_stage:
                # 防死循环：同一页连点 BEACON_TRIES 次还不生效就停手等人看。
                if self.beacon_tries >= BEACON_TRIES:
                    if press.reached():
                        press.reset()
                        logger.warning('Waypoint page does not respond after %s taps, stop'
                                       % self.beacon_tries)
                    continue
                if press.reached():
                    press.reset()
                    self.beacon_tries += 1
                    self.card_tries = 0
                    # ① 未展开 → 点卡片本体展开；② 已展开 → 点底部那颗 ∨ 提交。
                    point = (BEACON_CARD_POINT if beacon_stage == 1
                             else BEACON_CONFIRM_POINT)
                    logger.info('Waypoint stage %s, press (%s, %s), try %s/%s'
                                % (beacon_stage, point[0], point[1],
                                   self.beacon_tries, BEACON_TRIES))
                    self.tap_point(point[0], point[1], name='ROGUE_BEACON')
                continue
            if self.rogue_beacon_transition():
                # 航点页的过渡帧（刚点完卡片、装备图标弹窗盖着）：**什么都别做**，
                # 等它自己收起成"已展开"。不 `continue` 到后面的分支，否则
                # `rogue_option_points()` 会把这张卡当成事件选项卡去点。
                if press.reached():
                    press.reset()
                    logger.info('Waypoint page in transition (loot icon), wait')
                continue
            self.beacon_tries = 0

            # 6. 掷骰页：**整页只点一下骰子**（用户 2026-11-15：点一下骰子就行）。
            #    掷完出 `成功`/`失敗` 和 `重新擲骰`/`下一步` 两颗按钮；`重新擲骰`
            #    要花骰子点数（每天固定 20 点，很珍贵），**永远不点**（用户 2026-11-15）。
            #    所以这一页自己认按钮：只接受 x>=700 的白按钮（`下一步` 在 847 一带，
            #    `重新擲骰` 在 435 一侧），认不到就最多再点一次骰子看结果。
            # ❗失败结果页的标题是**事件名**（实测「騙術」），`rogue_dice_appear()`
            # 认不出，会一路干等到看门狗。所以这里再加一条**失败特征**判据
            # （中间的「失敗」大字），用户 2026-11-15 明确要求：认失败本身的特征，
            # 不要靠「下一步」按钮来认页面。
            if self.rogue_dice_appear() or self.rogue_dice_result_appear():
                signature = self.device.image[::32, ::32].tobytes()
                if signature != self.dice_page:
                    self.dice_page = signature
                    self.dice_tries = 0
                    self.dice_wait = Timer(8, count=1)
                point = self.rogue_secondary_point()
                if point and point[0] >= 700:
                    if press.reached():
                        press.reset()
                        logger.info('Leave the dice page, press (%s, %s)' % point)
                        self.tap_point(point[0], point[1], name='ROGUE_DICE_NEXT')
                    continue
                # ❗**结果页上绝不再点骰子**：点完「下一步」后有 1~2 秒的过渡动画，
                # 这段时间「失敗」还在、按钮已经没了，`rogue_secondary_point()`
                # 返回 None。原逻辑会掉进下面的 "Reveal the dice result" 分支去点画面，
                # 把过渡打断、又退回结果页 —— 实测 22:48 死循环了 20 多次。
                if self.rogue_dice_result_appear():
                    if press.reached():
                        press.reset()
                        logger.info('Dice result page, the 下一步 button is not ready, wait')
                    continue
                if self.dice_tries < DICE_TRIES and self.dice_wait.reached():
                    if press.reached():
                        press.reset()
                        self.dice_tries += 1
                        logger.info('Reveal the dice result (%s/%s)'
                                    % (self.dice_tries, DICE_TRIES))
                        self.tap_point(*DICE_POINT, name='ROGUE_DICE')
                continue

            # 6.1 【已删除】通用「白色 跳過 / 下一步」分支。
            #
            # 原实现是「只要画面右下角有白胶囊就点」，不看这是哪一页 —— 结果**把还没
            # 判断过的页面直接跳过去了**（用户 2026-11-15：「识别到跳过就直接跳过，
            # 导致本来要判断的页面直接跳过了，现在不知道那些页面有没有做判断」）。
            # 而且它排在 `# 6.5` 事件选项卡之前，只要有白按钮就 `continue`，
            # 后面所有页面判断都轮不到执行。
            #
            # 现在改成**只有明确认出页面才动作**：奖励页走 `# 2` 的橙色「獲得」、
            # 掷骰页走 `# 6`、删卡页走 `# 4.3`、复制页走各自的选卡分支。
            # 真正"只能跳过"的页面（卡牌轉換 / 灵光目标战斗员等）暂不处理 ——
            # 按用户的要求先留空，卡住了再逐个补"明确判据 + 跳过"。
            if self.copy_pending is not None and self.copy_pending.reached():
                self.copy_pending = None
            # `copying` 后面 `# 6.5` 的 `elif copying:` 分支还要用（复制卡牌的选卡页），
            # 删掉通用跳过分支时不能把它一起删了，否则 NameError。
            copying = self.copy_pending is not None and not self.copy_pending.reached()

            # 6.5 Event option selection and its checkmark submission.
            if self.handle_rogue_event(press):
                continue
            if copying:
                # 「請選擇欲複製的卡牌。」：卡在画面中部（y 172-598），底部检测带扫不到。
                # 和 `# 2.005` 一样，优先识别配置的目标卡：
                # 认到就锁定、认不出先重试几次，别一帧判死（OCR 会抖）。
                if press.reached():
                    press.reset()
                    if self.copy_target is None:
                        self.copy_target = self.rogue_copy_card_pick()
                    if self.copy_target:
                        x, y, name, score = self.copy_target
                        logger.info('Copy card page, pick %s at (%s, %s) score %.2f'
                                    % (name, x, y, score))
                        self.tap_point(x, y, name='ROGUE_COPY_CARD')
                        self.copy_target = None
                        self.copy_miss = 0
                        self.copy_pending = None
                    else:
                        self.copy_miss += 1
                        if self.copy_miss < COPY_CARD_MISS:
                            logger.info('Copy card page, %s not found yet (%s/%s), retry'
                                        % (self.config.ChaoszeroRogue_RogueCopyCard, self.copy_miss, COPY_CARD_MISS))
                            continue
                        # 同 `# 2.005`：认不出就赌第一张（用户 2026-11-17 选 B）
                        points = self.rogue_copy_card_points()
                        if points:
                            x, y = points[0][0], points[0][1]
                            logger.info('Copy card page, %s still not found after %s tries,'
                                        ' fall back to the first card at (%s, %s)'
                                        % (self.config.ChaoszeroRogue_RogueCopyCard, self.copy_miss, x, y))
                            self.tap_point(x, y, name='ROGUE_COPY_CARD')
                        self.copy_miss = 0
                        self.copy_pending = None
                continue

            # 6.6 傳送門 / 寶物倉庫入口卡（spec page_1 → page_2）：
            #     点卡选中（卡上移、底部出 ▼）→ 再点 ▼ 才进房。和事件选项卡同一套交互，
            #     只是整张卡在 y 550~630，`OPTION_BAND` 扫不到，所以只能靠模板认。
            # ❗用**模板本身**判断当前是未选中还是已选中（两个模板互斥），
            # 不要用 `treasure_stage` 计数：那页一旦认不出来 stage 就被重置，
            # 回头又去点卡，永远走不到 `∨`（2026-11-15 实测的死循环）。
            card_stage = self.rogue_treasure_card_stage()
            if card_stage:
                if press.reached():
                    press.reset()
                    if card_stage == 1:
                        logger.info('Press the 傳送門 card')
                        self.tap_point(TREASURE_CARD_POINT[0], TREASURE_CARD_POINT[1],
                                       name='ROGUE_TREASURE_CARD')
                    else:
                        logger.info('Confirm the 傳送門 card, entering the treasure room')
                        self.tap_point(TREASURE_ENTER[0], TREASURE_ENTER[1],
                                       name='ROGUE_TREASURE_ENTER')
                continue

            # 6.7 寶物倉庫（宝箱房）：三个箱位是固定的，但**必须先认到箱子才许点**
            #     （用户 2026-11-15：任何没有判断的乱点都不允许）。箱子上方那颗猫头图标
            #     开掉就没了，所以"图标还在"就是"这个箱子还没开"，一次点一个。
            #     开出来的是道具/卡/灵光甚至神闪，后续分别由 `獲得道具`、选项卡、
            #     `rogue_flash_appear` / `rogue_god_appear` 接住，这里不用管。
            slot = self.rogue_treasure_slot()
            if slot:
                if press.reached():
                    press.reset()
                    logger.info('Open the treasure chest at (%s, %s)' % slot)
                    self.tap_point(slot[0], slot[1], name='ROGUE_CHEST')
                continue

            # 7. 「點擊畫面可關閉視窗」的说明/预览弹窗（`精神異常` 那类整页说明）。
            #    动作就是点画面中部把它关掉。
            if self.rogue_modal_appear() or self.rogue_close_appear():
                if press.reached():
                    press.reset()
                    logger.info('Close the popup, tap the scene')
                    self.tap_point(*CUTSCENE_POINT, name='ROGUE_CLOSE')
                continue

            # 6.8 认不出的场景页：左上血条在（说明在局内），但整页没有任何已认的按钮。
            #      ❗**一个点都不点**（用户 2026-11-16：「未知页盲点要删掉」）。
            #      以前这里会先当剧情点画面中部、再按 SCENE_PATCH 固定点位挨个试 ——
            #      那等于在没有判据的页面上乱点，既可能误触（战斗演出时点在怪身上会
            #      弹敌人详情、把整场暂停），又掩盖了"这页根本没做判据"的事实。
            #      现在只做两件事：存帧（事后照真帧补判据）+ 等；真的不动了就收工。
            # ❗`BATTLE COMPLETE` 结算大字：**纯展示、会自己过去**，什么都不点。
            #   单独认一下只是为了**不存帧** —— 不清掉的话每场战斗都往
            #   `./log/rogue_pages/` 里塞一张，实测 120 张里 63 张是它，
            #   把真正需要看的未知页挤掉了（2026-11-17 聚类结果：27 类里第 1 类 63 帧）。
            if self.appear(ROGUE_BATTLE_COMPLETE, offset=(20, 16), similarity=0.85):
                continue

            if self.ui_battle_appear():
                # ❗**只在画面静止时存帧**：战斗动画每帧都在变，`rogue_dump_unknown`
                #   的签名去重挡不住，实测每 3 秒一张、3 分钟就 120 张全是战斗页。
                #   画面真静止了（`SCENE_STILL = 4` 秒）才说明"可能卡住"，那才值得存。
                if self.scene_wait.reached():
                    self.rogue_dump_unknown()
                if still.reached():
                    # ❗停任务，不撤退（同 `# 7` 那处）：实测卡死的是游戏客户端本身
                    # （2026-11-16 19:19 全黑帧 + 菜单点 4 次无反应），撤退也会卡住。
                    logger.warning('Unknown page and nothing to press, stop the task and '
                                   'wait for a human (frame saved under ./log/rogue_pages/)')
                    self.stopped_by_stuck = True
                    break
                continue

            # 7. 认不出的页面：**不串击**（用户 2026-11-14 明确要求：不要一串固定坐标
            #    挨个试）。只做两件事：底部有白色小圆点（卡牌选择标记）时按标记点，
            #    否则什么都不点，等画面自己变；真的不动了才收工。
            self.option_page = None
            # ❗整局结算之后（`確認` 按过）紧跟的是存档页，那页上有"删除存档"这种
            #   不可撤销的按钮。这一页还没做，所以结完账以后一律不按任何来路不明的
            #   标记点：宁可不做，也不能帮用户把要留的那份存档删掉。
            if self.settlement_seen:
                # 结算页上还有一段动画，`still` 每帧都被重置，等不到 → 用硬超时收工
                # （2026-11-15 04:17~04:36 在这页干等了 19 分钟）。
                if self.settle_wait.reached():
                    self.rogue_dump_unknown()
                    raise RequestHumanTakeover('Settlement did not reach a Rogue entry page')
                continue

            # ❗**这里原来是最后一个盲点**：未知页只要底部有 2~4 颗白色小圆点、
            # 且首尾间距 ≥200px，就按 `RoguePick` 点一下 —— 完全没有页面判据。
            # 用户 2026-11-16：「脚本又有一堆盲点的，什么时候点的都不知道」。
            # 而"按位置点卡"正是中立卡/诅咒卡偷偷进卡组的来源之一：复制页、灵光页、
            # 奖励页长得都像卡排，被点到就白拿一张。
            # **已删除**：未知页现在只存帧 + 等，绝不在没认出的页面上点任何东西。

            # ❗HUD 全隐藏的整屏演出：**同样一个点都不点**（用户 2026-11-16：
            #   「未知页盲点要删掉」）。这里以前会点画面中部推进，但那还是盲点 ——
            #   分不清"剧情/过场"和"没做判据的功能页"，前者该点、后者不该点。
            #   真过场会自己走完（`still` 会被重置）；不动的就收工存帧等人给规则。
            if still.reached():
                # ❗**停任务，不撤退**（用户 2026-11-16：「卡住或者某处反复死循环先暂停
                # 脚本，再等我处理」）。以前这里 `rogue_quit()` 会把这局直接放弃 ——
                # 而实测遇到的是**游戏客户端卡死**（2026-11-16 19:19 全黑帧 + 菜单
                # 点 4 次没反应 + `GameStuckError`），撤退本身也会卡住，等于白丢一局。
                logger.warning('Unknown page and nothing to press, stop the task and wait '
                               'for a human (frame saved under ./log/rogue_pages/)')
                self.stopped_by_stuck = True
                break
            continue

    def rogue_delete_rules(self):
        """Return ordered `[(card_name, count), ...]` configured for removal."""
        if not hasattr(self, 'config'):
            return [(name, 99) for name in REMOVE_TARGETS]
        try:
            node = self.config.data.get('ChaoszeroRogue', {})
            node = node.get('ChaoszeroRogue') or node
            text = str(node.get('RogueDeleteFilter') or '')
            slot_cids = [
                str(node.get('RogueSlot1Member') or ''),
                str(node.get('RogueSlot2Member') or ''),
                str(node.get('RogueSlot3Member') or ''),
            ]
            preferred = node.get('RogueRemoveMember', 1)
        except Exception as error:
            logger.warning('Failed to read RogueDeleteFilter from config.data: %s' % error)
            text = str(getattr(self.config, 'ChaoszeroRogue_RogueDeleteFilter', '') or '')
            slot_cids = [
                str(getattr(self.config, 'ChaoszeroRogue_RogueSlot1Member', '') or ''),
                str(getattr(self.config, 'ChaoszeroRogue_RogueSlot2Member', '') or ''),
                str(getattr(self.config, 'ChaoszeroRogue_RogueSlot3Member', '') or ''),
            ]
            preferred = getattr(self.config, 'ChaoszeroRogue_RogueRemoveMember', 1)
        rules = rogue_cards.parse_delete_filter(text)
        return rogue_cards.prioritize_delete_rules(rules, slot_cids, preferred)

    def rogue_delete_times(self):
        """Returns: int: 这一局最多删几张卡（0 = 不删）。"""
        return sum(count for _, count in self.rogue_delete_rules())

    def rogue_pick_index(self):
        """Returns: int: 配置里"选第几张卡"。"""
        try:
            index = int(self.config.ChaoszeroRogue_RoguePick)
        except (AttributeError, TypeError, ValueError):
            return 1
        return index if 1 <= index <= 3 else 1

    # ---------------------------------------------------------------- 入口

    def run(self):
        """
        Task: 卡厄思肉鸽 —— 进本、推进、结算。

        起点有两种：大厅或肉鸽入口页（正常开局），以及上一次中断的局内页面。局内的页面
        认不出 `page_main`，也没法用 `ui_quit_to_main()` 退出去 —— **它退不出去**，
        会落进 boot 的"点顶部唤醒"循环，5 分钟 `GameStuckError` 之后把客户端重启
        （2026-11-13 实测，白丢 5 分钟）。所以入口页之外接管已有进度。

        一次调度打 `RogueRuns` 局（0 = 不退出）。回到大厅或肉鸽入口页才开下一局：
        还停在局内说明这局没走完（超时 / 认不出的页面），硬开下一局只会把两局搅在一起。

        Pages:
            in:  大厅、肉鸽入口页或局内页
            out:  大厅、肉鸽入口页（正常）或局内页（这一局没走完）
        """
        logger.hr('Rogue', level=1)

        runs = 0
        limit = self.config.ChaoszeroRogue_RogueRuns
        limit = int(limit) if limit else 0
        # 只有本次 run() 亲自走过入口链、选过世界，后续轮才沿用游戏记住的地图
        # （用户 2026-11-19）；接管局内进度不算，下一轮仍要按配置重选。
        reselect = True

        # ❗不要每局回大厅去治疗中心查一遍：需要治疗时游戏自己会弹崩溃页
        # （`觸發精神異常` / `夢境模式` 变体），局内循环里接住就行（用户 2026-11-15：
        # 「你每打完一局就回大厅去治疗中心，这样要浪费多少时间？」）。
        while True:
            if limit and runs >= limit:
                logger.info('Ran %s run(s), stop this round' % runs)
                break

            fresh_run = self.rogue_outside_appear()
            if fresh_run:
                logger.info('At the lobby / team / 卡厄思 page, walk the entry chain')
                # 用户 2026-11-19：刚打完一局的下一轮游戏记住的就是刚刷的世界，
                # 别再退回世界列表重选（白退两次）；只有还没亲自选过才选一次。
                if not self.rogue_enter(reselect_world=reselect):
                    logger.warning('Could not start a run, give up this round')
                    self.config.task_delay(minute=30)
                    raise TaskFailed('ChaoszeroRogue: never got into a run from the lobby')
                reselect = False
                # ❗新开一局 = 又回到**第一面**，把"已进第二面"的持久标记清掉。
                # 只有"接管局内"（上面的 else 分支）才保留它 —— 那种情况可能已经
                # 在第二面了，重启脚本不该把状态丢掉。
                # 删卡次数同理：`RogueDelete` 是「一局 3 张」，新局重新计。
                self.rogue_state_save(core_started=False, remove_done=0, remove_counts={})
            else:
                logger.info('Not on an entry page, take over the run in progress')

            self.rogue_run(fresh_run=fresh_run)
            runs += 1

            # `RogueStopBeacon` 到点撤退：这一局是我们主动收掉的，别再开下一局
            # （否则"打到第 N 个航点就停"根本停不下来）。
            if self.stopped_by_beacon:
                logger.info('Stopped by RogueStopBeacon after %s waypoint(s), end this task'
                            % self.waypoints)
                break

            # 卡住 / 死循环：**停任务等人处理**，不撤退、不重开下一局
            # （用户 2026-11-16）。帧已经存到 `./log/rogue_pages/`。
            if self.stopped_by_stuck:
                raise RequestHumanTakeover('The Rogue screen got stuck or looped')

            if not self.rogue_outside_appear():
                logger.info('The run did not return to the lobby or a Rogue entry page, stop here')
                break
            logger.info('The run is over, back at the lobby or a Rogue entry page')

            # 一局结束后角色可能崩溃：游戏自己在需要治疗时弹「觸發精神異常」，
            # 上面有绿色 `治療中心` 和紫色 `下一步`（2026-11-15 用户实机图）。
            # 不要像原来那样盲点 `下一步`，否则崩溃角色一直治不了、下一局进不去。
            # 治完继续刷就行，对产出没有影响（用户确认）。
            if self.config.ChaoszeroRogue_RogueCure and self.rogue_crash_appear():
                self.rogue_crash_handle()
            continue

        logger.info('Rogue task finished after %s run(s)' % runs)
        if self.config.ChaoszeroRogue_RogueLoop:
            self.config.task_delay(minute=1)
        else:
            self.config.task_delay(minute=30)
