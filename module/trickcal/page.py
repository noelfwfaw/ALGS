"""Page graph of 嘟嘟脸恶作剧 (Trickcal).

Eight pages: the lobby, the mailbox, the friend list, the two task tabs
(daily / weekly), the 尊享商店, the 普通商店 and the 冒险通行证. The login flow is a button-driven chain
(`TrickcalLogin`), not a page graph, because the exported card spec has no
`exits` at all - every `ui_goto()` edge would be missing and `ui_ensure()` would
wait 60 seconds on a page it can never reach.

`page_friend` is checked with `FRIEND_TITLE`, the 「好友」 header text, not with
the back arrow and not with the bottom buttons. The arrow (24,17)-(66,63) is the
same widget in the same place on the return-event panel, so it scores 1.000
there too and would report the friend list while the event panel is up. The
bottom buttons are worse: **both grey out once they have been used**, and
`appear()` is a colour template match (`Button.match()` on the RGB template),
so 「一鍵發送」 stops matching the moment the send goes through (real frame
2026-11-11 22:04, counter 5/50, score below 0.85) - which is exactly one frame
after the page has been reached, and the page then reads as unknown.

The title is static: 1.000 on the exported frame, 0.990 on the real post-send
frame, and at most 0.353 on the other 20 frames available (return-event panel
0.353, login page 0.345, everything else <=0.18).

`page_main` is checked with the 「剧院」 text band of `E_7_1`, (816,662)-(896,696).
The whole 剧院 button (790,600)-(920,715) used to be the check and it is not
usable any more: the lobby's animated background shows through that box, so a
new real lobby frame (2026-11-11 邮箱.png) scored only 0.488 on it while the
text band scores 0.985. The 34-frame matrix now reads 0.917~1.000 on the seven
lobby frames and at most 0.558 on every other screen, including the mailbox
overlay and the reward popup.

`page_mail` is checked with `MAIL_CLOSE`, the X of the mailbox panel. It has to
be the X and not the mailbox icon or the claim button: the mailbox is a
translucent overlay, the lobby stays visible around it, and both `MAIL_ENTRY`
(0.997) and `MAIL_CLAIM_ALL` (0.925, see `RewardPopup`) keep matching through
the panel. The X is unique to this screen: 1.000 here, <=0.61 everywhere else.

The two task tabs are checked symmetrically by the **inactive** pill of the
other tab: `page_task` uses `TASK_WEEKLY_TAB` (inactive weekly pill,
(63,206)-(174,256)), and `page_task_weekly` uses `TASK_DAILY_TAB` (inactive
daily pill, (48,114)-(148,160)). Each check doubles as the click target to
switch to that other tab, and both tabs are linked bidirectionally so
`ui_ensure(page_task)` works even when clicking `TASK_ENTRY` lands directly on
the weekly tab (when daily tasks are finished and only weekly rewards wait).
The active weekly pill (`TASK_WEEKLY_TAB_ACTIVE`) contains a decorative white
sparkle and green clothespin tip whose crop drifted (`0.799` on real weekly
frames), whereas `TASK_DAILY_TAB` scores `1.000` on real weekly frames and `<=
0.395` everywhere else.

`page_shop` is checked with `SHOP_TITLE`, the 「尊享商店」 header at the top
left. The four tabs are one page and their icons look the same whether they are
selected or not (all three tab frames hit), so a tab can never be the page
check; which tab is open is decided by the cards, in `shop.py`. The header is
gone the moment the item detail opens, which is why `ui_additional()` cancels
that dialog (see `TrickcalUI.ui_additional`).

`page_normal_shop` is checked with `NORMAL_SHOP_TITLE`, the 「商店」 header at
(90,24)-(162,62). It is a **different page** from `page_shop`: different lobby
icon, different title, and a different job (bulk purchase instead of free gift
packs). Measured 0.966~1.000 on five normal-shop frames and at most 0.381 on
every other frame, including the 尊享商店 whose title is 「尊享商店」 at the same
place. Its seven tabs share the page, so the tab is never the page check; which
tab is open is read from the orange highlight (`NORMAL_SHOP_TAB_DAILY`) and the
card grid.

Links are one-way. A new page also has to be added to `TrickcalUI.pages`,
otherwise `ui_get_current_page()` never sees it (hard rule 61).
"""

