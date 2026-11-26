"""Normal-tab battle carousel navigation for Lost Sword (失落之剑)."""

import cv2
import numpy as np

from module.base.timer import Timer
from module.base.utils import get_color
from module.exception import GameStuckError
from module.logger import logger
from module.lostsword.assets import BATTLE_TITLE
from module.lostsword.page import (BATTLE_TAB_NORMAL,
                                   BATTLE_TAB_SELECTED_MEAN, page_battle)

BATTLE_CARDS_BAND = (0, 140, 1280, 660)
# Unclipped cards sit cleanly inside this horizontal window; clipped edge cards
# poke outside it and should only be tapped as a last-resort fallback.
BATTLE_CARD_SAFE_X = (80, 1200)
BATTLE_CARD_SIMILARITY = 0.85


class BattleNav:
    """
    Shared helpers for switching to the 「普通」 battle tab and locating its
    scrollable mode cards dynamically across carousel layout updates.
    """

    def battle_goto_normal(self, timeout=8):
        """
        Switch the battle page back to its 「普通」 tab and rewind its carousel.

        Pages:
            in: page_battle
            out: page_battle

        Args:
            timeout (int, float): Seconds.

        Returns:
            bool: If the 普通 tab is the open one.
        """
        retry = Timer(1.5)
        for _ in self.loop(skip_first=False, timeout=timeout):
            color = get_color(self.device.image, BATTLE_TAB_NORMAL.area)
            if sum(color) / 3 > BATTLE_TAB_SELECTED_MEAN:
                self.battle_scroll(forward=False)
                return True
            if retry.reached():
                retry.reset()
                if self.appear(BATTLE_TITLE, offset=30):
                    self.device.click(BATTLE_TAB_NORMAL)
        logger.warning('Cannot switch the battle page back to 普通')
        return False

    def _battle_drag_once(self, forward):
        """
        Drag the battle card carousel once and report whether it moved.

        Args:
            forward (bool): True to drag towards later cards, False to earlier.

        Returns:
            bool: True if the card band changed after the drag.

        Raises:
            GameStuckError: If the card band never stops animating.
        """
        if forward:
            p1, p2 = (1000, 400), (300, 400)
        else:
            p1, p2 = (300, 400), (1000, 400)
        self.device.screenshot()
        before = self.image_crop(BATTLE_CARDS_BAND, copy=True)
        # The carousel can ignore a minitouch drag. ADB sends the complete gesture.
        logger.info('Swipe %s -> %s @ BATTLE_CARDS', p1, p2)
        self.device.swipe_adb(p1, p2, duration=0.625)
        if not self.wait_until_still(BATTLE_CARDS_BAND, timeout=3, skip_first_screenshot=False):
            self.device.click_record_clear()
            raise GameStuckError('Battle card list did not settle after drag')
        after = self.image_crop(BATTLE_CARDS_BAND, copy=True)
        self.device.click_record_clear()
        return float(np.mean(cv2.absdiff(after, before))) >= 1.0

    def battle_scroll(self, forward, swipes=5):
        """
        Scroll the card list of the battle page until it clamps at an end.

        Pages:
            in: page_battle
            out: page_battle

        Args:
            forward (bool): True to drag towards the end, False to the start.
            swipes (int): How many drags to make at most.

        Raises:
            GameStuckError: If the list never clamps.
        """
        for _ in range(swipes):
            if not self._battle_drag_once(forward):
                return
        raise GameStuckError(f'Card list did not clamp after {swipes} drag(s)')

    def battle_find_card(self, card, similarity=BATTLE_CARD_SIMILARITY, allow_edge=True):
        """
        Locate a card anywhere along the normal battle card row.

        Args:
            card (Button): Card title template button (`button == area`).
            similarity (float): Template match threshold.
            allow_edge (bool): Whether clipped edge cards outside
                `BATTLE_CARD_SAFE_X` are accepted.

        Returns:
            tuple[int, int] | None: Center point (x, y) if matched, else None.
        """
        x1, _, x2, _ = card.area
        row_offset = (-x1, -20, 1280 - x2, 20)
        card.clear_offset()
        if self.appear(card, offset=row_offset, similarity=similarity):
            bx1, by1, bx2, by2 = card.button
            card.clear_offset()
            if allow_edge or (bx1 >= BATTLE_CARD_SAFE_X[0] and bx2 <= BATTLE_CARD_SAFE_X[1]):
                return ((bx1 + bx2) // 2, (by1 + by2) // 2)
            return None
        card.clear_offset()
        return None

    def _battle_scan_direction(self, card, forward, swipes=5):
        """Scan one carousel direction until an unclipped card appears or it clamps twice."""
        still = 0
        for _ in range(swipes):
            moved = self._battle_drag_once(forward)
            point = self.battle_find_card(card, allow_edge=False)
            if point is not None:
                return point
            # Require two stationary drags before declaring a clamp so a single
            # eaten drag right after switching tabs does not abort the scan.
            still = 0 if moved else still + 1
            if still >= 2:
                break
        return self.battle_find_card(card, allow_edge=True)

    def battle_locate_card(self, card, swipes=5):
        """
        Locate a card across the scrollable battle carousel.

        Args:
            card (Button): Card template button.
            swipes (int): Maximum drags per scan direction.

        Returns:
            tuple[int, int] | None: Tap point (x, y) if found, else None.
        """
        point = self.battle_find_card(card, allow_edge=False)
        if point is not None:
            return point
        for forward in (True, False):
            point = self._battle_scan_direction(card, forward, swipes=swipes)
            if point is not None:
                return point
        return self.battle_find_card(card, allow_edge=True)

    def battle_goto_card(self, card, destination, already_on=(), close_to_dest=(),
                         timeout=12, label=None):
        """
        Navigate from anywhere to a battle mode page via its carousel card.

        Pages:
            in: any
            out: destination

        Args:
            card (Button): Mode card template on `page_battle`.
            destination (Page): Target page to open.
            already_on (tuple[Page, ...]): Overlay pages that already count as arrived.
            close_to_dest (tuple[Page, ...]): Subpages routed directly via `ui_goto()`.
            timeout (int, float): Seconds to wait for `destination` after locating the card.
            label (str | None): Human-readable name for logs and errors.

        Raises:
            GameStuckError: If navigation, card lookup, or opening fails.
        """
        name = label or card.name
        current = self.ui_get_current_page(skip_first_screenshot=False)
        if current in (destination,) + tuple(already_on):
            self.ui_current = current
            return
        if current in tuple(close_to_dest):
            self.ui_goto(destination)
            return
        if current != page_battle:
            self.ui_goto(page_battle)
        if not self.battle_goto_normal():
            raise GameStuckError(f'{name}: cannot open the normal battle tab')

        point = self.battle_locate_card(card)
        if point is None:
            raise GameStuckError(f'{name}: card {card.name} not found on battle tab')

        retry = Timer(2)
        for _ in self.loop(timeout=timeout):
            if self.ui_page_appear(destination):
                self.ui_current = destination
                return
            if retry.reached() and self.ui_page_appear(page_battle):
                found = self.battle_find_card(card)
                if found is not None:
                    logger.info('%s card found at %s', name, found)
                    self.tap_point(*found)
                    retry.reset()
        raise GameStuckError(f'{name}: {destination.name} did not open')
