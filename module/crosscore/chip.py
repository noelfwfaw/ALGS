"""自动分解芯片 of 交错战线 (Cross Core).

Flow:
    page_main → click MAIN_STORAGE (warehouse icon beside mail)
    → switch to CHIP_TAB (芯片) if on item tab
    → click CHIP_DISMANTLE_BATCH (批量分解)
    → click CHIP_QUICK_SELECT (快捷选择)
    → click stars 1..N sequentially (游戏点选高星级不会自动包含低星级)
    → click CHIP_QUALITY_CONFIRM (确定)
    → click CHIP_DISMANTLE_CONFIRM (确认分解)
    → confirm CHIP_SELL_PROMPT via DIALOG_CONFIRM (if any chips matched)
    → close reward popup via handle_item_popup()
    → back_to_main()
"""

from module.base.timer import Timer
from module.crosscore.assets import (CHIP_DISMANTLE_BATCH,
                                     CHIP_DISMANTLE_CONFIRM,
                                     CHIP_QUALITY_CONFIRM, CHIP_QUALITY_TITLE,
                                     CHIP_QUICK_SELECT, CHIP_SELECTED_ZERO,
                                     CHIP_SELL_PROMPT, CHIP_STAR_1, CHIP_STAR_2,
                                     CHIP_STAR_3, CHIP_STAR_4, CHIP_STAR_5,
                                     CHIP_TAB, DIALOG_CONFIRM, MAIN_STORAGE)
from module.crosscore.crosscore_ui import CrosscoreUI
from module.crosscore.page import page_main
from module.crosscore.utils import gold_pixels
from module.logger import logger

RARITY_MAP = {
    '2星': 2,
    '3星': 3,
    '4星': 4,
    '5星': 5,
}

STAR_BUTTONS = {
    1: CHIP_STAR_1,
    2: CHIP_STAR_2,
    3: CHIP_STAR_3,
    4: CHIP_STAR_4,
    5: CHIP_STAR_5,
}

STAR_AREAS = {
    1: (665, 521, 735, 588),
    2: (748, 521, 818, 588),
    3: (831, 521, 901, 588),
    4: (914, 521, 984, 588),
    5: (997, 521, 1067, 588),
}

# Unselected star box has 0 gold pixels; selected box has 39..80 gold pixels.
STAR_GOLD_PIXELS = 20

# Top-right 芯片 tab: 0 gold pixels when 物品 is active, 99 when 芯片 is active.
CHIP_TAB_GOLD_AREA = (1130, 28, 1255, 72)
CHIP_TAB_GOLD_PIXELS = 40


