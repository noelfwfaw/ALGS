"""
页面图（page graph）of 棕色尘埃2.

还没有素材，所以这个文件里没有任何 `Page`。等素材到位后按下面的形状写：

    page_main = Page(MAIN_BTN_XXX)          # 一个在任何状态都画着的按钮/标题
    page_some = Page(SOME_TITLE)
    page_main.link(button=MAIN_BTN_SOME, destination=page_some)
    page_some.link(button=SOME_BTN_CLOSE, destination=page_main)

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
