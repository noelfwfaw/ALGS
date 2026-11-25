"""Resource dungeon (副本) sweep automation for Trickcal.

Covers all five star-candy dungeons entered via `page_main -> page_adventure -> page_dungeon`:
- 克隆工厂 (daily 8 entries, 20 star candy/run, fixed 4x3 stage grid)
- 金币大作战 (scrollable 1..20 vault blueprint map, 10 star candy/run)
- 神秘面包房 (魔卡龙区域 / 奶卡龙区域 tabs, scrollable 3-col shelves, 10 star candy/run)
- 糖果自由 (红/蓝/绿三台扭蛋机 chooser -> scrollable 3-col jar grid, 10 star candy/run)
- 到手蜡 (5x2 paged grids with `<` / `>` arrows, 20 star candy/run)
"""

import numpy as np

from module.base.timer import Timer
from module.base.utils import crop
from module.logger import logger
from module.trickcal.assets import (
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
    EVENT_SWEEP_TITLE,
    SHOP_BUY_CANCEL,
)
from module.trickcal.dungeon_stage import (
    BAKERY_TABS,
    CANDY_MACHINE_AREAS,
    CRAYON_NEXT_AREA,
    CRAYON_PREV_AREA,
    bakery_tab_selected,
    clone_slot_area,
    crayon_slot_area,
    crayon_target_page,
    dungeon_sweep_lit,
    find_bakery_stages,
    find_candy_stages,
    find_gold_vaults,
    read_clone_daily_remaining,
    read_crayon_page,
    read_dungeon_stamina,
    read_selected_stage,
    tap_box,
)
from module.trickcal.page import (
    page_dungeon_bakery_stage,
    page_dungeon_candy,
    page_dungeon_candy_stage,
    page_dungeon_clone,
    page_dungeon_clone_stage,
    page_dungeon_crayon_stage,
    page_dungeon_gold_stage,
    page_main,
)
from module.trickcal.trickcal_ui import TrickcalUI

DUNGEON_OFFSET = (20, 20)
DUNGEON_SWEEP_OFFSET = (25, 35)
SWEEP_MAX_ROUNDS = 10
SWEEP_TIMEOUT = 15
SCROLL_MAX_ATTEMPTS = 8
STAGE_SCROLL_ROI = (30, 120, 700, 660)


