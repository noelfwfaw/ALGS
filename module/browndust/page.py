"""
页面图 of 棕色尘埃2.

Seven pages so far, all measured on the 2026-10-28 screenshots:

- `page_map` —— 游戏每天第一次启动落地的地方。检查点就是右上角那个白色房子按钮，
  它同时也是"进主页面"的入口，所以一个素材干两件事（判地图页 + 点它进大厅）。
- `page_main` —— 大厅。检查点是左上角的「我的小屋」图标。
- `page_summon` —— 抽抽乐。检查点是卡池面板右上角那行「查看概率」：每期卡池都会换
  名字和立绘，只有这行 UI 文字不变；抽卡动画和结果展示页上它不在
  （实测 0.11 / 0.26，而卡池页 0.93~1.00），所以它同时是"抽完了没有"的判据。
- `page_hunt` —— 快速狩猎。见下面 `page_hunt`。
- `page_mail` —— 邮箱。见下面 `page_mail`。
- `page_task` —— 任务（每日/每周）。见下面 `page_task`。
- `page_pass` —— 通行证。见下面 `page_pass`。

为什么 `page_main` 要两条判据同时成立（`BrowndustUI.ui_page_appear`）：大厅每天压着
七八个弹窗，弹窗是一层全屏半透明黑遮罩。模板匹配对整体变暗不敏感，遮罩下照样
0.80~0.97，所以"模板匹配上了"只说明**背后是大厅**，不说明没被盖住；
"被没被盖住"看右上角那枚图标还亮不亮（`ui_lobby_shaded()`：干净 372~450 个
luma>200 的像素，8 张弹窗截图全是 0）。

也别回到"比区域平均色"那条路（2026-10-28 踩过）：大厅壁纸每次进场都可能换一张，
实机已经见过亮粉、暗紫、亮蓝、奶油白四种，壁纸能把 `MAIN_HOME_ICON` 的平均色
从 (107,106,109) 拉到 (200,202,204)，于是干净的大厅被判成"被遮罩压着"，
脚本一路点空白，等壁纸自己变回来。

三条必须守住的规则，都是另外两个游戏实机踩出来的：

1. **检查点要能在整页里唯一命中**，优先选带文字的面板标题。亮暗两态的按钮
   不可靠（通行证、竞技场赛季面板都栽过），优先「按下去会不会弹窗」或者
   「只有这一页才有的文字」。
2. **弹窗只盖住中间时，被盖住的页面照样 1.00**。所以「页面还在」永远不能当成
   「按压被接受了」的证据（硬约束 79）。
3. `link()` 只写一遍：一个按钮对应一个目的地。同一屏的两个阶段（比如结果页的
   「查看全部」和「确认」）分别建 Page，都 link 回同一个上一级，
   这样 `ui_goto` 从任何一阶段都能走回家。

`BrowndustUI.pages` 要把这里的页面全部列一遍，顺序即匹配顺序（先特殊后通用）。
"""
from module.base.button import Button
from module.browndust.assets import (HUNT_BUTTON, HUNT_ENTRY, MAIL_CLAIM, MAIL_ENTRY,
                                     MAIN_HOME_ICON, MAP_HOME_BTN, PASS_ENTRY,
                                     PASS_TITLE, SUMMON_BANNER, SUMMON_ENTRY,
                                     TASK_CLAIM_ALL, TASK_ENTRY)
from module.ui.page import Page

page_map = Page(MAP_HOME_BTN)
page_summon = Page(SUMMON_BANNER)
# 快速狩猎。检查点是右下角那个「快速狩猎」按钮 —— 它在大厅、抽抽乐、纯地图上
# 都是 0.26~0.29，只在快速狩猎的四个页签上 1.00。
#
# 但它在**弹窗和结算页上也 1.00**：这两层都是半透明覆盖，底下的按钮还看得见。
# 所以「已到这一页」必须再加一条"没有盖着东西"，见
# `BrowndustUI.ui_hunt_clean()`。
page_hunt = Page(HUNT_BUTTON)
page_main = Page(MAIN_HOME_ICON)
# 邮箱。检查点是右下角那个「全部领取」按钮 —— 它在别的页 0.34~0.60，在邮箱页
# 0.95~1.00（领空了也还有 0.95，形状不变只变灰，所以这个按钮能当检查点，
# 只是不能当"还有没有邮件"的判据，那个要数亮度，见 `mail.py`）。
#
# 它同样会在 REWARD 结算页上命中（0.945），因为结算页是半透明覆盖。所以
# "已到邮箱页"必须再加一条"没有结算页盖着"，见 `BrowndustUI.ui_reward_clean()`。
page_mail = Page(MAIL_CLAIM)
# 任务（每日/每周）。检查点是右下角那个「全部获得」按钮 —— 它在两个任务页签上
# 都是 1.00，在大厅 0.62、邮箱 0.57、快速狩猎 0.73、抽抽乐 0.46，唯一的干扰是
# 经营管理面板（0.81，面板自己那块「一键获得」），而那个面板根本不在 `pages` 里。
#
# 它跟邮箱那个按钮一样有"亮/灰"两态（领完了变灰），所以它能当检查点，不能当
# "还有没有奖励可领"的判据 —— 那个判据在 `task.py` 里数亮度。
page_task = Page(TASK_CLAIM_ALL)
# 通行证。检查点是页面左上角那行「通行证」标题（图标 + 文字）—— 通行证本身每期
# 都换（名字、立绘、数量），只有这行 UI 文字不变。它在别的页面上是 0.22~0.53，
# 在自己的页面上 0.99。
#
# 这个检查点**不加"没有被盖住"那一条**（跟邮箱、任务相反）：领完弹的 REWARD
# 是横在中间的条，通行证页确实还在，而且反过来加了那条会让 `ui_goto` 在结算页
# 盖着的时候哪儿都认不出来，一直转到 ui_additional 里去。结算页盖着时点左上角
# 的返回箭头就是"点画面任意处"，会把结算页关掉，下一轮再点一下才真的离开，
# 收敛得比卡住好。判"按钮能不能按"的地方另有 `pass.py` 里的 HUNT_REWARD 检查。
page_pass = Page(PASS_TITLE)

