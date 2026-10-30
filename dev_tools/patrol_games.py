"""Run every enabled task of one or more games, in the order the scheduler uses.

The scheduler itself is not started: each task's `run()` is called once, with
the game brought to the front exactly like `switch_game()` does, and `task_delay`
at the end of every task writes `Scheduler.NextRun` as usual. So the pass leaves
the config in the state a real run would, and the next scheduled run of each
task is the real one rather than "right now".

The order comes from `SCHEDULER_PRIORITY` in `config_manual.py`, which is the
same string the scheduler parses, so the pass cannot drift from the user's queue.

A task that dies hard (`exit(1)` in `AlGS.run`) takes the whole scheduler down in
production. Here it is caught instead: the failure is recorded, the next task is
tried, and three failures in a row inside one game skip the rest of that game -
the page it was left on is probably unknown, and every task after it would fail
on the same frame.

Usage:
    ./toolkit/python.exe -m dev_tools.patrol_games
    ./toolkit/python.exe -m dev_tools.patrol_games hazeworld browndust
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import inflection

from algs import AlGS
from module.base.decorator import del_cached_property
from module.config.config import Function
from module.config.server import to_package
from module.logger import logger

GAMES = ['hazeworld', 'lostsword', 'browndust']

# Three failures back to back leave the game on a page the loop cannot name, so
# the rest of the block would only repeat the same dump.
FAILS_BEFORE_SKIP = 3


def task_order(config, game):
    """
    Tasks of one game, in scheduler order, keeping only the enabled ones.

    Args:
        config (AlasConfig):
        game (str): Asset namespace, `hazeworld` for the `Hazeworld*` tasks.

    Returns:
        list[str]: Task names.
    """
    order = [part.strip() for part in config.SCHEDULER_PRIORITY.split('>')]
    order = [name for name in order if name]
    prefix = game.capitalize()
    return [name for name in order
            if name.startswith(prefix) and config.data[name]['Scheduler']['Enable']]


def patrol_game(algs, game):
    """
    Walk every enabled task of one game.

    Args:
        algs (AlGS):
        game (str):

    Returns:
        list[tuple[str, bool]]: (task, succeeded) in the order they ran.
    """
    config = algs.config
    tasks = task_order(config, game)
    logger.hr(f'Patrol {game}: {len(tasks)} tasks', level=1)
    if not tasks:
        logger.info(f'Nothing enabled for {game}, skip')
        return []

    # `Device` takes the package from the config at start up, and the value there
    # belongs to whichever game ran last. In memory only: `bind()` applies it and
    # nothing writes it back to the file.
    config.overridden['Emulator_PackageName'] = to_package(game)
    algs.switch_game(game, boot=True)

    results = []
    fails = 0
    for task in tasks:
        config = algs.config
        config.task = Function(config.data[task])
        config.bind(task)

        logger.info(f'Patrol: Start task `{task}`')
        logger.hr(task, level=0)
        try:
            success = algs.run(inflection.underscore(task))
        except SystemExit as e:
            # `run()` calls `exit(1)` on the errors a scheduler cannot survive.
            # Recording it keeps the pass going, which is the point of a patrol.
            logger.critical(f'Patrol: task `{task}` exited hard, code {e.code}')
            success = False
        logger.info(f'Patrol: End task `{task}`, success={success}')
        results.append((task, bool(success)))
        del_cached_property(algs, 'config')

        if success:
            fails = 0
            continue

        fails += 1
        if fails >= FAILS_BEFORE_SKIP:
            logger.critical(f'Patrol: {fails} tasks in a row failed in {game}, skip the rest')
            break

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('games', nargs='*',
                        help=f'Subset of {GAMES}, default all of them')
    args = parser.parse_args()
    games = args.games or GAMES
    for game in games:
        if game not in GAMES:
            logger.critical(f'Unknown game `{game}`, pick from {GAMES}')
            exit(1)

    algs = AlGS()
    summary = {}
    for game in games:
        summary[game] = patrol_game(algs, game)

    logger.hr('Patrol summary', level=0)
    total = 0
    failed = 0
    for game in games:
        rows = summary[game]
        ok = sum(1 for _, s in rows if s)
        total += len(rows)
        failed += len(rows) - ok
        logger.info(f'{game}: {ok}/{len(rows)} tasks ok')
        for task, success in rows:
            if not success:
                logger.warning(f'   failed: {task}')
    logger.info(f'Patrol done: {total - failed}/{total} tasks ok')


if __name__ == '__main__':
    main()
