"""每日探索 of 交错战线 (Cross Core).

The explore page opens from 「出击」 on the lobby, then 「每日探索」. It is two
columns: the left rail holds three category cards (资源采集 / 芯片嵌合 / 跃升行动),
the right column first lists the sub items of the chosen category and then the
layers of the chosen sub item. Pressing a layer opens its detail page, whose
bottom left 「扫荡」 leads to the sweep panel.

    大厅出击 → 每日探索 → 类别卡 → 子项 → 层 → 关卡详情 → 扫荡 → 开始战斗
    → 掉落加成提示（使用）→ 扫荡结算（点右下 奖励 标题关掉）→ 大厅

What the 2026-11-08 measurements settled:

1. Which category is open is read from the 8 px golden strip on its left edge:
   the selected card gets a golden band, the other two do not. The three bands
   are listed in `CATEGORY`, and `gold_pixels()` over such a narrow band can not
   be hit by the card art behind it.
2. Only 资源采集 exports its four sub item names as templates. 芯片嵌合 (8 items)
   and 跃升行动 (3 items) have no text assets, so their sub items are pressed by
   row (`SUB_ROWS`, pure coordinate buttons - never passed to `appear()`).
3. The chip list holds 8 items in 5 rows and the game remembers the scroll
   offset, so every row press first scrolls the list to an end, where the
   mapping is known again. Scrolling only works with a slow drag (0.9 s); a
   400 ms swipe is swallowed (用户实测).
4. The lock icons are the only way to tell whether a layer is unlocked. They are
   found with `find_all()` (a multi-target scan), never with `appear()`. Only
   the **highest unlocked** layer is swept - 用户要求「只扫最高层」.
5. The sweep result is closed through the golden 「奖励」 title at the bottom
   right. Tapping the middle of the black area does nothing, and the item icons
   open an item detail page instead (用户实测).
"""

from module.base.button import Button
from module.crosscore.assets import (EXPLORE_CAT_ASCEND, EXPLORE_CAT_CHIP,
                                     EXPLORE_CAT_RESOURCE, EXPLORE_CONFIRM,
                                     EXPLORE_DAILY, EXPLORE_DIALOG_OUTSIDE,
                                     EXPLORE_DROP, EXPLORE_LOCK,
                                     EXPLORE_LAYER_ROW_1, EXPLORE_LAYER_ROW_2,
                                     EXPLORE_LAYER_ROW_3, EXPLORE_LAYER_ROW_4,
                                     EXPLORE_LAYER_ROW_5, EXPLORE_LAYER_ROW_6,
                                     EXPLORE_NO_FUEL, EXPLORE_RESULT,
                                     EXPLORE_SORTIE,
                                     EXPLORE_START, EXPLORE_SUB_COIN,
                                     EXPLORE_SUB_RELIC, EXPLORE_SUB_ROW_1,
                                     EXPLORE_SUB_ROW_2, EXPLORE_SUB_ROW_3,
                                     EXPLORE_SUB_ROW_4, EXPLORE_SUB_ROW_5,
                                     EXPLORE_SUB_SKILL, EXPLORE_SUB_TECH,
                                     EXPLORE_SWEEP)
from module.crosscore.crosscore_ui import CrosscoreUI
from module.crosscore.page import page_main
from module.crosscore.utils import (find_all, gold_pixels, image_diff,
                                    template_of)
from module.logger import logger

# Rows of the right column. Sub items: centre y = 160 + 108 x (i-1), x = 1000.
SUB_X, SUB_Y0, SUB_PITCH = 1000, 160, 108
# Scrolled to the bottom the list clamps with the last card at y 540, i.e. 52 px
# above the row grid above (measured 2026-11-08: pressing 592 does nothing).
SUB_LAST_Y = 540
# The whole sub item list, used to tell "the list stopped moving" after a drag.
SUB_BAND = (840, 120, 1110, 630)
# Layers: centre y = 275 + 63 x (i-1).
LAYER_Y0, LAYER_PITCH = 275, 63
# The lock icons sit on the right of the layer rows (top y 324 / 387 / 450 / 512).
LAYER_LOCK_REGION = (1040, 250, 1095, 600)

