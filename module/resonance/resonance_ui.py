"""UI layer of 雷索纳斯 (Resonance Solstice)."""

import cv2
import numpy as np

from module.base.button import Button
from module.base.timer import Timer
from module.exception import GameStuckError
from module.resonance.assets import (
    ARREST_RESULT, BENTO_CONFIRM_MODAL, BENTO_RESULT_MODAL, DAILY_HOME, DISPATCH_REPORT, EXCHANGE_MODAL_ARROW,
    FATIGUE_CONFIRM_CANCEL, FATIGUE_CONFIRM_MODAL, LOGIN_DAILY_CHECK_IN, LOGIN_ENTER, LOGIN_REWARD, LOGIN_START,
    MAP_ASSIST_PANEL, MAP_DRIVE_ASSIST, OP_NEXT, OP_WIN, PRESTIGE_MODAL_CHECK, PRESTIGE_MODAL_CONFIRM,
    PREP_REWARD_MODAL, SHOP_CANCEL, SHOP_MAX, SHOP_MODAL_PRICE, TAP_BLANK_EXIT, TRADE_BUY_REPORT,
    TRADE_ITEMS_MODAL, TRADE_RESTOCK_CANCEL, TRADE_RESTOCK_MODAL, TRADE_SELL_REPORT,
)
from module.resonance.page import (
    page_daily, page_main, page_resonance_bento, page_resonance_city, page_resonance_crew,
    page_resonance_dispatch, page_resonance_exchange, page_resonance_fatigue, page_resonance_garbage,
    page_resonance_island_beach, page_resonance_island_friend, page_resonance_island_hub,
    page_resonance_island_promo, page_resonance_island_revenue, page_resonance_local_shop, page_resonance_mail,
    page_resonance_map_station, page_resonance_operation_detail, page_resonance_operation_team,
    page_resonance_operations, page_resonance_pass, page_resonance_prep, page_resonance_rest_area,
    page_resonance_rest_drink, page_resonance_shop, page_resonance_survey, page_resonance_terminal,
    page_resonance_trade_buy, page_resonance_trade_hub, page_resonance_trade_invest, page_resonance_trade_sell,
    page_resonance_train_maint, page_resonance_world_map,
)
from module.ui.ui import UI


EXCHANGE_MODAL_OFFSET = (300, 6)
TRANSIT_ENCOUNTER_BOX = (870, 180, 1090, 330)
TRANSIT_ENCOUNTER_TITLE_BOX = (975, 198, 1045, 260)
TRANSIT_ENCOUNTER_ALLOWED = (930, 205, 1040, 285)
TRANSIT_HUD_BOX = (480, 30, 830, 130)
TRANSIT_STATION_MARKER_ALLOWED = (515, 40, 560, 70)
TRANSIT_DESTINATION_TEXT_BOX = (590, 24, 720, 52)
TRANSIT_REMAINING_TEXT_BOX = (585, 108, 740, 126)
TRANSIT_CABIN_BOX = (680, 650, 790, 710)
TRANSIT_SPEED_BOX = (620, 635, 670, 685)
TRANSIT_SPEED_ALLOWED = (625, 640, 660, 680)
TRANSIT_B_BOX = (1085, 625, 1140, 670)
TRANSIT_B_GLYPH_BOX = (1088, 628, 1125, 668)
TRANSIT_D_BOX = (1195, 590, 1270, 640)
TRANSIT_D_ALLOWED = (1220, 598, 1263, 634)
TRANSIT_FORBIDDEN_BOXES = (
    (520, 115, 840, 190),  # 立即返航
    (1145, 625, 1205, 690),  # R
    (840, 340, 1080, 520),  # 诱饵气球
    (1040, 180, 1180, 340),  # 暂不可用
)


def _inside_box(point, box):
    return box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]


