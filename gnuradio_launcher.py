#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Standard library imports
import sys
import os
import json
import math
import importlib.util

# Third party imports
from PyQt5.QtWidgets import ( # type: ignore
    QMainWindow,
    QWidget,
    QGridLayout,
    QPushButton,
    QLabel,
    QApplication,
    QVBoxLayout,
    QDialog,
    QGraphicsOpacityEffect,
    QMessageBox
)
from PyQt5.QtCore import (Qt, QSize, QPoint, QPropertyAnimation,  # type: ignore
                          QEasingCurve, pyqtProperty)
from PyQt5.QtGui import QIcon, QPixmap, QFont, QPainter # type: ignore

# Add PIL import at the top with other imports
from PIL import Image, ImageEnhance # type: ignore
import io
import numpy as np # type: ignore

# Local imports 
from apps.utils import (apply_launcher_theme, apply_dark_theme,
                       DialogGeometryTracker, geometry_is_reachable,
                       read_settings)
from apps.settings_dialog import SettingsDialog

# Which way each radio goes. Two of the four are one-way instruments, and
# the grid follows: choose the VSG60 and every tile turns to its
# transmitting side, choose the BB60D and they all turn to receive. A radio
# that does both leaves the tiles free to flip.
RADIO_DIRECTIONS = {
    'hackrf': {'tx', 'rx'},
    'usrp': {'tx', 'rx'},
    'vsg': {'tx'},          # Signal Hound VSG60 - a signal generator
    'bb60': {'rx'},         # Signal Hound BB60D - a spectrum analyser
}
RADIO_NAMES = {
    'hackrf': 'The HackRF One', 'usrp': 'The Ettus USRP',
    'vsg': 'The Signal Hound VSG60', 'bb60': 'The Signal Hound BB60D',
}
DIRECTION_WORDS = {'tx': 'transmit', 'rx': 'receive'}


# Every tile in the grid, declared rather than built by hand, as
# (row, column, [face, ...]) where a face is
# (label, module, icon, direction) and direction is 'tx' or 'rx'.
#
# A tile with more than one face is a *flip* tile: a badge in its corner
# turns it over, and the icon and the label both change with it. That is
# how the two ends of one standard share a square - the ATSC transmitter
# and receiver, the FM + RDS transmitter and the RDS receiver - instead of
# sitting apart as though they were unrelated apps.
#
# The direction is not decoration. It is what lets the grid arrange itself
# around whichever radio is selected, and what stops an app being launched
# against a radio that cannot possibly run it - which used to end in "no
# HackRF found", sending people to check a cable that was not the problem.
#
# Row 0 holds the title and the settings gear. Row 1 is the plain signal
# generators, row 2 audio, row 3 video. The gap at (2, 4) is where the RDS
# receiver used to sit before it became the back of the transmitter's tile.
#
# scripts/test_launcher_gui.py reads this table to find what to click, so
# keep it literal: it is parsed with ast, not imported.
APP_TILES = [
    (1, 0, [("AM Sine Generator", "amSineGenerator", "amSine.jpg", "tx")]),
    (1, 1, [("ASK Generator", "askGenerator", "ask.jpg", "tx")]),
    (1, 2, [("FSK Signal Generator", "fskGenerator", "fsk.jpg", "tx")]),
    (1, 3, [("PSK Signal Generator", "pskGenerator", "psk.jpg", "tx")]),
    (1, 4, [("PPM-OOK Generator", "ppmookAudioXmitter", "ppm-ook.png", "tx")]),
    (2, 0, [("AM Audio Generator", "amAudioInternalGeneratorLive",
             "amAudio.jpg", "tx")]),
    (2, 1, [("FM Audio Generator", "fmAudioRecordedGenerator",
             "fmAudio.png", "tx")]),
    (2, 2, [("FM Subcarrier", "subcarrierRecordedAudio",
             "fmSubcarrier.jpg", "tx")]),
    (2, 3, [("FM + RDS Transmitter", "fmRdsTransmitter", "fmrds.png", "tx"),
            ("RDS Receiver", "rdsReceiver", "rds.png", "rx")]),
    # atscXmit.jpg is the radiating one and atsc.jpg is a television set,
    # so they land this way round rather than the way the filenames read.
    (3, 0, [("ATSC Video Transmitter", "atscXmitter", "atscXmit.jpg", "tx"),
            ("ATSC Video Receiver", "atscReceiver", "atsc.jpg", "rx")]),
    (3, 1, [("NTSC Analog Video", "ntscAnalogVideoRecorded",
             "ntsc.jpg", "tx")]),
    (3, 2, [("AM Video Transmitter", "amVideoRecordedXmitter",
             "amVideo.jpg", "tx")]),
]