LAYER_ROWS = (EXPLORE_LAYER_ROW_1, EXPLORE_LAYER_ROW_2, EXPLORE_LAYER_ROW_3,
              EXPLORE_LAYER_ROW_4, EXPLORE_LAYER_ROW_5, EXPLORE_LAYER_ROW_6)
SUB_ROWS = (EXPLORE_SUB_ROW_1, EXPLORE_SUB_ROW_2, EXPLORE_SUB_ROW_3,
            EXPLORE_SUB_ROW_4, EXPLORE_SUB_ROW_5)

# Category card and the golden strip on its left edge, which is lit while the
# category is open. The strip is 5 px wide and ~83 px tall for 资源采集 and
# 芯片嵌合, drifting between x 278 and x 300 while the selection animates, so
# their bands hold both ends (2026-11-08, two frames of the same selection).
# The three cards are **not** evenly spaced: the third one starts at y 451 (its
# art at 473~575), and its lit strip sits at x 297~309, y 433~594 (2026-11-09
# error frame). The old band (266, 370, 312, 465) only caught its top 34 rows
# and read 100 gold pixels, below the threshold, so 跃升行动 was reported as
# "did not highlight" while it was selected all along.
CATEGORY = {
    'resource': (EXPLORE_CAT_RESOURCE, (266, 150, 312, 245)),
    'chip': (EXPLORE_CAT_CHIP, (266, 260, 312, 355)),
    'ascend': (EXPLORE_CAT_ASCEND, (266, 390, 330, 620)),
}

# A selected strip has 255~548 gold pixels, an idle one 10~46 (the glow of the
# neighbouring card and the bracket line leak into the band). 120 sits in the
# middle of the gap.
CATEGORY_GOLD_PIXELS = 120

# 资源采集 is the only category whose sub items have templates.
RESOURCE_SUB = {'技能磨砺': EXPLORE_SUB_SKILL, '星币开采': EXPLORE_SUB_COIN,
                '技术分析': EXPLORE_SUB_TECH, '荒墟拾遗': EXPLORE_SUB_RELIC}

# 芯片嵌合 is the only list longer than one screen (8 items in 5 rows).
CHIP_COUNT = 8

