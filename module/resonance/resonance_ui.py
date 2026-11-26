"""UI layer of 雷索纳斯 (Resonance Solstice)."""

from module.base.button import Button
from module.exception import GameStuckError
from module.resonance.assets import (
    DAILY_HOME, EXCHANGE_MODAL_ARROW, FATIGUE_CONFIRM_CANCEL, FATIGUE_CONFIRM_MODAL, LOGIN_DAILY_CHECK_IN,
    LOGIN_ENTER, LOGIN_REWARD, LOGIN_START, MAP_ASSIST_PANEL, MAP_DRIVE_ASSIST, OP_NEXT, OP_WIN,
    PRESTIGE_MODAL_CHECK, PRESTIGE_MODAL_CONFIRM, PREP_REWARD_MODAL, SHOP_CANCEL, SHOP_MAX, SHOP_MODAL_PRICE,
    TRADE_BUY_REPORT, TRADE_ITEMS_MODAL, TRADE_RESTOCK_CANCEL, TRADE_RESTOCK_MODAL, TRADE_SELL_REPORT,
)
from module.resonance.page import (
    page_daily, page_main, page_resonance_bento, page_resonance_city, page_resonance_crew,
    page_resonance_dispatch, page_resonance_exchange, page_resonance_fatigue, page_resonance_garbage,
    page_resonance_island_beach, page_resonance_island_friend, page_resonance_island_hub,
    page_resonance_island_promo, page_resonance_island_revenue, page_resonance_mail,
    page_resonance_map_station, page_resonance_operation_detail, page_resonance_operation_team,
    page_resonance_operations, page_resonance_pass, page_resonance_prep, page_resonance_rest_area,
    page_resonance_rest_drink, page_resonance_shop, page_resonance_survey, page_resonance_terminal,
    page_resonance_trade_buy, page_resonance_trade_hub, page_resonance_trade_invest, page_resonance_trade_sell,
    page_resonance_train_maint, page_resonance_world_map,
)
from module.ui.ui import UI


EXCHANGE_MODAL_OFFSET = (300, 6)


class ResonanceUI(UI):
    """UI class of 雷索纳斯."""

    page_main = page_main
    pages = (
        page_daily, page_resonance_terminal, page_resonance_dispatch,
        page_resonance_prep, page_resonance_survey, page_resonance_operations, page_resonance_operation_detail,
        page_resonance_operation_team, page_resonance_pass, page_resonance_shop, page_resonance_exchange,
        page_resonance_crew, page_resonance_mail, page_resonance_world_map, page_resonance_map_station,
        page_resonance_fatigue, page_resonance_bento, page_resonance_rest_area, page_resonance_rest_drink,
        page_resonance_trade_hub, page_resonance_trade_invest, page_resonance_trade_buy, page_resonance_trade_sell,
        page_resonance_train_maint, page_resonance_garbage, page_resonance_island_hub,
        page_resonance_island_promo, page_resonance_island_beach, page_resonance_island_revenue,
        page_resonance_island_friend,
        # City shares MAIN_CHECK's top-right icon, so page_resonance_city must precede page_main.
        page_resonance_city, page_main,
    )

    def app_start(self):
        super().app_start()
        for _ in self.loop(skip_first=False, timeout=60):
            if self.ui_additional():
                continue
            if any(self.ui_page_appear(page) for page in self.pages if page is not self.page_main):
                self.appear_then_click(DAILY_HOME, offset=(5, 5), interval=2)
                continue
            if self.is_in_main():
                self.ui_current = self.page_main
                return
        raise GameStuckError('Resonance did not reach the main page after login')

    _reward_close_btn = Button(
        area=(580, 680, 700, 712), color=(), button=(580, 680, 700, 712), name='LOGIN_REWARD'
    )

    def handle_reward_popup(self):
        if self.appear_then_click(LOGIN_REWARD, offset=(5, 5), interval=2):
            return True
        if self.appear(LOGIN_REWARD, offset=(30, 140), similarity=0.78, interval=2):
            self.device.click(self._reward_close_btn)
            return True
        return False

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

    def handle_trade_report(self):
        """Dismiss buy or sell settlement report popup."""
        offset = (5, 5)
        return any(
            self.appear_then_click(button, offset=offset, interval=2)
            for button in (TRADE_BUY_REPORT, TRADE_SELL_REPORT)
        )

    def handle_trade_modal(self):
        """Dismiss trade restock, use-item, fatigue confirm, prestige, or assist modal overlays."""
        offset = (5, 5)
        if self.appear(TRADE_RESTOCK_MODAL, offset=offset) and self.appear(TRADE_RESTOCK_CANCEL, offset=offset):
            return self.appear_then_click(TRADE_RESTOCK_CANCEL, offset=offset, interval=2)
        if self.appear(FATIGUE_CONFIRM_MODAL, offset=offset) and self.appear(FATIGUE_CONFIRM_CANCEL, offset=offset):
            return self.appear_then_click(FATIGUE_CONFIRM_CANCEL, offset=offset, interval=2)
        if self.appear(PRESTIGE_MODAL_CHECK, offset=offset) and self.appear(PRESTIGE_MODAL_CONFIRM, offset=offset):
            return self.appear_then_click(PRESTIGE_MODAL_CONFIRM, offset=offset, interval=2)
        if self.appear(MAP_ASSIST_PANEL, offset=offset):
            return self.appear_then_click(MAP_DRIVE_ASSIST, offset=offset, interval=2)
        return self.appear_then_click(TRADE_ITEMS_MODAL, offset=offset, interval=2)

    def ui_additional(self):
        if (self.handle_reward_popup() or self.handle_operation_victory()
                or self.handle_shop_preview() or self.handle_trade_report() or self.handle_trade_modal()):
            return True
        return any(
            self.appear_then_click(button, offset=(5, 5), interval=2)
            for button in (LOGIN_DAILY_CHECK_IN, LOGIN_START, LOGIN_ENTER, PREP_REWARD_MODAL)
        )
