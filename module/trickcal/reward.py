"""The 「請點擊屏幕繼續」 reward popup, as a component any scene can reuse.

Every reward in this game ends with the same full-screen panel. Three things
about it were measured on the exported frames (2026-11-11), not guessed:

1. **It is a translucent overlay, not a new page.** The screen behind it keeps
   rendering: the mailbox 「一鍵領取」 button still scores 0.925 while the popup
   is up. Anything a task asks about *behind* the popup will answer "yes"
   through it, so the popup is always asked about first (`ui_additional()` does
   the same, which is what lets `ui_get_current_page()` settle).

2. **The item cards in the middle must not be tapped.** They are real buttons;
   tapping one opens the item detail instead of dismissing the panel. That is
   why `REWARD_POPUP.button` is a separate mask (`REWARD_POPUP.BUTTON.png`)
   over the 「請點擊屏幕繼續」 line at y 574~599, far below the cards.
   **Every** template taps that same line, headers included: the line sits at
   y 578~595 on all three panels (mailbox / shop / sign-in, measured), and
   tapping the *header* does nothing at all - the real run of 2026-11-11 23:34
   tapped `E_4_1` four times at the title (612,248 / 686,238 / 683,253) and the
   panel stayed up, eating the next tab's clicks for 15 seconds until a hint-line
   tap at (646,587) closed it. `E_4_1.BUTTON.png` now points there too.
   **The line is a click point only, never a template**: its background changes
   with the scene (mean 181,188,145 on the shop panel vs 206,216,163 on the
   header), so detection always uses the header text (`area` / `color`) - which
   is what `E_4_1` still reads, only its `button` moved (user, 23:40).

3. **The header text differs per scene**, so the templates are separate assets
   and not two thresholds of one: 「確認領取」 for the mailbox (`REWARD_POPUP`,
   1.000 on its own frame, <=0.43 on every other frame), 「獲得獎勵」 for the
   item purchases of the shop (`REWARD_POPUP_GAIN`, 1.000 here and <=0.40
   elsewhere, including 0.400 on the mailbox one), and another header for the
   daily sign-in (`E_4_1`). They score 0.23 against each other off-device, but
   on the real phone `E_4_1` also fires on the shop panel (same art), which is
   harmless now that both tap the hint line - order in `reward_popups` only
   decides which name gets logged.
   The 获得奖励 panel is drawn **over** the shop's item detail (the panel's own
   buttons stay visible but dimmed), and tapping it away closes both (user,
   2026-11-11 23:20) - so a task never has to close the item detail separately.

Reuse: a new reward scene that ends in this popup needs one line here - append
its Button to `RewardPopup.reward_popups`. The detection loop and the tap
point live in this class, not in the task, so the task just calls
`handle_reward_popup()` from its own state loop.
"""

from module.logger import logger
from module.trickcal.assets import E_4_1, REWARD_POPUP, REWARD_POPUP_GAIN

# 弹窗的标题文字，宽高都稳定，给一点余量就够。
POPUP_OFFSET = (20, 20)
# 点掉之后的冷却：弹窗是"点一下才走"，被吞掉一次就再点，不和别的点击抢计时器。
POPUP_INTERVAL = 2
# 点掉之后等它真的消失。实测淡出不到 1 秒，3 秒是防卡顿。
POPUP_FADE = 3


class RewardPopup:
    """
    Detect, tap and wait out the reward popup.

    Composed into the game's UI class, so every task of this game inherits it.
    Each entry's own `button` is the tap target: point it at the panel text,
    never at a card.
    """

    # (開啟場景, 素材)：標題文字不同，所以是兩張圖，不是一個閾值。
    # 顺序只在日志里决定"这块面板叫什么"，不影响行为：三块素材的 button 全部指向
    # 提示行 y 578~595（E_4_1.BUTTON.png 是为了这件事补的）。
    # ❗别把任何一块的 button 改回标题：真机 2026-11-11 23:34 点标题（612,248 等位置）
    # 四下毫无反应，面板一直挂着，15 秒里切页签的点击全被它吃掉；点提示行一次就关。
    # REWARD_POPUP_GAIN 是商店买东西后的面板：它画在商品详情页上面，点掉它连详情页
    # 一起关，所以商店任务不需要另外收详情页（用户 2026-11-11 23:20）。
    reward_popups = (REWARD_POPUP, E_4_1, REWARD_POPUP_GAIN)

    def reward_popup_appear(self):
        """
        Whether a reward popup is on screen right now.

        Returns:
            Button or None: The popup that matched, so the caller can wait for
            exactly that one to fade out.
        """
        for popup in self.reward_popups:
            if self.appear(popup, offset=POPUP_OFFSET):
                return popup
        return None

    def handle_reward_popup(self, interval=POPUP_INTERVAL):
        """
        Tap the reward popup away if one is up.

        Call it from a state loop; it does not screenshot, it judges the
        current frame.

        Args:
            interval (int): Retry throttle per popup, so a swallowed tap is
                retried instead of counting as "no popup".

        Returns:
            Button or None: The popup that was tapped.
        """
        for popup in self.reward_popups:
            # allow: 这不是退出条件。本方法只判一帧，返回 None 表示"这一帧不点"，
            # 调用方的状态循环下一帧会再来 —— interval 在这里是吞点击的重试节流（153）。
            if self.appear(popup, offset=POPUP_OFFSET, interval=interval):  # alas-lint: allow
                logger.info(f'Reward popup 「{popup.name}」, tap to continue')
                self.device.click(popup)
                return popup
        return None

    def dismiss_reward_popup(self, timeout=POPUP_FADE, settle=1):
        """
        One-shot: tap the popup if it is up and wait until it is gone.

        This is the shape to use whenever something is **underneath** the panel
        that must not be tapped. The panel fades out over a frame or two, and a
        tap sent during that fade goes through to the screen below - in the shop
        that is the product grid, where a stray tap opens another pack's detail
        or its price chip (user, 2026-11-11 23:44). So: one tap here, then wait
        for the panel to be really gone before anything else is pressed.

        Args:
            timeout (int): Upper bound for the panel to fade out.
            settle (int): Frames the panel has to stay gone before this returns.

        Returns:
            bool: True if no popup is on screen when this returns.
        """
        popup = self.reward_popup_appear()
        if popup is None:
            return True
        self.device.click(popup)  # alas-lint: allow - reward_popup_appear() just matched it on this frame
        return self.wait_until_disappear(popup, offset=POPUP_OFFSET, timeout=timeout, settle=settle)
