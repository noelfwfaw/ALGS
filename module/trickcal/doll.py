"""Doll Buster (娃娃怪破坏者) automation for Trickcal.

Entry path: `page_main -> page_adventure -> page_doll -> page_doll_stage`.
Daily limit: 4 free purple tickets/day, 10 red-candy stamina + 1 ticket per sweep.
Cannot select stages manually; defaults directly to the highest sweepable stage.
"""

import re

from module.base.timer import Timer
from module.base.utils import crop
from module.logger import logger
from module.ocr.ocr import Ocr
from module.trickcal.assets import (
    DOLL_SWEEP_BTN,
    DOLL_TICKET_CANCEL,
    DOLL_TICKET_EMPTY,
    DUNGEON_CLONE_EMPTY,
    DUNGEON_SWEEP_CONFIRM,
    DUNGEON_SWEEP_TITLE,
    EVENT_STAMINA_BUY,
    EVENT_SWEEP_CANCEL,
    EVENT_SWEEP_CLEAR,
    EVENT_SWEEP_CONFIRM,
    EVENT_SWEEP_MAX,
    EVENT_SWEEP_TITLE,
    SHOP_BUY_CANCEL,
)
from module.trickcal.dungeon_stage import _ocr_bw, _otsu_bw, tap_box
from module.trickcal.page import page_doll, page_doll_stage, page_main
from module.trickcal.trickcal_ui import TrickcalUI

DOLL_RACE_AREAS = {
    'dragon': (335, 140, 470, 225),
    'elf': (575, 145, 710, 230),
    'ghost': (810, 150, 945, 230),
    'fairy': (585, 305, 725, 385),
    'witch': (825, 300, 965, 380),
    'elemental': (315, 435, 460, 525),
    'mystic': (565, 455, 705, 540),
    'beast': (810, 455, 955, 540),
}

DOLL_HUB_TICKET_AREA = (562, 24, 612, 52)
DOLL_STAMINA_AREA = (708, 24, 800, 52)
DOLL_STAGE_TICKET_AREA = (1134, 562, 1196, 588)
DOLL_STAGE_TICKET_LEFT_AREA = (1134, 560, 1154, 588)

DOLL_STAMINA_COST = 10
DOLL_SWEEP_MAX_ROUNDS = 5
DOLL_OFFSET = (20, 20)
DOLL_SWEEP_OFFSET = (25, 35)
SWEEP_COLOR_THRESHOLD = 40

_DOLL_OCR_CACHE = {}


def _get_doll_stamina_ocr():
    if 'stamina' not in _DOLL_OCR_CACHE:
        _DOLL_OCR_CACHE['stamina'] = Ocr(
            tap_box(DOLL_STAMINA_AREA, 'OCR_DOLL_STAMINA'),
            lang='azur_lane',
            letter=(65, 65, 65),
            threshold=128,
            alphabet='0123456789/',
            name='OCR_DOLL_STAMINA',
        )
    return _DOLL_OCR_CACHE['stamina']


def read_doll_tickets(image, on_hub=True):
    """Read remaining Doll Buster daily tickets (`0..4`) on hub or stage badge."""
    if on_hub:
        patch = crop(image, DOLL_HUB_TICKET_AREA)
        txt = _ocr_bw(_otsu_bw(patch, invert=False), alphabet='0123456789/')
        m = re.search(r'(\d+)\s*/\s*(\d+)', txt)
        if m:
            return int(m.group(1))
        logger.warning(f'Could not parse Doll Buster hub tickets: {txt!r}')
        return None

    patch = crop(image, DOLL_STAGE_TICKET_AREA)
    txt = _ocr_bw(_otsu_bw(patch, invert=False), alphabet=None)
    m = re.search(r'(\d+)\s*[→\->=]+\s*(\d+)', txt)
    if m:
        return int(m.group(1))

    left_patch = crop(image, DOLL_STAGE_TICKET_LEFT_AREA)
    left_txt = _ocr_bw(_otsu_bw(left_patch, invert=False), alphabet='0123456789')
    m = re.search(r'\d+', left_txt)
    if m:
        return int(m.group(0))
    return None


def read_doll_stamina(image):
    """Read current red-candy stamina (`cur/cap`) from top bar on Doll Buster screens."""
    raw = _get_doll_stamina_ocr().ocr(image)
    m = re.search(r'(\d+)\s*/\s*(\d+)', raw)
    if not m:
        logger.warning(f'Could not parse Doll Buster stamina: {raw!r}')
        return None
    return int(m.group(1))


def doll_sweep_lit(image):
    """Return True when the bright-yellow 速战 button on `page_doll_stage` is enabled."""
    return DOLL_SWEEP_BTN.appear_on(image, threshold=SWEEP_COLOR_THRESHOLD)


