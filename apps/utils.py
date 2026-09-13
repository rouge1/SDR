import json
import os
from PyQt5 import Qt  #type: ignore
from PyQt5.QtCore import (QObject, QEvent, QRect, Qt as QtNs,  #type: ignore
                          pyqtSignal)


# --- Buffers ----------------------------------------------------------------

#: GNU Radio allocates stream buffers in whole memory pages.
BUFFER_PAGE = 4096


def page_aligned_items(item_size, page=BUFFER_PAGE):
    """How many items of this size fill a whole number of pages.

    GNU Radio rounds every buffer up to a page boundary, and warns when the
    size it was asked for is not already there:

        buffer_double_mapped :warning: allocate_buffer: tried to allocate
        316 items of size 207. Due to alignment requirements 4096 were
        allocated.

    The ATSC chain trips this four times on every run, because a transport
    packet is 188 bytes and a Reed-Solomon one is 207 - neither a power of
    two - so the line is printed at WARN, four times, every time, about
    something nobody can do anything about and which is not a fault.

    Asking for the aligned count up front silences it without hiding
    anything: the allocation is identical, since that is what GNU Radio was
    going to allocate anyway. 207 needs 4096 items, 188 needs 1024.
    """
    from math import gcd
    return page // gcd(int(item_size), page)


def align_output_buffer(block, port, item_size):
    """Ask a block for a page-aligned output buffer. See above."""
    try:
        block.set_min_output_buffer(port, page_aligned_items(item_size))
    except Exception:
        # Never worth failing a flowgraph over a log line.
        pass


# --- Tuning -----------------------------------------------------------------

#: The resolution every frequency control works in. 0.1 MHz is finer than
#: any radio here needs to be set and keeps the slider a manageable length.
FREQ_STEP_MHZ = 0.1


class FrequencyChooser(Qt.QWidget):
    """Tune to an exact frequency: type it, pick a channel, or drag to it.

    **A plain QSlider cannot do this job, and it was not obvious why.**
    ``atscXmitter`` had one running 50 to 2200 in whole megahertz: 2150
    positions rendered across a few hundred pixels, so one pixel of mouse
    travel is about seven megahertz and most frequencies are not reachable
    at all. Asked for 533 MHz - the channel this bench uses - the nearest
    the mouse could get was 539, and nothing about the control said so.

    So there are three ways in, and they stay in step with each other:

    - a **spin box**, which is the only one that can be exact, and which
      takes a typed number;
    - a **channel picker**, when the caller passes a channel plan, because
      "UHF 24" is how anyone actually thinks about a television channel;
    - a **slider** for sweeping, now stepping in tenths of a megahertz,
      with its page step set to one 6 MHz channel so PageUp and PageDown
      walk the band a channel at a time.

    ``valueChanged`` carries megahertz as a float and fires once per real
    change, whichever of the three caused it.
    """

    valueChanged = pyqtSignal(float)

    def __init__(self, minimum=50.0, maximum=2200.0, value=None, channels=None,
                 label="Center Frequency (MHz):", parent=None):
        super().__init__(parent)
        self._min = float(minimum)
        self._max = float(maximum)
        self._value = None

        layout = Qt.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.channel_combo = None
        if channels:
            row = Qt.QHBoxLayout()
            row.addWidget(Qt.QLabel("Channel:"))
            self.channel_combo = Qt.QComboBox()
            # A frequency between channels is a legitimate thing to want, so
            # the list says so rather than snapping to the nearest channel.
            self.channel_combo.addItem("(not on a channel)", None)
            for _number, centre, caption in channels:
                self.channel_combo.addItem(caption, float(centre))
            self.channel_combo.currentIndexChanged.connect(self._channel_picked)
            row.addWidget(self.channel_combo, 1)
            layout.addLayout(row)

        row = Qt.QHBoxLayout()
        row.addWidget(Qt.QLabel(label))
        self.spin = Qt.QDoubleSpinBox()
        self.spin.setDecimals(1)
        self.spin.setSingleStep(FREQ_STEP_MHZ)
        self.spin.setRange(self._min, self._max)
        # Without this the box emits on every keystroke, so typing "533"
        # tunes through 5 MHz and 53 MHz on the way.
        self.spin.setKeyboardTracking(False)
        self.spin.valueChanged.connect(self.setValue)
        row.addWidget(self.spin)
        row.addStretch()
        layout.addLayout(row)

        self.slider = Qt.QSlider(QtNs.Horizontal)
        self.slider.setRange(self._steps(self._min), self._steps(self._max))
        self.slider.setSingleStep(1)                  # an arrow key: 0.1 MHz
        self.slider.setPageStep(int(6.0 / FREQ_STEP_MHZ))   # a page: 6 MHz
        self.slider.valueChanged.connect(
            lambda steps: self.setValue(steps * FREQ_STEP_MHZ))
        layout.addWidget(self.slider)

        self.setValue(self._min if value is None else value)

    @staticmethod
    def _steps(mhz):
        return int(round(float(mhz) / FREQ_STEP_MHZ))

    def value(self):
        return self._value

    def setValue(self, mhz):
        try:
            mhz = round(min(max(float(mhz), self._min), self._max), 1)
        except (TypeError, ValueError):
            return
        if self._value is not None and abs(mhz - self._value) < FREQ_STEP_MHZ / 2:
            return
        self._value = mhz
        self._refresh()
        self.valueChanged.emit(mhz)

    def _refresh(self):
        """Put all three controls on the current value without feedback."""
        for widget, setter, new in (
                (self.spin, self.spin.setValue, self._value),
                (self.slider, self.slider.setValue, self._steps(self._value))):
            widget.blockSignals(True)
            setter(new)
            widget.blockSignals(False)
        if self.channel_combo is None:
            return
        index = 0
        for k in range(1, self.channel_combo.count()):
            centre = self.channel_combo.itemData(k)
            if centre is not None and abs(centre - self._value) < 0.05:
                index = k
                break
        self.channel_combo.blockSignals(True)
        self.channel_combo.setCurrentIndex(index)
        self.channel_combo.blockSignals(False)

    def _channel_picked(self, _index):
        centre = self.channel_combo.currentData()
        if centre is not None:
            self.setValue(centre)