from module.trickcal.assets import (ADVENTURE_ENTRY, ADVENTURE_TITLE, BACK,
                                   CLASS_ENTRY, CLASS_HUB_CHECK,
                                   CLASS_STAGE_CHECK, COSTUME_PASS_TITLE,
                                   DOLL_ENTRY,
                                   DOLL_HUB_TITLE, DOLL_STAGE_CHECK,
                                   DUNGEON_BAKERY_ENTER,
                                   DUNGEON_BAKERY_ENTRY,
                                   DUNGEON_BAKERY_SWEEP, DUNGEON_CANDY_CHOOSE,
                                   DUNGEON_CANDY_ENTRY, DUNGEON_CANDY_SWEEP,
                                   DUNGEON_CLONE_ENTER, DUNGEON_CLONE_ENTRY,
                                   DUNGEON_CLONE_SWEEP, DUNGEON_CRAYON_ENTER,
                                   DUNGEON_CRAYON_ENTRY,
                                   DUNGEON_CRAYON_SELECT_DECK, DUNGEON_ENTRY,
                                   DUNGEON_GOLD_ENTER, DUNGEON_GOLD_ENTRY,
                                   DUNGEON_GOLD_SWEEP, DUNGEON_HUB_TITLE,
                                   E_7_1, EVENT_ACHIEVEMENT_ENTRY,
                                   EVENT_BATTLE_ENTRY, EVENT_PASS_CHECK,
                                   EVENT_SHOP_ENTRY, EVENT_SHOP_TITLE,
                                   EVENT_STAGE_TITLE, EVENT_STORY_ENTRY,
                                   EVENT_STORY_TITLE, EVENT_TASK_TITLE,
                                   FRIEND_ENTRY, FRIEND_TITLE, HOME,
                                   MAIL_CLOSE, MAIL_ENTRY, NORMAL_SHOP_ENTRY,
                                   NORMAL_SHOP_TITLE, ORDER_CHECK,
                                   ORDER_ENTRY, ORDER_RELIC_TITLE, PASS_ENTRY,
                                   PASS_TITLE, PVP_ARENA_ENTER, PVP_ARENA_TITLE,
                                   PVP_ENTRY, PVP_GO_WIN, PVP_HUB_TITLE,
                                   SHOP_ENTRY, SHOP_TITLE, TASK_DAILY_TAB,
                                   TASK_ENTRY, TASK_WEEKLY_TAB)
from module.ui.page import Page

page_main = Page(E_7_1)
page_mail = Page(MAIL_CLOSE)
page_friend = Page(FRIEND_TITLE)
# 任务两个页签相互用「对面未选中状态的按钮」判页：停在每日时「一周」未选中
# (`TASK_WEEKLY_TAB`)，停在每周时「一天」未选中 (`TASK_DAILY_TAB`)，同时就是切页按钮。
page_task = Page(TASK_WEEKLY_TAB)
page_task_weekly = Page(TASK_DAILY_TAB)
# 商店的四个 tab 是同一个页面：左侧那排 tab 图标选没选中长得一样（三个 tab 帧上
# 都能命中），所以页面判据只能用左上角「尊享商店」标题，tab 靠卡片区分。
page_shop = Page(SHOP_TITLE)
# 普通商店是**另一个页面**，不是尊享商店的一部分：入口是大厅底部「商店」图标
# (301,641)-(375,694)，页面判据是左上角「商店」标题。7 个 tab（日常/杂货/战斗宝石/
# 证书/推荐/边境/最佳女主角奖）共用这一页，当前 tab 由左侧橙色高亮区分，见
# `NORMAL_SHOP_TAB_DAILY`。标题实测：普通商店 5 帧 0.966~1.000，尊享商店/大厅/
# 任务/邮箱最高 0.381。
page_normal_shop = Page(NORMAL_SHOP_TITLE)
# 冒险通行证：大厅左侧第二张卡（蓝色票券），页面判据是左上角「冒险通行证」标题。
# 实机 1.000，大厅/商店/任务/邮箱等 ≤0.41。注意别和旁边那张「等级通行证」搞混：
# 那张是日卡，入口在 (20,230)-(110,265)，这个任务只碰 (108,253)-(194,327)。
page_pass = Page(PASS_TITLE)
# 便装通行证：赛季制入口，页面判据为左上角「便装通行证」标题（需排在 page_event_pass 之前）
page_costume_pass = Page(COSTUME_PASS_TITLE)
# 主题剧院活动主页及「战斗」关卡列表页。每期活动名/入口图标会换，大厅进活动走
# `TrickcalEvent.event_open()` 处理固定入口与首次开场剧情弹窗，因此不从 `page_main` 单向连出。
page_event = Page(EVENT_BATTLE_ENTRY)
page_event_stage = Page(EVENT_STAGE_TITLE)
page_event_task = Page(EVENT_TASK_TITLE)
page_event_story = Page(EVENT_STORY_TITLE)
page_event_shop = Page(EVENT_SHOP_TITLE)
page_event_pass = Page(EVENT_PASS_CHECK)

