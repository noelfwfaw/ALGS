# -*- coding: utf-8 -*-
"""Build the release archives that ship the built-in Python environment.

Why this exists:
    `toolkit/` (portable Python 3.7.6 + adb + every dependency) is 615 MB and is
    excluded by `.gitignore`, so GitHub's "Source code (zip)" never contains it.
    A fresh machine then fails with `[ERROR] toolkit\\python.exe not found.`

Usage:
    toolkit\\python.exe -m dev_tools.make_full_package --tag v1.43.0
    toolkit\\python.exe -m dev_tools.make_full_package --tag v1.43.0 --dry-run

Outputs (dist/, ignored by git):
    AlGS-<tag>-full.zip  -- AlGS/<tracked files> + AlGS/toolkit/**
    toolkit.zip          -- toolkit/** only, downloaded by start_algs.bat

The source part comes from `git ls-files` (tracked files only), so local
config/*.yaml, log/, .workbuddy/, module/pool/ and .git/ never leak into the
package. Commit before building so the archive matches the release tag.
"""
import argparse
import os
import subprocess
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, 'dist')
TOOLKIT = os.path.join(ROOT, 'toolkit')
PREFIX = 'AlGS'


def tracked_files():
    """Relative paths of every git-tracked file, all ASCII in this repo."""
    out = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT)
    return [p.decode('utf-8') for p in out.split(b'\0') if p]


def toolkit_files():
    """(absolute path, archive path) for every file under toolkit/."""
    for base, dirs, names in os.walk(TOOLKIT):
        dirs[:] = sorted(d for d in dirs if d != '__pycache__')
        for name in sorted(names):
            path = os.path.join(base, name)
            rel = os.path.relpath(path, TOOLKIT).replace(os.sep, '/')
            yield path, 'toolkit/' + rel


def verify(full, env):
    """Fail loudly if the archives could not boot a fresh machine."""
    with zipfile.ZipFile(full) as z:
        names = set(z.namelist())
        required = [
            PREFIX + '/toolkit/python.exe',
            PREFIX + '/start_algs.bat',
            PREFIX + '/gui.py',
            PREFIX + '/deploy/template',
            PREFIX + '/config/template.json',
        ]
        missing = [n for n in required if n not in names]
        models = [n for n in names if '/cnocr_models/' in n]
        if missing:
            raise SystemExit('full package is missing: %s' % missing)
        if not models:
            raise SystemExit('full package has no cnocr models')
        print('full package  : %d entries, %d OCR model files' % (
            len(names), len(models)))
    with zipfile.ZipFile(env) as z:
        names = set(z.namelist())
        if 'toolkit/python.exe' not in names:
            raise SystemExit('toolkit.zip has no python.exe')
        print('env package   : %d entries' % len(names))


def build(tag, dry_run=False):
    if not os.path.isfile(os.path.join(TOOLKIT, 'python.exe')):
        raise SystemExit('toolkit/python.exe missing, cannot build packages')

    tracked = tracked_files()
    tk = list(toolkit_files())
    full = os.path.join(DIST, 'AlGS-%s-full.zip' % tag)
    env = os.path.join(DIST, 'toolkit.zip')
    print('tracked files : %d' % len(tracked))
    print('toolkit files : %d' % len(tk))
    print('outputs       : %s / %s' % (
        os.path.basename(full), os.path.basename(env)))
    if dry_run:
        return

    if not os.path.isdir(DIST):
        os.makedirs(DIST)
    for target in (full, env):
        if os.path.isfile(target):
            os.remove(target)

    with zipfile.ZipFile(full, 'w', zipfile.ZIP_DEFLATED, compresslevel=6,
                         allowZip64=True) as z:
        for rel in tracked:
            z.write(os.path.join(ROOT, rel), PREFIX + '/' + rel)
        for path, rel in tk:
            z.write(path, PREFIX + '/' + rel)
    with zipfile.ZipFile(env, 'w', zipfile.ZIP_DEFLATED, compresslevel=6,
                         allowZip64=True) as z:
        for path, rel in tk:
            z.write(path, rel)

    for target in (full, env):
        print('%-30s %.1f MB' % (os.path.basename(target),
                                 os.path.getsize(target) / 1024.0 / 1024))
    verify(full, env)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--tag', required=True,
                        help='release tag, e.g. v1.43.0')
    parser.add_argument('--dry-run', action='store_true',
                        help='only count files, do not write archives')
    args = parser.parse_args()
    build(args.tag, args.dry_run)
