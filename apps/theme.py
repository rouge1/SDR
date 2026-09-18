"""The one place the two front ends get their colours and type from.

The desktop launcher and the browser page are meant to look like one
program. They were drawn twice, which is how two front ends drift apart:
the first edit to either one and they stop matching, for no reason anybody
can see. So the palette, the type scale and the faces live here, and both
read them - ``apply_launcher_theme``, ``apply_dark_theme`` and
``apply_flowgraph_theme`` in ``apps/utils.py`` through :func:`launcher_qss`,
:func:`dialog_qss` and :func:`flowgraph_qss`, and ``web/server.py`` through
:func:`css`, which it serves as ``/theme.css``.

**This module imports nothing but the standard library at module level.**
The web server imports it, and the server deliberately pulls in no GNU
Radio, no Qt and no SoapySDR; :func:`load_fonts` is the one function that
needs Qt and it imports inside itself.

Qt Style Sheets are not CSS, and four of the things the page does have no
QSS equivalent at all - custom properties, ``object-fit: cover`` with
``filter: saturate()``, ``letter-spacing``, and the ``::after`` rule that
runs a hairline off the end of a bank name. Those are done in Python, in
``RFbenchToolkit.py``; everything that *is* expressible lives here.
"""

import os

#: Where ``fonts/`` sits, relative to this file rather than to the working
#: directory - an app can be started from anywhere.
FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'fonts')

#: Colours, faces and sizes. Sizes are in pixels here because that is what
#: Qt takes; :func:`css` divides by 16 to give the page the rem it had.
TOKENS = {
    'ground': '#10151a',      # the page behind everything
    'panel': '#1a2228',       # a tile, a card, a dialog
    'panel_2': '#212b32',     # a tile under the pointer, a plain button
    'well': '#0c1013',        # anything typed into
    'rule': '#2e3a43',        # a border that should be seen
    'rule_soft': '#222c33',   # one that should barely be
    'ink': '#e6ecef',         # body text
    'ink_2': '#93a3ad',       # labels, captions
    'ink_3': '#5d6d78',       # the quietest thing still meant to be read
    'live': '#ff9b21',        # on air
    'warn': '#e8b04b',        # a banner that wants reading
    'good': '#6fcf97',        # a receiver that has locked
    'bad': '#f0716a',         # one that has lost it
    'trace': '#cfe0e8',       # a plotted signal, on the well
    'f_num': 'Barlow Semi Condensed',
    'f_ui': 'Barlow',
    's_xs': 12, 's_sm': 13, 's_md': 15, 's_lg': 18, 's_xl': 24,
}

#: What to fall back to before the vendored faces are loaded, or if they
#: cannot be. Both front ends name the same stack.
FALLBACK = '"Helvetica Neue", Arial, sans-serif'


#: Registered families, once. ``addApplicationFont`` on the same file
#: twice hands back a second handle and registers the family again, which
#: is wasteful rather than wrong - but both themes call this, and every
#: dialog calls one of them.
_loaded = None


def load_fonts(directory=None, force=False):
    """Register the vendored faces with Qt, and say which arrived.

    No system install on any machine: ``fonts/`` travels with the repo,
    which is what makes Linux and Windows render the same. Returns the
    families actually registered, so a caller can notice rather than
    silently render in something else.
    """
    global _loaded
    if _loaded is not None and not force and directory is None:
        return _loaded
    from PyQt5.QtGui import QFontDatabase  # here, not at module level
    directory = directory or FONT_DIR
    families = set()
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        names = []
    for name in names:
        if not name.lower().endswith(('.ttf', '.otf')):
            continue
        handle = QFontDatabase.addApplicationFont(os.path.join(directory, name))
        if handle >= 0:
            families.update(QFontDatabase.applicationFontFamilies(handle))
    if directory == FONT_DIR:
        _loaded = families
    return families


# --- The launcher window ----------------------------------------------------

