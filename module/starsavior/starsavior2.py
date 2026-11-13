"""Starsavior2: 刷初始一轮。

流程（2026-11-06 用户口述）：

    登录    标题页 -> Sign in with Google -> 选已有账号
    引导    引导 1~52 -> 昵称 -> 引导 56~107
    旅程    倍速 x2 -> 训练 -> 评鉴战（先过引导再点自动战斗）-> 结算
    结算    两个签到 -> 解锁 -> 后续引导 -> 主界面
    领奖    邮箱 -> 任务
    抽卡    观测十连，直到「再次观测」变灰
    验号    只看 SSR（TODO，素材未框）
    重置    设定 -> 账号管理 -> 重置 -> 输确认语

每一段都是同一个循环 + 一张按钮表：

    for _ in self.loop(timeout=...):
        for button in 这一段的按钮:
            if appear(button): 点它; 等它消失; break

为什么能这么写：引导是一次性的，按钮点完就没了。所以每帧从头扫一遍最省心 ——
漏一帧下一帧接得上，中途重进游戏也能从任意位置接回来，不需要记录"我走到第几步"。

按钮表是从 dev_tools/specs 的页面卡导出的，改流程请改卡片再重新导出，别在这里手改：
    python -m dev_tools.spec_build <spec.json> --write
"""
import json
import os
import random
import re
import subprocess
import threading
import time

import numpy as np

import module.config.server as server
from module.base.button import Button
from module.base.timer import Timer
from module.exception import ScriptError, TaskFailed
from module.logger import logger
from module.notify import load_onepush_conf
from module.starsavior.assets import (
    E_4_2,    E_100_1, E_101_1, E_102_1, E_103_1, E_104_1,
    E_105_1, E_106_1, E_107_1, E_108_1, E_109_1,
    E_10_1, E_110_1, E_111_1, E_112_1, E_113_1,
    E_114_1, E_115_1, E_116_1, E_117_1, E_119_1,
    E_11_1, E_120_1, E_121_1, E_122_1, E_123_1,
    E_124_1, E_125_1, E_126_1, E_127_1, E_128_1,
    E_129_1, E_12_1, E_130_1, E_131_1, E_132_1,
    E_133_1, E_134_1, E_134_2, E_135_1, E_136_1,
    E_137_1, E_138_1, E_139_1, E_13_1, E_140_1,
    E_141_1, E_142_1, E_144_1, E_145_1, E_146_1,
    E_147_1, E_148_1, E_149_1, E_14_1, E_150_1,
    E_151_1, E_152_1, E_153_1, E_154_1, E_155_1,
    E_156_1, E_157_1, E_158_1, E_159_1, E_15_1,
    E_160_1, E_161_1, E_162_1, E_163_1, E_164_1,
    E_165_1, E_166_1, E_167_1, E_168_1, E_16_1,
    E_118_1, E_171_1, E_171_2, E_171_3, E_172_1, E_173_1,
    E_174_1,
    E_175_1, E_175_2, E_176_1, E_176_2, E_176_3,
    E_177_1, E_178_1,
    E_17_1, E_180_1, E_181_1, E_182_1, E_183_1,
    E_183_2, E_184_1, E_184_2, E_185_1, E_186_1,
    E_187_1, E_188_1, E_189_1, E_18_1, E_190_1,
    E_191_1, E_192_1, E_193_1, E_195_1, E_196_2,
    E_197_1, E_198_1, E_199_1, E_19_1, E_1_1,
    E_200_1, E_200_2, E_201_1, E_202_1, E_202_2,
    E_20_1, E_21_1, E_22_1,
    E_23_1, E_24_1, E_25_1, E_26_1, E_27_1,
    E_28_1, E_29_1, E_2_1, E_2_3, E_30_1,
    E_31_1, E_32_1, E_33_1, E_34_1, E_35_1,
    E_36_1, E_37_1, E_38_1, E_39_1, E_3_1,
    E_40_1, E_41_1, E_42_1, E_43_1, E_44_1,
    E_45_1, E_46_1, E_47_1, E_48_1, E_49_1,
    E_50_1, E_51_1, E_53_1, E_54_1, E_55_1,
    E_56_1, E_57_1, E_58_1, E_5_1, E_60_2,
    E_61_1, E_62_1, E_63_1, E_64_1, E_65_1,
    E_66_1, E_67_1, E_68_1, E_69_1, E_6_2,
    E_70_1, E_71_1, E_72_1, E_73_1, E_74_1,
    E_75_1, E_76_1, E_77_1, E_78_1, E_79_1,
    E_7_1, E_80_1, E_81_1, E_82_1, E_83_1,
    E_84_1, E_85_1, E_86_1, E_87_1, E_88_1,
    E_89_1, E_8_1, E_90_1, E_91_1, E_92_1,
    E_93_1, E_94_1, E_95_1, E_96_1, E_97_1,
    E_98_1, E_99_1, E_9_1,
    E_205_1, E_206_1, E_206_2, E_207_1, E_208_1, E_209_1, E_210_1, E_211_1, BATTLE_SKILL,
)
from module.starsavior import highlight
from module.starsavior.guide_chain import guide_page, previous_guide_page
from module.starsavior.journey import JourneySpeed, TrainFail, SPEED_BOX
from module.starsavior.ocr import RESET_DIALOG, RESET_ENTRY, RESET_TAB, read_nick, read_reset_input
from module.starsavior.scan import RescuerScan
from module.starsavior.starsavior_ui import StarsaviorUI
from module.starsavior.target import (
    MAX_COUNT,
    MIN_COUNT,
    TARGET_MODE_ALL,
    TARGET_MODE_ANY,
    TARGET_MODES,
    check_targets,
)

# 允许按钮偏离框选位置多少像素。引导气泡位置会变，所以不能按固定坐标点；
# 但开得越大越慢：两百个模板全屏扫一遍要三秒，外扩 60 像素只要几十毫秒。
CHAIN_OFFSET = 60

# Google 账号选择弹窗整块（原图坐标）。列表是从上往下展开的，等它停住再点。
ACCOUNT_DIALOG = (296, 154, 984, 593)

# 战场中央。战斗自动进行时这块一直在动（人物、特效、伤害数字），
# 用来区分"战斗还没打完"和"这段真的结束了"。
BATTLE_WATCH = (300, 300, 980, 560)

# ❗闪退重进可能落在「主界面 + 新手引导遮罩」：整屏被半透明黑幕压暗，
#   右侧亮蓝「主流路线」高亮框是唯一能点的东西，右上四格 E_171_1 在遮罩
#   背后照样 1.000（硬约束 42）—— `at_main_screen()` 会假阳性，接着跳过
#   引导链，浮层吞掉邮箱/任务/抽卡/验号/重置的每一次点击（真机
#   2026-11-10 15:40~15:41，最后「重置失败」+ `Reason: Error`）。
#   真机 15:41 抓帧：框区域 mean 119 / 整屏 mean 42（比值 2.82）、
#   亮蓝占比 0.191；对比 30 张其它真机帧，比值 0.57~1.91、亮蓝占比 0
#   （唯一 ratio=1.91 的 REWARD 结算页靠 blue=0 排除）。
TUTORIAL_ROUTE_AREA = (1035, 330, 1280, 430)
TUTORIAL_ROUTE_TAP = Button(area=TUTORIAL_ROUTE_AREA, color=(0, 0, 0),  # alas-lint: allow - a pure tap point, the overlay check is a pixel test, never a template match
                            button=(1157, 380, 1157, 380), name='TUTORIAL_ROUTE_TAP')
TUTORIAL_ROUTE_DARK = 60
TUTORIAL_ROUTE_RATIO = 1.8
TUTORIAL_ROUTE_BLUE = 0.10
TUTORIAL_ROUTE_TIMEOUT = 8
TUTORIAL_ROUTE_SETTLE = 2

# 判据和点击不在同一处的按钮：{判据: 真正要点的}。
# 「添加其他账号」是固定文字，可以当判据；上面那行账号的名字每次都不一样，
# 只能当点击目标。
CLICK_TARGET = {
    E_2_1: E_2_3,
    E_175_1: E_175_2,
    E_183_1: E_183_2,
    E_184_1: E_184_2,
}

# 昵称规则（GUI 里可以自己填，留空就随机）。
#
# ❗`input text` 只认 ASCII，中文昵称根本打不进去，所以白名单只放英文和数字；
#   写死一个名字会被游戏判「非法」（用户 2026-11-06 23:15：「不要用这个名，
#   换个，非法了」）—— 多半是重名或者被占用，所以留空时**每轮重新随机**。
#   长度 4~16 是游戏要求。
#
# ❗❗**随机名里不许出现任何有意义的词**。原来用「Savior + 4 位数字」，
#   真机 2026-11-07 23:30 游戏弹「包含无法使用的字。」—— `Savior8374`、
#   `Savior9748` 都被拒，确认键怎么点都不前进，看起来像「卡在昵称页」。
#   用户当天明确：「改成纯随机无意思的字母＋数字」。
#   `Savior` 是英文「救世主」，大概率撞了敏感词表；以后也别换别的单词前缀。
NICK_MIN = 4
NICK_MAX = 16
NICK_CHAR = re.compile(r'[0-9A-Za-z]')

# 随机名用的字符集：去掉 `i l o 0 1` 这些 OCR 容易认错的，
# 回读校验（`nick_typed_ok`）能少一堆误判。
NICK_LETTERS = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ'
NICK_DIGITS = '23456789'

# 停节点（`StopAt` 配置项的取值）。和「目标角色」互斥，只能填一个。
STOP_NONE = 'none'
STOP_NICKNAME = 'nickname'      # 节点1：到昵称输入框停下，不打字
STOP_GUIDE = 'guide'            # 节点2：所有引导走完停下（还没领奖、没抽卡）
STOP_VERIFY = 'verify'          # 节点3：一直跑到验号
STOP_CHOICES = (STOP_NONE, STOP_NICKNAME, STOP_GUIDE, STOP_VERIFY)

# 目标角色最多挂 7 只（`argument.yaml` 里是 `Target` + `Target2`~`Target7`）。
# ❗判定是**任意一个角色凑够它自己的数量就停**，不是七只凑齐 —— 见 `target.check_targets()`。
TARGET_FIELDS = (
    'Target', 'Target2', 'Target3', 'Target4',
    'Target5', 'Target6', 'Target7',
)

# 验号记录（`config/state/starsavior_accounts.json`）最多留多少轮。
# 一条只有「时间 + 角色列表」，一轮约 100 字节，500 轮也就 50KB 上下。
SCAN_LOG_LIMIT = 500

# 需要往里打字的按钮（昵称走实例方法 `text_for()`，这里只放固定文案）。
TEXT_INPUT = {
    E_200_1: '重置服务器账号',
}

# 点不动时改点的位置（比 `retry_point()` 的通用四角更准，用户指定过）。
#
# `E_139_1` = 「获得全新祝福」那屏的「确认」。这屏**确认键本身是死的**，
# 要先点它上面的**祝福框**（「专注提升 I +20」那条横条）才会推进。
# 用户 2026-11-07 13:1x：「我说的框是获得全新祝福下面那个框，点那里是能进行的」，
# 紧接着又补一句「点框内左右没有内容的地方」—— 横条中间是星星图标和「+20」
# 小框，**点图标/数字都不算点框**。
#
# ❗用法：**第 1 次点 area 中心（确认本体），点不动才走这份点列**。
#   `E_139_1` 是蓝色「确认」，同时出现在两屏（硬约束 157）：
#     · 「最终旅程结果」屏 —— 点确认就能过；
#     · 「获得全新祝福」屏 —— 点确认没反应（游戏 bug），要点祝福横条
#       右侧的空白（横条 = (512,397)-(812,433)，中间是星星图标和「+20」，
#       点图标/数字都不算点框）。
#   用户 16:15：「优先级应该是点下面那个确认，当点确认没用（游戏bug）
#   才去点偏移，现在一直点偏移本不会过结算」。
#   ❗重试计数按「**连着**几次点不动」算：点掉一次就清零（press 里
#   `tries.pop`），否则同一段里第二次出现就直接跳到点列 —— 16:32 的
#   「最终旅程结果」屏就是这么被跳过的（点中心本来 0.3 秒就过）。
#   真机 2026-11-07 14:12 的旧教训：中心连点 12 次都没推进 —— 那时是
#   **只点中心**、没有偏移；15:5x 左端 (520,415) 又点到了**祝福**，所以
#   点列只留**右端空白**（距右缘留 8px）。
RETRY_AT = {
    E_139_1: ((800, 415), (790, 420), (800, 408)),
}


# 登录：Sign in with Google -> 选已有账号（2 个）
#
# ❗「Touch to Start」(E_1_1) **不在**这张表里。它在登录弹窗背后一直可见
#   （弹窗是半透明的），放进表里就会被每帧重扫到、反复点，等于在登录页点"取消"——
#   真机 2026-11-06 19:32 / 19:33 两次都弹出了「已取消登入。」。
#   它由 `login()` 单独点一次。
LOGIN = (
    E_3_1, E_2_1,
)

# 账号已在线时点完「Touch to Start」会**直接进开场动画 / 剧情**，不弹 Google 登录页。
# 这四张是 `press()` 里量过的「右上 SKIP 横栏」三套版式（真机 2026-11-06 23:45）：
# 剧情页 0.95 命中，标题页 / 主界面全 0.000，正好当「已经进游戏」的正面判据。
# ❗不收 E_115_1（纯黑过场兜底）：加载黑屏也是黑的，会撞硬约束 163 的假阳性。
STORY_SKIP = (
    E_5_1, E_69_1, E_202_1, E_202_2,
)

# 引导 1~52（到昵称之前）
#
# ❗`E_5_1`（右上角 SKIP）**不在**这张表里。它在整个剧情里一直可见，
#   放进表里就是每帧都点它，而 `press` 靠"点完等它消失"判断下一步 ——
#   它永远不消失，于是卡在原地空转（真机 2026-11-06 19:36 连点 12 次，
#   剧情一句没推进，还把 nemu 截图拖超时了）。
#   剧情推进交给每屏自己的「点击继续」模板（E_6_2 这类），
#   它们点完就换屏，正好是 `press` 要的语义。
# ❗`E_4_2`(598,621,683,638) 是**登录之后第一次点击**的那个按钮
#   （用户 2026-11-06 22:44：「登录后 page_4 还要点一次才进入游戏…复用 E_4_2」）。
#   page_4 在 assets 里只有 `E_4_2` 这一张，没有 `E_4_1` ——
#   原来表里没收录它，选完账号之后就卡在这一页，开场引导/昵称/引导/旅程
#   四段全部"一个页面都没点到"，空转 60 秒后游戏自己退了（Game died）。
GUIDE_A = (
    E_4_2, E_6_2, E_7_1, E_8_1, E_9_1, E_10_1,
    E_11_1, E_12_1, E_13_1, E_14_1, E_15_1, E_16_1,
    E_17_1, E_18_1, E_19_1, E_20_1, E_21_1, E_22_1,
    E_23_1, E_24_1, E_25_1, E_26_1, E_27_1, E_28_1,
    E_29_1, E_30_1, E_31_1, E_32_1, E_33_1, E_34_1,
    E_35_1, E_36_1, E_37_1, E_38_1, E_39_1, E_40_1,
    E_41_1, E_42_1, E_43_1, E_44_1, E_45_1, E_46_1,
    E_47_1, E_48_1, E_49_1, E_50_1, E_51_1, E_53_1,
    E_54_1, E_55_1, E_56_1, E_57_1, E_58_1,
)

# 昵称（2 个）
NICK = (
    E_60_2, E_61_1,
)

# 引导 56~107（53 个）
GUIDE_B = (
    E_62_1, E_63_1, E_64_1, E_65_1, E_66_1, E_67_1,
    E_68_1, E_69_1, E_70_1, E_71_1, E_72_1, E_73_1,
    E_74_1, E_75_1, E_76_1, E_77_1, E_78_1, E_79_1,
    E_80_1, E_81_1, E_82_1, E_83_1, E_84_1, E_85_1,
    E_86_1, E_87_1, E_88_1, E_89_1, E_90_1, E_91_1,
    E_92_1, E_93_1, E_94_1, E_95_1, E_96_1, E_97_1,
    E_98_1, E_99_1, E_100_1, E_101_1, E_102_1, E_103_1,
    E_104_1, E_105_1, E_106_1, E_107_1, E_108_1, E_109_1,
    E_110_1, E_111_1, E_112_1, E_113_1, E_114_1,
)

# 旅程：倍速 -> 训练 -> 评鉴战（20 个）
# ❗`E_116_1` / `E_117_1` 故意不在表里：它们和 `E_118_1` 是**同一块 area**
#   (984,29,1012,47) 的三张模板，1x / 2x / 3x 三档的匹配分**全是 1.000**
#   （TM_CCOEFF_NORMED 只比结构不比颜色）。放进表里 press 会一档一档点下去，
#   3x 再点回 1x，永远停不下来。倍速交给 `journey.ensure_speed()` 读亮度判档位。
#
# ❗`E_122_1` 排在 `E_120_1` 前面：这两个是**同一屏**的两个按钮（右侧菱形图标），
#   122 是「训练」、120 是「休息」。按页号排会先点休息，时间白白前进一天又回到这一屏
#   （真机 2026-11-06 20:30，进度从「3 3月上旬」变成「2 3月下旬」）。
#   用户 20:31：「这里应该是到训练2，page_122了」。
JOURNEY = (
    E_115_1, E_119_1, E_122_1, E_120_1, E_121_1,
    E_122_1, E_123_1, E_124_1, E_125_1, E_126_1, E_127_1,
    E_128_1, E_129_1, E_130_1, E_131_1, E_132_1, E_133_1,
    E_134_1, E_134_2,
)

# 结算 -> 签到 -> 解锁 -> 后续引导（34 个）
#
# ❗`E_119_1`（跳过新手教学）也放进来：这个弹窗**跨段出现** ——
#   旅程里点过一次，清引导到 168 之后它又弹一次（用户 2026-11-06 21:17
#   「复用旅程里的跳过新手教学就行」）。
SETTLE = (
    # E_208_1「最终旅程结果」标题必须排在 E_139_1 前：这屏的确认键模板
    # 在新版 UI 下匹配不上，靠标题命中后点固定确认坐标。
    E_119_1, E_135_1, E_136_1, E_137_1, E_138_1, E_208_1, E_139_1, E_140_1,
    E_141_1, E_142_1, E_144_1, E_145_1, E_146_1, E_147_1,
    E_148_1, E_149_1, E_150_1, E_151_1, E_152_1, E_153_1,
    E_154_1, E_155_1, E_156_1, E_157_1, E_158_1, E_159_1,
    E_160_1, E_161_1, E_162_1, E_163_1, E_164_1, E_165_1,
    E_166_1, E_167_1, E_168_1,
)

# 邮箱（4 个）
# 用户 2026-11-06 21:23：「page_172 到 page_175 就是全流程领邮箱了」。
#
# ❗`E_171_2`（右上角信封）**不能进这张表**：邮箱面板盖住主界面之后它照样
#   匹配得上（面板没盖住那个角落），于是和 `E_175_1` 来回点，
#   真机 21:25 直接撞 `GameTooManyClickError: Too many click between
#   2 buttons: E_175_1, E_171_2`。入口得单独点一次，不能混在循环表里。
#
# ❗确认框 `E_173_1` 必须排在「一键领取」`E_172_1` **前面**。点 172 会弹
#   「信件全部领取 / 是否要领取所有信件?」模态框，框只盖住中间，底下的
#   一键领取仍露着、模板分照样 0.996；`press` 每帧从表头扫，先命中 172
#   就会一直点它并等它消失（永远不消失），173 一次都轮不到 —— 真机
#   2026-11-07 00:30 连点 4 次 172 后 blocked，173/174/175 全没点到，
#   两封信一封没领（用户：「邮箱卡住了，没有点确认，一直点一键领取」）。
#   实测普通邮箱面板 E_173_1=False、确认框 E_173_1=True，调顺序不会误点。
MAIL = (
    E_173_1, E_172_1, E_174_1, E_175_1,
)

# 「一键领取」按钮的底（亮=金黄 / 暗=灰）。两张模板 area 几乎重叠、匹配分都是
# 1.000，所以亮暗只能靠这片区域的**金黄像素占比**判（真机实测亮的 0.814/0.842，灰的 0）。
TASK_CLAIM_BOX = (1058, 631, 1136, 658)
TASK_CLAIM_ON = 0.30

# 判"领取动画走完没有"要看大一点：按钮 + 上面那条任务列表都会变。
TASK_CLAIM_AREA = (1027, 600, 1180, 690)

# 教学战里敌人身上那个白圈的中心（真机 live_st2 量的：(670,320)-(780,430)）。
# 用户 2026-11-06 23:06：「这种框都是会动的。你固定位置吧。
# 反正都是跑重置循环，不会换战斗风格」。写死没问题，但**换战斗布局就得改这里**。
BATTLE_TARGET = (725, 375)

# 白框只认这几块里的中心：highlight.find 在没有白圈的帧上会给 (961,107)
# 那种顶部假框。真机 2026-11-07 白圈从 (684,383) → (684,451) → **右下技能卡
# (1126,659)** 一路移动，只放开战场中央就会被区域挡掉、退回固定坐标点敌人，
# 教学战又卡住（02:06 完整一轮复现）。左上小图标那种小圈 find 本来就找不到，
# 交给表里的引导素材。
BATTLE_RING_AREAS = (
    (450, 250, 900, 600),      # 战场中央：白圈套敌人
    (1000, 600, 1280, 720),    # 右下技能卡：白框套 BURST / 特殊技
    (1100, 250, 1280, 420),    # 右侧角色头像
)

# 自动战斗有没有真的开：右上「总伤害量 N」那块白字。真机 2026-11-07
# 离线量过：关态（live_battle / auto_0_off，相隔数秒两帧）亮像素都是
# 0.000、底色是一片蓝色小条；点开之后 0.228~0.622（auto_1_on / live_auto）。
# ❗AUTO 按钮本身没有蓝环，右上角两态几乎一样，**不能用按钮颜色判成功**。
AUTO_BATTLE_AREA = (1140, 105, 1280, 180)
AUTO_BATTLE_ON = 0.05

# 评鉴战进场后**延迟 1~2 秒**才出现的对话条。真机 2026-11-12 22:36 的五帧
# 量准：空窗 / 引导结束都是 0.000，引导中 0.855~0.857。判据不是「画面变没变」
# ——这个游戏背景、人物、红色准心、血条特效全在动——而是右上这块**固定 UI**
# 的「中性亮色」占比。白框有字、有人像也不影响，亮色底仍占 85%。
BATTLE_DIALOG_AREA = (880, 120, 1260, 200)
BATTLE_DIALOG_NEUTRAL = 0.35
BATTLE_DIALOG_GRACE = 3.0      # E_134_1 点掉后，等延迟对话出现的最长时间
BATTLE_DIALOG_CLICK = (1100, 170)  # 点在对话框正文上，只推进这一句

# 一段 press 里倍速补档最多点几下。1x→3x 只要 2 下；旅程里「跳过新手教学」
# 和进新关卡会让倍速自己掉回 1x（用户 2026-11-06 20:28），留余量。
# ❗没有这个上限就会像 2026-11-07 02:41 那样：VICTORY 页上把一片纯暗块
#   读成 1x，每 2 秒补点一次、连点 60 多次，quiet 被每次补档 reset，
#   journey 段再也退不出去。
# ❗从 4 提到 8：过场里**点击会被吞**（档位条还亮着 1x，点了没反应）。
#   真机 2026-11-07 17:01 就是这样：引导段在过场里收工、旅程提前开跑，
#   补档连点两下都没验收 → 永久关掉 → 训练门禁挡着 → 整段旅程空转。
#   8 下 × 约 4 秒间隔 ≈ 30 秒，够熬过开场过场；仍然是有上限的，
#   不会回到 02:41 那种连点 60 次的局面。
SPEED_PRESS_CLICKS = 8

# 补档采样的间隔（秒）。连续两次独立采样都读到低档才允许点，
# 淡入淡出 / 大招白屏的单帧读值不算数。
SPEED_HOLD = 1.0

# 「选择特殊技攻击敌人」(引导 page_23) 那枚特殊技按钮见 assets.py 的手写条目
# `BATTLE_SKILL`：纯坐标、没有 file，只给 press() 用，永不进 appear 家族。

# 抽卡结果页底部的「观测10次」= `E_182_1`(665,654,838,679)，没资源时同一块变成
# `E_183_1`(663,654,839,680) —— 两张 area 几乎完全重叠，模板分不出亮暗。
# 真机量出来能抽的时候是**蓝底**（这片蓝像素占 0.558），抽不动时是灰的。
# 用户 2026-11-06 21:52：「抽卡的里我也是用了亮暗」。
GACHA_FULL_AREA = (0, 0, 1280, 720)       # 判"画面换没换"用全屏，最保险

# ❗抽卡这几个按钮**不能用 area 中心**：spec 框的矩形普遍比按钮矮一截，
#   area 中心正好落在按钮上边框上，点了完全没反应 —— 真机 2026-11-06 22:00
#   就是因为这个来回戳「再次观测」和「确认」戳了 50 多次。
#   下面这些是手动点通了才记下来的（按钮真正的视觉中心）。
GACHA_TAP_RESULT = (751, 672)    # 结果页「观测10次」（area 中心是 666，偏上 6px）
GACHA_TAP_CONFIRM = (540, 678)   # 结果页「确认」（area (507,654,549,677) 只框到左半）
# 「最终旅程结果」的蓝色确认中心：标题 E_208_1 只是判据，点击落在这里。
RESULT_CONFIRM = (639, 660)
GACHA_TAP_DRAW = (1142, 672)     # 抽卡界面「观测10次」
GACHA_TAP_DIALOG = (728, 492)    # 确认框「确认」
GACHA_RESULT_BOX = (665, 654, 838, 679)   # 结果页底部的「观测10次」
GACHA_DRAW_BOX = (1052, 660, 1232, 685)   # 抽卡界面右下角的「观测10次」
GACHA_BLUE_ON = 0.25

