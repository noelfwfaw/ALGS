"""Island story (海岛物语 & 垃圾压缩机前置清理) for 雷索纳斯."""

import re

from module.base.button import Button
from module.base.timer import Timer
from module.exception import GameStuckError
from module.logger import logger
from module.ocr.ocr import Ocr
from module.resonance import assets
from module.resonance.island_friends import run_island_friends
from module.resonance.island_volleyball import run_beach_volleyball
from module.resonance.page import (
    page_resonance_garbage, page_resonance_island_beach, page_resonance_island_hub, page_resonance_island_promo,
    page_resonance_island_revenue, page_resonance_terminal,
)
from module.resonance.resonance_ui import ResonanceUI


OFFSET = (5, 5)
PROMO_TOURIST_OCR = Ocr((1185, 20, 1268, 54), threshold=128, alphabet='0123456789/', name='Island tourists')
PROMO_FLYER_OCR = Ocr((980, 18, 1085, 58), threshold=128, alphabet='0123456789', name='Island flyers')
PROMO_AD_OCR = Ocr((820, 18, 930, 58), threshold=128, alphabet='0123456789', name='Island ad tickets')
BEACH_INCOME_OCR = Ocr((125, 650, 248, 686), threshold=128, alphabet='0123456789', name='Island income')

PROMO_CARD_BOXES = {
    'promotion': (160, 440, 340, 580),
    'theme': (550, 440, 730, 580),
    'celebrity': (940, 440, 1120, 580),
}
PROMO_METHOD_TABS = {
    'flyer': (520, 232, 650, 262),
    'ad_ticket': (705, 232, 845, 262),
}
SIDEBAR_ROI = (10, 80, 260, 715)
ISLAND_CARD_ROI = (15, 240, 220, 700)


def _box_button(box, name):
    return Button(area=box, color=(), button=box, name=name)


def is_promo_method_selected(image, method):
    """Return True when the requested promotion tab (white selected pill) is active."""
    x1, y1, x2, y2 = PROMO_METHOD_TABS[method]
    return float(image[y1:y2, x1:x2].mean()) > 215.0


def is_promo_park_full(image):
    """Return True when promotion top-right tourist capacity `cur/max` is full."""
    text = str(PROMO_TOURIST_OCR.ocr(image))
    match = re.search(r'(\d+)\s*/\s*(\d+)', text)
    if not match:
        return False
    cur, cap = int(match.group(1)), int(match.group(2))
    return cap > 0 and cur >= cap


def read_promo_stock(image, method):
    """Return flyer or ad-ticket stock from promotion header, or None."""
    ocr_obj = PROMO_AD_OCR if method == 'ad_ticket' else PROMO_FLYER_OCR
    digits = re.findall(r'\d+', str(ocr_obj.ocr(image)))
    return int(digits[0]) if digits else None


def read_beach_income(image):
    """Return accumulative 今日收益 gold amount on own island beach, or None."""
    digits = re.findall(r'\d+', str(BEACH_INCOME_OCR.ocr(image)))
    return int(digits[0]) if digits else None


def find_sidebar_template(image, template, roi):
    """Match a template inside `roi` and return a full-screen clickable Button, or None."""
    rx1, ry1, rx2, ry2 = roi
    score, button = template.match_result(image[ry1:ry2, rx1:rx2])
    if score <= 0.85:
        return None
    return button.move((rx1, ry1))


