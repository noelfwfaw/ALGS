"""The round table (圆桌) of the menu: raise the knight order level.

Layout:

    主界面 --底栏「菜单」--> 菜单（右侧图标网格）
    菜单 --「圆桌」图标--> 圆桌面板
        左：五位主力 + 骑士团成员列表
        右：骑士团等级 233/398、所需资源、右下「升级」
    圆桌面板 --「升级」--> 等级 +1，资源减少

Every press raises the level by one and costs gold + exp books, so the loop is
"press while the button is lit". When the resources run out the button dims and
nothing else happens - that is the end of the run, and the reason the task is
worth one pass a day.
"""

from module.base.timer import Timer
from module.base.utils import get_color
from module.logger import logger
from module.lostsword.assets import (ARENA_BTN_CLOSE, ROUND_BTN_UPGRADE,
                                     ROUND_NOTICE_TITLE)
from module.lostsword.event import match
from module.lostsword.lostsword_ui import (LostswordUI, page_menu, page_round)

# The top rim of the 「升级」 plate, above the label: cream (mean 235) while the
# resources are enough, dark grey (mean 118) once they are not. 170 sits in
# between with room on both sides.
ROUND_UPGRADE_BAR = (1058, 640, 1140, 647)
ROUND_UPGRADE_MEAN = 170
# The 「资源不足。」 notice a press raises when the resources are short. Its 确认
# button sits in the middle of the screen, the same box every notice of this
# game uses.
ROUND_NOTICE_REGION = (540, 320, 720, 400)
ROUND_DIALOG_OK = (644, 468)
# Each press is one level, and the level table above the button repaints in
# between; a press that lands during that repaint is swallowed, so the loop
# waits for the next screenshot instead of hammering.
ROUND_TAP_INTERVAL = 0.5
# 398 is the cap of the panel; leave room for a few hundred presses but do not
# loop forever if the button never dims.
ROUND_MAX_TAPS = 400


class LostswordRoundTable(LostswordUI):
    def run(self):
        logger.hr('Round table', level=1)
        self.ui_ensure(page_menu)
        self.ui_ensure(page_round)

        upgraded = self.round_upgrade_all()
        logger.info(f'Round table levels raised: {upgraded}')

        self.ui_goto_main()
        # One pass a day: the resources that gate the upgrades come in slowly,
        # and a second visit the same day would find the button dark again.
        self.config.task_delay(server_update=True)

    def round_upgrade_all(self, timeout=600):
        """
        Press 「升级」 until the button dims.

        Pages:
            in: page_round
            out: page_round

        Args:
            timeout (int, float): Seconds, a safety net only.

        Returns:
            int: How many levels were raised.
        """
        logger.hr('Upgrade the round table', level=2)
        timer = Timer(timeout).start()
        pressed = 0

        while 1:
            self.device.screenshot()
            if self.round_notice_appear():
                # The last press found the resources short: the game answers
                # with 「资源不足。」 instead of raising the level.
                logger.info('Out of resources, the level stops here')
                self.round_dismiss_notice()
                break
            if not self.round_upgrade_enabled():
                logger.info('The upgrade button is dim, resources are not enough')
                break

            self.tap_upgrade()
            pressed += 1
            if pressed % 10 == 0:
                logger.info(f'{pressed} levels raised')
            if pressed >= ROUND_MAX_TAPS:
                logger.warning('Stopped at the press limit')
                break
            if timer.reached():
                logger.warning('Stopped at the time limit')
                break

            self.device.sleep(ROUND_TAP_INTERVAL)

        return pressed

    def round_notice_appear(self):
        """
        Whether the 「资源不足。」 notice is on screen.

        Returns:
            bool: If the notice is there.
        """
        return match(self.device.image, ROUND_NOTICE_TITLE,
                     ROUND_NOTICE_REGION) > 0.85

    def round_dismiss_notice(self):
        """
        Dismiss the 「资源不足。」 notice.

        Its only button is the wide 确认 in the middle of the screen; the panel
        behind it stays open, so the run can go on closing it normally.
        """
        self.tap_point(*ROUND_DIALOG_OK)
        self.device.sleep(1.5)
        self.device.screenshot()

    def tap_point(self, x, y):
        """
        Press a point of this page with an adb tap.

        Args:
            x (int): Pixel x.
            y (int): Pixel y.
        """
        self.device.adb_shell(['input', 'tap', str(int(x)), str(int(y))])

    def round_upgrade_enabled(self):
        """
        Whether 「升级」 can be pressed.

        Returns:
            bool: If the button plate is the cream one.
        """
        color = get_color(self.device.image, ROUND_UPGRADE_BAR)
        return sum(color) / 3 > ROUND_UPGRADE_MEAN

    def tap_upgrade(self):
        """
        Press the 「升级」 button.

        The buttons of this game ignore the short minitouch tap of
        `device.click()` on some screens, so an adb tap is used here as well.
        """
        x1, y1, x2, y2 = ROUND_BTN_UPGRADE.button
        self.device.adb_shell(['input', 'tap',
                               str((x1 + x2) // 2), str((y1 + y2) // 2)])
