from datetime import datetime, timedelta

from module.base.button import Button
from module.base.timer import Timer
from module.exception import GameStuckError
from module.hazeworld.assets import (CORE_BTN_SWEEP, CORE_DIALOG_MAX,
                                     CORE_DIALOG_PLUS, CORE_DIALOG_START,
                                     CORE_DIALOG_TITLE, CORE_RESULT_CONFIRM,
                                     CORE_TYPE_ARMOR, CORE_TYPE_ATTACK,
                                     CORE_TYPE_BURST, CORE_TYPE_CRIT,
                                     CORE_TYPE_LIFE)
from module.hazeworld.hazeworld_ui import HazeworldUI, page_core
from module.logger import logger
from module.ocr.ocr import Digit, DigitCounter

# Config value of HazeworldCore_<weekday> -> sidebar button. Keep in sync with
# the option list of the day keys in argument.yaml.
CORE_TYPES = {
    'Life': CORE_TYPE_LIFE,
    'Attack': CORE_TYPE_ATTACK,
    'Armor': CORE_TYPE_ARMOR,
    'Critical': CORE_TYPE_CRIT,
    'Burst': CORE_TYPE_BURST,
}

# `datetime.weekday()` is 0 on Monday, so this is the config key of each day.
CORE_WEEKDAY_KEYS = [
    'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday',
]

# Stamina bar at the top right of the page, `21/260`, and the stamina a sortie
# costs, the number on the orange button at the bottom right. Both are read
# live: the cost follows the stage the player picked, and nothing on the page
# says "not enough stamina", the game only complains after the sweep is asked
# for. The digits are a soft white, a pure white letter colour drops one of them
# now and then, and a crop that is much wider than the text reads worse.
CORE_STAMINA = DigitCounter(
    Button(area=(1128, 24, 1205, 44), color=(), button=(1128, 24, 1205, 44),
           name='CORE_STAMINA'),
    letter=(240, 240, 240),
    threshold=128,
)
CORE_COST = Digit(
    Button(area=(1178, 650, 1225, 674), color=(), button=(1178, 650, 1225, 674),
           name='CORE_COST'),
    letter=(240, 240, 240),
    threshold=128,
)

# A two digit number loses a digit once in a while (measured: `21` read as `2`),
# and a lost digit only ever reads lower. A "not enough stamina" verdict costs a
# whole day of farming, so it is read twice before it is believed.
STAMINA_READS = 2

# The sweep dialog ignores taps faster than this, and the plus button needs the
# count display to catch up before the next tap lands.
COUNT_INTERVAL = 0.4

# One sweep animates for about a second, and the dialog allows as many as the
# stamina pays for (20 at the moment of writing). The settlement is waited for
# with a local timer, the framework stuck timer is only 60s.
SETTLE_TIMEOUT = 300

# Opening the sweep dialog is a client side action, a missing dialog after this
# long means the sweep button did nothing (the stage is locked).
DIALOG_TIMEOUT = 30

# A sweep the stamina does not pay for closes the dialog and does nothing, so
# the page comes back with its sweep button and no settlement is ever shown.
# The settlement itself settles a run in about half a second (10 runs took 4.8s
# on a real sweep), but the window is generous: believing "nothing ran" too early
# would abandon a real sweep, while believing it too late only wastes a wait.
SETTLE_START = 30


