"""Keep recent automatic screenshot and diagnostic records together."""

import re
import stat
import time
from datetime import date
from pathlib import Path

from filelock import FileLock, Timeout


MIB = 1024 * 1024
TEXT_FILE_BYTES = 16 * MIB
TEXT_TOTAL_BYTES = 100 * MIB
TEXT_MAX_AGE = 7 * 86400
TEXT_MAINTENANCE_INTERVAL = 60
TEXT_NAME = re.compile(r'(\d{4}-\d{2}-\d{2})_.+\.txt(?:\.\d{19})?')
DIAGNOSTIC_TOTAL_BYTES = 200 * MIB
ERROR_BUNDLE_BYTES = 16 * MIB
ERROR_LOG_BYTES = 1 * MIB
DIAGNOSTIC_LIMITS = {
    'event': (r'(\d{6}_\d+)\.(?:png|json)', 64, 48 * MIB),
    'card': (r'(\d{6})(?:_c[1-3])?\.(?:png|json)', 64, 12 * MIB),
    'fate': (r'(\d{6})(?:_effect[1-3])?\.(?:png|json)', 64, 16 * MIB),
    'unknown': (r'(unknown_\d{6})\.png', 64, 24 * MIB),
    'screenshot': (r'(\d{13})\.png', 16, 8 * MIB),
    'error': (r'(\d{13})', 15, 48 * MIB),
}
ERROR_FILE = re.compile(r'log\.txt|\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}-\d{6}\.png')


def _plain_path(info):
    return not (stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0)
                & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _prune_text_logs(folder, active):
    files = []
    for path in folder.iterdir():
        match = TEXT_NAME.fullmatch(path.name)
        if not match:
            continue
        try:
            date.fromisoformat(match[1])
            info = path.lstat()
            if stat.S_ISREG(info.st_mode) and _plain_path(info):
                files.append((info.st_mtime, path, info))
        except (OSError, ValueError):
            continue
    files.sort()
    total = sum(info.st_size for _, _, info in files)
    now = time.time()
    removed = 0
    for modified, path, info in files:
        expired = now - modified > TEXT_MAX_AGE
        over_quota = total > TEXT_TOTAL_BYTES and (
            path.suffix != '.txt' or now - modified > 30)
        if path == active or not (expired or over_quota):
            continue
        try:
            if path.lstat() == info:
                path.unlink()
                total -= info.st_size
                removed += info.st_size
        except OSError:
            continue
    return removed


def prune_text_logs(folder):
    """Apply the text quota without racing writers from other app processes."""
    folder = Path(folder).absolute()
    try:
        if not _plain_path(folder.lstat()):
            return 0
        with FileLock(str(folder / '.text-log.lock'), timeout=1):
            return _prune_text_logs(folder, None)
    except (OSError, Timeout):
        return 0


class TextLogStream:
    """Rich writes and flushes one rendered record at a time."""

    encoding = 'utf-8'

    def __init__(self, path):
        self.path = Path(path).absolute()
        self._pending = []
        self._last_cleanup = float('-inf')

    def write(self, text):
        self._pending.append(text)
        return len(text)

    def flush(self):
        if not self._pending:
            return
        data = ''.join(self._pending).encode(self.encoding, errors='replace')
        self._pending.clear()
        if len(data) > TEXT_FILE_BYTES:
            data = data[-TEXT_FILE_BYTES:].decode(self.encoding, errors='ignore').encode(self.encoding)
        folder = self.path.parent
        maintenance = False
        try:
            folder.mkdir(exist_ok=True)
            if not _plain_path(folder.lstat()):
                return
            with FileLock(str(folder / '.text-log.lock'), timeout=1):
                try:
                    info = self.path.lstat()
                except FileNotFoundError:
                    info = None
                if info is not None and not (stat.S_ISREG(info.st_mode) and _plain_path(info)):
                    return
                rotated = info is not None and info.st_size + len(data) > TEXT_FILE_BYTES
                if rotated:
                    self.path.rename(self.path.with_name(f'{self.path.name}.{time.time_ns()}'))
                with self.path.open('ab') as handle:
                    handle.write(data)
                now = time.monotonic()
                maintenance = now - self._last_cleanup >= TEXT_MAINTENANCE_INTERVAL
                if maintenance:
                    self._last_cleanup = now
                if rotated or maintenance:
                    _prune_text_logs(folder, self.path)
        except (OSError, Timeout):
            # A locked rollover is retried on the next record, while Rich still logs to the console.
            pass
        if maintenance:
            prune_runtime_diagnostics(folder)


