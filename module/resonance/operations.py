import cv2

from module.base.timer import Timer
from module.exception import GameStuckError
from module.logger import logger
from module.ocr.ocr import Ocr
from module.resonance import assets
from module.resonance.clarity import handle_clarity_recovery
from module.resonance.page import page_resonance_operations
from module.resonance.resonance_ui import ResonanceUI


CATEGORY_TABS = {
    'siege': (assets.OP_SIEGE_TAB, assets.OP_SIEGE_CHECK),
    'supply': (assets.OP_SUPPLY_TAB, assets.OP_SUPPLY_CHECK),
    'weekly': (assets.OP_WEEKLY_TAB, assets.OP_WEEKLY_CHECK),
}
STAGES = {
    'siege': ('Order', 'Blade', 'Lantern', 'Material', 'Knight', 'Think', 'Report', 'Large', 'Total'),
    'supply': ('Elegant', 'Standard', 'Salvation', 'Advanced', 'Chaos', 'Magic'),
    'weekly': ('Blind_Box',),
}
STAGE_TEMPLATES = {
    stage: getattr(assets, f'TEMPLATE_OP_{stage.upper()}')
    for stages in STAGES.values() for stage in stages
}
CARD_TITLES = (371, 398, 1138, 436)
CARD_ENTRIES = (371, 574, 1138, 633)
CARD_REWARDS = (371, 460, 1138, 535)
REMAINING = Ocr((1035, 147, 1123, 203), threshold=70, alphabet='0123456789/', name='Operation remaining')
OFFSET = (5, 5)


