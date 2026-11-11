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

**服务器维护是这条流程的例外**：客户端会把整个标题/大厅换成一张维护公告页，
上面没有任何能进游戏的按钮。`handle_maintenance()` 认出它就结束任务、把本游戏
的任务排到维护结束，见 `alas.py` 的 `boot_declined`。
"""

import numpy as np

from module.base.button import Button
from module.base.timer import Timer
from module.chaoszero.assets import (ANNOUNCE_CLOSE, ARK_TITLE, ARK_WAR_AUTO, ARK_WAR_TARGET,
                                     BOOT_CONNECT_FAILED, BOOT_TOUCH_START, CAFE_TITLE,
                                     PANEL_CLOSE, POLICY_TITLE, RESULT_CONFIRM, SIM_PAGE,
                                     TEAM_TITLE, TRAINING_TABS, TRAINING_TITLE)
from module.chaoszero.maintenance import Maintenance
from module.chaoszero.page import page_main
from module.exception import GameStuckError
from module.logger import logger
from module.ui.ui import UI

# 方舟都市那一片（方舟都市 / 政策室 / 咖啡廳）共用的返回箭头。它们的返回键
# 时灵时不灵（政策室首页实测按不动），而这个白底箭头一直在。
CHAOSZERO_BACK = Button(area=(20, 12, 86, 58), color=(0, 0, 0),  # alas-lint: allow - a point to tap, there is no image to match
                        button=(20, 12, 86, 58), name='CHAOSZERO_BACK')

# 点画面中间那一下用的坐标。标题页、连接失败提示、闲置立绘这三种屏都吃
# "点任意处"，而画面正中永远不会落在「資源修復」或右上角那排系统键上。
CHAOSZERO_TAP_CENTRE = Button(area=(540, 300, 740, 420), color=(0, 0, 0),  # alas-lint: allow - a point to tap, there is no image to match
                              button=(540, 300, 740, 420), name='CHAOSZERO_TAP_CENTRE')

# 唤醒闲置立绘用的点：画面顶部中间。停手二十秒后整个 UI 会收起来只剩一张全屏
# 立绘，这时候点哪儿都只是"唤醒"，但**正中是人物**，点上去会进角色互动，界面
# 反而更回不来；顶部那条永远是空的。
CHAOSZERO_WAKE = (640, 96)

# 冷启动到主界面：实机 logo + 校验补丁 + 标题约 25 秒。留到 5 分钟是为了
# 客户端更新后第一次启动要校验整个补丁包，那一步能停一两分钟。
CHAOSZERO_BOOT_TIMEOUT = 300

# 战斗页左上角那条血量条的判定区与阈值（实测战斗 1865，其它页 0）。
CHAOSZERO_HP_BAR = (0, 0, 360, 30)
CHAOSZERO_HP_GREEN = 500

# "什么都不认识"时隔多久点一下画面。闲置立绘只认得出"没有 UI"，没有正面判据，
# 所以这个节流就是它的处理方式；8 秒足够让游戏的转场动画先走完。
CHAOSZERO_TAP_INTERVAL = 8

class ChaoszeroUI(Maintenance, UI):
    """
    UI class of 卡厄思梦境.
    """

    page_main = page_main

    # 自己那套页面。`Page.all_pages` 是全局注册表，多游戏场景下必须只遍历
    # 本游戏的（硬约束 36），否则切到别的游戏后匹配本游戏的判据会 KeyError。
    pages = (page_main,)

    def tap_point(self, x, y, name=None):
        """
        Press one point of the screen.

        模擬 里有几个按不出来的元素只能按坐标点：主界面右侧那行菜单、模擬页
        四张卡、战斗训练的行和页签、难度数字。它们都是"位置固定、图案会变"
        的东西（卡片立绘每期换、难度数字跟着选中项缩放），做模板只会把
        "换了一期"变成"认不出来"。

        全游戏只有这一份（硬约束 60），以后别的任务要用坐标点也走这里。

        Args:
            x (int): Pixel x.
            y (int): Pixel y.
            name (str): Button name used by the click record, defaults to the point.
        """
        button = Button(area=(x - 6, y - 6, x + 6, y + 6), color=(0, 0, 0),
                        button=(x - 6, y - 6, x + 6, y + 6),
                        name=name or f'CHAOSZERO_TAP_{x}_{y}')
        self.device.click(button)  # alas-lint: allow - the caller checks the page first; a coordinate point has no template to guard with

    def ui_green_count(self, area):
        """
        Count the pixels of an area that are clearly the HP-bar green.

        战斗页最稳的判据是左上角那条血量条：一整条亮绿色，实测 1865 个像素，
        而其它所有页面（配置队伍 / 战斗训练 / 模擬 / 主界面 / 结算）那块都是 0。
        圆形的 ✕ 按钮反而不能当判据 —— 模板里带着战斗背景，换个场景就掉到阈值
        以下（2026-10-30 卡在战斗里五分钟，就是因为没认出战斗页、也没开自动）。

        Args:
            area (tuple): x1, y1, x2, y2.

        Returns:
            int: Number of green pixels.
        """
        image = self.image_crop(area)
        r, g, b = image[:, :, 0], image[:, :, 1], image[:, :, 2]
        return int(np.count_nonzero((g > 110) & (r < 110) & (b < 120)))

    def ui_battle_appear(self):
        """
        Whether the battle screen is on screen.

        Returns:
            bool: True if the HP bar is there.
        """
        return self.ui_green_count(CHAOSZERO_HP_BAR) > CHAOSZERO_HP_GREEN

    def ui_gold_count(self, area):
        """
        Count the pixels of an area that are clearly the auto-battle gold.

        The auto-battle button is the same icon in both states - crossed swords
        inside a ring of arrows - and only the ring changes: a glowing gold ring
        when auto is on, a plain white one when it is off. It used to be cyan,
        but the client changed the effect (2026-11-09): the old cyan count read
        0 even with auto on, so every battle was pressed three more times and
        toggled back off. Measured on the real client, gold pixels in that box:
        113 with auto on, 0 with it off - white is excluded by the green ceiling.

        Args:
            area (tuple): x1, y1, x2, y2.

        Returns:
            int: Number of gold pixels.
        """
        image = self.image_crop(area)
        r, g, b = image[:, :, 0], image[:, :, 1], image[:, :, 2]
        return int(np.count_nonzero((r > 180) & (g > 110) & (g < 230) & (b < 170)))

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

        0. Server maintenance ends the task (`TaskEnd`) instead of the loop -
           the client stays on that screen for hours, so neither waiting nor
           tapping can reach the lobby. See `handle_maintenance()`.
        1. A lobby ends the loop - the right-hand menu is drawn, nothing else is.
        2. 「遊戲連接失敗」 before the title check: the dialog is drawn on top of
           the title screen, and its only key is "tap anywhere". Checking the
           title first would keep tapping a screen that is behind the dialog.
        3. The 「公告 / 更新」 popup is dropped on the lobby right after the client
           gets online, and it covers the right-hand menu, so the lobby check
           above cannot win while it is up. See `handle_announce()`.
        4. 「TOUCH TO START」 is the only thing that takes the client inside.
        5. Anything left (logo splash, patch validation, the black frame after
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
        back = Timer(2)

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

            # Server maintenance. Checked before `page_main`: the client
            # replaces the whole screen, so there is no lobby behind it, and
            # this branch ends the task without sending a single tap.
            if self.handle_maintenance():
                continue

            # End
            if self.ui_page_appear(page_main):
                logger.info('Game is at page_main')
                return True

            # Connection failure, also handled from `ui_additional()` because
            # the client raises it in the middle of a task as well.
            if self.handle_connect_failed():
                continue

            # 公告弹窗：客户端一连上服务器就把它顶在大厅上面，整屏盖住。大厅的
            # 「故事」在它底下匹配不上（实测 0.40），不接这一支就会掉进最后那支
            # 「什么都不认识」，点顶部只是把立绘唤醒或关掉，弹窗一直不走。
            # 它也会在任务中途弹，所以 `ui_additional()` 里再挂一次。
            if self.handle_announce():
                continue

            # Title screen
            if self.appear_then_click(BOOT_TOUCH_START, offset=(20, 20), interval=3):
                logger.info('Title screen, touch to start')
                continue

            # 游戏停在模擬那几张页里（上一个任务退出时留的、或者手动点进去的）：
            # 那里点画面正中只会点开一张卡片，返回键才是出路。
            # 结算页：按「確認」回配置队伍。返回键在这一屏时灵时不灵（实测同一
            # 个页面 13:41 一次就退出去、14:08 连按四次都留在原地），按钮反而稳。
            if self.appear(RESULT_CONFIRM, offset=(20, 20)):
                if back.reached():
                    back.reset()
                    logger.info('Result page, press 確認')
                    self.device.click_record_clear()
                    self.device.click(RESULT_CONFIRM)
                continue

            # 方舟都市那一片：政策室、災難修復作戰、咖啡廳、批准页、方舟都市首页。
            # 它们的返回键不一定按得动（政策室首页实测按不动），统一点左上那颗白箭头。
            if self.appear(ARK_TITLE, offset=(20, 20)) \
                    or self.appear(POLICY_TITLE, offset=(20, 20)) \
                    or self.appear(ARK_WAR_TARGET, offset=(20, 20)) \
                    or self.appear(ARK_WAR_AUTO, offset=(20, 20)) \
                    or self.appear(CAFE_TITLE, offset=(20, 20)):
                if back.reached():
                    back.reset()
                    logger.info('Inside 方舟都市, tap the back arrow')
                    self.device.click(CHAOSZERO_BACK)
                continue

            if self.appear(SIM_PAGE, offset=(20, 20)) \
                    or self.appear(TRAINING_TITLE, offset=(20, 20)) \
                    or self.appear(TRAINING_TABS, offset=(20, 20)) \
                    or self.appear(TEAM_TITLE, offset=(20, 20)):
                if back.reached():
                    back.reset()
                    logger.info('Inside 模擬, press back')
                    self.device.adb_shell(['input', 'keyevent', '4'])
                continue

            # 全屏面板（作戰总览、日常任務、其它整页菜单）：这些页的返回键不管用，
            # 只有右上角那颗 ✕ 关得掉。
            if self.appear(PANEL_CLOSE, offset=(20, 20)):
                if back.reached():
                    back.reset()
                    logger.info('A full-screen panel is open, press its X')
                    self.device.click(PANEL_CLOSE)
                continue

            # 什么都不认识。这里可能是 logo、补丁校验、点完之后的黑屏，或者
            # 闲置立绘 —— 前三者点了没反应，后者点了就回主界面，所以点一下是
            # 唯一安全的动作。
            #
            # 点的是**画面顶部**而不是正中：闲置立绘那一下点正中会落到人物身上，
            # 那是"和角色互动"，界面不会回来（2026-11-04 实测：信箱面板关掉后
            # 大厅闲着，正中连点三十多次，一路点进角色对话、再点进道具详情，
            # 五分钟超时失败）。顶部那条永远是空的，和 `ark.py` 的唤醒点同一个。
            if tap.reached():
                tap.reset()
                logger.info('Unknown screen, tap the top to wake the lobby')
                self.device.click_record_clear()
                self.tap_point(*CHAOSZERO_WAKE)  # alas-lint: allow - waking an unknown screen on purpose, a blind tap is the only action that moves it
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

    def handle_announce(self):
        """
        Close the 「公告 / 更新」 announcement popup.

        The client drops it on top of the lobby when it comes online. It is a
        full-screen panel: the lobby's 「故事」 menu behind it does not match
        (0.40 against the template), so `page_main` is false and the boot loop
        would end up in the "unknown screen" branch, tapping the top forever.

        The check point is the strip of tabs (bell / 公告 / 更新), not the ✕:
        the ✕ glyph is shared with the full-screen panel's ✕ at
        (1192, 66, 1224, 98), 44 px to the right, while the tab strip matched
        1.00 on its own screenshot and at most 0.28 on the other 56 screens
        (boot screens, lobby frames, every task page). The click still lands on
        the popup's own ✕ at (1148, 68, 1185, 103).

        Returns:
            bool: If the popup was on screen (and its X was pressed).
        """
        if self.appear(ANNOUNCE_CLOSE, offset=(20, 20)):
            logger.info('Announcement popup, press its X')
            self.device.click(ANNOUNCE_CLOSE)
            # 关不掉不抛异常：`ui_additional()` 每帧都会回来，启动循环也会再转
            # 一圈，反复警告比整个任务失败更有用。
            if not self.wait_until_disappear(ANNOUNCE_CLOSE, offset=(20, 20),
                                             timeout=5, settle=2):
                logger.warning('The announcement popup is still there')
            return True

        return False

    def ui_quit_to_main(self):
        """
        Walk back to the lobby: three back keys, then the boot loop.

        模擬 / 政策室 / 咖啡廳 这些页之间没有 link，`ui_goto` 走不了，只能按返回键。
        主界面**不**在这个循环里判：停手二十秒后游戏会把整个 UI 收起来只剩一张
        全屏立绘，那在判据眼里就是"什么页面都不是"，再按一次返回键它会问要不要
        退出客户端。`handle_app_boot()` 认识那一屏（点醒它、停在大厅），所以最后
        一步交给它。

        Pages:
            in: any
            out: page_main

        Returns:
            bool: True when the lobby is back.
        """
        for _ in range(3):
            if self.ui_page_appear(page_main):
                logger.info('Back at page_main')
                return True
            # 结算页按「確認」比按返回键稳（同一个页面见过返回键失效）。
            if self.appear(RESULT_CONFIRM, offset=(20, 20)):
                logger.info('Result page, press 確認')
                self.device.click_record_clear()
                self.device.click(RESULT_CONFIRM)
                self.wait_until_disappear(RESULT_CONFIRM, offset=(20, 20), timeout=15, settle=2)
                continue
            # **只有认出"确实在模擬那几张页里"才按返回键**。认不出来的时候很可能是
            # 主界面的闲置态（UI 全收起来了，`page_main` 也不成立），在那里按返回键
            # 游戏会问"要不要退出客户端"。
            if not (self.appear(SIM_PAGE, offset=(20, 20))
                    or self.appear(TRAINING_TITLE, offset=(20, 20))
                    or self.appear(TRAINING_TABS, offset=(20, 20))
                    or self.appear(TEAM_TITLE, offset=(20, 20))):
                break
            self.device.adb_shell(['input', 'keyevent', '4'])
            self.wait_until_still((0, 0, 1280, 720), timeout=3)

        logger.info('Walk the boot screens to make sure the lobby is up')
        self.handle_app_boot()
        return True

    def ui_additional(self):
        """
        Handle the popups that can show up on any page.

        Three families so far:

        - Server maintenance, which replaces the whole screen and can be raised
          in the middle of a task as well. Checked first: while it is up the
          other two cannot be on screen. See `handle_maintenance()`.
        - The connection-failure strip, which the client raises whenever it
          loses the server - on the title screen, and in the middle of a task.
        - The 「公告 / 更新」 announcement popup, which comes on top of the lobby
          after the client gets online and also at its own schedule (a new
          banner, a hotfix notice). It covers `page_main` completely, so without
          this hook `ui_goto()` reports an unknown page and the task fails.

        Returns:
            bool: If handled.
        """
        if self.handle_maintenance():
            return True

        if self.handle_connect_failed():
            return True

        if self.handle_announce():
            return True

        return False
