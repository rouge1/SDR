#!/usr/bin/env python3
"""Check the two front ends really are painted from the same tokens.

``apps/theme.py`` is the single source of the palette, the type scale and
the faces: the launcher window and the config dialogs take it as Qt style
sheets, and the browser page takes it as the ``/theme.css`` the server
generates. That only stops them drifting if every name one side uses is a
name the other side defines, which is what this checks. No radio, no
display, no GNU Radio.

It also holds every theme to the contrast its colours are there for,
since a colour that reads on Slate can vanish on Reading Room's paper, and
nothing else would say so until somebody looked.

    python scripts/test_theme.py
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from apps import theme  # noqa: E402

FAILURES = []

#: (colour, what it sits on, the least contrast it may have, why). Slate's
#: own figures set these; every theme has to meet them.
CONTRAST = [
    ('ink', ('ground', 'panel', 'panel_2', 'well'), 7.0, 'body text'),
    ('ink_2', ('ground', 'panel', 'panel_2', 'well'), 4.5, 'labels'),
    ('heading', ('ground',), 4.5, "a bank's name"),
    ('tag', ('panel',), 3.0, "a tile's TRANSMIT line"),
    ('ink_3', ('ground', 'panel'), 3.0,
     'the quietest thing still meant to be read'),
    ('live', ('ground', 'panel'), 4.5, 'the ON AIR heading'),
    ('warn', ('ground', 'panel'), 4.5, "a receiver's lock line"),
    ('good', ('ground', 'panel'), 4.5, "a receiver's lock line"),
    ('bad', ('ground', 'panel'), 4.5, "a receiver's lock line"),
    ('trace', ('well',), 3.0, 'a plotted signal'),
    ('ground', ('ink', 'ink_0'), 4.5, 'the OK button, and under the pointer'),
]


def lum(colour):
    """The WCAG relative luminance of a #rrggbb colour."""
    out = []
    for i in (1, 3, 5):
        v = int(colour[i:i + 2], 16) / 255
        out.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def contrast(a, b):
    """The WCAG contrast ratio of two #rrggbb colours."""
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


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
    for name in ('pulse', 'charge'):
        check(('@keyframes %s{' % name) in css and ('animation:%s ' % name) in page,
              f"the page's {name} animation is one /theme.css generates")
    # web/server.py puts the saved theme on exactly this tag as it serves
    # the page; changed, the page would open in Slate every time.
    check(page.count('<html lang="en">') == 1,
          'the page\'s <html> tag is the one the server puts the theme on')
    for key in theme.THEMES:
        if key != theme.DEFAULT:
            check(':root[data-theme="%s"]{' % key in css,
                  f"/theme.css has a block for {theme.NAMES[key]}")

    print('\nthe themes')
    check(theme.DEFAULT == next(iter(theme.THEMES)),
          'the default is the first the disc shows')
    check(set(theme.NAMES) == set(theme.THEMES), 'every theme has a name')
    for key, palette in theme.THEMES.items():
        extra = (set(palette) - set(theme.PALETTE) - set(theme.EXTRAS)
                 - {'scheme', 'type'})
        missing = set(theme.PALETTE) - set(palette)
        check(not extra and not missing and palette.get('scheme') in
              ('dark', 'light'),
              f"{theme.NAMES[key]} defines every colour and nothing else"
              f"{'' if not missing else ': missing ' + ', '.join(sorted(missing))}"
              f"{'' if not extra else ': unknown ' + ', '.join(sorted(extra))}")
        if missing:
            continue
        low = []
        back, text, _edge = theme.ok_hover(palette)
        if contrast(text, back) < 4.5:
            low.append(f"OK under the pointer {contrast(text, back):.2f}:1")
        for fg, grounds, least, _why in CONTRAST:
            for bg in grounds:
                ratio = contrast(palette[fg], palette[bg])
                if ratio < least:
                    low.append(f"{fg} on {bg} {ratio:.2f}:1 < {least}")
        check(not low, f"{theme.NAMES[key]}'s colours read where they are used"
                       f"{'' if not low else ': ' + '; '.join(low)}")
        faces = palette.get('type', {})
        if faces:
            shipped = {family for family, _f, _w in theme.FACES}
            check(set(faces) <= {'f_num', 'f_ui', 'qss_bold'} and
                  {faces.get('f_num', 'Barlow Semi Condensed'),
                   faces.get('f_ui', 'Barlow')} <= shipped,
                  f"{theme.NAMES[key]}'s faces are ones that ship in fonts/")

    print('\ntokens -> Qt')
    for key in theme.THEMES:
        theme.use(key)
        sheets = (theme.launcher_qss(),
                  theme.dialog_qss('u.png', 'd.png', 'c.png'),
                  theme.flowgraph_qss('u.png', 'd.png', 'c.png'))
        check(all(theme.TOKENS['ground'] in s for s in sheets),
              f"all three stylesheets are painted in {theme.NAMES[key]} "
              f"when it is in force")
    theme.use(theme.DEFAULT)
    for name, sheet in (('launcher', theme.launcher_qss()),
                        ('dialog', theme.dialog_qss('u.png', 'd.png', 'c.png')),
                        ('flowgraph',
                         theme.flowgraph_qss('u.png', 'd.png', 'c.png'))):
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
    for family in sorted({family for family, _f, _w in theme.FACES}):
        licence = theme.LICENCES.get(family)
        check(bool(licence) and
              os.path.exists(os.path.join(theme.FONT_DIR, licence)),
              f"{family}'s licence ships beside it, as the OFL requires")

    print('\nthe tile tables')
    # Both front ends read these out of the launcher's source; the server
    # parses them with ast, so they have to stay plain literals.
    import ast
    source = open(os.path.join(ROOT, 'RFbenchToolkit.py')).read()
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
