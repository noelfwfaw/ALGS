"""页面图 of 卡厄思梦境 (Chaos Zero Nightmare).

One page so far, on purpose: the first feature of this game is "launch it and
reach the main page", and every later task adds its own page plus a `link()`
edge here. A page that is guessed before it has been measured is worse than no
page at all - `ui_goto()` would happily walk through a link that was never
confirmed on the real client.

- `page_main` —— 主界面（大厅）。两条判据同时挂在页面上：

  1. 右侧竖排菜单第一项「故事」。它是整页里唯一一段固定文字 ——
     别的文案都带状态（等级、体力、「完成第5章」「待處理的政策 8」）。
  只留这一条。原先还挂了右上角那颗「三条横线」，**那是错的**：它是顶栏的全局
  按钮，模擬页、配置队伍页上都有；`check_button` 又是"任一命中"，于是脚本在
  模擬页上也会认为"我在主界面"，然后对着主界面才有的入口一路空点（2026-10-30
  实测撞到 `GameTooManyClickError`）。

  实机量的相似度（2026-10-30，冷启动 + 闲置立绘两组截图）：大厅四条帧
  0.99~1.00，标题屏 0.22 / 0.31，全屏立绘（闲置）0.12 / 0.15 —— 0.85 的
  默认阈值两边都留得下余量。

进大厅之前的那几屏（厂商 logo、修補版本、标题、连接失败）**不建成 Page**：
它们都只出现在 `handle_app_boot()` 里，用不带 `link` 的常量判据就够，建了反而
会让 `ui_goto` 以为能从大厅「回去」。
"""

from module.chaoszero.assets import MAIN_MENU_STORY
from module.ui.page import Page

page_main = Page(MAIN_MENU_STORY)
