"""Promilia login and loading handling."""

from module.logger import logger
from module.promilia.assets import LOADING_LOGO, LOGIN_START


# The full button includes an animated background; only its title glyphs are static.
LOGIN_START_TEXT = LOGIN_START.crop((27, 22, 137, 36), name='LOGIN_START_TEXT')


class PromiliaLogin:
    """Handle the title-page button and the static loading screen."""

    def handle_login(self):
        """Press 「开始旅程」 once when the login page appears."""
        if self.appear(LOGIN_START_TEXT, offset=(20, 20), interval=3):
            LOGIN_START.load_offset(LOGIN_START_TEXT)
            self.device.click(LOGIN_START)
            logger.info('Promilia login, press 开始旅程')
            return True
        return False

    def handle_loading(self):
        """Consume loading frames without clicking and keep the watchdog clear."""
        if self.appear(LOADING_LOGO, offset=(20, 20)):
            self.device.stuck_record_clear()
            return True
        return False
