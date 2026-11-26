from datetime import datetime, timedelta
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np

from module.config import server


class TestResonanceProfit(unittest.TestCase):
    def setUp(self):
        self.addCleanup(server.set_server, server.server)
        server.set_server('resonance')

    def test_day_key_and_parse_profit_text(self):
        from module.resonance.profit_log import parse_sell_profit_text, profit_day_key

        self.assertEqual(profit_day_key(datetime(2026, 11, 26, 4, 59)), '2026-11-25')
        self.assertEqual(profit_day_key(datetime(2026, 11, 26, 5, 0)), '2026-11-26')
        self.assertEqual(parse_sell_profit_text('+1,234,567'), 1234567)
        self.assertEqual(parse_sell_profit_text('5060085'), 5060085)
        self.assertEqual(parse_sell_profit_text('-45,600'), -45600)
        self.assertIsNone(parse_sell_profit_text(''))
        self.assertIsNone(parse_sell_profit_text('abc'))
        self.assertIsNone(parse_sell_profit_text('999999999'))

    def test_record_pruning_and_daily_trend_summary(self):
        from module.resonance.profit_log import (
            load_profit_days, record_trade_profit, summarize_profit_history,
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'profit_log.json')
            now = datetime(2026, 11, 26, 10, 0, 0)
            old_day = now - timedelta(days=30)
            day_m2 = now - timedelta(days=2)
            day_m1 = now - timedelta(days=1)

            record_trade_profit('TEST', 999999, '旧站', '旧站B', path=path, now=old_day)
            record_trade_profit('TEST', 1000000, '修格里城', '曼德矿场', path=path, now=day_m2)
            record_trade_profit('TEST', 1500000, '七号自由港', '修格里城', path=path, now=day_m1)
            record_trade_profit('TEST', 500000, '修格里城', '七号自由港', path=path, now=day_m1)
            record_trade_profit('TEST', 1200000, '阿妮塔发射中心', '曼德矿场', path=path, now=now)
            record_trade_profit('TEST', 300000, '曼德矿场', '修格里城', path=path, now=now)
            record_trade_profit('OTHER', 88888, '修格里城', '铁盟哨站', path=path, now=now)

            # Old day (31st day ago relative to `now`) is pruned once a newer trade writes
            days_test = load_profit_days('TEST', path=path)
            self.assertEqual(len(days_test), 3)
            self.assertNotIn(old_day.strftime('%Y-%m-%d'), days_test)
            self.assertEqual(len(load_profit_days('OTHER', path=path)), 1)

            summary = summarize_profit_history('TEST', path=path, now=now)
            self.assertEqual(summary['today_key'], '2026-11-26')
            self.assertEqual(summary['today_total'], 1500000)
            self.assertEqual(summary['today_count'], 2)
            self.assertEqual(summary['today_avg'], 750000)
            self.assertEqual(summary['today_delta'], -500000)
            self.assertEqual(summary['today_pct'], -25.0)
            self.assertIn('▼ -500,000 (-25.0%)', summary['today_delta_text'])
            self.assertIn('今日利润 1,500,000', summary['overview_line'])
            self.assertEqual(summary['active_days'], 3)
            self.assertEqual(summary['count_30d'], 5)
            self.assertEqual(summary['total_30d'], 4500000)
            self.assertEqual(summary['best_day'], ('2026-11-25', 2000000))

            # Newest -> oldest rows: today (-25%), yesterday (+100%), day-2 (—)
            rows = summary['daily_rows']
            self.assertEqual([r['date'] for r in rows], ['2026-11-26', '2026-11-25', '2026-11-24'])
            self.assertEqual(rows[1]['delta'], 1000000)
            self.assertEqual(rows[1]['pct'], 100.0)
            self.assertIsNone(rows[2]['delta'])
            self.assertEqual(rows[2]['delta_text'], '—')
            self.assertEqual(summary['today_trades'][0]['from'], '曼德矿场')

    def test_read_sell_profit_and_caravan_recording(self):
        from module.resonance.caravan import PROFIT_OCR, ResonanceCaravan, read_sell_profit

        self.assertIsNone(read_sell_profit(None))
        pos_img = np.full((720, 1280, 3), 240, dtype=np.uint8)
        red_img = np.zeros((720, 1280, 3), dtype=np.uint8)
        red_img[534:566, 1050:1255] = (230, 60, 60)

        with patch.object(PROFIT_OCR, 'ocr', return_value=['+1693807']):
            self.assertEqual(read_sell_profit(pos_img), 1693807)
        with patch.object(PROFIT_OCR, 'ocr', return_value=['-12500']):
            self.assertEqual(read_sell_profit(pos_img), -12500)
        with patch.object(PROFIT_OCR, 'ocr', return_value=['12500']):
            self.assertEqual(read_sell_profit(red_img), -12500)

        caravan = ResonanceCaravan.__new__(ResonanceCaravan)
        caravan.config = Mock(config_name='TEST')
        caravan.sell_all = Mock(side_effect=[True, True, False])
        state = {'bought_city': '阿妮塔发射中心', 'expected_profit': 1500000}

        with patch('module.resonance.caravan.record_trade_profit') as rec:
            caravan._last_sell_image = pos_img
            with patch.object(PROFIT_OCR, 'ocr', return_value=['+1693807']):
                self.assertTrue(caravan._sell_and_record_profit('曼德矿场', state, raise_target=20))
            rec.assert_called_once_with(
                'TEST', 1693807, from_city='阿妮塔发射中心', to_city='曼德矿场', estimated=False,
            )
            rec.reset_mock()

            # Falls back to expected_profit when OCR returns None
            caravan._last_sell_image = pos_img
            with patch.object(PROFIT_OCR, 'ocr', return_value=['']):
                self.assertTrue(caravan._sell_and_record_profit('曼德矿场', state, raise_target=0))
            rec.assert_called_once_with(
                'TEST', 1500000, from_city='阿妮塔发射中心', to_city='曼德矿场', estimated=True,
            )
            rec.reset_mock()

            # Skipped sell does not record
            self.assertFalse(caravan._sell_and_record_profit('曼德矿场', state, raise_target=0))
            rec.assert_not_called()
