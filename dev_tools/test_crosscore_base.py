import os
import unittest
from unittest.mock import MagicMock

import numpy as np

from module.config.server import set_server

# Bind crosscore config/assets before importing any module.crosscore.* module.
set_server('crosscore')

from module.base.utils import crop, load_image  # noqa: E402
from module.crosscore.assets import (  # noqa: E402
    ORDER_BUILD,
    ORDER_LACK,
    ORDER_NEXT,
)
from module.crosscore.base import (  # noqa: E402
    CARD_DELIVER,
    CARD_LACK,
    CRAFT_BACK,
    CRAFT_BLACKBOX,
    CRAFT_CONFIRM,
    CRAFT_FUSED,
    CRAFT_MAX_PER_BATCH,
    CRAFT_MIN,
    CRAFT_PLUS,
    CRAFT_RESULT,
    OCR_FUSED_HELD,
    ORDER_BUILD_CORE,
    ORDER_GRID,
    CrosscoreBase,
)
from module.crosscore.utils import find_all, template_of  # noqa: E402

# Archived original attachment of the 2026-11-28 10:07 熔融石英 dialog:
# 38/40 red, 合成份数 1, the 确定 button greyed out. Only the optional real-image
# test below uses it; every other test works on synthetic frames.
REAL_INSUFFICIENT_SHOT = './screenshots/crosscore/craft_insufficient_20261128.png'


def _make_base():
    base = CrosscoreBase.__new__(CrosscoreBase)
    base.device = MagicMock()
    base.device.image = np.zeros((720, 1280, 3), dtype=np.uint8)
    base.device.click = MagicMock()
    base.device.click_record_clear = MagicMock()
    base.device.multi_click = MagicMock()
    base.loop = MagicMock(side_effect=lambda timeout=10: iter(range(10)))
    base.appear = MagicMock(return_value=False)
    base.wait_until_appear = MagicMock(return_value=True)
    base.wait_until_disappear = MagicMock(return_value=True)
    base.wait_until_still = MagicMock(return_value=True)
    base.handle_item_popup = MagicMock(return_value=False)
    base.order_library_wait = MagicMock(return_value=True)
    return base


def _pressed_in(base, button):
    """Whether any device click landed inside `button`'s area."""
    x1, y1, x2, y2 = button.area
    for call in base.device.click.call_args_list:
        if not call[0]:
            continue
        area = getattr(call[0][0], 'area', None)
        if not area:
            continue
        cx = (area[0] + area[2]) / 2.0
        cy = (area[1] + area[3]) / 2.0
        if x1 <= cx <= x2 and y1 <= cy <= y2:
            return True
    return False


def _make_dialog_base(visible):
    """Dialog harness where only the buttons in `visible` are on screen."""
    base = _make_base()
    base.read_number = MagicMock(return_value=1)

    def fake_appear(button, offset=(0, 0), interval=0, **kwargs):
        return any(button is item for item in visible)

    base.appear = MagicMock(side_effect=fake_appear)
    return base


def _paint_rare_card_border(patch):
    """Recolour outer card background around ORDER_BUILD_CORE to golden 稀有."""
    cx1, cy1, cx2, cy2 = ORDER_BUILD_CORE
    out = patch.copy()
    h, w, _ = out.shape
    for y in range(h):
        t = y / max(1, h - 1)
        gold = np.array([235 - 65 * t, 210 - 60 * t, 110 - 30 * t], dtype=np.uint8)
        for x in range(w):
            if cx1 <= x < cx2 and cy1 <= y < cy2:
                continue
            out[y, x] = gold
    return out


