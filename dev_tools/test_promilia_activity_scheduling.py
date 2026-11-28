"""Offline regressions for Promilia task selection through WebUI and AlGS."""

import json
import queue
import sys
import tempfile
import unittest
from contextlib import nullcontext
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import PIL
from PIL import Image

try:
    from module.webui import app as webui_app
finally:
    # The WebUI import installs a PIL stub for PyWebIO. Game tests need Pillow.
    sys.modules['PIL'] = PIL
    sys.modules['PIL.Image'] = Image

import alas
from module.config import config as config_module
from module.config import config_updater as config_updater_module
from module.config import watcher as watcher_module
from module.config.config import AlasConfig
from module.config.config_updater import ConfigUpdater
from module.config.deep import deep_get, deep_iter, deep_set
from module.config.utils import DEFAULT_TIME


class FakePin(dict):
    def __getitem__(self, key):
        return self.get(key)


class PromiliaActivitySchedulingTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.config_name = 't36-promilia'
        self.config_file = self.directory / (self.config_name + '.alas.json')

        def filepath_config(name, mod_name='alas'):
            return str(self.directory / (name + '.' + mod_name + '.json'))

        for module in (
                webui_app,
                config_module,
                config_updater_module,
                watcher_module):
            patcher = patch.object(module, 'filepath_config', side_effect=filepath_config)
            patcher.start()
            self.addCleanup(patcher.stop)

        data = ConfigUpdater().config_update({})
        for path, value in deep_iter(data, depth=3):
            if path[-2:] == ['Scheduler', 'Enable']:
                deep_set(data, path, False)
        deep_set(data, 'Alas.Optimization.WhenTaskQueueEmpty', 'close_emulator')
        deep_set(data, 'Restart.Scheduler.NextRun', datetime.now() + timedelta(days=2))
        deep_set(data, 'PromiliaActivity.Scheduler.NextRun', DEFAULT_TIME)
        self.config_file.write_text(json.dumps(data, default=str), encoding='utf-8')

        self.gui = webui_app.AlasGUI.__new__(webui_app.AlasGUI)
        self.gui.alas_name = self.config_name
        self.gui.alas_config = AlasConfig(self.config_name, '')
        self.gui.ALAS_ARGS = self.gui.alas_config.args
        self.gui.alas = SimpleNamespace(alive=False)
        self.gui.alive = True
        self.gui.visible = True
        self.gui.page = 'Overview'
        self.gui.modified_config_queue = queue.Queue()
        self.gui.pin_remove_invalid_mark = Mock()
        self.gui.pin_set_invalid_mark = Mock()
        self.pin = FakePin()

    def _save_enable(self):
        key = 'PromiliaActivity.Scheduler.Enable'
        self.pin['PromiliaActivity_Scheduler_Enable'] = [True]
        with patch.object(webui_app, 'pin', self.pin), \
                patch.object(webui_app, 'toast'), \
                patch.object(self.gui, 'alas_update_overview_task'), \
                patch.object(webui_app, 't', side_effect=lambda text, **kwargs: text):
            self.gui._save_config({key: [True]}, self.config_name, self.gui.alas_config)
        self.assertTrue(deep_get(
            json.loads(self.config_file.read_text(encoding='utf-8')),
            key,
        ))

    def _overview_texts(self):
        texts = []

        def put_text(value):
            texts.append(value)
            output = MagicMock()
            output.style.return_value = output
            return output

        with patch.object(webui_app, 'use_scope', side_effect=lambda *args, **kwargs: nullcontext()), \
                patch.object(webui_app, 'clear'), \
                patch.object(webui_app, 'put_text', side_effect=put_text), \
                patch.object(webui_app, 'put_column'), \
                patch.object(webui_app, 'put_button'), \
                patch.object(webui_app, 't', side_effect=lambda text, **kwargs: text):
            self.gui.alas_update_overview_task()
        return texts

    def _scheduler(self):
        scheduler = alas.GameScheduler(self.config_name)
        scheduler.__dict__['config'] = self.gui.alas_config
        scheduler.game = None
        scheduler.game_in_foreground = False
        scheduler.prefer_current_game = lambda command: False
        scheduler.session_claim = Mock()
        scheduler.wait_until = Mock(return_value=True)
        return scheduler

    def test_disabled_task_is_excluded_then_first_save_is_visible_and_selected(self):
        self.gui.alas_config.get_next_task()
        self.assertEqual([], self.gui.alas_config.pending_task)
        self.assertEqual(['Restart'], [task.command for task in self.gui.alas_config.waiting_task])
        self.assertNotIn('PromiliaActivity',
                         [task.command for task in self.gui.alas_config.pending_task
                          + self.gui.alas_config.waiting_task])

        self._save_enable()
        texts = self._overview_texts()
        self.assertEqual(1, texts.count('Task.PromiliaActivity.name'))
        self.assertEqual(['PromiliaActivity'], [task.command for task in self.gui.alas_config.pending_task])

        scheduler = self._scheduler()
        with patch('module.base.resource.release_resources'):
            self.assertEqual('PromiliaActivity', scheduler.get_next_task())
        self.assertNotIn('device', scheduler.__dict__)
        self.assertEqual('PromiliaActivity', scheduler.config.task.command)

    def test_debounced_save_refreshes_an_overview_already_open(self):
        self.assertNotIn('Task.PromiliaActivity.name', self._overview_texts())
        self.pin['PromiliaActivity_Scheduler_Enable'] = [True]
        self.gui.modified_config_queue.put({
            'name': 'PromiliaActivity.Scheduler.Enable',
            'value': [True],
        })
        texts = []
        dequeues = []

        def dequeue(*args, **kwargs):
            if not dequeues:
                dequeues.append(True)
                return {'name': 'PromiliaActivity.Scheduler.Enable', 'value': [True]}
            self.gui.alive = False
            raise queue.Empty

        def put_text(value):
            texts.append(value)
            output = MagicMock()
            output.style.return_value = output
            return output

        with patch.object(webui_app, 'pin', self.pin), \
                patch.object(webui_app, 'toast'), \
                patch.object(webui_app, 'use_scope', side_effect=lambda *args, **kwargs: nullcontext()), \
                patch.object(webui_app, 'clear'), \
                patch.object(webui_app, 'put_text', side_effect=put_text), \
                patch.object(webui_app, 'put_column'), \
                patch.object(webui_app, 'put_button'), \
                patch.object(webui_app, 't', side_effect=lambda text, **kwargs: text), \
                patch.object(self.gui.modified_config_queue, 'get', side_effect=dequeue):
            self.gui._alas_thread_update_config()

        self.assertIn('Task.PromiliaActivity.name', texts)

    def test_future_next_run_stays_in_waiting_without_device(self):
        self._save_enable()
        future = (datetime.now() + timedelta(hours=1)).replace(microsecond=0)
        data = self.gui.alas_config.read_file(self.config_name)
        deep_set(data, 'PromiliaActivity.Scheduler.NextRun', future)
        self.gui.alas_config.write_file(self.config_name, data)
        self.gui.alas_config.load()
        before = self.config_file.read_bytes()

        texts = self._overview_texts()
        self.assertEqual(1, texts.count('Task.PromiliaActivity.name'))
        self.assertEqual([], self.gui.alas_config.pending_task)
        self.assertEqual('PromiliaActivity', self.gui.alas_config.waiting_task[0].command)
        self.assertIn('PromiliaActivity', [task.command for task in self.gui.alas_config.waiting_task])

        scheduler = self._scheduler()
        task = scheduler.config.get_next(prefer=scheduler.prefer_current_game)

        self.assertEqual('PromiliaActivity', task.command)
        self.assertEqual(future, task.next_run)
        self.assertNotIn('device', scheduler.__dict__)
        self.assertEqual(before, self.config_file.read_bytes())


if __name__ == '__main__':
    unittest.main()
