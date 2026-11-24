"""Flash & god-spark OCR and column selection tests.

Run: toolkit/python.exe -m unittest dev_tools.test_rogue_cards_ocr
"""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
from PIL import Image

from module.config.server import set_server

set_server('chaoszero')

from module.chaoszero.rogue import ChaoszeroRogue
from module.chaoszero.rogue_cards import (
    CARD_MIN_SCORE,
    GOD_SPARK_DEFAULT_SCORE,
    NEUTRAL_FORM_INDEX,
    CardLibrary,
    CardReader,
    GodSparkLibrary,
    normalize,
    parse_god_type,
)


def make_synthetic_library():
    lib = CardLibrary.__new__(CardLibrary)
    raw = [
        '對目標造成220%傷害，若持有護盾則獲得堅毅2並額外觸發連擊效果',
        '賦予自身護盾180%，本回合結束時依剩餘手牌數回復體力',
        '從抽牌堆抽取2張攻擊卡牌，並使其本回合費用減少1點',
    ]
    lib.cards = {
        ('測試角色', '測試卡'): {
            'forms': [normalize(text) for text in raw],
            'raw': raw,
        }
    }
    return lib


class TestCardIdentifyGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = CardLibrary()

    def test_rejects_single_char_transition_frame(self):
        card, score, margin = self.library.identify(['', '', '點'])
        self.assertIsNone(card)
        self.assertEqual(score, 0.0)
        self.assertEqual(margin, 0.0)

    def test_rejects_low_score_noise(self):
        card, score, _margin = self.library.identify(['零一二三', '四五六七', '八九十'])
        self.assertIsNone(card)
        self.assertLess(score, CARD_MIN_SCORE)

    def test_identifies_real_card_cleanly(self):
        forms, _raw = self.library.forms('準備發射')
        card, score, margin = self.library.identify(forms[:3])
        self.assertEqual(card, '準備發射')
        self.assertGreaterEqual(score, 0.95)
        self.assertGreater(margin, 0.1)


