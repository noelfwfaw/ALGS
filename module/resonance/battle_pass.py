from module.base.timer import Timer
from module.exception import GameStuckError
from module.resonance.assets import (
    PASS_CLAIM_ALL, PASS_DAILY_SELECTED, PASS_DAILY_TAB, PASS_FIRST_BOOK, PASS_REWARDS_SELECTED,
    PASS_REWARDS_TAB, PASS_SECOND_BOOK, PASS_TASKS_SELECTED, PASS_TASKS_TAB, PASS_WEEKLY_SELECTED,
    PASS_WEEKLY_TAB,
)
from module.resonance.page import page_resonance_pass
from module.resonance.resonance_ui import ResonanceUI


OFFSET = (5, 5)
BOOKS = (PASS_FIRST_BOOK, PASS_SECOND_BOOK)


class ResonancePass(ResonanceUI):
    def run(self):
        self.ui_ensure(page_resonance_pass, skip_first_screenshot=False)
        self.claim_book()
        current = next((book for book in BOOKS if self.appear(book, offset=OFFSET)), None)
        for book in BOOKS:
            if book is not current and self.open_book(book):
                self.claim_book()
        self.ui_goto_main()
        self.config.task_delay(server_update=True)

    def open_book(self, book):
        if self.appear(PASS_REWARDS_SELECTED, offset=OFFSET):
            # An empty book slot is over the cover art and has no action.
            self.device.click(book)
            return self.wait_until_appear(book, offset=OFFSET, timeout=3, settle=2)
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
