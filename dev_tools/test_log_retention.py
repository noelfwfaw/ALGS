import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image
from rich.console import Console

from module import log_retention
from module.log_retention import DIAGNOSTIC_LIMITS, TextLogStream, prune_diagnostics, prune_text_logs


class DiagnosticRetentionTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)

    def write(self, filename, age):
        path = self.folder / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'data')
        stamp = time.time() - age
        os.utime(path, (stamp, stamp))
        return path

    def test_byte_limit_keeps_page_and_metadata_together(self):
        old = [self.write('101001' + ext, 120)
               for ext in ('.png', '.json', '_c1.png')]
        new = [self.write('101002' + ext, 60)
               for ext in ('.png', '.json', '_c1.png')]
        manual = self.write('notes.txt', 120)
        pattern = DIAGNOSTIC_LIMITS['card'][0]
        with patch.dict(DIAGNOSTIC_LIMITS, card=(pattern, 64, 18)):
            self.assertEqual(prune_diagnostics(self.folder, 'card'), 12)
        self.assertFalse(any(path.exists() for path in old))
        self.assertTrue(all(path.exists() for path in [*new, manual]))

    def test_error_bundle_cleanup_skips_busy_and_unrecognized_files(self):
        bundles = ['1000000000000', '1000000000001', '1000000000002', '1000000000003']
        for name, age in zip(bundles, (120, 100, 10, 0)):
            file = self.write(name + '/log.txt', age)
            os.utime(file.parent, (file.stat().st_mtime,) * 2)
        manual = self.write(bundles[1] + '/notes.txt', 100)
        busy = self.folder / bundles[2] / 'log.txt'
        pattern = DIAGNOSTIC_LIMITS['error'][0]
        with patch.dict(DIAGNOSTIC_LIMITS, error=(pattern, 1, 100)):
            self.assertEqual(prune_diagnostics(self.folder, 'error'), 4)
        self.assertFalse((self.folder / bundles[0]).exists())
        self.assertTrue(manual.exists())
        self.assertTrue(busy.exists())
        self.assertTrue((self.folder / bundles[3] / 'log.txt').exists())

    def test_first_log_write_prunes_automatic_records_across_directories(self):
        old = [self.write('rogue_card_pages/flash/101001' + ext, 120)
               for ext in ('.png', '.json', '_c1.png')]
        latest = self.write('rogue_pages/unknown_101002.png', 60)
        error = self.write('error/shop_buy_failed/1000000000000.png', 40)
        manual = [self.write('probe/1000000000001.png', 150),
                  self.write('rogue_card_pages/manual/101001.png', 150),
                  self.write('error/1000000000000/notes.txt', 150)]
        console = Console(file=TextLogStream(self.folder / '2026-11-19_test.txt'), no_color=True)
        with patch.object(log_retention, 'DIAGNOSTIC_TOTAL_BYTES', 8):
            console.print('boot')
        self.assertFalse(any(path.exists() for path in old))
        self.assertTrue(all(path.exists() for path in [latest, error, *manual]))

    def test_ongoing_logging_prunes_oversized_legacy_bundle_after_grace(self):
        bundle = self.write('error/1000000000000/log.txt', 0)
        console = Console(file=TextLogStream(self.folder / '2026-11-19_test.txt'), no_color=True)
        with patch.multiple(log_retention, DIAGNOSTIC_TOTAL_BYTES=2, TEXT_MAINTENANCE_INTERVAL=0):
            console.print('first')
            self.assertTrue(bundle.exists())
            stamp = time.time() - 60
            os.utime(bundle, (stamp, stamp))
            os.utime(bundle.parent, (stamp, stamp))
            console.print('second')
            self.assertFalse(bundle.parent.exists())

    def test_error_bundle_keeps_newest_screenshots_within_byte_budget(self):
        previous_cwd = os.getcwd()
        try:
            with patch.object(TextLogStream, 'flush'):
                from alas import GameScheduler
            log = self.write('run.txt', 0)
            log.write_bytes(('older lines\n' * 20 + '最新错误\n').encode('utf-8'))
            (self.folder / 'log').mkdir()
            os.chdir(str(self.folder))
            frame = np.zeros((12, 12, 3), dtype=np.uint8)
            stamp = datetime(2026, 11, 19, 12, 0)
            screenshots = [{'image': frame, 'time': stamp + timedelta(seconds=i)}
                           for i in range(3)]
            png = BytesIO()
            Image.fromarray(frame).save(png, format='PNG')
            budget = 32 + 2 * png.tell()
            task = SimpleNamespace(config=SimpleNamespace(Error_SaveError=True),
                                   device=SimpleNamespace(screenshot_deque=screenshots))
            with patch('alas.logger', Mock(log_file=str(log))), \
                    patch('alas.ERROR_BUNDLE_BYTES', budget), patch('alas.ERROR_LOG_BYTES', 32):
                GameScheduler.save_error_log(task)
            bundle, = (self.folder / 'log' / 'error').iterdir()
            self.assertEqual(sorted(path.name for path in bundle.glob('*.png')),
                             ['2026-11-19_12-00-01-000000.png', '2026-11-19_12-00-02-000000.png'])
            self.assertLessEqual(sum(path.stat().st_size for path in bundle.iterdir()), budget)
            self.assertTrue((bundle / 'log.txt').read_text(encoding='utf-8').endswith('最新错误\n'))
        finally:
            os.chdir(previous_cwd)


class TextRetentionTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.path = self.folder / '2026-11-18_test.txt'
        self.stream = TextLogStream(self.path)

    def test_rich_rollover_keeps_utf8_and_retries_after_busy_file(self):
        console = Console(file=self.stream, width=40, no_color=True)
        with patch.object(log_retention, 'TEXT_FILE_BYTES', 24):
            console.print('第一条日志')
            with patch.object(Path, 'rename', side_effect=PermissionError('busy')):
                console.print('占用中')
            console.print('新的日志')
        self.assertEqual(self.path.read_text(encoding='utf-8'), '新的日志\n')
        backup, = self.folder.glob(self.path.name + '.*')
        self.assertEqual(backup.read_text(encoding='utf-8'), '第一条日志\n')

    def test_ongoing_writes_prune_expired_history_and_oldest_rotations(self):
        console = Console(file=self.stream, no_color=True)
        console.print('first')
        old = self.folder / '2026-11-09_old.txt'
        rotation = self.folder / (self.path.name + '.1770000000000000000')
        manual = self.folder / '2026-99-99_manual.txt'
        for path in (old, rotation, manual):
            path.write_bytes(b'x' * 32)
        old_time = time.time() - log_retention.TEXT_MAX_AGE - 60
        os.utime(old, (old_time, old_time))
        os.utime(manual, (old_time, old_time))
        with patch.multiple(log_retention, TEXT_TOTAL_BYTES=16, TEXT_MAINTENANCE_INTERVAL=0):
            console.print('second')
        self.assertFalse(old.exists())
        self.assertFalse(rotation.exists())
        self.assertTrue(manual.exists())
        self.assertEqual(self.path.read_text(encoding='utf-8'), 'first\nsecond\n')

    def test_two_processes_share_file_and_preserve_records_across_rotations(self):
        script = """
import sys
from module import log_retention as limits
limits.TEXT_FILE_BYTES = 96
stream = limits.TextLogStream(sys.argv[1])
for i in range(24):
    stream.write('{}:{}\u5b57\\n'.format(sys.argv[2], i))
    stream.flush()
"""
        processes = [subprocess.Popen([sys.executable, '-c', script, str(self.path), tag])
                     for tag in ('a', 'b')]
        try:
            for process in processes:
                self.assertEqual(process.wait(timeout=20), 0)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.wait()
        logs = [self.path, *self.folder.glob(self.path.name + '.*')]
        self.assertGreater(len(logs), 1)
        self.assertTrue(all(path.stat().st_size <= 96 for path in logs))
        records = [line for path in logs for line in path.read_text(encoding='utf-8').splitlines()]
        self.assertCountEqual(records, [f'{tag}:{i}字' for tag in ('a', 'b') for i in range(24)])
        self.assertEqual(prune_text_logs(self.folder), 0)
