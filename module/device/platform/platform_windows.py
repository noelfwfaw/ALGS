import ctypes
import json
import re
import subprocess

import psutil

from deploy.Windows.utils import DataProcessInfo
from module.base.decorator import del_cached_property, run_once
from module.base.timer import Timer
from module.device.connection import AdbDeviceWithStatus
from module.device.platform.platform_base import PlatformBase
from module.device.platform.emulator_windows import Emulator, EmulatorInstance, EmulatorManager
from module.logger import logger


class EmulatorUnknown(Exception):
    pass


def get_focused_window():
    return ctypes.windll.user32.GetForegroundWindow()


def set_focus_window(hwnd):
    ctypes.windll.user32.SetForegroundWindow(hwnd)


def minimize_window(hwnd):
    ctypes.windll.user32.ShowWindow(hwnd, 6)


def get_window_title(hwnd):
    """Returns the window title as a string."""
    text_len_in_characters = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    string_buffer = ctypes.create_unicode_buffer(
        text_len_in_characters + 1)  # +1 for the \0 at the end of the null-terminated string.
    ctypes.windll.user32.GetWindowTextW(hwnd, string_buffer, text_len_in_characters + 1)
    return string_buffer.value


def flash_window(hwnd, flash=True):
    ctypes.windll.user32.FlashWindow(hwnd, flash)


