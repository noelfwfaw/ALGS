import subprocess
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, PropertyMock, call, patch

from module.base.grids import SelectedGrids
from module.device.device import Device
from module.device.platform.emulator_windows import Emulator
from module.device.platform.platform_windows import PlatformWindows
from module.device.screenshot import Screenshot
from module.exception import EmulatorNotRunningError


class DeviceInitTest(unittest.TestCase):
    def test_disconnected_probe_does_not_start_emulator(self):
        error = EmulatorNotRunningError('offline')
        device = Device.__new__(Device)
        with patch.object(Screenshot, '__init__', side_effect=error) as init, \
                patch.object(Device, 'emulator_start') as start:
            with self.assertRaises(EmulatorNotRunningError) as raised:
                device.__init__(start_emulator=False)

        self.assertIs(raised.exception, error)
        init.assert_called_once_with()
        start.assert_not_called()

    def test_default_init_still_starts_emulator(self):
        error = EmulatorNotRunningError('offline')
        instance = SimpleNamespace(serial='127.0.0.1:16384')
        config = SimpleNamespace(
            EmulatorInfo_Emulator='auto',
            Emulator_ScreenshotMethod='ADB',
            is_template_config=True,
            is_actual_task=False,
        )
        device = Device.__new__(Device)
        device.config = config
        with patch('module.device.device.IS_WINDOWS', False), \
                patch.object(Screenshot, '__init__', side_effect=[error, None]) as init, \
                patch.object(Device, 'emulator_instance', new_callable=PropertyMock,
                             return_value=instance), \
                patch.object(Device, 'emulator_start', return_value=True) as start, \
                patch.object(Device, 'screenshot_interval_set'), \
                patch.object(Device, 'method_check'):
            device.__init__()

        self.assertEqual(init.call_count, 2)
        start.assert_called_once_with()


class DeviceEmulatorStopTest(unittest.TestCase):
    def setUp(self):
        self.serial = '127.0.0.1:16384'
        self.device = Device.__new__(Device)
        self.device.serial = self.serial
        self.instance = SimpleNamespace(serial=self.serial)
        self.device._emulator_stop = Mock()
        self.device.emulator_stop = Mock(side_effect=AssertionError('unsafe stop called'))
        self.wrapper = Mock(return_value=True)
        self.device._emulator_function_wrapper = self.wrapper
        self.device.list_device = Mock(return_value=SelectedGrids([
            SimpleNamespace(serial=self.serial, status='device'),
        ]))

        patch('module.device.device.IS_WINDOWS', True).start()
        self.is_over_http = patch.object(
            Device, 'is_over_http', new_callable=PropertyMock, return_value=False
        ).start()
        self.is_emulator = patch.object(
            Device, 'is_emulator', new_callable=PropertyMock, return_value=True
        ).start()
        self.emulator_instance = patch.object(
            Device, 'emulator_instance', new_callable=PropertyMock, return_value=self.instance
        ).start()

        def make_timer(limit):
            timer = Mock()
            timer.start.return_value = timer
            timer.reached.return_value = limit == 0
            return timer

        patch('module.device.device.Timer', side_effect=make_timer).start()
        self.addCleanup(patch.stopall)

    def test_rejected_stop_returns_false_without_probing_adb(self):
        self.wrapper.return_value = False
        self.assertFalse(self.device.emulator_stop_and_wait())
        self.wrapper.assert_called_once_with(self.device._emulator_stop)
        self.device.list_device.assert_not_called()
        self.device.emulator_stop.assert_not_called()

    def test_offline_matching_serial_is_stopped(self):
        self.device.list_device.return_value.grids[0].status = 'offline'
        self.assertTrue(self.device.emulator_stop_and_wait())
        self.wrapper.assert_called_once_with(self.device._emulator_stop)
        self.device.list_device.assert_called_once_with()
        self.device.emulator_stop.assert_not_called()

    def test_missing_matching_serial_is_stopped(self):
        self.device.list_device.return_value = SelectedGrids([
            SimpleNamespace(serial='127.0.0.1:16416', status='device'),
        ])
        self.assertTrue(self.device.emulator_stop_and_wait())
        self.device.list_device.assert_called_once_with()

    def test_paired_adb_serial_must_also_go_offline(self):
        self.device.serial = 'emulator-5554'
        self.instance.serial = '127.0.0.1:5555'
        paired = SimpleNamespace(serial=self.instance.serial, status='device')
        self.device.list_device.side_effect = [SelectedGrids([paired]), SelectedGrids([])]
        self.assertTrue(self.device.emulator_stop_and_wait())
        self.assertEqual(2, self.device.list_device.call_count)

    def test_timeout_returns_false(self):
        self.assertFalse(self.device.emulator_stop_and_wait(timeout=0))
        self.device.list_device.assert_called_once_with()

    def test_deadline_returns_false(self):
        self.assertFalse(self.device.emulator_stop_and_wait(
            deadline=datetime.now() - timedelta(seconds=1)
        ))
        self.device.list_device.assert_not_called()
        self.wrapper.assert_not_called()

    def test_mismatched_instance_is_rejected(self):
        self.emulator_instance.return_value = SimpleNamespace(serial='127.0.0.1:16416')
        self.assertFalse(self.device.emulator_stop_and_wait())
        self.wrapper.assert_not_called()

    def test_missing_instance_is_rejected(self):
        self.emulator_instance.return_value = None
        self.assertFalse(self.device.emulator_stop_and_wait())
        self.wrapper.assert_not_called()

    def test_non_windows_remote_and_non_emulator_are_rejected(self):
        cases = (
            (False, False, True),
            (True, True, True),
            (True, False, False),
        )
        for windows, over_http, emulator in cases:
            with self.subTest(windows=windows, over_http=over_http, emulator=emulator), \
                    patch('module.device.device.IS_WINDOWS', windows):
                self.is_over_http.return_value = over_http
                self.is_emulator.return_value = emulator
                self.wrapper.reset_mock()
                self.assertFalse(self.device.emulator_stop_and_wait())
                self.wrapper.assert_not_called()

    def test_legacy_mumu_kill_branches_are_rejected(self):
        for name in ('MuMuPlayer', 'MuMuPlayerX'):
            with self.subTest(emulator=name), patch.object(Emulator, name, self.instance):
                self.wrapper.reset_mock()
                self.assertFalse(self.device.emulator_stop_and_wait())
                self.wrapper.assert_not_called()


