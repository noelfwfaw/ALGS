from module.base.timer import Timer
from module.logger import logger
from module.lostsword.assets import (REWARD_POPUP_TITLE, TREASURE_BTN_CLAIM,
                                    TREASURE_BTN_QUICK, TREASURE_DIALOG_FREE,
                                    TREASURE_DIALOG_PAID, TREASURE_QUICK_CLOSE,
                                    TREASURE_QUICK_TITLE)
from module.lostsword.lostsword_ui import LostswordUI, page_treasure
from module.lostsword.utils import match

"""
Treasure exploration (宝藏探索).

Flow observed in game:

    page_main -- treasure entry --> page_treasure
    page_treasure  获取宝藏     -> 已获得道具。 popup (tap a blank spot to close)
    page_treasure  快速探查     -> quick explore dialog
        the bottom button reads 「开始探查」 while the free try of the day is
        there: one press awards 120 minutes of treasure straight away.
        once it is gone the same button reads 「💎90 开始探查」, and the dialog
        is only closed, never paid for.
    page_treasure  close X      -> page_main

Two timing traps, both of them cost resources or open a wrong popup:

- The reward popup fades out *after* its title is gone. A click sent during the
  fade lands on the item list of that popup and opens the item detail page
  instead of the button underneath, so every "popup is gone" check needs the
  settle window of `LostswordUI.wait_overlay_gone()`.
- Every button here is missing on the frames while its panel slides in. Asking
  "is it there?" on the frame `Page arrive` was logged answers no, and a run is
  over before it started (measured 2026-10-29: `Quick explore button not found`
  nine milliseconds after `Page arrive`). Buttons are waited for, not looked up
  once.

And one trap that costs diamonds:

Reading only the paid side of the start button answers "free" for every frame
that fails to match it, including the ones that show nothing yet. The previous
version covered that up with a timeout that fell back to "assume it is paid",
which is safe but never once claimed the free try (measured 2026-10-29: two
runs, two skips). The two versions of the button are the same box, so both are
kept as templates and the answer is whichever one the frame looks more like -
see `treasure_quick_is_free()`.
"""