_LAUNCHER_QSS = """
QMainWindow, QWidget { background: %(ground)s; color: %(ink)s;
    font-family: "%(f_ui)s", %(fallback)s; font-size: %(s_md)spx; }
QToolTip { background: %(panel_2)s; color: %(ink)s;
    border: 1px solid %(rule)s; padding: 5px 7px; }

/* The header rail. A child widget paints its own background over the
   border-bottom - the wordmark did, and so would the centred column its
   contents sit in - so everything inside the rail is transparent and the
   rule shows through across the full width. */
#rail { background: %(ground)s; border-bottom: 1px solid %(rule)s; }
#rail QWidget { background: transparent; }
#mark { font-family: "%(f_num)s", %(fallback)s; font-weight: 600;
    font-size: %(s_lg)spx; color: %(ink)s; }
#radio-tag { font-size: %(s_xs)spx; color: %(ink_2)s; padding: 4px 9px;
    border: 1px solid %(rule)s; border-radius: 2px; background: transparent; }
#gear { border: none; border-radius: 2px; background: transparent;
    padding: 0; min-width: 0; }
#gear:hover { background: %(panel)s; }

/* A bank heading, and the hairline that is its ::after. */
#bank-name { color: %(ink_2)s; font-size: %(s_sm)spx; background: transparent; }
#hairline { background: %(rule_soft)s; border: none; }

/* A tile. Dimming is painted rather than set here: QSS has no opacity
   property, and a QGraphicsOpacityEffect on the tile would have to nest
   inside the one the caption already carries. */
#tile { background: %(panel)s; border: 1px solid %(rule)s;
    border-radius: 2px; padding: 0; text-align: left; }
#tile:hover { background: %(panel_2)s; border-color: %(ink_3)s; }
#tile:pressed { background: %(well)s; }
#tile:disabled { background: %(panel)s; border-color: %(rule)s; }
#tile QLabel { background: transparent; }
#dir { font-family: "%(f_num)s", %(fallback)s; font-weight: 600;
    font-size: %(s_xs)spx; color: %(ink_3)s; }
#name { font-size: %(s_sm)spx; color: %(ink)s; }
/* A tile the radio cannot run. The picture is dimmed by the painter -
   see FlipTile._draw - and the caption here, because the two labels
   already carry an opacity effect each for the flip and effects do not
   nest predictably. */
#dir:disabled { color: %(rule)s; }
#name:disabled { color: %(ink_3)s; }
#flip { background: %(panel)s; border: 1px solid %(ink_3)s;
    border-radius: 2px; color: %(ink)s; font-size: %(s_sm)spx;
    padding: 0; min-width: 0; }
#flip:hover { background: %(well)s; }

QScrollArea { background: %(ground)s; border: none; }
QScrollBar:vertical { background: %(ground)s; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: %(rule)s; border-radius: 2px;
    min-height: 30px; }
QScrollBar::handle:vertical:hover { background: %(ink_3)s; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: %(ground)s; }

QMessageBox { background: %(panel)s; }
QMessageBox QLabel { color: %(ink)s; background: transparent; }
QMessageBox QPushButton { background: %(panel_2)s; color: %(ink)s;
    border: 1px solid %(rule)s; border-radius: 2px;
    padding: 7px 14px; min-width: 80px; }
QMessageBox QPushButton:hover { border-color: %(ink_3)s; }
"""


def launcher_qss():
    """The launcher window's stylesheet."""
    return _LAUNCHER_QSS % dict(TOKENS, fallback=FALLBACK)


# --- The config dialogs -----------------------------------------------------

# The page's .sheet: a panel card, a well for anything typed into, one
# primary button. tidy_dialog still does the layout - this is paint only.
_DIALOG_BASE_QSS = """
QDialog, QWidget { background: %(panel)s; color: %(ink)s;
    font-family: "%(f_ui)s", %(fallback)s; font-size: %(s_md)spx; }
QToolTip { background: %(panel_2)s; color: %(ink)s;
    border: 1px solid %(rule)s; padding: 5px 7px; }
QLabel { background: transparent; color: %(ink_2)s; font-size: %(s_sm)spx; }
QGroupBox { border: 1px solid %(rule_soft)s; border-radius: 2px;
    margin-top: 10px; padding-top: 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 9px; padding: 0 4px;
    color: %(ink_2)s; font-size: %(s_sm)spx; }
"""

