import unittest
from unittest.mock import MagicMock

import numpy as np

from module.config.server import set_server

# Bind crosscore config/assets before importing any module.crosscore.* module.
set_server('crosscore')

from module.base.utils import crop, load_image  # noqa: E402
from module.crosscore.assets import (  # noqa: E402
    ORDER_BUILD,
    ORDER_LACK,
    ORDER_NEXT,
)
from module.crosscore.base import (  # noqa: E402
    CARD_DELIVER,
    CARD_LACK,
    ORDER_BUILD_CORE,
    ORDER_GRID,
    CrosscoreBase,
)
from module.crosscore.utils import find_all, template_of  # noqa: E402


def _make_base():
    base = CrosscoreBase.__new__(CrosscoreBase)
    base.device = MagicMock()
    base.device.image = np.zeros((720, 1280, 3), dtype=np.uint8)
    base.device.click = MagicMock()
    base.device.click_record_clear = MagicMock()
    base.loop = MagicMock(side_effect=lambda timeout=10: iter(range(10)))
    base.appear = MagicMock(return_value=False)
    base.wait_until_appear = MagicMock(return_value=True)
    base.handle_item_popup = MagicMock(return_value=False)
    base.order_library_wait = MagicMock(return_value=True)
    return base


def _paint_rare_card_border(patch):
    """Recolour outer card background around ORDER_BUILD_CORE to golden 稀有."""
    cx1, cy1, cx2, cy2 = ORDER_BUILD_CORE
    out = patch.copy()
    h, w, _ = out.shape
    for y in range(h):
        t = y / max(1, h - 1)
        gold = np.array([235 - 65 * t, 210 - 60 * t, 110 - 30 * t], dtype=np.uint8)
        for x in range(w):
            if cx1 <= x < cx2 and cy1 <= y < cy2:
                continue
            out[y, x] = gold
    return out


