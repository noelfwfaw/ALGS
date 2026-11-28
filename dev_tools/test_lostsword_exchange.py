import os
import unittest
from unittest.mock import MagicMock

import cv2
import numpy as np

from module.config import server
from module.exception import TaskFailed

_IMPORT_SERVER = server.server
try:
    server.set_server('lostsword')
    from module.lostsword.assets import (  # noqa: E402
        REWARD_POPUP_TITLE,
        SHOP_DIALOG_TITLE,
        SHOP_EXCHANGE_BUY,
        SHOP_LACK_CONFIRM,
        SHOP_TITLE,
    )
    from module.lostsword.exchange import (EXCHANGE_DIALOG_COST_AREA,  # noqa: E402
                                           EXCHANGE_SUBTABS,
                                           LostswordExchange)
    from module.lostsword.exchange_filter import (exchange_is_event_ticket,  # noqa: E402
                                                   exchange_keyword_hit,
                                                   exchange_norm,
                                                   exchange_parse_filter)
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
    ex.config = MagicMock()
    ex.loop = MagicMock(side_effect=lambda *args, **kwargs: iter(range(4)))
    return ex


def _card(title, row):
    return {
        'title': title,
        'norm': title,
        'rank': 1,
        'page': 0,
        'row': row,
        'x1': 360 + row * 210,
        'x2': 500 + row * 210,
        'tap_y': 285,
    }


def _page(*titles):
    return {(0, title) for title in titles}


# ---- scripted shelf used by the adversarial exchange regressions -------------

# The two wanted items, in filter order: the high priority one first, the low
# priority one eight cards further to the right.
_EXCHANGE_HIGH_ITEM = '驯鹿票券'
_EXCHANGE_LOW_ITEM = '初级经验书'
_EXCHANGE_FILTER = '驯鹿票券 > 初级经验书'
_EXCHANGE_EVENT_TAB = ('驯鹿币', (80, 479, 240, 523))
# The shelf shows two rows of cards and scrolls sideways; a drag of
# EXCHANGE_STEP_PX moves two columns, so consecutive views overlap.
_EXCHANGE_SHELF_WIDTH = 4
_EXCHANGE_SHELF_STEP = 2
# A bounded sweep over the scripted shelf never needs this many drags.
_EXCHANGE_MAX_DRAGS = 60
_EXCHANGE_SHELF_TITLES = [
    '驯鹿币袋', '南瓜币袋', '活动代币', '轮盘券',
    '稀有灵魂', '金币宝箱', '驯鹿票券', '精炼石',
    '时间卷轴', '公会勋章', '神秘石', '单次突袭门票',
    '初级经验书', '领主召唤券：巨石阵',
]


def _fake_card(title, row, column):
    """One scripted shelf card; the row belongs to the card, not to its slot."""
    return {
        'title': title,
        'norm': exchange_norm(title),
        'row': row,
        'x1': 300 + column % 4 * 296,
        'x2': 560 + column % 4 * 296,
        'tap_y': 285 if row == 0 else 573,
        'sold_out': False,
        'paid': False,
    }


