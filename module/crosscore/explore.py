"""每日探索 of 交错战线 (Cross Core).

    大厅出击 → 每日探索 → 类别卡 → 子项（匹配前两字 + 亮度判「明日开放」）
    → 层（从高到低找已解锁有字行；点进详情若「扫荡」带锁则顺延下一层）
    → 扫荡 → 开始战斗 → 掉落加成提示（使用）→ 扫荡结算（点 奖励 关掉）→ 大厅

Measured notes:
1. Selected category is read from `CATEGORY` gold strip via `gold_pixels()`.
2. Open sub-items sort above closed ones (`明日开放`, dimmed to luma ~75 vs
   197~255), so sub-items are located by 2-char title template instead of row.
3. Empty rows and locked rows carry 0 bright text pixels; an unlocked higher
   layer whose own stage was never cleared opens with locked `扫荡` and must
   step down to the highest cleared layer.
4. Sweep result closes via golden 「奖励」 title (bottom-right); tapping icons
   opens item details and dark area does nothing.
"""

import cv2
import numpy as np

from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import crop
from module.crosscore.assets import (
    EXPLORE_CAT_ASCEND, EXPLORE_CAT_CHIP, EXPLORE_CAT_RESOURCE, EXPLORE_CONFIRM,
    EXPLORE_DAILY, EXPLORE_DIALOG_OUTSIDE, EXPLORE_DROP, EXPLORE_LAYER_ROW_1,
    EXPLORE_LAYER_ROW_2, EXPLORE_LAYER_ROW_3, EXPLORE_LAYER_ROW_4, EXPLORE_LAYER_ROW_5,
    EXPLORE_LAYER_ROW_6, EXPLORE_LOCK, EXPLORE_MID_LAYER_ROW_1, EXPLORE_MID_LAYER_ROW_2,
    EXPLORE_MID_LAYER_ROW_3, EXPLORE_MID_LAYER_ROW_4, EXPLORE_MID_LAYER_ROW_5,
    EXPLORE_MID_LAYER_ROW_6, EXPLORE_NO_FUEL, EXPLORE_RESULT, EXPLORE_SORTIE,
    EXPLORE_START, EXPLORE_SUB_BLADE, EXPLORE_SUB_COIN, EXPLORE_SUB_EROSION,
    EXPLORE_SUB_INJECT, EXPLORE_SUB_INSPIRE, EXPLORE_SUB_LIFE, EXPLORE_SUB_LINK,
    EXPLORE_SUB_NATURE, EXPLORE_SUB_OPTIC, EXPLORE_SUB_PARADOX, EXPLORE_SUB_PHYSIQUE,
    EXPLORE_SUB_RELIC, EXPLORE_SUB_SKILL, EXPLORE_SUB_SYNTH, EXPLORE_SUB_TECH,
    EXPLORE_SWEEP, EXPLORE_SWEEP_LOCKED,
)
from module.crosscore.crosscore_ui import CrosscoreUI
from module.crosscore.page import page_main
from module.crosscore.utils import (find_all, gold_pixels, image_diff,
                                    template_of)
from module.logger import logger

SUB_BAND = (840, 120, 1110, 630)
SUB_SEARCH_REGION = (830, 125, 1080, 560)
# 95th percentile title luma: open stages measure 197~255, 「明日开放」 measures 74~76.
SUB_OPEN_LUMA = 135
LAYER_PITCH = 63
LAYER_LOCK_REGION = (1040, 250, 1095, 600)
# Unlocked existing layer rows measure 471~1025 bright pixels; locked/empty rows 0.
LAYER_ROW_TEXT_LUMA = 140
LAYER_ROW_BRIGHT_PIXELS = 100
# Middle-column selection highlight bars (`316~701` gold pixels vs `0` idle).
MID_BAR_GOLD_PIXELS = 100

LAYER_ROWS = (
    EXPLORE_LAYER_ROW_1, EXPLORE_LAYER_ROW_2, EXPLORE_LAYER_ROW_3,
    EXPLORE_LAYER_ROW_4, EXPLORE_LAYER_ROW_5, EXPLORE_LAYER_ROW_6,
)
MID_LAYER_ROWS = (
    EXPLORE_MID_LAYER_ROW_1, EXPLORE_MID_LAYER_ROW_2, EXPLORE_MID_LAYER_ROW_3,
    EXPLORE_MID_LAYER_ROW_4, EXPLORE_MID_LAYER_ROW_5, EXPLORE_MID_LAYER_ROW_6,
)