class TestGodSparkLibrary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = CardLibrary()
        cls.sparks = GodSparkLibrary()

    def test_parse_god_type(self):
        self.assertEqual(parse_god_type('靈光一閃：維托'), 'VITOR')
        self.assertEqual(parse_god_type('靈光一閃：尼希隆'), 'NIHILUM')
        self.assertEqual(parse_god_type('靈光一閃：@?#$'), 'CALIGO')
        self.assertIsNone(parse_god_type('一般頁面'))

    def test_default_god_spark_priority_order(self):
        expected = [
            '獲得AP1',
            '此卡牌費用減少1',
            '常態弱點攻擊',
            '賦予目標脆弱2',
            '抽取1',
            '此卡牌的傷害量增加30%',
            '士氣1、決心1',
            '費用變更為0',
        ]
        scores = [self.sparks.priority(desc) for desc in expected]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertGreater(len(set(scores)), len(scores) - 1)
        self.assertLess(self.sparks.priority('費用變更為0'), GOD_SPARK_DEFAULT_SCORE)

    def test_preference_score_matches_ordered_and_prefix_rules(self):
        self.assertEqual(self.sparks.matches_preferred('賦予目標脆弱2', ['獲得AP1', '賦予目標脆弱']), 1)
        s_pref_2 = self.sparks.preference_score('此卡牌費用減少1', ['獲得AP1', '此卡牌費用減少1'])
        s_vuln_2 = self.sparks.preference_score('賦予目標脆弱2', ['賦予目標脆弱'])
        s_unpref_ap = self.sparks.preference_score('獲得AP1', ['士氣1、決心1'])
        s_pref_morale = self.sparks.preference_score('士氣1、決心1', ['士氣1、決心1'])
        self.assertGreater(s_vuln_2, s_unpref_ap)
        self.assertGreater(s_pref_morale, s_unpref_ap)
        self.assertGreater(self.sparks.preference_score('獲得AP1', ['獲得AP1', '此卡牌費用減少1']), s_pref_2)

    def test_classified_god_and_normal_pools(self):
        self.assertEqual(len(self.sparks.sparks), 30)
        loaded_descs = {d for d, _ in self.sparks.sparks}
        for assault_only in (
            '賦予目標脆弱3',
            '使用自我意識技能時，費用減少1',
            '抽取至手牌達到4張為止',
            '費用變更為0',
        ):
            self.assertNotIn(assault_only, loaded_descs)
        for rogue_sortie in ('將棄牌堆中的2張消滅卡牌移動至手牌', '賦予此卡牌開戰'):
            self.assertIn(rogue_sortie, loaded_descs)

        atk_1 = {d for d, _ in self.sparks.god_pool(god_type='VITOR', category='CARD_ATK', cost=1)}
        skill_0 = {d for d, _ in self.sparks.god_pool(god_type='VITOR', category='CARD_SKILL', cost=0)}
        self.assertIn('常態弱點攻擊', atk_1)
        self.assertIn('此卡牌費用減少1', atk_1)
        self.assertNotIn('常態弱點攻擊', skill_0)
        self.assertNotIn('此卡牌費用減少1', skill_0)

        hero = self.library.card_meta('萬人的英雄')
        norm_descs = {
            d for d, _ in self.sparks.normal_pool(
                category=hero['category'], cost=hero['cost'],
                job=hero['job'], talents=hero['talent'],
            )
        }
        self.assertIn('持續1回合，獲得決心2', norm_descs)
        self.assertNotIn('持續1回合，獲得決心1', norm_descs)
        self.assertNotIn('持續1回合，獲得決心3', norm_descs)

        water = self.library.card_meta('水之根源')
        desc, _r, _p = self.sparks.match('獲得100%治癒 獲得AP1', base_raw=water['base_desc'])
        self.assertIsNone(desc)
        desc, _r, prio = self.sparks.match('獲得100%治癒 獲得AP1 獲得AP1', base_raw=water['base_desc'])
        self.assertEqual(desc, '獲得AP1')
        self.assertEqual(prio, 120)

    def test_matches_exact_and_noisy_god_sparks(self):
        cases = [
            ('此卡牌費用減少1', '此卡牌費用減少1', 115),
            ('移卡牌費用減少1', '此卡牌費用減少1', 115),
            ('%獲得AP1', '獲得AP1', 120),
            ('6將棄牌堆中的2張消滅卡牌移動至手牌', '將棄牌堆中的2張消滅卡牌移動至手牌', 76),
            ('賦予此卡牌開戰', '賦予此卡牌開戰', 55),
            ('士氣1、決心', '士氣1、決心1', 42),
        ]
        for raw_ocr, expected_desc, expected_prio in cases:
            desc, ratio, prio = self.sparks.match(raw_ocr)
            self.assertEqual(desc, expected_desc, raw_ocr)
            self.assertEqual(prio, expected_prio, raw_ocr)
            self.assertGreaterEqual(ratio, 0.78, raw_ocr)

    def test_ignores_spark_text_already_in_base_form(self):
        base_raw = '對敵人造成150%傷害。賦予此卡牌開戰。抽取1'
        desc, ratio, prio = self.sparks.match('對敵人造成150%傷害 賦予此卡牌開戰 抽取1', base_raw=base_raw)
        self.assertIsNone(desc)
        self.assertEqual(ratio, 0.0)
        self.assertEqual(prio, 0)

        desc, ratio, prio = self.sparks.match('X使主導卡牌費用減少1', base_raw='使手牌中的主導卡牌費用減少1')
        self.assertIsNone(desc)
        self.assertEqual(ratio, 0.0)
        self.assertEqual(prio, 0)

    def test_analyze_columns_distinguishes_neutral_and_real_rsp_forms(self):
        # 風能充電 rsp5 contains "傷害量減少50%" - must not be misclassified as NEUTRAL_FORM_INDEX
        forms, raw_forms = self.library.forms('風能充電')
        cols, info = self.library.analyze_columns(
            [forms[0], forms[1], forms[4]],
            [raw_forms[0], raw_forms[1], raw_forms[4]],
            '風能充電',
            self.sparks,
        )
        self.assertEqual([idx for _, _, idx in cols], [0, 1, 4])
        self.assertIsNone(info[2]['neutral_desc'])

        # 漩渦 base_desc + neutral + god spark: strips god first, then detects NEUTRAL_FORM_INDEX
        vortex = self.library.card_meta('漩渦')
        raw_neutral_god = vortex['base_desc'] + ' 持續1回合，獲得決心3 此卡牌費用減少1'
        cols, info = self.library.analyze_columns(
            [normalize(raw_neutral_god)],
            [raw_neutral_god],
            '漩渦',
            self.sparks,
            god=True,
            god_type='VITOR',
        )
        self.assertEqual(len(cols), 1)
        self.assertEqual(cols[0][2], NEUTRAL_FORM_INDEX)
        self.assertEqual(info[0]['god_desc'], '此卡牌費用減少1')
        self.assertEqual(info[0]['neutral_desc'], '持續1回合，獲得決心3')