def _error_files(folder):
    files = []
    for path in folder.iterdir():
        info = path.lstat()
        if not (ERROR_FILE.fullmatch(path.name) and stat.S_ISREG(info.st_mode)
                and _plain_path(info)):
            return None
        files.append((path, info))
    return files


def _diagnostic_records(folder, kind):
    pattern = DIAGNOSTIC_LIMITS[kind][0]
    groups = {}
    try:
        if any(not _plain_path(path.lstat()) for path in (folder, *folder.parents)):
            return []
        for path in folder.iterdir():
            match = re.fullmatch(pattern, path.name)
            if not match:
                continue
            try:
                info = path.lstat()
                if not _plain_path(info):
                    continue
                if kind == 'error' and stat.S_ISDIR(info.st_mode):
                    files = _error_files(path)
                    if files is not None:
                        groups[match[1]] = files, path, info.st_mtime
                elif kind != 'error' and stat.S_ISREG(info.st_mode):
                    files, _, _ = groups.setdefault(match[1], ([], None, 0))
                    files.append((path, info))
            except OSError:
                continue
    except OSError:
        return []

    records = []
    for name, (files, directory, mtime) in groups.items():
        size = sum(info.st_size for _, info in files)
        latest = max([mtime] + [info.st_mtime for _, info in files])
        records.append((latest, name, size, files, directory))
    return records


def _prune_diagnostic_records(records, max_groups, max_bytes, keep_latest):
    records.sort(key=lambda record: record[:2])
    remaining = len(records)
    total = sum(record[2] for record in records)
    removed = 0
    # Allow other processes to finish writing a page before pruning it.
    cutoff = time.time() - 30
    for index, (latest, _, _, files, directory) in enumerate(records):
        if remaining <= max_groups and total <= max_bytes:
            break
        if latest > cutoff or (keep_latest and index == len(records) - 1):
            break
        failed = False
        for path, info in files:
            try:
                if path.lstat() != info:
                    failed = True
                    continue
                path.unlink()
                removed += info.st_size
            except FileNotFoundError:
                pass
            except OSError:
                failed = True
                continue
            total -= info.st_size
        if directory is not None and not failed:
            try:
                directory.rmdir()
            except FileNotFoundError:
                pass
            except OSError:
                failed = True
        if not failed:
            remaining -= 1
    return removed


def prune_diagnostics(folder, kind):
    """Prune oldest complete records in one producer directory."""
    _, max_groups, max_bytes = DIAGNOSTIC_LIMITS[kind]
    records = _diagnostic_records(Path(folder).absolute(), kind)
    return _prune_diagnostic_records(records, max_groups, max_bytes, keep_latest=True)


def prune_runtime_diagnostics(folder):
    """Apply one budget to the automatic diagnostic records across all games."""
    folder = Path(folder).absolute()
    try:
        if any(not _plain_path(path.lstat()) for path in (folder, *folder.parents)):
            return 0
    except OSError:
        return 0
    sources = [(folder / 'rogue_event_pages', 'event'), (folder / 'rogue_pages', 'unknown'),
               (folder / 'error', 'error')]
    sources.extend((folder / 'rogue_card_pages' / kind, 'card')
                   for kind in ('copy', 'flash', 'god', 'meditate', 'remove', 'reward'))
    sources.extend((folder / 'rogue_fate_pages' / kind, 'fate') for kind in ('core', 'main'))
    try:
        errors = folder / 'error'
        if _plain_path(errors.lstat()):
            sources.extend((child, 'screenshot') for child in errors.iterdir()
                           if not child.name.isdecimal())
    except OSError:
        pass
    records = [record for path, kind in sources for record in _diagnostic_records(path, kind)]
    return _prune_diagnostic_records(records, len(records), DIAGNOSTIC_TOTAL_BYTES, keep_latest=False)
