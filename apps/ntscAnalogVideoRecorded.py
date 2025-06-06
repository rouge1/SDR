#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#
# SPDX-License-Identifier: GPL-3.0
#
# GNU Radio Python Flow Graph
# Title: NTSC Analog Video - Recorded
# Author: student
# GNU Radio version: 3.10.1.1

from packaging.version import Version as StrictVersion # type: ignore

if __name__ == '__main__':
    import ctypes
    import sys
    if sys.platform.startswith('linux'):
        try:
            x11 = ctypes.cdll.LoadLibrary('libX11.so')
            x11.XInitThreads()
        except:
            print("Warning: failed to XInitThreads()")

# Standard library imports
import json
import os
import signal
import sys
import time
from math import pi

# Third party imports
from gnuradio import analog #type: ignore
from gnuradio import blocks #type: ignore
from gnuradio import filter #type: ignore
from gnuradio import gr #type: ignore
from gnuradio import qtgui #type: ignore
from gnuradio import uhd #type: ignore
from gnuradio.fft import window #type: ignore
from gnuradio.filter import firdes #type: ignore
from gnuradio.qtgui import Range, RangeWidget #type: ignore
import pmt #type: ignore
from PyQt5 import Qt, QtCore #type: ignore
from PyQt5.QtCore import pyqtSlot #type: ignore
import sip #type: ignore

# Local imports 
from apps.utils import apply_dark_theme, read_settings

