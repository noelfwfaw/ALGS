"""Player profile, 12-city prestige, and crew resonance scanner for 雷索纳斯."""

from bisect import bisect_right
from difflib import SequenceMatcher
import json
import os
import time

import cv2
import numpy as np

from module.exception import GameStuckError
from module.ocr.ocr import Ocr
from module.resonance import assets
from module.resonance.columba import PRESTIGE_CITIES, load_columba_data
from module.resonance.crew_scan import (
    _crew_x0, _upscale_gray, classify_crew_resonance, detect_crew_rows, is_crew_slot_occupied,
    match_crew_role, parse_crew_roster_page,
)
from module.resonance.map_nav import MAP_COORDS_05X, _make_point_button, canonical_city_name
from module.resonance.page import page_main, page_resonance_crew
from module.resonance.shop import normalize_name
from module.resonance.trade import ResonanceTrade, parse_fraction_text

OFFSET = (5, 5)
PROFILE_CACHE_PATH = os.path.join('config', 'state', 'resonance_profile.json')

PRESTIGE_THRESHOLDS = (
    500, 1000, 1500, 2000, 2500,
    3500, 4500, 5500, 6500, 7500,
    9000, 10500, 12000, 13500, 15000,
    17000, 19000, 21000, 23000, 25000,
)

PRESTIGE_LIST_BOX = (720, 300, 1175, 615)
CREW_GRID_BOX = (40, 90, 1240, 660)

MAIN_AVATAR_BTN = _make_point_button(157, 663, 'MAIN_AVATAR', radius=25)
PROFILE_OUTSIDE_BTN = _make_point_button(970, 370, 'PROFILE_OUTSIDE', radius=30)

MAIN_CITY_OCR = Ocr([], lang='cnocr', threshold=128, name='Main city')
DRAWER_NUM_OCR = Ocr([], lang='cnocr', threshold=128, alphabet='0123456789/', name='Drawer bar')
PRESTIGE_NAME_OCR = Ocr([], lang='cnocr', threshold=128, name='Prestige city')
PRESTIGE_VAL_OCR = Ocr([], lang='cnocr', threshold=128, alphabet='0123456789', name='Prestige value')

_PRESTIGE_ALIASES = {
    '7号自由港': '七号自由港',
    '明数据中心': '澄明数据中心',
    '妮塔发射中心': '阿妮塔发射中心',
    '式林源': '武林源',
}


def prestige_points_to_level(points):
    """Convert cumulative city prestige points into trade prestige level 1..20."""
    idx = bisect_right(PRESTIGE_THRESHOLDS, max(0, int(points)))
    return max(1, min(20, idx))


def match_prestige_city(raw_name):
    """Match an OCR prestige row label to one of the 12 PRESTIGE_CITIES."""
    text = normalize_name(raw_name or '')
    if not text:
        return None
    if text in _PRESTIGE_ALIASES:
        return _PRESTIGE_ALIASES[text]
    if text in PRESTIGE_CITIES:
        return text
    norm = text.replace('坡', '城').replace('啵', '城').replace('圾', '城')
    if norm in PRESTIGE_CITIES:
        return norm
    for city in PRESTIGE_CITIES:
        if text in city or city in text:
            return city
    best = max(
        PRESTIGE_CITIES,
        key=lambda city: (
            len(set(norm) & set(city)),
            SequenceMatcher(None, norm, city).ratio(),
        ),
    )
    if SequenceMatcher(None, norm, best).ratio() >= 0.45 or len(set(norm) & set(best)) >= 2:
        return best
    return None


def read_main_city_name(image):
    """Read the current city name from the main-screen '访问城市' card."""
    sub = image[498:520, 1130:1240]
    inv = 255 - sub.min(axis=2)
    stretched = np.clip((inv.astype(np.float32) - 30.0) * (255.0 / 160.0), 0, 255).astype(np.uint8)
    raw = MAIN_CITY_OCR.ocr([_upscale_gray(255 - stretched, scale=3)], direct_ocr=True)
    text = normalize_name(raw[0] if isinstance(raw, list) and raw else '')
    if not text:
        return ''
    city = canonical_city_name(text)
    if city in MAP_COORDS_05X:
        return city
    best = max(MAP_COORDS_05X.keys(), key=lambda c: SequenceMatcher(None, text, c).ratio())
    return best if SequenceMatcher(None, text, best).ratio() >= 0.6 else ''


def _find_star_rows(image):
    """Locate star-icon Y spans (y0, y1) inside the open prestige modal."""
    strip = image[300:615, 730:760].mean(axis=(1, 2))
    bright = np.where(strip > 75)[0]
    if len(bright) == 0:
        return []
    runs = []
    start = prev = int(bright[0])
    for y in bright[1:]:
        yi = int(y)
        if yi > prev + 5:
            if prev - start >= 12:
                runs.append((300 + start, 300 + prev))
            start = yi
        prev = yi
    if prev - start >= 12:
        runs.append((300 + start, 300 + prev))
    return runs


