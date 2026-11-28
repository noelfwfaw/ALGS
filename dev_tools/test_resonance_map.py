import os
import unittest
from itertools import count
from unittest.mock import Mock, call, patch

import numpy as np

from module.base.utils import load_image
from module.config import server

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ARCHIVE_DIR = os.path.join(_REPO_ROOT, 'screenshots', 'resonance')

# Regions of the live 雷索纳斯 transit screens (1280x720), measured on the
# archived frames. The 「D」 region is deliberately narrow: the live gear cluster
# puts the red 「B」 badge at x 1187-1198 / y 629-647, so a wide selector also
# accepted a press on 「B」 as a press on 「D」.
GUARD_REGION = (880, 180, 1150, 320)   # the 「护卫队迎击」 wedge of the encounter wheel
WHEEL_REGION = (815, 186, 1206, 576)   # the whole encounter wheel
DRIVE_REGION = (1228, 597, 1265, 635)  # the 「D」 glyph only (live glyph: x 1243-1251, y 608-623)
B_REGION = (1180, 622, 1206, 655)      # the red 「B」 badge (live glyph: x 1187-1198, y 629-647)
RETURN_REGION = (550, 100, 730, 160)   # 「立即返航」
DECOY_REGION = (880, 440, 1140, 580)   # 「诱饵气球」
LEGACY_DRIVE_REGION = (1150, 570, 1280, 680)  # the earlier too-wide selector, kept as evidence


def _archived(name):
    """Return the archived resonance screenshot, or None when it is not archived here."""
    path = os.path.join(_ARCHIVE_DIR, name)
    if not os.path.exists(path):
        return None
    return load_image(path)


def _blank_with(*buttons):
    canvas = np.zeros((720, 1280, 3), dtype=np.uint8)
    for btn in buttons:
        x1, y1, x2, y2 = btn.area
        canvas[y1:y2, x1:x2] = load_image(btn.file, btn.area)
    return canvas


