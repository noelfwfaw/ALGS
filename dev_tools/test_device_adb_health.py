"""Offline regressions for slow/stalled local ADB server detection and recovery."""

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.base.decorator import has_cached_property
from module.device.connection import (
    ADB_CALL_SLOW_THRESHOLD,
    ADB_HEAL_COOLDOWN,
    ADB_SERVER_SLOW_THRESHOLD,
    Connection,
)


class DeviceAdbHealthTest(unittest.TestCase):
    def _make_conn(self, is_over_http=False, adb_restart_cfg=False):
        conn = Connection.__new__(Connection)
        conn.serial = '127.0.0.1:16544'
        conn.config = SimpleNamespace(
            Emulator_AdbRestart=adb_restart_cfg,
            DEVICE_OVER_HTTP=is_over_http,
        )
        conn.__dict__['adb_client'] = Mock()
        conn.__dict__['adb'] = Mock()
        conn.adb_binary = 'adb.exe'
        conn.subprocess_run = Mock()
        conn.release_resource = Mock()
        conn.adb_start_server = Mock()
        conn.adb_connect = Mock(return_value=True)
        conn.detect_device = Mock()
        conn.adb_disconnect = Mock()
        conn.list_device = Mock(return_value=[conn.__dict__['adb']])
        return conn

    def test_healthy_or_cold_start_adb_does_not_restart(self):
        conn = self._make_conn()
        with patch.object(conn, '_adb_server_version_latency', side_effect=[0.002]):
            self.assertFalse(conn.check_adb_server_health(force=True))
        conn.adb_start_server.assert_not_called()

        # First probe slow (cold daemon start), second warm probe fast -> healthy.
        with patch.object(
            conn,
            '_adb_server_version_latency',
            side_effect=[ADB_SERVER_SLOW_THRESHOLD + 0.5, 0.002],
        ):
            self.assertFalse(conn.check_adb_server_health(force=True))
        conn.adb_start_server.assert_not_called()

    def test_stalled_adb_restarts_server_clears_caches_and_honors_cooldown(self):
        conn = self._make_conn()
        old_client = conn.__dict__['adb_client']
        conn.adb_restart = Mock(wraps=lambda: Connection.adb_restart(conn))

        with patch.object(
            conn,
            '_adb_server_version_latency',
            side_effect=[ADB_SERVER_SLOW_THRESHOLD + 1.0, ADB_SERVER_SLOW_THRESHOLD + 1.5],
        ):
            with patch('module.device.connection_attr.AdbClient', return_value=Mock()):
                self.assertTrue(conn.check_adb_server_health(reconnect=True, force=True))

        old_client.server_kill.assert_called_once_with()
        conn.release_resource.assert_called_once_with()
        conn.adb_start_server.assert_called_once_with()
        conn.adb_connect.assert_called_once_with(wait_device=False)
        self.assertFalse(has_cached_property(conn, 'adb'))

        # Inside cooldown window: must not restart again even if forced.
        with patch.object(conn, '_adb_server_version_latency', return_value=2.0) as ping:
            self.assertFalse(conn.check_adb_server_health(reconnect=True, force=True))
            ping.assert_not_called()

        conn._adb_heal_at -= ADB_HEAL_COOLDOWN + 1
        with patch.object(conn, '_adb_server_version_latency', side_effect=[0.001]):
            self.assertFalse(conn.check_adb_server_health(reconnect=True, force=True))

    def test_adb_shell_triggers_heal_only_on_main_thread_when_slow(self):
        conn = self._make_conn()
        conn.__dict__['adb'].shell.return_value = 'ok'
        conn.check_adb_server_health = Mock(return_value=True)

        times = iter([10.0, 10.0 + ADB_CALL_SLOW_THRESHOLD + 2.0])
        with patch('module.device.connection.time.monotonic', side_effect=lambda: next(times)):
            self.assertEqual(conn.adb_shell(['echo', 'ok']), 'ok')
        conn.check_adb_server_health.assert_called_once_with(reconnect=True, force=False)

        # Worker threads (e.g. Starsavior2 crash probe) must not run main-thread restart/release.
        conn2 = self._make_conn()
        conn2.__dict__['adb'].shell.return_value = 'ok'
        conn2.adb_start_server = Mock()
        worker_out = []

        def run_worker():
            times_w = iter([20.0, 20.0 + ADB_CALL_SLOW_THRESHOLD + 2.0])
            with patch('module.device.connection.time.monotonic', side_effect=lambda: next(times_w)), \
                 patch.object(conn2, '_adb_server_version_latency', return_value=2.0):
                worker_out.append(conn2.adb_shell(['echo', 'ok']))

        t = threading.Thread(target=run_worker)
        t.start()
        t.join(timeout=2.0)
        self.assertEqual(worker_out, ['ok'])
        conn2.adb_start_server.assert_not_called()

    def test_adb_reconnect_heals_stalled_server_and_server_kill_falls_back(self):
        conn = self._make_conn(adb_restart_cfg=False)
        conn.__dict__['adb_client'].server_kill.side_effect = RuntimeError('hang')

        with patch.object(conn, '_adb_server_version_latency', side_effect=[1.5, 1.8]), \
             patch('module.device.connection_attr.AdbClient', return_value=Mock()):
            conn.adb_reconnect()

        conn.subprocess_run.assert_called_once_with(['adb.exe', 'kill-server'], timeout=5)
        conn.adb_start_server.assert_called_once_with()
        conn.adb_connect.assert_called_once_with(wait_device=False)
        conn.detect_device.assert_called_once_with()
        conn.adb_disconnect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
