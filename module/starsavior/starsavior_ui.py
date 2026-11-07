"""StarSavior 的界面层。

目前只有一条链条任务在跑（刷初始），而它**不导航**：不管从哪个画面开始，靠逐帧
认按钮往下走，一个都认不到就自己结束。所以这里还没有 `page_main`。

这不是偷懒，是有意留空。`page_main` 的语义是"用这个判据能认出主界面"，而主界面
有两副面孔：

- 引导中的主界面：长得像，但盖着高亮框/气泡/SKIP，点什么都点不动；
- 引导走完的主界面：这时才算能自由操控。

没量过就填一个，`ui_goto_main()` 会在引导途中以为"已经到家了"，然后把整条链条
晾在那儿。宁可让它抛 `GamePageUnknownError`，也不要它走错路。

补的办法（有了"可自由操控的主界面"截图之后）：

1. 在 `dev_tools/spec_editor.html` 里框一个只在主界面出现、引导期间也不变的东西；
2. 生成 `page.py` 里的 `page_main = Page(MAIN_XXX)`；
3. 把下面的模板块取消注释。

    from module.starsavior.page import page_main

    class StarsaviorUI(UI):
        page_main = page_main
        pages = (page_main,)
"""
from module.ui.ui import UI


class StarsaviorUI(UI):
    """StarSavior 的界面层。

    `pages` 留空表示"还没有自己的页面图"。链条任务不调用
    `ui_get_current_page()` / `ui_goto_main()`，所以空着不影响它跑。
    """
    pages = ()
