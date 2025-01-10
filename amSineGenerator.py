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
        
        # Pull in IP list of transmit SDRs
        ipFile=open("usrpXmit.cfg","r") # Open the file
        ipList=ipFile.readlines() # Read in list of SDR IP addresses
        N=len(ipList) # Number of systems available
                
        # Enter transmit SDR to use
        print("Enter signal generator number (1 - ",int(N),")")
        ipNum=N+1
        while(ipNum==(N+1)):
            ipNum=eval(input(": ") or "1")
            if (ipNum < 1)+(ipNum > N):
                print("Enter a number between 1 - ",int(N),")")
                ipNum=N+1
            else:
                break
        ipXmitAddr=ipList[ipNum-1] # IP address of transmit SDR
        mikePort=2020+ipNum
        
        # Input center frequency
        cf=0
        while(cf==0):
            cf=eval(input("Center frequency (MHz, 50 - 2200, default = 300): ") or "300")
            if (cf<50)+(cf>2200):
                print("Center frequency must be between 50 - 2200 MHz.")
                cf=0
            else:
                break
                
        # Input output power
        pwr=0
        while(pwr==0):
            pwr=eval(input("Enter input power level (dBm, -30 - -80, default= -50): ") or "-50")
            if(pwr<-80)+(pwr>-30):
                print("Power level must be between -30 - -80 dBm.")
                pwr=0
            else:
                break
        if(pwr<-50):
            rfGain=0
            atten=pwr+50
        else:
            atten=0
            rfGain=pwr+50
        rfGainDefault=rfGain
        attenDefault=atten
            
        # Enter carrier condition (full / suppressed)
        carrierDefault=-1
        while(carrierDefault<0):
            carrierDefault=eval(input("Carrier condition (1 = full / 0 = suppressed, default = 1): ") or "1")
            if(carrierDefault<0)+(carrierDefault>1):
                print("Value must be 0 or 1.")
                carrierDefault=-1
            else:
                break
                
        # Enter double or single sideband
        sidebandDefaultVal=0
        while(sidebandDefaultVal==0):
            sidebandDefaultVal=eval(input("Sideband condition (1 = single, 2 = double, default = 2): ") or "2")
            if(sidebandDefaultVal<1)+(sidebandDefaultVal>2):
                print("Value must be 1 (for single sideband) or 2 (for double sideband).")
                sidebandDefaultVal=0
            else:
                sidebandDefault=abs(sidebandDefaultVal-2)
                break
                
        # If single sideband, enter lower or upper
        if(sidebandDefault==1):
            sidebandTypeDefaultVal=0
            while(sidebandTypeDefaultVal==0):
                sidebandTypeDefaultVal=eval(input("1 = lower, 2 = upper, default = 2: ") or "2")
                if(sidebandTypeDefaultVal<1)+(sidebandTypeDefaultVal>2):
                    print("Value must be 1 (lower sideband) or 2 (upper sideband).")
                    sidebandTypeDefaultVal=0
                else:
                    sidebandTypeDefault=2*(sidebandTypeDefaultVal-1.5)
                    break
        else:
            sidebandTypeDefault=1
        
        # Enter frequency of sinewave
            sineFreq=0
            while(sineFreq==0):
                sineFreq=eval(input("Frequency of sinewave (Hz, 0.1 - 20000, default = 1000): ") or "1000")
                if(sineFreq<0.1)+(sineFreq>20e3):
                    print("Frequency must be between 0.1 - 20000 Hz.")
                    sineFreq=0
                else:
                    break
        sineFreqDefault=sineFreq
        
        input("All settings ready. Press Enter to begin transmitting.")

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




def main(top_block_cls=amSineGenerator, options=None):

    if StrictVersion("4.5.0") <= StrictVersion(Qt.qVersion()) < StrictVersion("5.0.0"):
        style = gr.prefs().get_string('qtgui', 'style', 'raster')
        Qt.QApplication.setGraphicsSystem(style)
    qapp = Qt.QApplication(sys.argv)

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

    qapp.exec_()

if __name__ == '__main__':
    main()
