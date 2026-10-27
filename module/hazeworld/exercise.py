from module.base.button import Button
from module.base.timer import Timer
from module.hazeworld.assets import (EX_BTN_BATTLE_DONE,
                                     EX_BTN_BATTLE_READY, EX_BTN_PROXY,
                                     EX_PROXY_CONFIRM, EX_PROXY_MAX,
                                     EX_PROXY_SETTLE, EX_PROXY_START,
                                     EX_PROXY_TITLE, EX_RANK_EXIT,
                                     EX_RESULT_CONFIRM, EX_RESULT_TITLE)
from module.hazeworld.hazeworld_ui import HazeworldUI, page_exercise
from module.logger import logger
from module.ocr.ocr import DigitCounter

# Ticket counter at the top right of the exercise page, `13/15`.
# Not a template: the number changes every fight, only OCR can read it.
# The digits are a soft white, the default pure white letter colour makes
# `extract_letters()` drop the thin slash and read `9/15` as `915`.
EXERCISE_TICKET = DigitCounter(  # alas-lint: allow - a disabled-state variant of a generated asset
    Button(area=(1095, 22, 1205, 52), color=(), button=(1095, 22, 1205, 52),
           name='EXERCISE_TICKET'),
    letter=(240, 240, 240),
    threshold=128,
)

# A proxy sweep runs 15 seconds per battle without a single click, and 15
# tickets a day makes one sweep longer than any timeout the framework keeps
# for "no click happened". The wait itself is normal, so it is bounded here.
PROXY_BATTLE_TIME = 15
PROXY_TIMEOUT = 600

# Exercise tickets recover one per hour and cap at 15, so running only at the
# server update would leave the counter full for the last third of the day and
# waste the recovery. Any interval below 15 hours never overflows the cap;
# 12 hours spends all 24 tickets a day while keeping 3 hours of margin for a
# run the scheduler delays behind other tasks.
EXERCISE_INTERVAL = 12 * 60


