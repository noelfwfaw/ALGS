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

    def test_buy_checkpoint_survives_new_object_and_records_actual_book_usage(self):
        from module.resonance.caravan import ResonanceCaravan, load_trade_state, save_trade_state

        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, 'trade_state.json')
            buyer = ResonanceCaravan.__new__(ResonanceCaravan)
            buyer.config = SimpleNamespace(config_name='TEST')
            buyer._last_restock_used = 1
            state = {}
            plan = {'to_city': 'B', 'leg': {'profit': 120, 'restock': 3}}
            with patch('module.resonance.caravan.save_trade_state',
                       side_effect=lambda *a, **kw: save_trade_state(*a, path=state_path, **kw)):
                buyer._finish_bought_leg('A', plan, state, 0, False, None, 'auto', 'TEST')

            pending = load_trade_state(state_path)
            self.assertEqual(pending['restock_used'], 1)
            self.assertEqual(state['restock_used'], 1)

            seller = ResonanceCaravan.__new__(ResonanceCaravan)
            seller.config = SimpleNamespace(config_name='TEST')
            seller.sell_all = Mock(return_value=True)
            seller._last_sell_image = object()
            with patch('module.resonance.caravan.read_sell_profit', side_effect=[120, None]):
                self.assertTrue(seller._sell_and_record_profit('B', pending, raise_target=0))
                self.assertTrue(seller._sell_and_record_profit('B', pending, raise_target=0))

            self.assertEqual(self.mock_record_trade_profit.call_args_list, [
                call('TEST', 120, from_city='A', to_city='B', estimated=False, restock_used=1),
                call('TEST', 120, from_city='A', to_city='B', estimated=True, restock_used=1),
            ])

    def test_pending_checkpoint_distinguishes_legacy_unknown_from_zero_books(self):
        from module.resonance.caravan import ResonanceCaravan

        seller = ResonanceCaravan.__new__(ResonanceCaravan)
        seller.config = SimpleNamespace(config_name='TEST')
        seller.sell_all = Mock(return_value=True)
        seller._last_sell_image = object()
        legacy = {'bought_city': 'A', 'target_city': 'B', 'expected_profit': 120}
        zero = dict(legacy, restock_used=0)

        for state, expected in ((legacy, None), (zero, 0)):
            with self.subTest(restock_used=expected):
                self.mock_record_trade_profit.reset_mock()
                with patch('module.resonance.caravan.read_sell_profit', return_value=None):
                    self.assertTrue(seller._sell_and_record_profit('B', state, raise_target=0))
                self.mock_record_trade_profit.assert_called_once_with(
                    'TEST', 120, from_city='A', to_city='B', estimated=True, restock_used=expected,
                )

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

    def test_unreadable_fatigue_delays_without_overflow_bypass_or_buying(self):
        from module.resonance.caravan import ResonanceCaravan
        from module.resonance.columba import PRESTIGE_CITIES

        prices = _sample_prices()
        profile = {'maxLot': 994, 'prestige': {c: 20 for c in PRESTIGE_CITIES}, 'roles': {}}

        probe = ResonanceCaravan.__new__(ResonanceCaravan)
        probe.device = Mock()
        probe.enter_exchange = Mock()
        probe.read_fatigue = Mock(return_value=None)
        self.assertIsNone(probe._read_current_fatigue({}))
        probe.enter_exchange.assert_called_once()
        self.assertEqual(probe.read_fatigue.call_count, 4)
        self.assertEqual(probe.device.screenshot.call_count, 2)

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
            ResonanceTrade_MarketFilter='good',
            ResonanceTrade_MarketOverflowProtect=True,
            ResonanceTrade_MarketWaitMinutes=30,
            task_delay=Mock(),
        )
        caravan.ui_ensure = Mock()
        caravan.wait_until_docked = Mock()
        caravan.ensure_profile = Mock(return_value=profile)
        caravan.get_current_city = Mock(return_value='阿妮塔发射中心')
        caravan.sell_all = Mock(return_value=False)
        caravan.buy_plan = Mock()
        caravan.travel_to = Mock()
        caravan.ui_goto_main = Mock()
        caravan._read_current_fatigue = Mock(return_value=None)

        with patch('module.resonance.caravan.load_trade_state', return_value={}), \
                patch('module.resonance.caravan.clear_trade_state'), \
                patch('module.resonance.caravan.fetch_prices', return_value=prices):
            caravan.run()

        caravan.buy_plan.assert_not_called()
        caravan.travel_to.assert_not_called()
        caravan.ui_goto_main.assert_called_once()
        caravan.config.task_delay.assert_called_once_with(minute=10)

    def test_atomic_fatigue_gate_blocks_before_buying_and_reserves_drive_plus_sell(self):
        from module.resonance.caravan import ResonanceCaravan
        from module.resonance.columba import PRESTIGE_CITIES

        prices = _sample_prices()
        profile = {'maxLot': 994, 'prestige': {c: 20 for c in PRESTIGE_CITIES}, 'roles': {}}

        def make_caravan(fatigue_seq):
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
                ResonanceTrade_UseFatigueItem='none',
                ResonanceTrade_UseBento=False,
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
            caravan._read_current_fatigue = Mock(side_effect=fatigue_seq)
            return caravan

        # remaining=100 (< atomic 71+44+44+4=163) must stop BEFORE buying or using restock books
        c_low = make_caravan([(812, 912)])
        with patch('module.resonance.caravan.load_trade_state', return_value={}), \
                patch('module.resonance.caravan.clear_trade_state'), \
                patch('module.resonance.caravan.fetch_prices', return_value=prices):
            c_low.run()
        c_low.buy_plan.assert_not_called()
        c_low.travel_to.assert_not_called()
        c_low.config.task_delay.assert_called_once()

        # remaining=200 (>= 163) runs leg and passes reserve_fatigue = drive(71) + sell(44) + buf(4) = 119
        c_ok = make_caravan([(712, 912), (890, 912)])
        with patch('module.resonance.caravan.load_trade_state', return_value={}), \
                patch('module.resonance.caravan.save_trade_state'), \
                patch('module.resonance.caravan.clear_trade_state'), \
                patch('module.resonance.caravan.fetch_prices', return_value=prices):
            c_ok.run()
        c_ok.buy_plan.assert_called_once()
        self.assertEqual(c_ok.buy_plan.call_args[1]['reserve_fatigue'], 119)
        c_ok.travel_to.assert_called_once()

    def _wilderness_leg_opts(self, data, route_mode='auto'):
        return (
            'profit', 20, 20, False, False, 'none', False, False, False, {}, route_mode, None, False,
            ('all', False, 30), data,
        )

    def _wilderness_plan(self, origin='阿妮塔发射中心', target='岚心城', combinations=None):
        return {
            'from_city': origin, 'to_city': target,
            'leg': {'fatigue': 71, 'profit': 120, 'restock': 2,
                    'combinations': [{'name': 'test_good'}] if combinations is None else combinations},
            'is_reposition': False, 'is_return': False,
        }

    def test_manual_crossing_stops_once_and_preserves_original_trade_state(self):
        from module.resonance.caravan import ResonanceCaravan, _calc_fatigue, safe_negotiation_budget
        from module.resonance.columba import load_columba_data

        data = load_columba_data()
        caravan = ResonanceCaravan.__new__(ResonanceCaravan)
        caravan.config = SimpleNamespace(config_name='TEST', ResonanceTrade_RecycleAtWilderness=True,
                                         ResonanceTrade_RaisePercent=20, task_delay=Mock())
        caravan.sell_all = Mock(return_value=False)
        caravan.buy_plan = Mock(return_value=True)
        caravan._last_restock_used = 1
        caravan._read_current_fatigue = Mock(return_value=(0, 912))
        caravan._check_market_gate = Mock(return_value=True)
        caravan._plan_leg_for_mode = Mock(return_value=self._wilderness_plan())
        caravan._garbage_cleaned_today = Mock(return_value=False)
        caravan.recycle_wilderness_garbage = Mock(return_value=True)
        caravan._mark_garbage_cleaned = Mock()
        caravan.get_current_city = Mock(side_effect=['荒原站', '岚心城'])
        caravan.travel_to = Mock(return_value=True)
        caravan.ui_goto_main = Mock()
        state = {}

        with patch('module.resonance.caravan.save_trade_state') as save_state:
            next_city, _ = caravan._execute_one_leg('阿妮塔发射中心', {}, {'roles': {}}, state,
                                                    self._wilderness_leg_opts(data, route_mode='manual'))

        self.assertEqual(next_city, '岚心城')
        self.assertEqual(caravan.travel_to.call_args_list, [
            call('荒原站', use_ramming=False, configure_assist=True),
            call('岚心城', use_ramming=False, configure_assist=False),
        ])
        caravan.sell_all.assert_called_once_with(raise_target=0)  # only the initial dock sale
        caravan.buy_plan.assert_called_once()
        caravan.recycle_wilderness_garbage.assert_called_once_with()
        caravan._mark_garbage_cleaned.assert_called_once_with('TEST')
        split_drive = (_calc_fatigue('阿妮塔发射中心', '荒原站', {}, data)
                       + _calc_fatigue('荒原站', '岚心城', {}, data))
        self.assertEqual(caravan.buy_plan.call_args[1]['reserve_fatigue'],
                         split_drive + safe_negotiation_budget(20) + 4)
        self.assertEqual(state, {
            'bought_city': '阿妮塔发射中心', 'target_city': '岚心城', 'negotiate_sell': True,
            'expected_profit': 120, 'sell_raise_target': 20, 'restock_used': 1,
            'via_wilderness': True, 'wilderness_done': True,
        })
        self.assertEqual(save_state.call_count, 2)  # post-buy checkpoint, then completed wilderness stop
        self.assertTrue(save_state.call_args_list[-1][1]['wilderness_done'])

    def test_wilderness_split_fatigue_blocks_before_buy_when_direct_leg_would_fit(self):
        from module.resonance.caravan import ResonanceCaravan, _calc_fatigue
        from module.resonance.columba import load_columba_data

        data = load_columba_data()
        split_drive = (_calc_fatigue('阿妮塔发射中心', '荒原站', {}, data)
                       + _calc_fatigue('荒原站', '岚心城', {}, data))
        self.assertGreater(split_drive, 71)
        caravan = ResonanceCaravan.__new__(ResonanceCaravan)
        caravan.config = SimpleNamespace(config_name='TEST', ResonanceTrade_RecycleAtWilderness=True,
                                         ResonanceTrade_RaisePercent=20, task_delay=Mock())
        caravan.sell_all = Mock(return_value=False)
        caravan.buy_plan = Mock(return_value=True)
        caravan._read_current_fatigue = Mock(return_value=(737, 912))  # 175: direct needs 163, split needs 182
        caravan._check_market_gate = Mock(return_value=True)
        caravan._plan_leg_for_mode = Mock(return_value=self._wilderness_plan())
        caravan._garbage_cleaned_today = Mock(return_value=False)
        caravan._schedule_fatigue_wait = Mock()
        caravan.travel_to = Mock()

        with patch('module.resonance.caravan.save_trade_state'):
            result = caravan._execute_one_leg('阿妮塔发射中心', {}, {'roles': {}}, {},
                                              self._wilderness_leg_opts(data))

        self.assertEqual(result, (None, False))
        caravan.buy_plan.assert_not_called()
        caravan.travel_to.assert_not_called()
        self.assertEqual(caravan._schedule_fatigue_wait.call_args[0][2], split_drive + 44 + 44 + 4)

    def test_switch_off_skips_cleanup_and_keeps_direct_travel(self):
        from module.resonance.caravan import ResonanceCaravan
        from module.resonance.columba import load_columba_data

        data = load_columba_data()
        caravan = ResonanceCaravan.__new__(ResonanceCaravan)
        caravan.config = SimpleNamespace(config_name='TEST', ResonanceTrade_RecycleAtWilderness=False,
                                         ResonanceTrade_RaisePercent=20, task_delay=Mock())
        caravan.sell_all = Mock(return_value=False)
        caravan.buy_plan = Mock(return_value=False)
        caravan._read_current_fatigue = Mock(return_value=(0, 912))
        caravan._check_market_gate = Mock(return_value=True)
        caravan._plan_leg_for_mode = Mock(return_value=self._wilderness_plan(combinations=[]))
        caravan._garbage_cleaned_today = Mock()
        caravan.recycle_wilderness_garbage = Mock()
        caravan.get_current_city = Mock()
        caravan.travel_to = Mock(return_value=True)
        state = {}

        with patch('module.resonance.caravan.save_trade_state') as save_state:
            next_city, _ = caravan._execute_one_leg('阿妮塔发射中心', {}, {'roles': {}}, state,
                                                    self._wilderness_leg_opts(data))

        self.assertEqual(next_city, '岚心城')
        caravan.travel_to.assert_called_once_with('岚心城', use_ramming=False, configure_assist=True)
        caravan._garbage_cleaned_today.assert_not_called()
        caravan.recycle_wilderness_garbage.assert_not_called()
        caravan.get_current_city.assert_not_called()
        self.assertEqual(state, {})
        save_state.assert_not_called()

    def test_already_docked_at_wilderness_cleans_before_empty_departure(self):
        from module.resonance.caravan import ResonanceCaravan
        from module.resonance.columba import load_columba_data

        data = load_columba_data()
        events = []
        caravan = ResonanceCaravan.__new__(ResonanceCaravan)
        caravan.config = SimpleNamespace(config_name='TEST', ResonanceTrade_RecycleAtWilderness=True,
                                         ResonanceTrade_RaisePercent=20, task_delay=Mock())
        caravan.sell_all = Mock(return_value=False)
        caravan.buy_plan = Mock()
        caravan._read_current_fatigue = Mock(return_value=(0, 912))
        caravan._check_market_gate = Mock(return_value=True)
        caravan._plan_leg_for_mode = Mock(return_value=self._wilderness_plan('荒原站', '岚心城', combinations=[]))
        caravan._garbage_cleaned_today = Mock(return_value=False)
        caravan.recycle_wilderness_garbage = Mock(side_effect=lambda: events.append('clean') or True)
        caravan._mark_garbage_cleaned = Mock()
        caravan.get_current_city = Mock(return_value='荒原站')
        caravan.travel_to = Mock(side_effect=lambda city, **kw: events.append(city) or True)
        state = {}

        with patch('module.resonance.caravan.save_trade_state') as save_state:
            next_city, _ = caravan._execute_one_leg('荒原站', {}, {'roles': {}}, state,
                                                    self._wilderness_leg_opts(data))

        self.assertEqual(next_city, '岚心城')
        self.assertEqual(events, ['clean', '岚心城'])
        self.assertEqual(state, {})
        self.assertEqual(save_state.call_count, 0)
        caravan._mark_garbage_cleaned.assert_called_once_with('TEST')

    def test_wilderness_cleanup_failure_retries_without_marking_or_losing_pending_state(self):
        from module.exception import TaskFailed
        from module.resonance.caravan import ResonanceCaravan, load_trade_state, save_trade_state

        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, 'trade_state.json')
            save_trade_state('阿妮塔发射中心', '岚心城', negotiate_sell=True, expected_profit=120,
                             sell_raise_target=20, restock_used=2, path=state_path, via_wilderness=True)
            pending = load_trade_state(state_path)
            caravan = ResonanceCaravan.__new__(ResonanceCaravan)
            caravan.config = SimpleNamespace(config_name='TEST', ResonanceTrade_RecycleAtWilderness=True, task_delay=Mock())
            caravan._garbage_cleaned_today = Mock(return_value=False)
            caravan.recycle_wilderness_garbage = Mock(return_value=False)
            caravan._mark_garbage_cleaned = Mock()
            caravan.get_current_city = Mock(return_value='荒原站')
            caravan.ui_goto_main = Mock()

            with patch('module.resonance.caravan.save_trade_state',
                       side_effect=lambda *a, **kw: save_trade_state(*a, path=state_path, **kw)), \
                    self.assertRaises(TaskFailed):
                caravan._finish_wilderness_stop(pending, 'TEST')

            self.assertEqual(caravan.recycle_wilderness_garbage.call_count, 2)
            caravan._mark_garbage_cleaned.assert_not_called()
            caravan.config.task_delay.assert_called_once_with(minute=10)
            reloaded = load_trade_state(state_path)
            self.assertTrue(reloaded['via_wilderness'])
            self.assertFalse(reloaded['wilderness_done'])
            self.assertEqual(reloaded['restock_used'], 2)
            self.assertEqual(reloaded['target_city'], '岚心城')

    def test_pending_empty_transit_resumes_from_wilderness_without_reselling_or_recleaning(self):
        from module.resonance.caravan import ResonanceCaravan, load_trade_state, save_trade_state
        from module.resonance.columba import load_columba_data

        data = load_columba_data()
        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, 'trade_state.json')
            save_trade_state('阿妮塔发射中心', '岚心城', path=state_path, via_wilderness=True)
            pending = load_trade_state(state_path)
            caravan = ResonanceCaravan.__new__(ResonanceCaravan)
            caravan.config = SimpleNamespace(config_name='TEST', ResonanceTrade_RecycleAtWilderness=False,
                                             ResonanceTrade_RaisePercent=20, task_delay=Mock())
            caravan._read_current_fatigue = Mock(return_value=(0, 912))
            caravan.recycle_wilderness_garbage = Mock()
            caravan._mark_garbage_cleaned = Mock()
            caravan.get_current_city = Mock(side_effect=['荒原站', '岚心城'])
            caravan.travel_to = Mock(return_value=True)
            caravan.sell_all = Mock()
            caravan.buy_plan = Mock()

            with patch('module.resonance.caravan.save_trade_state',
                       side_effect=lambda *a, **kw: save_trade_state(*a, path=state_path, **kw)):
                result = caravan._resume_pending_transit('荒原站', pending, False, 'none', False, data)

            self.assertEqual(result, ('岚心城', True))
            caravan.travel_to.assert_called_once_with('岚心城', use_ramming=False, configure_assist=True)
            caravan.sell_all.assert_not_called()
            caravan.buy_plan.assert_not_called()
            caravan.recycle_wilderness_garbage.assert_not_called()
            reloaded = load_trade_state(state_path)
            self.assertTrue(reloaded['wilderness_done'])
            self.assertEqual(reloaded['target_city'], '岚心城')

            caravan.recycle_wilderness_garbage.reset_mock()
            caravan.travel_to.reset_mock()
            caravan.get_current_city.reset_mock(side_effect=True)
            caravan.get_current_city.side_effect = ['岚心城']
            caravan._resume_pending_transit('荒原站', reloaded, False, 'none', False, data)
            caravan.recycle_wilderness_garbage.assert_not_called()
            caravan.travel_to.assert_called_once_with('岚心城', use_ramming=False, configure_assist=True)

            legacy_direct = dict(reloaded, via_wilderness=False, wilderness_done=False)
            caravan.travel_to.reset_mock()
            caravan.get_current_city.reset_mock()
            with patch('module.resonance.caravan.save_trade_state') as save_state:
                self.assertEqual(caravan._resume_pending_transit('荒原站', legacy_direct, False, 'none', False, data),
                                 ('荒原站', False))
            caravan.sell_all.assert_not_called()
            caravan.travel_to.assert_not_called()
            caravan.get_current_city.assert_not_called()
            save_state.assert_not_called()

            wilderness_target = dict(reloaded, target_city='荒原站', via_wilderness=False, wilderness_done=False)
            with patch('module.resonance.caravan.save_trade_state') as save_state:
                self.assertEqual(caravan._resume_pending_transit('荒原站', wilderness_target, False, 'none', False, data),
                                 ('荒原站', False))
            caravan.travel_to.assert_not_called()
            caravan.get_current_city.assert_not_called()
            save_state.assert_not_called()

    def test_pending_committed_transit_keeps_wilderness_after_switch_off(self):
        from module.resonance.caravan import ResonanceCaravan
        from module.resonance.columba import load_columba_data
        from module.resonance.route import _calc_fatigue
        from module.resonance.smart_state import DRIVE_FATIGUE_BUFFER, safe_negotiation_budget

        data = load_columba_data()
        caravan = ResonanceCaravan.__new__(ResonanceCaravan)
        caravan.config = SimpleNamespace(config_name='TEST', ResonanceTrade_RecycleAtWilderness=False,
                                         ResonanceTrade_RaisePercent=20, task_delay=Mock())
        caravan._read_current_fatigue = Mock(return_value=(0, 912))
        caravan._ensure_fatigue_for_leg = Mock(return_value=True)
        caravan.get_current_city = Mock(side_effect=['荒原站', '岚心城'])
        caravan.travel_to = Mock(return_value=True)
        caravan.sell_all = Mock()
        caravan.buy_plan = Mock()
        caravan.recycle_wilderness_garbage = Mock()
        caravan._garbage_cleaned_today = Mock()
        state = {'bought_city': '阿妮塔发射中心', 'target_city': '岚心城', 'negotiate_sell': True,
                 'expected_profit': 120, 'sell_raise_target': 20, 'restock_used': 2,
                 'via_wilderness': True, 'wilderness_done': False}

        with patch('module.resonance.caravan.save_trade_state') as save_state:
            result = caravan._resume_pending_transit('阿妮塔发射中心', state, True, 'none', False, data)

        self.assertEqual(result, ('岚心城', True))
        self.assertEqual(caravan.travel_to.call_args_list, [
            call('荒原站', use_ramming=True, configure_assist=True),
            call('岚心城', use_ramming=True, configure_assist=False),
        ])
        split_drive = (_calc_fatigue('阿妮塔发射中心', '荒原站', {}, data)
                       + _calc_fatigue('荒原站', '岚心城', {}, data))
        self.assertEqual(caravan._ensure_fatigue_for_leg.call_args_list[0], call(
            0, 912, split_drive + safe_negotiation_budget(20) + DRIVE_FATIGUE_BUFFER, 'none', False))
        self.assertEqual(caravan._ensure_fatigue_for_leg.call_count, 2)
        caravan.sell_all.assert_not_called()
        caravan.buy_plan.assert_not_called()
        caravan.recycle_wilderness_garbage.assert_not_called()
        caravan._garbage_cleaned_today.assert_not_called()
        self.assertEqual(state['target_city'], '岚心城')
        self.assertEqual(state['restock_used'], 2)
        self.assertTrue(save_state.call_args[1]['via_wilderness'])
        self.assertTrue(save_state.call_args[1]['wilderness_done'])

    def test_pending_direct_legacy_resume_keeps_old_gate_without_arrival_ocr_or_state_write(self):
        from module.resonance.caravan import ResonanceCaravan
        from module.resonance.columba import load_columba_data
        from module.resonance.route import _calc_fatigue
        from module.resonance.smart_state import DRIVE_FATIGUE_BUFFER

        data = load_columba_data()
        caravan = ResonanceCaravan.__new__(ResonanceCaravan)
        caravan.config = SimpleNamespace(config_name='TEST', ResonanceTrade_RecycleAtWilderness=False,
                                         ResonanceTrade_RaisePercent=20, task_delay=Mock())
        caravan._read_current_fatigue = Mock(return_value=(0, 912))
        caravan._ensure_fatigue_for_leg = Mock(return_value=True)
        caravan.get_current_city = Mock()
        caravan.travel_to = Mock(return_value=True)
        state = {'bought_city': '阿妮塔发射中心', 'target_city': '岚心城', 'negotiate_sell': True,
                 'expected_profit': 120, 'sell_raise_target': 20, 'restock_used': 2,
                 'via_wilderness': False, 'wilderness_done': False}

        with patch('module.resonance.caravan.save_trade_state') as save_state:
            result = caravan._resume_pending_transit('阿妮塔发射中心', state, True, 'none', False, data,
                                                     player_cfg={'roles': {}})

        self.assertEqual(result, ('岚心城', True))
        caravan.travel_to.assert_called_once_with('岚心城', use_ramming=True, configure_assist=True)
        caravan._ensure_fatigue_for_leg.assert_called_once_with(
            0, 912, _calc_fatigue('阿妮塔发射中心', '岚心城', {}, data) + DRIVE_FATIGUE_BUFFER,
            'none', False)
        caravan.get_current_city.assert_not_called()
        save_state.assert_not_called()
        self.assertEqual(state['restock_used'], 2)
        self.assertFalse(state['via_wilderness'])

    def test_pending_cargo_at_unexpected_city_is_not_sold(self):
        from module.exception import TaskFailed
        from module.resonance.caravan import ResonanceCaravan
        from module.resonance.columba import load_columba_data

        caravan = ResonanceCaravan.__new__(ResonanceCaravan)
        caravan.config = SimpleNamespace(config_name='TEST', task_delay=Mock())
        caravan.ui_goto_main = Mock()
        caravan.sell_all = Mock()
        state = {'bought_city': '阿妮塔发射中心', 'target_city': '岚心城', 'expected_profit': 120}
        with self.assertRaises(TaskFailed):
            caravan._execute_one_leg('曼德矿场', {}, {'roles': {}}, state,
                                     self._wilderness_leg_opts(load_columba_data()))
        caravan.sell_all.assert_not_called()
        caravan.config.task_delay.assert_called_once_with(minute=10)
        self.assertEqual(state['target_city'], '岚心城')

    def test_wilderness_as_real_destination_cleans_before_selling(self):
        from module.resonance.caravan import ResonanceCaravan
        from module.resonance.columba import load_columba_data

        data = load_columba_data()
        events = []
        caravan = ResonanceCaravan.__new__(ResonanceCaravan)
        caravan.config = SimpleNamespace(config_name='TEST', ResonanceTrade_RecycleAtWilderness=True,
                                         ResonanceTrade_RaisePercent=20, task_delay=Mock())
        caravan._garbage_cleaned_today = Mock(return_value=False)
        caravan.recycle_wilderness_garbage = Mock(side_effect=lambda: events.append('clean') or True)
        caravan._mark_garbage_cleaned = Mock()
        caravan.get_current_city = Mock(return_value='荒原站')
        caravan.sell_all = Mock(side_effect=lambda **kw: events.append('sell') or True)
        caravan._last_sell_image = object()
        caravan._read_current_fatigue = Mock(return_value=(0, 912))
        caravan._check_market_gate = Mock(return_value=False)
        caravan.buy_plan = Mock()
        caravan.travel_to = Mock()
        state = {'bought_city': '阿妮塔发射中心', 'target_city': '荒原站', 'negotiate_sell': True,
                 'expected_profit': 120, 'sell_raise_target': 20, 'restock_used': 2}

        with patch('module.resonance.caravan.read_sell_profit', return_value=120), \
                patch('module.resonance.caravan.clear_trade_state'):
            result = caravan._execute_one_leg('荒原站', {}, {'roles': {}}, state,
                                              self._wilderness_leg_opts(data))

        self.assertEqual(result, (None, False))
        self.assertEqual(events, ['clean', 'sell'])
        caravan.sell_all.assert_called_once_with(raise_target=20)
        caravan.buy_plan.assert_not_called()
        caravan.travel_to.assert_not_called()
        self.assertEqual(state, {})

    def test_smart_endgame_rechecks_crossing_and_uses_split_fatigue_budget(self):
        from module.resonance.caravan import ResonanceCaravan, _calc_fatigue, leg_atomic_fatigue_budget
        from module.resonance.columba import load_columba_data

        data = load_columba_data()
        initial = self._wilderness_plan('阿妮塔发射中心', '曼德矿场')
        initial.update({'is_smart_cycle': True, 'bargain_target': 0, 'raise_target': 0,
                        'atomic_fatigue': leg_atomic_fatigue_budget(71, 0, 0),
                        'cycle': {'book_weight': 30, 'neg_fatigue': None}})
        endgame = self._wilderness_plan()
        endgame.update({'is_smart_cycle': True, 'bargain_target': 20, 'raise_target': 20,
                        'expected_neg_fatigue': 1, 'atomic_fatigue': leg_atomic_fatigue_budget(71, 20, 20),
                        'cycle': {'book_weight': 30, 'neg_fatigue': None}})
        caravan = ResonanceCaravan.__new__(ResonanceCaravan)
        caravan.config = SimpleNamespace(config_name='TEST', ResonanceTrade_RecycleAtWilderness=True,
                                         ResonanceTrade_RaisePercent=20, task_delay=Mock())
        caravan.sell_all = Mock(return_value=False)
        caravan.buy_plan = Mock(return_value=True)
        caravan._last_restock_used = 1
        caravan._read_current_fatigue = Mock(return_value=(0, 912))
        caravan._check_market_gate = Mock(return_value=True)
        caravan._plan_leg_for_mode = Mock(return_value=initial)
        caravan._garbage_cleaned_today = Mock(return_value=False)
        caravan.recycle_wilderness_garbage = Mock(return_value=True)
        caravan._mark_garbage_cleaned = Mock()
        caravan.get_current_city = Mock(side_effect=['荒原站', '岚心城'])
        caravan.travel_to = Mock(return_value=True)
        caravan._has_or_recover_fatigue = Mock(side_effect=[False, True, True])
        state = {}

        with patch('module.resonance.caravan.plan_smart_endgame_leg', return_value=endgame), \
                patch('module.resonance.caravan.save_trade_state'):
            next_city, _ = caravan._execute_one_leg('阿妮塔发射中心', {}, {'roles': {}}, state,
                                                    self._wilderness_leg_opts(data, route_mode='smart_cycle'))

        self.assertEqual(next_city, '岚心城')
        split_drive = (_calc_fatigue('阿妮塔发射中心', '荒原站', {}, data)
                       + _calc_fatigue('荒原站', '岚心城', {}, data))
        self.assertEqual(caravan._has_or_recover_fatigue.call_args_list[1][0][2],
                         leg_atomic_fatigue_budget(split_drive, 20, 20))
        self.assertTrue(state['via_wilderness'])
        self.assertEqual([c[0][0] for c in caravan.travel_to.call_args_list], ['荒原站', '岚心城'])

    def _wilderness_caravan(self):
        from module.resonance.caravan import ResonanceCaravan

        caravan = ResonanceCaravan.__new__(ResonanceCaravan)
        caravan.config = SimpleNamespace(config_name='TEST', ResonanceTrade_RecycleAtWilderness=True,
                                         ResonanceTrade_RaisePercent=20, task_delay=Mock())
        caravan.sell_all = Mock(return_value=False)
        caravan.buy_plan = Mock(return_value=True)
        caravan._last_restock_used = 1
        caravan._read_current_fatigue = Mock(return_value=(0, 912))
        caravan._check_market_gate = Mock(return_value=True)
        caravan._plan_leg_for_mode = Mock(return_value=self._wilderness_plan())
        caravan._garbage_cleaned_today = Mock(return_value=False)
        caravan.recycle_wilderness_garbage = Mock(return_value=True)
        caravan._mark_garbage_cleaned = Mock()
        caravan.get_current_city = Mock(side_effect=['荒原站', '岚心城'])
        caravan.travel_to = Mock(return_value=True)
        caravan.ui_goto_main = Mock()
        return caravan

    def test_run_cleans_initial_wilderness_before_rest_area_departure(self):
        from module.exception import TaskFailed
        from module.resonance.caravan import ResonanceCaravan
        from module.resonance.columba import PRESTIGE_CITIES, load_columba_data
        from module.resonance.fatigue import nearest_rest_area_city

        data = load_columba_data()
        profile = {'maxLot': 994, 'prestige': {c: 20 for c in PRESTIGE_CITIES}, 'roles': {}}
        rest_city = nearest_rest_area_city('荒原站', {}, data)[0]

        for cleanup_ok in (True, False):
            with self.subTest(cleanup_ok=cleanup_ok):
                events = []
                caravan = ResonanceCaravan.__new__(ResonanceCaravan)
                caravan.config = SimpleNamespace(
                    config_name='TEST', ResonanceTrade_RecycleAtWilderness=True,
                    ResonanceTrade_UseRestArea=True, ResonanceTrade_UseFatigueItem='none',
                    ResonanceTrade_UseBento=False, ResonanceTrade_RefreshProfile=False,
                    ResonanceTrade_MarketFilter='all', ResonanceTrade_MarketOverflowProtect=False,
                    ResonanceTrade_MarketWaitMinutes=30, ResonanceTrade_RaisePercent=20, task_delay=Mock(),
                )
                caravan.ui_ensure = Mock()
                caravan.wait_until_docked = Mock()
                caravan.ensure_profile = Mock(return_value=profile)
                caravan.get_current_city = Mock(return_value='荒原站')
                caravan._garbage_cleaned_today = Mock(return_value=False)
                caravan.recycle_wilderness_garbage = Mock(side_effect=lambda: events.append('clean') or cleanup_ok)
                caravan._mark_garbage_cleaned = Mock()
                caravan._read_current_fatigue = Mock(side_effect=[(350, 912), (350, 912)])
                caravan.sell_all = Mock(return_value=False)
                caravan.travel_to = Mock(side_effect=lambda city, **kw: events.append(city) or True)
                caravan.drink_rest_area_soda = Mock(return_value=(6, False, (50, 912)))
                caravan._check_market_gate = Mock(return_value=False)
                caravan.ui_goto_main = Mock()

                with patch('module.resonance.caravan.load_trade_state', return_value={}), \
                        patch('module.resonance.caravan.clear_trade_state'), \
                        patch('module.resonance.caravan.fetch_prices', return_value=_sample_prices()), \
                        patch('module.resonance.caravan.is_rest_area_done_today', side_effect=[False, True]), \
                        patch('module.resonance.caravan.mark_rest_area_done'):
                    if cleanup_ok:
                        caravan.run()
                        self.assertEqual(events, ['clean', rest_city])
                        caravan._mark_garbage_cleaned.assert_called_once_with('TEST')
                        caravan.drink_rest_area_soda.assert_called_once_with(max_drinks=6)
                    else:
                        with self.assertRaises(TaskFailed):
                            caravan.run()
                        self.assertEqual(events, ['clean', 'clean'])
                        caravan._mark_garbage_cleaned.assert_not_called()
                        caravan.travel_to.assert_not_called()
                        caravan.drink_rest_area_soda.assert_not_called()
                        caravan.config.task_delay.assert_called_once_with(minute=10)

    def test_run_pending_via_wrong_city_never_sells_during_rest_area_recovery(self):
        from module.exception import TaskFailed
        from module.resonance.caravan import ResonanceCaravan
        from module.resonance.columba import PRESTIGE_CITIES, load_columba_data

        profile = {'maxLot': 994, 'prestige': {c: 20 for c in PRESTIGE_CITIES}, 'roles': {}}
        pending = {'bought_city': '阿妮塔发射中心', 'target_city': '岚心城', 'negotiate_sell': True,
                   'expected_profit': 120, 'restock_used': 1, 'via_wilderness': True,
                   'wilderness_done': True}
        caravan = ResonanceCaravan.__new__(ResonanceCaravan)
        caravan.config = SimpleNamespace(
            config_name='TEST', ResonanceTrade_RecycleAtWilderness=False,
            ResonanceTrade_UseRestArea=True, ResonanceTrade_UseFatigueItem='none',
            ResonanceTrade_UseBento=False, ResonanceTrade_RefreshProfile=False, task_delay=Mock(),
        )
        caravan.ui_ensure = Mock()
        caravan.wait_until_docked = Mock()
        caravan.ensure_profile = Mock(return_value=profile)
        caravan.get_current_city = Mock(return_value='曼德矿场')
        caravan._maybe_drink_rest_area = Mock()
        caravan.travel_to = Mock()
        caravan.sell_all = Mock()
        caravan.ui_goto_main = Mock()

        with patch('module.resonance.caravan.load_trade_state', return_value=dict(pending)), \
                patch('module.resonance.caravan.clear_trade_state') as clear_state, \
                patch('module.resonance.caravan.fetch_prices', return_value=_sample_prices()), \
                self.assertRaises(TaskFailed):
            caravan.run()

        caravan._maybe_drink_rest_area.assert_not_called()
        caravan.travel_to.assert_not_called()
        caravan.sell_all.assert_not_called()
        clear_state.assert_not_called()
        caravan.config.task_delay.assert_called_once_with(minute=10)
        self.assertEqual(pending['target_city'], '岚心城')
        self.assertEqual(pending['restock_used'], 1)
        self.assertTrue(pending['via_wilderness'])

    def test_smart_atomic_budget_priority_and_crossing_extra_drive(self):
        from module.resonance.caravan import ResonanceCaravan, _calc_fatigue
        from module.resonance.columba import load_columba_data

        data = load_columba_data()
        caravan = self._wilderness_caravan()
        plan = self._wilderness_plan()
        plan.update({'is_smart_cycle': True, 'bargain_target': 20, 'raise_target': 20, 'atomic_fatigue': 321})
        split_drive = (_calc_fatigue('阿妮塔发射中心', '荒原站', {}, data)
                       + _calc_fatigue('荒原站', '岚心城', {}, data))

        self.assertEqual(caravan._plan_needed_fatigue(plan, {'roles': {}}, data, False, 20, 20, False), 321)
        self.assertEqual(caravan._plan_needed_fatigue(plan, {'roles': {}}, data, True, 20, 20, False),
                         321 + split_drive - 71)

    def test_crossing_wrong_arrival_never_sells_and_preserves_pending_state(self):
        from module.exception import TaskFailed
        from module.resonance.caravan import load_trade_state, save_trade_state
        from module.resonance.columba import load_columba_data

        data = load_columba_data()
        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, 'trade_state.json')
            caravan = self._wilderness_caravan()
            caravan.get_current_city = Mock(side_effect=['荒原站', '曼德矿场'])

            with patch('module.resonance.caravan.clear_trade_state') as clear_state, \
                    patch('module.resonance.caravan.save_trade_state',
                          side_effect=lambda *a, **kw: save_trade_state(*a, path=state_path, **kw)), \
                    self.assertRaises(TaskFailed):
                caravan._execute_one_leg('阿妮塔发射中心', {}, {'roles': {}}, {},
                                         self._wilderness_leg_opts(data))

            self.assertEqual([c[0][0] for c in caravan.travel_to.call_args_list], ['荒原站', '岚心城'])
            self.assertEqual(caravan.get_current_city.call_args_list, [call(), call()])
            caravan.sell_all.assert_called_once_with(raise_target=0)
            caravan.buy_plan.assert_called_once()
            clear_state.assert_called_once_with()
            caravan.config.task_delay.assert_called_once_with(minute=10)
            reloaded = load_trade_state(state_path)
            self.assertEqual(reloaded['target_city'], '岚心城')
            self.assertEqual(reloaded['restock_used'], 1)
            self.assertTrue(reloaded['negotiate_sell'])
            self.assertTrue(reloaded['via_wilderness'])
            self.assertTrue(reloaded['wilderness_done'])

    def test_crossing_wilderness_exit_rechecks_unreadable_or_exhausted_fatigue(self):
        from module.resonance.caravan import load_trade_state, save_trade_state
        from module.resonance.columba import load_columba_data
        from module.resonance.route import _calc_fatigue
        from module.resonance.smart_state import DRIVE_FATIGUE_BUFFER, safe_negotiation_budget

        data = load_columba_data()
        for exit_fatigue in (None, (900, 912)):
            with self.subTest(exit_fatigue=exit_fatigue), tempfile.TemporaryDirectory() as tmp:
                state_path = os.path.join(tmp, 'trade_state.json')
                caravan = self._wilderness_caravan()
                caravan._read_current_fatigue = Mock(side_effect=[(0, 912), exit_fatigue])
                caravan._ensure_fatigue_for_leg = Mock(wraps=caravan._ensure_fatigue_for_leg)
                caravan.get_current_city = Mock(return_value='荒原站')

                with patch('module.resonance.caravan.clear_trade_state'), \
                        patch('module.resonance.caravan.save_trade_state',
                              side_effect=lambda *a, **kw: save_trade_state(*a, path=state_path, **kw)):
                    result = caravan._execute_one_leg('阿妮塔发射中心', {}, {'roles': {}}, {},
                                                      self._wilderness_leg_opts(data))

                self.assertEqual(result, (None, False))
                caravan.travel_to.assert_called_once_with('荒原站', use_ramming=False, configure_assist=True)
                caravan.sell_all.assert_called_once_with(raise_target=0)
                caravan.buy_plan.assert_called_once()
                self.assertEqual(caravan._read_current_fatigue.call_count, 2)
                if exit_fatigue is not None:
                    self.assertEqual(caravan._ensure_fatigue_for_leg.call_count, 1)
                    self.assertEqual(
                        caravan._ensure_fatigue_for_leg.call_args_list[0][0][2],
                        _calc_fatigue('荒原站', '岚心城', {}, data)
                        + safe_negotiation_budget(20) + DRIVE_FATIGUE_BUFFER,
                    )
                caravan.config.task_delay.assert_called_once()
                self.assertGreater(caravan.config.task_delay.call_args[1]['minute'], 0)
                reloaded = load_trade_state(state_path)
                self.assertEqual(reloaded['target_city'], '岚心城')
                self.assertEqual(reloaded['restock_used'], 1)
                self.assertTrue(reloaded['via_wilderness'])
                self.assertTrue(reloaded['wilderness_done'])

    def test_crossing_empty_leg_persists_only_confirmed_transit_checkpoint(self):
        from module.resonance.caravan import ResonanceCaravan
        from module.resonance.columba import load_columba_data

        data = load_columba_data()
        caravan = self._wilderness_caravan()
        caravan._plan_leg_for_mode = Mock(return_value=self._wilderness_plan(combinations=[]))
        state = {}

        with patch('module.resonance.caravan.clear_trade_state'), \
                patch('module.resonance.caravan.save_trade_state') as save_state:
            next_city, ok = caravan._execute_one_leg('阿妮塔发射中心', {}, {'roles': {}}, state,
                                                     self._wilderness_leg_opts(data))

        self.assertEqual((next_city, ok), ('岚心城', True))
        caravan.buy_plan.assert_not_called()
        self.assertEqual(save_state.call_count, 2)
        self.assertTrue(save_state.call_args_list[0][1]['via_wilderness'])
        self.assertEqual(save_state.call_args_list[0][1]['expected_profit'], 0)
        self.assertEqual(state, {'bought_city': '阿妮塔发射中心', 'target_city': '岚心城',
                                 'expected_profit': 0, 'via_wilderness': True, 'wilderness_done': True})
