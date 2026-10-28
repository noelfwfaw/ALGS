"""
棕色尘埃2 (Brown Dust II) 的界面层。

游戏信息（都已在本机确认，不是查来的）：

- 包名 `com.neowizgames.game.browndust2`，`adb shell pm list packages` 读出来的。
- 横屏 **1280x720**。模拟器的物理尺寸报的是 720x1280 竖屏，但游戏自己旋转成
  横屏，`screencap` 出来的就是 1280x720，和另外两个游戏同尺寸，素材可以直接
  在 720p 上框，不用给设备层加旋转支持。
- 启动落在标题页（`BROWN DUST II` 字样 + 左下角两个圆钮），标题页会先弹
  「更新通知」说明当前版本与最新版本，需要点「确认」才能继续。
  这条是 2026-10-28 的实测画面，版本号 2.25.20，商店里已经 2.37.13。

骨架状态：**还没有素材，所以没有任何 Page，`page_main` 留空**。基类的
`page_main` 默认就是 `None`，`ui_goto_main()` 遇到时会抛
`GamePageUnknownError('page_main is not set...')`，是一句能看懂的报错，
不是静默崩，所以空着是安全的，但不是能跑的状态。

第一个任务落地前要按这个顺序补：

1. `assets/browndust/browndust/*.png` —— 素材，用 `dev_tools/serve_asset_maker.bat`
   导出（命名空间和模块都填 `browndust`），再 `button_extract` 生成 `assets.py`。
2. `page.py` —— `Page(check_button)` 声明页面图，再 `link()` 连起来。**页面图的
   形状决定任务怎么写**，而形状来自游戏自己的导航：先进哪个页、从哪个按钮退出。
3. 这里补 `page_main = page_main` 和 `pages = (...)`。`pages` 必须写全本游戏的
   页面：`Page.all_pages` 是进程内共享的注册表，漏写会匹配到别的游戏的页面。
4. `algs.py` 的 `games` 里已经有这一项了，任务方法按
   `def browndust_xxx(self)` 加在同一个游戏段落下。

关于输入通道（待确认，别抄别的游戏）：`LostswordUI.tap_point()` 用
`adb shell input tap` 是因为那个游戏会吞 minitouch 的短按。棕色尘埃2 是否也这样
还没测过，所以这里**先不预置 `tap_point`**，等真的遇到吞点击再加，
不要靠猜。
"""
from module.ui.ui import UI


class BrowndustUI(UI):
    """
    UI class of 棕色尘埃2.

    Nothing is declared yet: a page needs a check point, and a check point
    needs an asset. See the module docstring for the order to fill this in.
    """

    # Set once `module/browndust/page.py` has a home page to point at.
    page_main = None

    # Own pages, in match order. Must list every page of this game once there
    # is more than one: the registry is shared by all games in the process and
    # matching a foreign page raises on every asset lookup.
    pages = ()