class HazeworldCore(HazeworldUI):
    """
    Spend stamina on the core material stage of today.

    Which core type can be farmed changes every day, so each weekday has its own
    setting. A day set to `None` is skipped without touching the game.

    The stage inside the core page is not selected here, the game keeps the last
    one the player picked, which is also what the reference script does.

    The stamina is checked before the sweep is asked for: the game accepts a
    sweep it cannot pay for and then does nothing at all, which used to leave
    the task waiting for a settlement that never came.

    Pages:
        in: page_main
        out: page_main
    """

    def run(self):
        logger.hr('Core material sweep', level=1)
        core = self.core_of_today()
        if core is None:
            logger.info('No core type set for today, skip')
            self.config.task_delay(server_update=True)
            return

        self.ui_ensure(page_core)

        # Selecting the type comes first even though the stamina is read from
        # the page: the switch repaints the stage list and the cost of a run,
        # and the first frame after ui_ensure() is still the fade in, where no
        # number can be read.
        if self.core_select_type(core):
            self.core_sweep(self.core_run_count())

        self.ui_goto_main()

        # Daily task. Stamina regenerates at a rate that fills the cap once a
        # day, so there is nothing to gain from running more often.
        self.config.task_delay(server_update=True)

    def core_of_today(self):
        """
        The core type button configured for the current game day.

        Returns:
            Button or None: None when today is set to `None` (skip).
        """
        # The game day rolls over at the server update hour, so a run at 04:00
        # still belongs to the day before.
        hour = int(str(self.config.Scheduler_ServerUpdate).split(':')[0])
        day = (datetime.now() - timedelta(hours=hour)).weekday()
        key = CORE_WEEKDAY_KEYS[day]
        value = getattr(self.config, f'HazeworldCore_{key}')

        if value not in CORE_TYPES:
            logger.info(f'Core type of {key} is {value}, nothing to farm')
            return None

        return CORE_TYPES[value]

    def core_select_type(self, button):
        """
        Switch the left sidebar to the given core type.

        Args:
            button (Button): Sidebar button of the type.

        Returns:
            bool: If the type is selected.
        """
        logger.hr(f'Core type {button.name}', level=2)
        # Switching reloads the stage list and the detail panel. Only the
        # selected block has a gold bar on its left edge, and the bar of the
        # previous type stays gold while the new one animates in, so waiting
        # for our own bar is the only positive way to know the switch landed.
        self.interval_clear(button)
        self.device.click(button)
        if self.appear_settled(button, timeout=8, offset=None, skip_first_screenshot=False):
            return True

        logger.warning(f'Core type {button.name} did not become selected')
        return False

    def core_stamina(self):
        """
        Read how much stamina is left and what one run costs.

        Reads the page twice while the numbers say "not enough": a lost digit
        reads lower, never higher, so the higher of the two reads is the closer
        one. The fast path is a single read, and a read that already pays for a
        run ends the loop as well.

        Returns:
            tuple(int or None, int or None): Stamina left and cost of one run,
                None for a number that could not be read. An empty bar is a 0,
                not a None, the two mean different things.
        """
        current, cost = None, None
        for _ in range(STAMINA_READS):
            left, price = self.core_ocr_stamina()
            if left is not None and (current is None or left > current):
                current, cost = left, price
            if current is not None and cost is not None and current >= cost:
                break
            self.device.screenshot()

        return current, cost

    def core_ocr_stamina(self):
        """
        One read of the stamina bar and of the sortie cost.

        Returns:
            tuple(int or None, int or None): Stamina left and cost of one run,
                None for a number that could not be read.
        """
        left, _, total = CORE_STAMINA.ocr(self.device.image)
        cost = CORE_COST.ocr(self.device.image)

        if total <= 0:
            # `DigitCounter` returns zeros when it cannot make out the pair.
            return None, None
        return left, cost

    def core_run_count(self):
        """
        How many runs to sweep with the stamina that is left.

        The game does not refuse a sweep it cannot pay for, it just closes the
        dialog and does nothing, so this is decided before the dialog is opened.
        A count larger than the stamina pays for is reduced instead of being
        refused as a whole.

        Returns:
            int or None: Runs to start, 0 for "as many as the stamina allows",
                None when the stamina does not pay for a single run.
        """
        current, cost = self.core_stamina()

        if current is None or cost is None or cost <= 0:
            # An unreadable number must not cost a day of farming. The sweep
            # itself is checked afterwards, so a wrong guess cannot hang.
            logger.warning('Cannot read the stamina, sweep anyway')
            return int(self.config.HazeworldCore_SweepCount)

        runs = current // cost
        if runs <= 0:
            logger.info(f'Not enough stamina to sweep: {current} left, {cost} a run')
            return None
        logger.info(f'Stamina {current} left, {cost} a run, {runs} run(s) at most')

        count = int(self.config.HazeworldCore_SweepCount)
        if count <= 0:
            return 0
        if count > runs:
            logger.info(f'Sweep count {count} is beyond the stamina, sweep {runs}')
            return runs
        return count

    def core_sweep(self, count):
        """
        Sweep the stage and wait out the settlement.

        Args:
            count (int or None): Runs to sweep, 0 for "as many as the stamina
                allows", None when the stamina does not pay for a single run
                (the reason is logged by `core_run_count()`).

        Pages:
            in: page_core
            out: page_core

        Returns:
            bool: If a sweep ran.
        """
        if count is None:
            return False
        if not self.core_sweep_start(count):
            return False
        return self.core_sweep_wait()

    def core_sweep_start(self, count):
        """
        Open the sweep dialog, set the run count and press start.

        Args:
            count (int): Runs to sweep, 0 for "as many as the stamina allows".

        Pages:
            in: page_core
            out: page_core (settlement running, or refused)

        Returns:
            bool: If the start button was pressed.
        """
        logger.hr('Sweep start', level=2)
        timeout = Timer(DIALOG_TIMEOUT).start()
        interval = Timer(COUNT_INTERVAL)
        clicked = 0
        prepared = False

        while 1:
            self.device.screenshot()

            if self.appear(CORE_DIALOG_TITLE, offset=(20, 20)):
                if not prepared:
                    if count == 0:
                        # "MAX" fills the dialog with as many runs as the
                        # stamina pays for.
                        logger.info('Sweep every run the stamina allows')
                        self.device.click(CORE_DIALOG_MAX)
                        prepared = True
                        interval.reset()
                        continue
                    if clicked < count - 1:
                        if interval.reached():
                            # The dialog opens on 1, so N runs need N-1 taps.
                            self.device.click(CORE_DIALOG_PLUS)
                            clicked += 1
                            interval.reset()
                        continue
                    logger.info(f'Sweep {count} runs')
                    prepared = True
                    interval.reset()
                    continue

                # Give the count display a moment to catch up, a start pressed
                # in the same frame still uses the old value.
                if not interval.reached():
                    continue
                if self.appear_then_click(CORE_DIALOG_START, offset=(20, 20), interval=3):
                    return True
                continue

            if self.appear_then_click(CORE_BTN_SWEEP, offset=(20, 20), interval=2):
                timeout.start()
                continue

            if timeout.reached():
                logger.warning('Sweep dialog did not open, the stage may be locked')
                return False

    def core_sweep_wait(self):
        """
        Wait until the settlement offers its confirm button.

        The settlement plays a short animation per run and the screen only
        changes once per second, which the framework counts as stuck after 60s,
        so the stuck record is cleared on every frame. The confirm button only
        shows up at the end, the skip button of the running animation sits in
        the same place but has a different label.

        A sweep that the game refuses (the stamina ran out between the check and
        the press) leaves the page behind with its sweep button and never shows
        a settlement. That state is not an error, it is reported as "nothing
        ran" so the task can end cleanly.

        Pages:
            in: page_core (settlement running)
            out: page_core

        Returns:
            bool: If a sweep ran and was settled.
        """
        logger.hr('Sweep settlement', level=2)
        timeout = Timer(SETTLE_TIMEOUT).start()
        start = Timer(SETTLE_START).start()

        while 1:
            self.device.screenshot()
            self.device.stuck_record_clear()

            if self.appear_then_click(CORE_RESULT_CONFIRM, offset=(20, 20), interval=2):
                logger.info('Sweep settled')
                return True

            if start.reached() and self.appear(CORE_BTN_SWEEP, offset=(20, 20)):
                logger.warning('Sweep did not start, not enough stamina?')
                return False

            if timeout.reached():
                raise GameStuckError('Sweep settlement did not finish')
