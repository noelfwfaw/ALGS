"""页面图 of 交错战线 (Cross Core).

- `page_main` —— 主界面（大厅）。判据是**底部那排页签**（基地 / 任务 / 编队 /
  队员），一条 358x38 的横条：

  实机量的相似度（2026-11-04，冷启动 + 大厅 + 各二级页）：
  大厅两帧 1.000，公告弹窗盖在上面时 0.998，标题屏 0.359、签到页 0.275、
  基地建设页 0.345 —— 0.85 的默认阈值两边都留得下余量。

  为什么不用别的：
  - 左上角头像 /「教学大纲」跟着等级和活动变；
  - 顶部那排资源是数字，天天在变；
  - 右下角圆形「出击」中间写着当前关卡（实测 4-9），关卡会动；
  - 底部「基地」页签**不是**大厅：点它进的是基地建设（等距地图），有它自己
    的返回箭头，所以那排页签只在真正的大厅里画出来。

- `page_mail` / `page_task` —— 邮箱页 / 任务页（2026-11-08 加的）。

  两个页面里**没有一块会随状态变**的东西：邮箱页的一键领取会变暗，任务页的
  一键领取会变暗、页签会切换。所以判据都用「一键领取的亮/暗两张模板，任一
  命中」。两张模板互相比只有 0.63 / 0.85，同一页的两态刚好都能覆盖，而两张
  模板在对方的页面上、在大厅上都不命中。

- `page_pass` —— 通行证页（勘探指南，2026-11-08 加的）。两个判据：右上角「任务」
  按钮（弹窗打开时被弹窗盖住，1.000 → 0.285）和「勘探任务」弹窗标题（只在弹窗打开
  时出现）。任一命中就算在本页，于是任务中途停在弹窗里时，`ui_goto` 也能从这里
  走 `BOOT_BACK` 回大厅，而不是空转。

  基地建设页**没有**建成 Page：它的进入/退出都由 `base.py` 直点（`MAIN_GOTO_BASE`
  进、`BOOT_HOME` 出），中间还有一张等距地图和三个面板，跟页签图也对不上。

进大厅之前的那几屏（NERI 厂商 logo、交错战线 logo、标题屏、加载中）**不建成
Page**：它们只出现在 `handle_app_boot()` 里，用不带 `link` 的常量判据就够，建了
反而会让 `ui_goto` 以为能从大厅「回去」。
"""

from module.crosscore.assets import (BOOT_BACK, MAIL_CLAIM, MAIL_CLAIM_DIM,
                                     MAIN_MAIL, MAIN_NAV_BAR, MAIN_TASK,
                                     PASS_ENTRY, PASS_POPUP, PASS_TASK,
                                     TASK_CLAIM, TASK_CLAIM_DIM)
from module.ui.page import Page

page_main = Page(MAIN_NAV_BAR)
page_mail = Page([MAIL_CLAIM, MAIL_CLAIM_DIM])
page_task = Page([TASK_CLAIM, TASK_CLAIM_DIM])
page_pass = Page([PASS_TASK, PASS_POPUP])

page_main.link(button=MAIN_MAIL, destination=page_mail)
page_main.link(button=MAIN_TASK, destination=page_task)
page_main.link(button=PASS_ENTRY, destination=page_pass)
page_mail.link(button=BOOT_BACK, destination=page_main)
page_task.link(button=BOOT_BACK, destination=page_main)
page_pass.link(button=BOOT_BACK, destination=page_main)
