# -*- coding: utf-8 -*-
"""Upload built archives to a GitHub Release.

Usage:
    toolkit\\python.exe -m dev_tools.upload_release_assets --tag v1.43.0 \
        --assets dist/AlGS-v1.43.0-full.zip dist/toolkit.zip

Notes:
    - GitHub release assets go to `uploads.github.com`, NOT `api.github.com`.
    - Only proxy 7897 works here; a direct connection to api.github.com is
      hijacked by the local hosts file.
    - Token comes from `git credential fill`, same as publish.py.
    - Same-named assets are deleted first so a re-run never hits HTTP 422.
"""
import argparse
import os
import subprocess
import sys
import time
from urllib.parse import quote

import requests

REPO = 'noelfwfaw/ALGS'
PROXY = 'http://127.0.0.1:7897'
PROXIES = {'http': PROXY, 'https': PROXY}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = 'https://api.github.com/repos/%s' % REPO
UPLOAD = 'https://uploads.github.com/repos/%s' % REPO


class ProgressFile(object):
    """File object that reports read progress; __len__ keeps Content-Length."""

    def __init__(self, path):
        self.f = open(path, 'rb')
        self.total = os.path.getsize(path)
        self.done = 0
        self.step = max(self.total // 10, 1)
        self.next_report = self.step

    def __len__(self):
        return self.total

    def read(self, size=-1):
        chunk = self.f.read(size)
        self.done += len(chunk)
        if self.done >= self.next_report and self.total:
            print('    %3d%%  %.1f / %.1f MB' % (
                min(100, self.done * 100 // self.total),
                self.done / 1024.0 / 1024,
                self.total / 1024.0 / 1024), flush=True)
            self.next_report += self.step
        return chunk

    def close(self):
        self.f.close()


def git_token():
    out = subprocess.run(
        ['git', 'credential', 'fill'],
        input='protocol=https\nhost=github.com\n\n',
        stdout=subprocess.PIPE, universal_newlines=True,
    ).stdout
    cred = dict(line.split('=', 1) for line in out.strip().splitlines()
                if '=' in line)
    token = cred.get('password', '')
    if not token:
        raise SystemExit('no GitHub token from `git credential fill`')
    return token


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tag', required=True)
    parser.add_argument('--assets', nargs='+', required=True,
                        help='local files, basename becomes the asset name')
    args = parser.parse_args()

    for key in ('HTTPS_PROXY', 'https_proxy', 'HTTP_PROXY', 'http_proxy'):
        os.environ[key] = PROXY
    bundle = os.path.join(ROOT, 'toolkit', 'ca-bundle.pem')
    if os.path.isfile(bundle):
        os.environ['REQUESTS_CA_BUNDLE'] = bundle

    token = git_token()
    headers = {'Authorization': 'token ' + token,
               'Accept': 'application/vnd.github+json'}

    release = requests.get(API + '/releases/tags/' + args.tag,
                           headers=headers, proxies=PROXIES, timeout=60)
    if release.status_code != 200:
        raise SystemExit('release %s not found: HTTP %s %s' % (
            args.tag, release.status_code, release.text[:200]))
    data = release.json()
    release_id = data['id']
    print('release %s -> id %s' % (args.tag, release_id))

    existing = {a['name']: a['id'] for a in data.get('assets', [])}
    for path in args.assets:
        name = os.path.basename(path)
        if not os.path.isfile(path):
            raise SystemExit('missing local file: %s' % path)
        size = os.path.getsize(path)
        print('%s  %.1f MB' % (name, size / 1024.0 / 1024), flush=True)
        if name in existing:
            old = requests.delete(
                API + '/releases/assets/%s' % existing[name],
                headers=headers, proxies=PROXIES, timeout=60)
            print('  removed old asset: HTTP %s' % old.status_code, flush=True)

        url = UPLOAD + '/releases/%s/assets?name=%s' % (
            release_id, quote(name))
        upload_headers = dict(headers)
        upload_headers['Content-Type'] = 'application/zip'
        upload_headers['Content-Length'] = str(size)
        stream = ProgressFile(path)
        started = time.time()
        try:
            response = requests.post(url, headers=upload_headers, data=stream,
                                     proxies=PROXIES, timeout=(30, 1800))
        finally:
            stream.close()
        print('  HTTP %s in %.1fs' % (
            response.status_code, time.time() - started), flush=True)
        if response.status_code not in (200, 201):
            print(response.text[:500])
            raise SystemExit('upload failed for %s' % name)

    check = requests.get(API + '/releases/tags/' + args.tag,
                         headers=headers, proxies=PROXIES, timeout=60).json()
    remote = {a['name']: a['size'] for a in check.get('assets', [])}
    print('remote assets: %s' % remote)
    for path in args.assets:
        name = os.path.basename(path)
        if remote.get(name) != os.path.getsize(path):
            raise SystemExit('size mismatch for %s' % name)
    print('ALL ASSETS VERIFIED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
