"""页面图 of 交错战线 (Cross Core).

One page so far, on purpose: the first feature of this game is "launch it and
reach the main page", and every later task adds its own page plus a `link()`
edge here. A page that is guessed before it has been measured is worse than no
page at all - `ui_goto()` would happily walk through a link that was never
confirmed on the real client.

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

进大厅之前的那几屏（NERI 厂商 logo、交错战线 logo、标题屏、加载中）**不建成
Page**：它们只出现在 `handle_app_boot()` 里，用不带 `link` 的常量判据就够，建了
反而会让 `ui_goto` 以为能从大厅「回去」。
"""

from module.crosscore.assets import MAIN_NAV_BAR
from module.ui.page import Page

page_main = Page(MAIN_NAV_BAR)
