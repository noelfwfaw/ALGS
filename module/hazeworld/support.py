from module.base.timer import Timer
from module.hazeworld.assets import (SUPPORT_CLAIM_1, SUPPORT_CLAIM_2,
                                     SUPPORT_CLAIM_3)
from module.hazeworld.hazeworld_ui import HazeworldUI, page_support
from module.logger import logger

# One claim button per support character, top to bottom.
SUPPORT_CLAIMS = [SUPPORT_CLAIM_1, SUPPORT_CLAIM_2, SUPPORT_CLAIM_3]

# A claim that yields coins opens the reward popup, and the popup takes a moment
# to be drawn. Clicking the next button before the popup is gone is swallowed,
# so claims are spaced out by this much. It doubles as the anti double click
# interval every click needs.
CLAIM_INTERVAL = 2

# Right after a click the panel shows a short dark overlay that hides the next
# claim button for about 0.3s (seen on a real client). A missing button is only
# believed after it stayed missing for this long, otherwise the loop stops after
# the first character.
EMPTY_SETTLE = 2


class HazeworldSupport(HazeworldUI):
    """
    Claim the friendship coin of every support character.

    Pages:
        in: page_main
        out: page_main
    """

    def run(self):
        logger.hr('Support coin claim', level=1)
        self.ui_ensure(page_support)

        if self.config.HazeworldSupport_ClaimAll:
            self.support_claim_all()

        self.ui_goto_main()

        # Daily task, run again after the game refreshes. The panel states the
        # daily cap is 50000, a full day is needed to fill it again.
        self.config.task_delay(server_update=True)

    def support_claim_all(self, skip_first_screenshot=True):
        """
        Press the claim button of every character, top to bottom.

        The button looks the same before and after claiming, only the amount
        above it drops to 0, so there is no disabled state to use as an exit
        condition. The loop is bounded by the number of slots instead, and
        stops early on the first empty slot.

        Pages:
            in: page_support
            out: page_support

        Returns:
            int: Times clicked.
        """
        # The panel fades in and ui_ensure() returns on that half drawn frame.
        # Settle it first, otherwise the claim buttons read as absent and the
        # whole panel is skipped.
        if not self.appear_settled(SUPPORT_CLAIM_1, timeout=5, skip_first_screenshot=skip_first_screenshot):
            logger.warning('No support character found, green coin skipped')
            return 0

        count = 0
        # A timer that is not started is reached at once, so the first click
        # goes through right away and `reset()` spaces out the following ones.
        interval = Timer(CLAIM_INTERVAL)
        # Started on the first frame where the next button is missing.
        empty = None

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # The popup covers the panel, so it must be handled before the
            # buttons below.
            if self.handle_support_reward():
                continue

            if count >= len(SUPPORT_CLAIMS):
                break

            claim = SUPPORT_CLAIMS[count]
            if self.appear(claim, offset=None):
                empty = None
                # Keep looping while the interval runs, the popup check above
                # then gets a few more frames to notice the reward popup.
                if interval.reached():
                    logger.info(f'Claim support coin ({count + 1})')
                    self.device.click(claim)
                    count += 1
                    interval.reset()
                continue

            # The slots are a vertical list, the ones below are empty as well,
            # but the overlay of the click above looks exactly like that.
            if empty is None:
                empty = Timer(EMPTY_SETTLE).start()
                continue
            if not empty.reached():
                continue

            logger.info(f'Support slot {count + 1} is empty')
            break

        logger.info(f'Support coin claimed {count} times')
        return count
