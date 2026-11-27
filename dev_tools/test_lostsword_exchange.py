import os
import unittest
from unittest.mock import MagicMock

import cv2
import numpy as np

from module.config import server

_IMPORT_SERVER = server.server
try:
    server.set_server('lostsword')
    from module.lostsword.exchange import EXCHANGE_SUBTABS, LostswordExchange  # noqa: E402
finally:
    server.set_server(_IMPORT_SERVER)


def _make_exchange():
    ex = LostswordExchange()
    ex.device = MagicMock()
    ex.device.image = np.zeros((720, 1280, 3), dtype=np.uint8)
    ex.device.click = MagicMock()
    ex.device.screenshot = MagicMock(side_effect=lambda: ex.device.image)
    ex.appear = MagicMock(return_value=False)
    ex.wait_until_still = MagicMock(return_value=True)
    return ex


def _load_rgb_1280(path):
    bgr = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if bgr.shape[:2] != (720, 1280):
        bgr = cv2.resize(bgr, (1280, 720), interpolation=cv2.INTER_CUBIC)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


class TestLostswordExchange(unittest.TestCase):
    def setUp(self):
        self.addCleanup(server.set_server, server.server)
        server.set_server('lostsword')

    def test_real_top_sidebar_locates_shifted_fixed_tabs(self):
        p = os.environ.get('LOSTSWORD_EXCHANGE_TOP_IMAGE')
        if not p or not os.path.isfile(p):
            self.skipTest('Set LOSTSWORD_EXCHANGE_TOP_IMAGE to the top-sidebar screenshot')
        top_img = _load_rgb_1280(p)

        expected_cy = {
            'consumable': 184,
            'raid': 276,
            'guild': 460,
            'arena': 552,
        }
        for key, cy in expected_cy.items():
            label, default_area, _ = EXCHANGE_SUBTABS[key]
            located = LostswordExchange.exchange_locate_fixed_tab(top_img, label, default_area)
            self.assertEqual(located, (80, cy - 22, 240, cy + 22), label)

        self.assertEqual(LostswordExchange.exchange_find_event_tabs(top_img), [])

    def test_real_bottom_sidebar_finds_both_reindeer_and_pumpkin(self):
        p = os.environ.get('LOSTSWORD_EXCHANGE_BOTTOM_IMAGE')
        if not p or not os.path.isfile(p):
            self.skipTest('Set LOSTSWORD_EXCHANGE_BOTTOM_IMAGE to the bottom-sidebar screenshot')
        bot_img = _load_rgb_1280(p)

        tabs = LostswordExchange.exchange_find_event_tabs(bot_img)
        self.assertEqual(
            tabs,
            [
                ('驯鹿币', (80, 479, 240, 523)),
                ('南瓜币', (80, 571, 240, 615)),
            ],
        )

        ex = _make_exchange()
        ex.device.image = bot_img
        cards = ex.exchange_scan_screen()
        self.assertEqual(len(cards), 6)

    def test_exchange_run_event_sweeps_all_event_tabs(self):
        ex = _make_exchange()
        area1 = (80, 479, 240, 523)
        area2 = (80, 571, 240, 615)
        ex.exchange_sidebar_bottom = MagicMock()
        ex.exchange_find_event_tabs = MagicMock(return_value=[('驯鹿币', area1), ('南瓜币', area2)])
        ex.exchange_select_slot = MagicMock(return_value=True)
        ex.exchange_sweep = MagicMock(side_effect=[3, 2])

        bought = ex.exchange_run_event('!初级经验书10个 > 全部')
        self.assertEqual(bought, 5)
        ex.exchange_sidebar_bottom.assert_called_once_with()
        self.assertEqual(
            [c[0] for c in ex.exchange_select_slot.call_args_list],
            [('驯鹿币', area1), ('南瓜币', area2)],
        )
        self.assertEqual(
            [c[0][0] for c in ex.exchange_sweep.call_args_list],
            ['活动·驯鹿币', '活动·南瓜币'],
        )

    def test_exchange_run_event_skips_when_no_event_tabs(self):
        ex = _make_exchange()
        ex.exchange_sidebar_bottom = MagicMock()
        ex.exchange_find_event_tabs = MagicMock(return_value=[])
        ex.exchange_select_slot = MagicMock()
        ex.exchange_sweep = MagicMock()

        bought = ex.exchange_run_event('!初级经验书10个 > 全部')
        self.assertEqual(bought, 0)
        ex.exchange_sidebar_bottom.assert_called_once_with()
        ex.exchange_select_slot.assert_not_called()
        ex.exchange_sweep.assert_not_called()


if __name__ == '__main__':
    unittest.main()
