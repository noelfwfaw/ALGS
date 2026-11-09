"""交错基地 (Cross Core base).

The base is a map with three things worth doing, in the order the user plays
them:

1. 领取素材 —— the teal claim icon (`BASE_CLAIM`) pops up on the base map when a
   facility has something to collect. Press it, close the 「获得物品」 popup.
   No icon means nothing to collect, not an error.
2. 驻员换班 —— every facility opens the same 预设 panel. The active team shows
   the green 「工作中」, the other one shows the yellow 「使用」. Every run of
   this task switches all facilities to the other team: the schedule itself is
   the rotation, so a manual "run now" switches too. The team that ends up on
   duty decides, through its configured hours, when the task comes back.
3. 订单库 —— scan the own library for 构建订单, then walk every friend with the
   right arrow; the right arrow on the last friend goes back to the own
   library and ends the block. A 构建订单 costs 10 稀有黑匣; when the card says
   「资源暂缺」, the 制作素材 page is opened first to craft what is missing.

Crafting numbers (game UI, 2026-11-08):

    1 稀有黑匣 = 280 原型石英 + 40 压电石英 + 40 熔融石英
    1 压电石英 = 8 原型石英
    1 熔融石英 = 8 原型石英

so the missing 压电/熔融 are crafted first, then the black boxes.

The 获得物品 popup (page_3 / page_14 / page_17 of the spec) is the same one the
boot already knows, so `handle_item_popup()` is reused as the global popup
state machine instead of adding a third template.
"""

import time

from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import crop
from module.crosscore.assets import (BASE_CLAIM, BASE_ORDER, BASE_STAFF,
                                     CRAFT_BACK,
                                     CRAFT_BLACKBOX, CRAFT_CONFIRM, CRAFT_FUSED,
                                     CRAFT_MAX, CRAFT_MIN, CRAFT_PIEZO, CRAFT_PLUS,
                                     CRAFT_RESULT, E_5_1,
                                     MAIN_GOTO_BASE, ORDER_BUILD,
                                     ORDER_CONFIRM, ORDER_CONFIRM_TITLE,
                                     ORDER_CRAFT, ORDER_FRIEND, ORDER_LACK,
                                     ORDER_NEXT, ORDER_SOLD, ORDER_VISIT,
                                     PRESET_USE_1, PRESET_USE_2,
                                     PRESET_WORKING_1, PRESET_WORKING_2,
                                     STAFF_BACK, STAFF_PRESET)
from module.crosscore.crosscore_ui import CrosscoreUI
from module.crosscore.page import page_main
from module.crosscore.utils import (find_all, has_template, image_diff,
                                    template_of)
from module.logger import logger
from module.ocr.ocr import Digit

# OCR areas, measured on the spec screenshots (2026-11-08).
# A single digit's glyph is only ~11 px wide (bbox 1059,216-1070,259), and a
# two-digit amount extends to the LEFT of it. The old (1050,...) window clipped
# the tens digit: on 2026-11-10 真机 `99` came back as `39` and `80` as `30`,
# while `50` and `18` were correct. Widened to hold both digits; verified
# offline against the one-digit screenshot and a two-digit mock. The amount is
# still only a sanity gate, batching is driven by the stock (see craft_item).
OCR_CRAFT_COUNT = (1015, 195, 1115, 280)
# 稀有黑匣 owned count in the order library's left 制作素材 panel. The craft
# page's number under the cube is the recipe output (always 1), not the stock
# (2026-11-08 真机), so the count is read before leaving the library.
OCR_BLACKBOX_OWN = (128, 380, 158, 410)
OCR_PIEZO_HELD = (533, 640, 582, 668)
OCR_FUSED_HELD = (648, 640, 712, 668)

# Order-card geometry, relative to the top-left of `ORDER_BUILD`'s template
# (which is the order card's reward icon, padded by 6 px). Measured on
# page_15: need "×10" at (1026,590), 资源暂缺 at (1063,600), 交付 at
# (992,648)-(1160,669).
CARD_NEED = (-66, 146, -26, 170)
CARD_LACK = (-70, 130, 80, 200)
CARD_SOLD = (-70, 67, 57, 102)
CARD_DELIVER = (-100, 204, 68, 225)

# Eight cards, four per row. The left 制作素材 panel starts at x=20, so the
# search starts far enough right not to read its 稀有黑匣 icon.
ORDER_GRID = (270, 60, 1270, 640)

# One 驻员预设 icon column on the staff page, four rows visible at a time.
STAFF_COLUMN = (970, 80, 1060, 645)

# Black boxes needed by one 构建订单, and the recipe of one black box.
BLACKBOX_PER_ORDER = 10
PIEZO_PER_BLACKBOX = 40
FUSED_PER_BLACKBOX = 40
# 合成对话框一次最多合成 99 份（游戏硬上限，2026-11-10 用户确认）。
# 一张订单缺 10 个黑匣时要补 10*40 = 400 个材料，必须拆成 99/99/99/99/4 五批。
CRAFT_MAX_PER_BATCH = 99
# 材料见底时「>|」每批只给几份，拆批会变多；给个上限防止无限点空按钮。
CRAFT_MAX_BATCHES = 16


