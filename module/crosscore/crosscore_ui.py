"""界面层 of 交错战线 (Cross Core).

游戏信息（都在本机确认过）：

- 包名 `com.megagame.crosscore`，`adb shell pm list packages` 读出来的。
- 横屏 **1280x720**。模拟器的物理尺寸报的是 720x1280 竖屏，游戏自己旋转成
  横屏，`screencap` 出来就是 1280x720，跟另外四个游戏同尺寸。

冷启动长这个样子（2026-11-04 实机，`dev_tools/probe_crosscore_boot.py` 拍的）：

    黑屏 → 「NERI INFRASTRUCTURE」厂商 logo + LOADING 进度条（0~100%，约 20 秒）
         → 交错战线 logo 动画（约 3 秒）
         → 标题屏：正中「开始游戏」圆环按钮，下面一条服务器选择「交错战线」，
           左下角版本号 3.3.1.13，右侧竖排 设置 / 公告 / 账号 / 修复 / 直播模式，
           底部「我已详细阅读并同意【用户注册协议】…」**默认就是勾上的**
         → 点「开始游戏」→ 标题屏上叠一层「加载中...」（约 8 秒，期间
           「开始游戏」四个字仍然露着）→ 主界面
         → 进主界面的第一次会弹「公告」（活动消息 banner），要关掉

主界面是一个带立绘的大厅：左上头像 +「教学大纲」+ UID，顶部一排资源
（体力 / 货币 / 信用点），左侧竖排活动入口，右侧 充值奖励 / 活动 / 满馈赠礼，
底部一排 基地 / 任务 / 编队 / 队员 / 构建 / 补给站 页签 + 右下角圆形「出击」。

两个别踩的地方：

1. 底部「基地」页签**不是**回到大厅，它进的是基地建设（等距地图）。大厅的
   判据只能是那排页签本身，`page.py` 里写了实机相似度。
2. 标题屏点完「开始游戏」后，加载层并不会盖住那四个字，所以在标题屏上
   **再点一次**是能点到的（会多排一次登录）。`handle_title_start()` 点完就用
   `wait_until_disappear()` 把这一段堵死，别改成 `appear_then_click`。

基地建设页的退出有两副面孔（2026-11-04 实测）：左上角的**返回箭头**会先弹
「是否退出基地？」（点了页面不动，脚本会原地按四十多下），而箭头旁边的
**主页按钮**一步就回大厅。所以 `handle_home()` 排在 `handle_sub_page()` 前面，
「是否退出基地？」本身也留了一个处理分支，万一从别处被弹出来也能出得去。

大厅的弹窗（公告、充值奖励）关闭键**不在同一个位置**（2026-11-08 实测）：
公告是右上角 (1194,80) 的白叉 + 橙尖，充值奖励的 ✕ 在 (1064,137)。所以它们
是两个模板，`handle_lobby_popup()` 按公告 → 充值依次处理。

签到页只在当天首次登录时出现；已经签到过再重启，游戏直接进大厅，只剩公告和
充值奖励两个弹窗。所以签到页是可选分支，认不出来就跳过，不能等。
"""

from module.base.button import Button
from module.base.timer import Timer
from module.crosscore.assets import (BOOT_BACK, BOOT_HOME, BOOT_POPUP_CLOSE,
                                     BOOT_START_GAME, DIALOG_CONFIRM, DIALOG_EXIT_BASE,
                                     E_3_1, E_4_1, E_4_2, E_5_1, E_5_2, E_6_1,
                                     E_6_2, E_7_1, E_7_2)
from module.crosscore.page import page_main, page_mail, page_pass, page_task
from module.exception import GameStuckError
from module.logger import logger
from module.ui.ui import UI

# 冷启动到主界面：实机 logo + 进度条 + 片头约 25 秒，点「开始游戏」到进大厅
# 再约 8 秒。留到 5 分钟是给客户端更新后第一次启动要重下资源包的那一次。
CROSSCORE_BOOT_TIMEOUT = 300

