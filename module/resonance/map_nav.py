"""World map city selection, driving assist setup, and train travel for 雷索纳斯."""

import cv2
import numpy as np

from module.base.button import Button
from module.base.timer import Timer
from module.exception import GameStuckError
from module.logger import logger
from module.ocr.ocr import Ocr
from module.resonance import assets
from module.resonance.page import (
    page_main, page_resonance_map_station, page_resonance_trade_hub, page_resonance_world_map,
)
from module.resonance.resonance_ui import ResonanceUI
from module.resonance.shop import normalize_name

OFFSET = (5, 5)
MAP_CENTER = (639, 360)
SAFE_VIEWPORT = (150, 110, 1110, 595)
CLICKABLE_VIEWPORT = (80, 100, 1115, 640)
ZOOM_SLIDER_X = (1130, 1175)
ZOOM_SLIDER_Y = (365, 570)
ZOOM_MIN_THUMB_Y = 550

# 0.5x zoomed-out map offsets relative to 修格里城 = (0, 0).
MAP_COORDS_05X = {
    '修格里城': ('gold', 0, 0),
    '澄明数据中心': ('gold', -141, -58),
    '七号自由港': ('gold', -333, 59),
    '曼德矿场': ('gold', 158, 100),
    '阿妮塔发射中心': ('gold', -583, 266),
    '云岫桥基地': ('blue', 434, -65),
    '铁盟哨站': ('blue', 108, 1),
    '阿妮塔战备工厂': ('blue', -249, 100),
    '黑月游乐城': ('cyan', -299, -183),
    '淘金乐园': ('cyan', 210, 242),
    '阿妮塔能源研究所': ('cyan', -358, 284),
    '荒原站': ('red', 234, 0),
    '栖羽站': ('blue', 783, -225),
    '岚心城': ('gold', 983, -224),
    '远星大桥': ('red', -200, 419),
    '贡露城': ('gold', -101, 421),
    '维蒂林场': ('cyan', 67, 352),
    '塔图站': ('cyan', 483, 369),
    '海角城': ('gold', -433, 550),
    '汇流塔': ('cyan', -550, 549),
}
CITY_ALIASES = {'7号自由港': '七号自由港', '甘露城': '贡露城'}
_MATCH_CANDIDATES = sorted(
    list(MAP_COORDS_05X.keys()) + list(CITY_ALIASES.keys()),
    key=len,
    reverse=True,
)

STATION_NAME_OCR = Ocr((758, 104, 1080, 138), lang='cnocr', threshold=128, name='Map station name')
ASSIST_TOGGLES = (
    ('auto_enter', (361, 320, 437, 352)),
    ('auto_rush', (361, 393, 437, 425)),
    ('auto_ram', (361, 466, 437, 499)),
    ('auto_guard', (361, 539, 437, 572)),
)


def canonical_city_name(name):
    """Normalize OCR output and map aliases (e.g. 7号自由港 -> 七号自由港)."""
    text = normalize_name(name or '')
    if not text:
        return ''
    if text in CITY_ALIASES:
        return CITY_ALIASES[text]
    if text in MAP_COORDS_05X:
        return text
    for candidate in _MATCH_CANDIDATES:
        if candidate in text:
            return CITY_ALIASES.get(candidate, candidate)
    return text


def get_zoom_thumb_y(image):
    """Return top Y coordinate of the white zoom slider thumb, or None."""
    sub = image[ZOOM_SLIDER_Y[0]:ZOOM_SLIDER_Y[1], ZOOM_SLIDER_X[0]:ZOOM_SLIDER_X[1]]
    white = (sub[:, :, 0] > 220) & (sub[:, :, 1] > 220) & (sub[:, :, 2] > 220)
    ys = np.where(white.sum(axis=1) >= 16)[0]
    return int(ys.min()) + ZOOM_SLIDER_Y[0] if len(ys) else None


def is_zoomed_out_min(image):
    """Return True when the map zoom slider sits at minimum zoom (0.5x)."""
    thumb_y = get_zoom_thumb_y(image)
    return thumb_y is not None and thumb_y >= ZOOM_MIN_THUMB_Y


def _collect_color_markers(out, mask, color_name):
    """Append qualifying station marker centroids from a binary color mask."""
    num, _, stats, centroids = cv2.connectedComponentsWithStats(mask.astype(np.uint8))
    for idx in range(1, num):
        area = int(stats[idx, cv2.CC_STAT_AREA])
        bw = int(stats[idx, cv2.CC_STAT_WIDTH])
        bh = int(stats[idx, cv2.CC_STAT_HEIGHT])
        if 18 <= area <= 400 and 6 <= bw <= 26 and 6 <= bh <= 26 and 0.55 <= bw / max(1, bh) <= 1.8:
            out.append((color_name, int(round(centroids[idx][0])), int(round(centroids[idx][1]))))