class CrosscoreBase(CrosscoreUI):
    """
    Base task of 交错战线: claim materials, rotate the staff, buy orders.

    Pages:
        in: page_main
        out: page_main
    """

    def run(self):
        """
        Run the three blocks and schedule the next run.

        The wait is decided by 驻员换班: the team that is on duty after this
        run determines when the base is worth visiting again.

        Pages:
            in: page_main
            out: page_main
        """
        logger.hr('交错基地', level=1)
        self.ui_ensure(page_main)

        if not self.base_enter():
            self.config.task_delay(minute=30)
            return

        self.base_claim()
        wait = self.base_staff()
        self.base_order()
        self.back_to_main()

        wait = 60 if wait is None else max(1, int(wait))
        logger.info(f'Next base run in {wait} minutes')
        self.config.task_delay(minute=wait)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def base_enter(self):
        """
        Open the base page from the lobby.

        Returns:
            bool: If the base page is on screen.
        """
        for _ in self.loop(timeout=30):
            if self.handle_item_popup():
                continue
            if self.handle_lobby_popup():
                continue
            if self.appear(BASE_STAFF, offset=(20, 20)):
                # The base map fades in; a click on a moving label is
                # swallowed, and the next screen then looks like "nothing
                # happened" (2026-11-08 真机：驻员页等了 10 秒没出来).
                self.wait_until_still(area=(0, 0, 1280, 720), timeout=3)
                return True
            if self.appear(MAIN_GOTO_BASE, offset=(20, 20), interval=2):
                logger.info('Open the base page')
                self.device.click(MAIN_GOTO_BASE)

        logger.warning('Cannot open the base page')
        return False

    # ------------------------------------------------------------------
    # 1. 领取素材
    # ------------------------------------------------------------------

    def base_claim(self):
        """
        Collect the base materials, one reward popup at a time.

        Pages:
            in: base page
            out: base page
        """
        logger.hr('领取素材', level=2)
        for _ in range(5):
            if self.appear(BASE_CLAIM, offset=(20, 20), interval=2):
                logger.info('Collect base materials')
                self.device.click(BASE_CLAIM)
                if not self.wait_until_appear(E_5_1, offset=(20, 20), timeout=5, settle=2):
                    logger.warning('The claim did not raise a reward popup')
                    continue
                self.handle_item_popup()
            else:
                logger.info('No base material to collect')
                return

    # ------------------------------------------------------------------
    # 2. 驻员换班
    # ------------------------------------------------------------------

    def base_staff(self):
        """
        Swap the staff of every facility on every run.

        The shift is driven by the schedule instead of a local timer: running
        this task *is* the switch. The preset panel is only read to know which
        team each facility has been using until now, then the other team is put
        to work. This way the user controls the rotation entirely through the
        next-run time of the task, and a manual "run now" also switches the
        staff instead of being ignored until some timer runs out (2026-11-08
        用户要求：只要运行了这个任务就应该换班).

        Returns:
            float | None: Minutes to the next visit, None if the staff page
                was not readable.
        """
        logger.hr('驻员换班', level=2)
        opened = False
        for _ in range(3):
            if self.appear(BASE_STAFF, offset=(20, 20), interval=1):
                logger.info('Open the 驻员 page')
                self.device.click(BASE_STAFF)
            if self.wait_until_appear(STAFF_PRESET, offset=(30, 260), timeout=6, settle=2):
                opened = True
                break
        if not opened:
            logger.warning('The 驻员 page did not open')
            return None

        now = time.time()
        # Team that was on duty when the run started, and the one this run puts
        # to work. Both are read from the first readable panel; every facility is
        # then moved to `target`, which also leaves alone a facility that already
        # happens to be there.
        plan_team = 0
        target = 0
        on_target = False

        # The list shows about four facilities at a time, six in total, and a
        # scroll moves it by roughly two rows, so the next screen repeats rows
        # from the previous one. Two rules keep every preset covered:
        #
        # - One preset per loop iteration, with the icon positions re-read on
        #   that frame. Opening a preset selects/expands its row and pushes the
        #   rows below it down; a snapshot reused for the next clicks became
        #   stale and the third click landed between two rows (2026-11-08 真机：
        #   第三个没点中).
        # - Every visible preset is read on every screen instead of
        #   de-duplicating by absolute y, which dropped a row that scrolled
        #   into an already handled position (六个预设只点开了五个).
        index = 0
        for _ in self.loop(timeout=180):
            points = self.staff_presets()
            if index >= len(points):
                # This screen is done, move the list and read the next one.
                index = 0
                if not self.staff_scroll():
                    break
                continue

            x, y = points[index]
            index += 1
            if not self.staff_open_preset(x, y):
                logger.warning('The 预设 panel did not open')
                continue

            active = self.preset_team()
            if not active:
                logger.warning('Cannot read which team is working')
                self.preset_panel_close()
                continue

            if not plan_team:
                plan_team = active
                target = 3 - plan_team
                logger.info(f'Team {plan_team} has been working, switch to team {target}')

            if active == target:
                # Already on the target team, nothing to click for this one.
                on_target = True
                self.preset_panel_close()
                continue

            use = PRESET_USE_2 if target == 2 else PRESET_USE_1
            if self.appear(use, offset=(20, 20), interval=2):
                logger.info(f'Switch to team {target}')
                self.device.click(use)
                # 使用 is applied at once and the panel closes itself, so the
                # green 「工作中」 can only be read after reopening the preset
                # (2026-11-08 真机：点完面板直接消失，等绿色标签等了 5 秒都是超时).
                self.preset_panel_wait_closed()
                if self.staff_open_preset(x, y) and self.preset_team() == target:
                    on_target = True
                else:
                    logger.warning(f'Team {target} did not start working')
            self.preset_panel_close()

        if not plan_team:
            logger.warning('No preset could be read, keep the current schedule')
            wait = 30
        else:
            wait = self.team_hours(target) * 60
            self.state_set(Team=target, LastSwitch=int(now))
            if on_target:
                logger.info(f'Team {target} is working now, come back in {wait:.0f} minutes')
            else:
                logger.warning(f'No facility switched to team {target}, come back in {wait:.0f} minutes')

        if self.appear(STAFF_BACK, offset=(20, 20), interval=2):
            self.device.click(STAFF_BACK)
            self.wait_until_disappear(STAFF_PRESET, offset=(30, 260), timeout=5)

        return wait

    def team_hours(self, team):
        """Configured working hours of a team."""
        if team == 1:
            return float(self.config.CrosscoreBase_Team1Hours)
        return float(self.config.CrosscoreBase_Team2Hours)

    def state_get(self):
        """
        Hidden task state, read from `Storage.Storage`.

        Args:
            None

        Returns:
            dict: Team and LastSwitch, empty on the first visit.
        """
        return self.config.cross_get('CrosscoreBase.Storage.Storage', {}) or {}

    def state_set(self, **kwargs):
        """
        Write back to `Storage.Storage`.

        Keys invented on the fly do not survive: `config_update()` rebuilds the
        config from the argument schema on every load and drops unknown args,
        so `cross_set('CrosscoreBase.CrosscoreBaseLastSwitch', ...)` was gone by
        the next run and the shift timer restarted every time (2026-11-08 真机).
        The `Storage` group is the one hidden dict every task has.
        """
        state = self.state_get()
        state.update(kwargs)
        self.config.cross_set('CrosscoreBase.Storage.Storage', state)

    def preset_panel_open(self):
        """
        Whether the 预设 panel is drawn.

        One of the two rows always shows 使用 and the other 工作中, so any of
        the four templates means the panel is up. Offsets are kept small: the
        same green text is on both rows, and a large offset would match the
        other row.
        """
        return self.appear(PRESET_WORKING_1, offset=(20, 20)) \
            or self.appear(PRESET_WORKING_2, offset=(20, 20)) \
            or self.appear(PRESET_USE_1, offset=(20, 20)) \
            or self.appear(PRESET_USE_2, offset=(20, 20))

    def preset_team(self):
        """
        Which preset is working, read from the green 「工作中」.

        Returns:
            int: 1 or 2, 0 when neither row is marked (empty preset).
        """
        if self.appear(PRESET_WORKING_2, offset=(20, 20)):
            return 2
        if self.appear(PRESET_WORKING_1, offset=(20, 20)):
            return 1
        return 0

    def preset_panel_wait_closed(self):
        """
        Wait until the panel closed itself after 使用 was pressed.

        Pressing 使用 applies the switch and closes the panel, so there is no
        separate close click and no green label to watch while it is going away.

        Returns:
            bool: If the panel is gone.
        """
        absent = 0
        for _ in self.loop(timeout=5):
            if self.preset_panel_open():
                absent = 0
            else:
                absent += 1
                if absent >= 2:
                    self.wait_until_still(area=(0, 80, 1280, 645), timeout=2)
                    return True
        logger.warning('The 预设 panel did not close after 使用')
        return False

    def preset_panel_close(self):
        """
        Close the panel by pressing outside it, then wait until it is really gone.

        The 工作中/使用 templates vanish during the close animation, but the
        dimmed modal keeps eating clicks for a moment longer. Returning on the
        first frame without a template made the next 预设 click disappear
        (2026-11-08 真机：(1012,531) 点开后 6 秒没反应), so two consecutive
        absent frames and a still page are required.
        """
        self.device.click(self.tap_point((640, 690), 'PRESET_CLOSE'))  # alas-lint: allow - the empty bottom edge of a panel that is known to be open, there is no template to match
        absent = 0
        for _ in self.loop(timeout=5):
            if self.preset_panel_open():
                absent = 0
            else:
                absent += 1
                if absent >= 2:
                    self.wait_until_still(area=(0, 80, 1280, 645), timeout=2)
                    return True
        logger.warning('The 预设 panel is still open')
        return False

    def staff_presets(self):
        """
        Visible 预设 icons of the facility list, top to bottom.

        Returns:
            list[tuple[int, int]]: Icon top-left corners.
        """
        points = find_all(self.device.image, template_of(STAFF_PRESET), STAFF_COLUMN, similarity=0.86)
        rows = []
        for x, y in points:
            if all(abs(y - ry) > 30 for _, ry in rows):
                rows.append((x, y))
        return rows

    def staff_open_preset(self, x, y):
        """
        Click a 预设 icon and wait until its panel is fully drawn.

        The panel fades in, so reading the team on the first frame that matches
        read a half-drawn panel and the roster looked like it was clicked at
        random (2026-11-08 真机：换班点得太快像乱点). Two consecutive matching
        frames are required, like a popup.

        Args:
            x, y: Top-left corner of the matched `STAFF_PRESET`.

        Returns:
            bool: If the panel is up.
        """
        if self.preset_panel_open():
            self.preset_panel_close()
        # Six presets mean twelve alternating clicks on two points, which is
        # exactly what the anti-stuck guard counts as a loop
        # (GameTooManyClickError, 2026-11-08 真机). Every open is a deliberate
        # new action, so the history is cleared first.
        self.device.click_record_clear()
        # Template top-left is the padded area, the icon centre is (26, 25).
        self.device.click(self.tap_point((x + 26, y + 25), 'STAFF_PRESET'))  # alas-lint: allow - the point comes from find_all() on this frame, there is no single Button to guard
        present = 0
        for _ in self.loop(timeout=6):
            if self.preset_panel_open():
                present += 1
                if present >= 2:
                    return True
            else:
                present = 0
        return False

    def staff_scroll(self):
        """
        Scroll the facility list by one screen.

        Returns:
            bool: False when the list did not move (reached the bottom).
        """
        before = crop(self.device.image, (0, 80, 1280, 645))
        self.device.swipe_vector((0, -320), box=(400, 180, 700, 600), name='STAFF_SCROLL')
        self.wait_until_still(area=(0, 80, 1280, 645), timeout=3)
        after = crop(self.device.image, (0, 80, 1280, 645))
        moved = float(abs(before.astype('int16') - after.astype('int16')).mean()) > 2
        return moved

    # ------------------------------------------------------------------
    # 3. 订单库
    # ------------------------------------------------------------------

    def base_order(self):
        """
        Buy 构建订单 in the own library and in every friend's library.

        Pages:
            in: base page
            out: own order library
        """
        logger.hr('订单库', level=2)
        if self.appear(BASE_ORDER, offset=(20, 20), interval=2):
            self.device.click(BASE_ORDER)
        else:
            logger.info('No 订单库 entry on the base page')
            return
        if not self.wait_until_appear(ORDER_FRIEND, offset=(20, 20), timeout=10, settle=2):
            logger.warning('The order library did not open')
            return
        # The grid slides in; a 交付 click on a moving card is swallowed and the
        # next screen looks exactly like "the order is not deliverable".
        self.wait_until_still(area=ORDER_GRID, timeout=3)

        crafts = 2
        for _ in range(2):
            state = self.order_scan()
            if state != 'lacked' or crafts <= 0:
                break
            crafts -= 1
            if not self.craft_missing():
                break
            if not self.order_reenter():
                break

        self.order_friends(crafts)

    def order_scan(self):
        """
        Deliver every 构建订单 card on the current library page.

        A delivered card can stay on screen with 日限 0/1, so the delivered
        positions are remembered and skipped when the page is scanned again.

        Returns:
            str: 'empty' (nothing left), 'lacked' (needs crafting), or
                'stuck' (the 交付 click did not raise the confirm dialog).
        """
        delivered = []
        for _ in range(8):
            if self.handle_item_popup():
                # The popup sits on top of the library; wait for the library
                # itself instead of the own-library only 选择好友 button, which
                # is absent on a friend's page.
                self.order_library_wait()
                continue

            points = find_all(self.device.image, template_of(ORDER_BUILD), ORDER_GRID, similarity=0.86)
            points = [p for p in points
                      if all(abs(p[0] - x) > 30 or abs(p[1] - y) > 30 for x, y in delivered)]
            if not points:
                return 'empty'

            x, y = points[0]
            # A delivered card stays on the page with a 「告罄」 band and a grey
            # 交付 bar. Clicking it does nothing but burn the retry window.
            sold = self.card_area(CARD_SOLD, x, y)
            if has_template(self.device.image, template_of(ORDER_SOLD), sold, similarity=0.85):
                logger.info('The construction order is 告罄, skip it')
                delivered.append((x, y))
                continue

            lack = self.card_area(CARD_LACK, x, y)
            # 0.80: the red 「资源暂缺」 sits on a different background on every
            # card, and the exact-text match measured 0.84 on the live library.
            if has_template(self.device.image, template_of(ORDER_LACK), lack, similarity=0.80):
                self.pending_need = self.read_number(
                    self.card_area(CARD_NEED, x, y), (255, 255, 255), 170, 'ORDER_NEED')
                logger.info(f'Construction order needs {self.pending_need} black boxes, craft first')
                return 'lacked'

            deliver = self.tap_area(self.card_area(CARD_DELIVER, x, y), 'ORDER_DELIVER')
            logger.info('Deliver a construction order')
            self.device.click(deliver)  # alas-lint: allow - the card is a match found by find_all() on this frame, there is no single Button to guard with
            delivered.append((x, y))
            if not self.order_confirm(deliver):
                return 'stuck'

        return 'empty'

    def order_confirm(self, deliver):
        """
        Press 确定 on 「是否确认提交订单？」 and close the reward popup.

        The first 交付 press is repeated while the confirm dialog is not up.
        2026-11-08 真机：the library slides in, the press lands on a moving
        card and is swallowed; without the retry the card is written off as
        undeliverable for the whole run.

        Args:
            deliver (Button): The card's 交付 bar, pressed again on retry.

        Returns:
            bool: If the order went through.
        """
        clicked = False
        done = False
        retry = Timer(4).start()
        # After 确定 the reward popup takes a moment to be drawn. Leaving before
        # it shows leaves the 获得物品 popup on top of the next screen: the
        # friend list then never opens and the whole friend walk is skipped
        # (2026-11-08 真机).
        popup_wait = None
        retries = 0
        for _ in self.loop(timeout=20):
            if self.handle_item_popup():
                done = True
            elif self.appear(ORDER_CONFIRM_TITLE, offset=(20, 20)):
                if self.appear(ORDER_CONFIRM, offset=(20, 20), interval=2):
                    self.device.click(ORDER_CONFIRM)
                    clicked = True
                    popup_wait = Timer(3).start()
                    retry.reset()
            elif clicked and popup_wait.reached():
                done = True
            elif not clicked and retry.reached() and retries < 2:
                retries += 1
                retry.reset()
                logger.info('No confirm dialog, press 交付 again')
                self.device.click(deliver)  # alas-lint: allow - the same card found by find_all(), pressed again after a swallowed click
            if done:
                return True

        logger.warning('The 交付 click did not raise the confirm dialog')
        return False

    def friend_list_enter(self):
        """
        Open the friend list, retrying if a late reward popup covers it.

        Returns:
            bool: If ORDER_VISIT is on screen.
        """
        for _ in range(2):
            if self.handle_item_popup():
                continue
            if self.appear(ORDER_FRIEND, offset=(20, 20), interval=2):
                logger.info('Open the friend list')
                self.device.click(ORDER_FRIEND)
            if self.wait_until_appear(ORDER_VISIT, offset=(20, 20), timeout=8, settle=2):
                return True
        return False

    def order_friends(self, crafts):
        """
        Walk the friends with the right arrow until it drops us back home.

        Args:
            crafts (int): How many times a missing-material craft may be done.
        """
        if not self.friend_list_enter():
            logger.info('No friend to visit')
            self.device.click(self.tap_point((640, 690), 'FRIEND_LIST_CLOSE'))  # alas-lint: allow - empty area below the friend list, there is no template to match
            return

        if self.appear(ORDER_VISIT, offset=(20, 20), interval=2):
            self.device.click(ORDER_VISIT)
        if not self.wait_until_appear(ORDER_NEXT, offset=(20, 20), timeout=10, settle=2):
            logger.warning('The friend order library did not open')
            return

        unchanged = 0
        for _ in self.loop(timeout=300):
            state = self.order_scan()
            if state == 'lacked' and crafts > 0:
                crafts -= 1
                if not self.craft_missing():
                    return
                # 2026-11-08 真机：the 制作素材 page returns to the same order
                # library, not to the friend list (page_10 -> page_9 in the
                # spec). Waiting for ORDER_VISIT here timed out and aborted the
                # whole friend walk, so just rescan the page we came back to.
                continue

            # No `interval` here: the arrow click sets an interval timer, and a
            # cached False two seconds later was read as "back to our own
            # library" after the very first friend (2026-11-08 真机).
            if self.appear(ORDER_NEXT, offset=(20, 20)):
                before = crop(self.device.image, ORDER_GRID)
                # Each press opens the next friend, so the same button is
                # pressed on purpose more than ten times in a row. Without this
                # the device's "too many clicks" guard aborts the walk.
                self.device.click_record_clear()
                self.device.click(ORDER_NEXT)
                # Wait for the next friend's library to be drawn. `wait_until_still`
                # alone returned during a pause in the slide, and the arrow was
                # then read as absent while the page was still being replaced.
                self.wait_until_appear(ORDER_NEXT, offset=(20, 20), timeout=5, settle=2)
                after = crop(self.device.image, ORDER_GRID)
                if before.shape == after.shape and image_diff(before, after) < 1:
                    unchanged += 1
                    logger.warning('The friend library did not change')
                    if unchanged >= 3:
                        logger.warning('The friend walk is stuck, stop here')
                        return
                else:
                    unchanged = 0
            else:
                logger.info('Back to the own order library')
                return

    def order_reenter(self):
        """
        Make sure an order library is on screen after crafting.

        2026-11-08 真机：离开 制作素材 page 后回到的是原来的订单库
        (page_10 -> page_9 in the spec), where 选择好友 is still visible. The
        friend list branch is kept for the case the game drops us on page_8.

        Returns:
            bool: If an order library is on screen.
        """
        return self.order_library_wait()

    def order_library_wait(self):
        """
        Wait until an order library is drawn, re-entering a friend if needed.

        `craft_back()` only proves the craft page is gone. The order library
        fades in behind it, and a scan taken during that fade finds neither a
        card nor the right arrow, which used to be read as "the friend walk is
        over" and ended the whole base task right after crafting
        (2026-11-08 真机：合成后直接点了左上角主页按钮).

        Returns:
            bool: If an order library (own or friend) is on screen.
        """
        for _ in self.loop(timeout=12):
            # The friend list also shows 选择好友, so ORDER_FRIEND alone would
            # report "library on screen" while the list is still open. VISIT
            # only exists on that list, so it is checked first.
            if self.appear(ORDER_VISIT, offset=(20, 20), interval=2):
                logger.info('Re-enter the friend order library')
                self.device.click(ORDER_VISIT)
                continue
            if self.appear(ORDER_NEXT, offset=(20, 20)) or self.appear(ORDER_FRIEND, offset=(20, 20)):
                return True

        logger.warning('Cannot get back to the order library')
        return False

    # ------------------------------------------------------------------
    # Crafting
    # ------------------------------------------------------------------

    def craft_missing(self):
        """
        Craft what is missing for the construction order on screen.

        Returns:
            bool: If the craft page was opened and left again.
        """
        need = getattr(self, 'pending_need', 0) or BLACKBOX_PER_ORDER
        # The craft page's cube carries the recipe output, so stock is read on
        # the library page, before 制作素材 is opened.
        held = self.read_number(OCR_BLACKBOX_OWN, (240, 240, 240), 150, 'BLACKBOX')
        logger.info(f'Craft materials for {need} black boxes, have {held}')
        # The library is still fading in when the first lacked card is handled,
        # and a press swallowed by that fade wasted the whole order
        # (2026-11-08 真机), so the same button is pressed again until the page
        # really opens.
        opened = False
        for _ in range(3):
            if self.appear(ORDER_CRAFT, offset=(20, 20), interval=2):
                self.device.click(ORDER_CRAFT)
            if self.wait_until_appear(CRAFT_BLACKBOX, offset=(20, 20), timeout=5, settle=2):
                opened = True
                break
        if not opened:
            logger.warning('The craft page did not open')
            return False

        missing = max(0, need - held)
        logger.info(f'Black boxes: have {held}, need {need}, craft {missing}')
        if missing <= 0:
            return self.craft_back()

        piezo = self.read_short_number(OCR_PIEZO_HELD, 'PIEZO')
        fused = self.read_short_number(OCR_FUSED_HELD, 'FUSED')
        piezo_need = missing * PIEZO_PER_BLACKBOX
        fused_need = missing * FUSED_PER_BLACKBOX
        logger.info(f'Piezo {piezo}/{piezo_need}, fused {fused}/{fused_need}')

        # Drive the two raw materials by their real stock, not by the amount
        # OCR'd inside the craft dialog (2026-11-10 真机: nine 99-piece batches
        # were made for a 353 gap because the dialog kept reporting 39).
        if piezo < piezo_need:
            self.craft_item(CRAFT_PIEZO, piezo_need - piezo,
                            stock=(OCR_PIEZO_HELD, 'PIEZO', piezo_need, piezo))
        if fused < fused_need:
            self.craft_item(CRAFT_FUSED, fused_need - fused,
                            stock=(OCR_FUSED_HELD, 'FUSED', fused_need, fused))
        # The black box stock is on the order library, not on the craft page,
        # so this one still batches on the dialog amount (usually one batch).
        self.craft_item(CRAFT_BLACKBOX, missing)

        return self.craft_back()

    def craft_item(self, entry, count, stock=None):
        """
        Craft `count` of one item, splitting into batches of at most 99.

        Args:
            entry (Button): Item cell on the craft page.
            count (int): How many to craft in total.
            stock (tuple | None): (ocr_area, name, need, baseline) of the
                held amount on the 制作素材 page. `baseline` is what
                craft_missing() read before crafting. When given, the
                remaining amount is recomputed from the real stock before
                every batch.

        ❗游戏一次最多合成 99 份（`CRAFT_MAX_PER_BATCH`）。一张订单缺 10 个黑匣
          时要补 10 × 40 = 400 个压电/熔融材料，直接连点 399 次「+」又慢又卡在
          99。拆批后每批走完整的「设数量 → 确认 → 结算 → 关框」。
        ❗对话框里的份数读回值**不能拿来驱动拆批**：2026-11-10 真机 `99` 被
          读成 `39`、`80` 被读成 `30`，一个 353 的缺口按「每批 39」开了九批
          99 份，实际合成 800+，用户看到熔融数量早就超了。有 `stock` 时每批
          回到制作素材页重读持有量，达标即停；读回值只用来确认数量非 0，
          不再作为产量记账。
        ❗`left` 只减不增：持有量 OCR 失败返回 0 时也不会把订单放大（R11）。
          持有量连续两轮不增长就停，防止合成没生效还一直点空按钮。
        """
        if count <= 0:
            return True
        logger.info(f'Craft {count} x {entry.name} (max {CRAFT_MAX_PER_BATCH} per batch)')
        left = count
        batch_index = 0
        last_held = None
        while left > 0:
            batch_index += 1
            # 材料见底时游戏每批只肯做一点，别无限循环点空按钮。
            if batch_index > CRAFT_MAX_BATCHES:
                logger.warning(f'Craft {entry.name}: stop after {batch_index - 1} batches, '
                               f'{left} left')
                return False
            if stock is not None:
                area, name, need, baseline = stock
                # The stock labels belong to the 制作素材 page; `entry` being
                # visible is the positive check that the dialog is gone.
                if not self.wait_until_appear(entry, offset=(20, 20), timeout=5):
                    logger.warning(f'{entry.name} is not on the craft page, stop')
                    return False
                held = self.read_short_number(area, name)
                # Crafting this material only ADDS to its stock. A reading
                # below the baseline is an OCR failure, not a bigger gap;
                # without this guard a 0 turned a 353 gap into 720 (R11).
                if held < baseline:
                    logger.warning(f'{name} stock read {held} < initial {baseline}, '
                                   f'OCR unreliable, stop')
                    return False
                if held >= need:
                    logger.info(f'{name} stock {held}/{need}, stop crafting')
                    return True
                if last_held is not None and held <= last_held:
                    logger.warning(f'{name} stock did not grow ({last_held} -> {held}), stop')
                    return False
                last_held = held
                left = min(left, need - held)
            target = min(left, CRAFT_MAX_PER_BATCH)
            logger.info(f'Craft batch {batch_index}: up to {target} x {entry.name}, '
                        f'{left} left')
            crafted = self._craft_item_once(entry, target)
            if crafted <= 0:
                logger.warning(f'Craft batch {batch_index} made nothing, stop ({left} left)')
                return batch_index > 1
            if stock is None:
                left -= min(crafted, target)
        return True

    def _craft_item_once(self, entry, count):
        """
        One batch: open recipe, set amount, confirm, collect, close dialog.

        A full 99 batch presses the game's 「>|」 (`CRAFT_MAX`) once instead of
        tapping 「+」 98 times. The amount shown in the dialog is only a
        sanity gate: its OCR confused 9/8 with 3 on 2026-11-10 真机, so the
        caller batches on the real stock instead (see craft_item).

        Args:
            entry (Button): Item cell on the craft page.
            count (int): Upper bound for this batch.

        Returns:
            int: Non-zero amount read back when the batch was confirmed,
                0 when nothing was made / it failed.
        """
        if count <= 0:
            return 0
        if count > CRAFT_MAX_PER_BATCH:
            count = CRAFT_MAX_PER_BATCH
        logger.info(f'Craft up to {count} x {entry.name}')
        if self.appear(entry, offset=(20, 20), interval=2):
            self.device.click(entry)
        else:
            logger.warning(f'{entry.name} is not on the craft page')
            return 0

        if self.wait_until_appear(CRAFT_MIN, offset=(20, 20), timeout=8, settle=2):
            # |< resets the amount to one, so the + count is always the same.
            self.device.click(CRAFT_MIN)
        else:
            logger.warning('The craft dialog did not open')
            return 0

        for _ in self.loop(timeout=3):
            if self.read_number(OCR_CRAFT_COUNT, (255, 255, 255), 180, 'CRAFT_COUNT') == 1:
                break

        if count >= CRAFT_MAX_PER_BATCH and self.appear(CRAFT_MAX, offset=(10, 10)):
            # 「>|」一次到游戏允许的最大份数（材料不够就只给到能做的数）。
            logger.info('Craft amount: press MAX (>|)')
            self.device.click(CRAFT_MAX)
        elif count > 1 and self.appear(CRAFT_PLUS, offset=(20, 20)):
            self.device.multi_click(CRAFT_PLUS, n=count - 1, interval=0.15)

        # Wait for the amount to settle on a non-initial value. `>|` and the
        # `+` presses are drawn over a few frames, so confirming on the first
        # frame that still shows 1 would craft a single piece. The exact value
        # is NOT used to drive batching (see craft_item), so it does not have
        # to reach `count` before we confirm.
        current = 0
        previous = -1
        for _ in self.loop(timeout=2):
            value = self.read_number(OCR_CRAFT_COUNT, (255, 255, 255), 180, 'CRAFT_COUNT')
            current = value
            if value == previous and value > 0 and (value > 1 or count == 1):
                break
            previous = value
        if current <= 0:
            logger.warning('Craft amount unreadable, close the dialog without confirming')
            self.craft_dialog_close()
            return 0
        if current != count:
            logger.info(f'Craft amount read as {current} (asked {count}), '
                        f'not used to drive batches')

        if self.appear(CRAFT_CONFIRM, offset=(20, 20), interval=2):
            self.device.click(CRAFT_CONFIRM)
        rewarded = False
        for _ in self.loop(timeout=8):
            if self.appear(CRAFT_RESULT, offset=(20, 20)):
                # 合成结束的两种结算页（整屏「合成成功」/「获得物品」弹窗）底部
                # 都是「·点击空白处继续·」，点空白关掉它。合成对话框还在下面，
                # 交给后面的返回按钮收尾。
                logger.info('Craft result, press the blank area')
                self.device.click(self.tap_point((640, 560), 'CRAFT_RESULT_CLICK'))
                self.wait_until_appear(CRAFT_PLUS, offset=(20, 20), timeout=5)
                rewarded = True
                break
            if self.handle_item_popup():
                rewarded = True
            if rewarded:
                break
        if not rewarded:
            logger.warning('No reward popup after crafting')

        # ❗对话框没关掉**不等于这批没合成**。2026-11-10 真机：卡顿让返回键
        #   只点一次被吞，`wait_until_disappear(CRAFT_PLUS)` 5 秒超时就把整批
        #   判失败、直接 `Craft batch 3/8 failed, stop`，后面的材料全没做，
        #   还连累 craft_back() 白等 15 秒。现在关框自己重试，且已经确认过
        #   合成就按实际数量记账。
        self.craft_dialog_close()
        return current

    def craft_dialog_close(self):
        """
        Close the craft dialog with the top-left back arrow.

        The dialog sits behind the result sheet, and the arrow is highlighted
        for a moment after it closes; a single press can also be swallowed by
        the fade-in when the game stutters (2026-11-10 真机). Every press is
        judged on a fresh frame: keep pressing while `CRAFT_PLUS` is visible.

        Returns:
            bool: If the dialog disappeared.
        """
        if not self.wait_until_appear(CRAFT_PLUS, offset=(20, 20), timeout=5):
            logger.warning('The craft dialog did not come back after the result')
            return False
        self.device.click_record_clear()
        for _ in self.loop(timeout=12):
            if self.appear(CRAFT_BACK, offset=(20, 20), interval=1.5):
                self.device.click(CRAFT_BACK)
            # ❗用框架原语等消失，不要裸写 `not appear(CRAFT_PLUS)`：合成结算页
            #   淡出的过渡帧什么都匹配不上，那样会误判「对话框已关」（R5）。
            if self.wait_until_disappear(CRAFT_PLUS, offset=(20, 20), timeout=2):
                return True
        logger.warning('The craft dialog did not close')
        return False

    def craft_back(self):
        """
        Leave the craft page and wait until an order library is drawn.

        The back arrow is drawn highlighted right after the dialog was closed
        with it, and does not match its template for a moment; a three-shot
        retry gave up before the highlight faded (2026-11-08 真机). The loop
        therefore runs on time, not on tries, and leaves as soon as a library
        is recognised.

        Returns:
            bool: If the order library came back.
        """
        for _ in self.loop(timeout=15):
            # Positive exit: the library is back (the friend list branch is
            # left to order_library_wait()).
            if self.appear(ORDER_FRIEND, offset=(20, 20)) or self.appear(ORDER_NEXT, offset=(20, 20)):
                break
            if self.appear(CRAFT_BLACKBOX, offset=(20, 20)) and self.appear(CRAFT_BACK, offset=(20, 20)):
                self.device.click_record_clear()
                self.device.click(CRAFT_BACK)
        else:
            logger.warning('The craft page is still there')
        return self.order_library_wait()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def tap_point(point, name='CROSSCORE_TAP'):
        """
        Button for a coordinate tap.

        `Device.click()` only accepts a Button. The staff icons and the order
        cards are located by `find_all()` at run time, so their positions are
        not constants in `assets.py`.
        """
        x, y = point
        return Button(area=(x - 6, y - 6, x + 6, y + 6), color=(0, 0, 0),
                      button=(x - 6, y - 6, x + 6, y + 6), name=name)

    @staticmethod
    def tap_area(area, name='CROSSCORE_TAP'):
        """Button for a rectangle found at run time, such as the 交付 bar."""
        return Button(area=area, color=(0, 0, 0), button=area, name=name)

    @staticmethod
    def card_area(offsets, x, y):
        """Shift a card offset tuple to the matched card position."""
        return (x + offsets[0], y + offsets[1], x + offsets[2], y + offsets[3])

    def read_number(self, area, letter, threshold, name):
        """
        OCR a number with the measured colour of each field.

        Args:
            area (tuple): OCR area on the 1280x720 screenshot.
            letter (tuple): Text colour.
            threshold (int): Binarisation threshold.
            name (str): Detector name for the log.

        Returns:
            int: The number, 0 when OCR fails.
        """
        return int(Digit(area, letter=letter, threshold=threshold, name=name).ocr(self.device.image))

    def read_short_number(self, area, name):
        """
        OCR a 「x/y」 amount that turns red when x is below the requirement.

        The white pass reads the amount when it is sufficient, the red pass
        reads it when the game paints it red; the other pass returns 0 on that
        colour, so the maximum is the real number (2026-11-08 真机：熔融石英
        36/40 是红字，白字 OCR 读成 0).
        """
        white = self.read_number(area, (235, 235, 235), 150, name)
        red = self.read_number(area, (220, 90, 100), 150, name)
        return max(white, red)