class CrosscoreChip(CrosscoreUI):
    """
    Dismantle chips up to configured rarity threshold and return to lobby.

    Pages:
        in: page_main
        out: page_main
    """

    def run(self):
        """
        Enter warehouse -> chip tab -> batch dismantle, dismantle 1..N star chips,
        and return to main page.

        Pages:
            in: page_main
            out: page_main
        """
        logger.hr('交错芯片分解', level=1)
        self.ui_ensure(page_main)

        rarity = str(self.config.CrosscoreChip_Rarity)
        max_star = RARITY_MAP.get(rarity)
        if max_star is None:
            logger.warning(f'Unknown chip rarity <{rarity}>, fall back to 3星')
            max_star = 3
        logger.info(f'Chip dismantle target rarity: 1星..{max_star}星')

        if not self._enter_chip_dismantle() \
                or not self._quick_select_stars(max_star) \
                or not self._confirm_dismantle():
            logger.warning('Chip dismantle did not finish cleanly, retry in 15 minutes')
            self.back_to_main()
            self.config.task_delay(minute=15)
            return

        self.back_to_main()
        self.config.task_delay(server_update=True)

    def _enter_chip_dismantle(self):
        """
        Navigate from lobby to warehouse chip batch dismantle screen.

        Returns:
            bool: True if batch dismantle mode (`CHIP_QUICK_SELECT`) is open.
        """
        logger.hr('进入芯片批量分解', level=2)
        for _ in self.loop(timeout=45):
            if self.handle_item_popup():
                continue
            if self.handle_lobby_popup():
                continue
            if self.appear(CHIP_QUICK_SELECT, offset=(20, 20)):
                logger.info('Chip batch dismantle screen ready')
                return True
            if self.appear(CHIP_DISMANTLE_BATCH, offset=(20, 20), interval=1.5):
                logger.info('Enter batch dismantle')
                self.device.click(CHIP_DISMANTLE_BATCH)
                continue
            if self.appear(CHIP_TAB, offset=(20, 20)):
                if gold_pixels(self.device.image, CHIP_TAB_GOLD_AREA) < CHIP_TAB_GOLD_PIXELS \
                        and self.appear(CHIP_TAB, offset=(20, 20), interval=1.5):
                    logger.info('Switch to chip tab')
                    self.device.click(CHIP_TAB)
                continue
            if self.appear(MAIN_STORAGE, offset=(20, 20), interval=2.5):
                logger.info('Open warehouse')
                self.device.click(MAIN_STORAGE)

        logger.warning('Timeout entering chip batch dismantle screen')
        return False

    def _quick_select_stars(self, max_star: int):
        """
        Open quick select popup, ensure stars 1..max_star are selected, and confirm.

        Args:
            max_star (int): Highest star rarity (2..5) to select from 1星 upward.

        Returns:
            bool: True if quick select confirmed and returned to dismantle screen.
        """
        logger.hr(f'快捷选择 1星~{max_star}星', level=2)
        for _ in self.loop(timeout=45):
            if self.appear(CHIP_QUALITY_TITLE, offset=(20, 20)):
                pending = self._next_star_to_toggle(max_star)
                if pending is not None:
                    star, select = pending
                    btn = STAR_BUTTONS[star]
                    sim = 0.80 if select else 0.75
                    if self.appear(btn, offset=(20, 20), similarity=sim, interval=0.8):
                        action = 'Select' if select else 'Unselect'
                        logger.info(f'{action} chip rarity {star}星')
                        self.device.click(btn)
                    continue

                if self.appear(CHIP_QUALITY_CONFIRM, offset=(20, 20), interval=1.5):
                    logger.info('Confirm quick select stars')
                    self.device.click(CHIP_QUALITY_CONFIRM)
                    if self.wait_until_disappear(CHIP_QUALITY_TITLE, offset=(20, 20), timeout=5, settle=1):
                        return True
                continue

            if self.appear(CHIP_QUICK_SELECT, offset=(20, 20), interval=1.5):
                logger.info('Open quick select popup')
                self.device.click(CHIP_QUICK_SELECT)

        logger.warning('Timeout selecting chip stars')
        return False

    def _next_star_to_toggle(self, max_star: int):
        """
        Return `(star, should_select)` for the first star whose toggle state
        differs from `1..max_star`, or None if all five match.
        """
        for star in range(1, 6):
            should_select = star <= max_star
            is_selected = gold_pixels(self.device.image, STAR_AREAS[star]) >= STAR_GOLD_PIXELS
            if is_selected != should_select:
                return star, should_select
        return None

    def _confirm_dismantle(self):
        """
        Press 确认分解, handle confirmation/reward popups, or exit if no chips matched.

        Returns:
            bool: True when dismantle finished or no dismantleable chips exist.
        """
        logger.hr('确认分解芯片', level=2)
        confirm_clicks = 0
        no_popup_timer = None
        reward_wait = None
        claimed = False

        for _ in self.loop(timeout=45):
            if self.handle_item_popup():
                claimed = True
                continue

            if self.appear(CHIP_SELL_PROMPT, offset=(20, 20)):
                if self.appear(DIALOG_CONFIRM, offset=(20, 20), interval=1.5):
                    logger.info('Confirm sell chips dialog')
                    self.device.click(DIALOG_CONFIRM)
                    reward_wait = Timer(8).start()
                continue

            if claimed:
                logger.info('Chip dismantle rewards claimed')
                return True

            if reward_wait is not None:
                if reward_wait.reached():
                    logger.info('Sell dialog closed without item popup')
                    return True
                continue

            if no_popup_timer is not None and no_popup_timer.reached():
                if confirm_clicks >= 1 and self.appear(CHIP_SELECTED_ZERO, offset=(20, 20), similarity=0.92):
                    logger.info('No chips selected to dismantle')
                    return True
                if confirm_clicks >= 2:
                    logger.info('No dismantle confirmation dialog, no chips to dismantle')
                    return True

            if confirm_clicks < 2 and self.appear(CHIP_DISMANTLE_CONFIRM, offset=(20, 20), interval=1.5):
                logger.info('Click confirm dismantle')
                self.device.click(CHIP_DISMANTLE_CONFIRM)
                confirm_clicks += 1
                no_popup_timer = Timer(1.5 if confirm_clicks == 1 else 2.0).start()

        logger.warning('Timeout confirming chip dismantle')
        return False
