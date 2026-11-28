from module.base.button import Button
from module.base.timer import Timer
from module.exception import GameStuckError, TaskFailed
from module.resonance.assets import (
    PASS_CLAIM_ALL, PASS_DAILY_SELECTED, PASS_DAILY_TAB, PASS_REWARDS_SELECTED, PASS_REWARDS_TAB,
    PASS_TASKS_SELECTED, PASS_TASKS_TAB, PASS_WEEKLY_SELECTED, PASS_WEEKLY_TAB,
)
from module.resonance.page import page_resonance_pass
from module.resonance.resonance_ui import ResonanceUI


OFFSET = (5, 5)
BOOK_AREAS = ((22, 118, 200, 190), (22, 194, 200, 265))
BOOK_MARK_AREAS = ((0, 140, 22, 164), (0, 216, 22, 240))
BOOK_MARK_COLORS = ((205, 225, 219), (187, 154, 106))
BOOKS = (
    Button(area=BOOK_AREAS[0], color=(), button=(46, 126, 184, 182), name='PASS_FIRST_BOOK'),
    Button(area=BOOK_AREAS[1], color=(), button=(46, 202, 184, 257), name='PASS_SECOND_BOOK'),
)  # alas-lint: allow R9: coordinate-only hitboxes; old template assets are obsolete


class ResonancePass(ResonanceUI):
    def run(self):
        self.ui_ensure(page_resonance_pass, skip_first_screenshot=False)
        available = [index for index in range(len(BOOKS)) if self.book_available(index)]
        if not available:
            raise GameStuckError('Resonance pass books were not found')
        current = self.selected_book()
        available.sort(key=lambda index: index != current)
        for index in available:
            if index != current and not self.open_book(index):
                self.config.task_delay(success=False)
                raise TaskFailed('Resonance pass book %d could not be selected' % (index + 1))
            self.claim_book()
        self.ui_goto_main()
        self.config.task_delay(server_update=True)

    def book_available(self, index):
        # Pale blue is an unselected card rail; gold is the selected card rail.
        return any(self.image_color_count(BOOK_MARK_AREAS[index], color, threshold=50, count=150)
                   for color in BOOK_MARK_COLORS)

    def selected_book(self):
        selected = [index for index in range(len(BOOKS))
                    if self.image_color_count(BOOK_MARK_AREAS[index], BOOK_MARK_COLORS[1], threshold=50, count=150)]
        return selected[0] if len(selected) == 1 else None

    def open_book(self, index):
        if self.book_available(index) and self.appear(PASS_REWARDS_SELECTED, offset=OFFSET):
            confirmed = False
            retry = Timer(2).start()
            for _ in self.loop(timeout=8, skip_first=False):
                if self.appear(PASS_REWARDS_SELECTED, offset=OFFSET) and self.selected_book() == index:
                    if confirmed:
                        return True
                    confirmed = True
                else:
                    confirmed = False
                    if self.book_available(index) and self.appear(PASS_REWARDS_SELECTED, offset=OFFSET) and retry.reached():
                        self.device.click(BOOKS[index])
                        retry.reset()
        return False

    def claim_book(self):
        self.select_view(PASS_TASKS_TAB, PASS_TASKS_SELECTED)
        for tab, selected in (
            (PASS_DAILY_TAB, PASS_DAILY_SELECTED),
            (PASS_WEEKLY_TAB, PASS_WEEKLY_SELECTED),
            (PASS_REWARDS_TAB, PASS_REWARDS_SELECTED),
        ):
            self.select_view(tab, selected)
            self.claim_view(selected)

    def select_view(self, tab, selected):
        self.ui_click(tab, selected, additional=self.handle_reward_popup, confirm_wait=0,
                      offset=OFFSET, retry_wait=2, skip_first_screenshot=True)

    def claim_view(self, selected):
        idle = Timer(1.5, count=2).start()
        for _ in self.loop(timeout=25):
            if self.handle_reward_popup():
                idle.reset()
                continue
            if self.appear(selected, offset=OFFSET):
                if self.appear_then_click(PASS_CLAIM_ALL, offset=OFFSET, interval=3):
                    idle.reset()
                    continue
                if self.appear(PASS_CLAIM_ALL, offset=OFFSET):
                    idle.reset()
                    continue
                if idle.reached():
                    return
            else:
                idle.reset()
        raise GameStuckError(f'Resonance pass did not finish claiming on {selected}')