# Option name -> (category, 0-based index inside the category).
OPTIONS = {
    '技能磨砺': ('resource', 0), '星币开采': ('resource', 1),
    '技术分析': ('resource', 2), '荒墟拾遗': ('resource', 3),
    '鼓舞嵌合': ('chip', 0), '光枢嵌合': ('chip', 1), '注刘嵌合': ('chip', 2),
    '链接嵌合': ('chip', 3), '体魄嵌合': ('chip', 4), '侵蚀嵌合': ('chip', 5),
    '迅刃嵌合': ('chip', 6), '矛盾嵌合': ('chip', 7),
    '自然跃升': ('ascend', 0), '人造跃升': ('ascend', 1), '生命跃升': ('ascend', 2),
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
        category, index = OPTIONS[name]
        logger.info(f'Explore <{name}>, category {category}, index {index}')

        if not self.explore_enter() \
                or not self.explore_open_category(category) \
                or not self.explore_pick_sub(name, category, index) \
                or not self.explore_pick_layer() \
                or not self.explore_sweep():
            logger.warning('Explore failed, retry in 15 minutes')
            # The failure leaves the game on the explore page, which is not a
            # registered Page: the next task's `ui_get_current_page()` would
            # time out and die with GamePageUnknownError (2026-11-09 real run).
            self.back_to_main()
            self.config.task_delay(minute=15)
            return

        self.back_to_main()
        # Explore entries reset with the daily server update.
        self.config.task_delay(server_update=True)

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

    def explore_pick_sub(self, name, category, index):
        """
        Select one sub item of the open category.

        Args:
            name (str): Option name, for the log.
            category (str): One of the keys of `CATEGORY`.
            index (int): 0-based index inside the category.

        Returns:
            bool: If the layer list (its 「固定掉落」 title) is on screen.
        """
        logger.hr(name, level=2)
        if category == 'resource':
            return self.explore_pick_sub_button(RESOURCE_SUB[name])
        return self.explore_pick_sub_row(category, index)

    def explore_pick_sub_button(self, button):
        """
        Press a sub item that has a template (资源采集 only).

        Args:
            button (Button): Sub item to press.

        Returns:
            bool: If the layer list showed up.
        """
        for _ in self.loop(timeout=30):
            if self.appear(button, offset=(20, 20), interval=2):
                logger.info(f'Press sub item {button.name}')
                self.device.click(button)
                if self.wait_until_appear(EXPLORE_DROP, offset=(20, 20), timeout=8):
                    return True

        logger.warning(f'Sub item {button.name} did not open the layer list')
        return False

    def explore_pick_sub_row(self, category, index):
        """
        Press a sub item that has no template (芯片嵌合 / 跃升行动), by row.

        The chip list is 8 items in 5 rows and the game remembers the scroll
        offset it was left at, so the list is scrolled to a known end before the
        press:

        - items 1~5: scrolled to the top, row centres are 160 + 108 x (i-1);
        - items 6~8: scrolled to the bottom, the last card is clamped at
          y 540 and the rows count upwards in 108 px steps from there.

        Args:
            category (str): `chip` or `ascend`.
            index (int): 0-based index inside the category.

        Returns:
            bool: If the layer list showed up.
        """
        self.explore_scroll(top=True)
        if index < len(SUB_ROWS):
            button = SUB_ROWS[index]
        else:
            # Beyond the fifth item the list is scrolled to its end. The last
            # card does not land on the row grid then, so the click is built
            # from the clamped position and counted upwards instead.
            self.explore_scroll(top=False)
            y = SUB_LAST_Y - SUB_PITCH * (CHIP_COUNT - 1 - index)
            button = Button(area=(SUB_X - 6, y - 6, SUB_X + 6, y + 6),
                            color=(0, 0, 0),
                            button=(SUB_X - 6, y - 6, SUB_X + 6, y + 6),
                            name=f'EXPLORE_SUB_{index}')

        for _ in self.loop(timeout=30):
            # The opened category card is highlighted, and the template of the
            # card is the idle one: guarding on it drops the press once the
            # category is selected. Any of the three cards is the guard instead.
            if self.explore_page_appear():
                logger.info(f'Press sub item {category} index {index}')
                self.device.click(button)  # alas-lint: allow - 子项行没有模板，上面的类别卡 appear() 是守卫
                if self.wait_until_appear(EXPLORE_DROP, offset=(20, 20), timeout=8):
                    return True

        logger.warning(f'Sub item {category} index {index} did not open the layer list')
        return False

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
        Open the highest unlocked layer of the chosen sub item.

        A layer that was never cleared carries a lock on the right of its row.
        The locks are found with `find_all()` (a multi-target scan; `appear()`
        would answer for one row only), and a row counts as locked when a lock
        top sits within 8 px of 259 + 63 x (i-1) - the lock template is 28 px
        high and starts at the row top.

        Candidates are the unlocked rows from the bottom of the screen up, so
        the highest unlocked layer is the first one tried (用户要求「只扫最高层」).
        A locked row is never pressed. When the sub item has fewer than six
        layers the rows below the last one are empty: pressing one does not
        leave the page, so the loop falls through to the next candidate.

        Pages:
            in: explore page, layer list
            out: layer detail page

        Returns:
            bool: If a layer detail page is on screen.
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

        for row in range(len(LAYER_ROWS), 0, -1):
            if row in locked:
                continue
            if self.appear(EXPLORE_DROP, offset=(20, 20)):
                logger.info(f'Press layer {row}')
                self.device.click(LAYER_ROWS[row - 1])  # alas-lint: allow - 层行没有模板，EXPLORE_DROP 是守卫
                if self.wait_until_appear(EXPLORE_SWEEP, offset=(20, 20), timeout=5):
                    logger.info(f'Layer {row} is open')
                    return True

        logger.warning('No unlocked layer to sweep')
        return False

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
