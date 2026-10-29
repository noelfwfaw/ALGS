"""The coupon list of GameKee (gamekee.com).

The site is a Vue SPA: the page itself is a 3.6 KB shell and every list on it is
fetched as XHR from `/v1/**`. Those endpoints are same origin, need no login and
carry no signature - the single requirement is the `game-alias` header, without
it the server answers `403 缺少游戏信息`. So this module talks to the endpoint
and never renders a page.

The endpoint only returns codes that have not expired yet (`end_at` in the
future), which is why "a code that disappeared from the list" is the only
evidence of it expiring. `is_use` is useless here: it belongs to the logged-in
account and is always false for an anonymous request.

The research behind these details - how the endpoint was found with a Chrome
netlog, the full endpoint list, the incremental snapshot design - lives in the
library document 「GameKee抓取方案」.
"""

import datetime
import time

import requests

from module.logger import logger

API = 'https://www.gamekee.com/v1/game/cdk/query-list'
URL = 'https://www.gamekee.com/{alias}/redemptionCode/20'
# The list of this game never came close to 100 entries; the endpoint has no
# page count in `meta` (only request ids), so a second page would have to be
# guessed. One page it is.
PAGE_LIMIT = 100
# Backoff between attempts. A single network hiccup should not cost the day.
RETRY_DELAY = (1.5, 3.0, 4.5)
TIMEOUT = 20

HEADERS = {
    'game-alias': 'lostsword',
    'X-Requested-With': 'XMLHttpRequest',
    'Lang': 'zh-cn',
    # An empty UA is the easiest way to get rate limited.
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
}


class GameKeeError(Exception):
    """The site answered something the caller cannot use."""


def fetch_codes(alias='lostsword', limit=PAGE_LIMIT, timeout=TIMEOUT):
    """
    Read the coupon list and keep the ones that are still valid.

    Args:
        alias (str): Game alias, `lostsword` for Lost Sword. The first segment
            of the wiki URL is the same string.
        limit (int): Entries per page.
        timeout (int, float): Seconds per attempt.

    Returns:
        list[dict]: Newest first, each `{'code': str, 'content': str,
            'end_at': datetime.datetime}`.

    Raises:
        GameKeeError: After every attempt failed, with the reason of the last
            one. The caller decides whether that is worth a retry tomorrow.
    """
    headers = dict(HEADERS)
    headers['game-alias'] = alias
    referer = URL.format(alias=alias)
    headers['Referer'] = referer

    last = None
    for attempt, delay in enumerate(RETRY_DELAY, start=1):
        try:
            response = requests.get(
                API, params={'page_no': 1, 'limit': limit},
                headers=headers, timeout=timeout)
        except requests.RequestException as e:
            last = f'{type(e).__name__}: {e}'
            logger.warning(f'GameKee request failed ({attempt}/{len(RETRY_DELAY)}): {last}')
            time.sleep(delay)
            continue

        if response.status_code == 403:
            # The one failure that a retry cannot fix: the header is gone.
            raise GameKeeError(
                f'GameKee answered 403, the game-alias header was rejected: {referer}')
        if response.status_code != 200:
            last = f'HTTP {response.status_code}'
            logger.warning(f'GameKee answered {last} ({attempt}/{len(RETRY_DELAY)})')
            time.sleep(delay)
            continue

        try:
            payload = response.json()
        except ValueError as e:
            last = f'not JSON: {e}'
            logger.warning(f'GameKee sent {last} ({attempt}/{len(RETRY_DELAY)})')
            time.sleep(delay)
            continue

        code = payload.get('code')
        if code != 0:
            last = f'code={code} msg={payload.get("msg")}'
            logger.warning(f'GameKee refused the query ({attempt}/{len(RETRY_DELAY)}): {last}')
            time.sleep(delay)
            continue

        return normalize_codes(payload.get('data') or [])

    raise GameKeeError(f'GameKee did not answer in {len(RETRY_DELAY)} attempts, last: {last}')


def normalize_codes(items, now=None):
    """
    Turn the raw entries into the three fields the task uses, dropping expired.

    The endpoint is documented to return only codes that are still valid, but
    the task must never hand a dead code to the game: the date is checked again
    here rather than trusting the filter on the other side.

    Args:
        items (list[dict]): `data` of the response.
        now (datetime.datetime): For tests, defaults to the current time.

    Returns:
        list[dict]: `{'code', 'content', 'end_at'}`, newest first.
    """
    now = now or datetime.datetime.now()
    codes = []
    for item in items:
        code = (item.get('code') or '').strip()
        end_at = item.get('end_at')
        if not code or not end_at:
            continue
        end_at = datetime.datetime.fromtimestamp(int(end_at))
        if end_at <= now:
            continue
        codes.append(
            {
                'code': code,
                'content': (item.get('content') or '').strip(),
                'end_at': end_at,
            }
        )
    codes.sort(key=lambda c: c['end_at'], reverse=True)
    return codes
