import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from module.config.server import set_server

# Bind trickcal assets/config before importing module.trickcal.*
set_server('trickcal')

from module.base.utils import load_image  # noqa: E402
from module.trickcal.assets import (  # noqa: E402
    DUNGEON_BAKERY_SWEEP,
    DUNGEON_CANDY_SWEEP,
    DUNGEON_CLONE_EMPTY,
    DUNGEON_CLONE_SWEEP,
    DUNGEON_CLONE_ZERO,
    DUNGEON_CRAYON_SWEEP,
    DUNGEON_GOLD_SWEEP,
    DUNGEON_SWEEP_CONFIRM,
    DUNGEON_SWEEP_TITLE,
    EVENT_STAMINA_BUY,
    EVENT_SWEEP_CANCEL,
    EVENT_SWEEP_CLEAR,
    EVENT_SWEEP_MAX,
)
from module.trickcal.dungeon import TrickcalDungeon  # noqa: E402
from module.trickcal.dungeon_stage import (  # noqa: E402
    BAKERY_TABS,
    CANDY_MACHINE_AREAS,
    CRAYON_NEXT_AREA,
    CRAYON_PREV_AREA,
    _resolve_three_col_row,
    bakery_tab_selected,
    clone_slot_area,
    crayon_slot_area,
    crayon_target_page,
    dungeon_sweep_lit,
)
from module.trickcal.page import (  # noqa: E402
    page_dungeon_bakery_stage,
    page_dungeon_candy,
    page_dungeon_candy_stage,
    page_dungeon_clone,
    page_dungeon_clone_stage,
    page_dungeon_crayon_stage,
    page_dungeon_gold_stage,
)


def _make_dungeon():
    dg = TrickcalDungeon.__new__(TrickcalDungeon)
    dg.device = MagicMock()
    dg.device.image = np.zeros((720, 1280, 3), dtype=np.uint8)
    dg.device.click = MagicMock()
    dg.device.click_record_clear = MagicMock()
    dg.device.drag = MagicMock()
    dg.device.screenshot = MagicMock(side_effect=lambda: dg.device.image)
    dg.device.stuck_record_clear = MagicMock()
    dg.loop = MagicMock(side_effect=lambda timeout=10: iter(range(20)))
    dg.ui_ensure = MagicMock()
    dg.ui_goto_main = MagicMock()
    dg.ui_page_appear = MagicMock(return_value=False)
    dg.appear = MagicMock(return_value=False)
    dg.handle_reward_popup = MagicMock(return_value=False)
    dg.config = MagicMock()
    dg.config.TrickcalDungeon_CloneFactory = True
    dg.config.TrickcalDungeon_CloneFactoryStage = 5
    dg.config.TrickcalDungeon_Dungeon = 'gold'
    dg.config.TrickcalDungeon_DungeonStage = 3
    return dg