def detect_map_markers_05x(image):
    """Detect visible station markers (color, cx, cy) on a 0.5x zoomed-out world map."""
    roi = np.ones(image.shape[:2], dtype=bool)
    roi[:90, :] = False
    roi[:225, :135] = False
    roi[615:, 845:] = False
    roi[325:625, 1125:1180] = False

    rgb = image.astype(np.int16)
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    masks = (
        ('gold', roi & (r > 180) & (g > 120) & (b < 80) & (r - b > 120)),
        ('blue', roi & (b > 170) & (r < 80) & (g > 60) & (g < 170)),
        ('cyan', roi & (b > 170) & (g > 160) & (r < 90)),
        ('red', roi & (r > 150) & (g < 65) & (b < 65)),
    )
    markers = []
    for color_name, mask in masks:
        _collect_color_markers(markers, mask, color_name)
    return markers


def _match_city_for_marker(color, x, y, ox, oy, table, used_cities, tol):
    """Find first unmatched reference city within tol of (x - ox, y - oy)."""
    for city, (ref_color, rx, ry) in table.items():
        if city in used_cities or color != ref_color:
            continue
        dx_err = (x - ox) - rx
        dy_err = (y - oy) - ry
        if abs(dx_err) <= tol and abs(dy_err) <= tol:
            return city, dx_err, dy_err
    return None


def _score_origin_hypothesis(ox, oy, detected, table, tol):
    """Score candidate map origin (ox, oy) by counting matching station markers."""
    matched = []
    used_cities = set()
    for color, x, y in detected:
        hit = _match_city_for_marker(color, x, y, ox, oy, table, used_cities, tol)
        if hit is not None:
            city, dx_err, dy_err = hit
            matched.append((city, dx_err, dy_err))
            used_cities.add(city)
    if not matched:
        return None
    err_x = int(round(float(np.median([e[1] for e in matched]))))
    err_y = int(round(float(np.median([e[2] for e in matched]))))
    return len(matched), ox + err_x, oy + err_y, [e[0] for e in matched]


def _hypotheses_for_marker(color, dx, dy, detected, table, tol):
    """Evaluate all reference cities matching a single detected marker color."""
    best = None
    for _, (ref_color, rx, ry) in table.items():
        if color != ref_color:
            continue
        candidate = _score_origin_hypothesis(dx - rx, dy - ry, detected, table, tol)
        if candidate is not None and (best is None or candidate[0] > best[0]):
            best = candidate
    return best


def localize_map_origin(detected, table=MAP_COORDS_05X, tol=5):
    """Return (inliers, ox, oy, matched_cities) for the 0.5x map origin, or None."""
    if not detected:
        return None
    best = None
    for color, dx, dy in detected:
        candidate = _hypotheses_for_marker(color, dx, dy, detected, table, tol)
        if candidate is not None and (best is None or candidate[0] > best[0]):
            best = candidate
    min_inliers = len(detected) if len(detected) <= 2 else 3
    if best is None or best[0] < min_inliers:
        return None
    return best


def localize_map_transform(detected, table=MAP_COORDS_05X, tol=6):
    """Return (inliers, ox, oy, scale, matched_cities), allowing slight zoom drift."""
    exact = localize_map_origin(detected, table=table, tol=tol)
    if exact is not None:
        return exact[0], float(exact[1]), float(exact[2]), 1.0, exact[3]
    if len(detected) < 3:
        return None
    best = None
    for step in range(92, 114, 2):
        scale = step / 100.0
        scaled_table = {c: (rc, rx * scale, ry * scale) for c, (rc, rx, ry) in table.items()}
        for color, dx, dy in detected:
            cand = _hypotheses_for_marker(color, dx, dy, detected, scaled_table, tol)
            if cand is not None and (best is None or cand[0] > best[0]):
                best = (cand[0], float(cand[1]), float(cand[2]), scale, cand[3])
    min_inliers = 3 if len(detected) <= 3 else 4
    return best if best is not None and best[0] >= min_inliers else None


