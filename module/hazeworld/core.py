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

# Config value of HazeworldCore_Core -> sidebar button. Keep in sync with the
# option list of `Core` in argument.yaml.
CORE_TYPES = {
    'Life': CORE_TYPE_LIFE,
    'Attack': CORE_TYPE_ATTACK,
    'Armor': CORE_TYPE_ARMOR,
    'Critical': CORE_TYPE_CRIT,
    'Burst': CORE_TYPE_BURST,
}

# The sweep dialog ignores taps faster than this, and the plus button needs the
# count display to catch up before the next tap lands.
COUNT_INTERVAL = 0.4

# One sweep animates for about a second, and the dialog allows as many as the
# stamina pays for (20 at the moment of writing). The settlement is waited for
# with a local timer, the framework stuck timer is only 60s.
SETTLE_TIMEOUT = 300

# Opening the sweep dialog is a client side action, a missing dialog after this
# long means the sweep button did nothing (no stamina, or the stage is locked).
DIALOG_TIMEOUT = 30


class HazeworldCore(HazeworldUI):
    """
    Spend stamina on a core material stage with the sweep button.

    The stage inside the core page is not selected here, the game keeps the last
    one the player picked, which is also what the reference script does. Which
    core type to farm is configurable.

    Pages:
        in: page_main
        out: page_main
    """

    def run(self):
        logger.hr('Core material sweep', level=1)
        self.ui_ensure(page_core)
        self.core_select_type()

        if self.core_sweep():
            self.ui_goto_main()

        # Daily task. Stamina regenerates at a rate that fills the cap once a
        # day, so there is nothing to gain from running more often.
        self.config.task_delay(server_update=True)

    def core_select_type(self):
        """
        Switch the left sidebar to the configured core type.

        Returns:
            bool: If the type is selected.
        """
        button = CORE_TYPES.get(self.config.HazeworldCore_Core)
        if button is None:
            logger.warning(f'Unknown core type {self.config.HazeworldCore_Core}, use Life')
            button = CORE_TYPE_LIFE

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

    def core_sweep(self):
        """
        Take every run the stamina allows and wait out the settlement.

        Pages:
            in: page_core
            out: page_core

        Returns:
            bool: If a sweep was started.
        """
        if not self.core_sweep_start():
            return False
        self.core_sweep_wait()
        return True

    def core_sweep_start(self):
        """
        Open the sweep dialog, set the run count and press start.

        Pages:
            in: page_core
            out: page_core (settlement running)

        Returns:
            bool: If the start button was pressed.
        """
        logger.hr('Sweep start', level=2)
        count = int(self.config.HazeworldCore_SweepCount)
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
                logger.warning('Sweep dialog did not open, out of stamina?')
                return False

    def core_sweep_wait(self):
        """
        Wait until the settlement offers its confirm button.

        The settlement plays a short animation per run and the screen only
        changes once per second, which the framework counts as stuck after 60s,
        so the stuck record is cleared on every frame. The confirm button only
        shows up at the end, the skip button of the running animation sits in
        the same place but has a different label.

        Pages:
            in: page_core (settlement running)
            out: page_core
        """
        logger.hr('Sweep settlement', level=2)
        timeout = Timer(SETTLE_TIMEOUT).start()

        while 1:
            self.device.screenshot()
            self.device.stuck_record_clear()

            if self.appear_then_click(CORE_RESULT_CONFIRM, offset=(20, 20), interval=2):
                logger.info('Sweep settled')
                return True

            if timeout.reached():
                raise GameStuckError('Sweep settlement did not finish')