class TrickcalDoll(TrickcalUI):
    """
    Sweep 娃娃怪破坏者 (4 daily tickets, 10 red candy + 1 ticket per run).

    Pages:
        in: page_main
        out: page_main
    """

    def ui_additional(self):
        """Dismiss leftover stamina/ticket/sweep/shop overlays during `ui_goto`."""
        if self.appear(DOLL_TICKET_EMPTY, offset=DOLL_OFFSET) and self.appear(
            DOLL_TICKET_CANCEL, offset=DOLL_OFFSET, interval=2
        ):
            logger.info('Leftover ticket empty popup (入场券不足), press 取消')
            self.device.click(DOLL_TICKET_CANCEL)
            return True
        if self.appear(EVENT_STAMINA_BUY, offset=DOLL_OFFSET, interval=2):
            logger.info('Leftover stamina buy popup, press 取消')
            self.device.click(EVENT_STAMINA_BUY)
            return True
        if self.appear(EVENT_SWEEP_CLEAR, offset=DOLL_OFFSET, interval=2):
            logger.info('Leftover sweep CLEAR popup, press 确定')
            self.device.click(EVENT_SWEEP_CLEAR)
            return True
        if self.appear(EVENT_SWEEP_CANCEL, offset=DOLL_OFFSET, interval=2):
            logger.info('Leftover sweep count popup, press 取消')
            self.device.click(EVENT_SWEEP_CANCEL)
            return True
        if self.appear(SHOP_BUY_CANCEL, offset=DOLL_OFFSET, interval=2):
            logger.info('Leftover shop buy popup, press 取消')
            self.device.click(SHOP_BUY_CANCEL)
            return True
        return super().ui_additional()

    def run(self):
        """Enter the selected race in 娃娃怪破坏者 and sweep remaining tickets."""
        logger.hr('Trickcal Doll', level=1)
        race = self.config.TrickcalDoll_Race
        if race not in DOLL_RACE_AREAS:
            logger.warning(f'Unknown Doll Buster race {race!r}, skip')
            self.config.task_delay(server_update=True)
            return

        self.ui_ensure(page_main)
        self.ui_ensure(page_doll)

        tickets = read_doll_tickets(self.device.image, on_hub=True)
        if tickets == 0:
            logger.info('Doll Buster daily tickets 0/4, skip')
            self.ui_goto_main()
            self.config.task_delay(server_update=True)
            return

        stamina = read_doll_stamina(self.device.image)
        if stamina is not None and stamina < DOLL_STAMINA_COST:
            logger.info(f'Red-candy stamina {stamina} < {DOLL_STAMINA_COST}, skip Doll Buster')
            self.ui_goto_main()
            self.config.task_delay(server_update=True)
            return

        if not self._enter_race(race):
            logger.warning(f'Could not enter Doll Buster race {race}, skip')
            self.ui_goto_main()
            self.config.task_delay(server_update=True)
            return

        self._sweep_doll()
        self.ui_goto_main()
        self.config.task_delay(server_update=True)

    def _enter_race(self, race):
        """Tap the configured race TV on `page_doll` until `page_doll_stage` opens."""
        tv_btn = tap_box(DOLL_RACE_AREAS[race], f'DOLL_RACE_{race.upper()}')
        retry = Timer(2.0)
        for _ in self.loop(timeout=10):
            if self.ui_page_appear(page_doll_stage):
                return True
            if self.ui_page_appear(page_doll) and retry.reached():
                retry.reset()
                logger.info(f'Enter Doll Buster race {race}')
                self.device.click(tv_btn)  # alas-lint: allow - guarded by ui_page_appear(page_doll)
        return self.ui_page_appear(page_doll_stage)

    def _dismiss_ticket_empty(self):
        """Close the 「入场券不足」 modal via 取消 without navigating to shop."""
        retry = Timer(2.0)
        clean = 0
        for _ in self.loop(timeout=8):
            if self.appear(DOLL_TICKET_EMPTY, offset=DOLL_OFFSET):
                clean = 0
                if self.appear(DOLL_TICKET_CANCEL, offset=DOLL_OFFSET) and retry.reached():
                    retry.reset()
                    logger.info('Doll Buster tickets exhausted (入场券不足), press 取消')
                    self.device.click(DOLL_TICKET_CANCEL)
                continue
            clean += 1
            if clean >= 2:
                return True
        return False

    def _dismiss_stamina_buy(self):
        """Close the stamina purchase modal via 取消 without buying."""
        retry = Timer(2.0)
        clean = 0
        for _ in self.loop(timeout=8):
            if self.appear(EVENT_STAMINA_BUY, offset=DOLL_OFFSET):
                clean = 0
                if retry.reached():
                    retry.reset()
                    logger.info('Out of red-candy stamina (buy popup), press 取消')
                    self.device.click(EVENT_STAMINA_BUY)
                continue
            clean += 1
            if clean >= 2:
                return True
        return False

    def _open_sweep_dialog(self):
        """Press 速战 until sweep count modal opens or tickets/stamina report exhausted."""
        retry = Timer(2.0)
        for _ in self.loop(timeout=15):
            if self.appear(DOLL_TICKET_EMPTY, offset=DOLL_OFFSET):
                self._dismiss_ticket_empty()
                return False
            if self.appear(DUNGEON_CLONE_EMPTY, offset=DOLL_OFFSET):
                logger.info('Doll Buster daily entries exhausted (每日入场次数已用完), stop')
                return False
            if self.appear(EVENT_STAMINA_BUY, offset=DOLL_OFFSET):
                self._dismiss_stamina_buy()
                return False
            if self.appear(DUNGEON_SWEEP_TITLE, offset=DOLL_SWEEP_OFFSET) or self.appear(
                EVENT_SWEEP_TITLE, offset=DOLL_SWEEP_OFFSET
            ):
                return True
            if retry.reached():
                retry.reset()
                logger.info('Open Doll Buster sweep dialog, press 速战')
                self.device.click(DOLL_SWEEP_BTN)  # alas-lint: allow - guarded by doll_sweep_lit() before call
        return False

    def _sweep_confirm_once(self):
        """Set sweep count to 最大, press 速战, and wait for CLEAR or reward popup."""
        max_tapped = False
        settle = Timer(0.5)
        confirm_retry = Timer(2.0)
        for _ in self.loop(timeout=20):
            if self.appear(DOLL_TICKET_EMPTY, offset=DOLL_OFFSET):
                self._dismiss_ticket_empty()
                return False
            if self.appear(EVENT_STAMINA_BUY, offset=DOLL_OFFSET):
                self._dismiss_stamina_buy()
                return False
            if self.handle_reward_popup():
                continue
            if self.appear(EVENT_SWEEP_CLEAR, offset=DOLL_OFFSET):
                return True
            if self.appear(DUNGEON_SWEEP_TITLE, offset=DOLL_SWEEP_OFFSET) or self.appear(
                EVENT_SWEEP_TITLE, offset=DOLL_SWEEP_OFFSET
            ):
                if not max_tapped:
                    logger.info('Set Doll Buster sweep count to 最大')
                    self.device.click(EVENT_SWEEP_MAX)  # alas-lint: allow - guarded by sweep dialog title
                    max_tapped = True
                    settle = Timer(0.5).start()
                    continue
                if not settle.reached():
                    continue
                confirm_btn = None
                if self.appear(DUNGEON_SWEEP_CONFIRM, offset=DOLL_OFFSET):
                    confirm_btn = DUNGEON_SWEEP_CONFIRM
                elif self.appear(EVENT_SWEEP_CONFIRM, offset=DOLL_OFFSET):
                    confirm_btn = EVENT_SWEEP_CONFIRM
                if confirm_btn is not None and confirm_retry.reached():
                    confirm_retry.reset()
                    logger.info('Confirm Doll Buster sweep, press 速战')
                    self.device.click(confirm_btn)
        return False

    def _close_sweep_cancel(self):
        """Cancel out of sweep count dialog back to `page_doll_stage`."""
        retry = Timer(2.0)
        for _ in self.loop(timeout=8):
            if self.appear(EVENT_SWEEP_CANCEL, offset=DOLL_OFFSET):
                if retry.reached():
                    retry.reset()
                    logger.info('Cancel Doll Buster sweep dialog')
                    self.device.click(EVENT_SWEEP_CANCEL)
                continue
            if self.ui_page_appear(page_doll_stage):
                return True
        return False

    def _close_sweep_clear(self):
        """Dismiss CLEAR popup and settle back on `page_doll_stage`."""
        retry = Timer(2.0)
        clean = 0
        for _ in self.loop(timeout=12):
            if self.handle_reward_popup():
                clean = 0
                continue
            if self.appear(EVENT_SWEEP_CLEAR, offset=DOLL_OFFSET):
                clean = 0
                if retry.reached():
                    retry.reset()
                    logger.info('Dismiss Doll Buster sweep CLEAR result, press 确定')
                    self.device.click(EVENT_SWEEP_CLEAR)
                continue
            if self.ui_page_appear(page_doll_stage):
                clean += 1
                if clean >= 2:
                    return True
            else:
                clean = 0
        return False

    def _sweep_doll(self):
        """Sweep the default stage until tickets or red-candy stamina run out."""
        for _ in range(DOLL_SWEEP_MAX_ROUNDS):
            stamina = read_doll_stamina(self.device.image)
            if stamina is not None and stamina < DOLL_STAMINA_COST:
                logger.info(f'Red-candy stamina {stamina} < {DOLL_STAMINA_COST}, stop Doll Buster')
                return True

            tickets = read_doll_tickets(self.device.image, on_hub=False)
            if tickets == 0:
                logger.info('Doll Buster tickets 0 -> 0, stop')
                return True

            if not doll_sweep_lit(self.device.image):
                logger.warning('Doll Buster 速战 is disabled (no stage cleared yet or 0 tickets), stop')
                return False

            if not self._open_sweep_dialog():
                return True
            if not self._sweep_confirm_once():
                self._close_sweep_cancel()
                return True
            if not self._close_sweep_clear():
                return False
        return True
