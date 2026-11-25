"""Theme theater (主题剧院) limited-time event automation for Trickcal.

Flow covered in this module:

    page_main --top-left event icon--> [cutscene skip / tutorial X] --> page_event
    page_event --战斗--> page_event_stage
    page_event_stage: walk 微微辣 -> 中辣 -> 变态辣
        uncleared stage (3 dark diamonds) -> 选择卡组 -> formation
        enable 快速战斗 + 开启自动 -> 出发 (+ 直接出发 on 加成提示)
        wait out auto-progression -> dismiss 自动进行结束 / 新的故事 -> 退出 -> page_event_stage
"""

import re

import numpy as np

from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import crop
from module.logger import logger
from module.ocr.ocr import Ocr
from module.trickcal.assets import (
    BACK,
    EVENT_AUTO_END,
    EVENT_BATTLE_AUTO,
    EVENT_BATTLE_EXIT,
    EVENT_BONUS_CONFIRM,
    EVENT_DEPART,
    EVENT_DIFF_HARD_LOCKED,
    EVENT_DIFF_MEDIUM_LOCKED,
    EVENT_NEW_STORY,
    EVENT_SELECT_DECK,
    EVENT_SHOP_CANCEL,
    EVENT_SHOP_REWARD,
    EVENT_STAGE_PERFECT_CLEAR,
    EVENT_STAGE_TITLE,
    EVENT_STAGE_UNCLEARED,
    EVENT_STAMINA_BUY,
    EVENT_SWEEP_BTN,
    EVENT_SWEEP_CANCEL,
    EVENT_SWEEP_CLEAR,
    EVENT_SWEEP_CONFIRM,
    EVENT_SWEEP_MAX,
    EVENT_SWEEP_TITLE,
)
from module.trickcal.assets import EVENT_VICTORY_NEXT
from module.trickcal.event_extra import TrickcalEventExtra
from module.trickcal.page import page_event, page_event_stage, page_main
from module.trickcal.trickcal_ui import (
    STORY_MENU_OFFSET,
    STORY_MENU_SIMILARITY,
    TrickcalUI,
)

EVENT_OFFSET = (20, 20)

# Horizontal sweep for the frontier stage ribbon (322, 220, 456, 260):
# clamped within [0, 1280] x [0, 720] so Button._button_offset shifts cleanly.
STAGE_UNCLEARED_OFFSET = (-280, -40, 780, 40)

# 「退出」 sits at x≈694 on 3-button screens, shifts to x≈796 on 2-button screens,
# and shifts to x≈898 on 1-button last-stage Victory screens (e.g. 中辣 10阶段).
# Measured: 1.000 on Victory, 0.798 even while dimmed behind 自动进行结束, <=0.56 elsewhere.
BATTLE_EXIT_OFFSET = (-40, -20, 300, 20)
BATTLE_EXIT_SIMILARITY = 0.75

# 「前往下一关」 sits at x=1050 on 3-button Victory screens (with 「再次挑战」) and
# shifts left to x=948 on 2-button Victory screens (such as 中辣).
VICTORY_NEXT_OFFSET = (-180, -20, 40, 20)

# Fixed tap rectangles (x1, y1, x2, y2) for widgets that rotate art per event
# or toggle state by colour rather than template; wrapped via `_area_button`.
EVENT_ENTRY_AREA = (325, 140, 392, 212)
EVENT_DIFF_MILD_AREA = (804, 646, 944, 692)
EVENT_DIFF_MEDIUM_AREA = (964, 646, 1102, 692)
EVENT_DIFF_HARD_AREA = (1122, 646, 1260, 692)
EVENT_QUICK_AREA = (840, 634, 902, 682)
EVENT_AUTO_AREA = (1182, 634, 1244, 682)
# Focused frontier stage house on 微微辣 (e.g. stage 10 when cleared).
EVENT_STAGE_FOCUS_AREA = (340, 310, 438, 410)
EVENT_STAMINA_AREA = (896, 26, 1002, 53)

# Bright green toggle circle pixel count threshold (measured: OFF=0, ON=2134/2242).
TOGGLE_GREEN_PIXELS = 500
DIFF_LOCKED_COLOR_THRESHOLD = 25
# Lit yellow 速战 rgb≈(239, 228, 187) vs disabled grey (164, 164, 164).
SWEEP_BTN_COLOR_THRESHOLD = 30
SWEEP_STAMINA_COST = 10
SWEEP_MAX_ROUNDS = 10
SWEEP_TIMEOUT = 15

