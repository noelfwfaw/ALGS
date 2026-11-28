import unittest
from unittest.mock import Mock, patch

import requests

from module.config import server
from module.resonance import route


def _sample_data():
    cities = ['修格里城', '七号自由港', '汇流塔', '海角城']
    products = [
        {
            'name': '高利特产',
            'type': 'Special',
            'buyPrices': {'修格里城': 1000},
            'buyLot': {'修格里城': 10},
        },
        {
            'name': '次利普货',
            'type': 'Normal',
            'buyPrices': {'修格里城': 2000},
            'buyLot': {'修格里城': 20},
        },
        {
            'name': '制造品',
            'type': 'Craft',
            'buyPrices': {'修格里城': 500},
            'buyLot': {'修格里城': 50},
        },
        {
            'name': '红茶',
            'type': 'Normal',
            'buyPrices': {'汇流塔': 500},
            'buyLot': {'汇流塔': 20},
        },
        {
            'name': '斑节虾',
            'type': 'Special',
            'buyPrices': {'七号自由港': 800},
            'buyLot': {'七号自由港': 10},
        },
    ]
    return {
        'cities': cities,
        'city_attach': {'汇流塔': '海角城'},
        'city_with_prestige': ['修格里城', '七号自由港', '海角城'],
        'city_fatigues': [
            {'cities': ['修格里城', '七号自由港'], 'fatigue': 40},
            {'cities': ['修格里城', '汇流塔'], 'fatigue': 50},
            {'cities': ['修格里城', '海角城'], 'fatigue': 60},
            {'cities': ['七号自由港', '汇流塔'], 'fatigue': 30},
            {'cities': ['七号自由港', '海角城'], 'fatigue': 35},
            {'cities': ['汇流塔', '海角城'], 'fatigue': 20},
        ],
        'products': products,
        'resonance_skills': {
            '朱利安': {
                '1': {'buyMore': {'product': {'斑节虾': 20}}},
                '4': {'buyMore': {'product': {'斑节虾': 20}, 'city': {'七号自由港': 20}}},
            },
            '波克士': {
                '1': {'other': {'driveLessFatigue': 5}},
            },
            'TestAll': {
                '1': {'buyMore': {'all': 10}},
            },
        },
        'city_by_id': {str(i): c for i, c in enumerate(cities, 1)},
        'product_by_id': {str(i): p['name'] for i, p in enumerate(products, 1)},
        'products_by_city': {
            c: [p for p in products if c in p['buyPrices']]
            for c in cities
        },
        'fatigue_map': {
            frozenset(('修格里城', '七号自由港')): 40,
            frozenset(('修格里城', '汇流塔')): 50,
            frozenset(('修格里城', '海角城')): 60,
            frozenset(('七号自由港', '汇流塔')): 30,
            frozenset(('七号自由港', '海角城')): 35,
            frozenset(('汇流塔', '海角城')): 20,
        },
    }