class DialogGeometryTracker(QObject):
    """Event filter that captures dialog geometry the moment it is hidden.

    Install before calling exec_() and read ``captured`` afterwards to get
    the last valid position/size regardless of how the dialog was closed
    (OK, Cancel, or window-close button).
    """
    def __init__(self, dialog):
        super().__init__(dialog)
        self.captured = None
        dialog.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Hide and self.captured is None:
            self.captured = {
                'x': obj.pos().x(),
                'y': obj.pos().y(),
                'width': obj.width(),
                'height': obj.height(),
            }
        return False


def geometry_is_reachable(app, position, minimum=(160, 40)):
    """True if a window restored at this saved geometry could still be grabbed.

    The point of validating a saved position is that the user can reach the
    title bar again, not that the window fits neatly. The per-site checks this
    replaces got three things wrong:

    - They measured against the dialog's ``width()`` *before* it was shown,
      which is Qt's 640x480 default and has nothing to do with the dialog - its
      real size hint is more like 515x631. On a 1366x768 laptop that made the
      test ``0 <= x <= 726``, so any dialog parked on the right half of the
      screen was judged invalid, reopened at the default position, and had that
      default saved back over the real one. It looked like the position was
      never being remembered.
    - They demanded the whole window fit inside the screen, throwing away a
      window deliberately parked against an edge.
    - They only looked at the primary screen, so a window on a second monitor
      was never valid - which is the normal case on a multi-head desk.

    Sizes come from the saved geometry, and ``availableGeometry`` is used so the
    taskbar does not count as usable space.
    """
    try:
        rect = QRect(int(position['x']), int(position['y']),
                     int(position.get('width') or minimum[0]),
                     int(position.get('height') or minimum[1]))
    except (KeyError, TypeError, ValueError):
        return False
    for screen in app.screens():
        overlap = screen.availableGeometry().intersected(rect)
        if overlap.width() >= minimum[0] and overlap.height() >= minimum[1]:
            return True
    return False