class ConfigDialog(Qt.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("NTSC Analog Video Configuration")
        self.layout = Qt.QVBoxLayout(self)
        self.config_dir = "config"
        self.config_file = os.path.join(self.config_dir, "ntscAnalogVideoRecorded_config.json")
        
        # Read settings from window_settings.json
        settings = read_settings()
        self.ipList = settings['ip_addresses']
        self.media_dir = settings['media_directory']
        self.N = len(self.ipList)
        
        # Add OK/Cancel buttons
        self.button_box = Qt.QDialogButtonBox(
            Qt.QDialogButtonBox.Ok | Qt.QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        
        # Create all controls
        self.create_usrp_selector()
        self.create_frequency_control()
        self.create_power_control()
        self.create_video_selector()
        self.create_video_invert_control() 
        self.create_audio_controls()
        
        self.layout.addWidget(self.button_box)
        
        # Load saved configuration
        self.load_config()
        
        # Apply dark theme
        apply_dark_theme(self)

    def create_usrp_selector(self):
        self.usrp_combo = Qt.QComboBox()
        ok_button = self.button_box.button(Qt.QDialogButtonBox.Ok)
        
        if not self.ipList:  # If list is empty
            self.usrp_combo.addItem("IP addr missing - Go to Settings")
            ok_button.setEnabled(False)  # Disable the OK button
            
            # Add opacity effect to dim the button
            opacity_effect = Qt.QGraphicsOpacityEffect()
            opacity_effect.setOpacity(0.30)  # 30% opacity
            ok_button.setGraphicsEffect(opacity_effect)
        else:
            for i in range(self.N):
                self.usrp_combo.addItem(f"USRP {i+1} ({self.ipList[i].strip()})")
            ok_button.setEnabled(True)
            # Clear any existing opacity effect
            ok_button.setGraphicsEffect(None)
                    
        self.layout.addWidget(Qt.QLabel("Select USRP:"))
        self.layout.addWidget(self.usrp_combo)

    def create_frequency_control(self):
        self.cf_layout = Qt.QHBoxLayout()
        self.cf_slider = Qt.QSlider(QtCore.Qt.Horizontal)
        self.cf_slider.setMinimum(50)
        self.cf_slider.setMaximum(2200)
        self.cf_slider.setValue(300)
        self.cf_label = Qt.QLabel("Center Frequency: 300 MHz")
        self.cf_slider.valueChanged.connect(
            lambda v: self.cf_label.setText(f"Center Frequency: {v} MHz"))
        self.cf_layout.addWidget(self.cf_label)
        self.cf_layout.addWidget(self.cf_slider)
        self.layout.addLayout(self.cf_layout)

    def create_power_control(self):
        self.pwr_layout = Qt.QHBoxLayout()
        self.pwr_slider = Qt.QSlider(QtCore.Qt.Horizontal)
        self.pwr_slider.setMinimum(-80)
        self.pwr_slider.setMaximum(-30)
        self.pwr_slider.setValue(-50)
        self.pwr_label = Qt.QLabel("Power Level: -50 dBm")
        self.pwr_slider.valueChanged.connect(
            lambda v: self.pwr_label.setText(f"Power Level: {v} dBm"))
        self.pwr_layout.addWidget(self.pwr_label)
        self.pwr_layout.addWidget(self.pwr_slider)
        self.layout.addLayout(self.pwr_layout)

    def create_video_selector(self):
        self.video_combo = Qt.QComboBox()
        ok_button = self.button_box.button(Qt.QDialogButtonBox.Ok)
        
        # Read settings from window_settings.json
        settings = read_settings()
        self.media_dir = settings.get('media_directory', '')
        
        try:
            if not self.media_dir or not os.path.exists(self.media_dir):
                raise FileNotFoundError("Error - Setup Media directory in Settings")
                
            # Search for .dat files in media directory
            self.video_files = []
            for file in os.listdir(self.media_dir):
                if file.endswith('.dat'):
                    full_path = os.path.join(self.media_dir, file)
                    display_name = os.path.splitext(file)[0].replace('-', ' ')
                    self.video_files.append((display_name, file))
                    
            if not self.video_files:
                raise FileNotFoundError("No video files found in media directory")
                
            # Sort video files alphabetically by display name
            self.video_files.sort()
            
            for display_name, filename in self.video_files:
                full_path = os.path.join(self.media_dir, filename)
                self.video_combo.addItem(display_name, full_path)
                
            # Only enable OK button if we have both IP addresses and video files
            ok_button.setEnabled(bool(self.ipList))
            ok_button.setGraphicsEffect(None)
                
        except Exception as e:
            self.video_combo.addItem(str(e))
            self.video_combo.setEnabled(False)
            # Disable OK button and add opacity effect
            ok_button.setEnabled(False)
            opacity_effect = Qt.QGraphicsOpacityEffect()
            opacity_effect.setOpacity(0.30)
            ok_button.setGraphicsEffect(opacity_effect)
                
        self.layout.addWidget(Qt.QLabel("Video Source:"))
        self.layout.addWidget(self.video_combo)

    def create_video_invert_control(self):
        # Video Inversion control
        self.video_invert = Qt.QCheckBox("Invert Video")
        self.video_invert.setChecked(False)  # Default to normal
        self.layout.addWidget(self.video_invert)

    def create_audio_controls(self):
        self.audio_combo = Qt.QComboBox()
        self.layout.addWidget(Qt.QLabel("Audio File:"))
        
        # Check if media directory exists
        if not os.path.exists(self.media_dir):
            self.audio_combo.addItem("Error - Setup Media directory in Settings")
            self.audio_paths = [os.path.join(self.media_dir, "default.wav")]
            self.audio_combo.setEnabled(False)
        else:
            # Scan media directory for .wav files
            audio_files = sorted([f for f in os.listdir(self.media_dir) if f.endswith('.wav')])
            if audio_files:
                # Create display names by cleaning up filenames
                audio_names = [os.path.splitext(f)[0].replace('-', ' ') for f in audio_files]
                self.audio_paths = [os.path.join(self.media_dir, f) for f in audio_files]
                self.audio_combo.addItems(audio_names)
            else:
                self.audio_combo.addItem("No audio files found")
                self.audio_paths = [os.path.join(self.media_dir, "default.wav")]
                self.audio_combo.setEnabled(False)
                
        self.layout.addWidget(self.audio_combo)

    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    
                self.usrp_combo.setCurrentIndex(config.get('usrp_index', 0))
                self.cf_slider.setValue(config.get('center_freq', 300))
                self.pwr_slider.setValue(config.get('power_level', -50))
                video_index = config.get('video_index', 0)
                if video_index < self.video_combo.count():
                    self.video_combo.setCurrentIndex(video_index)
                audio_index = config.get('audio_index', 0)
                if audio_index < self.audio_combo.count():
                    self.audio_combo.setCurrentIndex(audio_index)
                self.video_invert.setChecked(config.get('video_invert', False))
            except:
                # If loading fails, keep default values
                pass
        else:
            # Create config directory if it doesn't exist
            os.makedirs(self.config_dir, exist_ok=True)

    def save_config(self):
        # Get the filename (not full path) of selected video
        current_index = self.video_combo.currentIndex()
        video_filename = None
        if current_index >= 0 and current_index < len(self.video_files):
            _, video_filename = self.video_files[current_index]
        
        config = {
            'usrp_index': self.usrp_combo.currentIndex(),
            'center_freq': self.cf_slider.value(),
            'power_level': self.pwr_slider.value(),
            'video_index': self.video_combo.currentIndex(),
            'audio_index': self.audio_combo.currentIndex(),
            'video_invert': self.video_invert.isChecked()
        }
        
        with open(self.config_file, 'w') as f:
            json.dump(config, f, indent=4)

    def accept(self):
        self.save_config()
        super().accept()

    def get_values(self):
        ipNum = self.usrp_combo.currentIndex() + 1
        ipXmitAddr = self.ipList[self.usrp_combo.currentIndex()].strip()
        
        # Get full path from current media directory
        current_video_path = self.video_combo.currentData()
        
        return {
            'ipNum': ipNum,
            'ipXmitAddr': ipXmitAddr,
            'mikePort': 2020 + ipNum,
            'cf': self.cf_slider.value(),
            'pwr': self.pwr_slider.value(),
            'videoFileName': current_video_path,
            'audioFileName': self.audio_paths[self.audio_combo.currentIndex()],
            'videoInvert': -1 if self.video_invert.isChecked() else 1  # Modified to match expected values
        }

class ntscAnalogVideoRecorded(gr.top_block, Qt.QWidget):

    def __init__(self, config_values=None):
        gr.top_block.__init__(self, "NTSC Analog Video - Recorded", catch_exceptions=True)
        Qt.QWidget.__init__(self)
        self.setWindowTitle("NTSC Analog Video - Recorded")
        qtgui.util.check_set_qss()
        try:
            self.setWindowIcon(Qt.QIcon.fromTheme('gnuradio-grc'))
        except:
            pass
        self.top_scroll_layout = Qt.QVBoxLayout()
        self.setLayout(self.top_scroll_layout)
        self.top_scroll = Qt.QScrollArea()
        self.top_scroll.setFrameStyle(Qt.QFrame.NoFrame)
        self.top_scroll_layout.addWidget(self.top_scroll)
        self.top_scroll.setWidgetResizable(True)
        self.top_widget = Qt.QWidget()
        self.top_scroll.setWidget(self.top_widget)
        self.top_layout = Qt.QVBoxLayout(self.top_widget)
        self.top_grid_layout = Qt.QGridLayout()
        self.top_layout.addLayout(self.top_grid_layout)

        self.settings = Qt.QSettings("GNU Radio", "ntscAnalogVideoRecorded")

        try:
            if StrictVersion(Qt.qVersion()) < StrictVersion("5.0.0"):
                self.restoreGeometry(self.settings.value("geometry").toByteArray())
            else:
                self.restoreGeometry(self.settings.value("geometry"))
        except:
            pass

        # Use provided config values or get them from dialog
        if config_values is None:
            config_dialog = ConfigDialog()
            if not config_dialog.exec_():
                sys.exit(0)
            values = config_dialog.get_values()
        else:
            values = config_values

        # Assign configuration values
        ipNum = values['ipNum']
        ipXmitAddr = values['ipXmitAddr']
        mikePort = values['mikePort']
        cf = values['cf']
        pwr = values['pwr']
        videoFileName = values['videoFileName']
        audioFileName = values['audioFileName']
        videoInvert = values['videoInvert']

        ##################################################
        # Variables
        ##################################################
        self.rfPwrDefault = rfPwrDefault = pwr
        self.cfDefault = cfDefault = cf
        self.videoInvert = videoInvert
        self.videoFileName = videoFileName
        self.usrpNum = usrpNum = ipNum
        self.signalType = signalType = 'NTSC Video - Recorded'
        self.samp_rate = samp_rate = 10e6
        self.rfPwr = rfPwr = rfPwrDefault
        self.outputIpAddr = outputIpAddr = ipXmitAddr
        self.cf = cf = cfDefault
        self.audioFileName = audioFileName

        ##################################################
        # Blocks
        ##################################################
        # Create the options list
        self._videoInvert_options = [-1, 1]
        # Create the labels list
        self._videoInvert_labels = ['Normal', 'Inverted']
        # Create the combo box
        # Create the radio buttons
        self._videoInvert_group_box = Qt.QGroupBox("Video Inversion" + ": ")
        self._videoInvert_box = Qt.QHBoxLayout()
        class variable_chooser_button_group(Qt.QButtonGroup):
            def __init__(self, parent=None):
                Qt.QButtonGroup.__init__(self, parent)
            @pyqtSlot(int)
            def updateButtonChecked(self, button_id):
                self.button(button_id).setChecked(True)
        self._videoInvert_button_group = variable_chooser_button_group()
        self._videoInvert_group_box.setLayout(self._videoInvert_box)
        for i, _label in enumerate(self._videoInvert_labels):
            radio_button = Qt.QRadioButton(_label)
            self._videoInvert_box.addWidget(radio_button)
            self._videoInvert_button_group.addButton(radio_button, i)
        self._videoInvert_callback = lambda i: Qt.QMetaObject.invokeMethod(self._videoInvert_button_group, "updateButtonChecked", Qt.Q_ARG("int", self._videoInvert_options.index(i)))
        self._videoInvert_callback(self.videoInvert)
        self._videoInvert_button_group.buttonClicked[int].connect(
            lambda i: self.set_videoInvert(self._videoInvert_options[i]))
        self.top_grid_layout.addWidget(self._videoInvert_group_box, 1, 5, 1, 5)
        for r in range(1, 2):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(5, 10):
            self.top_grid_layout.setColumnStretch(c, 1)
        self._rfPwr_range = Range(-140, -30, 1, rfPwrDefault, 200)
        self._rfPwr_win = RangeWidget(self._rfPwr_range, self.set_rfPwr, "RF Output Power", "counter_slider", float, QtCore.Qt.Horizontal)
        self.top_grid_layout.addWidget(self._rfPwr_win, 1, 0, 1, 5)
        for r in range(1, 2):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(0, 5):
            self.top_grid_layout.setColumnStretch(c, 1)
        self._cf_range = Range(50, 2200, 0.001, cfDefault, 200)
        self._cf_win = RangeWidget(self._cf_range, self.set_cf, "Center Frequency (MHz)", "counter", float, QtCore.Qt.Horizontal)
        self.top_grid_layout.addWidget(self._cf_win, 0, 5, 1, 5)
        for r in range(0, 1):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(5, 10):
            self.top_grid_layout.setColumnStretch(c, 1)
        self._usrpNum_tool_bar = Qt.QToolBar(self)

        if None:
            self._usrpNum_formatter = None
        else:
            self._usrpNum_formatter = lambda x: str(x)

        self._usrpNum_tool_bar.addWidget(Qt.QLabel("USRP # "))
        self._usrpNum_label = Qt.QLabel(str(self._usrpNum_formatter(self.usrpNum)))
        self._usrpNum_tool_bar.addWidget(self._usrpNum_label)
        self.top_grid_layout.addWidget(self._usrpNum_tool_bar, 0, 0, 1, 1)
        for r in range(0, 1):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(0, 1):
            self.top_grid_layout.setColumnStretch(c, 1)
        self.uhd_usrp_sink_0 = uhd.usrp_sink(
            ",".join(('addr='+outputIpAddr, '')),
            uhd.stream_args(
                cpu_format="fc32",
                args='',
                channels=list(range(0,1)),
            ),
            "",
        )
        self.uhd_usrp_sink_0.set_samp_rate(samp_rate*2)
        self.uhd_usrp_sink_0.set_time_now(uhd.time_spec(time.time()), uhd.ALL_MBOARDS)

        self.uhd_usrp_sink_0.set_center_freq(cf*1e6+6e6, 0)
        self.uhd_usrp_sink_0.set_antenna("TX/RX", 0)
        self.uhd_usrp_sink_0.set_gain((rfPwr+50)*(rfPwr>-50), 0)
        self._signalType_tool_bar = Qt.QToolBar(self)

        if None:
            self._signalType_formatter = None
        else:
            self._signalType_formatter = lambda x: str(x)

        self._signalType_tool_bar.addWidget(Qt.QLabel("Signal Type: "))
        self._signalType_label = Qt.QLabel(str(self._signalType_formatter(self.signalType)))
        self._signalType_tool_bar.addWidget(self._signalType_label)
        self.top_grid_layout.addWidget(self._signalType_tool_bar, 0, 1, 1, 4)
        for r in range(0, 1):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(1, 5):
            self.top_grid_layout.setColumnStretch(c, 1)
        self.rational_resampler_xxx_2 = filter.rational_resampler_ccc(
                interpolation=2,
                decimation=1,
                taps=[],
                fractional_bw=0)
        self.rational_resampler_xxx_1 = filter.rational_resampler_fff(
                interpolation=625,
                decimation=3,
                taps=[],
                fractional_bw=0)
        self.rational_resampler_xxx_0 = filter.rational_resampler_fff(
                interpolation=9,
                decimation=10,
                taps=[],
                fractional_bw=0)
        self.qtgui_time_sink_x_0 = qtgui.time_sink_f(
            286*5, #size
            9e6, #samp_rate
            'NTSC Baseband Time Domain', #name
            1, #number of inputs
            None # parent
        )
        self.qtgui_time_sink_x_0.set_update_time(0.05)
        self.qtgui_time_sink_x_0.set_y_axis(-1, 1)

        self.qtgui_time_sink_x_0.set_y_label('Amplitude', "")

        self.qtgui_time_sink_x_0.enable_tags(True)
        self.qtgui_time_sink_x_0.set_trigger_mode(qtgui.TRIG_MODE_FREE, qtgui.TRIG_SLOPE_POS, 0.0, 0, 0, "")
        self.qtgui_time_sink_x_0.enable_autoscale(False)
        self.qtgui_time_sink_x_0.enable_grid(True)
        self.qtgui_time_sink_x_0.enable_axis_labels(True)
        self.qtgui_time_sink_x_0.enable_control_panel(False)
        self.qtgui_time_sink_x_0.enable_stem_plot(False)

        self.qtgui_time_sink_x_0.disable_legend()

        labels = ['Signal 1', 'Signal 2', 'Signal 3', 'Signal 4', 'Signal 5',
            'Signal 6', 'Signal 7', 'Signal 8', 'Signal 9', 'Signal 10']
        widths = [1, 1, 1, 1, 1,
            1, 1, 1, 1, 1]
        colors = ['black', 'red', 'green', 'black', 'cyan',
            'magenta', 'yellow', 'dark red', 'dark green', 'dark blue']
        alphas = [1.0, 1.0, 1.0, 1.0, 1.0,
            1.0, 1.0, 1.0, 1.0, 1.0]
        styles = [1, 1, 1, 1, 1,
            1, 1, 1, 1, 1]
        markers = [-1, -1, -1, -1, -1,
            -1, -1, -1, -1, -1]


        for i in range(1):
            if len(labels[i]) == 0:
                self.qtgui_time_sink_x_0.set_line_label(i, "Data {0}".format(i))
            else:
                self.qtgui_time_sink_x_0.set_line_label(i, labels[i])
            self.qtgui_time_sink_x_0.set_line_width(i, widths[i])
            self.qtgui_time_sink_x_0.set_line_color(i, colors[i])
            self.qtgui_time_sink_x_0.set_line_style(i, styles[i])
            self.qtgui_time_sink_x_0.set_line_marker(i, markers[i])
            self.qtgui_time_sink_x_0.set_line_alpha(i, alphas[i])

        self._qtgui_time_sink_x_0_win = sip.wrapinstance(self.qtgui_time_sink_x_0.qwidget(), Qt.QWidget)
        self.top_grid_layout.addWidget(self._qtgui_time_sink_x_0_win, 2, 0, 5, 7)
        for r in range(2, 7):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(0, 7):
            self.top_grid_layout.setColumnStretch(c, 1)
        self.qtgui_freq_sink_x_0 = qtgui.freq_sink_c(
            8192, #size
            window.WIN_BLACKMAN_hARRIS, #wintype
            0, #fc
            samp_rate, #bw
            'RF Spectrum', #name
            1,
            None # parent
        )
        self.qtgui_freq_sink_x_0.set_update_time(0.10)
        self.qtgui_freq_sink_x_0.set_y_axis(-140, -10)
        self.qtgui_freq_sink_x_0.set_y_label('Relative Gain', 'dB')
        self.qtgui_freq_sink_x_0.set_trigger_mode(qtgui.TRIG_MODE_FREE, 0.0, 0, "")
        self.qtgui_freq_sink_x_0.enable_autoscale(False)
        self.qtgui_freq_sink_x_0.enable_grid(True)
        self.qtgui_freq_sink_x_0.set_fft_average(1.0)
        self.qtgui_freq_sink_x_0.enable_axis_labels(True)
        self.qtgui_freq_sink_x_0.enable_control_panel(False)
        self.qtgui_freq_sink_x_0.set_fft_window_normalized(False)

        self.qtgui_freq_sink_x_0.disable_legend()


        labels = ['', '', '', '', '',
            '', '', '', '', '']
        widths = [1, 1, 1, 1, 1,
            1, 1, 1, 1, 1]
        colors = ["black", "red", "green", "black", "cyan",
            "magenta", "yellow", "dark red", "dark green", "dark blue"]
        alphas = [1.0, 1.0, 1.0, 1.0, 1.0,
            1.0, 1.0, 1.0, 1.0, 1.0]

        for i in range(1):
            if len(labels[i]) == 0:
                self.qtgui_freq_sink_x_0.set_line_label(i, "Data {0}".format(i))
            else:
                self.qtgui_freq_sink_x_0.set_line_label(i, labels[i])
            self.qtgui_freq_sink_x_0.set_line_width(i, widths[i])
            self.qtgui_freq_sink_x_0.set_line_color(i, colors[i])
            self.qtgui_freq_sink_x_0.set_line_alpha(i, alphas[i])

        self._qtgui_freq_sink_x_0_win = sip.wrapinstance(self.qtgui_freq_sink_x_0.qwidget(), Qt.QWidget)
        self.top_grid_layout.addWidget(self._qtgui_freq_sink_x_0_win, 7, 0, 5, 10)
        for r in range(7, 12):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(0, 10):
            self.top_grid_layout.setColumnStretch(c, 1)
        self.qtgui_const_sink_x_0 = qtgui.const_sink_c(
            1250, #size
            'NTSC Video Constellation', #name
            1, #number of inputs
            None # parent
        )
        self.qtgui_const_sink_x_0.set_update_time(0.10)
        self.qtgui_const_sink_x_0.set_y_axis(-1, 1)
        self.qtgui_const_sink_x_0.set_x_axis(-1, 1)
        self.qtgui_const_sink_x_0.set_trigger_mode(qtgui.TRIG_MODE_FREE, qtgui.TRIG_SLOPE_POS, 0.0, 0, "")
        self.qtgui_const_sink_x_0.enable_autoscale(False)
        self.qtgui_const_sink_x_0.enable_grid(True)
        self.qtgui_const_sink_x_0.enable_axis_labels(True)

        self.qtgui_const_sink_x_0.disable_legend()

        labels = ['', '', '', '', '',
            '', '', '', '', '']
        widths = [1, 1, 1, 1, 1,
            1, 1, 1, 1, 1]
        colors = ["black", "red", "red", "red", "red",
            "red", "red", "red", "red", "red"]
        styles = [1, 0, 0, 0, 0,
            0, 0, 0, 0, 0]
        markers = [-1, 0, 0, 0, 0,
            0, 0, 0, 0, 0]
        alphas = [1.0, 1.0, 1.0, 1.0, 1.0,
            1.0, 1.0, 1.0, 1.0, 1.0]

        for i in range(1):
            if len(labels[i]) == 0:
                self.qtgui_const_sink_x_0.set_line_label(i, "Data {0}".format(i))
            else:
                self.qtgui_const_sink_x_0.set_line_label(i, labels[i])
            self.qtgui_const_sink_x_0.set_line_width(i, widths[i])
            self.qtgui_const_sink_x_0.set_line_color(i, colors[i])
            self.qtgui_const_sink_x_0.set_line_style(i, styles[i])
            self.qtgui_const_sink_x_0.set_line_marker(i, markers[i])
            self.qtgui_const_sink_x_0.set_line_alpha(i, alphas[i])

        self._qtgui_const_sink_x_0_win = sip.wrapinstance(self.qtgui_const_sink_x_0.qwidget(), Qt.QWidget)
        self.top_grid_layout.addWidget(self._qtgui_const_sink_x_0_win, 2, 7, 5, 3)
        for r in range(2, 7):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(7, 10):
            self.top_grid_layout.setColumnStretch(c, 1)
        self.filter_fft_low_pass_filter_0 = filter.fft_filter_ccc(1, firdes.low_pass(1, samp_rate, 2.475e6, 300e3, window.WIN_HAMMING, 6.76), 1)
        self.blocks_wavfile_source_0 = blocks.wavfile_source(audioFileName, True)
        self.blocks_null_source_0 = blocks.null_source(gr.sizeof_float*1)
        self.blocks_multiply_xx_1 = blocks.multiply_vcc(1)
        self.blocks_multiply_xx_0_0_0 = blocks.multiply_vcc(1)
        self.blocks_multiply_xx_0_0 = blocks.multiply_vcc(1)
        self.blocks_multiply_xx_0 = blocks.multiply_vcc(1)
        self.blocks_multiply_const_vxx_2 = blocks.multiply_const_cc(10**((rfPwr<=-50)*(rfPwr+50)/20)*0.95)
        self.blocks_multiply_const_vxx_1 = blocks.multiply_const_cc(0.25)
        self.blocks_multiply_const_vxx_0 = blocks.multiply_const_ff(videoInvert*0.9)
        self.blocks_float_to_complex_0 = blocks.float_to_complex(1)
        self.blocks_file_source_0 = blocks.file_source(gr.sizeof_float*1, videoFileName, True, 0, 0)
        self.blocks_file_source_0.set_begin_tag(pmt.PMT_NIL)
        self.blocks_add_xx_0 = blocks.add_vcc(1)
        self.blocks_add_const_vxx_0 = blocks.add_const_ff(1)
        self.analog_sig_source_x_1 = analog.sig_source_c(samp_rate*2, analog.GR_COS_WAVE, -6e6, 1, 0, 0)
        self.analog_sig_source_x_0_0_0 = analog.sig_source_c(samp_rate, analog.GR_COS_WAVE, 2.75e6, 0.8, 0, 0)
        self.analog_sig_source_x_0_0 = analog.sig_source_c(samp_rate, analog.GR_COS_WAVE, -25e3, 1, 0, 0)
        self.analog_sig_source_x_0 = analog.sig_source_c(samp_rate, analog.GR_COS_WAVE, -1.725e6, 1, 0, 0)
        self.analog_frequency_modulator_fc_0 = analog.frequency_modulator_fc(2*pi*25e3/samp_rate)


        ##################################################
        # Connections
        ##################################################
        self.connect((self.analog_frequency_modulator_fc_0, 0), (self.blocks_multiply_xx_0_0_0, 0))
        self.connect((self.analog_sig_source_x_0, 0), (self.blocks_multiply_xx_0, 1))
        self.connect((self.analog_sig_source_x_0_0, 0), (self.blocks_multiply_xx_0_0, 1))
        self.connect((self.analog_sig_source_x_0_0_0, 0), (self.blocks_multiply_xx_0_0_0, 1))
        self.connect((self.analog_sig_source_x_1, 0), (self.blocks_multiply_xx_1, 1))
        self.connect((self.blocks_add_const_vxx_0, 0), (self.blocks_float_to_complex_0, 0))
        self.connect((self.blocks_add_xx_0, 0), (self.blocks_multiply_const_vxx_1, 0))
        self.connect((self.blocks_file_source_0, 0), (self.blocks_multiply_const_vxx_0, 0))
        self.connect((self.blocks_float_to_complex_0, 0), (self.blocks_multiply_xx_0, 0))
        self.connect((self.blocks_multiply_const_vxx_0, 0), (self.blocks_add_const_vxx_0, 0))
        self.connect((self.blocks_multiply_const_vxx_0, 0), (self.rational_resampler_xxx_0, 0))
        self.connect((self.blocks_multiply_const_vxx_1, 0), (self.blocks_multiply_const_vxx_2, 0))
        self.connect((self.blocks_multiply_const_vxx_1, 0), (self.qtgui_const_sink_x_0, 0))
        self.connect((self.blocks_multiply_const_vxx_1, 0), (self.qtgui_freq_sink_x_0, 0))
        self.connect((self.blocks_multiply_const_vxx_2, 0), (self.rational_resampler_xxx_2, 0))
        self.connect((self.blocks_multiply_xx_0, 0), (self.filter_fft_low_pass_filter_0, 0))
        self.connect((self.blocks_multiply_xx_0_0, 0), (self.blocks_add_xx_0, 0))
        self.connect((self.blocks_multiply_xx_0_0_0, 0), (self.blocks_add_xx_0, 1))
        self.connect((self.blocks_multiply_xx_1, 0), (self.uhd_usrp_sink_0, 0))
        self.connect((self.blocks_null_source_0, 0), (self.blocks_float_to_complex_0, 1))
        self.connect((self.blocks_wavfile_source_0, 0), (self.rational_resampler_xxx_1, 0))
        self.connect((self.filter_fft_low_pass_filter_0, 0), (self.blocks_multiply_xx_0_0, 0))
        self.connect((self.rational_resampler_xxx_0, 0), (self.qtgui_time_sink_x_0, 0))
        self.connect((self.rational_resampler_xxx_1, 0), (self.analog_frequency_modulator_fc_0, 0))
        self.connect((self.rational_resampler_xxx_2, 0), (self.blocks_multiply_xx_1, 0))


    def closeEvent(self, event):
        self.settings = Qt.QSettings("GNU Radio", "ntscAnalogVideoRecorded")
        self.settings.setValue("geometry", self.saveGeometry())
        self.stop()
        self.wait()

        event.accept()

    def get_rfPwrDefault(self):
        return self.rfPwrDefault

    def set_rfPwrDefault(self, rfPwrDefault):
        self.rfPwrDefault = rfPwrDefault
        self.set_rfPwr(self.rfPwrDefault)

    def get_cfDefault(self):
        return self.cfDefault

    def set_cfDefault(self, cfDefault):
        self.cfDefault = cfDefault
        self.set_cf(self.cfDefault)

    def get_videoInvert(self):
        return self.videoInvert

    def set_videoInvert(self, videoInvert):
        self.videoInvert = videoInvert
        self._videoInvert_callback(self.videoInvert)
        self.blocks_multiply_const_vxx_0.set_k(self.videoInvert*0.9)

    def get_videoFileName(self):
        return self.videoFileName

    def set_videoFileName(self, videoFileName):
        self.videoFileName = videoFileName
        self.blocks_file_source_0.open(self.videoFileName, True)

    def get_usrpNum(self):
        return self.usrpNum

    def set_usrpNum(self, usrpNum):
        self.usrpNum = usrpNum
        Qt.QMetaObject.invokeMethod(self._usrpNum_label, "setText", Qt.Q_ARG("QString", str(self._usrpNum_formatter(self.usrpNum))))

    def get_signalType(self):
        return self.signalType

    def set_signalType(self, signalType):
        self.signalType = signalType
        Qt.QMetaObject.invokeMethod(self._signalType_label, "setText", Qt.Q_ARG("QString", str(self._signalType_formatter(self.signalType))))

    def get_samp_rate(self):
        return self.samp_rate

    def set_samp_rate(self, samp_rate):
        self.samp_rate = samp_rate
        self.analog_frequency_modulator_fc_0.set_sensitivity(2*pi*25e3/self.samp_rate)
        self.analog_sig_source_x_0.set_sampling_freq(self.samp_rate)
        self.analog_sig_source_x_0_0.set_sampling_freq(self.samp_rate)
        self.analog_sig_source_x_0_0_0.set_sampling_freq(self.samp_rate)
        self.analog_sig_source_x_1.set_sampling_freq(self.samp_rate*2)
        self.filter_fft_low_pass_filter_0.set_taps(firdes.low_pass(1, self.samp_rate, 2.475e6, 300e3, window.WIN_HAMMING, 6.76))
        self.qtgui_freq_sink_x_0.set_frequency_range(0, self.samp_rate)
        self.uhd_usrp_sink_0.set_samp_rate(self.samp_rate*2)

    def get_rfPwr(self):
        return self.rfPwr

    def set_rfPwr(self, rfPwr):
        self.rfPwr = rfPwr
        self.blocks_multiply_const_vxx_2.set_k(10**((self.rfPwr<=-50)*(self.rfPwr+50)/20)*0.95)
        self.uhd_usrp_sink_0.set_gain((self.rfPwr+50)*(self.rfPwr>-50), 0)

    def get_outputIpAddr(self):
        return self.outputIpAddr

    def set_outputIpAddr(self, outputIpAddr):
        self.outputIpAddr = outputIpAddr

    def get_cf(self):
        return self.cf

    def set_cf(self, cf):
        self.cf = cf
        self.uhd_usrp_sink_0.set_center_freq(self.cf*1e6+6e6, 0)

    def get_audioFileName(self):
        return self.audioFileName

    def set_audioFileName(self, audioFileName):
        self.audioFileName = audioFileName




def main(top_block_cls=ntscAnalogVideoRecorded, options=None, app=None, config_values=None):

    if app is None:
        if StrictVersion("4.5.0") <= StrictVersion(Qt.qVersion()) < StrictVersion("5.0.0"):
            style = gr.prefs().get_string('qtgui', 'style', 'raster')
            Qt.QApplication.setGraphicsSystem(style)
        app = Qt.QApplication(sys.argv)

    tb = top_block_cls(config_values)

    tb.start()

    tb.show()

    def sig_handler(sig=None, frame=None):
        tb.stop()
        tb.wait()
        Qt.QApplication.quit()

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    timer = Qt.QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None)

    if app.instance():
        return tb
    else:
        return app.exec_()

if __name__ == '__main__':
    main()