def _click_center(target):
    """Return the click centre of a Button / bbox target, or None."""
    bbox = getattr(target, 'button', None)
    if bbox is None and isinstance(target, (tuple, list)) and len(target) >= 4:
        bbox = tuple(target[:4])
    if not isinstance(bbox, (tuple, list)) or len(bbox) < 4:
        return None
    x1, y1, x2, y2 = bbox[:4]
    return ((x1 + x2) // 2, (y1 + y2) // 2)


def _dark_glyph_boxes(image, region, min_area=8):
    """Return the boxes of the small dark glyph components inside `region`."""
    import cv2

    x1, y1, x2, y2 = region
    gray = image[y1:y2, x1:x2].max(axis=2)
    mask = (gray < 120).astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    boxes = []
    for index in range(1, count):
        x, y, width, height, area = stats[index]
        if area < min_area or width > 30 or height > 40:
            continue
        boxes.append((int(x + x1), int(y + y1), int(x + x1 + width), int(y + y1 + height)))
    return boxes


def _box_inside(box, region):
    return (region[0] <= box[0] and region[1] <= box[1]
            and box[2] <= region[2] and box[3] <= region[3])


def _box_overlaps(box, region):
    return not (box[2] <= region[0] or region[2] <= box[0]
                or box[3] <= region[1] or region[3] <= box[1])


def _inside(center, box):
    if center is None:
        return False
    return box[0] <= center[0] <= box[2] and box[1] <= center[1] <= box[3]


def _click_kind(target):
    """Classify a click as a known transit action."""
    name = getattr(target, 'name', None)
    if name in ('OP_NEXT', 'OP_BACK', 'LOGIN_REWARD', 'MAP_DEPART'):
        return name
    center = _click_center(target)
    if center is None:
        return None
    if _inside(center, DRIVE_REGION):
        return 'D'
    if _inside(center, B_REGION):
        return 'B'
    if _inside(center, GUARD_REGION):
        return 'GUARD'
    return None


class _TransitFeed:
    """Scripted transit screen feed.

    A state advances when the script clicks one of the state's triggers (an asset
    name such as 'OP_NEXT' or a screen region such as 'GUARD' / 'D'), or when the
    state was shown more than `hold` times without a reaction.
    """

    def __init__(self, states):
        self.states = list(states)
        self.index = 0
        self.shown = 0
        self.clicks = []

    @property
    def frame(self):
        return self.states[self.index]['frame']

    def screenshot(self):
        self.shown += 1
        if self.shown > self.states[self.index].get('hold', 6):
            self.shown = 1
            self.index = min(self.index + 1, len(self.states) - 1)
        return self.frame

    def click(self, target):
        self.clicks.append(_click_center(target))
        kind = _click_kind(target)
        triggers = self.states[self.index].get('advance_on') or ()
        if kind is not None and kind in triggers:
            self.shown = 0
            self.index = min(self.index + 1, len(self.states) - 1)


def _assist_frame(assets, states):
    img = (
        load_image(assets.MAP_ASSIST_PANEL.file)
        + load_image(assets.MAP_EXCHANGE.file)
        + load_image(assets.MAP_DRIVE_ASSIST.file)
        + load_image(assets.MAP_DEPART.file)
    )
    from module.resonance.map_nav import ASSIST_TOGGLES
    for (_, area), is_on in zip(ASSIST_TOGGLES, states):
        if is_on:
            x1, y1, x2, y2 = area
            img[y1 + 5:y2 - 5, x1 + (x2 - x1) // 2 + 4:x2 - 4] = (245, 245, 245)
    return img


class TestResonanceMap(unittest.TestCase):
    def setUp(self):
        self.addCleanup(server.set_server, server.server)
        server.set_server('resonance')

    def test_wilderness_partition_requires_confirmed_crossing_only(self):
        from module.resonance.map_nav import (
            MAP_COORDS_05X, WILDERNESS_CITY, WILDERNESS_EAST_CITIES, route_passes_wilderness,
        )

        west = '阿妮塔发射中心'
        self.assertEqual(WILDERNESS_EAST_CITIES, {'云岫桥基地', '栖羽站', '岚心城'})
        self.assertTrue(WILDERNESS_EAST_CITIES <= set(MAP_COORDS_05X))
        for east in WILDERNESS_EAST_CITIES:
            with self.subTest(east=east):
                self.assertTrue(route_passes_wilderness(west, east))
                self.assertTrue(route_passes_wilderness(east, west))
                self.assertFalse(route_passes_wilderness(east, east))
                self.assertFalse(route_passes_wilderness(WILDERNESS_CITY, east))
                self.assertFalse(route_passes_wilderness(west, WILDERNESS_CITY))
        self.assertFalse(route_passes_wilderness('修格里城', '曼德矿场'))
        self.assertFalse(route_passes_wilderness('云岫桥基地', '岚心城'))
        self.assertFalse(route_passes_wilderness(west, '未知站'))
        self.assertFalse(route_passes_wilderness('', east))

    def test_constellation_localization_and_aliases(self):
        from module.resonance.map_nav import (
            ASSIST_TOGGLES, MAP_COORDS_05X, canonical_city_name, get_zoom_thumb_y,
            is_assist_toggle_on, is_zoomed_out_min, localize_map_origin,
        )

        self.assertEqual(canonical_city_name('7号自由港'), '七号自由港')
        self.assertEqual(canonical_city_name(' 阿妮塔能源研究所 '), '阿妮塔能源研究所')

        ox, oy = 639, 364
        detected = [
            (MAP_COORDS_05X[c][0], ox + MAP_COORDS_05X[c][1], oy + MAP_COORDS_05X[c][2])
            for c in ('修格里城', '铁盟哨站', '曼德矿场', '澄明数据中心', '七号自由港')
        ]
        # Add noise blobs that should be rejected by consensus
        detected.extend([('blue', 100, 100), ('cyan', 950, 500)])
        loc = localize_map_origin(detected)
        self.assertIsNotNone(loc)
        inliers, rx, ry, matched = loc
        self.assertEqual(inliers, 5)
        self.assertEqual((rx, ry), (ox, oy))
        self.assertEqual(set(matched), {'修格里城', '铁盟哨站', '曼德矿场', '澄明数据中心', '七号自由港'})

        zoom_img = np.zeros((720, 1280, 3), dtype=np.uint8)
        zoom_img[551:570, 1141:1165] = (240, 240, 240)
        self.assertEqual(get_zoom_thumb_y(zoom_img), 551)
        self.assertTrue(is_zoomed_out_min(zoom_img))
        zoom_img[551:570, :] = 0
        zoom_img[456:475, 1141:1165] = (240, 240, 240)
        self.assertFalse(is_zoomed_out_min(zoom_img))

        from module.resonance import assets
        assist = _assist_frame(assets, (True, False, False, True))
        self.assertEqual([is_assist_toggle_on(assist, area) for _, area in ASSIST_TOGGLES], [True, False, False, True])

    def test_configure_drive_assist_enforces_three_on_and_configurable_ramming(self):
        from module.resonance import assets
        from module.resonance.map_nav import ResonanceMapNav

        station = load_image(assets.MAP_EXCHANGE.file) + load_image(assets.MAP_DRIVE_ASSIST.file) + load_image(assets.MAP_DEPART.file)

        # use_ramming=False: turns on auto_rush (index 1) and leaves auto_ram (index 2) OFF
        nav = ResonanceMapNav.__new__(ResonanceMapNav)
        nav.device = Mock()
        nav.device.image = station
        nav.interval_timer = {}
        f0 = _assist_frame(assets, (True, False, False, True))
        f1 = _assist_frame(assets, (True, True, False, True))
        frames = iter([f0, f0, f1, station])
        nav.device.screenshot.side_effect = lambda: setattr(nav.device, 'image', next(frames))
        with patch('module.base.timer.time', side_effect=count(100, 0.6)):
            nav.configure_drive_assist(use_ramming=False)

        clicked = [c[0][0].name for c in nav.device.click.call_args_list]
        self.assertEqual(clicked, ['MAP_DRIVE_ASSIST', 'ASSIST_auto_rush', 'MAP_DRIVE_ASSIST'])

        # use_ramming=True: turns on both auto_rush and auto_ram
        nav2 = ResonanceMapNav.__new__(ResonanceMapNav)
        nav2.device = Mock()
        nav2.device.image = station
        nav2.interval_timer = {}
        g0 = _assist_frame(assets, (True, False, False, True))
        g1 = _assist_frame(assets, (True, True, False, True))
        g2 = _assist_frame(assets, (True, True, True, True))
        frames2 = iter([g0, g0, g1, g1, g2, station])
        nav2.device.screenshot.side_effect = lambda: setattr(nav2.device, 'image', next(frames2))
        with patch('module.base.timer.time', side_effect=count(100, 0.6)):
            nav2.configure_drive_assist(use_ramming=True)

        clicked2 = [c[0][0].name for c in nav2.device.click.call_args_list]
        self.assertEqual(clicked2, ['MAP_DRIVE_ASSIST', 'ASSIST_auto_rush', 'ASSIST_auto_ram', 'MAP_DRIVE_ASSIST'])

    def test_select_city_drags_then_clicks_and_verifies_header_and_travels(self):
        from module.resonance import assets
        from module.resonance.map_nav import MAP_COORDS_05X, ResonanceMapNav, STATION_NAME_OCR

        map_frame = load_image(assets.MAP_ZOOM_PLUS.file) + load_image(assets.MAP_ZOOM_MINUS.file)
        map_frame[551:570, 1141:1165] = (240, 240, 240)
        station = load_image(assets.MAP_EXCHANGE.file) + load_image(assets.MAP_DRIVE_ASSIST.file) + load_image(assets.MAP_DEPART.file)
        transit = np.zeros((720, 1280, 3), dtype=np.uint8)
        main = load_image(assets.MAIN_CHECK.file) + load_image(assets.MAIN_VISIT_CITY.file)

        nav = ResonanceMapNav.__new__(ResonanceMapNav)
        nav.device = Mock()
        nav.device.image = map_frame
        nav.interval_timer = {}
        nav.ui_ensure = Mock()
        nav.configure_drive_assist = Mock()

        # Frame 1: origin at (200, 360) -> 岚心城 is at (200+983, 360-224) = (1183, 136) -> drags!
        # Frame 2 (wait_until_still consumes 2 frames): origin shifted to (-220, 360) -> clicks!
        # Frame 3 (wait_until_appear): station screen opens -> STATION_NAME_OCR reads '岚心城'
        # Depart -> transit (wait_until_disappear) -> transit -> main (2 settle frames)
        loc_far = (5, 200, 360, ['修格里城'])
        loc_near = (5, -220, 360, ['岚心城'])
        frames = iter([map_frame, map_frame, station, transit, transit, main, main])
        nav.device.screenshot.side_effect = lambda: setattr(nav.device, 'image', next(frames))
        nav._wait_map_markers_still = Mock(side_effect=lambda *a, **kw: (setattr(nav.device, 'image', next(frames)), True)[1])

        with patch('module.base.timer.time', side_effect=count(100, 0.6)), \
                patch('module.resonance.map_nav.detect_map_markers_05x', return_value=[('gold', 200, 360)]), \
                patch('module.resonance.map_nav.localize_map_origin', side_effect=[loc_far, loc_near]), \
                patch.object(STATION_NAME_OCR, 'ocr', return_value='岚心城'):
            arrived = nav.travel_to('岚心城', use_ramming=False)

        self.assertTrue(arrived)
        nav.device.drag.assert_called_once()
        tx, ty = -220 + MAP_COORDS_05X['岚心城'][1], 360 + MAP_COORDS_05X['岚心城'][2]
        self.assertEqual(nav.device.click.call_args_list[0][0][0].name, 'MAP_CITY_岚心城')
        self.assertEqual(nav.device.click.call_args_list[0][0][0].button, (tx - 10, ty - 10, tx + 10, ty + 10))
        self.assertEqual(nav.device.click.call_args_list[1], call(assets.MAP_DEPART))
        nav.configure_drive_assist.assert_called_once_with(use_ramming=False)
        self.assertTrue(nav.device.stuck_record_clear.called)

    def test_open_current_city_exchange_via_world_map(self):
        from module.resonance import assets
        from module.resonance.map_nav import MAP_CENTER, ResonanceMapNav
        from module.resonance.page import page_resonance_trade_hub

        map_frame = load_image(assets.MAP_ZOOM_PLUS.file)
        station = load_image(assets.MAP_EXCHANGE.file)
        nav = ResonanceMapNav.__new__(ResonanceMapNav)
        nav.device = Mock()
        nav.device.image = map_frame
        nav.interval_timer = {}
        nav.ui_ensure = Mock()

        frames = iter([station])
        nav.device.screenshot.side_effect = lambda: setattr(nav.device, 'image', next(frames))
        with patch('module.base.timer.time', side_effect=count(100, 0.6)):
            nav.open_current_city_exchange()

        self.assertEqual(nav.device.click.call_args_list[0][0][0].name, 'MAP_CENTER_STATION')
        cx, cy = MAP_CENTER
        self.assertEqual(nav.device.click.call_args_list[0][0][0].button, (cx - 10, cy - 10, cx + 10, cy + 10))
        self.assertEqual(nav.ui_ensure.call_args_list[-1], call(page_resonance_trade_hub, skip_first_screenshot=True))

    def test_depart_confirm_ticks_skip_week_and_confirms(self):
        from module.resonance import assets
        from module.resonance.map_nav import DEPART_SKIP_WEEK_INNER, ResonanceMapNav, is_depart_skip_week_checked

        station = load_image(assets.MAP_DEPART.file)
        popup_unchecked = load_image(assets.MAP_DEPART_CONFIRM.file)
        popup_checked = popup_unchecked.copy()
        x1, y1, x2, y2 = DEPART_SKIP_WEEK_INNER
        popup_checked[y1 + 2:y2 - 2, x1 + 2:x2 - 2] = (240, 240, 240)
        transit = np.zeros((720, 1280, 3), dtype=np.uint8)
        main = load_image(assets.MAIN_CHECK.file) + load_image(assets.MAIN_VISIT_CITY.file)

        self.assertFalse(is_depart_skip_week_checked(popup_unchecked))
        self.assertTrue(is_depart_skip_week_checked(popup_checked))

        nav = ResonanceMapNav.__new__(ResonanceMapNav)
        nav.device = Mock()
        nav.device.image = station
        nav.interval_timer = {}

        frames = iter([popup_unchecked, popup_checked, transit, main, main])
        nav.device.screenshot.side_effect = lambda: setattr(nav.device, 'image', next(frames))
        with patch('module.base.timer.time', side_effect=count(100, 1.5)):
            nav._depart_and_wait_arrival('阿妮塔发射中心', timeout=30)

        clicked = [c[0][0].name for c in nav.device.click.call_args_list]
        self.assertEqual(clicked, ['MAP_DEPART', 'MAP_DEPART_SKIP_WEEK', 'MAP_DEPART_CONFIRM'])

    def test_localize_map_transform_scaled_and_snap(self):
        from module.resonance.map_nav import localize_map_origin, localize_map_transform, snap_to_detected_marker

        # Exact live markers captured at slight ~1.03x zoom before full 0.5x settle
        scaled_markers = [
            ('gold', 212, 122), ('gold', 212, 131), ('gold', 714, 285), ('gold', 370, 420),
            ('cyan', 1037, 100), ('cyan', 448, 143), ('cyan', 890, 213), ('cyan', 249, 421),
            ('red', 613, 283),
        ]
        self.assertIsNone(localize_map_origin(scaled_markers, tol=5))
        res = localize_map_transform(scaled_markers)
        self.assertIsNotNone(res)
        inliers, _, _, scale, matched = res
        self.assertGreaterEqual(inliers, 7)
        self.assertAlmostEqual(scale, 1.03, delta=0.02)
        self.assertIn('海角城', matched)

        # Snap prefers nearby matching color within 25px, ignores wrong color or far markers
        self.assertEqual(snap_to_detected_marker(705, 290, 'gold', scaled_markers), (714, 285))
        self.assertEqual(snap_to_detected_marker(610, 280, 'gold', scaled_markers), (610, 280))
        self.assertEqual(snap_to_detected_marker(100, 100, 'gold', scaled_markers), (100, 100))

    def test_bright_sky_main_recognition_and_transit_timeout(self):
        import inspect
        import os
        from module.resonance import assets
        from module.resonance.map_nav import ResonanceMapNav
        from module.resonance.page import page_main
        from module.resonance.profile import ResonanceProfile
        from module.resonance.resonance_ui import ResonanceUI

        self.assertGreaterEqual(inspect.signature(ResonanceMapNav._depart_and_wait_arrival).parameters['timeout'].default, 900)
        self.assertGreaterEqual(inspect.signature(ResonanceMapNav.travel_to).parameters['timeout'].default, 900)
        self.assertGreaterEqual(inspect.signature(ResonanceProfile.wait_until_docked).parameters['timeout'].default, 900)

        station = load_image(assets.MAP_DEPART.file)
        transit = np.zeros((720, 1280, 3), dtype=np.uint8)
        bright_main = load_image(assets.MAIN_TERMINAL.file) + load_image(assets.MAIN_VISIT_CITY.file)

        nav = ResonanceMapNav.__new__(ResonanceMapNav)
        nav.device = Mock()
        nav.device.image = station
        nav.interval_timer = {}
        frames = iter([transit, bright_main, bright_main])
        nav.device.screenshot.side_effect = lambda: setattr(nav.device, 'image', next(frames))
        with patch('module.base.timer.time', side_effect=count(100, 1.5)):
            nav._depart_and_wait_arrival('曼德矿场', timeout=30)
        self.assertIs(nav.ui_current, page_main)

        err_img_path = 'log/error/1795656060699/2026-11-26_09-21-00-661210.png'
        if os.path.exists(err_img_path):
            err_img = load_image(err_img_path)
            ui = ResonanceUI.__new__(ResonanceUI)
            ui.device = Mock()
            ui.interval_timer = {}
            ui.device.image = err_img
            self.assertIs(ui.ui_get_current_page(skip_first_screenshot=True), page_main)

            nav2 = ResonanceMapNav.__new__(ResonanceMapNav)
            nav2.device = Mock()
            nav2.device.image = station
            nav2.interval_timer = {}
            f2 = iter([transit, err_img, err_img])
            nav2.device.screenshot.side_effect = lambda: setattr(nav2.device, 'image', next(f2))
            with patch('module.base.timer.time', side_effect=count(100, 1.5)):
                nav2._depart_and_wait_arrival('曼德矿场', timeout=30)
            self.assertIs(nav2.ui_current, page_main)

            prof = ResonanceProfile.__new__(ResonanceProfile)
            prof.device = Mock()
            prof.device.image = transit
            prof.interval_timer = {}
            f3 = iter([err_img, err_img])
            prof.device.screenshot.side_effect = lambda: setattr(prof.device, 'image', next(f3))
            with patch('module.base.timer.time', side_effect=count(100, 1.5)):
                prof.wait_until_docked(timeout=30)
            self.assertIs(prof.ui_current, page_main)

    def _run_transit(self, feed, first_frame, timeout=60):
        """Drive the public wait_until_docked entry against a scripted screen feed."""
        from module.resonance.profile import ResonanceProfile

        prof = ResonanceProfile.__new__(ResonanceProfile)
        prof.device = Mock()
        prof.device.image = first_frame
        prof.interval_timer = {}

        def _screenshot():
            prof.device.image = feed.screenshot()
            return prof.device.image

        def _click(target):
            feed.click(target)
            prof.device.image = feed.frame

        prof.device.screenshot.side_effect = _screenshot
        prof.device.click.side_effect = _click
        with patch('module.base.timer.time', side_effect=count(100, 1.5)):
            prof.wait_until_docked(timeout=timeout)
        return prof

    def test_guard_encounter_then_parked_state_resumes_drive(self):
        """Restart lands on a transit guard encounter: counter it, then resume the drive at the stop."""
        from module.resonance import assets
        from module.resonance.page import page_main

        encounter = _archived('transit_guard_encounter_20261128.png')
        parked = _archived('transit_parked_20261128.png')
        if encounter is None or parked is None:
            self.skipTest('archived resonance screenshots are not available in this worktree')

        driving = np.zeros((720, 1280, 3), dtype=np.uint8)
        battle = _blank_with(assets.OP_PAUSE, assets.OP_AUTO_ON)
        victory = _blank_with(assets.OP_WIN, assets.OP_NEXT)
        reward = _blank_with(assets.LOGIN_REWARD)
        main = load_image(assets.MAIN_CHECK.file) + load_image(assets.MAIN_VISIT_CITY.file)

        feed = _TransitFeed([
            {'frame': encounter, 'hold': 8, 'advance_on': ('GUARD',)},
            {'frame': battle, 'hold': 3},
            {'frame': victory, 'hold': 6, 'advance_on': ('OP_NEXT',)},
            {'frame': reward, 'hold': 4, 'advance_on': ('LOGIN_REWARD',)},
            {'frame': parked, 'hold': 10, 'advance_on': ('D',)},
            {'frame': driving, 'hold': 3},
            {'frame': main, 'hold': 99},
        ])

        prof = self._run_transit(feed, encounter)

        self.assertIs(prof.ui_current, page_main)
        guard_clicks = [c for c in feed.clicks if _inside(c, WHEEL_REGION)]
        self.assertEqual(len(guard_clicks), 1, 'the guard encounter option must be selected exactly once')
        self.assertTrue(_inside(guard_clicks[0], GUARD_REGION), 'the 「护卫队迎击」 option must be selected')
        drive_clicks = [c for c in feed.clicks if _inside(c, DRIVE_REGION)]
        self.assertEqual(len(drive_clicks), 1, 'the 「D」 must be clicked exactly once, clicks=%r' % (feed.clicks,))
        self.assertFalse(
            [c for c in feed.clicks if _inside(c, B_REGION)],
            'the red 「B」 badge must never be pressed, clicks=%r' % (feed.clicks,),
        )
        self.assertLess(
            feed.clicks.index(guard_clicks[0]), feed.clicks.index(drive_clicks[0]),
            'the D may only be clicked after the counterattack',
        )
        self.assertFalse(
            [c for c in feed.clicks if _inside(c, RETURN_REGION)],
            '「立即返航」 must never be clicked',
        )
        self.assertFalse(
            [c for c in feed.clicks if _inside(c, DECOY_REGION)],
            'the 「诱饵气球」 option must not be selected',
        )

    def test_travel_to_resumes_drive_after_guard_encounter(self):
        """The journey entry must survive a guard encounter and resume the drive at the stop."""
        from module.resonance import assets
        from module.resonance.map_nav import ResonanceMapNav

        encounter = _archived('transit_guard_encounter_20261128.png')
        parked = _archived('transit_parked_20261128.png')
        if encounter is None or parked is None:
            self.skipTest('archived resonance screenshots are not available in this worktree')

        station = load_image(assets.MAP_DEPART.file)
        battle = _blank_with(assets.OP_PAUSE, assets.OP_AUTO_ON)
        victory = _blank_with(assets.OP_WIN, assets.OP_NEXT)
        reward = _blank_with(assets.LOGIN_REWARD)
        driving = np.zeros((720, 1280, 3), dtype=np.uint8)
        main = load_image(assets.MAIN_CHECK.file) + load_image(assets.MAIN_VISIT_CITY.file)

        feed = _TransitFeed([
            {'frame': station, 'hold': 4, 'advance_on': ('MAP_DEPART',)},
            {'frame': encounter, 'hold': 8, 'advance_on': ('GUARD',)},
            {'frame': battle, 'hold': 3},
            {'frame': victory, 'hold': 6, 'advance_on': ('OP_NEXT',)},
            {'frame': reward, 'hold': 4, 'advance_on': ('LOGIN_REWARD',)},
            {'frame': parked, 'hold': 10, 'advance_on': ('D',)},
            {'frame': driving, 'hold': 3},
            {'frame': main, 'hold': 99},
        ])

        nav = ResonanceMapNav.__new__(ResonanceMapNav)
        nav.device = Mock()
        nav.device.image = station
        nav.interval_timer = {}
        nav.ui_ensure = Mock()
        nav.select_city_on_map = Mock()
        nav.configure_drive_assist = Mock()

        def _screenshot():
            nav.device.image = feed.screenshot()
            return nav.device.image

        def _click(target):
            feed.click(target)
            nav.device.image = feed.frame

        nav.device.screenshot.side_effect = _screenshot
        nav.device.click.side_effect = _click

        with patch('module.base.timer.time', side_effect=count(100, 0.6)):
            arrived = nav.travel_to('岚心城', use_ramming=False)

        self.assertTrue(arrived)
        guard_clicks = [c for c in feed.clicks if _inside(c, WHEEL_REGION)]
        self.assertEqual(len(guard_clicks), 1, 'the guard encounter option must be selected exactly once')
        self.assertTrue(_inside(guard_clicks[0], GUARD_REGION), 'the 「护卫队迎击」 option must be selected')
        drive_clicks = [c for c in feed.clicks if _inside(c, DRIVE_REGION)]
        self.assertEqual(len(drive_clicks), 1, 'the 「D」 must be clicked exactly once, clicks=%r' % (feed.clicks,))
        self.assertFalse(
            [c for c in feed.clicks if _inside(c, B_REGION)],
            'the red 「B」 badge must never be pressed, clicks=%r' % (feed.clicks,),
        )
        self.assertLess(
            feed.clicks.index(guard_clicks[0]), feed.clicks.index(drive_clicks[0]),
            'the D may only be clicked after the counterattack',
        )
        self.assertFalse(
            [c for c in feed.clicks if _inside(c, RETURN_REGION)],
            '「立即返航」 must never be clicked',
        )

    def test_arrival_screen_never_clicks_guard_or_drive(self):
        """On the arrival screen nothing may be clicked, neither the wheel nor the drive selector."""
        from module.resonance import assets
        from module.resonance.page import page_main

        main = load_image(assets.MAIN_CHECK.file) + load_image(assets.MAIN_VISIT_CITY.file)
        feed = _TransitFeed([{'frame': main, 'hold': 99}])

        prof = self._run_transit(feed, main)

        self.assertIs(prof.ui_current, page_main)
        self.assertEqual(feed.clicks, [], 'nothing may be clicked on the arrival screen')

    def test_transit_without_encounter_never_clicks_guard_or_drive(self):
        """A plain transit run without an encounter must not pick an option nor press the D."""
        from module.resonance import assets
        from module.resonance.page import page_main

        driving = np.zeros((720, 1280, 3), dtype=np.uint8)
        main = load_image(assets.MAIN_CHECK.file) + load_image(assets.MAIN_VISIT_CITY.file)

        feed = _TransitFeed([
            {'frame': driving, 'hold': 4},
            {'frame': main, 'hold': 99},
        ])

        prof = self._run_transit(feed, driving)

        self.assertIs(prof.ui_current, page_main)
        self.assertFalse(
            [c for c in feed.clicks if _inside(c, WHEEL_REGION)],
            'no encounter option may be selected without an encounter',
        )
        self.assertFalse(
            [c for c in feed.clicks if _inside(c, DRIVE_REGION)],
            'the D must not be clicked while the transit is still running',
        )

    def test_archived_gear_cluster_keeps_the_d_apart_from_the_red_b(self):
        """The live gear cluster must place the 「D」 where the narrow selector expects it.

        The wide selector used by the first version of this file also covered the
        red 「B」 badge, so a press on 「B」 could pass as a press on 「D」.
        """
        parked = _archived('transit_parked_20261128.png')
        if parked is None:
            self.skipTest('archived resonance screenshots are not available in this worktree')

        boxes = _dark_glyph_boxes(parked, (1150, 560, 1280, 720))
        d_boxes = [box for box in boxes if _box_inside(box, DRIVE_REGION)]
        self.assertEqual(len(d_boxes), 1, 'the live 「D」 glyph must sit inside the D region, boxes=%r' % (boxes,))
        b_boxes = [box for box in boxes if _box_inside(box, B_REGION)]
        self.assertEqual(len(b_boxes), 1, 'the live red 「B」 badge must sit inside the B region, boxes=%r' % (boxes,))
        for box in b_boxes:
            self.assertFalse(
                _box_overlaps(box, DRIVE_REGION),
                'the 「B」 badge must not overlap the 「D」 region, box=%r' % (box,),
            )
            self.assertTrue(
                _box_inside(box, LEGACY_DRIVE_REGION),
                'the previous wide region used to swallow the 「B」 badge, box=%r' % (box,),
            )

    def test_parked_frame_without_destination_never_presses_the_d(self):
        """A stopped cab whose destination line is gone must not be resumed."""
        from module.resonance import assets
        from module.resonance.page import page_main

        parked = _archived('transit_parked_20261128.png')
        if parked is None:
            self.skipTest('archived resonance screenshots are not available in this worktree')

        no_destination = parked.copy()
        no_destination[24:52, 590:720] = 0
        main = load_image(assets.MAIN_CHECK.file) + load_image(assets.MAIN_VISIT_CITY.file)

        feed = _TransitFeed([
            {'frame': no_destination, 'hold': 12},
            {'frame': main, 'hold': 99},
        ])

        prof = self._run_transit(feed, no_destination)

        self.assertIs(prof.ui_current, page_main)
        self.assertFalse(
            [c for c in feed.clicks if _inside(c, DRIVE_REGION)],
            'the 「D」 must not be pressed while the destination is unknown, clicks=%r' % (feed.clicks,),
        )
        self.assertFalse(
            [c for c in feed.clicks if _inside(c, B_REGION)],
            'the red 「B」 badge must never be pressed, clicks=%r' % (feed.clicks,),
        )
