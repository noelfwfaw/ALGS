"""进出棕色尘埃2 的兑换网页。

这三件事和"兑一个码"不是同一类工作：走到网页上、从网页上走回大厅、以及怎么按
一个坐标。它们的共同点是**都没有页面图可以依靠** —— 兑换页是游戏内嵌的 webview，
「其他」菜单是一层全屏覆盖，两者都不在 `pages` 里，所以既不能用 `ui_goto` 走，
也不能在它们开着的时侯调 `ui_goto_main()`：那是 `GamePageUnknownError`，
调度器会把它变成 `exit(1)`，带走整个进程而不是这一个任务。

依赖组合类的 `self.device`、`self.appear()`、`self.wait_until_*()`、
`self.ui_ensure()`。
"""
from module.base.timer import Timer
from module.browndust.assets import COUPON_ALERT_OK, COUPON_ENTRY, COUPON_WEB_CLOSE, COUPON_WEB_TITLE
from module.browndust.browndust_ui import BROWNDUST_POPUP_SIMILARITY, page_main
from module.logger import logger

# 「其他」菜单左上角的返回箭头。和别的页一样是游戏统一的半透明胶囊，背后是
# 每次都可能换立绘，做不成模板，只能按坐标点。
MENU_BACK = (152, 38)
# 网页正文。换页途中、滚动之后，用它判断"这一帧到底稳了没有"。
WEB_BODY = (20, 70, 1260, 700)


class CouponPage:
    """
    Walk in and out of the coupon page.

    Methods used from the composed class: `device`, `appear()`,
    `wait_until_appear/disappear/still()`, `ui_ensure()`, `coupon_tap()`.
    """

    def coupon_reset(self):
        """
        Walk back from wherever the last run stopped, before `ui_ensure()`.

        A run that died in the middle leaves the webview or the menu on screen,
        and neither is in the page graph: `ui_ensure(page_main)` would raise
        `GamePageUnknownError`, which the scheduler turns into `exit(1)` - the
        whole process, not just this task.
        """
        self.device.screenshot()

        if self.appear(COUPON_ALERT_OK, offset=30):
            logger.info('A coupon alert was left open, dismiss it')
            self.coupon_tap(COUPON_ALERT_OK)
            self.wait_until_disappear(COUPON_ALERT_OK, offset=30, timeout=5)
            self.device.screenshot()

        if self.appear(COUPON_WEB_TITLE, offset=30):
            logger.info('The coupon page was left open, close it')
            self.coupon_tap(COUPON_WEB_CLOSE)
            self.wait_until_disappear(COUPON_WEB_TITLE, offset=30, timeout=10)
            self.device.screenshot()

        if self.appear(COUPON_ENTRY, offset=30):
            logger.info('The 其他 menu was left open, close it')
            self.coupon_tap(MENU_BACK)
            self.wait_until_disappear(COUPON_ENTRY, offset=30, timeout=10)
            self.device.screenshot()

    def coupon_exit(self, rounds=4, timeout=40):
        """
        Close the page and the menu, end on the lobby.

        The page's own X is the way out (`COUPON_WEB_CLOSE`), then the menu's
        back arrow. Every press is followed by a look at what is in front now,
        because the layers fade out and a press sent during the fade lands on
        the layer that is already going away (measured on 失落之剑, hard rule
        113; this game fades the same way).

        Pages:
            in: any page of the flow
            out: page_main

        Args:
            rounds (int): How many panels to close at most.
            timeout (int, float): Seconds before giving up.

        Returns:
            bool: If the lobby was reached.
        """
        timeout = Timer(timeout).start()

        for _ in range(rounds):
            if timeout.reached():
                break
            self.device.screenshot()

            if self.appear(page_main.check_button, offset=30,
                           similarity=BROWNDUST_POPUP_SIMILARITY):
                break
            if self.appear(COUPON_ALERT_OK, offset=30):
                self.coupon_tap(COUPON_ALERT_OK)
                self.wait_until_disappear(COUPON_ALERT_OK, offset=30, timeout=5)
                continue
            if self.appear(COUPON_WEB_TITLE, offset=30):
                self.coupon_tap(COUPON_WEB_CLOSE)
                self.wait_until_disappear(COUPON_WEB_TITLE, offset=30, timeout=10)
                continue
            if self.appear(COUPON_ENTRY, offset=30):
                self.coupon_tap(MENU_BACK)
                self.wait_until_disappear(COUPON_ENTRY, offset=30, timeout=10)
                continue
            # 换页途中的一帧，哪个检测点都认不出来。等它停稳再看，别瞎点。
            self.wait_until_still(WEB_BODY, timeout=3)

        self.device.screenshot()
        if self.appear(page_main.check_button, offset=30,
                       similarity=BROWNDUST_POPUP_SIMILARITY):
            # 大厅可能压着每日弹窗，交给框架那一套关（它认得大厅的遮罩）。
            self.ui_ensure(page_main)
            return True

        # 退不出去也绝不在网页上调 `ui_goto_main()`：网页不在页面图里，
        # `GamePageUnknownError` 会被调度器变成 exit(1)，带走整个进程。
        logger.warning('The coupon flow could not walk back to the lobby')
        return False

    def coupon_tap(self, target):
        """
        Tap a button's centre, or a raw pixel, with `adb shell input tap`.

        Every press of this flow goes through here: the probe that measured the
        flow used adb taps and every one of them landed, while the game's own
        control method is unchanged for the rest of the tasks.

        Args:
            target (Button, tuple): Button, or `(x, y)`.
        """
        if isinstance(target, tuple):
            x, y = target
        else:
            x1, y1, x2, y2 = target.area
            x, y = (x1 + x2) // 2, (y1 + y2) // 2

        if not (0 <= x < 1280 and 0 <= y < 720):
            # 坐标是算出来的（输入框跟着「兑换」按钮走），算歪了就别按 ——
            # 屏幕外的点击在 adb 那边是静默失败，事后只能看到"没反应"。
            logger.warning(f'Refuse to tap outside the screen: ({x}, {y})')
            return

        logger.info(f'Tap {target} @ ({x}, {y})')
        self.device.click_adb(x, y)  # alas-lint: allow - the coupon page has no control method of its own