class TestCrosscoreBaseOrders(unittest.TestCase):
    def test_order_build_points_matches_yellow_rare_card(self):
        base = _make_base()
        img = load_image('./assets/crosscore/crosscore/ORDER_BUILD.png')

        # Place a golden-yellow 稀有构建订单 card in the top-left slot while
        # keeping the original grey 构建订单 card in the bottom-right slot.
        tpl = template_of(ORDER_BUILD)
        th, tw, _ = tpl.shape
        x, y = 412, 140
        img[y:y + th, x:x + tw] = _paint_rare_card_border(tpl)
        base.device.image = img

        # Full-frame template misses the golden card because of its padding.
        full_points = find_all(img, tpl, ORDER_GRID, similarity=0.86)
        self.assertEqual(full_points, [(1092, 444)])

        # Core pass-ticket matching finds both yellow rare and regular cards.
        core_points = base.order_build_points()
        self.assertEqual(core_points, [(412, 140), (1092, 444)])

        # Smoke check on ORDER_SOLD.png: non-build cards must not false-match.
        base.device.image = load_image('./assets/crosscore/crosscore/ORDER_SOLD.png')
        self.assertLessEqual(len(base.order_build_points()), 1)

    def test_order_friends_crafts_more_than_two_lacked_orders(self):
        base = _make_base()
        base.friend_list_enter = MagicMock(return_value=True)
        # 3 friends then back to own library (ORDER_NEXT disappears on 4th scan).
        friend_idx = {'i': 0}

        def fake_scan(can_craft=True):
            # Friend libraries 0, 1, 2 each need 1 craft before returning 'empty'.
            if not getattr(base, '_crafted_here', False):
                base._crafted_here = True
                return 'lacked'
            base._crafted_here = False
            return 'empty'

        def fake_craft_missing():
            return 'ok'

        def fake_appear(btn, offset=(0, 0), interval=0):
            if btn is ORDER_NEXT:
                friend_idx['i'] += 1
                return friend_idx['i'] <= 3
            return False

        base._crafted_here = False
        base.order_scan = MagicMock(side_effect=fake_scan)
        base.craft_missing = MagicMock(side_effect=fake_craft_missing)
        base.appear = MagicMock(side_effect=fake_appear)

        base.order_friends(crafts=16, can_craft=True)
        self.assertEqual(base.craft_missing.call_count, 3)

    def test_order_friends_short_craft_disables_further_crafting(self):
        base = _make_base()
        base.friend_list_enter = MagicMock(return_value=True)

        # Friend 1 runs craft_missing -> 'short'; Friend 2 still scans with
        # can_craft=False so ready cards there can still be delivered without
        # retrying crafting or aborting the friend walk.
        seen_can_craft = []
        friend_idx = {'i': 0}

        def fake_scan(can_craft=True):
            seen_can_craft.append(can_craft)
            if len(seen_can_craft) == 1:
                return 'lacked'
            return 'empty'

        def fake_appear(btn, offset=(0, 0), interval=0):
            if btn is ORDER_NEXT:
                friend_idx['i'] += 1
                return friend_idx['i'] <= 2
            return False

        base.order_scan = MagicMock(side_effect=fake_scan)
        base.craft_missing = MagicMock(return_value='short')
        base.appear = MagicMock(side_effect=fake_appear)

        base.order_friends(crafts=16, can_craft=True)
        # Scans: friend 1 (True -> short), friend 1 rescan (False), friend 2 (False), own (False).
        self.assertEqual(seen_can_craft, [True, False, False, False])
        self.assertEqual(base.craft_missing.call_count, 1)

    def test_craft_missing_returns_short_when_stock_stays_low(self):
        base = _make_base()
        base.pending_need = 6
        base.read_number = MagicMock(side_effect=[0, 2])
        # Multi-frame stock reads return the same explicit 0 every frame.
        base.read_short_number = MagicMock(return_value=0)
        base.craft_item = MagicMock(return_value=True)
        base.craft_back = MagicMock(return_value=True)

        self.assertEqual(base.craft_missing(), 'short')

        # craft_back failure must escalate to 'abort'.
        base.read_number = MagicMock(side_effect=[0])
        base.read_short_number = MagicMock(return_value=0)
        base.craft_back = MagicMock(return_value=False)
        self.assertEqual(base.craft_missing(), 'abort')

    def test_order_scan_delivers_ready_card_before_lacked_card(self):
        base = _make_base()
        base.order_confirm = MagicMock(return_value=True)
        base.read_number = MagicMock(return_value=6)

        img = load_image('./assets/crosscore/crosscore/ORDER_BUILD.png')
        tpl = template_of(ORDER_BUILD)
        th, tw, _ = tpl.shape
        # Put a golden 稀有 构建订单 at top-left (412, 140) and mark it 资源暂缺.
        x_rare, y_rare = 412, 140
        img[y_rare:y_rare + th, x_rare:x_rare + tw] = _paint_rare_card_border(tpl)
        lack_tpl = template_of(ORDER_LACK)
        lh, lw, _ = lack_tpl.shape
        lx1, ly1, _, _ = base.card_area(CARD_LACK, x_rare, y_rare)
        img[ly1 + 10:ly1 + 10 + lh, lx1 + 10:lx1 + 10 + lw] = lack_tpl

        # Put a second, deliverable grey 构建订单 at (752, 444) by copying (1092, 444)
        # or simply leaving (1092, 444) from ORDER_BUILD.png as the ready card.
        base.device.image = img

        # On scan with can_craft=True, ready card at (1092, 444) is delivered
        # first; once delivered, the second iteration hits lacked card (412, 140).
        self.assertEqual(base.order_scan(can_craft=True), 'lacked')
        base.device.click.assert_called_once()
        clicked_btn = base.device.click.call_args[0][0]
        self.assertEqual(clicked_btn.area, base.card_area(CARD_DELIVER, 1092, 444))
        self.assertEqual(base.pending_need, 6)

        # With can_craft=False, the ready card is delivered and lacked is skipped.
        base.device.click.reset_mock()
        self.assertEqual(base.order_scan(can_craft=False), 'empty')
        base.device.click.assert_called_once()