# 左侧五个页签的点击坐标（原图）。真机 `live_tab0` 量准的：**行高是 50**，
# 每日 100 / 每周 150 / 成就 200 / 挑战 250 / 指南 300，文字中心 x≈84。
#
# ❗原来按 48 的间距写成 96/144/192/240，累积偏出去 10 像素，点到页签**外面**了 ——
#   于是"切页签"其实没切，还在上一页（已领完、灰的），一秒就判"领完了"，
#   四个页签只领到每日一个。用户 2026-11-06 21:48 一眼看出来：
#   「你现在只领了每日的」。
TASK_TABS = (
    ('每日', (84, 100)),
    ('每周', (84, 150)),
    ('成就', (84, 200)),
    ('挑战', (84, 250)),
)

# 左侧页签栏。切页签时高亮会移动，拿这块的帧差当"切过去了"的判据。
TASK_TAB_AREA = (0, 60, 200, 330)

# 任务（只做能一键领取的那个页签）（1 个）
TASK = (
    E_177_1,
)

# 抽卡（5 个）
GACHA = (
    E_180_1, E_181_1, E_182_1, E_183_1, E_184_1,
)

# 验号前的引导（8 个）。
#
# ❗这里只放**引导本身**，不能放 193 / 195 / 196：
#   193 是左上返回箭头，列表页同一个位置也有一个 —— 放进来 press 会在列表上
#   一直点它，直接把列表点退出去了；
#   195 是「突破极限」入口、196 是那个面板的 ✕ —— 放进来 press 会替我们开面板、
#   关面板，把页面搅乱。这三个由 scan.py 在需要时按顺序点。
VERIFY = (
    E_185_1, E_186_1, E_187_1, E_188_1,
    E_189_1, E_190_1, E_191_1, E_192_1,
)

# 重置那条路上的五个素材（197 账号管理 / 198 重置标题 / 199 确认 / 200_1 输入框 / 200_2 确认）。
#
# ❗**它们全部不能当判据**，真机实测匹配分都是 0.000（2026-11-06 19:30）：
#   `E_197_1` 是未选中态的灰字，「账号管理」被选中时才高亮；
#   `E_198_1` 是白底模板，实际按钮是深底；
#   `E_199_1` / `E_200_2` 两个「确认」是另一版式；
#   `E_200_1` 输入框是**纯色**（std 3.7），对任何暗画面都得 1.000，等于永远成立。
# 所以 `reset()` 改成用 OCR 认字（`ocr.py` 的 RESET_TAB / RESET_ENTRY / RESET_DIALOG），
# 坐标直接写死 —— 每一步的坐标都在真机上量过、截图确认过。

# 重置账号时要在弹窗里输入的确认语（游戏要求一字不差）
# 游戏里写的是「重置服务器**帐**号」（帐），而界面上的选项叫「重置服务器**账**号」（账）。
# 真机 2026-11-06 22:52 输入「账号」版本，点确认**照样重置成功** —— 游戏不做字面校验。
RESET_WORD = '重置服务器账号'

# 游戏闪退检测（2026-11-09 真机）：16:58 客户端自己掉到桌面，之后所有段的
# 按钮表一个都认不到、一路空转到 17:01「重置失败」才退出，日志里连一条
# `App stop/start` 都没有 —— 工具是独立进程，没有调度器那套「卡死 → Restart」兜底。
#
# 两种退出都要认（2026-11-09 17:2x 现场 adb 实测）：
#   ① 进程消失 —— `pidof com.studiobside.starMain` 为空；
#   ② **退回桌面但进程还在** —— 前台是 `app.lawnchair/.LawnchairLauncher`，
#      `pidof` 仍能读到 30928。这次用户看到的正是 ②，只看 ① 会完全漏检。
# ❗桌面判据只认「默认 HOME 包名 / 名字里带 launcher」，不认「前台不是游戏」：
#   Google 登录、权限弹窗、输入法都会短时间把游戏压到后台，拿"不是游戏"判
#   会把正常流程误杀。命令输出经 grep 只回一行，比整套 `dumpsys window` 轻。
CRASH_FRONT_CMD = ('dumpsys activity activities | '
                   'grep -E "topResumedActivity|mResumedActivity"')
CRASH_POLL = 3
CRASH_CONFIRM = 2
CRASH_GRACE = 10           # 画面就绪后再给 10 秒，别把刚起来的客户端判死
CRASH_MAX_RESTART = 3      # 一次工具运行最多自动重启几次，防无限重启


class GameCrashed(Exception):
    """Internal signal: game is gone or back on the desktop, `run()` restarts it."""

    def __init__(self, message, gone=False):
        super().__init__(message)
        self.gone = gone   # True = 进程没了，False = 只是退回桌面