class PlatformWindows(PlatformBase, EmulatorManager):
    @classmethod
    def execute(cls, command):
        """
        Args:
            command (str):

        Returns:
            subprocess.Popen:
        """
        command = command.replace(r"\\", "/").replace("\\", "/").replace('"', '"')
        logger.info(f'Execute: {command}')
        # `close_fds` only work on Windows
        # `start_new_session` to avoid emulator getting tree-killed when Alas gets killed
        return subprocess.Popen(command, close_fds=True, start_new_session=True)

    @classmethod
    def kill_process_by_regex(cls, regex: str) -> int:
        """
        Kill processes with cmdline match the given regex.

        Args:
            regex:

        Returns:
            int: Number of processes killed
        """
        count = 0

        for proc in psutil.process_iter():
            cmdline = DataProcessInfo(proc=proc, pid=proc.pid).cmdline
            if re.search(regex, cmdline):
                logger.info(f'Kill emulator: {cmdline}')
                proc.kill()
                count += 1

        return count

    @classmethod
    def _parse_mumu_api_output(cls, stdout: bytes):
        """Read the last MuMuManager JSON envelope containing an error code."""
        text = stdout.decode('utf-8', errors='ignore')
        for line in reversed(text.splitlines()):
            line = line.strip()
            if not line.startswith('{') or not line.endswith('}'):
                continue
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if isinstance(data, dict) and 'errcode' in data:
                return data
        return None

    @classmethod
    def _mumu_manager_api(cls, console: str, instance_id: int, action: str, timeout: int = 20) -> bool:
        """Run one MuMuManager command synchronously and validate its response."""
        command = [console, 'api', '-v', str(instance_id), action]
        logger.info(f'Execute: {" ".join(command)}')
        try:
            result = subprocess.run(command, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            logger.warning(f'MuMuManager {action} timeout after {timeout}s')
            return False

        stdout = result.stdout or b''
        output = stdout.decode('utf-8', errors='ignore').strip()
        if output:
            logger.info(f'MuMuManager {action}: {output}')

        data = cls._parse_mumu_api_output(stdout)
        if data is not None:
            if data.get('errcode') == 0:
                return True
            errmsg = str(data.get('errmsg', data.get('message', '')))
            if action == 'shutdown_player' and 'player not running' in errmsg.lower():
                logger.info(f'MuMuPlayer is already stopped: {data}')
                return True
            logger.warning(f'MuMuManager {action} failed: {data}')
            return False

        # Some MuMu builds report an already stopped instance as plain text.
        if action == 'shutdown_player' and any(line.strip().lower() == 'player not running'
                                                for line in output.splitlines()):
            return True
        if result.returncode != 0:
            logger.warning(f'MuMuManager {action} failed, returncode {result.returncode}')
            return False
        return True

    def _emulator_start(self, instance: EmulatorInstance):
        """
        Start a emulator without error handling
        """
        exe: str = instance.emulator.path
        if instance == Emulator.MuMuPlayer:
            # NemuPlayer.exe
            self.execute(exe)
        elif instance == Emulator.MuMuPlayerX:
            # NemuPlayer.exe -m nemu-12.0-x64-default
            self.execute(f'"{exe}" -m {instance.name}')
        elif instance == Emulator.MuMuPlayer12:
            # MuMuManager.exe api -v 0 launch_player
            # Launch via MuMuManager instead of MuMuPlayer.exe/MuMuNxMain.exe.
            # MuMuNxMain.exe is a GUI singleton, if two instances get launched at the same time,
            # the second launch request is handed over to a MuMuNxMain.exe that is still initializing
            # and gets silently dropped, while MuMuManager queues requests in backend service.
            if instance.MuMuPlayer12_id is None:
                logger.warning(f'Cannot get MuMu instance index from name {instance.name}')
                return False
            return self._mumu_manager_api(
                Emulator.single_to_console(exe), instance.MuMuPlayer12_id, 'launch_player'
            )
        elif instance == Emulator.LDPlayer14 or instance == Emulator.LDPlayer9:
            # ldconsole.exe launch --index 0 --mini
            # LDPlayer above 9 has `--mini` to start as minimized window, `--hide` to start with no frontend window
            self.execute(f'"{Emulator.single_to_console(exe)}" launch --index {instance.LDPlayer_id} --mini')
        elif instance == Emulator.LDPlayerFamily:
            # ldconsole.exe launch --index 0
            self.execute(f'"{Emulator.single_to_console(exe)}" launch --index {instance.LDPlayer_id}')
        elif instance == Emulator.NoxPlayerFamily:
            # Nox.exe -clone:Nox_1
            self.execute(f'"{exe}" -clone:{instance.name}')
        elif instance == Emulator.BlueStacks5:
            # HD-Player.exe --instance Pie64
            self.execute(f'"{exe}" --instance {instance.name}')
        elif instance == Emulator.BlueStacks4:
            # Bluestacks.exe -vmname Android_1
            self.execute(f'"{exe}" -vmname {instance.name}')
        elif instance == Emulator.MEmuPlayer:
            # MEmu.exe MEmu_0
            self.execute(f'"{exe}" {instance.name}')
        else:
            raise EmulatorUnknown(f'Cannot start an unknown emulator instance: {instance}')

    def _emulator_stop(self, instance: EmulatorInstance):
        """
        Stop a emulator without error handling
        """
        exe: str = instance.emulator.path
        if instance == Emulator.MuMuPlayer:
            # MuMu6 does not have multi instance, kill one means kill all
            # Has 4 processes
            # "C:\Program Files\NemuVbox\Hypervisor\NemuHeadless.exe" --comment nemu-6.0-x64-default --startvm
            # "E:\ProgramFiles\MuMu\emulator\nemu\EmulatorShell\NemuPlayer.exe"
            # E:\ProgramFiles\MuMu\emulator\nemu\EmulatorShell\NemuService.exe
            # "C:\Program Files\NemuVbox\Hypervisor\NemuSVC.exe" -Embedding
            self.kill_process_by_regex(
                rf'('
                rf'NemuHeadless.exe'
                rf'|NemuPlayer.exe\"'
                rf'|NemuPlayer.exe$'
                rf'|NemuService.exe'
                rf'|NemuSVC.exe'
                rf')'
            )
        elif instance == Emulator.MuMuPlayerX:
            # MuMu X has 3 processes
            # "E:\ProgramFiles\MuMu9\emulator\nemu9\EmulatorShell\NemuPlayer.exe" -m nemu-12.0-x64-default -s 0 -l
            # "C:\Program Files\Muvm6Vbox\Hypervisor\Muvm6Headless.exe" --comment nemu-12.0-x64-default --startvm xxx
            # "C:\Program Files\Muvm6Vbox\Hypervisor\Muvm6SVC.exe" --Embedding
            self.kill_process_by_regex(
                rf'('
                rf'NemuPlayer.exe.*-m {instance.name}'
                rf'|Muvm6Headless.exe'
                rf'|Muvm6SVC.exe'
                rf')'
            )
        elif instance == Emulator.MuMuPlayer12:
            # MuMuManager.exe api -v 1 shutdown_player
            if instance.MuMuPlayer12_id is None:
                logger.warning(f'Cannot get MuMu instance index from name {instance.name}')
                return False
            return self._mumu_manager_api(
                Emulator.single_to_console(exe), instance.MuMuPlayer12_id, 'shutdown_player'
            )
        elif instance == Emulator.LDPlayerFamily:
            # ldconsole.exe quit --index 0
            self.execute(f'"{Emulator.single_to_console(exe)}" quit --index {instance.LDPlayer_id}')
        elif instance == Emulator.NoxPlayerFamily:
            # Nox.exe -clone:Nox_1 -quit
            self.execute(f'"{exe}" -clone:{instance.name} -quit')
        elif instance == Emulator.BlueStacks5:
            # BlueStack has 2 processes
            # C:\Program Files\BlueStacks_nxt_cn\HD-Player.exe --instance Pie64
            # C:\Program Files\BlueStacks_nxt_cn\BstkSVC.exe -Embedding
            self.kill_process_by_regex(
                rf'('
                rf'HD-Player.exe.*"--instance" "{instance.name}"'
                rf')'
            )
        elif instance == Emulator.BlueStacks4:
            # E:\Program Files (x86)\BluestacksCN\bsconsole.exe quit --name Android
            self.execute(f'"{Emulator.single_to_console(exe)}" quit --name {instance.name}')
        elif instance == Emulator.MEmuPlayer:
            # F:\Program Files\Microvirt\MEmu\memuc.exe stop -n MEmu_0
            self.execute(f'"{Emulator.single_to_console(exe)}" stop -n {instance.name}')
        else:
            raise EmulatorUnknown(f'Cannot stop an unknown emulator instance: {instance}')

    def _emulator_function_wrapper(self, func: callable):
        """
        Args:
            func (callable): _emulator_start or _emulator_stop

        Returns:
            bool: If success
        """
        try:
            result = func(self.emulator_instance)
        except OSError as e:
            msg = str(e)
            # OSError: [WinError 740] 请求的操作需要提升。
            if 'WinError 740' in msg:
                logger.error('To start/stop MumuAppPlayer, ALAS needs to be run as administrator')
        except EmulatorUnknown as e:
            logger.error(e)
        except Exception as e:
            logger.exception(e)
        else:
            # Legacy emulator branches return None; MuMuManager returns a bool.
            if result is not False:
                return True

        logger.error(f'Emulator function {func.__name__}() failed')
        return False

    def emulator_start_watch(self):
        """
        Returns:
            bool: True if startup completed
                False if timeout
        """
        logger.hr('Emulator start', level=2)
        current_window = get_focused_window()
        instance = self.emulator_instance
        serial = instance.serial
        mumu12 = instance == Emulator.MuMuPlayer12
        logger.info(f'Current window: {current_window}')

        def adb_connect():
            m = self.adb_client.connect(self.serial)
            if 'connected' in m:
                # Connected to 127.0.0.1:59865
                # Already connected to 127.0.0.1:59865
                return False
            elif '(10061)' in m:
                # cannot connect to 127.0.0.1:55555:
                # No connection could be made because the target machine actively refused it. (10061)
                return False
            else:
                return True

        @run_once
        def show_online(m):
            logger.info(f'Emulator online: {m}')

        @run_once
        def show_ping(m):
            logger.info(f'Command ping: {m}')

        @run_once
        def show_package(m):
            logger.info(f'Found azurlane packages: {m}')

        interval = Timer(0.5).start()
        timeout = Timer(180).start()
        serial_timer = Timer(5).start()
        new_window = 0
        while 1:
            interval.wait()
            interval.reset()
            if timeout.reached():
                logger.warning(f'Emulator start timeout')
                return False

            # Check emulator window showing up
            # logger.info([get_focused_window(), get_window_title(get_focused_window())])
            if current_window != 0 and new_window == 0:
                new_window = get_focused_window()
                if current_window != new_window:
                    logger.info(f'New window showing up: {new_window}, focus back')
                    set_focus_window(current_window)
                else:
                    new_window = 0

            # Check device connection
            devices = self.list_device().select(serial=serial)
            if mumu12 and not devices.select(status='device') and serial_timer.reached():
                serial_timer.reset()
                # MuMu can change the forwarded port while starting this VM.
                candidate = next((item for item in instance.emulator.iter_instances()
                                  if item.name == instance.name and item.serial), None)
                if candidate is not None and candidate.serial != serial:
                    logger.info(f'Emulator serial changed: {serial} -> {candidate.serial}')
                    serial = self.serial = self.config.Emulator_Serial = candidate.serial
                    self.emulator_instance = candidate
                    del_cached_property(self, 'adb')
                    adb_connect()
                    continue
            # logger.info(devices)
            if devices:
                device: AdbDeviceWithStatus = devices.first_or_none()
                if device.status == 'device':
                    # Emulator online
                    pass
                if device.status == 'offline':
                    self.adb_client.disconnect(serial)
                    adb_connect()
                    continue
            else:
                # Try to connect
                adb_connect()
                continue
            show_online(devices.first_or_none())

            # Check command availability
            try:
                pong = self.adb_shell(['echo', 'pong'])
                if mumu12 and self.adb_shell(['getprop', 'sys.boot_completed']).strip() != '1':
                    continue
            except Exception as e:
                logger.info(e)
                continue
            show_ping(pong)

            # Check azuelane package
            packages = self.list_known_packages(show_log=False)
            if len(packages):
                pass
            else:
                continue
            show_package(packages)

            # All check passed
            break

        if new_window != 0 and new_window != current_window:
            logger.info(f'Minimize new window: {new_window}')
            minimize_window(new_window)
        if current_window:
            logger.info(f'De-flash current window: {current_window}')
            flash_window(current_window, flash=False)
        if new_window:
            logger.info(f'Flash new window: {new_window}')
            flash_window(new_window, flash=True)
        logger.info('Emulator start completed')
        return True

    def emulator_start(self):
        logger.hr('Emulator start', level=1)
        for _ in range(3):
            # Stop
            if not self._emulator_function_wrapper(self._emulator_stop):
                return False
            # Start
            if self._emulator_function_wrapper(self._emulator_start):
                if self.emulator_start_watch():
                    # Success
                    return True
                else:
                    # Start command was sent but emulator didn't come online, stop and start again
                    continue
            else:
                # Failed to start, stop and start again
                if self._emulator_function_wrapper(self._emulator_stop):
                    continue
                else:
                    return False

        logger.error('Failed to start emulator 3 times, stopped')
        return False

    def emulator_stop(self):
        logger.hr('Emulator stop', level=1)
        for _ in range(3):
            # Stop
            if self._emulator_function_wrapper(self._emulator_stop):
                # Success
                return True
            else:
                # Failed to stop, start and stop again
                if self._emulator_function_wrapper(self._emulator_start):
                    continue
                else:
                    return False

        logger.error('Failed to stop emulator 3 times, stopped')
        return False
    
if __name__ == '__main__':
    self = PlatformWindows('alas')
    d = self.emulator_instance
    print(d)
