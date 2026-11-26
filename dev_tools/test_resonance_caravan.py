import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from module.config import server


def _sample_prices():
    """Return synthetic prices where 阿妮塔发射中心->岚心城 is best, 修格里城->阿妮塔发射中心 is profitable."""
    from module.resonance.columba import load_columba_data

    data = load_columba_data()
    prod_city = {p['name']: p for p in data['products']}
    prices = {}
    # Main best leg: 阿妮塔发射中心 -> 岚心城
    anita_prod = next(p['name'] for p in data['products_by_city']['阿妮塔发射中心'] if p.get('type') != 'Craft')
    prices[anita_prod] = {
        'buy': {'阿妮塔发射中心': {'price': 500, 'variation': 80, 'trend': 'down', 'time': 0}},
        'sell': {'岚心城': {'price': 4500, 'variation': 150, 'trend': 'up', 'time': 0}},
    }
    # Repositioning leg: 修格里城 -> 阿妮塔发射中心
    shug_prod = next(p['name'] for p in data['products_by_city']['修格里城'] if p.get('type') != 'Craft')
    prices[shug_prod] = {
        'buy': {'修格里城': {'price': 400, 'variation': 90, 'trend': 'down', 'time': 0}},
        'sell': {'阿妮塔发射中心': {'price': 1500, 'variation': 120, 'trend': 'up', 'time': 0}},
    }
    # Ensure base price > 0 sanity
    assert prod_city[anita_prod]['buyPrices']['阿妮塔发射中心'] > 0
    return prices