# Left-edge gold strip bands per category (`ascend` sits lower, at y 390~620).
CATEGORY = {
    'resource': (EXPLORE_CAT_RESOURCE, (266, 150, 312, 245)),
    'chip': (EXPLORE_CAT_CHIP, (266, 260, 312, 355)),
    'ascend': (EXPLORE_CAT_ASCEND, (266, 390, 330, 620)),
}
CATEGORY_GOLD_PIXELS = 120

OPTIONS = {
    '技能磨砺': ('resource', EXPLORE_SUB_SKILL), '星币开采': ('resource', EXPLORE_SUB_COIN),
    '技术分析': ('resource', EXPLORE_SUB_TECH), '荒墟拾遗': ('resource', EXPLORE_SUB_RELIC),
    '鼓舞嵌合': ('chip', EXPLORE_SUB_INSPIRE), '光枢嵌合': ('chip', EXPLORE_SUB_OPTIC),
    '注刘嵌合': ('chip', EXPLORE_SUB_INJECT), '链接嵌合': ('chip', EXPLORE_SUB_LINK),
    '体魄嵌合': ('chip', EXPLORE_SUB_PHYSIQUE), '侵蚀嵌合': ('chip', EXPLORE_SUB_EROSION),
    '迅刃嵌合': ('chip', EXPLORE_SUB_BLADE), '矛盾嵌合': ('chip', EXPLORE_SUB_PARADOX),
    '自然跃升': ('ascend', EXPLORE_SUB_NATURE), '人造跃升': ('ascend', EXPLORE_SUB_SYNTH),
    '生命跃升': ('ascend', EXPLORE_SUB_LIFE),
}


