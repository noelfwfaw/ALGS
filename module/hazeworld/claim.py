from module.base.timer import Timer
from module.logger import logger


# How a claim loop waits for the page to make up its mind.
#
# A button that is neither in its clickable look nor in its disabled one is a
# button in transition - it plays its own animation after a press and fades in
# after a tab switch - and such a frame is not evidence either way. Without a
# `disabled` asset to match there is only absence to go on, and one frame of
# absence is what every redraw looks like, so it takes this many frames in a row
# before the button counts as gone.
CLAIM_EMPTY_FRAMES = 3

# Seconds before the same button may be pressed again.
#
# A press takes a moment to be drawn: the button plays its own animation and the
# list behind it is redrawn. Reading "still clickable" on the very next frame is
# therefore not evidence that a second claim is available - it is usually the
# first press that has not landed on screen yet - and pressing again on it is how
# the log once showed twenty presses in a row. One press per second is faster
# than the animation and slower than the frame rate.
CLAIM_PRESS_INTERVAL = 1

# The net for a page that never gives an answer at all. Nothing waits this long
# in a normal run: an empty button is settled in one frame when there is a
# `disabled` asset, and a full one is pressed on the frame it is seen.
CLAIM_UNKNOWN_TIMEOUT = 5


class Claim:
    """
    The "claim all" loop, shared by every hazeworld task.

    Mixed into `HazeworldUI`, which provides `appear()`, `device` and
    `handle_reward()`.
    """

    def claim_state(self, claim, disabled=None, available=None):
        """
        What the "claim all" button says on the current frame.

        A button that is animating shows neither of its two looks: this game
        plays a pressed animation after every tap, and fades the button in after
        a tab switch. A frame of that has no answer in it, which is a state of
        its own and has to be reported as one - folding it into "nothing to
        claim" is what made a task skip a tab it had just opened.

        Args:
            claim (Button): Claim all button, matches when it is clickable.
            disabled (Button): The same button in its disabled look. None when
                the asset does not exist, in which case only "clickable" and
                "no answer" are told apart.
            available (callable): Decides "there is something to claim" instead
                of `appear(claim)`.

        Returns:
            True: There is something to claim and the button can be pressed.
            False: The button is drawn in its disabled look.
            None: Neither - the frame caught the button animating.
        """
        if available is not None:
            clickable = available()
        else:
            clickable = self.appear(claim, offset=None)

        if clickable:
            return True
        if disabled is not None and self.appear(disabled, offset=None):
            return False
        return None

    def claim_press(self, claim, available=None):
        """
        Press the claim button, on a frame `claim_state()` already accepted.

        Only one of the two judgements may decide the press. When `available` is
        given it already answered "the button is there" with a measure the asset
        can support - a colour spread, a label match. Asking the template
        afterwards is a second, stricter opinion that some assets can never
        give: the stored crop of `PASS_CLAIM_ALL` is its disabled look, so a
        match refuses the very frame that says click me.

        Args:
            claim (Button): Claim all button.
            available (callable): The judgement `claim_state()` used, if any.
        """
        if available is not None or self.appear(claim, offset=(20, 20)):
            self.device.click(claim)

    def claim_all(self, claim, disabled=None, max_click=20, available=None,
                  skip_first_screenshot=True):
        """
        Click the "claim all" button until there is nothing left to claim.

        The caller makes sure the page is drawn - a caller that switches a tab
        waits with `wait_until_still()` first. A frame that `claim_state()`
        cannot answer keeps the loop going: only the disabled look is proof.

        Args:
            claim (Button): Claim all button, only matches when it is clickable.
            disabled (Button): The same button in disabled state, the positive
                exit condition. None to exit by absence, which takes
                `CLAIM_EMPTY_FRAMES` frames to be believed.
            max_click (int): Safety limit, to avoid clicking forever.
            available (callable): Decides "there is something to claim" instead
                of `appear(claim)`, see `HazeworldTask.task_claim_available`.
            skip_first_screenshot (bool):

        Returns:
            int: Times clicked.
        """
        count = 0
        empty = 0
        # Runs from the last frame that gave an answer. A net for a page that
        # never settles, not a wait.
        unknown = Timer(CLAIM_UNKNOWN_TIMEOUT).start()
        # Starts out reached, so the first press is never delayed.
        press = Timer(CLAIM_PRESS_INTERVAL)

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handle_reward():
                empty = 0
                unknown.reset()
                continue

            state = self.claim_state(claim, disabled=disabled, available=available)

            if state is True:
                if not press.reached():
                    # The previous press has not been drawn yet, so this frame
                    # is still showing what was just claimed.
                    continue
                if count >= max_click:
                    logger.warning(f'Claim all clicked {count} times, stop')
                    break
                logger.info(f'Claim all ({count + 1})')
                self.claim_press(claim, available=available)
                # The counter follows the press, never the judgement: it used to
                # be incremented on a frame where the press was skipped, and the
                # log claimed twenty clicks for a pass that was never claimed.
                count += 1
                press.reset()
                empty = 0
                unknown.reset()
                continue

            if state is False:
                logger.info('Nothing left to claim')
                break

            # No answer. Without a `disabled` asset to match, that is all this
            # loop will ever see once the button is gone, so a few frames of it
            # are the exit condition; with one, the loop waits for the button to
            # finish animating, and `unknown` is only there to stop the wait
            # from lasting forever.
            empty += 1
            if disabled is None and empty >= CLAIM_EMPTY_FRAMES:
                logger.info(f'{claim.name} is gone')
                break
            if unknown.reached():
                logger.warning(f'{claim.name} shows neither state, giving up')
                break

        logger.info(f'Claim all finished, clicked {count} times')
        return count