class TestResonanceCaravan(unittest.TestCase):
    def setUp(self):
        self.addCleanup(server.set_server, server.server)
        server.set_server('resonance')
        patcher = patch('module.resonance.caravan.save_market_status')
        self.mock_save_market_status = patcher.start()
        self.addCleanup(patcher.stop)
        profit_patcher = patch('module.resonance.caravan.record_trade_profit')
        self.mock_record_trade_profit = profit_patcher.start()
        self.addCleanup(profit_patcher.stop)

    def test_plan_next_leg_reposition_uses_zero_restock(self):
        from module.resonance.caravan import build_player_config, plan_next_leg
        from module.resonance.columba import PRESTIGE_CITIES, load_columba_data

        data = load_columba_data()
        profile = {'maxLot': 994, 'prestige': {c: 20 for c in PRESTIGE_CITIES}, 'roles': {}}
        cfg = SimpleNamespace(
            ResonanceTrade_SortBy='profit',
            ResonanceTrade_RoundTrip=False,
            ResonanceTrade_RestockBooks=3,
            ResonanceTrade_BargainPercent=20,
            ResonanceTrade_RaisePercent=20,
            ResonanceTrade_ReturnBargain=False,
            ResonanceTrade_ExcludedCities='武林源',
        )
        player_cfg = build_player_config(profile, cfg, data)
        self.assertIn('武林源', player_cfg['excludedCities'])
        self.assertFalse(player_cfg['bargain']['disabled'])
        self.assertTrue(player_cfg['returnBargain']['disabled'])

        cfg_ret = SimpleNamespace(**{**cfg.__dict__, 'ResonanceTrade_ReturnBargain': True})
        self.assertFalse(build_player_config(profile, cfg_ret, data)['returnBargain']['disabled'])

        prices = _sample_prices()

        # Starting in 修格里城 while global best is 阿妮塔发射中心 -> 岚心城
        repo = plan_next_leg('修格里城', prices, player_cfg, 'profit', data)
        self.assertIsNotNone(repo)
        self.assertTrue(repo['is_reposition'])
        self.assertEqual((repo['from_city'], repo['to_city']), ('修格里城', '阿妮塔发射中心'))
        self.assertEqual(repo['leg']['restock'], 0)
        self.assertGreater(repo['leg']['profit'], 0)

        # Already at best origin 阿妮塔发射中心 -> main leg with configured 3 restock books
        main_leg = plan_next_leg('阿妮塔发射中心', prices, player_cfg, 'profit', data)
        self.assertFalse(main_leg['is_reposition'])
        self.assertEqual((main_leg['from_city'], main_leg['to_city']), ('阿妮塔发射中心', '岚心城'))
        self.assertEqual(main_leg['leg']['restock'], 3)

        # No profitable cargo for repositioning -> empty leg fallback still moves to best origin
        no_repo_prices = {
            k: v for k, v in prices.items()
            if '阿妮塔发射中心' in v.get('buy', {})
        }
        empty_repo = plan_next_leg('修格里城', no_repo_prices, player_cfg, 'profit', data)
        self.assertTrue(empty_repo['is_reposition'])
        self.assertEqual(empty_repo['to_city'], '阿妮塔发射中心')
        self.assertEqual(empty_repo['leg']['combinations'], [])

    def test_caravan_same_city_crash_recovery_skips_sell_and_departs(self):
        from module.resonance.caravan import ResonanceCaravan, load_trade_state
        from module.resonance.columba import PRESTIGE_CITIES

        prices = _sample_prices()
        profile = {'maxLot': 994, 'prestige': {c: 20 for c in PRESTIGE_CITIES}, 'roles': {}}

        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, 'trade_state.json')
            with open(state_path, 'w', encoding='utf-8') as f:
                json.dump({'bought_city': '阿妮塔发射中心', 'target_city': '岚心城', 'negotiate_sell': True}, f)

            caravan = ResonanceCaravan.__new__(ResonanceCaravan)
            caravan.device = Mock()
            caravan.config = SimpleNamespace(
                ResonanceTrade_SortBy='profit_per_fatigue',
                ResonanceTrade_RoundTrip=False,
                ResonanceTrade_RestockBooks=2,
                ResonanceTrade_BargainPercent=20,
                ResonanceTrade_RaisePercent=20,
                ResonanceTrade_ReturnBargain=False,
                ResonanceTrade_UseRamming=False,
                ResonanceTrade_UseFatigueItem=False,
                ResonanceTrade_ExcludedCities='武林源',
                ResonanceTrade_RefreshProfile=False,
                task_delay=Mock(),
            )
            caravan.ui_ensure = Mock()
            caravan.wait_until_docked = Mock()
            caravan.ensure_profile = Mock(return_value=profile)
            caravan.get_current_city = Mock(return_value='阿妮塔发射中心')
            # Fatigue checks: 1) before resume travel (enough), 2) after arrival sell in 岚心城 (exhausted)
            caravan._read_current_fatigue = Mock(side_effect=[(0, 912), (890, 912)])
            caravan.travel_to = Mock(return_value=True)
            caravan.sell_all = Mock(return_value=True)
            caravan.buy_plan = Mock()
            caravan.ui_goto_main = Mock()

            with patch('module.resonance.caravan.TRADE_STATE_PATH', state_path), \
                    patch('module.resonance.caravan.load_trade_state', side_effect=lambda p=state_path: load_trade_state(p)), \
                    patch('module.resonance.caravan.clear_trade_state', side_effect=lambda p=state_path: os.remove(p) if os.path.exists(p) else None), \
                    patch('module.resonance.caravan.fetch_prices', return_value=prices):
                caravan.run()

            # First action traveled straight to 岚心城 without selling back in 阿妮塔发射中心
            caravan.travel_to.assert_called_once_with('岚心城', use_ramming=False, configure_assist=True)
            caravan.sell_all.assert_called_once_with(raise_target=20)
            caravan.buy_plan.assert_not_called()
            self.assertTrue(caravan.config.task_delay.called)
            self.assertGreater(caravan.config.task_delay.call_args[1]['minute'], 0)

    def test_caravan_recovers_fatigue_with_item_and_continues(self):
        from module.resonance.caravan import ResonanceCaravan
        from module.resonance.columba import PRESTIGE_CITIES

        prices = _sample_prices()
        profile = {'maxLot': 994, 'prestige': {c: 20 for c in PRESTIGE_CITIES}, 'roles': {}}

        caravan = ResonanceCaravan.__new__(ResonanceCaravan)
        caravan.device = Mock()
        caravan.config = SimpleNamespace(
            ResonanceTrade_SortBy='profit',
            ResonanceTrade_RoundTrip=False,
            ResonanceTrade_RestockBooks=0,
            ResonanceTrade_BargainPercent=0,
            ResonanceTrade_RaisePercent=0,
            ResonanceTrade_UseRamming=True,
            ResonanceTrade_UseFatigueItem=True,
            ResonanceTrade_ExcludedCities='武林源',
            ResonanceTrade_RefreshProfile=False,
            task_delay=Mock(),
        )
        caravan.ui_ensure = Mock()
        caravan.wait_until_docked = Mock()
        caravan.ensure_profile = Mock(return_value=profile)
        caravan.get_current_city = Mock(return_value='阿妮塔发射中心')
        caravan.sell_all = Mock(return_value=False)
        caravan.buy_plan = Mock(return_value=True)
        caravan.travel_to = Mock(return_value=True)
        caravan.ui_goto_main = Mock()
        # First leg in 阿妮塔发射中心: fatigue 880/912 (only 32 left < needed 70+), recover_fatigue succeeds once,
        # second leg in 岚心城: fatigue 900/912 and recover_fatigue returns False -> schedules delay.
        caravan._read_current_fatigue = Mock(side_effect=[(880, 912), (900, 912)])
        caravan.recover_fatigue = Mock(side_effect=[True, False])

        with patch('module.resonance.caravan.load_trade_state', return_value={}), \
                patch('module.resonance.caravan.save_trade_state'), \
                patch('module.resonance.caravan.clear_trade_state'), \
                patch('module.resonance.caravan.fetch_prices', return_value=prices):
            caravan.run()

        self.assertEqual(caravan.recover_fatigue.call_count, 2)
        caravan.buy_plan.assert_called_once()
        caravan.travel_to.assert_called_once_with('岚心城', use_ramming=True, configure_assist=True)
        caravan.config.task_delay.assert_called_once()
        self.assertEqual(caravan.sell_all.call_args_list, [call(raise_target=0), call(raise_target=0)])

    def test_negotiation_policy_skips_misc_and_reposition_only_best_go(self):
        from module.resonance.caravan import ResonanceCaravan
        from module.resonance.columba import PRESTIGE_CITIES

        prices = _sample_prices()
        profile = {'maxLot': 994, 'prestige': {c: 20 for c in PRESTIGE_CITIES}, 'roles': {}}

        caravan = ResonanceCaravan.__new__(ResonanceCaravan)
        caravan.device = Mock()
        caravan.config = SimpleNamespace(
            ResonanceTrade_SortBy='profit',
            ResonanceTrade_RoundTrip=False,
            ResonanceTrade_RestockBooks=2,
            ResonanceTrade_BargainPercent=20,
            ResonanceTrade_RaisePercent=20,
            ResonanceTrade_ReturnBargain=False,
            ResonanceTrade_UseRamming=False,
            ResonanceTrade_UseFatigueItem=False,
            ResonanceTrade_ExcludedCities='武林源',
            ResonanceTrade_RefreshProfile=False,
            task_delay=Mock(),
        )
        caravan.ui_ensure = Mock()
        caravan.wait_until_docked = Mock()
        caravan.ensure_profile = Mock(return_value=profile)
        caravan.get_current_city = Mock(return_value='修格里城')
        caravan.sell_all = Mock(return_value=True)
        caravan.buy_plan = Mock(return_value=True)
        caravan.travel_to = Mock(return_value=True)
        caravan.ui_goto_main = Mock()
        # Leg 1 (reposition 修格里城->阿妮塔发射中心), Leg 2 (best go 阿妮塔发射中心->岚心城), Leg 3 (exhausted at 岚心城)
        caravan._read_current_fatigue = Mock(side_effect=[(0, 912), (200, 912), (890, 912)])

        with patch('module.resonance.caravan.load_trade_state', return_value={}), \
                patch('module.resonance.caravan.save_trade_state'), \
                patch('module.resonance.caravan.clear_trade_state'), \
                patch('module.resonance.caravan.fetch_prices', return_value=prices):
            caravan.run()

        # Sell calls: 1) initial misc cargo -> 0, 2) arrived reposition cargo -> 0, 3) arrived best go cargo -> 20
        self.assertEqual(caravan.sell_all.call_args_list, [
            call(raise_target=0),
            call(raise_target=0),
            call(raise_target=20),
        ])
        # Buy calls: 1) reposition buy -> 0, 2) best go buy -> 20
        self.assertEqual([c[1]['bargain_target'] for c in caravan.buy_plan.call_args_list], [0, 20])

    def test_manual_two_city_shuttle_and_rest_area_threshold(self):
        from module.resonance.caravan import ResonanceCaravan, plan_next_leg
        from module.resonance.columba import PRESTIGE_CITIES, load_columba_data

        data = load_columba_data()
        profile = {'maxLot': 994, 'prestige': {c: 20 for c in PRESTIGE_CITIES}, 'roles': {}}
        prices = _sample_prices()
        player_cfg = {
            'maxLot': 994,
            'prestige': profile['prestige'],
            'roles': {},
            'onegraph': {'maxRestock': 2, 'goAndReturn': False},
            'bargain': {'bargainPercent': 20, 'raisePercent': 20, 'disabled': False},
            'returnBargain': {'bargainPercent': 0, 'raisePercent': 0, 'disabled': True},
            'excludedCities': ['阿妮塔发射中心'],
        }

        # From outside city -> 0-restock reposition to closer of (阿妮塔发射中心, 岚心城)
        repo = plan_next_leg('修格里城', prices, player_cfg, 'profit', data, manual_cities=('阿妮塔发射中心', '岚心城'))
        self.assertTrue(repo['is_reposition'])
        self.assertEqual((repo['from_city'], repo['to_city']), ('修格里城', '阿妮塔发射中心'))
        self.assertEqual(repo['leg']['restock'], 0)

        # At city A -> buys profitable goods directly toward city B
        leg_a = plan_next_leg('阿妮塔发射中心', prices, player_cfg, 'profit', data, manual_cities=('阿妮塔发射中心', '岚心城'))
        self.assertFalse(leg_a['is_reposition'])
        self.assertFalse(leg_a['is_return'])
        self.assertEqual((leg_a['from_city'], leg_a['to_city']), ('阿妮塔发射中心', '岚心城'))
        self.assertGreater(leg_a['leg']['profit'], 0)

        # At city B -> goes back to city A respecting returnBargain
        leg_b = plan_next_leg('岚心城', prices, player_cfg, 'profit', data, manual_cities=('阿妮塔发射中心', '岚心城'))
        self.assertFalse(leg_b['is_reposition'])
        self.assertTrue(leg_b['is_return'])
        self.assertEqual((leg_b['from_city'], leg_b['to_city']), ('岚心城', '阿妮塔发射中心'))

        # Rest area check: skips below 300, travels to nearest rest area when >= 300
        caravan = ResonanceCaravan.__new__(ResonanceCaravan)
        caravan.device = Mock()
        caravan._read_current_fatigue = Mock(side_effect=[(299, 912), (350, 912)])
        caravan.sell_all = Mock()
        caravan.travel_to = Mock(return_value=True)
        caravan.drink_rest_area_soda = Mock(return_value=(6, False, (50, 912)))

        with patch('module.resonance.caravan.is_rest_area_done_today', return_value=False), \
                patch('module.resonance.caravan.clear_trade_state'), \
                patch('module.resonance.caravan.mark_rest_area_done') as mark_done:
            c1, a1 = caravan._maybe_drink_rest_area('阿妮塔战备工厂', player_cfg, {}, False, False, data)
            self.assertEqual((c1, a1), ('阿妮塔战备工厂', False))
            caravan.drink_rest_area_soda.assert_not_called()

            c2, a2 = caravan._maybe_drink_rest_area('阿妮塔战备工厂', player_cfg, {}, False, False, data)
            self.assertEqual((c2, a2), ('七号自由港', True))
            caravan.travel_to.assert_called_once_with('七号自由港', use_ramming=False, configure_assist=True)
            caravan.drink_rest_area_soda.assert_called_once_with(max_drinks=6)
            mark_done.assert_called_once()

    def test_caravan_market_filter_and_overflow_protection(self):
        from module.resonance.caravan import ResonanceCaravan
        from module.resonance.columba import PRESTIGE_CITIES

        prices = _sample_prices()
        profile = {'maxLot': 994, 'prestige': {c: 20 for c in PRESTIGE_CITIES}, 'roles': {}}

        def make_caravan(market_filter, overflow_protect, wait_min, cur_fatigue):
            caravan = ResonanceCaravan.__new__(ResonanceCaravan)
            caravan.device = Mock()
            caravan.config = SimpleNamespace(
                ResonanceTrade_SortBy='profit',
                ResonanceTrade_RoundTrip=False,
                ResonanceTrade_RestockBooks=0,
                ResonanceTrade_BargainPercent=0,
                ResonanceTrade_RaisePercent=0,
                ResonanceTrade_UseRamming=False,
                ResonanceTrade_UseFatigueItem='none',
                ResonanceTrade_UseBento=False,
                ResonanceTrade_ExcludedCities='武林源',
                ResonanceTrade_RefreshProfile=False,
                ResonanceTrade_MarketFilter=market_filter,
                ResonanceTrade_MarketOverflowProtect=overflow_protect,
                ResonanceTrade_MarketWaitMinutes=wait_min,
                task_delay=Mock(),
            )
            caravan.ui_ensure = Mock()
            caravan.wait_until_docked = Mock()
            caravan.ensure_profile = Mock(return_value=profile)
            caravan.get_current_city = Mock(return_value='阿妮塔发射中心')
            caravan.sell_all = Mock(return_value=True)
            caravan.buy_plan = Mock(return_value=True)
            caravan.travel_to = Mock(return_value=True)
            caravan.ui_goto_main = Mock()
            caravan._read_current_fatigue = Mock(side_effect=[(cur_fatigue, 912), (900, 912)])
            return caravan

        # 1) Cold market (<25), fatigue=200 -> sells arrived cargo first, then delays without buying
        c1 = make_caravan('good', True, 25, 200)
        with patch('module.resonance.caravan.load_trade_state', return_value={}), \
                patch('module.resonance.caravan.clear_trade_state'), \
                patch('module.resonance.caravan.fetch_prices', return_value=prices), \
                patch('module.resonance.caravan.evaluate_market_quality',
                      return_value={'index': 10.0, 'live': 12000, 'base': 11000, 'good': 21000, 'sort_by': 'profit', 'route': '阿妮塔发射中心 -> 岚心城'}):
            c1.run()
        c1.sell_all.assert_called_once()
        c1.buy_plan.assert_not_called()
        c1.travel_to.assert_not_called()
        c1.ui_goto_main.assert_called_once()
        c1.config.task_delay.assert_called_once_with(minute=25)
        self.assertEqual(self.mock_save_market_status.call_args[0][1]['status'], 'wait')
        self.assertTrue(self.mock_save_market_status.call_args[0][1]['next_check'])

        # 2) Cold market (<25), fatigue=50 <= 60, OverflowProtect=True -> runs to prevent fatigue overflow
        c2 = make_caravan('good', True, 25, 50)
        with patch('module.resonance.caravan.load_trade_state', return_value={}), \
                patch('module.resonance.caravan.save_trade_state'), \
                patch('module.resonance.caravan.clear_trade_state'), \
                patch('module.resonance.caravan.fetch_prices', return_value=prices), \
                patch('module.resonance.caravan.evaluate_market_quality',
                      return_value={'index': 10.0, 'live': 12000, 'base': 11000, 'good': 21000, 'sort_by': 'profit', 'route': '阿妮塔发射中心 -> 岚心城'}):
            c2.run()
        c2.buy_plan.assert_called_once()
        c2.travel_to.assert_called_once()
        self.assertEqual(self.mock_save_market_status.call_args_list[-2][0][1]['status'], 'overflow')

        # 3) Cold market (<25), fatigue=50 <= 60, OverflowProtect=False -> still delays
        c3 = make_caravan('good', False, 45, 50)
        with patch('module.resonance.caravan.load_trade_state', return_value={}), \
                patch('module.resonance.caravan.clear_trade_state'), \
                patch('module.resonance.caravan.fetch_prices', return_value=prices), \
                patch('module.resonance.caravan.evaluate_market_quality',
                      return_value={'index': 10.0, 'live': 12000, 'base': 11000, 'good': 21000, 'sort_by': 'profit', 'route': '阿妮塔发射中心 -> 岚心城'}):
            c3.run()
        c3.buy_plan.assert_not_called()
        c3.config.task_delay.assert_called_once_with(minute=45)
        self.assertEqual(self.mock_save_market_status.call_args[0][1]['status'], 'wait')

        # 4) Good market (>=25), fatigue=200 -> proceeds normally
        c4 = make_caravan('good', True, 25, 200)
        with patch('module.resonance.caravan.load_trade_state', return_value={}), \
                patch('module.resonance.caravan.save_trade_state'), \
                patch('module.resonance.caravan.clear_trade_state'), \
                patch('module.resonance.caravan.fetch_prices', return_value=prices), \
                patch('module.resonance.caravan.evaluate_market_quality',
                      return_value={'index': 32.5, 'live': 14250, 'base': 11000, 'good': 21000, 'sort_by': 'profit', 'route': '阿妮塔发射中心 -> 岚心城'}):
            c4.run()
        c4.buy_plan.assert_called_once()
        c4.travel_to.assert_called_once()
        self.assertEqual(self.mock_save_market_status.call_args_list[-1][0][1]['status'], 'pass')

    def test_reposition_excludes_negotiation_only_goods(self):
        from module.resonance.caravan import build_player_config, plan_next_leg
        from module.resonance.columba import PRESTIGE_CITIES, load_columba_data

        data = load_columba_data()
        profile = {'maxLot': 994, 'prestige': {c: 20 for c in PRESTIGE_CITIES}, 'roles': {}}
        cfg = SimpleNamespace(
            ResonanceTrade_SortBy='profit',
            ResonanceTrade_RoundTrip=False,
            ResonanceTrade_RestockBooks=2,
            ResonanceTrade_BargainPercent=20,
            ResonanceTrade_RaisePercent=20,
            ResonanceTrade_ReturnBargain=False,
            ResonanceTrade_ExcludedCities='武林源',
        )
        player_cfg = build_player_config(profile, cfg, data)

        anita_prod = next(p['name'] for p in data['products_by_city']['阿妮塔发射中心'] if p.get('type') != 'Craft')
        shug_prods = [p['name'] for p in data['products_by_city']['修格里城'] if p.get('type') != 'Craft']
        neg_only_good, safe_good = shug_prods[0], shug_prods[1]
        prices = {
            anita_prod: {
                'buy': {'阿妮塔发射中心': {'price': 500, 'variation': 80, 'trend': 'down', 'time': 0}},
                'sell': {'岚心城': {'price': 15000, 'variation': 150, 'trend': 'up', 'time': 0}},
            },
            # Profitable only under 20% bargain + 20% raise, money-losing at 0% + 0%
            neg_only_good: {
                'buy': {'修格里城': {'price': 1000, 'variation': 100, 'trend': 'same', 'time': 0}},
                'sell': {'阿妮塔发射中心': {'price': 1000, 'variation': 100, 'trend': 'same', 'time': 0}},
            },
            # Still profitable at 0% + 0%
            safe_good: {
                'buy': {'修格里城': {'price': 400, 'variation': 90, 'trend': 'down', 'time': 0}},
                'sell': {'阿妮塔发射中心': {'price': 900, 'variation': 120, 'trend': 'up', 'time': 0}},
            },
        }

        repo = plan_next_leg('修格里城', prices, player_cfg, 'profit', data)
        self.assertTrue(repo['is_reposition'])
        self.assertEqual((repo['from_city'], repo['to_city']), ('修格里城', '阿妮塔发射中心'))
        bought_names = [item['name'] for item in repo['leg']['combinations']]
        self.assertEqual(bought_names, [safe_good])
        self.assertNotIn(neg_only_good, bought_names)
        self.assertLess(repo['leg']['combinations'][0]['single_profit'], 600)
