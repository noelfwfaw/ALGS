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

`page_main` is the only registered page (see page.py). Popups that cover the
lobby are handled here so `ui_get_current_page()` can settle. Without a check
button, `ui_goto_main()` would raise GamePageUnknownError and take the whole
scheduler down when `WhenTaskQueueEmpty` is set to `goto_main`.
"""

from module.base.timer import Timer
from module.config.server import to_package
from module.exception import GameStuckError
from module.logger import logger
from module.trickcal.assets import (E_1_1, E_2_1, E_2_2, E_3_1, E_4_1,
                                    E_5_1, E_5_2, E_6_1, E_6_2)
from module.trickcal.page import page_main
from module.ui.ui import UI

OFFSET = (20, 20)
BOOT_TIMEOUT = 300
BOOT_IDLE_TAP = 5
# A cold start draws the lobby first and replaces the whole screen with the
# return-event panel about 10s later (probe: tap at 32.6s, panel at 42.4s).
# Keep the boot loop alive after the first lobby frame. At 0.2s per frame this
# is ~15s; counting frames instead of wall time means a slow device only
# watches longer, it cannot lose the settle window to one slow screenshot.
BOOT_LOBBY_SETTLE_FRAMES = 75
# The rotating title illustration drops this text to 0.69 on a real frame
# while every other frame stays at or below 0.29. 0.60 sits between them;
# do not tighten it back to the 0.85 default (hard rule 190).
TITLE_SIMILARITY = 0.60
# Looser title check for the idle fallback only. The real title frame with a
# different illustration scores 0.64; the return-event page scores 0.08.
IDLE_SIMILARITY = 0.45


class TrickcalUI(UI):
    """
    UI class of 嘟嘟脸恶作剧.
    """

    page_main = page_main

    pages = (page_main,)

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

        The lobby is not the end of the launch: this client replaces it with
        the return-event panel several seconds later, so the loop keeps closing
        popups for `BOOT_LOBBY_SETTLE_FRAMES` consecutive clean frames before
        returning (42 / 176). An unnamed screen is never tapped blindly: the
        idle fallback needs a loose title-text match first.

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

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
                if not self.device.has_cached_image:
                    self.device.screenshot()
            else:
                self.device.screenshot()
            self.device.stuck_record_clear()

            # End: a clean lobby is not enough. The return-event panel replaces
            # the whole screen seconds after the first lobby frame, so keep the
            # loop alive and keep closing popups until the lobby has stayed
            # clean for a while (42 / 176).
            if self.ui_page_appear(page_main):
                if self.ui_additional():
                    lobby_stable = 0
                    idle.reset()
                    continue
                lobby_stable += 1
                idle.reset()
                if lobby_stable >= BOOT_LOBBY_SETTLE_FRAMES:
                    logger.info('Game is at page_main')
                    return True
                continue

            # A full-screen popup replaced the lobby; start the settle over.
            lobby_stable = 0
            if self.handle_boot_popups(idle):
                continue
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
                        self.handle_announcement, self.handle_title_start,
                        self.handle_sign_in, self.handle_signed_in_page):
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

    def handle_reward_popup(self):
        """
        Tap 「请点击屏幕继续」 on the reward popup.

        Returns:
            bool: If the popup was dismissed.
        """
        if self.appear(E_4_1, offset=OFFSET, interval=2):
            logger.info('Sign-in reward popup, tap to continue')
            self.device.click(E_4_1)
            return True
        return False

    def ui_additional(self):
        """
        Close the two popups that can cover the lobby.

        Returns:
            bool: If a popup was handled this frame.
        """
        if self.handle_return_event():
            return True
        if self.handle_announcement():
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
