"""
Rename assets from whatever the user typed (Chinese is fine) to ALAS style names.

`assets.py` is generated from file names, so a Chinese file name becomes
`邮件领取 = Button(...)` -- legal Python, but it breaks the project convention
(upper case ASCII identifiers) and makes the code unreadable.

This tool does the mechanical part: rename `邮件领取.png`, `邮件领取.BUTTON.png`,
`邮件领取.AREA.png`, `邮件领取.COLOR.png` and `TEMPLATE_邮件领取.png` in one go,
then rewrite `manifest.json` so the handoff document stays correct.

Usage:
    # See what is in the folder right now
    python -m dev_tools.asset_rename --module mygame --list

    # Rename
    python -m dev_tools.asset_rename --module mygame --map "邮件领取=MAIL_BTN_CLAIM,一键领取=MAIL_BTN_CLAIM_ALL"

    # Same thing from a json file {"邮件领取": "MAIL_BTN_CLAIM", ...}
    python -m dev_tools.asset_rename --module mygame --map-file rename.json

    # Check only, change nothing
    python -m dev_tools.asset_rename --module mygame --map "..." --dry-run

Run this BEFORE `dev_tools.button_extract`: the generator turns file names into
python identifiers, and undoing that means editing generated code by hand.
"""
import argparse
import json
import os

import module.config.server as server

SUFFIXES = ['', '.BUTTON', '.AREA', '.COLOR']
PREFIXES = ['', 'TEMPLATE_']
ASCII_OK = set('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_')


def asset_folder(namespace, module):
    """
    Args:
        namespace (str):
        module (str):

    Returns:
        str: Path of ./assets/<namespace>/<module>
    """
    return os.path.join('./assets', namespace, module)


def scan(folder):
    """
    Group png files by their base name, e.g.
    {'邮件领取': ['邮件领取.png', '邮件领取.BUTTON.png'], ...}

    Args:
        folder (str):

    Returns:
        dict[str, list[str]]
    """
    groups = {}
    if not os.path.isdir(folder):
        return groups
    for file in sorted(os.listdir(folder)):
        if not file.lower().endswith('.png'):
            continue
        stem = file[:-4]
        for suffix in SUFFIXES[1:]:
            if stem.endswith(suffix):
                stem = stem[:-len(suffix)]
                break
        if stem.startswith('TEMPLATE_'):
            stem = stem[len('TEMPLATE_'):]
        groups.setdefault(stem, []).append(file)
    return groups


def clean_target(name):
    """
    Args:
        name (str): Raw target name from the command line.

    Returns:
        str: Upper case ASCII name.

    Raises:
        ValueError: the name has characters that cannot be an identifier.
    """
    name = name.strip().upper().replace(' ', '_')
    if name.startswith('TEMPLATE_'):
        name = name[len('TEMPLATE_'):]
    bad = {c for c in name if c not in ASCII_OK}
    if bad or not name:
        raise ValueError(f'"{name}" 里有不能做标识符的字符: {"".join(sorted(bad))}')
    return name


def pairs_of(old, new):
    """
    Args:
        old (str): Current base name.
        new (str): Target base name.

    Returns:
        list[tuple[str, str]]: [(old file name, new file name), ...]
    """
    out = []
    for prefix in PREFIXES:
        for suffix in SUFFIXES:
            out.append((f'{prefix}{old}{suffix}.png', f'{prefix}{new}{suffix}.png'))
    return out


def rename(folder, mapping, dry_run=False):
    """
    Args:
        folder (str):
        mapping (dict[str, str]): old base name -> new base name.
        dry_run (bool):

    Returns:
        tuple[int, list[str], dict[str, str]]: Renamed count, errors, old file -> new file.
    """
    errors = []
    renamed = 0
    file_map = {}

    for old, new in mapping.items():
        old_png = pairs_of(old, new)
        found = [(src, dst) for src, dst in old_png if os.path.exists(os.path.join(folder, src))]
        if not found:
            errors.append(f'找不到 "{old}" 对应的 png')
            continue
        for src, dst in found:
            src_path = os.path.join(folder, src)
            dst_path = os.path.join(folder, dst)
            if os.path.exists(dst_path) and src != dst:
                errors.append(f'{dst} 已存在，跳过 {src}（先手动处理重名）')
                continue
            file_map[src] = dst
            if src == dst:
                continue
            print(f'  {src}  ->  {dst}')
            if not dry_run:
                os.rename(src_path, dst_path)
            renamed += 1

    return renamed, errors, file_map


