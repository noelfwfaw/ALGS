"""Clarity (体力/澄明度) recovery helper using consumable items (never spending 桦石)."""

import math

import numpy as np

from module.base.button import Button
from module.base.timer import Timer
from module.exception import GameStuckError
from module.logger import logger
from module.ocr.ocr import Ocr
from module.resonance import assets
from module.resonance.fatigue import FATIGUE_CONFIRM_QTY_OCR
from module.resonance.trade import parse_fraction_text


OFFSET = (5, 5)
CLARITY_ITEM_TIERS = {
    'none': (),
    'lollipop': ('lollipop',),
    'lollipop_gum': ('lollipop', 'gum'),
    'all': ('lollipop', 'gum', 'cactus'),
}
# Only safe consumables are listed; 桦石 is never auto-spent.
CLARITY_ITEMS = (
    ('lollipop', 40, (55, 540, 335, 654)),
    ('gum', 60, (355, 540, 635, 654)),
    ('cactus', 180, (655, 540, 935, 654)),
)
def _box_button(box, name):
    return Button(area=box, color=(), button=box, name=name)


CLARITY_ITEM_BTN = {
    key: _box_button((x1 + 25, 548, x2 - 15, 646), f'CLARITY_ITEM_{key.upper()}')
    for key, _, (x1, _, x2, _) in CLARITY_ITEMS
}
CLARITY_FRACTION_OCR = Ocr((170, 408, 335, 462), lang='cnocr', threshold=128, alphabet='0123456789/', name='Clarity recovery')
CLARITY_CNT_OCR = Ocr([], lang='azur_lane', threshold=128, alphabet='0123456789', name='Clarity item count')


def normalize_clarity_item_mode(value):
    """Normalize config option (bool or tier key) into one of `CLARITY_ITEM_TIERS` keys."""
    if isinstance(value, bool):
        return 'all' if value else 'none'
    text = str(value or 'none').strip().lower()
    if text in ('true', 'yes', '1'):
        return 'all'
    return text if text in CLARITY_ITEM_TIERS else 'none'


def read_clarity_fraction(image):
    """Parse `(current, max)` clarity from the `澄明度 · 请选择恢复方式` header, or None."""
    return parse_fraction_text(CLARITY_FRACTION_OCR.ocr(image))


def parse_clarity_items(image):
    """Parse owned stock of safe clarity items (`lollipop`, `gum`, `cactus`) from recovery screen."""
    results = []
    for key, recover, (x1, _, _, _) in CLARITY_ITEMS:
        badge = image[620:654, x1:x1 + 55]
        ymask = (badge[:, :, 0] > 190) & (badge[:, :, 1] > 150) & (badge[:, :, 2] < 80)
        pill = image[560:602, x1 + 70:x1 + 215]
        obtain_w = int((pill.min(axis=2) > 210).sum())
        if int(ymask.sum()) < 150 or obtain_w >= 450:
            results.append({'key': key, 'recover': recover, 'owned': 0})
            continue
        ys, xs = np.where(ymask)
        patch = badge[int(ys.min()):int(ys.max()) + 1, int(xs.min()):int(xs.max()) + 1]
        inv = 255 - patch.mean(axis=2).astype(np.uint8)
        up = np.repeat(np.repeat(inv, 2, axis=0), 2, axis=1)
        raw = CLARITY_CNT_OCR.ocr([np.stack((up, up, up), axis=2)], direct_ocr=True)
        text = raw[0] if isinstance(raw, list) and raw else ''
        digits = ''.join(ch for ch in str(text) if ch.isdigit())
        results.append({'key': key, 'recover': recover, 'owned': int(digits) if digits else 1})
    return results


def choose_clarity_item_plan(needed_clarity, items, allowed_keys=None):
    """Pick first allowed item with stock > 0 and quantity needed; return `(key, count)` or None."""
    if needed_clarity <= 0:
        return None
    allowed = None if allowed_keys is None else set(allowed_keys)
    for item in items:
        if allowed is not None and item.get('key') not in allowed:
            continue
        owned = item.get('owned', 0)
        if owned <= 0:
            continue
        want = max(1, int(math.ceil(needed_clarity / float(item['recover']))))
        return item['key'], min(owned, want)
    return None


def _dismiss_clarity_prompt(ui):
    """Cancel `是否补充澄明度?` confirmation dialog if shown."""
    for _ in ui.loop(timeout=10):
        if ui.appear(assets.CLARITY_PROMPT, offset=OFFSET):
            ui.appear_then_click(assets.CLARITY_PROMPT_CANCEL, offset=OFFSET, interval=1.5)
            continue
        return