EVENT_OPEN_TIMEOUT = 45
EVENT_ENTRY_MAX_TAPS = 5
STAGE_OPEN_TIMEOUT = 15
FORM_TIMEOUT = 30
BATTLE_TIMEOUT = 1800
EXIT_HOLD = 10


def _area_button(area, name):
    """Build a tap-only Button for a fixed coordinate rectangle."""
    return Button(area=area, color=(0, 0, 0), button=area, name=name)


def _toggle_is_on(image, area):
    """Return True when the 快速战斗 / 开启自动 toggle circle is lit green."""
    patch = crop(image, area).astype(np.int16)
    green_mask = (
        (patch[:, :, 1] - patch[:, :, 0] > 25)
        & (patch[:, :, 1] - patch[:, :, 2] > 25)
        & (patch[:, :, 1] > 140)
    )
    return int(np.count_nonzero(green_mask)) >= TOGGLE_GREEN_PIXELS


class TrickcalEvent(TrickcalEventExtra, TrickcalUI):
    """
    Theme theater (主题剧院) event task.

    Pages:
        in: page_main
        out: page_main
    """

    def run(self):
        """
        Open the active theme theater event, clear unlocked battle difficulties,
        and return to the lobby.

        Pages:
            in: page_main
            out: page_main
        """
        logger.hr('Trickcal Event', level=1)
        self._out_of_stamina = False
        self.ui_ensure(page_main)
        if not self.event_open():
            logger.warning('Could not open theme theater event, return to lobby')
            self.ui_goto_main()
            self.config.task_delay(server_update=True)
            return

        self.event_battle_clear()
        if self.config.TrickcalEvent_SweepStamina and not self._out_of_stamina:
            self.event_battle_sweep()
        self.event_story_clear()
        self.event_claim_tasks()
        self.event_claim_pass()
        self.event_shop_buy()
        self.ui_goto_main()
        self.config.task_delay(server_update=True)

    def handle_stamina_buy_popup(self):
        """Dismiss 「购买朱珠糖」 by pressing 取消 (never 购买) when stamina is depleted."""
        if self.appear(EVENT_STAMINA_BUY, offset=EVENT_OFFSET, interval=2):
            logger.info('Out of stamina (购买朱珠糖 popup), press 取消')
            self._out_of_stamina = True
            self.device.click(EVENT_STAMINA_BUY)
            return True
        return False

    def _dismiss_stamina_buy(self):
        """Close the 「购买朱珠糖」 popup via 取消 and mark stamina exhausted."""
        self._out_of_stamina = True
        retry = Timer(2.0)
        clean = 0
        for _ in self.loop(timeout=8):
            if self.appear(EVENT_STAMINA_BUY, offset=EVENT_OFFSET):
                clean = 0
                if retry.reached():
                    retry.reset()
                    logger.info('Out of stamina (购买朱珠糖 popup), press 取消')
                    self.device.click(EVENT_STAMINA_BUY)  # alas-lint: allow - guarded by appear(EVENT_STAMINA_BUY)
                continue
            if (
                self.appear(EVENT_SWEEP_BTN, offset=EVENT_OFFSET)
                or self.appear(EVENT_SELECT_DECK, offset=EVENT_OFFSET)
                or self.appear(EVENT_DEPART, offset=EVENT_OFFSET)
                or self.ui_page_appear(page_event_stage)
            ):
                clean += 1
                if clean >= 2:
                    return True
            else:
                clean = 0
        return False

    def ui_additional(self):
        """Close any leftover stamina/sweep/shop modal before base popup checks during `ui_goto`."""
        if self.handle_stamina_buy_popup():
            return True
        if self.appear(EVENT_SHOP_REWARD, offset=EVENT_OFFSET, interval=2):
            logger.info('Leftover event shop reward popup, press continue')
            self.device.click(EVENT_SHOP_REWARD)
            return True
        if self.appear(EVENT_SHOP_CANCEL, offset=EVENT_OFFSET, interval=2):
            logger.info('Leftover event shop buy popup, press 取消')
            self.device.click(EVENT_SHOP_CANCEL)
            return True
        if self.appear(EVENT_SWEEP_CLEAR, offset=EVENT_OFFSET, interval=2):
            logger.info('Leftover sweep CLEAR popup, press 确定')
            self.device.click(EVENT_SWEEP_CLEAR)
            return True
        if self.appear(EVENT_SWEEP_CANCEL, offset=EVENT_OFFSET, interval=2):
            logger.info('Leftover sweep count popup, press 取消')
            self.device.click(EVENT_SWEEP_CANCEL)
            return True
        return super().ui_additional()

    def event_open(self):
        """
        Enter the theme theater main page from the lobby top-left entry icon,
        skipping any first-time opening cutscene and tutorial overlay.

        Pages:
            in: page_main
            out: page_event or page_event_stage

        Returns:
            bool: True if the event page was reached.
        """
        logger.hr('Open event', level=2)
        entry_retry = Timer(2.5)
        entry_taps = 0

        for _ in self.loop(timeout=EVENT_OPEN_TIMEOUT):
            if self.ui_page_appear(page_event):
                logger.info('Page arrive: page_event')
                return True
            if self.ui_page_appear(page_event_stage):
                logger.info('Page arrive: page_event_stage')
                return True
            if self.handle_event_story_or_guide():
                continue
            if self.ui_additional():
                continue
            if self.ui_page_appear(page_main):
                if entry_taps >= EVENT_ENTRY_MAX_TAPS and entry_retry.reached():
                    logger.warning('No transition after lobby event taps; event may be inactive')
                    return False
                if entry_retry.reached():
                    entry_retry.reset()
                    entry_taps += 1
                    logger.info(f'Tap lobby event entry ({entry_taps}/{EVENT_ENTRY_MAX_TAPS})')
                    self.device.click(_area_button(EVENT_ENTRY_AREA, 'EVENT_ENTRY_TAP'))  # alas-lint: allow - guarded by ui_page_appear(page_main); entry art changes per event
                continue

        logger.warning('Timed out opening theme theater event')
        return False

    def _diff_locked(self, button):
        """Return True if a locked difficulty pill is both template- and grey-matched."""
        return (
            self.appear(button, offset=EVENT_OFFSET)
            and button.appear_on(self.device.image, threshold=DIFF_LOCKED_COLOR_THRESHOLD)
        )

    def _switch_difficulty(self, area, tap_name, label):
        """Select a difficulty pill on `page_event_stage` and wait for stage redraw."""
        logger.info(f'Switch difficulty to {label}')
        self.device.click_record_clear()
        self.device.click(_area_button(area, tap_name))  # alas-lint: allow - caller ensures page_event_stage and unlocked pill
        settle = Timer(1.0).start()
        for _ in self.loop(timeout=2):
            if settle.reached() and self.ui_page_appear(page_event_stage):
                return

    def event_battle_clear(self):
        """
        Enter 战斗 (`page_event_stage`) and clear unlocked difficulties in order:
        微微辣 -> 中辣 -> 变态辣.
        """
        logger.hr('Event battle', level=2)
        self.ui_ensure(page_event_stage)

        if self._diff_locked(EVENT_DIFF_MEDIUM_LOCKED):
            self._switch_difficulty(EVENT_DIFF_MILD_AREA, 'EVENT_DIFF_MILD_TAP', '微微辣')
            self.event_clear_current_difficulty('微微辣')
            if getattr(self, '_out_of_stamina', False):
                return
        else:
            logger.info('微微辣 already cleared (中辣 unlocked), skip')

        if self._diff_locked(EVENT_DIFF_MEDIUM_LOCKED):
            logger.info('中辣 is still locked, stop battle progression')
            return

        if self._diff_locked(EVENT_DIFF_HARD_LOCKED):
            self._switch_difficulty(EVENT_DIFF_MEDIUM_AREA, 'EVENT_DIFF_MEDIUM_TAP', '中辣')
            self.event_clear_current_difficulty('中辣')
            if getattr(self, '_out_of_stamina', False):
                return
        else:
            logger.info('中辣 already cleared (变态辣 unlocked), skip')

        if self._diff_locked(EVENT_DIFF_HARD_LOCKED):
            logger.info('变态辣 is still locked, stop battle progression')
            return

        self._switch_difficulty(EVENT_DIFF_HARD_AREA, 'EVENT_DIFF_HARD_TAP', '变态辣')
        self.event_clear_current_difficulty('变态辣')

    def _read_event_stamina(self):
        """Read current stamina from top bar (`cur/cap`), or None if unreadable."""
        ocr = Ocr(
            _area_button(EVENT_STAMINA_AREA, 'OCR_EVENT_STAMINA'),
            letter=(65, 65, 65),
            threshold=128,
            alphabet='0123456789/',
            name='OCR_EVENT_STAMINA',
        )
        raw = ocr.ocr(self.device.image)
        match = re.match(r'^(\d+)\s*/\s*(\d+)$', raw.strip())
        if not match:
            logger.warning(f'Could not parse event stamina: {raw!r}')
            return None
        return int(match.group(1))

    def _sweep_btn_lit(self):
        """Return True if 速战 is visible and lit yellow (3-star cleared)."""
        return (
            self.appear(EVENT_SWEEP_BTN, offset=EVENT_OFFSET)
            and EVENT_SWEEP_BTN.appear_on(self.device.image, threshold=SWEEP_BTN_COLOR_THRESHOLD)
        )

    def _open_focused_stage_detail(self):
        """Open stage detail on the focused stage if not already open."""
        tap_retry = Timer(2.0)
        for _ in self.loop(timeout=STAGE_OPEN_TIMEOUT):
            if self.appear(EVENT_SELECT_DECK, offset=EVENT_OFFSET) or self.appear(EVENT_SWEEP_BTN, offset=EVENT_OFFSET):
                return True
            if self.ui_page_appear(page_event_stage) and tap_retry.reached():
                tap_retry.reset()
                logger.info('Tap focused stage on 微微辣')
                self.device.click(_area_button(EVENT_STAGE_FOCUS_AREA, 'EVENT_STAGE_FOCUS_TAP'))  # alas-lint: allow - guarded by ui_page_appear(page_event_stage)
        return False

    def _open_sweep_dialog(self):
        """Press lit 速战 until the 「请设置速战次数」 dialog appears."""
        retry = Timer(2.0)
        for _ in self.loop(timeout=SWEEP_TIMEOUT):
            if self.appear(EVENT_STAMINA_BUY, offset=EVENT_OFFSET):
                self._dismiss_stamina_buy()
                return False
            if self.appear(EVENT_SWEEP_TITLE, offset=EVENT_OFFSET):
                return True
            if self._sweep_btn_lit() and retry.reached():
                retry.reset()
                logger.info('Open sweep dialog, press 速战')
                self.device.click(EVENT_SWEEP_BTN)  # alas-lint: allow - guarded by _sweep_btn_lit() on this frame
        return False

    def _sweep_confirm_once(self):
        """Set sweep count to 最大, press 速战, and return True once CLEAR appears."""
        max_tapped = False
        settle = Timer(0.5)
        confirm_retry = Timer(2.0)
        for _ in self.loop(timeout=20):
            if self.appear(EVENT_STAMINA_BUY, offset=EVENT_OFFSET):
                self._dismiss_stamina_buy()
                return False
            if self.handle_reward_popup():
                continue
            if self.appear(EVENT_SWEEP_CLEAR, offset=EVENT_OFFSET):
                return True
            if self.appear(EVENT_SWEEP_TITLE, offset=EVENT_OFFSET):
                if not max_tapped:
                    logger.info('Set sweep count to 最大')
                    self.device.click(EVENT_SWEEP_MAX)  # alas-lint: allow - guarded by appear(EVENT_SWEEP_TITLE)
                    max_tapped = True
                    settle = Timer(0.5).start()
                    continue
                if not settle.reached():
                    continue
                if self.appear(EVENT_SWEEP_CONFIRM, offset=EVENT_OFFSET) and confirm_retry.reached():
                    confirm_retry.reset()
                    logger.info('Confirm sweep, press 速战')
                    self.device.click(EVENT_SWEEP_CONFIRM)  # alas-lint: allow - guarded by appear(EVENT_SWEEP_CONFIRM)
        return False

    def _close_sweep_cancel(self):
        """Close the sweep count dialog via 取消 when a sweep cannot proceed."""
        retry = Timer(2.0)
        for _ in self.loop(timeout=10):
            if self.appear(EVENT_SWEEP_CANCEL, offset=EVENT_OFFSET):
                if retry.reached():
                    retry.reset()
                    logger.info('Cancel sweep dialog, press 取消')
                    self.device.click(EVENT_SWEEP_CANCEL)  # alas-lint: allow - guarded by appear(EVENT_SWEEP_CANCEL)
                continue
            if self.appear(EVENT_SWEEP_BTN, offset=EVENT_OFFSET) or self.ui_page_appear(page_event_stage):
                return True
        return False

    def _close_sweep_clear(self):
        """
        Dismiss the sweep CLEAR result via 确定 back to `page_event_stage`.

        `EVENT_STAGE_TITLE` remains visible behind the translucent CLEAR popup,
        so a 1-frame animation or press-down dip on `EVENT_SWEEP_CLEAR` must
        not count as closed. Exit immediately only once the covered detail
        buttons (`EVENT_SWEEP_BTN` / `EVENT_SELECT_DECK`) reappear, or after 3
        consecutive clean frames on `page_event_stage`.
        """
        retry = Timer(2.0)
        clean = 0
        for _ in self.loop(timeout=SWEEP_TIMEOUT):
            if self.handle_reward_popup():
                clean = 0
                continue
            if self.appear(EVENT_SWEEP_CLEAR, offset=EVENT_OFFSET):
                clean = 0
                if retry.reached():
                    retry.reset()
                    logger.info('Dismiss sweep CLEAR result, press 确定')
                    self.device.click(EVENT_SWEEP_CLEAR)  # alas-lint: allow - guarded by appear(EVENT_SWEEP_CLEAR)
                continue
            if self.appear(EVENT_SWEEP_BTN, offset=EVENT_OFFSET) or self.appear(EVENT_SELECT_DECK, offset=EVENT_OFFSET):
                return True
            if self.handle_stamina_buy_popup():
                clean = 0
                continue
            if self.ui_page_appear(page_event_stage):
                clean += 1
                if clean >= 3:
                    return True
            else:
                clean = 0
        return False

    def event_battle_sweep(self):
        """
        Switch back to 微微辣 and sweep the focused 3-star stage using 最大 until
        stamina drops below `SWEEP_STAMINA_COST`.

        Returns:
            bool: True if sweep checks ran cleanly.
        """
        logger.hr('Event battle sweep', level=2)
        if getattr(self, '_out_of_stamina', False):
            logger.info('Out of stamina, skip sweep')
            return False
        self.ui_ensure(page_event_stage)
        self._switch_difficulty(EVENT_DIFF_MILD_AREA, 'EVENT_DIFF_MILD_TAP', '微微辣')

        stamina = self._read_event_stamina()
        if stamina is not None and stamina < SWEEP_STAMINA_COST:
            logger.info(f'Stamina {stamina} < {SWEEP_STAMINA_COST}, skip sweep')
            return False

        if not self._open_focused_stage_detail():
            logger.warning('微微辣 focused stage detail did not open, skip sweep')
            return False

        if not self._sweep_btn_lit():
            logger.info('微微辣聚焦关卡未三星，无法速战，跳过清体力')
            return False

        for _ in range(SWEEP_MAX_ROUNDS):
            stamina_before = self._read_event_stamina()
            if stamina_before is not None and stamina_before < SWEEP_STAMINA_COST:
                logger.info(f'Stamina {stamina_before} < {SWEEP_STAMINA_COST}, sweep finished')
                break

            if self.appear(EVENT_STAMINA_BUY, offset=EVENT_OFFSET):
                self._dismiss_stamina_buy()
                break

            if self.appear(EVENT_SWEEP_TITLE, offset=EVENT_OFFSET):
                pass
            else:
                if not self._open_focused_stage_detail():
                    logger.warning('Focused stage detail did not open during sweep')
                    break
                if not self._sweep_btn_lit():
                    logger.info('速战未点亮，结束清体力')
                    break
                if not self._open_sweep_dialog():
                    if getattr(self, '_out_of_stamina', False):
                        logger.info('Out of stamina while opening sweep dialog, stop sweep')
                    else:
                        logger.warning('Sweep dialog did not open')
                    break

            if not self._sweep_confirm_once():
                if getattr(self, '_out_of_stamina', False):
                    logger.info('Out of stamina during sweep confirm, stop sweep')
                else:
                    logger.info('Sweep did not reach CLEAR (insufficient stamina or capped), close dialog')
                    self._close_sweep_cancel()
                break

            if not self._close_sweep_clear():
                logger.warning('Sweep CLEAR dialog did not close cleanly')
                break

            stamina_after = self._read_event_stamina()
            if stamina_after is not None and stamina_after < SWEEP_STAMINA_COST:
                logger.info(f'Stamina {stamina_after} < {SWEEP_STAMINA_COST}, sweep finished')
                break
            if (
                stamina_before is not None
                and stamina_after is not None
                and stamina_after == stamina_before
            ):
                logger.info(f'Stamina did not decrease ({stamina_before} -> {stamina_after}), stop sweep')
                break

        return True

    def _back_to_stage_list(self):
        """Return to `page_event_stage` if formation failed before battle started."""
        for _ in self.loop(timeout=10):
            if self.handle_stamina_buy_popup():
                continue
            if self.ui_page_appear(page_event_stage):
                return True
            if self.appear(BACK, offset=EVENT_OFFSET, interval=2):
                self.device.click(BACK)
        return False

    def _stage_uncleared_appear(self):
        """
        Detect an uncleared stage ribbon using luminance matching.

        Ribbon backing changes colour across difficulties (teal in 微微辣,
        yellow in 中辣) while the 3 unlit dark diamonds keep the same contrast,
        unlike cleared golden stars.
        """
        return EVENT_STAGE_UNCLEARED.match_luma(
            self.device.image, offset=STAGE_UNCLEARED_OFFSET, similarity=0.85
        )

    def event_clear_current_difficulty(self, name):
        """
        Select the uncleared frontier stage on the current difficulty tab,
        configure formation toggles, depart, and wait until the run finishes.

        Args:
            name (str): Difficulty label for logging.

        Returns:
            bool: True if a sortie ran and returned to `page_event_stage`.
        """
        logger.hr(f'Clear difficulty: {name}', level=3)
        found = False
        for _ in self.loop(timeout=4):
            if self._stage_uncleared_appear():
                found = True
                break
        if not found:
            logger.info(f'{name}: no uncleared stage found, skip')
            return False

        detail_opened = False
        stage_retry = Timer(2.0)
        for _ in self.loop(timeout=STAGE_OPEN_TIMEOUT):
            if self.appear(EVENT_STAGE_PERFECT_CLEAR, offset=EVENT_OFFSET):
                logger.info(f'{name}: stage already perfectly cleared, skip')
                return False
            if self.appear(EVENT_SELECT_DECK, offset=EVENT_OFFSET):
                detail_opened = True
                break
            if self._stage_uncleared_appear() and stage_retry.reached():
                stage_retry.reset()
                logger.info(f'{name}: tap uncleared stage')
                self.device.click(EVENT_STAGE_UNCLEARED)  # alas-lint: allow - guarded by _stage_uncleared_appear() match_luma on this frame
        if not detail_opened:
            logger.warning(f'{name}: stage detail panel did not open')
            return False

        form_opened = False
        for _ in self.loop(timeout=STAGE_OPEN_TIMEOUT):
            if self.appear(EVENT_STAMINA_BUY, offset=EVENT_OFFSET):
                self._dismiss_stamina_buy()
                return False
            if self.appear(EVENT_DEPART, offset=EVENT_OFFSET):
                form_opened = True
                break
            if self.appear(EVENT_SELECT_DECK, offset=EVENT_OFFSET, interval=2):
                logger.info(f'{name}: press 选择卡组')
                self.device.click(EVENT_SELECT_DECK)
        if not form_opened:
            logger.warning(f'{name}: formation page did not open')
            return False

        if not self.event_formation_depart():
            self._back_to_stage_list()
            return False

        return self.event_battle_wait()

    def event_formation_depart(self):
        """
        Ensure 快速战斗 and 开启自动 are enabled on the formation page, press
        出发, and confirm 「加成提示 -> 直接出发」 if shown.

        Returns:
            bool: True once battle loading/combat has started.
        """
        quick_retry = Timer(1.5)
        auto_retry = Timer(1.5)
        depart_retry = Timer(3.0)
        departed = False
        absent = 0

        for _ in self.loop(timeout=FORM_TIMEOUT):
            if self.appear(EVENT_STAMINA_BUY, offset=EVENT_OFFSET):
                self._dismiss_stamina_buy()
                return False

            # Foreground bonus prompt sits above the still-visible 出发 button.
            if self.appear(EVENT_BONUS_CONFIRM, offset=EVENT_OFFSET, interval=2):
                logger.info('Bonus prompt, press 直接出发')
                self.device.click(EVENT_BONUS_CONFIRM)
                departed = True
                absent = 0
                continue

            if (
                self.appear(EVENT_BATTLE_AUTO, offset=EVENT_OFFSET)
                or self.appear(EVENT_VICTORY_NEXT, offset=VICTORY_NEXT_OFFSET)
                or self.appear(EVENT_AUTO_END, offset=EVENT_OFFSET)
            ):
                logger.info('Event battle started')
                return True

            if self.appear(EVENT_DEPART, offset=EVENT_OFFSET):
                absent = 0
                if not departed:
                    if not _toggle_is_on(self.device.image, EVENT_QUICK_AREA):
                        if quick_retry.reached():
                            quick_retry.reset()
                            logger.info('Enable 快速战斗')
                            self.device.click(_area_button(EVENT_QUICK_AREA, 'EVENT_QUICK_TAP'))  # alas-lint: allow - guarded by appear(EVENT_DEPART) and toggle color check
                        continue
                    if not _toggle_is_on(self.device.image, EVENT_AUTO_AREA):
                        if auto_retry.reached():
                            auto_retry.reset()
                            logger.info('Enable 开启自动')
                            self.device.click(_area_button(EVENT_AUTO_AREA, 'EVENT_AUTO_TAP'))  # alas-lint: allow - guarded by appear(EVENT_DEPART) and toggle color check
                        continue
                if depart_retry.reached():
                    depart_retry.reset()
                    departed = True
                    logger.info('Press 出发')
                    self.device.click(EVENT_DEPART)  # alas-lint: allow - guarded by appear(EVENT_DEPART) above
                continue

            if departed:
                absent += 1
                if absent >= 3:
                    logger.info('Formation closed after depart, battle underway')
                    return True

        logger.warning('Event formation depart timed out')
        return False

    def event_battle_wait(self, timeout=BATTLE_TIMEOUT, report_interval=60):
        """
        Wait until auto-progression finishes, dismissing story-unlock overlays
        safely and pressing 退出 once the run parks at the end.

        Returns:
            bool: True when back on `page_event_stage`.
        """
        overall = Timer(timeout).start()
        report = Timer(report_interval).start()
        exit_hold = Timer(EXIT_HOLD).start()
        exit_retry = Timer(2.0)
        auto_ended = False

        for _ in self.loop():
            self.device.stuck_record_clear()

            if self.handle_stamina_buy_popup():
                exit_hold.reset()
                continue

            if self.handle_reward_popup():
                exit_hold.reset()
                continue

            if self.ui_page_appear(page_event_stage):
                logger.info('Back at 活动关卡列表, difficulty run finished')
                return True

            # Check 「自动进行结束」 / 「新的故事」 overlays BEFORE 「退出」 so we
            # dismiss them cleanly via 「请点击屏幕继续」 (never tapping center card).
            if self.appear(EVENT_AUTO_END, offset=EVENT_OFFSET, interval=2):
                logger.info('Auto battle finished popup, tap bottom continue')
                auto_ended = True
                self.device.click(EVENT_AUTO_END)
                exit_hold.reset()
                continue

            if self.appear(EVENT_NEW_STORY, offset=EVENT_OFFSET, interval=2):
                logger.info('New story unlocked popup, tap bottom continue')
                self.device.click(EVENT_NEW_STORY)
                exit_hold.reset()
                continue

            if self.handle_event_story_or_guide():
                exit_hold.reset()
                continue

            if self.appear(EVENT_BATTLE_AUTO, offset=EVENT_OFFSET):
                exit_hold.reset()
                if report.reached():
                    report.reset()
                    logger.info(f'Auto event battle running ({int(overall.current_time())}s elapsed)')
                continue

            if self.appear(EVENT_VICTORY_NEXT, offset=VICTORY_NEXT_OFFSET):
                # Victory between stages auto-advances after 3s; do not click 退出 early.
                exit_hold.reset()
                continue

            if self.appear(EVENT_BATTLE_EXIT, offset=BATTLE_EXIT_OFFSET, similarity=BATTLE_EXIT_SIMILARITY):
                if auto_ended or exit_hold.reached():
                    if exit_retry.reached():
                        exit_retry.reset()
                        logger.info('Press 退出 to return to stage list')
                        self.device.click(EVENT_BATTLE_EXIT)
                continue

            exit_hold.reset()
            if overall.reached():
                logger.warning('Event battle wait timed out')
                return False