# Reading whether the start button still costs nothing is a comparison between
# two templates taken at the very same box. Measured 2026-10-29:
#
#   frame          free    paid
#   免费 (1 try)   0.994   0.185
#   付费 (90 💎)   0.185   0.961
#   宝藏面板       0.070  -0.041
#   奖励弹窗       0.107  -0.132
#   大厅          -0.003   0.108
#   竞技场列表      0.044   0.112
#
# The threshold keeps a blank or half drawn frame from counting as either
# answer, and the margin insists the winner wins clearly. Should a future
# version of the dialog ever put both templates in the same ballpark, doing
# nothing loses one day of treasure while guessing wrong spends 90 diamonds on
# the spot, and there is no undo for that.
TREASURE_QUICK_MIN_SIMILARITY = 0.80
TREASURE_QUICK_MARGIN = 0.10


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
        not a failure. The button is waited for instead of looked up once: the
        frame the panel arrives on predates its own buttons.

        Pages:
            in: page_treasure
            out: page_treasure

        Returns:
            bool: If a reward popup was handled.
        """
        for _ in range(2):
            if self.wait_until_appear(TREASURE_BTN_CLAIM, offset=30, timeout=3):
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
        never worth it: close the dialog and leave. Whether it is gone is read,
        never assumed, because pressing the paid button spends them straight
        away.

        Pages:
            in: page_treasure
            out: page_treasure

        Returns:
            bool: If an exploration was started.
        """
        # The panel has just arrived, and the frame `Page arrive` is logged on
        # predates the buttons in it, so asking once and giving up kills the run
        # before it starts (that is what 2026-10-29 02:03 did). The press is
        # tried twice the same way: it lands during the slide-in now and then,
        # and nothing comes of it.
        for _ in range(2):
            if self.wait_until_appear(TREASURE_BTN_QUICK, offset=30, timeout=4,
                                      settle=self.SETTLE_FRAMES):
                self.device.click(TREASURE_BTN_QUICK)
            else:
                logger.warning('Quick explore button not found, skipped')
                return False
            if self.wait_overlay(TREASURE_QUICK_TITLE, timeout=5):
                break
        else:
            logger.warning('Quick explore dialog did not open, skipped')
            return False

        free = self.treasure_quick_is_free()
        if free is None:
            logger.warning('Cannot tell whether this one is free, skipped')
            self.treasure_quick_close()
            return False
        if not free:
            logger.info('Free attempt used up, starting one costs 90 diamonds, skipped')
            self.treasure_quick_close()
            return False

        logger.info('Free attempt available, start exploring')
        # The dialog matches from the first frame of its fade-in, so the button
        # itself is waited for until it is drawn. `TREASURE_DIALOG_FREE` carries
        # both the shape of that button and its coordinates: both versions of it
        # fill the same box, and this branch only runs while the free one is up.
        #
        # An exploration that started shows itself one of two ways: the reward
        # popup comes up, or the dialog closes back to the panel with the timer
        # running from there. Neither one happening is what a swallowed press
        # looks like, so the press gets a second try, and that one goes through
        # adb: some buttons of this game ignore a minitouch short press
        # altogether (the arena result page does, measured 2026-10-29).
        for attempt in range(2):
            if self.wait_until_appear(TREASURE_DIALOG_FREE, offset=30, timeout=6,
                                      settle=self.SETTLE_FRAMES):
                if attempt:
                    self.tap_asset(TREASURE_DIALOG_FREE)
                else:
                    self.device.click(TREASURE_DIALOG_FREE)
            if self.treasure_wait_quick_result(timeout=10):
                return True

        logger.warning('Nothing came of the start button, skipped')
        self.treasure_quick_close()
        return False

    def treasure_quick_is_free(self, timeout=8):
        """
        Read whether one more press of the quick-explore start button is free.

        The two versions of that button sit at the same place with the same
        size, so there is nothing but their own pixels to tell them apart: the
        free one reads 「开始探查」, and once the free try of the day is gone the
        very same button reads 「💎90 开始探查」. Both are kept as templates of
        the same box and the answer is whichever one the frame looks more like.

        Reading only the paid side answers "free" for every frame that fails to
        match it, including frames that show nothing yet, which is how the daily
        free try went unclaimed every run until now (measured 2026-10-29: two
        runs, two skips). Frames during the fade-in are unreadable rather than
        wrong: neither template reaches `TREASURE_QUICK_MIN_SIMILARITY` then, so
        the wait simply goes on to the next one.

        Args:
            timeout (int, float): Seconds.

        Returns:
            bool: True when one press is free, False when it costs diamonds.
            None: Unreadable on every frame of the wait. This is deliberately
                not answerable either way: closing the dialog loses a day of
                treasure, pressing the wrong version spends 90 diamonds.
        """
        timeout = Timer(timeout).start()
        area = TREASURE_DIALOG_FREE.area
        free_score = paid_score = 0.0
        answer = None
        agree = 0

        for _ in self.loop():
            image = self.device.image
            free_score = match(image, TREASURE_DIALOG_FREE, area)
            paid_score = match(image, TREASURE_DIALOG_PAID, area)

            if max(free_score, paid_score) < TREASURE_QUICK_MIN_SIMILARITY:
                verdict = None
            elif free_score - paid_score > TREASURE_QUICK_MARGIN:
                verdict = True
            elif paid_score - free_score > TREASURE_QUICK_MARGIN:
                verdict = False
            else:
                verdict = None

            if verdict is None or verdict != answer:
                answer = verdict
                agree = 0 if verdict is None else 1
            else:
                agree += 1
            if verdict is not None and agree >= self.SETTLE_FRAMES:
                return verdict

            if timeout.reached():
                break

        logger.warning('Quick explore price unreadable (free=%.2f paid=%.2f), '
                       'nothing pressed' % (free_score, paid_score))
        return None

    def treasure_quick_close(self):
        """
        Close the quick-explore dialog without pressing anything inside it.

        Pages:
            in: page_treasure_quick
            out: page_treasure
        """
        if self.appear(TREASURE_QUICK_CLOSE, offset=30):
            self.device.click(TREASURE_QUICK_CLOSE)
        self.wait_overlay_gone(TREASURE_QUICK_TITLE)

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
