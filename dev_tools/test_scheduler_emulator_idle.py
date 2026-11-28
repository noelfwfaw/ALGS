import threading
import unittest
from collections import namedtuple
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import alas
from module.config.watcher import ConfigWatcher
from module.exception import EmulatorNotRunningError


Task = namedtuple('Task', 'command next_run')


class FakeConfig:
    def __init__(self, tasks, method='close_emulator', events=None):
        self.tasks = list(tasks)
        self.Optimization_WhenTaskQueueEmpty = method
        self.events = events if events is not None else []
        self.task = None
        self.task_calls = []
        self.watch_starts = 0
        self.reload = False
        self.connection_dirty = False
        self.config_name = 'idle-test'
        self.task_delays = []

    def get_next(self, prefer=None):
        return self.tasks.pop(0)

    def bind(self, task):
        pass

    def start_watching(self):
        self.watch_starts += 1
        self.connection_dirty = False
        self.events.append('watch')

    def should_reload(self):
        return self.reload or self.connection_dirty

    def task_call(self, task):
        self.task_calls.append(task)

    def task_delay(self, target):
        self.task_delays.append(target)
        self.events.append('delay')
        self.tasks.insert(0, self.task._replace(next_run=target))


class FakeDevice:
    def __init__(self, events=None, stop_result=True):
        self.events = events if events is not None else []
        self.config = None
        self.stop_result = stop_result
        self.app_stop_error = None
        self.emulator_stop_error = None

    def app_stop(self):
        self.events.append('app_stop')
        if self.app_stop_error is not None:
            raise self.app_stop_error

    def release_during_wait(self):
        self.events.append('release_wait')

    def emulator_stop_and_wait(self, deadline):
        self.events.append('emulator_stop')
        if self.emulator_stop_error is not None:
            raise self.emulator_stop_error
        return self.stop_result


