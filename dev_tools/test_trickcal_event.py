import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from module.config.server import set_server

# Bind trickcal assets/config before importing module.trickcal.*
set_server('trickcal')

from module.base.utils import load_image  # noqa: E402
from module.trickcal.assets import (  # noqa: E402
    E_4_1,
    EVENT_AUTO_END,
    EVENT_BATTLE_AUTO,
    EVENT_BATTLE_EXIT,
    EVENT_BONUS_CONFIRM,
    EVENT_DEPART,
    EVENT_DIFF_HARD_LOCKED,
    EVENT_DIFF_MEDIUM_LOCKED,
    EVENT_GUIDE_CLOSE,
    EVENT_NEW_STORY,
    EVENT_PASS_CLAIM_ALL,
    EVENT_SELECT_DECK,
    EVENT_SHOP_BUY_TITLE,
    EVENT_SHOP_CANCEL,
    EVENT_SHOP_CONFIRM,
    EVENT_SHOP_MAX,
    EVENT_SHOP_REWARD,
    EVENT_STAGE_PERFECT_CLEAR,
    EVENT_STAGE_TITLE,
    EVENT_STAGE_UNCLEARED,
    EVENT_STAMINA_BUY,
    EVENT_STORY_CONTINUE,
    EVENT_STORY_LEAVE,
    EVENT_STORY_MENU,
    EVENT_CUTSCENE_SKIP,
    EVENT_STORY_NEW,
    EVENT_STORY_SKIP_CONFIRM,
    EVENT_SWEEP_BTN,
    EVENT_SWEEP_CLEAR,
    EVENT_SWEEP_CONFIRM,
    EVENT_SWEEP_MAX,
    EVENT_SWEEP_TITLE,
    EVENT_TASK_CLAIM_ALL,
    EVENT_VICTORY_NEXT,
)
from module.trickcal.event import (  # noqa: E402
    BATTLE_EXIT_OFFSET,
    EVENT_AUTO_AREA,
    EVENT_QUICK_AREA,
    STAGE_UNCLEARED_OFFSET,
    STORY_MENU_OFFSET,
    STORY_MENU_SIMILARITY,
    VICTORY_NEXT_OFFSET,
    TrickcalEvent,
    _toggle_is_on,
)
from module.trickcal.event_extra import (  # noqa: E402
    EVENT_TASK_TABS,
    STORY_NEW_OFFSET,
    _shop_card_buy_area,
    _task_tab_selected,
    find_event_shop_unsold_cards,
)
from module.trickcal.page import (  # noqa: E402
    page_event,
    page_event_pass,
    page_event_shop,
    page_event_stage,
    page_event_story,
    page_event_task,
)


def _make_event():
    ev = TrickcalEvent.__new__(TrickcalEvent)
    ev.device = MagicMock()
    ev.device.image = np.zeros((720, 1280, 3), dtype=np.uint8)
    ev.device.click = MagicMock()
    ev.device.click_record_clear = MagicMock()
    ev.device.sleep = MagicMock()
    ev.device.screenshot = MagicMock(side_effect=lambda: ev.device.image)
    ev.device.stuck_record_clear = MagicMock()
    ev.loop = MagicMock(side_effect=lambda timeout=10: iter(range(20)))
    ev.ui_ensure = MagicMock()
    ev.ui_goto_main = MagicMock()
    ev.ui_additional = MagicMock(return_value=False)
    ev.ui_page_appear = MagicMock(return_value=False)
    ev.appear = MagicMock(return_value=False)
    ev.config = MagicMock()
    return ev


def _composite(*asset_paths):
    canvas = np.zeros((720, 1280, 3), dtype=np.uint8)
    for path in asset_paths:
        layer = load_image(path)
        mask = np.any(layer > 0, axis=2)
        canvas[mask] = layer[mask]
    return canvas


