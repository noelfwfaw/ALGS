"""Run one task against the device, the way the scheduler would.

The scheduler is skipped on purpose: the game is brought to the front, the
config is bound to the task and the task's `run()` is called once. Everything
else (delays, error handling) works as usual, so the run also writes
`Scheduler.NextRun` of that task.

Usage:
    ./toolkit/python.exe -m dev_tools.run_task LostswordShop
    ./toolkit/python.exe -m dev_tools.run_task LostswordAffection --no-boot

The game is taken from the task name (`Lostsword*` / `Hazeworld*`), so the
namespace and the package are right without being repeated on the command line.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import inflection

from algs import AlGS
from module.config.config import Function
from module.config.server import set_server, to_package
from module.logger import logger


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('task', help='Task name as written in task.yaml')
    parser.add_argument('--no-boot', action='store_true',
                        help='Do not launch the game, assume it is on screen')
    args = parser.parse_args()

    algs = AlGS()
    task = args.task

    game = algs.task_game(task)
    if game is None:
        logger.critical(f'Cannot tell which game `{task}` belongs to')
        exit(1)
    package = to_package(game)

    logger.hr(f'Run task `{task}` ({game})', level=1)
    config = algs.config
    # `Device` reads `Emulator.PackageName` and sets the asset namespace from it,
    # before the task has a chance to switch anything. The value of the user's
    # config belongs to the other game, so it is overridden in memory only:
    # `overridden` is applied by `bind()` and never written back to the file.
    config.overridden['Emulator_PackageName'] = package
    # `config.task` is a `Function` in the scheduler, and `Device.__init__` reads
    # its `command` to decide whether it is a real task, so a plain string fails
    # there. Build one from the config, like `get_next_task()` does.
    config.task = Function(config.data[task])
    config.bind(task)

    # Same order as `switch_game()`: namespace, package, then the records are
    # cleared so nothing from the other game is compared with these assets.
    set_server(game)
    algs.game = game
    algs.device.package = package
    algs.device.stuck_record_clear()
    algs.device.click_record_clear()

    if not args.no_boot:
        algs.start()
    algs.game_in_foreground = True

    algs.run(inflection.underscore(task))
    logger.info(f'Task `{task}` returned')


if __name__ == '__main__':
    main()
