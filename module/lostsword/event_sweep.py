"""Sweeping of the event (活动) tab.

The stage list of an event carries a 「一键扫荡」 button next to 「选择」. Pressing
it raises the shared 「副本一键扫荡」 panel - the same one the copy (副本) tab
uses - which lists the stages with nothing ticked.

Three details of that panel are worth knowing:

- It refuses to sweep with nothing ticked, and answers with a one-line notice
  instead. 一键选择 is what ticks everything.
- An event whose sweep tries are spent still shows the button, and the game
  answers the press with a notice rather than the panel. That notice, not the
  button, is what tells "no tries left".
- The press itself is swallowed while the stage list is still settling, so it is
  repeated.

The page checks and waits used here live in `event_monitor.py`.
"""

from module.base.timer import Timer
from module.logger import logger
from module.lostsword.assets import (COPY_BTN_SELECT_ALL, COPY_BTN_SWEEP_ALL,
                                     EVENT_BTN_SWEEP_ALL, REWARD_POPUP_TITLE)
from module.lostsword.utils import match

# The 确认 of the one-line notices of this game.
EVENT_DIALOG_OK = (644, 468)
# The X of the 「副本一键扫荡」 panel.
EVENT_PANEL_CLOSE = (1146, 64)
# The 「一键扫荡」 button of the stage list, bottom left corner.
SWEEP_BUTTON_REGION = (600, 610, 900, 720)
MATCH_THRESHOLD = 0.85


class EventSweep:
    """
    Sweep the open event through the shared 「副本一键扫荡」 panel.

    Mixed into `LostswordEvent` next to `EventMonitor`, and it leans on both:

    - from `EventMonitor`: `on_stage_page()`, `event_notice_appear()`,
      `event_wait_title()`
    - from `LostswordUI`: `tap_point()`, `tap_asset()` (the panel buttons ignore
      the minitouch tap) and `handle_reward_popup()`
    - from the framework: `self.loop()`, `wait_until_appear/disappear/still()`

    The sweep panel itself is shared with the copy task, so it is recognised by
    its own title rather than by the page underneath it.
    """

    # ------------------------------------------------------------------- sweep

    def event_sweep(self):
        """
        Sweep the event if it still has sweep tries.

        An event whose stages are all cleared may have no sweep at all, so the
        button decides: no 「一键扫荡」 means there is nothing to sweep here. The
        button does not tell whether tries are left - it looks the same with none
        - so the panel is opened and the sweep is tried; an empty sweep only
        raises a notice, which is dismissed.

        Pages:
            in: stage list of the event
            out: stage list of the event

        Returns:
            bool: If a sweep paid out.
        """
        if not self.on_stage_page():
            return False
        if not self.sweep_button_appear():
            logger.info('No 一键扫荡 on this event, nothing to sweep')
            return False

        logger.hr('Sweep the event', level=2)
        state = self.sweep_panel_open()
        if state == 'empty':
            logger.info('The sweep has no tries left')
            return False
        if state != 'open':
            logger.warning('The sweep panel did not open')
            return False

        # The panel lists the stages with nothing ticked and refuses to sweep
        # that way, so everything is selected first.
        self.tap_asset(COPY_BTN_SELECT_ALL)
        # Ticking repaints the sweep button and the ticks animate; waiting for
        # the panel to stop changing is the same wait without a fixed pause.
        self.wait_until_still(COPY_BTN_SWEEP_ALL.area, timeout=2)

        for attempt in range(2):
            self.tap_asset(COPY_BTN_SWEEP_ALL)
            if self.event_wait_title(REWARD_POPUP_TITLE, timeout=5):
                self.handle_reward_popup()
                logger.info('Swept the event')
                return True
            logger.info('No reward popup, press 一键扫荡 again')

        logger.info('The sweep paid nothing, no tries left')
        self.sweep_panel_dismiss()
        return False

    def sweep_button_appear(self):
        """
        Whether the stage list shows a 「一键扫荡」 button.

        Returns:
            bool: If the button is in the bottom left corner.
        """
        return match(self.device.image, EVENT_BTN_SWEEP_ALL,
                     (600, 610, 900, 720)) > 0.85

    def sweep_panel_open(self, timeout=5):
        """
        Open the 「副本一键扫荡」 panel of the stage page.

        The press is routinely swallowed while the stage page is still settling,
        so it is repeated; and an empty sweep answers with a one-line notice
        instead of the panel.

        Args:
            timeout (int, float): Seconds to wait for the panel per attempt.

        Returns:
            str: 'open', 'empty' when the game answers with a notice instead, or
                'failed' when nothing happened at all.
        """
        tries = 3
        pressed = 0
        retry = Timer(2).start()
        deadline = Timer(timeout * tries).start()

        for _ in self.loop():
            # End - the panel is up.
            if self.sweep_panel_appear():
                return 'open'

            # End - the game answered with a notice: no tries left.
            if self.event_notice_appear():
                logger.info('The sweep answered with a notice, no tries left')
                self.event_notice_dismiss()
                return 'empty'

            # Click - one press per two seconds, the same ladder the notices use.
            if pressed < tries and retry.reached():
                retry.reset()
                pressed += 1
                self.tap_asset(EVENT_BTN_SWEEP_ALL)
                continue

            if deadline.reached():
                return 'failed'

    def sweep_panel_appear(self):
        """
        Whether the 「副本一键扫荡」 panel is on screen.

        Returns:
            bool: If its title is drawn somewhere on the screen.
        """
        return match(self.device.image, COPY_BTN_SWEEP_ALL,
                     (0, 0, 1280, 720)) > 0.85

    def sweep_panel_dismiss(self, timeout=6):
        """
        Close the notice of an empty sweep, then the panel itself.

        A sweep without tries answers with a one-line notice and a single wide
        button in the middle of the screen; the panel stays up behind it.
        """
        if self.event_notice_appear():
            self.event_notice_dismiss()

        if not self.wait_until_appear(COPY_BTN_SWEEP_ALL, offset=30, timeout=2):
            return
        self.tap_point(*EVENT_PANEL_CLOSE)
        self.wait_until_disappear(COPY_BTN_SWEEP_ALL, offset=30, timeout=timeout,
                                  settle=2)

    def event_notice_dismiss(self, timeout=5):
        """
        Press the 确认 of a one-line notice until it is gone.

        The notice fades in and swallows the first tap, so the press is repeated.

        Pages:
            in: the page with a notice on top of it
            out: the same page

        Args:
            timeout (int, float): Seconds.

        Returns:
            bool: If the notice left.
        """
        retry = Timer(1.5).start()
        deadline = Timer(timeout).start()

        for _ in self.loop():
            # End - the notice is gone.
            if not self.event_notice_appear():
                return True

            # Click - its only button.
            if retry.reached():
                retry.reset()
                self.tap_point(*EVENT_DIALOG_OK)

            if deadline.reached():
                logger.warning('The notice did not close')
                return False
