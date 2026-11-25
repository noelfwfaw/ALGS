import re

import cv2

from module.exception import GameStuckError, TaskFailed
from module.logger import logger
from module.ocr.ocr import Ocr
from module.resonance import assets
from module.resonance.page import page_resonance_exchange, page_resonance_shop
from module.resonance.resonance_ui import EXCHANGE_MODAL_OFFSET, ResonanceUI
from module.resonance.shop import QUANTITY, filter_names, normalize_name


OFFSET = (5, 5)
OFFERS = (809, 151, 1252, 693)
BUTTONS = (1116, 150, 1245, 696)
PROMPT = (390, 428, 895, 461)
ITEM_NAME = Ocr(PROMPT, lang='cnocr', threshold=100, name='Exchange item')


class ResonanceExchange(ResonanceUI):
    def run(self):
        wanted = filter_names(self.config.ResonanceExchange_Include)
        if wanted:
            if self.ui_get_current_page(skip_first_screenshot=False) is not page_resonance_exchange:
                self.ui_ensure(page_resonance_shop)
                self.ui_click(assets.SHOP_HQ_TAB, assets.SHOP_HQ, offset=OFFSET, retry_wait=2,
                              skip_first_screenshot=True)
                self.ui_click(assets.EXCHANGE_TAB, assets.EXCHANGE_HUB, offset=OFFSET, retry_wait=2,
                              skip_first_screenshot=True)
            self.scan(wanted)
            if wanted:
                logger.info(f'赴命商店没有提交兑换的道具：{", ".join(sorted(wanted))}')
            self.ui_goto_main()
        self.config.task_delay(server_update=True)

    def scan(self, wanted):
        for _ in range(32):
            if not self.scroll_offers(1):
                break
        else:
            raise GameStuckError('Resonance exchange did not reach the top')
        for _ in range(32):
            self.exchange_visible(wanted)
            if not wanted or not self.scroll_offers(-1):
                return
        raise GameStuckError('Resonance exchange did not reach the bottom')

    def scroll_offers(self, direction):
        if self.appear(assets.EXCHANGE_HUB, offset=OFFSET):
            before = self.image_crop(OFFERS)
            # Leave overlap even on controls that add momentum after the swipe.
            self.device.swipe((1090, 416), (1090, 416 + direction * 145), duration=0.50,
                              name='EXCHANGE_SCROLL')
            if self.wait_until_still(OFFERS, timeout=8, threshold=2, skip_first_screenshot=False):
                return cv2.absdiff(before, self.image_crop(OFFERS)).mean() >= 2
        raise GameStuckError('Resonance exchange did not settle after scrolling')

    def exchange_visible(self, wanted):
        inspected = []
        for _ in range(12):
            if self.appear(assets.EXCHANGE_HUB, offset=OFFSET):
                buttons = assets.TEMPLATE_EXCHANGE_OPEN.match_multi(
                    self.image_crop(BUTTONS), similarity=0.88, threshold=8,
                )
                for button in buttons:
                    y = BUTTONS[1] + button.area[1]
                    button = button.move(BUTTONS[:2], name=f'EXCHANGE_OFFER_{y}')
                    active = self.image_color_count(button, (248, 176, 12), threshold=65, count=300)
                    if not active:
                        continue
                    picture = self.image_crop((650, y, 782, y + 65))
                    if any(abs(y - previous_y) < 5 and cv2.absdiff(picture, previous).mean() < 5
                           for previous_y, previous in inspected):
                        continue
                    inspected.append((y, picture))
                    self.device.click(button)
                    self.exchange_offer(wanted)
                    if not wanted:
                        return
                    break
                else:
                    return
            else:
                break
        raise GameStuckError('Resonance exchange could not finish reading its visible offers')

    def read_offer_name(self):
        # The list can scroll long names. The confirmation prints the full name in orange.
        mask = cv2.inRange(self.image_crop(PROMPT), (145, 55, 0), (255, 226, 106))
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
        for index in range(1, count):
            if stats[index, cv2.CC_STAT_AREA] < 4:
                mask[labels == index] = 0
        text = ITEM_NAME.ocr([cv2.cvtColor(mask, cv2.COLOR_GRAY2RGB)], direct_ocr=True)
        match = re.fullmatch(r'(.+?)[×xX*]\d+', normalize_name(text))
        return match[1] if match else None

    def exchange_offer(self, wanted):
        if self.wait_until_appear(assets.EXCHANGE_MODAL_ARROW, offset=EXCHANGE_MODAL_OFFSET, timeout=3, settle=2):
            for _ in self.loop(timeout=8):
                if self.appear(assets.EXCHANGE_MODAL_ARROW, offset=EXCHANGE_MODAL_OFFSET):
                    name = self.read_offer_name()
                    if name not in wanted:
                        break
                    quantity = re.fullmatch(r'(\d+)/(\d+)', QUANTITY.ocr(self.device.image))
                    if quantity:
                        current, maximum = map(int, quantity.groups())
                        if 0 < current == maximum and self.appear(assets.SHOP_CONFIRM, offset=OFFSET):
                            self.device.click(assets.SHOP_CONFIRM)
                            wanted.discard(name)
                            self.finish_exchange(name)
                            return
                        if 0 < current < maximum:
                            self.appear_then_click(assets.SHOP_MAX, offset=OFFSET, interval=2)
            self.ui_click(assets.SHOP_CANCEL, assets.EXCHANGE_HUB, offset=OFFSET, retry_wait=2,
                          skip_first_screenshot=True)
            return
        if self.ui_page_appear(page_resonance_exchange, offset=OFFSET):
            return
        raise GameStuckError('Resonance exchange opened an unrecognized dialog')

    def finish_exchange(self, name):
        received = False
        for _ in self.loop(skip_first=False, timeout=12):
            if self.appear(assets.LOGIN_REWARD, offset=OFFSET):
                received = True
                self.handle_reward_popup()
                continue
            if received and self.appear(assets.EXCHANGE_HUB, offset=OFFSET):
                return
        if self.appear(assets.EXCHANGE_HUB, offset=OFFSET):
            logger.warning(f'赴命商店未看到 {name} 的领奖弹窗，本轮跳过重复提交')
            return
        self.config.task_delay(server_update=True)
        raise TaskFailed(f'赴命商店未能核实 {name} 的兑换结果，已停止本轮任务')
