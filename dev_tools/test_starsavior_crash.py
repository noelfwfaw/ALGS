"""Offline regressions for Starsavior2 non-blocking crash detection."""

import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from module.base.timer import Timer
from module.config.server import set_server

set_server('starsavior')

from module.starsavior.starsavior2 import CRASH_CONFIRM, GameCrashed, Starsavior2


class StarsaviorCrashTest(unittest.TestCase):
    def _make_task(self, adb_shell):
        task = Starsavior2.__new__(Starsavior2)
        task.device = SimpleNamespace(adb_shell=adb_shell)
        task.hot_update_state = Mock(return_value='')
        task._desktop_package = 'app.lawnchair'
        task.arm_crash_watch()
        task.crash_grace_until = 0.0
        return task

    def _wait_probe(self, task, timeout=2.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            thread = task._crash_probe_thread
            if thread is None or not thread.is_alive():
                return
            time.sleep(0.01)
        self.fail('Background crash probe did not finish in time')

    def test_slow_adb_shell_never_blocks_check_game_crash(self):
        gate = threading.Event()
        calls = []

        def slow_adb(cmd):
            calls.append(cmd)
            gate.wait(timeout=2.0)
            return '__PID__:1234\n  topResumedActivity=ActivityRecord{1 u0 com.studiobside.starMain/.Main}'

        task = self._make_task(slow_adb)
        task._crash_timer = Timer(0.01)

        t0 = time.perf_counter()
        for _ in range(5):
            task.check_game_crash()
        elapsed = time.perf_counter() - t0

        self.assertLess(elapsed, 0.2)
        self.assertEqual(len(calls), 1)

        gate.set()
        self._wait_probe(task)
        task.check_game_crash()
        self.assertEqual(task.crash_missing, 0)

    def test_two_gone_or_desktop_probes_raise_game_crashed(self):
        responses = iter([
            '__PID__:',
            '__PID__:',
        ])
        task = self._make_task(lambda cmd: next(responses))

        task._crash_timer = Timer(0.01)
        task.check_game_crash()
        self._wait_probe(task)
        task.check_game_crash()
        self.assertEqual(task.crash_missing, 1)

        task._crash_timer = Timer(0.01)
        task.check_game_crash()
        self._wait_probe(task)
        with self.assertRaises(GameCrashed) as ctx:
            task.check_game_crash()
        self.assertTrue(ctx.exception.gone)

    def test_stale_probe_from_disarmed_epoch_is_ignored(self):
        started = threading.Event()
        release = threading.Event()

        def stale_adb(cmd):
            started.set()
            release.wait(timeout=2.0)
            return '__PID__:'

        task = self._make_task(stale_adb)
        task._crash_timer = Timer(0.01)
        task.check_game_crash()
        self.assertTrue(started.wait(timeout=1.0))

        # Simulates entering reset() and re-arming afterwards before the old probe finished.
        task.disarm_crash_watch()
        task.arm_crash_watch()
        task.crash_grace_until = 0.0
        release.set()
        self._wait_probe(task)

        task.check_game_crash()
        self.assertEqual(task.crash_missing, 0)
        self.assertIsNone(task._crash_probe_result)

    def test_desktop_probe_marks_not_gone_and_hot_update_resets_counter(self):
        task = self._make_task(
            lambda cmd: '__PID__:999\n  topResumedActivity=ActivityRecord{1 u0 app.lawnchair/.Launcher}'
        )
        task.crash_missing = CRASH_CONFIRM - 1
        task.hot_update_state = Mock(return_value='progress')
        task._crash_timer = Timer(0.01)
        task.check_game_crash()
        self._wait_probe(task)
        task.check_game_crash()
        self.assertEqual(task.crash_missing, 0)

        task.hot_update_state = Mock(return_value='')
        for step in range(CRASH_CONFIRM):
            task._crash_timer = Timer(0.01)
            task.check_game_crash()
            self._wait_probe(task)
            if step < CRASH_CONFIRM - 1:
                task.check_game_crash()
            else:
                with self.assertRaises(GameCrashed) as ctx:
                    task.check_game_crash()
                self.assertFalse(ctx.exception.gone)


if __name__ == '__main__':
    unittest.main()