class TestGodSparkColumnSelection(unittest.TestCase):
    def setUp(self):
        self.library = make_synthetic_library()
        forms, _raw = self.library.forms('測試卡')
        self.high_ratio_f0 = forms[0][:-4]
        self.low_ratio_f0 = ''.join(ch for i, ch in enumerate(forms[0]) if i % 3 != 0)
        self.other_f1 = forms[1]

    def test_breaks_tie_between_matching_form_index_columns_by_god_score(self):
        texts = [self.high_ratio_f0, self.other_f1, self.low_ratio_f0]
        cols = dict((c, (r, i)) for c, r, i in self.library.read_columns(texts, '測試卡'))
        self.assertEqual(cols[0][1], 0)
        self.assertEqual(cols[2][1], 0)
        self.assertGreater(cols[0][0], cols[2][0])

        picked = self.library.pick_column(
            texts, name='測試卡', form_index=0, god_scores=[0, 0, 100]
        )
        self.assertIsNotNone(picked)
        self.assertEqual(picked[0], 2)
        self.assertEqual(picked[2], 0)

    def test_god_first_vs_form_first(self):
        texts = [self.high_ratio_f0, self.other_f1, self.low_ratio_f0]
        # form_first (god_first=False): configured form_index beats higher god_score on another form
        picked = self.library.pick_column(
            texts, name='測試卡', form_index=0, god_scores=[0, 10120, 0], god_first=False,
        )
        self.assertEqual(picked[0], 0)
        self.assertEqual(picked[2], 0)

        # god_first=True: higher god_score on col 1 wins over configured form_index on col 0
        picked_god = self.library.pick_column(
            texts, name='測試卡', form_index=0, god_scores=[0, 10120, 0], god_first=True,
        )
        self.assertEqual(picked_god[0], 1)

    def test_unconfigured_card_prefers_higher_god_score(self):
        texts = [self.high_ratio_f0, self.other_f1, self.low_ratio_f0]
        picked = self.library.pick_column(
            texts, name='測試卡', god_scores=[0, 95, 0]
        )
        self.assertIsNotNone(picked)
        self.assertEqual(picked[0], 1)

    def test_rogue_flash_column_ordered_god_filter_and_god_first_mode(self):
        real_lib = CardLibrary()
        sparks = GodSparkLibrary()
        _forms, raw_forms = real_lib.forms('劍之雨')
        # Three columns all showing rsp1 with 3 different god sparks
        raws_same_form = [
            raw_forms[0] + ' 此卡牌費用減少1',
            raw_forms[0] + ' 常態弱點攻擊',
            raw_forms[0] + ' 獲得AP1',
        ]
        norm_texts = [normalize(r) for r in raws_same_form]

        def make_flash_task(rules, god_rules, god_first=False):
            t = ChaoszeroRogue.__new__(ChaoszeroRogue)
            t.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8), screenshot=Mock())
            t.card_library = real_lib
            t.god_spark_library = sparks
            t.card_reader = SimpleNamespace(read_all=Mock(return_value=norm_texts), last_raw=raws_same_form)
            t.meditate_pending = []
            t.spark_targets = {k: v for k, v in rules.items()}
            t.rogue_spark_filter = Mock(return_value=rules)
            t._rogue_meditate_allows = Mock(return_value=True)
            t.config = SimpleNamespace(
                ChaoszeroRogue_RogueGodSparkFirst=god_first,
                ChaoszeroRogue_RogueGodSparkFilter='',
                data={'ChaoszeroRogue': {'ChaoszeroRogue': {
                    'RogueGodSparkFilter': god_rules,
                }}},
            )
            return t

        # Ordered preference: 常態弱點攻擊 > 獲得AP1 picks col 2 over col 3
        task_pref = make_flash_task({'劍之雨': ['1']}, '劍之雨 = 常態弱點攻擊 > 獲得AP1')
        self.assertEqual(task_pref.rogue_flash_column(scale=1.8, god=True), 2)
        self.assertEqual(task_pref.spark_selected, '劍之雨')

        # Unconfigured god filter falls back to default priority (獲得AP1 > 費用減少1 > 常態弱點攻擊)
        task_def = make_flash_task({'劍之雨': ['1']}, '')
        self.assertEqual(task_def.rogue_flash_column(scale=1.8, god=True), 3)

        # god_first=True overrides form rule when another form carries a preferred god spark,
        # without marking spark_selected for the mismatched form
        raws_mixed = [
            raw_forms[0],
            raw_forms[1] + ' 常態弱點攻擊',
            raw_forms[2] + ' 抽取1',
        ]
        task_gf = make_flash_task({'劍之雨': ['1']}, '劍之雨 = 常態弱點攻擊', god_first=True)
        task_gf.card_reader = SimpleNamespace(
            read_all=Mock(return_value=[normalize(r) for r in raws_mixed]),
            last_raw=raws_mixed,
        )
        self.assertEqual(task_gf.rogue_flash_column(scale=1.8, god=True), 2)
        self.assertIsNone(task_gf.spark_selected)

        # Unspecified card (not in RogueSparkFilter) ALWAYS prioritizes god spark on god=True,
        # even when RogueGodSparkFirst=False
        task_unspec = make_flash_task({}, '劍之雨 = 常態弱點攻擊', god_first=False)
        task_unspec.card_reader = SimpleNamespace(
            read_all=Mock(return_value=[normalize(r) for r in raws_mixed]),
            last_raw=raws_mixed,
        )
        self.assertEqual(task_unspec.rogue_flash_column(scale=1.8, god=True), 2)

        # Unspecified card on god=True when god spark OCR fails falls back to rogue_god_pick()
        # before form_value
        raws_no_ocr_god = [raw_forms[0], raw_forms[1], raw_forms[2]]
        task_vis = make_flash_task({}, '', god_first=False)
        task_vis.card_reader = SimpleNamespace(
            read_all=Mock(return_value=[normalize(r) for r in raws_no_ocr_god]),
            last_raw=raws_no_ocr_god,
        )
        task_vis.rogue_god_pick = Mock(return_value=3)
        self.assertEqual(task_vis.rogue_flash_column(scale=1.8, god=True), 3)

        # Configured card whose wanted form didn't roll still falls back to OCR-matched
        # flash_god_column in rogue_choose_flash before magenta rogue_god_pick()
        raws_fallback = [raw_forms[1], raw_forms[2], raw_forms[3] + ' 抽取1']
        task_fb = make_flash_task({'劍之雨': ['1']}, '', god_first=False)
        task_fb.card_reader = SimpleNamespace(
            read_all=Mock(return_value=[normalize(r) for r in raws_fallback]),
            last_raw=raws_fallback,
        )
        task_fb.spark_pending = None
        task_fb.rogue_god_pick = Mock(return_value=None)
        task_fb.rogue_pick_index = Mock(return_value=1)
        task_fb.rogue_pick = Mock(return_value=True)
        task_fb.rogue_choose_flash(god=True)
        self.assertEqual(task_fb.flash_god_column, 3)
        self.assertEqual(task_fb.rogue_pick.call_args[0][1], 3)


