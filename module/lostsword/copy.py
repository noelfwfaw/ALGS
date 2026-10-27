from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import get_color
from module.logger import logger
from module.lostsword.assets import (ARENA_BTN_CLOSE, COPY_BTN_ONEKEY,
                                     COPY_BTN_SELECT, COPY_BTN_SELECT_ALL,
                                     COPY_BTN_SWEEP_ALL, COPY_TAB,
                                     REWARD_POPUP_TITLE)
from module.lostsword.lostsword_ui import LostswordUI, page_battle

"""
Copy sweep (副本扫荡, sweeping the repeatable stages).

Flow observed in game:

    page_main -- bottom bar 「战斗」 --> page_battle -- top 「副本」 tab --> stage
                                         cards
    cards -- any sweepable card --> stage page (area / enemies / loot)
    stage page -- bottom 「一键扫荡」 --> 「副本一键扫荡」 panel
    panel -- 「一键选择/取消」 --> three rows ticked (gold / exp books / attribute
                                  stones)
    panel -- bottom 「一键扫荡」 --> 「已获得道具。」 --> close
    stage page -- top right round X --> cards (one more X back to page_battle)

**One stage page covers all three resources.** Opening 一键扫荡 from any sweepable
stage raises a panel that lists 金币 / 经验书 / 火焰属性副本 together, each with its
3/3 daily free sweeps; ticking 一键选择 and pressing 一键扫荡 collects the lot
(measured: 119万 gold + 28,125 exp books + 18 attribute stones in one popup). So the
task opens one stage page only, instead of walking three cards.

Two details that the panel insists on:

- It comes up with **nothing ticked**, and pressing 一键扫荡 in that state only
  raises 「未选择任何副本。」 with a 确认 button. 一键选择 is what ticks the three
  rows (and the daily-free sub-rows under them).
- The cards need a longer press than minitouch's default tap: `device.click()`
  never opened a card over four attempts, while `adb shell input tap` on the same
  coordinates opened it every time.

The stage list scrolls and its content changes (today: 巨石阵 / 经验书 / 黄金猎犬 /
属性石), so the cards are tried in order and the first one whose page shows
「一键扫荡」 is used. 巨石阵 is a limited stage without that button and is skipped.
"""

# Card slots 2..4 of the stage list: the first card is the limited 巨石阵 by
# default, the sweepable ones follow it.
COPY_CARD_SLOTS = ((530, 450), (890, 450), (1160, 450))

# The 确认 button of the small dialogs on the stage page (no tries left, nothing
# ticked); they all use the same box in the middle of the screen.
COPY_DIALOG_CONFIRM = (504, 450, 788, 486)

# The reward popup covers the whole screen and its middle band holds the item
# icons, so the dismissing tap goes to the blank strip above them.
COPY_POPUP_CLOSE_TAP = Button(area=(600, 90, 680, 130), color=(0, 0, 0),  # alas-lint: allow - a click point on a blank part of a panel
                              button=(600, 90, 680, 130),
                              name='COPY_POPUP_CLOSE_TAP')  # alas-lint: allow