class MuMuManagerApiTest(unittest.TestCase):
    console = r'C:\Program Files\Netease\MuMuPlayer-12.0\shell\MuMuManager.exe'

    def test_last_json_envelope_is_used(self):
        output = b'noise\n{"errcode":9}\nnot json\n{"errcode":0,"errmsg":""}\n'
        self.assertEqual(
            PlatformWindows._parse_mumu_api_output(output),
            {'errcode': 0, 'errmsg': ''},
        )

    def test_success_uses_list_argv_and_timeout(self):
        result = SimpleNamespace(stdout=b'{"errcode":0,"errmsg":""}', returncode=0)
        with patch('module.device.platform.platform_windows.subprocess.run',
                   return_value=result) as run:
            self.assertTrue(PlatformWindows._mumu_manager_api(self.console, 7, 'launch_player'))
        run.assert_called_once_with(
            [self.console, 'api', '-v', '7', 'launch_player'],
            capture_output=True,
            timeout=20,
        )

    def test_nonzero_errcode_is_rejected_even_with_zero_returncode(self):
        result = SimpleNamespace(stdout=b'{"errcode":5,"errmsg":"denied"}', returncode=0)
        with patch('module.device.platform.platform_windows.subprocess.run', return_value=result):
            self.assertFalse(PlatformWindows._mumu_manager_api(self.console, 7, 'shutdown_player'))

    def test_shutdown_already_stopped_is_success(self):
        result = SimpleNamespace(
            stdout=b'{"errcode":5,"errmsg":"Player not running"}', returncode=1
        )
        with patch('module.device.platform.platform_windows.subprocess.run', return_value=result):
            self.assertTrue(PlatformWindows._mumu_manager_api(self.console, 7, 'shutdown_player'))
            self.assertFalse(PlatformWindows._mumu_manager_api(self.console, 7, 'launch_player'))

    def test_legacy_output_uses_returncode(self):
        for returncode, expected in ((0, True), (2, False)):
            with self.subTest(returncode=returncode), \
                    patch('module.device.platform.platform_windows.subprocess.run',
                          return_value=SimpleNamespace(stdout=b'legacy output', returncode=returncode)):
                self.assertIs(
                    PlatformWindows._mumu_manager_api(self.console, 7, 'launch_player'),
                    expected,
                )

    def test_timeout_is_rejected(self):
        with patch('module.device.platform.platform_windows.subprocess.run',
                   side_effect=subprocess.TimeoutExpired('MuMuManager', 20)):
            self.assertFalse(PlatformWindows._mumu_manager_api(self.console, 7, 'launch_player'))


