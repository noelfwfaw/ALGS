from module.logger import logger
from module.lostsword.assets import OFFER_POPUP


class OfferPopup:
    """
    关掉大厅上偶尔自己弹出来的限时礼包卡（「Hot Deal!」那一版）。

    混入 `LostswordUI` 使用，不单独实例化；`lostsword_ui.py` 已经贴着五百行
    的规范线，所以按 `sign_in.py` 的老办法单独放一支。

    它不是任务，也没有自己的页面：`handle_app_boot()` 和 `ui_additional()` 各挂
    一次，前者管冷启动撞上，后者管跑到一半撞上。
    """

    def handle_offer_popup(self, timeout=8):
        """
        Close the limited-time offer card that the lobby pushes over itself.

        The game occasionally interrupts the lobby with a paid bundle ("新人克星
        礼包 II", "Hot Deal!") that takes the whole screen and hides every piece
        of the lobby UI behind a *blurred* copy of it, so `page_main` matches
        nothing while it is up. Nothing here can be answered either: the card has
        a price button and a close key, and the shutdown is only the close key in
        the top right corner (the same place every other page of this game puts
        its own).

        Detected on the card's own furniture, not on the text: the title, the
        character art, the items and the price change with every bundle, while
        the 「Hot Deal!」 ribbon at the bottom left belongs to the layout. Measured
        over the 207 screenshots of this game in `screenshots/lostsword/` plus
        the boot and sign-in probe frames: 1.000 on the card, 0.39 on the
        runner-up, so the default 0.85 of `appear()` has 0.45 of headroom on the
        side that matters. `log/stub_offer.py` repeats that measurement.

        A different offer layout would need a second asset; keep the check a
        loop over a tuple when that happens, the handling below is the same.

        Args:
            timeout (int): Seconds to wait for the card to fade out.

        Returns:
            bool: If the card was on screen (and its close key was pressed).
        """
        # "看不到" 就是这一支要问的问题：看不到才轮到别的分支，看得到就关掉它。
        if not self.appear(OFFER_POPUP, offset=(30, 30), interval=2):  # alas-lint: allow - the absence is the answer, the caller continues on False
            return False

        logger.info('Limited-time offer popup, close it')
        # 这个游戏有一部分按钮不吃 minitouch 的短按（硬约束 60），关闭键就是
        # 右上角那枚圆圈，走 adb 更稳；按下去对不对由下面的消失判断回答。
        self.tap_asset(OFFER_POPUP)
        if not self.wait_until_disappear(OFFER_POPUP, offset=(30, 30), timeout=timeout, settle=2):
            logger.warning('The offer popup did not close, press it again next round')
        return True
