from module.hazeworld.assets import FRIEND_LIKE_ALL
from module.hazeworld.hazeworld_ui import HazeworldUI, page_friend
from module.logger import logger


class HazeworldFriend(HazeworldUI):
    """
    Like every friend in one click.

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
        logger.hr('Friend like', level=1)
        self.ui_ensure(page_friend)

        if self.config.HazeworldFriend_LikeAll:
            self.friend_like_all()

        self.ui_goto_main()

        # Daily task, run again after the game refreshes.
        self.config.task_delay(server_update=True)

    def friend_like_all(self, skip_first_screenshot=True):
        """
        Press "like all" once and clear the popup it may raise.

        The button keeps the same appearance after being pressed, so it cannot
        be used as an exit condition. The action is idempotent (the game stops
        giving stamina once 15/15 is reached), so it is clicked once and then
        the popup is handled.

        Pages:
            in: page_friend
            out: page_friend
        """
        logger.hr('Friend like all', level=2)
        # The friend page fades in, and ui_ensure() returns on that half drawn
        # frame, so wait for a settled screenshot before deciding anything.
        if self.wait_until_settled(FRIEND_LIKE_ALL, timeout=3, skip_first_screenshot=skip_first_screenshot):
            logger.info('Like all friends')
            self.device.click(FRIEND_LIKE_ALL)

        while 1:
            self.device.screenshot()
            if self.handle_reward():
                continue
            break

        self.interval_clear(FRIEND_LIKE_ALL)