def _tight_number_crop(gray):
    """Trim dark margins around bright prestige digits for reliable single-digit OCR."""
    rows = np.where(gray.max(axis=1) > 120)[0]
    cols = np.where(gray.max(axis=0) > 120)[0]
    if len(rows) and len(cols):
        gray = gray[
            max(0, int(rows[0]) - 4):min(gray.shape[0], int(rows[-1]) + 5),
            max(0, int(cols[0]) - 6):min(gray.shape[1], int(cols[-1]) + 7),
        ]
    return np.stack((gray, gray, gray), axis=2)


def parse_prestige_rows(image):
    """Parse visible (canonical_city, points) pairs from the '所有城市声望' modal."""
    rows = _find_star_rows(image)
    if not rows:
        return []
    name_imgs = []
    val_imgs = []
    for y0, y1 in rows:
        yc = (y0 + y1) // 2
        name_imgs.append(_upscale_gray(image[yc - 16:yc + 16, 768:960].max(axis=2), scale=2))
        val_imgs.append(_tight_number_crop(image[yc - 16:yc + 16, 1020:1170].max(axis=2)))

    names = PRESTIGE_NAME_OCR.ocr(name_imgs, direct_ocr=True)
    vals = PRESTIGE_VAL_OCR.ocr(val_imgs, direct_ocr=True)
    parsed = []
    for raw_name, raw_val in zip(names, vals):
        city = match_prestige_city(raw_name)
        digits = ''.join(ch for ch in str(raw_val) if ch.isdigit())
        if city and digits:
            parsed.append((city, int(digits)))
    return parsed


