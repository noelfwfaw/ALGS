"""The main story (冒险): push the current stage until the team loses.

Layout:

    主界面 --右侧「冒险」--> 冒险地图
        顶部三个难度 普通 / 困难 / 地狱（游戏记住上次选的）
        左侧关卡列表，右侧当前关卡的敌人与战利品，右下「选择」
    冒险地图 --「选择」--> 编队页 --「出发」--> 战斗
        赢了自动进下一关（和活动图一样），输了开 DEFEAT 页，按「返回」回主界面

One pass a day walks the three difficulties in order: 普通, then 困难, then 地狱.
Each one is pushed until the same stage comes back twice - that is the stage the
team cannot pass, and the difficulty is done.
"""

from module.base.timer import Timer
from module.logger import logger
from module.lostsword.affection import read_text
from module.lostsword.assets import (MAIN_BTN_SELECT, MAIN_BTN_SKIP,
                                     MAIN_BTN_START, MAIN_DEFEAT)
from module.lostsword.event import match
from module.lostsword.lostsword_ui import (MAIN_DEFEAT_BACK, LostswordUI,
                                          page_main)

# The three difficulty tabs across the top of the map, left to right.
MAIN_DIFFICULTIES = (('普通', (99, 50)), ('困难', (235, 50)), ('地狱', (371, 53)))
MAIN_ADV_POINT = (1176, 517)
MAIN_SELECT_POINT = (1046, 654)
MAIN_START_POINT = (1044, 662)
# "Stage 39-2" under the enemy panel; it tells whether the push moved on.
MAIN_STAGE_AREA = (1090, 190, 1240, 220)
# A stage takes a couple of minutes; the limit is a net for a stuck battle.
MAIN_FIGHT_TIMEOUT = 900
# How many stages to push per difficulty before giving up.
MAIN_MAX_STAGES = 30
# Clearing the last stage of a chapter drops into its story, which has a
# 「Skip+」 at the top right; the stage page only comes back after that.
MAIN_SKIP_POINT = (1162, 36)
MAIN_SKIP_REGION = (1080, 10, 1240, 60)
# Losing a stage opens the DEFEAT page: 领取角色 / 前往商店 / 进行强化 in the middle,
# 返回 and 战术 at the bottom. 「返回」 is the only way out, and it leads to the
# lobby through a loading screen - not back to the stage list.
MAIN_DEFEAT_REGION = (480, 110, 800, 215)