def _boxes_overlap(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _largest_component(mask):
    """Return (stats, centroid) for the largest connected component."""
    count, _, stats, centroids = cv2.connectedComponentsWithStats(mask.astype(np.uint8))
    if count <= 1:
        return None
    index = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return stats[index], centroids[index]


def _yellow_component(image, box, min_area):
    """Find a local yellow UI component without matching the moving background."""
    x1, y1, x2, y2 = box
    rgb = image[y1:y2, x1:x2].astype(np.int16)
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    found = _largest_component((r > 170) & (g > 120) & (b < 110) & (r - b > 100))
    if found is None:
        return None
    stats, centroid = found
    if stats[cv2.CC_STAT_AREA] < min_area:
        return None
    return (int(stats[cv2.CC_STAT_LEFT] + x1), int(stats[cv2.CC_STAT_TOP] + y1),
            int(stats[cv2.CC_STAT_WIDTH]), int(stats[cv2.CC_STAT_HEIGHT])), centroid


def _red_component(image, box, min_area):
    x1, y1, x2, y2 = box
    rgb = image[y1:y2, x1:x2].astype(np.int16)
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    found = _largest_component((r > 100) & (r - g > 35) & (r - b > 35))
    if found is None:
        return None
    stats, centroid = found
    if stats[cv2.CC_STAT_AREA] < min_area:
        return None
    return (int(stats[cv2.CC_STAT_LEFT] + x1), int(stats[cv2.CC_STAT_TOP] + y1),
            int(stats[cv2.CC_STAT_WIDTH]), int(stats[cv2.CC_STAT_HEIGHT])), centroid + (x1, y1)


def _white_text_ready(image, box):
    """Require several bright glyph components, not a flat color patch."""
    x1, y1, x2, y2 = box
    mask = image[y1:y2, x1:x2].min(axis=2) > 160
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8))
    glyphs = [s for s in stats[1:] if s[cv2.CC_STAT_AREA] >= 6
              and 2 <= s[cv2.CC_STAT_WIDTH] <= 45 and 2 <= s[cv2.CC_STAT_HEIGHT] <= 25]
    return len(glyphs) >= 5 and sum(int(s[cv2.CC_STAT_AREA]) for s in glyphs) >= 200


def _white_glyph_ready(image, box):
    x1, y1, x2, y2 = box
    mask = image[y1:y2, x1:x2].min(axis=2) > 160
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8))
    return any(s[cv2.CC_STAT_AREA] >= 120 and 15 <= s[cv2.CC_STAT_WIDTH] <= 30
               and 20 <= s[cv2.CC_STAT_HEIGHT] <= 40 for s in stats[1:])


def _dark_text_ready(image, box):
    x1, y1, x2, y2 = box
    mask = image[y1:y2, x1:x2].max(axis=2) < 70
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8))
    return int(mask.sum()) >= 250 and sum(int(s[cv2.CC_STAT_AREA]) >= 5 for s in stats[1:]) >= 5