# 冒险 -> 副本及五个资源副本页面图
page_adventure = Page(ADVENTURE_TITLE)
page_dungeon = Page(DUNGEON_HUB_TITLE)
page_dungeon_gold = Page(DUNGEON_GOLD_ENTER)
page_dungeon_gold_stage = Page(DUNGEON_GOLD_SWEEP)
page_dungeon_bakery = Page(DUNGEON_BAKERY_ENTER)
page_dungeon_bakery_stage = Page(DUNGEON_BAKERY_SWEEP)
page_dungeon_candy = Page(DUNGEON_CANDY_CHOOSE)
page_dungeon_candy_stage = Page(DUNGEON_CANDY_SWEEP)
page_dungeon_crayon = Page(DUNGEON_CRAYON_ENTER)
page_dungeon_crayon_stage = Page(DUNGEON_CRAYON_SELECT_DECK)
page_dungeon_clone = Page(DUNGEON_CLONE_ENTER)
page_dungeon_clone_stage = Page(DUNGEON_CLONE_SWEEP)

# 短期速成班页面图（不连固定 `page_class -> page_class_stage` 边，入口卡片按星期与配置决定）
page_class = Page(CLASS_HUB_CHECK)
page_class_stage = Page(CLASS_STAGE_CHECK)

# 娃娃怪破坏者页面图（不连固定 `page_doll -> page_doll_stage` 边，入口电视按种族选项决定）
page_doll = Page(DOLL_HUB_TITLE)
page_doll_stage = Page(DOLL_STAGE_CHECK)

# 巅峰对决（胜利者的竞技场）
page_pvp = Page(PVP_HUB_TITLE)
page_pvp_arena = Page(PVP_ARENA_TITLE)
page_pvp_deck = Page(PVP_GO_WIN)

# 圣团页面图
page_order = Page(ORDER_CHECK)
page_order_relic = Page(ORDER_RELIC_TITLE)

