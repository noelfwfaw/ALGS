from datetime import datetime, timedelta
import os
import re

from filelock import FileLock

from module.base.button import Button
from module.exception import GamePageUnknownError
from module.ocr.ocr import Ocr
from module.resonance import assets
from module.resonance.page import page_main, page_resonance_city
from module.resonance.resonance_ui import ResonanceUI
from module.resonance.shop import normalize_name
from module.resonance.smart_state import _read_json_dict, _write_json_dict


OFFSET = (5, 5)
GARBAGE_STATE_PATH = os.path.join('config', 'state', 'resonance_wilderness_recycle.json')

CITY_GARBAGE_NPC = Button(area=(), color=(), button=(290, 79, 362, 151),  # alas-lint: allow - click-only avatar centre; city OCR and colour guard it
                          name='CITY_GARBAGE_NPC')
CITY_GARBAGE_NPC_CHECK = Button(area=(265, 60, 390, 175), color=(), button=(),  # alas-lint: allow - colour-only avatar ROI; no image asset is generated
                                name='CITY_GARBAGE_NPC_CHECK')
RECYCLE_OPTION = Button(area=(), color=(), button=(750, 300, 1180, 350),  # alas-lint: allow - click-only coordinates; station and option OCR guard it
                        name='RECYCLE_OPTION')
RECYCLE_ALL = Button(area=(), color=(), button=(996, 107, 1225, 160),  # alas-lint: allow - click-only coordinates; panel label and colour guard it
                     name='RECYCLE_ALL')
NPC_MENU_FIRST_ROW = Button(area=(733, 292, 1192, 358), color=(), button=(),  # alas-lint: allow - colour-only ROI; no image asset is generated
                            name='NPC_MENU_FIRST_ROW')
NPC_MENU_SECOND_ROW = Button(area=(733, 367, 1192, 433), color=(), button=(),  # alas-lint: allow - colour-only ROI; no image asset is generated
                             name='NPC_MENU_SECOND_ROW')
RECYCLE_ALL_CHECK = Button(area=(996, 107, 1225, 160), color=(), button=(),  # alas-lint: allow - colour-only ROI; no image asset is generated
                           name='RECYCLE_ALL_CHECK')

CITY_NAME_OCR = Ocr((170, 515, 450, 550), lang='cnocr', threshold=128, name='WILDERNESS_CITY_NAME')
DIALOG_STATION_OCR = Ocr((940, 220, 1030, 250), lang='cnocr', threshold=128, name='GARBAGE_DIALOG_STATION')
RECYCLE_OPTION_OCR = Ocr((785, 308, 890, 345), lang='cnocr', threshold=128, name='GARBAGE_RECYCLE_OPTION')
PANEL_LABEL_OCR = Ocr((748, 158, 900, 190), lang='cnocr', threshold=128, name='GARBAGE_PANEL_LABEL')
GARBAGE_COUNT_OCR = Ocr((775, 120, 840, 155), lang='cnocr', threshold=128,
                        alphabet='0123456789', name='GARBAGE_COUNT')
PANEL_REWARD_OCR = Ocr((1100, 165, 1190, 197), lang='cnocr', threshold=128,
                       letter=(255, 200, 80), alphabet='0123456789', name='GARBAGE_REWARD')
POPUP_REWARD_OCR = Ocr((640, 392, 702, 416), lang='cnocr', threshold=128,
                       alphabet='0123456789', name='GARBAGE_POPUP_REWARD')


def _server_day_key(now=None):
    current = now if now is not None else datetime.now()
    return (current - timedelta(hours=5)).strftime('%Y-%m-%d')


def _garbage_state_key(config_name):
    name = str(config_name or 'default').strip()
    return name or 'default'


def is_garbage_cleaned_today(config_name, path=GARBAGE_STATE_PATH, now=None):
    if not os.path.isfile(path):
        return False
    with FileLock(f'{path}.lock', timeout=5):
        state = _read_json_dict(path)
    return state.get(_garbage_state_key(config_name)) == _server_day_key(now)


def mark_garbage_cleaned(config_name, path=GARBAGE_STATE_PATH, now=None):
    today = _server_day_key(now)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with FileLock(f'{path}.lock', timeout=5):
        state = _read_json_dict(path)
        state[_garbage_state_key(config_name)] = today
        _write_json_dict(state, path)


def _read_digits(ocr, image):
    raw = normalize_name(ocr.ocr(image))
    return int(raw) if re.fullmatch(r'[0-9]+', raw) else None