# Buttons, anything typed into, sliders and ticks - the same in a config
# dialog and in the flowgraph window it opens, so the two read as one app.
_CONTROLS_QSS = """
QPushButton { background: %(panel_2)s; color: %(ink)s;
    border: 1px solid %(rule)s; border-radius: 2px;
    padding: 8px 16px; min-width: 80px; font-size: %(s_sm)spx; }
QPushButton:hover { border-color: %(ink_3)s; }
QPushButton:pressed { background: %(well)s; }
/* OK is the page's .btn.primary. */
QPushButton:default { background: %(ink)s; color: %(ground)s;
    border-color: %(ink)s; }
QPushButton:default:hover { background: #ffffff; }
QPushButton:disabled { color: %(ink_3)s; border-color: %(rule_soft)s;
    background: %(panel)s; }

QLineEdit, QAbstractSpinBox, QComboBox { background: %(well)s; color: %(ink)s;
    border: 1px solid %(rule)s; border-radius: 2px; padding: 7px 9px;
    selection-background-color: %(rule)s; selection-color: %(ink)s; }
QLineEdit:hover, QAbstractSpinBox:hover, QComboBox:hover,
QLineEdit:focus, QAbstractSpinBox:focus, QComboBox:focus {
    border-color: %(ink_3)s; }
QLineEdit:disabled, QAbstractSpinBox:disabled, QComboBox:disabled {
    color: %(ink_3)s; border-color: %(rule_soft)s; }
QComboBox QAbstractItemView { background: %(well)s; color: %(ink)s;
    border: 1px solid %(rule)s; selection-background-color: %(panel_2)s;
    selection-color: %(ink)s; }

/* A spin box or combo that a stylesheet touches at all stops drawing its
   own arrows - they come out as empty rectangles - and Qt's CSS subset
   will not draw a triangle out of borders either. So they are images. */
QComboBox::drop-down { subcontrol-origin: padding;
    subcontrol-position: center right; width: 22px; border: none;
    background: transparent; }
QComboBox::down-arrow { image: url(%(down)s); width: 9px; height: 5px; }
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {
    subcontrol-origin: border; background: %(panel_2)s; border: none;
    width: 17px; }
QAbstractSpinBox::up-button { subcontrol-position: top right;
    margin: 1px 1px 0 0; border-top-right-radius: 1px; }
QAbstractSpinBox::down-button { subcontrol-position: bottom right;
    margin: 0 1px 1px 0; border-bottom-right-radius: 1px; }
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {
    background: %(rule)s; }
QAbstractSpinBox::up-arrow { image: url(%(up)s); width: 9px; height: 5px; }
QAbstractSpinBox::down-arrow { image: url(%(down)s); width: 9px; height: 5px; }

QSlider { background: transparent; }
QSlider::groove:horizontal { background: %(well)s;
    border: 1px solid %(rule)s; height: 4px; border-radius: 2px; }
QSlider::sub-page:horizontal { background: %(ink_3)s; border-radius: 2px; }
QSlider::handle:horizontal { background: %(ink)s; border: none; width: 12px;
    margin: -5px 0; border-radius: 2px; }
QSlider::handle:horizontal:hover { background: #ffffff; }
QSlider::handle:horizontal:disabled { background: %(ink_3)s; }

QCheckBox { background: transparent; color: %(ink_2)s; spacing: 8px; }
QCheckBox::indicator { width: 14px; height: 14px; border-radius: 2px;
    border: 1px solid %(rule)s; background: %(well)s; }
QCheckBox::indicator:hover { border-color: %(ink_3)s; }
QCheckBox::indicator:checked { background: %(ink)s; border-color: %(ink)s;
    image: url(%(tick)s); }
QCheckBox:disabled { color: %(ink_3)s; }
"""

_DIALOG_QSS = _DIALOG_BASE_QSS + _CONTROLS_QSS


def dialog_qss(up, down, tick):
    """A config dialog's stylesheet.

    The three paths are the arrow and tick images, absolute, because a
    stylesheet resolves ``url()`` against the process's working directory
    and an app can be started from anywhere.
    """
    return _DIALOG_QSS % dict(TOKENS, fallback=FALLBACK,
                              up=up, down=down, tick=tick)


# --- The flowgraph windows --------------------------------------------------