class _FakeShelf:
    """
    Scripted shelf that replaces the screen layer of the exchange sweep.

    The cards live in one flat list (row 0 and row 1 alternating) and are
    rendered as overlapping views, the way the real shelf shows two rows while
    the list scrolls sideways. `exchange_collect_all` and `exchange_seek_card`
    stay untouched, so the sweep still has to find the wanted cards itself.
    """

    def __init__(self, cards):
        self.cards = list(cards)
        self.index = 0
        self.drags = 0
        self.forwards = 0
        self.backs = 0
        self.on_end = None
        self._ended = False

    def views(self):
        return [
            self.cards[i:i + _EXCHANGE_SHELF_WIDTH]
            for i in range(0, len(self.cards) - _EXCHANGE_SHELF_WIDTH + 1, _EXCHANGE_SHELF_STEP)
        ]

    def current(self):
        """The cards on screen right now."""
        views = self.views()
        index = min(self.index, len(views) - 1)
        return [dict(card) for card in views[index]]

    def drag(self, delta_x):
        """Move one view; a shelf that cannot move further reports no change."""
        if delta_x > 0:
            if self.index + 1 >= len(self.views()):
                if self.on_end is not None and not self._ended:
                    self._ended = True
                    self.on_end()
                return False
            self.index += 1
            self.forwards += 1
        else:
            if self.index <= 0:
                return False
            self.index -= 1
            self.backs += 1
        self.drags += 1
        return True

    def drop_first(self):
        """The shop re-rendered its list: every card drifts against the index."""
        self.cards = self.cards[1:] + [_fake_card('强化结晶', 0, 0)]

    def remove(self, title):
        """A bought card leaves the shelf and the rest drifts behind it."""
        self.cards = [card for card in self.cards if card['title'] != title]
        self.cards.append(_fake_card('强化结晶', 0, 0))

    def flip_rows(self):
        """The shop re-rendered the rows, so no card keeps its old anchor."""
        for card in self.cards:
            card['row'] = 1 - card['row']


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

    def test_lack_confirm_retries_after_swallowed_click(self):
        ex = _make_exchange()
        ex.wait_overlay_settle = MagicMock(return_value=True)
        ex.wait_overlay_gone = MagicMock(side_effect=[False, True])
        ex.appear = MagicMock(return_value=True)

        self.assertTrue(ex.exchange_dismiss_lack())
        self.assertEqual(ex.device.click.call_count, 2)
        purchase = SHOP_EXCHANGE_BUY.button
        self.assertEqual(purchase, (560, 592, 720, 632))
        for call in ex.device.click.call_args_list:
            self.assertIs(call[0][0], SHOP_LACK_CONFIRM)
            x1, y1, x2, y2 = call[0][0].button
            self.assertTrue(560 <= x1 < x2 <= 720)
            self.assertTrue(450 <= y1 < y2 <= 492)
            self.assertFalse(
                max(x1, purchase[0]) < min(x2, purchase[2])
                and max(y1, purchase[1]) < min(y2, purchase[3])
            )

    def test_permanent_lack_popup_fails_without_closing_purchase_dialog(self):
        ex = _make_exchange()
        ex.wait_overlay_settle = MagicMock(return_value=True)
        ex.wait_overlay_gone = MagicMock(return_value=False)
        ex.appear = MagicMock(side_effect=lambda button, **kwargs: button in (SHOP_DIALOG_TITLE, SHOP_LACK_CONFIRM))
        ex.exchange_close_dialog = MagicMock()

        with self.assertRaises(TaskFailed):
            ex.exchange_buy_card(_card('resource test', 0))
        ex.config.task_delay.assert_called_once_with(success=False)
        ex.exchange_close_dialog.assert_not_called()
        self.assertEqual(ex.device.click.call_count, 4)

    def test_outer_close_failure_aborts_sweep_before_next_card(self):
        ex = _make_exchange()
        cards = [_card('first', 0), _card('second', 1)]
        ex.exchange_collect_all = MagicMock(return_value=(cards, [_page('first', 'second')]))
        ex.exchange_seek_card = MagicMock(return_value=(cards[0], 0))
        ex.wait_overlay_settle = MagicMock(return_value=True)
        ex.exchange_dismiss_lack = MagicMock(return_value=True)
        ex.exchange_close_dialog = MagicMock(return_value=False)
        ex.appear = MagicMock(side_effect=lambda button, **kwargs: button in (SHOP_DIALOG_TITLE, SHOP_LACK_CONFIRM))

        with self.assertRaises(TaskFailed):
            ex.exchange_sweep('fixed', ['wanted'], [])
        ex.config.task_delay.assert_called_once_with(success=False)
        ex.exchange_seek_card.assert_called_once()
        self.assertEqual(ex.exchange_seek_card.call_args[0][0], cards[0])
        self.assertEqual(ex.device.click.call_count, 1)

    def test_normal_exchange_closes_reward_then_verifies_shelf(self):
        ex = _make_exchange()
        ex.wait_overlay_settle = MagicMock(return_value=True)
        ex.appear = MagicMock(side_effect=lambda button, **kwargs: button in (SHOP_DIALOG_TITLE, REWARD_POPUP_TITLE))
        ex.handle_reward_popup = MagicMock(return_value=True)
        ex.exchange_close_dialog = MagicMock(return_value=True)

        self.assertEqual(ex.exchange_buy_card(_card('normal', 0)), 'bought')
        ex.handle_reward_popup.assert_called_once_with()
        ex.exchange_close_dialog.assert_called_once_with(timeout=6)

    def test_close_dialog_waits_until_shelf_is_visible(self):
        ex = _make_exchange()
        visible = iter([True, True, False, True])
        ex.appear = MagicMock(side_effect=lambda button, **kwargs: next(visible))
        ex.shop_close_dialog = MagicMock(side_effect=[False, True])
        ex.wait_overlay_gone = MagicMock(return_value=True)

        self.assertTrue(ex.exchange_close_dialog())
        self.assertEqual(ex.shop_close_dialog.call_count, 2)
        ex.wait_overlay_gone.assert_called_once_with(SHOP_DIALOG_TITLE, timeout=6)

    def test_insufficient_item_does_not_stop_later_exchange(self):
        ex = _make_exchange()
        cards = [_card('lacking', 0), _card('normal', 1)]
        ex.exchange_collect_all = MagicMock(return_value=(cards, [_page('lacking', 'normal')]))
        ex.exchange_seek_card = MagicMock(side_effect=[(cards[0], 0), (cards[1], 0)])
        ex.exchange_buy_card = MagicMock(side_effect=['insufficient', 'bought'])

        self.assertEqual(ex.exchange_sweep('fixed', ['wanted'], []), 1)
        self.assertEqual(ex.exchange_buy_card.call_count, 2)

    def test_collect_does_not_create_a_page_when_drag_fails(self):
        ex = _make_exchange()
        ex.exchange_scroll_home = MagicMock()
        ex.exchange_scan_screen = MagicMock(return_value=[_card('stable', 0)])
        ex.exchange_drag_shelf = MagicMock(return_value=False)

        items, pages = ex.exchange_collect_all([(0, '')], [])
        self.assertEqual([c['page'] for c in items], [0])
        self.assertEqual(pages, [_page('stable')])
        ex.exchange_drag_shelf.assert_called_once_with(592)

    def test_collect_stops_at_scan_cap_without_extra_drag(self):
        ex = _make_exchange()
        ex.exchange_scroll_home = MagicMock()
        ex.exchange_scan_screen = MagicMock(
            side_effect=[[_card('stable%d' % i, 0)] for i in range(8)]
        )
        ex.exchange_drag_shelf = MagicMock(return_value=True)

        _, pages = ex.exchange_collect_all([(0, '')], [])
        self.assertEqual(len(pages), 8)
        self.assertEqual(ex.exchange_drag_shelf.call_count, 7)

    def test_collect_stops_when_shelf_view_does_not_change(self):
        ex = _make_exchange()
        ex.exchange_scroll_home = MagicMock()
        ex.exchange_scan_screen = MagicMock(return_value=[_card('stable', 0)])
        ex.exchange_drag_shelf = MagicMock(return_value=True)

        _, pages = ex.exchange_collect_all([(0, '')], [])
        self.assertEqual(pages, [_page('stable')])
        ex.exchange_drag_shelf.assert_called_once_with(592)

    def test_seek_failed_movement_keeps_the_verified_page(self):
        ex = _make_exchange()
        target = _card('目标', 0)
        target['page'] = 2
        pages = [_page('第一屏'), _page('第二屏'), _page('目标')]
        ex.exchange_scan_screen = MagicMock(return_value=[_card('第一屏', 0)])
        ex.exchange_drag_shelf = MagicMock(return_value=False)
        ex.exchange_scroll_home = MagicMock()

        self.assertEqual(ex.exchange_seek_card(target, pages, 0), (None, 0))
        ex.exchange_drag_shelf.assert_called_once_with(592)
        ex.exchange_scroll_home.assert_not_called()

    def test_seek_stops_when_anchors_stay_on_the_same_page(self):
        ex = _make_exchange()
        target = _card('目标', 0)
        target['page'] = 2
        pages = [_page('第一屏'), _page('第二屏'), _page('目标')]
        ex.exchange_scan_screen = MagicMock(return_value=[_card('第一屏', 0)])
        ex.exchange_drag_shelf = MagicMock(return_value=True)
        ex.exchange_scroll_home = MagicMock()

        self.assertEqual(ex.exchange_seek_card(target, pages, 0), (None, 0))
        ex.exchange_drag_shelf.assert_called_once_with(592)

    def test_seek_uses_live_anchors_after_popup_instead_of_assuming_home(self):
        for current, target_page, step in ((0, 1, 592), (1, 2, 592), (2, 1, -592)):
            with self.subTest(current=current, target_page=target_page):
                ex = _make_exchange()
                target = _card('目标', 0)
                target['page'] = target_page
                pages = [_page('第一屏'), _page('第二屏'), _page('第三屏')]
                pages[target_page] = _page('目标')
                names = ('第一屏', '第二屏', '第三屏')
                ex.exchange_scan_screen = MagicMock(side_effect=[
                    [_card(names[current], 0)],
                    [_card('目标', 0)],
                ])
                ex.exchange_drag_shelf = MagicMock(return_value=True)
                ex.exchange_scroll_home = MagicMock()

                live, position = ex.exchange_seek_card(target, pages, None)
                self.assertEqual((live['title'], position), ('目标', target_page))
                ex.exchange_drag_shelf.assert_called_once_with(step)
                ex.exchange_scroll_home.assert_not_called()

    def test_missing_targets_share_one_rescan_and_later_item_is_bought(self):
        ex = _make_exchange()
        missing = [_card('missing1', 0), _card('missing2', 0), _card('missing3', 0)]
        available = _card('available', 0)
        pages = [_page('missing1', 'missing2', 'missing3')]
        ex.exchange_collect_all = MagicMock(side_effect=[(missing, pages), ([available], pages)])
        ex.exchange_seek_card = MagicMock(side_effect=[(None, None)] * 3 + [(available, 0)])
        ex.exchange_buy_card = MagicMock(return_value='bought')

        self.assertEqual(ex.exchange_sweep('event', ['wanted'], []), 1)
        self.assertEqual(ex.exchange_collect_all.call_count, 2)
        self.assertEqual(ex.exchange_seek_card.call_count, 4)
        ex.exchange_buy_card.assert_called_once_with(available)

    def test_rescan_buys_high_priority_before_low_priority(self):
        ex = _make_exchange()
        high = _card('驯鹿票券', 0)
        high['rank'] = 1
        low = _card('初级经验书', 0)
        low['rank'] = 2
        pages = [_page('驯鹿票券', '初级经验书')]
        ex.exchange_collect_all = MagicMock(side_effect=[([high, low], pages), ([high, low], pages)])
        missed = {'high': False}

        def _seek(target, seek_pages, current_page):
            if target['title'] == '驯鹿票券' and not missed['high']:
                missed['high'] = True
                return None, None
            return target, 0

        ex.exchange_seek_card = MagicMock(side_effect=_seek)
        ex.exchange_buy_card = MagicMock(return_value='bought')

        self.assertEqual(ex.exchange_sweep('event', ['wanted'], []), 2)
        self.assertEqual(ex.exchange_collect_all.call_count, 2)
        self.assertEqual(
            [call[0][0]['title'] for call in ex.exchange_buy_card.call_args_list],
            ['驯鹿票券', '初级经验书'],
        )

    def test_rescan_skips_high_priority_that_stays_missing(self):
        ex = _make_exchange()
        high = _card('驯鹿票券', 0)
        high['rank'] = 1
        low = _card('初级经验书', 0)
        low['rank'] = 2
        pages = [_page('驯鹿票券', '初级经验书')]
        ex.exchange_collect_all = MagicMock(side_effect=[([high, low], pages), ([low], pages)])

        def _seek(target, seek_pages, current_page):
            if target['title'] == '驯鹿票券':
                return None, None
            return target, 0

        ex.exchange_seek_card = MagicMock(side_effect=_seek)
        ex.exchange_buy_card = MagicMock(return_value='bought')

        self.assertEqual(ex.exchange_sweep('event', ['wanted'], []), 1)
        self.assertEqual(ex.exchange_collect_all.call_count, 2)
        ex.exchange_buy_card.assert_called_once_with(low)

    def test_sweep_forgets_page_number_after_each_purchase(self):
        ex = _make_exchange()
        cards = [_card('first', 0), _card('second', 0)]
        pages = [_page('first'), _page('second')]
        ex.exchange_collect_all = MagicMock(return_value=(cards, pages))
        ex.exchange_seek_card = MagicMock(side_effect=[(cards[0], 0), (cards[1], 1)])
        ex.exchange_buy_card = MagicMock(return_value='bought')

        self.assertEqual(ex.exchange_sweep('fixed', ['wanted'], []), 2)
        self.assertIsNone(ex.exchange_seek_card.call_args_list[1][0][2])

    def test_real_event_frames_keep_gold_ticket_and_sold_out_distinct(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        expected = (
            ('抽取宠物召唤券', '宠物召唤券', '稀有灵魂'),
            ('稀有级礼物盒', '时间卷轴', '领主召唤券：巨石阵', '精炼石'),
            ('经验值宝箱', '神秘石', '金币宝箱'),
            ('驯鹿票券', '单人突袭门票', '轮盘券'),
        )
        for index, titles in enumerate(expected, 1):
            with self.subTest(frame=index):
                path = os.path.join(root, 'screenshots', 'lostsword', 'exchange_event_reindeer_%02d.png' % index)
                if not os.path.isfile(path):
                    self.skipTest('The archived event frames are not available')
                ex = _make_exchange()
                ex.device.image = _load_rgb_1280(path)
                cards = ex.exchange_scan_screen(include_all=True)
                for title in titles:
                    self.assertTrue(any(exchange_keyword_hit(title, c['title']) for c in cards), title)
                if index == 4:
                    ticket = next(c for c in cards if exchange_keyword_hit('驯鹿票券', c['title']))
                    sold = next(c for c in cards if exchange_keyword_hit('抽取角色召唤券', c['title']))
                    self.assertFalse(ticket['paid'])
                    self.assertFalse(ticket['sold_out'])
                    self.assertFalse(sold['paid'])
                    self.assertTrue(sold['sold_out'])

    def test_real_event_frame_keeps_both_event_coin_labels(self):
        """The archived original frame must expose both event currency tabs."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, 'screenshots', 'lostsword', 'exchange_event_single_purchase_20261128.png')
        if not os.path.isfile(path):
            self.skipTest('The archived event frame is not available')
        img = _load_rgb_1280(path)

        self.assertEqual(
            LostswordExchange.exchange_find_event_tabs(img),
            [('驯鹿币', (80, 479, 240, 523)), ('南瓜币', (80, 571, 240, 615))],
        )

        ex = _make_exchange()
        ex.device.image = img
        cards = ex.exchange_scan_screen(include_all=True)
        self.assertGreaterEqual(len(cards), 6)
        for title in ('抽取宠物召唤券', '宠物召唤券', '角色召唤券', '稀有灵魂', '传说级礼物盒'):
            self.assertTrue(any(exchange_keyword_hit(title, card['title']) for card in cards), title)

    def test_real_event_balance_and_card_prices(self):
        """Archived event screenshots yield exact coin balances and unit prices."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        checks = (
            ('exchange_event_reindeer_01.png', 11310, [75, 75, 50, 150, 1500, 300]),
            ('exchange_event_single_purchase_20261128.png', 10310, [75, 75, 50, 150, 1500, 300]),
        )
        for filename, expected_bal, expected_prices in checks:
            path = os.path.join(root, 'screenshots', 'lostsword', filename)
            if not os.path.isfile(path):
                self.skipTest(f'{filename} is not available')
            img = _load_rgb_1280(path)
            self.assertEqual(LostswordExchange.exchange_read_event_balance(img), expected_bal)
            if expected_prices is not None:
                ex = _make_exchange()
                ex.device.image = img
                cards = ex.exchange_scan_screen(include_all=True)
                self.assertEqual([c['price'] for c in cards], expected_prices)

    def test_real_event_ticket_gold_detection_and_keyword_hit(self):
        """Archived event frames identify only gold-priced tickets (`*票券`)."""
        self.assertTrue(exchange_keyword_hit('票券', '驯鹿票券'))
        self.assertTrue(exchange_keyword_hit('票券', '南瓜票券'))
        for other in ('单人突袭门票', '轮盘券', '角色召唤券', '词条转换券'):
            self.assertFalse(exchange_keyword_hit('票券', other), other)

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for idx in range(1, 5):
            path = os.path.join(root, 'screenshots', 'lostsword', f'exchange_event_reindeer_0{idx}.png')
            if not os.path.isfile(path):
                self.skipTest(f'exchange_event_reindeer_0{idx}.png is not available')
            ex = _make_exchange()
            ex.device.image = _load_rgb_1280(path)
            for c in ex.exchange_scan_screen(include_all=True):
                is_ticket = exchange_keyword_hit('驯鹿票券', c['title'])
                self.assertEqual(c['gold'], is_ticket, c['title'])
                self.assertEqual(exchange_is_event_ticket(c), is_ticket, c['title'])

    def test_single_pass_event_sweep_skips_unaffordable_and_zero_balance(self):
        """Zero balance still buys gold tickets and skips event-coin items cleanly."""
        includes, excludes = exchange_parse_filter('!排除项 > 全部')

        ex_ticket = _make_exchange()
        ex_ticket.exchange_read_event_balance = MagicMock(return_value=0)
        ex_ticket.exchange_scroll_home = MagicMock()
        ex_ticket.exchange_drag_shelf = MagicMock(side_effect=[True, False])
        ex_ticket.exchange_buy_card = MagicMock(return_value='bought')
        p0 = [dict(_card('角色召唤券', 0), price=150, gold=False)]
        p1 = [dict(_card('驯鹿票券', 0), price=50000, gold=True)]
        ex_ticket.exchange_scan_screen = MagicMock(side_effect=[p0, p1, p1])
        self.assertEqual(ex_ticket.exchange_sweep('活动·驯鹿币', includes, excludes, single_currency=True), 1)
        self.assertEqual(
            [c[0][0]['title'] for c in ex_ticket.exchange_buy_card.call_args_list],
            ['驯鹿票券'],
        )
        ex_ticket.exchange_scroll_home.assert_called_once_with()

        ex_zero = _make_exchange()
        ex_zero.exchange_read_event_balance = MagicMock(return_value=0)
        ex_zero.exchange_scroll_home = MagicMock()
        ex_zero.exchange_drag_shelf = MagicMock(return_value=False)
        ex_zero.exchange_scan_screen = MagicMock(return_value=[dict(_card('角色召唤券', 0), price=150, gold=False)])
        ex_zero.exchange_buy_card = MagicMock()
        self.assertEqual(ex_zero.exchange_sweep('活动·驯鹿币', includes, excludes, single_currency=True), 0)
        ex_zero.exchange_buy_card.assert_not_called()

        ex_low = _make_exchange()
        ex_low.exchange_read_event_balance = MagicMock(return_value=35)
        ex_low.exchange_scroll_home = MagicMock()
        ex_low.exchange_drag_shelf = MagicMock(side_effect=[True, False])
        ex_low.exchange_buy_card = MagicMock()
        page0 = [
            dict(_card('角色召唤券', 0), price=150, gold=False),
            dict(_card('宠物召唤券', 1), price=75, gold=False),
            dict(_card('灵魂', 1), price=50, gold=False),
        ]
        page1 = [dict(_card('词条转换券', 0), price=300, gold=False)]
        ex_low.exchange_scan_screen = MagicMock(side_effect=[page0, page1])

        self.assertEqual(ex_low.exchange_sweep('活动·驯鹿币', includes, excludes, single_currency=True), 0)
        ex_low.exchange_buy_card.assert_not_called()
        self.assertEqual(
            [c[0][0] for c in ex_low.exchange_drag_shelf.call_args_list],
            [592, 592],
        )

    def test_event_sweep_buys_gold_ticket_before_event_coin_items(self):
        """Single-pass event sweep buys gold ticket first, then event-coin items; `!票券` excludes it."""
        includes, excludes = exchange_parse_filter('!初级经验书10个 > 全部')
        ex = _make_exchange()
        balances = iter([150, 0])
        ex.exchange_read_event_balance = MagicMock(side_effect=lambda img: next(balances))
        ex.exchange_scroll_home = MagicMock()
        ex.exchange_drag_shelf = MagicMock(side_effect=[True, False])
        ex.exchange_buy_card = MagicMock(return_value='bought')

        page0 = [dict(_card('角色召唤券', 0), price=150, gold=False)]
        page1 = [dict(_card('驯鹿票券', 0), price=50000, gold=True)]
        ex.exchange_scan_screen = MagicMock(side_effect=[page0, page1, page1, page0])

        bought = ex.exchange_sweep('活动·驯鹿币', includes, excludes, single_currency=True)
        self.assertEqual(bought, 2)
        self.assertEqual(
            [c[0][0]['title'] for c in ex.exchange_buy_card.call_args_list],
            ['驯鹿票券', '角色召唤券'],
        )

        inc_ex, exc_ex = exchange_parse_filter('!票券 > 全部')
        ex_skip = _make_exchange()
        bal_skip = iter([150, 0])
        ex_skip.exchange_read_event_balance = MagicMock(side_effect=lambda img: next(bal_skip))
        ex_skip.exchange_scroll_home = MagicMock()
        ex_skip.exchange_drag_shelf = MagicMock(side_effect=[True, False])
        ex_skip.exchange_buy_card = MagicMock(return_value='bought')
        ex_skip.exchange_scan_screen = MagicMock(side_effect=[page0, page1, page0])

        bought_skip = ex_skip.exchange_sweep('活动·驯鹿币', inc_ex, exc_ex, single_currency=True)
        self.assertEqual(bought_skip, 1)
        self.assertEqual(
            [c[0][0]['title'] for c in ex_skip.exchange_buy_card.call_args_list],
            ['角色召唤券'],
        )

    def test_multi_priority_event_sweep_buys_gold_ticket_at_zero_balance(self):
        """Multi-priority event sweep buys matching gold tickets even at 0 event coins."""
        includes, excludes = exchange_parse_filter('稀有灵魂 > 全部')
        ex = _make_exchange()
        ex.exchange_read_event_balance = MagicMock(return_value=0)
        ex.exchange_scroll_home = MagicMock()
        ex.exchange_drag_shelf = MagicMock(side_effect=[True, False])
        ex.exchange_buy_card = MagicMock(return_value='bought')

        page0 = [dict(_card('稀有灵魂', 0), price=1500, gold=False)]
        page1 = [dict(_card('驯鹿票券', 0), price=50000, gold=True)]
        ex.exchange_scan_screen = MagicMock(side_effect=[page0, page1, page1])

        bought = ex.exchange_sweep('活动·驯鹿币', includes, excludes, single_currency=True)
        self.assertEqual(bought, 1)
        self.assertEqual(
            [c[0][0]['title'] for c in ex.exchange_buy_card.call_args_list],
            ['驯鹿票券'],
        )

    def test_single_pass_tightens_budget_on_insufficient_and_handles_reflow(self):
        """Insufficient warning tightens budget cap and reflowed affordable cards are bought in place."""
        includes, excludes = exchange_parse_filter('全部')
        ex = _make_exchange()
        ex.exchange_read_event_balance = MagicMock(return_value=None)
        ex.exchange_scroll_home = MagicMock()
        ex.exchange_drag_shelf = MagicMock(return_value=False)

        c_short = dict(_card('词条转换券', 0), price=300)
        c_expensive = dict(_card('宝石箱', 0), price=500)
        c_cheap = dict(_card('强化石', 1), price=75)
        c_cheap_reflowed = dict(_card('强化石', 0), price=75)
        # First scan sees cheap at row 1 (sorted after x1=360); after buying/reflow it sits at row 0.
        c_cheap['x1'] = 600
        c_cheap_reflowed['x1'] = 600

        ex.exchange_scan_screen = MagicMock(side_effect=[
            [c_short, c_expensive, c_cheap],
            [c_short, c_expensive, c_cheap_reflowed],
            [c_short, c_expensive],
        ])
        ex.exchange_buy_card = MagicMock(side_effect=['insufficient', 'bought'])

        bought = ex.exchange_sweep('活动·驯鹿币', includes, excludes, single_currency=True)
        self.assertEqual(bought, 1)
        self.assertEqual(
            [c[0][0]['title'] for c in ex.exchange_buy_card.call_args_list],
            ['词条转换券', '强化石'],
        )

    def test_seek_card_matches_reflowed_row_without_dragging(self):
        """Seek must accept a target card that shifted from row 0 to row 1 without dragging."""
        ex = _make_exchange()
        target = _card('角色召唤券', 0)
        target['page'] = 0
        moved = _card('角色召唤券', 1)
        ex.exchange_scan_screen = MagicMock(return_value=[moved])
        ex.exchange_drag_shelf = MagicMock()

        live, page = ex.exchange_seek_card(target, [_page('角色召唤券')], 0)
        self.assertIs(live, moved)
        self.assertEqual(page, 0)
        ex.exchange_drag_shelf.assert_not_called()


