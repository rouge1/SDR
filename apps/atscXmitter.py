#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#
# SPDX-License-Identifier: GPL-3.0
#
# GNU Radio Python Flow Graph
# Title: ATSC Transmitter
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

# Standard library imports
import math
import signal
import sys
import time
import os
import json

# Third party imports
from PyQt5 import Qt, QtCore # type: ignore
import sip # type: ignore # type: ignore
import pmt # type: ignore

from gnuradio import blocks, dtv, filter, gr, qtgui, uhd # type: ignore
from gnuradio.filter import firdes # type: ignore
from gnuradio.fft import window # type: ignore
from gnuradio.qtgui import Range, RangeWidget # type: ignore

# Local imports
from apps.utils import apply_dark_theme, read_settings

class ConfigDialog(Qt.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ATSC Transmitter Configuration")
        self.layout = Qt.QVBoxLayout(self)
        self.config_dir = "config"
        self.config_file = os.path.join(self.config_dir, "atsc_config.json")
        
        # Read settings from window_settings.json
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
        self.create_power_control()
        self.create_file_selector()
        
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

    def create_file_selector(self):
        self.file_combo = Qt.QComboBox()
        
        try:
            with open("tsFileList.txt", "r") as f:
                self.ts_files = f.readlines()
                for ts_file in self.ts_files:
                    display_name = ts_file.strip()
                    self.file_combo.addItem(display_name, display_name)
        except:
            self.file_combo.addItem("No TS files found")
            self.file_combo.setEnabled(False)
            
        self.layout.addWidget(Qt.QLabel("Select Transport Stream File:"))
        self.layout.addWidget(self.file_combo)

    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    
                self.usrp_combo.setCurrentIndex(config.get('usrp_index', 0))
                self.cf_slider.setValue(config.get('center_freq', 300))
                self.pwr_slider.setValue(config.get('power_level', -50))
                
                # Try to find saved file in current file list
                saved_file = config.get('ts_file')
                if saved_file:
                    index = self.file_combo.findData(saved_file)
                    if index >= 0:
                        self.file_combo.setCurrentIndex(index)
            except:
                pass
        else:
            os.makedirs(self.config_dir, exist_ok=True)

    def save_config(self):
        config = {
            'usrp_index': self.usrp_combo.currentIndex(),
            'center_freq': self.cf_slider.value(),
            'power_level': self.pwr_slider.value(),
            'ts_file': self.file_combo.currentData()
        }
        
        with open(self.config_file, 'w') as f:
            json.dump(config, f, indent=4)

    def accept(self):
        self.save_config()
        super().accept()

    def get_values(self):
        ipNum = self.usrp_combo.currentIndex() + 1
        ipXmitAddr = self.ipList[self.usrp_combo.currentIndex()].strip()
        pwr = self.pwr_slider.value()
        
        # Calculate RF gain and attenuation
        if pwr < -50:
            rfGain = 0
            atten = pwr + 50
        else:
            atten = 0
            rfGain = pwr + 50
            
        return {
            'ipNum': ipNum,
            'ipXmitAddr': ipXmitAddr,
            'cf': self.cf_slider.value(),
            'pwr': pwr,
            'rfGain': rfGain,
            'atten': atten,
            'ts_file': self.file_combo.currentData()
        }

class atscXmitter2(gr.top_block, Qt.QWidget):

    def __init__(self, config_values=None):
        gr.top_block.__init__(self, "ATSC Transmitter", catch_exceptions=True)
        Qt.QWidget.__init__(self)
        self.setWindowTitle("ATSC Transmitter")
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

        self.settings = Qt.QSettings("GNU Radio", "atscXmitter2")

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
        pwr = values['pwr']
        rfGain = values['rfGain']
        atten = values['atten']
        self.ts_file = values['ts_file']

        ##################################################
        # Variables
        ##################################################
        self.symbol_rate = symbol_rate = 4500000.0 / 286 * 684
        self.rfPwrDefault = rfPwrDefault = pwr
        self.cfDefault = cfDefault = cf
        self.atscFileName = atscFileName = self.ts_file
        self.samp_rate = samp_rate = 12.5e6
        self.rfPwr = rfPwr = rfPwrDefault
        self.pilot_freq = pilot_freq = (6000000.0 - (symbol_rate / 2)) / 2
        self.outputIpAddr = outputIpAddr = ipXmitAddr
        self.modulation = modulation = 'ATSC'
        self.fileBeingBroadcast = fileBeingBroadcast = atscFileName
        self.cf = cf 

        ##################################################
        # Blocks
        ##################################################
        self._rfPwr_range = Range(-80, -30, 1, rfPwrDefault, 200)
        self._rfPwr_win = RangeWidget(self._rfPwr_range, self.set_rfPwr, "RF Output Power", "counter_slider", float, QtCore.Qt.Horizontal)
        self.top_grid_layout.addWidget(self._rfPwr_win, 1, 0, 1, 5)
        for r in range(1, 2):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(0, 5):
            self.top_grid_layout.setColumnStretch(c, 1)
        self._cf_range = Range(50, 2200, 0.1, cfDefault, 200)
        self._cf_win = RangeWidget(self._cf_range, self.set_cf, "Center Frequency (MHz)", "counter", float, QtCore.Qt.Horizontal)
        self.top_grid_layout.addWidget(self._cf_win, 0, 0, 1, 5)
        for r in range(0, 1):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(0, 5):
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

        self.uhd_usrp_sink_0.set_center_freq(cf*1e6, 0)
        self.uhd_usrp_sink_0.set_antenna("TX/RX", 0)
        self.uhd_usrp_sink_0.set_gain((rfPwr+50)*(rfPwr>-50), 0)
        self.rational_resampler_xxx_1 = filter.rational_resampler_ccc(
                interpolation=25,
                decimation=57,
                taps=[],
                fractional_bw=0)
        self.rational_resampler_xxx_0 = filter.rational_resampler_ccc(
                interpolation=143,
                decimation=54,
                taps=[],
                fractional_bw=0)
        self.qtgui_freq_sink_x_0 = qtgui.freq_sink_c(
            2048, #size
            window.WIN_BLACKMAN_hARRIS, #wintype
            cf*1e6, #fc
            samp_rate, #bw
            "", #name
            1,
            None # parent
        )
        self.qtgui_freq_sink_x_0.set_update_time(0.10)
        self.qtgui_freq_sink_x_0.set_y_axis(-140, -20)
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
        self.top_grid_layout.addWidget(self._qtgui_freq_sink_x_0_win, 3, 0, 10, 10)
        for r in range(3, 13):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(0, 10):
            self.top_grid_layout.setColumnStretch(c, 1)
        self._modulation_tool_bar = Qt.QToolBar(self)

        if None:
            self._modulation_formatter = None
        else:
            self._modulation_formatter = lambda x: str(x)

        self._modulation_tool_bar.addWidget(Qt.QLabel("Modulation: "))
        self._modulation_label = Qt.QLabel(str(self._modulation_formatter(self.modulation)))
        self._modulation_tool_bar.addWidget(self._modulation_label)
        self.top_grid_layout.addWidget(self._modulation_tool_bar, 0, 5, 1, 5)
        for r in range(0, 1):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(5, 10):
            self.top_grid_layout.setColumnStretch(c, 1)
        self._fileBeingBroadcast_tool_bar = Qt.QToolBar(self)

        if None:
            self._fileBeingBroadcast_formatter = None
        else:
            self._fileBeingBroadcast_formatter = lambda x: str(x)

        self._fileBeingBroadcast_tool_bar.addWidget(Qt.QLabel("File Being Broadcast: "))
        self._fileBeingBroadcast_label = Qt.QLabel(str(self._fileBeingBroadcast_formatter(self.fileBeingBroadcast)))
        self._fileBeingBroadcast_tool_bar.addWidget(self._fileBeingBroadcast_label)
        self.top_grid_layout.addWidget(self._fileBeingBroadcast_tool_bar, 2, 0, 1, 5)
        for r in range(2, 3):
            self.top_grid_layout.setRowStretch(r, 1)
        for c in range(0, 5):
            self.top_grid_layout.setColumnStretch(c, 1)
        self.fft_filter_xxx_0 = filter.fft_filter_ccc(1, firdes.root_raised_cosine(0.11, symbol_rate, symbol_rate/2, 0.1152, 200), 1)
        self.fft_filter_xxx_0.declare_sample_delay(0)
        self.dtv_dvbs2_modulator_bc_0 = dtv.dvbs2_modulator_bc(
            dtv.FECFRAME_NORMAL,
            dtv.C1_4,
            dtv.MOD_8VSB,
            dtv.INTERPOLATION_OFF)
        self.dtv_atsc_trellis_encoder_0 = dtv.atsc_trellis_encoder()
        self.dtv_atsc_rs_encoder_0 = dtv.atsc_rs_encoder()
        self.dtv_atsc_randomizer_0 = dtv.atsc_randomizer()
        self.dtv_atsc_pad_0 = dtv.atsc_pad()
        self.dtv_atsc_interleaver_0 = dtv.atsc_interleaver()
        self.dtv_atsc_field_sync_mux_0 = dtv.atsc_field_sync_mux()
        self.blocks_vector_to_stream_1 = blocks.vector_to_stream(gr.sizeof_char*1, 1024)
        self.blocks_rotator_cc_0 = blocks.rotator_cc(((-3000000.0 + pilot_freq) / symbol_rate) * (math.pi * 2), False)
        self.blocks_multiply_const_vxx_0 = blocks.multiply_const_cc(10**((rfPwr<=-50)*(rfPwr+50)/20))
        self.blocks_keep_m_in_n_0 = blocks.keep_m_in_n(gr.sizeof_char, 832, 1024, 4)
        self.blocks_file_source_0 = blocks.file_source(gr.sizeof_char*1, atscFileName, True, 0, 0)
        self.blocks_file_source_0.set_begin_tag(pmt.PMT_NIL)


        ##################################################
        # Connections
        ##################################################
        self.connect((self.blocks_file_source_0, 0), (self.dtv_atsc_pad_0, 0))
        self.connect((self.blocks_keep_m_in_n_0, 0), (self.dtv_dvbs2_modulator_bc_0, 0))
        self.connect((self.blocks_multiply_const_vxx_0, 0), (self.uhd_usrp_sink_0, 0))
        self.connect((self.blocks_rotator_cc_0, 0), (self.fft_filter_xxx_0, 0))
        self.connect((self.blocks_vector_to_stream_1, 0), (self.blocks_keep_m_in_n_0, 0))
        self.connect((self.dtv_atsc_field_sync_mux_0, 0), (self.blocks_vector_to_stream_1, 0))
        self.connect((self.dtv_atsc_interleaver_0, 0), (self.dtv_atsc_trellis_encoder_0, 0))
        self.connect((self.dtv_atsc_pad_0, 0), (self.dtv_atsc_randomizer_0, 0))
        self.connect((self.dtv_atsc_randomizer_0, 0), (self.dtv_atsc_rs_encoder_0, 0))
        self.connect((self.dtv_atsc_rs_encoder_0, 0), (self.dtv_atsc_interleaver_0, 0))
        self.connect((self.dtv_atsc_trellis_encoder_0, 0), (self.dtv_atsc_field_sync_mux_0, 0))
        self.connect((self.dtv_dvbs2_modulator_bc_0, 0), (self.blocks_rotator_cc_0, 0))
        self.connect((self.fft_filter_xxx_0, 0), (self.rational_resampler_xxx_0, 0))
        self.connect((self.rational_resampler_xxx_0, 0), (self.rational_resampler_xxx_1, 0))
        self.connect((self.rational_resampler_xxx_1, 0), (self.blocks_multiply_const_vxx_0, 0))
        self.connect((self.rational_resampler_xxx_1, 0), (self.qtgui_freq_sink_x_0, 0))


    def closeEvent(self, event):
        self.settings = Qt.QSettings("GNU Radio", "atscXmitter2")
        self.settings.setValue("geometry", self.saveGeometry())
        self.stop()
        self.wait()

        event.accept()

    def get_symbol_rate(self):
        return self.symbol_rate

    def set_symbol_rate(self, symbol_rate):
        self.symbol_rate = symbol_rate
        self.set_pilot_freq((6000000.0 - (self.symbol_rate / 2)) / 2)
        self.blocks_rotator_cc_0.set_phase_inc(((-3000000.0 + self.pilot_freq) / self.symbol_rate) * (math.pi * 2))
        self.fft_filter_xxx_0.set_taps(firdes.root_raised_cosine(0.11, self.symbol_rate, self.symbol_rate/2, 0.1152, 200))

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

    def get_atscFileName(self):
        return self.atscFileName

    def set_atscFileName(self, atscFileName):
        self.atscFileName = atscFileName
        self.set_fileBeingBroadcast(self.atscFileName)
        self.blocks_file_source_0.open(self.atscFileName, True)

    def get_samp_rate(self):
        return self.samp_rate

    def set_samp_rate(self, samp_rate):
        self.samp_rate = samp_rate
        self.qtgui_freq_sink_x_0.set_frequency_range(self.cf*1e6, self.samp_rate)
        self.uhd_usrp_sink_0.set_samp_rate(self.samp_rate)

    def get_rfPwr(self):
        return self.rfPwr

    def set_rfPwr(self, rfPwr):
        self.rfPwr = rfPwr
        self.blocks_multiply_const_vxx_0.set_k(10**((self.rfPwr<=-50)*(self.rfPwr+50)/20))
        self.uhd_usrp_sink_0.set_gain((self.rfPwr+50)*(self.rfPwr>-50), 0)

    def get_pilot_freq(self):
        return self.pilot_freq

    def set_pilot_freq(self, pilot_freq):
        self.pilot_freq = pilot_freq
        self.blocks_rotator_cc_0.set_phase_inc(((-3000000.0 + self.pilot_freq) / self.symbol_rate) * (math.pi * 2))

    def get_outputIpAddr(self):
        return self.outputIpAddr

    def set_outputIpAddr(self, outputIpAddr):
        self.outputIpAddr = outputIpAddr

    def get_modulation(self):
        return self.modulation

    def set_modulation(self, modulation):
        self.modulation = modulation
        Qt.QMetaObject.invokeMethod(self._modulation_label, "setText", Qt.Q_ARG("QString", str(self._modulation_formatter(self.modulation))))

    def get_fileBeingBroadcast(self):
        return self.fileBeingBroadcast

    def set_fileBeingBroadcast(self, fileBeingBroadcast):
        self.fileBeingBroadcast = fileBeingBroadcast
        Qt.QMetaObject.invokeMethod(self._fileBeingBroadcast_label, "setText", Qt.Q_ARG("QString", str(self._fileBeingBroadcast_formatter(self.fileBeingBroadcast))))

    def get_cf(self):
        return self.cf

    def set_cf(self, cf):
        self.cf = cf
        self.qtgui_freq_sink_x_0.set_frequency_range(self.cf*1e6, self.samp_rate)
        self.uhd_usrp_sink_0.set_center_freq(self.cf*1e6, 0)

def main(top_block_cls=ppmookLiveAudioXmitter, options=None, app=None, config_values=None):
    if app is None:
        if StrictVersion("4.5.0") <= StrictVersion(Qt.qVersion()) < StrictVersion("5.0.0"):
            style = gr.prefs().get_string('qtgui', 'style', 'raster')
            Qt.QApplication.setGraphicsSystem(style)
        app = Qt.QApplication(sys.argv)
        
        # Apply dark theme to the application
        apply_dark_theme(app)

    tb = top_block_cls(config_values)
    tb.start()
    tb.show()

    def sig_handler(sig=None, frame=None):
        def _signal_handler():
            tb.stop()
            tb.wait()
            app.quit()  # Changed from Qt.QApplication.quit()
        
        # Use QTimer to handle the signal in the Qt event loop
        Qt.QTimer.singleShot(0, _signal_handler)

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    # Modified event loop handling
    timer = Qt.QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None)

    def handle_close():
        tb.stop()
        tb.wait()
        app.quit()  # Use app instance instead of Qt.QApplication

    # Connect close event
    tb.closeEvent = lambda event: handle_close()

    return app.exec_()

if __name__ == '__main__':
    main()