class TrickcalDungeon(TrickcalUI):
    """
    Clear star-candy stamina in 克隆工厂 and one chosen main dungeon via 速战.

    Pages:
        in: page_main
        out: page_main
    """

    def ui_additional(self):
        """Dismiss any leftover sweep/stamina/shop overlay during `ui_goto`."""
        if self.appear(EVENT_STAMINA_BUY, offset=DUNGEON_OFFSET, interval=2):
            logger.info('Leftover stamina buy popup, press 取消')
            self.device.click(EVENT_STAMINA_BUY)
            return True
        if self.appear(EVENT_SWEEP_CLEAR, offset=DUNGEON_OFFSET, interval=2):
            logger.info('Leftover sweep CLEAR popup, press 确定')
            self.device.click(EVENT_SWEEP_CLEAR)
            return True
        if self.appear(EVENT_SWEEP_CANCEL, offset=DUNGEON_OFFSET, interval=2):
            logger.info('Leftover sweep count popup, press 取消')
            self.device.click(EVENT_SWEEP_CANCEL)
            return True
        if self.appear(SHOP_BUY_CANCEL, offset=DUNGEON_OFFSET, interval=2):
            logger.info('Leftover shop buy popup, press 取消')
            self.device.click(SHOP_BUY_CANCEL)
            return True
        return super().ui_additional()

    def run(self):
        """
        Sweep 克隆工厂 (if enabled) and the configured main dungeon via 速战.

        Pages:
            in: page_main
            out: page_main
        """
        logger.hr('Trickcal Dungeon', level=1)
        self.ui_ensure(page_main)

        if self.config.TrickcalDungeon_CloneFactory:
            self.run_clone_factory(int(self.config.TrickcalDungeon_CloneFactoryStage))

        target = self.config.TrickcalDungeon_Dungeon
        if target != 'none':
            self.run_selected_dungeon(target, int(self.config.TrickcalDungeon_DungeonStage))

        self.ui_goto_main()
        self.config.task_delay(server_update=True)

    def _select_fixed_slot(self, kind, target, slot_area, stage_page):
        """Tap a fixed grid slot until the right detail panel shows `target`."""
        retry = Timer(2.0)
        for _ in self.loop(timeout=8):
            if read_selected_stage(self.device.image, kind) == target:
                return True
            if self.ui_page_appear(stage_page) and retry.reached():
                retry.reset()
                logger.info(f'Select {kind} stage {target}')
                self.device.click(tap_box(slot_area, f'DUNGEON_{kind.upper()}_STAGE'))  # alas-lint: allow - guarded by ui_page_appear
        return read_selected_stage(self.device.image, kind) == target

    def _select_scrollable_stage(self, kind, target, finder, stage_page, higher_is_down):
        """Scroll a stage list/map until `target` appears, tap it, and confirm selection."""
        if read_selected_stage(self.device.image, kind) == target:
            return True

        unchanged = 0
        for _ in range(SCROLL_MAX_ATTEMPTS):
            visible = finder(self.device.image)
            if target in visible:
                cx, cy = visible[target]
                return self._select_fixed_slot(
                    kind,
                    target,
                    (cx - 25, cy - 25, cx + 25, cy + 25),
                    stage_page,
                )

            if visible:
                want_higher = target > max(visible)
            else:
                want_higher = target >= 8

            # Bakery/Candy put higher numbers below (drag up); Gold map puts 9..20 above (drag down).
            drag_up = (want_higher and higher_is_down) or (not want_higher and not higher_is_down)
            before = crop(self.device.image, STAGE_SCROLL_ROI)
            start = (360, 540) if drag_up else (360, 200)
            end = (360, 200) if drag_up else (360, 540)
            logger.info(f'Scroll {kind} {"up" if drag_up else "down"} looking for stage {target} (visible={sorted(visible)})')
            self.device.drag(start, end, point_random=(-10, -10, 10, 10), name=f'DUNGEON_{kind.upper()}_SCROLL')

            settle = Timer(0.7).start()
            for _ in self.loop(timeout=2):
                if settle.reached() and self.ui_page_appear(stage_page):
                    break

            after = crop(self.device.image, STAGE_SCROLL_ROI)
            diff = float(np.abs(after.astype(np.int16) - before.astype(np.int16)).mean())
            if diff < 2.0:
                unchanged += 1
                if unchanged >= 2:
                    logger.warning(f'{kind} scroll reached boundary without finding stage {target}')
                    break
            else:
                unchanged = 0

        return read_selected_stage(self.device.image, kind) == target

    def _select_bakery_tab(self, tab_key):
        """Switch 神秘面包房 between 魔卡龙区域 and 奶卡龙区域."""
        retry = Timer(1.5)
        for _ in self.loop(timeout=6):
            if bakery_tab_selected(self.device.image, tab_key):
                return True
            if self.ui_page_appear(page_dungeon_bakery_stage) and retry.reached():
                retry.reset()
                logger.info(f'Switch bakery tab to {tab_key}')
                self.device.click(tap_box(BAKERY_TABS[tab_key], 'DUNGEON_BAKERY_TAB'))  # alas-lint: allow - guarded by ui_page_appear(page_dungeon_bakery_stage)
        return bakery_tab_selected(self.device.image, tab_key)

    def _select_crayon_stage(self, target):
        """Flip to the page containing `target` in 到手蜡 and tap its 5x2 slot."""
        if read_selected_stage(self.device.image, 'crayon') == target:
            return True

        target_page = crayon_target_page(target)
        for _ in range(5):
            cur_page = read_crayon_page(self.device.image)
            if cur_page is None:
                cur_stage = read_selected_stage(self.device.image, 'crayon')
                cur_page = crayon_target_page(cur_stage) if cur_stage is not None else 1
            if cur_page == target_page:
                break
            arrow = CRAYON_NEXT_AREA if target_page > cur_page else CRAYON_PREV_AREA
            logger.info(f'Flip crayon page {cur_page} -> {target_page}')
            self.device.click(tap_box(arrow, 'DUNGEON_CRAYON_PAGE'))  # alas-lint: allow - guarded by page_dungeon_crayon_stage loop
            settle = Timer(0.6).start()
            for _ in self.loop(timeout=2):
                if settle.reached() and self.ui_page_appear(page_dungeon_crayon_stage):
                    break

        return self._select_fixed_slot('crayon', target, crayon_slot_area(target), page_dungeon_crayon_stage)

    def _dismiss_stamina_buy(self):
        """Close the stamina purchase modal via 取消 without buying."""
        retry = Timer(2.0)
        clean = 0
        for _ in self.loop(timeout=8):
            if self.appear(EVENT_STAMINA_BUY, offset=DUNGEON_OFFSET):
                clean = 0
                if retry.reached():
                    retry.reset()
                    logger.info('Out of star-candy stamina (buy popup), press 取消')
                    self.device.click(EVENT_STAMINA_BUY)
                continue
            clean += 1
            if clean >= 2:
                return True
        return False

    def _open_sweep_dialog(self, sweep_btn):
        """Press 速战 until the 「请设置速战次数」 dialog appears."""
        retry = Timer(2.0)
        for _ in self.loop(timeout=SWEEP_TIMEOUT):
            if self.appear(DUNGEON_CLONE_EMPTY, offset=DUNGEON_OFFSET):
                logger.info('Clone factory daily entries exhausted (每日入场次数已用完), stop')
                return False
            if self.appear(EVENT_STAMINA_BUY, offset=DUNGEON_OFFSET):
                self._dismiss_stamina_buy()
                return False
            if self.appear(DUNGEON_SWEEP_TITLE, offset=DUNGEON_SWEEP_OFFSET) or self.appear(
                EVENT_SWEEP_TITLE, offset=DUNGEON_SWEEP_OFFSET
            ):
                return True
            if retry.reached():
                retry.reset()
                logger.info('Open dungeon sweep dialog, press 速战')
                self.device.click(sweep_btn)  # alas-lint: allow - guarded by dungeon_sweep_lit() before call
        return False

    def _sweep_confirm_once(self):
        """Set sweep count to 最大, press 速战, and return True once CLEAR appears."""
        max_tapped = False
        settle = Timer(0.5)
        confirm_retry = Timer(2.0)
        for _ in self.loop(timeout=20):
            if self.appear(EVENT_STAMINA_BUY, offset=DUNGEON_OFFSET):
                self._dismiss_stamina_buy()
                return False
            if self.handle_reward_popup():
                continue
            if self.appear(EVENT_SWEEP_CLEAR, offset=DUNGEON_OFFSET):
                return True
            if self.appear(DUNGEON_SWEEP_TITLE, offset=DUNGEON_SWEEP_OFFSET) or self.appear(
                EVENT_SWEEP_TITLE, offset=DUNGEON_SWEEP_OFFSET
            ):
                if not max_tapped:
                    logger.info('Set dungeon sweep count to 最大')
                    self.device.click(EVENT_SWEEP_MAX)  # alas-lint: allow - guarded by sweep dialog title
                    max_tapped = True
                    settle = Timer(0.5).start()
                    continue
                if not settle.reached():
                    continue
                if self.appear(DUNGEON_SWEEP_CONFIRM, offset=DUNGEON_OFFSET) and confirm_retry.reached():
                    confirm_retry.reset()
                    logger.info('Confirm dungeon sweep, press 速战')
                    self.device.click(DUNGEON_SWEEP_CONFIRM)
        return False

    def _close_sweep_cancel(self, stage_page):
        """Close the sweep count dialog via 取消 when a sweep cannot proceed."""
        retry = Timer(2.0)
        for _ in self.loop(timeout=8):
            if self.appear(EVENT_SWEEP_CANCEL, offset=DUNGEON_OFFSET):
                if retry.reached():
                    retry.reset()
                    logger.info('Cancel dungeon sweep dialog')
                    self.device.click(EVENT_SWEEP_CANCEL)
                continue
            if self.ui_page_appear(stage_page):
                return True
        return False

    def _close_sweep_clear(self, stage_page):
        """Dismiss CLEAR result overlay and settle back on `stage_page`."""
        retry = Timer(2.0)
        clean = 0
        for _ in self.loop(timeout=12):
            if self.handle_reward_popup():
                clean = 0
                continue
            if self.appear(EVENT_SWEEP_CLEAR, offset=DUNGEON_OFFSET):
                clean = 0
                if retry.reached():
                    retry.reset()
                    logger.info('Dismiss dungeon sweep CLEAR result, press 确定')
                    self.device.click(EVENT_SWEEP_CLEAR)
                continue
            if self.ui_page_appear(stage_page):
                clean += 1
                if clean >= 2:
                    return True
            else:
                clean = 0
        return False

    def _sweep_stage(self, kind, sweep_btn, stage_page, cost, bakery=False, is_clone=False):
        """Sweep the already-selected stage until stamina < `cost` or entries exhausted."""
        for _ in range(SWEEP_MAX_ROUNDS):
            stamina = read_dungeon_stamina(self.device.image, bakery=bakery)
            if stamina is not None and stamina < cost:
                logger.info(f'Star-candy stamina {stamina} < {cost}, stop {kind}')
                return True

            if is_clone:
                if self.appear(DUNGEON_CLONE_ZERO, offset=DUNGEON_OFFSET):
                    logger.info('Clone factory entries 0 -> 0, stop')
                    return True
                rem = read_clone_daily_remaining(self.device.image, on_splash=False)
                if rem == 0:
                    logger.info('Clone factory daily entries 0/8, stop')
                    return True

            if not dungeon_sweep_lit(self.device.image, kind):
                logger.warning(f'{kind} stage 速战 is disabled (not 3-starred or 0 entries), stop')
                return False

            if not self._open_sweep_dialog(sweep_btn):
                return True
            if not self._sweep_confirm_once():
                self._close_sweep_cancel(stage_page)
                return True
            if not self._close_sweep_clear(stage_page):
                return False
        return True

    def run_clone_factory(self, stage):
        """Sweep daily 8 entries in 克隆工厂 on `stage` (1..12)."""
        logger.hr('Dungeon: Clone Factory', level=2)
        stage = max(1, min(12, int(stage)))
        self.ui_ensure(page_dungeon_clone)

        rem = read_clone_daily_remaining(self.device.image, on_splash=True)
        if rem == 0:
            logger.info('Clone factory daily entries 0/8, skip')
            return True

        stamina = read_dungeon_stamina(self.device.image)
        if stamina is not None and stamina < 20:
            logger.info(f'Star-candy stamina {stamina} < 20, skip clone factory')
            return True

        self.ui_ensure(page_dungeon_clone_stage)
        if not self._select_fixed_slot('clone', stage, clone_slot_area(stage), page_dungeon_clone_stage):
            logger.warning(f'Could not select clone stage {stage}, skip')
            return False

        return self._sweep_stage(
            'clone',
            DUNGEON_CLONE_SWEEP,
            page_dungeon_clone_stage,
            cost=20,
            is_clone=True,
        )

    def run_selected_dungeon(self, dungeon_key, stage):
        """Enter the user-selected main dungeon, pick `stage`, and sweep remaining stamina."""
        stage = max(1, int(stage))
        logger.hr(f'Dungeon: {dungeon_key} stage {stage}', level=2)

        if dungeon_key == 'gold':
            self.ui_ensure(page_dungeon_gold_stage)
            if not self._select_scrollable_stage('gold', min(20, stage), find_gold_vaults, page_dungeon_gold_stage, higher_is_down=False):
                logger.warning(f'Could not select gold stage {stage}, skip')
                return False
            return self._sweep_stage('gold', DUNGEON_GOLD_SWEEP, page_dungeon_gold_stage, cost=10)

        if dungeon_key in BAKERY_TABS:
            self.ui_ensure(page_dungeon_bakery_stage)
            if not self._select_bakery_tab(dungeon_key):
                logger.warning(f'Could not switch bakery tab {dungeon_key}, skip')
                return False
            if not self._select_scrollable_stage('bakery', stage, find_bakery_stages, page_dungeon_bakery_stage, higher_is_down=True):
                logger.warning(f'Could not select bakery stage {stage}, skip')
                return False
            return self._sweep_stage('bakery', DUNGEON_BAKERY_SWEEP, page_dungeon_bakery_stage, cost=10, bakery=True)

        if dungeon_key in CANDY_MACHINE_AREAS:
            self.ui_ensure(page_dungeon_candy)
            retry = Timer(2.0)
            entered = False
            for _ in self.loop(timeout=8):
                if self.ui_page_appear(page_dungeon_candy_stage):
                    entered = True
                    break
                if self.ui_page_appear(page_dungeon_candy) and retry.reached():
                    retry.reset()
                    logger.info(f'Enter candy machine {dungeon_key}')
                    self.device.click(tap_box(CANDY_MACHINE_AREAS[dungeon_key], 'DUNGEON_CANDY_MACHINE'))  # alas-lint: allow - guarded by ui_page_appear(page_dungeon_candy)
            if not entered:
                logger.warning(f'Could not enter candy machine {dungeon_key}, skip')
                return False
            if not self._select_scrollable_stage('candy', stage, find_candy_stages, page_dungeon_candy_stage, higher_is_down=True):
                logger.warning(f'Could not select candy stage {stage}, skip')
                return False
            return self._sweep_stage('candy', DUNGEON_CANDY_SWEEP, page_dungeon_candy_stage, cost=10)

        if dungeon_key == 'crayon':
            self.ui_ensure(page_dungeon_crayon_stage)
            if not self._select_crayon_stage(stage):
                logger.warning(f'Could not select crayon stage {stage}, skip')
                return False
            return self._sweep_stage('crayon', DUNGEON_CRAYON_SWEEP, page_dungeon_crayon_stage, cost=20)

        logger.warning(f'Unknown dungeon key: {dungeon_key!r}')
        return False