def adopt_legacy_config(config_dir, legacy_name, config_file):
    """Fold a config saved under an old filename into the module-named one.

    Four dialogs used to save under a name that did not match their module -
    fmAudioRecordedGenerator wrote fmAudioGenerator_config.json, atscXmitter
    wrote atsc_config.json, and so on - while the launcher has always written
    dialog_position to ``<module>_config.json``. Settings and window geometry
    therefore ended up in two separate files for those four. Renaming on its own
    would have orphaned whatever was already saved, so the old file is merged in
    on first run instead.

    Keys from the launcher-written file win, because that is the one that may
    already hold ``dialog_position``; the legacy file only ever held the
    dialog's own settings, so in practice they do not overlap. The old file is
    then renamed aside rather than deleted - that makes the migration a one
    shot, and leaves the original recoverable if a merge ever goes wrong.
    """
    legacy = os.path.join(config_dir, legacy_name)
    if not os.path.exists(legacy):
        return
    try:
        with open(legacy) as f:
            merged = json.load(f)
        if not isinstance(merged, dict):
            return
        if os.path.exists(config_file):
            with open(config_file) as f:
                current = json.load(f)
            if isinstance(current, dict):
                merged.update(current)
        os.makedirs(config_dir, exist_ok=True)
        with open(config_file, 'w') as f:
            json.dump(merged, f, indent=4)
        os.replace(legacy, legacy + '.migrated')
    except Exception as e:
        # A failed migration must never stop the dialog opening. The app falls
        # back to defaults and the legacy file is left where it is.
        print(f"Could not migrate {legacy_name}: {e}")


#This function is called to apply the theme to the launcher
def apply_launcher_theme(widget):
    stylesheet = """
    QMainWindow {
        background-color: #2e2e2e;
    }
    QLabel {
        color: #ffffff;
    }
    QPushButton {
        background-color: #4b4b4b;
        color: #ffffff;
        border: 2px solid #5c5c5c;
        border-radius: 10px;
        padding: 0px;  /* Remove padding to allow icon to fill */
    }
    QPushButton:hover {
        background-color: #656565;
        border: 2px solid #767676;
    }
    QPushButton:pressed {
        background-color: #3d3d3d;
        border: 2px solid #4e4e4e;
    }
    /* A tile the selected radio cannot run: still there, plainly not
       available, and its tooltip says which way the radio goes. */
    QPushButton:disabled {
        background-color: #383838;
        color: #6e6e6e;
        border: 2px dashed #4a4a4a;
    }
    QLabel:disabled {
        color: #6e6e6e;
    }
    QMessageBox {
        background-color: #2e2e2e;
        color: #ffffff;
    }
    """
    widget.setStyleSheet(stylesheet)

# --- Dialog layout ----------------------------------------------------------

#: The rhythm every config dialog is laid out on: the gap around the edge,
#: and the gap between one control and the next.
DIALOG_MARGIN = 12
DIALOG_SPACING = 8


def _dialog_layout(widget):
    """The widget's layout, whether or not the method has been shadowed.

    Every ConfigDialog here does ``self.layout = Qt.QVBoxLayout(self)``, which
    replaces the ``layout()`` method with the layout object. Both spellings
    have to work.
    """
    attr = getattr(widget, 'layout', None)
    if isinstance(attr, Qt.QLayout):
        return attr
    try:
        return widget.layout()
    except TypeError:
        return None


#: Widgets that arrange their own insides. Do not reach into these at all:
#: a combo box's list is a view of its own, and a tool bar and a button box
#: lay themselves out.
_SELF_CONTAINED = (Qt.QAbstractScrollArea, Qt.QAbstractItemView,
                   Qt.QComboBox, Qt.QDialogButtonBox, Qt.QToolBar)