class LostswordCopy(LostswordUI):
    """
    Sweep the three repeatable stages through the shared 一键扫荡 panel.

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
        logger.hr('Copy sweep', level=1)
        self.ui_ensure(page_battle)
        if not self.copy_goto_tab():
            logger.warning('Cannot open the 副本 tab')
        elif self.copy_open_stage():
            self.copy_sweep_all()
        else:
            logger.warning('No sweepable stage found')

        self.ui_goto_main()
        # The sweeps are per-day, refreshed at the daily reset of this game.
        self.config.task_delay(server_update=True)

    def copy_goto_tab(self, timeout=10):
        """
        Open the 副本 tab of the battle page.

        The selected tab is drawn on a cream pill (mean 208) and the idle ones on
        the dark panel (58), the same brightness trick as the 普通 tab.

        Pages:
            in: page_battle
            out: page_battle

        Args:
            timeout (int, float): Seconds.

        Returns:
            bool: If the tab is open.
        """
        timeout = Timer(timeout).start()

        for _ in self.loop():
            # End - the pill of this tab is the cream one.
            color = get_color(self.device.image, COPY_TAB.area)
            if sum(color) / 3 > 140:
                # The card list keeps the offset it was left at; put it back so
                # the slots below sit where they are expected.
                self.battle_scroll(forward=False)
                return True

            # Click - the tab is always on screen, the pill colour above is what
            # decides, so the press is the usual interval throttled one.
            if self.appear_then_click(COPY_TAB, offset=30, interval=1.5):
                continue

            if timeout.reached():
                logger.warning('Cannot open the 副本 tab')
                return False

    def copy_open_stage(self, timeout=5):
        """
        Open a stage page that has the 「一键扫荡」 button.

        Pages:
            in: page_battle (stage list)
            out: stage page

        Args:
            timeout (int, float): Seconds to wait for a stage page per attempt.

        Returns:
            bool: If such a page is open.
        """
        for index, point in enumerate(COPY_CARD_SLOTS, 2):
            logger.info(f'Try card slot {index}')
            # `adb tap` instead of `device.click`: the cards ignore the shorter
            # minitouch tap (measured four times, then four successful adb taps).
            self.device.adb_shell(['input', 'tap', str(point[0]), str(point[1])])  # alas-lint: allow

            if self.wait_until_appear(COPY_BTN_ONEKEY, offset=30, timeout=timeout):
                logger.info(f'Stage page opened from slot {index}')
                return True

            logger.info(f'Slot {index}: no 一键扫荡 here, go back')
            if self.appear(ARENA_BTN_CLOSE, offset=30):
                self.device.click(ARENA_BTN_CLOSE)
                # The card list has to be back before the next slot is pressed,
                # otherwise the tap lands on a page that is still sliding out.
                self.wait_until_disappear(COPY_BTN_SELECT, offset=30, timeout=5, settle=2)

        return False

    def copy_sweep_all(self, timeout=4):
        """
        Open the shared sweep panel, tick everything, sweep, and close the popup.

        Pages:
            in: stage page
            out: stage page

        Args:
            timeout (int, float): Seconds to wait for each panel.

        Returns:
            bool: If a reward popup was claimed.
        """
        logger.info('Open the 副本一键扫荡 panel')
        # The first tap on 一键扫荡 is routinely swallowed (measured three times
        # in a row: the button raised nothing, the very same tap a second later
        # raised the panel), so the press is repeated while the panel is not up.
        for _ in range(3):
            self.tap_asset(COPY_BTN_ONEKEY)
            if self.wait_until_appear(COPY_BTN_SWEEP_ALL, offset=30, timeout=timeout):
                break
        else:
            # With the daily tries spent the panel never appears: the game
            # answers the press with a small "no tries left" dialog instead.
            logger.info('Sweep panel did not open, no tries left today')
            self.copy_dismiss_dialog()
            return False

        # The panel opens with nothing ticked and refuses to sweep that way.
        self.tap_asset(COPY_BTN_SELECT_ALL)
        # Ticking repaints the sweep button (it goes from grey to lit) and the
        # ticks animate, so wait for the plate to stop changing rather than for
        # a fixed pause.
        self.wait_until_still(COPY_BTN_SWEEP_ALL.area, timeout=2)

        logger.info('Sweep everything')
        for _ in range(3):
            self.tap_asset(COPY_BTN_SWEEP_ALL)
            if self.wait_until_appear(REWARD_POPUP_TITLE, offset=30, timeout=timeout):
                break
        else:
            logger.warning('No reward popup after sweeping')
            self.copy_close_panel()
            return False

        self.handle_reward_popup(button=COPY_POPUP_CLOSE_TAP)
        self.copy_close_panel()
        return True

    def copy_dismiss_dialog(self, timeout=3):
        """
        Close the small dialog the game answers with (no tries left, nothing
        ticked). It carries a single wide 确认 button in the middle of the screen.

        Pages:
            in: stage page with a dialog on top
            out: stage page

        Args:
            timeout (int, float): Seconds to wait for the dialog to close.

        Returns:
            bool: If a dialog was dismissed.
        """
        # Still on the stage page with a dialog on top: press its only button.
        if not self.wait_until_appear(COPY_BTN_ONEKEY, offset=30, timeout=2):
            return False

        x1, y1, x2, y2 = COPY_DIALOG_CONFIRM
        self.device.adb_shell(['input', 'tap',
                               str((x1 + x2) // 2), str((y1 + y2) // 2)])  # alas-lint: allow
        # The dialog fades out over the button box that was just pressed, so the
        # frame is only trusted once that box stops changing.
        return self.wait_until_still(COPY_DIALOG_CONFIRM, timeout=timeout)

    def copy_close_panel(self, timeout=5):
        """
        Leave the sweep panel and the stage page, back to the card list.

        Pages:
            in: sweep panel or stage page
            out: page_battle (card list)

        Args:
            timeout (int, float): Seconds to wait for each panel to leave.

        Returns:
            bool: If the card list is back.
        """
        self.device.screenshot()

        if self.appear(COPY_BTN_SWEEP_ALL, offset=30):
            if self.appear(ARENA_BTN_CLOSE, offset=30):
                self.device.click(ARENA_BTN_CLOSE)
            self.wait_until_disappear(COPY_BTN_SWEEP_ALL, offset=30, timeout=timeout, settle=2)

        if self.appear(COPY_BTN_ONEKEY, offset=30):
            if self.appear(ARENA_BTN_CLOSE, offset=30):
                self.device.click(ARENA_BTN_CLOSE)
            self.wait_until_disappear(COPY_BTN_ONEKEY, offset=30, timeout=timeout, settle=2)

        return self.appear(COPY_TAB, offset=30)
