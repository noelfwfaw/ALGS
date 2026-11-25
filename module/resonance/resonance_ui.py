"""UI layer of 雷索纳斯 (Resonance Solstice)."""

from module.exception import GameStuckError
from module.resonance.assets import (
    DAILY_HOME, EXCHANGE_MODAL_ARROW, LOGIN_DAILY_CHECK_IN, LOGIN_ENTER, LOGIN_REWARD, LOGIN_START, OP_NEXT, OP_WIN,
    SHOP_CANCEL, SHOP_MAX, SHOP_MODAL_PRICE,
)
from module.resonance.page import (
    page_daily, page_main, page_resonance_exchange, page_resonance_operation_detail, page_resonance_operation_team,
    page_resonance_operations, page_resonance_pass, page_resonance_shop,
)
from module.ui.ui import UI


EXCHANGE_MODAL_OFFSET = (300, 6)


class ResonanceUI(UI):
    """UI class of 雷索纳斯."""

    page_main = page_main
    pages = (
        page_main, page_daily, page_resonance_operations, page_resonance_operation_detail,
        page_resonance_operation_team, page_resonance_pass, page_resonance_shop, page_resonance_exchange,
    )

    def app_start(self):
        super().app_start()
        for _ in self.loop(skip_first=False, timeout=60):
            if self.ui_additional():
                continue
            if self.is_in_main():
                self.ui_current = self.page_main
                return
            if any(self.ui_page_appear(page) for page in self.pages[1:]):
                self.appear_then_click(DAILY_HOME, offset=(5, 5), interval=2)
        raise GameStuckError('Resonance did not reach the main page after login')

    def handle_reward_popup(self):
        return self.appear_then_click(LOGIN_REWARD, offset=(5, 5), interval=2)

    def operation_victory_ready(self):
        # The arrow is visible underneath the victory animation, before it is clickable.
        return (
            self.appear(OP_WIN, offset=(10, 10))
            and self.appear(OP_NEXT, offset=(6, 6))
            and self.image_color_count(OP_NEXT, (255, 255, 255), threshold=45, count=1000)
        )

    def handle_operation_victory(self):
        return self.operation_victory_ready() and self.appear_then_click(OP_NEXT, offset=(6, 6), interval=2)

    def handle_shop_preview(self):
        offset = (5, 5)
        return (
            (self.appear(EXCHANGE_MODAL_ARROW, offset=EXCHANGE_MODAL_OFFSET)
             or (self.appear(SHOP_MODAL_PRICE, offset=offset) and self.appear(SHOP_MAX, offset=offset)))
            and self.appear_then_click(SHOP_CANCEL, offset=offset, interval=2)
        )

    def ui_additional(self):
        if self.handle_reward_popup() or self.handle_operation_victory() or self.handle_shop_preview():
            return True
        return any(
            self.appear_then_click(button, offset=(5, 5), interval=2)
            for button in (LOGIN_DAILY_CHECK_IN, LOGIN_START, LOGIN_ENTER)
        )