class CrosscoreExplore(CrosscoreUI):
    """
    Sweep the highest unlocked layer of one daily explore option.

    Pages:
        in: page_main
        out: page_main
    """

    def run(self):
        """
        Pages:
            in: page_main
            out: page_main
        """
        logger.hr('交错每日探索', level=1)
        self.ui_ensure(page_main)

        name = self.config.CrosscoreExplore_Explore
        if name not in OPTIONS:
            logger.warning(f'Unknown explore option <{name}>, fall back to 技能磨砺')
            name = '技能磨砺'
        category, _ = OPTIONS[name]
        logger.info(f'Explore <{name}>, category {category}')

        if not self.explore_enter() \
                or not self.explore_open_category(category):
            self._handle_explore_fail()
            return

        sub_state = self.explore_pick_sub(name, category)
        if sub_state == 'skip':
            self.back_to_main()
            self.config.task_delay(server_update=True)
            return
        if sub_state != 'ok':
            self._handle_explore_fail()
            return

        layer_state = self.explore_pick_layer()
        if layer_state == 'skip':
            self.back_to_main()
            self.config.task_delay(server_update=True)
            return
        if layer_state != 'ok' or not self.explore_sweep():
            self._handle_explore_fail()
            return

        self.back_to_main()
        # Explore entries reset with the daily server update.
        self.config.task_delay(server_update=True)

    def _handle_explore_fail(self):
        logger.warning('Explore failed, retry in 15 minutes')
        # The failure leaves the game on the explore page, which is not a
        # registered Page: the next task's `ui_get_current_page()` would
        # time out and die with GamePageUnknownError (2026-11-09 real run).
        self.back_to_main()
        self.config.task_delay(minute=15)

    def explore_enter(self):
        """
        Walk from the lobby to the explore page.

        The lobby raises 「出击」, which opens the sortie page, where 「每日探索」
        sits in the middle. Both pages are waited out with an interval so that a
        swallowed click is not repeated on every frame.

        Returns:
            bool: If the explore page (its category cards) is on screen.
        """
        for _ in self.loop(timeout=60):
            if self.handle_item_popup():
                continue
            if self.handle_lobby_popup():
                continue
            if self.explore_page_appear():
                # The category cards fade in, and a click on a half drawn card
                # is lost; the first answer has to come from a still frame.
                self.wait_until_still(EXPLORE_CAT_RESOURCE.area, timeout=3)
                return True
            if self.appear(EXPLORE_DAILY, offset=(20, 20), interval=3):
                logger.info('Sortie page, press 每日探索')
                self.device.click(EXPLORE_DAILY)
            elif self.appear(EXPLORE_SORTIE, offset=(20, 20), interval=3):
                logger.info('Lobby, press 出击')
                self.device.click(EXPLORE_SORTIE)

        logger.warning('Cannot open the explore page')
        return False

    def explore_page_appear(self):
        """
        Whether the explore page is drawn, on any of its three category cards.

        Only one card is lit at a time but all three are always on screen, and
        none of them matches the sortie page or the lobby at this position.
        """
        return self.appear(EXPLORE_CAT_RESOURCE, offset=(20, 20)) \
            or self.appear(EXPLORE_CAT_CHIP, offset=(20, 20)) \
            or self.appear(EXPLORE_CAT_ASCEND, offset=(20, 20))

    def explore_open_category(self, category):
        """
        Press a category card until its left edge turns gold.

        The card is pressed by template; whether the press landed is read from
        the golden strip instead of the template, because the selected and the
        idle card are structurally the same image.

        Args:
            category (str): One of the keys of `CATEGORY`.

        Returns:
            bool: If the category is selected.
        """
        card, band = CATEGORY[category]

        for _ in self.loop(timeout=20):
            if self.handle_item_popup():
                continue
            if gold_pixels(self.device.image, band) > CATEGORY_GOLD_PIXELS:
                logger.info(f'Category <{category}> is selected')
                self.wait_until_still(band, timeout=3)
                return True
            if self.appear(card, offset=(20, 20), interval=2):
                logger.info(f'Press category <{category}>')
                self.device.click(card)

        logger.warning(f'Category <{category}> did not highlight')
        return False

    def explore_pick_sub(self, name, category):
        """
        Locate one sub item by template inside `SUB_SEARCH_REGION`, skip if
        dimmed (`明日开放`), otherwise click it and wait for the layer list.

        Open stages sort above closed (`明日开放`) stages and can shift row
        positions on any day, so matching by title template avoids fixed-row
        drift.

        Args:
            name (str): Option name.
            category (str): One of the keys of `CATEGORY`.

        Returns:
            str: `'ok'`, `'skip'` (not open today), or `'fail'`.
        """
        logger.hr(name, level=2)
        _, target_btn = OPTIONS[name]
        tmpl = template_of(target_btn)
        found = self._locate_sub_item(tmpl, category)
        if found is None:
            logger.warning(f'Sub item <{name}> not found in list')
            return 'fail'

        mx, my, p95 = found
        if p95 < SUB_OPEN_LUMA:
            logger.info(f'Sub item <{name}> is not open today (明日开放), skip')
            return 'skip'

        button = Button(area=(mx + 20, my, mx + 120, my + 30),
                        color=(0, 0, 0),
                        button=(mx + 20, my, mx + 120, my + 30),
                        name=target_btn.name)
        retry = Timer(3)
        for _ in self.loop(timeout=30):
            if self.appear(EXPLORE_DROP, offset=(20, 20), similarity=0.80):
                return 'ok'
            if self.explore_page_appear() and retry.reached():
                retry.reset()
                logger.info(f'Press sub item <{name}> at ({mx}, {my})')
                self.device.click(button)  # alas-lint: allow - 动态定位子项卡，左栏类别卡 appear() 是守卫

        logger.warning(f'Sub item <{name}> did not open the layer list')
        return 'fail'

    def _locate_sub_item(self, tmpl, category):
        """Find `(x, y, p95_luma)` in `SUB_SEARCH_REGION`, scrolling `chip` top then bottom."""
        found = self._match_sub_in_view(tmpl)
        if found is not None or category != 'chip':
            return found

        self.explore_scroll(top=True)
        found = self._match_sub_in_view(tmpl)
        if found is not None:
            return found

        self.explore_scroll(top=False)
        return self._match_sub_in_view(tmpl)

    def _match_sub_in_view(self, tmpl):
        """Match `tmpl` in `SUB_SEARCH_REGION` and return `(x, y, p95_luma)` or None."""
        x1, y1, _, _ = SUB_SEARCH_REGION
        roi = crop(self.device.image, SUB_SEARCH_REGION, copy=False)
        if roi.shape[0] < tmpl.shape[0] or roi.shape[1] < tmpl.shape[1]:
            return None
        res = cv2.matchTemplate(roi, tmpl, cv2.TM_CCOEFF_NORMED)
        if float(res.max()) < 0.85:
            return None
        dy, dx = np.unravel_index(res.argmax(), res.shape)
        mx, my = x1 + int(dx), y1 + int(dy)
        patch = self.device.image[my:my + tmpl.shape[0], mx:mx + tmpl.shape[1]]
        p95 = float(np.percentile(patch.mean(axis=2), 95))
        return mx, my, p95

    def explore_scroll(self, top, swipes=3):
        """
        Scroll the sub item list until it clamps at one of its ends.

        Same behaviour check as the lost sword card list: drag once, wait until
        the list stops moving, and call it the end when the band did not change.
        A fast swipe is swallowed by this list (400 ms measured no movement), so
        the drag is deliberately slow.

        Pages:
            in: explore page, sub item list
            out: same

        Args:
            top (bool): True to drag the list back to its top, False to its
                bottom.
            swipes (int): How many drags to make at most.
        """
        if top:
            p1, p2 = (1000, 320), (1000, 540)
        else:
            p1, p2 = (1000, 540), (1000, 320)

        clamped = False
        self.device.screenshot()
        for _ in range(swipes):
            before = self.image_crop(SUB_BAND, copy=True)
            self.device.swipe(p1, p2, duration=0.9)
            # The list snaps after the drag; comparing a mid-snap frame would
            # always show a difference and every drag would look like movement.
            self.wait_until_still(SUB_BAND, timeout=3)
            self.device.screenshot()
            after = self.image_crop(SUB_BAND, copy=True)
            if image_diff(before, after) < 1:
                clamped = True
                break

        if not clamped:
            logger.warning(f'The sub item list did not reach its end in {swipes} swipe(s)')
        # Swipes are counted as clicks; a task that scrolls twice would trip the
        # "too many click" guard halfway.
        self.device.click_record_clear()

    def explore_pick_layer(self):
        """
        Open the highest sweepable layer of the chosen sub item.

        An unlocked layer whose previous tier was cleared can still have locked
        「扫荡」 (`EXPLORE_SWEEP_LOCKED`) because the current tier itself was
        never cleared. Step down through lower unlocked candidates in the middle
        column until a sweepable layer is found, or return `'skip'` if none.

        Pages:
            in: explore page, layer list
            out: layer detail page (sweepable) or same

        Returns:
            str: `'ok'`, `'skip'` (no cleared/sweepable layer), or `'fail'`.
        """
        # The layer list fades in after the sub item press; a half drawn frame
        # carries no lock yet and every row would read as unlocked.
        self.wait_until_still(LAYER_LOCK_REGION, timeout=3)
        locks = find_all(self.device.image, template_of(EXPLORE_LOCK), LAYER_LOCK_REGION)
        lock_y = [y for _, y in locks]
        locked = set()
        for row in range(1, len(LAYER_ROWS) + 1):
            top = 259 + LAYER_PITCH * (row - 1)
            if any(abs(y - top) <= 8 for y in lock_y):
                locked.add(row)

        candidates = [row for row in range(len(LAYER_ROWS), 0, -1)
                      if row not in locked and self._layer_row_has_text(row)]
        if not candidates:
            logger.warning('No unlocked layer to sweep')
            return 'fail'

        saw_locked_sweep = False
        for row in candidates:
            state = self._open_layer_candidate(row)
            if state == 'ok':
                return 'ok'
            if state == 'locked':
                saw_locked_sweep = True

        if saw_locked_sweep:
            logger.info('No layer has cleared sweep unlocked, skip daily explore')
            return 'skip'
        logger.warning('Failed to open any unlocked layer')
        return 'fail'

    def _open_layer_candidate(self, row):
        """Click candidate `row` and return `'ok'`, `'locked'`, or `'timeout'`."""
        self.interval_timer.pop(EXPLORE_DROP.name, None)
        self.interval_timer.pop(EXPLORE_SWEEP_LOCKED.name, None)
        from_drop = self.appear(EXPLORE_DROP, offset=(20, 20), similarity=0.80)
        for _ in self.loop(timeout=6):
            if self.appear(EXPLORE_SWEEP, offset=(20, 20)):
                logger.info(f'Layer {row} is open')
                return 'ok'
            if from_drop or self._mid_layer_selected(row):
                if self.appear(EXPLORE_SWEEP_LOCKED, offset=(20, 20), similarity=0.80):
                    self.wait_until_still(EXPLORE_SWEEP_LOCKED.area, timeout=2)
                    if self.appear(EXPLORE_SWEEP, offset=(20, 20)):
                        logger.info(f'Layer {row} is open')
                        return 'ok'
                    if self.appear(EXPLORE_SWEEP_LOCKED, offset=(20, 20), similarity=0.80):
                        logger.info(f'Layer {row} sweep is locked, try lower layer')
                        return 'locked'
            if self.appear(EXPLORE_DROP, offset=(20, 20), similarity=0.80, interval=2):
                logger.info(f'Press layer {row}')
                self.device.click(LAYER_ROWS[row - 1])
            elif self.appear(EXPLORE_SWEEP_LOCKED, offset=(20, 20), similarity=0.80, interval=2):
                logger.info(f'Press middle layer {row}')
                self.device.click(MID_LAYER_ROWS[row - 1])

        return 'timeout'

    def _mid_layer_selected(self, row):
        """Whether `row` (1-based) in the middle list shows golden selection bars."""
        y1 = 248 + LAYER_PITCH * (row - 1)
        y2 = y1 + 54
        golds = gold_pixels(self.device.image, (366, y1, 382, y2)) \
            + gold_pixels(self.device.image, (670, y1, 686, y2))
        return golds >= MID_BAR_GOLD_PIXELS

    def _layer_row_has_text(self, row):
        """Whether layer `row` (1-based) renders bright unlocked layer text (`第N层`)."""
        roi = crop(self.device.image, LAYER_ROWS[row - 1].area, copy=False)
        bright = int(np.count_nonzero(roi.mean(axis=2) > LAYER_ROW_TEXT_LUMA))
        return bright >= LAYER_ROW_BRIGHT_PIXELS

    def explore_sweep(self):
        """
        Sweep the open layer and close the result panel.

        The four screens are told apart by their own elements and are checked
        independently instead of in a fixed order: the drop bonus prompt only
        shows up while bonus uses are left, so waiting for it in sequence would
        hang on the days it is skipped.

        `panel_seen` keeps the loop from pressing the 「扫荡」 of the detail page
        once the sweep panel is already open - the detail page is what is drawn
        behind it.

        Pages:
            in: layer detail page
            out: layer detail page (result panel closed)

        Returns:
            bool: If the result panel was closed.
        """
        panel_seen = False
        # A greyed-out 扫荡 (the layer was never cleared) swallows the press
        # without any feedback. Three tries, then give up: retrying every frame
        # would trip the "too many click" guard on the same button.
        sweep_clicks = 0

        for _ in self.loop(timeout=180):
            if self.handle_item_popup():
                continue
            if self.appear(EXPLORE_NO_FUEL, offset=(20, 20)):
                # Pressing 开始战斗 without enough fuel raises the fuel supply
                # dialog instead of starting a sweep. That is the normal end of
                # a day, not a stuck game.
                logger.info('No fuel left, the daily explore is done')
                if self.appear(EXPLORE_NO_FUEL, offset=(20, 20), interval=3):
                    self.device.click(EXPLORE_DIALOG_OUTSIDE)
                return True
            if self.appear(EXPLORE_RESULT, offset=(20, 20)):
                panel_seen = True
                # The golden 奖励 title closes the panel. The item icons open an
                # item detail page and the black area does nothing (用户实测).
                if self.appear(EXPLORE_RESULT, offset=(20, 20), interval=3):
                    logger.info('Sweep done, close the result panel')
                    self.device.click(EXPLORE_RESULT)
                # A frame without 奖励 is not proof that the panel is gone: it
                # redraws while the reward numbers count up, and the negative
                # check returned True while the panel was still on screen
                # (2026-11-08 real run). The detail page's 扫荡 button is the
                # first positive proof of the way back.
                if self.wait_until_appear(EXPLORE_SWEEP, offset=(20, 20), timeout=10):
                    return True
                continue
            if self.appear(EXPLORE_CONFIRM, offset=(20, 20), interval=3):
                panel_seen = True
                logger.info('Drop bonus prompt, press 使用')
                self.device.click(EXPLORE_CONFIRM)
                continue
            if self.appear(EXPLORE_START, offset=(20, 20), interval=3):
                panel_seen = True
                logger.info('Sweep panel, press 开始战斗')
                self.device.click(EXPLORE_START)
                continue
            if panel_seen:
                continue
            if self.appear(EXPLORE_SWEEP, offset=(20, 20), interval=3):
                if sweep_clicks >= 3:
                    logger.warning('The sweep panel does not open, '
                                   'the layer is probably not cleared yet')
                    return False
                sweep_clicks += 1
                logger.info('Detail page, press 扫荡')
                self.device.click(EXPLORE_SWEEP)

        logger.warning('The sweep did not finish')
        return False
