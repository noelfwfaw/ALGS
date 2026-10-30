import os
import re
import threading
import time
from datetime import datetime, timedelta

import inflection
from cached_property import cached_property

from module.base.decorator import del_cached_property
from module.config.config import AlasConfig, TaskEnd
from module.config.deep import deep_get, deep_set
from module.exception import *
from module.logger import logger


# Seconds within which a second session claim is skipped. A drain that is
# immediately followed by `Restart` would otherwise claim twice for the same
# nothing; a real session gap is hours.
SESSION_CLAIM_INTERVAL = 10 * 60


class GameScheduler:
    """
    Generic task scheduler.

    A task is a method of this class whose name is the task name in
    `module/config/argument/task.yaml` converted with `inflection.underscore`.
    Game specific tasks are added by subclassing or by appending methods here.

    The scheduler itself knows nothing about any game: it only reads
    `Scheduler.NextRun` / `Scheduler.Enable` from the user config and calls the
    matching method.
    """

    stop_event: threading.Event = None

    # When the queue last drained and the session wide rewards were taken, used
    # by `session_claim()` to skip a repeated claim right after a restart.
    session_claim_time: datetime = None

    # Whether this process has already brought `self.game` to the front.
    # `app_is_running()` only says the process exists: a game left in the
    # background by an earlier run is "running" while the screen shows the other
    # game, and skipping the launch then leaves the task waiting for a page that
    # never comes (measured 2026-10-27: `LostswordMain` sat on a blank wait for
    # ten minutes because the Lostsword process was alive in the background).
    game_in_foreground: bool = False

    # Namespace -> (module, class name) of the game UI class, filled by the
    # subclass. Empty in a single game setup, which turns every game switch
    # below into a no-op.
    games = {}

    def __init__(self, config_name='alas'):
        logger.hr('Start', level=0)
        self.config_name = config_name
        # Skip first restart
        self.is_first_task = True
        # Namespace of the game currently on screen, None until the first task
        # asks for one (then it is taken from the asset namespace).
        self.game = None
        # Failure count of tasks
        # Key: str, task name, value: int, failure count
        self.failure_record = {}

    @cached_property
    def config(self):
        try:
            config = AlasConfig(config_name=self.config_name)
            return config
        except RequestHumanTakeover:
            logger.critical('Request human takeover')
            exit(1)
        except Exception as e:
            logger.exception(e)
            exit(1)

    @cached_property
    def device(self):
        try:
            from module.device.device import Device
            device = Device(config=self.config)
            return device
        except RequestHumanTakeover:
            logger.critical('Request human takeover')
            exit(1)
        except Exception as e:
            logger.exception(e)
            exit(1)

    def run(self, command, skip_first_screenshot=False):
        """
        Run a task and handle every exception at the top level.

        Args:
            command (str): Snake case task name, a method of this class.
            skip_first_screenshot (bool):

        Returns:
            bool: If the task succeed.
        """
        try:
            if not skip_first_screenshot:
                self.device.screenshot()
            self.__getattribute__(command)()
            return True
        except TaskEnd:
            return True
        except GameNotRunningError as e:
            logger.warning(e)
            self.config.task_call('Restart')
            return False
        except (GameStuckError, GameTooManyClickError) as e:
            logger.error(e)
            self.save_error_log()
            logger.warning(f'Game stuck, {self.device.package} will be restarted in 10 seconds')
            logger.warning('If you are playing by hand, please stop the script')
            self.config.task_call('Restart')
            self.device.sleep(10)
            return False
        except GameBugError as e:
            logger.warning(e)
            self.save_error_log()
            logger.warning('An error has occurred in game client, unable to handle')
            logger.warning(f'Restarting {self.device.package} to fix it')
            self.config.task_call('Restart')
            self.device.sleep(10)
            return False
        except ScriptError as e:
            logger.exception(e)
            logger.critical('This is likely to be a mistake of developers, but sometimes just random issues')
            exit(1)
        except RequestHumanTakeover:
            logger.critical('Request human takeover')
            exit(1)
        except GamePageUnknownError:
            logger.critical('Game page unknown')
            self.save_error_log()
            exit(1)
        except Exception as e:
            logger.exception(e)
            self.save_error_log()
            exit(1)

    def save_error_log(self):
        """
        Save last 60 screenshots in ./log/error/<timestamp>
        Save logs to ./log/error/<timestamp>/log.txt
        """
        from module.base.utils import save_image

        if self.config.Error_SaveError:
            if not os.path.exists('./log/error'):
                os.mkdir('./log/error')
            folder = f'./log/error/{int(time.time() * 1000)}'
            logger.warning(f'Saving error: {folder}')
            os.mkdir(folder)
            for data in self.device.screenshot_deque:
                image_time = datetime.strftime(data['time'], '%Y-%m-%d_%H-%M-%S-%f')
                save_image(data['image'], f'{folder}/{image_time}.png')
            with open(logger.log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                start = 0
                for index, line in enumerate(lines):
                    line = line.strip(' \r\t\n')
                    if re.match('^═{15,}$', line):
                        start = index
                lines = lines[start - 2:]
            with open(f'{folder}/log.txt', 'w', encoding='utf-8') as f:
                f.writelines(lines)

    def game_ui(self):
        """
        UI instance of the game currently bound to the config.

        The scheduler subclass exposes its game UI class as `ui_class`, which
        is how the framework walks pages on its own. Without it the base UI is
        used, which has no `page_main`.

        Returns:
            UI:
        """
        from module.ui.ui import UI

        ui_class = getattr(self, 'ui_class', None) or UI
        return ui_class(self.config, device=self.device)

    def restart(self):
        """
        Restart the current game app and wait until it is playable.

        Pages:
            in: any
            out: page_main
        """
        logger.hr('Restart app', level=1)
        self.device.app_stop()
        self.start()
        # Restart is a daily task, it must push its own next run, otherwise
        # SuccessInterval is 0 and the scheduler picks it again immediately.
        self.config.task_delay(server_update=True)

    def task_game(self, task):
        """
        Game a task belongs to.

        Every game names its tasks after its own namespace (`Hazeworld*`,
        `Lostsword*`), so the prefix is the mapping and a new task files itself.
        Framework tasks (`Restart`, `start`, `goto_main`) match nothing: they act
        on whichever game is on screen.

        Args:
            task (str): Task name, as written in `task.yaml`.

        Returns:
            str: Asset namespace, or None for a framework task.
        """
        if not task:
            return None
        name = task.lower()
        # Longest first, so a namespace that is a prefix of another cannot win.
        for game in sorted(self.games, key=len, reverse=True):
            if name.startswith(game):
                return game
        return None

    def peek_next_game(self):
        """
        Game of the next task that has one and is already due.

        Used by `Restart` so that it boots the game the queue is about to use,
        instead of the one that happened to run last night. Tasks that are only
        waiting for their next run are not considered: restarting a game an hour
        before it is used again would just be a cold boot for nothing.

        Returns:
            str: Asset namespace, or None.
        """
        for func in self.config.pending_task:
            game = self.task_game(func.command)
            if game is not None:
                return game
        return None

    def game_alive(self, package):
        """
        Whether a package has a process on the device, foreground or not.

        `app_is_running()` answers a different question: it compares the
        *foreground* package with `device.package`, so a game left in the
        background reads as "not running" while its process is very much alive.
        That is the difference between "the screen shows another app" and "the
        game is gone", and only the second one is safe to skip a force-stop on.

        Args:
            package (str): Package name.

        Returns:
            bool:
        """
        if not package:
            return False
        try:
            return bool(self.device.adb_shell(['pidof', package]).strip())
        except Exception as e:
            # A dropped adb connection, or `pidof` missing on an old Android
            # build, is not a reason to leave a game running: stop it anyway.
            logger.info(f'Cannot tell whether {package} is running: {e}')
            return True

    def stop_game(self, package):
        """
        Force-stop one package if its process is still alive.

        Args:
            package (str): Package name.

        Returns:
            bool: If a running process was stopped.
        """
        if not self.config.Error_HandleError:
            logger.warning('No app stop, because HandleError disabled')
            return False
        if not self.game_alive(package):
            return False
        logger.info(f'Stop game: {package}')
        self.device.app_stop_adb(package)
        return True

    def switch_game(self, game, boot=True):
        """
        Put the given game in front and make its namespace the active one.

        Switching is four steps in a fixed order: stop the old game, repoint the
        package, switch the asset namespace (which drops the images and OCR
        models of the old game), then clear the click/stuck records. Recognising
        anything before the namespace switch would compare the new screen with
        the old game's templates.

        Stopping the old game is part of switching, and it is *not* the same
        thing as `Optimization_WhenTaskQueueEmpty`: that option decides whether
        the game is left open while the queue is empty and waiting for the next
        task (`stay_there` / `goto_main`) or closed (`close_game`). Once a task
        of another game is due, the old game has to go either way, so this never
        assumes the previous stop happened and never asks whether the game is in
        the foreground.

        Two games are never left running: the low memory killer picks one of them
        on a phone-sized device, and it picks the foreground one often enough to
        look like a random crash.

        Args:
            game (str): Asset namespace, None for "whatever is on screen".
            boot (bool): Launch the game when it is not running. False lets the
                caller do it, which is what `Restart` wants.

        Returns:
            bool: If the game changed.
        """
        from module.config.server import set_server, to_package, to_server

        if self.game is None:
            # Nothing switched yet in this process. The game on screen is the one
            # the device was bound to at start up (`Emulator_PackageName`), which
            # is not necessarily the default asset namespace: a config that owns a
            # single game (its own emulator, its own package) would otherwise
            # "switch" to the game it is already on, force-stop a healthy client
            # and cold start it for nothing.
            self.game = to_server(self.device.package)

        if game is not None and game != self.game:
            package = to_package(game)
            if package is None:
                raise ScriptError(
                    f'Game `{game}` has no package, register it in module/config/server.py')

            logger.hr(f'Switch game: {self.game} -> {game}', level=1)
            # The bound package is the game that just ran; the loop after it
            # catches a third game left behind by anything else. The target game
            # is never stopped: if it is running in the background, `start()`
            # brings that process to the front instead of a cold boot.
            old_package = self.device.package
            self.stop_game(old_package)
            for name in self.games:
                other = to_package(name)
                if other and other not in (old_package, package):
                    self.stop_game(other)
            # `app_start` / `app_stop` / `app_is_running` are all relative to it.
            self.device.package = package
            set_server(game)
            self.game = game
            # Nothing has been shown yet for the new game.
            self.game_in_foreground = False
            self.device.stuck_record_clear()
            self.device.click_record_clear()
        elif not boot:
            return False
        elif self.game_in_foreground and self.device.app_is_running():
            return False
        else:
            logger.info(f'Game `{self.game}` is not in the foreground, start it')

        if boot:
            try:
                self.start()
            except (GameStuckError, GameNotRunningError, GameTooManyClickError) as e:
                # A game that does not come up is a task failure, not a reason to
                # kill the scheduler: the task below runs into the same wall right
                # away, and the usual handling takes it from there (archive,
                # `Restart`, three strikes).
                logger.warning(f'Game `{self.game}` did not come up: {e}')
        return True

    def start(self):
        """
        Start the current game app and wait until it is playable.

        `app_start()` also brings a game that is only running in the background
        to the front, so the flag below is set even when nothing was launched.

        Pages:
            in: any
            out: page_main
        """
        self.game_ui().app_start()
        self.game_in_foreground = True

    def goto_main(self):
        """
        Go back to the home page of the current game.

        Pages:
            in: any
            out: page_main
        """
        self.game_ui().ui_goto_main()

    def wait_until(self, target):
        """
        Wait until the given datetime.

        Args:
            target (datetime.datetime):

        Returns:
            bool: True if the wait finished, False if the config was reloaded.
        """
        if not isinstance(target, datetime):
            target = datetime.strptime(target, '%Y-%m-%d %H:%M:%S')
        target = target + timedelta(seconds=1)
        # Baseline for should_reload(). Without it the config written by the
        # previous task looks newer than the baseline forever, should_reload()
        # returns True on every wake up and the scheduler spins in this loop.
        self.config.start_watching()

        while 1:
            if datetime.now() > target:
                return True
            if self.stop_event is not None:
                if self.stop_event.is_set():
                    logger.info('Update event detected')
                    logger.info(f'[{self.config_name}] exited. Reason: Update')
                    exit(0)
            time.sleep(5)
            if self.config.should_reload():
                return False

    def get_next_task(self):
        """
        Returns:
            str: Name of the next task.
        """
        while 1:
            task = self.config.get_next()
            self.config.task = task
            self.config.bind(task)

            from module.base.resource import release_resources
            if self.config.task.command != 'Alas':
                release_resources(next_task=task.command)

            if task.next_run > datetime.now():
                logger.info(f'Wait until {task.next_run} for task `{task.command}`')
                self.is_first_task = False
                # Nothing is queued any more: this is the end of the session for
                # the game that is on screen. The session wide claims (mission
                # list, battle pass) are taken here rather than at launch, so
                # they never sit in front of the tasks the user queued up.
                self.session_claim()
                method = self.config.Optimization_WhenTaskQueueEmpty
                if method == 'close_game':
                    logger.info('Close game during wait')
                    self.device.app_stop()
                    release_resources()
                    self.device.release_during_wait()
                    if not self.wait_until(task.next_run):
                        del_cached_property(self, 'config')
                        continue
                    if task.command != 'Restart':
                        self.config.task_call('Restart')
                        del_cached_property(self, 'config')
                        continue
                elif method == 'goto_main':
                    logger.info('Goto main page during wait')
                    self.run('goto_main')
                    release_resources()
                    self.device.release_during_wait()
                    if not self.wait_until(task.next_run):
                        del_cached_property(self, 'config')
                        continue
                elif method == 'stay_there':
                    logger.info('Stay there during wait')
                    release_resources()
                    self.device.release_during_wait()
                    if not self.wait_until(task.next_run):
                        del_cached_property(self, 'config')
                        continue
                else:
                    logger.warning(f'Invalid Optimization_WhenTaskQueueEmpty: {method}, fallback to stay_there')
                    release_resources()
                    self.device.release_during_wait()
                    if not self.wait_until(task.next_run):
                        del_cached_property(self, 'config')
                        continue
            break

        AlasConfig.is_hoarding_task = False
        return task.command

    def session_claim(self):
        """
        Take the rewards of the game on screen, once the queue is drained.

        Only the game that is actually running is asked: when the emulator is
        off, or the last task belonged to the other game, there is nothing to
        claim and starting a game just to claim would defeat the purpose.

        A drain can happen twice in a row - the scheduler closes the game after
        the first one, waits, then boots it again for `Restart`, and the queue is
        empty right after that boot as well. Claiming costs up to a minute of
        page walking, so a claim made moments ago is not repeated; a real new
        session is hours apart, which the window covers easily.

        Returns:
            bool: If a game handled it.
        """
        now = datetime.now()
        if self.session_claim_time is not None and \
                (now - self.session_claim_time).total_seconds() < SESSION_CLAIM_INTERVAL:
            logger.info('Session claim done recently, skip')
            return False

        try:
            if not self.device.app_is_running():
                return False
            logger.hr('Session claim', level=1)
            self.session_claim_time = now
            return self.game_ui().handle_session_claim()
        except Exception as e:
            # The queue is drained either way; a claim that fails must not turn
            # into a task failure or keep the game from being closed.
            logger.warning(f'Session claim failed, ignored: {e}')
            return False

    def loop(self):
        """
        Scheduler main loop: pick the next task, run it, record the result.
        """
        logger.set_file_logger(self.config_name)
        logger.info(f'Start scheduler loop: {self.config_name}')

        while 1:
            # Check update event from GUI
            if self.stop_event is not None:
                if self.stop_event.is_set():
                    logger.info("Update event detected")
                    logger.info(f"[{self.config_name}] exited.")
                    break
            # Get task
            task = self.get_next_task()
            # Init device and change server
            _ = self.device
            self.device.config = self.config
            # Bring the game that owns this task to the front. A framework task
            # has no game of its own, so `Restart` prepares the one the queue is
            # about to use and leaves the launching to itself.
            game = self.task_game(task)
            if game is not None:
                self.switch_game(game)
            elif task == 'Restart':
                self.switch_game(self.peek_next_game(), boot=False)
            # Skip first restart
            if self.is_first_task and task == 'Restart':
                logger.info('Skip task `Restart` at scheduler start')
                self.config.task_delay(server_update=True)
                del_cached_property(self, 'config')
                continue

            # Run
            logger.info(f'Scheduler: Start task `{task}`')
            self.device.stuck_record_clear()
            self.device.click_record_clear()
            logger.hr(task, level=0)
            success = self.run(inflection.underscore(task))
            logger.info(f'Scheduler: End task `{task}`')
            self.is_first_task = False

            # Check failures
            failed = deep_get(self.failure_record, keys=task, default=0)
            failed = 0 if success else failed + 1
            deep_set(self.failure_record, keys=task, value=failed)
            if failed >= 3:
                logger.critical(f"Task `{task}` failed 3 or more times.")
                logger.critical("Possible reason #1: You haven't used it correctly. "
                                "Please read the help text of the options.")
                logger.critical("Possible reason #2: There is a problem with this task. "
                                "Please contact developers or try to fix it yourself.")
                logger.critical('Request human takeover')
                exit(1)

            if success:
                del_cached_property(self, 'config')
                continue
            elif self.config.Error_HandleError:
                del_cached_property(self, 'config')
                continue
            else:
                break



if __name__ == '__main__':
    scheduler = GameScheduler()
    scheduler.loop()
