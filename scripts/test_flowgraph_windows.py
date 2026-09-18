#!/usr/bin/env python3
"""Open every flowgraph window with no radio, and check it wears the theme.

    python scripts/test_flowgraph_windows.py                 # every app
    python scripts/test_flowgraph_windows.py amSineGenerator
    python scripts/test_flowgraph_windows.py --save /tmp/shots

The config dialogs have ``scripts/test_dialog_layout.py``; this is the same
for the windows that come up once OK is pressed. Each app is built the way
``launch_application`` builds it - its own ``ConfigDialog`` for the values
it would open with, then its real ``main()`` - with the radio swapped for a
stand-in, so the whole signal chain runs and the plots have something to
draw. A transmitter's radio becomes a throttle into nothing, at the rate
the app asked for; a receiver's becomes noise with a tone in it; a sound
card becomes nothing at all. Nothing opens a device, so it runs beside a
launcher, and with any radio plugged in.

What it checks, on the window as rendered:

- **It carries the flowgraph theme** (``apply_flowgraph_theme``), and
  almost nothing on it is still the light grey and white it used to be.
- **Every plot's canvas is the well**, as the browser page draws its plots.
- **Every trace can be seen against it.** The apps set their traces in
  GNU Radio's colours for a white canvas, and black is the commonest - on
  the well it would be invisible. Each line in use needs 3:1 against the
  canvas, the WCAG figure for a graphic that has to be made out.
- **Every label can be read**: 4.5:1 against what is behind it, including
  the receivers' own status colours.

Each app runs in a process of its own, because ``main()`` installs signal
handlers and a flowgraph that goes wrong should take only itself down. None
of them is ever closed: an app's ``closeEvent`` writes its geometry into
the user's own ``QSettings``, and a test must not.
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Every app with a flowgraph window, in launcher order.
MODULES = [
    'askGenerator', 'fskGenerator', 'pskGenerator', 'amSineGenerator',
    'ppmookAudioXmitter', 'amAudioInternalGeneratorLive',
    'fmAudioRecordedGenerator', 'subcarrierRecordedAudio',
    'fmRdsTransmitter', 'rdsReceiver',
    'atscXmitter', 'atscReceiver', 'ntscAnalogVideoRecorded', 'ntscReceiver',
    'fmVideoXmitter', 'fmVideoReceiver',
]

#: How long each flowgraph runs before it is looked at, so the plots have
#: drawn a few frames.
RUN_SECONDS = 2.5

#: The size each window is looked at - the 1366x768 laptop, less its frame.
SIZE = (1340, 700)

#: WCAG 2.1: 3:1 for a graphic that has to be made out, 4.5:1 for text.
TRACE_CONTRAST = 3.0
TEXT_CONTRAST = 4.5

#: At most this share of a window may be near white. Text in the theme's
#: ink is near white, so it is not zero; an unthemed panel is far more.
BRIGHT_SHARE = 0.03


def contrast(a, b):
    """WCAG contrast ratio between two QColors."""
    def lum(c):
        out = []
        for v in (c.redF(), c.greenF(), c.blueF()):
            out.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
        return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def install_stand_ins():
    """Swap every radio and sound card for a block that opens nothing."""
    from gnuradio import analog, audio, blocks, gr, soapy
    import apps.utils as utils

    class _Quiet:
        """Any other setter the app calls on its radio does nothing.

        Only setters: the receivers ask ``getattr(source, 'adc_overflows')``
        to find out whether the radio is a BB60D, so a stand-in that
        answered everything would pass for one.
        """

        def __getattr__(self, attr):
            if attr.startswith('_'):
                raise AttributeError(attr)
            try:
                return gr.hier_block2.__getattr__(self, attr)
            except AttributeError:
                if attr.startswith('set_'):
                    return lambda *args, **kwargs: None
                raise

    class RadioSink(_Quiet, gr.hier_block2):
        def __init__(self, *args, **kwargs):
            gr.hier_block2.__init__(
                self, 'stand-in radio sink',
                gr.io_signature(1, 1, gr.sizeof_gr_complex),
                gr.io_signature(0, 0, 0))
            self._rate = 2e6
            self._throttle = blocks.throttle(gr.sizeof_gr_complex, self._rate)
            self._null = blocks.null_sink(gr.sizeof_gr_complex)
            self.connect(self, self._throttle, self._null)

        def set_sample_rate(self, channel, rate):
            self._rate = float(rate)
            self._throttle.set_sample_rate(self._rate)

        def get_sample_rate(self, channel=0):
            return self._rate

    class RadioSource(_Quiet, gr.hier_block2):
        def __init__(self, *args, **kwargs):
            gr.hier_block2.__init__(
                self, 'stand-in radio source',
                gr.io_signature(0, 0, 0),
                gr.io_signature(1, 1, gr.sizeof_gr_complex))
            self._rate = 2e6
            self._noise = analog.noise_source_c(analog.GR_GAUSSIAN, 0.01, 0)
            self._tone = analog.sig_source_c(self._rate, analog.GR_COS_WAVE,
                                             self._rate / 20, 0.1, 0)
            self._add = blocks.add_cc()
            self._throttle = blocks.throttle(gr.sizeof_gr_complex, self._rate)
            self.connect(self._noise, (self._add, 0))
            self.connect(self._tone, (self._add, 1))
            self.connect(self._add, self._throttle, self)

        def set_sample_rate(self, channel, rate):
            self._rate = float(rate)
            self._throttle.set_sample_rate(self._rate)
            self._tone.set_sampling_freq(self._rate)
            self._tone.set_frequency(self._rate / 20)

        def get_sample_rate(self, channel=0):
            return self._rate

    soapy.sink = RadioSink
    soapy.source = RadioSource
    audio.sink = lambda *args, **kwargs: blocks.null_sink(gr.sizeof_float)

    real = utils.read_settings

    def read_settings():
        settings = real()
        settings['radio_type'] = 'hackrf'
        return settings
    utils.read_settings = read_settings


def child(name, save):
    """One app, in this process. Prints result lines, then exits hard."""
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    os.chdir(ROOT)
    sys.path.insert(0, ROOT)
    import importlib.util
    import time
    from PyQt5 import Qt

    app = Qt.QApplication([])
    install_stand_ins()

    spec = importlib.util.spec_from_file_location(name, f'apps/{name}.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)

    dialog = module.ConfigDialog()
    values = dialog.get_values()
    dialog.deleteLater()
    values['radio_type'] = 'hackrf'

    tb = module.main(app=app, config_values=values)
    tb.resize(*SIZE)
    end = time.time() + RUN_SECONDS
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)

    problems = inspect(Qt, tb, name, save)
    try:
        tb.stop()
        tb.wait()
    except Exception:
        pass
    for problem in problems:
        print(f"PROBLEM {problem}", flush=True)
    print(f"RESULT {name} {len(problems)}", flush=True)
    sys.stdout.flush()
    os._exit(0)


def commonest(Qt, image, rect):
    """The colour covering most of this part of the image - its background,
    for a label or a canvas, since text and traces are thin."""
    counts = {}
    for y in range(rect.top(), rect.bottom() + 1, 2):
        for x in range(rect.left(), rect.right() + 1, 2):
            if 0 <= x < image.width() and 0 <= y < image.height():
                rgb = image.pixel(x, y) & 0xffffff
                counts[rgb] = counts.get(rgb, 0) + 1
    if not counts:
        return None
    return Qt.QColor(max(counts, key=counts.get))


def close_to(a, b, tolerance):
    return (abs(a.red() - b.red()) <= tolerance
            and abs(a.green() - b.green()) <= tolerance
            and abs(a.blue() - b.blue()) <= tolerance)


def inspect(Qt, tb, name, save):
    """What is wrong with this window, as a list of sentences."""
    from apps import theme
    problems = []
    # Everything in the window, scrolled into view or not: at the laptop's
    # size most windows scroll, and a plot below the fold is still a plot.
    content = tb.top_scroll.widget()
    image = content.grab().toImage().convertToFormat(Qt.QImage.Format_RGB32)
    if save:
        os.makedirs(save, exist_ok=True)
        tb.grab().save(os.path.join(save, f'{name}.png'))
        image.save(os.path.join(save, f'{name}-whole.png'))
    well = Qt.QColor(theme.TOKENS['well'])

    sheet = tb.styleSheet()
    if theme.TOKENS['ground'] not in sheet or 'DisplayPlot' not in sheet:
        problems.append("the window does not carry the flowgraph theme - "
                        "apply_flowgraph_theme(self) is missing from __init__")

    plots = [w for w in content.findChildren(Qt.QWidget)
             if w.isVisible() and w.inherits('DisplayPlot')]
    if not plots:
        problems.append("no plot found")
    canvases = []
    for plot in plots:
        title = plot.metaObject().className()
        for label in plot.findChildren(Qt.QWidget, 'QwtPlotTitle'):
            if label.property('plainText'):
                title = label.property('plainText')
        canvas = next((w for w in plot.findChildren(Qt.QWidget)
                       if w.inherits('QwtPlotCanvas')), None)
        if canvas is None:
            continue
        rect = Qt.QRect(canvas.mapTo(content, Qt.QPoint(0, 0)), canvas.size())
        canvases.append(rect)
        # The well has to show, not dominate: a constellation drawn with
        # lines can cover most of its canvas, and that is the signal.
        inside = [image.pixel(x, y)
                  for y in range(rect.top() + 2, rect.bottom() - 1, 2)
                  for x in range(rect.left() + 2, rect.right() - 1, 2)]
        share = (sum(1 for c in inside if close_to(Qt.QColor(c), well, 3))
                 / max(len(inside), 1))
        if share < 0.10:
            behind = commonest(Qt, image, rect.adjusted(2, 2, -2, -2))
            problems.append(f"'{title}': the canvas is "
                            f"{behind.name() if behind else 'not drawn'}, "
                            f"not the well {well.name()}")
        # A plot reports black for a line it does not have, so only the
        # lines its legend lists are asked about - or just the first.
        lines = max(1, sum(1 for w in plot.findChildren(Qt.QWidget)
                           if w.inherits('QwtLegendLabel')))
        for i in range(1, lines + 1):
            colour = plot.property(f'line_color{i}')
            if isinstance(colour, Qt.QColor) and \
                    contrast(colour, well) < TRACE_CONTRAST:
                problems.append(f"'{title}': trace {i} is {colour.name()}, "
                                f"{contrast(colour, well):.1f}:1 on the well")
        for scale in plot.findChildren(Qt.QWidget):
            if scale.inherits('QwtScaleWidget') and scale.isVisible() and \
                    scale.font().family() != theme.TOKENS['f_ui']:
                problems.append(f"'{title}': axis in "
                                f"{scale.font().family()}, not "
                                f"{theme.TOKENS['f_ui']}")
                break

    # Almost nothing near white outside the plots. The old window was light
    # grey all over; the theme's ink is near white too, but only as text.
    # A trace may be as bright as it likes.
    bright = total = 0
    for y in range(0, image.height(), 2):
        for x in range(0, image.width(), 2):
            if any(r.contains(x, y) for r in canvases):
                continue
            c = image.pixel(x, y)
            total += 1
            if min((c >> 16) & 255, (c >> 8) & 255, c & 255) > 200:
                bright += 1
    if total and bright / total > BRIGHT_SHARE:
        problems.append(f"{100 * bright / total:.1f}% of the window is near "
                        f"white, against {100 * BRIGHT_SHARE:.0f}% allowed - "
                        f"something is still in the old light theme")

    for label in content.findChildren(Qt.QLabel):
        if not label.isVisible() or not label.isEnabled() or \
                not label.text().strip() or label.width() < 4:
            continue
        rect = Qt.QRect(label.mapTo(content, Qt.QPoint(0, 0)), label.size())
        behind = commonest(Qt, image, rect)
        ink = label.palette().color(Qt.QPalette.WindowText)
        if behind is not None and contrast(ink, behind) < TEXT_CONTRAST:
            text = Qt.QTextDocumentFragment.fromHtml(label.text()).toPlainText()
            problems.append(f"label '{text[:40]}' is {ink.name()} on "
                            f"{behind.name()}, {contrast(ink, behind):.1f}:1")

    if Qt.QApplication.font().family() != theme.TOKENS['f_ui']:
        problems.append(f"the application font is "
                        f"{Qt.QApplication.font().family()}, so the plots' "
                        f"axis titles are not in {theme.TOKENS['f_ui']}")
    return problems


def run_child(argv_tail, label):
    """Run one check in a process of its own; its result, and what it said."""
    argv = [sys.executable, os.path.abspath(__file__)] + argv_tail
    try:
        out = subprocess.run(argv, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True,
                             timeout=180, cwd=ROOT).stdout
    except subprocess.TimeoutExpired:
        out = ''
    lines = out.splitlines()
    result = next((l for l in lines if l.startswith('RESULT ')), None)
    for line in lines:
        if line.startswith('PROBLEM '):
            print('      ' + line.split(' ', 1)[1])
    if result is None:
        print(f"  FAIL {label:30} no result - its output ended:")
        for line in lines[-8:]:
            print('       ' + line)
        return False
    if result.split()[-1] != '0':
        print(f"  FAIL {label:30} {result.split()[-1]} problem(s)")
        return False
    print(f"  ok   {label}")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('apps', nargs='*', help='only these modules')
    parser.add_argument('--save', metavar='DIR',
                        help='write a PNG of every window here')
    parser.add_argument('--child', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        child(args.child, args.save)
        return 0

    failed = []
    print('the windows, with no radio')
    names = args.apps or MODULES
    for name in names:
        tail = ['--child', name]
        if args.save:
            tail += ['--save', os.path.abspath(args.save)]
        if not run_child(tail, name):
            failed.append(name)
    print(f"\n{len(names)} windows checked")
    if failed:
        print("RESULT: FAIL - " + ', '.join(failed))
        return 1
    print("all checks passed")
    return 0


if __name__ == '__main__':
    sys.exit(main())
