#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#
# SPDX-License-Identifier: GPL-3.0
#
# GNU Radio Python Flow Graph
# Title: PPM-OOK Live Audio Xmitter
# Author: Gary Schafer
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
import glob

# Third party imports
import numpy as np # type: ignore
import sip # type: ignore
from PyQt5 import Qt, QtCore  # type: ignore
from PyQt5.QtCore import pyqtSlot # type: ignore

from gnuradio import blocks, digital, eng_notation, filter, gr, network, qtgui, uhd # type: ignore
from gnuradio.filter import firdes # type: ignore
from gnuradio.fft import window   # type: ignore
from gnuradio.qtgui import Range, RangeWidget # type: ignore

# Local imports
from apps.utils import apply_dark_theme, read_settings

def get_wav_files(settings):
    """Get list of wav files from media directory"""
    try:
        media_dir = settings.get('media_directory', '')
        if not media_dir or not os.path.exists(media_dir):
            return None
            
        wav_files = glob.glob(os.path.join(media_dir, "*.wav"))
        return wav_files if wav_files else []
    except:
        return None

class ConfigDialog(Qt.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PPM-OOK Audio Transmitter Configuration")
        self.layout = Qt.QVBoxLayout(self)
        self.config_dir = "config"
        self.config_file = os.path.join(self.config_dir, "ppmook_config.json")
        
        # Read settings
        settings = read_settings()
        self.ipList = settings['ip_addresses']
        self.N = len(self.ipList)
        
        # Add OK/Cancel buttons
        self.button_box = Qt.QDialogButtonBox(
            Qt.QDialogButtonBox.Ok | Qt.QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        
        # Create widgets
        self.create_usrp_selector()
        self.create_frequency_control()
        self.create_pulse_width_control()
        self.create_mod_level_control()
        self.create_coherence_control()
        self.create_source_control()
        
        self.layout.addWidget(self.button_box)
        
        # Load saved configuration
        self.load_config()
        
        # Apply dark theme
        apply_dark_theme(self)

    def create_usrp_selector(self):
        self.usrp_combo = Qt.QComboBox()
        ok_button = self.button_box.button(Qt.QDialogButtonBox.Ok)
        
        if not self.ipList:
            self.usrp_combo.addItem("IP addr missing - Go to Settings")
            ok_button.setEnabled(False)
            opacity_effect = Qt.QGraphicsOpacityEffect()
            opacity_effect.setOpacity(0.30)
            ok_button.setGraphicsEffect(opacity_effect)
        else:
            for i in range(self.N):
                self.usrp_combo.addItem(f"USRP {i+1} ({self.ipList[i].strip()})")
            ok_button.setEnabled(True)
            ok_button.setGraphicsEffect(None)
        
        self.layout.addWidget(Qt.QLabel("Select USRP:"))
        self.layout.addWidget(self.usrp_combo)

    def create_frequency_control(self):
        self.cf_layout = Qt.QHBoxLayout()
        self.cf_slider = Qt.QSlider(QtCore.Qt.Horizontal)
        self.cf_slider.setMinimum(30)
        self.cf_slider.setMaximum(2200)
        self.cf_slider.setValue(300)  # Changed from 295 to 300
        self.cf_label = Qt.QLabel("Center Frequency: 300 MHz")  # Changed from 295 to 300
        self.cf_slider.valueChanged.connect(
            lambda v: self.cf_label.setText(f"Center Frequency: {v} MHz"))
        self.cf_layout.addWidget(self.cf_label)
        self.cf_layout.addWidget(self.cf_slider)
        self.layout.addLayout(self.cf_layout)

    def create_pulse_width_control(self):
        self.pulse_group = Qt.QButtonGroup()
        pulse_layout = Qt.QHBoxLayout()
        pulse_label = Qt.QLabel("Pulse Duration:")
        pulse_layout.addWidget(pulse_label)
        
        for width, label in [(10, "10 μs"), (20, "20 μs"), (40, "40 μs")]:
            radio = Qt.QRadioButton(label)
            if width == 20:  # Default
                radio.setChecked(True)
            self.pulse_group.addButton(radio)
            self.pulse_group.setId(radio, width)
            pulse_layout.addWidget(radio)
            
        self.layout.addLayout(pulse_layout)

    def create_mod_level_control(self):
        self.mod_layout = Qt.QHBoxLayout()
        self.mod_slider = Qt.QSlider(QtCore.Qt.Horizontal)
        self.mod_slider.setMinimum(1)
        self.mod_slider.setMaximum(50)
        self.mod_slider.setValue(10)
        self.mod_label = Qt.QLabel("Modulation Level: 1.0")
        self.mod_slider.valueChanged.connect(
            lambda v: self.mod_label.setText(f"Modulation Level: {v/10:.1f}"))
        self.mod_layout.addWidget(self.mod_label)
        self.mod_layout.addWidget(self.mod_slider)
        self.layout.addLayout(self.mod_layout)

    def create_coherence_control(self):
        self.coherence_group = Qt.QButtonGroup()
        coherence_layout = Qt.QHBoxLayout()
        coherence_label = Qt.QLabel("Coherence:")
        coherence_layout.addWidget(coherence_label)
        
        for val, label in [(0, "Non-Coherent"), (1, "Coherent")]:
            radio = Qt.QRadioButton(label)
            if val == 0:  # Default
                radio.setChecked(True)
            self.coherence_group.addButton(radio)
            self.coherence_group.setId(radio, val)
            coherence_layout.addWidget(radio)
            
        self.layout.addLayout(coherence_layout)

    def create_source_control(self):
        """Replace the live audio source with recorded audio file selector"""
        self.source_combo = Qt.QComboBox()
        ok_button = self.button_box.button(Qt.QDialogButtonBox.Ok)
        
        # Read media directory setting and get wav files
        settings = read_settings() 
        wav_files = get_wav_files(settings)
        
        if wav_files is None:
            # No media directory configured
            self.source_combo.addItem("Media directory missing - Go to Settings") 
            ok_button.setEnabled(False)
            
            # Add opacity effect to dim the button
            opacity_effect = Qt.QGraphicsOpacityEffect()
            opacity_effect.setOpacity(0.30)
            ok_button.setGraphicsEffect(opacity_effect)
        else:
            # Media directory exists
            if wav_files:
                # Add all wav files found
                for wav_file in wav_files:
                    display_name = os.path.splitext(os.path.basename(wav_file))[0].replace('-', ' ')
                    self.source_combo.addItem(display_name, wav_file)
                    
            # Add No Modulation option
            self.source_combo.addItem("No Modulation", "none")
            ok_button.setEnabled(True)
            ok_button.setGraphicsEffect(None)
            
        self.layout.addWidget(Qt.QLabel("Input Source:"))
        self.layout.addWidget(self.source_combo)

    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    
                self.usrp_combo.setCurrentIndex(config.get('usrp_index', 0))
                self.cf_slider.setValue(config.get('center_freq', 300))
                self.mod_slider.setValue(config.get('mod_level', 10))
                
                pulse_width = config.get('pulse_width', 20)
                for button in self.pulse_group.buttons():
                    if self.pulse_group.id(button) == pulse_width:
                        button.setChecked(True)
                        
                coherence = config.get('coherence', 0)
                for button in self.coherence_group.buttons():
                    if self.coherence_group.id(button) == coherence:
                        button.setChecked(True)
            except:
                pass
        else:
            os.makedirs(self.config_dir, exist_ok=True)

    def save_config(self):
        config = {
            'usrp_index': self.usrp_combo.currentIndex(),
            'center_freq': self.cf_slider.value(),
            'mod_level': self.mod_slider.value(),
            'pulse_width': self.pulse_group.checkedId(),
            'coherence': self.coherence_group.checkedId()
        }
        
        with open(self.config_file, 'w') as f:
            json.dump(config, f, indent=4)

    def accept(self):
        self.save_config()
        super().accept()

    def get_values(self):
        ipNum = self.usrp_combo.currentIndex() + 1
        ipXmitAddr = self.ipList[self.usrp_combo.currentIndex()].strip()
        
        # Get selected source
        current_data = self.source_combo.currentData()
        if current_data == "none":
            sourceIndex = 1
            wavFile = None
        else:
            sourceIndex = 0
            wavFile = current_data
            
        return {
            'ipNum': ipNum,
            'ipXmitAddr': ipXmitAddr,
            'cf': self.cf_slider.value(),
            'pulseWidth': self.pulse_group.checkedId(),
            'modLevel': self.mod_slider.value() / 10,
            'coherence': self.coherence_group.checkedId(),
            'sourceIndex': sourceIndex,
            'wavFile': wavFile
        }

class ppmookLiveAudioXmitter(gr.top_block, Qt.QWidget):

    def __init__(self, config_values=None):
        gr.top_block.__init__(self, "PPM-OOK Live Audio Xmitter", catch_exceptions=True)
        Qt.QWidget.__init__(self)
        self.setWindowTitle("PPM-OOK Live Audio Xmitter")
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

        self.settings = Qt.QSettings("GNU Radio", "ppmookLiveAudioXmitter")

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
            
        # Assign all values
        ipNum = values['ipNum']
        ipXmitAddr = values['ipXmitAddr']
        cf = values['cf']
        pulseWidth = values['pulseWidth']
        modLevel = values['modLevel']
        coherence = values['coherence']
        sourceIndex = values['sourceIndex']
        wavFile = values['wavFile']
        
        # Update variables
        self.pulseWidthDefault = pulseWidth
        self.modLevelDefault = modLevel
        self.coherenceDefault = coherence
        self.cfDefault = cf

        ##################################################
        # Variables
        ##################################################
        self.sps = sps = 500
        self.samp_rate = samp_rate = 20e6
        self.pulseWidthDefault = pulseWidthDefault = 20
        self.modLevelDefault = modLevelDefault = 1
        self.coherenceDefault = coherenceDefault = 0
        self.cf = cf = 300  # Changed from 295 to 300
        self.pulseWidth = pulseWidth = pulseWidthDefault
        self.pulsePeriod = pulsePeriod = sps/samp_rate*1e6
        self.modLevel = modLevel = modLevelDefault
        self.coherence = coherence = coherenceDefault
        self.centerFrequency = centerFrequency = cf

        ##################################################
        # Blocks
        ##################################################
        # Create the options list
        self._pulseWidth_options = [10, 20, 40]
        # Create the labels list
        self._pulseWidth_labels = ['10 usec', '20 usec', '40 usec']
        # Create the combo box
        # Create the radio buttons
        self._pulseWidth_group_box = Qt.QGroupBox("Pulse Duration" + ": ")
        self._pulseWidth_box = Qt.QHBoxLayout()
        class variable_chooser_button_group(Qt.QButtonGroup):
            def __init__(self, parent=None):
                Qt.QButtonGroup.__init__(self, parent)
            @pyqtSlot(int)
            def updateButtonChecked(self, button_id):
                self.button(button_id).setChecked(True)
        self._pulseWidth_button_group = variable_chooser_button_group()
        self._pulseWidth_group_box.setLayout(self._pulseWidth_box)
        for i, _label in enumerate(self._pulseWidth_labels):
            radio_button = Qt.QRadioButton(_label)
            self._pulseWidth_box.addWidget(radio_button)
            self._pulseWidth_button_group.addButton(radio_button, i)
        self._pulseWidth_callback = lambda i: Qt.QMetaObject.invokeMethod(self._pulseWidth_button_group, "updateButtonChecked", Qt.Q_ARG("int", self._pulseWidth_options.index(i)))
        self._pulseWidth_callback(self.pulseWidth)
        self._pulseWidth_button_group.buttonClicked[int].connect(
            lambda i: self.set_pulseWidth(self._pulseWidth_options[i]))
        self.top_grid_layout.addWidget(self._pulseWidth_group_box, 1, 0, 1, 5)
        for r in range(1, 2):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(0, 5):
            self.top_grid_layout.setColumnStretch(c, 1)
        self._modLevel_range = Range(0.1, 5, 0.1, modLevelDefault, 200)
        self._modLevel_win = RangeWidget(self._modLevel_range, self.set_modLevel, "Modulation Level", "counter_slider", float, QtCore.Qt.Horizontal)
        self.top_grid_layout.addWidget(self._modLevel_win, 0, 5, 1, 5)
        for r in range(0, 1):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(5, 10):
            self.top_grid_layout.setColumnStretch(c, 1)
        # Create the options list
        self._coherence_options = [0, 1]
        # Create the labels list
        self._coherence_labels = ['Non-Coherent', 'Coherent']
        # Create the combo box
        # Create the radio buttons
        self._coherence_group_box = Qt.QGroupBox("Coherence On/Off" + ": ")
        self._coherence_box = Qt.QHBoxLayout()
        class variable_chooser_button_group(Qt.QButtonGroup):
            def __init__(self, parent=None):
                Qt.QButtonGroup.__init__(self, parent)
            @pyqtSlot(int)
            def updateButtonChecked(self, button_id):
                self.button(button_id).setChecked(True)
        self._coherence_button_group = variable_chooser_button_group()
        self._coherence_group_box.setLayout(self._coherence_box)
        for i, _label in enumerate(self._coherence_labels):
            radio_button = Qt.QRadioButton(_label)
            self._coherence_box.addWidget(radio_button)
            self._coherence_button_group.addButton(radio_button, i)
        self._coherence_callback = lambda i: Qt.QMetaObject.invokeMethod(self._coherence_button_group, "updateButtonChecked", Qt.Q_ARG("int", self._coherence_options.index(i)))
        self._coherence_callback(self.coherence)
        self._coherence_button_group.buttonClicked[int].connect(
            lambda i: self.set_coherence(self._coherence_options[i]))
        self.top_grid_layout.addWidget(self._coherence_group_box, 2, 0, 1, 5)
        for r in range(2, 3):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(0, 5):
            self.top_grid_layout.setColumnStretch(c, 1)
        self.uhd_usrp_sink_0 = uhd.usrp_sink(
            ",".join((f'addr={ipXmitAddr}', '')),  # Use IP from config
            uhd.stream_args(
                cpu_format="fc32",
                args='',
                channels=list(range(0,1)),
            ),
            "",
        )
        self.uhd_usrp_sink_0.set_samp_rate(samp_rate)
        self.uhd_usrp_sink_0.set_time_now(uhd.time_spec(time.time()), uhd.ALL_MBOARDS)

        self.uhd_usrp_sink_0.set_center_freq(cf*1e6, 0)
        self.uhd_usrp_sink_0.set_antenna("TX/RX", 0)
        self.uhd_usrp_sink_0.set_gain(10, 0)
        self.rational_resampler_xxx_0 = filter.rational_resampler_fff(
                interpolation=int(samp_rate/sps/1000),
                decimation=24,
                taps=[],
                fractional_bw=0)
        self.qtgui_time_sink_x_0 = qtgui.time_sink_f(
            5000, #size
            samp_rate, #samp_rate
            'Baseband Pulse Stream', #name
            1, #number of inputs
            None # parent
        )
        self.qtgui_time_sink_x_0.set_update_time(0.10)
        self.qtgui_time_sink_x_0.set_y_axis(-1.5, 1.5)

        self.qtgui_time_sink_x_0.set_y_label('Amplitude', "")

        self.qtgui_time_sink_x_0.enable_tags(True)
        self.qtgui_time_sink_x_0.set_trigger_mode(qtgui.TRIG_MODE_NORM, qtgui.TRIG_SLOPE_POS, 0.5, 0, 0, "")
        self.qtgui_time_sink_x_0.enable_autoscale(False)
        self.qtgui_time_sink_x_0.enable_grid(True)
        self.qtgui_time_sink_x_0.enable_axis_labels(True)
        self.qtgui_time_sink_x_0.enable_control_panel(False)
        self.qtgui_time_sink_x_0.enable_stem_plot(False)

        self.qtgui_time_sink_x_0.disable_legend()

        labels = ['Baseband Pulse Stream', 'Signal 2', 'Signal 3', 'Signal 4', 'Signal 5',
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
        self.top_grid_layout.addWidget(self._qtgui_time_sink_x_0_win, 3, 0, 5, 10)
        for r in range(3, 8):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(0, 10):
            self.top_grid_layout.setColumnStretch(c, 1)
        self.qtgui_freq_sink_x_1 = qtgui.freq_sink_c(
            8192, #size
            window.WIN_BLACKMAN_hARRIS, #wintype
            cf*1e6, #fc
            samp_rate, #bw
            'RF Spectrum', #name
            1,
            None # parent
        )
        self.qtgui_freq_sink_x_1.set_update_time(0.10)
        self.qtgui_freq_sink_x_1.set_y_axis(-120, -20)
        self.qtgui_freq_sink_x_1.set_y_label('Relative Gain', 'dB')
        self.qtgui_freq_sink_x_1.set_trigger_mode(qtgui.TRIG_MODE_FREE, 0.0, 0, "")
        self.qtgui_freq_sink_x_1.enable_autoscale(False)
        self.qtgui_freq_sink_x_1.enable_grid(True)
        self.qtgui_freq_sink_x_1.set_fft_average(1.0)
        self.qtgui_freq_sink_x_1.enable_axis_labels(True)
        self.qtgui_freq_sink_x_1.enable_control_panel(False)
        self.qtgui_freq_sink_x_1.set_fft_window_normalized(False)

        self.qtgui_freq_sink_x_1.disable_legend()


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
                self.qtgui_freq_sink_x_1.set_line_label(i, "Data {0}".format(i))
            else:
                self.qtgui_freq_sink_x_1.set_line_label(i, labels[i])
            self.qtgui_freq_sink_x_1.set_line_width(i, widths[i])
            self.qtgui_freq_sink_x_1.set_line_color(i, colors[i])
            self.qtgui_freq_sink_x_1.set_line_alpha(i, alphas[i])

        self._qtgui_freq_sink_x_1_win = sip.wrapinstance(self.qtgui_freq_sink_x_1.qwidget(), Qt.QWidget)
        self.top_grid_layout.addWidget(self._qtgui_freq_sink_x_1_win, 8, 0, 5, 10)
        for r in range(8, 13):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(0, 10):
            self.top_grid_layout.setColumnStretch(c, 1)
        self._pulsePeriod_tool_bar = Qt.QToolBar(self)

        if None:
            self._pulsePeriod_formatter = None
        else:
            self._pulsePeriod_formatter = lambda x: eng_notation.num_to_str(x)

        self._pulsePeriod_tool_bar.addWidget(Qt.QLabel("Pulse Period (usec): "))
        self._pulsePeriod_label = Qt.QLabel(str(self._pulsePeriod_formatter(self.pulsePeriod)))
        self._pulsePeriod_tool_bar.addWidget(self._pulsePeriod_label)
        self.top_grid_layout.addWidget(self._pulsePeriod_tool_bar, 1, 5, 1, 5)
        for r in range(1, 2):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(5, 10):
            self.top_grid_layout.setColumnStretch(c, 1)
        self.filter_fft_low_pass_filter_0 = filter.fft_filter_fff(1, firdes.low_pass(modLevel, 24000, 4000, 1000, window.WIN_HAMMING, 6.76), 1)
        self.fft_filter_xxx_0_0 = filter.fft_filter_fff(1, [1,]*pulseWidth, 1)
        self.fft_filter_xxx_0_0.declare_sample_delay(0)
        self.fft_filter_xxx_0 = filter.fft_filter_fff(1, (1,)*sps, 1)
        self.fft_filter_xxx_0.declare_sample_delay(0)
        self.digital_glfsr_source_x_0 = digital.glfsr_source_f(31, True, 0b1001000000000000000000000000000, 1)
        self.digital_binary_slicer_fb_1 = digital.binary_slicer_fb()
        self.digital_binary_slicer_fb_0 = digital.binary_slicer_fb()
        self._centerFrequency_range = Range(30, 2200, 0.01, cf, 200)
        self._centerFrequency_win = RangeWidget(self._centerFrequency_range, self.set_centerFrequency, "Center Frequency (MHz)", "counter", float, QtCore.Qt.Horizontal)
        self.top_grid_layout.addWidget(self._centerFrequency_win, 0, 0, 1, 5)
        for r in range(0, 1):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(0, 5):
            self.top_grid_layout.setColumnStretch(c, 1)
        self.blocks_vector_source_x_0_0 = blocks.vector_source_f((0,)*10+(1,)*(sps-10), True, 1, [])
        self.blocks_vector_source_x_0 = blocks.vector_source_f(np.arange(1,-1,-2/sps), True, 1, [])
        self.blocks_stream_mux_0 = blocks.stream_mux(gr.sizeof_float*1, (int(sps-1),1))
        self.blocks_selector_0 = blocks.selector(gr.sizeof_float*1,coherence,0)
        self.blocks_selector_0.set_enabled(True)
        self.blocks_repeat_0 = blocks.repeat(gr.sizeof_float*1, int(sps))
        self.blocks_null_source_0_0 = blocks.null_source(gr.sizeof_float*1)
        self.blocks_null_source_0 = blocks.null_source(gr.sizeof_float*1)
        self.blocks_multiply_xx_2 = blocks.multiply_vff(1)
        self.blocks_multiply_xx_1 = blocks.multiply_vff(1)
        self.blocks_multiply_xx_0 = blocks.multiply_vff(1)
        self.blocks_multiply_const_vxx_1 = blocks.multiply_const_cc(0.1)
        self.blocks_multiply_const_vxx_0 = blocks.multiply_const_ff(-1)
        self.blocks_float_to_complex_0 = blocks.float_to_complex(1)
        self.blocks_delay_1 = blocks.delay(gr.sizeof_float*1, 1)
        self.blocks_char_to_float_1 = blocks.char_to_float(1, 1)
        self.blocks_char_to_float_0 = blocks.char_to_float(1, 1)
        self.blocks_add_xx_0 = blocks.add_vff(1)
        self.blocks_add_const_vxx_0 = blocks.add_const_ff(-0.5)

        # Modify blocks to use recorded audio instead of TCP source
        if wavFile and os.path.exists(wavFile):
            self.source_0 = blocks.wavfile_source(wavFile, True)
        else:
            self.source_0 = blocks.null_source(gr.sizeof_float*1)

        # Replace network TCP source with wav file source
        self.blocks_selector_0 = blocks.selector(gr.sizeof_float*1, sourceIndex, 0)
        self.blocks_selector_0.set_enabled(True)

        ##################################################
        # Connections
        ##################################################
        self.connect((self.blocks_add_const_vxx_0, 0), (self.blocks_delay_1, 0))
        self.connect((self.blocks_add_const_vxx_0, 0), (self.blocks_multiply_xx_0, 1))
        self.connect((self.blocks_add_xx_0, 0), (self.digital_binary_slicer_fb_1, 0))
        self.connect((self.blocks_char_to_float_0, 0), (self.blocks_add_const_vxx_0, 0))
        self.connect((self.blocks_char_to_float_1, 0), (self.blocks_multiply_xx_2, 0))
        self.connect((self.blocks_delay_1, 0), (self.blocks_multiply_xx_0, 0))
        self.connect((self.blocks_float_to_complex_0, 0), (self.blocks_multiply_const_vxx_1, 0))
        self.connect((self.blocks_float_to_complex_0, 0), (self.qtgui_freq_sink_x_1, 0))
        self.connect((self.blocks_multiply_const_vxx_0, 0), (self.digital_binary_slicer_fb_0, 0))
        self.connect((self.blocks_multiply_const_vxx_1, 0), (self.uhd_usrp_sink_0, 0))
        self.connect((self.blocks_multiply_xx_0, 0), (self.blocks_multiply_const_vxx_0, 0))
        self.connect((self.blocks_multiply_xx_1, 0), (self.blocks_selector_0, 0))
        self.connect((self.blocks_multiply_xx_2, 0), (self.blocks_multiply_xx_1, 1))
        self.connect((self.blocks_multiply_xx_2, 0), (self.blocks_selector_0, 1))
        self.connect((self.blocks_null_source_0, 0), (self.blocks_stream_mux_0, 0))
        self.connect((self.blocks_null_source_0_0, 0), (self.blocks_float_to_complex_0, 1))
        self.connect((self.blocks_repeat_0, 0), (self.blocks_multiply_xx_1, 0))
        self.connect((self.blocks_selector_0, 0), (self.fft_filter_xxx_0_0, 0))
        self.connect((self.blocks_stream_mux_0, 0), (self.fft_filter_xxx_0, 0))
        self.connect((self.blocks_vector_source_x_0, 0), (self.blocks_add_xx_0, 0))
        self.connect((self.blocks_vector_source_x_0_0, 0), (self.blocks_multiply_xx_2, 1))
        self.connect((self.digital_binary_slicer_fb_0, 0), (self.blocks_char_to_float_1, 0))
        self.connect((self.digital_binary_slicer_fb_1, 0), (self.blocks_char_to_float_0, 0))
        self.connect((self.digital_glfsr_source_x_0, 0), (self.blocks_repeat_0, 0))
        self.connect((self.fft_filter_xxx_0, 0), (self.blocks_add_xx_0, 1))
        self.connect((self.fft_filter_xxx_0_0, 0), (self.blocks_float_to_complex_0, 0))
        self.connect((self.fft_filter_xxx_0_0, 0), (self.qtgui_time_sink_x_0, 0))
        self.connect((self.filter_fft_low_pass_filter_0, 0), (self.rational_resampler_xxx_0, 0))
        self.connect((self.source_0, 0), (self.filter_fft_low_pass_filter_0, 0))
        self.connect((self.rational_resampler_xxx_0, 0), (self.blocks_stream_mux_0, 1))


    def closeEvent(self, event):
        self.settings = Qt.QSettings("GNU Radio", "ppmookLiveAudioXmitter")
        self.settings.setValue("geometry", self.saveGeometry())
        self.stop()
        self.wait()

        event.accept()

    def get_sps(self):
        return self.sps

    def set_sps(self, sps):
        self.sps = sps
        self.set_pulsePeriod(self.sps/self.samp_rate*1e6)
        self.blocks_repeat_0.set_interpolation(int(self.sps))
        self.blocks_vector_source_x_0.set_data(np.arange(1,-1,-2/self.sps), [])
        self.blocks_vector_source_x_0_0.set_data((0,)*10+(1,)*(self.sps-10), [])
        self.fft_filter_xxx_0.set_taps((1,)*self.sps)

    def get_samp_rate(self):
        return self.samp_rate

    def set_samp_rate(self, samp_rate):
        self.samp_rate = samp_rate
        self.set_pulsePeriod(self.sps/self.samp_rate*1e6)
        self.qtgui_freq_sink_x_1.set_frequency_range(self.cf*1e6, self.samp_rate)
        self.qtgui_time_sink_x_0.set_samp_rate(self.samp_rate)
        self.uhd_usrp_sink_0.set_samp_rate(self.samp_rate)

    def get_pulseWidthDefault(self):
        return self.pulseWidthDefault

    def set_pulseWidthDefault(self, pulseWidthDefault):
        self.pulseWidthDefault = pulseWidthDefault
        self.set_pulseWidth(self.pulseWidthDefault)

    def get_modLevelDefault(self):
        return self.modLevelDefault

    def set_modLevelDefault(self, modLevelDefault):
        self.modLevelDefault = modLevelDefault
        self.set_modLevel(self.modLevelDefault)

    def get_coherenceDefault(self):
        return self.coherenceDefault

    def set_coherenceDefault(self, coherenceDefault):
        self.coherenceDefault = coherenceDefault
        self.set_coherence(self.coherenceDefault)

    def get_cf(self):
        return self.cf

    def set_cf(self, cf):
        self.cf = cf
        self.set_centerFrequency(self.cf)
        self.qtgui_freq_sink_x_1.set_frequency_range(self.cf*1e6, self.samp_rate)
        self.uhd_usrp_sink_0.set_center_freq(self.cf*1e6, 0)

    def get_pulseWidth(self):
        return self.pulseWidth

    def set_pulseWidth(self, pulseWidth):
        self.pulseWidth = pulseWidth
        self._pulseWidth_callback(self.pulseWidth)
        self.fft_filter_xxx_0_0.set_taps([1,]*self.pulseWidth)

    def get_pulsePeriod(self):
        return self.pulsePeriod

    def set_pulsePeriod(self, pulsePeriod):
        self.pulsePeriod = pulsePeriod
        Qt.QMetaObject.invokeMethod(self._pulsePeriod_label, "setText", Qt.Q_ARG("QString", str(self._pulsePeriod_formatter(self.pulsePeriod))))

    def get_modLevel(self):
        return self.modLevel

    def set_modLevel(self, modLevel):
        self.modLevel = modLevel
        self.filter_fft_low_pass_filter_0.set_taps(firdes.low_pass(self.modLevel, 24000, 4000, 1000, window.WIN_HAMMING, 6.76))

    def get_coherence(self):
        return self.coherence

    def set_coherence(self, coherence):
        self.coherence = coherence
        self._coherence_callback(self.coherence)
        self.blocks_selector_0.set_input_index(self.coherence)

    def get_centerFrequency(self):
        return self.centerFrequency

    def set_centerFrequency(self, centerFrequency):
        self.centerFrequency = centerFrequency




def main(top_block_cls=ppmookLiveAudioXmitter, options=None, app=None, config_values=None):

    if app is None:
        if StrictVersion("4.5.0") <= StrictVersion(Qt.qVersion()) < StrictVersion("5.0.0"):
            style = gr.prefs().get_string('qtgui', 'style', 'raster')
            #Qt.QApplication.setGraphicsSystem(style)
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