def snap_to_detected_marker(tx, ty, ref_color, detected, max_dist=25):
    """Snap target (tx, ty) to nearest detected marker of matching color within max_dist."""
    best = None
    max_d2 = max_dist * max_dist
    for color, dx, dy in detected:
        if color != ref_color:
            continue
        d2 = (dx - tx) ** 2 + (dy - ty) ** 2
        if d2 <= max_d2 and (best is None or d2 < best[0]):
            best = (d2, dx, dy)
    return (best[1], best[2]) if best is not None else (int(round(tx)), int(round(ty)))


DEPART_SKIP_WEEK_INNER = (877, 510, 902, 534)


def is_assist_toggle_on(image, area):
    """Return True when the white toggle knob sits in the right half of `area`."""
    x1, y1, x2, y2 = area
    right_half = image[y1:y2, x1 + (x2 - x1) // 2:x2]
    return int((right_half.min(axis=2) > 200).sum()) > 150


def is_depart_skip_week_checked(image):
    """Return True when the '本周不再提示' checkbox on the depart popup shows a checkmark."""
    x1, y1, x2, y2 = DEPART_SKIP_WEEK_INNER
    return int((image[y1:y2, x1:x2].min(axis=2) > 180).sum()) >= 40


def _make_point_button(cx, cy, name, radius=10):
    """Construct a click-only Button centered at (cx, cy)."""
    cx, cy = int(cx), int(cy)
    area = (max(0, cx - radius), max(0, cy - radius), min(1280, cx + radius), min(720, cy + radius))
    return Button(area=area, color=(0, 0, 0), button=area, name=name)


class ResonanceMapNav(ResonanceUI):
    """World map city selection, driving assist setup, and train travel."""

    def read_selected_station_name(self):
        """Read selected city name from the blue station header."""
        return canonical_city_name(STATION_NAME_OCR.ocr(self.device.image))

    def zoom_out_min(self):
        """Zoom the world map all the way out to 0.5x."""
        drag_timer = Timer(1.2)
        self.interval_clear(assets.MAP_ZOOM_MINUS)
        for _ in self.loop(timeout=15):
            if self.ui_page_appear(page_resonance_world_map, offset=OFFSET):
                if is_zoomed_out_min(self.device.image):
                    return
                thumb_y = get_zoom_thumb_y(self.device.image)
                if thumb_y is not None and thumb_y < ZOOM_MIN_THUMB_Y and drag_timer.reached():
                    self.device.drag(
                        (1152, thumb_y + 8), (1152, 566),
                        segments=5, shake=(0, 0), point_random=(0, 0, 0, 0), shake_random=(0, 0, 0, 0),
                        hold_duration=0.15, name='MAP_ZOOM_OUT',
                    )
                    drag_timer.reset()
                    continue
                self.appear_then_click(assets.MAP_ZOOM_MINUS, offset=OFFSET, interval=1.0)
                continue
            if self.handle_trade_modal():
                continue
        raise GameStuckError('Resonance world map did not zoom out to minimum scale')

    def _wait_map_markers_still(self, timeout=2.5):
        """Wait until station markers stop moving after a map drag."""
        prev = detect_map_markers_05x(self.device.image)
        for _ in self.loop(skip_first=False, timeout=timeout):
            cur = detect_map_markers_05x(self.device.image)
            if len(cur) >= 3 and len(prev) >= 3:
                stable = sum(
                    1 for c, x, y in cur
                    if any(pc == c and abs(px - x) <= 3 and abs(py - y) <= 3 for pc, px, py in prev)
                )
                if stable >= min(len(cur), len(prev)) - 1:
                    return True
            elif len(cur) < 3 and len(prev) < 3:
                return True
            prev = cur
        return False

    def _select_city_step(self, target, ref_color, rx, ry, state):
        """Execute one closed-loop step toward selecting `target` on the 0.5x world map."""
        if self.ui_page_appear(page_resonance_map_station, offset=OFFSET):
            if self.read_selected_station_name() == target:
                return True
            self.ui_ensure(page_resonance_world_map, skip_first_screenshot=True)
            return False

        if self.ui_page_appear(page_resonance_world_map, offset=OFFSET):
            if not is_zoomed_out_min(self.device.image):
                self.zoom_out_min()
            detected = detect_map_markers_05x(self.device.image)
            loc = localize_map_transform(detected)
            if loc is None:
                self.device.drag(
                    (640, 360), (500, 360),
                    segments=6, shake=(0, 0), point_random=(0, 0, 0, 0), shake_random=(0, 0, 0, 0),
                    hold_duration=0.15, name='WORLD_MAP_RECOVER',
                )
                self._wait_map_markers_still()
                return False
            _, ox, oy, scale, _ = loc
            tx, ty = int(round(ox + rx * scale)), int(round(oy + ry * scale))
            prev_xy = state.get('origin')
            clamped = prev_xy is not None and abs(ox - prev_xy[0]) < 15 and abs(oy - prev_xy[1]) < 15
            in_safe = SAFE_VIEWPORT[0] <= tx <= SAFE_VIEWPORT[2] and SAFE_VIEWPORT[1] <= ty <= SAFE_VIEWPORT[3]
            in_click = CLICKABLE_VIEWPORT[0] <= tx <= CLICKABLE_VIEWPORT[2] and CLICKABLE_VIEWPORT[1] <= ty <= CLICKABLE_VIEWPORT[3]
            if in_safe or (clamped and in_click):
                sx, sy = snap_to_detected_marker(tx, ty, ref_color, detected)
                self.device.click(_make_point_button(sx, sy, 'MAP_CITY_' + target))
                self.wait_until_appear(assets.MAP_EXCHANGE, offset=OFFSET, timeout=5)
                return False
            state['origin'] = (ox, oy)
            dx = max(-360, min(360, 640 - tx))
            dy = max(-220, min(220, 360 - ty))
            self.device.drag(
                (640 - dx // 2, 360 - dy // 2), (640 + dx // 2, 360 + dy // 2),
                segments=6, shake=(0, 0), point_random=(0, 0, 0, 0), shake_random=(0, 0, 0, 0),
                hold_duration=0.15, name='WORLD_MAP_DRAG',
            )
            self._wait_map_markers_still()
            return False

        if self.handle_trade_modal() or self.handle_reward_popup():
            self.device.screenshot()
            return False
        self.ui_ensure(page_resonance_world_map, skip_first_screenshot=False)
        return False

    def select_city_on_map(self, target_city):
        """Open the world map, pan via constellation localization, and select `target_city`."""
        target = canonical_city_name(target_city)
        if target not in MAP_COORDS_05X:
            raise ValueError('Unknown or unmapped Resonance city: %r' % (target_city,))
        self.ui_ensure(page_resonance_world_map, skip_first_screenshot=False)
        self.zoom_out_min()
        ref_color, rx, ry = MAP_COORDS_05X[target]
        state = {}
        for _ in range(12):
            if self._select_city_step(target, ref_color, rx, ry, state):
                return True
        raise GameStuckError('Resonance failed to select city %s on world map' % target)

    def _open_assist_panel(self):
        """Open 波克士行驶辅助 panel on the station screen."""
        self.interval_clear(assets.MAP_DRIVE_ASSIST)
        for _ in self.loop(timeout=10):
            if self.appear(assets.MAP_ASSIST_PANEL, offset=OFFSET):
                return
            if self.appear(assets.MAP_EXCHANGE, offset=OFFSET):
                self.appear_then_click(assets.MAP_DRIVE_ASSIST, offset=OFFSET, interval=2)
        raise GameStuckError('Resonance driving assist panel did not open')

    def _sync_assist_toggles(self, desired):
        """Toggle any mismatched driving assist switches to match `desired`."""
        retry = Timer(1.2)
        for _ in self.loop(timeout=20):
            if self.appear(assets.MAP_ASSIST_PANEL, offset=OFFSET):
                mismatch = next(
                    ((key, area) for key, area in ASSIST_TOGGLES
                     if is_assist_toggle_on(self.device.image, area) != desired[key]),
                    None,
                )
                if mismatch is None:
                    return
                if retry.reached():
                    x1, y1, x2, y2 = mismatch[1]
                    self.device.click(_make_point_button((x1 + x2) // 2, (y1 + y2) // 2,
                                                         'ASSIST_' + mismatch[0], radius=6))
                    retry.reset()
        raise GameStuckError('Resonance driving assist toggles did not settle')

    def _close_assist_panel(self):
        """Close 波克士行驶辅助 panel back to page_resonance_map_station."""
        self.interval_clear(assets.MAP_DRIVE_ASSIST)
        for _ in self.loop(timeout=10):
            if self.appear(assets.MAP_ASSIST_PANEL, offset=OFFSET):
                self.appear_then_click(assets.MAP_DRIVE_ASSIST, offset=OFFSET, interval=2)
                continue
            if self.wait_until_disappear(assets.MAP_ASSIST_PANEL, offset=OFFSET,
                                         skip_first_screenshot=True, timeout=1):
                return
        raise GameStuckError('Resonance driving assist panel did not close')

    def configure_drive_assist(self, use_ramming=False):
        """Enforce auto-enter, auto-rush, auto-guard ON and ramming per `use_ramming`."""
        desired = {
            'auto_enter': True,
            'auto_rush': True,
            'auto_ram': bool(use_ramming),
            'auto_guard': True,
        }
        self._open_assist_panel()
        self._sync_assist_toggles(desired)
        self._close_assist_panel()

    def _handle_depart_confirm(self, skip_timer, skip_clicks):
        """Tick '本周不再提示' and click '立即出发' on the depart confirmation popup."""
        if self.appear(assets.MAP_DEPART_CONFIRM, offset=OFFSET):
            if not is_depart_skip_week_checked(self.device.image) and skip_clicks < 2:
                if skip_timer.reached():
                    self.device.click(_make_point_button(890, 522, 'MAP_DEPART_SKIP_WEEK', radius=8))
                    skip_clicks += 1
                    skip_timer.reset()
                return True, skip_clicks
            self.appear_then_click(assets.MAP_DEPART_CONFIRM, offset=OFFSET, interval=2)
            return True, skip_clicks
        return False, skip_clicks

    def _depart_and_wait_arrival(self, target_city, timeout=900):
        """Click MAP_DEPART, confirm popup if shown, and wait until arrival at main screen."""
        self.interval_clear((assets.MAP_DEPART, assets.MAP_DEPART_CONFIRM))
        skip_timer = Timer(1.2)
        skip_clicks = 0
        for _ in self.loop(timeout=15):
            handled, skip_clicks = self._handle_depart_confirm(skip_timer, skip_clicks)
            if handled:
                continue
            if self.appear_then_click(assets.MAP_DEPART, offset=OFFSET, interval=2):
                continue
            if self.wait_until_disappear(assets.MAP_DEPART, offset=OFFSET,
                                         skip_first_screenshot=True, timeout=1):
                if self.appear(assets.MAP_DEPART_CONFIRM, offset=OFFSET):
                    continue
                break
        else:
            raise GameStuckError('Resonance depart button did not transition into transit')

        settled = 0
        for _ in self.loop(skip_first=False, timeout=timeout):
            self.device.stuck_record_clear()
            handled, skip_clicks = self._handle_depart_confirm(skip_timer, skip_clicks)
            if handled or self.handle_reward_popup() or self.handle_operation_victory():
                settled = 0
                continue
            if self.ui_page_appear(page_main, offset=OFFSET) and self.appear(assets.MAIN_VISIT_CITY, offset=OFFSET):
                settled += 1
                if settled >= 2:
                    self.ui_current = page_main
                    return
            else:
                settled = 0
        raise GameStuckError('Resonance train did not arrive at %s' % target_city)

    def travel_to(self, target_city, use_ramming=False, configure_assist=True, timeout=900):
        """Select `target_city` on world map, configure driving assist, depart, and await arrival."""
        self.select_city_on_map(target_city)
        if configure_assist:
            self.configure_drive_assist(use_ramming=use_ramming)
        if self.appear(assets.MAP_DEPART, offset=OFFSET):
            self._depart_and_wait_arrival(target_city, timeout=timeout)
            return True
        logger.info('Resonance already at destination %s' % target_city)
        self.ui_goto_main()
        return False

    def open_current_city_exchange(self):
        """Open the current city's exchange hub via world map -> station -> MAP_EXCHANGE."""
        if self.ui_page_appear(page_resonance_map_station, offset=OFFSET):
            self.ui_ensure(page_resonance_trade_hub, skip_first_screenshot=True)
            return

        self.ui_ensure(page_resonance_world_map, skip_first_screenshot=False)
        retry = Timer(2)
        tried_center = False
        for _ in self.loop(timeout=15):
            if self.ui_page_appear(page_resonance_map_station, offset=OFFSET):
                break
            if self.ui_page_appear(page_resonance_world_map, offset=OFFSET) and retry.reached():
                cx, cy = MAP_CENTER
                if tried_center:
                    markers = detect_map_markers_05x(self.device.image)
                    if markers:
                        _, cx, cy = min(markers, key=lambda m: (m[1] - MAP_CENTER[0]) ** 2 + (m[2] - MAP_CENTER[1]) ** 2)
                else:
                    tried_center = True
                self.device.click(_make_point_button(cx, cy, 'MAP_CENTER_STATION'))
                retry.reset()
        else:
            raise GameStuckError('Resonance current city station did not open on map')
        self.ui_ensure(page_resonance_trade_hub, skip_first_screenshot=True)
