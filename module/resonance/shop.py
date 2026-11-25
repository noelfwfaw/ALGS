import re
import unicodedata

import cv2

from module.exception import GameStuckError, TaskFailed
from module.logger import logger
from module.ocr.ocr import Ocr
from module.resonance import assets
from module.resonance.page import page_resonance_shop
from module.resonance.resonance_ui import ResonanceUI


OFFSET = (5, 5)
INVENTORY = (613, 166, 1239, 651)
PRICE_COLUMNS = ((782, 198, 899, 655), (1119, 198, 1236, 655))
MODAL_CURRENCY = (584, 432, 642, 475)
MODAL_NAME = (520, 304, 760, 329)
GOLD_BALANCE = (1018, 107, 1147, 130)
GOLD_TOTAL = (637, 441, 820, 467)
QUANTITY = Ocr((570, 351, 707, 379), threshold=75, alphabet='0123456789/', name='Shop quantity')
MONEY = Ocr([], lang='cnocr', threshold=75, alphabet='0123456789', name='Shop gold')


def normalize_name(name):
    return ''.join(unicodedata.normalize('NFKC', name).split())


def filter_names(text):
    names = map(normalize_name, re.split(r'[,，、;；\n]+', text or ''))
    return set(filter(None, names))


class ResonanceShop(ResonanceUI):
    def run(self):
        include = filter_names(self.config.ResonanceShop_Include)
        exclude = filter_names(self.config.ResonanceShop_Exclude)
        self.ui_ensure(page_resonance_shop, skip_first_screenshot=False)
        self.ui_click(assets.SHOP_HQ_TAB, assets.SHOP_HQ, offset=OFFSET, retry_wait=2, skip_first_screenshot=True)
        self.ui_click(assets.SHOP_BATCH_ON, assets.SHOP_BATCH_OFF, offset=OFFSET, retry_wait=2,
                      skip_first_screenshot=True)
        self.scan_shop(include, exclude)
        self.ui_goto_main()
        self.config.task_delay(server_update=True)

    def scan_shop(self, include, exclude):
        for _ in range(24):
            if not self.scroll_shop(1):
                break
        else:
            raise GameStuckError('Resonance shop did not reach the top')
        for _ in range(24):
            self.buy_visible(include, exclude)
            if not self.scroll_shop(-1):
                return
        raise GameStuckError('Resonance shop did not reach the bottom')

    def scroll_shop(self, direction):
        if self.appear(assets.SHOP_HQ, offset=OFFSET) and self.appear(assets.SHOP_BATCH_OFF, offset=OFFSET):
            before = self.image_crop(INVENTORY)
            self.device.swipe((1090, 410), (1090, 410 + direction * 245), duration=0.45, name='SHOP_SCROLL')
            if self.wait_until_still(INVENTORY, timeout=8, threshold=2, skip_first_screenshot=False):
                return cv2.absdiff(before, self.image_crop(INVENTORY)).mean() >= 2
        raise GameStuckError('Resonance shop did not settle after scrolling')

    def gold_items(self):
        for dx, column in zip((0, 337), PRICE_COLUMNS):
            for icon in assets.TEMPLATE_SHOP_LIST_GOLD.match_multi(
                    self.image_crop(column), similarity=0.86, threshold=7):
                y = icon.area[1] + column[1]
                icon = icon.move(column[:2], name=f'SHOP_ITEM_{dx}_{y}')
                if self.image_color_count(icon, (217, 175, 66), threshold=58, count=35):
                    yield icon, (726 + dx, y - 41, 902 + dx, y - 14)

    def buy_visible(self, include, exclude):
        tried = []
        for _ in range(24):
            if self.appear(assets.SHOP_HQ, offset=OFFSET) and self.appear(assets.SHOP_BATCH_OFF, offset=OFFSET):
                for icon, name_area in self.gold_items():
                    icon_x, icon_y = icon.area[:2]
                    title = self.image_crop(name_area)
                    # Some goods cap a single order below the remaining stock.
                    quota = self.image_crop((name_area[2] - 119, icon_y - 65, name_area[2], icon_y - 43))
                    if any(abs(x - icon_x) <= 5 and abs(y - icon_y) <= 5
                           and cv2.absdiff(previous_title, title).mean() < 5
                           and (not purchased or cv2.absdiff(previous_quota, quota).mean() < 0.75)
                           for x, y, previous_title, previous_quota, purchased in tried):
                        continue
                    tried.append((icon_x, icon_y, title, quota, False))
                    name = None
                    if include or exclude:
                        name = self.read_name(name_area)
                        if not name or name in exclude or (include and name not in include):
                            continue
                    balance = self.image_crop(GOLD_BALANCE)
                    self.device.click(icon)
                    if self.buy_item(name, balance):
                        tried[-1] = (icon_x, icon_y, title, quota, True)
                    break
                else:
                    return
            else:
                break
        raise GameStuckError('Resonance shop could not finish scanning its visible items')

    def read_name(self, area):
        reader = Ocr(area, lang='cnocr', threshold=120, name='Shop item')
        return normalize_name(reader.ocr(self.device.image))

    def modal_is_gold(self):
        payment_row = self.image_crop((MODAL_CURRENCY[0], MODAL_CURRENCY[1], 850, MODAL_CURRENCY[3]))
        if assets.TEMPLATE_SHOP_MODAL_TICKET.match(payment_row, similarity=0.82):
            return False
        price = self.image_crop(MODAL_CURRENCY)
        similarity, coin = assets.TEMPLATE_SHOP_MODAL_GOLD.match_result(price)
        return similarity > 0.92 and self.image_color_count(
            coin.move(MODAL_CURRENCY[:2]), (217, 175, 66), threshold=58, count=45,
        )

    def buy_item(self, expected_name, balance):
        if self.wait_until_appear(assets.SHOP_MODAL_PRICE, offset=OFFSET, timeout=3, settle=2):
            return self.confirm_item(expected_name, balance)
        if self.appear(assets.SHOP_HQ, offset=OFFSET):
            logger.info('Resonance shop item did not open a purchase dialog')
            return False
        else:
            raise GameStuckError('Resonance shop item opened an unrecognized dialog')

    def confirm_item(self, expected_name, balance):
        for _ in self.loop(timeout=8):
            if self.appear(assets.SHOP_MODAL_PRICE, offset=OFFSET) and self.appear(assets.SHOP_MAX, offset=OFFSET):
                if not self.modal_is_gold():
                    logger.warning('Resonance shop skipped a purchase without a confirmed gold price')
                    break
                if expected_name and self.read_name(MODAL_NAME) != expected_name:
                    logger.warning(f'Resonance shop skipped an item with a mismatched name: {expected_name}')
                    break
                quantity = re.fullmatch(r'(\d+)/(\d+)', QUANTITY.ocr(self.device.image))
                if quantity:
                    current, maximum = map(int, quantity.groups())
                    if 0 < current == maximum and self.appear(assets.SHOP_CONFIRM, offset=OFFSET):
                        total = self.image_crop(GOLD_TOTAL)
                        self.device.click(assets.SHOP_CONFIRM)
                        return self.wait_for_purchase(balance, total)
                    if 0 < current < maximum:
                        self.appear_then_click(assets.SHOP_MAX, offset=OFFSET, interval=2)
        if self.appear(assets.SHOP_CANCEL, offset=OFFSET):
            self.ui_click(assets.SHOP_CANCEL, assets.SHOP_HQ, offset=OFFSET, retry_wait=2,
                          skip_first_screenshot=True)
            return False
        else:
            raise GameStuckError('Resonance shop could not cancel its purchase dialog')

    def wait_for_purchase(self, balance, total):
        received = False
        for _ in self.loop(skip_first=False, timeout=12):
            if self.appear(assets.LOGIN_REWARD, offset=OFFSET):
                received = True
                self.handle_reward_popup()
                continue
            if received and self.purchase_list_ready():
                return True

        if not received and self.purchase_list_ready():
            result = self.verify_gold_charge(balance, total)
            if result is not None:
                return result
        self.config.task_delay(server_update=True)
        raise TaskFailed('琐呐总部商店未能确认购买结果，已停止本轮扫货')

    def purchase_list_ready(self):
        return (
            self.appear(assets.SHOP_HQ, offset=OFFSET)
            and self.wait_until_still(INVENTORY, timeout=5, threshold=2, skip_first_screenshot=False)
            and self.appear(assets.SHOP_HQ, offset=OFFSET)
        )

    def verify_gold_charge(self, balance, total):
        after = self.image_crop(GOLD_BALANCE)
        amounts = MONEY.ocr([balance, total, after], direct_ocr=True)
        if len(amounts) == 3 and all(amount.isascii() and amount.isdigit() for amount in amounts):
            before, cost, remaining = map(int, amounts)
            if 0 < cost == before - remaining:
                logger.info(f'琐呐总部商店未看到领奖弹窗，已核实扣除金币 {cost}，继续扫货')
                return True
            if before == remaining and cv2.absdiff(balance, after).mean() < 1:
                logger.warning('琐呐总部商店未看到领奖弹窗且金币余额未变，跳过该订单并继续扫货')
                return False
        return None
