"""往游戏自绘的输入条里打字。

这个游戏的兑换弹窗不弹系统键盘，它自己画一条输入条在屏幕最下面，所以
`input text` 能直接写进去，也能连按退格清空 —— 但"弹出来了没有""里面有没有字"
这两件事只能靠像素回答，因为整条输入条是游戏画的，没有任何原生控件可以查。

**输入条是屏幕最下面一条白底横幅**：拉出来时那条的平均亮度是 250，收起来是
29（实测 2026-10-29，区域 `(0, 650, 1280, 710)`）。判据取 200。

**输入框不会自己清空**：兑换完一个码，框里还留着上一个，不清就会两个码拼成一个
不存在的码。空框的深色像素是 0 个，有字是 916~1280 个（占位提示「请输入优惠券。」
是浅灰，不进这个判据），所以阈值取 200 就足以区分。

依赖组合类的 `self.device`、`self.loop()`、`self.tap_point()`。
"""

from module.base.timer import Timer

# 兑换弹窗的输入框。点它才会拉出游戏自己的输入条。
REDEEM_INPUT = (640, 358)
# 输入条最右边的「确定」。
REDEEM_KEYBOARD_OK = (1200, 665)
# 屏幕上被输入条占住的那一条：拉出来 250，收起来 29。
REDEEM_KEYBOARD_AREA = (0, 650, 1280, 710)
REDEEM_KEYBOARD_LUMA = 200
# 输入框里那一行字。空着 0 个深色像素，有字 900 以上。
REDEEM_INPUT_AREA = (420, 340, 860, 376)
REDEEM_INPUT_DARK = 200
# 清空输入框时按几次退格。最长的兑换码也没这么长，多按没有副作用。
REDEEM_CLEAR_PRESSES = 24


class CouponInput:
    """
    Read and write the coupon input box, and the bar it brings up.

    Methods used from the composed class: `device`, `loop()`, `tap_point()`.
    """

    def coupon_keyboard(self, want=True, timeout=3):
        """
        Wait for the game's own input bar to slide in or out.

        It is a full width white strip at the bottom of the screen, so the check
        is the brightness of that strip: 250 with the bar, 29 without.

        Args:
            want (bool): True to wait for it to appear, False for it to leave.
            timeout (int, float): Seconds.

        Returns:
            bool: If it is in the wanted state.
        """
        timeout = Timer(timeout).start()
        for _ in self.loop():
            luma = self.coupon_keyboard_luma()
            if (luma >= REDEEM_KEYBOARD_LUMA) == want:
                return True
            if timeout.reached():
                return False

    def coupon_keyboard_luma(self):
        """
        Mean brightness of the strip the input bar occupies.

        Returns:
            float: 0~255.
        """
        x1, y1, x2, y2 = REDEEM_KEYBOARD_AREA
        image = self.device.image
        if image is None:
            return 0.0
        patch = image[y1:y2, x1:x2]
        if patch.size == 0:
            return 0.0
        return float(patch.sum(axis=2).mean() / 3)

    def coupon_keyboard_close(self):
        """
        Put the input bar away so the next step sees the dialog again.
        """
        self.tap_point(*REDEEM_KEYBOARD_OK)
        self.coupon_keyboard(want=False)

    def coupon_clear(self):
        """
        Delete whatever the input box holds.

        The box keeps the last code after a redemption, so every code after the
        first one would otherwise be typed behind it.
        """
        self.device.adb_shell(['input', 'keyevent', '123'])  # alas-lint: allow - MOVE_END
        for _ in range(REDEEM_CLEAR_PRESSES):
            self.device.adb_shell(['input', 'keyevent', '67'])  # alas-lint: allow - DEL

    def coupon_input_wait(self, want_text, timeout=3):
        """
        Wait until the input box holds text or is empty.

        Args:
            want_text (bool): True to wait for a code in it, False for empty.
            timeout (int, float): Seconds.

        Returns:
            bool: If it reached the wanted state.
        """
        timeout = Timer(timeout).start()
        for _ in self.loop():
            dark = self.coupon_input_dark()
            if (dark > REDEEM_INPUT_DARK) == want_text:
                return True
            if timeout.reached():
                return False

    def coupon_input_dark(self):
        """
        Count the dark pixels of the input box, which is how "it holds a code"
        is answered: an empty box has none, a filled one nine hundred and more.

        Returns:
            int: Pixel count.
        """
        x1, y1, x2, y2 = REDEEM_INPUT_AREA
        image = self.device.image
        if image is None:
            return 0
        patch = image[y1:y2, x1:x2]
        if patch.size == 0:
            return 0
        luma = patch.sum(axis=2) / 3
        return int((luma < 140).sum())
