"""往棕色尘埃2 的兑换网页里打字。

这个网页是游戏内嵌的 webview，**没有键盘**：点一下序列号输入框只出现一个光标，
不出输入条也不出系统键盘，所以 `input text` 能直接写进框里，不需要"等键盘弹出"
那一步。要回答的只剩两件事 —— 框里有没有字、上一个码清干净了没有 ——
而这两件都只能数像素：那是一张画出来的网页，没有任何原生控件可以查。

**输入框会自己清空**：每交一次（成功、失败都一样），页面把框恢复成占位提示。
清空仍然是每次打字前的一步，因为它要防的是"这一次没清干净"这种版本变化，
而不是省一行代码。

实测（2026-10-29，滚到底之后的网页）：空框里 0 个深色像素（占位提示「请输入序列号」
是浅灰，luma 117，不进判据），有字 1400~1800 个。阈值取 200 两边都宽裕。

依赖组合类的 `self.device`、`self.loop()`。
"""

from module.base.timer import Timer

# 输入框里那一行字，相对输入框中心的位置。滚到哪儿网页都会一起移动，所以这个
# 框是**算出来的**，不是写死的（空着 0 个深色像素，有字 1400 以上）。
INPUT_TEXT_BOX = (-340, -26, 340, 28)
INPUT_TEXT_DARK = 200
# 清空输入框时按几次退格。最长的兑换码也没这么长，多按没有副作用。
CLEAR_PRESSES = 24


class CouponInput:
    """
    Read and write the serial number field of the coupon page.

    Methods used from the composed class: `device`, `loop()`.
    """

    def coupon_clear(self):
        """
        Delete whatever the input box holds.

        MOVE_END first, so the caret sits at the end of the text; without it the
        backspaces only eat the characters in front of wherever the tap happened
        to put the caret.
        """
        self.device.adb_shell(['input', 'keyevent', '123'])  # alas-lint: allow - MOVE_END
        for _ in range(CLEAR_PRESSES):
            self.device.adb_shell(['input', 'keyevent', '67'])  # alas-lint: allow - DEL

    def coupon_input_wait(self, want_text, box, timeout=3):
        """
        Wait until the input box holds text or is empty.

        Args:
            want_text (bool): True to wait for a code in it, False for empty.
            box (tuple): Centre (x, y) of the input field in this frame.
            timeout (int, float): Seconds.

        Returns:
            bool: If it reached the wanted state.
        """
        timeout = Timer(timeout).start()
        for _ in self.loop():
            dark = self.coupon_input_dark(box)
            if (dark > INPUT_TEXT_DARK) == want_text:
                return True
            if timeout.reached():
                return False

    def coupon_input_dark(self, box):
        """
        Count the dark pixels of the input box, which is how "it holds a code"
        is answered: an empty box has none, a filled one fourteen hundred and
        more. The grey placeholder text is far lighter and does not count.

        Args:
            box (tuple): Centre (x, y) of the input field in this frame.

        Returns:
            int: Pixel count.
        """
        x, y = box
        x1, y1, x2, y2 = INPUT_TEXT_BOX
        image = self.device.image
        if image is None:
            return 0
        patch = image[y + y1:y + y2, x + x1:x + x2]
        if patch.size == 0:
            return 0
        luma = patch.sum(axis=2) / 3
        return int((luma < 140).sum())
