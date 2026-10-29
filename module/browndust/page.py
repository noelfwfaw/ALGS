"""
页面图 of 棕色尘埃2.

Eleven pages so far: the seven below, measured on the 2026-10-28 screenshots,
and the four of the running event, measured on 2026-10-29 (see the end of the
file).

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
from module.browndust.assets import (BATTLE_PANEL, EVENT_ENTRY, EVENT_MISSION_CLAIM,
                                     EVENT_SCHEDULE, EVENT_TAB_MISSION,
                                     EVENT_TAB_SHOP, EVENT_TAB_STORY,
                                     EVENT_TAB_TRACKER, HUNT_BUTTON, HUNT_ENTRY,
                                     MAIL_CLAIM, MAIL_ENTRY, MAIN_HOME_ICON,
                                     MAP_HOME_BTN, PASS_ENTRY, PASS_TITLE,
                                     SHOP_TITLE, STORY_TITLE, SUMMON_BANNER,
                                     SUMMON_ENTRY, TASK_CLAIM_ALL, TASK_ENTRY,
                                     WB_EDIT_TEAM)
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

# ---- 活动（每期换皮的那一套）---------------------------------------------
#
# 活动页。检查点是左上角那枚「行程」按钮：它只在这一页上有 —— 点进去的
# 剧情/战斗/任务几个子页左上角都换成了一行"图标 + 页名"的标题，别的页面上
# 根本没有这枚按钮（剧情列表页 0.50、大厅 0.48，都在 0.85 之下）。
#
# 为什么不用底部那排页签当检查点：它们**只在活动页上出现**没错，但每个页签
# 都是一块红色木牌 + 白字，六块长得几乎是同一张图，认错一格就会点进别的模式。
# 「行程」是唯一的。
page_event = Page(EVENT_SCHEDULE)

# 活动「剧情」页（亲密度剧集列表）。检查点是左上角标题「剧情」。
#
# 它和 `PASS_TITLE`（通行证标题）在**同一个位置、同样大小、同样是"图标+两个字"**，
# 所以专门量了互相的干扰：剧情标题在通行证页 0.480，通行证标题在剧情页 0.500，
# 两边都远在 0.85 之下。这对位置上的近邻是这一层最容易踩的坑，换期重新抠图时
# 要重新量一遍。
page_event_story = Page(STORY_TITLE)

# 活动页的返回箭头。跟其它五页的返回键同一个位置（游戏统一的左上角胶囊），
# 所以还是纯坐标：背后是每期都换的活动主视觉。
EVENT_BACK = Button(area=(124, 24, 152, 56), color=(0, 0, 0),  # alas-lint: allow - a click point on the back arrow, there is no image to match
                    button=(124, 24, 152, 56), name='EVENT_BACK')

# 大厅右侧那面活动横幅。`EVENT_ENTRY` 取的是横幅下面那行小字（这一期是
# 「魔兽追踪者解锁」），它既当检查点也当点击点 —— 实测点它的中心就进活动页，
# 不用再建一个 `.BUTTON`。代价是换期要重新导出这张图，见 skill 8.6。
page_main.link(button=EVENT_ENTRY, destination=page_event)
page_event.link(button=EVENT_BACK, destination=page_main)

# 活动页底部第一块木牌「剧情」。实测点木牌下面的**文字**就能进（不用点上面的
# 图标），所以直接用素材的 area。
page_event.link(button=EVENT_TAB_STORY, destination=page_event_story)

# 剧情页的返回箭头，还是同一个位置。回的是活动页而不是大厅：活动页才是它的
# 上一级，`ui_goto(page_main)` 会顺着这条边再走一步。
STORY_BACK = Button(area=(124, 24, 152, 56), color=(0, 0, 0),  # alas-lint: allow - a click point on the back arrow, there is no image to match
                    button=(124, 24, 152, 56), name='STORY_BACK')
page_event_story.link(button=STORY_BACK, destination=page_event)

# ---- 活动战斗（普通战斗 / 挑战战斗）---------------------------------------
#
# **两个页签共用这一个页面。** 它们的骨架完全一样（左边一列关卡、右边一张详情
# 面板），只有左上角那两个字不一样 —— 而「普通战斗」和「挑战战斗」的标题模板
# 互相能到 0.834，离 0.85 的阈值只有一点余量，拿它当检查点迟早会认错。
#
# 所以检查点取面板里的「通关奖励」：两个模式都 1.000 / 0.991，活动页 0.462、
# 剧情页 0.577、结果页 0.568，安全。
#
# 代价是"当前在普通还是挑战"没法从页面图上看出来，所以切换页签不用 link，
# 由 `event_battle.py` 先 `ui_goto(page_event)` 再点页签。
page_event_battle = Page(BATTLE_PANEL)

# 战斗页的返回箭头，还是同一个位置。回活动页 —— 活动页才是它的上一级。
BATTLE_BACK = Button(area=(124, 24, 152, 56), color=(0, 0, 0),  # alas-lint: allow - a click point on the back arrow, there is no image to match
                     button=(124, 24, 152, 56), name='BATTLE_BACK')
page_event_battle.link(button=BATTLE_BACK, destination=page_event)

# ---- 魔兽追踪者 -----------------------------------------------------------
#
# 检查点是底部那枚「编辑队伍」。它在魔兽页上 1.000 / 0.990，而编辑队伍页自己的
# 标题虽然也写着这四个字，但位置在左上角、字号也小一圈，对不上这块（0.309）；
# 推荐部署面板 0.325、结算页 0.188、活动页 0.123，都远在 0.85 之下。
#
# 为什么不用左上角那行「魔兽」标题：它跟「魔兽练习战斗」的标题只差两个字，
# 而练习战斗是独立的一套阵容和战绩，认错就会进错页。
page_world_boss = Page(WB_EDIT_TEAM)

# 魔兽页的返回箭头，还是同一个位置。回活动页 —— 活动页才是它的上一级。
BOSS_BACK = Button(area=(124, 24, 152, 56), color=(0, 0, 0),  # alas-lint: allow - a click point on the back arrow, there is no image to match
                   button=(124, 24, 152, 56), name='BOSS_BACK')

# 活动页底部第四块木牌进、魔兽页左上角箭头出。
page_event.link(button=EVENT_TAB_TRACKER, destination=page_world_boss)
page_world_boss.link(button=BOSS_BACK, destination=page_event)

# ---- 活动任务（助力任务）--------------------------------------------------
#
# 检查点是右下角那颗「全部领取」。它有两种状态：有奖励可领时亮蓝底白字，领空之后
# 深蓝底灰字 —— 实测模板分 1.000 / 0.960，两态都匹配得上，所以它能当检查点，
# 但不能当"还有没有奖励"的判据，那个在 `event_mission.py` 里数亮度（796 vs 0）。
#
# 位置也帮了忙：邮箱页那颗「全部领取」是同一个胶囊、同样四个字，可它画在
# (1007,642)-(1177,680)，跟这块差着 140 像素，`appear(offset=(30,30))` 搜不到。
# 其它页面（大厅、活动页、魔兽页、结算页）最高 0.404。
page_event_mission = Page(EVENT_MISSION_CLAIM)

# 活动任务页的返回箭头，还是同一个位置。回活动页 —— 活动页才是它的上一级。
MISSION_BACK = Button(area=(124, 24, 152, 56), color=(0, 0, 0),  # alas-lint: allow - a click point on the back arrow, there is no image to match
                      button=(124, 24, 152, 56), name='EVENT_MISSION_BACK')

# 活动页底部第五块木牌进、活动任务页左上角箭头出。
page_event.link(button=EVENT_TAB_MISSION, destination=page_event_mission)
page_event_mission.link(button=MISSION_BACK, destination=page_event)

# ---- 活动商店 -------------------------------------------------------------
#
# 检查点是左上角那行「活动商店」标题（图标 + 文字）。它只在这一页上 —— 活动页
# 0.267、活动任务页和任务页 0.612、魔兽页 0.541，都远在 0.85 之下。
#
# 但它**在购买弹窗底下也是 0.997**：弹窗只是一层半透明遮罩，模板匹配对整体变暗
# 不敏感。所以它回答"在不在商店页"，回答不了"有没有被弹窗盖着" —— 那个由
# `SHOP_BUY_PANEL`（弹窗里那行黄字）自己回答，实测弹窗上 1.000、列表上 0.228。
page_shop = Page(SHOP_TITLE)

# 商店页的返回箭头，跟其它页同一个位置（游戏统一的左上角胶囊），所以还是纯坐标：
# 它背后是每次都换的活动主视觉。
SHOP_BACK = Button(area=(124, 24, 152, 56), color=(0, 0, 0),  # alas-lint: allow - a click point on the back arrow, there is no image to match
                   button=(124, 24, 152, 56), name='SHOP_BACK')

# 活动页底部第六块木牌进、商店页左上角箭头出。
page_event.link(button=EVENT_TAB_SHOP, destination=page_shop)
page_shop.link(button=SHOP_BACK, destination=page_event)
