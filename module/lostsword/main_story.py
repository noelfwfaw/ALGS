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
from module.lostsword.utils import read_text
from module.lostsword.assets import (MAIN_BTN_SELECT, MAIN_BTN_SKIP,
                                     MAIN_BTN_START, MAIN_DEFEAT)
from module.lostsword.utils import match
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
        """
        Pages:
            in: page_main
            out: page_main
        """
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
        # The story of a chapter is skipped by one button, but the button stays
        # drawn while the scene advances, so pressing it every frame would skip
        # several pages at once. One press per two seconds is the same cadence
        # the scene needs, without the sleep.
        skip = Timer(2).start()

        for _ in self.loop():
            # A battle and a story scene are live scenes that barely change for
            # minutes, which reads as a frozen game to the stuck detector.
            self.device.stuck_record_clear()

            # End - one of the two pages this task starts from.
            if self.on_stage_page() or self.on_lobby():
                return True

            # Click - chapter story, the stage page only comes back once it ends.
            if match(self.device.image, MAIN_BTN_SKIP, MAIN_SKIP_REGION) > 0.85:
                if skip.reached():
                    skip.reset()
                    self.tap_point(*MAIN_SKIP_POINT)
                continue

            if timeout.reached():
                logger.warning('The game did not come back from the fight')
                return False

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
        # press sent too early is lost, so the entry is pressed again on a timer
        # until the map answers instead of trusting one tap.
        self.ui_ensure(page_main)
        retry = Timer(2).start()

        for _ in self.loop(timeout=timeout):
            # End - the map is up.
            if self.on_stage_page():
                break

            # Click - the entry is in a fixed corner of the lobby, the page check
            # above is what decides whether the press landed.
            if retry.reached():
                retry.reset()
                self.tap_point(*MAIN_ADV_POINT)
        else:
            logger.warning('The adventure map did not open')
            return False

        self.tap_point(*difficulty_point)
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

        for _ in self.loop(timeout=timeout):
            self.device.stuck_record_clear()
            if self.on_stage_page():
                return True
        else:
            return False

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

            if not self.main_sortie(timeout=10):
                logger.warning(f'{name}: the sortie page did not open')
                break
            if not self.main_wait_fight_end():
                logger.info(f'{name}: defeated here, next difficulty')
                break
            cleared += 1
            logger.info(f'{name}: stage {cleared} done')
        return cleared

    def on_sortie_page(self):
        """
        Whether the sortie page of a stage is on screen.

        Returns:
            bool: If 「出发」 is in its corner.
        """
        return match(self.device.image, MAIN_BTN_START,
                     (950, 610, 1150, 700)) > 0.85

    def main_sortie(self, timeout=10):
        """
        Get to the sortie page, pressing 「选择」 until it shows.

        The stage page repaints its right half when the next stage loads, and a
        press that lands during that repaint is lost - the run then sits on the
        stage page until the caller gives up. Repeating the press on a timer
        makes that a matter of the next frame instead of a lost stage.

        Pages:
            in: page_main_difficulty
            out: sortie page

        Args:
            timeout (int, float): Seconds.

        Returns:
            bool: If the sortie page is open.
        """
        timeout = Timer(timeout).start()
        retry = Timer(2).start()

        for _ in self.loop(timeout=timeout):
            self.device.stuck_record_clear()

            # End - the sortie page answered.
            if self.on_sortie_page():
                return True

            # Click - 「选择」 sits in the bottom right corner of the stage page.
            if retry.reached():
                retry.reset()
                self.tap_point(*MAIN_SELECT_POINT)
        else:
            return False

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
        skip = Timer(2).start()
        start = Timer(5).start()

        for _ in self.loop():
            # A battle is a live scene that barely changes for minutes, which
            # reads as a frozen game to the stuck detector.
            self.device.stuck_record_clear()

            # End - back on the stage list: the stage was cleared and the game
            # moved on to the next one by itself.
            if self.on_stage_page():
                return True

            # End - the team lost.
            if self.main_defeat_appear():
                logger.info('The team lost this stage')
                self.main_defeat_leave()
                return False

            # Click - the story of a chapter end, which the stage page only comes
            # back from once it is over. One press per two seconds, otherwise the
            # scene advances several pages at once.
            if match(self.device.image, MAIN_BTN_SKIP, MAIN_SKIP_REGION) > 0.85:
                if skip.reached():
                    skip.reset()
                    logger.info('Chapter story, skip it')
                    self.tap_point(*MAIN_SKIP_POINT)
                continue

            # Click - the sortie page is still up, 「出发」 was swallowed by the
            # page sliding in. Slow retry: the loading screen follows the press,
            # and a burst of taps would queue several battles.
            if self.on_sortie_page():
                if start.reached():
                    start.reset()
                    self.tap_point(*MAIN_START_POINT)
                continue

            if timeout.reached():
                return False

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
        timeout = Timer(timeout).start()
        retry = Timer(1.5).start()

        for _ in self.loop():
            # The defeat artwork is a still scene, which reads as a frozen game
            # to the stuck detector.
            self.device.stuck_record_clear()

            # End - the page is gone.
            if not self.main_defeat_appear():
                return True

            # Click - 「返回」 is the only way out, and the page fades in eating
            # the taps aimed at it, so the press is repeated until the artwork
            # is off screen.
            if retry.reached():
                retry.reset()
                if self.appear(MAIN_DEFEAT, offset=30):
                    self.device.click(MAIN_DEFEAT_BACK)

            if timeout.reached():
                logger.warning('The defeat page does not close')
                return False