def _collect(layout, rows, captions, nested, group=False):
    """Find the labels and nested layouts under this one.

    A label that leads a ``QHBoxLayout`` is a *row* label - it names the
    control beside it. A label sitting on its own in a vertical layout is a
    *caption* - it names the control underneath it.

    Inside a group box only the layouts are collected. Its contents are
    indented from the dialog's own column by the frame, so pulling its rows
    into that column would push them back out of the box.
    """
    if isinstance(layout, Qt.QHBoxLayout) and not group:
        widgets = [layout.itemAt(i).widget() for i in range(layout.count())]
        widgets = [w for w in widgets if w is not None]
        if len(widgets) > 1 and isinstance(widgets[0], Qt.QLabel):
            rows.append(widgets[0])
    vertical = isinstance(layout, Qt.QVBoxLayout)
    for i in range(layout.count()):
        item = layout.itemAt(i)
        child = item.layout()
        if child is not None:
            nested.append(child)
            _collect(child, rows, captions, nested, group)
            continue
        w = item.widget()
        if w is None or isinstance(w, _SELF_CONTAINED):
            continue
        if vertical and i and isinstance(w, Qt.QLabel) and not group:
            captions.append(w)
            continue
        inner = _dialog_layout(w)
        if inner is not None:
            if isinstance(w, Qt.QGroupBox):
                # The box's own layout keeps its margins, or the frame cuts
                # through the text - but the rows inside it still get
                # straightened.
                _collect(inner, rows, captions, nested, group=True)
                continue
            # A plain QWidget used only to hold a row - the containers that
            # exist so an opacity effect has something to apply to - keeps
            # its layout's default 9 px margin otherwise, and that indents
            # the row it holds out of line with the rest of the dialog.
            nested.append(inner)
            _collect(inner, rows, captions, nested, group)


def tidy_dialog(dialog):
    """Straighten a hand-built dialog. Four fixes, all of them layout.

    The fifteen config dialogs are each assembled by hand out of
    ``QVBoxLayout`` and ``QHBoxLayout``, and they were all crooked in the
    same ways - which is what makes this worth doing centrally rather than
    in fifteen places.

    - **The label in a row sat four or five pixels below the control beside
      it.** The stylesheet gave every ``QLabel`` a 10 px top margin, to
      space a caption off whatever was above it. Inside a row that margin
      pushes the *text* down within the label's own rectangle while the spin
      box or slider next to it stays centred, so the box reads as sitting
      high - measured on every row of all fifteen dialogs. The margin is
      gone from the stylesheet and the gap comes from layout spacing now,
      which is what layout spacing is for.
    - **Sliders started at a different x in every row**, because each one
      began wherever its label's text happened to end: four different
      positions in one dialog. Every label that leads a row is given the
      width of the widest of them, so the controls line up in a column. It
      also stops the slider shifting sideways as a live value in the label
      changes width - "Power Level: 5%" to "Power Level: 100%" moved it.
    - **A nested row was indented**, since sub-layouts keep their own
      default margins - "Sine Frequency" sat ten pixels right of every
      other label in the same dialog.
    - **Short dialogs spread their contents out.** A forced 400 px minimum
      height left the receivers half empty, and a ``QVBoxLayout`` hands the
      slack to whatever can grow, which is the labels: the gaps between
      controls came out uneven. A stretch before the button box collects
      it in one place instead.
    """
    if not isinstance(dialog, Qt.QWidget):
        return                      # apply_dark_theme is also called on a
                                    # QApplication, which has no layout.
    top = _dialog_layout(dialog)
    if top is None:
        return
    top.setContentsMargins(DIALOG_MARGIN, DIALOG_MARGIN,
                           DIALOG_MARGIN, DIALOG_MARGIN)
    top.setSpacing(DIALOG_SPACING)

    rows, captions, nested = [], [], []
    _collect(top, rows, captions, nested)
    for layout in nested:
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(DIALOG_SPACING)
    if rows:
        width = max(label.sizeHint().width() for label in rows)
        for label in rows:
            label.setMinimumWidth(width)
            # Fixed, or the column still moves: a label is Preferred by
            # default, so in a row with a spin box - which is Expanding -
            # the two share the slack and that row's control starts 26 px
            # right of every other. Fixed caps the label at its own text,
            # and the minimum above brings the short ones up to the column.
            label.setSizePolicy(Qt.QSizePolicy.Fixed,
                                label.sizePolicy().verticalPolicy())
    for label in captions:
        # A caption belongs to the control below it, so give it more room
        # above than below. This is the grouping the old stylesheet margin
        # was after - it just applied it to every label, including the ones
        # in a row, which is what knocked those crooked.
        label.setContentsMargins(0, DIALOG_SPACING, 0, 0)

    if isinstance(top, Qt.QVBoxLayout):
        index = top.count()
        for i in range(top.count()):
            if isinstance(top.itemAt(i).widget(), Qt.QDialogButtonBox):
                index = i
                break
        top.insertStretch(index, 1)


#: The repository's icons, found from this file so that it does not matter
#: which directory the app was started from.
ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'icons')


