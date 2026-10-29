"""The local ledger of coupon codes: what was already redeemed, what is dead.

One file per game, e.g. `config/state/lostsword_codes.json` - a subfolder of
`config/`, on purpose. `module/config/utils.py` builds the instance dropdown of
the WebUI out of `os.listdir('./config')`, taking every top-level `*.json` as an
instance name (`alas_instance()`, and `list_mod_instance()` for the modded
ones). A ledger sitting next to `alas.json` shows up there as an instance called
`lostsword_codes`, and picking it runs the scheduler against a file that has no
`Alas` section. Both enumerators only read the top level, so a subfolder is
invisible to them.

The ledger is runtime state, not code, and `config/state/` is out of the
repository:

    {
      "updated_at": "2026-10-29 10:40:00",
      "codes": {
        "LTSDREKINDLED": {
          "status": "used",
          "content": "★5角色召唤 x1 + ★5宠物召唤 x1 + 1000钻石",
          "end_at": "2026-12-31 23:00:00",
          "checked_at": "2026-10-29 10:40:00"
        }
      }
    }

Five statuses, and every one of them means "do not try again":

    redeemed   the game took it
    used       the code was spent before (「已使用过的优惠券」 / 「本序列号已使用完毕」)
    expired    past `end_at`, or gone from the list without ever being sent
    invalid    the server does not know the code - 棕色尘埃2 answers this with
               「无效的序列号」. Not the same thing as expired: the code may
               still be inside its `end_at` and simply never existed.
    failed     the game answered something that could not be read; retrying the
               same code every day would just repeat the same failure

The point of `failed` is the opposite of the other four: a code that could not
be read is kept out of the retry loop for good, because a task that retries the
one broken entry every day never gets to the new ones in a useful order.
"""

import datetime
import json
import os

from module.logger import logger

REDEEMED = 'redeemed'
USED = 'used'
EXPIRED = 'expired'
INVALID = 'invalid'
FAILED = 'failed'

# Every one of them means the code will not be sent to the game again.
SETTLED = (REDEEMED, USED, EXPIRED, INVALID, FAILED)


class CodeBook:
    """
    Read, query and update the ledger.

    It is deliberately a plain file under `config/state/`: the user can open it,
    delete a line to retry a code, and nothing else in the run depends on it.
    """

    def __init__(self, file):
        """
        Args:
            file (str): Path of this game's ledger, e.g.
                `./config/state/lostsword_codes.json`. Required, because a
                default would silently mix the two games' codes.
        """
        self.file = file
        self.data = self.load()

    def load(self):
        """
        Read the ledger, tolerating a missing or broken file.

        A broken ledger must not stop the task: losing the record means the
        codes get tried again, which the game answers with 「已使用过的优惠券」
        - one wasted round trip, not a failure.

        Returns:
            dict: `{'updated_at': str, 'codes': {code: entry}}`.
        """
        if not os.path.exists(self.file):
            logger.info(f'No coupon ledger yet, starting one: {self.file}')
            return {'codes': {}}

        try:
            with open(self.file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            logger.warning(f'Coupon ledger is unreadable, starting over: {e}')
            return {'codes': {}}

        if not isinstance(data, dict) or not isinstance(data.get('codes'), dict):
            logger.warning('Coupon ledger has an unexpected shape, starting over')
            return {'codes': {}}
        return data

    @property
    def codes(self):
        return self.data.setdefault('codes', {})

    def save(self):
        """
        Write the ledger back, creating the folder if needed.
        """
        folder = os.path.dirname(self.file)
        if folder and not os.path.exists(folder):
            os.makedirs(folder)

        self.data['updated_at'] = now_text()
        try:
            with open(self.file, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2, sort_keys=True)
                f.write('\n')
        except OSError as e:
            logger.warning(f'Could not write the coupon ledger: {e}')

    def pending(self, codes):
        """
        Keep the codes that are worth sending to the game today.

        Args:
            codes (list[dict]): Fresh list from `gamekee.fetch_codes()`.

        Returns:
            list[dict]: Same shape, in the order given.
        """
        now = datetime.datetime.now()
        todo = []
        for code in codes:
            entry = self.codes.get(code['code'])
            if entry and entry.get('status') in SETTLED:
                continue
            if code['end_at'] <= now:
                # The endpoint filters by itself; this is the second opinion.
                self.mark(code, EXPIRED)
                continue
            todo.append(code)
        return todo

    def mark(self, code, status, detail=''):
        """
        Record the outcome of one code.

        Args:
            code (dict): `{'code', 'content', 'end_at'}` of the code.
            status (str): One of `SETTLED`.
            detail (str): What the game said, for the log and for the user who
                opens the file later.
        """
        self.codes[code['code']] = {
            'status': status,
            'content': code.get('content', ''),
            'end_at': code['end_at'].strftime('%Y-%m-%d %H:%M:%S'),
            'checked_at': now_text(),
        }
        if detail:
            self.codes[code['code']]['detail'] = detail

    def log_summary(self):
        """
        Print how many codes sit in each status, so the log answers "why did
        nothing happen today" at a glance.
        """
        counts = {}
        for entry in self.codes.values():
            status = entry.get('status', '?')
            counts[status] = counts.get(status, 0) + 1
        if counts:
            logger.attr('Coupon ledger', ', '.join(
                f'{k}={v}' for k, v in sorted(counts.items())))
        else:
            logger.attr('Coupon ledger', 'empty')


def now_text():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