class HazeworldExercise(HazeworldUI):
    """
    Exercise hall: spend the daily arena tickets.

    Two ways to fight, picked by `HazeworldExercise.ProxyBattle`:

    - proxy battle: "代理作战" -> MAX -> "开始代理" -> the game sweeps every
      ticket on its own -> "代理完成" -> "确认". Fast, no battle animation.
    - manual: "作战准备" per fight, then "战斗胜利" -> "确认", sometimes with
      a rank change popup in between. Slower, but the fight is visible.

    Tickets recover one per hour up to 15, so the next run is at most 12 hours
    away and pulled towards the server update, see `EXERCISE_INTERVAL`.

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
        logger.hr('Exercise', level=1)
        self.ui_ensure(page_exercise)

        if self.config.HazeworldExercise_ProxyBattle:
            self.exercise_proxy()
        else:
            self.exercise_manual()

        self.ui_goto_main()

        # Not a daily task: tickets keep recovering after the server update,
        # see EXERCISE_INTERVAL. `task_delay()` picks whichever comes first, so
        # the pair settles on 05:00 (shared with the daily tasks) and 17:00.
        self.config.task_delay(server_update=True, minute=EXERCISE_INTERVAL)

    def exercise_ticket_left(self, retry=2):
        """
        Read the ticket counter of the exercise page.

        `letter` is set in `EXERCISE_TICKET`: the digits printed by the game
        are a bit darker than pure white, and with the default letter colour
        the slash between the two numbers is dropped by the threshold, so
        `9/15` comes back as `915` and `DigitCounter` rejects it.

        Args:
            retry (int): How many screenshots to try before giving up.

        Returns:
            int or None: Battles left, None if the counter could not be read.
        """
        for _ in range(retry):
            self.device.screenshot()
            current, remain, total = EXERCISE_TICKET.ocr(self.device.image)
            if total:
                logger.attr('Exercise ticket', f'{current}/{total}')
                return current

        logger.warning('Cannot read the exercise ticket counter')
        return None

    # ==================== Proxy battle ====================

    def exercise_proxy(self):
        """
        Sweep the arena with the proxy battle dialog until the tickets run out.

        The dialog needs the "代理作战" button to be unlocked: a fresh account
        has it greyed out with a lock icon and the button does not match, so it
        falls back to fighting one by one instead of waiting for nothing.

        Pages:
            in: page_exercise
            out: page_exercise
        """
        logger.hr('Proxy battle', level=2)
        if not self.wait_until_appear(EX_BTN_PROXY, offset=(20, 20), timeout=2):
            logger.warning('Proxy battle is not unlocked, fight one by one')
            self.exercise_manual()
            return

        left = self.exercise_ticket_left()
        if left is not None and left <= 0:
            logger.info('No exercise ticket left')
            return

        if not self.exercise_proxy_start():
            logger.warning('Proxy battle did not start, fight one by one')
            self.exercise_manual()
            return

        if not self.exercise_proxy_wait(left):
            logger.warning('Proxy battle did not finish in time')
            return

        self.exercise_proxy_result()

    def exercise_proxy_start(self, skip_first_screenshot=True):
        """
        Open the proxy dialog, take every ticket and start the sweep.

        The dialog dims the hall but leaves the hall buttons readable, so the
        dialog is checked before them. The dialog fades in and eats the first
        click, so MAX is pressed for a while instead of once, and "开始代理"
        is only pressed after that - starting the sweep with the default
        count would only fight a single battle. A click swallowed by the
        dialog animation is simply retried by the interval.

        Pages:
            in: page_exercise
            out: page_exercise (sweeping)

        Returns:
            bool: True if the sweep started.
        """
        logger.info('Proxy battle start')
        timeout = Timer(120, count=10).start()
        max_timer = Timer(3, count=2).start()
        opened = False

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if timeout.reached():
                logger.warning('Proxy battle dialog did not open')
                return False

            if self.appear(EX_PROXY_TITLE, offset=(20, 20)):
                opened = True
                if not max_timer.reached():
                    logger.info('Proxy battle dialog, take every ticket')
                    self.appear_then_click(EX_PROXY_MAX, offset=(20, 20), interval=1)
                    continue
                self.appear_then_click(EX_PROXY_START, offset=(20, 20), interval=3)
                continue

            if opened:
                # Dialog closed, the sweep is running.
                return True

            if self.appear_then_click(EX_BTN_PROXY, offset=(20, 20), interval=3):
                continue

    def exercise_proxy_wait(self, battle_count=None, skip_first_screenshot=True):
        """
        Wait until the proxy sweep is over.

        The sweep runs 15 seconds per battle without a click, longer than the
        60 seconds the framework tolerates before it declares a stuck game. The
        wait is expected here, so the stuck record is cleared while it runs. A
        local timeout derived from the ticket count keeps it from waiting
        forever when the sweep did not actually start.

        Args:
            battle_count (int): Battles the sweep should run, None if unknown.
            skip_first_screenshot (bool):

        Pages:
            in: page_exercise (sweeping)
            out: page_exercise (result ready)

        Returns:
            bool: True if "代理完成" appeared.
        """
        logger.info('Proxy battle running')
        timeout = Timer(PROXY_TIMEOUT, count=10).start()
        if battle_count:
            timeout = Timer(battle_count * PROXY_BATTLE_TIME + 120, count=10).start()

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(EX_BTN_BATTLE_DONE, offset=(20, 20)):
                return True

            if timeout.reached():
                return False

            self.device.stuck_record_clear()

    def exercise_proxy_result(self, skip_first_screenshot=True):
        """
        Take the sweep result and go back to the hall.

        Pages:
            in: page_exercise (result ready)
            out: page_exercise

        Returns:
            bool: True if the hall is reached again.
        """
        logger.info('Proxy battle result')
        timeout = Timer(120, count=10).start()
        confirmed = False

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if timeout.reached():
                logger.warning('Proxy battle result did not go back to the hall')
                return False

            if self.appear_then_click(EX_BTN_BATTLE_DONE, offset=(20, 20), interval=3):
                continue

            # Reward popup of the sweep, the hall behind it is readable so it
            # is checked before the hall itself.
            if self.appear(EX_PROXY_SETTLE, offset=(20, 20)):
                self.appear_then_click(EX_PROXY_CONFIRM, offset=(20, 20), interval=2)
                confirmed = True
                continue

            if self.appear_then_click(EX_RANK_EXIT, offset=(20, 20), interval=2):
                continue

            if confirmed and self.appear(EX_BTN_PROXY, offset=(20, 20)):
                return True

    # ==================== Manual battle ====================

    def exercise_manual(self, skip_first_screenshot=True):
        """
        Fight one battle at a time until the tickets run out.

        Pages:
            in: page_exercise
            out: page_exercise
        """
        logger.hr('Manual battle', level=2)
        count = 0

        while 1:
            left = self.exercise_ticket_left()
            if left is not None and left <= 0:
                logger.info('No exercise ticket left')
                break

            if not self.exercise_start():
                logger.warning('Exercise battle did not start, stop here')
                break

            if not self.exercise_result():
                logger.warning('Exercise battle did not return to the hall, stop here')
                break

            count += 1
            logger.info(f'Exercise battle finished, total {count}')

        logger.info(f'Exercise finished, fought {count} time(s)')
        return count

    def exercise_start(self, skip_first_screenshot=True):
        """
        Press "作战准备" and wait until the battle is over.

        The button is pressed on an interval instead of once, so a click that
        a page transition swallows is retried instead of being lost. The exit
        condition is the result screen, which only appears after the fight, so
        no click counter is needed to tell "started" from "not started yet".

        Pages:
            in: page_exercise
            out: page_exercise_result

        Returns:
            bool: True if the result screen appeared.
        """
        logger.info('Exercise battle start')
        timeout = Timer(300, count=10).start()
        started = False

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(EX_RESULT_TITLE, offset=(20, 20)):
                return True

            if timeout.reached():
                logger.warning('Exercise battle did not finish in time')
                return False

            # The rank popup covers the hall but leaves its title and its
            # buttons readable, so clear it before anything else.
            if self.appear_then_click(EX_RANK_EXIT, offset=(20, 20), interval=3):
                continue

            # A proxy sweep left over from the last session, take its result
            # first, the hall cannot start a new fight before that.
            if self.appear_then_click(EX_BTN_BATTLE_DONE, offset=(20, 20), interval=3):
                continue

            if self.appear_then_click(EX_BTN_BATTLE_READY, offset=(20, 20), interval=3):
                started = True
                continue

            if started:
                # The fight runs itself, this wait is expected.
                self.device.stuck_record_clear()

    def exercise_result(self, skip_first_screenshot=True):
        """
        Confirm the result screen and get back to the exercise page.

        Pages:
            in: page_exercise_result
            out: page_exercise

        Returns:
            bool: True if the exercise page is reached again.
        """
        logger.info('Exercise result')
        timeout = Timer(120, count=10).start()
        confirmed = False

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if timeout.reached():
                logger.warning('Exercise result did not go back to the hall')
                return False

            if self.appear_then_click(EX_RESULT_CONFIRM, offset=(20, 20), interval=2):
                confirmed = True
                continue

            if self.appear_then_click(EX_RANK_EXIT, offset=(20, 20), interval=2):
                continue

            # Only trust the hall once the result screen was confirmed,
            # otherwise the fading result screen is mistaken for it.
            if confirmed and self.ui_page_appear(page_exercise, offset=(20, 20)):
                return True
