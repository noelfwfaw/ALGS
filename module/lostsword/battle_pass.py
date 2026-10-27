from module.logger import logger
from module.lostsword.assets import (ARENA_BTN_CLOSE, PASS_BTN,
                                    PASS_CLAIM_ALL, PASS_TITLE,
                                    REWARD_POPUP_TITLE)
from module.lostsword.lostsword_ui import LostswordUI, page_main

"""
赛季通行证 (battle pass).

Flow observed in game:

    page_main  --左侧「赛季通行证」图标-->  page_pass（自动选中一个赛季）
    page_pass  --底部「全部领取」-->  已获得道具。弹窗
    page_pass  --右上圆 X-->  page_main

There are several passes in the left column (引路者之路 / 回归助力通行证 /
圆桌加速通行证 I~II / 秘密之心 / 成长之路 I~II) and each has its own reward
track. Opening the panel selects the one that has something to hand out, so the
task does not have to know which one that is: enter, claim, leave, enter again.
When the panel comes up with 「全部领取」 greyed out there is nothing left in any
of them and the loop ends.

The "is there anything to claim" decision is **not** a colour read any more.
This button has been repainted at least once: it used to be cream when enabled
(~208) and grey when not (~103), and a threshold of 150 was written around that.
After a later patch the enabled button is the *dark* one (mean 103) and the
disabled one is darker still (mean 62), so that threshold read every enabled
button as "nothing to claim" and the task walked in and straight back out - the
pass never got claimed again (reported 2026-10-27).

What is stable across themes is the only thing that matters anyway: pressing the
button pays out and raises the reward popup, pressing it when there is nothing
leaves the screen unchanged. So the loop presses and watches for the popup, and
stops after two presses in a row that pay nothing.
"""

# Seven passes are listed in the left column; eight entries cover a full round.
PASS_TRIES = 8
# Consecutive rounds (open -> press -> close) that may pay nothing before the
# whole thing is called done. Two, because a press that lands while the panel is
# still sliding in is swallowed and looks exactly like an empty pass.
PASS_EMPTY_ROUNDS = 2


class LostswordBattlePass(LostswordUI):
    """
    Claim every battle pass reward that is ready.

    Pages:
        in: page_main
        out: page_main
    """

    def pass_claim(self):
        """
        Enter and leave the pass panel until nothing is left to claim.

        Pages:
            in: page_main
            out: page_main

        Returns:
            int: How many times a reward popup was claimed.
        """
        logger.hr('Battle pass', level=2)
        claimed = 0
        empty = 0

        for _ in range(PASS_TRIES):
            self.ui_ensure(page_main)
            if not self.pass_open():
                break

            if self.pass_claim_once():
                claimed += 1
                empty = 0
            else:
                empty += 1
                if empty >= PASS_EMPTY_ROUNDS:
                    logger.info('No battle pass reward left')
                    self.pass_close()
                    break

            self.pass_close()

        return claimed

    def pass_claim_once(self):
        """
        Press 「全部领取」 once and dismiss what it pays out.

        The press is repeated once: the panel has just faded in and a tap that
        lands during the fade is swallowed, which is indistinguishable from an
        empty pass.

        Pages:
            in: page_pass
            out: page_pass

        Returns:
            bool: If a reward popup showed up.
        """
        for attempt in range(2):
            if self.appear(PASS_CLAIM_ALL, offset=30):
                self.device.click(PASS_CLAIM_ALL)
            if self.wait_overlay(REWARD_POPUP_TITLE, timeout=5):
                logger.info('Claimed the battle pass rewards')
                self.handle_reward_popup()
                return True
            if attempt == 0:
                logger.info('No popup, press 全部领取 again')
        return False

    def pass_open(self, timeout=8):
        """
        Open the pass panel from the lobby.

        Closing the panel and immediately tapping the lobby entry again loses
        the tap: the panel is still sliding out and the lobby is still sliding
        in (measured once, 10 seconds of nothing). The tap is therefore repeated
        once after the first wait runs out.

        Pages:
            in: page_main
            out: page_pass

        Args:
            timeout (int, float): Seconds to wait for the panel per attempt.

        Returns:
            bool: If the panel is open.
        """
        # The lobby is still sliding in when the task panel (claimed right
        # before this) closes; a tap in that window does nothing. Watching the
        # entry until it stops moving is the same wait without the guess.
        self.wait_until_still(PASS_BTN.area, timeout=3)
        for attempt in range(2):
            if self.appear(PASS_BTN, offset=30):
                self.device.click(PASS_BTN)
            if self.wait_overlay(PASS_TITLE, timeout=timeout):
                return True
            if attempt == 0:
                logger.info('Battle pass panel did not open, tap again')
                self.wait_until_still(PASS_BTN.area, timeout=2)
        logger.warning('Battle pass panel did not open')
        return False

    def pass_close(self):
        """
        Close the pass panel and wait for the lobby.

        Pages:
            in: page_pass
            out: page_main

        Returns:
            bool: If the panel left.
        """
        if self.appear(PASS_TITLE, offset=30):
            self.device.click(ARENA_BTN_CLOSE)
            if not self.wait_overlay_gone(PASS_TITLE, timeout=8):
                logger.warning('Battle pass panel is still open')
                return False
        return self.wait_overlay(page_main.check_button, timeout=8)

    def run(self):  # alas-lint: allow - not a scheduled task, claimed from handle_session_claim()
        """
        Standalone entry, used by the tests. The session claim calls
        `pass_claim()` directly, see `LostswordUI.handle_session_claim()`.
        """
        claimed = self.pass_claim()
        logger.info(f'Battle pass claimed: {claimed}')
