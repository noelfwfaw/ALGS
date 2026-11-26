import json
import os
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.config import server


def _cycle_graph_data():
    """Build synthetic 4-city test dataset with triangle profit structure."""
    cities = ['甲城', '乙城', '丙城', '丁城']
    products = [
        {'name': '甲货', 'type': 'Normal', 'buyPrices': {'甲城': 1000}, 'buyLot': {'甲城': 20}, 'sellPrices': {'乙城': 3000}},
        {'name': '乙货', 'type': 'Normal', 'buyPrices': {'乙城': 1000}, 'buyLot': {'乙城': 20}, 'sellPrices': {'丙城': 3000}},
        {'name': '丙货', 'type': 'Normal', 'buyPrices': {'丙城': 1000}, 'buyLot': {'丙城': 20}, 'sellPrices': {'甲城': 2800}},
        {'name': '丁货', 'type': 'Normal', 'buyPrices': {'丁城': 1000}, 'buyLot': {'丁城': 20}, 'sellPrices': {'甲城': 1600}},
    ]
    fatigues = [
        ('甲城', '乙城', 30), ('乙城', '丙城', 30), ('丙城', '甲城', 30),
        ('甲城', '丁城', 20), ('乙城', '丁城', 50), ('丙城', '丁城', 50),
    ]
    return {
        'cities': cities,
        'city_attach': {},
        'city_with_prestige': cities,
        'city_fatigues': [{'cities': [a, b], 'fatigue': f} for a, b, f in fatigues],
        'products': products,
        'resonance_skills': {},
        'products_by_city': {c: [p for p in products if c in p['buyPrices']] for c in cities},
        'fatigue_map': {frozenset((a, b)): f for a, b, f in fatigues},
    }