class TestTrickcalEvent(unittest.TestCase):
    def test_cutscene_and_guide_modal_priority(self):
        # 1. Confirm dialog sits over expanded story sidebar (`EVENT_CUTSCENE_SKIP`):
        #    must tap `EVENT_STORY_SKIP_CONFIRM`, never `EVENT_CUTSCENE_SKIP`.
        ev = _make_event()
        ev.device.image = _composite(
            './assets/trickcal/trickcal/EVENT_CUTSCENE_SKIP.png',
            './assets/trickcal/trickcal/EVENT_STORY_SKIP_CONFIRM.png',
        )
        ev.appear = lambda btn, offset=(0, 0), interval=0, similarity=0.85: btn.match(
            ev.device.image, offset=offset, similarity=similarity
        )
        self.assertTrue(ev.handle_event_story_or_guide())
        ev.device.click.assert_called_once_with(EVENT_STORY_SKIP_CONFIRM)

        # 2. Last story dialog sits over expanded story sidebar:
        #    must tap `EVENT_STORY_LEAVE`, never `EVENT_CUTSCENE_SKIP`.
        ev = _make_event()
        ev.device.image = _composite(
            './assets/trickcal/trickcal/EVENT_CUTSCENE_SKIP.png',
            './assets/trickcal/trickcal/EVENT_STORY_LEAVE.png',
        )
        ev.appear = lambda btn, offset=(0, 0), interval=0, similarity=0.85: btn.match(
            ev.device.image, offset=offset, similarity=similarity
        )
        self.assertTrue(ev.handle_event_story_or_guide())
        ev.device.click.assert_called_once_with(EVENT_STORY_LEAVE)

        # 3. Continue-playback dialog sits over expanded story sidebar:
        #    must tap `EVENT_STORY_CONTINUE`, never `EVENT_CUTSCENE_SKIP`.
        ev = _make_event()
        ev.device.image = _composite(
            './assets/trickcal/trickcal/EVENT_CUTSCENE_SKIP.png',
            './assets/trickcal/trickcal/EVENT_STORY_CONTINUE.png',
        )
        ev.appear = lambda btn, offset=(0, 0), interval=0, similarity=0.85: btn.match(
            ev.device.image, offset=offset, similarity=similarity
        )
        self.assertTrue(ev.handle_event_story_or_guide())
        ev.device.click.assert_called_once_with(EVENT_STORY_CONTINUE)

        # 4. Reward popup `E_4_1` sits over expanded story sidebar:
        #    must tap reward popup first.
        ev = _make_event()
        ev.device.image = _composite(
            './assets/trickcal/trickcal/EVENT_CUTSCENE_SKIP.png',
            './assets/trickcal/trickcal/E_4_1.png',
        )
        ev.appear = lambda btn, offset=(0, 0), interval=0, similarity=0.85: btn.match(
            ev.device.image, offset=offset, similarity=similarity
        )
        self.assertTrue(ev.handle_event_story_or_guide())
        ev.device.click.assert_called_once_with(E_4_1)

        # 4. Guide overlay taps top-right close X, never its center header.
        ev = _make_event()
        ev.device.image = load_image('./assets/trickcal/trickcal/EVENT_GUIDE_CLOSE.png')
        ev.appear = lambda btn, offset=(0, 0), interval=0, similarity=0.85: btn.match(
            ev.device.image, offset=offset, similarity=similarity
        )
        self.assertTrue(ev.handle_event_story_or_guide())
        ev.device.click.assert_called_once_with(EVENT_GUIDE_CLOSE)
        x1, y1, x2, y2 = EVENT_GUIDE_CLOSE.button
        self.assertGreater(x1, 1200)
        self.assertLess(y2, 60)

    def test_toggle_color_and_formation_depart(self):
        img = np.zeros((720, 1280, 3), dtype=np.uint8)
        for area in (EVENT_QUICK_AREA, EVENT_AUTO_AREA):
            x1, y1, x2, y2 = area
            img[y1:y2, x1:x2] = (150, 150, 150)  # Grey OFF state
        self.assertFalse(_toggle_is_on(img, EVENT_QUICK_AREA))
        self.assertFalse(_toggle_is_on(img, EVENT_AUTO_AREA))

        for area in (EVENT_QUICK_AREA, EVENT_AUTO_AREA):
            x1, y1, x2, y2 = area
            img[y1:y2, x1:x2] = (140, 188, 110)  # Green ON state
        self.assertTrue(_toggle_is_on(img, EVENT_QUICK_AREA))
        self.assertTrue(_toggle_is_on(img, EVENT_AUTO_AREA))

        # Walk formation: quick OFF -> tap quick -> auto OFF -> tap auto ->
        # tap 出发 -> 加成提示 (EVENT_BONUS_CONFIRM over EVENT_DEPART) -> 直接出发 ->
        # dimmed fade frame with EVENT_DEPART still matching (must NOT toggle quick/auto) -> battle.
        ev = _make_event()
        step = {'n': 0}
        frames = ['quick_off', 'auto_off', 'ready', 'bonus', 'dimmed_fade', 'battle']

        def refresh_frame():
            frame = frames[min(step['n'], len(frames) - 1)]
            canvas = np.zeros((720, 1280, 3), dtype=np.uint8)
            qx1, qy1, qx2, qy2 = EVENT_QUICK_AREA
            ax1, ay1, ax2, ay2 = EVENT_AUTO_AREA
            if frame == 'dimmed_fade':
                canvas[qy1:qy2, qx1:qx2] = (80, 105, 65)
                canvas[ay1:ay2, ax1:ax2] = (80, 105, 65)
            else:
                canvas[qy1:qy2, qx1:qx2] = (150, 150, 150) if frame == 'quick_off' else (140, 188, 110)
                canvas[ay1:ay2, ax1:ax2] = (150, 150, 150) if frame in ('quick_off', 'auto_off') else (140, 188, 110)
            ev.device.image = canvas
            return frame

        def fake_loop(timeout=10):
            for _ in range(10):
                refresh_frame()
                yield

        def fake_appear(btn, offset=(0, 0), interval=0, similarity=0.85):
            frame = frames[min(step['n'], len(frames) - 1)]
            if frame in ('quick_off', 'auto_off', 'ready'):
                return btn is EVENT_DEPART
            if frame == 'bonus':
                # Note: EVENT_DEPART still matches behind the dimmed bonus dialog!
                return btn in (EVENT_BONUS_CONFIRM, EVENT_DEPART)
            if frame == 'dimmed_fade':
                # Advance to battle after inspecting one dimmed frame where EVENT_DEPART
                # is still matched while green pixels have dropped.
                step['n'] += 1
                return btn is EVENT_DEPART
            if frame == 'battle':
                return btn is EVENT_BATTLE_AUTO
            return False

        clicks = []

        def fake_click(btn):
            clicks.append(btn.name)
            step['n'] += 1

        ev.loop = fake_loop
        ev.appear = fake_appear
        ev.device.click.side_effect = fake_click

        self.assertTrue(ev.event_formation_depart())
        self.assertEqual(
            clicks,
            ['EVENT_QUICK_TAP', 'EVENT_AUTO_TAP', 'EVENT_DEPART', 'EVENT_BONUS_CONFIRM'],
        )

    def test_battle_wait_dismisses_auto_end_and_exits(self):
        ev = _make_event()
        # Sequence: active auto battle -> victory countdown -> auto-end + new story -> exit -> stage page
        seq = ['battle', 'victory_next', 'auto_end', 'exit_only', 'stage_page']
        idx = {'i': 0}

        def fake_loop():
            while idx['i'] < len(seq):
                yield

        def fake_page_appear(page):
            return page is page_event_stage and seq[idx['i']] == 'stage_page'

        def fake_appear(btn, offset=(0, 0), interval=0, similarity=0.85):
            state = seq[idx['i']]
            if state == 'battle':
                idx['i'] += 1
                return btn is EVENT_BATTLE_AUTO
            if state == 'victory_next':
                # Both EVENT_VICTORY_NEXT and EVENT_BATTLE_EXIT appear on victory;
                # must NOT click exit while VICTORY_NEXT is counting down.
                if btn is EVENT_VICTORY_NEXT:
                    idx['i'] += 1
                    return True
                return btn is EVENT_BATTLE_EXIT
            if state == 'auto_end':
                return btn in (EVENT_AUTO_END, EVENT_NEW_STORY, EVENT_BATTLE_EXIT)
            if state == 'exit_only':
                return btn is EVENT_BATTLE_EXIT
            return False

        clicks = []

        def fake_click(btn):
            clicks.append((btn.name, btn.button))
            idx['i'] += 1

        ev.loop = fake_loop
        ev.ui_page_appear = fake_page_appear
        ev.appear = fake_appear
        ev.device.click.side_effect = fake_click

        self.assertTrue(ev.event_battle_wait(report_interval=0))
        self.assertEqual([c[0] for c in clicks], ['EVENT_AUTO_END', 'EVENT_BATTLE_EXIT'])
        # `EVENT_AUTO_END` must tap bottom continue line (y >= 670), never center card.
        self.assertGreaterEqual(clicks[0][1][1], 670)

    def test_difficulty_progression_and_lock_stop(self):
        # Case A: clears 微微辣, unlocks 中辣, fails/stops before 变态辣.
        ev = _make_event()
        # Lock queries:
        # 1. check medium lock before mild (True -> mild needs clearing)
        # 2. check medium lock after mild (False -> unlocked)
        # 3. check hard lock before medium (True -> medium needs clearing)
        # 4. check hard lock after medium (True -> still locked, stop!)
        lock_answers = {
            EVENT_DIFF_MEDIUM_LOCKED: iter([True, False]),
            EVENT_DIFF_HARD_LOCKED: iter([True, True]),
        }
        ev._diff_locked = lambda btn: next(lock_answers[btn])
        cleared = []
        ev.event_clear_current_difficulty = lambda name: cleared.append(name) or True

        ev.event_battle_clear()
        self.assertEqual(cleared, ['微微辣', '中辣'])

        # Case B: 中辣 already unlocked -> skips 微微辣 and starts at 中辣 -> 变态辣.
        ev = _make_event()
        lock_answers_b = {
            EVENT_DIFF_MEDIUM_LOCKED: iter([False, False]),
            EVENT_DIFF_HARD_LOCKED: iter([True, False]),
        }
        ev._diff_locked = lambda btn: next(lock_answers_b[btn])
        cleared_b = []
        ev.event_clear_current_difficulty = lambda name: cleared_b.append(name) or True

        ev.event_battle_clear()
        self.assertEqual(cleared_b, ['中辣', '变态辣'])

    def test_diff_locked_checks_template_and_color(self):
        ev = _make_event()
        img = load_image('./assets/trickcal/trickcal/EVENT_DIFF_MEDIUM_LOCKED.png')
        ev.device.image = img
        ev.appear = lambda btn, offset=(0, 0), interval=0, similarity=0.85: btn.match(
            ev.device.image, offset=offset, similarity=similarity
        )
        self.assertTrue(ev._diff_locked(EVENT_DIFF_MEDIUM_LOCKED))

        # Recolor the pill box to bright teal (unlocked pill color): even if
        # `appear` is mocked True, `appear_on` must reject it as unlocked.
        unlocked = img.copy()
        x1, y1, x2, y2 = EVENT_DIFF_MEDIUM_LOCKED.area
        unlocked[y1:y2, x1:x2] = (95, 218, 180)
        ev.device.image = unlocked
        ev.appear = MagicMock(return_value=True)
        self.assertFalse(ev._diff_locked(EVENT_DIFF_MEDIUM_LOCKED))

    def test_offsets_stay_within_screen_and_shift_button_targets(self):
        # 1. Stage uncleared ribbon shifted to stage 3 (+420 px) still matches & shifts button.
        EVENT_STAGE_UNCLEARED.clear_offset()
        for idx, d in enumerate(STAGE_UNCLEARED_OFFSET):
            base_val = EVENT_STAGE_UNCLEARED.area[idx]
            bound = 0 if idx < 2 else (1280 if idx == 2 else 720)
            if idx < 2:
                self.assertGreaterEqual(base_val + d, bound)
            else:
                self.assertLessEqual(base_val + d, bound)

        ribbon_img = load_image('./assets/trickcal/trickcal/EVENT_STAGE_UNCLEARED.png')
        rx1, ry1, rx2, ry2 = EVENT_STAGE_UNCLEARED.area
        shifted_canvas = np.zeros_like(ribbon_img)
        shift_x = 420
        shifted_canvas[ry1:ry2, rx1 + shift_x:rx2 + shift_x] = ribbon_img[ry1:ry2, rx1:rx2]
        self.assertTrue(EVENT_STAGE_UNCLEARED.match_luma(shifted_canvas, offset=STAGE_UNCLEARED_OFFSET))
        self.assertEqual(EVENT_STAGE_UNCLEARED.button[0], 340 + shift_x)

        # Simulated 中辣-yellow ribbon (teal pixels recolored to yellow) still matches by luma,
        # whereas 3 cleared bright-gold diamonds must NOT match.
        yellow_canvas = shifted_canvas.copy()
        patch = yellow_canvas[ry1:ry2, rx1 + shift_x:rx2 + shift_x]
        teal_mask = patch[:, :, 1] > patch[:, :, 0]
        patch[teal_mask] = (230, 185, 70)
        self.assertTrue(EVENT_STAGE_UNCLEARED.match_luma(yellow_canvas, offset=STAGE_UNCLEARED_OFFSET))

        gold_stars = yellow_canvas.copy()
        sp = gold_stars[ry1:ry2, rx1 + shift_x:rx2 + shift_x]
        sp[sp.mean(axis=2) < 110] = (245, 210, 80)
        self.assertFalse(EVENT_STAGE_UNCLEARED.match_luma(gold_stars, offset=STAGE_UNCLEARED_OFFSET))

        # 2. Battle 退出 shifted +102 px (2-button) and +204 px (1-button) still match & shift.
        EVENT_BATTLE_EXIT.clear_offset()
        for idx, d in enumerate(BATTLE_EXIT_OFFSET):
            base_val = EVENT_BATTLE_EXIT.area[idx]
            if idx < 2:
                self.assertGreaterEqual(base_val + d, 0)
            else:
                self.assertLessEqual(base_val + d, 1280 if idx == 2 else 720)

        exit_img = load_image('./assets/trickcal/trickcal/EVENT_BATTLE_EXIT.png')
        ex1, ey1, ex2, ey2 = EVENT_BATTLE_EXIT.area
        for delta in (102, 204):
            shifted_exit = np.zeros_like(exit_img)
            shifted_exit[ey1:ey2, ex1 + delta:ex2 + delta] = exit_img[ey1:ey2, ex1:ex2]
            self.assertTrue(EVENT_BATTLE_EXIT.match(shifted_exit, offset=BATTLE_EXIT_OFFSET))
            self.assertEqual(EVENT_BATTLE_EXIT.button[0], ex1 + delta)

        # 3. Battle 前往下一关 shifted -102 px (2-button Victory layout) still matches.
        EVENT_VICTORY_NEXT.clear_offset()
        for idx, d in enumerate(VICTORY_NEXT_OFFSET):
            base_val = EVENT_VICTORY_NEXT.area[idx]
            if idx < 2:
                self.assertGreaterEqual(base_val + d, 0)
            else:
                self.assertLessEqual(base_val + d, 1280 if idx == 2 else 720)

        next_img = load_image('./assets/trickcal/trickcal/EVENT_VICTORY_NEXT.png')
        nx1, ny1, nx2, ny2 = EVENT_VICTORY_NEXT.area
        shifted_next = np.zeros_like(next_img)
        shifted_next[ny1:ny2, nx1 - 102:nx2 - 102] = next_img[ny1:ny2, nx1:nx2]
        self.assertTrue(EVENT_VICTORY_NEXT.match(shifted_next, offset=VICTORY_NEXT_OFFSET))
        self.assertEqual(EVENT_VICTORY_NEXT.button[0], nx1 - 102)

        # Reset offsets so later tests see clean defaults.
        EVENT_STAGE_UNCLEARED.clear_offset()
        EVENT_BATTLE_EXIT.clear_offset()
        EVENT_VICTORY_NEXT.clear_offset()
        self.assertIsNotNone(EVENT_STAGE_TITLE)

    def test_sweep_btn_lit_rejects_disabled_grey(self):
        ev = _make_event()
        img = load_image('./assets/trickcal/trickcal/EVENT_SWEEP_BTN.png')
        ev.device.image = img
        ev.appear = lambda btn, offset=(0, 0), interval=0, similarity=0.85: btn.match(
            ev.device.image, offset=offset, similarity=similarity
        )
        self.assertTrue(ev._sweep_btn_lit())

        # Disabled 速战 button (e.g. stage not 3-starred yet) is grey (~164, 164, 164).
        disabled = img.copy()
        x1, y1, x2, y2 = EVENT_SWEEP_BTN.area
        disabled[y1:y2, x1:x2] = (164, 164, 164)
        ev.device.image = disabled
        ev.appear = MagicMock(return_value=True)
        self.assertFalse(ev._sweep_btn_lit())

    def test_event_battle_sweep_clears_stamina_and_stops(self):
        ev = _make_event()
        stamina_reads = iter([55, 55, 5])
        ev._read_event_stamina = lambda: next(stamina_reads)
        ev._sweep_btn_lit = MagicMock(return_value=True)

        # Sequence of visible screens across the single sweep cycle:
        # 1. open stage detail (EVENT_SWEEP_BTN on page)
        # 2. open sweep dialog (EVENT_SWEEP_BTN -> EVENT_SWEEP_TITLE)
        # 3. confirm dialog (EVENT_SWEEP_TITLE -> 最大 -> 速战 -> EVENT_SWEEP_CLEAR)
        # 4. clear dialog (EVENT_SWEEP_CLEAR -> 确定 -> back on page_event_stage)
        stage_state = {'phase': 'detail'}

        def fake_appear(btn, offset=(0, 0), interval=0, similarity=0.85):
            phase = stage_state['phase']
            if phase == 'detail':
                return btn in (EVENT_SELECT_DECK, EVENT_SWEEP_BTN)
            if phase == 'dialog':
                return btn in (EVENT_SWEEP_TITLE, EVENT_SWEEP_MAX, EVENT_SWEEP_CONFIRM)
            if phase == 'clear':
                return btn is EVENT_SWEEP_CLEAR
            if phase == 'done':
                return btn in (EVENT_SELECT_DECK, EVENT_SWEEP_BTN)
            return False

        def fake_page_appear(page):
            return page is page_event_stage and stage_state['phase'] in ('detail', 'done')

        clicks = []

        def fake_click(btn):
            clicks.append(btn.name)
            if btn is EVENT_SWEEP_BTN:
                stage_state['phase'] = 'dialog'
            elif btn is EVENT_SWEEP_CONFIRM:
                stage_state['phase'] = 'clear'
            elif btn is EVENT_SWEEP_CLEAR:
                stage_state['phase'] = 'done'

        ev.appear = fake_appear
        ev.ui_page_appear = fake_page_appear
        ev.device.click.side_effect = fake_click

        with patch('module.trickcal.event.Timer') as mock_timer_cls:
            inst = mock_timer_cls.return_value
            inst.start.return_value = inst
            inst.reached.return_value = True
            self.assertTrue(ev.event_battle_sweep())

        self.assertEqual(
            clicks,
            ['EVENT_DIFF_MILD_TAP', 'EVENT_SWEEP_BTN', 'EVENT_SWEEP_MAX', 'EVENT_SWEEP_CONFIRM', 'EVENT_SWEEP_CLEAR'],
        )

    def test_run_respects_sweep_stamina_option(self):
        for flag, expected_calls in ((False, 0), (True, 1)):
            ev = _make_event()
            ev.config.TrickcalEvent_SweepStamina = flag
            order = []
            ev.event_open = MagicMock(return_value=True)
            ev.event_battle_clear = MagicMock(side_effect=lambda: order.append('clear'))
            ev.event_battle_sweep = MagicMock(side_effect=lambda: order.append('sweep'))
            ev.event_story_clear = MagicMock(side_effect=lambda: order.append('story'))
            ev.event_claim_tasks = MagicMock(side_effect=lambda: order.append('tasks'))
            ev.event_claim_pass = MagicMock(side_effect=lambda: order.append('pass'))
            ev.event_shop_buy = MagicMock(side_effect=lambda: order.append('shop'))
            ev.run()
            self.assertEqual(ev.event_battle_sweep.call_count, expected_calls)
            expected_order = ['clear', 'sweep', 'story', 'tasks', 'pass', 'shop'] if flag else ['clear', 'story', 'tasks', 'pass', 'shop']
            self.assertEqual(order, expected_order)

    def test_perfect_clear_toast_aborts_stage_open(self):
        ev = _make_event()
        ev._stage_uncleared_appear = MagicMock(return_value=True)
        ev.appear = lambda btn, offset=(0, 0), interval=0, similarity=0.85: btn is EVENT_STAGE_PERFECT_CLEAR
        self.assertFalse(ev.event_clear_current_difficulty('中辣'))
        ev.device.click.assert_not_called()

    def test_close_sweep_clear_ignores_single_frame_dip(self):
        ev = _make_event()
        # Frame 0: CLEAR visible -> click 确定
        # Frame 1: 1-frame press-down dip where CLEAR misses while stage title still matches behind it
        # Frame 2: CLEAR still visible -> click 确定 again
        # Frame 3: detail EVENT_SWEEP_BTN reappears -> CLEAR truly gone!
        frames = ['clear', 'dip', 'clear', 'detail']
        idx = {'i': 0}

        def fake_loop(timeout=10):
            while idx['i'] < len(frames):
                yield
                idx['i'] += 1

        def fake_appear(btn, offset=(0, 0), interval=0, similarity=0.85):
            state = frames[idx['i']]
            if state == 'clear':
                return btn is EVENT_SWEEP_CLEAR
            if state == 'detail':
                return btn is EVENT_SWEEP_BTN
            return False

        ev.loop = fake_loop
        ev.appear = fake_appear
        ev.ui_page_appear = lambda page: page is page_event_stage

        with patch('module.trickcal.event.Timer') as mock_timer_cls:
            inst = mock_timer_cls.return_value
            inst.reached.return_value = True
            self.assertTrue(ev._close_sweep_clear())

        self.assertEqual(ev.device.click.call_count, 2)

    def test_stamina_buy_popup_cancels_and_stops_sweep(self):
        # 1. Button mask must target the left 「取消」 button, never the right 「购买」 button.
        bx1, by1, bx2, by2 = EVENT_STAMINA_BUY.button
        self.assertLessEqual(bx2, 630)
        self.assertGreaterEqual(bx1, 395)

        # 2. When 「购买朱珠糖」 appears during _open_sweep_dialog, must click 取消,
        #    mark _out_of_stamina = True, and return False without pressing 购买.
        ev = _make_event()
        ev._out_of_stamina = False
        state = {'buy_up': True}

        def fake_appear(btn, offset=(0, 0), interval=0, similarity=0.85):
            if state['buy_up']:
                return btn is EVENT_STAMINA_BUY
            return btn is EVENT_SWEEP_BTN

        def fake_click(btn):
            if btn is EVENT_STAMINA_BUY:
                state['buy_up'] = False

        ev.appear = fake_appear
        ev.device.click.side_effect = fake_click

        with patch('module.trickcal.event.Timer') as mock_timer_cls:
            inst = mock_timer_cls.return_value
            inst.reached.return_value = True
            self.assertFalse(ev._open_sweep_dialog())

        self.assertTrue(ev._out_of_stamina)
        ev.device.click.assert_called_once_with(EVENT_STAMINA_BUY)

    def test_event_story_new_offset_and_skip(self):
        # 1. STORY_NEW_OFFSET stays inside screen bounds and shifts button to ticket slot 3.
        EVENT_STORY_NEW.clear_offset()
        for idx, d in enumerate(STORY_NEW_OFFSET):
            base_val = EVENT_STORY_NEW.area[idx]
            if idx < 2:
                self.assertGreaterEqual(base_val + d, 0)
            else:
                self.assertLessEqual(base_val + d, 1280 if idx == 2 else 720)

        new_img = load_image('./assets/trickcal/trickcal/EVENT_STORY_NEW.png')
        nx1, ny1, nx2, ny2 = EVENT_STORY_NEW.area
        shifted = np.zeros_like(new_img)
        shifted[ny1:ny2, nx1 + 380:nx2 + 380] = new_img[ny1:ny2, nx1:nx2]
        self.assertTrue(EVENT_STORY_NEW.match(shifted, offset=STORY_NEW_OFFSET))
        self.assertEqual(EVENT_STORY_NEW.button[0], 445 + 380)
        EVENT_STORY_NEW.clear_offset()

        # 2. event_story_clear opens NEW ticket, skips cutscene, and finishes when no NEW remains.
        ev = _make_event()
        state = {'phase': 'has_new'}

        def fake_appear(btn, offset=(0, 0), interval=0, similarity=0.85):
            return state['phase'] == 'has_new' and btn is EVENT_STORY_NEW

        def fake_page_appear(page):
            return page is page_event_story and state['phase'] in ('has_new', 'done')

        def fake_skip():
            if state['phase'] == 'cutscene':
                state['phase'] = 'done'
                return True
            return False

        def fake_click(btn):
            if btn.name == 'EVENT_STORY_NEW':
                state['phase'] = 'cutscene'

        ev.appear = fake_appear
        ev.ui_page_appear = fake_page_appear
        ev.handle_event_story_or_guide = fake_skip
        ev.device.drag = MagicMock()
        ev.device.click.side_effect = fake_click

        with patch('module.trickcal.event_extra.Timer') as mock_timer_cls:
            inst = mock_timer_cls.return_value
            inst.start.return_value = inst
            inst.reached.return_value = True
            self.assertTrue(ev.event_story_clear())

        self.assertEqual([c[0][0].name for c in ev.device.click.call_args_list], ['EVENT_STORY_NEW'])

        # 3. Peeking NEW ticket off right edge (button=(1160, 555, 1405, 675)):
        #    scrolls left first and clamps click strictly inside x <= 1260.
        ev2 = _make_event()
        peeking_canvas = np.zeros_like(new_img)
        peeking_shift = 1152 - nx1
        peeking_canvas[ny1:ny2, nx1 + peeking_shift:nx2 + peeking_shift] = new_img[ny1:ny2, nx1:nx2]
        ev2.device.image = peeking_canvas
        st2 = {'scrolled': False, 'phase': 'has_new'}

        def fake_appear2(btn, offset=(0, 0), interval=0, similarity=0.85):
            if st2['phase'] != 'has_new' or btn is not EVENT_STORY_NEW:
                return False
            if not st2['scrolled']:
                return EVENT_STORY_NEW.match(peeking_canvas, offset=offset, similarity=similarity)
            # After scroll, still keep ticket near right edge to verify clamp.
            return EVENT_STORY_NEW.match(peeking_canvas, offset=offset, similarity=similarity)

        def fake_drag2(*args, **kwargs):
            st2['scrolled'] = True

        def fake_click2(btn):
            if btn.name == 'EVENT_STORY_NEW':
                st2['phase'] = 'cutscene'

        ev2.appear = fake_appear2
        ev2.ui_page_appear = lambda page: page is page_event_story and st2['phase'] in ('has_new', 'done')
        ev2.handle_event_story_or_guide = lambda: st2.__setitem__('phase', 'done') or True if st2['phase'] == 'cutscene' else False
        ev2.device.drag = MagicMock(side_effect=fake_drag2)
        ev2.device.click.side_effect = fake_click2

        with patch('module.trickcal.event_extra.Timer') as mock_timer_cls:
            inst = mock_timer_cls.return_value
            inst.start.return_value = inst
            inst.reached.return_value = True
            self.assertTrue(ev2.event_story_clear())

        self.assertGreaterEqual(ev2.device.drag.call_count, 1)
        clicked_btn = ev2.device.click.call_args_list[0][0][0]
        self.assertEqual(clicked_btn.name, 'EVENT_STORY_NEW')
        self.assertLessEqual(clicked_btn.area[2], 1260)
        self.assertGreaterEqual(clicked_btn.area[0], 20)
        EVENT_STORY_NEW.clear_offset()

    def test_event_claim_tasks_walks_three_tabs(self):
        ev = _make_event()
        img_lit = load_image('./assets/trickcal/trickcal/EVENT_TASK_CLAIM_ALL.png')
        cx1, cy1, cx2, cy2 = EVENT_TASK_CLAIM_ALL.area

        def make_tab_frame(active_idx, lit):
            frame = img_lit.copy()
            if not lit:
                frame[cy1:cy2, cx1:cx2] = (174, 174, 174)
            for i, (_, (tx1, ty1, tx2, ty2)) in enumerate(EVENT_TASK_TABS):
                frame[ty1:ty2, tx1:tx2] = (245, 210, 109) if i == active_idx else (244, 232, 188)
            return frame

        # Start already on tab 0 (每日任务) with lit claim button.
        # On 成就 (tab 1), simulate first tap swallowed (tab stays cream on tab 0)
        # and second tap succeeding with lit 全部领取.
        state = {'active': 0, 'claimed': [False, False, False], 'ach_swallowed': True}
        ev.device.image = make_tab_frame(0, True)

        def fake_click(btn):
            if btn.name == 'EVENT_TASK_TAB':
                target = next(i for i, (_, area) in enumerate(EVENT_TASK_TABS) if area == btn.area)
                if target == 1 and state['ach_swallowed']:
                    state['ach_swallowed'] = False
                    return
                state['active'] = target
                lit = (target in (0, 1)) and not state['claimed'][target]
                ev.device.image = make_tab_frame(target, lit)
            elif btn is EVENT_TASK_CLAIM_ALL:
                state['claimed'][state['active']] = True
                ev.device.image = make_tab_frame(state['active'], False)

        ev.appear = lambda btn, offset=(0, 0), interval=0, similarity=0.85: btn is EVENT_TASK_CLAIM_ALL
        ev.ui_page_appear = lambda page: page is page_event_task
        ev.device.click.side_effect = fake_click

        with patch('module.trickcal.event_extra.Timer') as mock_timer_cls:
            inst = mock_timer_cls.return_value
            inst.start.return_value = inst
            inst.reached.return_value = True
            self.assertTrue(ev.event_claim_tasks())

        self.assertTrue(state['claimed'][0])
        self.assertTrue(state['claimed'][1])
        self.assertTrue(_task_tab_selected(make_tab_frame(1, False), EVENT_TASK_TABS[1][1]))
        self.assertFalse(_task_tab_selected(make_tab_frame(1, False), EVENT_TASK_TABS[0][1]))
        names = [c[0][0].name for c in ev.device.click.call_args_list]
        self.assertEqual(
            names,
            ['EVENT_TASK_CLAIM_ALL', 'EVENT_TASK_TAB', 'EVENT_TASK_TAB', 'EVENT_TASK_CLAIM_ALL', 'EVENT_TASK_TAB'],
        )

    def test_find_event_shop_unsold_cards_skips_sold_and_empty(self):
        img = np.zeros((720, 1280, 3), dtype=np.uint8)
        # Slot (0,0) darkened 已购买 (grey), slot (0,1), (0,2), (1,0) unsold cream cards,
        # slot (1,1) dark empty wood, plus a narrow peeking top strip (h=30) below row 1.
        img[148:343, 568:763] = (105, 116, 93)
        for x1, y1, x2, y2 in (
            (783, 148, 978, 343),
            (998, 148, 1192, 343),
            (568, 363, 763, 558),
        ):
            img[y1:y2, x1:x2] = (244, 240, 228)
        img[575:605, 568:763] = (244, 240, 228)  # peeking strip below

        cards = find_event_shop_unsold_cards(img)
        self.assertEqual(cards, [(783, 148, 978, 343), (998, 148, 1192, 343), (568, 363, 763, 558)])

        # Wide white item-info tooltip covering multiple slots must be rejected (> 240px).
        tooltip = np.zeros((720, 1280, 3), dtype=np.uint8)
        tooltip[148:558, 568:1192] = (244, 240, 228)
        self.assertEqual(find_event_shop_unsold_cards(tooltip), [])

    def test_event_shop_buy_stops_on_unaffordable_without_skipping(self):
        ev = _make_event()
        # Grid starts with card 1 (top-left), card 2 (top-mid), card 3 (top-right).
        # Card 1 buys successfully and turns sold; card 2 cannot be afforded (grey 购买),
        # so event_shop_buy must cancel and STOP immediately without opening card 3.
        card1 = (568, 148, 763, 343)
        card2 = (783, 148, 978, 343)
        card3 = (998, 148, 1192, 343)
        buy1 = _shop_card_buy_area(card1)
        buy2 = _shop_card_buy_area(card2)
        buy3 = _shop_card_buy_area(card3)

        def make_grid(sold_first):
            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            if not sold_first:
                frame[148:343, 568:763] = (244, 240, 228)
            frame[148:343, 783:978] = (244, 240, 228)
            frame[148:343, 998:1192] = (244, 240, 228)
            return frame

        state = {'sold1': False, 'phase': 'shop'}
        ev.device.image = make_grid(False)
        opened_cards = []

        confirm_tpl = load_image('./assets/trickcal/trickcal/EVENT_SHOP_CONFIRM.png')
        cx1, cy1, cx2, cy2 = EVENT_SHOP_CONFIRM.area
        confirm_grey = np.repeat(
            (confirm_tpl[cy1:cy2, cx1:cx2].mean(axis=2, keepdims=True) * 0.78).astype(np.uint8),
            3,
            axis=2,
        )

        def fake_appear(btn, offset=(0, 0), interval=0, similarity=0.85):
            phase = state['phase']
            if phase == 'buy_ok':
                if btn is EVENT_SHOP_CONFIRM:
                    # Lit yellow confirm button color inside frame.
                    ev.device.image[cy1:cy2, cx1:cx2] = (242, 210, 117)
                return btn in (EVENT_SHOP_BUY_TITLE, EVENT_SHOP_MAX, EVENT_SHOP_CONFIRM)
            if phase == 'buy_fail':
                # Disabled grey 购买 fails RGB `appear(EVENT_SHOP_CONFIRM)`, so render a
                # greyscale confirm patch for `match_luma` + `appear_on` == False.
                ev.device.image[cy1:cy2, cx1:cx2] = confirm_grey
                return btn in (EVENT_SHOP_BUY_TITLE, EVENT_SHOP_CANCEL)
            if phase == 'reward':
                return btn is EVENT_SHOP_REWARD
            return False

        def fake_click(btn):
            if btn.name == 'EVENT_SHOP_CARD':
                opened_cards.append(btn.area)
                state['phase'] = 'buy_ok' if btn.area == buy1 else 'buy_fail'
            elif btn is EVENT_SHOP_CONFIRM:
                state['sold1'] = True
                state['phase'] = 'reward'
            elif btn is EVENT_SHOP_REWARD:
                state['phase'] = 'shop'
                ev.device.image = make_grid(True)
            elif btn is EVENT_SHOP_CANCEL:
                state['phase'] = 'shop'
                ev.device.image = make_grid(True)

        ev.appear = fake_appear
        ev.ui_page_appear = lambda page: page is page_event_shop and state['phase'] == 'shop'
        ev.device.click.side_effect = fake_click

        with patch('module.trickcal.event_extra.Timer') as mock_timer_cls:
            inst = mock_timer_cls.return_value
            inst.start.return_value = inst
            inst.reached.return_value = True
            self.assertTrue(ev.event_shop_buy())

        self.assertEqual(opened_cards, [buy1, buy2])
        self.assertNotIn(buy3, opened_cards)
        for card, buy in ((card1, buy1), (card2, buy2)):
            self.assertGreater(buy[1], (card[1] + card[3]) // 2)

    def test_event_story_menu_luma_over_varied_backgrounds(self):
        EVENT_STORY_MENU.clear_offset()
        x1, y1, x2, y2 = EVENT_STORY_MENU.area
        ox, oy = STORY_MENU_OFFSET
        self.assertGreaterEqual(x1 - ox, 0)
        self.assertGreaterEqual(y1 - oy, 0)
        self.assertLessEqual(x2 + ox, 1280)
        self.assertLessEqual(y2 + oy, 720)

        tmpl = load_image('./assets/trickcal/trickcal/EVENT_STORY_MENU.png')
        patch = tmpl[y1:y2, x1:x2]
        bar_mask = patch.mean(axis=2) > 195

        # Dark roof shadow vs bright sky / warm bg behind the translucent dark circle.
        for bg_rgb in ((25, 30, 35), (125, 140, 155), (145, 115, 95)):
            canvas = np.full((720, 1280, 3), bg_rgb, dtype=np.uint8)
            region = canvas[y1:y2, x1:x2]
            region[bar_mask] = patch[bar_mask]

            ev = _make_event()
            ev.device.image = canvas
            self.assertTrue(ev.handle_event_story_or_guide())
            ev.device.click.assert_called_once_with(EVENT_STORY_MENU)
            bx1, by1, bx2, by2 = EVENT_STORY_MENU.button
            self.assertGreaterEqual(bx1, 1200)
            self.assertLessEqual(by2, 70)

        # Plain backgrounds and vertical-stripe pattern must not match.
        for bg_rgb in ((25, 30, 35), (240, 240, 240)):
            plain = np.full((720, 1280, 3), bg_rgb, dtype=np.uint8)
            self.assertFalse(
                EVENT_STORY_MENU.match_luma(plain, offset=STORY_MENU_OFFSET, similarity=STORY_MENU_SIMILARITY)
            )

        stripes = np.full((720, 1280, 3), (40, 50, 40), dtype=np.uint8)
        stripes[y1:y2, x1:x2:4] = (235, 235, 220)
        self.assertFalse(
            EVENT_STORY_MENU.match_luma(stripes, offset=STORY_MENU_OFFSET, similarity=STORY_MENU_SIMILARITY)
        )
        EVENT_STORY_MENU.clear_offset()

    def test_handle_app_boot_skips_cutscene_and_returns_to_main(self):
        EVENT_STORY_MENU.clear_offset()
        x1, y1, x2, y2 = EVENT_STORY_MENU.area
        tmpl = load_image('./assets/trickcal/trickcal/EVENT_STORY_MENU.png')
        patch = tmpl[y1:y2, x1:x2]
        bar_mask = patch.mean(axis=2) > 195
        menu_frame = np.full((720, 1280, 3), (25, 30, 35), dtype=np.uint8)
        menu_frame[y1:y2, x1:x2][bar_mask] = patch[bar_mask]

        frames = [
            menu_frame,
            load_image('./assets/trickcal/trickcal/EVENT_CUTSCENE_SKIP.png'),
            load_image('./assets/trickcal/trickcal/EVENT_STORY_SKIP_CONFIRM.png'),
            np.zeros((720, 1280, 3), dtype=np.uint8),
        ]
        idx = {'i': 0}
        clicks = []

        ev = _make_event()
        ev.device.has_cached_image = True
        ev.device.image = frames[0]
        ev.device.screenshot = MagicMock(side_effect=lambda: setattr(ev.device, 'image', frames[idx['i']]) or ev.device.image)
        ev.appear = lambda btn, offset=(0, 0), interval=0, similarity=0.85: btn.match(
            ev.device.image, offset=offset, similarity=similarity
        )
        ev.ui_page_appear = lambda page: page is page_event_story and idx['i'] >= 3

        def fake_click(btn):
            clicks.append(btn.name)
            idx['i'] = min(idx['i'] + 1, len(frames) - 1)

        ev.device.click.side_effect = fake_click
        ev.handle_idle_title = MagicMock(return_value=False)

        self.assertTrue(ev.handle_app_boot(skip_first_screenshot=True, timeout=10))
        self.assertEqual(clicks, ['EVENT_STORY_MENU', 'EVENT_CUTSCENE_SKIP', 'EVENT_STORY_SKIP_CONFIRM'])
        ev.ui_goto_main.assert_called_once_with()
        ev.handle_idle_title.assert_not_called()
        EVENT_STORY_MENU.clear_offset()

    def test_event_claim_pass_opens_and_claims_until_dim(self):
        img_lit = load_image('./assets/trickcal/trickcal/EVENT_PASS_CLAIM_ALL.png')
        cx1, cy1, cx2, cy2 = EVENT_PASS_CLAIM_ALL.area
        self.assertTrue(EVENT_PASS_CLAIM_ALL.appear_on(img_lit, threshold=30))

        img_dim = img_lit.copy()
        img_dim[cy1:cy2, cx1:cx2] = (161, 161, 161)
        self.assertFalse(EVENT_PASS_CLAIM_ALL.appear_on(img_dim, threshold=30))

        ev = _make_event()
        phase = {'step': 'event'}
        ev.device.image = np.zeros((720, 1280, 3), dtype=np.uint8)
        clicks = []

        def fake_page_appear(page):
            if phase['step'] == 'event':
                return page is page_event
            if phase['step'] in ('pass_lit', 'pass_dim'):
                return page is page_event_pass
            return False

        def fake_appear(btn, offset=(0, 0), interval=0, similarity=0.85):
            if phase['step'] == 'reward':
                return btn is EVENT_SHOP_REWARD
            if phase['step'] == 'pass_lit' and btn is EVENT_PASS_CLAIM_ALL:
                return True
            return False

        def fake_click(btn):
            clicks.append((btn.name, btn.area))
            if btn.name == 'EVENT_PASS_ENTRY':
                phase['step'] = 'pass_lit'
                ev.device.image = img_lit
            elif btn is EVENT_PASS_CLAIM_ALL:
                phase['step'] = 'reward'
            elif btn is EVENT_SHOP_REWARD:
                phase['step'] = 'pass_dim'
                ev.device.image = img_dim

        ev.ui_page_appear = fake_page_appear
        ev.appear = fake_appear
        ev.device.click.side_effect = fake_click

        with patch('module.trickcal.event_extra.Timer') as mock_timer_cls:
            inst = mock_timer_cls.return_value
            inst.start.return_value = inst
            inst.reached.return_value = True
            self.assertTrue(ev.event_claim_pass())

        ev.ui_ensure.assert_called_once_with(page_event)
        self.assertEqual([c[0] for c in clicks], ['EVENT_PASS_ENTRY', 'EVENT_PASS_CLAIM_ALL', 'EVENT_SHOP_REWARD'])
        ex1, ey1, ex2, ey2 = clicks[0][1]
        self.assertGreaterEqual(ex1, 945)
        self.assertLessEqual(ex2, 1135)
        self.assertGreaterEqual(ey1, 622)
        self.assertLessEqual(ey2, 670)

    def test_event_battle_wait_dismisses_level_up_via_reward_popup(self):
        ev = _make_event()
        seq = ['level_up', 'stage']
        ev.loop = lambda timeout=10: iter(range(len(seq) + 2))
        ev.ui_page_appear = lambda p: p is page_event_stage and seq[0] == 'stage'
        ev.handle_stamina_buy_popup = lambda: False
        ev.handle_reward_popup = MagicMock(side_effect=lambda: (seq.pop(0) and True) if seq[0] == 'level_up' else False)
        self.assertTrue(ev.event_battle_wait(report_interval=0))
        self.assertGreaterEqual(ev.handle_reward_popup.call_count, 1)


if __name__ == '__main__':
    unittest.main()