class ResonanceIsland(ResonanceUI):
    """Train garbage compactor pre-clean + 海岛物语 daily routine."""

    def clean_train_garbage(self):
        """Clear compressed garbage blocks in train maintenance before visiting friends.

        Pages:
            in: any known page
            out: page_resonance_garbage
        """
        self.ui_ensure(page_resonance_garbage, skip_first_screenshot=False)
        cleared = False
        empty_timer = Timer(1.2, count=2).start()
        for _ in self.loop(timeout=25):
            if (
                self.appear(assets.GARBAGE_CONFIRM_MODAL, offset=(120, 10))
                or self.appear(assets.GARBAGE_CONFIRM_OK, offset=OFFSET)
            ):
                if self.appear_then_click(assets.GARBAGE_CONFIRM_OK, offset=OFFSET, interval=2):
                    cleared = True
                    empty_timer.reset()
                continue
            if self.appear_then_click(assets.GARBAGE_CLEAR_ALL, offset=OFFSET, interval=2):
                empty_timer.reset()
                continue
            if self.appear(assets.GARBAGE_CHECK, offset=OFFSET):
                if empty_timer.reached():
                    logger.info('列车垃圾压缩机清理完成' if cleared else '列车垃圾暂存区已为空')
                    return
                continue
            empty_timer.reset()
        raise GameStuckError('Train garbage compactor cleanup timed out')

    def goto_island_hub(self):
        """Navigate from terminal into 海岛物语 hub.

        Pages:
            in: any known page
            out: page_resonance_island_hub
        """
        if self.appear(assets.ISLAND_HUB_CHECK, offset=OFFSET):
            return
        self.ui_ensure(page_resonance_terminal, skip_first_screenshot=False)
        click_timer = Timer(1.5)
        swipe_timer = Timer(1.5).start()
        for _ in self.loop(timeout=30):
            if self.appear(assets.ISLAND_HUB_CHECK, offset=OFFSET):
                return
            if self.appear(assets.OP_BACK, offset=OFFSET):
                card = find_sidebar_template(self.device.image, assets.TEMPLATE_ISLAND_ENTRY_TAB, ISLAND_CARD_ROI)
                if card is not None:
                    if click_timer.reached():
                        self.device.click(card)
                        click_timer.reset()
                    continue
                biz = find_sidebar_template(self.device.image, assets.TEMPLATE_TERMINAL_BIZ_TAB, SIDEBAR_ROI)
                if biz is not None:
                    if click_timer.reached():
                        self.device.click(biz)
                        click_timer.reset()
                    continue
                if swipe_timer.reached():
                    self.device.swipe((120, 620), (120, 220), duration=0.4, name='TERMINAL_SIDEBAR_UP')
                    swipe_timer.reset()
        raise GameStuckError('Did not enter 海岛物语 hub')

    def run_promotion(self):
        """Execute 海岛宣传 with configured promotion card, method tab, and MAX quantity.

        Pages:
            in: page_resonance_island_hub
            out: page_resonance_island_hub
        """
        promo_type = getattr(self.config, 'ResonanceIsland_PromotionType', 'promotion')
        method = getattr(self.config, 'ResonanceIsland_PromotionMethod', 'flyer')
        if promo_type == 'none':
            return
        self.ui_ensure(page_resonance_island_promo, skip_first_screenshot=False)
        if is_promo_park_full(self.device.image):
            logger.info('海岛游客已满，跳过海岛宣传')
            self.ui_ensure(page_resonance_island_hub, skip_first_screenshot=False)
            return
        stock = read_promo_stock(self.device.image, method)
        if stock is not None and stock <= 0:
            logger.info(f'海岛宣传道具 ({method}) 为 0，跳过海岛宣传')
            self.ui_ensure(page_resonance_island_hub, skip_first_screenshot=False)
            return

        submitted = False
        max_clicked = False
        result_clicks = 0
        card_timer = Timer(1.5).start()
        for _ in self.loop(timeout=30):
            if self.handle_reward_popup():
                continue
            if self.appear(assets.ISLAND_PROMO_RESULT, offset=OFFSET):
                submitted = True
                if result_clicks < 2:
                    if self.appear_then_click(assets.ISLAND_PROMO_RESULT, offset=OFFSET, interval=1):
                        result_clicks += 1
                else:
                    self.appear_then_click(assets.ISLAND_PROMO_GO_REVENUE, offset=OFFSET, interval=2)
                continue
            if submitted and (
                self.appear(assets.ISLAND_PROMO_CHECK, offset=OFFSET)
                or self.appear(assets.ISLAND_BEACH_CHECK, offset=OFFSET)
                or self.appear(assets.ISLAND_HUB_CHECK, offset=OFFSET)
            ):
                break
            if self.appear(assets.ISLAND_PROMO_MODAL, offset=OFFSET):
                if not is_promo_method_selected(self.device.image, method):
                    self.device.click(_box_button(PROMO_METHOD_TABS[method], f'PROMO_TAB_{method}'))
                    continue
                if not max_clicked and self.appear_then_click(assets.ISLAND_PROMO_MAX, offset=OFFSET, interval=1):
                    max_clicked = True
                    continue
                if self.appear_then_click(assets.ISLAND_PROMO_CONFIRM, offset=OFFSET, interval=2):
                    submitted = True
                continue
            if self.appear(assets.ISLAND_PROMO_CHECK, offset=OFFSET) and not submitted and card_timer.reached():
                self.device.click(_box_button(PROMO_CARD_BOXES[promo_type], f'PROMO_CARD_{promo_type}'))
                card_timer.reset()
                continue

        self.ui_ensure(page_resonance_island_hub, skip_first_screenshot=False)

    def collect_daily_income(self):
        """Open 今日收益 -> 营收概览 and collect income, then return to beach.

        Pages:
            in: page_resonance_island_beach
            out: page_resonance_island_beach
        """
        self.ui_ensure(page_resonance_island_beach, skip_first_screenshot=False)
        income = read_beach_income(self.device.image)
        if income == 0:
            logger.info('海岛今日收益为 0，跳过收钱')
            return
        self.ui_ensure(page_resonance_island_revenue, skip_first_screenshot=False)
        collected = False
        settle = Timer(6.0).start()
        for _ in self.loop(timeout=15):
            if self.handle_reward_popup():
                collected = True
                settle.reset()
                continue
            if collected and self.appear(assets.ISLAND_REVENUE_CHECK, offset=OFFSET):
                break
            if self.appear_then_click(assets.ISLAND_REVENUE_COLLECT, offset=OFFSET, interval=2):
                settle.reset()
                continue
            if settle.reached():
                break
        self.ui_ensure(page_resonance_island_beach, skip_first_screenshot=False)

    def run(self):
        clean_garbage = getattr(self.config, 'ResonanceIsland_CleanTrainGarbage', True)
        promo_type = getattr(self.config, 'ResonanceIsland_PromotionType', 'promotion')
        play_vb = getattr(self.config, 'ResonanceIsland_PlayVolleyball', True)
        collect_income = getattr(self.config, 'ResonanceIsland_CollectIncome', True)
        friend_fight = getattr(self.config, 'ResonanceIsland_FriendFight', True)
        friend_clean = getattr(self.config, 'ResonanceIsland_FriendClean', True)

        if clean_garbage:
            self.clean_train_garbage()

        if promo_type != 'none' or play_vb or collect_income or friend_fight or friend_clean:
            self.goto_island_hub()
            if promo_type != 'none':
                self.run_promotion()
            if play_vb:
                run_beach_volleyball(self)
            if collect_income or friend_fight or friend_clean:
                self.ui_ensure(page_resonance_island_beach, skip_first_screenshot=False)
                if collect_income:
                    self.collect_daily_income()
                if friend_fight or friend_clean:
                    run_island_friends(self, fight=friend_fight, clean=friend_clean)

        self.ui_goto_main()
        self.config.task_delay(server_update=True)
