"""Regenerate the game / namespace dropdowns inside spec_editor.html.

The editor is a single static file opened from disk, so it cannot look at the
repository itself. This script keeps the two lists it carries in sync with the
folders that actually exist, which is the same arrangement asset_maker.html
uses and the same thing that goes wrong when it is forgotten: a new game simply
never shows up in the dropdown.

A game is a folder under `module/` that has both `assets.py` and `page.py`,
because that is the minimum the generator needs to import. A namespace is a
folder under `assets/` other than `gui`; a namespace may exist before its module
does (star savior is in that state), and it is listed for that reason.

Usage:
    python -m dev_tools.spec_games
"""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, 'dev_tools', 'spec_editor.html')

BEGIN = '/* GAMES:BEGIN'
END = '/* GAMES:END */'


def scan():
    """
    Read the repository and return what the dropdowns should offer.

    Returns:
        tuple: (games, namespaces) as sorted lists of folder names.
    """
    module_root = os.path.join(ROOT, 'module')
    games = []
    for name in sorted(os.listdir(module_root)):
        folder = os.path.join(module_root, name)
        if not os.path.isdir(folder):
            continue
        if os.path.isfile(os.path.join(folder, 'assets.py')) and os.path.isfile(os.path.join(folder, 'page.py')):
            games.append(name)

    assets_root = os.path.join(ROOT, 'assets')
    namespaces = []
    for name in sorted(os.listdir(assets_root)):
        folder = os.path.join(assets_root, name)
        if not os.path.isdir(folder):
            continue
        # A game namespace holds `assets/<ns>/<ns>/`, the folder its assets are
        # generated into. `gui` and `gooey` are the framework's own, and they do
        # not have one, which is what keeps them out of the list.
        if not os.path.isdir(os.path.join(folder, name)):
            continue
        namespaces.append(name)

    # A game that has assets but no module yet is still worth listing: its cards
    # can be drawn before a line of code exists. `spec_build --write` lays down
    # the module skeleton on the first build.
    for name in namespaces:
        if name not in games:
            games.append(name)
    games.sort()

    return games, namespaces


def render(games, namespaces):
    """Build the JavaScript block that replaces the old one."""
    return (
        f'{BEGIN} 由 dev_tools/spec_games.py 扫描仓库生成，加了新游戏后跑一次 */\n'
        f'const GAMES={json.dumps(list(games))};\n'
        f'const NAMESPACES={json.dumps(list(namespaces))};\n'
        f'{END}'
    )


def main():
    games, namespaces = scan()
    with open(HTML, encoding='utf-8') as f:
        text = f.read()

    head, sep, rest = text.partition(BEGIN)
    if not sep:
        raise SystemExit(f'{BEGIN} not found in {HTML}, nothing to replace')
    _, sep, tail = rest.partition(END)
    if not sep:
        raise SystemExit(f'{END} not found in {HTML}, nothing to replace')

    text = head + render(games, namespaces) + tail
    with open(HTML, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)

    print(f'games      {len(games):2d}  {", ".join(games)}')
    print(f'namespaces {len(namespaces):2d}  {", ".join(namespaces)}')


if __name__ == '__main__':
    main()