def icon_url(name):
    """An icons/ path in the form a Qt stylesheet url() wants.

    Forward slashes on every platform - a Windows backslash is an escape
    character to the stylesheet parser, and the rule is dropped silently.
    """
    return os.path.join(ICON_DIR, name).replace('\\', '/')


#This function is called to apply the theme to the dialog
def apply_dark_theme(widget):
    # A floor on the width only. There used to be one of 400 on the height
    # too, which made every short dialog too tall - see tidy_dialog.
    if isinstance(widget, Qt.QDialog):
        widget.setMinimumWidth(360)

    stylesheet = """
    QDialog, QWidget {
        background-color: #2e2e2e;
        color: #ffffff;
    }
    QLabel {
        color: #ffffff;
    }
    QPushButton {
        background-color: #4b4b4b;
        color: #ffffff;
        border: 2px solid #5c5c5c;
        border-radius: 5px;
        padding: 5px;
        min-width: 80px;
    }
    QPushButton:hover {
        background-color: #656565;
        border: 2px solid #767676;
    }
    QPushButton:pressed {
        background-color: #3d3d3d;
        border: 2px solid #4e4e4e;
    }
    QComboBox {
        background-color: #4b4b4b;
        color: #ffffff;
        border: 2px solid #5c5c5c;
        border-radius: 5px;
        padding: 5px;
    }
    QComboBox:hover {
        background-color: #656565;
        border: 2px solid #767676;
    }
    /* Typed-in controls, matching the combo boxes. Without these they fall
       through to the plain QWidget rule and come out as flat dark boxes,
       so two controls doing the same job - pick a number, type a number -
       looked like they belonged to different applications. */
    QLineEdit, QAbstractSpinBox {
        background-color: #4b4b4b;
        color: #ffffff;
        border: 2px solid #5c5c5c;
        border-radius: 5px;
        padding: 4px;
        selection-background-color: #767676;
    }
    QLineEdit:focus, QAbstractSpinBox:focus {
        border: 2px solid #8a8a8a;
    }
    QLineEdit:disabled, QAbstractSpinBox:disabled {
        color: #6e6e6e;
        border: 2px solid #4a4a4a;
    }
    /* A spin box that a stylesheet touches at all stops drawing its own
       arrows - the two buttons come out as empty boxes - and Qt's CSS
       subset will not draw a triangle out of borders either; it renders
       the four borders as a rectangle. So the arrows are images. */
    QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {
        subcontrol-origin: border;
        background-color: #5c5c5c;
        border: none;
        width: 17px;
    }
    QAbstractSpinBox::up-button {
        subcontrol-position: top right;
        border-top-right-radius: 3px;
        margin: 2px 2px 0px 0px;
    }
    QAbstractSpinBox::down-button {
        subcontrol-position: bottom right;
        border-bottom-right-radius: 3px;
        margin: 0px 2px 2px 0px;
    }
    QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {
        background-color: #767676;
    }
    QAbstractSpinBox::up-arrow {
        image: url(%(up)s);
        width: 9px;
        height: 5px;
    }
    QAbstractSpinBox::down-arrow {
        image: url(%(down)s);
        width: 9px;
        height: 5px;
    }
    QComboBox QAbstractItemView {
        background-color: #4b4b4b;
        color: #ffffff;
        selection-background-color: #656565;
        selection-color: #ffffff;
        border: 1px solid #5c5c5c;
    }
    QSlider {
        background-color: transparent;
    }
    QSlider::groove:horizontal {
        background-color: #4b4b4b;
        height: 8px;
        border-radius: 4px;
    }
    QSlider::handle:horizontal {
        background-color: #ffffff;
        border: none;
        width: 16px;
        margin: -4px 0;
        border-radius: 8px;
    }
    QSlider::handle:horizontal:hover {
        background-color: #dddddd;
    }
    """
    # There were QHBoxLayout and QVBoxLayout rules here too. A Qt stylesheet
    # only ever applies to widgets, so they had never done anything; the
    # spacing they were meant to give is set by tidy_dialog.
    #
    # The arrow paths are absolute and worked out from this file, not from
    # the working directory, because a stylesheet resolves url() against the
    # process's cwd and an app can be started from anywhere.
    widget.setStyleSheet(stylesheet % {'up': icon_url('spin-up.png'),
                                       'down': icon_url('spin-down.png')})
    tidy_dialog(widget)

