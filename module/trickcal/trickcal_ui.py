"""UI layer of 嘟嘟脸恶作剧 (Trickcal).

Facts read off the emulator / exported screenshots (2026-11-11):

- Package `com.bilibili.trickcalcn`, versionName 1.7.0.
- `wm size` reports 720x1280 portrait, but the client renders landscape.
  Do not work around this in the device layer.
- All 7 frames of the login spec are 1280x720.

Launch: `alas.py:start()` calls `game_ui().app_start()` when switching games,
and `dev_tools/run_task.py` calls it without `--no-boot`. Overriding that
method is what makes a launch actually reach the lobby: the base
`UI.app_start()` only restarts the process, it does not walk the login flow.

Boot loop, rewritten 2026-11-11 after three real runs (shape of
`CrosscoreUI.handle_app_boot()`):

- `device.app_start()` sets `self.image = None`, so this loop takes its own
  screenshot on every frame instead of relying on `loop(skip_first=...)`
  (hard rule 158).
- The title screen rotates its background illustration. The same UI with a
  different character scores only 0.64~0.69 on the "拉动脸颊开始游戏"
  template, below the 0.85 default. The title check uses 0.60; the 5s idle
  fallback uses 0.45 and still requires that same template to match, because
  a blind tap once landed on the return-event page's 「获取」 buttons.
- The lobby is drawn first, then this client replaces the whole screen with
  the return-event panel ~10s later (cold-start probe, 2026-11-11). The loop
  therefore keeps closing popups for a settle window after the first lobby
  frame instead of returning immediately.
- The 7 exported frames are historical snapshots. Only the lobby and the
  popup layouts are stable; do not tighten the title check back to 0.85.

`page_main` and `page_mail` are the registered pages (see page.py). Popups that
cover either of them are handled here so `ui_get_current_page()` can settle.
Without a check button, `ui_goto_main()` would raise GamePageUnknownError and
take the whole scheduler down when `WhenTaskQueueEmpty` is set to `goto_main`.

The reward popup is a reusable component, not a method of this class: see
`module/trickcal/reward.py`. It is composed in through inheritance, so the boot
loop and every task (mailbox claim today) share one implementation and one tap
point.

The shop's **item detail** (the 取消 / 购买 panel, see `shop.py`) is handled here
for the same reason: it is opaque, it covers the 「尊享商店」 title, and it can be
left open by any of the three free packs. `ui_additional()` cancels it, never
buys it, so a leftover panel cannot make `ui_goto()` wait for a page it will
never recognise (151).
"""

from module.base.timer import Timer
from module.config.server import to_package
from module.exception import GameStuckError
from module.logger import logger
from module.trickcal.assets import (COUNTDOWN_POPUP, DOWNLOAD_CONFIRM, DOWNLOAD_DEPART, DOWNLOAD_TITLE,
                                    E_1_1, E_2_1, E_2_2, E_3_1, E_5_1, E_5_2,
                                    E_6_1, E_6_2, EVENT_CUTSCENE_SKIP,
                                    EVENT_GUIDE_CLOSE, EVENT_STORY_CONTINUE,
                                    EVENT_STORY_LEAVE, EVENT_STORY_MENU,
                                    EVENT_STORY_SKIP_CONFIRM, HOME,
                                    SHOP_BUY_CANCEL, SHOP_BUY_CONFIRM)
from module.trickcal.page import (page_adventure, page_class,
                                  page_class_stage, page_costume_pass,
                                  page_doll, page_doll_stage,
                                  page_dungeon,
                                  page_dungeon_bakery,
                                  page_dungeon_bakery_stage,
                                  page_dungeon_candy, page_dungeon_candy_stage,
                                  page_dungeon_clone, page_dungeon_clone_stage,
                                  page_dungeon_crayon,
                                  page_dungeon_crayon_stage, page_dungeon_gold,
                                  page_dungeon_gold_stage, page_event,
                                  page_event_pass, page_event_shop,
                                  page_event_stage, page_event_story,
                                  page_event_task, page_friend, page_mail,
                                  page_main, page_normal_shop, page_order,
                                  page_order_relic, page_pass, page_pvp,
                                  page_pvp_arena, page_pvp_deck, page_shop,
                                  page_task, page_task_weekly)