class TestCrosscoreCraftStock(unittest.TestCase):
    """craft_item() must be driven by the real stock, never by the dialog OCR.

    Live 2026-11-28 10:06-10:07: the stock read back 99 -> 1984 after two 99
    batches of 熔融石英 (target 720), the loop believed the 1984 and stopped,
    then asked 18 黑匣 and only got 4 while the dialog kept reporting 1.
    """

    def test_ocr_jump_to_1984_does_not_end_crafting(self):
        base = _make_base()
        stock = {'value': 0}
        reads = {'count': 0}
        batches = []

        def read_short(area, name):
            reads['count'] += 1
            if reads['count'] == 3:
                # The live jump: the third read (after 99 and 198) came back 1984.
                return 1984
            return stock['value']

        def craft_once(entry, count):
            batches.append(count)
            stock['value'] += count
            return count

        base.read_short_number = MagicMock(side_effect=read_short)
        base._craft_item_once = MagicMock(side_effect=craft_once)

        ok = base.craft_item(CRAFT_FUSED, 720,
                             stock=(OCR_FUSED_HELD, 'FUSED', 720, 0))

        self.assertTrue(ok, 'crafting must reach the 720 target on the real stock')
        self.assertTrue(all(c <= CRAFT_MAX_PER_BATCH for c in batches),
                        f'every batch must stay <= 99, got {batches}')
        self.assertGreater(len(batches), 2,
                           'the bogus 1984 readback must not end the batches')
        # 假达标 must not skip the remaining gap; 防过量 must not overshoot it.
        self.assertEqual(sum(batches), 720, f'batches {batches} must add up to the gap')

    def test_clean_stock_gap_is_split_into_99_batches(self):
        base = _make_base()
        stock = {'value': 0}
        batches = []

        def craft_once(entry, count):
            batches.append(count)
            stock['value'] += count
            return count

        base.read_short_number = MagicMock(side_effect=lambda area, name: stock['value'])
        base._craft_item_once = MagicMock(side_effect=craft_once)

        # 10 黑匣 x 40 压电 = 400, i.e. 99/99/99/99/4.
        ok = base.craft_item(CRAFT_FUSED, 400,
                             stock=(OCR_FUSED_HELD, 'FUSED', 400, 0))

        self.assertTrue(ok)
        self.assertTrue(all(c <= CRAFT_MAX_PER_BATCH for c in batches), batches)
        self.assertEqual(sum(batches), 400, batches)

    def test_zero_readback_does_not_inflate_the_gap(self):
        base = _make_base()
        batches = []
        base.read_short_number = MagicMock(return_value=0)
        base._craft_item_once = MagicMock(
            side_effect=lambda entry, count: batches.append(count) or count)

        # Baseline stock was 99, a 0 read is an OCR failure, not a 720 gap.
        ok = base.craft_item(CRAFT_FUSED, 720,
                             stock=(OCR_FUSED_HELD, 'FUSED', 720, 99))

        self.assertFalse(ok, 'a 0 readback must not be reported as progress')
        self.assertEqual(batches, [], 'a 0 readback must not trigger more batches')

    def test_single_frame_zero_on_material_page_uses_stable_gap(self):
        base = _make_base()
        base.pending_need = 1
        # Black box counts: 0 before crafting, 1 after (the order is filled).
        blackbox = {'reads': 0}

        def read_blackbox(*args, **kwargs):
            blackbox['reads'] += 1
            return 0 if blackbox['reads'] == 1 else 1

        base.read_number = MagicMock(side_effect=read_blackbox)

        # The 制作素材 page is still fading in: the very first read is a single
        # 0 frame, then two real frames show 30 held of the 40 needed.
        fused = {'reads': 0}

        def read_short(area, name, *args, **kwargs):
            if name == 'PIEZO':
                return 40
            fused['reads'] += 1
            return 0 if fused['reads'] == 1 else 30

        base.read_short_number = MagicMock(side_effect=read_short)
        calls = []
        base.craft_item = MagicMock(
            side_effect=lambda entry, count, stock=None, **kwargs:
            calls.append((entry, count, stock)) or True)
        base.craft_back = MagicMock(return_value=True)

        self.assertEqual(base.craft_missing(), 'ok')

        fused_calls = [call for call in calls if call[0] is CRAFT_FUSED]
        self.assertEqual(len(fused_calls), 1, calls)
        _, count, stock = fused_calls[0]
        # 30 really held of 40: the initial gap is 10, never the 40 a lone
        # 0 frame would imply.
        self.assertEqual(count, 10, f'{count} would overshoot the stable gap')
        self.assertEqual(stock, (OCR_FUSED_HELD, 'FUSED', 40, 30))

    def test_partial_batch_is_not_counted_as_full_success(self):
        base = _make_base()
        stock = {'value': 0}
        batches = []

        def craft_once(entry, count):
            batches.append(count)
            # Only 4 pieces of material were really available for the 18 asked.
            made = min(count, max(0, 4 - stock['value']))
            stock['value'] += made
            return made

        base._craft_item_once = MagicMock(side_effect=craft_once)

        # No stock tuple: the batch readback is the only progress signal.
        ok = base.craft_item(CRAFT_BLACKBOX, 18)

        self.assertFalse(ok, f'4/18 made must not be reported as success, batches {batches}')
        self.assertEqual(batches[0], 18)
        self.assertTrue(batches[1:] == [] or batches[1] == 14,
                        f'the remaining gap should be 14, batches {batches}')
        self.assertTrue(all(c <= CRAFT_MAX_PER_BATCH for c in batches), batches)