class ResonanceWildernessRecycle(ResonanceUI):
    def _is_wilderness_city(self, image):
        name = normalize_name(CITY_NAME_OCR.ocr(image))
        return name in ('荒原站', '荒原立站')

    def _garbage_npc_visible(self):
        return self.image_color_count(CITY_GARBAGE_NPC_CHECK, (240, 240, 240), threshold=25, count=500)

    def _is_recycle_dialog(self, image):
        station = normalize_name(DIALOG_STATION_OCR.ocr(image))
        option = normalize_name(RECYCLE_OPTION_OCR.ocr(image))
        return station == '荒原站' and option == '垃圾回收'

    def _is_recycle_dialog_layout(self, image):
        return (self.image_color_count(NPC_MENU_FIRST_ROW, (245, 245, 245), threshold=25, count=15000)
                and self.image_color_count(NPC_MENU_SECOND_ROW, (245, 245, 245), threshold=25, count=15000))

    def _recycle_panel_quantity(self, image):
        if normalize_name(PANEL_LABEL_OCR.ocr(image)) == '当前垃圾数量':
            return _read_digits(GARBAGE_COUNT_OCR, image)
        return None

    def _return_to_main(self, cleaned):
        for _ in self.loop(skip_first=False, timeout=12):
            image = self.device.image
            if assets.LOGIN_REWARD.match(image, offset=OFFSET, similarity=0.8):
                self.handle_reward_popup()
                continue
            if self.handle_reward_popup():
                continue
            if self.ui_page_appear(page_main, offset=OFFSET) and self.appear(assets.MAIN_VISIT_CITY, offset=OFFSET):
                return cleaned
            quantity = self._recycle_panel_quantity(image)
            if quantity is not None:
                if quantity == 0:
                    cleaned = True
                self.appear_then_click(assets.OP_BACK, offset=OFFSET, interval=2)
                continue
            if self._is_recycle_dialog(image) or self._is_recycle_dialog_layout(image):
                self.appear_then_click(assets.OP_BACK, offset=OFFSET, interval=2)
                continue
            if self.ui_page_appear(page_resonance_city, offset=OFFSET):
                self.appear_then_click(assets.DAILY_HOME, offset=OFFSET, interval=2)
                continue
        raise GamePageUnknownError('Wilderness recycle could not return to the train main page')

    def recycle_wilderness_garbage(self):
        self.ui_ensure(page_main, skip_first_screenshot=False)
        submitted = False
        cleaned = False
        expected_reward = None
        city_clicked = False
        npc_clicked = False
        option_clicked = False

        for _ in self.loop(skip_first=False, timeout=20):
            image = self.device.image
            if assets.LOGIN_REWARD.match(image, offset=OFFSET, similarity=0.8):
                if submitted and not cleaned and expected_reward is not None:
                    cleaned = _read_digits(POPUP_REWARD_OCR, image) == expected_reward
                self.handle_reward_popup()
                continue
            if self.handle_reward_popup():
                continue
            if self.ui_page_appear(page_main, offset=OFFSET) and self.appear(assets.MAIN_VISIT_CITY, offset=OFFSET):
                if cleaned:
                    return True
                if submitted:
                    return False
                if not city_clicked:
                    self.appear_then_click(assets.MAIN_VISIT_CITY, offset=OFFSET, interval=2)
                    city_clicked = True
                continue
            if self._is_recycle_dialog(image):
                if cleaned or submitted:
                    self.appear_then_click(assets.OP_BACK, offset=OFFSET, interval=2)
                elif not option_clicked and self.appear(assets.OP_BACK, offset=OFFSET):
                    self.device.click(RECYCLE_OPTION)
                    self.interval_reset(RECYCLE_OPTION)
                    option_clicked = True
                continue
            quantity = self._recycle_panel_quantity(image)
            if quantity is not None:
                if quantity == 0:
                    cleaned = True
                if cleaned:
                    self.appear_then_click(assets.OP_BACK, offset=OFFSET, interval=2)
                elif (not submitted and quantity > 0
                      and self.image_color_count(RECYCLE_ALL_CHECK, (255, 190, 40), threshold=45, count=5000)
                      and self.appear(assets.OP_BACK, offset=OFFSET)):
                    expected_reward = _read_digits(PANEL_REWARD_OCR, image)
                    self.device.click(RECYCLE_ALL)
                    self.interval_reset(RECYCLE_ALL)
                    submitted = True
                continue
            if self.ui_page_appear(page_resonance_city, offset=OFFSET):
                if cleaned:
                    self.appear_then_click(assets.DAILY_HOME, offset=OFFSET, interval=2)
                elif (not npc_clicked and self._garbage_npc_visible()
                      and self._is_wilderness_city(image)):
                    self.device.click(CITY_GARBAGE_NPC)
                    self.interval_reset(CITY_GARBAGE_NPC)
                    npc_clicked = True
                continue

        return self._return_to_main(cleaned)
