"""界面层 of 卡厄思梦境 (Chaos Zero Nightmare).

游戏信息（都在本机确认过）：

- 包名 `com.smilegate.chaoszero.stove.google`，`adb shell pm list packages` 读出来的。
  中文社区也写作「卡厄思梦镜」，同一个客户端。
- 横屏 **1280x720**。模拟器的物理尺寸报的是 720x1280 竖屏，游戏自己旋转成横屏，
  `screencap` 出来就是 1280x720，跟另外三个游戏同尺寸，设备层不需要旋转支持。

冷启动长这个样子（2026-10-30 实机，`dev_tools/probe_chaoszero_boot.py` 拍的）：

    黑屏 → Smilegate / SUPER CREATIVE 两个 logo
         → 标题页，左下角「▶▶ 正在驗證修補版本」（校验补丁，会停几十秒）
         → 标题页 + 「TOUCH TO START」+ 左下「資源修復」+ 右侧地球/齿轮/客服/退出
             ↳ 连不上服务器时弹一条白带「遊戲連接失敗，請重新連接。」，
               底下的提示变成「▽ 點擊屏幕」；这条白带上**没有按钮**，
               点画面任意处就重连（见 `handle_connect_failed()`）
         → 点 TOUCH TO START → 黑屏约 1 秒 → 主界面

主界面是一个带 live2D 角色的场景：左上「等級 / 名字 / 经验条」，顶部一排资源，
右侧竖排菜单（故事 / 出征 / 模擬 / 卡厄思 / 方舟都市 / 戰鬥員 / 救援），
底部聊天条和当期活动横幅。角色会冒白色对话气泡（轮换的闲聊，不用管）。

**闲置约 20 秒后，游戏会把整个 UI 收起来只剩一张全屏立绘**，点一下才回来。
那不是崩溃也不是切页，`handle_app_boot()` 里有一支专门处理它 —— 否则脚本会在
"什么都不认识"的循环里转到超时。

`app_start()` 只负责"从任何一屏走到主界面"。登录奖励、签到面板这些还没实测到，
等真机跑过一天再往里加，不预先猜。
"""

from module.base.button import Button
from module.base.timer import Timer
from module.chaoszero.assets import BOOT_CONNECT_FAILED, BOOT_TOUCH_START
from module.chaoszero.page import page_main
from module.exception import GameStuckError
from module.logger import logger
from module.ui.ui import UI

# 点画面中间那一下用的坐标。标题页、连接失败提示、闲置立绘这三种屏都吃
# "点任意处"，而画面正中永远不会落在「資源修復」或右上角那排系统键上。
CHAOSZERO_TAP_CENTRE = Button(area=(540, 300, 740, 420), color=(0, 0, 0),  # alas-lint: allow - a point to tap, there is no image to match
                              button=(540, 300, 740, 420), name='CHAOSZERO_TAP_CENTRE')

# 冷启动到主界面：实机 logo + 校验补丁 + 标题约 25 秒。留到 5 分钟是为了
# 客户端更新后第一次启动要校验整个补丁包，那一步能停一两分钟。
CHAOSZERO_BOOT_TIMEOUT = 300

# "什么都不认识"时隔多久点一下画面。闲置立绘只认得出"没有 UI"，没有正面判据，
# 所以这个节流就是它的处理方式；8 秒足够让游戏的转场动画先走完。
CHAOSZERO_TAP_INTERVAL = 8


