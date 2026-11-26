import unittest
from itertools import count
from unittest.mock import Mock, call, patch

import numpy as np

from module.base.utils import load_image
from module.config import server


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