# The page's panel view (web/prototype/index.html): the window on the
# ground, each group of controls a panel card, each plot a well with a
# rule round it, traces in the trace colour.
#
# **No font-family or font-size on QWidget, QLabel or the plots' own
# frames**, unlike the dialog. A stylesheet font beats setFont(), and the
# receivers set fonts that mean something - the RadioText and the program
# list in monospace, so a gap or a stray character shows where it is, and
# the lock status large. The face comes from the application font instead
# (see apply_flowgraph_theme), which a widget's own setFont() still
# overrides. Rules below that do set a face are for widgets no app sets
# one on.
_FLOWGRAPH_BASE_QSS = """
QWidget { background: %(ground)s; color: %(ink)s; }
QToolTip { background: %(panel_2)s; color: %(ink)s;
    border: 1px solid %(rule)s; padding: 5px 7px; }
QLabel, QRadioButton, QCheckBox, QSlider, QToolBar { background: transparent; }

/* GRC puts every window inside a scroll area. */
QScrollArea { background: %(ground)s; border: none; }
QScrollBar:vertical { background: %(ground)s; width: 10px; margin: 0; }
QScrollBar:horizontal { background: %(ground)s; height: 10px; margin: 0; }
QScrollBar::handle { background: %(rule)s; border-radius: 2px; }
QScrollBar::handle:vertical { min-height: 30px; }
QScrollBar::handle:horizontal { min-width: 30px; }
QScrollBar::handle:hover { background: %(ink_3)s; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: %(ground)s; }

/* A group of controls, or a receiver's readout, is a panel card. What it
   holds sits on the card rather than painting the ground over it. */
QGroupBox { background: %(panel)s; border: 1px solid %(rule)s;
    border-radius: 2px; margin-top: 22px; padding: 6px 8px; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left;
    left: 1px; top: 0; padding: 0 0 5px 0; background: transparent;
    color: %(ink_2)s; font-family: "%(f_ui)s", %(fallback)s;
    font-size: %(s_sm)spx; }
QGroupBox > QWidget { background: transparent; }

/* A control's name, from GNU Radio's RangeWidget and GRC's labelled tool
   bars, is quieter than the value beside it. */
RangeWidget QLabel { color: %(ink_2)s; }
QToolBar { border: none; spacing: 4px; padding: 0; }
QToolBar QLabel { color: %(ink_2)s; }
QToolBar::handle { width: 0; height: 0; image: none; }

/* GRC's choosers are radio buttons in a group box. */
QRadioButton { color: %(ink_2)s; spacing: 8px; }
QRadioButton:checked { color: %(ink)s; }
QRadioButton:disabled { color: %(ink_3)s; }
QRadioButton::indicator { width: 14px; height: 14px; border-radius: 8px;
    border: 1px solid %(rule)s; background: %(well)s; }
QRadioButton::indicator:hover { border-color: %(ink_3)s; }
QRadioButton::indicator:checked { border-color: %(ink)s;
    background: qradialgradient(cx: 0.5, cy: 0.5, radius: 0.5,
        fx: 0.5, fy: 0.5, stop: 0 %(ink)s, stop: 0.42 %(ink)s,
        stop: 0.52 %(well)s, stop: 1 %(well)s); }

/* A plot's right-click menus, and the little dialogs they open. */
QMenu { background: %(panel_2)s; color: %(ink)s; border: 1px solid %(rule)s;
    padding: 4px 0; }
QMenu::item { padding: 5px 18px; background: transparent; }
QMenu::item:selected { background: %(rule)s; }
QMenu::separator { height: 1px; background: %(rule_soft)s; margin: 4px 0; }
QDialog { background: %(panel)s; }

/* A plot is a well with a rule round it, as on the page. */
DisplayPlot { background: %(well)s; border: 1px solid %(rule)s;
    border-radius: 2px;
    qproperty-palette_color: %(well)s;
    qproperty-zoomer_color: %(ink)s;
    qproperty-axes_label_font_size: 10;
    qproperty-line_color1: %(trace)s;
    qproperty-line_color2: %(ink_3)s;
    qproperty-line_color3: %(live)s;
    qproperty-line_color4: %(good)s;
    qproperty-line_color5: %(warn)s;
    qproperty-line_color6: %(bad)s;
    qproperty-line_color7: %(ink_2)s;
    qproperty-line_color8: %(rule)s;
    qproperty-line_color9: %(ink)s; }
TimeDomainDisplayPlot { qproperty-tag_text_color: %(ink)s;
    qproperty-tag_background_color: %(panel_2)s; }
/* Not marker_peak_amplitude_color: setting it at all segfaults GNU Radio
   3.10.12's frequency plot, with no Python frame to say why. */
FrequencyDisplayPlot { qproperty-max_fft_color: %(ink_2)s;
    qproperty-min_fft_color: %(ink_3)s;
    qproperty-marker_lower_intensity_color: %(ink_3)s;
    qproperty-marker_upper_intensity_color: %(warn)s;
    qproperty-marker_noise_floor_amplitude_color: %(ink_3)s;
    qproperty-marker_CF_color: %(rule)s; }
QwtPlotCanvas { background: %(well)s; border: 1px solid %(rule)s;
    border-radius: 0; }
DisplayPlot QWidget { background: transparent; }
DisplayPlot QwtPlotCanvas { background: %(well)s; }
QwtTextLabel#QwtPlotTitle { color: %(ink)s; padding: 6px 0 2px 0;
    font-family: "%(f_ui)s", %(fallback)s; font-size: %(s_sm)spx;
    font-weight: 600; }
QwtScaleWidget { color: %(ink_3)s; font-family: "%(f_ui)s", %(fallback)s;
    font-size: %(s_xs)spx; }
QwtLegendLabel { color: %(ink_2)s; font-size: %(s_sm)spx; }
"""