from module.trickcal.reward import RewardPopup
from module.ui.page import Page
from module.ui.ui import UI

OFFSET = (20, 20)
HOME_OFFSET = (20, 20)
HOME_INTERVAL = 3
UI_GOTO_MAIN_TIMEOUT = 60
# Top-right cutscene menu icon ≡: search the inner 3 bars by luma so
# bright-sky and dark-roof cutscene backgrounds both match reliably.
STORY_MENU_OFFSET = (15, 15)
STORY_MENU_SIMILARITY = 0.75
BOOT_TIMEOUT = 300
BOOT_IDLE_TAP = 5
# A cold start draws the lobby first and replaces the whole screen with the
# return-event panel about 10s later (probe: tap at 32.6s, panel at 42.4s).
# Keep the boot loop alive after the first lobby frame. At 0.2s per frame this
# is ~15s; counting frames instead of wall time means a slow device only
# watches longer, it cannot lose the settle window to one slow screenshot.
# Only cold starts pay it: a boot that starts and ends on `page_main` returns
# on the first frame (see `handle_app_boot`).
BOOT_LOBBY_SETTLE_FRAMES = 75
# The rotating title illustration drops this text to 0.69 on a real frame
# while every other frame stays at or below 0.29. 0.60 sits between them;
# do not tighten it back to the 0.85 default (hard rule 190).
TITLE_SIMILARITY = 0.60
# Looser title check for the idle fallback only. The real title frame with a
# different illustration scores 0.64; the return-event page scores 0.08.
IDLE_SIMILARITY = 0.45
BUY_POPUP_OFFSET = (20, 20)
# 按一下没反应是常态（153），2 秒重试一次，不和别的点击抢计时器。
BUY_POPUP_INTERVAL = 2