class TestCrosscoreCraftConfirm(unittest.TestCase):
    """A dark 确定 or a batch without 结算 must never be counted as production."""

    def test_dark_confirm_is_not_pressed_nor_counted(self):
        base = _make_dialog_base({CRAFT_FUSED, CRAFT_MIN})
        # 合成份数 reads 1, 确定 stays greyed out (materials short).
        base.read_number = MagicMock(return_value=1)

        ok = base.craft_item(CRAFT_FUSED, 1)

        self.assertFalse(ok, 'a dim confirm must not be counted as production')
        self.assertFalse(_pressed_in(base, CRAFT_CONFIRM),
                         'the disabled 确定 button must not be pressed')

    def test_no_settlement_is_not_counted(self):
        base = _make_dialog_base(
            {CRAFT_FUSED, CRAFT_MIN, CRAFT_PLUS, CRAFT_CONFIRM, CRAFT_BACK})
        x1, y1, x2, y2 = CRAFT_CONFIRM.area
        base.device.image[y1:y2, x1:x2] = CRAFT_CONFIRM.color
        # A finite 1 -> 2 amount: the MIN reset first reads the legitimate 1,
        # then the + press settles on 2. A constant 2 never exercises the
        # reset, so a no-settlement batch could silently count as production.
        amounts = iter((1, 2, 2))
        base.read_number = MagicMock(
            side_effect=lambda *args, **kwargs: next(amounts, 2))

        ok = base.craft_item(CRAFT_FUSED, 2)

        self.assertFalse(ok, 'a confirmed batch without 结算 must not be counted')
        self.assertTrue(_pressed_in(base, CRAFT_CONFIRM),
                        'the lit 确定 button must be pressed')
        self.assertTrue(_pressed_in(base, CRAFT_BACK),
                        'the dialog must be backed out when nothing settled')


class TestCrosscoreRealInsufficientShot(unittest.TestCase):
    """Original 2026-11-28 screenshot: 熔融石英 38/40 red, 份数 1, 确定 dark."""

    def test_insufficient_fused_shot_withdraws_without_confirm(self):
        if not os.path.exists(REAL_INSUFFICIENT_SHOT):
            self.skipTest(f'{REAL_INSUFFICIENT_SHOT} not archived')

        base = _make_base()
        base.device.image = load_image(REAL_INSUFFICIENT_SHOT)
        image = base.device.image
        base.read_number = MagicMock(return_value=1)  # 合成份数 on this frame

        def real_appear(button, offset=(0, 0), interval=0, similarity=0.85, **kwargs):
            # The recipe list sits behind the opened dialog; the assertions below
            # are about the dialog itself, so the entry is treated as visible.
            if button is CRAFT_FUSED:
                return True
            return bool(button.match(image, offset=offset, similarity=similarity))

        base.appear = real_appear

        ok = base.craft_item(CRAFT_FUSED, 1)

        self.assertFalse(ok, '38/40 熔融石英 cannot make one piece, no production')
        self.assertFalse(_pressed_in(base, CRAFT_CONFIRM),
                         'the greyed 确定 button must not be pressed')
        self.assertTrue(_pressed_in(base, CRAFT_BACK),
                        'the short dialog must be left safely')


if __name__ == '__main__':
    unittest.main()
