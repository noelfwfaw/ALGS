"""
Order daily relic claim (Trickcal 圣团 -> 总部 -> 世界树圣物).

Flow:
    page_main --bottom-right 「圣团」 ORDER_ENTRY--> page_order (ORDER_CHECK)
    page_order --ensure 「总部」 tab via ORDER_HQ_TAB_AREA if ORDER_HQ_TITLE absent-->
    tap 世界树圣物 shrine (ORDER_RELIC_SHRINE_AREA) --> page_order_relic (ORDER_RELIC_TITLE)
    tap lit yellow 「获取」 (ORDER_RELIC_CLAIM) --> handle_reward_popup()
    exit to page_main
"""

from module.base.timer import Timer
from module.logger import logger
from module.trickcal.assets import ORDER_HQ_TITLE, ORDER_RELIC_CLAIM
from module.trickcal.dungeon_stage import tap_box
from module.trickcal.page import page_main, page_order, page_order_relic
from module.trickcal.trickcal_ui import TrickcalUI

ORDER_OFFSET = (20, 20)
ORDER_STEP_TIMEOUT = 10
ORDER_CLAIM_TIMEOUT = 10
RELIC_CLAIM_COLOR_THRESHOLD = 45
RELIC_CLAIM_GREY_FRAMES = 3

# 圣团页面底部「总部」页签区域（若上次停在其他页签则需切回总部）
ORDER_HQ_TAB_AREA = (292, 635, 372, 695)
# 圣团总部左下角世界树圣物底座可点击区域
ORDER_RELIC_SHRINE_AREA = (140, 425, 290, 560)


def order_relic_claim_lit(image):
    """Return True when the 世界树圣物「获取」 button is lit yellow rather than greyed out."""
    return ORDER_RELIC_CLAIM.appear_on(image, threshold=RELIC_CLAIM_COLOR_THRESHOLD)


class TrickcalOrder(TrickcalUI):
    """Claim the daily World Tree Relic reward inside 圣团."""

    def run(self):
        """Enter 圣团 -> 总部 -> 世界树圣物, claim reward if available, and return to lobby."""
        logger.hr('Trickcal Order', level=1)
        self.ui_ensure(page_main)
        self.ui_ensure(page_order)

        if self._ensure_hq() and self._open_relic():
            self._claim_relic()

        self.ui_goto_main()
        self.config.task_delay(server_update=True)

    def _ensure_hq(self):
        """Ensure 圣团 is currently on the 总部 tab."""
        if self.appear(ORDER_HQ_TITLE, offset=ORDER_OFFSET):
            return True

        hq_tab = tap_box(ORDER_HQ_TAB_AREA, 'ORDER_HQ_TAB')
        retry = Timer(2.0)
        for _ in self.loop(timeout=ORDER_STEP_TIMEOUT):
            if self.appear(ORDER_HQ_TITLE, offset=ORDER_OFFSET):
                return True
            if self.ui_page_appear(page_order) and retry.reached():
                retry.reset()
                logger.info('Order: switch to 总部 tab')
                self.device.click(hq_tab)  # alas-lint: allow - guarded by ui_page_appear(page_order)
        logger.warning('Order: failed to switch to 总部 tab before timeout')
        return False

    def _open_relic(self):
        """Tap 世界树圣物 on the 总部 screen until page_order_relic appears."""
        if self.ui_page_appear(page_order_relic):
            return True

        shrine = tap_box(ORDER_RELIC_SHRINE_AREA, 'ORDER_RELIC_SHRINE')
        retry = Timer(2.0)
        for _ in self.loop(timeout=ORDER_STEP_TIMEOUT):
            if self.ui_page_appear(page_order_relic):
                return True
            if self.handle_reward_popup():
                continue
            if self.ui_page_appear(page_order) and self.appear(ORDER_HQ_TITLE, offset=ORDER_OFFSET) and retry.reached():
                retry.reset()
                logger.info('Order: tap 世界树圣物')
                self.device.click(shrine)  # alas-lint: allow - guarded by ui_page_appear(page_order) and ORDER_HQ_TITLE
        logger.warning('Order: failed to open 世界树圣物 before timeout')
        return False

    def _claim_relic(self):
        """Claim World Tree Relic daily reward when 获取 is lit yellow and dismiss reward popup."""
        retry = Timer(2.0)
        claimed = False
        grey_frames = 0
        for _ in self.loop(timeout=ORDER_CLAIM_TIMEOUT):
            if self.handle_reward_popup():
                claimed = True
                grey_frames = 0
                continue
            if self.ui_page_appear(page_order_relic) and ORDER_RELIC_CLAIM.match_luma(self.device.image, offset=ORDER_OFFSET):
                if order_relic_claim_lit(self.device.image):
                    grey_frames = 0
                    if retry.reached():
                        retry.reset()
                        logger.info('Order: press 世界树圣物 获取')
                        self.device.click(ORDER_RELIC_CLAIM)  # alas-lint: allow - guarded by ui_page_appear(page_order_relic), match_luma, and order_relic_claim_lit()
                else:
                    grey_frames += 1
                    if (claimed and grey_frames >= 2) or grey_frames >= RELIC_CLAIM_GREY_FRAMES:
                        if not claimed:
                            logger.info('Order: 世界树圣物 获取 already claimed (grey), skip')
                        return claimed
            else:
                grey_frames = 0
        return claimed
