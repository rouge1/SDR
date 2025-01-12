#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#
# SPDX-License-Identifier: GPL-3.0
#
# GNU Radio Python Flow Graph
# Title: AM Sinewave Signal Generator
# Author: Gary Schafer
# GNU Radio version: 3.10.1.1

from packaging.version import Version as StrictVersion

if __name__ == '__main__':
    import ctypes
    import sys
    if sys.platform.startswith('linux'):
        try:
            x11 = ctypes.cdll.LoadLibrary('libX11.so')
            x11.XInitThreads()
        except:
            print("Warning: failed to XInitThreads()")

from PyQt5 import Qt
from PyQt5.QtCore import QObject, pyqtSlot
from gnuradio import eng_notation
from gnuradio import qtgui
from gnuradio.filter import firdes
import sip
from gnuradio import analog
from gnuradio import blocks
from gnuradio import filter
from gnuradio import gr
from gnuradio.fft import window
import sys
import signal
from argparse import ArgumentParser
from gnuradio.eng_arg import eng_float, intx
from gnuradio import uhd
import time
from gnuradio.qtgui import Range, RangeWidget
from PyQt5 import QtCore
from gnuradio import qtgui

class ConfigDialog(Qt.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AM Sine Generator Configuration")
        self.layout = Qt.QVBoxLayout(self)
        
        try:
            with open("usrpXmit.cfg", "r") as ipFile:
                self.ipList = ipFile.readlines()
                self.N = len(self.ipList)
        except:
            self.ipList = ["192.168.10.2"]
            self.N = 1
            
        # Create all the input widgets
        self.create_usrp_selector()
        self.create_frequency_control()
        self.create_power_control()
        self.create_carrier_control()
        self.create_sideband_control()
        self.create_sine_frequency_control()
        
        # Add OK/Cancel buttons
        self.button_box = Qt.QDialogButtonBox(
            Qt.QDialogButtonBox.Ok | Qt.QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.layout.addWidget(self.button_box)

    def create_usrp_selector(self):
        self.usrp_combo = Qt.QComboBox()
        for i in range(self.N):
            self.usrp_combo.addItem(f"USRP {i+1} ({self.ipList[i].strip()})")
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

    def create_carrier_control(self):
        self.carrier_combo = Qt.QComboBox()
        self.carrier_combo.addItems(["Full Carrier", "Suppressed Carrier"])
        self.layout.addWidget(Qt.QLabel("Carrier Condition:"))
        self.layout.addWidget(self.carrier_combo)

    def create_sideband_control(self):
        # Sideband condition
        self.sideband_combo = Qt.QComboBox()
        self.sideband_combo.addItems(["Double Sideband", "Single Sideband"])
        self.layout.addWidget(Qt.QLabel("Sideband Condition:"))
        self.layout.addWidget(self.sideband_combo)
        self.sideband_combo.currentIndexChanged.connect(self.toggle_sideband_type)
        
        # Sideband type (initially hidden)
        self.sideband_type_widget = Qt.QWidget()
        self.sideband_type_layout = Qt.QVBoxLayout(self.sideband_type_widget)
        self.sideband_type_combo = Qt.QComboBox()
        self.sideband_type_combo.addItems(["Lower Sideband", "Upper Sideband"])
        self.sideband_type_layout.addWidget(Qt.QLabel("Sideband Type:"))
        self.sideband_type_layout.addWidget(self.sideband_type_combo)
        self.layout.addWidget(self.sideband_type_widget)
        self.sideband_type_widget.hide()

    def create_sine_frequency_control(self):
        self.sine_layout = Qt.QHBoxLayout()
        self.sine_slider = Qt.QSlider(QtCore.Qt.Horizontal)
        self.sine_slider.setMinimum(1)  # 0.1 Hz * 10
        self.sine_slider.setMaximum(200000)  # 20000 Hz * 10
        self.sine_slider.setValue(10000)  # 1000 Hz default
        self.sine_label = Qt.QLabel("Sine Frequency: 1000 Hz")
        self.sine_slider.valueChanged.connect(
            lambda v: self.sine_label.setText(f"Sine Frequency: {v/10} Hz"))
        self.sine_layout.addWidget(self.sine_label)
        self.sine_layout.addWidget(self.sine_slider)
        self.layout.addLayout(self.sine_layout)

    def toggle_sideband_type(self, index):
        if index == 1:  # Single Sideband selected
            self.sideband_type_widget.show()
        else:
            self.sideband_type_widget.hide()

    def get_values(self):
        ipNum = self.usrp_combo.currentIndex() + 1
        ipXmitAddr = self.ipList[ipNum - 1].strip()
        mikePort = 2020 + ipNum
        
        pwr = self.pwr_slider.value()
        if pwr < -50:
            rfGain = 0
            atten = pwr + 50
        else:
            atten = 0
            rfGain = pwr + 50
            
        return {
            'ipNum': ipNum,
            'ipXmitAddr': ipXmitAddr,
            'mikePort': mikePort,
            'cf': self.cf_slider.value(),
            'pwr': pwr,
            'rfGain': rfGain,
            'atten': atten,
            'rfGainDefault': rfGain,
            'attenDefault': atten,
            'carrierDefault': 1 if self.carrier_combo.currentIndex() == 0 else 0,
            'sidebandDefaultVal': 2 if self.sideband_combo.currentIndex() == 0 else 1,
            'sidebandDefault': 0 if self.sideband_combo.currentIndex() == 0 else 1,
            'sidebandTypeDefaultVal': 2 if self.sideband_type_combo.currentIndex() == 1 else 1,
            'sidebandTypeDefault': 1 if self.sideband_combo.currentIndex() == 0 else (2 * (self.sideband_type_combo.currentIndex() == 1) - 1),
            'sineFreqDefault': self.sine_slider.value() / 10
        }

class amSineGenerator(gr.top_block, Qt.QWidget):

    def __init__(self):
        gr.top_block.__init__(self, "AM Sinewave Signal Generator", catch_exceptions=True)
        Qt.QWidget.__init__(self)
        self.setWindowTitle("AM Sinewave Signal Generator")
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

        self.settings = Qt.QSettings("GNU Radio", "amSineGenerator")

        try:
            if StrictVersion(Qt.qVersion()) < StrictVersion("5.0.0"):
                self.restoreGeometry(self.settings.value("geometry").toByteArray())
            else:
                self.restoreGeometry(self.settings.value("geometry"))
        except:
            pass

        ##################################################
        # Title of Program
        ##################################################
        
        print("AM w/ Sinewave\n")

        ##################################################
        # Variable Entry
        ##################################################
        
        # Create and show configuration dialog
        config_dialog = ConfigDialog()
        if not config_dialog.exec_():
            sys.exit(0)
            
        values = config_dialog.get_values()
        
        # Assign all values
        ipNum = values['ipNum']
        ipXmitAddr = values['ipXmitAddr']
        mikePort = values['mikePort']
        cf = values['cf']
        pwr = values['pwr']
        rfGain = values['rfGain']
        atten = values['atten']
        rfGainDefault = values['rfGainDefault']
        attenDefault = values['attenDefault']
        carrierDefault = values['carrierDefault']
        sidebandDefaultVal = values['sidebandDefaultVal']
        sidebandDefault = values['sidebandDefault']
        sidebandTypeDefaultVal = values['sidebandTypeDefaultVal']
        sidebandTypeDefault = values['sidebandTypeDefault']
        sineFreqDefault = values['sineFreqDefault']
        
        ##################################################
        # Variables
        ##################################################
        self.sineFreqDefault = sineFreqDefault
        self.sidebandTypeDefault = sidebandTypeDefault
        self.sidebandDefault = sidebandDefault
        self.rfPwrDefault = rfPwrDefault = pwr
        self.modIndexDefault = modIndexDefault = 1
        self.cfDefault = cfDefault = cf
        self.carrierDefault = carrierDefault
        self.usrpNum = usrpNum = ipNum
        self.sineFreq = sineFreq = sineFreqDefault
        self.sidebandType = sidebandType = sidebandTypeDefault
        self.sideband = sideband = sidebandDefault
        self.samp_rate = samp_rate = 2e6
        self.rfPwr = rfPwr = rfPwrDefault
        self.outputIpAddr = outputIpAddr = ipXmitAddr
        self.modName = modName = 'AM w/ Sinewave'
        self.modIndex = modIndex = modIndexDefault
        self.mikePort = mikePort = 2025
        self.mikeIpAddr = mikeIpAddr = "192.168.51.100"
        self.inputSelectDefault = inputSelectDefault = 0
        self.centerFreq = centerFreq = cfDefault
        self.carrier = carrier = carrierDefault

        ##################################################
        # Blocks
        ##################################################
        self._sineFreq_range = Range(0, 20e3, 0.1, sineFreqDefault, 200)
        self._sineFreq_win = RangeWidget(self._sineFreq_range, self.set_sineFreq, "Sinewave Frequency (Hz)", "counter_slider", float, QtCore.Qt.Horizontal)
        self.top_grid_layout.addWidget(self._sineFreq_win, 4, 0, 1, 5)
        for r in range(4, 5):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(0, 5):
            self.top_grid_layout.setColumnStretch(c, 1)
        # Create the options list
        self._sidebandType_options = [-1, 1]
        # Create the labels list
        self._sidebandType_labels = ['Lower', 'Upper']
        # Create the combo box
        # Create the radio buttons
        self._sidebandType_group_box = Qt.QGroupBox("Lower / Upper Sideband" + ": ")
        self._sidebandType_box = Qt.QHBoxLayout()
        class variable_chooser_button_group(Qt.QButtonGroup):
            def __init__(self, parent=None):
                Qt.QButtonGroup.__init__(self, parent)
            @pyqtSlot(int)
            def updateButtonChecked(self, button_id):
                self.button(button_id).setChecked(True)
        self._sidebandType_button_group = variable_chooser_button_group()
        self._sidebandType_group_box.setLayout(self._sidebandType_box)
        for i, _label in enumerate(self._sidebandType_labels):
            radio_button = Qt.QRadioButton(_label)
            self._sidebandType_box.addWidget(radio_button)
            self._sidebandType_button_group.addButton(radio_button, i)
        self._sidebandType_callback = lambda i: Qt.QMetaObject.invokeMethod(self._sidebandType_button_group, "updateButtonChecked", Qt.Q_ARG("int", self._sidebandType_options.index(i)))
        self._sidebandType_callback(self.sidebandType)
        self._sidebandType_button_group.buttonClicked[int].connect(
            lambda i: self.set_sidebandType(self._sidebandType_options[i]))
        self.top_grid_layout.addWidget(self._sidebandType_group_box, 2, 7, 1, 3)
        for r in range(2, 3):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(7, 10):
            self.top_grid_layout.setColumnStretch(c, 1)
        # Create the options list
        self._sideband_options = [0, 1]
        # Create the labels list
        self._sideband_labels = ['Double', 'Single']
        # Create the combo box
        # Create the radio buttons
        self._sideband_group_box = Qt.QGroupBox("Single / Double Sideband" + ": ")
        self._sideband_box = Qt.QHBoxLayout()
        class variable_chooser_button_group(Qt.QButtonGroup):
            def __init__(self, parent=None):
                Qt.QButtonGroup.__init__(self, parent)
            @pyqtSlot(int)
            def updateButtonChecked(self, button_id):
                self.button(button_id).setChecked(True)
        self._sideband_button_group = variable_chooser_button_group()
        self._sideband_group_box.setLayout(self._sideband_box)
        for i, _label in enumerate(self._sideband_labels):
            radio_button = Qt.QRadioButton(_label)
            self._sideband_box.addWidget(radio_button)
            self._sideband_button_group.addButton(radio_button, i)
        self._sideband_callback = lambda i: Qt.QMetaObject.invokeMethod(self._sideband_button_group, "updateButtonChecked", Qt.Q_ARG("int", self._sideband_options.index(i)))
        self._sideband_callback(self.sideband)
        self._sideband_button_group.buttonClicked[int].connect(
            lambda i: self.set_sideband(self._sideband_options[i]))
        self.top_grid_layout.addWidget(self._sideband_group_box, 2, 4, 1, 3)
        for r in range(2, 3):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(4, 7):
            self.top_grid_layout.setColumnStretch(c, 1)
        self._rfPwr_range = Range(-140, -30, 1, rfPwrDefault, 200)
        self._rfPwr_win = RangeWidget(self._rfPwr_range, self.set_rfPwr, "RF Output Power", "counter_slider", float, QtCore.Qt.Horizontal)
        self.top_grid_layout.addWidget(self._rfPwr_win, 1, 5, 1, 4)
        for r in range(1, 2):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(5, 9):
            self.top_grid_layout.setColumnStretch(c, 1)
        self._modIndex_range = Range(0, 10, 0.001, modIndexDefault, 200)
        self._modIndex_win = RangeWidget(self._modIndex_range, self.set_modIndex, "Modulation Index", "counter_slider", float, QtCore.Qt.Horizontal)
        self.top_grid_layout.addWidget(self._modIndex_win, 1, 0, 1, 4)
        for r in range(1, 2):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(0, 4):
            self.top_grid_layout.setColumnStretch(c, 1)
        self._centerFreq_range = Range(50, 2200, 0.01, cfDefault, 200)
        self._centerFreq_win = RangeWidget(self._centerFreq_range, self.set_centerFreq, "Center Frequency (MHz)", "counter", float, QtCore.Qt.Horizontal)
        self.top_grid_layout.addWidget(self._centerFreq_win, 0, 5, 1, 3)
        for r in range(0, 1):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(5, 8):
            self.top_grid_layout.setColumnStretch(c, 1)
        # Create the options list
        self._carrier_options = [0, 1]
        # Create the labels list
        self._carrier_labels = ['Suppressed', 'Full']
        # Create the combo box
        # Create the radio buttons
        self._carrier_group_box = Qt.QGroupBox("Carrier Condition" + ": ")
        self._carrier_box = Qt.QHBoxLayout()
        class variable_chooser_button_group(Qt.QButtonGroup):
            def __init__(self, parent=None):
                Qt.QButtonGroup.__init__(self, parent)
            @pyqtSlot(int)
            def updateButtonChecked(self, button_id):
                self.button(button_id).setChecked(True)
        self._carrier_button_group = variable_chooser_button_group()
        self._carrier_group_box.setLayout(self._carrier_box)
        for i, _label in enumerate(self._carrier_labels):
            radio_button = Qt.QRadioButton(_label)
            self._carrier_box.addWidget(radio_button)
            self._carrier_button_group.addButton(radio_button, i)
        self._carrier_callback = lambda i: Qt.QMetaObject.invokeMethod(self._carrier_button_group, "updateButtonChecked", Qt.Q_ARG("int", self._carrier_options.index(i)))
        self._carrier_callback(self.carrier)
        self._carrier_button_group.buttonClicked[int].connect(
            lambda i: self.set_carrier(self._carrier_options[i]))
        self.top_grid_layout.addWidget(self._carrier_group_box, 2, 0, 1, 4)
        for r in range(2, 3):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(0, 4):
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
        self.uhd_usrp_sink_0.set_samp_rate(samp_rate)
        self.uhd_usrp_sink_0.set_time_now(uhd.time_spec(time.time()), uhd.ALL_MBOARDS)

        self.uhd_usrp_sink_0.set_center_freq(centerFreq*1e6-330e3, 0)
        self.uhd_usrp_sink_0.set_antenna("TX/RX", 0)
        self.uhd_usrp_sink_0.set_gain((rfPwr+50)*(rfPwr>-50), 0)
        self.rational_resampler_xxx_1 = filter.rational_resampler_ccc(
                interpolation=1,
                decimation=10,
                taps=[],
                fractional_bw=0)
        self.rational_resampler_xxx_0 = filter.rational_resampler_ccc(
                interpolation=40,
                decimation=1,
                taps=[],
                fractional_bw=0)
        self.qtgui_time_sink_x_0 = qtgui.time_sink_c(
            25000, #size
            samp_rate, #samp_rate
            'Baseband Time Domain', #name
            1, #number of inputs
            None # parent
        )
        self.qtgui_time_sink_x_0.set_update_time(0.10)
        self.qtgui_time_sink_x_0.set_y_axis(-1, 1)

        self.qtgui_time_sink_x_0.set_y_label('Amplitude', "")

        self.qtgui_time_sink_x_0.enable_tags(True)
        self.qtgui_time_sink_x_0.set_trigger_mode(qtgui.TRIG_MODE_FREE, qtgui.TRIG_SLOPE_POS, 0.0, 0, 0, "")
        self.qtgui_time_sink_x_0.enable_autoscale(False)
        self.qtgui_time_sink_x_0.enable_grid(True)
        self.qtgui_time_sink_x_0.enable_axis_labels(True)
        self.qtgui_time_sink_x_0.enable_control_panel(False)
        self.qtgui_time_sink_x_0.enable_stem_plot(False)


        labels = ['Real', 'Imag', 'Signal 3', 'Signal 4', 'Signal 5',
            'Signal 6', 'Signal 7', 'Signal 8', 'Signal 9', 'Signal 10']
        widths = [1, 1, 1, 1, 1,
            1, 1, 1, 1, 1]
        colors = ['blue', 'red', 'green', 'black', 'cyan',
            'magenta', 'yellow', 'dark red', 'dark green', 'dark blue']
        alphas = [1.0, 1.0, 1.0, 1.0, 1.0,
            1.0, 1.0, 1.0, 1.0, 1.0]
        styles = [1, 1, 1, 1, 1,
            1, 1, 1, 1, 1]
        markers = [-1, -1, -1, -1, -1,
            -1, -1, -1, -1, -1]


        for i in range(2):
            if len(labels[i]) == 0:
                if (i % 2 == 0):
                    self.qtgui_time_sink_x_0.set_line_label(i, "Re{{Data {0}}}".format(i/2))
                else:
                    self.qtgui_time_sink_x_0.set_line_label(i, "Im{{Data {0}}}".format(i/2))
            else:
                self.qtgui_time_sink_x_0.set_line_label(i, labels[i])
            self.qtgui_time_sink_x_0.set_line_width(i, widths[i])
            self.qtgui_time_sink_x_0.set_line_color(i, colors[i])
            self.qtgui_time_sink_x_0.set_line_style(i, styles[i])
            self.qtgui_time_sink_x_0.set_line_marker(i, markers[i])
            self.qtgui_time_sink_x_0.set_line_alpha(i, alphas[i])

        self._qtgui_time_sink_x_0_win = sip.wrapinstance(self.qtgui_time_sink_x_0.qwidget(), Qt.QWidget)
        self.top_grid_layout.addWidget(self._qtgui_time_sink_x_0_win, 5, 0, 5, 7)
        for r in range(5, 10):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(0, 7):
            self.top_grid_layout.setColumnStretch(c, 1)
        self.qtgui_freq_sink_x_0 = qtgui.freq_sink_c(
            4096, #size
            window.WIN_BLACKMAN_hARRIS, #wintype
            centerFreq*1e6, #fc
            samp_rate/10, #bw
            'Modulated Spectrum', #name
            1,
            None # parent
        )
        self.qtgui_freq_sink_x_0.set_update_time(0.10)
        self.qtgui_freq_sink_x_0.set_y_axis(-140, 10)
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
        self.top_grid_layout.addWidget(self._qtgui_freq_sink_x_0_win, 10, 0, 5, 10)
        for r in range(10, 15):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(0, 10):
            self.top_grid_layout.setColumnStretch(c, 1)
        self.qtgui_const_sink_x_0 = qtgui.const_sink_c(
            2500, #size
            'IQ Polar Plot', #name
            1, #number of inputs
            None # parent
        )
        self.qtgui_const_sink_x_0.set_update_time(0.10)
        self.qtgui_const_sink_x_0.set_y_axis(-1.25, 1.25)
        self.qtgui_const_sink_x_0.set_x_axis(-1.25, 1.25)
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
        markers = [0, 0, 0, 0, 0,
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
        self.top_grid_layout.addWidget(self._qtgui_const_sink_x_0_win, 5, 7, 5, 3)
        for r in range(5, 10):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(7, 10):
            self.top_grid_layout.setColumnStretch(c, 1)
        self._modName_tool_bar = Qt.QToolBar(self)

        if None:
            self._modName_formatter = None
        else:
            self._modName_formatter = lambda x: str(x)

        self._modName_tool_bar.addWidget(Qt.QLabel("Modulation: "))
        self._modName_label = Qt.QLabel(str(self._modName_formatter(self.modName)))
        self._modName_tool_bar.addWidget(self._modName_label)
        self.top_grid_layout.addWidget(self._modName_tool_bar, 0, 1, 1, 2)
        for r in range(0, 1):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(1, 3):
            self.top_grid_layout.setColumnStretch(c, 1)
        self.hilbert_fc_0 = filter.hilbert_fc(1500, window.WIN_HAMMING, 6.76)
        self.blocks_selector_2 = blocks.selector(gr.sizeof_gr_complex*1,sideband,0)
        self.blocks_selector_2.set_enabled(True)
        self.blocks_multiply_xx_0 = blocks.multiply_vcc(1)
        self.blocks_multiply_const_vxx_3 = blocks.multiply_const_cc(0.5)
        self.blocks_multiply_const_vxx_0 = blocks.multiply_const_ff(sidebandType)
        self.blocks_float_to_complex_0_0 = blocks.float_to_complex(1)
        self.blocks_float_to_complex_0 = blocks.float_to_complex(1)
        self.blocks_complex_to_float_0 = blocks.complex_to_float(1)
        self.blocks_add_const_vxx_0 = blocks.add_const_ff(carrier)
        self.analog_sig_source_x_1 = analog.sig_source_c(samp_rate, analog.GR_COS_WAVE, 330e3, 10**((rfPwr<=-50)*(rfPwr+50)/20)*0.95, 0, 0)
        self.analog_sig_source_x_0 = analog.sig_source_f(50e3, analog.GR_COS_WAVE, sineFreq, modIndex, 0, 0)


        ##################################################
        # Connections
        ##################################################
        self.connect((self.analog_sig_source_x_0, 0), (self.blocks_add_const_vxx_0, 0))
        self.connect((self.analog_sig_source_x_1, 0), (self.blocks_multiply_xx_0, 1))
        self.connect((self.blocks_add_const_vxx_0, 0), (self.blocks_float_to_complex_0, 0))
        self.connect((self.blocks_add_const_vxx_0, 0), (self.hilbert_fc_0, 0))
        self.connect((self.blocks_complex_to_float_0, 0), (self.blocks_float_to_complex_0_0, 0))
        self.connect((self.blocks_complex_to_float_0, 1), (self.blocks_multiply_const_vxx_0, 0))
        self.connect((self.blocks_float_to_complex_0, 0), (self.blocks_selector_2, 0))
        self.connect((self.blocks_float_to_complex_0_0, 0), (self.blocks_multiply_xx_0, 0))
        self.connect((self.blocks_float_to_complex_0_0, 0), (self.qtgui_const_sink_x_0, 0))
        self.connect((self.blocks_float_to_complex_0_0, 0), (self.qtgui_time_sink_x_0, 0))
        self.connect((self.blocks_float_to_complex_0_0, 0), (self.rational_resampler_xxx_1, 0))
        self.connect((self.blocks_multiply_const_vxx_0, 0), (self.blocks_float_to_complex_0_0, 1))
        self.connect((self.blocks_multiply_const_vxx_3, 0), (self.blocks_complex_to_float_0, 0))
        self.connect((self.blocks_multiply_xx_0, 0), (self.uhd_usrp_sink_0, 0))
        self.connect((self.blocks_selector_2, 0), (self.rational_resampler_xxx_0, 0))
        self.connect((self.hilbert_fc_0, 0), (self.blocks_selector_2, 1))
        self.connect((self.rational_resampler_xxx_0, 0), (self.blocks_multiply_const_vxx_3, 0))
        self.connect((self.rational_resampler_xxx_1, 0), (self.qtgui_freq_sink_x_0, 0))


    def closeEvent(self, event):
        self.settings = Qt.QSettings("GNU Radio", "amSineGenerator")
        self.settings.setValue("geometry", self.saveGeometry())
        self.stop()
        self.wait()

        event.accept()

    def get_sineFreqDefault(self):
        return self.sineFreqDefault

    def set_sineFreqDefault(self, sineFreqDefault):
        self.sineFreqDefault = sineFreqDefault
        self.set_sineFreq(self.sineFreqDefault)

    def get_sidebandTypeDefault(self):
        return self.sidebandTypeDefault

    def set_sidebandTypeDefault(self, sidebandTypeDefault):
        self.sidebandTypeDefault = sidebandTypeDefault
        self.set_sidebandType(self.sidebandTypeDefault)

    def get_sidebandDefault(self):
        return self.sidebandDefault

    def set_sidebandDefault(self, sidebandDefault):
        self.sidebandDefault = sidebandDefault
        self.set_sideband(self.sidebandDefault)

    def get_rfPwrDefault(self):
        return self.rfPwrDefault

    def set_rfPwrDefault(self, rfPwrDefault):
        self.rfPwrDefault = rfPwrDefault
        self.set_rfPwr(self.rfPwrDefault)

    def get_modIndexDefault(self):
        return self.modIndexDefault

    def set_modIndexDefault(self, modIndexDefault):
        self.modIndexDefault = modIndexDefault
        self.set_modIndex(self.modIndexDefault)

    def get_cfDefault(self):
        return self.cfDefault

    def set_cfDefault(self, cfDefault):
        self.cfDefault = cfDefault
        self.set_centerFreq(self.cfDefault)

    def get_carrierDefault(self):
        return self.carrierDefault

    def set_carrierDefault(self, carrierDefault):
        self.carrierDefault = carrierDefault
        self.set_carrier(self.carrierDefault)

    def get_usrpNum(self):
        return self.usrpNum

    def set_usrpNum(self, usrpNum):
        self.usrpNum = usrpNum
        Qt.QMetaObject.invokeMethod(self._usrpNum_label, "setText", Qt.Q_ARG("QString", str(self._usrpNum_formatter(self.usrpNum))))

    def get_sineFreq(self):
        return self.sineFreq

    def set_sineFreq(self, sineFreq):
        self.sineFreq = sineFreq
        self.analog_sig_source_x_0.set_frequency(self.sineFreq)

    def get_sidebandType(self):
        return self.sidebandType

    def set_sidebandType(self, sidebandType):
        self.sidebandType = sidebandType
        self._sidebandType_callback(self.sidebandType)
        self.blocks_multiply_const_vxx_0.set_k(self.sidebandType)

    def get_sideband(self):
        return self.sideband

    def set_sideband(self, sideband):
        self.sideband = sideband
        self._sideband_callback(self.sideband)
        self.blocks_selector_2.set_input_index(self.sideband)

    def get_samp_rate(self):
        return self.samp_rate

    def set_samp_rate(self, samp_rate):
        self.samp_rate = samp_rate
        self.analog_sig_source_x_1.set_sampling_freq(self.samp_rate)
        self.qtgui_freq_sink_x_0.set_frequency_range(self.centerFreq*1e6, self.samp_rate/10)
        self.qtgui_time_sink_x_0.set_samp_rate(self.samp_rate)
        self.uhd_usrp_sink_0.set_samp_rate(self.samp_rate)

    def get_rfPwr(self):
        return self.rfPwr

    def set_rfPwr(self, rfPwr):
        self.rfPwr = rfPwr
        self.analog_sig_source_x_1.set_amplitude(10**((self.rfPwr<=-50)*(self.rfPwr+50)/20)*0.95)
        self.uhd_usrp_sink_0.set_gain((self.rfPwr+50)*(self.rfPwr>-50), 0)

    def get_outputIpAddr(self):
        return self.outputIpAddr

    def set_outputIpAddr(self, outputIpAddr):
        self.outputIpAddr = outputIpAddr

    def get_modName(self):
        return self.modName

    def set_modName(self, modName):
        self.modName = modName
        Qt.QMetaObject.invokeMethod(self._modName_label, "setText", Qt.Q_ARG("QString", str(self._modName_formatter(self.modName))))

    def get_modIndex(self):
        return self.modIndex

    def set_modIndex(self, modIndex):
        self.modIndex = modIndex
        self.analog_sig_source_x_0.set_amplitude(self.modIndex)

    def get_mikePort(self):
        return self.mikePort

    def set_mikePort(self, mikePort):
        self.mikePort = mikePort

    def get_mikeIpAddr(self):
        return self.mikeIpAddr

    def set_mikeIpAddr(self, mikeIpAddr):
        self.mikeIpAddr = mikeIpAddr

    def get_inputSelectDefault(self):
        return self.inputSelectDefault

    def set_inputSelectDefault(self, inputSelectDefault):
        self.inputSelectDefault = inputSelectDefault

    def get_centerFreq(self):
        return self.centerFreq

    def set_centerFreq(self, centerFreq):
        self.centerFreq = centerFreq
        self.qtgui_freq_sink_x_0.set_frequency_range(self.centerFreq*1e6, self.samp_rate/10)
        self.uhd_usrp_sink_0.set_center_freq(self.centerFreq*1e6-330e3, 0)

    def get_carrier(self):
        return self.carrier

    def set_carrier(self, carrier):
        self.carrier = carrier
        self._carrier_callback(self.carrier)
        self.blocks_add_const_vxx_0.set_k(self.carrier)




def main(top_block_cls=amSineGenerator, options=None, app=None):
    if app is None:
        if StrictVersion("4.5.0") <= StrictVersion(Qt.qVersion()) < StrictVersion("5.0.0"):
            style = gr.prefs().get_string('qtgui', 'style', 'raster')
            Qt.QApplication.setGraphicsSystem(style)
        app = Qt.QApplication(sys.argv)

    tb = top_block_cls()
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