class SchedulerEmulatorIdleTest(unittest.TestCase):
    def make_scheduler(self, config, device=None):
        scheduler = alas.GameScheduler('idle-test')
        scheduler.__dict__['config'] = config
        if device is not None:
            scheduler.__dict__['device'] = device
        scheduler.game = None
        scheduler.game_in_foreground = False
        return scheduler

    def release_resources(self, *args, **kwargs):
        if kwargs:
            self.events.append('release_next')
        else:
            self.events.append('release')

    def test_long_idle_without_device_waits_without_booting_or_restart(self):
        self.events = []
        task = Task('HazeworldMain', datetime.now() + timedelta(seconds=600))
        config = FakeConfig([task], events=self.events)
        scheduler = self.make_scheduler(config)
        scheduler.session_claim = Mock()

        def offline_device(**kwargs):
            raise EmulatorNotRunningError('offline')

        def wait(target, baseline_ready):
            self.assertFalse(config.should_reload())
            self.events.append('wait')
            return True

        scheduler.wait_until = Mock(side_effect=wait)
        with patch('module.device.device.Device', side_effect=offline_device) as device_class, \
                patch('module.base.resource.release_resources', side_effect=self.release_resources):
            self.assertEqual('HazeworldMain', scheduler.get_next_task())

        device_class.assert_called_once_with(config=config, start_emulator=False)
        scheduler.session_claim.assert_not_called()
        scheduler.wait_until.assert_called_once_with(task.next_run, baseline_ready=True)
        self.assertEqual(1, config.watch_starts)
        self.assertEqual([], config.task_calls)
        self.assertNotIn('device', scheduler.__dict__)
        self.assertEqual(['release_next', 'watch', 'wait'], self.events)

    def test_short_idle_without_device_does_not_create_one(self):
        task = Task('HazeworldMain', datetime.now() + timedelta(seconds=60))
        config = FakeConfig([task])
        scheduler = self.make_scheduler(config)
        scheduler.session_claim = Mock()
        scheduler.wait_until = Mock(return_value=True)

        with patch('module.device.device.Device') as device_class, \
                patch('module.base.resource.release_resources') as release:
            self.assertEqual('HazeworldMain', scheduler.get_next_task())

        device_class.assert_not_called()
        scheduler.session_claim.assert_not_called()
        scheduler.wait_until.assert_called_once_with(task.next_run, baseline_ready=True)
        self.assertEqual(1, config.watch_starts)
        self.assertEqual([], config.task_calls)
        self.assertNotIn('device', scheduler.__dict__)
        release.assert_any_call()

    def test_long_idle_existing_device_claims_then_stops_in_order(self):
        self.events = []
        task = Task('HazeworldMain', datetime.now() + timedelta(seconds=600))
        config = FakeConfig([task], events=self.events)
        device = FakeDevice(self.events)
        scheduler = self.make_scheduler(config, device)
        scheduler.game = 'hazeworld'
        scheduler.game_in_foreground = True
        scheduler.session_claim = Mock(side_effect=lambda: self.events.append('claim'))
        scheduler.wait_until = Mock(side_effect=lambda *args, **kwargs: self.events.append('wait') or True)

        with patch('module.base.resource.release_resources', side_effect=self.release_resources):
            self.assertEqual('HazeworldMain', scheduler.get_next_task())

        self.assertIs(config, device.config)
        self.assertEqual(
            ['release_next', 'watch', 'claim', 'app_stop', 'release', 'release_wait',
             'emulator_stop', 'wait'],
            self.events,
        )
        self.assertEqual([], config.task_calls)
        self.assertNotIn('device', scheduler.__dict__)
        self.assertIsNone(scheduler.game)
        self.assertFalse(scheduler.game_in_foreground)

    def test_app_stop_failure_still_attempts_emulator_stop(self):
        task = Task('HazeworldMain', datetime.now() + timedelta(seconds=600))
        config = FakeConfig([task])
        device = FakeDevice()
        device.app_stop_error = RuntimeError('app stop failed')
        scheduler = self.make_scheduler(config, device)
        scheduler.session_claim = Mock()
        scheduler.wait_until = Mock(return_value=True)

        with patch('module.base.resource.release_resources'):
            self.assertEqual('HazeworldMain', scheduler.get_next_task())

        self.assertEqual(['app_stop', 'release_wait', 'emulator_stop'], device.events)
        self.assertNotIn('device', scheduler.__dict__)

    def test_unconfirmed_or_failed_stop_falls_back_to_wait_and_drops_device(self):
        for stop_result, stop_error in ((False, None), (True, RuntimeError('stop failed'))):
            with self.subTest(stop_result=stop_result, stop_error=stop_error):
                task = Task('HazeworldMain', datetime.now() + timedelta(seconds=600))
                config = FakeConfig([task])
                device = FakeDevice(stop_result=stop_result)
                device.emulator_stop_error = stop_error
                scheduler = self.make_scheduler(config, device)
                scheduler.game = 'hazeworld'
                scheduler.game_in_foreground = True
                scheduler.session_claim = Mock()
                scheduler.wait_until = Mock(return_value=True)

                with patch('module.base.resource.release_resources'):
                    self.assertEqual('HazeworldMain', scheduler.get_next_task())

                scheduler.wait_until.assert_called_once_with(task.next_run, baseline_ready=True)
                self.assertNotIn('device', scheduler.__dict__)
                self.assertIsNone(scheduler.game)
                self.assertFalse(scheduler.game_in_foreground)

    def test_online_temp_device_is_used_without_claim(self):
        self.events = []
        task = Task('HazeworldMain', datetime.now() + timedelta(seconds=600))
        config = FakeConfig([task], events=self.events)
        device = FakeDevice(self.events)
        scheduler = self.make_scheduler(config)
        scheduler.session_claim = Mock()

        def connect(**kwargs):
            self.events.append('connect')
            return device

        def wait(target, baseline_ready):
            self.assertFalse(config.should_reload())
            self.events.append('wait')
            return True

        scheduler.wait_until = Mock(side_effect=wait)
        with patch('module.device.device.Device', side_effect=connect) as device_class, \
                patch('module.base.resource.release_resources', side_effect=self.release_resources):
            self.assertEqual('HazeworldMain', scheduler.get_next_task())

        device_class.assert_called_once_with(config=config, start_emulator=False)
        scheduler.session_claim.assert_not_called()
        self.assertEqual(1, config.watch_starts)
        self.assertEqual(
            ['release_next', 'watch', 'connect', 'app_stop', 'release', 'release_wait',
             'emulator_stop', 'wait'],
            self.events,
        )
        self.assertNotIn('device', scheduler.__dict__)

    def test_config_update_during_temporary_connection_skips_shutdown(self):
        future = Task('HazeworldMain', datetime.now() + timedelta(seconds=600))
        due = Task('HazeworldShop', datetime.now() - timedelta(seconds=1))
        config = FakeConfig([future, due])
        scheduler = self.make_scheduler(config)
        device = FakeDevice()

        def connect(**kwargs):
            config.connection_dirty = True
            return device

        with patch('module.device.device.Device', side_effect=connect), \
                patch('module.base.resource.release_resources'), \
                patch('alas.del_cached_property') as drop:
            self.assertEqual('HazeworldShop', scheduler.get_next_task())

        self.assertEqual([], device.events)
        self.assertEqual(1, config.watch_starts)
        drop.assert_called_once_with(scheduler, 'config')

    def test_config_update_during_wait_reloads_and_reevaluates_without_restart(self):
        future = Task('HazeworldMain', datetime.now() + timedelta(seconds=600))
        due = Task('HazeworldShop', datetime.now() - timedelta(seconds=1))
        config = FakeConfig([future, due])
        device = FakeDevice()
        scheduler = self.make_scheduler(config, device)
        scheduler.session_claim = Mock()
        scheduler.wait_until = Mock(return_value=False)

        with patch('module.base.resource.release_resources'), \
                patch('alas.del_cached_property') as drop:
            self.assertEqual('HazeworldShop', scheduler.get_next_task())

        scheduler.wait_until.assert_called_once_with(future.next_run, baseline_ready=True)
        self.assertEqual(['device', 'config'], [call[0][1] for call in drop.call_args_list])
        self.assertEqual([], config.task_calls)

    def test_due_task_reconnects_after_shutdown_and_boots_its_game(self):
        task = Task('HazeworldMain', datetime.now() + timedelta(seconds=600))
        config = FakeConfig([task])
        old_device = FakeDevice()
        new_device = Mock()
        scheduler = self.make_scheduler(config, old_device)
        scheduler.stop_event = threading.Event()
        scheduler.game = 'resonance'
        scheduler.games = {'hazeworld': ('unused', 'unused')}
        scheduler.session_claim = Mock()
        scheduler.wait_until = Mock(return_value=True)
        scheduler.switch_game = Mock()

        def run(command):
            self.assertEqual('hazeworld_main', command)
            self.assertIs(new_device, scheduler.device)
            scheduler.switch_game.assert_called_once_with('hazeworld')
            scheduler.stop_event.set()
            return True

        scheduler.run = Mock(side_effect=run)
        with patch('module.device.device.Device', return_value=new_device) as device_class, \
                patch('module.base.resource.release_resources'), patch('alas.logger.set_file_logger'):
            scheduler._loop()

        self.assertEqual(['app_stop', 'release_wait', 'emulator_stop'], old_device.events)
        device_class.assert_called_once_with(config=config)
        self.assertEqual([], config.task_calls)

    def test_resonance_low_market_waits_then_good_market_boots(self):
        self.events = []
        due = Task('ResonanceTrade', datetime.now() - timedelta(seconds=1))
        config = FakeConfig([due], events=self.events)
        config.ResonanceTrade_MarketFilter = 'good'
        next_check = datetime.now() + timedelta(minutes=30)
        scheduler = self.make_scheduler(config)
        scheduler.games = {'resonance': ('unused', 'unused')}
        scheduler.stop_event = threading.Event()
        device = Mock()

        def precheck(_):
            self.events.append('precheck')
            return next_check if not config.task_delays else None

        def connect(**kwargs):
            self.events.append('device')
            return device

        scheduler.wait_until = Mock(side_effect=lambda *args, **kwargs: self.events.append('wait') or True)
        scheduler.switch_game = Mock(side_effect=lambda game: self.events.append('switch'))

        def run(command):
            self.events.append('run')
            scheduler.stop_event.set()
            return True

        scheduler.run = Mock(side_effect=run)
        with patch('module.resonance.market.precheck_resonance_market', side_effect=precheck) as market, \
                patch('module.device.device.Device', side_effect=connect) as device_class, \
                patch('module.base.resource.release_resources'), patch('alas.del_cached_property'), \
                patch('alas.logger.set_file_logger'):
            scheduler._loop()

        self.assertEqual(2, market.call_count)
        self.assertEqual([next_check], config.task_delays)
        scheduler.wait_until.assert_called_once_with(next_check, baseline_ready=True)
        device_class.assert_called_once_with(config=config)
        scheduler.switch_game.assert_called_once_with('resonance')
        scheduler.run.assert_called_once_with('resonance_trade')
        self.assertEqual([], config.task_calls)
        self.assertEqual(
            ['precheck', 'delay', 'watch', 'wait', 'precheck', 'device', 'switch', 'run'],
            self.events,
        )

    def test_resonance_refresh_profile_skips_market_and_boots(self):
        due = Task('ResonanceTrade', datetime.now() - timedelta(seconds=1))
        config = FakeConfig([due])
        config.ResonanceTrade_MarketFilter = 'good'
        config.ResonanceTrade_RefreshProfile = True
        scheduler = self.make_scheduler(config)
        scheduler.games = {'resonance': ('unused', 'unused')}
        scheduler.stop_event = threading.Event()
        scheduler.switch_game = Mock()

        def run(command):
            scheduler.stop_event.set()
            return True

        scheduler.run = Mock(side_effect=run)
        with patch('module.resonance.market.fetch_prices') as fetch, \
                patch('module.device.device.Device', return_value=Mock()) as device_class, \
                patch('module.base.resource.release_resources'), patch('alas.del_cached_property'), \
                patch('alas.logger.set_file_logger'):
            scheduler._loop()

        fetch.assert_not_called()
        device_class.assert_called_once_with(config=config)
        scheduler.switch_game.assert_called_once_with('resonance')
        scheduler.run.assert_called_once_with('resonance_trade')
        self.assertEqual([], config.task_delays)
        self.assertEqual([], config.task_calls)

    def test_future_resonance_market_wait_still_closes_existing_device(self):
        task = Task('ResonanceTrade', datetime.now() + timedelta(seconds=600))
        config = FakeConfig([task])
        config.ResonanceTrade_MarketFilter = 'good'
        device = FakeDevice()
        scheduler = self.make_scheduler(config, device)
        scheduler.game = 'resonance'
        scheduler.game_in_foreground = True
        scheduler.session_claim = Mock()
        scheduler.wait_until = Mock(return_value=True)

        with patch('module.base.resource.release_resources'), \
                patch('module.device.device.Device') as device_class:
            self.assertEqual('ResonanceTrade', scheduler.get_next_task())

        self.assertEqual(['app_stop', 'release_wait', 'emulator_stop'], device.events)
        device_class.assert_not_called()
        scheduler.wait_until.assert_called_once_with(task.next_run, baseline_ready=True)
        self.assertEqual([], config.task_calls)
        self.assertNotIn('device', scheduler.__dict__)

    def test_existing_idle_modes_keep_behavior(self):
        for method in ('close_game', 'goto_main', 'stay_there', 'invalid'):
            with self.subTest(method=method):
                task = Task('HazeworldMain', datetime.now() + timedelta(seconds=600))
                restart = Task('Restart', datetime.now() - timedelta(seconds=1))
                config = FakeConfig([task, restart], method=method)
                device = FakeDevice()
                scheduler = self.make_scheduler(config, device)
                scheduler.session_claim = Mock()
                scheduler.run = Mock()
                scheduler.wait_until = Mock(return_value=True)

                with patch('module.base.resource.release_resources'), patch('alas.del_cached_property'):
                    expected = 'Restart' if method == 'close_game' else 'HazeworldMain'
                    self.assertEqual(expected, scheduler.get_next_task())

                scheduler.session_claim.assert_called_once_with()
                scheduler.wait_until.assert_called_once_with(task.next_run)
                self.assertEqual(['Restart'] if method == 'close_game' else [], config.task_calls)
                self.assertIs(device, scheduler.__dict__['device'])
                if method == 'close_game':
                    self.assertIn('app_stop', device.events)
                else:
                    self.assertNotIn('app_stop', device.events)
                if method == 'goto_main':
                    scheduler.run.assert_called_once_with('goto_main')
                else:
                    scheduler.run.assert_not_called()

    def test_wait_until_reuses_baseline_and_detects_update_before_returning(self):
        task = Task('HazeworldMain', datetime.now() - timedelta(seconds=3))
        config = FakeConfig([task])
        scheduler = self.make_scheduler(config)
        config.reload = True

        with patch('alas.time.sleep') as sleep:
            self.assertFalse(scheduler.wait_until(task.next_run, baseline_ready=True))

        sleep.assert_not_called()
        self.assertEqual(0, config.watch_starts)

    def test_watch_detects_config_write_in_same_second(self):
        watcher = ConfigWatcher()
        before = Mock(st_mtime=1780000000.1)
        after = Mock(st_mtime=1780000000.9)
        with patch('module.config.watcher.os') as watcher_os:
            watcher_os.stat.side_effect = [before, after]
            watcher.start_watching()
            self.assertTrue(watcher.should_reload())

    def test_wait_until_default_still_starts_watching_and_honors_stop_event(self):
        task = Task('HazeworldMain', datetime.now() + timedelta(seconds=600))
        config = FakeConfig([task])
        scheduler = self.make_scheduler(config)
        stop_event = threading.Event()
        stop_event.set()
        scheduler.stop_event = stop_event

        with patch('alas.time.sleep') as sleep:
            with self.assertRaises(SystemExit) as raised:
                scheduler.wait_until(task.next_run)

        self.assertEqual(0, raised.exception.code)
        self.assertEqual(1, config.watch_starts)
        sleep.assert_not_called()


if __name__ == '__main__':
    unittest.main()