page_main.link(button=MAIL_ENTRY, destination=page_mail)
page_mail.link(button=MAIL_CLOSE, destination=page_main)
page_main.link(button=FRIEND_ENTRY, destination=page_friend)
page_friend.link(button=HOME, destination=page_main)
page_main.link(button=TASK_ENTRY, destination=page_task)
page_task.link(button=TASK_WEEKLY_TAB, destination=page_task_weekly)
page_task_weekly.link(button=TASK_DAILY_TAB, destination=page_task)
page_task.link(button=BACK, destination=page_main)
page_task_weekly.link(button=BACK, destination=page_main)
page_main.link(button=SHOP_ENTRY, destination=page_shop)
page_shop.link(button=HOME, destination=page_main)
page_main.link(button=NORMAL_SHOP_ENTRY, destination=page_normal_shop)
page_normal_shop.link(button=HOME, destination=page_main)
page_main.link(button=PASS_ENTRY, destination=page_pass)
page_pass.link(button=BACK, destination=page_main)
page_costume_pass.link(button=HOME, destination=page_main)
page_event.link(button=HOME, destination=page_main)
page_event.link(button=EVENT_BATTLE_ENTRY, destination=page_event_stage)
page_event_stage.link(button=BACK, destination=page_event)
page_event.link(button=EVENT_ACHIEVEMENT_ENTRY, destination=page_event_task)
page_event_task.link(button=BACK, destination=page_event)
page_event.link(button=EVENT_STORY_ENTRY, destination=page_event_story)
page_event_story.link(button=BACK, destination=page_event)
page_event.link(button=EVENT_SHOP_ENTRY, destination=page_event_shop)
page_event_shop.link(button=BACK, destination=page_event)
page_event_pass.link(button=BACK, destination=page_event)

page_main.link(button=ADVENTURE_ENTRY, destination=page_adventure)
page_adventure.link(button=HOME, destination=page_main)
page_adventure.link(button=DUNGEON_ENTRY, destination=page_dungeon)
page_dungeon.link(button=BACK, destination=page_adventure)

page_dungeon.link(button=DUNGEON_GOLD_ENTRY, destination=page_dungeon_gold)
page_dungeon_gold.link(button=BACK, destination=page_dungeon)
page_dungeon_gold.link(button=DUNGEON_GOLD_ENTER, destination=page_dungeon_gold_stage)
page_dungeon_gold_stage.link(button=BACK, destination=page_dungeon_gold)

page_dungeon.link(button=DUNGEON_BAKERY_ENTRY, destination=page_dungeon_bakery)
page_dungeon_bakery.link(button=BACK, destination=page_dungeon)
page_dungeon_bakery.link(button=DUNGEON_BAKERY_ENTER, destination=page_dungeon_bakery_stage)
page_dungeon_bakery_stage.link(button=BACK, destination=page_dungeon_bakery)

page_dungeon.link(button=DUNGEON_CANDY_ENTRY, destination=page_dungeon_candy)
page_dungeon_candy.link(button=BACK, destination=page_dungeon)
page_dungeon_candy_stage.link(button=BACK, destination=page_dungeon_candy)

page_dungeon.link(button=DUNGEON_CRAYON_ENTRY, destination=page_dungeon_crayon)
page_dungeon_crayon.link(button=BACK, destination=page_dungeon)
page_dungeon_crayon.link(button=DUNGEON_CRAYON_ENTER, destination=page_dungeon_crayon_stage)
page_dungeon_crayon_stage.link(button=BACK, destination=page_dungeon_crayon)

page_dungeon.link(button=DUNGEON_CLONE_ENTRY, destination=page_dungeon_clone)
page_dungeon_clone.link(button=BACK, destination=page_dungeon)
page_dungeon_clone.link(button=DUNGEON_CLONE_ENTER, destination=page_dungeon_clone_stage)
page_dungeon_clone_stage.link(button=BACK, destination=page_dungeon_clone)

page_adventure.link(button=CLASS_ENTRY, destination=page_class)
page_class.link(button=BACK, destination=page_adventure)
page_class_stage.link(button=BACK, destination=page_class)

page_adventure.link(button=DOLL_ENTRY, destination=page_doll)
page_doll.link(button=BACK, destination=page_adventure)
page_doll_stage.link(button=BACK, destination=page_doll)

page_adventure.link(button=PVP_ENTRY, destination=page_pvp)
page_pvp.link(button=BACK, destination=page_adventure)
page_pvp.link(button=PVP_ARENA_ENTER, destination=page_pvp_arena)
page_pvp_arena.link(button=BACK, destination=page_pvp)
page_pvp_deck.link(button=BACK, destination=page_pvp_arena)
page_main.link(button=ORDER_ENTRY, destination=page_order)
page_order.link(button=HOME, destination=page_main)
page_order_relic.link(button=BACK, destination=page_order)