class ChaoszeroUI(UI):
    """
    UI class of 卡厄思梦境.
    """

    page_main = page_main

    # 自己那套页面。`Page.all_pages` 是全局注册表，多游戏场景下必须只遍历
    # 本游戏的（硬约束 36），否则切到别的游戏后匹配本游戏的判据会 KeyError。
    pages = (page_main,)

    def app_start(self):
        """
        Launch the game and walk through the boot screens until page_main.

        A running game is not launched again - `app_start` only brings it to the
        front - so the loop starts from whatever is on screen: the title screen
        (normal cold start), the connection-failure dialog, or the idle
        full-screen artwork the game falls into after ~20 seconds of no input.

        Pages:
            in: any
            out: page_main
        """
        if self.device.app_is_running():
            logger.info('Game is already running, bring it to the front')
        self.device.app_start()
        self.handle_app_boot()

    def handle_app_boot(self, skip_first_screenshot=True):
        """
        Walk the boot screens until the lobby is on screen.

        The order of the checks is the order the screens appear in:

        1. A lobby ends the loop - the right-hand menu is drawn, nothing else is.
        2. 「遊戲連接失敗」 before the title check: the dialog is drawn on top of
           the title screen, and its only key is "tap anywhere". Checking the
           title first would keep tapping a screen that is behind the dialog.
        3. 「TOUCH TO START」 is the only thing that takes the client inside.
        4. Anything left (logo splash, patch validation, the black frame after
           the tap) is waited out; the idle artwork is the one screen here that
           needs a tap, and it has no positive check point at all - see
           `CHAOSZERO_TAP_INTERVAL`.

        Pages:
            in: any
            out: page_main

        Returns:
            bool: True if page_main is reached.

        Raises:
            GameStuckError: If the lobby is not reached in time.
        """
        logger.hr('App boot', level=2)
        timeout = Timer(CHAOSZERO_BOOT_TIMEOUT, count=3).start()
        # 未启动的 Timer 第一次 reached() 就是 True，第一次不用干等。
        tap = Timer(CHAOSZERO_TAP_INTERVAL)

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
                if not self.device.has_cached_image:
                    self.device.screenshot()
            else:
                self.device.screenshot()

            # A cold start is a minute of static screens and another of patch
            # validation, and none of it is pressed: `Device` reads "nothing
            # clicked for 60 seconds" as a hang (hard rule 13). `timeout` below
            # is what ends a boot that really is stuck.
            self.device.stuck_record_clear()

            # End
            if self.ui_page_appear(page_main):
                logger.info('Game is at page_main')
                return True

            # Connection failure, also handled from `ui_additional()` because
            # the client raises it in the middle of a task as well.
            if self.handle_connect_failed():
                continue

            # Title screen
            if self.appear_then_click(BOOT_TOUCH_START, offset=(20, 20), interval=3):
                logger.info('Title screen, touch to start')
                continue

            # 什么都不认识。这里可能是 logo、补丁校验、点完之后的黑屏，或者
            # 闲置立绘 —— 前三者点了没反应，后者点了就回主界面，所以点一下是
            # 唯一安全的动作；节流由 `tap` 负责，点击记录每轮清一次，不然同一
            # 个"按钮"点满 12 次会撞 `GameTooManyClickError`。
            if tap.reached():
                tap.reset()
                logger.info('Unknown screen, tap the centre')
                self.device.click_record_clear()
                self.device.click(CHAOSZERO_TAP_CENTRE)  # alas-lint: allow - tapping an unknown screen on purpose, there is no button to verify against
                continue

            if timeout.reached():
                logger.warning('Wait game boot timeout')
                raise GameStuckError(
                    'Game did not reach page_main after launch. '
                    'If the connection-failure dialog kept coming back, the emulator has no network '
                    'to the game server.')

    def handle_connect_failed(self):
        """
        Dismiss 「遊戲連接失敗，請重新連接。」 by tapping the screen.

        The dialog has no button: it is a full-width strip with one line of text
        and a 「▽ 點擊屏幕」 hint at the bottom of the title screen, and the tap
        is what makes the client redial the server. It shows up on a cold start
        (the client gives up before the patch server answers) and, like the
        store dialog in 棕色尘埃2, it can come back at any time - so the handler
        is wired into `ui_additional()` as well.

        Similarity stays at the default 0.85: the template is the white strip
        with its one line of text, matched 1.00 on its own screenshot and at
        most 0.13 on the other screens of the boot (splash / title / lobby /
        idle artwork).

        Returns:
            bool: If the dialog was on screen (and the screen was tapped).
        """
        if self.appear(BOOT_CONNECT_FAILED, offset=(20, 20), interval=3):
            logger.info('Connection failed, tap the screen to retry')
            self.device.click(BOOT_CONNECT_FAILED)
            # 点完要验收（硬约束 79）：这条白带上没有按钮，"它下去了"就是唯一的
            # 证据。客户端重连要一两秒，所以给 5 秒而不是 3 秒、settle 要 2 帧；
            # 还没下去就交给下一轮（`interval=3` 会再点一次），这里只记一笔。
            if not self.wait_until_disappear(BOOT_CONNECT_FAILED, offset=(20, 20),
                                             timeout=5, settle=2):
                logger.warning('The connection dialog is still there, the client is still dialling')
            return True

        return False

    def ui_additional(self):
        """
        Handle the popups that can show up on any page.

        Only one family so far: the connection-failure strip, which the client
        raises whenever it loses the server - on the title screen, and in the
        middle of a task.

        Returns:
            bool: If handled.
        """
        if self.handle_connect_failed():
            return True

        return False
