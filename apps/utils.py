import json
import os
from PyQt5 import Qt  #type: ignore
from PyQt5.QtCore import QObject, QEvent, QRect  #type: ignore


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
    QMessageBox {
        background-color: #2e2e2e;
        color: #ffffff;
    }
    """
    widget.setStyleSheet(stylesheet)

#This function is called to apply the theme to the dialog
def apply_dark_theme(widget):
    # Set minimum dialog size
    if isinstance(widget, Qt.QDialog):
        widget.setMinimumWidth(350)
        widget.setMinimumHeight(400)
    
    stylesheet = """
    QDialog, QWidget {
        background-color: #2e2e2e;
        color: #ffffff;
    }
    QLabel {
        color: #ffffff;
        margin-top: 10px;  /* Add spacing above labels */
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
        margin: 5px 0px;  /* Add vertical spacing */
    }
    QComboBox:hover {
        background-color: #656565;
        border: 2px solid #767676;
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
        margin: 15px 0px;  /* Add more vertical spacing around sliders */
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
    QHBoxLayout {
        margin: 10px 0px;  /* Add spacing around horizontal layouts */
    }
    QVBoxLayout {
        margin: 10px 0px;  /* Add spacing around vertical layouts */
    }
    """
    widget.setStyleSheet(stylesheet)

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


# Every spectrum plot uses this vertical range, so a signal at a given level
# looks the same height in whichever app you open.
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