def read_settings():
    """Read settings from window_settings.json and ensure required fields exist"""
    settings_file = os.path.join("config", "window_settings.json")
    settings = {'media_directory': '', 'ip_addresses': [], 'radio_type': 'hackrf'}
    
    try:
        if os.path.exists(settings_file):
            with open(settings_file) as f:
                saved_settings = json.load(f)
                settings.update(saved_settings)
                
                # If any defaults were missing, write them back
                if 'media_directory' not in saved_settings or 'ip_addresses' not in saved_settings:
                    with open(settings_file, 'w') as f:
                        json.dump(settings, f, indent=4)
                        
    except Exception as e:
        print(f"Error reading settings:", e)
        
    return settings


# --- Radio output power -----------------------------------------------------
#
# The power slider is a plain 0-100% control. Each radio has a different native
# gain unit and a different usable span, so the percentage is mapped onto that
# radio's own range: 0% is always its minimum and 100% always its maximum.
#
# This replaced an older scheme where the slider was labelled dBm but actually
# fed `(rfPwr+50)*(rfPwr>-50)` to HackRF/USRP - which capped both radios at
# 20 dB of gain and left the bottom 30 dB of the slider doing nothing at all.

RADIO_POWER_RANGE = {
    'hackrf': (0.0, 47.0),     # SoapySDR VGA gain, dB
    'usrp':   (0.0, 31.5),     # UHD gain, dB - replaced by the device's own
                               # range when it can be queried
    'vsg':    (-120.0, 10.0),  # Signal Hound calibrated output level, dBm
}


def resolve_power_range(radio_type, sink=None):
    """Return (min, max) for a radio, in that radio's own gain units.

    USRP gain range depends on the daughterboard, so query the device when a
    constructed sink is available and fall back to the table otherwise.
    """
    if radio_type == 'usrp' and sink is not None:
        try:
            rng = sink.get_gain_range()
            return (float(rng.start()), float(rng.stop()))
        except Exception:
            pass
    return RADIO_POWER_RANGE.get(radio_type, RADIO_POWER_RANGE['hackrf'])


def scale_power(percent, power_range):
    """Map a 0-100% slider position onto a radio's gain/level range."""
    low, high = power_range
    percent = min(max(float(percent), 0.0), 100.0)
    return low + (high - low) * percent / 100.0


def power_percent(value, default=50):
    """Sanitise a saved power setting, as an int.

    Configs written before the percentage change hold dBm-ish values such as
    -50, which would silently clamp to 0% (no output). Fall back to the default
    for anything outside 0-100.

    Returns an int because this feeds QSlider.setValue(), which rejects a float
    with a TypeError - and load_config() swallows exceptions, so a float here
    silently drops every setting restored after the power slider.
    """
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    if not 0.0 <= value <= 100.0:
        return default
    return int(round(value))


# Every spectrum plot opens on this vertical range, so a signal at a given
# level looks the same height in whichever app you open.
#
# Autoscale is on only for the baseband plots (freq_sink_f - the MPX views and
# the subcarrier's audio), and off for the RF ones (freq_sink_c). Autoscale fits
# the axis from the lowest bin to the highest, and the RF spectra of these
# synthesised signals have bins at numerical zero: fmAudioRecordedGenerator and
# amSineGenerator both stretched to about -380 dB, which left the carrier and
# the noise floor squeezed into the top third of the plot - the opposite of
# centring it. The baseband plots have audio or noise in every bin and fit
# well, fmRdsTransmitter offscreen and rdsReceiver live on 98.7 alike. RF plots
# therefore keep this measured fixed range.
#
# Top is 0 dB: that is digital full scale, and nothing can get above it. The
# strongest thing any of these flowgraphs can put on a plot is an unmodulated
# carrier - all of its power in one bin - and that measures about -10 dB. The
# old ceilings of +10 were showing 20 dB of space no signal could ever reach.
#
# Bottom is -170 dB because the FFT's own numerical noise floor sits near -160.
# The old floors of -120/-140 cut straight through it, so the skirts of a
# signal ended in a flat clipped band across the bottom of the plot instead of
# descending into the grass.
SPECTRUM_Y_AXIS = (-170, 0)
