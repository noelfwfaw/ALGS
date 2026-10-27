from module.base.timer import Timer
from module.base.utils import get_color
from module.logger import logger
from module.lostsword.assets import (ARENA_BTN_CLOSE, PASS_BTN,
                                    PASS_CLAIM_ALL, PASS_TITLE,
                                    REWARD_POPUP_TITLE)
from module.lostsword.lostsword_ui import LostswordUI, page_main, page_pass

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

The button is drawn in both states, only the background colour changes (enabled
~208, greyed out ~103), so the "is there anything to claim" decision is a colour
read and never a template match.
"""

# Greyed out 103~125 measured; the enabled button is the same cream as every
# other 全部领取 of this game (~208). 150 sits between them with room on both
# sides, which matters because a wrong "grey" here means never claiming again.
PASS_CLAIM_MEAN = 150
# Seven passes are listed in the left column; eight entries cover a full round.
PASS_TRIES = 8


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

        for _ in range(PASS_TRIES):
            self.ui_ensure(page_main)
            if not self.pass_open():
                break

            if not self.pass_claimable():
                logger.info('No battle pass reward left')
                self.pass_close()
                break

            logger.info('Claim the battle pass rewards')
            for attempt in range(2):
                self.device.click(PASS_CLAIM_ALL)
                if self.wait_overlay(REWARD_POPUP_TITLE, timeout=6):
                    self.handle_reward_popup()
                    claimed += 1
                    break
                if attempt == 0:
                    # The panel has just faded in; a tap that lands during the
                    # fade is swallowed, so press once more before giving up.
                    logger.info('No popup, press 全部领取 again')
            else:
                logger.warning('No reward popup after 全部领取')

            self.pass_close()

        return claimed

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
        # before this) closes; a tap in that window does nothing.
        self.device.sleep(0.8)
        for attempt in range(2):
            self.device.click(PASS_BTN)
            if self.wait_overlay(PASS_TITLE, timeout=timeout):
                return True
            if attempt == 0:
                logger.info('Battle pass panel did not open, tap again')
                # Give the lobby the time to finish its transition.
                self.device.sleep(1.5)
                self.device.screenshot()
        logger.warning('Battle pass panel did not open')
        return False

    def pass_claimable(self):
        """
        Whether 「全部领取」 is the enabled one.

        Returns:
            bool: If the button is drawn on the cream background.
        """
        color = get_color(self.device.image, PASS_CLAIM_ALL.area)
        return sum(color) / 3 > PASS_CLAIM_MEAN

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

    def run(self):
        """
        Standalone entry, used by the tests. The daily routine calls
        `pass_claim()` directly, see `LostswordUI.handle_daily_task()`.
        """
        claimed = self.pass_claim()
        logger.info(f'Battle pass claimed: {claimed}')
