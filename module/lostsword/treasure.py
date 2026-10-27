from module.base.button import Button
from module.base.timer import Timer
from module.logger import logger
from module.lostsword.assets import (REWARD_POPUP_TITLE, TREASURE_BTN_CLAIM,
                                    TREASURE_BTN_QUICK, TREASURE_DIALOG_PAID,
                                    TREASURE_QUICK_CLOSE, TREASURE_QUICK_TITLE)
from module.lostsword.lostsword_ui import LostswordUI, page_treasure

"""
Treasure exploration (宝藏探索).

Flow observed in game:

    page_main -- treasure entry --> page_treasure
    page_treasure  获取宝藏     -> 已获得道具。 popup (tap a blank spot to close)
    page_treasure  快速探查     -> quick explore dialog
        first attempt of the day is free: the bottom reads 「开始探查」 and one
        press awards 120 minutes of treasure straight away.
        once it is used up the bottom reads 「💎90 开始探查」, and the dialog is
        only closed, never paid for.
    page_treasure  close X      -> page_main

Two timing traps, both of them cost resources or open a wrong popup:

- The reward popup fades out *after* its title is gone. A click sent during the
  fade lands on the item list of that popup and opens the item detail page
  instead of the button underneath, so every "popup is gone" check needs the
  settle window of `LostswordUI.wait_overlay_gone()`.
- The quick-explore dialog fades in. Its price row ("💎90 开始探查") does not
  match until it is drawn, so "not matched" must not be read as "free attempt
  available", otherwise the script presses start and spends 90 diamonds.
"""

# The bottom button of the quick explore dialog: 「开始探查」 when free, 「💎90
# 开始探查」 when it costs diamonds, at the same place and size either way. The
# asset of the paid version is reused for its geometry only, so this is an alias
# of an existing asset and not a hand drawn button.
TREASURE_QUICK_START = Button(area=TREASURE_DIALOG_PAID.area,  # alas-lint: allow - a click point alias of a generated asset
                              color=TREASURE_DIALOG_PAID.color,
                              button=TREASURE_DIALOG_PAID.button,
                              name='TREASURE_QUICK_START')  # alas-lint: allow


class LostswordTreasure(LostswordUI):
    """
    Claim the accumulated treasure, then spend the free quick-explore of the day.

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
        logger.hr('Treasure explore', level=1)
        self.ui_ensure(page_treasure)

        if self.config.LostswordTreasure_Claim:
            self.treasure_claim()
        if self.config.LostswordTreasure_Quick:
            # Closing the reward popup takes the panel with it (one tap is
            # consumed by the popup and by the panel underneath), so the panel
            # is entered again instead of assumed to be still open.
            self.ui_ensure(page_treasure)
            self.treasure_quick()

        self.ui_goto_main()

        # Treasure accumulates by the minute, but one claim a day is enough, so
        # it follows the daily reset.
        self.config.task_delay(server_update=True)

    def treasure_claim(self):
        """
        Claim the treasure and dismiss the reward popup.

        The button looks the same whether there is something to claim or not,
        so "clicked and no popup came up" means nothing has accumulated yet,
        not a failure. The click is retried once because the panel slides in
        and a click sent during that animation is swallowed by the input lock.

        Pages:
            in: page_treasure
            out: page_treasure

        Returns:
            bool: If a reward popup was handled.
        """
        for _ in range(2):
            if self.appear(TREASURE_BTN_CLAIM, offset=30):
                self.device.click(TREASURE_BTN_CLAIM)
            else:
                logger.info('Claim button not found')
                break
            if self.wait_overlay(REWARD_POPUP_TITLE, timeout=5):
                logger.info('Treasure claimed, dismiss the reward popup')
                return self.handle_reward_popup()

        logger.info('Nothing to claim yet')
        return False

    def treasure_quick(self):
        """
        Open the quick-explore dialog and spend the free attempt of the day.

        When the free attempt is gone the dialog asks for 90 diamonds, which is
        never worth it: close the dialog and leave.

        Pages:
            in: page_treasure
            out: page_treasure

        Returns:
            bool: If an exploration was started.
        """
        for _ in range(2):
            if self.appear(TREASURE_BTN_QUICK, offset=30):
                self.device.click(TREASURE_BTN_QUICK)
            else:
                logger.warning('Quick explore button not found, skipped')
                return False
            if self.wait_overlay(TREASURE_QUICK_TITLE, timeout=5):
                break
        else:
            logger.warning('Quick explore dialog did not open, skipped')
            return False

        if self.treasure_wait_paid():
            logger.info('Free attempt used up, starting one costs 90 diamonds, skipped')
            if self.appear(TREASURE_QUICK_CLOSE, offset=30):
                self.device.click(TREASURE_QUICK_CLOSE)
                self.wait_overlay_gone(TREASURE_QUICK_TITLE)
            return False

        logger.info('Free attempt available, start exploring')
        # The dialog is matched from its first fading frame and a press during
        # the fade in is lost, and the start button has no template of its own,
        # so the press is hung off the dialog title being drawn.
        if self.wait_overlay_settle(TREASURE_QUICK_TITLE, timeout=6):
            if self.appear(TREASURE_QUICK_TITLE, offset=30, interval=2):
                self.device.click(TREASURE_QUICK_START)
        self.treasure_wait_quick_result(timeout=30)
        return True

    def treasure_wait_paid(self, frames=None, timeout=5):
        """
        Decide whether the quick explore costs diamonds.

        The price row is drawn with the dialog, so a frame from the fade-in
        matches nothing. Read that as "free" and the script presses start and
        spends 90 diamonds, so the absence has to hold for a settle window too.

        Args:
            frames (int): Consecutive frames without a match needed.
            timeout (int, float): Seconds.

        Returns:
            bool: True if it costs diamonds.
        """
        frames = frames or self.SETTLE_FRAMES
        timeout = Timer(timeout).start()
        absent = 0

        for _ in self.loop():
            # End - the price row is drawn, the free attempt is gone.
            if self.appear(TREASURE_DIALOG_PAID, offset=30, similarity=0.9):
                return True

            # End - the dialog is open and stays without a price row.
            if self.appear(TREASURE_QUICK_TITLE, offset=30):
                absent = 0
            else:
                absent += 1
                if absent >= frames:
                    return False

            if timeout.reached():
                logger.warning('Quick explore price did not settle, assume it is paid')
                return True

    def treasure_wait_quick_result(self, timeout=30):
        """
        Wait until the quick-explore result is settled.

        Two outcomes are known: a reward popup (which is dismissed here), or
        the dialog closing straight back to the panel. Anything else is left to
        the caller, which closes the panel and goes home anyway.

        Args:
            timeout (int, float): Seconds.

        Returns:
            bool: If a result was recognised.
        """
        timeout = Timer(timeout).start()
        absent = 0

        for _ in self.loop():
            # End - the exploration is done, the reward popup is up.
            if self.appear(REWARD_POPUP_TITLE, offset=30):
                logger.info('Exploration finished, dismiss the reward popup')
                return self.handle_reward_popup()

            # End - the dialog left and the panel is back: the exploration runs
            # in the background from here on.
            if self.appear(TREASURE_QUICK_TITLE, offset=30):
                absent = 0
            else:
                absent += 1
                if absent >= self.SETTLE_FRAMES:
                    logger.info('Exploration started')
                    return True

            if timeout.reached():
                logger.warning('Quick explore result unknown')
                return False