class Starsavior2(JourneySpeed, TrainFail, RescuerScan, StarsaviorUI):
    """刷初始：登录 -> 引导 -> 旅程 -> 结算 -> 领奖 -> 抽卡 -> 验号（按配置决定停在哪）。

    验号那一段的实现单独放在 `scan.py`（要按行遍历，和这里的"每帧重扫"不是一路）。

    ❗这是 WebUI「工具」页的工具，**不是调度任务**（`task.yaml` 里 `page: 'tool'`、
    没有 `Scheduler` 组）。所以这里既不 `task_delay()` 也不碰 `Scheduler.Enable`：
    跑完 `run()` 返回，进程就结束了，要不要再来一轮由配置里的三种模式决定。
    """

    # 工具配置（`run()` 开头的 `load_plan()` 覆盖）。写成类属性是为了不重写
    # `UI.__init__` —— 这里只需要默认值，不参与构造。
    nickname = ''
    input_enabled = True       # 节点1：点开昵称输入框但不打字
    targets = None             # None = 没设目标，跑一轮就停
    target_mode = TARGET_MODE_ANY   # any = 任意一个角色凑够就停 / all = 全都要
    stop_at = STOP_NONE
    target_hit = False
    target_detail = ()         # 验号结果（`verify()` 里覆盖），推送正文要用
    last_scan = ()             # 本轮读到的 SSR（`verify()` 里覆盖），每轮推送正文要用

    # press() 在引导段看到标题/登录页时置 True；guide_press() 读到后重新登录。
    # 默认 False：别的段不传 stop_on_login，行为不变。
    need_relogin = False

    # 闪退检测开关。默认关：`--step` 单跑、冷启动画面还没画出来时不查；
    # 只有 `run()` 在 `wait_start_screen()` 之后才 arm。
    crash_watch = False
    crash_missing = 0
    crash_grace_until = 0.0

    def arm_crash_watch(self):
        """画面已就绪，开始查游戏进程；重启 / 重置之后要重新调一次。"""
        self._crash_timer = None
        self.crash_missing = 0
        self.crash_grace_until = time.time() + CRASH_GRACE
        self.crash_watch = True

    def loop(self, skip_first=True, timeout=None):
        """
        给所有状态循环挂一层闪退检测，其它行为与 `ModuleBase.loop()` 一致。

        这个工具的每一段（guide / journey / settle / claim / gacha / verify /
        reset / wait_start_screen）都走 `self.loop()`，所以挂在这里一处就能覆盖
        全部长循环，不必逐段插检测。`check_game_crash()` 自己按秒节流。

        Raises:
            GameCrashed: 连续多次查不到游戏进程，交给 `run()` 重启并重走本轮。
        """
        for image in super().loop(skip_first=skip_first, timeout=timeout):
            self.check_game_crash()
            yield image

    def check_game_crash(self):
        """按秒查一次，连续多次确认「进程没了 / 退回桌面」才抛 `GameCrashed`。

        adb 自己掉线时只跳过本轮检测：那是连接问题，重启游戏救不了。
        """
        if not self.crash_watch or time.time() < self.crash_grace_until:
            return
        timer = getattr(self, '_crash_timer', None)
        if timer is None:
            self._crash_timer = Timer(CRASH_POLL).start()
            return
        if not timer.reached():
            return
        timer.reset()

        package = server.to_package('starsavior')
        try:
            alive = bool(self.device.adb_shell(['pidof', package]).strip())
        except Exception as e:
            logger.warning('闪退检测：adb 查进程失败（%s），跳过本轮' % e)
            self.crash_missing = 0
            return
        gone = not alive
        desktop = self.game_on_desktop() if alive else False
        if alive and not desktop:
            self.crash_missing = 0
            return

        self.crash_missing += 1
        reason = '进程消失' if gone else '退回桌面'
        logger.warning('闪退检测：%s（%d/%d）'
                       % (reason, self.crash_missing, CRASH_CONFIRM))
        if self.crash_missing >= CRASH_CONFIRM:
            raise GameCrashed('%s，连续 %d 次' % (reason, self.crash_missing),
                              gone=gone)

    def desktop_package(self):
        """默认桌面的包名，查一次就缓存（`cmd package resolve-activity`）。"""
        cached = getattr(self, '_desktop_package', None)
        if cached is not None:
            return cached
        cached = ''
        try:
            out = self.device.adb_shell([
                'cmd', 'package', 'resolve-activity', '--brief',
                '-a', 'android.intent.action.MAIN',
                '-c', 'android.intent.category.HOME',
            ])
            for line in out.splitlines():
                if '/' in line:
                    cached = line.split('/')[0].strip()
        except Exception as e:
            logger.warning('闪退检测：查不到桌面包名（%s），只靠进程判据' % e)
        self._desktop_package = cached
        return cached

    def game_on_desktop(self):
        """前台是不是桌面。只认「默认 HOME / 名字带 launcher」，不认普通系统弹窗。"""
        try:
            front = self.device.adb_shell(CRASH_FRONT_CMD)
        except Exception as e:
            logger.warning('闪退检测：查前台失败（%s），跳过本轮' % e)
            return False
        # `dumpsys activity activities` 可能给多行（每个 task 一条），
        # 只拿当前 resumed 那一行，别把历史记录里的桌面读成前台。
        line = ''
        for row in front.splitlines():
            if 'topResumedActivity' in row:
                line = row
                break
            if 'mResumedActivity' in row and not line:
                line = row
        if not line:
            return False
        home = self.desktop_package()
        if home and home in line:
            return True
        return 'launcher' in line.lower() or 'lawnchair' in line.lower()

    def restart_game(self, gone=False, force=False):
        """闪退后把游戏拉回来；等画面交给下一轮的 `wait_start_screen()`。

        Args:
            gone (bool): 进程已经没了（此时 stop 无害）。
            force (bool): 连续重启仍拉不回来，这次强杀冷启动。

        ❗进程还在、只是退回桌面时**先不 force-stop**：`app_start()` 会把已有
          Activity 带回前台，不打断游戏内存里的进度；真拉不回来再强杀。
        ❗不调 `ui_goto_main()` / 任何 UI 的 boot 流程：星之救援者还没量出
          `page_main`（`starsavior_ui.py` 里是留空的），调用会直接
          `GamePageUnknownError`。`device.app_start()` 会作废旧帧并清看门狗。
        """
        logger.hr('游戏闪退，重启', level=1)
        self.crash_watch = False
        self.crash_missing = 0
        try:
            package = server.to_package('starsavior')
            # `dev_tools/run_tool.py --step` 不走 `switch_game()`，
            # `device.package` 还停在 alas.json 里那个游戏上，不修会启动错包。
            if self.device.package != package:
                logger.info('重启：device.package %s -> %s'
                            % (self.device.package, package))
                self.device.package = package
            if gone or force:
                self.device.app_stop()
            else:
                logger.info('重启：进程还在，先只把游戏拉回前台')
            self.device.app_start()
        finally:
            self._crash_timer = None

    def tutorial_route_overlay(self):
        """
        「主界面 + 新手引导遮罩」的纯像素判据。

        半透明黑幕把整屏压暗，只留右侧那块亮蓝「主流路线」高亮框可点。
        用**相对亮度**（框 / 整屏）而不是绝对阈值：换主题、换亮度也不会漂。
        三条同时成立才算：整屏偏暗、框明显比整屏亮、框里亮蓝像素够多。
        30 张其它真机帧上全部为 False（含 REWARD 结算页，它亮但蓝=0）。

        Returns:
            bool: 引导遮罩还在不在。
        """
        # 刚进这一段时 device 可能还没 image 属性（真机撞过 AttributeError），
        # 用 getattr 兜一下；拿不到帧就当"没有遮罩"，交给上层继续判。
        image = getattr(self.device, 'image', None)
        if image is None:
            return False
        a = np.asarray(image, dtype=np.int32)[..., :3]
        whole = a.mean()
        x0, y0, x1, y1 = TUTORIAL_ROUTE_AREA
        box = a[y0:y1, x0:x1]
        r, g, b = box[:, :, 0], box[:, :, 1], box[:, :, 2]
        blue = float(((b > 190) & (g > 150) & (r < 190)).mean())
        ratio = box.mean() / max(whole, 1)
        return (whole < TUTORIAL_ROUTE_DARK
                and ratio >= TUTORIAL_ROUTE_RATIO
                and blue >= TUTORIAL_ROUTE_BLUE)

    def dismiss_tutorial_route(self):
        """
        点掉新手引导高亮框，让 `guide()` 能按当前画面接住。

        点一下没反应不等于失败（硬约束 153）：这里等**连续两帧**都看不到
        遮罩才算收工，动画中间帧的一次假阴性不会提前放过它。

        Returns:
            bool: True = 浮层已经不在（本来就没有，或点掉了）。
        """
        if not self.tutorial_route_overlay():  # alas-lint: allow - "no overlay" is the normal path, nothing is pressed here
            return True
        logger.info('闪退重进：还在新手引导浮层，点「主流路线」继续')
        self.device.click(TUTORIAL_ROUTE_TAP)  # alas-lint: allow - matched by the pixel test above, its disappearance below is the proof
        clean = 0
        for _ in self.loop(timeout=TUTORIAL_ROUTE_TIMEOUT):
            if self.tutorial_route_overlay():
                clean = 0
                continue
            clean += 1
            if clean >= TUTORIAL_ROUTE_SETTLE:
                return True
        logger.warning('闪退重进：新手引导浮层没点掉')
        return False

    def resumed_at_hall(self):
        """
        闪退重进后是不是真的在**可交互**的大厅。

        `at_main_screen()` 只认右上四格，引导遮罩背后照样成立；必须再排除
        `tutorial_route_overlay()`，否则会跳过引导链、让遮罩吞掉后面所有点击。

        ❗四格在、`tutorial_route_overlay()` 也不在，仍不一定是可交互大厅：
        2026-11-13 12:16 闪退重进落在「主界面 + 观测新手遮罩」，半透明黑幕
        把整屏压暗，四格在、菜单点不开、侧栏全上锁。旧判据把它当成大厅，
        跳过引导后邮箱/任务/抽卡/验号全部点空，最后重置也失败。
        这里要求菜单**真的能打开**：打不开就说明还在开荒遮罩，交回 `guide()`。

        Returns:
            bool: 可以跳过开场引导 / 旅程 / 结算。
        """
        if not self.at_main_screen() or self.tutorial_route_overlay():
            return False
        self.device.screenshot()
        if not self.open_menu(timeout=6):
            logger.info('重进：四格在但菜单打不开，当成还在引导期')
            return False
        # 菜单是浮层，验证完先收起来；后面的领奖 / 抽卡会自己重开。
        self.device.screenshot()
        if self.appear(E_171_1, offset=(10, 10)):
            self.click_button(E_171_1, '菜单 → 主界面')
            self.wait_until_disappear(E_176_2, offset=(10, 10),
                                      timeout=3, settle=2)
        return True

    def at_main_screen(self):
        """
        主界面右上四格在 = 结算已经走完、账号在大厅。

        项目里多处真机量过的**正面**判据（`settle()` 用它决定要不要再扫一遍
        「跳过新手教学」，`gacha()` 用它确认回到主界面）。不用「标题页不见了」
        当"已经进游戏"：加载黑屏上标题页也不见（真机 2026-11-07 12:43 误判过）。
        """
        return self.appear(E_171_1, offset=(10, 10))

    def in_game(self):
        """
        账号已经进游戏的正面判据。

        ❗只用主界面四格，不放宽到「标题页不见了」或别的小图标：加载黑屏上
          标题页也不见（真机 2026-11-07 12:43），近常量区域的小模板
          `appear(offset=)` 会假阳性（硬约束 163）。重进落在引导 / 旅程页时
          `login()` 第 0 步已按「标题页和登录弹窗都看不见 → 当作已登录」
          直接返回，不需要这里再认。
        """
        return self.at_main_screen()

    def at_journey(self):
        """
        当前画面是不是**旅程 HUD**。

        旅程页没有右上四格，也没有剧情 SKIP，只有顶部倍速 `E_116_1`
        （`JourneyPlay` 场景）。闪退重进 / 点完 Touch to Start 时游戏会直接
        恢复到旅程，不能只靠大厅和 SKIP 判。

        2026-11-12 20:55 两张真机截图 0.981 / 0.986；另外 24 张历史截图
        最高只有 0.067，标题页、登录页、结算页都不命中。

        Returns:
            bool: 当前在旅程 HUD。
        """
        return self.appear(E_116_1, offset=CHAIN_OFFSET)

    def in_game_screen(self):
        """
        「账号已经进游戏」的正面判据，补上**大厅以外**的游戏内画面。

        `in_game()` 只认主界面右上四格；账号已在线时点完 `E_1_1` 直接进的是
        开场动画 / 剧情页，那里既没有四格也没有 Google 登录弹窗，
        `login()` 第 2 步就会白等 20 秒再 `return False`（真机 2026-11-10
        17:25:57~17:26:17）。四张量过的 SKIP 横栏模板正好覆盖这一段。

        ❗旅程页也要单独认：它既没有四格也没有 SKIP，但顶部倍速一直可见。
          2026-11-12 20:52 闪退后客户端直接恢复到 `JourneyPlay`，旧判据
          让 `login()` 白等 20 秒后判失败，实际 6 秒就已经在旅程里。

        ❗仍然不用「标题页不见了」：加载黑屏上标题页也不见（163）。

        ❗教学战也要认：2026-11-13 逐页强杀实测，page_7 / 16 / 25 / 37
        这些存档点重启后客户端直接回到教学战，既没有四格、SKIP，也没有
        旅程倍速；不认 BOSS 血条就会白等 20 秒判登录失败。`in_battle()`
        只认顶部深红血条，普通大厅/加载页不会命中。

        Returns:
            bool: 已经在游戏内（大厅 / 开场动画 / 剧情页 / 旅程 / 战斗）。
        """
        if self.in_game():
            return True
        # 教学大厅的「参加评鉴战」目标卡会盖住右上四格，单独认。
        if self.appear(E_209_1, offset=CHAIN_OFFSET):
            return True
        if self.at_journey():
            return True
        if self.in_battle():
            return True
        # ❗无 SKIP 的剧情页：2026-11-13 07:5x 打完基础评鉴战，VICTORY 后闪退，
        #   客户端恢复到战后剧情（克莱儿“…太惊人了。”）。这一屏没有 SKIP、
        #   没有四格、没有血条，但左上角目标书本 `E_211_1` 一直在。
        #   231 张实测截图里它只在这张剧情页命中，主大厅/旅程/战斗都不命中。
        if self.appear(E_211_1, offset=CHAIN_OFFSET):
            return True
        # 重启有时直接落回昵称框（page_60），这里也要算已进游戏，
        # 否则 wait_start_screen 会白等 180 秒、login 也判失败。
        if self.appear(E_60_2, offset=CHAIN_OFFSET):
            return True
        for button in STORY_SKIP:
            if self.appear(button, offset=CHAIN_OFFSET):
                return True
        return False

    def wait_enter_game(self, timeout=30):
        """点完 Touch to Start 后，等读条结束并确认**真的**进了游戏。

        ❗不能用「按钮消失了」当成功：读条会短暂盖住 Touch to Start，
        0.2 秒后按钮消失、1 秒后标题页又回来，实际没进去
        （真机 2026-11-12 17:42）。只认 `in_game_screen()` 的正面判据；
        标题页连续 3 帧回来就判这次没进去，交给调用方重试。

        Returns:
            bool: True = 已经在游戏内（大厅 / 开场动画 / 剧情页）。
        """
        game_hits = 0
        title_frames = 0
        for _ in self.loop(timeout=timeout):
            self.device.stuck_record_clear()
            # 读条 / 登录过程中弹的「发生错误」「通知」会盖住一切，先点掉
            if self.dismiss_game_error() or self.dismiss_notice():
                game_hits = 0
                title_frames = 0
                continue
            game_hits = game_hits + 1 if self.in_game_screen() else 0
            if game_hits >= 3:
                return True
            if (self.appear(E_3_1, offset=CHAIN_OFFSET)
                    or self.appear(E_2_1, offset=CHAIN_OFFSET)):
                return False
            if (self.appear(E_4_2, offset=CHAIN_OFFSET)
                    or self.appear(E_1_1, offset=CHAIN_OFFSET)):
                title_frames += 1
                if title_frames >= 3:
                    return False
            else:
                title_frames = 0
        return False

    def warmup_ocr(self):
        """后台线程先把 cnocr 模型加载好。

        ❗验号第一次读角色名要 **5.5 秒**（真机 2026-11-07 10:29:45 开始加载、
        10:29:50 才出来，日志 `[角色名 5.458s]`），全花在模型加载上。这 5.5 秒
        卡在「验号刚开始」那一屏，用户看到的就是「192_1 救援者引导走完，等半天
        才去验号」。这里丢到后台线程，和 guide / journey 那十几分钟重叠，
        等于不花时间 —— 失败也不影响主流程，验号时照旧懒加载。
        """
        def load():
            try:
                from module.starsavior import ocr
                blank = np.zeros((40, 240, 3), dtype=np.uint8)
                for button in (ocr.NAME, ocr.TROUPE):
                    button.ocr(blank)
                logger.info('OCR 预热完成')
            except Exception as error:
                logger.warning('OCR 预热失败（不影响后续，验号时会自己加载）：%s' % error)

        threading.Thread(target=load, daemon=True).start()

    def set_round(self, value):
        """把「第几轮」写进配置，GUI 工具页会读它显示（参数区不可见）。

        ❗用 `cross_set` 而不是 `self.config.Starsavior2_Round = value`：
          后者依赖 `config_generated.py` 已重新生成、且当前任务确实绑定了该参数，
          漏了会静默失败。`cross_set` 直接走 modified + 落盘，不依赖绑定。
        """
        try:
            self.config.cross_set('Starsavior2.Starsavior2.Round', int(value))
        except Exception as e:
            logger.warning('写入轮数失败（不影响刷初始）：%s' % e)

    def run(self):
        """工具页入口：按配置跑一轮，或者刷到目标角色为止。

        三种模式（GUI 里「目标角色」和「停节点」**只能填一个**）：

        · 选了目标角色 → 一轮轮刷到出。达标停下、**不重置**（号留在游戏里）；
          没达标就重置账号接着刷。重置失败就停，别把号刷丢。
        · 选了停节点 → 跑到那个节点就停（节点1 昵称前 / 节点2 引导后 / 节点3 验号）。
        · 两个都没填 → 只跑一轮，验号完停下，**不重置**。

        「刷初始次数」> 0 时跑满这么多轮就停，**不重置**；和目标角色同时用 =
        先到哪个算哪个（达标优先）。次数在**重置之前**判，不会白丢一轮的号。

        ❗**不要加 `task_delay()` / 改 `Scheduler.Enable`**：这不是调度任务，
        跑完 `run()` 返回、进程结束就完事；那些调用只会往别的任务的配置里写脏东西。
        """
        logger.hr('刷初始（工具）', level=1)
        self.set_round(0)
        self.load_plan()

        index = 0
        restarts = 0
        self.resume_after_crash = False
        while 1:
            index += 1
            self.set_round(index)
            logger.hr('第 %d 轮' % index, level=1)
            self.target_hit = False
            self.target_detail = ()
            self.last_scan = ()
            self.click_count = 0
            # ❗冷启动 / 换号后画面还没画出来，这段时间**不查进程**：
            #   `app_start()` 是"先杀再启"，中间必然有几帧 `pidof` 是空的。
            #   等 `wait_start_screen()` 认到画面再开检测。
            self.crash_watch = False
            try:
                # ❗先等画面，再判登录：冷启动/换号后的加载画面上 `login()` 的判据
                #   会误判成"已经在游戏里"，接着整条链在加载画面上空转。
                if not self.wait_start_screen():
                    # 认不出画面就再拉一次游戏，别硬着头皮往下点。
                    raise GameCrashed('等不到游戏画面', gone=True)
                self.arm_crash_watch()
                # ❗`login()` 返回 False 说明登录链没走完，后面所有段的按钮表
                #   都不适用，继续跑只会逐段 idle 空转，最后还可能去 `reset()`
                #   把号刷丢。明确停住，账号留着让用户手动收拾。
                #   ❗❗但这条让容错比 v1.42.1 之前（忽略返回值、继续扫状态机）
                #   低得多：只要 `login()` 认不出「已经登录」就会整轮判死。
                #   所以 `login()` 必须认全游戏内画面 —— 主界面四格、开场动画、
                #   剧情页（SKIP 横栏）、旅程 HUD（顶部倍速），见 `in_game_screen()`。
                #   17:10 / 17:25 / 20:53 三次误报都栽在判据不全；
                #   别再把它回退成「白等 20 秒就停」。
                if not self.login():
                    raise TaskFailed(self.fail_reason(
                        '登录没走完，已停止，避免在游戏内空转把号刷丢。'
                        '账号没有丢；把游戏停回标题页再手动重跑。'))
                self.warmup_ocr()

                # ❗闪退重进：游戏保留登录态和开荒进度，重进可能直接落在主界面
                #   或旅程（2026-11-12 20:52 就是旅程闪退后恢复到 JourneyPlay）。
                #   `guide/journey/settle` 的按钮表全是引导期素材，在大厅上只会
                #   逐段 idle 空转（真机 2026-11-10 07:31:14~07:32:13 连着三段
                #   「一个页面都没点到」）。判到主界面就直接接领奖 / 抽卡 / 验号；
                #   判到旅程就跳过引导、从当前旅程画面续跑；判不到说明还在
                #   标题 / 登录 / 引导期，按原来的整轮状态机自愈。
                #   ❗要放在 `login()` **之后**：账号在线时是 `login()` 点了
                #   「Touch to Start」才真正进到大厅的。
                #   ❗❗但 `at_main_screen()` 单看右上四格会**假阳性**：重置后的
                #   新号重进会落在「主界面 + 新手引导遮罩」，四格在半透明黑幕
                #   背后照样 1.000。2026-11-10 15:40 真机就这样跳过了引导链，
                #   浮层吞掉之后每一次点击，最后「重置失败」+ `Reason: Error`。
                #   所以先点掉引导浮层，再用「四格在 + 遮罩不在」判真大厅；
                #   遮罩还在就回退整轮状态机，绝不跳过。
                resumed_late = False
                resumed_journey = False
                if self.resume_after_crash:
                    self.resume_after_crash = False
                    self.device.screenshot()
                    self.dismiss_tutorial_route()
                    self.device.screenshot()
                    resumed_late = self.resumed_at_hall()
                    if resumed_late:
                        logger.hr('闪退重进：已在大厅，跳过开场引导 / 旅程 / 结算', level=2)
                    else:
                        # 服务器也记旅程进度：闪退重进会直接落在 `JourneyPlay`，
                        # 这时再走 `guide()` 整条引导表一页都认不出，只会空转。
                        # 旅程本身是无状态的按钮表，可以接着当前画面继续跑。
                        resumed_journey = self.at_journey()
                        if resumed_journey:
                            logger.hr('闪退重进：已在旅程，跳过开场引导，继续旅程', level=2)
                        else:
                            logger.info('闪退重进：还在引导期 / 不在大厅，按当前画面重走本轮状态机')

                # 工具手动停在中途再重跑 / 未知原因回到标题后重登：可能直接落在
                # 大厅或旅程，这时都不该重走开场引导。
                # ❗大厅要排除「主界面 + 新手引导遮罩」：那还是开荒期，必须走引导。
                if not resumed_late and not resumed_journey and self.resumed_at_hall():
                    resumed_late = True
                    logger.info('登录：已在大厅，跳过开场引导 / 旅程 / 结算')
                if not resumed_late and not resumed_journey and self.at_journey():
                    resumed_journey = True
                    logger.info('登录：已在旅程，跳过开场引导，继续旅程')

                # ❗无 SKIP 的剧情页：登录判据已经认它，但 guide() 的按钮表里
                #   没有任何可点的东西，不先点完剧情就会整段空转。
                #   2026-11-13 07:5x 打完基础评鉴战，VICTORY 后闪退，重登落在
                #   战后剧情；这里点完剧情，若出现「旅程结束」(`E_135_1`) 就
                #   接 settle() 走完结算，否则交给下面的状态机。
                resumed_story = False
                if not resumed_late and not resumed_journey:
                    self.device.screenshot()
                    if self.appear(E_211_1, offset=CHAIN_OFFSET):
                        logger.hr('闪退重进：无 SKIP 剧情，先点完', level=2)
                        if self.story_advance():
                            # ❗先认「旅程结束」(`E_135_1`)：战后剧情点完会回到
                            #   大厅，这一屏右上四格也在，先判大厅会跳过 settle。
                            #   剧情结束后常有一小段黑屏，给 20 秒等落点。
                            for _ in self.loop(timeout=20):
                                self.device.stuck_record_clear()
                                self.device.screenshot()
                                if self.appear(E_135_1, offset=CHAIN_OFFSET):
                                    resumed_story = True
                                    break
                                if self.at_journey():
                                    resumed_journey = True
                                    break
                                if (self.in_game()
                                        or self.appear(E_209_1, offset=CHAIN_OFFSET)):
                                    resumed_late = True
                                    break

                if resumed_late:
                    # 节点1 / 节点2 都在引导期，重进时早就过了，别继续抽卡。
                    if self.stop_at in (STOP_NICKNAME, STOP_GUIDE):
                        self.report_plan('闪退重进时已在大厅，停节点已经过了（不重置账号）')
                        return
                elif resumed_journey:
                    # 节点1 / 节点2 都在引导期，重进时已经过了旅程入口，别继续跑。
                    if self.stop_at in (STOP_NICKNAME, STOP_GUIDE):
                        self.report_plan('闪退重进时已在旅程，停节点已经过了（不重置账号）')
                        return
                    # 旅程没走完，跳过开场引导，从当前旅程画面继续。
                    self.journey()
                    self.settle()
                elif resumed_story:
                    # 剧情已经点完：如果是战后剧情，这一屏右侧有「旅程结束」
                    # (`E_135_1`)，先走完结算再去领奖。
                    if self.stop_at in (STOP_NICKNAME, STOP_GUIDE):
                        self.report_plan('闪退重进时剧情已经过了停节点（不重置账号）')
                        return
                    self.device.screenshot()
                    if self.appear(E_135_1, offset=CHAIN_OFFSET):
                        self.settle()
                else:
                    if not self.guide(stop_at_nickname=self.stop_at == STOP_NICKNAME):
                        self.report_plan('节点1：昵称输入框（没有输入昵称）')
                        return
                    if self.stop_at == STOP_GUIDE:
                        self.report_plan('节点2：所有引导走完（还没领奖励、没抽卡）')
                        return

                    self.journey()
                    self.settle()

                self.claim()
                self.gacha()
                self.verify()
                # 每轮验号完都推一次结果（含没达标/没读到 SSR），推完继续下一轮。
                # 不在这里等用户确认；目标达成 / 停节点 / 刷满次数仍按下面的逻辑停。
                self.notify_round(index)

                # 节点3：验号结束就是终点，不管目标角色（冲突时已经在 load_plan
                # 里被清空了）。不留这一支会掉进下面的「没有目标角色」，日志里写
                # 「只跑一轮」，看不出选的是节点3。
                if self.stop_at == STOP_VERIFY:
                    self.report_plan('节点3：验号完成（不重置账号）')
                    return

                if self.target_hit:
                    self.report_plan('目标达成，号留在游戏里，不重置')
                    return
                # ❗次数上限**必须在重置之前判**。放到 `while` 头上判的话，最后一轮
                #   会先被重置掉、回到标题页，才发现「已经刷够了」—— 白丢一个号。
                # ❗也要排在「没有目标角色」前面：只填次数不填目标 = 老老实实刷这么多轮，
                #   不能因为没挂目标就只跑一轮。
                if self.reroll_count and index >= self.reroll_count:
                    self.report_plan('已刷满 %d 轮，停下（不重置，号留在游戏里）' % self.reroll_count)
                    return
                if not self.targets:
                    self.report_plan('没有目标角色：跑完这一轮就停，不重置')
                    return

                logger.hr('第 %d 轮没达标，重置账号接着刷' % index, level=1)
                # ❗重置账号时游戏会重载回标题页，进程可能短暂消失；
                #   这一小段关掉检测，免得把自己的换号判成闪退。
                self.crash_watch = False
                try:
                    reset_ok = self.reset()
                finally:
                    self.arm_crash_watch()
                if not reset_ok:
                    logger.warning('重置失败，停止（别把号刷丢）')
                    self.report_plan('重置失败')
                    # ❗不能 `return`：进程会记 `Reason: Finish`，WebUI 里看着像
                    #   正常跑完，手机上也没有推送。抛 `TaskFailed` 交给
                    #   `GameScheduler.run()`：它负责推一条，并把这次运行记成失败。
                    raise TaskFailed(self.fail_reason(
                        '重置账号失败，已停止。账号没有丢；游戏停在重置弹窗'
                        '或加载页，手动点掉弹窗、回到标题页就能重跑。'))
                # 完整跑完一轮，闪退额度重新给满（只拦「连续重启」）。
                restarts = 0
            except GameCrashed as e:
                # 闪退重进不算新的一轮：GUI 的「第 N 轮」保持连续。
                index -= 1
                restarts += 1
                if restarts > CRASH_MAX_RESTART:
                    raise TaskFailed(self.fail_reason(
                        '游戏连续闪退 %d 次，已停止自动重启。账号没有丢，'
                        '检查模拟器内存 / 客户端后再手动启动。' % restarts))
                logger.warning('游戏闪退（%s），重启并重走这一轮的状态机（第 %d/%d 次）'
                               % (e, restarts, CRASH_MAX_RESTART))
                # 游戏自己记开荒进度和登录态：在昵称页闪退，重进就落在昵称页；
                # 在结算段闪退，重进可能**直接落在大厅**（真机 2026-11-10 07:30）。
                # 各段本来就是「每帧重扫按钮表、不记走到第几步」，所以重跑整轮
                # 能按当前画面接；但已经在大厅时引导期那几张表一页都认不出，
                # `run()` 会用 `resume_after_crash` 跳过那几段空转。
                self.restart_game(gone=e.gone, force=restarts >= 2)
                self.resume_after_crash = True
                continue

    def load_plan(self):
        """把 GUI 的配置落成实例状态：昵称 / 达标条件 / 目标 / 停节点。"""
        self.nickname = self.make_nickname(self.config.Starsavior2_Nickname)
        self.target_mode = self.read_mode()
        self.targets = self.read_targets()
        self.stop_at = self.read_stop()
        # 刷初始次数：跑满这么多轮就停，**不重置**。0 / 留空 = 不限。
        try:
            self.reroll_count = max(0, int(self.config.Starsavior2_RerollCount or 0))
        except (TypeError, ValueError):
            logger.warning('「刷初始次数」填的不是数字，按「不限」处理')
            self.reroll_count = 0

        # ❗互斥：两个都填了按「停节点」跑。GUI 的帮助文字和 `argument.yaml`
        #   都写着「填了节点就按节点跑，目标角色会被忽略」，代码以前反着来：
        #   一选节点就被静默忽略、按旧的目标角色继续刷（真机 2026-11-08 12:10，
        #   用户：「选了节点，但是还是继续打了」）。目标角色常常是上一轮留下的
        #   旧值，停节点才是这次显式要的，冲突时保住后者。
        if self.targets and self.stop_at != STOP_NONE:
            logger.warning('「目标角色」和「停节点」只能填一个，两个都填了 → '
                           '按停节点跑，目标角色忽略')
            self.targets = None

        # 节点1 只点开输入框、不打字；别的模式照常输入。
        self.input_enabled = self.stop_at != STOP_NICKNAME

        if self.targets:
            target_note = ' / '.join('%s × %d 只' % (row['label'], row['count'])
                                     for row in self.targets)
            target_note = '%s（%s）' % (
                target_note,
                '任意一个角色凑够就停' if self.target_mode == TARGET_MODE_ANY
                else '每一只都要凑够')
        else:
            target_note = '不指定（跑一轮就停）'
        logger.info('本轮配置：昵称 %s / 目标 %s / 停节点 %s / 次数 %s'
                    % (self.nickname, target_note, self.stop_at,
                       self.reroll_count if self.reroll_count else '不限'))

    def read_targets(self):
        """GUI 的七个「目标角色」→ `check_targets()` 要的列表；一个都没选返回 None。

        ❗最多 7 只（`TARGET_FIELDS`），**每一只各自带自己的数量**
          （`TargetCount` / `TargetCount2` ... `TargetCount7`）。
        怎么算达标由 `TargetMode` 决定，这里只负责把配置读成列表。
        七个位里重复选同一只的，只算一次（后面那几位的数量不叠加）。
        """
        targets = []
        seen = set()
        for index, field in enumerate(TARGET_FIELDS, start=1):
            # `getattr` 兜底：`config_generated.py` 还没重新生成时不会 AttributeError。
            label = str(getattr(self.config, 'Starsavior2_' + field, 'none') or 'none').strip()
            if label in ('', 'none'):
                continue
            if label in seen:
                logger.info('目标角色 %s 填了不止一次，只算一次' % label)
                continue
            seen.add(label)
            targets.append({'label': label, 'count': self.read_count(index)})

        if not targets:
            return None
        return targets

    def read_count(self, index):
        """第 `index` 个目标要几只（1~4）。字段名 `TargetCount` + 序号，第 1 个没有后缀。"""
        field = 'TargetCount' if index == 1 else 'TargetCount%d' % index
        if not hasattr(self.config, 'Starsavior2_' + field):
            # 旧配置（`config_generated.py` 没重新生成）只有 TargetCount 一个，退回用它。
            field = 'TargetCount'
        raw = getattr(self.config, 'Starsavior2_' + field, 1)
        try:
            count = int(raw or 1)
        except (TypeError, ValueError):
            logger.warning('%s 不是数字，按 1 只算' % field)
            count = 1
        return min(max(count, MIN_COUNT), MAX_COUNT)

    def read_mode(self):
        """`TargetMode`：`any` = 任意一个角色凑够就停，`all` = 挂上的全都要凑够。"""
        if not hasattr(self.config, 'Starsavior2_TargetMode'):
            return TARGET_MODE_ANY
        mode = str(self.config.Starsavior2_TargetMode or TARGET_MODE_ANY).strip()
        if mode not in TARGET_MODES:
            logger.warning('未知的达标条件 %r，按「任意一个角色」处理' % mode)
            return TARGET_MODE_ANY
        return mode

    def read_stop(self):
        stop = str(self.config.Starsavior2_StopAt or STOP_NONE).strip()
        if stop not in STOP_CHOICES:
            logger.warning('未知的停节点 %r，按「不中途停」处理' % stop)
            return STOP_NONE
        return stop

    @staticmethod
    def retry_point(area, tries):
        """同一按钮点不动时的备用落点：在框内绕中心换四个点。

        ❗游戏会**吞掉正中那一下**：同一个坐标连点 5 次，判据一动不动
        （真机 2026-11-07 13:10 的 `E_139_1`，结算段直接卡死，后面
        领奖 / 抽卡 / 验号全废）。换个离边 1/4 的点再点一下就过了。
        用户 13:1x：「做点击偏移，点了确认后，再点一下框内」。

        Args:
            area (tuple): (x1, y1, x2, y2) 按钮的 area。
            tries (int): 这个按钮已经点了几次（第 2 次起才换点）。

        Returns:
            tuple: (x, y)
        """
        x1, y1, x2, y2 = area
        dx = max((x2 - x1) // 4, 2)
        dy = max((y2 - y1) // 4, 2)
        points = (
            (x1 + dx, y1 + dy),
            (x2 - dx, y2 - dy),
            (x1 + dx, y2 - dy),
            (x2 - dx, y1 + dy),
        )
        return points[(tries - 2) % len(points)]

    @staticmethod
    def random_nickname():
        """纯随机的无意义昵称：6 个字母 + 4 个数字，打乱顺序，共 10 位。

        ❗**不能带任何有意义的词**：原来是 `Savior` + 4 位数字，真机
          2026-11-07 23:30 游戏弹「包含无法使用的字。」，确认键怎么点都不走。
          强制混进数字是因为有些游戏要求「字母 + 数字」，纯字母可能又被判非法。
        """
        chars = [random.choice(NICK_LETTERS) for _ in range(6)]
        chars += [random.choice(NICK_DIGITS) for _ in range(4)]
        random.shuffle(chars)
        return ''.join(chars)

    @classmethod
    def make_nickname(cls, text):
        """把 GUI 里填的昵称变成真能打进去的名字。

        · 留空 → 纯随机字母数字（`random_nickname()`）。写死的名字会被游戏判
          「非法」（用户 2026-11-06 23:15：「不要用这个名，换个，非法了」），
          所以空的必须每轮重新随机，不能缓存一个常量。
        · 只留英文/数字：`input text` 送不了中文，游戏也只收这两种。
        · 过滤完长度不在 4~16 → 退回随机名，别让游戏弹「非法昵称」。
        """
        text = str(text or '').strip()
        if not text:
            return cls.random_nickname()
        cleaned = ''.join(NICK_CHAR.findall(text))
        if cleaned != text:
            logger.warning('昵称里有游戏不接受的字符，已经去掉：%r → %r'
                           % (text, cleaned))
        if len(cleaned) < NICK_MIN or len(cleaned) > NICK_MAX:
            fallback = cls.random_nickname()
            logger.warning('昵称要 %d~%d 个字符（%r 现在 %d 个），改用随机名 %s'
                           % (NICK_MIN, NICK_MAX, cleaned, len(cleaned), fallback))
            return fallback
        return cleaned

    def text_for(self, button):
        """这个按钮要不要打字、打什么。

        ❗昵称是**实例级**的：GUI 里可以自定义，留空才随机；节点1 要
        「点到输入框但先别输」，这时返回 None。
        """
        if button is E_60_2:
            return self.nickname if self.input_enabled else None
        return TEXT_INPUT.get(button)

    def type_content(self, button, content):
        """把字打进刚点开的输入框。昵称走「分片 + 回读」，其它仍是整串发。

        ❗一次发整串会**丢掉开头几个字符**。真机 2026-11-07 19:09：
          昵称 `Savior7458` 进框只剩 `ior7458`（前 3 个字符被吞），名字变成
          7 位，游戏「确认」被连点 10 次都不前进，最后 `GameTooManyClickError`
          把游戏判成卡死、重启 —— 而日志里写的是「已输入 Savior7458」。
          **发送成功 ≠ 进框成功**，所以必须回读。
        """
        if button is not E_60_2:
            self.device.adb_shell(['input', 'text', content])
            logger.info('%s 已输入 %s' % (button.name, content))
            return True
        return self.type_nickname(content)

    def type_nickname(self, nickname):
        """昵称分片输入 + OCR 回读，对不上就清空重输（最多 2 次）。

        分片是因为丢字只发生在整串的最前面（输入法还没就绪）：每片 3 个字符、
        片间留 0.15s，比一次发整串稳得多。回读用 `ocr.read_nick`。

        ❗回读只是**辅助**判据，最终看游戏自己：框里有字「确认」(`E_61_1`) 才
          点亮（空框时是灰的，真机 2026-11-06 23:12）。2026-11-08 14:55 框里
          明明是完整的 `2Jf33vvm7j`，cnocr 读成 `283wmizj`（8 位），脚本据此
          判失败、在点「确认」之前自己中止了 —— 用户：「实际成功输入了，但是
          没有点确认。」
        """
        seen = ''
        for attempt in (1, 2):
            # ❗**每次都要先清空**，包括第一次：从中断的画面接着跑时，框里可能
            #   还留着上一轮被游戏拒掉的名字（真机 2026-11-07 23:30 框里是
            #   `Savior8374`，提示「包含无法使用的字。」），不清空就会拼成
            #   `Savior8374Xk7mQ2p`，照样过不了。
            self.clear_nick_input()
            for i in range(0, len(nickname), 3):
                self.device.adb_shell(['input', 'text', nickname[i:i + 3]])
                # 这不是在等画面，是在等输入法把这一片送进框：框里只在整串
                # 输完后才有可读的字，中途没有可以 appear 的判据。
                time.sleep(0.15)  # alas-lint: allow - IME 分片节奏，屏幕上没有可等的状态
            seen = read_nick(self.device.screenshot())
            if self.nick_typed_ok(seen, nickname):
                logger.info('昵称已输入 %s' % nickname)
                return True
            logger.warning('昵称回读不一致：要 %r，框里读出来是 %r（第 %d 次）'
                           % (nickname, seen, attempt))
            # 框里明明有字、游戏也把「确认」点亮了，就别因为 OCR 认不准清空重输。
            if seen and self.wait_until_appear(E_61_1, offset=CHAIN_OFFSET, timeout=2):
                logger.info('昵称 %r 回读为 %r（OCR 不准），但「确认」已点亮，按已输入继续'
                            % (nickname, seen))
                return True
        # 不再死点确认键：那只会连点到 GameTooManyClickError，还要多花十分钟重走引导
        raise ScriptError('昵称输不进去：要 %r，两次都没进框' % nickname)

    def clear_nick_input(self):
        """清空昵称框：点一下框内 → 光标移到末尾 → 连按退格。"""
        self.tap_at(640, 385, '昵称框（清空重输）')
        self.device.adb_shell(['input', 'keyevent', 'KEYCODE_MOVE_END'])
        self.device.adb_shell(['input', 'keyevent'] + ['KEYCODE_DEL'] * 24)
        time.sleep(0.3)

    @staticmethod
    def nick_typed_ok(seen, want):
        """昵称进框了吗 —— **只比长度**，不比字符。

        ❗cnocr 认字母数字混排非常不准。真机 2026-11-07 23:35：框里明明是
          `C4y8S6k8nc`，OCR 读出 `Cayestkisnc`（10 位变 11 位，数字全认成字母），
          逐字比对只有 4 个对得上，判「输入不完整」→ 白白清空重输两次。
          而**丢字的特征是长度明显变短**（`Savior7458` 只进去 `ior7458`，
          少 3 个字符），所以比长度就够用，还不会被 OCR 的错字干扰。
          容差 1：OCR 偶尔多读/少读一个字符。
        """
        a = ''.join((seen or '').split())
        b = ''.join((want or '').split())
        if not a or not b:
            return False
        return abs(len(a) - len(b)) <= 1

    def report_plan(self, reason):
        """工具跑完的收尾小结：让日志自己说明停在哪、为什么。"""
        logger.hr('刷初始结束：%s' % reason, level=1)
        logger.info('昵称：%s' % self.nickname)
        if self.targets:
            logger.info('目标：%s → %s'
                        % (' / '.join('%s × %d 只' % (row['label'], row['count'])
                                      for row in self.targets),
                           '已达成' if self.target_hit else '未达成'))
            logger.info('达标条件：%s'
                        % ('任意一个角色凑够' if self.target_mode == TARGET_MODE_ANY
                           else '挂上的全都要凑够'))
        else:
            logger.info('目标：不指定（只跑一轮）')
        logger.info('账号：%s' % ('已留在游戏里，没有重置' if not self.targets or self.target_hit
                                 else '见上一段日志'))

    def notify_round(self, index):
        """每轮验号后推一条结果，**复用「错误推送」那份设置**。

        ❗不另加配置项：读 `Error.OnePushConfig`（`config/alas.json` 里
          `Error` 组那段 onepush YAML，本地推送 / webhook / telegram 都行），
          填什么就发什么。

        ❗每轮都发（达标 / 未达标 / 没读到 SSR），发完立刻继续下一轮，不等
          用户确认；目标达成、停节点、刷满次数仍由 `run()` 决定停不停。
          没配 / 发失败都只记一条日志，绝不影响刷初始本身。
        """
        data, conf = load_onepush_conf(getattr(self.config, 'Error_OnePushConfig', ''))
        provider = data.get('provider')
        if not provider or str(provider).strip().lower() in ('null', 'none'):
            logger.info('推送：Error.OnePushConfig 没配 provider，跳过')
            return False

        detail = self.target_detail or ()
        chars = self.format_scan_characters(self.last_scan or ())
        if self.target_hit:
            status = '目标达成'
            ending = '账号留在游戏里，没有重置。'
        elif self.stop_at == STOP_VERIFY:
            status = '验号完成（停节点）'
            ending = '已按停节点停下，没有重置。'
        elif not self.targets:
            status = '仅记录（未设置目标）'
            ending = '未设置目标，这一轮结束。'
        elif self.reroll_count and index >= self.reroll_count:
            status = '未达成（已刷满 %d 轮）' % self.reroll_count
            ending = '已刷满设定轮数，停下，不重置。'
        else:
            status = '未达成'
            ending = '继续下一轮。'

        # ❗标题和正文都必须带 `AlGS`：钉钉连接器的 flow 里挂了关键词过滤
        #   （`trigger_filter_break: flow input not contain keywords`），
        #   输入里不出现关键词就直接 break，钉钉侧表现为「没收到消息」，
        #   而 HTTP 照样 200，`handle_notify` 也照样记 success —— 完全看不出来。
        lines = ['AlGS 刷初始：第 %d 轮，%s。' % (index, status),
                 '昵称：%s' % self.nickname]
        if self.targets:
            target_note = ' / '.join('%s × %d 只' % (row['label'], row['count'])
                                     for row in self.targets)
            lines.append('目标：%s → %s'
                         % (target_note, '已达成' if self.target_hit else '未达成'))
            if detail:
                for row in detail:
                    lines.append('  %s：%d/%d 只%s'
                                 % (row['label'], row['got'], row['need'],
                                    '' if row['hit'] else '（还没够）'))
            else:
                lines.append('目标进度：本轮没读到 SSR')
        else:
            lines.append('目标：未设置（只做记录）')

        if chars:
            lines.append('本轮 SSR（%d 种）：' % len(chars))
            lines.extend('  ' + char for char in chars)
        else:
            lines.append('本轮 SSR：没读到')
        lines.append(ending)

        content = '\n'.join(lines)
        title = 'AlGS 刷初始：第 %d 轮 %s' % (index, status)
        try:
            from module.notify import handle_notify
            ok = handle_notify(conf, title=title, content=content)
        except Exception as e:
            logger.warning('推送失败：%s' % e)
            return False
        if ok:
            logger.info('推送：已发出（%s）' % title)
        else:
            logger.warning('推送：没发出去，检查 Error.OnePushConfig')
        return ok

    def fail_reason(self, reason):
        """失败原因 + 昵称 + 目标进度，交给 `GameScheduler.run()` 推送。

        ❗工具自己**不推**：`run()` 的「失败就 return」不是异常，兜底捕获不到
          （2026-11-08 01:11 重置失败那轮就是这样，手机静默）。走 `TaskFailed`
          抛出去，调度器那边统一推一条、并把这次运行记成失败。
        """
        detail = reason + '\n昵称：%s' % self.nickname
        if self.targets:
            detail += '\n目标：%s → %s' % (
                ' / '.join('%s × %d 只' % (row['label'], row['count'])
                          for row in self.targets),
                '已达成' if self.target_hit else '未达成')
        return detail

    def press(self, buttons, note, timeout=300, idle=12, once=False, dialogue=False,
              frames=False, speed=False, skip=True, stop_on=(), stop_after_page=None,
              stop_after_button=(), hit_out=None, restore_after=None,
              stop_on_login=False, login_start_pending=False):
        """
        把一串按钮按顺序点完，直到连着 `idle` 秒什么都认不到。

        每一帧都从表头重新扫：命中的那个点掉，然后等它从画面上消失，再回到第一行。
        这样写的好处是不记"我走到第几步"—— 少识别一帧下一帧就补上，中途重进游戏
        也能从当前画面接回来。代价是每帧要扫一整个表，所以表不能太长（一段几十个
        按钮、offset=60 时一帧几十毫秒，截图本身才是瓶颈）。

        `wait_until_disappear` 超时不算失败：有些按钮点完是变灰而不是消失，
        原地等下去只会白等，下一帧重新判断更准。

        Args:
            buttons (tuple): 这一段要点的按钮，顺序即优先级。
            note (str): 日志标题。
            timeout (int): 整段最多花多少秒。
            idle (int): 连续多少秒没有可点的按钮就认为这一段结束。
            dialogue (bool): 允许"点画面推进对话"这条兜底。

                ❗**只有开场引导该给 True**。旅程 / 结算阶段的画面上也有 SKIP，
                但那是**关卡内的跳过键**，不是剧情。在那里点画面中央等于点到
                战场、训练场、结算面板上 —— 用户 2026-11-06 19:58：
                「我怕一直点中间，到后面的旅程也点中间是不行的。
                 如果只有白框的时候点中间还行。」
                昵称之后连引导本身也不许点了：用户 2026-11-06 20:17
                「昵称之后的引导都不要点中间」。

            frames (bool): 允许找「引导高亮框」并点它的中心（`highlight.find`）。

                ❗几何法在普通游戏画面上会误判（救援者列表页会给一个假框），
                所以只有引导那三段开，别的段一律关。

            stop_on (tuple): 看到这里面任意一个按钮就**立刻收工**，交给下一段
                （开场引导见到昵称框就走，不用干等 idle）。

            stop_after_page (int): 点掉这个页号的引导页之后**立刻收工**，不等 idle。

                ❗`page_168` 是「主界面上的 16 页后续引导」（153~168）的最后一页，
                点掉它的时候游戏**已经在主界面了**，再等 `idle` 只是空耗 40 秒
                （真机 2026-11-07 14:36~14:37 日志一路刷
                `page_168 之后 10s/20s/30s/40s 没有点掉新引导页`）。
                用户 14:4x：「168_1 后就在主页面了不用等 40s，直接下一步领奖励」。
                只在 settle 段用；`GUIDE_PAGES` 里 168 之后还有 185~192
                （救援者引导，属于 verify），所以这里比的是 `>=`，
                正常轮里 settle 走不到那些页。

            restore_after (float): 多少秒没有命中就恢复全表扫描（默认 `idle * 0.7`）。

                ❗只给「页少、节奏快」的段压短，比如救援者引导只有 8 页、
                一页约 1 秒，等 8 秒才能重扫一页都点不动，用户 16:2x：
                「不用8秒那么久」。长段别动它，重扫会把淘汰的旧页放回来。
                ❗`idle` 压得很小的段要**显式给这个值**：默认跟着 `idle` 缩，
                2 秒的 `idle` 会把重扫周期缩到 1.4 秒，51 页全表重扫得太勤。

            speed (bool): 顺手把倍速保持在 3x（`journey.py` 的 `ensure_speed`）。

                ❗倍速会**自己掉回 1x**：跳过新手教学、进新关卡都会重置。
                用户 2026-11-06 20:28：「到跳过新手教学这里倍数会回到 1 倍数，
                要重新点」。所以不是开头点一次就完事，得整段盯着。

            once (bool): 每个按钮**最多点一次**。

                ❗登录必须用它。标题页的「Touch to Start」在登录弹窗盖上来之后
                还留在背景里（弹窗是半透明的），`appear()` 照样匹配 —— 于是每帧
                又点一次，等于在登录页点"取消"，真机实测直接弹出「已取消登入。」
                （2026-11-06 19:32）。

            stop_on_login (bool): 引导段专用：每帧先判**标题页 / 登录弹窗**，
                命中就不点、把 `need_relogin` 置 True 并收工，交给
                `guide_press()` 重新登录。

                ❗非引导按钮（page_4 的 `E_4_2`、page_61 的 `E_61_1`）
                不在 `GUIDE_PAGES` 里，`guide_page()` 返回 None，**永不过期**；
                被踢回标题后它们每帧都会重新命中，继续点就是
                「Touch to Start → 登录失败 → 确认 → 标题」死循环。

            login_start_pending (bool): 允许再点一次 page_4 的 `E_4_2`
                （登录后「点一次进游戏」）。点掉并验证消失后自动关闭；
                之后同一段里再看到它，就是被踢回标题，不是引导页。

        Returns:
            bool: True 表示这一段自然结束，False 表示超时/中途需要重登。
        """
        logger.hr(note, level=2)
        quiet = Timer(idle).start()
        typed = set()
        done = set() if once else None
        advance = Timer(0.8)   # 剧情点击 / SKIP 的重试间隔
        skip_fail = 0          # 连续点了几次 SKIP 都没反应
        confirm = Timer(3)     # 「刚点过 SKIP」之后认确认框的窗口（未启动 = 不认）
        hit = [] if hit_out is None else hit_out   # 这一段点过的按钮名（按点击顺序，用来报页号；传 list 进来可以在段外查它点过什么）
        blocked = set()        # 点了不消失的按钮，本段不再点
        tries = {}             # 每个按钮点了几次（判断"是不是真点不动"）
        enter_tries = 0        # page_4「进游戏」点了几次还没看到游戏内画面
        # 评鉴战延迟对话：E_134_1 点掉后先等它出现，出现后逐句点掉再开 AUTO。
        battle_dialog_pending = False
        battle_dialog_seen = False
        battle_dialog_until = 0.0
        battle_dialog_click = 0.0
        # ❗点完且验证「消失」的按钮，2 秒内不再点：关闭动画的残帧还会被
        #   匹配上一帧（真机 2026-11-07 15:20 E_119_1 点完 0.3s 验证消失、
        #   0.2s 后又命中，多打一击被动画吞掉，还留下误导性的
        #   「第 2 次没点动」日志）。2 秒足够盖过残帧窗口；真要重弹的
        #   （第二个教学弹窗）隔着十几秒过场，不受影响。
        cooldown = {}          # button.name -> 冷却截止时刻
        # 引导页淘汰：见 guide_chain.py。只对标题「引导N」的 140 页生效，
        # 每点成功一页只淘汰它的紧邻前一页，不一次性禁用前面全部。
        expired = set()        # 已走过的引导页号
        # 长时间无命中就恢复全表扫描。默认按 idle 的 0.7 倍；短段（救援者引导
        # 只有 8 页、一页 1 秒）等 8 秒太久，用 `restore_after` 单独压短。
        restore_wait = idle * 0.7 if restore_after is None else restore_after
        no_hit = Timer(restore_wait).start()
        train_wait = Timer(2.5)  # 训练失败点完之后等多久再看（训练要跑一会儿）
        train_tries = 0        # 训练失败连点了几次
        # 引导页之间的识别时长（用户 2026-11-07：「记录每个引导之间的识别时长」，
        # 观察到 page_38 之后像停住了）。三个时刻：上一页点掉 -> 下一页首次被
        # appear 认到 -> 这一页点掉。段末汇总并落盘，方便多轮对照。
        guide_log = []         # 每段一条记录
        seen_at = {}           # button.name -> 本段本次首次识别到的时刻
        last_done = None       # (page, moment) 上一个点掉的引导页
        gap_reported = 0       # 已播报过的「等待下一页」秒数（10 秒一档）
        speed_low = 0          # 连续几次独立采样读到低倍速
        speed_hold = Timer(SPEED_HOLD)   # 采样节流，别把一帧抖动当掉档
        speed_clicks = 0       # 本段补档点过几下
        speed_fails = 0        # 点击没验收到预期档位的次数
        speed_reached = False  # 本段读到过 3x 没有（到过就别轻易再点）
        speed_ok = True        # 补档还允不允许点
        # ❗「跳过新手教学」(E_119_1) 会把倍速**打回 1x**（用户 2026-11-06 20:28）。
        #   真机 2026-11-07 04:42:20 点掉它之后 0.7 秒就点了训练 (E_122_1)，
        #   补档来不及（要连续 2 次独立采样），1x 下训练结算的对话不自动推进，
        #   整段卡在「训练成功!」那一屏。用户 04:5x 定的规矩：
        #   「跳过新手教学之后要先看三倍速，再点训练；且之后就不用再判断倍数
        #   有没有开了，避免关了倍数」。所以：
        #     speed_recheck=True  期间**只补档、不点训练**；
        #     确认到 3x（或 45 秒都没按钮）→ 关掉补档，本段再也不动倍速。
        speed_recheck = False  # 119_1 之后、训练之前的「必须先看到 3x」窗口
        # ❗这个兜底只管「倍速按钮一直不出现」（卡在别的页面），不管「按钮在、
        #   但档位还没上去」—— 后者只要采样到按钮就 reset，见下面补档分支。
        #   原来写 45 秒：真机 2026-11-07 14:45:28 第二次补档把 1x 点到 2x 之后，
        #   画面切进过场、39 秒没有倍速按钮，45 秒一到就去点训练，最终停在 2x。
        recheck_wait = Timer(120)
        speed_after = False    # 窗口是「因为看到 3x」关掉的 —— 下一次点训练才关补档
        # 登录后 page_4 的 E_4_2 还要点一次才进游戏；只允许这一次，
        # 点掉并验证消失后关闭。已经在游戏里（有 SKIP/四格）就不给这次机会。
        login_pending = login_start_pending and not self.in_game_screen()
        for _ in self.loop(timeout=timeout):
            # 剧情 / 加载 / 战斗 / 抽卡动画是游戏自己走完的过程，不该归看门狗管
            # （硬约束 152）：60 秒没点击就 stuck_record_check -> app_is_running()，
            # 而 starsavior 还挂在 alas.json 上（包名是 hazeworld），判"游戏没在跑"
            # 直接抛 GameNotRunningError，整段被掐断（真机 00:14 journey、00:31
            # gacha 各崩一次）。上限交给本循环自己的 Timer(timeout)。
            self.device.stuck_record_clear()
            # ===== 中途回到标题 / 登录页：立刻收工，交给 guide_press() =====
            # ❗不能只靠按钮表：标题页的 E_4_2 / E_1_1 会被当成引导页一直点，
            #   直到 GameTooManyClickError（2026-11-12 17:02 实测 14 次）。
            #   登录弹窗 E_3_1 / 账号列表 E_2_1 也不能点，交给 login()。
            if stop_on_login:
                if (self.appear(E_3_1, offset=CHAIN_OFFSET)
                        or self.appear(E_2_1, offset=CHAIN_OFFSET)):
                    logger.warning(f'{note}：出现登录 / 选账号弹窗，停止这一段，准备重新登录')
                    self.need_relogin = True
                    return False
                # pending 期间允许表去点 page_4 那一次；in_game_screen() 只在
                # 标题模板命中时才算，避免每帧多扫五张 SKIP 模板。
                if (not login_pending
                        and (self.appear(E_1_1, offset=CHAIN_OFFSET)
                             or self.appear(E_4_2, offset=CHAIN_OFFSET))
                        and not self.in_game_screen()):
                    logger.warning(f'{note}：回到标题页（Touch to Start），停止这一段，准备重新登录')
                    self.need_relogin = True
                    return False
            # 旅程的终点是评鉴战 VICTORY 页。它上面一个 JOURNEY 表里的按钮
            # 都没有，只有右下角「离开」(E_135_1，属 SETTLE 段)。以前靠
            # idle=40 秒自然收工，倍速补档又每 2 秒 reset 一次 quiet，
            # 于是整段卡在 VICTORY 上（真机 2026-11-07 02:41 连点 60 多次
            # E_116_1）。看见「离开」就正面收工，交给 settle() 去点。
            # ❗只有 speed 段认它：别的段 E_135_1 可能是别的蓝色按钮。
            # 离线 34 帧验证：三张 VICTORY 1.000，其余全 0.000。
            if speed and self.appear(E_135_1, offset=(10, 10)):
                logger.info(f'{note}：评鉴战 VICTORY，这一段结束')
                self.report_pages(note, buttons, hit)
                self.report_guide_timing(note, guide_log)
                return True
            # 卡在哪一页后面要能从日志直接读出来：每满 10 秒播报一次累计等待。
            # 某个引导页之后再也没有新页被点掉时，这里会一直往上加（38_1
            # 那种「停住」就是这种形状），比事后翻点击记录直观。
            if last_done is not None:
                waiting = time.time() - last_done[1]
                if waiting >= 10 and waiting >= gap_reported + 10:
                    gap_reported = int(waiting // 10) * 10
                    logger.info('%s：page_%d 之后 %.0fs 没有点掉新引导页'
                                % (note, last_done[0], waiting))
            # ===== 剧情 / 视频：三件事，按这个顺序判 =====
            #
            # ⓪ 「跳过视频」确认框。点了 SKIP 之后弹出来的，必须先按掉，
            #    否则剧情永远停在这一句 —— 用户 2026-11-06 20:13：
            #    「没有跳过，就会这样卡住」，配图就是这种画面。
            #
            #    判据是**零新增素材**的：弹窗一出来，右上角的 SKIP 就被遮罩压掉，
            #    真机实测 E_5_1 从 1.000 掉到 0.000；而那个蓝色「确认」按钮
            #    （E_200_2，和重置弹窗是同一个版式同一个位置）从 0.000 变 1.000。
            #    两张图一起验的：
            #        剧情视频中    SKIP 1.000 / 确认键 0.000
            #        跳过视频弹窗  SKIP 0.000 / 确认键 1.000
            #        列表页 / 主界面 两个都是 0.000（不会误判）
            #
            #    ❗但 E_200_2 是**通用**的蓝色确认键，旅程里「体力不足 → 是否购买」
            #      也是同一版式同一位置，无脑点下去会花钻石。所以只在
            #      「刚点过 SKIP 的 3 秒内」才认它 —— 那个确认框只可能是我自己点出来的。
            if not confirm.reached() and self.appear(E_200_2, offset=(10, 10)):
                self.click_button(E_200_2, '确认跳过视频')
                skip_fail = 0
                confirm.reset()     # 弹窗可能连开两层，窗口再续一次
                advance.reset()
                quiet.reset()
                self.device.click_record_clear()
                continue

            # 每帧只算一次，下面 ①② 都要用
            # SKIP 有三套版式，**同游戏不同页面的 SKIP 长得不一样**（用户 23:56：
            # 「这个游戏不严谨，不同 skip 的确位置不一样」），所以三张模板都要试：
            #   `E_5_1`  (1140,20,1265,70)  开场引导的剧情 SKIP
            #   `E_69_1` (1137,36,1200,55)  抽卡动画的 SKIP
            #   `E_202_1`/`E_202_2` (1178,38,1240,54)  昵称之后那段剧情的 SKIP
            #       —— 它挂在 `LOG / ⏭AUTO / ▶SKIP` 这条横栏里（白粗字 + 播放三角），
            #       和上面两张**都不互匹配**：真机 2026-11-06 23:45 在这屏量到
            #       E_5_1 = 0.000、E_69_1 = 0.000，而新素材自己 1.000。
            #       两张是同一条按钮的两个取样（昵称后的对话 / 之后的对话页），
            #       互相 0.988，留两张是防它换底色。
            skip_button = None
            if self.appear(E_5_1, offset=CHAIN_OFFSET):
                skip_button = E_5_1
            elif self.appear(E_69_1, offset=CHAIN_OFFSET):
                skip_button = E_69_1
            elif self.appear(E_202_1, offset=CHAIN_OFFSET):
                skip_button = E_202_1
            elif self.appear(E_202_2, offset=CHAIN_OFFSET):
                skip_button = E_202_2
            # ❗`E_115_1` 是「纯黑过场 + SKIP」那一帧的取样（旅程进场那一下）。
            #   它**过拟合**：离线四张画面实测 —— 自己那张 1.000，但剧情页只有
            #   0.761、E_202 横栏 0.753、E_5_1 那张 0.798，换个背景全部低于 0.85。
            #   反过来 `E_5_1` 是大裁框（带横栏底色），四张全在 0.898~1.000。
            #   所以排最后当**黑屏兜底**：黑过场里 E_5_1 已经掉到 0.898（勉强过），
            #   E_115_1 是 1.000，接得住；真机 2026-11-07 16:09 就是点完 SKIP 之后
            #   黑过场里 12 秒没人认它（GUIDE_B 表里没有、in_story 又不认）而空转。
            elif self.appear(E_115_1, offset=CHAIN_OFFSET):
                skip_button = E_115_1
            # ❗**不要再加"白字占比"那种兜底**。2026-11-06 23:22 试过一版：
            #   靠 (1170,30)-(1245,60) 的白像素判 SKIP，结果旅程页右上角
            #   有白色资源数字也满足，`in_story` 恒真 —— 一整段点了 26 次
            #   (1206,45)，把 ADB 点到 `ConnectionAbortedError`。
            #   要认新的 SKIP 样式就**补素材**（用户已确认走这条路，23:58 补了 E_202）。
            in_story = skip_button is not None
            in_battle = self.in_battle()
            # ❗1x 的评鉴战要打好几分钟（3x 实测 60~70 秒）。用户 2026-11-07 04:5x
            #   定了「训练之后不再判断倍数」，于是这一段可能整场都在 1x ——
            #   不能让 75 秒 idle 在战斗中途收工，否则 settle() 接不上 VICTORY 页。
            #   真机 04:49:53 就是这样：04:49:02 开打、04:49:53 段就结束了，
            #   VICTORY 页在之后才出来，`离开`(E_135_1) 也没人点。
            #   战斗是游戏自己走完的过程，不该算进 idle（硬约束 152），
            #   上限交给本循环自己的 timeout=600。
            if speed and in_battle:
                quiet.reset()

            # ⓪ 好评弹窗（E_204_1）：「团长！喜欢星之救援者吗？」整屏盖住，
            #    任何一段都认不出自己的按钮 —— 真机 2026-11-07 06:14 连着三轮
            #    全空转（开场引导 40 秒、昵称 12 秒、引导 12 秒都没东西可点，
            #    gacha 只跑 0.4 秒）。放最前面点「取消」，点完这一帧不再做别的
            #    判断：画面已经变了，等下一帧重新认。
            if self.close_review():
                quiet.reset()
                continue

            # ⓪ 见了就收工：`stop_on` 里的按钮是「下一段该接手」的信号
            #    （开场引导看到昵称框 → 立刻交给「昵称」段，别再干等 idle）。
            #
            # ❗**只在"干净"的画面上认**：有 SKIP 说明还在剧情里、有血条说明在
            #   战斗里，这两种画面上的小图标（右上角的 `→`、播放三角之类）容易和
            #   别的页撞。真机 2026-11-07 引导段一共 51 页，误判一次就把后面
            #   几十页全漏掉，代价远大于省下的十几秒。
            for stop_button in stop_on:
                if in_story or in_battle:
                    continue
                if self.appear(stop_button, offset=CHAIN_OFFSET):
                    logger.info(f'{note}：看到 {stop_button.name}，这一段提前收工')
                    self.report_guide_timing(note, guide_log)
                    return True

            # ⓪ 训练失败：右上角弹三选一。能重试就重试，不能就休息。
            #    用户 2026-11-06 20:33：「训练会失败，我没有考虑到，你加上这个状态机吧」。
            #
            #    ❗**两个判据都要**：
            #      · 左上角「训练失败」标题（E_201_1）—— 光看那三行会被别的白色界面
            #        骗（评鉴战页 `live_j9` 三行的亮字占比 0.694/0.643/0.938，比真选项还高）；
            #      · 三行里有两行有字（标题在选项消失后还留一会儿，光看标题会反复触发）。
            #
            #    ❗点一次要等 `TRAIN_WAIT`，不能每帧点：训练要跑一会儿，这期间
            #      对话框不动，每帧点就会连点几十次（真机 20:38 连点了 100 次）。
            if speed and self.appear(E_201_1, offset=(10, 10)) and train_wait.reached():
                if self.handle_train_fail():
                    train_wait.reset()
                    train_tries += 1
                    quiet.reset()
                    self.device.click_record_clear()
                    if train_tries > 6:
                        logger.warning(f'{note}：训练失败点了 6 次还没过去，先停这一段')
                        return False
                    continue

            # ⓪ 倍速：只要看得到倍速按钮、又不是 3x，就补点一下。
            #    倍速会自己掉回 1x（跳过新手教学、进新关卡都重置），
            #    所以得整段盯着，不是开头点一次就完事。
            #    用户 2026-11-06 20:26：「到旅程了，这里最关键的是能不能点上 3 倍数」、
            #    20:28：「到跳过新手教学这里倍数会回到 1 倍数，要重新点」。
            #
            #    三道闸（和 journey.ensure_speed 同一套）：
            #      ① 连续两次**独立采样**（间隔 1 秒）都低档才点，单帧抖动不算；
            #      ② 点完只认「换到预期下一档」且连续两帧成立，验不到就按
            #         节流重新读，不立刻补点（硬约束 153）；
            #      ③ 到过 3x 就软封（要连续 4 次采样低档才解封）—— 3x 再点
            #         一下会绕回 1x，1x 下对话不自动推进（用户 02:19）。
            #    另有 `journey.SPEED_STD` 纯色块门禁：战斗 / VICTORY 那块是纯暗，
            #    旧版把它读成 1x，02:41 在 VICTORY 上连点了 60 多次 E_116_1。
            if speed and speed_ok and speed_hold.reached():
                level = self.speed_level()
                speed_hold.reset()
                # ❗倍速按钮还在 = 还在这段旅程里，只是档位没上去。这时候不能
                #   因为「窗口总时长」到了就放弃补档：真机 2026-11-07 14:45:28
                #   第二次补档刚把 1x 点到 2x，画面就切进过场、39 秒没有按钮，
                #   45 秒窗口一到期就直接去点训练了，最终停在 2x。
                #   只有「一直看不到按钮」才允许倒计时走完（见 recheck_wait）。
                if speed_recheck and level != 0:
                    recheck_wait.reset()
                if level == 3:
                    speed_reached = True
                    if speed_recheck:
                        # 跳过新手教学之后的重新确认到位：关窗，但**补档先留着** ——
                        # 要等下一次「训练」真的点下去（=开始训练）才关，否则
                        # 真机 2026-11-07 05:15:36 那一轮：进入旅程后的第一次训练
                        # 就把补档关了，2 秒后 119_1 把倍速打回 1x，再没人补，
                        # 门禁永远挡着训练，最后点了「休息」(E_120_1)，整段空转到收工。
                        speed_recheck = False
                        speed_after = True
                        logger.info(f'{note}：跳过新手教学后倍速已回到 3x，可以点训练')
                if level in (1, 2):
                    speed_low += 1
                else:
                    speed_low = 0
                need_low = 4 if speed_reached else 2
                if speed_low >= need_low and speed_clicks < SPEED_PRESS_CLICKS:
                    expect = level % 3 + 1
                    self.click_button(E_116_1,
                                      '倍速补档 %d→%d' % (level, expect))
                    speed_clicks += 1
                    stable = 0
                    for _ in self.loop(timeout=2):
                        if self.speed_level() == expect:
                            stable += 1
                            if stable >= 2:
                                break
                        else:
                            stable = 0
                    else:
                        speed_fails += 1
                        logger.warning('%s：倍速 %d→%d 没验收到（第 %d 次）'
                                       % (note, level, expect, speed_fails))
                        # ❗不因为「连两次没验收」就永久关掉：过场里点击
                        #   会被吞（档位条还亮着 1x），而 story 一结束就
                        #   该补上了。真机 17:01 就是两下没验收 → 本段不再
                        #   补 → 训练门禁永远挡着 → 旅程整段空转。
                        #   改成连失败 5 次（约 20 秒）才放弃。
                        if speed_fails >= 5:
                            speed_ok = False
                            logger.warning(f'{note}：倍速补了 5 次都没验收，本段不再补')
                    speed_low = 0
                    advance.reset()
                    quiet.reset()
                    self.device.click_record_clear()
                    continue

            # ① 引导高亮框：**只有剧情 / 战斗画面里才找**。
            #    几何法在普通 UI（抽卡页、救援者列表、编成页）上会给假框，
            #    点下去就是乱点 —— 真机 2026-11-06 20:20 在「晨星观测」抽卡页
            #    连点了 7 次假框（(811,345) (711,182) (1003,323) …），
            #    每帧一个位置，全是画面里的角色和按钮。
            #    引导高亮框只会出现在演出里（教学战点敌人、剧情里点按钮），
            #    而演出一定有 SKIP（右上）或在战斗（顶部血条）。
            # ➀ **教学战里那个敌人圈**：位置固定 (725,375)，直接点（BATTLE_TARGET）。
            #    白圈内部是彩色敌人，highlight.find 的"白边框套暗内容"判据找不到它
            #    （真机 22:55 找到的是 BURST 按钮那种 UI 高光），所以保留固定坐标。
            #
            #    ❗但它**不能排在表扫描前面**：真机 2026-11-07 01:18 从 page_38 起，
            #    这个分支每 0.8 秒抢占一帧，GUIDE_A 的 38/39/40/41/42 说明文字页
            #    几乎轮不到匹配，整段看起来就是「38_1 开始停住了」。现在挪到
            #    `for button` 的 else 里：表里命中优先，全表都没认出来才点敌人。

            # ❗`(not skip or skip_fail)`：**有 SKIP 就先跳剧情，别去找几何框**。
            #    真机 2026-11-07 00:01 在昵称后那段剧情上（新素材 E_202_1 已命中、
            #    in_story=True），几何法却在 (795,156) 给了一个假框，连点 5 次
            #    才轮到 SKIP —— 正是用户 2026-11-06 20:20 骂过的「乱点假框」。
            #    留 `skip_fail` 这一口：SKIP 点不动时（纯文字对话），才轮到框去试。
            if frames and advance.reached() and in_story and (not skip or skip_fail):
                point = highlight.find(self.device.image)
                if point:
                    self.tap_at(point[0], point[1], '点高亮框')
                    advance.reset()
                    quiet.reset()
                    self.device.click_record_clear()
                    continue

            # ② 剧情：右上角有 SKIP 就点它，一下跳完整段。
            #    战斗里那个位置是 ⏸ 暂停、不是 SKIP，所以不会误点。
            #
            #    ❗以前这里是「点画面中央推进」—— 那是把视频当对话处理。
            #      视频是自动播的，点中央只是让它继续播，台词一句都不变，
            #      `quiet` 又每帧被 reset，于是一路点到 timeout 才退出，
            #      看起来就是「卡住」。真机 20:13 卡了整整一段。
            #
            #    SKIP 是**所有段都允许**的（跳视频不会误操作任何东西）。
            #    点中央则只有 `dialogue=True` 的段才做 ——
            #    用户 2026-11-06 20:17：「昵称之后的引导都不要点中间」。
            # ❗`skip=False` 的段**不点右上角的 SKIP**，直接点画面推进
            #   （用户 2026-11-06 23:17：「不点右上的跳过」）。
            #   某些剧情点一下 SKIP 会把整段跳掉、后面的引导对不上；
            #   点中央只是"下一句"，节奏跟手点一样。
            if in_story and not skip and dialogue and advance.reached():
                self.tap_at(640, 400, '点画面推进对话')
                advance.reset()
                quiet.reset()
                self.device.click_record_clear()
                continue

            if in_story and advance.reached():
                self.click_button(skip_button, '跳过')
                confirm.reset()      # 打开"认确认框"的窗口
                if self.wait_until_disappear(skip_button, offset=CHAIN_OFFSET, timeout=1.2, settle=1):
                    skip_fail = 0
                    quiet.reset()
                    self.device.click_record_clear()
                    continue

                # SKIP 点了没反应 = 这一屏跳不过去（纯文字对话那种）。
                skip_fail += 1
                advance.reset()
                if dialogue:
                    self.tap_at(640, 400, 'SKIP 无效，点画面推进对话')
                    skip_fail = 0
                    quiet.reset()
                    self.device.click_record_clear()
                    continue
                # 不许点中央的段：连点三次都没反应就别在这儿耗着了，
                # 把控制权交回给下一段（它可能认得这一屏）。
                if skip_fail >= 3:
                    logger.warning(f'{note}：SKIP 点了 3 次都没反应，这一段先跳过')
                    self.report_guide_timing(note, guide_log)
                    return False
                continue

            for button in buttons:
                if guide_page(button.name) in expired:
                    # 已经走过的引导页：连模板匹配都不做。非引导按钮
                    # guide_page() 返回 None，永远不会进这个集合。
                    continue
                if button.name in typed:
                    continue
                if done is not None and button.name in done:
                    continue
                if button.name in blocked:
                    continue
                if time.time() < cooldown.get(button.name, 0):
                    # 刚点掉、还在播关闭动画：残帧不算数，别在动画上浪费点击
                    continue
                if self.appear(button, offset=CHAIN_OFFSET):
                    # ❗AUTO 的时机门控：评鉴战说明链（page_127~134）没过完
                    #   之前，AUTO 按钮虽然可见，但点了会被吞。2026-11-12 22:04
                    #   就是 23 秒时先点了一次，说明页白字被白像素判据误判成
                    #   「自动战斗已开启」，按钮一封，等 32 秒真正进战斗后
                    #   又要重新解封、重新点。
                    # ❗不要用 `in_battle()` 当“引导结束”：用户 2026-11-07 03:42
                    #   确认过，进入战斗就有 BOSS 血条；引导本身延迟 1~2 秒才出现，
                    #   这段空窗和引导结束后的画面一样，血条分不出来。
                    #   这里以 `E_134_1`（说明链最后一步）为界，并且**只认右上
                    #   对话条**：空窗和结束画面一样，但中间一定出现过白框。
                    if button is E_134_2:
                        if 'E_134_1' not in hit:
                            continue
                        now = time.time()
                        if self.battle_dialog_visible(self.device.image):
                            # 对话还在：点正文推进，别碰 AUTO。这个游戏背景、
                            # 人物、准心都在动，不能靠整屏差异判断。
                            battle_dialog_seen = True
                            battle_dialog_pending = True
                            if now - battle_dialog_click >= 0.8:
                                self.tap_at(BATTLE_DIALOG_CLICK[0], BATTLE_DIALOG_CLICK[1],
                                            '点击评鉴战引导对话')
                                battle_dialog_click = now
                            continue
                        if battle_dialog_pending:
                            if battle_dialog_seen:
                                battle_dialog_pending = False
                                logger.info('%s：评鉴战引导对话已结束，可以点 AUTO'
                                            % button.name)
                            elif now < battle_dialog_until:
                                # 空窗期：延迟对话可能还没出现，先不点 AUTO。
                                continue
                            else:
                                battle_dialog_pending = False
                        # 已经开着就别再点（再点一次会关掉）；封掉本段。
                        # 这里的白像素判据只在战斗内使用，对话框可见时
                        # auto_battle_started() 会直接返回 False。
                        if self.auto_battle_started(self.device.image):
                            blocked.add(button.name)
                            logger.info('%s：自动战斗已开启，本段不再点' % button.name)
                            continue
                    # ❗跳过新手教学之后必须**先重新看到 3x 才点训练**：1x 下训练
                    #   结算的对话不自动推进，真机 2026-11-07 04:42:22 就是
                    #   119_1 点完 0.7 秒就点训练，然后卡在「训练成功!」那一屏。
                    #   窗口有 45 秒兜底，不让某一段因为倍速按钮不出现而死等。
                    if speed and speed_recheck and button in (E_122_1, E_120_1):
                        if not recheck_wait.reached():
                            continue
                        logger.warning('%s：%d 秒没见到倍速按钮，放弃等 3x，放开训练/休息'
                                       % (note, recheck_wait.limit))
                        speed_recheck = False
                    now = time.time()
                    if button.name not in seen_at:
                        seen_at[button.name] = now
                    page = guide_page(button.name)
                    # ❗这里必须用 button **对象** 查表，不能用 button.name。
                    #   两个表的 key 都是 Button 实例，而 name 是文件名 `E_2_1`，
                    #   拿字符串去查永远 miss —— 于是 CLICK_TARGET 和 TEXT_INPUT
                    #   都成了摆设：账号行没被点、"添加其他账号"被点、昵称从来没打进去。
                    target = CLICK_TARGET.get(button, button)
                    # 教学战 page_23 的提示文字只当判据，按钮在右下角。
                    if in_battle and button is E_23_1:
                        target = BATTLE_SKILL
                    content = self.text_for(button)

                    # 「进游戏」最多点 3 次；不管按钮消没消失都计数，
                    # 防止标题页反复回来时无限点。
                    if button in (E_1_1, E_4_2) and login_pending:
                        enter_tries += 1
                        if enter_tries > 3:
                            logger.warning(
                                'Touch to Start 连点 3 次还没进游戏，交给重新登录')
                            self.need_relogin = True
                            return False

                    self.click_count = getattr(self, 'click_count', 0) + 1
                    logger.info('第 %d 次点击：%s（%s）'
                                % (self.click_count, button.name, note))
                    hit.append(button.name)
                    tries[button.name] = tries.get(button.name, 0) + 1
                    # 跳过新手教学会把倍速打回 1x：清掉「已到过 3x」的软闸、
                    # 立刻解封采样，并打开「先看 3x 再点训练」的窗口。
                    if speed and button is E_119_1:
                        speed_reached = False
                        speed_low = 0
                        speed_hold.reset()
                        speed_recheck = True
                        speed_after = False
                        recheck_wait.reset()
                        logger.info(f'{note}：跳过新手教学，等倍速回到 3x 再点训练')
                    # 训练**真的开始了**（119_1 之后、3x 已确认的那一次）才关补档
                    # —— 进入旅程后第一次点训练只是进训练场，倍速还得继续盯
                    # （真机 05:15:36 那一轮就是在那一下关早了）。
                    if speed and button is E_122_1 and speed_after:
                        speed_after = False
                        speed_ok = False
                        logger.info(f'{note}：训练已开始，本段不再补档')

                    # ❗**不用 `device.click(target)`**：它在 `button` 矩形里
                    # **随机取点**，而 spec 框出来的矩形经常比按钮本身大一圈
                    # （把上面的下拉箭头、旁边的装饰都框进去），于是有一半
                    # 点在按钮边缘甚至外面 —— 用户 2026-11-06 21:14
                    # 「page_165 点到边缘了」、21:15「page_168 点到边缘了」、
                    # 以及那句「不能所有的都点中间吗？」。
                    # 统一点 area 的中心：框多歪，落点都在中间。
                    cx = (target.area[0] + target.area[2]) // 2
                    cy = (target.area[1] + target.area[3]) // 2
                    # ❗同一个点连点 5 次都没反应的按钮，**换个落点**再点。
                    #   游戏会吞掉正中那一下（真机 2026-11-07 13:10 的
                    #   `E_139_1`：161~165 次点击全打在中心，结算卡住不动，
                    #   后面领奖 / 抽卡 / 验号全废）。用户 13:1x：
                    #   「做点击偏移，点了确认后，再点一下框内」。
                    retry = tries.get(button.name, 1)
                    if button in RETRY_AT:
                        # ❗点列**只在确认键点不动之后**才用：`E_139_1` 是蓝色
                        #   「确认」，它同时出现在「最终旅程结果」和「获得全新
                        #   祝福」两屏 —— 结果屏点确认就能过；祝福屏点确认没
                        #   反应（游戏 bug）才要点祝福横条右侧的空白。用户
                        #   16:15：「优先级应该是点下面那个确认，当点确认没用
                        #   （游戏bug）才去点偏移，现在一直点偏移本不会过结算」。
                        #   所以第 1 次永远点 area 中心（确认本体），第 2 次起
                        #   才走点列。
                        if retry >= 2:
                            points = RETRY_AT[button]
                            cx, cy = points[(retry - 2) % len(points)]
                            logger.info('%s：第 %d 次点击，落点 (%d, %d)'
                                        % (button.name, retry, cx, cy))
                    elif retry >= 2:
                        # 其它按钮仍然是「点不动才换点」：游戏会吞掉正中那一下
                        # （真机 2026-11-07 13:10，`E_139_1` 连点 12 次全打在中心）。
                        cx, cy = self.retry_point(target.area, retry)
                        logger.info('%s：第 %d 次没点动，换框内另一点 (%d, %d)'
                                    % (button.name, retry, cx, cy))
                    # E_208_1 的 area 是标题，点击点必须落到下面的蓝色确认；
                    # 覆盖上面的重试点，标题命中后每次都点同一个确认位置。
                    if button is E_208_1:
                        cx, cy = RESULT_CONFIRM
                    self.device.click(Button(  # alas-lint: allow - 只把落点钉到 area 内某个点，没有 file、不进 appear 家族；判据仍然是上面那条 appear
                        area=(cx - 2, cy - 2, cx + 2, cy + 2),
                        color=(0, 0, 0),
                        button=(cx - 2, cy - 2, cx + 2, cy + 2),
                        name=button.name,
                    ))
                    if done is not None:
                        done.add(button.name)
                    if content:
                        # 点一下只是聚焦，字还得真的打进去；打完不许再打，
                        # 否则下一帧又命中同一个输入框，变成 xxx xxxxxx。
                        #
                        # ❗**点完不能立刻发字**：焦点还没落上、键盘还在弹，
                        #   这一枪 `input text` 会全丢（真机 2026-11-06 23:12
                        #   昵称页就是这么丢的 —— 输入框一直空着，确认键一直是灰的，
                        #   最后报「昵称：表里有但没点到 → [61]」）。
                        #   等下半屏稳定（键盘弹出动画结束）再发。
                        #
                        # ❗等静止**还不够**：19:09 那一轮等到了静止，整串发出去
                        #   仍然被吞掉开头 3 个字符（`Savior7458` → `ior7458`），
                        #   昵称短了、确认键永远点不动。真正的判据是**回读框里的字**，
                        #   见 `type_content` / `type_nickname`。
                        self.wait_until_still((0, 300, 1280, 720), timeout=2, threshold=3.0)
                        self.type_content(button, content)
                        typed.add(button.name)
                    quiet.reset()
                    no_hit.reset()
                    # 每次点击都记一条「点了多久、按钮消没消失」——
                    # 用户 2026-11-06 21:30：「每次都做记录，这才能知道哪里出了问题」。
                    click_at = time.time()
                    # ❗`E_115_1` 是旅程开场剧情右上角的 SKIP（和倍速按钮同一横栏），
                    #   但它**不在** `in_story` 认的那三套 SKIP 模板里，是从表里
                    #   点掉的 —— 表内点击不会自动开「认确认框」的窗口。点完它
                    #   会弹「是否跳过」确认框把 SKIP 盖住，窗口没开的话确认框
                    #   （E_200_2）没人按，剧情就没跳掉、SKIP 也认不到了
                    #   （真机 2026-11-07 15:5x：115_1 只点了一次，没完全跳过）。
                    #   和 in_story 分支同一个安全前提：确认框只可能是我自己点出来的。
                    if button is E_115_1:
                        confirm.reset()
                    if button is E_134_1:
                        # 说明链最后一步点下去就开始等；真正开打后右上会
                        # 延迟 1~2 秒弹对话条，AUTO 必须等它走完。
                        battle_dialog_pending = True
                        battle_dialog_seen = False
                        battle_dialog_until = click_at + BATTLE_DIALOG_GRACE
                        battle_dialog_click = 0.0
                    if button is E_134_2:
                        vanished = self.wait_auto_battle_start(timeout=6)
                    else:
                        vanished = self.wait_until_disappear(
                            button, offset=CHAIN_OFFSET, timeout=3, settle=2)
                    # page_4 的「进游戏」不能只看按钮消失：读条会短暂盖住它，
                    # 0.2 秒后消失、1 秒后标题又回来，实际没进去（2026-11-12 17:42）。
                    # 只认 in_game_screen() 的正面判据；标题回来就保持 pending，
                    # 冷却 2 秒后再点一次；3 次都进不去才交给 guide_press() 重登。
                    if button in (E_1_1, E_4_2) and vanished and login_pending:
                        if self.wait_enter_game(timeout=30):
                            login_pending = False
                            enter_tries = 0
                            logger.info('Touch to Start 点完，确认已进入游戏')
                        else:
                            logger.warning(
                                'Touch to Start 点完没进游戏（标题又回来了），'
                                '已点 %d/3 次，交给 guide_press 重登' % enter_tries)
                            # ❗不能只记一条日志就继续空转：2026-11-13 10:25
                            #   点完 Touch to Start 等了 30 秒还在标题，press
                            #   把这次当成“点过”收工，后面昵称/引导全是空表，
                            #   最后直接跳进旅程。必须立刻把控制权交给
                            #   guide_press() 重登，再重扫当前画面。
                            self.need_relogin = True
                            return False
                    done_at = time.time()
                    if button is E_134_2:
                        logger.info('%s 点完 %.1fs 后自动战斗%s'
                                    % (button.name, done_at - click_at,
                                       '已开启' if vanished else '还没开'))
                        if vanished:
                            # 开关按钮开了一次就封掉，下帧别把它关回去。
                            blocked.add(button.name)
                            # ❗下一场战斗的第一次点击必须回到 area 中心。
                            #   否则 `tries` 会把上一场的重试次数带进来，
                            #   新一场第一下就落到偏移点，2026-11-12 21:53
                            #   因此连吃两次 6 秒超时（第 2/3 次才点动）。
                            tries.pop(button.name, None)
                    else:
                        logger.info('%s 点完 %.1fs 后%s'
                                    % (button.name, done_at - click_at,
                                       '消失了' if vanished else '还在'))
                        if vanished:
                            cooldown[button.name] = time.time() + 2
                            # ❗点掉过一次就把重试计数清零：`tries` 只该数
                            #   「连着几次点不动」，不能把同一段里前面点过的
                            #   次数带进下一次出现 —— 真机 16:32 的 `E_139_1`
                            #   前两次点掉了，第三次一出现就按 retry=3 直接走
                            #   偏移点列，其实点中心就能过（用户：「这里应该
                            #   没有bug，有办法让它不调用偏移吗？」）。
                            tries.pop(button.name, None)
                    if page is not None:
                        wait = None
                        if last_done is not None:
                            wait = max(0.0, seen_at.get(button.name, now) - last_done[1])
                        entry = {
                            'note': note,
                            'name': button.name,
                            'page': page,
                            'prev': last_done[0] if last_done else None,
                            'wait': round(wait, 2) if wait is not None else None,
                            'recognize': round(click_at - seen_at.get(button.name, now), 2),
                            'click': round(done_at - click_at, 2),
                            'vanished': bool(vanished),
                        }
                        guide_log.append(entry)
                        logger.info('引导计时 page_%s → page_%d：等待 %s / 识别 %.2fs / 点掉 %.2fs'
                                    % (entry['prev'] if last_done else '-', page,
                                       ('%.2fs' % wait) if wait is not None else '-',
                                       entry['recognize'], entry['click']))
                        if vanished:
                            last_done = (page, done_at)
                            gap_reported = 0
                            seen_at.pop(button.name, None)
                            # ❗最后一页引导点掉 = 游戏已经回主界面了，不用再干等 idle。
                            #   168 之后没有任何引导页可点，`idle=40` 只会白等 40 秒
                            #   （真机 2026-11-07 14:36:37~14:37:07 一路播报
                            #   「page_168 之后 10s/20s/30s/40s 没有点掉新引导页」）。
                            if stop_after_page and page >= stop_after_page:
                                logger.info('%s：page_%d 点掉，已经在主界面，这一段收工'
                                            % (note, page))
                                self.report_pages(note, buttons, hit)
                                self.report_guide_timing(note, guide_log)
                                return True
                    # 引导页**点成功**（按钮真的消失）才淘汰紧邻的前一页。
                    # ❗不用「识别到就淘汰」：TM_CCOEFF_NORMED 只比结构不比颜色，
                    #    单帧误命中若直接推进游标，会把中间没点到的页全锁死且不可逆。
                    #    只淘汰一页 + 真实点击判据，误判的爆炸半径最多 1 页。
                    if vanished:
                        page = guide_page(button.name)
                        # ❗`E_134_2` 是自动战斗**开关**，任何时刻都可能被点到，
                        #   它不代表「说明链走到 page_134 了」。拿它去淘汰 page_133
                        #   会把还没点过的 `E_133_1` 关进 expired，之后要等
                        #   `no_hit`（idle*0.7 = 52.5 秒）恢复全表扫描才补上 ——
                        #   真机 2026-11-07 04:47:31 点了 AUTO，04:48:46 才轮到
                        #   E_133_1，正好卡了 51.47 秒（用户：「133_1 好像识别不到，
                        #   卡了半天才到下一个引导」）。开关不算一步，跳过淘汰。
                        prev = None if button is E_134_2 else previous_guide_page(page)
                        if prev is not None and prev not in expired:
                            expired.add(prev)
                            logger.info('引导 page_%d 已过，淘汰 page_%d' % (page, prev))
                        # 评鉴战说明最后一步（page_134）点掉 = 真正开打在即。
                        # 之前 AUTO 若在说明阶段被白字骗成「已开启」而封禁，
                        # 这里要放开一次，让它在正确时机补上（真机 03:39:39）。
                        if button is E_134_1:
                            if E_134_2.name in blocked:
                                blocked.discard(E_134_2.name)
                                logger.info('%s：评鉴战说明已过，解除对 %s 的封禁'
                                            % (note, E_134_2.name))
                    # 见了就正面收工：`stop_after_button` 里的按钮点掉且验证
                    # 消失后，这一段的使命就完成了，不用等 idle。
                    # ❗专为 settle 第二遍：它的任务只剩「接住 168 之后弹出的
                    #   第二个跳过新手教学」，点掉就该把控制权交给领奖——
                    #   它到不了 168，stop_after_page 永远不触发，干等 idle=40
                    #   只会白等 40 秒（真机 2026-11-07 15:20:34~15:21:14）。
                    if vanished and button in stop_after_button:
                        logger.info('%s：%s 点掉，这一段正面收工' % (note, button.name))
                        self.report_pages(note, buttons, hit)
                        self.report_guide_timing(note, guide_log)
                        return True
                    if not vanished:
                        # 点了它还在，有两种可能：
                        #   ① 常驻元素 —— 「选择旅程」那屏的 E_84_1 是左下角的
                        #      旅程卡片 (44,624,228,685)，点它只是"选中"，
                        #      画面不变（真机 2026-11-06 20:23 连点了 3 次，
                        #      真正的「开始」E_85_1 一直轮不到）；
                        #   ② **同一个位置会连着弹下一个一样的窗** ——
                        #      「跳过新手教学」有旅程版和作战版两个，点掉一个
                        #      立刻又露出另一个（用户 2026-11-06 21:18：
                        #      「有两个，所以你得运行两次」）。
                        # 所以给 4 次机会再判死（正好把 `retry_point()` 的
                        # 4 个备用点走一遍），不能一次就封。
                        if tries.get(button.name, 0) >= 4:
                            blocked.add(button.name)
                            logger.info('%s 点了 %d 次还在，本段不再点它'
                                        % (button.name, tries[button.name]))
                    break
            else:
                # 表里一个都没命中，战斗画面里才退一步点敌人圈推进（见上面 ➀）。
                # 每次都先判 in_battle + advance 节流，不是无脑连点。
                if frames and in_battle and advance.reached():
                    point = highlight.find(self.device.image)
                    if point is not None and any(
                            x1 <= point[0] <= x2 and y1 <= point[1] <= y2
                            for x1, y1, x2, y2 in BATTLE_RING_AREAS):
                        self.tap_at(point[0], point[1], '教学战：点白圈')
                    else:
                        self.tap_at(BATTLE_TARGET[0], BATTLE_TARGET[1], '教学战：点敌人')
                    advance.reset()
                    quiet.reset()
                    self.device.click_record_clear()
                    continue
                # 长时间没有任何可点元素：可能回到了旧引导页、或中途重进了游戏。
                # 恢复全表扫描一次，别让一段里累积的淘汰把整轮锁死。
                if expired and no_hit.reached():
                    logger.info('%s：%.0f 秒没有命中，恢复全表扫描（%d 页）'
                                % (note, restore_wait, len(expired)))
                    expired.clear()
                    no_hit.reset()
                if quiet.reached():
                    # idle 到期 ≠ 这段结束，但**只有在战斗中**才值得继续等：
                    # 战斗是自动打的（BOSS 血条自己掉），打的时候没有任何按钮可点，
                    # 画面却一直在动 —— 真机 2026-11-06 19:59：BOSS 还剩 5% 血，
                    # `journey` 就因为 12 秒没命中而放弃，把整场战斗丢了。
                    #
                    # ❗以前这里不看是不是战斗，任何画面「还在动」都继续等 ——
                    #    于是抽卡结果页那种有光效动画的 UI 会让 press 永远不结束，
                    #    真机 20:22 在「观测结果」页空转了整整 300 秒（用户看到的就是"卡住"）。
                    # ❗threshold 5.0 太钝：评鉴战里角色/特效只占战场一小块，
                    #   全区域平均差常常不到 5，被判成"画面静止" → 40 秒就收工。
                    #   真机 2026-11-07 03:51:53 就是这样提前 30 秒放弃，
                    #   VICTORY 到的时候 press 已经退出了。降到 2.0。
                    if in_battle and not self.wait_until_still(BATTLE_WATCH, timeout=2, threshold=2.0):
                        quiet.reset()
                        continue
                    logger.info(f'{note}：{idle} 秒没有可点的按钮，这一段结束')
                    self.report_pages(note, buttons, hit)
                    self.report_guide_timing(note, guide_log)
                    return True
        logger.warning(f'{note}：超过 {timeout} 秒还没走完')
        self.report_pages(note, buttons, hit)
        self.report_guide_timing(note, guide_log)
        return False

    @staticmethod
    def report_guide_timing(note, guide_log):
        """段末汇总每两个引导页之间的识别时长，并追加落盘。

        用户 2026-11-07 要「记录每个引导之间的识别时长」来定位 page_38
        之后的停顿。日志给最长的一段，逐页明细写进
        `config/state/starsavior_guide_timing.jsonl`，多轮可以对照。
        """
        if len(guide_log) == 0:
            return
        waits = [e['wait'] for e in guide_log if e['wait'] is not None]
        if waits:
            worst = max((e for e in guide_log if e['wait'] is not None),
                        key=lambda e: e['wait'])
            logger.info('%s：引导间隔 %d 段，平均 %.1fs，最长 page_%s → page_%d %.1fs'
                        % (note, len(waits), sum(waits) / len(waits),
                           worst['prev'], worst['page'], worst['wait']))
        path = os.path.join('config', 'state', 'starsavior_guide_timing.jsonl')
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            stamp = time.strftime('%Y-%m-%d %H:%M:%S')
            with open(path, 'a', encoding='utf-8') as f:
                for entry in guide_log:
                    row = dict(entry, time=stamp)
                    f.write(json.dumps(row, ensure_ascii=False) + '\n')
        except OSError as error:
            logger.warning('%s：引导计时落盘失败 %s' % (note, error))

    @staticmethod
    def report_pages(note, buttons, hit):
        """报出这一段点过的页号，以及表里有但没点到的页号。

        页号就是截图编号（`E_70_1` → 70），用户 2026-11-06 20:22：
        「中间有没有记录到的引导就是比点中间那个给吞了」——
        他要的就是这句：哪几页跳过去了。

        ❗missed 里的页不一定是 bug：有的页压根不会出现（同一个画面被框了两次），
          但连着的几个号一起缺，那就是真的漏了。
        """
        def num(name):
            parts = name.split('_')
            if len(parts) < 3 or parts[0] != 'E':
                return None
            try:
                return int(parts[1])
            except ValueError:
                return None

        got = [n for n in (num(x) for x in hit) if n is not None]
        if not got:
            logger.info(f'{note}：一个页面都没点到')
            return
        unique = sorted(set(got))
        logger.info(f'{note}：点过 {len(got)} 次，{len(unique)} 页 → {unique}')

        want = [n for n in (num(b.name) for b in buttons) if n is not None]
        missed = [n for n in want if n not in set(got)]
        if missed:
            logger.warning(f'{note}：表里有但没点到 → {missed}')

    # 冷启动/换号之后可能先看到的画面：标题页、登录弹窗、账号列表、
    # 主界面四格、开场引导第一屏。看到任意一个就说明游戏画出来了。
    START_SCREENS = (E_1_1, E_3_1, E_2_1, E_171_1, E_4_2, E_60_2)

    def dismiss_game_error(self):
        """点掉启动时偶发的「发生错误 (6 NEC_FAIL_RECONNECT_PRESENCE_NOT_FOUND)」弹窗。

        ❗真机 2026-11-07 14:5x：工具页点 Start 有概率弹一次（冷启动那一会儿
        连不上服务器），弹窗把标题页 / 「Sign in with Google」整块盖住，
        `wait_start_screen` 判不出就绪、`login()` 也点不到按钮。
        **点掉「确认」之后就能正常登录**（用户：「这个点掉后一般就能正常登录
        账号了」）。点完等它真的消失再返回，免得下一帧又读到自己。

        Returns:
            bool: 这一帧看到并点掉了，返回 True。
        """
        if self.appear(E_206_1, offset=(10, 10)):
            logger.info('登录：点掉「发生错误」（NEC_FAIL_RECONNECT_PRESENCE_NOT_FOUND）')
            self.click_button(E_206_2, '确认（开始游戏异常）')
            self.wait_until_disappear(E_206_1, offset=(10, 10), timeout=3)
            return True
        return False

    def dismiss_notice(self):
        """点掉「通知」弹窗：重置完回标题页时必弹一次「与服务器联机中断。」。

        ❗真机 2026-11-09 04:5x 抓的帧：一个白底弹窗，左上角「通知」标题，
        正文「与服务器联机中断。」，下面一颗蓝「确认」。点掉就能继续，
        不点的话它整块盖住「Touch to Start」，`wait_start_screen` 判不出
        就绪、`login()` 也点不到按钮。

        ❗判据是**两条正面条件**：`E_207_1`（那行「通知」标题，走**颜色**快筛）
        + `E_206_2`（那颗蓝「确认」，和「发生错误」弹窗是同一颗，模板实测 1.000）。
        只有标题没有蓝确认的（公告类通知）不点，交给上层继续等 ——
        宁可少点一次，也不要在认错的弹窗上瞎按。

        ❗`E_207_1` **不能用 `offset=(10, 10)`**（那是模板匹配）：它是白底黑字，
          模板块里大片纯色，`TM_CCOEFF_NORMED` 在标题页的蓝白天空上会算出
          1.0 的假阳性（2026-11-09 实测：n2 标题页 match=True，但直接算相似度
          只有 0.044）。用 `offset=0` 走颜色快筛：弹窗上该区域 (206,206,205)，
          标题页是 (175,192,243)，差 38 稳稳分开。
        """
        if self.appear(E_207_1, offset=0, threshold=10):
            if self.appear(E_206_2, offset=(10, 10)):
                logger.info('登录：点掉「通知」弹窗（与服务器联机中断）')
                self.click_button(E_206_2, '确认（通知）')
                self.wait_until_disappear(E_206_2, offset=(10, 10), timeout=5)
                return True
            logger.info('登录：看到「通知」弹窗但没有「确认」按钮，先不动')
        return False

    def wait_start_screen(self, timeout=180, settle=3):
        """等游戏真的画出画面再开工。

        ❗必须在 `login()` **之前**。`login()` 第 0 步的判据是「标题页和登录弹窗
        **都看不见** → 当作已登录」，这个判据在**加载画面**上永远成立，于是它
        立刻返回，`guide()` 再空转 40 秒，后面整条链都在加载画面上瞎点。

        真机 2026-11-07 12:43 撞过一次（工具页 `app_keptlive=false`，
        `switch_game()` 的 `app_start()` 先杀再启，冷启动到标题页要 60~90 秒）：
        昵称没输、引导一个都没点到、抽卡进不去观测、验号只读到 1 行。

        ❗要**连续 `settle` 帧**都看到才算就绪：`app_start()` 是"先杀再启"，
        刚启动那一两帧还是**上一个进程留下的标题页**，只判一帧就会在它被杀掉
        之后立刻"就绪"，紧接着 `login()` 在启动动画上误判成已登录
        （真机 12:52:32 实测：等了 0.0s 就"就绪"，下一行就是"不在标题页"）。
        """
        logger.hr('等游戏画面', level=2)
        # ❗`skip_first=False`：工具是 `AlGS.run(command, skip_first_screenshot=True)`
        #   进来的，进程刚起、一张截图都还没拍，`device.image` 是 None。
        #   默认的 `loop()` 会跳过首帧截图，第一下 `appear()` 就
        #   `AttributeError: 'NoneType' object has no attribute 'shape'`
        #   （真机 2026-11-07 13:52，工具页第一次点启动就撞上）。
        start = time.time()
        hits = 0
        for _ in self.loop(skip_first=False, timeout=timeout):
            # 游戏自己在加载，别让看门狗把正常等待判成卡死。
            self.device.stuck_record_clear()
            # 启动阶段偶发的「发生错误」弹窗：点掉再判，别让它把画面判成「没就绪」
            if self.dismiss_game_error():
                hits = 0
                continue
            # 重置完回标题页必弹一次「通知 / 与服务器联机中断。」，同样会盖住标题页
            if self.dismiss_notice():
                hits = 0
                continue
            found = False
            for button in self.START_SCREENS:
                if self.appear(button, offset=CHAIN_OFFSET):
                    found = True
                    break
            # 冷启动也可能不经标题页、直接恢复到教学战 / 旅程 / 剧情页
            # （2026-11-13 逐页强杀实测），只等 START_SCREENS 会白等 180 秒。
            if not found and (self.in_battle() or self.at_journey()
                              or any(self.appear(b, offset=CHAIN_OFFSET)
                                     for b in STORY_SKIP)):
                found = True
            hits = hits + 1 if found else 0
            if hits >= settle:
                logger.info('游戏已就绪（等了 %.1fs，连续 %d 帧）'
                            % (time.time() - start, hits))
                return True
        logger.warning('等了 %d 秒还没看到启动画面，直接往下走' % timeout)
        return False

    def login(self):
        """
        标题页 -> Sign in with Google -> 选已有账号。

        ❗这里**故意不用 `press()`**，一步一步走、每步等页面真的画完。
        原因是登录这几个页面全是"弹窗盖在背景上"，`appear()` 在背景上照样成立，
        每帧重扫就会反复点同一个位置，等于反复点"取消"：

            - 「Touch to Start」在登录弹窗背后一直可见 → 反复点它 →「已取消登入。」；
            - 账号列表刚滑出来就点账号行 → 点在还没铺开的地方 → 同样取消登入。

        用户 2026-11-06 19:34：「好像是点太快账号了，就取消了，调下速度看看」。
        所以每一步都 `settle=3`（连续三帧都看到才算到位，约 0.9 秒）。
        """
        self.device.screenshot()
        # 启动时那个「发生错误」弹窗会盖住整个登录页，先点掉再往下判
        self.dismiss_game_error()
        # 重置完回标题页那个「与服务器联机中断。」同理
        self.dismiss_notice()

        # 0. 已经在游戏里（引导 / 剧情 / 主界面）：标题页的「Touch to Start」根本不可见，
        #    这时再点它就是瞎点。直接认作已登录 —— `run()` 里下一段 `guide()` 会接住。
        #
        # ❗但**登录弹窗必须先认出来**：重置完回到标题页之后，游戏 0.5 秒内
        #   就会自动弹出「请选择登入方式」（Sign in with Google / Apple），
        #   它把「Touch to Start」整块盖住（实测 E_1_1 从 1.000 掉到 0.473，
        #   而 E_3_1 正好 1.000）。只判 E_1_1 就会误判成"已登录"，紧接着
        #   `guide()` 在弹窗上瞎点、整轮卡在选账号页 —— 真机 2026-11-07
        #   05:05:07 就是这样：「登录：不在标题页，当作已登录」→ 卡登录。
        on_login = (self.appear(E_3_1, offset=CHAIN_OFFSET)
                    or self.appear(E_2_1, offset=CHAIN_OFFSET))
        # ❗标题页可能只认得出 E_4_2、认不出 E_1_1（2026-11-12 17:02 被踢回
        #   标题时表里点的就是 E_4_2）。只判 E_1_1 会把标题页误判成「已登录」，
        #   紧接着 guide() 又把 E_4_2 当引导页点回登录循环。
        on_title = (self.appear(E_1_1, offset=CHAIN_OFFSET)
                    or self.appear(E_4_2, offset=CHAIN_OFFSET))
        if not on_login and not on_title:
            # ❗读条/转场会短暂把标题盖掉：不能只看“标题不见了”就判已登录
            #   （真机 2026-11-12 17:42：Touch to Start 消失 0.2 秒后又被读条
            #   盖住，1 秒后标题回来）。先等几秒，看到游戏内正面判据才算；
            #   标题/登录页回来就继续走登录。
            for _ in self.loop(timeout=3):
                if self.in_game_screen():
                    logger.info('登录：已在游戏内（正面判据）')
                    return True
                if (self.appear(E_3_1, offset=CHAIN_OFFSET)
                        or self.appear(E_2_1, offset=CHAIN_OFFSET)
                        or self.appear(E_1_1, offset=CHAIN_OFFSET)
                        or self.appear(E_4_2, offset=CHAIN_OFFSET)):
                    break
            else:
                logger.info('登录：不在标题页，当作已登录')
                return True

        # 1. 标题页 → 登录方式页。已经在登录/选账号页就别点「Touch to Start」，
        #    它在弹窗背后一直可见，点了等于取消（真机 19:32 / 19:33 各撞一次）。
        already = (self.appear(E_3_1, offset=CHAIN_OFFSET)
                   or self.appear(E_2_1, offset=CHAIN_OFFSET))
        if not already:  # alas-lint: allow - "已经过了标题页"才是要不要点的答案，且这一步不点任何东西
            # 两个模板是同一个位置的两个取样：重置后是 E_1_1，被踢回标题
            # 的现场是 E_4_2（2026-11-12 17:02）。哪个在就点哪个。
            if self.appear(E_4_2, offset=CHAIN_OFFSET):
                self.click_once(E_4_2, 'Touch to Start', offset=CHAIN_OFFSET, interval=3)
            else:
                self.click_once(E_1_1, 'Touch to Start', offset=CHAIN_OFFSET, interval=3)

        # 2. 还没到选账号页就先点 Google
        #
        # ❗账号仍在线时（闪退重进 / 没重置），点完「Touch to Start」会**直接进游戏**，
        #   根本不会弹 Google 登录页。只等 `E_3_1` 会白等 20 秒再 `return False`，
        #   `run()` 又在游戏内空转整条引导链 —— 真机 2026-11-10 07:31:14
        #   「登录：没等到 Sign in with Google」→ 开场引导/昵称/引导三段连着
        #   「一个页面都没点到」。
        #   所以这里等的其实是「登录弹窗出现」**或**「已经进游戏」，两条都是正面判据，
        #   并且都要连续 3 帧，别被转场帧骗过去。
        #   ❗❗「已经进游戏」不能只认主界面四格：账号在线时进的是**开场动画 / 剧情页**
        #   （右上 LOG / AUTO / SKIP 横栏），四格要等结算走完才出现。v1.42.1 只判
        #   `in_game()`，真机 2026-11-10 17:25 就这样把已登录的号判成
        #   「没等到 Sign in with Google」并整轮 `TaskFailed`。改用 `in_game_screen()`。
        #   ❗闪退重进还可能直接落到**旅程 HUD**（没有四格 / SKIP，只有顶部倍速），
        #   2026-11-12 20:53 因此白等 20 秒；`in_game_screen()` 现在也认旅程。
        if not self.appear(E_2_1, offset=CHAIN_OFFSET):  # alas-lint: allow - same as above, this branch only decides whether to click Google
            login_hits = 0
            in_game_hits = 0
            for _ in self.loop(timeout=20):
                # ❗点完 Touch 后服务器偶发「错误通知 (6 NEC_FAIL_RECONNECT_PRESENCE_NOT_FOUND)」，
                #   弹窗盖住 Google 登录页。2026-11-13 12:32 就是这里白等 20 秒后
                #   报「没等到 Sign in with Google」；启动入口的 dismiss 已经点过，
                #   但这一颗是在点 Touch 之后才弹的，循环里必须再判一次。
                if self.dismiss_game_error() or self.dismiss_notice():
                    login_hits = 0
                    in_game_hits = 0
                    continue
                login_hits = login_hits + 1 if self.appear(E_3_1, offset=CHAIN_OFFSET) else 0
                in_game_hits = in_game_hits + 1 if self.in_game_screen() else 0
                if login_hits >= 3:
                    self.click_button(E_3_1, 'Sign in with Google')
                    break
                if in_game_hits >= 3:
                    logger.info('登录：账号已在线，没有 Google 登录页，直接进游戏')
                    return True
            else:
                logger.warning('登录：没等到「Sign in with Google」')
                return False

        # 3. 等账号列表滑出来、**停住**，再点账号行。
        #    列表是从上往下展开的动画，`settle=3`（0.6 秒）不够 —— 真机 19:35
        #    在动画中间点了一次，落在还没铺开的地方，弹窗原地不动。
        for _ in range(3):
            # 点完账号可能已经进游戏：账号列表不会再出现，别把它判成登录失败
            # （真机 2026-11-10 17:10:52「登录：没等到账号列表」就是这么来的）。
            if self.in_game_screen():
                logger.info('登录：已经进游戏，账号列表不用再等')
                return True
            if not self.wait_until_appear(E_2_1, offset=CHAIN_OFFSET, timeout=15, settle=4):
                # 等账号列表期间也可能弹「发生错误 / 通知」；先点掉再给一次机会
                if self.dismiss_game_error() or self.dismiss_notice():
                    if not self.wait_until_appear(E_2_1, offset=CHAIN_OFFSET,
                                                  timeout=15, settle=4):
                        if self.in_game_screen():
                            logger.info('登录：账号列表没再出现，但已经进游戏')
                            return True
                        logger.warning('登录：没等到账号列表')
                        return False
                elif self.in_game_screen():
                    logger.info('登录：账号列表没再出现，但已经进游戏')
                    return True
                else:
                    logger.warning('登录：没等到账号列表')
                    return False
            self.wait_until_still(ACCOUNT_DIALOG, timeout=3, threshold=3.0)
            self.click_button(E_2_3, '选账号')
            # 弹窗关掉才算真的点中了；没关就再点一次
            if self.wait_until_disappear(E_2_1, offset=CHAIN_OFFSET, timeout=6, settle=2):
                # ❗选完账号≠已经进游戏：重置号/被踢回标题的号选完账号会
                #   先落回标题页，再点一次 Touch to Start 才进开场。
                #   2026-11-13 10:25 这里直接 `return True`，guide 在标题页
                #   点了一次 Touch to Start 没进去，居然继续按空表跑完，
                #   最后把半截教学当成旅程。必须等到 `in_game_screen()`。
                #
                # ❗但也不能选完账号 1 秒就判失败：2026-11-13 10:47 实测
                #   03.8s 标题页出现，04.8s 就点 Touch，点击被服务器登录流程
                #   吞掉，`wait_enter_game` 只等 1 秒就判没进游戏。
                #   2026-11-13 11:22 又踩了另一种：选完账号 5 秒时屏幕是
                #   黑的（加载中），既不是标题也不是游戏内，5 秒宽限一到就
                #   判失败。所以这里统一等 30 秒：黑屏/标题都继续等，只有
                #   标题出现超过 6 秒且距上次点击超过 6 秒才补点一次。
                start = time.time()
                last_touch = 0.0
                seen_title = False
                for _ in self.loop(timeout=30):
                    if self.dismiss_game_error() or self.dismiss_notice():
                        continue
                    if self.in_game_screen():
                        logger.info('登录：选完账号已进入游戏')
                        return True
                    if (self.appear(E_3_1, offset=CHAIN_OFFSET)
                            or self.appear(E_2_1, offset=CHAIN_OFFSET)):
                        logger.warning('登录：选完账号又回到登录弹窗')
                        return False
                    if (self.appear(E_4_2, offset=CHAIN_OFFSET)
                            or self.appear(E_1_1, offset=CHAIN_OFFSET)):
                        seen_title = True
                        now = time.time()
                        if now - start >= 6 and now - last_touch >= 6:
                            logger.info(
                                '登录：选完账号回到标题页，再点一次 Touch to Start')
                            if self.appear(E_4_2, offset=CHAIN_OFFSET):
                                self.click_button(E_4_2, 'Touch to Start（选完账号后）')
                            else:
                                self.click_button(E_1_1, 'Touch to Start（选完账号后）')
                            last_touch = now
                if seen_title:
                    logger.warning('登录：选完账号 30 秒还停在标题页，没进游戏')
                else:
                    logger.warning('登录：选完账号 30 秒还在加载/黑屏，没进游戏')
                return False
            # ❗弹窗判据在转场里会闪（17:10 实测 6 秒没凑齐连续 2 帧不可见），
            #   但游戏可能已经登录成功；先问一次「是不是进游戏了」，别直接重试。
            if self.in_game_screen():
                logger.info('登录：账号弹窗没判成消失，但已经进游戏')
                return True
        logger.warning('登录：点了账号但弹窗没关')
        return False

    def guide_press(self, buttons, note, start_pending=False, **kwargs):
        """`press()` 的引导包装：中途回到标题/登录页就重登，再从当前画面接。

        服务器记开荒进度，重登后不会重开教学；而 `press()` 是无状态的
        （每帧重扫按钮表、不记步数），所以重登成功后**重跑同一段**即可。

        ❗重登只试一次。再掉回标题就 `TaskFailed` 停住，不把
          「登录 → 掉线 → 登录」做成新的死循环。

        Args:
            buttons (tuple): 同 `press()`。
            note (str): 同 `press()`。
            start_pending (bool): 这一段的开头是否还允许点一次 page_4 的
                `E_4_2`（登录后「点一次进游戏」）。只有 `guide()` 第一段
                给 True；被踢回标题后重跑时也会重新允许一次。

        Returns:
            bool: 同 `press()`。
        """
        pending = start_pending
        for attempt in range(2):
            self.need_relogin = False
            ok = self.press(buttons, note, stop_on_login=True,
                            login_start_pending=pending, **kwargs)
            if not self.need_relogin:
                return ok
            if attempt:
                raise TaskFailed(self.fail_reason(
                    '引导中途回到标题/登录页，重新登录后再次掉回，已停止（账号没丢）。'))
            logger.warning('%s：中途回到标题/登录页，重新登录后从当前画面继续' % note)
            if not self.login():
                raise TaskFailed(self.fail_reason(
                    '引导中途回到标题/登录页，重新登录没走完，已停止'
                    '（账号没丢；把游戏停回标题页再手动重跑）。'))
            # 重登后可能还要点一次 page_4 才真正进游戏；`press()` 只在
            # 不在游戏内时才把这次机会留着（有 SKIP/四格就不给）。
            pending = True
        return False

    def story_advance(self, timeout=120):
        """点完没有 SKIP 的剧情页（闪退后最常卡住的一屏）。

        判据只用固定 UI：左上角目标书本 `E_211_1`。背景、人物、血条全在动，
        绝不能做整屏帧差（硬约束 206）。剧情页只有两种操作：
          · 普通对话：点屏幕下方 (640,620) 继续；
          · 右侧选项框：点 (1050,515) 选第一个选项。
        没有选项时点 (1050,515) 只会落在背景上，不会触发任何奖励/购买，
        所以这里可以交替点，不必先做选项识别。

        ❗每帧清一次点击记录：真机手动推进时同一坐标连点 12 次就会
          `GameTooManyClickError`，而长剧情要几十上百次。

        Returns:
            bool: True = 目标卡消失/已经回到大厅、旅程或战斗；False = 超时。
        """
        logger.hr('剧情续跑', level=2)
        self.device.screenshot()
        for _ in self.loop(timeout=timeout):
            self.device.stuck_record_clear()
            self.device.screenshot()
            if self.appear(E_119_1, offset=CHAIN_OFFSET):
                self.click_button(E_119_1, '剧情 → 跳过新手教学')
                self.wait_until_disappear(E_119_1, offset=CHAIN_OFFSET, timeout=5, settle=2)
                continue
            if self.in_game() or self.at_journey() or self.in_battle():
                logger.info('剧情续跑：已经回到可续跑画面')
                return True
            if not self.appear(E_211_1, offset=CHAIN_OFFSET):  # alas-lint: allow - 目标卡是剧情页唯一的固定判据；它消失就是剧情结束，过渡帧里继续等正是想要的，不会误点别的按钮
                logger.info('剧情续跑：目标卡消失，剧情结束')
                return True
            self.tap_at(1050, 515, '剧情选项')
            self.tap_at(640, 620, '剧情继续')
            self.device.click_record_clear()
        logger.warning('剧情续跑：%s 秒还没点完' % timeout)
        return False

    def guide(self, stop_at_nickname=False):
        """登录之后的开场引导，一直走到昵称确认。

        Args:
            stop_at_nickname (bool): 节点1。看到昵称输入框就停，**不输入昵称**。

        Returns:
            bool: True = 引导全部走完（交给旅程）；False = 按节点1 停在昵称前。
        """
        # ❗`idle=40`：全新账号登录后这段加载空窗很长，教学战往往 20 秒后
        #   才出来。默认 idle=12 会在教学战出现前就收工（真机 2026-11-07
        #   04:07:01 那一轮），接着「昵称」段 90 秒在教学战画面上空转，
        #   日志只剩 `Area (300,300,980,560) is still changing`，看起来像卡死，
        #   实际要 3 分半钟才等到第三段接上。教学战素材都在 GUIDE_A 表里，
        #   这一段多等一会儿就能自己接住。
        # ❗`stop_on=(E_60_2,)`：昵称弹窗**可能在教学战之后马上出现**，而这一段的
        #   表里只有 GUIDE_A（33 页，没有昵称素材）—— 弹窗一出来就整屏盖住，
        #   这一段什么都认不到，只能干等 `idle=40` 走完。真机 2026-11-07 10:16
        #   实测：10:16:26 弹窗出现，10:17:06 段才结束，白等 40 秒；下一段
        #   「昵称」接手后 0.5 秒就输入完了（用户：「到了 page_60 后半天不输入
        #   昵称，远不止 12 秒」）。
        #   ❗不把 NICK 并进这一段：这段是 `dialogue=True`，SKIP 失效时会点画面
        #     中央，而「昵称之后不许点中间」（用户 2026-11-06 20:17）。看到昵称框
        #     就立刻收工，交给下面那个 `dialogue=False` 的「昵称」段去输入。
        self.guide_press(GUIDE_A, '开场引导', start_pending=True,
                         dialogue=True, frames=True, idle=40,
                         stop_on=(E_60_2,))
        if stop_at_nickname:
            # ❗节点1：**只走到昵称框、不打字**。
            #   昵称弹窗可能还没出来（教学战本身要 20~40 秒），所以没看见就继续
            #   往下点，一露头就 `stop_on` 收工 —— 不会点到 E_61_1 的「确认」。
            #   打字也关掉了（`input_enabled=False`），用户要的就是"空着"的状态。
            if not self.appear(E_60_2, offset=CHAIN_OFFSET):  # alas-lint: allow - 判据是正面条件（昵称输入框），"看不见"= 弹窗还没出来（教学战/转场），这里只决定要不要再扫一遍；误判的代价是多点一段引导，不会点错
                # 上面那段 press 是 `dialogue=True`，走不完教学战就会静默收工，
                # 所以没看到昵称框就再扫一遍（`stop_on` 一露头就停，不会去点「确认」）。
                self.guide_press(GUIDE_A + NICK + GUIDE_B, '引导（走到昵称前）',
                                 timeout=420, frames=True, dialogue=True,
                                 stop_on=(E_60_2,))
            if self.appear(E_60_2, offset=CHAIN_OFFSET):
                logger.hr('引导：已停在昵称输入框（节点1，没有输入昵称）', level=2)
            else:
                logger.warning('引导：没等到昵称输入框，按节点1 直接停')
            return False
        # ❗昵称之后**既不许点画面中央、也不许找高亮框** ——
        #    用户 2026-11-06 20:17：「昵称之后的引导都不要点中间」。
        #    那边的引导全是"点这个按钮"，表里都有；而几何找框在普通 UI 上会误判
        #    （20:20 在抽卡页连点 7 次假框），开了就是乱点。
        #    视频仍然照跳（那是 SKIP，不是点画面）。
        # ❗`idle=6`（默认 12）：昵称只有 2 页，打完字确认键一出现就点掉了；
        #   真机 2026-11-07 17:01 遇到一次截图超时，输入框 3 秒没消失，
        #   后面又干等满 12 秒才收工（用户：「昵称输入会卡一下」）。
        #   这里提前收工也不亏：下一段「引导（进旅程之前）」扫的是
        #   `GUIDE_A + NICK + GUIDE_B` 合表，`E_60_2` / `E_61_1` 都在里面，
        #   真没点完下一段会接手。
        self.guide_press(NICK, '昵称', timeout=90, idle=6)
        # ❗`frames=True`：教学战里有"怪物的亮圆框"，那是引导要求点的目标，
        #   表里没有对应素材，只能靠几何找框。用户 2026-11-06 22:54 确认「加」。
        #   只开 `frames`、**不开 `dialogue`** —— 仍然是"点框"不"点中央"，
        #   守住 20:17 那条「昵称之后的引导都不要点中间」。
        # `dialogue=True`：SKIP 点了没反应的纯文字对话，退一步点画面中央推进。
        # `skip` 保持默认 True —— 用户 2026-11-06 23:20 澄清过：
        # 「我意思是他没点右上的跳过」（要的是**点得上** SKIP，不是不要点）。
        # ❗从标题页全新开跑时，教学战要在 GUIDE_A / 昵称两段之后才加载出来
        #   （那两段各 12 秒 idle 都撞上加载空窗提前收工），而教学战素材
        #   E_23_1 / 38~42 / 44 / 56 全在 **GUIDE_A 表**里。只扫 GUIDE_B 就一个
        #   都认不出，白框移到右下技能卡时几何找框又被区域挡掉，教学战卡死
        #   （2026-11-07 02:06 完整一轮复现）。这一段把两张表合起来扫。
        # ❗`NICK` 也要并进来：全新账号的真实顺序是「开场 → 教学战 → 昵称」，
        #   不是「昵称 → 教学战」。真机 2026-11-07 04:07 那一轮，「昵称」段
        #   90 秒在教学战画面上空转过去了，教学战 04:10:28 才打完，昵称弹窗
        #   落在这一段里 —— 表里没有 E_60_2/E_61_1 就永远认不出。
        #   昵称那两条走 `text_for()`（实例级昵称），不会点画面中央。
        # ❗`stop_on=(E_116_1,)`：点完最后一个 SKIP 之后，画面会黑一下加载，
        #   然后进旅程主页（右上角有倍速按钮）。这张表里**一页都不认识旅程主页**，
        #   所以就算页面早就刷出来了，press 也认不出，只能干等满 `idle=12` 秒
        #   （真机 2026-11-07 22:33 与 23:12 两次都是这样：收工后 84~100ms，
        #   `journey()` 一上来就把倍速点上了 —— 说明页面在 idle 到期前就已经就绪）。
        #   看到倍速按钮就把控制权交给 `journey().ensure_speed`，它认识这个页面。
        #
        #   ❗**别用 E_122_1（训练/休息菱形）**：现场截图实测它在旅程主页上是
        #   `False`（`E_116_1 True / E_122_1 False / E_120_1 False`），那两个菱形
        #   只在「关卡选择」页出现，拿它当判据永远不会命中。
        #   `stop_on` 本身已经限制成「没有 SKIP、没有血条」的干净画面才判，
        #   所以引导页和教学战不会误伤。
        #
        # ❗这一段必须**正面确认到了旅程**才许收工：2026-11-13 10:26 重置后
        #   重登，四段视频 SKIP 点完落在 12 秒 idle 空窗里，`guide()` 直接
        #   `return True`，`journey()` 在还没过完的教学/剧情上乱点，用户看到
        #   的就是「教学引导没过，直接到旅程那边了」。`stop_on` 没命中就说明
        #   还没到旅程，再扫一遍当前画面；三次都不到就按失败交给调度器，
        #   宁可不跑也不要带着半截教学进旅程。
        reached = False
        for attempt in range(3):
            self.guide_press(GUIDE_A + NICK + GUIDE_B, '引导（进旅程之前）',
                             timeout=420, frames=True, dialogue=True,
                             idle=40, stop_on=(E_116_1,))
            self.device.screenshot()
            if self.at_journey() and not self.in_battle():
                reached = True
                break
            logger.warning('引导：还没到旅程（第 %d 次扫完），继续点当前画面'
                           % (attempt + 1))
        if not reached:
            raise TaskFailed(self.fail_reason(
                '引导结束但没到旅程（教学没走完，不继续跑）'))
        return True

    def journey(self):
        """
        旅程：点两次倍速 -> 训练 -> 评鉴战。

        评鉴战那一步是「先过引导再点自动战斗」：134_1 是引导高亮，134_2 是自动战斗
        按钮，两个都在这张表里、134_1 排在前面，所以引导先被点掉，自动战斗才会被认到。
        """
        # 先试一次（这一屏可能还没露出倍速按钮，试不到就让 press 整段盯着）。
        # 20 秒：每次点击前有 1 秒静止确认、点后有 2 秒验收，1x→3x 两下
        # 加上一次被吞的重试也就 12 秒左右；12 秒实测只够点一下。
        self.ensure_speed(3, timeout=20)
        # ❗`idle=75`：旅程里夹着**纯过场**（开场独白、点完「跳过新手教学」后的
        #   JOURNEY 加载大白屏），这些十几秒里一个可点元素都没有，默认 idle=12
        #   会让这一段提前收工 —— 真机 2026-11-07 00:10 就停在 JOURNEY 加载页，
        #   下一段 settle() 也是空转，整条链断在那儿。
        #   评鉴战本身要 60~70 秒才出 VICTORY（03:51:13 开 AUTO → 03:52:2x 胜利），
        #   40 秒会在胜利前 30 秒就收工，所以放到 75 秒。
        self.press(JOURNEY, '旅程：倍速 / 训练 / 评鉴战', timeout=600, idle=75,
                   speed=True, stop_on=(E_208_1,))

    def settle(self):
        """旅程结算：点掉两个签到 -> 解锁 -> 后续引导 -> 主界面。

        ❗**跑两遍**。「跳过新手教学」有旅程版和作战版两个，点掉一个之后
        游戏会播一小段过场（黑屏），第二个要十几秒后才弹 —— 第一遍 press
        的 12 秒静默会被这段过场耗掉，等第二个弹出来时这一段已经收工了。
        用户 2026-11-06 21:18：「有两个，所以你得运行两次」。

        ❗`idle=40`（原 12）：这一段跨「旅程结算 → 主界面上的 16 页后续引导
        （page_153~168）」，中间夹着游戏自己播的结算过场和「跳过新手教学」剧情。
        真机 2026-11-07 11:46 那一轮第一遍只点到 `E_135_1` 就 12 秒静默收工，
        第二遍在 `E_136_1` 上撞到游戏本体的点击 bug 卡了 10 秒也收了 ——
        **page_153~168 一页都没点到**，紧接着 claim「打不开菜单项」、
        gacha 0.2 秒退出、verify 空读、reset 连设定页都进不去，整轮白跑。
        11:51 从 page_153 续跑证明这 16 页只要 20 秒（平均 1.1s/页），
        缺的只是「别在过场里收工」。

        ❗但 `idle=40` 的代价是**末尾空等**：page_168 是最后一页，点掉它就已经
        在主界面了，后面没有任何引导页可点，却还要静默满 40 秒才收工
        （真机 2026-11-07 14:36:37~14:37:07 一路播报「page_168 之后 Ns 没有
        点掉新引导页」）。用户 14:4x：「168_1 后就在主页面了不用等 40s，
        直接下一步领奖励」。所以两遍都加 `stop_after_page=168`：
        点掉 168 立刻返回，省掉这 40 秒。

        ❗**不加 `stop_on=(E_171_1,)`**：153~168 这 16 页**本身就在主界面上**，
        右上四格从第一页起就可见（真机 11:49:52 实测 0.995），加了这个 stop
        会刚起步就收工，等于没改。
        """
        # ❗只跑一遍，别复制成两个 press：16:46 那轮就是因为这里多出一份
        #   不带 `hit_out` 的 press，第一遍 168 收工后又从头扫了一遍，
        #   点掉两个教学却没有收工判据，硬等满 40 秒。
        hit1 = []
        self.press(SETTLE, '结算 / 签到 / 解锁', timeout=600, idle=40,
                   stop_after_page=168, hit_out=hit1)
        # ❗第二遍只在「还没回到主界面」时才跑。原来那句「第二遍没东西可点的话
        #   就是空转 12 秒，不亏」是错的：真机 2026-11-07 10:26 实测，`E_168_1`
        #   一过就已经在主界面了，第二遍整整 12 秒**一页都没点到**
        #   （用户：「168_1 的引导走完，等半天才去领奖励抽卡」）。
        #   判据用主界面右上角四格 `E_171_1` —— 它在就说明结算已经走完了。
        self.device.screenshot()
        # 这里的"看不见四格"不是转场误判：判据是**正面**的（主界面四格在 = 结算完了），
        # 只有"看不见"才需要再扫一遍，而且这一分支本身就是那一步。宁可按旧行为多扫一遍
        # （多花 40 秒），也不要漏掉「跳过新手教学」。
        hit2 = []
        if not self.appear(E_171_1, offset=(10, 10)):  # alas-lint: allow - 判据是正面条件（主界面四格），"看不见"=还没回主界面；这里只决定要不要再扫一遍，误判的代价是多花 40 秒而不是点错东西
            self.press(SETTLE, '结算 / 签到 / 解锁（第二个跳过教学）', timeout=600,
                       idle=40, stop_after_page=168, stop_after_button=(E_119_1,),
                       hit_out=hit2)

        # ❗兜底：结算阶段一共有**两个**「跳过新手教学」（用户 15:5x：
        #   「旅程里有一个教学。后面还有两个教学，一共三个」），它们都在
        #   page_168 点掉**之后**隔几秒才弹 —— 上面两遍谁先点掉 168 谁先收工，
        #   第二遍又会在点掉第一个教学时 `stop_after_button` 收工（真机
        #   16:34:24 就是这样，只点掉一个就跑去开邮箱，后面全被第二个弹窗挡住）。
        #   所以这里**不管两遍点没点过都要守**：按「点掉几个」计数，
        #   两遍里点过几个先算进 `clicked`，凑满两个再说。
        # ❗收工判据是**正面**的：两个教学都点过、主界面四格连续 3 秒可见，
        #   就立刻交棒领奖 —— 只靠「40 秒窗口到期」会点完再白等 40 秒
        #   （真机 16:18:39 点完第二个教学、16:19:19 才进邮箱）。
        clicked = hit1.count('E_119_1') + hit2.count('E_119_1')
        wait_teach = Timer(40).start()
        main_stable = Timer(3)   # 点过两个教学之后，四格连续 3 秒 = 回主界面了
        for _ in self.loop(timeout=55):
            if wait_teach.reached():
                break
            # 过场是游戏自己播的，别让看门狗把这段等待判成卡死（硬约束 152）
            self.device.stuck_record_clear()
            if self.appear(E_119_1, offset=CHAIN_OFFSET):
                self.click_button(E_119_1, '跳过新手教学（结算兜底）')
                self.wait_until_disappear(E_119_1, offset=CHAIN_OFFSET, timeout=3)
                wait_teach.reset()   # 第二个教学可能紧接着弹，窗口续上
                clicked += 1
                main_stable.reset()
                continue
            # 两个教学都点过、主界面四格连续 3 秒可见 → 立刻收工，别空等 40 秒
            if clicked >= 2:
                if self.appear(E_171_1, offset=CHAIN_OFFSET):
                    if main_stable.reached():
                        break
                else:
                    main_stable.reset()

    def type_text(self, text):
        """把**中文**送进当前聚焦的输入框。

        ❗不能用 `device.adb_shell`：真机 2026-11-07 01:08 逐项测过
          · list 形式 `['input','text','重置服务器账号']` → 中文字全丢；
          · str 形式 `"input text '重置服务器账号'"` → 报
            `/system/bin/sh: no closing quote`，引号被编码弄坏。
          只有 `subprocess` 直接调 adb.exe、把 UTF-8 参数交给 CreateProcess
          才送得出去。

        ❗❗**要等输入法连上这次输入再打**（见 `wait_ime_connected`）：中文是
          ACTION_MULTIPLE 字符事件，要经过输入法的 InputConnection 才落到
          EditText 上。刚点完框那几十毫秒连接还没建好，字直接没了 ——
          真机 00:22 / 01:10 两轮 8 次全空都是这么来的。
          ❗也不能靠"把输入法禁掉"绕过去：没有输入法就没有 InputConnection，
          中文同样一个字符都不落（2026-11-08 实测 `pm disable-user` 之后
          中文全丢、英数反而照进）。
          `input text` 不论字去哪都返回 0，所以日志的「已输入」不算数 ——
          要靠 `read_reset_input` 回读。
        """
        result = subprocess.run(
            [self.device.adb_binary, '-s', self.device.serial,
             'shell', 'input', 'text', text],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        if result.returncode or result.stderr:
            logger.warning('输入文字返回 %s %r'
                           % (result.returncode, result.stderr[:120]))
        return result

    def wait_reset_overlay(self):
        """点完输入框后，等游戏把自己的输入浮层挂好（约 0.5 秒）。

        ❗**这一步不能省**。真机 2026-11-08 同一屏扫过 0.05 / 0.1 / 0.3 /
          0.6 / 1.2 秒五个值：**≤0.3 秒字全丢**（框里空、屏幕底部那条游戏
          自带的编辑条也空），**≥0.6 秒白字立刻进框**。中文是 ACTION_MULTIPLE
          字符事件，浮层没挂好就没人接 —— 00:22 / 01:10 两轮 8 次全空就是这么来的。
        ❗别拿 `dumpsys input_method` 的 `mBoundToMethod` 当判据：它在弹窗
          第二次打开时**一直是 true**（上一轮的连接还挂着），实测 0.08 秒就
          满足，字照样丢。
        """
        # 不是「sleep 串联点击」：等完只打一次字，而且打完立刻回读验证。
        time.sleep(0.8)

    @staticmethod
    def reset_word_ok(seen):
        """OCR 读出来的确认语对不对。

        ❗容忍 1 个 OCR 错字（cnocr 常把「账」读成「帐」，游戏本身也写成「帐」），
          但**顺序错一律不算对**：游戏那个 bug 就是顺序乱
          （服务器 → 务服器），必须清空重输。
        """
        got = ''.join((seen or '').split())
        want = RESET_WORD
        if got == want:
            return True
        if len(got) != len(want):
            return False
        same = sum(1 for a, b in zip(got, want) if a == b)
        return same >= len(want) - 1

    def finish_reset_input(self):
        """输入确认语 -> 点确认 -> 等回标题页；没过就重输。

        单独一个方法，方便从「输入弹窗」这个状态接着跑（本轮中断时）。

        ❗**脚本不清空输入框**。字不对时点确认后，游戏会自己把框清空
          （用户 2026-11-08 明确要求）。自己按 20 下退格是多余动作，
          还多两次 adb 往返。

        ❗**OCR 回读不当闸门**。00:22 那轮 4 次全卡在「框里读到 '（十)' /
          '重一)》入}'」→ 一次都没点确认，用户看到的就是「一直点黑框，
          不知道在干嘛」。读到内容是乱码也照样点确认：游戏校验不过会自己
          清框，下一轮重输。

        ❗**只有「一个字都读不到」才算这次没输进去**，那种情况点确认没意义，
          直接重来（框是空的，重打不会叠字）。

        ❗**点完框要等游戏的输入浮层挂好再打**（`wait_reset_overlay`），这是
          23:19 / 00:04 / 00:22 / 01:10 四次连丢的共同原因。
        """
        for attempt in range(1, 5):
            # 弹窗还在淡入时点框会点空（00:04 那轮 537ms 抢跑），先等画面静止
            self.wait_until_still((0, 300, 1280, 720), timeout=3, threshold=3.0)
            self.tap_at(640, 401, '点输入框')
            self.wait_reset_overlay()
            self.type_text(RESET_WORD)
            # 回读只为了在日志里留下框里到底是什么：读准了就提前收，
            # 读不准就等满 3 秒再拿最后一帧。
            seen = ''
            for _ in self.loop(timeout=3):
                self.device.stuck_record_clear()
                seen = read_reset_input(self.device.image)
                if self.reset_word_ok(seen):
                    break
            if not seen:
                logger.warning('重置：第 %d 次字没进框（框里一片空），重输' % attempt)
                continue
            if self.reset_word_ok(seen):
                logger.info('重置：第 %d 次输入，框里读到 %s' % (attempt, seen))
            else:
                logger.warning('重置：第 %d 次框里读到 %r（要 %r），照样点确认'
                               % (attempt, seen, RESET_WORD))

            self.tap_at(735, 468, '确认')
            # ❗校验不过时游戏**不报错、弹窗不关、只把输入框清空**。
            #   真机 2026-11-07 22:40 现场：点完确认原样干等 120 秒，
            #   弹窗还杵着、框里已经空了。所以「弹窗还在」就是这次没过。
            for _ in self.loop(timeout=10):
                self.device.stuck_record_clear()
                # 回到标题页的同一帧可能先弹「与服务器联机中断。」，点掉再判
                if self.dismiss_notice():
                    continue
                if self.appear(E_1_1, offset=CHAIN_OFFSET):
                    logger.info('重置完成，回到标题页')
                    return True
            self.device.screenshot()
            if not self.reset_input_ready(self.device.image):
                logger.info('重置：输入弹窗已经关了，等加载回标题页')
                break
            logger.warning('重置：第 %d 次点确认没生效（弹窗还在），重输' % attempt)
        else:
            logger.warning('重置：重输 4 次都没通过校验，停下')
            return False

        # 弹窗已关 = 校验通过，剩下的只是加载，慢一点也值得等。
        for _ in self.loop(timeout=120):
            self.device.stuck_record_clear()
            # 加载完到标题页的这一刻最容易弹「与服务器联机中断。」
            if self.dismiss_notice():
                continue
            if self.appear(E_1_1, offset=CHAIN_OFFSET):
                logger.info('重置完成，回到标题页')
                return True
        logger.warning('重置：输入弹窗关了，但没回到标题页')
        return False

    @staticmethod
    def reset_input_ready(image):
        """输入确认语的弹窗出来没有：看那块**深灰输入框**。

        `E_200_1` (566,380,676,415) 是纯色（std 3.7），拿模板当判据对任何
        暗画面都成立；`RESET_DIALOG` 的 OCR 在这屏读成乱码「扒羹立讹|」
        （真机 00:59 连读 10 秒）。直接量亮度最稳：
            输入弹窗  mean 68.3 / dark<150 占 1.000
            警告弹窗  mean 245.5 / dark<150 占 0.000
        """
        if image is None:
            return False
        a = np.asarray(image[380:415, 566:676], dtype=np.int32)
        return float((a.mean(axis=2) < 150).mean()) > 0.80

    @staticmethod
    def task_claim_ready(image):
        """「一键领取」是不是亮的（金黄底）。见 `claim_task` 里的说明。"""
        if image is None:
            return False
        a = np.asarray(image[TASK_CLAIM_BOX[1]:TASK_CLAIM_BOX[3],
                             TASK_CLAIM_BOX[0]:TASK_CLAIM_BOX[2]], dtype=np.int32)
        r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
        return float(((r > 170) & (g > 120) & (b < 100)).mean()) > TASK_CLAIM_ON

    def open_menu(self, timeout=6):
        """打开「菜单」页（那一整片功能网格）。

        主界面右上角的四格 `E_171_1` 点开就是它（用户 2026-11-06 21:32：
        「page_176 是菜单页」）。菜单页上有三个入口，都靠这一页的素材：
            `E_176_1` 设置   → 重置账号用
            `E_176_2` 救援者 → 验号用
            `E_176_3` 任务   → 领任务奖励用

        ❗点开之后**只点一次**：再点一下 `E_171_1` 的位置会把菜单关掉
        （菜单是浮层，点外面就收）—— 用户 21:30：「刚刚你点开菜单，
        不知道为什么又关掉了」，就是两次点击撞在一起。
        """
        # 先把可能盖在上面的奖励弹窗按掉（「点击以继续」= `E_174_1`，
        # 邮箱和任务都用这一张）。不按掉的话主界面的四格根本看不见，
        # `open_menu()` 会直接判"打不开菜单页"（真机 21:40 连撞两次）。
        self.device.screenshot()
        # ❗好评弹窗（`E_204_1`/`E_204_2`）也整屏盖住主界面，它比奖励弹窗更阴：
        #   抽卡「返回主界面」那一下正好会弹它，于是 `E_171_3` 等不到、四格也看不见，
        #   `open_menu()` 直接判「打不开菜单页」，验号在错误画面上空读 ——
        #   真机 2026-11-07 13:23 就是这样，读出来「一个 SSR 都没读到」
        #   （用户 13:2x：「没有进行验号，是不是好评弹窗干扰了？」）。
        if self.close_review():
            self.device.screenshot()
        if self.appear(E_174_1, offset=(10, 10)):
            self.click_button(E_174_1, '奖励弹窗 → 继续')
            self.wait_until_disappear(E_174_1, offset=(10, 10), timeout=3, settle=2)
            self.device.screenshot()

        if self.appear(E_176_2, offset=(10, 10)):
            return True      # 菜单已经开着
        if self.appear(E_171_1, offset=(10, 10)):
            self.click_button(E_171_1, '主界面 → 菜单')
            return self.wait_until_appear(E_176_2, offset=(10, 10), timeout=timeout)
        logger.info('菜单：主界面上没看到四格入口（可能不在主界面）')
        return False

    def claim(self):
        """领奖：邮箱 + 任务。

        邮箱入口（右上角信封 `E_171_2`）**单独点一次**再进循环表 ——
        它和邮件面板里的按钮会同时匹配，混进 `press` 就是来回点
        （真机 2026-11-06 21:25 撞过 `GameTooManyClickError`）。
        """
        logger.hr('邮箱', level=2)
        # ❗先截一帧：`appear()` 是直接读 `device.image` 的，它自己**不截图**，
        #   刚进来的话 device 还没 image 属性（真机 21:30 撞 `AttributeError:
        #   'Device' object has no attribute 'image'`）。
        self.device.screenshot()
        if self.appear(E_171_2, offset=(10, 10)):
            self.click_button(E_171_2, '打开邮箱')
            self.wait_until_disappear(E_171_2, offset=(10, 10), timeout=3, settle=2)
        # ❗`idle=2`（默认 12）：邮箱里点掉「全部领取」之后就没有可点的了，
        #   12 秒纯属白等（真机 2026-11-07 17:22「邮箱：12 秒没有可点的按钮」，
        #   用户：「缩短时间」）。2026-11-12 23:05 又出现 5 秒空等，用户要求改 2 秒。
        self.press(MAIL, '邮箱', timeout=180, idle=2)
        self.claim_task()

    def claim_task(self):
        """任务奖励：四个页签（每日 / 每周 / 成就 / 挑战）都领。

        用户 2026-11-06 21:41：「每日，每周，成就，挑战，都要领」。

        ❗每个页签**要点两次**才领得完（用户 21:37：「每日和每周都要领两次的，
          所以我才用亮暗，暗了才是真领完了」），所以是循环到变灰为止。
        """
        logger.hr('任务奖励', level=2)

        self.device.screenshot()
        in_panel = (self.appear(E_177_1, offset=(20, 20))
                    or self.appear(E_178_1, offset=(20, 20)))
        if not in_panel:
            if not self.open_menu():
                logger.warning('任务：打不开菜单页')
                return False
            self.device.screenshot()
            if self.appear(E_176_3, offset=(10, 10)):
                self.click_button(E_176_3, '菜单页 → 任务')
                self.wait_until_disappear(E_176_3, offset=(10, 10), timeout=3, settle=2)
            else:
                logger.warning('任务：菜单页上没有「任务」图标')
                return False

        for name, (x, y) in TASK_TABS:
            before = self.device.image.copy()
            self.tap_at(x, y, '任务页签：%s' % name)
            # 点完**必须确认真的切过去了**：页签没切成功时右侧列表压根不变，
            # 读到的还是上一页（已经领灰）的状态，会一秒就判"领完了"。
            if not self.wait_area_changed(TASK_TAB_AREA, before, timeout=3):
                logger.warning('任务：点「%s」之后页签没变化，可能没点中' % name)
            self.wait_until_still(TASK_CLAIM_AREA, timeout=2, threshold=4.0)
            self.claim_one_tab(name)

        # ❗领完人**还留在任务面板**，要退两层才能回主界面：
        #   任务面板 --✕(E_175_2)--> **菜单页**（功能网格浮层）--点四格--> 主界面。
        #   用户 2026-11-07 00:44：「任务退出回的是菜单，点了观测就是回到主页面，
        #   所以没有点进观测」。菜单页是半透明浮层，底下主界面的左侧「观测」
        #   还露着，`E_171_3` 会**假阳性**（实测菜单页 E_171_3=True、
        #   E_171_1=False、E_176_2=True；主界面 E_171_1=True、E_176_2=False）。
        #   所以验收只认右上角四格 `E_171_1`。
        self.device.screenshot()
        if self.appear(E_175_2, offset=(10, 10)):
            self.click_button(E_175_2, '任务面板 关闭')
            self.wait_until_appear(E_176_2, offset=(10, 10), timeout=6)
        # 菜单是浮层，点四格(E_171_1)那个位置就收起；点一下没反应就重试到
        # 判据成立（硬约束 153），不一次判失败。
        for _ in self.loop(timeout=12):
            self.device.screenshot()
            if self.appear(E_171_1, offset=(10, 10)):
                break
            if self.appear(E_176_2, offset=(10, 10)):
                gx = (E_171_1.area[0] + E_171_1.area[2]) // 2
                gy = (E_171_1.area[1] + E_171_1.area[3]) // 2
                self.tap_at(gx, gy, '菜单页 收起')
                self.wait_until_still((0, 0, 1280, 720), timeout=2, threshold=3.0)
        if not self.wait_until_appear(E_171_1, offset=(10, 10), timeout=6):
            logger.warning('任务：关掉面板后没回到主界面')
            return False
        logger.info('任务：已回到主界面')
        return True

    def wait_area_changed(self, area, before, timeout=3, threshold=6.0):
        """等 `area` 这块画面和 `before` 明显不一样（用来确认页签真的切了）。

        ❗**隔 4 像素采样再比**：抽卡那段传的是全屏 (0,0,1280,720)，
        每帧对 1280x720x3 的 int16 数组做 `abs().mean()` 要十几毫秒，
        而这个判据每帧都要算一遍。隔点采样后像素量降到 1/16，
        对"画面换没换"这种粗判断完全够用（阈值本来就有 6 的余量）。
        """
        if before is None:
            return False
        x1, y1, x2, y2 = area
        step = 4
        ref = np.asarray(before[y1:y2:step, x1:x2:step], dtype=np.int16)
        for _ in self.loop(timeout=timeout):
            cur = np.asarray(self.device.image[y1:y2:step, x1:x2:step], dtype=np.int16)
            if cur.shape == ref.shape and float(np.abs(cur - ref).mean()) > threshold:
                return True
        return False

    def claim_one_tab(self, name):
        """把一个页签领到「一键领取」变灰为止。"""
        for _ in self.loop(timeout=90):
            self.device.screenshot()
            if not self.task_claim_ready(self.device.image):
                logger.info('任务（%s）：一键领取变灰了，这个页签领完' % name)
                return True
            self.click_button(E_177_1, '任务一键领取（%s）' % name)
            # 领完会弹全屏 REWARD，**复用邮箱那套**（`E_174_1` 点击以继续 /
            # `E_175_2` 关闭）—— 用户 2026-11-06 21:39：
            # 「会有奖励弹窗复用一下邮箱那里的」。不点掉它，下一帧读到的是
            # 弹窗画面，任务按钮那块全黑 → 误判成"变灰、领完了"。
            # ❗**只点 `E_174_1`（点击以继续），不要 `E_175_2`**：
            #   `E_175_2` 是右上角那个 ✕ (1216,39,1238,63)，任务面板自己的
            #   关闭键也是它 —— 放进表里就会把整个任务面板关掉，后面的页签
            #   全落在主界面上（用户 2026-11-06 21:49：
            #   「不知道为什么点了右上角的返回」）。
            self.press((E_174_1,), '任务奖励弹窗', timeout=20, idle=3)
            self.wait_until_still(TASK_CLAIM_AREA, timeout=3, threshold=4.0)

        logger.warning('任务（%s）：一键领取一直是亮的，点了 90 秒还没领完' % name)
        return False

    def gacha(self):
        """抽卡：观测 → 确认 → skip → 再次观测，一直抽到没资源。

        用户 2026-11-06 21:52 给的流程：
            主页面点 `171_3` → `180_1`（观测10次）→ `181_1`（确认）→ skip
            → `182_1`（再次观测）→ skip → `182_1` …
            → 直到 `183_1` 没资源 → `183_2`（确认，退出结果页）
            → `184_1` 没资源 → `184_2`（返回主页面）

        ❗「有没有资源」不能靠模板判：
          · 结果页底部「观测10次」`E_182_1`(665,654,838,679) 和没资源的
            `E_183_1`(663,654,839,680) area 几乎完全重叠；
          · 抽卡界面的 `E_180_1`(1052,660,1232,685) 和 `E_184_1`(1052,659,1232,684) 一样。
          只能量**蓝底占比**（真机亮的 0.558、灰的 0）。
        """
        logger.hr('抽卡', level=1)
        self.device.screenshot()

        # 入口：**先确认真的在主界面**（右上四格 `E_171_1`），再点左侧「观测」。
        # ❗不能用 `E_171_3` 当"在主界面"的判据：菜单页是半透明浮层，底下
        #   主界面的「观测」还露着，它照样 True；在菜单页点观测只是把菜单收起，
        #   并不会进观测页（真机 00:41 的 20 秒超时就是这么来的）。
        # ❗点 `E_171_3.area` 的中心 (108,493)。旧注释说要点 (100,520)，
        #   但 00:42 实测 area 中心立刻 `E_180_1` 出现。用 `.area` 不用
        #   `.button`：后者会被 match 的 offset 改写（硬约束 136）。
        # ❗新号侧栏「观测」被教学遮罩挡着，点了没反应；右上四格菜单里的
        #   「观测」格子能直接进（2026-11-13 08:58 真机实测）。所以先走
        #   `E_171_1` → `E_210_1` → `E_180_1`，菜单格子认不到再退回侧栏。
        entered = False
        if self.appear(E_180_1, offset=(20, 20)):
            # 已经在观测页（手动进来 / 上一轮没退出去）就别再点入口。
            # 观测页右上角有铃铛，`E_171_1` 在真机上会误匹配，点下去只会
            # 打开通知（2026-11-13 09:48 实测）。
            entered = True
        elif self.appear(E_171_1, offset=(10, 10)):
            self.click_button(E_171_1, '主界面 → 菜单')
            entered = False
            if self.wait_until_appear(E_210_1, offset=(10, 10), timeout=6):
                self.click_button(E_210_1, '菜单 → 观测')
                entered = self.wait_until_appear(E_180_1, offset=(20, 20), timeout=20)
            else:
                logger.info('抽卡：菜单里没有「观测」格子，退回侧栏入口')
                # ❗菜单是半透明浮层，侧栏「观测」在它底下照样露着；不先收起
                #   菜单就点侧栏，只会把菜单关掉，人还站在大厅（2026-11-13
                #   09:37 新号实测：E_210 超时 → 点 E_171_3 → E_180 超时）。
                #   菜单页右上四格 E_171_1 还在，再点一次就是收起。
                if self.appear(E_171_1, offset=(10, 10)):
                    self.tap_at(1221, 36, '菜单页 收起')
                    self.wait_until_still(GACHA_FULL_AREA, timeout=2, threshold=3.0)
                if self.appear(E_171_1, offset=(10, 10)):
                    cx = (E_171_3.area[0] + E_171_3.area[2]) // 2
                    cy = (E_171_3.area[1] + E_171_3.area[3]) // 2
                    self.tap_at(cx, cy, '主界面 → 观测')
                entered = self.wait_until_appear(E_180_1, offset=(20, 20), timeout=20)
            if not entered:
                logger.warning('抽卡：没能进到观测界面')
                return False

        # ❗既不在主界面也不在观测/结果页就别进循环：四条分支一个都不认得时
        #   只会在下面空转到 900 秒（真机 00:36 上游 claim_task 没回主界面就
        #   撞过一次）。上游已经补了返回步骤，这里再挡一道。
        if not (self.appear(E_171_1, offset=(10, 10))
                or self.appear(E_180_1, offset=(20, 20))
                or self.appear(E_184_2, offset=(20, 20))
                or self.appear(E_183_2, offset=(20, 20))):
            logger.warning('抽卡：既不在主界面也不在观测页，退出')
            return False

        for _ in self.loop(timeout=900):
            # 抽卡动画 / 结果页光效期间几十秒没有可点元素，别让看门狗把
            # 正常等待判成 Game died（硬约束 152，上限交给本循环 timeout）。
            self.device.stuck_record_clear()
            self.device.screenshot()
            before = self.device.image.copy()

            # ---- ① 确认框**必须最先判** ----
            # ❗弹窗是模态的，底下结果页的「确认」(`E_183_2`) 和按钮照样匹配得上，
            #   只是被遮罩压暗了 —— 先判结果页的话会走进"观测灰了"那条分支，
            #   把弹窗点掉、再点「再次观测」、再被误判……真机 2026-11-06 22:03
            #   就是这么来回戳了 60 多次（用户：「点了观测左边的确认？」「是因为
            #   判断到了没资源吗？」—— 都不是，是判据顺序被弹窗骗了）。
            if self.appear(E_181_1, offset=(20, 20)):
                self.tap_at(GACHA_TAP_DIALOG[0], GACHA_TAP_DIALOG[1], '确认抽卡')
                self.wait_until_disappear(E_181_1, offset=(20, 20), timeout=5, settle=2)
                self.device.click_record_clear()
                continue

            # ---- ② 抽卡结果页（底部有白色「确认」）----
            if self.appear(E_183_2, offset=(20, 20)):
                if self.box_is_blue(GACHA_RESULT_BOX):
                    for _ in range(3):
                        self.tap_at(GACHA_TAP_RESULT[0], GACHA_TAP_RESULT[1], '再次观测')
                        if self.wait_until_appear(E_181_1, offset=(20, 20), timeout=2.5):
                            break
                        self.wait_until_still(GACHA_FULL_AREA, timeout=2, threshold=3.0)
                    self.device.click_record_clear()
                else:
                    logger.info('抽卡：结果页的观测已经灰了，点确认退出')
                    self.tap_at(GACHA_TAP_CONFIRM[0], GACHA_TAP_CONFIRM[1], '结果页 → 确认')
                    self.wait_area_changed(GACHA_FULL_AREA, before, timeout=4)
                continue

            # ---- ③ 抽卡界面（左上角有返回 `E_184_2`）----
            if self.appear(E_184_2, offset=(20, 20)):
                if self.box_is_blue(GACHA_DRAW_BOX):
                    for _ in range(3):
                        self.tap_at(GACHA_TAP_DRAW[0], GACHA_TAP_DRAW[1], '观测10次')
                        if self.wait_until_appear(E_181_1, offset=(20, 20), timeout=2.5):
                            break
                        self.wait_until_still(GACHA_FULL_AREA, timeout=2, threshold=3.0)
                    self.device.click_record_clear()
                else:
                    logger.info('抽卡：观测10次已经灰了（没资源），返回主界面')
                    self.tap_at(120, 46, '观测界面 → 返回')
                    # ❗「返回主界面」这一下**常常正好弹好评弹窗**，整屏盖住主界面：
                    #   `E_171_3` 等不到，紧接着 `open_menu()` 也判「打不开菜单页」，
                    #   验号于是在错误画面上空读（真机 2026-11-07 13:23 实测：
                    #   `wait_until_appear(E_171_3) timeout` → 「一个 SSR 都没读到」）。
                    #   这里一边等主界面一边按掉它，按掉之后主界面就露出来了。
                    for _ in self.loop(timeout=20):
                        self.device.stuck_record_clear()
                        if self.appear(E_171_3, offset=(10, 10)):
                            break
                        self.close_review()
                    logger.info('抽卡：回到主界面，抽卡结束')
                    return True
                continue

            # ---- ④ 抽卡动画：右上角 SKIP（`E_69_1`）----
            if self.appear(E_69_1, offset=(20, 20)):
                self.click_button(E_69_1, '抽卡动画 → 跳过')
                self.wait_until_disappear(E_69_1, offset=(20, 20), timeout=3, settle=2)
                continue

        logger.warning('抽卡：900 秒还没抽完')
        return False

    def box_is_blue(self, box):
        """这一块是不是蓝色按钮（能点的状态）。见 `gacha` 里的说明。"""
        image = self.device.image
        if image is None:
            return False
        a = np.asarray(image[box[1]:box[3], box[0]:box[2]], dtype=np.int32)
        r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
        return float(((b > 150) & (r < 120) & (g < 160)).mean()) > GACHA_BLUE_ON

    def verify(self):
        """
        验号：从上往下一行一行点，SSR 才算。

        用户 2026-11-06 18:45 定的流程：点一行 → 看左上角那块稀有度 →
        不是 SSR 就整个结束（列表是 SSR 在前）→ 是 SSR 就记团名和人名、
        进详情、点突破极限、看「获得了多少个」。

        读的是「突破极限 → 所需材料 N/1」的 N，**不是**详情页右上角那个「共鸣」——
        实测丝卡蕾详情页写 0、突破极限页却是 2/1，两个数不是一回事。

        只读当前一屏。露一半的那一行不点（圆心在面板边缘上，点它是点屏幕外）。
        """
        logger.hr('验号', level=2)
        self.target_hit = False
        self.target_detail = ()
        self.last_scan = ()

        # 入口：菜单页的「救援者」`E_176_2`(825,321,878,391) —— 用户 21:30 指的。
        # 路径是 主界面 → 四格菜单 `E_171_1` → 菜单页 → 救援者。
        if self.open_menu():
            self.device.screenshot()
            if self.appear(E_176_2, offset=(10, 10)):
                self.click_button(E_176_2, '菜单页 → 救援者')
                self.wait_until_disappear(E_176_2, offset=(10, 10), timeout=5, settle=2)
            else:
                logger.warning('验号：菜单页上没有「救援者」图标')
        else:
            logger.warning('验号：打不开菜单页，当成已经在救援者页面')

        # 点进救援者**必定有一段引导**（185~192），用户 2026-11-06 22:07：
        # 「就像旅程那里一样，先引导后验号」。引导走完会停在详情页，
        # 下面 `back_to_list()` 负责退回来。
        # ❗`restore_after=2`：只有 8 页、一页约 1 秒，等 8 秒才重扫太久
        #   （用户 16:2x：「不用8秒那么久」）。
        # ❗`idle=5`（默认 12）：8 页点完就是尾巴，真机 16:49 记到的最长间隔
        #   只有 page_187 → page_188 的 2.4s，12 秒纯属白等（用户 16:5x：
        #   「是这里等了12秒吧。缩短」）。
        self.press(VERIFY, '救援者引导', timeout=600, idle=5, restore_after=2)
        # 引导最后一步可能是点左上返回。press 的静默（现在 idle=5）已经等过了，
        # 这里再兜一次「回列表」，免得带着详情页进去扫。
        self.back_to_list()

        accounts = self.scan_rescuers()
        self.last_scan = accounts
        if not accounts:
            logger.warning('验号：一个 SSR 都没读到')
            return False

        # ❗目标来自 GUI（`Starsavior2.Target` + `Target2`~`Target7`，最多 7 只），
        #   不再读 `config/state` 里那份 json：全都留「不指定」就**不做达标判定**，
        #   只把这一轮的号记下来（跑完就停、不重置）。
        targets = self.targets or []
        if not targets:
            logger.info('验号：没有设置目标角色，这一轮只做记录')
            self.save_scan(accounts)
            self.target_hit = False
            logger.info('验号：读到 %d 个 SSR' % len(accounts))
            return True

        hit, detail = check_targets(accounts, targets, self.target_mode)
        self.save_scan(accounts)
        logger.info('验号：读到 %d 个 SSR' % len(accounts))
        for row in detail:
            logger.info('验号目标 %s：需要 %d 只，实际 %d 只 → %s'
                        % (row['label'], row['need'], row['got'],
                           '凑够' if row['hit'] else '不够'))
        self.target_hit = hit
        self.target_detail = detail
        if hit:
            logger.info('验号：%s，这一轮停在号上不重置'
                        % ('任意一个角色凑够' if self.target_mode == TARGET_MODE_ANY
                           else '挂上的目标全部凑够'))
        return True

    def save_scan(self, accounts):
        """把这一轮的号记一笔：**只有时间和角色（各几只）**，给人事后翻。

        ❗这份文件**只写不读** —— 达标判定只看 GUI 配置 + 当前这一帧的扫描结果，
          所以 `targets` / `target_detail` / `ssr` / `total` 这些字段脚本自己都用不上，
          删掉（用户 2026-11-07：「无用的话简洁点，就时间，角色，多少只就行」）。
        旧格式（带 targets / characters 是 dict）读进来会顺手归一，
        跑一轮之后整个文件就都是新格式了。

        写到 `config/state/`：那里的东西是**状态**不是配置，
        `config_updater` 不会去覆盖它（`config/*.json` 顶层的会被管）。
        """
        directory = './config/state'
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, 'starsavior_accounts.json')

        log = []
        if os.path.exists(path):
            try:
                with open(path, encoding='utf-8') as f:
                    log = json.load(f)
                if not isinstance(log, list):
                    log = []
            except (ValueError, OSError):
                log = []

        log = [self.compact_scan(row) for row in log]
        log.append({
            'time': time.strftime('%Y-%m-%d %H:%M:%S'),
            'characters': self.format_scan_characters(accounts),
        })
        # 只留最近 SCAN_LOG_LIMIT 轮，别让文件无限长
        log = log[-SCAN_LOG_LIMIT:]

        # 一轮一行，不展开成 indent 那种一大片 —— 翻二十轮只要滚二十行
        with open(path, 'w', encoding='utf-8') as f:
            f.write('[\n')
            f.write(',\n'.join('  ' + json.dumps(row, ensure_ascii=False) for row in log))
            f.write('\n]\n')
        logger.info('验号：已记到 %s（累计 %d 轮）' % (path, len(log)))

    @staticmethod
    def format_scan_characters(accounts):
        """`[{'label': '亚瑟菈@星光华尔兹', 'count': 2}]` → `['亚瑟菈@星光华尔兹 ×2']`。"""
        return ['%s ×%d' % (a.get('label') or a.get('name') or '?', a.get('count') or 1)
                for a in accounts]

    @classmethod
    def compact_scan(cls, row):
        """旧条目（带 targets / target_detail / ssr）压成「时间 + 角色列表」。"""
        if not isinstance(row, dict):
            return {'time': '', 'characters': []}
        chars = row.get('characters') or []
        if chars and isinstance(chars[0], dict):
            chars = cls.format_scan_characters(chars)
        return {'time': row.get('time') or '', 'characters': chars}

    @staticmethod
    def battle_dialog_visible(image):
        """评鉴战右上对话条在不在（见 BATTLE_DIALOG_AREA）。

        真机 2026-11-12 22:36 五帧：空窗 0.001/0.000，第一句 0.857，
        最后一句 0.855，引导结束 0.000。背景、人物、准心、血条都在动，
        所以只看这块固定 UI 的**中性亮色占比**，不做整屏帧差。
        """
        if image is None:
            return False
        x1, y1, x2, y2 = BATTLE_DIALOG_AREA
        area = image[y1:y2, x1:x2]
        gray = area.mean(axis=2)
        diff = area.max(axis=2) - area.min(axis=2)
        neutral = (gray > 160) & (diff < 30)
        return float(neutral.mean()) > BATTLE_DIALOG_NEUTRAL

    @staticmethod
    def auto_battle_started(image):
        """自动战斗开没开：右上「总伤害量」白字出现（见 AUTO_BATTLE_AREA）。

        ❗`E_134_2` 是**开关按钮**，点完不会消失；用 `wait_until_disappear`
        判成功会连点 3 次把开关切回关，评鉴战就停在等待玩家操作。
        ❗评鉴战对话条也是白色，会大面积盖住 AUTO_BATTLE_AREA。引导期间
        必须先判对话，否则 22:04 那样把对话白框误判成「自动战斗已开启」。
        """
        if image is None:
            return False
        if Starsavior2.battle_dialog_visible(image):
            return False
        x1, y1, x2, y2 = AUTO_BATTLE_AREA
        area = image[y1:y2, x1:x2]
        return float((area.mean(axis=2) > 180).mean()) > AUTO_BATTLE_ON

    def wait_auto_battle_start(self, timeout=6):
        """点了 AUTO 之后等战斗真的开始；没开始让 press 按节流重试。

        ❗要**连续两帧**判据成立才算开启：`AUTO_BATTLE_AREA` 很宽，
        评鉴战说明的白字会落进去。真机 2026-11-07 03:38:41 就是单帧
        被说明文字骗成「已开启」，按钮随即 `blocked`，进真战斗后 AUTO
        其实是关的，角色站着不动等到 600 秒超时。
        """
        stable = 0
        for _ in self.loop(timeout=timeout):
            if self.auto_battle_started(self.device.image):
                stable += 1
                if stable >= 2:
                    return True
            else:
                stable = 0
        return False

    def in_battle(self):
        """在不在战斗里：顶部有 BOSS 血条。

        ❗血条是**暗红**，不是鲜红。真机 2026-11-06 23:23 量准：
          血条在 **y=45、x 410~887**，均值 RGB 只有 **(69, 16, 16)**。
          原来判据写 `(r>140)&(g<90)&(b<90)` + 区域 (340,25)-(1000,65)，
          红占比恒为 **0.0000** —— `in_battle` 永远返回 False，教学战的
          「点敌人」分支根本进不去（22:55 那轮就是这么空转的）。
          现在改成暗红判据 + 精确到血条那一条带。

        ❗这条也是挡住"点画面推进对话"的关键：引导本身就有战斗，
        没有它的话"有 SKIP 就点中央"会一路点到战场上
        （用户 2026-11-06 20:00：「点中间会不会吃掉其他的引导判断？」）。
        """
        image = self.device.image
        if image is None:
            return False
        a = image[41:50, 400:900]
        r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
        # ❗0.10 在战斗后期会失效：BOSS 血条被打短之后这条带里只剩 0.0582
        #   （2026-11-07 01:35 的 live_after/live_b 两帧），标题页是 0.0000。
        #   判成"不在战斗"会让兜底「点白圈」一次都不发，press 12 秒就收工，
        #   教学战停在白圈上不动。降到 0.04，和 0 之间仍有足够间隔。
        return float(((r > 55) & (g < 60) & (b < 60) & (r > g * 2)).mean()) > 0.04

    def wait_text(self, ocr, words, timeout=8):
        """等某个区域 OCR 出指定文字。

        这条路（重置）的所有按钮模板真机都是 0.000，只能认字 ——
        「文字在，页面就在」。见 `ocr.py` 里那段注释。
        """
        for _ in self.loop(timeout=timeout):
            text = (ocr.ocr(self.device.image) or '').replace(' ', '')
            for word in words:
                if word in text:
                    return True
        return False

    def reset(self):
        """
        重置服务器账号。

        路径（2026-11-06 19:24~19:47 真机**逐步走通**，每一跳都截图确认过）：

            列表页 → 左上返回 → 主界面
            主界面右上四格菜单 `E_171_1` 中心 → 右侧竖排最下的齿轮 `E_205_1` 中心 (1202, 531)
             → 游戏设定页 → 左侧「账号管理」`E_197_1` 中心 (114, 343)
             → 「重置服务器账号」(835, 366) → 警告弹窗「确认」(735, 468)
            → 输入弹窗：点输入框 (640, 401) → 打「重置服务器账号」→「确认」
            → 标题页

        ❗判据：前三个页面用模板 `E_197_1 / E_198_1 / E_199_1`
          （用户 00:52 给的 page_197~199 截图，离线复验各 1.000）；
          只有**输入弹窗**还用 OCR「请输入」。`RESET_DIALOG` 的框
          (390,278,990,322) 正好框住输入弹窗正文，框不到警告弹窗
          y≈355 的「立即初始化」，所以警告弹窗不能用它认。
          `E_200_1` 输入框是纯色，永远不能当判据。

        ❗中文输入走 `type_text()`（`subprocess` 直调 adb.exe 传 UTF-8 参数），
          `adb_shell(['input','text',...])` 的中文字会全丢。而且**点完输入框
          必须等输入法连上**（`wait_ime_connected`）再打 —— 中文要经过输入法的
          InputConnection 才落到 EditText，连接没好字就蒸发了。23:19 / 00:04 /
          00:22 / 01:10 四次连丢都是这个原因。日志写着「已输入」不算数，
          只认 `read_reset_input` 回读。
        """
        logger.hr('重置账号', level=2)

        # 1. 归位到主界面。
        # ❗**不能无条件点左上 (54,45)**：主界面那个位置是左上头像，点它会打开
        #   「账号个人档案」，后面 (1230,45)/(1220,536) 全点空 —— 真机
        #   2026-11-07 00:45 验号失败后抽卡已把人放回主界面，reset 照样点这一下，
        #   结果进了账号详情（用户：「不知道点了什么点到了左上的账号」）。
        #   判据只用**正面条件**：主界面 = 右上四格 `E_171_1` + 左侧观测
        #   `E_171_3` 同时都在。账号详情页 E_171_1=True 但 E_171_3=False，
        #   菜单页 E_171_3=True 但 E_171_1=False，任务面板两个都 False ——
        #   都能区分，且不用 `not appear`（过渡帧会把负面判据骗成真，R5）。
        def at_hall():
            return (self.appear(E_171_1, offset=(10, 10))
                    and self.appear(E_171_3, offset=(10, 10)))

        for _ in self.loop(timeout=12):
            self.device.screenshot()
            if at_hall():
                logger.info('重置：已经在主界面')
                break
            if self.appear(E_193_1, offset=(10, 10)):
                self.tap_at(54, 45, '子页面 → 主界面')
                self.wait_until_still((0, 0, 1280, 720), timeout=3, threshold=3.0)
                continue
            if self.appear(E_176_2, offset=(10, 10)):
                gx = (E_171_1.area[0] + E_171_1.area[2]) // 2
                gy = (E_171_1.area[1] + E_171_1.area[3]) // 2
                self.tap_at(gx, gy, '菜单页 收起')
                self.wait_until_still((0, 0, 1280, 720), timeout=3, threshold=3.0)
                continue
            if self.appear(E_175_2, offset=(10, 10)):
                # 游戏设定页 / 任务面板这类全屏面板：右上 ✕ 关掉。
                # 真机 00:49 重置失败后停在设定页，从这里自己归位。
                self.click_button(E_175_2, '面板 → 关闭')
                self.wait_until_still((0, 0, 1280, 720), timeout=3, threshold=3.0)
                continue
            # 认不出的页面：不点，交给下一帧重新判，绝不朝内容乱点
        else:
            logger.warning('重置：12 秒没能归位到主界面')
            return False

        # 2. 主界面 → 系统菜单 → 设定页
        # ❗点 `E_171_1` 的**中心**，不要写死 (1230, 45)：那个位置在四格按钮框的
        #   右下角，实际可点区域比框小，真机 2026-11-07 12:49/12:52 连撞两次
        #   —— (1230,45) 点空、菜单没开，紧接着 (1220,536) 把刚开的面板关掉，
        #   `wait_until_appear(E_197_1)` 白等 10 秒判「进不了设定页」。
        #   (1222, 37) 实测能开（12:53 手点复验）。
        self.tap_at((E_171_1.area[0] + E_171_1.area[2]) // 2,
                    (E_171_1.area[1] + E_171_1.area[3]) // 2, '系统菜单')
        # 等网格展开动画走完；不等的话下一枪会点在菜单还没铺开的地方
        self.wait_until_still((900, 60, 1280, 700), timeout=3, threshold=4.0)
        # ❗齿轮点 **`E_205_1` 的 area 中心 (1202, 531)**，不再写死坐标。
        #   以前写 (1220, 536)，偏右 18 像素、正好落在齿轮右边的空白上，
        #   点完页面纹丝不动（真机 2026-11-07 14:17 整轮重置失败）。
        #   素材是用户 14:18 重新导出的 `E_205_1.png`，图标 bbox 离线量过：
        #   x 1190~1215 / y 518~545。`click_button()` 钉的是 area 中心 ——
        #   用户反复强调的那句「所有的点击都点中间」（00:46、14:18）。
        #
        # ❗**点一下没反应就接着点**，不是点一次干等 10 秒：菜单展开动画、
        #   商店红点 / 活动弹窗都可能把第一下吞掉（用户 14:20：「而且只点了
        #   一次，页面没变的话，应该反复点击」；硬约束 153）。2 秒节流，
        #   15 秒里最多点 7 次。
        clicked = 0
        last_click = 0
        for _ in self.loop(timeout=15):
            if self.appear(E_197_1, offset=(10, 10)):
                break
            # 齿轮露出来了（菜单铺开）才点；还没露出来就只等，不点
            if self.appear(E_205_1, offset=(10, 10)):
                if time.time() - last_click >= 2:
                    self.click_button(E_205_1, '设定')
                    last_click = time.time()
                    clicked += 1
        else:
            # ❗用模板 `E_197_1` 判「进没进设定页」，不用 OCR：暗灰「账号管理」
            #   常被读成「号管理」（首字被左边圆图标吃掉），真机 00:49 明明
            #   在设定页却连读 10 秒判「进不了」。
            logger.warning('重置：进不了游戏设定页（点了 %d 次「设定」）' % clicked)
            return False

        # 3. 左侧「账号管理」——`E_197_1` 就是这个页签（83x28 正好框住四个字），
        #    点它的中心 (114, 343)，别再用写死的 (100, 345)（偏左 14px）。
        self.click_button(E_197_1, '账号管理页签')
        # `E_198_1` 在账号管理页 1.000、设定页 0（00:52 离线复验）；
        # 比 OCR 认「重置服务器账号」稳，且不受按钮亮暗影响。
        if not self.wait_until_appear(E_198_1, offset=(10, 10), timeout=10):
            logger.warning('重置：没进账号管理页')
            return False

        # 4. 「重置服务器账号」→ 警告弹窗 → 确认
        self.tap_at(835, 366, '重置服务器账号')
        # ❗警告弹窗用 `E_199_1`（蓝确认按钮，1.000）认，不用 OCR：
        #   `RESET_DIALOG` 的框 (390,278,990,322) 是为**输入弹窗**的
        #   「请输入…」正文画的，而警告弹窗「立即初始化」在 y≈355，
        #   框里只有空白 → 真机 00:51 连读 10 秒全是噪声 'l'。
        #   输入弹窗那一步继续用 OCR「请输入」（位置正好在框里）。
        if not self.wait_until_appear(E_199_1, offset=(10, 10), timeout=10):
            logger.warning('重置：没有等到警告弹窗')
            return False

        self.tap_at(735, 468, '确认重置')
        # 等输入弹窗的深灰输入框（见 `reset_input_ready`），不用 OCR。
        for _ in self.loop(timeout=10):
            self.device.stuck_record_clear()
            if self.reset_input_ready(self.device.image):
                break
        else:
            logger.warning('重置：没有等到输入确认语的弹窗')
            return False

        # 5~6. 输入确认语（验收字真的进去了才点确认）→ 回标题页
        return self.finish_reset_input()