class TrickcalUI(RewardPopup, UI):
    """
    UI class of 嘟嘟脸恶作剧.
    """

    page_main = page_main

    # 少一个页面 `ui_get_current_page()` 就永远认不出，`ui_goto` 会静默死等 60 秒。
    pages = (page_main, page_mail, page_friend, page_task, page_task_weekly,
             page_shop, page_normal_shop, page_pass, page_costume_pass,
             page_event,
             page_event_stage, page_event_task, page_event_story,
             page_event_shop, page_event_pass, page_adventure, page_dungeon,
             page_dungeon_gold, page_dungeon_gold_stage,
             page_dungeon_bakery, page_dungeon_bakery_stage,
             page_dungeon_candy, page_dungeon_candy_stage,
             page_dungeon_crayon, page_dungeon_crayon_stage,
             page_dungeon_clone, page_dungeon_clone_stage,
             page_class, page_class_stage, page_doll, page_doll_stage,
             page_pvp, page_pvp_arena, page_pvp_deck,
             page_order, page_order_relic)

    def ui_goto(self, destination, offset=(30, 30), skip_first_screenshot=True):
        """Go to `destination`; when returning to `page_main`, prefer the top-right HOME button."""
        if destination != page_main:
            return super().ui_goto(destination, offset=offset, skip_first_screenshot=skip_first_screenshot)

        Page.init_connection(destination)
        self.interval_clear(list(self.ui_iter_check_buttons()))
        home_retry = Timer(HOME_INTERVAL)
        logger.hr(f'UI goto {destination}')
        try:
            for _ in self.loop(skip_first=skip_first_screenshot, timeout=UI_GOTO_MAIN_TIMEOUT):
                if self.ui_loading_appear():
                    self.ui_wait_loading()
                    continue
                if self.ui_page_appear(page=destination, offset=offset):
                    logger.info(f'Page arrive: {destination}')
                    self.ui_current = destination
                    return
                if self.ui_additional():
                    continue
                if self.appear(HOME, offset=HOME_OFFSET):
                    if home_retry.reached():
                        home_retry.reset()
                        logger.info('Page switch: HOME -> page_main')
                        self.device.click(HOME)
                    continue

                for page in self.ui_iter_pages():
                    if page.parent is None or page.check_button is None:
                        continue
                    if self.ui_page_appear(page, offset=offset, interval=5):
                        self.ui_current = page
                        logger.info(f'Page switch: {page} -> {page.parent}')
                        button = page.links[page.parent]
                        self.device.click(button)
                        self.interval_reset(button)
                        self.ui_wait_page_leave(page, offset=offset)
                        break

            raise GameStuckError(f'UI goto {destination} timed out')
        finally:
            Page.clear_connection()

    def app_start(self):
        """
        Launch the client and walk the cold-start flow to the lobby.

        `device.package` is normally rebound by `switch_game()` / `run_task`.
        This game shares an emulator and a config with chaoszero, so correct
        it here too: a stray launch must never start the other client.

        Returns:
            bool: True when the lobby is reached; raises on timeout.
        """
        package = to_package('trickcal')
        if self.device.package != package:
            logger.warning(f'Correct device.package {self.device.package} -> {package}')
            self.device.package = package
        if self.device.app_is_running():
            logger.info('Game is already running, bring it to the front')
        self.device.app_start()
        return self.handle_app_boot()

    def handle_app_boot(self, skip_first_screenshot=True, timeout=BOOT_TIMEOUT):
        """
        Cold start: launch -> logo / loading -> title -> sign-in -> reward ->
        announcement -> lobby.

        A fresh screenshot on each frame (the first is reused only when a real
        cached image exists, see 158), positive checks, and a timer that owns
        the upper bound (152). Every handler throttles its own click with
        `interval=2` (153).

        After a cold start the lobby is not the end of the launch: this client
        replaces it with the return-event panel several seconds later, so the
        loop keeps closing popups for `BOOT_LOBBY_SETTLE_FRAMES` consecutive
        clean frames before returning (42 / 176). That wait is skipped when the
        loop never left `page_main`: the client was already logged in, the panel
        is either behind us or will be closed by `ui_additional()` in the next
        `ui_ensure()`, and every game switch used to pay ~15s for nothing. An
        unnamed screen is never tapped blindly: the idle fallback needs a loose
        title-text match first.

        Args:
            skip_first_screenshot (bool): Reuse a cached frame if there is one.
            timeout (int): Upper bound owned by this loop.

        Returns:
            bool: True if `page_main` was reached.

        Raises:
            GameStuckError: If the lobby was not reached in time.
        """
        logger.hr('App boot', level=2)
        timer = Timer(timeout, count=3).start()
        idle = Timer(BOOT_IDLE_TAP).start()
        lobby_stable = 0
        # 只有这一轮真的走过登录流程（见过非大厅的画面）才需要盯回归活动页：
        # 它在大厅出现约 10 秒之后才整屏弹出。进循环时就已经在大厅，说明客户端
        # 早就登录完了，那一屏要么已经过去，要么后弹时由 `ui_additional()` 关掉，
        # 没必要每次接手一个已在运行的客户端都空等 15 秒（真机实测 75 帧 ≈15s）。
        cold_start = False

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
                if not self.device.has_cached_image:
                    self.device.screenshot()
            else:
                self.device.screenshot()
            self.device.stuck_record_clear()

            # End: a clean lobby is not enough after a cold start. The
            # return-event panel replaces the whole screen seconds after the
            # first lobby frame, so keep the loop alive and keep closing popups
            # until the lobby has stayed clean for a while (42 / 176).
            if self.ui_page_appear(page_main):
                if self.ui_additional():
                    cold_start = True
                    lobby_stable = 0
                    idle.reset()
                    continue
                if not cold_start:
                    logger.info('Game is already at page_main, skip the lobby settle')
                    return True
                lobby_stable += 1
                idle.reset()
                if lobby_stable >= BOOT_LOBBY_SETTLE_FRAMES:
                    logger.info('Game is at page_main')
                    return True
                continue

            # A full-screen popup replaced the lobby; start the settle over.
            cold_start = True
            lobby_stable = 0
            if self.handle_boot_popups(idle):
                continue
            for page in self.pages:
                if page is not page_main and self.ui_page_appear(page):
                    logger.info(f'Game is already logged in at {page}, return to page_main')
                    self.ui_goto_main()
                    return True
            if self.handle_idle_title(idle):
                continue

            if timer.reached():
                logger.warning('Wait game boot timeout')
                raise GameStuckError('Trickcal did not reach the lobby after launch')

    def handle_boot_popups(self, idle):
        """
        Close or advance every known screen of the login flow.

        One action per frame, in the order the client draws them. The reward
        popup goes before the claim button because the claim template still
        scores 0.99 behind it, and the sign-in X needs the greyed-out button
        as a gate (hard rule 183).

        Args:
            idle (Timer): Reset when a known screen was handled.

        Returns:
            bool: If a screen was handled this frame.
        """
        for handler in (self.handle_return_event, self.handle_reward_popup,
                        self.handle_resource_download, self.handle_announcement,
                        self.handle_countdown_popup, self.handle_cutscene_skip,
                        self.handle_title_start, self.handle_sign_in,
                        self.handle_signed_in_page):
            if handler():
                idle.reset()
                return True
        return False

    def handle_idle_title(self, idle):
        """
        Advance a screen that stayed unnamed for `BOOT_IDLE_TAP` seconds.

        A blind tap here once landed on the return-event page's 「获取」
        buttons. Only the title text may be pressed, and only when it still
        matches at `IDLE_SIMILARITY`; the return-event page scores 0.08 on
        this template, so it can never be tapped from here.

        Args:
            idle (Timer): The 5s guard, reset on every check.

        Returns:
            bool: If the title screen was pressed.
        """
        if idle.reached():
            idle.reset()
            if self.appear(E_1_1, offset=OFFSET, similarity=IDLE_SIMILARITY):
                logger.info(f'No known page for {BOOT_IDLE_TAP}s, loose title match, press to start')
                # A swallowed click is retried by the 5s timer; own the count
                # so click_record cannot end the boot before `timer` does.
                self.device.click_record_clear()
                self.device.click(E_1_1)  # alas-lint: allow - the loose title match plus the 5s idle timer are the guard
                return True
        return False

    def handle_title_start(self):
        """
        Press 「拉动脸颊开始游戏」 on the title screen.

        Similarity is deliberately low: the illustration behind the text
        rotates, so the same screen scores 0.69 on a real frame against the
        exported template. The 8-frame matrix puts every other screen at 0.29
        or below, leaving margin on both sides of 0.60 (hard rule 190).

        Returns:
            bool: If the title screen was on screen and pressed.
        """
        if self.appear(E_1_1, offset=OFFSET, similarity=TITLE_SIMILARITY, interval=2):
            logger.info('Title screen, press to start')
            # A swallowed click is retried every 2s; own the retry count here
            # so click_record does not end the boot before its own timer.
            self.device.click_record_clear()
            self.device.click(E_1_1)
            return True
        return False

    def handle_sign_in(self):
        """
        Claim the daily sign-in reward.

        `E_4_1` (reward popup) is checked before this in the boot loop, so the
        0.99 hit on the popup frame cannot repeat the claim.

        Returns:
            bool: If the claim button was pressed.
        """
        if self.appear(E_3_1, offset=OFFSET, interval=2):
            logger.info('Sign-in page, claim')
            self.device.click(E_3_1)
            return True
        return False

    def handle_signed_in_page(self):
        """
        Leave the sign-in page after claiming.

        `E_5_2` (page X) scores 1.00 on three frames and is a resident key;
        only `E_5_1` (greyed-out button) proves the claim is done (183).

        Returns:
            bool: If the page was closed.
        """
        if self.appear(E_5_1, offset=OFFSET) \
                and self.appear(E_5_2, offset=OFFSET, interval=2):
            logger.info('Sign-in finished, close the page')
            self.device.click(E_5_2)
            return True
        return False

    def ui_additional(self):
        """
        Close the popups that can cover the lobby or the mailbox.

        The reward popup goes first: it is a translucent overlay, so both the
        lobby check and the mailbox check stay "true" behind it and either
        could be reported as reached while a reward panel is up.

        The shop's item detail comes second. It is opaque and covers the whole
        grid **and** the 「尊享商店」 title, so with it up `page_shop` reads as
        unknown and `ui_goto()` would silently wait 60 seconds (151). Here it is
        cancelled, never bought: this hook runs on every page and knows nothing
        about what is being bought, so `TrickcalShop` is the only place that
        presses 购买.

        Returns:
            bool: If a popup was handled this frame.
        """
        if self.handle_reward_popup():
            return True
        if self.handle_resource_download():
            return True
        if self.handle_buy_popup():
            return True
        if self.handle_return_event():
            return True
        if self.handle_announcement():
            return True
        if self.handle_countdown_popup():
            return True
        if self.handle_cutscene_skip():
            return True
        return False

    def _appear_luma(self, button, offset=OFFSET, interval=0, similarity=0.85):
        """Detect `button` via luminance template matching with optional interval throttling."""
        if hasattr(self.device, 'stuck_record_add'):
            self.device.stuck_record_add(button)
        if interval:
            timers = getattr(self, 'interval_timer', None)
            if timers is None:
                timers = {}
                self.interval_timer = timers
            if button.name in timers:
                if timers[button.name].limit != interval:
                    timers[button.name] = Timer(interval)
            else:
                timers[button.name] = Timer(interval)
            if not timers[button.name].reached():
                return False
        appear = button.match_luma(self.device.image, offset=offset, similarity=similarity)
        if appear and interval:
            self.interval_timer[button.name].reset()
        return appear

    def handle_cutscene_skip(self):
        """
        Dismiss one cutscene / story skip dialog / tutorial guide overlay on the
        current frame in strict modal priority order.

        The sidebar `EVENT_CUTSCENE_SKIP` stays visible (~0.997) behind dimmed
        modals such as `EVENT_STORY_SKIP_CONFIRM` and `EVENT_STORY_LEAVE`, so
        foreground dialogs must be checked before the sidebar button.

        Returns:
            bool: If a cutscene or guide control was clicked.
        """
        if self.appear(EVENT_GUIDE_CLOSE, offset=OFFSET, interval=2):
            logger.info('Theme theater guide popup, press close')
            self.device.click(EVENT_GUIDE_CLOSE)
            return True
        if self.appear(EVENT_STORY_SKIP_CONFIRM, offset=OFFSET, interval=2):
            logger.info('Event story skip confirm, press 跳过')
            self.device.click(EVENT_STORY_SKIP_CONFIRM)
            return True
        if self.appear(EVENT_STORY_LEAVE, offset=OFFSET, interval=2):
            logger.info('Event last story dialog, press 不看了')
            self.device.click(EVENT_STORY_LEAVE)
            return True
        if self.appear(EVENT_STORY_CONTINUE, offset=OFFSET, interval=2):
            logger.info('Event story continue dialog, press 继续观看')
            self.device.click(EVENT_STORY_CONTINUE)
            return True
        if self.appear(EVENT_CUTSCENE_SKIP, offset=OFFSET, interval=2):
            logger.info('Event story sidebar, press 跳过')
            self.device.click(EVENT_CUTSCENE_SKIP)
            return True
        if self._appear_luma(
            EVENT_STORY_MENU,
            offset=STORY_MENU_OFFSET,
            interval=2,
            similarity=STORY_MENU_SIMILARITY,
        ):
            logger.info('Event story menu, press top-right ≡')
            self.device.click(EVENT_STORY_MENU)  # alas-lint: allow - guarded by _appear_luma(EVENT_STORY_MENU)
            return True
        return False

    def handle_event_story_or_guide(self):
        """
        Dismiss reward popups or any opening cutscene / story skip / guide overlay
        on the current frame.

        Returns:
            bool: If an overlay or cutscene control was clicked.
        """
        if self.handle_reward_popup():
            return True
        return self.handle_cutscene_skip()

    def buy_popup_appear(self):
        """
        Whether the shop's item detail (the purchase dialog) is on screen.

        The dialog is **one widget for every pack**: 每日 / 每周 / 每月免费礼包
        only change the title and the description line, while 取消 and 购买 keep
        both their art and their position. Measured on the real frame (2026-11-11
        23:03): both buttons score 1.000 on it and at most 0.185 on the three
        shop tabs, the lobby, the mailbox, the transition frame and the reward
        popup - so one pair of assets serves all three packs.

        Both buttons are required. A 购买-shaped patch alone is not a dialog and
        pressing it would buy whatever happens to be behind it.

        Returns:
            bool: True if both buttons are on screen.
        """
        return self.appear(SHOP_BUY_CANCEL, offset=BUY_POPUP_OFFSET) \
            and self.appear(SHOP_BUY_CONFIRM, offset=BUY_POPUP_OFFSET)

    def handle_buy_popup(self, confirm=False):
        """
        Press 购买 (or 取消) of the item detail, throttled to one tap per 2s.

        Args:
            confirm (bool): True presses 購買, False presses 取消.

        Returns:
            bool: If a button was pressed on this frame.
        """
        button = SHOP_BUY_CONFIRM if confirm else SHOP_BUY_CANCEL
        other = SHOP_BUY_CANCEL if confirm else SHOP_BUY_CONFIRM
        # `other` 不带 interval：它只是"弹窗还在"的证明。节流只加在要按的那颗上，
        # 否则冷却期里会被读成"弹窗不在"（mail.py 踩过同一个坑）。
        if self.appear(other, offset=BUY_POPUP_OFFSET) \
                and self.appear(button, offset=BUY_POPUP_OFFSET, interval=BUY_POPUP_INTERVAL):
            logger.info(f'Item detail, press 「{button.name}」')
            self.device.click(button)  # alas-lint: allow - 上一条 appear() 就是这一帧的判据
            return True
        return False

    def handle_return_event(self):
        """
        Close the return-event panel without claiming anything.

        Both the title and its back arrow are required, so a lone arrow on
        another screen is never pressed.

        Returns:
            bool: If the panel was closed.
        """
        if self.appear(E_2_1, offset=OFFSET) \
                and self.appear(E_2_2, offset=OFFSET, interval=2):
            logger.info('Return event panel, close it without claiming rewards')
            self.device.click(E_2_2)
            return True
        return False

    def handle_announcement(self):
        """
        Close the announcement popup.

        Returns:
            bool: If the popup was closed.
        """
        if self.appear(E_6_1, offset=OFFSET) \
                and self.appear(E_6_2, offset=OFFSET, interval=2):
            logger.info('Announcement popup, press its X')
            self.device.click(E_6_2)
            return True
        return False

    def handle_resource_download(self):
        """
        Confirm the resource-download dialog and press 「立刻出发！」 once done.

        Both the 「资源下载」 header and the 「开始下载」 button are required so a
        yellow button on another screen is never pressed by this handler.

        Returns:
            bool: If a download prompt or depart button was pressed.
        """
        if self.appear(DOWNLOAD_TITLE, offset=OFFSET) \
                and self.appear(DOWNLOAD_CONFIRM, offset=OFFSET, interval=2):
            logger.info('Resource download popup, press 开始下载')
            self.device.click_record_clear()
            self.device.click(DOWNLOAD_CONFIRM)
            return True
        if self.appear(DOWNLOAD_DEPART, offset=OFFSET, interval=2):
            logger.info('Resource download finished, press 立刻出发')
            self.device.click_record_clear()
            self.device.click(DOWNLOAD_DEPART)
            return True
        return False

    def handle_countdown_popup(self):
        """
        Dismiss the full-screen event countdown overlay ("请点击屏幕继续") on the lobby.

        Returns:
            bool: If the countdown overlay was dismissed.
        """
        if self.appear(COUNTDOWN_POPUP, offset=OFFSET, interval=2):
            logger.info('Event countdown popup, tap to continue')
            self.device.click(COUNTDOWN_POPUP)
            return True
        return False