class LostswordMain(LostswordUI):
    def run(self):
        logger.hr('Main story', level=1)
        # A previous run may have left a battle going; it has to end before the
        # lobby is reachable. A game that is not even running is a launch
        # problem, and waiting the full settle window only hides it.
        if not self.main_settle():
            logger.warning('The game is not on a page this task knows, try again later')
            self.config.task_delay(success=False)
            return
        self.ui_ensure(page_main)

        for name, point in MAIN_DIFFICULTIES:
            logger.hr(f'{name}', level=2)
            if not self.main_open(point):
                logger.warning(f'{name}: the adventure map did not open')
                continue
            pushed = self.main_push(name)
            logger.info(f'{name}: {pushed} stage(s)')

        self.ui_goto_main()
        self.config.task_delay(server_update=True)

    def main_settle(self, timeout=600):
        """
        Wait for whatever the game is doing right now to end.

        The task can start in the middle of a fight - either one it left behind
        or one the user started. A fight ends at the stage page (loss) or at the
        lobby (the player quit), so those two are what this waits for.

        Returns:
            bool: If the game is back on a page the task knows.
        """
        if not self.device.app_is_running():
            logger.warning('The game is not running, nothing to settle')
            return False

        timeout = Timer(timeout).start()
        while 1:
            self.device.stuck_record_clear()
            self.device.screenshot()
            if self.on_stage_page() or self.on_lobby():
                return True
            if match(self.device.image, MAIN_BTN_SKIP, MAIN_SKIP_REGION) > 0.85:
                self.tap_point(*MAIN_SKIP_POINT)
                self.device.sleep(2)
                continue
            if timeout.reached():
                logger.warning('The game did not come back from the fight')
                return False
            self.device.sleep(3)

    def on_lobby(self):
        """
        Whether the lobby is on screen.

        The framework's own page check is used rather than matching the 「冒险」
        entry: that icon is animated, and a frame caught mid-pulse scores 0.85,
        which is right on the threshold. `page_main` is detected on the battle
        icon, which every other decision in this codebase already trusts.

        Returns:
            bool: If the lobby is there.
        """
        return self.ui_page_appear(page_main)

    def main_open(self, difficulty_point, timeout=20):
        """
        Open the adventure map on one difficulty.

        Pages:
            in: page_main
            out: page_main_difficulty

        Args:
            difficulty_point (tuple): (x, y) of the difficulty tab.
            timeout (int, float): Seconds to wait for the map.

        Returns:
            bool: If the map is open on that difficulty.
        """
        # Every difficulty starts from the lobby. After a defeat the game walks
        # back there by itself, but the walk goes through a loading screen and a
        # press sent too early is lost, so the entry is retried instead of
        # trusting one tap.
        for _ in range(2):
            self.ui_ensure(page_main)
            # The lobby keeps fading in for a moment after `ui_ensure` returns
            # (it comes back from the defeat page through a loading screen), and
            # a press sent in that moment is swallowed.
            self.device.sleep(1.2)
            self.tap_point(*MAIN_ADV_POINT)
            if self.wait_stage_page(timeout=timeout):
                break
            logger.info('The adventure map did not open, press again')
        else:
            return False

        self.tap_point(*difficulty_point)
        self.device.sleep(1.5)
        return self.wait_stage_page(timeout=8)

    def wait_stage_page(self, timeout=10):
        """
        Wait until the stage selection page is on screen.

        Args:
            timeout (int, float): Seconds.

        Returns:
            bool: If it showed up.
        """
        timeout = Timer(timeout).start()
        while 1:
            self.device.stuck_record_clear()
            self.device.screenshot()
            if self.on_stage_page():
                return True
            if timeout.reached():
                return False
            self.device.sleep(0.8)

    def on_stage_page(self):
        """
        Whether the adventure stage page is on screen.

        Returns:
            bool: If the 「选择」 button is in its corner.
        """
        return match(self.device.image, MAIN_BTN_SELECT,
                     (950, 600, 1150, 700)) > 0.85

    def main_push(self, name):
        """
        Clear stages of one difficulty until the same one comes back.

        Pages:
            in: page_main_difficulty
            out: page_main_difficulty

        Args:
            name (str): For the log.

        Returns:
            int: How many stages were cleared.
        """
        cleared = 0
        last = None
        for _ in range(MAIN_MAX_STAGES):
            if not self.on_stage_page():
                break
            stage = read_text(self.device.image, MAIN_STAGE_AREA)
            if stage and stage == last:
                logger.info(f'{name}: cannot pass {stage}, moving on')
                break
            last = stage

            self.tap_point(*MAIN_SELECT_POINT)
            if not self.wait_sortie_page(timeout=10):
                logger.warning(f'{name}: the sortie page did not open')
                break
            self.tap_point(*MAIN_START_POINT)
            if not self.main_wait_fight_end():
                logger.info(f'{name}: defeated here, next difficulty')
                break
            cleared += 1
            logger.info(f'{name}: stage {cleared} done')
        return cleared

    def wait_sortie_page(self, timeout=10):
        """
        Wait until the sortie page of a stage is on screen.

        Args:
            timeout (int, float): Seconds.

        Returns:
            bool: If it showed up.
        """
        timeout = Timer(timeout).start()
        while 1:
            self.device.stuck_record_clear()
            self.device.screenshot()
            if match(self.device.image, MAIN_BTN_START,
                     (950, 610, 1150, 700)) > 0.85:
                return True
            if timeout.reached():
                return False
            self.device.sleep(0.6)

    def main_defeat_appear(self):
        """
        Whether the DEFEAT page is on screen.

        Returns:
            bool: If it is there.
        """
        return match(self.device.image, MAIN_DEFEAT,
                     MAIN_DEFEAT_REGION) > 0.85

    def main_wait_fight_end(self, timeout=MAIN_FIGHT_TIMEOUT):
        """
        Wait for one stage to be over.

        A win sends the game to the next stage by itself, so the stage only
        comes back as a page when the team loses - and a loss opens the DEFEAT
        page first, whose 「返回」 goes back to the lobby through a loading
        screen rather than to the list.

        Args:
            timeout (int, float): Seconds.

        Returns:
            bool: If the stage was cleared. False means the team lost.
        """
        timeout = Timer(timeout).start()
        while 1:
            self.device.stuck_record_clear()
            self.device.screenshot()
            if self.on_stage_page():
                self.device.sleep(1)
                self.device.screenshot()
                return True
            if match(self.device.image, MAIN_BTN_SKIP,
                     MAIN_SKIP_REGION) > 0.85:
                logger.info('Chapter story, skip it')
                self.tap_point(*MAIN_SKIP_POINT)
                self.device.sleep(2)
                continue
            if self.main_defeat_appear():
                logger.info('The team lost this stage')
                self.main_defeat_leave()
                return False
            if timeout.reached():
                return False
            self.device.sleep(2)

    def main_defeat_leave(self, timeout=20):
        """
        Press 「返回」 on the defeat page until it is gone.

        The page fades in, and a tap that lands during the fade is swallowed -
        the run then stays on the result page, and walking home from there only
        reports an unknown page. The press is therefore repeated until the
        artwork is off screen.

        Returns:
            bool: If the page is gone.
        """
        self.device.sleep(1.5)
        timeout = Timer(timeout).start()
        while 1:
            self.device.stuck_record_clear()
            self.device.screenshot()
            if not self.main_defeat_appear():
                return True
            if timeout.reached():
                logger.warning('The defeat page does not close')
                return False
            self.device.click(MAIN_DEFEAT_BACK)
            self.device.sleep(1.5)

    def tap_point(self, x, y):
        """
        Press a point of this page with an adb tap.

        Args:
            x (int): Pixel x.
            y (int): Pixel y.
        """
        self.device.adb_shell(['input', 'tap', str(int(x)), str(int(y))])
