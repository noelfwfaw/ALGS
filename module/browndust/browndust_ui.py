"""
棕色尘埃2 (Brown Dust II) 的界面层。

游戏信息（都已在本机确认）：

- 包名 `com.neowizgames.game.browndust2`，`adb shell pm list packages` 读出来的。
- 横屏 **1280x720**。模拟器的物理尺寸报的是 720x1280 竖屏，但游戏自己旋转成
  横屏，`screencap` 出来的就是 1280x720，和另外两个游戏同尺寸，素材直接框在
  720p 上，不需要给设备层加旋转支持。

冷启动长这个样子（2026-10-28 实机）：

    黑屏 → 加载 → 标题页（BROWN DUST II + 右下 TOUCH TO START）
              ↳ 版本过旧时先弹「更新通知」，写着"需要更新，将前往商店"
              ↳ 首次进新版本会弹「下载」（资源包 16 GB）
              ↳ 商店连不上时弹「支付失败 / EXCEPTION」（居中确认框，**任何页面**都会弹，
                不只是标题页 —— 见 `handle_payment_error()`）
              ↳ 大版本后弹「说明：为同步服务器数据，游戏将自动重启」，确认后客户端重启
    → 地图页（3D 城镇，右上角一个白色房子按钮）
    → 点那个房子 → 大厅（左上角「我的小屋」，每天压着一堆活动/通行证弹窗）
    → 一直点空白关弹窗，直到大厅真的干净

那个"一直点空白"不是偷懒：大厅的每日弹窗有七八个，全是活动登录、通行证、
PRE-ORDER 广告，**没有一个是任务需要的**，而且大多数右上角连 X 都没有，
只有"点面板外面"这一条路。想关它们就得先知道哪个是弹窗 —— 判据见
`ui_lobby_shaded()`：大厅图标模板还匹配（说明背后是大厅）+ 右上角的白图标
被压成灰（说明有东西盖着它）。只看模板分不开（遮罩下 0.80~0.97），
只看颜色也不行（大厅壁纸每次进场都可能换），两条一起才分得开。

「支付失败」**不算冷启动的一步**：它是商店客户端拿不到商品列表，游戏什么时候想
问商店就什么时候弹，进大厅以后照样弹。所以它挂在框架的全局钩子
`ui_additional()` 上（`ui_goto` / `ui_get_current_page` 每轮都会调），冷启动循环
只是额外早查一次，免得标题页背景上的 TOUCH TO START 抢先。

版本过旧和资源包下载**不自动处理**：前者要去 Play 商店，后者是 16 GB 流量，
两件都该由人决定，所以直接 `RequestHumanTakeover` 报错停下，而不是猜。
"""
import numpy as np

from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import rgb2luma
from module.exception import GameStuckError, RequestHumanTakeover
from module.logger import logger
from module.browndust.assets import (BOOT_DOWNLOAD_DIALOG, BOOT_PAYMENT_ERROR,
                                     BOOT_RESTART_DIALOG, BOOT_TOUCH_START,
                                     BOOT_UPDATE_NOTICE, EVENT_MISSION_CLAIM,
                                     HUNT_BUTTON, HUNT_REWARD, HUNT_START,
                                     MAIL_CLAIM, MAIN_HOME_ICON, MAP_HOME_BTN,
                                     TASK_CLAIM_ALL)
from module.browndust.page import *  # noqa: F401,F403 - the pages, re-exported for the tasks
from module.browndust.page import (page_event, page_event_battle, page_event_mission,
                                   page_event_story, page_hunt, page_main, page_mail,
                                   page_map, page_pass, page_summon, page_task,
                                   page_world_boss)
from module.ui.ui import UI

# 关大厅弹窗时点的地方：左边那条竖栏（我的小屋/好友/公会…）的左侧留白。
# 这一点的安全性是在每张截图上量过的 —— 竖栏从 x=71 起，底部导航栏从 y=592 起，
# (20~60, 430~470) 两边都不碰，而所有弹窗的面板都从 x≈207 才开始，
# 所以它永远落在遮罩上，不在面板里、也不在任何按钮上。
BROWNDUST_TAP_BLANK = Button(area=(20, 430, 60, 470), color=(0, 0, 0),  # alas-lint: allow - a blank spot, there is no image to match
                             button=(20, 430, 60, 470), name='BROWNDUST_TAP_BLANK')

