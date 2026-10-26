from module.hazeworld.assets import PASS_CLAIM_ALL
from module.hazeworld.hazeworld_ui import HazeworldUI, page_pass
from module.logger import logger


class HazeworldPass(HazeworldUI):
    """
    Claim battle pass level rewards.

    Pages:
        in: page_main
        out: page_main
    """

    def run(self):
        logger.hr('Battle pass claim', level=1)
        self.ui_ensure(page_pass)

        if self.config.HazeworldPass_ClaimAll:
            self.pass_claim()

        self.ui_goto_main()

        # Daily task, run again after the game refreshes.
        self.config.task_delay(server_update=True)

    def pass_claim(self, skip_first_screenshot=True):
        """
        Press "claim all" on the battle pass page.

        The pass page has no greyed-out variant captured yet, so the loop is
        limited by `max_click` instead of an exit asset.

        Pages:
            in: page_pass
            out: page_pass
        """
        # The pass page fades in, and ui_ensure() returns on that half drawn
        # frame. Settle it first, otherwise the color check point below reads
        # "no claim button" and the pass rewards are silently skipped.
        if not self.appear_settled(PASS_CLAIM_ALL, timeout=3, skip_first_screenshot=skip_first_screenshot):
            logger.warning('Claim all button not found, battle pass skipped')
            return 0
        return self.claim_all(PASS_CLAIM_ALL, disabled=None, max_click=3)