class TestResonanceRoute(unittest.TestCase):
    def test_decode_prices(self):
        data = _sample_data()
        raw = {
            '1': {
                'b': {'1': {'p': 1050, 'v': 105, 't': 1, 'ti': 1700000001}},
                's': {'2': {'p': 1600, 'v': 110, 't': 0, 'ti': 1700000002}},
            }
        }
        decoded = route.decode_prices(raw, data=data)
        self.assertEqual(decoded['高利特产']['buy']['修格里城'], {
            'price': 1050,
            'variation': 105,
            'trend': 'up',
            'time': 1700000001,
        })
        self.assertEqual(decoded['高利特产']['sell']['七号自由港'], {
            'price': 1600,
            'variation': 110,
            'trend': 'down',
            'time': 1700000002,
        })

    def test_js_round(self):
        self.assertEqual(route.js_round(2.5), 3)
        self.assertEqual(route.js_round(3.5), 4)
        self.assertEqual(route.js_round(2.4), 2)

    def test_one_way_exact_math_special_tax_and_wasting_restock(self):
        data = _sample_data()
        prices = {
            '高利特产': {
                'buy': {'修格里城': {'price': 1000}},
                'sell': {'七号自由港': {'price': 2000}},
            },
            '次利普货': {
                'buy': {'修格里城': {'price': 2000}},
                'sell': {'七号自由港': {'price': 2500}},
            },
            '制造品': {
                'buy': {'修格里城': {'price': 500}},
                'sell': {'七号自由港': {'price': 5000}},
            },
        }
        cfg = {
            'maxLot': 45,
            'bargain': {
                'bargainPercent': 20,
                'raisePercent': 20,
                'bargainFatigue': 2,
                'raiseFatigue': 3,
                'disabled': False,
            },
            'prestige': {'修格里城': 1, '七号自由港': 1},
            'onegraph': {'maxRestock': 1, 'goAndReturn': False},
        }
        routes = route.recommend_routes(
            prices, player_config=cfg, data=data, from_city='修格里城', to_city='七号自由港', limit=5,
        )
        self.assertEqual(len(routes), 1)
        r = routes[0]
        leg = r['go']
        # 高利特产: buy=800, sell=2400, sellTax=0.07 (七号自由港 specialTax), buyTax=0.10 -> 1408
        # 次利普货: buy=1600, sell=3000, sellTax=0.07, buyTax=0.10 -> 1142
        # 制造品: skipped (type == Craft)
        # prestige 1 extraBuy=0.1 => buyLot: 高利=11, 次利=22; restock=1 => avail: 22 and 44; maxLot=45 => take 22 and 23
        self.assertEqual([c['name'] for c in leg['combinations']], ['高利特产', '次利普货'])
        self.assertEqual([c['name'] for c in leg['buy_order']], ['次利普货', '高利特产'])
        self.assertEqual(leg['combinations'][0]['single_profit'], 1408)
        self.assertEqual(leg['combinations'][1]['single_profit'], 1142)
        self.assertEqual(leg['combinations'][1]['buy_lot'], 23)
        self.assertEqual(leg['combinations'][1]['available_lot'], 44)
        self.assertEqual(leg['used_lot'], 45)
        expected_profit = 22 * 1408 + 23 * 1142
        self.assertEqual(leg['profit'], expected_profit)
        self.assertEqual(leg['fatigue'], 45)
        self.assertEqual(leg['profit_per_fatigue'], route.js_round(expected_profit / 45))
        self.assertEqual(leg['general_profit_index'], route.js_round(expected_profit / (45 + 33 * 1)))
        self.assertFalse(leg['is_wasting_restock'])

        # With maxLot=10, restock=1 wastes restock because restock=0 already fills 10 of 高利特产 (buy_lot=11)
        cfg['maxLot'] = 10
        cfg['onegraph']['maxRestock'] = 1
        wasted = route.recommend_routes(
            prices, player_config=cfg, data=data, from_city='修格里城', to_city='七号自由港',
        )[0]['go']
        self.assertTrue(wasted['is_wasting_restock'])
        self.assertEqual(wasted['last_not_wasting_restock'], 0)

        # Verify city_attach maps 汇流塔 prestige lookup to 海角城
        prices_attach = {
            '红茶': {
                'buy': {'汇流塔': {'price': 500}},
                'sell': {'修格里城': {'price': 1000}},
            },
        }
        cfg_attach = {'maxLot': 20, 'prestige': {'海角城': 20, '修格里城': 1}, 'onegraph': {'maxRestock': 0}}
        attach_route = route.recommend_routes(
            prices_attach, player_config=cfg_attach, data=data, from_city='汇流塔', to_city='修格里城',
        )[0]
        # 海角城 level 20 => extraBuy=2.0 => buyLot = round(20 * (100+200)/100) = 60, capped to maxLot 20
        self.assertEqual(attach_route['go']['combinations'][0]['available_lot'], 60)
        self.assertEqual(attach_route['go']['used_lot'], 20)

    def test_round_trip_split_and_dedup(self):
        data = _sample_data()
        prices = {
            '高利特产': {
                'buy': {'修格里城': {'price': 1000}},
                'sell': {'海角城': {'price': 2000}},
            },
            '红茶': {
                'buy': {'汇流塔': {'price': 500}},
                'sell': {'修格里城': {'price': 600}},
            },
            '斑节虾': {
                'buy': {'七号自由港': {'price': 800}},
                'sell': {'修格里城': {'price': 1500}},
            },
        }
        # Make 海角城 -> 修格里城 profitable too, identical to test symmetric tie vs asymmetric split
        data['products'].append({
            'name': '海角特产',
            'type': 'Normal',
            'buyPrices': {'海角城': 1000},
            'buyLot': {'海角城': 10},
        })
        data['products_by_city']['海角城'].append(data['products'][-1])
        prices['海角特产'] = {
            'buy': {'海角城': {'price': 1000}},
            'sell': {'修格里城': {'price': 1500}},
        }
        cfg = {
            'maxLot': 40,
            'onegraph': {'maxRestock': 2, 'goAndReturn': True},
            'prestige': {'修格里城': 1, '海角城': 1, '七号自由港': 1},
        }
        # Go (修格里城->海角城) has higher singleProfit than return (海角城->修格里城),
        # so optimal split puts all 2 restocks on go leg (buyLot=11*(2+1)=33 <= 40).
        fixed = route.recommend_routes(
            prices, player_config=cfg, data=data, from_city='修格里城', to_city='海角城',
        )
        self.assertEqual(len(fixed), 1)
        rt = fixed[0]
        self.assertTrue(rt['go_and_return'])
        self.assertEqual(rt['go']['restock'], 2)
        self.assertEqual(rt['ret']['restock'], 0)
        self.assertEqual(rt['restock'], 2)
        self.assertEqual(rt['fatigue'], 120)
        self.assertEqual(rt['general_profit_index'], route.js_round(rt['profit'] / (120 + 33 * 2)))

        # Symmetric tie: when from_city is None and both directions yield equal profit, keep from_city < to_city
        prices['海角特产']['sell']['修格里城']['price'] = 2000
        deduped = route.recommend_routes(prices, player_config=cfg, data=data, limit=None)
        pairs = {(r['from_city'], r['to_city']) for r in deduped}
        self.assertIn(('修格里城', '海角城'), pairs)
        self.assertNotIn(('海角城', '修格里城'), pairs)
        self.assertLess('修格里城', '海角城')

        # When from_city is explicitly pinned, keep the pinned direction even if from_city > to_city
        pinned = route.recommend_routes(prices, player_config=cfg, data=data, from_city='海角城', limit=None)
        self.assertTrue(any(r['from_city'] == '海角城' and r['to_city'] == '修格里城' for r in pinned))

    def test_player_config_modifiers(self):
        data = _sample_data()
        prices = {
            '斑节虾': {
                'buy': {'七号自由港': {'price': 800}},
                'sell': {'修格里城': {'price': 1600}},
            },
            '红茶': {
                'buy': {'汇流塔': {'price': 500}},
                'sell': {'修格里城': {'price': 1000}},
            },
        }
        raw_cfg = {
            'maxLot': 500,
            'prestige': {'七号自由港': 10, '修格里城': 1, '海角城': 1},
            'roles': {
                # Level 5 not defined for 朱利安 -> falls back to level 4 (20% product + 20% Special city)
                '朱利安': {'resonance': 5},
                '波克士': {'resonance': 1},
                'TestAll': {'resonance': 1},
            },
            'events': {'红茶战争': {'activated': True}},
            'excludedCities': ['汇流塔'],
            'allExchangesBuyMorePercent': 10,
            'productsBuyMorePercent': {'斑节虾': 5},
            'onegraph': {'maxRestock': 0},
        }
        cfg = route.normalize_player_config(raw_cfg, data=data)
        self.assertEqual(cfg['roles']['朱利安']['resonance'], 4)

        routes = route.recommend_routes(prices, player_config=cfg, data=data, limit=10)
        # 汇流塔 excluded
        self.assertTrue(all(r['from_city'] != '汇流塔' and r['to_city'] != '汇流塔' for r in routes))
        shrimp = next(r for r in routes if r['from_city'] == '七号自由港' and r['to_city'] == '修格里城')
        # 波克士 driveLessFatigue=5 reduces 40 -> 35
        self.assertEqual(shrimp['fatigue'], 35)
        # buyMore = 20(product) + 20(Special city) + 10(TestAll) + 100(extraBuy 1.0) + 10(all) + 5(prod) = 165%
        # buyLot = round(10 * 265 / 100) = 27 (26.5 -> 27 via js_round)
        self.assertEqual(shrimp['go']['used_lot'], 27)

        # productUnlockStatus=False excludes product, 红茶战争 boosts 红茶 when 汇流塔 not excluded
        cfg['excludedCities'] = []
        cfg['productUnlockStatus'] = {'斑节虾': False}
        routes2 = route.recommend_routes(prices, player_config=cfg, data=data, limit=10)
        self.assertFalse(any(r['from_city'] == '七号自由港' and r['profit'] > 0 for r in routes2))
        tea = next(r for r in routes2 if r['from_city'] == '汇流塔' and r['to_city'] == '修格里城')
        # 红茶 base=20, extraBuy(海角城 Lv1)=10% + 红茶战争 50% + TestAll 10% + allExchanges 10% = 80% => 36
        self.assertEqual(tea['go']['used_lot'], 36)

    def test_http_request_proxy_fallback(self):
        direct_session = Mock()
        direct_session.request.side_effect = requests.RequestException('direct blocked')
        proxy_resp = Mock()
        proxy_resp.json.return_value = {'ok': True}
        proxy_session = Mock()
        proxy_session.request.return_value = proxy_resp

        with patch('module.resonance.columba.requests.Session', side_effect=[direct_session, proxy_session]), \
                patch('module.resonance.columba.urllib.request.getproxies',
                      return_value={'https': 'https://127.0.0.1:7897', 'http': 'http://127.0.0.1:7897'}):
            result = route.http_request('GET', 'https://www.resonance-columba.com/api/get-prices', timeout=5)

        self.assertEqual(result, {'ok': True})
        self.assertFalse(direct_session.trust_env)
        self.assertFalse(proxy_session.trust_env)
        _, kwargs = proxy_session.request.call_args
        self.assertEqual(kwargs['proxies'], {
            'https': 'http://127.0.0.1:7897',
            'http': 'http://127.0.0.1:7897',
        })

    def test_market_quality_index_bounds_and_config_invariance(self):
        from module.resonance.market import evaluate_market_quality

        data = _sample_data()
        for p in data['products']:
            if p['name'] == '高利特产':
                p['sellPrices'] = {'七号自由港': 2000}
            elif p['name'] == '次利普货':
                p['sellPrices'] = {'七号自由港': 2500}
            elif p['name'] == '红茶':
                p['sellPrices'] = {'修格里城': 1000}
            elif p['name'] == '斑节虾':
                p['sellPrices'] = {'修格里城': 1600}

        parity_prices = {
            '高利特产': {'buy': {'修格里城': {'price': 1000, 'variation': 100}}, 'sell': {'七号自由港': {'price': 2000, 'variation': 100}}},
            '次利普货': {'buy': {'修格里城': {'price': 2000, 'variation': 100}}, 'sell': {'七号自由港': {'price': 2500, 'variation': 100}}},
            '红茶': {'buy': {'汇流塔': {'price': 500, 'variation': 100}}, 'sell': {'修格里城': {'price': 1000, 'variation': 100}}},
            '斑节虾': {'buy': {'七号自由港': {'price': 800, 'variation': 100}}, 'sell': {'修格里城': {'price': 1600, 'variation': 100}}},
        }
        good_prices = {
            '高利特产': {'buy': {'修格里城': {'price': 800, 'variation': 80}}, 'sell': {'七号自由港': {'price': 2400, 'variation': 120}}},
            '次利普货': {'buy': {'修格里城': {'price': 1600, 'variation': 80}}, 'sell': {'七号自由港': {'price': 3000, 'variation': 120}}},
            '红茶': {'buy': {'汇流塔': {'price': 400, 'variation': 80}}, 'sell': {'修格里城': {'price': 1200, 'variation': 120}}},
            '斑节虾': {'buy': {'七号自由港': {'price': 640, 'variation': 80}}, 'sell': {'修格里城': {'price': 1920, 'variation': 120}}},
        }
        mid_prices = {
            '高利特产': {'buy': {'修格里城': {'price': 900, 'variation': 90}}, 'sell': {'七号自由港': {'price': 2200, 'variation': 110}}},
            '次利普货': {'buy': {'修格里城': {'price': 1800, 'variation': 90}}, 'sell': {'七号自由港': {'price': 2750, 'variation': 110}}},
            '红茶': {'buy': {'汇流塔': {'price': 450, 'variation': 90}}, 'sell': {'修格里城': {'price': 1100, 'variation': 110}}},
            '斑节虾': {'buy': {'七号自由港': {'price': 720, 'variation': 90}}, 'sell': {'修格里城': {'price': 1760, 'variation': 110}}},
        }

        cfg_small = route.normalize_player_config({
            'maxLot': 400,
            'prestige': {'修格里城': 5, '七号自由港': 5, '海角城': 5},
            'onegraph': {'maxRestock': 0},
        }, data=data)
        cfg_large = route.normalize_player_config({
            'maxLot': 1000,
            'prestige': {'修格里城': 20, '七号自由港': 20, '海角城': 20},
            'bargain': {'bargainPercent': 20, 'raisePercent': 20, 'disabled': False},
            'onegraph': {'maxRestock': 2},
        }, data=data)

        for cfg in (cfg_small, cfg_large):
            for sort_by in ('profit_per_fatigue', 'general_profit_index'):
                self.assertEqual(evaluate_market_quality(parity_prices, cfg, sort_by, data)['index'], 0.0)
                self.assertEqual(evaluate_market_quality(good_prices, cfg, sort_by, data)['index'], 100.0)
                mid_mq = evaluate_market_quality(mid_prices, cfg, sort_by, data)
                self.assertGreater(mid_mq['index'], 40.0)
                self.assertLess(mid_mq['index'], 60.0)

        # Fallback when static sellPrices is missing: derive baseline from live_price / (variation / 100)
        no_static_sell = _sample_data()
        self.assertEqual(evaluate_market_quality(good_prices, cfg_small, 'general_profit_index', no_static_sell)['index'], 100.0)

        # Manual corridor evaluation evaluates both A->B and B->A using exact corridor rules
        corridor = evaluate_market_quality(
            mid_prices, cfg_large, 'profit_per_fatigue', data, manual_cities=('修格里城', '七号自由港'),
        )
        self.assertGreater(corridor['index'], 40.0)
        self.assertIn('->', corridor['route'])

    def test_scheduler_precheck_missing_profile_waits_then_passes(self):
        import os
        import tempfile
        from datetime import datetime
        from types import SimpleNamespace
        from module.resonance.market import load_market_status, precheck_resonance_market

        data = _sample_data()
        parity = {'高利特产': {
            'buy': {'修格里城': {'price': 1000, 'variation': 100}},
            'sell': {'七号自由港': {'price': 2000, 'variation': 100}},
        }}
        good = {'高利特产': {
            'buy': {'修格里城': {'price': 800, 'variation': 80}},
            'sell': {'七号自由港': {'price': 2400, 'variation': 120}},
        }}
        config = SimpleNamespace(
            config_name='TEST', ResonanceTrade_MarketFilter='good',
            ResonanceTrade_MarketWaitMinutes=30, ResonanceTrade_RefreshProfile=False,
        )
        with tempfile.TemporaryDirectory() as tmp:
            profile_path = os.path.join(tmp, 'missing-profile.json')
            status_path = os.path.join(tmp, 'market-status.json')
            with patch('module.resonance.market.load_columba_data', return_value=data), \
                    patch('module.resonance.market.fetch_prices', side_effect=[parity, good]) as fetch, \
                    patch('module.resonance.market.datetime') as clock:
                clock.now.return_value = datetime(2026, 11, 28, 12)
                next_check = precheck_resonance_market(
                    config, profile_path=profile_path, status_path=status_path,
                )
                waited = load_market_status('TEST', path=status_path)
                passed = precheck_resonance_market(
                    config, profile_path=profile_path, status_path=status_path,
                )

        self.assertEqual(datetime(2026, 11, 28, 12, 30), next_check)
        self.assertIsNone(passed)
        self.assertEqual(2, fetch.call_count)
        fetch.assert_called_with(ttl=180, data=data)
        self.assertEqual('wait', waited['status'])
        self.assertEqual('2026-11-28 12:30:00', waited['next_check'])

    def test_market_status_persistence_webui_refresh_and_formatting(self):
        self.addCleanup(server.set_server, server.server)
        server.set_server('resonance')
        import os
        import tempfile
        from module.resonance.map_nav import MAP_COORDS_05X
        from module.resonance.market import (
            MAPPED_CITIES, build_market_status_record, format_market_summary, load_market_status,
            refresh_market_status_for_webui, save_market_status,
        )

        self.assertEqual(set(MAP_COORDS_05X.keys()), MAPPED_CITIES)

        with tempfile.TemporaryDirectory() as tmp:
            status_path = os.path.join(tmp, 'market_status.json')
            self.assertIsNone(load_market_status('TEST', path=status_path))

            sample_mq = {
                'index': 37.5,
                'live': 15300,
                'base': 12000,
                'good': 20800,
                'sort_by': 'general_profit_index',
                'route': '修格里城 -> 七号自由港',
            }
            rec_a = build_market_status_record(sample_mq, 'pass', 'good', fatigue=120)
            rec_b = build_market_status_record(sample_mq, 'wait', 'great', fatigue=250, next_check='2026-11-26 11:00:00')
            save_market_status('INST_A', rec_a, path=status_path)
            save_market_status('INST_B', rec_b, path=status_path)
            self.assertEqual(load_market_status('INST_A', path=status_path)['status'], 'pass')
            self.assertEqual(load_market_status('INST_B', path=status_path)['next_check'], '2026-11-26 11:00:00')

            data = _sample_data()
            for p in data['products']:
                if p['name'] == '高利特产':
                    p['sellPrices'] = {'七号自由港': 2000}
                elif p['name'] == '次利普货':
                    p['sellPrices'] = {'七号自由港': 2500}
                elif p['name'] == '红茶':
                    p['sellPrices'] = {'修格里城': 1000}
                elif p['name'] == '斑节虾':
                    p['sellPrices'] = {'修格里城': 1600}
            good_prices = {
                '高利特产': {'buy': {'修格里城': {'price': 800, 'variation': 80}}, 'sell': {'七号自由港': {'price': 2400, 'variation': 120}}},
                '次利普货': {'buy': {'修格里城': {'price': 1600, 'variation': 80}}, 'sell': {'七号自由港': {'price': 3000, 'variation': 120}}},
                '红茶': {'buy': {'汇流塔': {'price': 400, 'variation': 80}}, 'sell': {'修格里城': {'price': 1200, 'variation': 120}}},
                '斑节虾': {'buy': {'七号自由港': {'price': 640, 'variation': 80}}, 'sell': {'修格里城': {'price': 1920, 'variation': 120}}},
            }
            mid_prices = {
                '高利特产': {'buy': {'修格里城': {'price': 900, 'variation': 90}}, 'sell': {'七号自由港': {'price': 2200, 'variation': 110}}},
                '次利普货': {'buy': {'修格里城': {'price': 1800, 'variation': 90}}, 'sell': {'七号自由港': {'price': 2750, 'variation': 110}}},
                '红茶': {'buy': {'汇流塔': {'price': 450, 'variation': 90}}, 'sell': {'修格里城': {'price': 1100, 'variation': 110}}},
                '斑节虾': {'buy': {'七号自由港': {'price': 720, 'variation': 90}}, 'sell': {'修格里城': {'price': 1760, 'variation': 110}}},
            }
            prof = {'maxLot': 500, 'prestige': {'修格里城': 10, '七号自由港': 10, '海角城': 10}, 'roles': {}}
            r_pass = refresh_market_status_for_webui(
                'INST_UI',
                {'MarketFilter': 'good', 'SortBy': 'general_profit_index', 'RestockBooks': 0},
                profile=prof,
                prices=good_prices,
                data=data,
                status_path=status_path,
            )
            self.assertEqual(r_pass['status'], 'pass')
            self.assertEqual(load_market_status('INST_UI', path=status_path)['index'], 100.0)

            r_open = refresh_market_status_for_webui(
                'INST_OPEN',
                {'MarketFilter': 'all', 'SortBy': 'profit_per_fatigue', 'RestockBooks': 0},
                profile=prof,
                prices=mid_prices,
                data=data,
                status_path=status_path,
            )
            self.assertEqual(r_open['status'], 'open')

            parity_prices = {
                '高利特产': {'buy': {'修格里城': {'price': 1000, 'variation': 100}}, 'sell': {'七号自由港': {'price': 2000, 'variation': 100}}},
                '红茶': {'buy': {'汇流塔': {'price': 500, 'variation': 100}}, 'sell': {'修格里城': {'price': 1000, 'variation': 100}}},
            }
            r_wait = refresh_market_status_for_webui(
                'INST_WAIT',
                {'MarketFilter': 'good', 'SortBy': 'general_profit_index', 'RestockBooks': 0},
                profile=prof,
                prices=parity_prices,
                data=data,
                status_path=status_path,
            )
            self.assertEqual(r_wait['status'], 'wait')

            for st_rec in (
                rec_a,
                rec_b,
                build_market_status_record(sample_mq, 'overflow', 'good', fatigue=40),
                r_open,
            ):
                fmt = format_market_summary(st_rec)
                self.assertTrue(fmt['badge'])
                self.assertTrue(fmt['overview_line'])
                self.assertGreaterEqual(len(fmt['detail_lines']), 4)