def face_directions():
    """module name -> 'tx' or 'rx', read off the tile table."""
    return {face[1]: face[3] for _row, _col, faces in APP_TILES
            for face in faces}

TILE_SIZE = 200
BADGE_SIZE = 32
BADGE_INSET = 6
FLIP_MS = 380


class FlipTile(QPushButton):
    """One square of the launcher grid, which may have more than one face.

    Clicking the tile launches whichever app is showing. Clicking the badge
    in its corner turns the tile over: the icon and the caption both change,
    animated as a card being flipped rather than simply swapped, so it is
    obvious that this is one tile with two sides and not a button that
    mysteriously rearranged itself.

    The turn is drawn by squeezing the icon horizontally through zero width
    and back - ``cos`` of the animation phase - and swapping the face at the
    moment it is edge on, which is exactly when nothing of it is visible.
    The caption fades on the same curve; squeezing text instead just looks
    like a rendering fault.

    Which side is up is remembered in ``window_settings.json``, so a tile
    left showing the receiver is still showing it next time.
    """

    def __init__(self, launcher, faces, size=TILE_SIZE):
        super().__init__()
        self.launcher = launcher
        self.faces = list(faces)
        self.key = self.faces[0][1]      # the first module names the tile
        self.face = 0
        self._target = 0
        self._flip = 0.0
        # Which faces the selected radio can actually run, and whether the
        # tile can be used at all. Both are set by ``set_directions``.
        self.allowed = list(range(len(self.faces)))
        self.usable = True
        self._remember_turn = True
        self.setFixedSize(size, size)

        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        layout.setAlignment(Qt.AlignCenter)

        self._pixmaps = [QIcon(f"icons/{face[2]}").pixmap(QSize(size, size))
                         for face in self.faces]
        # One box big enough for every face, so squeezing the picture inside
        # it cannot shove the caption around while the tile turns - and so a
        # face with a different aspect ratio from the first is not clipped.
        self._box = QSize(max(p.width() for p in self._pixmaps),
                          max(p.height() for p in self._pixmaps))
        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setFixedSize(self._box)

        self.text_label = QLabel()
        self.text_label.setFont(QFont('Arial', 11))
        self.text_label.setAlignment(Qt.AlignCenter)
        self.text_label.setWordWrap(True)
        self._fade = QGraphicsOpacityEffect(self.text_label)
        self._fade.setOpacity(1.0)
        self.text_label.setGraphicsEffect(self._fade)

        layout.addWidget(self.icon_label)
        layout.addWidget(self.text_label)
        self.setLayout(layout)

        self.badge = None
        if len(self.faces) > 1:
            self._build_badge(size)

        self.clicked.connect(self._launch)
        self.animation = QPropertyAnimation(self, b'flip_phase', self)
        self.animation.setDuration(FLIP_MS)
        self.animation.setEasingCurve(QEasingCurve.InOutQuad)

        self.set_face(launcher.saved_face(self.key, len(self.faces)))

    # -- the badge -------------------------------------------------------

    def _build_badge(self, size):
        self.badge = QPushButton("↻", self)
        self.badge.setFixedSize(BADGE_SIZE, BADGE_SIZE)
        self.badge.setCursor(Qt.PointingHandCursor)
        self.badge.setFont(QFont('Arial', 15))
        # Its own stylesheet: the launcher theme styles every QPushButton,
        # and a child of a button would otherwise look like a second tile.
        self.badge.setStyleSheet("""
            QPushButton {
                background-color: rgba(24, 24, 24, 200);
                color: #ffffff;
                border: 1px solid #8a8a8a;
                border-radius: %dpx;
                padding: 0px;
                min-width: 0px;
            }
            QPushButton:hover { background-color: rgba(90, 90, 90, 230); }
        """ % (BADGE_SIZE // 2))
        self.badge.move(size - BADGE_SIZE - BADGE_INSET, BADGE_INSET)
        self.badge.clicked.connect(self.flip)
        self.badge.raise_()

    # -- faces -----------------------------------------------------------

    def current(self):
        return self.faces[self.face]

    def set_face(self, index, remember=False):
        """Show a face at once, with no animation."""
        self.face = index % len(self.faces)
        self._target = self.face
        self._flip = 0.0
        self._show_face()
        self._draw(1.0)
        self._fade.setOpacity(1.0)
        if remember:
            self.launcher.remember_face(self.key, self.face)

    def _next_allowed(self):
        """The face after this one, among those the radio can run."""
        if len(self.allowed) < 2:
            return self.face
        here = (self.allowed.index(self.face) if self.face in self.allowed
                else -1)
        return self.allowed[(here + 1) % len(self.allowed)]

    def _show_face(self):
        name = self.current()[0]
        self.text_label.setText(name)
        if not self.usable:
            return
        if self.badge is not None and len(self.allowed) > 1:
            nxt = self.faces[self._next_allowed()][0]
            self.badge.setToolTip(f"Flip to {nxt}")
            self.setToolTip(f"{name} - the badge flips to {nxt}")
        else:
            self.setToolTip(name)

    def flip(self, remember=True):
        """Turn to the next face the radio can run."""
        if (len(self.allowed) < 2
                or self.animation.state() == QPropertyAnimation.Running):
            return
        self.turn_to(self._next_allowed(), remember=remember)

    def turn_to(self, index, remember=True):
        """Animate round to a particular face."""
        if index == self.face or self.animation.state() == QPropertyAnimation.Running:
            return
        self._target = index
        self._remember_turn = remember
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.start()

    # -- following the radio ---------------------------------------------

    def set_directions(self, directions, radio_type, animate=True):
        """Arrange the tile around what the selected radio can do.

        A tile whose only app the radio cannot run is dimmed and refuses
        clicks, and says why: a greyed-out square that explains itself beats
        an app that opens and then fails on a device it was never going to
        be able to use. A tile with one usable face loses its badge - there
        is nothing to flip to. Only a tile with two usable faces stays
        flippable, which on a HackRF is all of them.

        The *saved* face is left alone throughout. Switching to a BB60D and
        back to a HackRF puts every tile back the way it was, because the
        turns a radio forces are deliberately not remembered.
        """
        self.allowed = [i for i, face in enumerate(self.faces)
                        if face[3] in directions]
        self.usable = bool(self.allowed)
        self.setEnabled(self.usable)

        if not self.usable:
            wants = DIRECTION_WORDS.get(self.faces[0][3], self.faces[0][3])
            radio = RADIO_NAMES.get(radio_type, 'The selected radio')
            self.setToolTip(f"{self.faces[0][0]} needs a radio that can "
                            f"{wants}. {radio} cannot.")
            if self.badge is not None:
                self.badge.setVisible(False)
            self._show_face()
            self._draw(1.0)
            return

        if self.badge is not None:
            self.badge.setVisible(len(self.allowed) > 1)

        # Prefer whichever side was last left showing, if this radio can
        # run it; otherwise the only one it can.
        want = self.launcher.saved_face(self.key, len(self.faces))
        if want not in self.allowed:
            want = self.allowed[0]
        if want != self.face:
            if animate:
                self.turn_to(want, remember=False)
            else:
                self.set_face(want)
        else:
            self._show_face()
            self._draw(1.0)

    # -- the turn --------------------------------------------------------

    def _get_flip(self):
        return self._flip

    def _set_flip(self, value):
        self._flip = float(value)
        # 1 at the start, 0 edge on, -1 fully round: the sign is what says
        # which face should be showing.
        squeeze = math.cos(math.pi * self._flip)
        if squeeze < 0 and self.face != self._target:
            self.face = self._target
            self._show_face()
            # A turn the radio forced is not a preference, so it is not
            # saved: put a two-way radio back and the tile returns to
            # whichever side the user actually chose.
            if self._remember_turn:
                self.launcher.remember_face(self.key, self.face)
        self._draw(abs(squeeze))
        self._fade.setOpacity(abs(squeeze))

    # Named for what it is - how far through the turn - and not ``flip``,
    # which is the method that starts one. QPropertyAnimation looks the
    # property up by this attribute name.
    flip_phase = pyqtProperty(float, _get_flip, _set_flip)

    def _draw(self, width_fraction):
        """Paint the current icon squeezed to a fraction of its width."""
        base = self._pixmaps[self.face]
        target = QPixmap(self._box)
        target.fill(Qt.transparent)
        width = max(1, int(round(base.width() * width_fraction)))
        painter = QPainter(target)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        # Dimmed here rather than with a QGraphicsOpacityEffect on the tile,
        # because the caption already carries one and effects do not nest
        # predictably.
        if not self.usable:
            painter.setOpacity(0.25)
        painter.drawPixmap((self._box.width() - width) // 2,
                           (self._box.height() - base.height()) // 2,
                           base.scaled(width, base.height(),
                                       Qt.IgnoreAspectRatio,
                                       Qt.SmoothTransformation))
        painter.end()
        self.icon_label.setPixmap(target)

    def _launch(self):
        self.launcher.launch_application(self.current()[1])


class GNURadioLauncher(QMainWindow):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app  # Store reference to QApplication
        self.setWindowTitle("GNU Radio Applications Launcher")
        self.setMinimumSize(800, 600)
        
        # Create config directory if it doesn't exist
        self.config_dir = "config"
        self.settings_file = os.path.join(self.config_dir, "window_settings.json")
        os.makedirs(self.config_dir, exist_ok=True)
        
        # Create main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        grid = QGridLayout(main_widget)
        
        # Add settings button in top right with transparent background
        settings_btn = QPushButton()
        icon_path = "icons/settings.png"
        
        # Process image with PIL
        img = Image.open(icon_path)
        img = img.convert("RGBA")
        
        # Add brightness enhancement
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(1.1)  # Adjust this value to make it brighter/darker
        
        # Knock the light background out of the icon: a pixel whose R, G and B
        # are all at or above the threshold becomes fully transparent.
        # numpy rather than getdata()/putdata() - Pillow 12 deprecates those and
        # 14 removes them, and Windows solves to a newer Pillow than Linux does,
        # so the loop warned there and not here.
        threshold = 100
        arr = np.asarray(img).copy()
        light = (arr[:, :, :3] >= threshold).all(axis=2)
        arr[light] = (255, 255, 255, 0)
        img = Image.fromarray(arr, "RGBA")
        
        # Convert PIL image to QPixmap
        buffer = io.BytesIO()
        img.save(buffer, "PNG")
        buffer.seek(0)
        pixmap = QPixmap()
        pixmap.loadFromData(buffer.getvalue())
        
        icon = QIcon(pixmap)
        settings_btn.setIcon(icon)
        settings_btn.setFixedSize(40, 40)
        settings_btn.setIconSize(QSize(40, 40))
        settings_btn.clicked.connect(self.show_settings)
        grid.addWidget(settings_btn, 0, 4, Qt.AlignRight | Qt.AlignTop)
        
        # Add title
        title = QLabel("GNU Radio Applications")
        title.setFont(QFont('Arial', 20))
        title.setAlignment(Qt.AlignCenter)
        grid.addWidget(title, 0, 0, 1, 3)
        
        # Add application buttons, from the table at the top of this file.
        self.tiles = {}
        for row, col, faces in APP_TILES:
            self.create_tile(faces, grid, row, col)
        # Arrange them around whichever radio is selected. No animation on
        # the way up - there is nothing to show a turn away from yet.
        self.apply_radio_directions(animate=False)

        # Apply stylesheet
        apply_launcher_theme(self)
        
        # Load last position or center if none exists
        self.load_window_position()
        
    def center_window(self):
        """Center the window on the screen and save position"""
        # Get the screen geometry
        screen = self.app.primaryScreen().geometry()
        # Calculate center position
        window_geometry = self.frameGeometry()
        center_point = screen.center()
        window_geometry.moveCenter(center_point)
        self.move(window_geometry.topLeft())
        
        # Save position to config file
        self.save_window_position()
        
    def save_window_position(self):
        """Save the current window position and size to settings file"""
        try:
            # Load existing settings
            settings = {}
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r') as f:
                    settings = json.load(f)
            
            # Update window position and size
            settings['window_position'] = {
                'x': self.pos().x(),
                'y': self.pos().y(),
                'width': self.width(),
                'height': self.height()
            }

            
            # Save updated settings
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f, indent=4)
        except Exception as e:
            print(f"Error saving window position: {e}")
            
    def load_window_position(self):
        """Load the saved window position and size from settings file or center if none exists"""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r') as f:
                    settings = json.load(f)
                    if 'window_position' in settings:
                        position = settings['window_position']
                        screen = self.app.primaryScreen().availableGeometry()

                        # Size first, so the reachability test and the move both
                        # work on the geometry the window will actually have.
                        if 'width' in position and 'height' in position:
                            width = min(max(position['width'], 800), screen.width())
                            height = min(max(position['height'], 600), screen.height())
                            self.resize(width, height)

                        if geometry_is_reachable(self.app, position):
                            self.move(QPoint(position['x'], position['y']))
                        else:
                            self.center_window()
                    else:
                        self.center_window()
            else:
                self.center_window()
        except Exception as e:
            print(f"Error loading window position: {e}")
            self.center_window()

    def create_tile(self, faces, grid, row, col):
        """Put one tile in the grid. Two or more faces makes it a flip tile."""
        tile = FlipTile(self, faces)
        self.tiles[tile.key] = tile
        grid.addWidget(tile, row, col, Qt.AlignCenter)
        return tile

    def create_app_button(self, name, module_name, icon_name, grid, row, col):
        """One app, one tile - the single-face case of ``create_tile``."""
        return self.create_tile([(name, module_name, icon_name)],
                                grid, row, col)

    # ------------------------------------------------- following the radio
    def apply_radio_directions(self, animate=True):
        """Turn every tile to a side the selected radio can actually run.

        Called on startup and again whenever Settings closes, so choosing
        the VSG60 turns the grid to transmit and the BB60D turns it to
        receive, in front of you. A HackRF or USRP allows both and leaves
        the tiles as the user left them.
        """
        radio_type = read_settings().get('radio_type', 'hackrf')
        directions = RADIO_DIRECTIONS.get(radio_type, {'tx', 'rx'})
        for tile in self.tiles.values():
            tile.set_directions(directions, radio_type, animate=animate)
        return radio_type

    # ---------------------------------------------------------- flip state
    def saved_face(self, key, count):
        """Which side of a tile was showing when the launcher last closed."""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r') as f:
                    faces = json.load(f).get('tile_faces', {})
                return int(faces.get(key, 0)) % max(count, 1)
        except Exception as e:
            print(f"Error loading tile faces: {e}")
        return 0

    def remember_face(self, key, index):
        try:
            settings = {}
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r') as f:
                    settings = json.load(f)
            settings.setdefault('tile_faces', {})[key] = int(index)
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f, indent=4)
        except Exception as e:
            print(f"Error saving tile face: {e}")

    def launch_application(self, module_name):
        try:
            # The grid already dims what the radio cannot run, so this is
            # the backstop for anything that reaches here another way.
            radio_type = read_settings().get('radio_type', 'hackrf')
            directions = RADIO_DIRECTIONS.get(radio_type, {'tx', 'rx'})
            wanted = face_directions().get(module_name)
            if wanted is not None and wanted not in directions:
                radio = RADIO_NAMES.get(radio_type, 'The selected radio')
                word = DIRECTION_WORDS.get(wanted, wanted)
                QMessageBox.warning(
                    self, f"This Radio Cannot {word.capitalize()}",
                    f"{radio} cannot {word}, so it cannot run this "
                    f"application.\n\nChoose a different radio in Settings "
                    f"(the gear icon), or use a tile that this one can run."
                )
                return

            # Import the module
            module_path = os.path.join('apps', f"{module_name}.py")
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # Create configuration dialog (no need to pass parameters)
            config_dialog = module.ConfigDialog()
            
            # Load saved dialog position/size from per-app config file
            app_config_file = os.path.join(self.config_dir, f"{module_name}_config.json")
            screen = self.app.primaryScreen().geometry()
            default_pos = self.pos() + QPoint(50, 50)

            try:
                if os.path.exists(app_config_file):
                    with open(app_config_file, 'r') as f:
                        app_config = json.load(f)
                    position = app_config.get('dialog_position')
                    if position:
                        if geometry_is_reachable(self.app, position):
                            # Size first: moving then resizing can push the
                            # dialog somewhere the saved position never meant.
                            if 'width' in position and 'height' in position:
                                config_dialog.resize(position['width'], position['height'])
                            config_dialog.move(QPoint(position['x'], position['y']))
                        else:
                            config_dialog.move(default_pos)
                    else:
                        config_dialog.move(default_pos)
                else:
                    config_dialog.move(default_pos)
            except Exception as e:
                print(f"Error loading dialog position: {e}")
                config_dialog.move(default_pos)

            # Track geometry before the dialog is hidden (covers OK, Cancel, and window close)
            tracker = DialogGeometryTracker(config_dialog)

            # Show dialog and wait for user response
            result = config_dialog.exec_()

            # Save dialog position/size to per-app config file
            try:
                app_config = {}
                if os.path.exists(app_config_file):
                    with open(app_config_file, 'r') as f:
                        app_config = json.load(f)
                pos = tracker.captured or {
                    'x': config_dialog.pos().x(),
                    'y': config_dialog.pos().y(),
                    'width': config_dialog.width(),
                    'height': config_dialog.height(),
                }
                app_config['dialog_position'] = pos
                with open(app_config_file, 'w') as f:
                    json.dump(app_config, f, indent=4)
            except Exception as e:
                print(f"Error saving dialog position: {e}")

            if result == QDialog.Accepted:
                config_values = config_dialog.get_values()

                # Validate HackRF is present before launching
                if config_values.get('radio_type') == 'hackrf':
                    try:
                        import SoapySDR
                        devices = SoapySDR.Device.enumerate({'driver': 'hackrf'})
                        if not devices:
                            raise RuntimeError("no hackrf device found")
                    except Exception:
                        QMessageBox.warning(
                            self, "HackRF Not Found",
                            "No HackRF One was detected on USB.\n\n"
                            "Please connect your HackRF One and try again, "
                            "or change the radio type to USRP in Settings."
                        )
                        return

                # Validate the Signal Hound BB60D is present before launching
                elif config_values.get('radio_type') == 'bb60':
                    from apps.bb60_source import (find_devices as find_bb60,
                                                  is_available as bb60_software)
                    if not bb60_software():
                        QMessageBox.warning(
                            self, "Signal Hound BB60D Software Not Found",
                            "The SoapySDR module for the BB60D could not be "
                            "found, so it cannot be used on this machine.\n\n"
                            "It is a system module - normally "
                            "/usr/local/lib/SoapySDR/modules0.8/"
                            "libSignalHoundBB60.so - and is not part of this "
                            "conda environment."
                        )
                        return
                    if not find_bb60():
                        QMessageBox.warning(
                            self, "Signal Hound BB60D Not Found",
                            "No Signal Hound BB60D was detected on USB.\n\n"
                            "Check it is connected, and that no other "
                            "application already has it open."
                        )
                        return

                # Validate the Signal Hound VSG is present before launching
                elif config_values.get('radio_type') == 'vsg':
                    try:
                        from apps.vsg_sink import (find_devices, in_use, is_available,
                                                   library_error)
                        # A missing vendor library is a software install
                        # problem, not an absent device - reporting it as
                        # "not detected on USB" sends people to check cables.
                        if not is_available():
                            QMessageBox.warning(
                                self, "Signal Hound VSG Software Not Found",
                                "The Signal Hound VSG API library could not be "
                                "loaded, so the VSG60 cannot be used on this "
                                f"machine.\n\n{library_error()}"
                            )
                            return
                        if not find_devices():
                            raise RuntimeError("no VSG device found on USB")
                        # The vendor library aborts the process on a second
                        # open, so refuse before we get anywhere near it.
                        if in_use():
                            QMessageBox.warning(
                                self, "Signal Hound VSG In Use",
                                "The Signal Hound VSG60 is already being used "
                                "by another running flowgraph.\n\n"
                                "Close that application first - opening the VSG "
                                "twice crashes both and can leave the device "
                                "needing a USB reset."
                            )
                            return
                    except Exception as e:
                        QMessageBox.warning(
                            self, "Signal Hound VSG Not Found",
                            "No Signal Hound VSG60 was detected on USB.\n\n"
                            f"{e}\n\n"
                            "Please connect your VSG60 and try again, "
                            "or change the radio type in Settings."
                        )
                        return

                # Load radio mode setting
                radio_mode = 'single'
                try:
                    if os.path.exists(self.settings_file):
                        with open(self.settings_file, 'r') as f:
                            settings = json.load(f)
                            radio_mode = settings.get('radio_mode', 'single')
                except Exception as e:
                    print(f"Error loading radio mode setting: {e}")

                # Only hide launcher in single mode
                if radio_mode == 'single':
                    self.save_window_position()
                    self.hide()
                
                # Start the GNU Radio application
                tb = module.main(app=self.app, config_values=config_values)
                
                # Modify close event only in single mode
                if radio_mode == 'single' and hasattr(tb, 'closeEvent'):
                    original_close_event = tb.closeEvent
                    def new_close_event(event):
                        original_close_event(event)
                        self.load_window_position()
                        self.show()
                    tb.closeEvent = new_close_event

        except Exception as e:
            error_dialog = QMessageBox()
            if 'vsg' in str(e).lower() or 'signal hound' in str(e).lower():
                error_dialog.setIcon(QMessageBox.Warning)
                error_dialog.setWindowTitle("Signal Hound VSG Not Found")
                error_dialog.setText("Signal Hound VSG60 not detected on USB.")
                error_dialog.setInformativeText(
                    "Please connect your VSG60 and try again, "
                    "or change the radio type in Settings."
                )
            elif 'hackrf' in str(e).lower():
                error_dialog.setIcon(QMessageBox.Warning)
                error_dialog.setWindowTitle("HackRF Not Found")
                error_dialog.setText("HackRF One not detected on USB.")
                error_dialog.setInformativeText(
                    "Please connect your HackRF One and try again, "
                    "or change the radio type to USRP in Settings."
                )
            else:
                error_dialog.setIcon(QMessageBox.Critical)
                error_dialog.setWindowTitle("Error")
                error_dialog.setText(f"Error launching {module_name}")
                error_dialog.setInformativeText(str(e))
            error_dialog.exec_()

    def show_settings(self):
        settings_dialog = SettingsDialog(self.settings_file, parent=self)
        apply_dark_theme(settings_dialog)
        tracker = DialogGeometryTracker(settings_dialog)
        settings_dialog.exec_()
        # The radio may have changed, which changes what every tile can do.
        self.apply_radio_directions()
        if tracker.captured:
            try:
                existing = {}
                if os.path.exists(self.settings_file):
                    with open(self.settings_file, 'r') as f:
                        existing = json.load(f)
                existing['settings_dialog_position'] = tracker.captured
                with open(self.settings_file, 'w') as f:
                    json.dump(existing, f, indent=4)
            except Exception as e:
                print(f"Error saving settings dialog geometry: {e}")

    def closeEvent(self, event):
        """Save window position when closing the application"""
        self.save_window_position()
        super().closeEvent(event)

if __name__ == '__main__':
    # Enable high DPI scaling for 4K displays
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    
    launcher = GNURadioLauncher(app)
    launcher.show()
    sys.exit(app.exec_())