# 地图页右上角那个房子就是大厅入口。它已经是 `page_map` 的检查点，所以这条边
# 等于"在地图页上唯一能按的键"，`ui_goto(page_main)` 会用同一个坐标回家。
page_map.link(button=MAP_HOME_BTN, destination=page_main)

# 抽抽乐页的返回箭头。它没有自己的图案（一个半透明的胶囊加一道箭头，背后的
# 卡池立绘每期都换），所以是纯坐标点击点 —— 只用于回家，不做任何判据。
SUMMON_BACK = Button(area=(124, 24, 152, 56), color=(0, 0, 0),  # alas-lint: allow - a click point on the back arrow, there is no image to match
                     button=(124, 24, 152, 56), name='SUMMON_BACK')

# 大厅底栏「抽抽乐」进、抽抽乐页左上角箭头出。反向边要显式再写一条。
page_main.link(button=SUMMON_ENTRY, destination=page_summon)
page_summon.link(button=SUMMON_BACK, destination=page_main)

# 快速狩猎页的返回箭头。和抽抽乐页的返回键**是同一个位置**（游戏统一的左上角
# 胶囊），所以还是纯坐标点击点：它背后是每次都换的地图画卷，没有稳定图案。
HUNT_BACK = Button(area=(124, 24, 152, 56), color=(0, 0, 0),  # alas-lint: allow - a click point on the back arrow, there is no image to match
                   button=(124, 24, 152, 56), name='HUNT_BACK')

# 大厅右上角「快速狩猎」图标进、快速狩猎页左上角箭头出。
page_main.link(button=HUNT_ENTRY, destination=page_hunt)
page_hunt.link(button=HUNT_BACK, destination=page_main)

# 邮箱页的返回箭头。跟抽抽乐、快速狩猎**同一个位置**（游戏统一的左上角胶囊），
# 所以还是纯坐标：它背后是每次都换的壁纸，没有稳定图案。
MAIL_BACK = Button(area=(124, 24, 152, 56), color=(0, 0, 0),  # alas-lint: allow - a click point on the back arrow, there is no image to match
                   button=(124, 24, 152, 56), name='MAIL_BACK')

# 大厅右上角那个信封图标进、邮箱页左上角箭头出。
page_main.link(button=MAIL_ENTRY, destination=page_mail)
page_mail.link(button=MAIL_BACK, destination=page_main)

# 任务页的返回箭头。跟抽抽乐、快速狩猎、邮箱**同一个位置**（游戏统一的左上角
# 胶囊），所以还是纯坐标：它背后是每次都换的列表内容，没有稳定图案。
TASK_BACK = Button(area=(124, 24, 152, 56), color=(0, 0, 0),  # alas-lint: allow - a click point on the back arrow, there is no image to match
                   button=(124, 24, 152, 56), name='TASK_BACK')

# 大厅底栏「任务」进、任务页左上角箭头出。
page_main.link(button=TASK_ENTRY, destination=page_task)
page_task.link(button=TASK_BACK, destination=page_main)

# 通行证页的返回箭头。跟抽抽乐、快速狩猎、邮箱、任务**同一个位置**（游戏统一的
# 左上角胶囊），所以还是纯坐标：它背后是每期都换的通行证立绘。
PASS_BACK = Button(area=(124, 24, 152, 56), color=(0, 0, 0),  # alas-lint: allow - a click point on the back arrow, there is no image to match
                   button=(124, 24, 152, 56), name='PASS_BACK')

# 大厅右侧竖栏那枚「RETURN / 通行证」图标进、通行证页左上角箭头出。
#
# 入口素材只取圆盘里的票券图案：那枚图标右上角挂着一枚红「!」（"有东西可领"），
# 它经常不在，模板带上它就会在不该失败的时候失败。取整块圆盘也不行 —— 圆盘在
# 壁纸上是低对比度的一大片，`TM_CCOEFF_NORMED` 会在纯色块上虚高（抽抽乐页 0.94、
# 纯黑遮罩 0.99）。所以它只在大厅上被读，别处一律不认。
page_main.link(button=PASS_ENTRY, destination=page_pass)
page_pass.link(button=PASS_BACK, destination=page_main)
