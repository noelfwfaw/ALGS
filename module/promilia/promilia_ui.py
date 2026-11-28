"""Promilia interface layer."""

from module.logger import logger
from module.promilia.assets import (ACTIVITY_DAILY_ACTIVE, ACTIVITY_REWARD_CLOSE,
                                    ACTIVITY_REWARD_TITLE)
from module.promilia.login import PromiliaLogin
from module.promilia.page import page_activity, page_main
from module.promilia.update import PromiliaUpdate
from module.ui.ui import UI


class PromiliaUI(PromiliaUpdate, PromiliaLogin, UI):
    """Promilia UI with update, login, reward and page handling."""

    page_main = page_main
    pages = (page_main, page_activity)

    def activity_reward_appear(self):
        """Require both the reward title and its safe-close hint."""
        return (self.appear(ACTIVITY_REWARD_TITLE, offset=(20, 20))
                and self.appear(ACTIVITY_REWARD_CLOSE, offset=(20, 20)))

    def handle_activity_reward(self):
        """Close one activity reward panel, never clicking through a lingering frame."""
        if not self.activity_reward_appear():
            if getattr(self, '_activity_reward_closing', False):
                restored = (self.appear(ACTIVITY_DAILY_ACTIVE, offset=(20, 20))
                            or self.is_in_main())
                absent = getattr(self, '_activity_reward_absent', 0) + 1 if restored else 0
                self._activity_reward_absent = absent
                if absent >= 2:
                    self._activity_reward_closing = False
                    self._activity_reward_absent = 0
            else:
                self._activity_reward_absent = 0
            return False
        self._activity_reward_absent = 0
        if getattr(self, '_activity_reward_closing', False):
            return True
        if self.appear_then_click(ACTIVITY_REWARD_CLOSE, offset=(20, 20), interval=3):
            self._activity_reward_closing = True
            logger.info('Close Promilia activity reward')
        return True

    def ui_additional(self):
        """Handle global modals first, then login and loading states."""
        if self.handle_update_notice():
            return True
        if self.handle_update_downloading():
            return True
        if self.handle_activity_reward():
            return True
        if self.handle_login():
            return True
        if self.handle_loading():
            return True
        return False