def load_profile(path=PROFILE_CACHE_PATH):
    """Load cached player profile JSON if present, else return None."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def save_profile(profile, path=PROFILE_CACHE_PATH):
    """Atomically persist player trade profile JSON."""
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


class ResonanceProfile(ResonanceTrade):
    """Controller for docked arrival, city reading, prestige, and crew resonance scans."""

    def wait_until_docked(self, timeout=900):
        """Wait until the train finishes any active transit and docks on page_main."""
        settled = 0
        for _ in self.loop(skip_first=False, timeout=timeout):
            self.device.stuck_record_clear()
            if self.handle_reward_popup() or self.handle_operation_victory():
                settled = 0
                continue
            if self.ui_page_appear(page_main, offset=OFFSET) and self.appear(assets.MAIN_VISIT_CITY, offset=OFFSET):
                settled += 1
                if settled >= 2:
                    self.ui_current = page_main
                    return
            else:
                settled = 0
        raise GameStuckError('Resonance train did not dock at station')

    def get_current_city(self):
        """Return canonical current city name from main screen, falling back to world map."""
        self.ui_ensure(page_main, skip_first_screenshot=False)
        self.wait_until_docked()
        city = read_main_city_name(self.device.image)
        if city in MAP_COORDS_05X:
            return city
        self.open_current_city_exchange()
        city = canonical_city_name(self.read_selected_station_name())
        self.ui_goto_main()
        return city

    def _open_profile_drawer(self):
        """Open the left conductor profile drawer from page_main."""
        self.interval_clear((MAIN_AVATAR_BTN, assets.PROFILE_MORE_INFO))
        for _ in self.loop(skip_first=False, timeout=12):
            if self.appear(assets.PROFILE_DRAWER_CHECK, offset=OFFSET):
                self.wait_until_still((350, 250, 670, 290), timeout=4, threshold=1.5, skip_first_screenshot=False)
                return
            if self.ui_page_appear(page_main, offset=OFFSET) and self.appear(assets.MAIN_VISIT_CITY, offset=OFFSET):
                self.device.click(MAIN_AVATAR_BTN)
                self.wait_until_appear(assets.PROFILE_DRAWER_CHECK, offset=OFFSET, timeout=3)
                continue
            if self.handle_reward_popup():
                continue
        raise GameStuckError('Resonance profile drawer did not open')

    def _close_profile_drawer(self):
        """Close the conductor profile drawer back to page_main."""
        for _ in self.loop(skip_first=False, timeout=12):
            if self.ui_page_appear(page_main, offset=OFFSET) and self.appear(assets.MAIN_VISIT_CITY, offset=OFFSET):
                return
            if (self.appear(assets.PRESTIGE_MODAL_CHECK, offset=OFFSET)
                    or self.appear(assets.PRESTIGE_MODAL_CONFIRM, offset=OFFSET)):
                self.appear_then_click(assets.PRESTIGE_MODAL_CONFIRM, offset=OFFSET, interval=2)
                continue
            if self.appear(assets.PROFILE_DRAWER_CHECK, offset=OFFSET):
                self.device.click(PROFILE_OUTSIDE_BTN)
                self.wait_until_appear(assets.MAIN_VISIT_CITY, offset=OFFSET, timeout=3)
                continue
        raise GameStuckError('Resonance profile drawer did not close')

    def _open_prestige_modal(self):
        """Expand profile details and open the '所有城市声望' modal."""
        self.interval_clear((assets.PROFILE_MORE_INFO, assets.PROFILE_PRESTIGE_EYE))
        for _ in self.loop(timeout=15):
            if (self.appear(assets.PRESTIGE_MODAL_CHECK, offset=OFFSET)
                    and self.appear(assets.PRESTIGE_MODAL_CONFIRM, offset=OFFSET)):
                self.wait_until_still(PRESTIGE_LIST_BOX, timeout=5, threshold=1.5, skip_first_screenshot=False)
                return
            if self.appear(assets.PROFILE_COLLAPSE, offset=OFFSET):
                self.appear_then_click(assets.PROFILE_PRESTIGE_EYE, offset=OFFSET, interval=2)
                continue
            if self.appear(assets.PROFILE_MORE_INFO, offset=OFFSET):
                self.appear_then_click(assets.PROFILE_MORE_INFO, offset=OFFSET, interval=2)
                continue
        raise GameStuckError('Resonance prestige modal did not open')

    def _read_drawer_bars(self):
        """Read (fatigue_tuple, max_lot) from the open profile drawer."""
        res = DRAWER_NUM_OCR.ocr([
            self.device.image[258:282, 360:460],
            self.device.image[258:282, 570:665],
        ], direct_ocr=True)
        fatigue = parse_fraction_text(res[0]) if len(res) >= 1 else None
        cargo = parse_fraction_text(res[1]) if len(res) >= 2 else None
        return fatigue, (cargo[1] if cargo else 500)

    def scan_profile_and_prestige(self):
        """Read cargo capacity, fatigue, and all 12 city prestige levels from profile."""
        self._open_profile_drawer()
        fatigue, max_lot = self._read_drawer_bars()
        self._open_prestige_modal()

        points_by_city = {}
        prev = None
        for _ in range(4):
            if (self.appear(assets.PRESTIGE_MODAL_CHECK, offset=OFFSET)
                    or self.appear(assets.PRESTIGE_MODAL_CONFIRM, offset=OFFSET)):
                for city, pts in parse_prestige_rows(self.device.image):
                    points_by_city[city] = pts
                if len(points_by_city) >= len(PRESTIGE_CITIES):
                    break
                cur = self.image_crop(PRESTIGE_LIST_BOX)
                if prev is not None and cv2.absdiff(prev, cur).mean() < 2:
                    break
                prev = cur
                self.device.swipe((985, 580), (985, 410), duration=0.45, name='PRESTIGE_SCROLL')
                self.wait_until_still(PRESTIGE_LIST_BOX, timeout=6, threshold=1.0, skip_first_screenshot=False)
            else:
                raise GameStuckError('Resonance prestige modal closed unexpectedly')

        self._close_profile_drawer()
        prestige = {
            city: prestige_points_to_level(points_by_city.get(city, 0))
            for city in PRESTIGE_CITIES
        }
        return {'maxLot': max_lot, 'prestige': prestige, 'fatigue': fatigue}

    def scan_crew_resonance(self):
        """Scan the crew roster screen and return {role: {'resonance': level}}."""
        self.ui_ensure(page_resonance_crew, skip_first_screenshot=False)
        self.wait_until_still(CREW_GRID_BOX, timeout=5, threshold=1.5, skip_first_screenshot=False)
        known_roles = set(load_columba_data()['resonance_skills'].keys())
        roles = {}
        prev = None
        for _ in range(25):
            if self.ui_page_appear(page_resonance_crew, offset=OFFSET):
                roles.update({
                    role: max(lv, roles.get(role, 0))
                    for role, lv in parse_crew_roster_page(self.device.image, known_roles).items()
                })
                cur = self.image_crop(CREW_GRID_BOX)
                if prev is not None and cv2.absdiff(prev, cur).mean() < 2:
                    break
                prev = cur
                self.device.drag(
                    (640, 560), (640, 310),
                    point_random=(0, 0, 0, 0), hold_duration=0.15, name='CREW_SCROLL',
                )
                self.wait_until_still(CREW_GRID_BOX, timeout=8, threshold=1.0, skip_first_screenshot=False)
            else:
                raise GameStuckError('Resonance crew roster closed unexpectedly')

        self.ui_goto_main()
        return {role: {'resonance': lv} for role, lv in roles.items() if lv > 0}

    def ensure_profile(self, force_refresh=False, max_age_hours=24, cache_path=PROFILE_CACHE_PATH):
        """Return cached trade profile if fresh, else scan prestige, cargo, and crew."""
        cached = load_profile(cache_path)
        now = time.time()
        if (
            not force_refresh
            and cached is not None
            and cached.get('maxLot', 0) > 0
            and len(cached.get('prestige', {})) >= len(PRESTIGE_CITIES)
            and (now - cached.get('updated_at', 0)) < max_age_hours * 3600
        ):
            return cached

        info = self.scan_profile_and_prestige()
        roles = self.scan_crew_resonance()
        profile = {
            'maxLot': info['maxLot'],
            'prestige': info['prestige'],
            'roles': roles,
            'updated_at': now,
        }
        save_profile(profile, path=cache_path)
        return profile