def update_manifest(folder, file_map, dry_run=False):
    """
    Keep manifest.json in sync so the handoff document never lies.

    Args:
        folder (str):
        file_map (dict[str, str]): old file name -> new file name.
        dry_run (bool):

    Returns:
        int: Updated box count.
    """
    path = os.path.join(folder, 'manifest.json')
    if not os.path.isfile(path):
        return 0
    with open(path, 'r', encoding='utf-8') as f:
        manifest = json.load(f)

    updated = 0
    for shot in manifest.get('shots', []):
        for box in shot.get('boxes', []):
            new_file = file_map.get(box.get('file'))
            if not new_file or new_file == box.get('file'):
                continue
            box['file'] = new_file
            base = os.path.splitext(new_file)[0]
            for suffix in SUFFIXES[1:]:
                if base.endswith(suffix):
                    base = base[:-len(suffix)]
                    break
            if base.startswith('TEMPLATE_'):
                base = base[len('TEMPLATE_'):]
            box['name'] = base
            updated += 1

    if updated and not dry_run:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
    return updated


def non_ascii(folder):
    """
    Args:
        folder (str):

    Returns:
        list[str]: Files whose name is not plain ASCII.
    """
    if not os.path.isdir(folder):
        return []
    return [f for f in sorted(os.listdir(folder)) if f.lower().endswith('.png') and not f.isascii()]


def main():
    parser = argparse.ArgumentParser(description='Rename assets to ALAS style names')
    parser.add_argument('--module', default='hazeworld', help='module package name')
    parser.add_argument('--namespace', default=None, help='asset namespace, default = module')
    parser.add_argument('--map', default=None, help='"中文名=NAME,中文名2=NAME2"')
    parser.add_argument('--map-file', default=None, help='json file {"中文名": "NAME"}')
    parser.add_argument('--list', action='store_true', help='list current assets and exit')
    parser.add_argument('--dry-run', action='store_true', help='print actions, change nothing')
    args = parser.parse_args()

    namespace = args.namespace or args.module
    if namespace not in server.VALID_SERVER:
        print(f'[warn] "{namespace}" 不在 VALID_SERVER={server.VALID_SERVER}，'
              f'素材不会被 button_extract 读取')
    folder = asset_folder(namespace, args.module)

    groups = scan(folder)
    if args.list or not (args.map or args.map_file):
        if not groups:
            print(f'{folder} 里没有 png')
            return 1
        print(f'{folder}')
        width = max(len(k) for k in groups)
        for name, files in sorted(groups.items()):
            mark = '' if name.isascii() else '  <- 待改名'
            print(f'  {name:<{width}}  {len(files)} 个文件{mark}')
        print()
        print(f'共 {len(groups)} 个素材，{sum(len(v) for v in groups.values())} 个文件')
        return 0

    mapping = {}
    if args.map_file:
        with open(args.map_file, 'r', encoding='utf-8') as f:
            mapping.update(json.load(f))
    if args.map:
        for item in args.map.replace('\n', ',').split(','):
            if not item.strip():
                continue
            old, _, new = item.partition('=')
            mapping[old.strip()] = new.strip()

    cleaned = {}
    errors = []
    for old, new in mapping.items():
        try:
            cleaned[old] = clean_target(new)
        except ValueError as e:
            errors.append(str(e))

    if errors:
        for e in errors:
            print(f'[error] {e}')
        return 1

    print(f'{folder}{" (dry run)" if args.dry_run else ""}')
    renamed, rename_errors, file_map = rename(folder, cleaned, dry_run=args.dry_run)
    updated = update_manifest(folder, file_map, dry_run=args.dry_run)

    for e in rename_errors:
        print(f'[error] {e}')
    print(f'重命名 {renamed} 个文件，manifest 更新 {updated} 条')

    left = non_ascii(folder)
    if left:
        print()
        print(f'还有 {len(left)} 个文件名不是 ASCII，必须先改完才能跑 button_extract：')
        for f in left:
            print(f'  {f}')
        return 1

    print('全部是 ASCII，可以跑 dev_tools.button_extract 了')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