class MuMuControlTest(unittest.TestCase):
    def setUp(self):
        self.console = r'C:\Program Files\Netease\MuMuPlayer-12.0\shell\MuMuManager.exe'
        self.instance = SimpleNamespace(
            name='MuMuPlayer-12.0-7',
            serial='127.0.0.1:16640',
            MuMuPlayer12_id=7,
            emulator=SimpleNamespace(path=r'C:\MuMuPlayer\MuMuPlayer.exe'),
        )
        self.platform = PlatformWindows.__new__(PlatformWindows)
        patch.object(Emulator, 'MuMuPlayer12', self.instance).start()
        patch.object(Emulator, 'single_to_console', return_value=self.console).start()
        patch.object(
            PlatformWindows, 'emulator_instance', new_callable=PropertyMock,
            return_value=self.instance,
        ).start()
        self.addCleanup(patch.stopall)

    def test_start_and_stop_return_command_result(self):
        for method, action in (
            ('_emulator_start', 'launch_player'),
            ('_emulator_stop', 'shutdown_player'),
        ):
            for accepted in (True, False):
                with self.subTest(method=method, accepted=accepted), \
                        patch.object(PlatformWindows, '_mumu_manager_api',
                                     return_value=accepted) as api:
                    self.assertIs(getattr(self.platform, method)(self.instance), accepted)
                    api.assert_called_once_with(self.console, 7, action)

    def test_missing_instance_index_does_not_run_command(self):
        self.instance.MuMuPlayer12_id = None
        with patch.object(PlatformWindows, '_mumu_manager_api') as api, \
                patch.object(self.platform, 'execute') as execute:
            self.assertFalse(self.platform._emulator_start(self.instance))
            self.assertFalse(self.platform._emulator_stop(self.instance))
        api.assert_not_called()
        execute.assert_not_called()

    def test_mumu12_start_does_not_use_popen(self):
        result = SimpleNamespace(stdout=b'{"errcode":0}', returncode=0)
        with patch('module.device.platform.platform_windows.subprocess.run',
                   return_value=result) as run, \
                patch.object(self.platform, 'execute') as execute:
            self.assertTrue(self.platform._emulator_start(self.instance))
        run.assert_called_once_with(
            [self.console, 'api', '-v', '7', 'launch_player'],
            capture_output=True,
            timeout=20,
        )
        execute.assert_not_called()

    def test_start_keeps_existing_serial_watch(self):
        with patch.object(PlatformWindows, '_mumu_manager_api', return_value=True) as api, \
                patch.object(PlatformWindows, 'emulator_start_watch', return_value=True) as watch:
            self.assertTrue(self.platform.emulator_start())
        self.assertEqual(api.call_args_list, [
            call(self.console, 7, 'shutdown_player'),
            call(self.console, 7, 'launch_player'),
        ])
        watch.assert_called_once_with()

    def test_start_after_mumu_reports_stopped_as_plain_text(self):
        stopped = SimpleNamespace(
            stdout=b'current select player index: 7\nmain status changed: status=2 pid=0 privilege=0\n'
                   b'player not running\r\n',
            returncode=4294967294,
        )
        started = SimpleNamespace(stdout=b'{"errcode":0}', returncode=0)
        with patch('module.device.platform.platform_windows.subprocess.run',
                   side_effect=[stopped, started]) as run, \
                patch.object(PlatformWindows, 'emulator_start_watch', return_value=True) as watch:
            self.assertTrue(self.platform.emulator_start())

        self.assertEqual(['shutdown_player', 'launch_player'],
                         [command[0][0][-1] for command in run.call_args_list])
        watch.assert_called_once_with()

    def test_start_follows_same_instance_to_new_port_and_waits_for_android(self):
        updated = SimpleNamespace(name=self.instance.name, serial='127.0.0.1:16642')
        other = SimpleNamespace(name='MuMuPlayer-12.0-8', serial='127.0.0.1:16608')
        self.instance.emulator.iter_instances = Mock(return_value=[other, updated])
        self.platform.serial = self.instance.serial
        self.platform.config = SimpleNamespace(Emulator_Serial=self.instance.serial)
        self.platform.adb_client = Mock()
        self.platform.adb_client.connect.return_value = 'connected'
        online = SelectedGrids([SimpleNamespace(serial=updated.serial, status='device')])
        self.platform.list_device = Mock(side_effect=[SelectedGrids([]), online, online])
        self.platform.adb_shell = Mock(side_effect=['pong', '', 'pong', '1'])
        self.platform.list_known_packages = Mock(return_value=['com.example.game'])

        def make_timer(limit):
            timer = Mock()
            timer.start.return_value = timer
            timer.reached.return_value = limit == 5
            return timer

        with patch('module.device.platform.platform_windows.Timer', side_effect=make_timer), \
                patch('module.device.platform.platform_windows.get_focused_window', return_value=0):
            self.assertTrue(self.platform.emulator_start_watch())

        self.platform.adb_client.connect.assert_called_once_with(updated.serial)
        self.assertEqual(updated.serial, self.platform.serial)
        self.assertEqual(updated.serial, self.platform.config.Emulator_Serial)
        self.assertEqual(4, self.platform.adb_shell.call_count)
        self.platform.list_known_packages.assert_called_once_with(show_log=False)

    def test_wrapper_preserves_none_and_false_semantics(self):
        for result, expected in ((None, True), (True, True), (False, False)):
            with self.subTest(result=result):
                func = Mock(return_value=result)
                func.__name__ = 'emulator_operation'
                self.assertIs(self.platform._emulator_function_wrapper(func), expected)
                func.assert_called_once_with(self.instance)

    def test_wrapper_catches_command_oserror(self):
        func = Mock(side_effect=OSError('spawn failed'))
        func.__name__ = 'emulator_operation'
        self.assertFalse(self.platform._emulator_function_wrapper(func))


if __name__ == '__main__':
    unittest.main()