class TestRealGodScreenshots(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = CardLibrary()
        cls.sparks = GodSparkLibrary()
        cls.reader = CardReader()

    @staticmethod
    def _load_rgb(path):
        return np.array(Image.open(path).convert('RGB'))

    @staticmethod
    def _make_task(image, rules, god_filter=''):
        task = ChaoszeroRogue.__new__(ChaoszeroRogue)
        task.device = SimpleNamespace(image=image, screenshot=Mock())
        task.card_library = TestRealGodScreenshots.library
        task.card_reader = TestRealGodScreenshots.reader
        task.god_spark_library = TestRealGodScreenshots.sparks
        task.meditate_pending = []
        task.rogue_spark_filter = Mock(return_value=rules)
        task._rogue_meditate_allows = Mock(return_value=True)
        task.spark_targets = {}
        task.config = SimpleNamespace(
            ChaoszeroRogue_RogueGodSparkFirst=False,
            data={'ChaoszeroRogue': {'ChaoszeroRogue': {'RogueGodSparkFilter': god_filter}}},
        )
        return task

    @unittest.skipUnless(
        os.path.exists('log/rogue_card_pages/god/003948.png'),
        'Real god screenshot 003948.png not present',
    )
    def test_003948_contrast_fallback_and_god_spark(self):
        img = self._load_rgb('log/rogue_card_pages/god/003948.png')
        texts = self.reader.read_all(img, scale=1.8)
        card, score, margin = self.library.identify(texts)
        self.assertEqual(card, '準備發射')
        self.assertGreater(score, 0.5)
        self.assertGreater(margin, 0.04)

        cols, info = self.library.analyze_columns(
            texts, self.reader.last_raw, card, self.sparks, god=True, god_type='NIHILUM'
        )
        col_map = {c: (r, idx) for c, r, idx in cols}
        self.assertEqual(col_map[2][1], 2)
        self.assertGreaterEqual(col_map[2][0], 0.85)
        self.assertEqual(info[2]['god_desc'], '將棄牌堆中的2張消滅卡牌移動至手牌')
        self.assertEqual(info[2]['god_prio'], 76)

    @unittest.skipUnless(
        os.path.exists('log/rogue_card_pages/god/012626.png'),
        'Real god screenshot 012626.png not present',
    )
    def test_012626_neutral_vs_rsp2_and_god_spark(self):
        img = self._load_rgb('log/rogue_card_pages/god/012626.png')
        texts = self.reader.read_all(img, scale=1.8)
        card, _score, margin = self.library.identify(texts)
        self.assertEqual(card, '漩渦')
        self.assertGreater(margin, 0.04)

        cols, info = self.library.analyze_columns(
            texts, self.reader.last_raw, card, self.sparks, god=True, god_type='VITOR'
        )
        col_map = {c: (r, idx) for c, r, idx in cols}
        self.assertEqual(col_map[0][1], NEUTRAL_FORM_INDEX)
        self.assertEqual(info[0]['neutral_desc'], '持續1回合，獲得不屈3')
        self.assertEqual(col_map[1][1], NEUTRAL_FORM_INDEX)
        self.assertEqual(info[1]['neutral_desc'], '持續1回合，獲得決心3')
        self.assertEqual(col_map[2][1], 1)
        self.assertGreaterEqual(col_map[2][0], 0.90)
        self.assertEqual(info[2]['god_desc'], '賦予此卡牌開戰')
        self.assertEqual(info[2]['god_prio'], 55)

    @unittest.skipUnless(
        os.path.exists('log/rogue_card_pages/god/004044.png'),
        'Real god screenshot 004044.png not present',
    )
    def test_004044_neutral_pendant_not_confused_with_rsp4(self):
        img = self._load_rgb('log/rogue_card_pages/god/004044.png')
        texts = self.reader.read_all(img, scale=1.8)
        card, _score, _margin = self.library.identify(texts)
        self.assertEqual(card, '決心墜飾')

        cols, info = self.library.analyze_columns(
            texts, self.reader.last_raw, card, self.sparks, god=True, god_type='SECRED'
        )
        col_map = {c: idx for c, _r, idx in cols}
        self.assertEqual(col_map[0], NEUTRAL_FORM_INDEX)
        self.assertEqual(info[0]['neutral_desc'], '回合結束時，獲得20%固定護盾')
        self.assertEqual(col_map[2], 4)

    @unittest.skipUnless(
        os.path.exists('log/rogue_card_pages/flash/011809.png')
        and os.path.exists('log/rogue_card_pages/flash/022426.png'),
        'Real flash screenshots not present',
    )
    def test_flash_pages_distinguish_neutral_from_rsp1(self):
        img_has_rsp1 = self._load_rgb('log/rogue_card_pages/flash/011809.png')
        task = self._make_task(img_has_rsp1, {'萬人的英雄': ['1']})
        self.assertEqual(task.rogue_flash_column(scale=1.0, god=False), 3)

        task_neutral = self._make_task(img_has_rsp1, {'萬人的英雄': ['6']})
        self.assertIn(task_neutral.rogue_flash_column(scale=1.0, god=False), (1, 2))

        img_no_rsp1 = self._load_rgb('log/rogue_card_pages/flash/022426.png')
        task_miss = self._make_task(img_no_rsp1, {'萬人的英雄': ['1']})
        self.assertIsNone(task_miss.rogue_flash_column(scale=1.0, god=False))
        self.assertEqual(task_miss.meditate_pending, ['萬人的英雄'])

        task_pick_neutral = self._make_task(img_no_rsp1, {'萬人的英雄': ['中立']})
        self.assertIn(task_pick_neutral.rogue_flash_column(scale=1.0, god=False), (1, 3))

    @unittest.skipUnless(
        os.path.exists('log/rogue_card_pages/god/091304.png'),
        'Real god screenshot 091304.png not present',
    )
    def test_091304_neutral_god_spark_tie_break_and_strict_rsp1_miss(self):
        img = self._load_rgb('log/rogue_card_pages/god/091304.png')

        # Neutral columns 1 and 3 are NOT rsp1; asking for rsp1 must fall back & queue meditation
        task_rsp1 = self._make_task(img, {'萬人的英雄': ['1']})
        self.assertIsNone(task_rsp1.rogue_flash_column(scale=1.8, god=True))
        self.assertEqual(task_rsp1.meditate_pending, ['萬人的英雄'])

        # Asking for neutral (6 / 中立) or leaving unconfigured picks col 3 (cost -1 god spark)
        for rules in ({'萬人的英雄': ['6']}, {'萬人的英雄': ['中立']}, {}):
            task = self._make_task(img, rules)
            self.assertEqual(task.rogue_flash_column(scale=1.8, god=True), 3)


if __name__ == '__main__':
    unittest.main()
