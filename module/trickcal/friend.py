"""
Friend leaves (Trickcal): claim the leaves friends sent, send one back.

Flow read off the exported frames (2026-11-11, `screenshots/trickcal/`):

    page_main  --right-top two-person icon (1132,163)-(1166,199)-->  page_friend
    page_friend  --bottom-right 「一鍵領取」 (845,640)-(983,701)-->  reward popup
    page_friend  --bottom-right 「一鍵發送」 (1077,641)-(1208,704)-->  nothing,
                                                then 「一鍵領取」 lights up again (friends reply)
    page_main  <--top-left arrow (24,17)-(66,63)--

Three things are not what they look like:

1. **Both bottom buttons change colour, and `appear()` is a colour match.**
   `appear(button, offset=...)` goes through `Button.match()`, which template
   matches the *RGB* crop; the binarized and luma variants are separate methods
   (`match_binary()` / `match_luma()`). So a button whose paint follows its state
   disappears from `appear()` the moment it repaints:

   - 「一鍵領取」 is grey (mean 153) at 0/20 and lights up when leaves are
     waiting, so the exported asset is the *empty* state - and the asset was cut
     from that state, which is why `appear()` used to work here by accident.
   - 「一鍵發送」 is orange (232,194,97) at 0/50 and **greys out once everybody
     got one** (real frame 2026-11-11 22:04, counter 5/50, colour 153).

   Both are therefore located with `match_luma()` (presence, colour-blind) and
   read with `appear_on()` (the colour constant), never with `appear()`.
   The claim button needs **two** templates: the grey asset scores only 0.835 on
   the lit paint (real frame 2026-11-12 00:27), under the 0.85 luma threshold, so
   a lit button read as "not on screen" and the 00:27 run walked away with both
   buttons lit. `FRIEND_CLAIM_LIT` is the lit paint (1.000 there, 0.835 back on
   the grey one); the pair covers presence for both states. `appear_on()` on the
   grey asset is still what says "nothing waiting".

2. **Claiming opens the generic reward popup** (user, 2026-11-11 22:5x). Sending
   does not. That popup has to be closed *before* the send button is read: it is
   a translucent panel, the bottom bar behind it is shadowed, and the send
   button then reads as "dim" - which is exactly how the 22:37 run claimed a
   batch of leaves and then silently skipped the send (the counter stayed at
   0/50 because nothing had been sent). `wait_until_still()` alone is not a
   receipt for a claim, it is a receipt for "the counter stopped moving" - the
   popup sits on top of it.

3. **There is no confirmation for the send.** 领取 n/20 (leaves collected) and
   发送 n/50 (friends served) are the only feedback. Once everybody has received
   one, the send button is grey and the click is skipped, which is the normal
   finished state.
4. **Sending makes the claim light up again**, so one claim is not the whole
   task (user, 2026-11-11 23:49): the leaves the friends send back arrive right
   after 「一鍵發送」 and 「一鍵領取」 lights up the moment the send went through.
   The real run of 23:49 had nothing to claim, sent, and walked away with the
   new leaves still sitting there. `friend_leaves()` therefore runs
   领取 -> 发送 -> 领取 ... until neither button moves any more, bounded by
   `FRIEND_ROUNDS` because the claim button keeps coming back all day.
5. **The bottom bar is painted after the title.** `page_friend` is identified by
   the 「好友」 title at the top left and `ui_ensure()` returns the moment that
   title matches, so the first frame on the page can be one where the bottom bar
   is still empty: both buttons read "not on screen" and the task finishes with
   nothing done (the 00:27 run read the frame 0.3s after the switch). Both
   buttons are drawn grey when there is nothing to do, so "neither is there"
   only ever means "not painted yet" - `friend_wait_bar()` waits for one of them
   before anything is judged.

Measured on real frames (`.workbuddy/memory/2026-11-11.md`): luma scores are
1.000 (claim) / 0.931~0.979 (send) on the friend list and the buttons are absent
elsewhere; the entry icon 0.999~1.000 on every lobby frame (it also shows
through the mailbox overlay, so it is only clicked from `page_main`).
"""

