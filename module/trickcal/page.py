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

The two task tabs are checked with **the same box in its two states**, the
weekly pill (63,206)-(174,256): unselected on the daily tab, purple on the
weekly one. That is the same geometry as the button that switches between them,
so a stale frame can never point a click at the wrong widget, and both states
are positive checks - a tab switch is never verified with "the old tab is
gone". Measured 1.000 in its own state and below 0.85 in the other.

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

from module.trickcal.assets import (BACK, E_7_1, FRIEND_ENTRY, FRIEND_TITLE,
                                   MAIL_CLOSE, MAIL_ENTRY, NORMAL_SHOP_ENTRY,
                                   NORMAL_SHOP_TITLE, PASS_ENTRY, PASS_TITLE,
                                   SHOP_ENTRY, SHOP_TITLE, TASK_ENTRY,
                                   TASK_WEEKLY_TAB, TASK_WEEKLY_TAB_ACTIVE)
from module.ui.page import Page

page_main = Page(E_7_1)
page_mail = Page(MAIL_CLOSE)
page_friend = Page(FRIEND_TITLE)
# 进任务页默认停在每日任务，所以「周任务 tab 还没选中」就是每日任务的判据。
page_task = Page(TASK_WEEKLY_TAB)
page_task_weekly = Page(TASK_WEEKLY_TAB_ACTIVE)
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

page_main.link(button=MAIL_ENTRY, destination=page_mail)
page_mail.link(button=MAIL_CLOSE, destination=page_main)
page_main.link(button=FRIEND_ENTRY, destination=page_friend)
page_friend.link(button=BACK, destination=page_main)
page_main.link(button=TASK_ENTRY, destination=page_task)
page_task.link(button=TASK_WEEKLY_TAB, destination=page_task_weekly)
page_task.link(button=BACK, destination=page_main)
page_task_weekly.link(button=BACK, destination=page_main)
page_main.link(button=SHOP_ENTRY, destination=page_shop)
page_shop.link(button=BACK, destination=page_main)
page_main.link(button=NORMAL_SHOP_ENTRY, destination=page_normal_shop)
page_normal_shop.link(button=BACK, destination=page_main)
page_main.link(button=PASS_ENTRY, destination=page_pass)
page_pass.link(button=BACK, destination=page_main)
