"""
The 冒险通行证 of Trickcal: one press of 一键领取.

This is **not** the 等级通行证 that sits next to it in the lobby: the lobby has
two cards on the left, 等级通行证 (sun icon) at (20,230)-(110,265) and
冒险通行证 (blue ticket) at (108,253)-(194,327). Only the second one is used
here (user, 2026-11-12).

Flow read off the real frames (2026-11-12):

    page_main  --lobby 「冒险通行证」 card (108,253)-(194,327)-->  page_pass
    page_pass  --bottom-right 「一键领取」 (1005,605)-(1190,695)-->  reward popup
    page_main  <--shared top-left arrow--

Two things are not what they look like:

1. **The button is its own state check.** Lit and dim are the same art at the
   same place, so presence is not the question - the colour is:

       lit  frame: PASS_CLAIM 0.941, PASS_CLAIM_DARK 0.808
       dim  frame: PASS_CLAIM 0.413, PASS_CLAIM_DARK 0.966

   At the default 0.85 the two templates are exactly exclusive, so "is there
   anything to claim" is answered by which one matches, and the dim one is a
   positive check for "nothing left" (hard rule 5: no `not appear` gate).

2. **The popup is the shared 「獲得獎勵」 panel**, the same asset the shop uses
   (`REWARD_POPUP_GAIN`, verified on the real claim frame 2026-11-12 01:2x), so
   `RewardPopup` is reused as-is and this task never taps anything else to close
   it.
"""

from module.exception import TaskFailed
from module.logger import logger
from module.trickcal.assets import PASS_CLAIM, PASS_CLAIM_DARK
from module.trickcal.page import page_main, page_pass
from module.trickcal.trickcal_ui import TrickcalUI

PASS_OFFSET = (10, 10)
# 点一次「一键领取」之后：弹窗 + 按钮变暗。实测 1 秒内出弹窗、领完立刻变暗。
PASS_TIMEOUT = 25
# 按一下没反应是常态（153），2 秒重试一次。
PASS_INTERVAL = 2
# 弹窗淡出的那一两帧谁都不匹配，连着干净几帧才算真的关了。
PASS_SETTLE = 2


class TrickcalPass(TrickcalUI):
    """
    Claim the 冒险通行证 rewards with the bottom-right 一键领取.

    Pages:
        in: page_main
        out: page_main
    """

    def run(self):
        """
        Pages:
            in: page_main
            out: page_main

        Raises:
            TaskFailed: If the page could not be opened or the claim never
                settled. The next run is delayed first, so the scheduler does not
                retry the claim right away.
        """
        self.ui_ensure(page_main)
        success, reason = self.pass_claim()
        self.config.task_delay(server_update=True)
        if not success:
            raise TaskFailed(reason)

    def pass_claim(self):
        """
        Open the pass page, press 一键领取 once, close the popup, come back.

        Pages:
            in: page_main
            out: page_main

        Returns:
            (bool, str): Whether the claim settled, and why it did not.
        """
        logger.hr('Adventure pass', level=2)
        self.ui_ensure(page_pass)
        ok = self.pass_claim_once()
        self.ui_goto_main()
        if ok:
            return True, ''
        return False, '「一键领取」既没点亮、也没变暗，见日志'

    def pass_claim_once(self):
        """
        Press 一键领取 until the button is dim again, dismissing the popup.

        The popup is a translucent overlay, so it is answered first on every
        frame; the button underneath keeps rendering through it.

        Pages:
            in: page_pass
            out: page_pass

        Returns:
            bool: True when the button is dim (nothing left to claim).
        """
        for _ in self.loop(timeout=PASS_TIMEOUT):
            if self.reward_popup_appear() is not None:
                self.dismiss_reward_popup(settle=PASS_SETTLE)
                continue
            if self.appear(PASS_CLAIM_DARK, offset=PASS_OFFSET):
                logger.info('「一键领取」is dim, nothing left to claim')
                return True
            if self.appear(PASS_CLAIM, offset=PASS_OFFSET, interval=PASS_INTERVAL):
                logger.info('「一键领取」is lit, press it')
                self.device.click(PASS_CLAIM)  # alas-lint: allow - 上一条 appear() 就是这一帧的判据
        logger.warning('「一键领取」never settled')
        return False