from module.logger import logger
from module.trickcal.assets import (FRIEND_CLAIM_ALL, FRIEND_CLAIM_LIT,
                                    FRIEND_SEND_ALL)
from module.trickcal.page import page_friend, page_main
from module.trickcal.trickcal_ui import TrickcalUI

FRIEND_OFFSET = (30, 30)
# 发送点完等计数停下（0/50 → n/50 那一行会变）；发送不弹窗，没有别的验收手段。
FRIEND_SETTLE = 2
# 领取之后等通用奖励弹窗出来并点掉，10 秒是防网络卡（弹窗实测 0.3s 内出来）。
FRIEND_CLAIM_TIMEOUT = 10
# 领取 → 发送 → 再领取 的最大轮数。发送完领取会重新亮起来（好友回赠），所以一轮不够；
# 但领取按钮一整天都可能反复亮，必须封顶，不能"亮就继续领"。
FRIEND_ROUNDS = 3
# 进好友页之后等底栏画出来。`page_friend` 的判据是左上「好友」标题，它比底栏先到；
# 0.3 秒就读按钮会读到没画完的那一帧（用户 2026-11-12 00:27 就是这样两个都"找不到"）。
FRIEND_BAR_TIMEOUT = 5


class TrickcalFriend(TrickcalUI):
    """
    Collect the leaves friends sent over, and send one back.

    Pages:
        in: page_main
        out: page_main
    """

    def run(self):
        """
        Pages:
            in: page_main
            out: page_main
        """
        self.ui_ensure(page_main)
        self.friend_leaves()
        self.config.task_delay(server_update=True)

    def friend_leaves(self):
        """
        Open the friend list, claim, send, claim again, come back to the lobby.

        Sending makes 「一鍵領取」 light up again (friends send back), so the two
        directions alternate until neither button moves. That is the fix for the
        23:49 run, which had nothing to claim, sent, and left with the leaves
        that had just arrived still sitting there.

        Pages:
            in: page_main
            out: page_main
        """
        logger.hr('Friend leaves', level=2)
        self.ui_ensure(page_friend)
        self.friend_wait_bar()
        claimed = sent = 0
        for _ in range(FRIEND_ROUNDS):
            claimed_now = self.friend_claim_leaves()
            sent_now = self.friend_send_leaves()
            claimed += claimed_now
            sent += sent_now
            # 这一轮两边都点不动才是收工：只发不领（或反过来）都要再转一轮去看另一头。
            if not (claimed_now or sent_now):
                break
        logger.info(f'[Friend leaves] claim {claimed}, send {sent}')
        self.ui_goto_main()

    def friend_wait_bar(self, timeout=FRIEND_BAR_TIMEOUT):
        """
        Wait until the bottom bar is painted before judging either button.

        `page_friend` is identified by the 「好友」 title at the top left, and that
        title arrives before the bottom bar does: the 00:27 run read the frame
        0.3s after the page switch, both buttons scored "not on screen", and the
        task walked away while the real screen had both of them lit (user,
        2026-11-12 00:27). Both buttons are drawn grey when there is nothing to
        do, so "neither is there" only ever means "not painted yet".

        Pages:
            in: page_friend
            out: page_friend

        Args:
            timeout (int): Upper bound owned by this loop.

        Returns:
            bool: True if at least one button is on screen.
        """
        for _ in self.loop(timeout=timeout):
            if self.friend_claim_present() or self.friend_send_present():
                return True
        logger.warning('Neither friend button showed up, the list may not have loaded')
        return False

    def friend_claim_present(self):
        """
        Whether the claim button is painted at all - colour-blind.

        Two templates, because one is not enough: the asset is the grey state,
        and the **lit** state scores only 0.835 against it (real frame 2026-11-12
        00:27) - under the 0.85 luma threshold, so a lit button would read as
        "not on screen". `FRIEND_CLAIM_LIT` was cut from that real frame and
        scores 1.000 there and 0.835 back on the grey one, so the pair covers
        both states with room to spare.

        Returns:
            bool: True if either variant matches.
        """
        return FRIEND_CLAIM_ALL.match_luma(self.device.image, offset=FRIEND_OFFSET) \
            or FRIEND_CLAIM_LIT.match_luma(self.device.image, offset=FRIEND_OFFSET)

    def friend_claim_available(self):
        """
        Whether there is anything to claim.

        Presence is a luma match (over both paint states), the state is the
        colour: the exported button is the greyed-out state, so a colour match
        means "nothing to claim" and any repaint brighter than 10 units of the
        stored mean counts as lit. `appear()`, which template matches RGB, would
        drop the button as soon as it lights up.

        Returns:
            bool: True if the button is lit, i.e. there are leaves waiting.
        """
        if not self.friend_claim_present():
            logger.info('Friend claim button not on screen')
            return False
        if FRIEND_CLAIM_ALL.appear_on(self.device.image):
            return False
        return True

    def friend_claim_leaves(self):
        """
        Claim every leaf at once, if any are waiting.

        Pages:
            in: page_friend
            out: page_friend

        Returns:
            bool: Whether a claim was clicked.
        """
        if not self.friend_claim_available():
            logger.info('No leaves to claim')
            return False
        logger.info('Claim the leaves')
        # friend_claim_available() 刚刚同时验了按钮和它的颜色（灰=没得领），
        # 亮着才走到这里，所以这一下是有判据的点击。
        self.device.click(FRIEND_CLAIM_ALL)  # alas-lint: allow
        self.friend_wait_claimed()
        return True

    def friend_wait_claimed(self, timeout=FRIEND_CLAIM_TIMEOUT):
        """
        Sit through the reward popup of one claim.

        领取会弹通用奖励弹窗（用户 2026-11-11 确认），而弹窗是半透明遮罩：
        盖着的时候底栏被压暗，「一鍵發送」读出来就是"暗的"。2026-11-11 22:37
        就是这么把发送静默跳过的 —— 领取成功、发送一次没点、计数还停在 0/50。
        所以这里必须先**亲眼看到弹窗并点掉**，再往下走；只等
        `wait_until_still()` 不算回执，它只证明两帧之间画面没变。

        Pages:
            in: page_friend
            out: page_friend

        Args:
            timeout (int): Upper bound owned by this loop.

        Returns:
            bool: True if the popup was closed and the claim button went dim.
        """
        popup_seen = False
        for _ in self.loop(timeout=timeout):
            # interval=0：弹窗自己的节流还没到期时，会把"弹窗还在"读成"没有弹窗"。
            if self.handle_reward_popup(interval=0):
                popup_seen = True
                continue
            if not popup_seen:
                continue
            if not self.friend_claim_available():
                logger.info('Leaves claimed, reward popup closed')
                return True
        logger.warning('Claim gave no sign of life: '
                       'no reward popup, or the claim button is still lit')
        return False

    def friend_send_present(self):
        """
        Whether the send button is painted at all - colour-blind.

        One template is enough here: the asset is the orange state and the grey
        one still scores 0.931~0.979 (measured on the real post-send frame), so
        luma covers both paints.

        Returns:
            bool: True if the button is on screen.
        """
        return FRIEND_SEND_ALL.match_luma(self.device.image, offset=FRIEND_OFFSET)

    def friend_send_available(self):
        """
        Whether the send button is lit, i.e. there is anyone left to send to.

        Same split as the claim button: luma says the button is on screen, the
        colour says whether it is lit. The greyed state is the normal one once
        the daily send went through (0/50 -> n/50 greys the button out), so this
        is not an error.

        Returns:
            bool: True if the button is lit and can be clicked.
        """
        if not self.friend_send_present():
            logger.warning('Send button not found, skip sending')
            return False
        if not FRIEND_SEND_ALL.appear_on(self.device.image):
            logger.info('Send button is greyed out, already sent today')
            return False
        return True

    def friend_send_leaves(self):
        """
        Send a leaf to every friend.

        Pages:
            in: page_friend
            out: page_friend

        Returns:
            bool: Whether the send button was clicked.
        """
        if not self.friend_send_available():
            return False
        logger.info('Send the leaves')
        self.device.click(FRIEND_SEND_ALL)  # alas-lint: allow
        self.wait_until_still(FRIEND_SEND_ALL.area, timeout=FRIEND_SETTLE)
        return True
