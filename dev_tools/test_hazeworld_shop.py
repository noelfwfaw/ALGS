import unittest
from unittest.mock import Mock

import numpy as np

from module.hazeworld.shop_base import HazeworldShopBase
from module.hazeworld.shop_grid import SHOP_COLUMN_PITCH, SHOP_DRAG_RETRY


def _make_shop_task(purchases, screens):
    task = HazeworldShopBase.__new__(HazeworldShopBase)
    task.device = Mock()
    task.device.image = np.zeros((720, 1280, 3), dtype=np.uint8)
    task.config = Mock()
    task.config.HazeworldShop_Filter = '自定义'
    task.config.HazeworldShop_Purchases = purchases
    task.CONFIG_TASK = 'HazeworldShop'
    task.shop_filter_init()

    task.pos = 0
    task.drag_deltas = []
    task.screens = screens

    def fake_drag_moved(before, delta):
        task.drag_deltas.append(delta)
        if delta < 0:
            if task.pos == 0:
                return False
            task.pos = max(0, task.pos - 3)
            return True
        if task.pos < len(task.screens) - 1:
            task.pos += 1
            return True
        return False

    task.shop_drag_moved = fake_drag_moved
    task.shop_cards = lambda: [card for col in task.screens[task.pos] for card in col[1:] if card is not None]
    task.shop_columns = lambda cards: task.screens[task.pos]
    task.shop_goods_diff = lambda before: 50.0
    task.shop_sold_out = Mock(return_value=True)
    task.shop_price = Mock(return_value=100)
    task.shop_balance = Mock(return_value=99999)
    return task


def _col(x, top_name, bot_name=None):
    top = (0, x, x + 220, top_name, top_name) if top_name else None
    bot = (1, x, x + 220, bot_name, bot_name) if bot_name else None
    return [x, top, bot]


class TestHazeworldShop(unittest.TestCase):
    def test_linear_walk_no_rewinds_and_adaptive_stride(self):
        # First screen has 3 columns -> steps by 2*272; second screen has 2 columns -> steps by 272
        screens = [
            [_col(308, 'A', 'B'), _col(580, 'C', 'D'), _col(852, 'E', 'F')],
            [_col(362, 'G', 'H'), _col(634, 'I', 'J')],
            [_col(656, 'Target', None)],
        ]
        task = _make_shop_task('Target', screens)
        task.shop_sold_out = lambda card: card[3] != 'Target'

        card, reached_end, moved = task.shop_find(0, at_start=True)
        self.assertIsNotNone(card)
        self.assertEqual(card[3], 'Target')
        self.assertFalse(reached_end)
        self.assertTrue(moved)
        self.assertEqual(task.drag_deltas, [SHOP_COLUMN_PITCH * 2, SHOP_COLUMN_PITCH])

    def test_clamped_stagnation_stops_immediately(self):
        screens = [
            [_col(308, 'A', 'B'), _col(580, 'C', 'D'), _col(852, 'E', 'F')],
            [_col(656, 'Tail', None)],
        ]
        task = _make_shop_task('Missing', screens)
        # Simulate clamped end: drag_moved says True once with tiny diff (< SHOP_STEP_MIN_DIFF)
        diffs = iter([50.0, 4.5])
        task.shop_drag_moved = lambda before, delta: (task.drag_deltas.append(delta) or True)
        task.shop_goods_diff = lambda before: next(diffs)

        card, reached_end, moved = task.shop_find(0, at_start=True)
        self.assertIsNone(card)
        self.assertTrue(reached_end)
        self.assertTrue(moved)
        self.assertEqual(len(task.drag_deltas), 2)

    def test_sold_out_multi_rule_sweep_does_single_pass(self):
        screens = [
            [_col(308, '原始核心碎片', '绝密报告'), _col(580, '核心芯片', '精英演习券'), _col(852, '自选水晶', None)],
            [_col(362, '盾币', '蜜桃'), _col(634, '尴尬邂逅', None)],
            [_col(656, '亚特兰蒂斯', None)],
        ]
        task = _make_shop_task('原始核心碎片\n绝密报告\n核心芯片\n自选水晶\n亚特兰蒂斯', screens)
        task.shop_buy_card = Mock()

        out_of_money = task.shop_sweep()
        self.assertFalse(out_of_money)
        task.shop_buy_card.assert_not_called()
        # Single forward pass across 3 screens -> 0 negative rewind drags!
        self.assertTrue(all(d > 0 for d in task.drag_deltas))
        self.assertEqual(
            task.drag_deltas,
            [SHOP_COLUMN_PITCH * 2, SHOP_COLUMN_PITCH] + [SHOP_COLUMN_PITCH] * SHOP_DRAG_RETRY,
        )

    def test_sweep_skips_empty_ranks_and_buys_in_priority_order(self):
        # Ranks: 0='Wanted0', 1='Wanted1' (sold out), 2='Wanted2' (buyable on screen 1)
        screens = [
            [_col(308, 'Wanted0', 'Other'), _col(580, 'Wanted1', None), _col(852, 'Filler', None)],
            [_col(656, 'Wanted2', None)],
        ]
        stock = {'Wanted0': True, 'Wanted1': False, 'Wanted2': True}
        task = _make_shop_task('Wanted0\nWanted1\nWanted2', screens)
        task.shop_sold_out = lambda card: not stock.get(card[3], False)
        bought = []

        def fake_buy(card):
            bought.append(card[3])
            stock[card[3]] = False
            task.pos = 0
            return 'bought'

        task.shop_buy_card = fake_buy
        out_of_money = task.shop_sweep()
        self.assertFalse(out_of_money)
        self.assertEqual(bought, ['Wanted0', 'Wanted2'])
        # Rank 0 bought on screen 0; then 1 forward sweep hits Wanted2; final sweep ends without re-scanning Wanted1!
        self.assertEqual(task.drag_deltas.count(-SHOP_COLUMN_PITCH * 3), 1)

    def test_scroll_home_stops_after_two_clamped_drags(self):
        task = HazeworldShopBase.__new__(HazeworldShopBase)
        task.wait_until_still = Mock(return_value=True)
        task.shop_goods_image = Mock(return_value=np.zeros((10, 10, 3), dtype=np.int16))
        calls = iter([True, False, False, True])
        task.shop_drag_moved = Mock(side_effect=lambda before, delta: next(calls))

        self.assertTrue(task.shop_scroll_home())
        self.assertEqual(task.shop_drag_moved.call_count, 3)