def _hole_glyph_targets(image, box, min_brightness, outer_bounds, hole_bounds):
    """Return hole centers for bright enclosed glyphs, including the narrow speed zero and D."""
    x1, y1, x2, y2 = box
    gray = image[y1:y2, x1:x2].max(axis=2)
    contours, hierarchy = cv2.findContours((gray > 140).astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    targets = []
    for index, contour in enumerate(contours):
        if hierarchy is None or hierarchy[0, index, 3] != -1:
            continue
        x, y, width, height = cv2.boundingRect(contour)
        if not (outer_bounds[0] <= width <= outer_bounds[2] and outer_bounds[1] <= height <= outer_bounds[3]):
            continue
        holes = np.where(hierarchy[0, :, 3] == index)[0]
        if len(holes) != 1:
            continue
        hx, hy, hw, hh = cv2.boundingRect(contours[int(holes[0])])
        if not (hole_bounds[0] <= hw <= hole_bounds[2] and hole_bounds[1] <= hh <= hole_bounds[3]):
            continue
        filled = np.zeros(gray.shape, dtype=np.uint8)
        cv2.drawContours(filled, [contour], -1, 255, -1)
        if float(gray[filled > 0].mean()) < min_brightness:
            continue
        targets.append((x1 + hx + hw / 2, y1 + hy + hh / 2))
    return targets


def transit_encounter_target(image):
    """Return the safe top-sector center only for the guard encounter wheel."""
    found = _yellow_component(image, TRANSIT_ENCOUNTER_BOX, min_area=5000)
    if found is None:
        return None
    (_, _, width, height), centroid = found
    if width < 150 or height < 100:
        return None
    target = (centroid[0] + TRANSIT_ENCOUNTER_BOX[0], centroid[1] + TRANSIT_ENCOUNTER_BOX[1])
    if not _inside_box(target, TRANSIT_ENCOUNTER_ALLOWED) or not _dark_text_ready(image, TRANSIT_ENCOUNTER_TITLE_BOX):
        return None
    return int(round(target[0])), int(round(target[1]))


def transit_parked_target(image):
    """Return enabled D only on an unobscured, destination-bound, stopped cab."""
    marker = _yellow_component(image, TRANSIT_HUD_BOX, min_area=120)
    if marker is None:
        return None
    (_, _, width, height), centroid = marker
    marker_center = (centroid[0] + TRANSIT_HUD_BOX[0], centroid[1] + TRANSIT_HUD_BOX[1])
    if width < 20 or height < 12 or not _inside_box(marker_center, TRANSIT_STATION_MARKER_ALLOWED):
        return None
    if not (_white_text_ready(image, TRANSIT_DESTINATION_TEXT_BOX)
            and _white_text_ready(image, TRANSIT_REMAINING_TEXT_BOX)
            and _white_text_ready(image, TRANSIT_CABIN_BOX)):
        return None
    brake = _red_component(image, TRANSIT_B_BOX, min_area=180)
    if brake is None:
        return None
    (_, _, brake_width, brake_height), brake_center = brake
    if brake_width < 15 or brake_height < 15 or not _inside_box(brake_center, (1105, 635, 1138, 670)):
        return None
    if not _white_glyph_ready(image, TRANSIT_B_GLYPH_BOX):
        return None
    speed = _hole_glyph_targets(image, TRANSIT_SPEED_BOX, min_brightness=75,
                                outer_bounds=(8, 20, 30, 45), hole_bounds=(3, 8, 15, 30))
    if len(speed) != 1 or not _inside_box(speed[0], TRANSIT_SPEED_ALLOWED):
        return None
    drive = _hole_glyph_targets(image, TRANSIT_D_BOX, min_brightness=115,
                                outer_bounds=(20, 25, 90, 55), hole_bounds=(3, 8, 15, 25))
    if len(drive) != 1 or not _inside_box(drive[0], TRANSIT_D_ALLOWED):
        return None
    return int(round(drive[0][0])), int(round(drive[0][1]))


class ResonanceUI(UI):
    """UI class of 雷索纳斯."""

    page_main = page_main
    pages = (
        page_daily, page_resonance_terminal, page_resonance_dispatch,
        page_resonance_prep, page_resonance_survey, page_resonance_operations, page_resonance_operation_detail,
        page_resonance_operation_team, page_resonance_pass, page_resonance_local_shop, page_resonance_shop,
        page_resonance_exchange,
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
            if self.ui_additional() or self.handle_transit_recovery():
                continue
            if any(self.ui_page_appear(page) for page in self.pages if page is not self.page_main):
                self.appear_then_click(DAILY_HOME, offset=(5, 5), interval=2)
                continue
            if self.is_in_main():
                self.ui_current = self.page_main
                return
        raise GameStuckError('Resonance did not reach the main page after login')

    def transit_encounter_target(self):
        """Locate the safe guard encounter option in the current frame."""
        return transit_encounter_target(self.device.image)

    def transit_parked_target(self):
        """Locate enabled D in the current stopped transit frame."""
        return transit_parked_target(self.device.image)

    def handle_transit_recovery(self):
        """Resume a restart-interrupted transit without touching return or decoy controls."""
        if self.appear_then_click(ARREST_RESULT, offset=(5, 5), interval=2):
            return True
        if self.appear_then_click(TAP_BLANK_EXIT, offset=(40, 100), similarity=0.80, interval=2):
            return True
        timer = getattr(self, '_transit_recovery_timer', None)
        if timer is None:
            timer = Timer(2)
            self._transit_recovery_timer = timer
        if not timer.reached():
            return False
        target = self.transit_encounter_target()
        name = 'TRANSIT_GUARD_ENCOUNTER'
        allowed = TRANSIT_ENCOUNTER_ALLOWED
        radius = 24
        if target is None:
            target = self.transit_parked_target()
            name = 'TRANSIT_RESUME_D'
            allowed = TRANSIT_D_ALLOWED
            radius = 16
        if target is None:
            return False
        x, y = target
        area = (x - radius, y - radius, x + radius, y + radius)
        if not (allowed[0] <= area[0] and allowed[1] <= area[1]
                and area[2] <= allowed[2] and area[3] <= allowed[3]):
            return False
        if any(_boxes_overlap(area, forbidden) for forbidden in TRANSIT_FORBIDDEN_BOXES):
            return False
        button = Button(area=area, color=(0, 0, 0), button=area, name=name)
        self.device.click(button)  # alas-lint: allow - custom current-frame color/glyph judgment.
        timer.reset()
        return True

    _reward_close_btn = Button(
        area=(580, 680, 700, 712), color=(), button=(580, 680, 700, 712), name='LOGIN_REWARD'
    )

    def handle_reward_popup(self):
        if self.appear_then_click(LOGIN_REWARD, offset=(5, 5), interval=2):
            return True
        if self.appear(LOGIN_REWARD, offset=(30, 140), similarity=0.78, interval=2):
            self.device.click(self._reward_close_btn)
            return True
        if self.appear(BENTO_RESULT_MODAL, offset=(10, 10), similarity=0.75, interval=2):
            self.device.click(BENTO_RESULT_MODAL)
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
        if self.appear_then_click(BENTO_CONFIRM_MODAL, offset=(60, 10), interval=2):
            return True
        return self.appear_then_click(TRADE_ITEMS_MODAL, offset=offset, interval=2)

    def ui_additional(self):
        if (self.handle_reward_popup() or self.handle_operation_victory()
                or self.handle_shop_preview() or self.handle_trade_report() or self.handle_trade_modal()):
            return True
        return any(
            self.appear_then_click(button, offset=(5, 5), interval=2)
            for button in (LOGIN_DAILY_CHECK_IN, LOGIN_START, LOGIN_ENTER, PREP_REWARD_MODAL, DISPATCH_REPORT)
        )
