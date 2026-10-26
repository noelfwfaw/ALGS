"""
Guard against upstream code that silently breaks this fork.

Upstream ships traps that only fire once the repository is modified. The known
one lives in module/device/connection_attr.py: the proxy cleanup is gated on a
count of *locked* config options, and when the gate fails it does not skip the
cleanup, it prepends a backspace character to every value whose key ends with
"eri" (Serial). Since any fork trims argument.yaml and therefore has zero
locked options, the trap fires on every run and the failure surfaces as

    cannot resolve host '127.0.0.1' and port 16640

with mismatched quotes in the log, while the emulator works fine.

Run after merging from upstream:

    ./toolkit/python.exe -m dev_tools.check_fork_integrity

Pages:
    none
"""
import io
import os
import re
import sys
import tokenize

# Importable both as `-m dev_tools.check_fork_integrity` and as a plain script.
if __package__ in (None, ''):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module.config.config import AlasConfig

# Files whose fork specific patches must survive an upstream merge.
MARKERS = {
    'module/device/connection_attr.py': '[AlGS PATCH]',
}

# Patterns matched against executable code only, comments and strings removed.
FORBIDDEN_CODE = [
    (re.compile(r'chr\s*\(\s*8\s*\)'), 'chr(8) serial poisoning'),
    (re.compile(r'chr\s*\(\s*0x0?8\s*\)'), 'chr(8) serial poisoning'),
]

# A raw backspace byte in source is never legitimate.
FORBIDDEN_BYTES = [0x08]

SKIP_DIRS = {'.git', '__pycache__', 'toolkit', '.workbuddy', 'log', 'node_modules', 'screenshots'}

SKIP_TOKENS = {
    tokenize.COMMENT, tokenize.STRING, tokenize.NL, tokenize.NEWLINE,
    tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING,
}


def iter_py_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.endswith('.py'):
                yield os.path.join(dirpath, name)


def iter_code_lines(path):
    """
    Yield (lineno, code) with comments and string literals blanked out.

    Sanitizing first is what keeps this checker from flagging its own docstring.
    """
    with open(path, 'rb') as f:
        source = f.read()
    lines = {}
    try:
        for token in tokenize.tokenize(io.BytesIO(source).readline):
            if token.type in SKIP_TOKENS:
                continue
            lines.setdefault(token.start[0], []).append(token.string)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return
    for lineno in sorted(lines):
        yield lineno, ' '.join(lines[lineno])


def check_markers():
    failed = 0
    for path, marker in MARKERS.items():
        if not os.path.exists(path):
            print(f'FAIL  {path} is missing')
            failed += 1
            continue
        text = io.open(path, encoding='utf-8', errors='ignore').read()
        if marker in text:
            print(f'OK    {path} keeps its {marker} patch')
        else:
            print(f'FAIL  {path} lost its {marker} patch, an upstream merge probably reverted it')
            failed += 1
    return failed


def check_forbidden():
    failed = 0
    for path in iter_py_files('.'):
        raw = io.open(path, 'rb').read()
        for byte in FORBIDDEN_BYTES:
            if byte in raw:
                print(f'FAIL  {path} contains the raw control byte {byte:#04x}')
                failed += 1
        for lineno, code in iter_code_lines(path):
            for pattern, label in FORBIDDEN_CODE:
                if pattern.search(code):
                    print(f'FAIL  {path}:{lineno} contains {label}')
                    failed += 1
    if failed == 0:
        print('OK    no forbidden pattern in any python file')
    return failed


def check_config_values():
    """Config values must be plain text, a control byte means corruption."""
    try:
        config = AlasConfig('alas', task=None)
    except Exception as e:
        print(f'SKIP  cannot load config: {e}')
        return 0

    failed = 0
    for key, value in config.__dict__.items():
        if not isinstance(value, str):
            continue
        if any(ord(c) < 32 for c in value):
            print(f'FAIL  AlasConfig.{key} = {value!r} contains a control character')
            failed += 1
    if failed == 0:
        print('OK    all string config values are clean')
    return failed


def main():
    failed = check_markers() + check_forbidden() + check_config_values()
    print(f'\n{"PASS" if failed == 0 else "FAILED"}  {failed} problem(s)')
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