# 冷启动要等客户端加载（实机 30~90 秒，慢的模拟器更久），再乘上弹窗和重启的次数。
BROWNDUST_BOOT_TIMEOUT = 600

# 大厅弹窗的外框模板阈值。这个值判的是"背后是不是大厅"，不是"干不干净"：
# 干净的主页面 0.93~1.00，被遮罩压过的 0.80~0.97，两者是重叠的，所以 0.85 也够，
# 取 0.75 是因为「午夜装扮通行证」那个弹窗把大厅压得最狠（0.80），留点余量。
BROWNDUST_POPUP_SIMILARITY = 0.75

# 大厅的"亮度尺"：右上角那排图标里的「主页」房子。
#
# 为什么不数区域平均色（2026-10-28 17:30 实机）：大厅壁纸/主题每次进场都可能换，
# 实机已经见过亮粉、暗紫、亮蓝、奶油白四种，`MAIN_HOME_ICON` 那 47x42 的平均色
# 从 (107,106,109) 一路到 (200,202,204)。于是**干净的大厅被判成"被遮罩压着"**，
# `ui_additional()` 一路点空白，直到壁纸自己变回来 —— 那一次连点了 20 下，
# 每下 0.4 秒（= 一帧），白等 8 秒。
#
# 换成"这块区域里还有没有亮点"就稳了，因为游戏会按壁纸明暗自动反色画图标：
# 暗壁纸上是白图标、奶油白壁纸上是深灰图标配亮底 —— 两种情况这块区域里都有
# 接近纯白的像素。遮罩是**全屏**乘一层黑，亮的地方压成灰，所以"亮像素数"掉了就是
# 被盖住了。实机量到的（luma > 200 的像素数）：
#
#     干净的大厅（6 张，5 种壁纸）      372 ~ 450
#     每日主页面弹窗 1~8                全部 0
#     抽抽乐页 / 地图页 / 角色展示页      55 / 185 / 272（模板那条已经挡住了）
#
# 所以阈值放在 300：离干净的最低值还有 20%，离弹窗是 300 比 0。
BROWNDUST_LOBBY_LIGHT = (1020, 36, 1044, 60)
BROWNDUST_LOBBY_LUMA = 200
BROWNDUST_LOBBY_LIGHT_COUNT = 300

# 地图页那个房子按钮的阈值比默认的 0.85 低。模板里含着右上角那枚红点
# （"有东西可以领"的提示），红点消失时整块图只剩房子和描边，实测最高相似度会
# 掉到 0.7 附近 —— 而它在其它页面上的最高干扰分是 0.58（午夜装扮通行证那张），
# 所以 0.75 既容得下红点变化，也还离干扰分有一段距离。
BROWNDUST_MAP_BTN_SIMILARITY = 0.75


