"""UI layer of 嘟嘟脸恶作剧 (Trickcal).

Facts read off the emulator / exported screenshots (2026-11-11):

- Package `com.bilibili.trickcalcn`, versionName 1.7.0.
- Installed on instance 127.0.0.1:16448 (config/chaoszero.json), the same
  instance as chaoszero and crosscore. One process binds one emulator: when
  this game runs, tasks of games on 127.0.0.1:16640 must be disabled.
- `wm size` reports 720x1280 portrait, but the client renders landscape like
  chaoszero and crosscore do. Do not work around this in the device layer.
- All 7 frames of the login spec are 1280x720.

Launch: `alas.py:start()` calls `game_ui().app_start()` when switching games,
and `dev_tools/run_task.py` calls it without `--no-boot`. Overriding that
method is what makes a launch actually reach the lobby: the base
`UI.app_start()` only restarts the process, it does not walk the login flow.

Similarity matrix on the 7 exported frames (`asset_check --module trickcal`):
`E_5_2` (sign-in X) is 1.00 on three frames and `E_3_1` (claim) is 0.99 on the
reward popup, so the boot loop is driven by per-page positive checks with an
explicit wait after every press, not by a button chain (hard rule 183).

`page_main` is the only registered page (see page.py). Popups that cover the
lobby are handled here so `ui_get_current_page()` can settle. Without a check
button, `ui_goto_main()` would raise GamePageUnknownError and take the whole
scheduler down - both local configs use `WhenTaskQueueEmpty: goto_main`.
"""

from module.config.server import to_package
from module.logger import logger
from module.trickcal.assets import (E_1_1, E_2_1, E_2_2, E_3_1, E_4_1,
                                    E_5_1, E_5_2, E_6_1, E_6_2, E_7_1)
from module.trickcal.page import page_main
from module.ui.ui import UI

OFFSET = (20, 20)
BOOT_TIMEOUT = 300


class TrickcalUI(UI):
    """
    UI class of 嘟嘟脸恶作剧.
    """

    page_main = page_main

    pages = (page_main,)

    def app_start(self):
        """
        Launch the client and walk the whole cold-start flow to the lobby.

        `device.package` is normally rebound by `switch_game()` / `run_task`.
        This game shares an emulator and a config with chaoszero, so correct
        it here too: a stray launch must never start the other client.

        Returns:
            bool: If the lobby was reached.
        """
        package = to_package('trickcal')
        if self.device.package != package:
            logger.warning(f'Correct device.package {self.device.package} -> {package}')
            self.device.package = package
        if self.device.app_is_running():
            logger.info('Game is already running, bring it to the front')
        self.device.app_start()
        return self.handle_app_boot()

    def handle_app_boot(self, timeout=BOOT_TIMEOUT):
        """
        Cold start: launch -> logo / loading -> title -> sign-in -> reward ->
        announcement -> lobby. Frames before the title screen are game-owned
        and have no check button, so every frame clears the stuck record and
        the upper bound is this loop's own timer (152). Branch order and the
        explicit waits come from the similarity matrix; see the module
        docstring and `references/games/trickcal.md` (183).

        Args:
            timeout (int): Upper bound owned by this loop.

        Returns:
            bool: If the lobby (`E_7_1`) was reached.
        """
        # skip_first=False 是必须的：device.app_start() 会把 self.image 置为
        # None 作废旧帧，而 loop() 默认首帧复用旧截图、不去截一张，
        # 第一句 appear() 就会拿 None 进 Button.match() 崩掉（15:14 真机实测）。
        for _ in self.loop(skip_first=False, timeout=timeout):
            # 冷启动的 logo / 加载 / 登录是游戏自己走的过程，可能几十秒没有
            # 任何判据。纯等待不归看门狗管，上限交给本循环自己的 timeout。
            self.device.stuck_record_clear()

            # End: a clean lobby. This template scores only 0.13 through the
            # announcement popup, so this is a real end condition. It is the
            # same check button as `page_main`; use the verified ±20 offset.
            if self.appear(E_7_1, offset=OFFSET):
                logger.info('Trickcal lobby reached')
                return True

            # Return-event panel: only on returning accounts, a normal login
            # goes straight to the sign-in page. Close it and claim nothing.
            if self.appear(E_2_1, offset=OFFSET) \
                    and self.appear(E_2_2, offset=OFFSET):
                logger.info('Return event panel, close it without claiming rewards')
                self.device.click(E_2_2)
                self.wait_until_disappear(E_2_1, offset=OFFSET, timeout=10, settle=2)
                continue

            # Reward popup after the claim. Must stay ahead of `E_3_1`.
            if self.appear(E_4_1, offset=OFFSET):
                logger.info('Sign-in reward popup, tap to continue')
                self.device.click(E_4_1)
                self.wait_until_disappear(E_4_1, offset=OFFSET, timeout=10, settle=2)
                continue

            # Announcement popup over the lobby.
            if self.appear(E_6_1, offset=OFFSET) \
                    and self.appear(E_6_2, offset=OFFSET):
                logger.info('Announcement, press its X')
                self.device.click(E_6_2)
                self.wait_until_disappear(E_6_2, offset=OFFSET, timeout=10, settle=2)
                continue

            # Title screen.
            if self.appear(E_1_1, offset=OFFSET):
                logger.info('Title screen, press to start')
                self.device.click(E_1_1)
                self.wait_until_disappear(E_1_1, offset=OFFSET, timeout=20, settle=2)
                continue

            # Sign-in page, claim. Explicitly wait for the reward popup so the
            # resident `E_5_2` cannot close this page in between.
            if self.appear(E_3_1, offset=OFFSET):
                logger.info('Sign-in page, claim')
                self.device.click(E_3_1)
                if not self.wait_until_appear(E_4_1, offset=OFFSET, timeout=15, settle=2):
                    logger.warning('Reward popup not seen after claim, keep waiting')
                continue

            # Sign-in finished: only `E_5_1` (greyed-out button, 1.00 on
            # page_5 and <=0.75 on page_3/4) proves the page may be closed.
            if self.appear(E_5_1, offset=OFFSET) \
                    and self.appear(E_5_2, offset=OFFSET):
                logger.info('Sign-in finished, close the page')
                self.device.click(E_5_2)
                self.wait_until_disappear(E_5_2, offset=OFFSET, timeout=10, settle=2)
                continue

        logger.warning('Trickcal boot did not reach the lobby in time')
        return False

    def ui_additional(self):
        """
        Close the two popups that can cover the lobby.

        These handlers are for `ui_get_current_page()` / `ui_goto_main()`;
        `handle_app_boot()` uses its own checked branches with explicit waits
        because the boot flow must verify each press before moving on.

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
