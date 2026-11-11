"""UI layer of 嘟嘟脸恶作剧 (Trickcal).

Facts read off the emulator / exported screenshots (2026-11-11):

- Package `com.bilibili.trickcalcn`, versionName 1.7.0.
- Installed on instance 127.0.0.1:16448 (config/chaoszero.json), the same
  instance as chaoszero and crosscore. One process binds one emulator: when
  this game runs, tasks of games on 127.0.0.1:16640 must be disabled.
- `wm size` reports 720x1280 portrait, but the client renders landscape like
  chaoszero and crosscore do. Do not work around this in the device layer.
- All 7 frames of the login spec are 1280x720.

`page_main` is the only registered page (see page.py). Popups that cover the
lobby are handled here so `ui_get_current_page()` can settle: a popup hides
the lobby button row, `ui_additional()` closes it, the next frame sees
`page_main` again. Without a check button, `ui_goto_main()` would raise
GamePageUnknownError and take the whole scheduler down - both local configs
use `WhenTaskQueueEmpty: goto_main`.
"""

from module.trickcal.assets import E_2_1, E_2_2, E_6_1, E_6_2
from module.trickcal.page import page_main
from module.logger import logger
from module.ui.ui import UI


class TrickcalUI(UI):
    """
    UI class of 嘟嘟脸恶作剧.
    """

    page_main = page_main

    pages = (page_main,)

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

        The panel only shows up for returning accounts; a normal login goes
        straight from the title screen to the sign-in page. Both the title
        and its back arrow are required, so a lone arrow on another screen
        is never pressed.

        Returns:
            bool: If the panel was closed.
        """
        if self.appear(E_2_1, offset=(20, 20)) \
                and self.appear(E_2_2, offset=(20, 20), interval=2):
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
        if self.appear(E_6_1, offset=(20, 20)) \
                and self.appear(E_6_2, offset=(20, 20), interval=2):
            logger.info('Announcement popup, press its X')
            self.device.click(E_6_2)
            return True
        return False