# 点完「开始游戏」到大厅画出来这段时间，「开始游戏」四个字一直露在加载层下面
# （实测 0.99），所以等它消失等于等进大厅。第一次进大厅还要拉公告，给 90 秒。
CROSSCORE_ENTER_TIMEOUT = 90

# 点了没反应时的重试间隔（硬约束 153：点一下没动不算失败，隔两秒再点）。
CROSSCORE_RETRY_INTERVAL = 2

# 大厅长时间不操作会进入待机：立绘和背景还在，**所有图标全部隐藏**，随便点一下
# 才恢复（2026-11-08 用户实测）。那时 page_main 和所有弹窗判据都匹配不上，
# 启动等待会一路空转到超时，所以在「一段时间没有任何已知页面」时补一次点击。
# 点在屏幕正中：片头 / 加载层的点击本来就没有作用，标题屏和已知页面又都先被
# 各自的分支接走了，所以这里只可能是待机画面。
IDLE_WAKE_INTERVAL = 8


class CrosscoreUI(UI):
    """
    UI class of 交错战线.
    """

    page_main = page_main

    # 自己那套页面。`Page.all_pages` 是全局注册表，多游戏场景下必须只遍历
    # 本游戏的（硬约束 36），否则切到别的游戏后匹配本游戏的判据会 KeyError。
    pages = (page_main, page_mail, page_task, page_pass)

    def app_start(self):
        """
        Launch the game and walk through the boot screens until page_main.

        A running game is not launched again - `app_start` only brings it to the
        front - so the loop starts from whatever is on screen: the vendor logo,
        the title screen, or the lobby the game was left on.

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

        1. The lobby ends the loop. It is checked first because a cold start is
           two minutes of screens that only need waiting, and a slow device has
           to be able to leave the loop as soon as the lobby is drawn.
        2. Lobby popups (公告 / 充值奖励) are closed **before** returning: they
           are drawn on top of the lobby, and `page_main` still matches behind
           them (0.998), so "lobby is up" does not mean "lobby is usable".
        3. The 「获得物品」 popup is checked before the panels it is drawn on
           top of: it covers the sign-in page, and the 已签到 button behind it
           matches at 0.998, so a signed-in check running first would press the
           back arrow while the reward is still unclaimed.
        4. The daily sign-in page and the 已签到 panel only show up on the first
           login of the day, so they are optional branches: press 签到, wait for
           the reward popup, then leave the greyed-out panel. On a restart after
           signing in the game skips all three.
        5. 「是否退出基地？」 - the dialog the base-building page raises when it
           is left. It is a dialog, so it comes after the lobby check and before
           everything that is a page.
        6. 「开始游戏」 is the only thing that takes the client inside.
        7. The base page has a home button that goes straight back to the lobby
           (measured: no dialog in between), so it is pressed before the back
           arrow of the shared header.
        8. Anything else with a back arrow in the top left is a secondary page
           (签到 / 任务) the game was left on; walk back out of it.
        9. What is left - the NERI splash, the logo animation, the 加载中
           overlay - is waited out; pressing anything there does nothing.

        Pages:
            in: any
            out: page_main

        Returns:
            bool: True if page_main is reached.

        Raises:
            GameStuckError: If the lobby is not reached in time.
        """
        logger.hr('App boot', level=2)
        timeout = Timer(CROSSCORE_BOOT_TIMEOUT, count=3).start()
        idle = Timer(IDLE_WAKE_INTERVAL).start()

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
                if not self.device.has_cached_image:
                    self.device.screenshot()
            else:
                self.device.screenshot()

            # A cold start is two minutes of static screens and none of it is
            # pressed: `Device` reads "nothing clicked for 60 seconds" as a hang
            # (hard rule 13). `timeout` below is what ends a boot that really is
            # stuck.
            self.device.stuck_record_clear()

            # End
            if self.ui_page_appear(page_main):
                if self.handle_lobby_popup():
                    continue
                if self.handle_item_popup():
                    continue
                logger.info('Game is at page_main')
                return True

            # Popup over the lobby
            if self.handle_lobby_popup():
                continue
            if self.handle_item_popup():
                continue

            # Daily sign-in, only on the first login of the day
            if self.handle_sign_in():
                continue
            if self.handle_signed_in_page():
                continue

            # 「是否退出基地？」 over the base page
            if self.handle_exit_dialog():
                continue

            # Title screen
            if self.handle_title_start():
                continue

            # The base page's own home button, then the shared header arrow
            if self.handle_home():
                continue

            if self.handle_sub_page():
                continue

            # Nothing known on screen for a while: the lobby is showing its idle
            # view with every icon hidden, one tap brings them back.
            if idle.reached():
                idle.reset()
                logger.info('No known page, tap the screen to wake the idle lobby')
                wake = Button(area=(636, 356, 644, 364), color=(0, 0, 0),
                              button=(636, 356, 644, 364), name='WAKE_TAP')
                # The idle lobby hides every icon, so there is no template to
                # guard this tap with; it is repeated by the timer above.
                self.device.click(wake)  # alas-lint: allow - the idle lobby hides every icon, there is nothing to appear-guard

            if timeout.reached():
                logger.warning('Wait game boot timeout')
                raise GameStuckError(
                    'Game did not reach page_main after launch. '
                    'If it kept sitting on the title screen, the account may be logged out '
                    'or the client is asking for an update.')

    def handle_title_start(self):
        """
        Press 「开始游戏」 on the title screen and wait until it is gone.

        The four characters stay visible while the loading overlay is drawn on
        top of them (measured 0.99 similarity on that frame), so they are a good
        end marker for "the client took the click": they only disappear when the
        lobby replaces the whole screen. `interval` keeps a swallowed click from
        being repeated every frame, and the wait makes sure the next click only
        happens after this one has finished - tapping twice on this screen
        queues a second login.

        Returns:
            bool: If the title screen was on screen (and was pressed).
        """
        if self.appear(BOOT_START_GAME, offset=(20, 20), interval=CROSSCORE_RETRY_INTERVAL):
            logger.info('Title screen, press 开始游戏')
            self.device.click_record_clear()
            self.device.click(BOOT_START_GAME)
            if not self.wait_until_disappear(BOOT_START_GAME, offset=(20, 20),
                                             timeout=CROSSCORE_ENTER_TIMEOUT, settle=2):
                logger.warning('Title screen is still there, the click was swallowed or the login is slow')
            return True

        return False

    def handle_lobby_popup(self):
        """
        Close a lobby popup: 公告 first, then 充值奖励.

        They do **not** share a close button (2026-11-08 实测): the 公告 uses the
        white cross at the top right (1194,80), while the 充值奖励 raises its own
        ✕ at (1064,137). The old single template left the recharge popup on
        screen, and the boot waited on the lobby until it timed out.

        Both handlers require the popup body and its ✕ at the same time; a lone
        ✕ would be a blind tap, and the recharge banner is also part of the
        clean lobby, so its body alone must not count as "popup is open".

        Returns:
            bool: If a popup was on screen (and was pressed).
        """
        if self.handle_announcement_popup():
            return True
        if self.handle_recharge_popup():
            return True

        return False

    def handle_announcement_popup(self):
        """
        Close the 公告 popup.

        Returns:
            bool: If handled.
        """
        if self.appear(E_3_1, offset=(20, 20)) \
                and self.appear(BOOT_POPUP_CLOSE, offset=(20, 20), interval=CROSSCORE_RETRY_INTERVAL):
            logger.info('公告 popup, press its X')
            self.device.click_record_clear()
            self.device.click(BOOT_POPUP_CLOSE)
            if not self.wait_until_disappear(E_3_1, offset=(20, 20), timeout=5, settle=2):
                # 不是失败：关掉公告后充值奖励会立刻顶上来，下一轮再关。
                logger.info('Another popup is on screen, close it in the next round')
            return True

        return False

    def handle_recharge_popup(self):
        """
        Close the 充值奖励 popup, whose ✕ is not at the top right.

        The popup body (E_6_1) is checked together with its own ✕ (E_6_2): the
        same banner is also part of the clean lobby, and a check that fires on
        the clean lobby would keep the boot loop from ever returning.

        Returns:
            bool: If handled.
        """
        if self.appear(E_6_1, offset=(20, 20)) \
                and self.appear(E_6_2, offset=(20, 20), interval=CROSSCORE_RETRY_INTERVAL):
            logger.info('充值奖励 popup, press its own X')
            self.device.click_record_clear()
            self.device.click(E_6_2)
            if not self.wait_until_disappear(E_6_1, offset=(20, 20), timeout=5, settle=2):
                logger.warning('The recharge popup is still there, the X did not take')
            return True

        return False

    def handle_item_popup(self):
        """
        Close the 「获得物品」 popup raised by the daily sign-in.

        Returns:
            bool: If handled.
        """
        if self.appear(E_5_1, offset=(20, 20)) \
                and self.appear(E_5_2, offset=(20, 20), interval=CROSSCORE_RETRY_INTERVAL):
            logger.info('Item popup, press its confirm button')
            self.device.click_record_clear()
            self.device.click(E_5_2)
            if not self.wait_until_disappear(E_5_1, offset=(20, 20), timeout=5, settle=2):
                logger.warning('The item popup is still there')
            return True

        return False

    def handle_sign_in(self):
        """
        Press 「签到」 on the daily sign-in page.

        The page only shows up on the first login of the day; a restart after
        signing in goes straight to the lobby (2026-11-08 实测), so this is an
        optional branch. The page and the button are checked together, then the
        code waits for the 「获得物品」 popup: the click is swallowed while the
        panel is still fading in.

        Returns:
            bool: If handled.
        """
        if self.appear(E_4_1, offset=(20, 20)) \
                and self.appear(E_4_2, offset=(20, 20), interval=CROSSCORE_RETRY_INTERVAL):
            logger.info('Sign-in page, press 签到')
            self.device.click_record_clear()
            self.device.click(E_4_2)
            if not self.wait_until_appear(E_5_1, offset=(20, 20), timeout=10, settle=2):
                logger.warning('Sign-in popup did not show up')
            return True

        return False

    def handle_signed_in_page(self):
        """
        Leave the 已签到 panel through its back arrow.

        After the reward popup is closed the panel stays on screen with the
        bottom-right button greyed out; its only way out is the top-left arrow.
        The page check is that greyed button (E_7_2), the action is the arrow
        (E_7_1).

        Returns:
            bool: If handled.
        """
        if self.appear(E_7_2, offset=(20, 20)) \
                and self.appear(E_7_1, offset=(20, 20), interval=CROSSCORE_RETRY_INTERVAL):
            logger.info('Signed-in panel, press the back arrow')
            self.device.click_record_clear()
            self.device.click(E_7_1)
            if not self.wait_until_disappear(E_7_2, offset=(20, 20), timeout=5, settle=2):
                logger.warning('The signed-in panel is still there')
            return True

        return False

    def handle_exit_dialog(self):
        """
        Confirm 「是否退出基地？」.

        Leaving the base-building page through its back arrow does not leave it:
        the client asks 「是否退出基地？」 with 取消 / 确定 first, and the page
        stays behind the dialog (2026-11-04 实测：按返回箭头后箭头还在，屏幕
        一动不动，脚本连按了四十多次都出不来). Two elements decide it is this
        dialog and not another 确定/取消 pair: the question itself and the
        yellow 确定 - measured 1.000 on the dialog, at most 0.58 and 0.49 on the
        rest of the boot.

        Returns:
            bool: If the dialog was on screen (and 确定 was pressed).
        """
        if self.appear(DIALOG_EXIT_BASE, offset=(20, 20)) \
                and self.appear(DIALOG_CONFIRM, offset=(20, 20), interval=CROSSCORE_RETRY_INTERVAL):
            logger.info('「是否退出基地？」 is asking, press 确定')
            self.device.click_record_clear()
            self.device.click(DIALOG_CONFIRM)
            if not self.wait_until_disappear(DIALOG_EXIT_BASE, offset=(20, 20), timeout=5, settle=2):
                logger.warning('The dialog is still there, 确定 did not take')
            return True

        return False

    def handle_home(self):
        """
        Press the home button of the base-building page.

        基地建设 is the only full page that draws a home button next to its back
        arrow, and the button goes straight back to the lobby. The back arrow
        next to it does not - it raises 「是否退出基地？」 first - so the home
        button is tried before the shared header arrow.

        Returns:
            bool: If the home button was on screen (and was pressed).
        """
        if self.appear(BOOT_HOME, offset=(20, 20), interval=CROSSCORE_RETRY_INTERVAL):
            logger.info('A page with a home button is open, press it')
            self.device.click_record_clear()
            self.device.click(BOOT_HOME)
            if not self.wait_until_disappear(BOOT_HOME, offset=(20, 20), timeout=5, settle=2):
                logger.warning('The home button is still there, the page did not move')
            return True

        return False

    def handle_sub_page(self):
        """
        Leave a secondary page (签到 / 任务) through its back arrow.

        Every full page of this game draws the same white 「‹」 in a rounded box
        at the top left, and the lobby does not (it has the player avatar there),
        so one template is the generic way out of "the game was left somewhere
        that is not the lobby". Measured 1.000 on 基地建设, 0.995 on 签到, at most
        0.61 on the lobby / title / splash.

        基地建设 is not handled here any more: its arrow asks 「是否退出基地？」
        first and its own home button leaves in one click, so `handle_home()` runs
        before this one and takes it.

        Returns:
            bool: If a secondary page was on screen (and was left).
        """
        if self.appear(BOOT_BACK, offset=(20, 20), interval=CROSSCORE_RETRY_INTERVAL):
            logger.info('A secondary page is open, press the back arrow')
            self.device.click_record_clear()
            self.device.click(BOOT_BACK)
            if not self.wait_until_disappear(BOOT_BACK, offset=(20, 20), timeout=5, settle=2):
                logger.warning('The back arrow is still there, the page did not move')
            return True

        return False

    def ui_additional(self):
        """
        Handle the popups that can show up on any page.

        Two families so far:

        1. The lobby popups (公告 / 充值奖励), which the client raises on
           entering the lobby - including when the lobby is re-entered in the
           middle of a task.
        2. The 「获得物品」 reward popup. It is the same template on every page
           of the game (page_3 / page_14 / page_17 of the spec are identical),
           and the base task raises it from claiming, delivering orders and
           crafting alike, so it is handled once here instead of in every
           caller.

        Returns:
            bool: If handled.
        """
        if self.handle_item_popup():
            return True
        if self.handle_lobby_popup():
            return True

        return False

    def back_to_main(self):
        """
        Walk back to the lobby from wherever a task ended. The base map's home
        button is tried first: its back arrow raises 「是否退出基地？」.

        Returns:
            bool: If page_main is reached.
        """
        for _ in self.loop(timeout=60):
            if self.ui_page_appear(page_main):
                logger.info('Back to page_main')
                return True
            if self.handle_item_popup():
                continue
            if self.handle_lobby_popup():
                continue
            if self.handle_exit_dialog():
                continue
            if self.appear(BOOT_HOME, offset=(20, 20), interval=2):
                self.device.click(BOOT_HOME)
                continue
            if self.appear(BOOT_BACK, offset=(20, 20), interval=2):
                self.device.click(BOOT_BACK)

        logger.warning('Cannot go back to page_main')
        return False