class ResonanceOperations(ResonanceUI):
    def run(self):
        plan = (
            ('siege', self.config.ResonanceOperations_SiegeRuns, self.config.ResonanceOperations_SiegeStage),
            ('supply', self.config.ResonanceOperations_SupplyRuns, self.config.ResonanceOperations_SupplyStage),
            ('weekly', self.config.ResonanceOperations_WeeklyRuns, 'Blind_Box'),
        )
        if any(count for _, count, _ in plan):
            self.ui_ensure(page_resonance_operations, skip_first_screenshot=False)
            for category, count, stage in plan:
                if count:
                    if self.run_category(category, count, stage) == 'no_clarity':
                        break
            self.ui_goto_main()
        self.config.task_delay(server_update=True)

    def run_category(self, category, limit, preferred):
        self.select_category(category)
        remaining = self.read_remaining()
        # The game counter includes manual play and survives interruptions.
        target_remaining = 3 - limit
        for expected in range(remaining - 1, target_remaining - 1, -1):
            stage, seen = self.find_stage(category, preferred)
            if stage is None and category == 'supply' and len(seen) == 1:
                stage, _ = self.find_stage(category, next(iter(seen)))
            if stage is None:
                logger.warning(f'No eligible operation matching {preferred!r}, open stages: {sorted(seen)}')
                return
            logger.info(f'Resonance operation: {category}/{stage}')
            preferred = stage
            if self.start_battle() == 'no_clarity':
                logger.info('行动汇总澄明度不足，停止后续作战')
                return 'no_clarity'
            self.wait_for_victory()
            self.ui_ensure(page_resonance_operations, skip_first_screenshot=False)
            self.select_category(category)
            if self.read_remaining() != expected:
                raise GameStuckError('Resonance operation did not consume exactly one reward attempt')

    def select_category(self, category):
        tab, selected = CATEGORY_TABS[category]
        for _ in self.loop(timeout=12):
            if self.appear(selected, offset=OFFSET):
                return
            if self.appear_then_click(tab, offset=OFFSET, interval=2):
                continue
        raise GameStuckError(f'Resonance operation category did not open: {category}')

    def read_remaining(self):
        for _ in self.loop(timeout=8):
            if self.ui_page_appear(page_resonance_operations, offset=OFFSET):
                if self.appear(assets.OP_EMPTY, offset=(2, 2), similarity=0.94):
                    return 0
                result = REMAINING.ocr(self.device.image)
                if result in ('0/3', '1/3', '2/3', '3/3'):
                    return int(result[0])
        raise GameStuckError('Resonance operation reward counter was unreadable')

    def visible_open_stages(self, category):
        titles = self.image_crop(CARD_TITLES)
        entries = [
            button.move(CARD_ENTRIES[:2])
            for button in assets.TEMPLATE_OP_ENTER.match_multi(
                self.image_crop(CARD_ENTRIES), similarity=0.90, threshold=6,
            )
        ]
        visible = {}
        for stage in STAGES[category]:
            score, title = STAGE_TEMPLATES[stage].match_result(titles)
            if score > 0.88:
                title_x = CARD_TITLES[0] + (title.button[0] + title.button[2]) / 2
                for entry in entries:
                    entry_x = (entry.button[0] + entry.button[2]) / 2
                    if abs(title_x - entry_x) < 45:
                        visible[stage] = entry
                        break
        return visible

    def find_stage(self, category, preferred):
        seen = set()
        for direction in (-1, 1):
            for _ in range(12):
                if self.ui_page_appear(page_resonance_operations, offset=OFFSET):
                    visible = self.visible_open_stages(category)
                    seen.update(visible)
                    stage = next(iter(visible), None) if preferred == 'Auto' else preferred
                    if stage in visible:
                        self.device.click(visible[stage])
                        return stage, seen
                    before = self.image_crop(CARD_REWARDS)
                    self.device.swipe((755, 360), (755 + 280 * direction, 360),
                                      duration=0.55, name='OPERATION_CAROUSEL')
                    if not self.wait_until_still(CARD_REWARDS, timeout=12, threshold=3,
                                                 skip_first_screenshot=False):
                        raise GameStuckError('Resonance operations carousel did not settle')
                    if cv2.absdiff(before, self.image_crop(CARD_REWARDS)).mean() < 2:
                        break
                else:
                    raise GameStuckError('Resonance operations carousel is no longer visible')
            else:
                raise GameStuckError('Resonance operations carousel did not reach its end')
        return None, seen

    def start_battle(self):
        sent = False
        for _ in self.loop(skip_first=False, timeout=30):
            if self.appear(assets.OP_PAUSE, offset=OFFSET):
                return 'started'
            if self.appear(assets.CLARITY_PROMPT, offset=OFFSET) or self.appear(assets.CLARITY_RECOVERY_CHECK, offset=OFFSET):
                mode = getattr(self.config, 'ResonanceOperations_UseClarityItem', 'none')
                if handle_clarity_recovery(self, mode):
                    self.interval_clear((assets.OP_START, assets.OP_START_WIDE))
                    sent = False
                    continue
                return 'no_clarity'
            if sent:
                continue
            if self.appear(assets.OP_TEAM, offset=OFFSET):
                sent = self.appear_then_click(assets.OP_TEAM_START, offset=OFFSET, interval=2)
                continue
            if self.appear(assets.OP_DETAIL, offset=OFFSET):
                if self.appear_then_click(assets.OP_START, offset=OFFSET, interval=2):
                    continue
                if self.appear_then_click(assets.OP_START_WIDE, offset=(120, 15), interval=2):
                    continue
        raise GameStuckError('Resonance operation battle did not start')

    def wait_for_victory(self):
        auto_confirmed = False
        auto_off = Timer(0.5, count=2).start()
        auto_retry = Timer(4)
        for _ in self.loop(timeout=240):
            if self.handle_reward_popup():
                continue
            if self.operation_victory_ready():
                if not auto_confirmed:
                    logger.warning('Resonance operation won before the auto combat switch was confirmed')
                return
            if self.appear(assets.OP_PAUSE, offset=OFFSET):
                self.device.stuck_record_clear()
                if auto_confirmed:
                    continue
                if self.image_color_count(assets.OP_PAUSE, (255, 255, 255), threshold=50, count=250):
                    if self.image_color_count(assets.OP_AUTO_ON, (255, 255, 255), threshold=70, count=240):
                        auto_off.reset()
                        if self.appear(assets.OP_AUTO_ON, offset=OFFSET, similarity=0.76):
                            auto_confirmed = True
                            logger.info('Resonance auto combat confirmed on')
                        continue
                    if (self.appear(assets.OP_AUTO_OFF, offset=OFFSET, similarity=0.74)
                            and self.image_color_count(assets.OP_AUTO_OFF, (130, 130, 130), threshold=18, count=250)):
                        if auto_off.reached() and auto_retry.reached():
                            self.device.click(assets.OP_AUTO_OFF)
                            auto_off.reset()
                            auto_retry.reset()
                        continue
            auto_off.reset()
        raise GameStuckError('Resonance operation battle timed out')