class TestResonanceSmartCycle(unittest.TestCase):
    def setUp(self):
        self.addCleanup(server.set_server, server.server)
        server.set_server('resonance')

    def test_three_city_cycle_beats_two_city_round_trips(self):
        from module.resonance.smart_cycle import build_edge_options, solve_optimal_cycle

        data = _cycle_graph_data()
        prices = {
            '甲货': {'buy': {'甲城': {'price': 1000}}, 'sell': {'乙城': {'price': 3000}, '丙城': {'price': 1100}}},
            '乙货': {'buy': {'乙城': {'price': 1000}}, 'sell': {'丙城': {'price': 3000}, '甲城': {'price': 1100}}},
            '丙货': {'buy': {'丙城': {'price': 1000}}, 'sell': {'甲城': {'price': 2800}, '乙城': {'price': 1100}}},
            '丁货': {'buy': {'丁城': {'price': 1000}}, 'sell': {'甲城': {'price': 1600}}},
        }
        cfg = {'maxLot': 200, 'prestige': {c: 20 for c in data['cities']}, 'excludedCities': []}
        cities, edges = build_edge_options(prices, cfg, data, max_books=3)

        best_2 = solve_optimal_cycle(edges, cities, book_weight=33.0, max_len=2)
        best_4 = solve_optimal_cycle(edges, cities, book_weight=33.0, max_len=4)
        self.assertIsNotNone(best_2)
        self.assertIsNotNone(best_4)
        self.assertGreater(best_4['score'], best_2['score'])
        self.assertEqual(set(best_4['cities'][:-1]), {'甲城', '乙城', '丙城'})
        self.assertEqual(len(best_4['legs']), 3)

    def test_asymmetric_negotiation_and_restock_optimization(self):
        from module.resonance.smart_cycle import build_edge_options, solve_optimal_cycle

        # On a narrower spread (buy=1800, sell=2500), +20% raise boosts profit ~83% for +63% fatigue (wins over 0/0),
        # while adding -20% bargain only boosts ~34% for +39% more fatigue (0/20 beats 20/20).
        # buyLot=50 at lv20 gives 150 lots with 0 restock, filling maxLot=150 (so r>0 is pruned).
        data = _cycle_graph_data()
        data['products'][0]['buyLot'] = {'甲城': 50}
        data['products'][1]['buyLot'] = {'乙城': 50}
        prices = {
            '甲货': {'buy': {'甲城': {'price': 1800}}, 'sell': {'乙城': {'price': 2500}}},
            '乙货': {'buy': {'乙城': {'price': 1800}}, 'sell': {'甲城': {'price': 2500}}},
        }
        cfg = {'maxLot': 150, 'prestige': {c: 20 for c in data['cities']}, 'excludedCities': ['丙城', '丁城']}
        cities, edges = build_edge_options(prices, cfg, data, max_books=3)
        cycle = solve_optimal_cycle(edges, cities, book_weight=33.0, max_len=2)
        self.assertIsNotNone(cycle)
        for leg in cycle['legs']:
            self.assertEqual(leg['restock'], 0)
            self.assertEqual(leg['bargain_pct'], 0)
            self.assertEqual(leg['raise_pct'], 20)

        # Bigger maxLot=120 with buyLot=20*3=60/book forces r=1 to double cargo & profit
        data['products'][0]['buyLot'] = {'甲城': 20}
        data['products'][1]['buyLot'] = {'乙城': 20}
        cfg['maxLot'] = 120
        cities, edges = build_edge_options(prices, cfg, data, max_books=3)
        cycle_restock = solve_optimal_cycle(edges, cities, book_weight=10.0, max_len=2)
        self.assertTrue(all(leg['restock'] == 1 for leg in cycle_restock['legs']))

    def test_inventory_adaptive_book_weight_and_state_calibration(self):
        from module.resonance.smart_cycle import (
            DEFAULT_BOOK_WEIGHT, ZERO_BOOK_COOLDOWN_SECONDS, compute_book_weight,
            get_active_cooldowns, load_smart_state, record_negotiation_fatigue, record_zero_book_buy,
            update_smart_books,
        )

        self.assertEqual(compute_book_weight(None), (DEFAULT_BOOK_WEIGHT, 5))
        self.assertEqual(compute_book_weight(0), (120.0, 0))
        self.assertEqual(compute_book_weight(10), (90.0, 1))
        self.assertEqual(compute_book_weight(20), (70.0, 3))
        self.assertEqual(compute_book_weight(60), (42.0, 5))
        self.assertEqual(compute_book_weight(200), (30.0, 5))
        self.assertEqual(compute_book_weight(500), (22.0, 5))
        self.assertEqual(compute_book_weight(999), (22.0, 5))

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'smart.json')
            init = load_smart_state('TEST', path=path)
            self.assertIsNone(init['owned_books'])

            update_smart_books('TEST', 18, path=path)
            record_zero_book_buy('TEST', '海角城', path=path, now_ts=1000.0)
            record_negotiation_fatigue('TEST', True, 20, 30, path=path)
            record_negotiation_fatigue('TEST', False, 10, 2, path=path)  # clamped >= 6.0

            st = load_smart_state('TEST', path=path)
            self.assertEqual(st['owned_books'], 18)
            self.assertAlmostEqual(st['neg_fatigue']['buy']['20'], 24.0)
            self.assertAlmostEqual(st['neg_fatigue']['sell']['10'], 9.0)

            active = get_active_cooldowns(st, now_ts=1000.0)
            self.assertAlmostEqual(active['海角城'], 0.35)
            expired = get_active_cooldowns(st, now_ts=1000.0 + ZERO_BOOK_COOLDOWN_SECONDS + 1)
            self.assertEqual(expired, {})

    def test_plan_entry_on_cycle_and_endgame_short_leg(self):
        from module.resonance.smart_cycle import plan_smart_cycle_leg, plan_smart_endgame_leg

        data = _cycle_graph_data()
        prices = {
            '甲货': {'buy': {'甲城': {'price': 1000}}, 'sell': {'乙城': {'price': 3000}}},
            '乙货': {'buy': {'乙城': {'price': 1000}}, 'sell': {'丙城': {'price': 3000}}},
            '丙货': {'buy': {'丙城': {'price': 1000}}, 'sell': {'甲城': {'price': 2800}}},
            '丁货': {'buy': {'丁城': {'price': 1000}}, 'sell': {'甲城': {'price': 2800}}},
        }
        cfg = {'maxLot': 60, 'prestige': {c: 20 for c in data['cities']}, 'excludedCities': []}
        smart_state = {'owned_books': 100, 'zero_book_buys': {}}

        on_cycle = plan_smart_cycle_leg('甲城', prices, cfg, data, smart_state=smart_state)
        self.assertEqual((on_cycle['from_city'], on_cycle['to_city']), ('甲城', '乙城'))
        self.assertFalse(on_cycle['is_reposition'])

        off_cycle = plan_smart_cycle_leg('丁城', prices, cfg, data, smart_state=smart_state)
        self.assertEqual((off_cycle['from_city'], off_cycle['to_city']), ('丁城', '甲城'))
        self.assertGreater(off_cycle['leg']['profit'], 0)

        # Endgame: when remaining fatigue=25 (< 30 needed for 丙->甲), check shorter leg inside fatigue budget
        data['city_fatigues'].append({'cities': ['丁城', '乙城'], 'fatigue': 100})
        data['fatigue_map'][frozenset(('甲城', '丁城'))] = 15
        prices['甲货']['sell']['丁城'] = {'price': 3200}
        plan_a = plan_smart_cycle_leg('甲城', prices, cfg, data, smart_state=smart_state)
        endgame = plan_smart_endgame_leg(
            '甲城', plan_a['_edges'], plan_a['cycle'], remaining_fatigue=20, book_weight=plan_a['cycle']['book_weight'],
        )
        self.assertIsNotNone(endgame)
        self.assertLessEqual(endgame['leg']['fatigue'], 20)

        none_endgame = plan_smart_endgame_leg(
            '甲城', plan_a['_edges'], plan_a['cycle'], remaining_fatigue=5, book_weight=plan_a['cycle']['book_weight'],
        )
        self.assertIsNone(none_endgame)

    def test_caravan_smart_cycle_end_to_end_and_telemetry(self):
        from module.resonance.caravan import ResonanceCaravan
        from module.resonance.smart_state import (
            load_smart_state, record_negotiation_fatigue, record_zero_book_buy, update_smart_books,
        )

        data = _cycle_graph_data()
        data['products'][0]['buyLot'] = {'甲城': 50}
        data['products'][1]['buyLot'] = {'乙城': 50}
        prices = {
            '甲货': {'buy': {'甲城': {'price': 1800}}, 'sell': {'乙城': {'price': 2500}}},
            '乙货': {'buy': {'乙城': {'price': 1800}}, 'sell': {'甲城': {'price': 2500}}},
        }
        cfg_lot = 150
        profile = {'maxLot': cfg_lot, 'prestige': {c: 20 for c in data['cities']}, 'roles': {}}

        with tempfile.TemporaryDirectory() as tmp:
            smart_path = os.path.join(tmp, 'smart.json')
            trade_path = os.path.join(tmp, 'trade.json')

            caravan = ResonanceCaravan.__new__(ResonanceCaravan)
            caravan.device = Mock()
            caravan.config = SimpleNamespace(
                config_name='TEST',
                ResonanceTrade_RouteMode='smart_cycle',
                ResonanceTrade_SortBy='general_profit_index',
                ResonanceTrade_MarketFilter='all',
                ResonanceTrade_MarketOverflowProtect=True,
                ResonanceTrade_MarketWaitMinutes=30,
                ResonanceTrade_RoundTrip=False,
                ResonanceTrade_RestockBooks=2,
                ResonanceTrade_BargainPercent=20,
                ResonanceTrade_RaisePercent=20,
                ResonanceTrade_ReturnBargain=False,
                ResonanceTrade_AutoInvest=False,
                ResonanceTrade_UseRamming=False,
                ResonanceTrade_UseRestArea=False,
                ResonanceTrade_UseBento=False,
                ResonanceTrade_UseFatigueItem='none',
                ResonanceTrade_ExcludedCities='丙城, 丁城',
                ResonanceTrade_RefreshProfile=False,
                task_delay=Mock(),
            )
            caravan.ui_ensure = Mock()
            caravan.wait_until_docked = Mock()
            caravan.ensure_profile = Mock(return_value=profile)
            caravan.get_current_city = Mock(return_value='甲城')
            caravan.sell_all = Mock(side_effect=[False, True])
            caravan.buy_plan = Mock(side_effect=lambda *a, **kw: setattr(caravan, '_last_restock_owned', 85) or True)
            caravan.travel_to = Mock(return_value=True)
            caravan.ui_goto_main = Mock()
            caravan._read_current_fatigue = Mock(side_effect=[(0, 912), (895, 912)])

            with patch('module.resonance.caravan.load_trade_state', return_value={}), \
                    patch('module.resonance.caravan.save_trade_state') as mock_save_state, \
                    patch('module.resonance.caravan.clear_trade_state'), \
                    patch('module.resonance.caravan.fetch_prices', return_value=prices), \
                    patch('module.resonance.caravan.load_columba_data', return_value=data), \
                    patch('module.resonance.caravan.MAP_COORDS_05X', {'甲城': (0, 0), '乙城': (1, 1)}), \
                    patch('module.resonance.caravan.save_market_status'), \
                    patch('module.resonance.caravan.record_trade_profit'), \
                    patch('module.resonance.caravan.load_smart_state', side_effect=lambda c: load_smart_state(c, path=smart_path)), \
                    patch('module.resonance.caravan.update_smart_books', side_effect=lambda c, n: update_smart_books(c, n, path=smart_path)), \
                    patch('module.resonance.caravan.record_zero_book_buy', side_effect=lambda c, city: record_zero_book_buy(c, city, path=smart_path)), \
                    patch('module.resonance.caravan.record_negotiation_fatigue', side_effect=lambda c, ib, t, f: record_negotiation_fatigue(c, ib, t, f, path=smart_path)), \
                    patch('module.resonance.caravan.TRADE_STATE_PATH', trade_path):
                # Record sell fatigue after 2nd sell_all call
                orig_sell = caravan.sell_all
                def sell_side_effect(raise_target=0):
                    res = orig_sell(raise_target=raise_target)
                    caravan._last_negotiate_fatigue = 18 if raise_target > 0 else None
                    return res
                caravan.sell_all = Mock(side_effect=sell_side_effect)
                caravan.run()

            caravan.buy_plan.assert_called_once()
            self.assertEqual(caravan.buy_plan.call_args[1]['bargain_target'], 0)
            self.assertEqual(mock_save_state.call_args[1]['sell_raise_target'], 20)
            self.assertEqual(caravan.sell_all.call_args_list[1][1]['raise_target'], 20)

            st = load_smart_state('TEST', path=smart_path)
            self.assertEqual(st['owned_books'], 85)
            self.assertIn('甲城', st['zero_book_buys'])
            self.assertAlmostEqual(st['neg_fatigue']['sell']['20'], 21.0)

    def test_market_smart_cycle_quality_and_lightweight_import(self):
        from module.resonance.market import (
            SMART_CYCLE_GOOD_BUY_V, SMART_CYCLE_GOOD_SELL_V, build_market_status_record,
            evaluate_market_quality, format_market_summary,
        )

        data = _cycle_graph_data()
        parity = {
            '甲货': {'buy': {'甲城': {'price': 1000, 'variation': 100}}, 'sell': {'乙城': {'price': 3000, 'variation': 100}}},
            '乙货': {'buy': {'乙城': {'price': 1000, 'variation': 100}}, 'sell': {'丙城': {'price': 3000, 'variation': 100}}},
            '丙货': {'buy': {'丙城': {'price': 1000, 'variation': 100}}, 'sell': {'甲城': {'price': 2800, 'variation': 100}}},
        }
        good = {
            '甲货': {
                'buy': {'甲城': {'price': 890, 'variation': SMART_CYCLE_GOOD_BUY_V}},
                'sell': {'乙城': {'price': 3330, 'variation': SMART_CYCLE_GOOD_SELL_V}},
            },
            '乙货': {
                'buy': {'乙城': {'price': 890, 'variation': SMART_CYCLE_GOOD_BUY_V}},
                'sell': {'丙城': {'price': 3330, 'variation': SMART_CYCLE_GOOD_SELL_V}},
            },
            '丙货': {
                'buy': {'丙城': {'price': 890, 'variation': SMART_CYCLE_GOOD_BUY_V}},
                'sell': {'甲城': {'price': 3108, 'variation': SMART_CYCLE_GOOD_SELL_V}},
            },
        }
        one_leg_boom = {
            '甲货': {'buy': {'甲城': {'price': 800, 'variation': 80}}, 'sell': {'乙城': {'price': 3600, 'variation': 120}}},
            '乙货': {'buy': {'乙城': {'price': 1000, 'variation': 100}}, 'sell': {'丙城': {'price': 3000, 'variation': 100}}},
            '丙货': {'buy': {'丙城': {'price': 1000, 'variation': 100}}, 'sell': {'甲城': {'price': 2800, 'variation': 100}}},
        }
        cfg = {'maxLot': 200, 'prestige': {c: 20 for c in data['cities']}, 'excludedCities': ['丁城']}
        smart_state = {'owned_books': 150}

        mq_parity = evaluate_market_quality(parity, cfg, 'profit', data, route_mode='smart_cycle', smart_state=smart_state)
        mq_good = evaluate_market_quality(good, cfg, 'profit', data, route_mode='smart_cycle', smart_state=smart_state)
        mq_boom = evaluate_market_quality(
            one_leg_boom, cfg, 'profit', data, route_mode='smart_cycle', smart_state=smart_state,
        )
        self.assertEqual(mq_parity['index'], 0.0)
        self.assertEqual(mq_good['index'], 100.0)
        self.assertGreater(mq_boom['index'], 40.0)
        self.assertEqual(mq_good['sort_by'], 'smart_cycle')
        self.assertIn('3城环:', mq_good['route'])
        self.assertIn('→', mq_good['cycle_detail'])

        rec = build_market_status_record(mq_good, 'pass', 'good', fatigue=120)
        summary = format_market_summary(rec)
        self.assertTrue(any('智能环路方案：' in line for line in summary['detail_lines']))
        self.assertTrue(any('进货书库存：150 本' in line for line in summary['detail_lines']))

        proc = subprocess.run(
            [
                sys.executable, '-c',
                "import sys, module.resonance.smart_cycle, module.resonance.market; "
                "assert 'cv2' not in sys.modules and 'PIL' not in sys.modules",
            ],
            check=False,
        )
        self.assertEqual(proc.returncode, 0)