class BrowndustUI(UI):
    """
    UI class of 棕色尘埃2.
    """

    page_main = page_main
    page_hunt = page_hunt
    page_mail = page_mail
    page_task = page_task
    page_pass = page_pass
    page_event_mission = page_event_mission

    # Own pages, in the order they are declared above. The registry is shared
    # with every other game, and their check points only exist in their own
    # asset namespace.
    #
    # `page_task` **必须**排在 `page_mail` 前面：两个页面的检查点是同一颗米白
    # 胶囊按钮，只差按钮上的字（「全部获得」/「全部领取」），而任务页上
    # `MAIL_CLAIM` 照样打 0.952（阈值 0.85）。实测 `ui_get_current_page` 把任务页
    # 认成了邮箱页 —— 两页的返回键恰好在同一个位置，所以没出事，但换页就错了。
    # 反方向是安全的：邮箱页上 `TASK_CLAIM_ALL` 只有 0.567。
    #
    # `page_pass` 的检查点是标题文字，跟谁都不撞（别的页 0.22~0.53），但它的
    # 「全部获得」和任务页那颗是**同一种胶囊、同样的四个字**，所以两个页面的
    # 判定不能互相翻车：实测任务页上 `PASS_CLAIM` 0.54、通行证页上
    # `TASK_CLAIM_ALL` 0.75，都在 0.85 之下。
    #
    # 两个活动页排在 `page_main` 前面只是"先特殊后通用"的次序，它们和谁都不撞：
    # `EVENT_SCHEDULE`（活动页的「行程」）在别的页 0.35~0.50，`STORY_TITLE`
    # （剧情页标题）0.48~0.52 —— 后者和 `PASS_TITLE` 同位置同尺寸，是这里唯一
    # 需要盯着的一对，实测互相 0.480 / 0.500。
    pages = (page_map, page_hunt, page_summon, page_task, page_pass, page_mail,
             page_event, page_event_story, page_event_battle, page_world_boss,
             page_event_mission, page_main)

    def tap_point(self, x, y):
        """
        Press a point of this game with an adb tap.

        大多数按钮吃 `device.click()` 的 minitouch 短按，但魔兽页的「去战斗」
        不吃 —— 2026-10-29 连续两次点下去游戏一声不响（同一坐标换
        `adb shell input tap` 一点就进战斗），而同一轮里「编辑队伍」「推荐部署」
        「返回」全都是 minitouch 点成功的。所以"必须落下去"的那一下走 adb，
        调用的地方照样在点完之后等屏幕给出结果 —— 换掉的只是输入通道。

        全游戏只有这一份（硬约束 60）：兑换码那条流程的 `coupon_tap()` 也走这里。

        Args:
            x (int): Pixel x.
            y (int): Pixel y.
        """
        self.device.click_adb(x, y)

    def tap_asset(self, button):
        """
        Press the click point of a button with an adb tap.

        Args:
            button (Button): Target.
        """
        x1, y1, x2, y2 = button.button
        self.tap_point((x1 + x2) // 2, (y1 + y2) // 2)

    def ui_page_appear(self, page, offset=(30, 30), interval=0):
        """
        Whether the given page is on screen.

        The lobby needs two questions, not one, and neither is a colour
        comparison of the page's own check point:

        - the 「我的小屋」 **template** still matches at
          `BROWNDUST_POPUP_SIMILARITY`. Template matching normalises brightness
          away, so this only answers "the page behind whatever is on top is the
          lobby" - exactly what is wanted, because the daily popups are a
          translucent overlay, not a different page.
        - the top-right icon is **still bright** (`ui_lobby_shaded()`). The
          overlay is a full-screen black layer, so it dims that icon to grey;
          the wallpaper behind it does not, because the game draws the icon in
          the opposite brightness of whatever wallpaper it picked.

        The old version compared the mean colour of the check point's own area
        and had to force `offset=0` to do it. That broke whenever the game
        changed the lobby wallpaper, see `BROWNDUST_LOBBY_LIGHT`.

        The hunt page needs the same shape for the same reason: its check point
        (the bottom-right 「快速狩猎」 button) still scores 1.00 through the
        quick-hunt dialog and through the reward banner, both of which are
        translucent overlays drawn on top of it. `ui_hunt_clean()` is the
        "nothing is on top of it" half.

        Args:
            page (Page):
            offset:
            interval:

        Returns:
            bool: If the page appears.
        """
        if page is self.page_main:
            return self.appear(MAIN_HOME_ICON, offset=offset, interval=interval,
                               similarity=BROWNDUST_POPUP_SIMILARITY) and not self.ui_lobby_shaded()
        if page is self.page_hunt:
            return self.appear(HUNT_BUTTON, offset=offset, interval=interval) and self.ui_hunt_clean(offset=offset)
        if page is self.page_mail:
            return self.appear(MAIL_CLAIM, offset=offset, interval=interval) and self.ui_reward_clean(offset=offset)
        if page is self.page_task:
            return self.appear(TASK_CLAIM_ALL, offset=offset, interval=interval) and self.ui_reward_clean(offset=offset)
        if page is self.page_event_mission:
            # 活动任务页的「全部领取」透过 REWARD 结算页照样 0.957，跟邮箱、日常任务
            # 完全同一个理由 —— 结算页是半透明的一条带子，画在列表上面而不是替掉它。
            return self.appear(EVENT_MISSION_CLAIM, offset=offset, interval=interval) and self.ui_reward_clean(offset=offset)
        return super().ui_page_appear(page, offset=offset, interval=interval)

    def ui_hunt_clean(self, offset=(30, 30)):
        """
        Whether the quick-hunt map page is on screen with nothing on top of it.

        Two overlays are drawn over that page and neither replaces it, so the
        map's own check point cannot tell them apart:

        - the 「快速狩猎」 dialog (`HUNT_START`: 1.00 under the dialog, 0.23~0.36
          anywhere else),
        - the reward banner (`HUNT_REWARD`: 1.00 on the reward screen, 0.08~0.18
          anywhere else).

        Args:
            offset: Same search range as the caller used for the page itself.

        Returns:
            bool: True if neither overlay is there.
        """
        if self.appear(HUNT_START, offset=offset):
            return False
        if self.appear(HUNT_REWARD, offset=offset):
            return False
        return True

    def ui_reward_clean(self, offset=(30, 30)):
        """
        Whether the page under the REWARD screen is really back.

        「全部领取」 (mailbox) and 「全部获得」 (quests) both open the same
        translucent REWARD screen, and that screen lets the page under it score
        right through it: the mailbox check point 0.945, the quests' 0.963. So
        "the page is back" and "the reward screen is still up" are the same
        answer unless this half is asked as well. Same reason as
        `ui_hunt_clean()`.

        Args:
            offset: Same search range as the caller used for the page itself.

        Returns:
            bool: True if the reward screen is not there.
        """
        if self.appear(HUNT_REWARD, offset=offset):
            return False
        return True

    def ui_bright_count(self, button, luma):
        """
        Count the pixels of an area brighter than `luma`.

        "Is this piece of UI still bright?" is the question behind two
        completely different checks in this game, and both of them had to give
        up on mean colour and on template matching first:

        - the lobby popups: a full-screen translucent black layer dims
          everything, and only a brightness count stays readable through the
          lobby's rotating wallpaper (`ui_lobby_shaded()`);
        - the 抽抽乐 tabs: the open tab's label is drawn white, the closed one
          grey, and the tab's icon takes the pickup's theme colour, so the label
          is the only part that answers (see `module/browndust/summon.py`).

        Args:
            button (Button, tuple): Button instance or area.
            luma (int): 0-255, `rgb2luma` of the frame.

        Returns:
            int: Number of pixels above `luma`.
        """
        return int(np.count_nonzero(rgb2luma(self.image_crop(button)) > luma))

    def ui_lobby_shaded(self):
        """
        Whether the lobby is covered by one of its daily popups.

        The popups are a full-screen translucent black layer, so this asks the
        only question they change the answer to: is the top-right icon still
        bright? Measured on the real device - a clean lobby has 372~450 pixels
        above luma 200 in `BROWNDUST_LOBBY_LIGHT`, every one of the eight daily
        popups has 0 (the layer turns them into ~57). See
        `BROWNDUST_LOBBY_LIGHT` for why neither a mean colour nor "count the
        white pixels" survives the lobby's wallpaper rotation.

        Only meaningful when the lobby template matched; on any other page that
        icon is not there at all and this returns True (i.e. "not a clean
        lobby"), which is the safe answer.

        Returns:
            bool: True if a popup (or anything else dark) is on top of it.
        """
        return self.ui_bright_count(BROWNDUST_LOBBY_LIGHT,
                                    BROWNDUST_LOBBY_LUMA) < BROWNDUST_LOBBY_LIGHT_COUNT

    def app_start(self):
        """
        Launch the game and walk through the boot screens until page_main.

        A running game is not launched again - `app_start` only brings it to the
        front - so the boot loop starts from whatever is on screen: the title
        screen (normal cold start), the map page (first login of the day) or the
        lobby with its popups. All three are handled by the same state loop.

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
        Walk the boot screens, the map page and the lobby popups.

        The order of the checks is the order of the screens:

        1. A clean lobby ends the loop. "Clean" is the colour check, see
           `module/browndust/page.py`.
        2. 「更新通知」 and 「下载」 never get pressed: the first one leads to the
           Play Store, the second one downloads 16 GB. Both raise
           `RequestHumanTakeover` so a person decides.
        3. 「支付失败」 is a confirm-only dialog that is *not* tied to the title
           screen — it also shows up on the lobby, i.e. after boot, so it lives
           in `handle_payment_error()` and is handled from `ui_additional()` as
           well. Here it is checked **before** `BOOT_TOUCH_START` because that
           text is still on screen behind it (0.97 against the dialog frame).
        4. The map page's house button leads to the lobby.
        5. The title screen takes a tap anywhere.
        6. Anything left is assumed to be a lobby popup, which is closed by
           tapping the blank strip on the left.

        Pages:
            in: any
            out: page_main

        Returns:
            bool: True if page_main is reached.

        Raises:
            RequestHumanTakeover: If the client needs an update or a resource
                download that only a person can start.
            GameStuckError: If the lobby is not reached in time.
        """
        logger.hr('App boot', level=2)
        timeout = Timer(BROWNDUST_BOOT_TIMEOUT, count=3).start()
        # 盲点（下面那个"什么都不认识"的分支）的节流。故意不 `.start()`：
        # 未启动的 Timer 第一次 `reached()` 就是 True，第一次不用干等。
        tap = Timer(2)

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
                if not self.device.has_cached_image:
                    self.device.screenshot()
            else:
                self.device.screenshot()

            # End
            if self.ui_page_appear(page_main):
                logger.info('Game is at page_main')
                return True

            # 需要人来决定的两件事
            if self.appear(BOOT_UPDATE_NOTICE, offset=(20, 20)):
                logger.critical('Client is out of date, the game wants the store')
                raise RequestHumanTakeover(
                    '棕色尘埃2 客户端版本过旧，游戏要求先前往商店更新。'
                    '脚本不会替你去商店，也不会下载任何东西，请手动更新后重跑。')
            if self.appear(BOOT_DOWNLOAD_DIALOG, offset=(20, 20)):
                logger.critical('Game wants to download its resource package')
                raise RequestHumanTakeover(
                    '棕色尘埃2 要求下载游戏资源包（实机显示 16 GB）。'
                    '这一步只该由人来点，请手动下载完成后重跑。')

            # 两个确认框，顺序在 TOUCH TO START 之前：标题页那张背景上
            # TOUCH TO START 还在，先判它就会一直点标题页，永远关不掉弹窗。
            # 支付失败这个和 `ui_additional()` 共用一份实现，它不只长在标题页。
            if self.handle_payment_error():
                continue
            if self.appear_then_click(BOOT_RESTART_DIALOG, offset=(20, 20), interval=3):
                logger.info('Client restart notice, press 确认')
                continue

            # 地图页 → 大厅
            if self.appear(MAP_HOME_BTN, offset=(20, 20),
                           similarity=BROWNDUST_MAP_BTN_SIMILARITY):
                logger.info('Map page, enter the lobby')
                self.device.click(MAP_HOME_BTN)
                # 按压有没有被接受，唯一的证据是地图页离开了（硬约束 79）。
                # 实机第一次跑就踩到：这一下被转场动画吞掉，2.9 秒后又匹配到
                # 同一个按钮，白白多点一次；万一连续被吞就会一路点到超时。
                if not self.wait_until_disappear(MAP_HOME_BTN, offset=(20, 20),
                                                 timeout=10, settle=2):
                    logger.warning('The map page did not leave, press it again')
                continue

            # 标题页
            if self.appear_then_click(BOOT_TOUCH_START, offset=(20, 20), interval=2):
                logger.info('Title screen, tap to start')
                continue

            # 剩下的都当成大厅弹窗
            if self.ui_additional():
                continue

            # 什么都不认识。这里最可能是抽卡后的角色展示（全屏立绘，没有按钮，
            # 点哪都过），其次是加载动画。点一下继续，实在推进不了由超时兜底 ——
            # 宁可多点几下，也不能卡在这儿等一个不会自己消失的画面。
            if tap.reached():
                tap.reset()
                logger.info('Unknown screen, tap the blank strip')
                self.device.click_record_clear()
                self.device.click(BROWNDUST_TAP_BLANK)  # alas-lint: allow - tapping an unknown screen on purpose, there is no button to verify against
                self.wait_until_still(MAIN_HOME_ICON.area, timeout=2)
                continue

            if timeout.reached():
                logger.warning('Wait game boot timeout')
                raise GameStuckError('Game did not reach page_main after launch')

    def handle_payment_error(self):
        """
        Press 确认 on the 「支付失败」 dialog, wherever it shows up.

        The dialog is not a boot screen: it is the store client failing to fetch
        the product list (`System.TimeoutException:GetProducts`, 60 s timeout),
        and the game raises it whenever it decides to talk to the store - on the
        title screen, on the map page, and on the lobby after the boot already
        finished, i.e. in the middle of a task. Its only key is 确认; tapping the
        shaded area around it (what the lobby popup handler does) never closes
        it, and it is opaque enough to hide the lobby icon, so without this
        check the boot loop and `ui_goto` both see an unknown screen.

        Called from two places, on purpose:

        - `ui_additional()`, the framework's "popup on any page" hook, which
          `ui_goto` and `ui_get_current_page` call every round.
        - `handle_app_boot()`, *before* `BOOT_TOUCH_START`: that text is still
          on screen behind the dialog (0.97), so checking the title first would
          tap the title screen forever and never close the dialog.

        Similarity stays at the default 0.85. The template is only the title
        text, matched 1.00 on its own screenshot and at most 0.36 on the other
        23 screenshots of the game (the eight lobby popups included), so there
        is no need for a looser threshold.

        Returns:
            bool: If the dialog was on screen (and 确认 was pressed).
        """
        if self.appear(BOOT_PAYMENT_ERROR, offset=(20, 20), interval=3):
            logger.info('Payment error popup, press 确认')
            self.device.click(BOOT_PAYMENT_ERROR)  # alas-lint: allow - guarded by the appear() above and verified by the wait_until_disappear() below
            # 按压被接受没有别的证据，只有弹窗真的消失（硬约束 79）。这个弹窗关得慢，
            # 淡出期间每一帧都还能匹配，所以给它 10 秒而不是 3 秒，settle 要 2 帧。
            if not self.wait_until_disappear(BOOT_PAYMENT_ERROR, offset=(20, 20),
                                             timeout=10, settle=2):
                logger.warning('The payment error popup did not disappear, press it again next round')
            return True

        return False

    def ui_additional(self):
        """
        Handle the popups that show up on any page.

        Two families, in this order:

        1. The store's 「支付失败」 dialog. It has to be checked first: the lobby
           branch below dismisses things by tapping the shaded area outside the
           panel, which does nothing to this dialog - it would keep returning
           True and the loop would tap forever while the dialog stays.
        2. The lobby's daily popups.

        Returns:
            bool: If handled.
        """
        if self.handle_payment_error():
            return True

        # 大厅弹窗的判据，两条都要满足：
        # - 大厅图标**模板**还匹配，说明"背后的页面是大厅"；
        # - 右上角的白图标**变灰了**，说明"有东西盖着它"。
        # 少第一条会在标题页、地图页、抽抽乐页上乱点；少第二条会把干净的大厅
        # 一直点下去。这里就是要"看不见"，所以否定条件是本意：看不到大厅图标 =
        # 这层遮罩不是大厅的弹窗，交给别人处理。看不见时返回 False（不点），
        # 不会误动作。
        if not self.appear(MAIN_HOME_ICON, offset=30,  # alas-lint: allow - "not visible" is the question being asked
                           similarity=BROWNDUST_POPUP_SIMILARITY):
            return False
        if not self.ui_lobby_shaded():
            return False

        logger.info('Lobby popup, tap the blank strip to dismiss it')
        # Tapping the same spot over and over is exactly what the framework's
        # "stuck, hammering one button" detector watches for, and a lobby with
        # eight popups would trip it at the twelfth tap. These taps are
        # legitimate, so the record is cleared instead of the taps avoided.
        self.device.click_record_clear()
        # 点的是遮罩本身，没有按钮可以 appear —— 按压之后用
        # `wait_until_still` 等面板淡出，那才是这一步的验证。
        self.device.click(BROWNDUST_TAP_BLANK)  # alas-lint: allow - the target is the overlay, there is no button to guard with
        # The panel fades out on its own; use one area to tell "it is gone" from
        # "still animating" instead of a fixed sleep.
        self.wait_until_still(MAIN_HOME_ICON.area, timeout=2)
        return True