def _exit_clarity_recovery(ui):
    """Back out of `CLARITY_RECOVERY_CHECK` / `CLARITY_CONFIRM_MODAL` to the previous screen."""
    for _ in ui.loop(timeout=10):
        if ui.handle_reward_popup():
            continue
        if ui.appear(assets.CLARITY_CONFIRM_MODAL, offset=OFFSET):
            ui.appear_then_click(assets.FATIGUE_CONFIRM_CANCEL, offset=OFFSET, interval=1.5)
            continue
        if ui.appear(assets.CLARITY_RECOVERY_CHECK, offset=OFFSET):
            ui.appear_then_click(assets.OP_BACK, offset=OFFSET, interval=1.5)
            continue
        return


def _adjust_and_confirm_clarity_item(ui, count):
    """Adjust item count in `CLARITY_CONFIRM_MODAL`, click `补充`, and return confirmed count."""
    ui.interval_clear((
        assets.FATIGUE_CONFIRM_MAX, assets.FATIGUE_CONFIRM_PLUS,
        assets.FATIGUE_CONFIRM_MINUS, assets.FATIGUE_CONFIRM_OK, assets.FATIGUE_CONFIRM_CANCEL,
    ))
    confirmed = 0
    for _ in ui.loop(timeout=15):
        if ui.handle_reward_popup():
            continue
        if ui.appear(assets.CLARITY_CONFIRM_MODAL, offset=OFFSET):
            if confirmed:
                continue
            frac = parse_fraction_text(FATIGUE_CONFIRM_QTY_OCR.ocr(ui.device.image))
            if frac is None:
                continue
            cur, max_qty = frac
            cap = min(count, max_qty)
            if cap <= 0:
                ui.appear_then_click(assets.FATIGUE_CONFIRM_CANCEL, offset=OFFSET, interval=1.5)
                continue
            if cur == cap:
                if ui.appear_then_click(assets.FATIGUE_CONFIRM_OK, offset=OFFSET, interval=1.5):
                    confirmed = cap
                continue
            if cur < cap and cap == max_qty:
                ui.appear_then_click(assets.FATIGUE_CONFIRM_MAX, offset=OFFSET, interval=1.5)
            elif cur < cap:
                ui.appear_then_click(assets.FATIGUE_CONFIRM_PLUS, offset=OFFSET, interval=0.8)
            else:
                ui.appear_then_click(assets.FATIGUE_CONFIRM_MINUS, offset=OFFSET, interval=0.8)
            continue
        if confirmed or ui.appear(assets.CLARITY_RECOVERY_CHECK, offset=OFFSET):
            return confirmed
    raise GameStuckError('Resonance clarity item confirmation timed out')


def _use_clarity_item(ui, item_btn, count):
    """Tap `item_btn` on `CLARITY_RECOVERY_CHECK` and confirm usage."""
    retry = Timer(1.5)
    for _ in ui.loop(timeout=12):
        if ui.appear(assets.CLARITY_CONFIRM_MODAL, offset=OFFSET):
            return _adjust_and_confirm_clarity_item(ui, count)
        if ui.appear(assets.CLARITY_RECOVERY_CHECK, offset=OFFSET) and retry.reached():
            ui.device.click(item_btn)
            retry.reset()
            continue
    raise GameStuckError('Resonance clarity item confirm modal did not open')


def _open_clarity_recovery_page(ui):
    """Click `确认` on `CLARITY_PROMPT` until `CLARITY_RECOVERY_CHECK` opens."""
    for _ in ui.loop(timeout=12):
        if ui.appear(assets.CLARITY_RECOVERY_CHECK, offset=OFFSET):
            return True
        if ui.appear(assets.CLARITY_PROMPT, offset=OFFSET):
            ui.appear_then_click(assets.CLARITY_PROMPT_CONFIRM, offset=OFFSET, interval=1.5)
            continue
    return False


def handle_clarity_recovery(ui, item_mode, needed=40):
    """Handle clarity prompt or recovery page according to `item_mode`; return True if recovered."""
    mode = normalize_clarity_item_mode(item_mode)
    allowed = CLARITY_ITEM_TIERS[mode]
    if not allowed:
        logger.info('雷索纳斯澄明度不足，未启用道具恢复，取消补充')
        _dismiss_clarity_prompt(ui)
        _exit_clarity_recovery(ui)
        return False

    if not _open_clarity_recovery_page(ui):
        return False

    frac = read_clarity_fraction(ui.device.image)
    items = parse_clarity_items(ui.device.image)
    shortfall = max(1, needed - frac[0]) if frac is not None else needed
    plan = choose_clarity_item_plan(shortfall, items, allowed_keys=allowed)
    if plan is None:
        logger.warning('雷索纳斯澄明度不足且没有可用的允许恢复道具 (%s)', mode)
        _exit_clarity_recovery(ui)
        return False

    key, count = plan
    used = _use_clarity_item(ui, CLARITY_ITEM_BTN[key], count)
    if used > 0:
        logger.info('雷索纳斯已使用澄明度恢复道具: %s x%d', key, used)
    _exit_clarity_recovery(ui)
    return used > 0
