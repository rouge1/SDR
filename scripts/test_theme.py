#!/usr/bin/env python3
"""Check the two front ends really are painted from the same tokens.

``apps/theme.py`` is the single source of the palette, the type scale and
the faces: the launcher window and the config dialogs take it as Qt style
sheets, and the browser page takes it as the ``/theme.css`` the server
generates. That only stops them drifting if every name one side uses is a
name the other side defines, which is what this checks. No radio, no
display, no GNU Radio.

    python scripts/test_theme.py
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from apps import theme  # noqa: E402

FAILURES = []


def check(condition, message):
    print(('  ok   ' if condition else '  FAIL ') + message)
    if not condition:
        FAILURES.append(message)


def main():
    print('tokens -> the browser page')
    css = theme.css()
    defined = set(re.findall(r'^\s*(--[a-z0-9-]+)\s*:', css, re.M))
    page = open(os.path.join(ROOT, 'web', 'index.html')).read()
    used = set(re.findall(r'var\((--[a-z0-9-]+)\)', page))
    missing = sorted(used - defined)
    check(not missing, f"every var() the page uses is defined ({len(used)} of "
                       f"them){'' if not missing else ': missing ' + ', '.join(missing)}")
    check('fonts.googleapis.com' not in page and 'http://' not in page
          and 'https://' not in page,
          'the page asks nothing of the network')
    check('/theme.css' in page, 'the page links the generated stylesheet')

    print('\ntokens -> Qt')
    for name, sheet in (('launcher', theme.launcher_qss()),
                        ('dialog', theme.dialog_qss('u.png', 'd.png', 'c.png'))):
        leftover = re.findall(r'%\([a-z_0-9]+\)s', sheet)
        check(not leftover,
              f"the {name} stylesheet has no unsubstituted token"
              f"{'' if not leftover else ': ' + ', '.join(sorted(set(leftover)))}")
        check(theme.TOKENS['ground'] in sheet or theme.TOKENS['panel'] in sheet,
              f"the {name} stylesheet carries the palette")

    print('\nthe faces')
    for _family, filename, _weight in theme.FACES:
        path = os.path.join(theme.FONT_DIR, filename)
        check(os.path.exists(path), f"{filename} is in fonts/")
    check(os.path.exists(os.path.join(theme.FONT_DIR, 'OFL.txt')),
          'the licence ships beside them, as the OFL requires')

    print('\nthe tile tables')
    # Both front ends read these out of the launcher's source; the server
    # parses them with ast, so they have to stay plain literals.
    import ast
    source = open(os.path.join(ROOT, 'gnuradio_launcher.py')).read()
    found = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if getattr(target, 'id', None) in ('APP_TILES', 'BANK_NAMES'):
                    found[target.id] = ast.literal_eval(node.value)
    check(set(found) == {'APP_TILES', 'BANK_NAMES'},
          'APP_TILES and BANK_NAMES are literals ast can read')
    if len(found) == 2:
        rows = {row for row, _col, _faces in found['APP_TILES']}
        unnamed = sorted(rows - set(found['BANK_NAMES']))
        check(not unnamed,
              f"every row of tiles has a heading"
              f"{'' if not unnamed else ': ' + str(unnamed) + ' has none'}")

    print(f"\n{len(FAILURES)} failed" if FAILURES else '\nall checks passed')
    return 1 if FAILURES else 0


if __name__ == '__main__':
    sys.exit(main())