_FLOWGRAPH_QSS = _FLOWGRAPH_BASE_QSS + _CONTROLS_QSS


def flowgraph_qss(up, down, tick):
    """A running flowgraph window's stylesheet. The paths are as for
    :func:`dialog_qss`."""
    return _FLOWGRAPH_QSS % dict(TOKENS, fallback=FALLBACK,
                                 up=up, down=down, tick=tick)


# --- The browser page -------------------------------------------------------

#: The six faces, as (token naming the family, file, CSS weight). Qt reads
#: the same directory through :func:`load_fonts` and picks its own weights.
FACES = [
    ('f_ui', 'Barlow-Regular.ttf', 400),
    ('f_ui', 'Barlow-Medium.ttf', 500),
    ('f_ui', 'Barlow-SemiBold.ttf', 600),
    ('f_num', 'BarlowSemiCondensed-Medium.ttf', 500),
    ('f_num', 'BarlowSemiCondensed-SemiBold.ttf', 600),
    ('f_num', 'BarlowSemiCondensed-Bold.ttf', 700),
]


def css():
    """The page's ``@font-face`` rules and ``:root``, served as /theme.css.

    Sizes go out in rem, as the page has always had them, so a reader who
    scales their browser text still gets it; Qt has no such idea and takes
    the pixels directly.
    """
    lines = ['/* Generated from apps/theme.py - edit the tokens there, not',
             '   here, so the launcher window and this page cannot drift. */']
    for family, filename, weight in FACES:
        lines.append(
            '@font-face{font-family:"%s";font-style:normal;font-weight:%d;'
            'font-display:swap;src:url("/fonts/%s") format("truetype")}'
            % (TOKENS[family], weight, filename))
    lines.append(':root{')
    for name in ('ground', 'panel', 'panel_2', 'well', 'rule', 'rule_soft',
                 'ink', 'ink_2', 'ink_3', 'live', 'warn', 'good', 'bad',
                 'trace'):
        lines.append('  --%s:%s;' % (name.replace('_', '-'), TOKENS[name]))
    lines.append('  --f-num:"%s",%s;' % (TOKENS['f_num'], FALLBACK))
    lines.append('  --f-ui:"%s",%s;' % (TOKENS['f_ui'], FALLBACK))
    for name in ('s_xs', 's_sm', 's_md', 's_lg', 's_xl'):
        lines.append('  --%s:%grem;'
                     % (name.replace('_', '-'), TOKENS[name] / 16))
    lines.append('}')
    return '\n'.join(lines) + '\n'


#: The settings glyph: three faders, which says "settings" without a
#: photograph of a cog, and which the browser front end already draws. It
#: is inline SVG rather than a file because QtSvg has no ``currentColor``,
#: so the ink has to be put in before it is rendered.
_GEAR = """<svg xmlns="http://www.w3.org/2000/svg" width="17" height="17"
 viewBox="0 0 17 17" fill="none">
<path d="M2 4h5M10 4h5M2 8.5h9M14 8.5h1M2 13h3M8 13h7"
 stroke="%(ink)s" stroke-width="1.4" stroke-linecap="round"/>
<circle cx="8.5" cy="4" r="1.7" stroke="%(ink)s" stroke-width="1.4"/>
<circle cx="12.5" cy="8.5" r="1.7" stroke="%(ink)s" stroke-width="1.4"/>
<circle cx="6.5" cy="13" r="1.7" stroke="%(ink)s" stroke-width="1.4"/>
</svg>"""


def gear_svg(colour=None):
    return _GEAR % {'ink': colour or TOKENS['ink_2']}