class TestLostswordExchangeShelfDrift(unittest.TestCase):
    """
    Adversarial regressions for the event exchange sweep.

    The screen is replaced by a scripted shelf, but `exchange_collect_all`,
    `exchange_seek_card` and `exchange_sweep` stay real, so the sweep still
    has to find the wanted cards on its own. The fixture walks the sweep
    through the two hard states of the contract:

    1. the shop re-rendered its list right after the scan, so the indexed
       anchors stopped matching and the first item could only be located
       again through the shared rescan - which is then spent for good;
    2. after that first purchase the shelf drifts again (the live view
       matches two indexed pages equally, or none at all) while the second
       wanted item is still on the shelf, but no longer on screen.

    The low priority item sits eight cards behind the high priority one, so it
    can only be bought by dragging further to the right, and the number of
    drags has to stay bounded.
    """

    def setUp(self):
        self.addCleanup(server.set_server, server.server)
        server.set_server('lostsword')

    def _shelf(self):
        return [_fake_card(title, index % 2, index)
                for index, title in enumerate(_EXCHANGE_SHELF_TITLES)]

    def _run(self, entry, after_purchase):
        shelf = _FakeShelf(self._shelf())
        ex = _make_exchange()

        # The shop re-rendered its list right after the scan: the indexed
        # anchors stop matching and the first item is only reachable through
        # the shared rescan.
        shelf.on_end = shelf.drop_first

        bought = []
        live = []

        def _buy(card):
            bought.append(card['title'])
            if len(bought) == 1:
                after_purchase(shelf)
                live.append(shelf.current())
            return 'bought'

        ex.exchange_scan_screen = MagicMock(side_effect=lambda *args, **kwargs: shelf.current())
        ex.exchange_drag_shelf = MagicMock(side_effect=lambda delta_x: shelf.drag(delta_x))
        ex.exchange_buy_card = MagicMock(side_effect=_buy)

        if entry == 'event':
            ex.exchange_sidebar_bottom = MagicMock()
            ex.exchange_find_event_tabs = MagicMock(return_value=[_EXCHANGE_EVENT_TAB])
            ex.exchange_select_slot = MagicMock(return_value=True)
            total = ex.exchange_run_event(_EXCHANGE_FILTER)
        else:
            includes, excludes = exchange_parse_filter(_EXCHANGE_FILTER)
            total = ex.exchange_sweep('活动·驯鹿币', includes, excludes)
        return total, bought, shelf, live

    @staticmethod
    def _equal_split(shelf):
        """The shelf drifts by one card: the live view matches two pages equally."""
        shelf.remove(_EXCHANGE_HIGH_ITEM)

    @staticmethod
    def _anchor_less(shelf):
        """The shop re-rendered the rows: the live view shares no anchor at all."""
        shelf.remove(_EXCHANGE_HIGH_ITEM)
        shelf.flip_rows()

    def _assert_sweep_result(self, total, bought, shelf, live):
        # The high priority item is restored and bought before the low priority
        # one, and no item is ordered twice.
        self.assertEqual(bought, [_EXCHANGE_HIGH_ITEM, _EXCHANGE_LOW_ITEM])
        self.assertEqual(total, 2)
        self.assertEqual(len(bought), len(set(bought)))
        # The drag made progress and stayed bounded.
        self.assertGreater(shelf.drags, 0)
        self.assertLessEqual(shelf.drags, _EXCHANGE_MAX_DRAGS)
        # The second item is not on screen any more, it is further to the right.
        self.assertNotIn(_EXCHANGE_LOW_ITEM, [card['title'] for card in live[0]])

    def test_event_sweep_keeps_buying_after_the_shelf_anchors_split(self):
        """The event entry keeps exchanging after the shelf lost its anchor."""
        total, bought, shelf, live = self._run('event', self._equal_split)
        self._assert_sweep_result(total, bought, shelf, live)

    def test_sweep_keeps_buying_after_the_shelf_lost_every_anchor(self):
        """The sweep keeps exchanging when no page can be told apart any more."""
        total, bought, shelf, live = self._run('sweep', self._anchor_less)
        self._assert_sweep_result(total, bought, shelf, live)

    def test_buy_card_refuses_a_blue_diamond_cost(self):
        """A blue diamond (paid) item must never be bought."""
        ex = _make_exchange()
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        x1, y1, x2, y2 = EXCHANGE_DIALOG_COST_AREA
        image[y1:y2, x1:x2] = (0, 64, 255)
        ex.device.image = image
        ex.wait_overlay_settle = MagicMock(return_value=True)
        ex.wait_overlay_gone = MagicMock(return_value=True)
        ex.appear = MagicMock(return_value=True)
        ex.exchange_close_dialog = MagicMock(return_value=True)

        self.assertEqual(ex.exchange_buy_card(_card('paid', 0)), 'paid')
        ex.exchange_close_dialog.assert_called_once()
        ex.device.click.assert_not_called()


if __name__ == '__main__':
    unittest.main()