class TestTrickcalDungeon(unittest.TestCase):
    def test_grid_and_row_inference_helpers(self):
        # 1. _resolve_three_col_row infers missing cells from partial reads.
        reads = [(0, 144, 334, None), (1, 370, 334, 22), (2, 596, 334, 23)]
        self.assertEqual(
            _resolve_three_col_row(reads),
            {21: (144, 334), 22: (370, 334), 23: (596, 334)},
        )
        # Noisy misread overridden by aligned `(base - 1) % 3 == 0` reads.
        reads2 = [(0, 144, 334, 2), (1, 370, 334, 5), (2, 596, 334, 6)]
        self.assertEqual(
            _resolve_three_col_row(reads2),
            {4: (144, 334), 5: (370, 334), 6: (596, 334)},
        )

        # 2. Crayon page and 5x2 grid coordinates.
        self.assertEqual(crayon_target_page(1), 1)
        self.assertEqual(crayon_target_page(10), 1)
        self.assertEqual(crayon_target_page(11), 2)
        s1 = crayon_slot_area(1)
        s6 = crayon_slot_area(6)
        s10 = crayon_slot_area(10)
        self.assertLess(s1[0], s10[0])
        self.assertLess(s1[1], s6[1])

        # 3. Clone 4x3 grid clamps to 1..12 and steps left-to-right, top-to-bottom.
        c1 = clone_slot_area(1)
        c5 = clone_slot_area(5)
        c12 = clone_slot_area(12)
        self.assertEqual(clone_slot_area(99), c12)
        self.assertLess(c1[1], c5[1])
        self.assertLess(c5[0], c12[0])

    def test_bakery_tab_and_sweep_lit_detectors(self):
        # 1. Bakery selected (pink) vs unselected (cream) tabs.
        img = np.zeros((720, 1280, 3), dtype=np.uint8)
        mx1, my1, mx2, my2 = BAKERY_TABS['bakery_macaron']
        cx1, cy1, cx2, cy2 = BAKERY_TABS['bakery_cream']
        img[my1:my2, mx1:mx2] = (232, 192, 125)
        img[cy1:cy2, cx1:cx2] = (225, 155, 150)
        self.assertFalse(bakery_tab_selected(img, 'bakery_macaron'))
        self.assertTrue(bakery_tab_selected(img, 'bakery_cream'))

        # 2. Candy 速战 uses saturation so red/blue/green lit machines all pass,
        #    while grey disabled returns False.
        x1, y1, x2, y2 = DUNGEON_CANDY_SWEEP.area
        for rgb in ((233, 128, 222), (110, 180, 245), (120, 215, 130)):
            canvas = np.zeros((720, 1280, 3), dtype=np.uint8)
            canvas[y1:y2, x1:x2] = rgb
            self.assertTrue(dungeon_sweep_lit(canvas, 'candy'))
        grey = np.zeros((720, 1280, 3), dtype=np.uint8)
        grey[y1:y2, x1:x2] = (181, 181, 181)
        self.assertFalse(dungeon_sweep_lit(grey, 'candy'))

        # 3. Color-matched 速战 buttons accept lit asset & reject dim grey.
        for kind, btn in (
            ('gold', DUNGEON_GOLD_SWEEP),
            ('bakery', DUNGEON_BAKERY_SWEEP),
            ('crayon', DUNGEON_CRAYON_SWEEP),
            ('clone', DUNGEON_CLONE_SWEEP),
        ):
            lit = load_image(btn.file)
            self.assertTrue(dungeon_sweep_lit(lit, kind))
            bx1, by1, bx2, by2 = btn.area
            dim = lit.copy()
            dim[by1:by2, bx1:bx2] = (180, 180, 180)
            self.assertFalse(dungeon_sweep_lit(dim, kind))

    def test_run_order_and_config_toggles(self):
        for clone_on, dungeon_key in (
            (True, 'gold'),
            (False, 'bakery_cream'),
            (True, 'none'),
        ):
            dg = _make_dungeon()
            dg.config.TrickcalDungeon_CloneFactory = clone_on
            dg.config.TrickcalDungeon_CloneFactoryStage = 5
            dg.config.TrickcalDungeon_Dungeon = dungeon_key
            dg.config.TrickcalDungeon_DungeonStage = 7

            order = []
            dg.run_clone_factory = MagicMock(side_effect=lambda s: order.append(('clone', s)))
            dg.run_selected_dungeon = MagicMock(side_effect=lambda k, s: order.append((k, s)))
            dg.run()

            expected = []
            if clone_on:
                expected.append(('clone', 5))
            if dungeon_key != 'none':
                expected.append((dungeon_key, 7))
            self.assertEqual(order, expected)
            dg.ui_goto_main.assert_called_once_with()
            dg.config.task_delay.assert_called_once_with(server_update=True)

    def test_clone_factory_skips_when_zero_entries_or_low_stamina(self):
        # Case A: remaining entries 0/8 on splash -> stops without opening stage list.
        dg = _make_dungeon()
        with patch('module.trickcal.dungeon.read_clone_daily_remaining', return_value=0), \
             patch('module.trickcal.dungeon.read_dungeon_stamina', return_value=200):
            self.assertTrue(dg.run_clone_factory(5))
        dg.ui_ensure.assert_called_once_with(page_dungeon_clone)
        dg.device.click.assert_not_called()

        # Case B: star-candy stamina < 20 on splash -> stops without opening stage list.
        dg = _make_dungeon()
        with patch('module.trickcal.dungeon.read_clone_daily_remaining', return_value=8), \
             patch('module.trickcal.dungeon.read_dungeon_stamina', return_value=15):
            self.assertTrue(dg.run_clone_factory(5))
        dg.ui_ensure.assert_called_once_with(page_dungeon_clone)
        dg.device.click.assert_not_called()

    def test_scrollable_stage_direction_and_dim_abort(self):
        # 1. Gold blueprint map: higher stages sit ABOVE, so looking for stage 12
        #    while seeing {1..4} must drag DOWN (start_y < end_y).
        dg = _make_dungeon()
        visible_seq = iter([{1: (100, 400), 4: (400, 500)}, {12: (220, 260)}])
        selected = {'val': 3}

        def fake_select_click(btn):
            if btn.name == 'DUNGEON_GOLD_STAGE':
                selected['val'] = 12

        dg.ui_page_appear = lambda p: p is page_dungeon_gold_stage
        dg.device.click.side_effect = fake_select_click
        diff_toggle = {'n': 0}

        def fake_crop(img, roi):
            diff_toggle['n'] += 1
            return np.full((10, 10, 3), (diff_toggle['n'] * 30) % 255, dtype=np.uint8)

        with patch('module.trickcal.dungeon.read_selected_stage', side_effect=lambda *_: selected['val']), \
             patch('module.trickcal.dungeon.crop', side_effect=fake_crop), \
             patch('module.trickcal.dungeon.Timer') as mock_timer:
            mock_timer.return_value.start.return_value.reached.return_value = True
            mock_timer.return_value.reached.return_value = True
            ok = dg._select_scrollable_stage(
                'gold', 12, lambda *_: next(visible_seq), page_dungeon_gold_stage, higher_is_down=False
            )
        self.assertTrue(ok)
        start, end = dg.device.drag.call_args[0]
        self.assertLess(start[1], end[1])

        # 2. Bakery/Candy list: higher stages sit BELOW, so looking for stage 12
        #    while seeing {1..6} must drag UP (start_y > end_y).
        dg2 = _make_dungeon()
        visible_seq2 = iter([{1: (122, 160), 6: (582, 391)}, {12: (582, 567)}])
        sel2 = {'val': 1}
        dg2.ui_page_appear = lambda p: p is page_dungeon_candy_stage
        dg2.device.click.side_effect = lambda btn: sel2.__setitem__('val', 12) if btn.name == 'DUNGEON_CANDY_STAGE' else None
        diff2 = {'n': 0}

        def fake_crop2(img, roi):
            diff2['n'] += 1
            return np.full((10, 10, 3), (diff2['n'] * 30) % 255, dtype=np.uint8)

        with patch('module.trickcal.dungeon.read_selected_stage', side_effect=lambda *_: sel2['val']), \
             patch('module.trickcal.dungeon.crop', side_effect=fake_crop2), \
             patch('module.trickcal.dungeon.Timer') as mock_timer:
            mock_timer.return_value.start.return_value.reached.return_value = True
            mock_timer.return_value.reached.return_value = True
            ok2 = dg2._select_scrollable_stage(
                'candy', 12, lambda *_: next(visible_seq2), page_dungeon_candy_stage, higher_is_down=True
            )
        self.assertTrue(ok2)
        start2, end2 = dg2.device.drag.call_args[0]
        self.assertGreater(start2[1], end2[1])

        # 3. Dim/disabled 速战 must abort without clicking or force-battling.
        dg3 = _make_dungeon()
        with patch('module.trickcal.dungeon.read_dungeon_stamina', return_value=200), \
             patch('module.trickcal.dungeon.dungeon_sweep_lit', return_value=False):
            self.assertFalse(dg3._sweep_stage('gold', DUNGEON_GOLD_SWEEP, page_dungeon_gold_stage, cost=10))
        dg3.device.click.assert_not_called()

    def test_crayon_page_flip_and_full_sweep_flow(self):
        # 1. Crayon stage 14 flips from page 1 -> page 2 via right arrow then taps slot 14.
        dg = _make_dungeon()
        c_state = {'page': 1, 'stage': 9}
        dg.ui_page_appear = lambda p: p is page_dungeon_crayon_stage

        def fake_crayon_click(btn):
            if btn.name == 'DUNGEON_CRAYON_PAGE' and btn.area == CRAYON_NEXT_AREA:
                c_state['page'] = 2
            elif btn.name == 'DUNGEON_CRAYON_PAGE' and btn.area == CRAYON_PREV_AREA:
                c_state['page'] = 1
            elif btn.name == 'DUNGEON_CRAYON_STAGE':
                c_state['stage'] = 14

        dg.device.click.side_effect = fake_crayon_click
        with patch('module.trickcal.dungeon.read_crayon_page', side_effect=lambda *_: c_state['page']), \
             patch('module.trickcal.dungeon.read_selected_stage', side_effect=lambda *_: c_state['stage']), \
             patch('module.trickcal.dungeon.Timer') as mock_timer:
            mock_timer.return_value.start.return_value.reached.return_value = True
            mock_timer.return_value.reached.return_value = True
            self.assertTrue(dg._select_crayon_stage(14))

        clicked = [(c[0][0].name, c[0][0].area) for c in dg.device.click.call_args_list]
        self.assertEqual(
            clicked,
            [('DUNGEON_CRAYON_PAGE', CRAYON_NEXT_AREA), ('DUNGEON_CRAYON_STAGE', crayon_slot_area(14))],
        )

        # 2. Full sweep loop: 速战 -> 最大 -> 速战 -> 确定 until stamina drops below cost,
        #    never triggering stamina purchase.
        dg2 = _make_dungeon()
        sw_state = {'phase': 'stage', 'stamina': 120}
        dg2.ui_page_appear = lambda p: p is page_dungeon_gold_stage and sw_state['phase'] == 'stage'

        def fake_appear(btn, offset=(0, 0), interval=0, similarity=0.85):
            ph = sw_state['phase']
            if ph == 'dialog':
                return btn in (DUNGEON_SWEEP_TITLE, DUNGEON_SWEEP_CONFIRM)
            if ph == 'clear':
                return btn is EVENT_SWEEP_CLEAR
            return False

        def fake_sw_click(btn):
            if btn is DUNGEON_GOLD_SWEEP:
                sw_state['phase'] = 'dialog'
            elif btn is DUNGEON_SWEEP_CONFIRM:
                sw_state['phase'] = 'clear'
            elif btn is EVENT_SWEEP_CLEAR:
                sw_state['stamina'] = 5
                sw_state['phase'] = 'stage'

        dg2.appear = fake_appear
        dg2.device.click.side_effect = fake_sw_click

        with patch('module.trickcal.dungeon.read_dungeon_stamina', side_effect=lambda *_, **__: sw_state['stamina']), \
             patch('module.trickcal.dungeon.dungeon_sweep_lit', return_value=True), \
             patch('module.trickcal.dungeon.Timer') as mock_timer:
            mock_timer.return_value.start.return_value.reached.return_value = True
            mock_timer.return_value.reached.return_value = True
            self.assertTrue(dg2._sweep_stage('gold', DUNGEON_GOLD_SWEEP, page_dungeon_gold_stage, cost=10))

        seq = [c[0][0].name for c in dg2.device.click.call_args_list]
        self.assertEqual(
            seq,
            ['DUNGEON_GOLD_SWEEP', 'EVENT_SWEEP_MAX', 'DUNGEON_SWEEP_CONFIRM', 'EVENT_SWEEP_CLEAR'],
        )

        # 3. Stamina buy popup during sweep dialog cancels safely instead of buying.
        dg3 = _make_dungeon()
        buy_open = {'v': True}
        dg3.appear = lambda btn, offset=(0, 0), interval=0, similarity=0.85: btn is EVENT_STAMINA_BUY and buy_open['v']
        dg3.device.click.side_effect = lambda btn: buy_open.__setitem__('v', False) if btn is EVENT_STAMINA_BUY else None
        with patch('module.trickcal.dungeon.Timer') as mock_timer:
            mock_timer.return_value.reached.return_value = True
            self.assertFalse(dg3._open_sweep_dialog(DUNGEON_GOLD_SWEEP))
        dg3.device.click.assert_called_once_with(EVENT_STAMINA_BUY)

        # 4. Clone factory exits immediately when 0 -> 0 badge OR 每日入场次数已用完 toast appears.
        dg4 = _make_dungeon()
        dg4.appear = lambda btn, offset=(0, 0), interval=0, similarity=0.85: btn is DUNGEON_CLONE_ZERO
        with patch('module.trickcal.dungeon.read_dungeon_stamina', return_value=460), \
             patch('module.trickcal.dungeon.read_clone_daily_remaining', return_value=None):
            self.assertTrue(dg4._sweep_stage('clone', DUNGEON_CLONE_SWEEP, page_dungeon_clone_stage, cost=20, is_clone=True))
        dg4.device.click.assert_not_called()

        dg5 = _make_dungeon()
        dg5.appear = lambda btn, offset=(0, 0), interval=0, similarity=0.85: btn is DUNGEON_CLONE_EMPTY
        with patch('module.trickcal.dungeon.Timer') as mock_timer:
            mock_timer.return_value.reached.return_value = True
            self.assertFalse(dg5._open_sweep_dialog(DUNGEON_CLONE_SWEEP))
        dg5.device.click.assert_not_called()


if __name__ == '__main__':
    unittest.main()