class TestCrosscoreBaseOrders(unittest.TestCase):
    def test_order_build_points_matches_yellow_rare_card(self):
        base = _make_base()
        img = load_image('./assets/crosscore/crosscore/ORDER_BUILD.png')

        # Place a golden-yellow 稀有构建订单 card in the top-left slot while
        # keeping the original grey 构建订单 card in the bottom-right slot.
        tpl = template_of(ORDER_BUILD)
        th, tw, _ = tpl.shape
        x, y = 412, 140
        img[y:y + th, x:x + tw] = _paint_rare_card_border(tpl)
        base.device.image = img

        # Full-frame template misses the golden card because of its padding.
        full_points = find_all(img, tpl, ORDER_GRID, similarity=0.86)
        self.assertEqual(full_points, [(1092, 444)])

        # Core pass-ticket matching finds both yellow rare and regular cards.
        core_points = base.order_build_points()
        self.assertEqual(core_points, [(412, 140), (1092, 444)])

        # Smoke check on ORDER_SOLD.png: non-build cards must not false-match.
        base.device.image = load_image('./assets/crosscore/crosscore/ORDER_SOLD.png')
        self.assertLessEqual(len(base.order_build_points()), 1)

    def test_order_friends_crafts_more_than_two_lacked_orders(self):
        base = _make_base()
        base.friend_list_enter = MagicMock(return_value=True)
        # 3 friends then back to own library (ORDER_NEXT disappears on 4th scan).
        friend_idx = {'i': 0}

        def fake_scan(can_craft=True):
            # Friend libraries 0, 1, 2 each need 1 craft before returning 'empty'.
            if not getattr(base, '_crafted_here', False):
                base._crafted_here = True
                return 'lacked'
            base._crafted_here = False
            return 'empty'

        def fake_craft_missing():
            return 'ok'

        def fake_appear(btn, offset=(0, 0), interval=0):
            if btn is ORDER_NEXT:
                friend_idx['i'] += 1
                return friend_idx['i'] <= 3
            return False

        base._crafted_here = False
        base.order_scan = MagicMock(side_effect=fake_scan)
        base.craft_missing = MagicMock(side_effect=fake_craft_missing)
        base.appear = MagicMock(side_effect=fake_appear)

        base.order_friends(crafts=16, can_craft=True)
        self.assertEqual(base.craft_missing.call_count, 3)

    def test_order_friends_short_craft_disables_further_crafting(self):
        base = _make_base()
        base.friend_list_enter = MagicMock(return_value=True)

        # Friend 1 runs craft_missing -> 'short'; Friend 2 still scans with
        # can_craft=False so ready cards there can still be delivered without
        # retrying crafting or aborting the friend walk.
        seen_can_craft = []
        friend_idx = {'i': 0}

        def fake_scan(can_craft=True):
            seen_can_craft.append(can_craft)
            if len(seen_can_craft) == 1:
                return 'lacked'
            return 'empty'

        def fake_appear(btn, offset=(0, 0), interval=0):
            if btn is ORDER_NEXT:
                friend_idx['i'] += 1
                return friend_idx['i'] <= 2
            return False

        base.order_scan = MagicMock(side_effect=fake_scan)
        base.craft_missing = MagicMock(return_value='short')
        base.appear = MagicMock(side_effect=fake_appear)

        base.order_friends(crafts=16, can_craft=True)
        # Scans: friend 1 (True -> short), friend 1 rescan (False), friend 2 (False), own (False).
        self.assertEqual(seen_can_craft, [True, False, False, False])
        self.assertEqual(base.craft_missing.call_count, 1)

    def test_craft_missing_returns_short_when_stock_stays_low(self):
        base = _make_base()
        base.pending_need = 6
        base.read_number = MagicMock(side_effect=[0, 2])
        base.read_short_number = MagicMock(side_effect=[0, 0])
        base.craft_item = MagicMock(return_value=True)
        base.craft_back = MagicMock(return_value=True)

        self.assertEqual(base.craft_missing(), 'short')

        # craft_back failure must escalate to 'abort'.
        base.read_number = MagicMock(side_effect=[0])
        base.read_short_number = MagicMock(side_effect=[0, 0])
        base.craft_back = MagicMock(return_value=False)
        self.assertEqual(base.craft_missing(), 'abort')

    def test_order_scan_delivers_ready_card_before_lacked_card(self):
        base = _make_base()
        base.order_confirm = MagicMock(return_value=True)
        base.read_number = MagicMock(return_value=6)

        img = load_image('./assets/crosscore/crosscore/ORDER_BUILD.png')
        tpl = template_of(ORDER_BUILD)
        th, tw, _ = tpl.shape
        # Put a golden 稀有 构建订单 at top-left (412, 140) and mark it 资源暂缺.
        x_rare, y_rare = 412, 140
        img[y_rare:y_rare + th, x_rare:x_rare + tw] = _paint_rare_card_border(tpl)
        lack_tpl = template_of(ORDER_LACK)
        lh, lw, _ = lack_tpl.shape
        lx1, ly1, _, _ = base.card_area(CARD_LACK, x_rare, y_rare)
        img[ly1 + 10:ly1 + 10 + lh, lx1 + 10:lx1 + 10 + lw] = lack_tpl

        # Put a second, deliverable grey 构建订单 at (752, 444) by copying (1092, 444)
        # or simply leaving (1092, 444) from ORDER_BUILD.png as the ready card.
        base.device.image = img

        # On scan with can_craft=True, ready card at (1092, 444) is delivered
        # first; once delivered, the second iteration hits lacked card (412, 140).
        self.assertEqual(base.order_scan(can_craft=True), 'lacked')
        base.device.click.assert_called_once()
        clicked_btn = base.device.click.call_args[0][0]
        self.assertEqual(clicked_btn.area, base.card_area(CARD_DELIVER, 1092, 444))
        self.assertEqual(base.pending_need, 6)

        # With can_craft=False, the ready card is delivered and lacked is skipped.
        base.device.click.reset_mock()
        self.assertEqual(base.order_scan(can_craft=False), 'empty')
        base.device.click.assert_called_once()


if __name__ == '__main__':
    unittest.main()
