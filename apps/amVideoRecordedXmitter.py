#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#
# SPDX-License-Identifier: GPL-3.0
#
# GNU Radio Python Flow Graph
# Title: AM Recorded Video Xmitter
# Author: instructor
# GNU Radio version: v3.10-compat-xxx-xunknown

from distutils.version import StrictVersion # type: ignore

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

# Third party imports 
from PyQt5 import Qt, QtCore # type: ignore
import sip # type: ignore

from gnuradio import blocks, filter, gr, qtgui, uhd # type: ignore
from gnuradio.fft import window # type: ignore
import pmt # type: ignore

# Local imports
from apps.utils import apply_dark_theme, read_settings

class ConfigDialog(Qt.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AM Video Transmitter Configuration")
        self.layout = Qt.QVBoxLayout(self)
        self.config_dir = "config"
        self.config_file = os.path.join(self.config_dir, "amVideoTransmitter_config.json")
        
        # Read settings from window_settings.json
        settings = read_settings()
        self.ipList = settings['ip_addresses']
        self.N = len(self.ipList)
        
        # Add OK/Cancel buttons
        self.button_box = Qt.QDialogButtonBox(
            Qt.QDialogButtonBox.Ok | Qt.QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        
        # Create all the input widgets
        self.create_usrp_selector()
        self.create_frequency_control()
        self.create_power_control()
        self.create_video_selector()
        self.create_video_invert_control()
        
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
        self.power_layout = Qt.QHBoxLayout()
        self.power_slider = Qt.QSlider(QtCore.Qt.Horizontal)
        self.power_slider.setMinimum(0)
        self.power_slider.setMaximum(20)
        self.power_slider.setValue(0)
        self.power_label = Qt.QLabel("Output Power: 0 dBm")
        self.power_slider.valueChanged.connect(
            lambda v: self.power_label.setText(f"Output Power: {v} dBm"))
        self.power_layout.addWidget(self.power_label)
        self.power_layout.addWidget(self.power_slider)
        self.layout.addLayout(self.power_layout)

    def create_video_selector(self):
        self.video_combo = Qt.QComboBox()
        
        # Read media directory from settings
        settings = read_settings()
        self.media_dir = settings.get('media_directory', '')
        
        if not self.media_dir or not os.path.exists(self.media_dir):
            self.video_combo.addItem("Error - Setup Media directory in Settings")
            self.video_combo.setEnabled(False)
            return
            
        # Search for .dat files in media directory
        self.video_files = []
        for file in os.listdir(self.media_dir):
            if file.endswith('.dat'):
                full_path = os.path.join(self.media_dir, file)
                # Use filename without extension as display name
                display_name = os.path.splitext(file)[0].replace('-', ' ')
                self.video_files.append((display_name, file))
                
        # Sort video files alphabetically by display name
        self.video_files.sort()
        
        for display_name, filename in self.video_files:
            full_path = os.path.join(self.media_dir, filename)
            self.video_combo.addItem(display_name, full_path)
            
        if self.video_combo.count() == 0:
            self.video_combo.addItem("No video files found in media directory")
            self.video_combo.setEnabled(False)
            
        self.layout.addWidget(Qt.QLabel("Video Source:"))
        self.layout.addWidget(self.video_combo)

    def create_video_invert_control(self):
        self.invert_group = Qt.QButtonGroup(self)
        self.invert_layout = Qt.QHBoxLayout()
        self.normal_radio = Qt.QRadioButton("Normal Video")
        self.invert_radio = Qt.QRadioButton("Invert Video")
        
        self.invert_group.addButton(self.normal_radio, 1)
        self.invert_group.addButton(self.invert_radio, 2)
        self.normal_radio.setChecked(True)
        
        self.invert_layout.addWidget(self.normal_radio)
        self.invert_layout.addWidget(self.invert_radio)
        self.layout.addLayout(self.invert_layout)

    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    
                self.usrp_combo.setCurrentIndex(config.get('usrp_index', 0))
                self.cf_slider.setValue(config.get('center_freq', 300))
                self.power_slider.setValue(config.get('power', 0))
                
                # Load video file by name from current media directory
                saved_video_name = config.get('video_filename')
                if saved_video_name:
                    # Find the index of the file in current video_files list
                    for i, (_, filename) in enumerate(self.video_files):
                        if filename == saved_video_name:
                            self.video_combo.setCurrentIndex(i)
                            break
                
                invert_value = config.get('invert_video', 1)
                self.invert_group.button(invert_value).setChecked(True)
                
            except:
                pass
        else:
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
            'power': self.power_slider.value(),
            'video_filename': video_filename,
            'invert_video': self.invert_group.checkedId()
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
        
        values = {
            'ipNum': ipNum,
            'ipXmitAddr': ipXmitAddr,
            'centerFreq': self.cf_slider.value(),
            'power': self.power_slider.value(),
            'videoFile': current_video_path,
            'invertVideo': 2 if self.invert_radio.isChecked() else 1
        }
        return values


class amVideoRecordedXmitter(gr.top_block, Qt.QWidget):

    def __init__(self, config_values=None):
        gr.top_block.__init__(self, "AM Recorded Video Xmitter", catch_exceptions=True)
        Qt.QWidget.__init__(self)
        self.setWindowTitle("AM Recorded Video Xmitter")
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

        self.settings = Qt.QSettings("GNU Radio", "amVideoRecordedXmitter")

        try:
            if StrictVersion(Qt.qVersion()) < StrictVersion("5.0.0"):
                self.restoreGeometry(self.settings.value("geometry").toByteArray())
            else:
                self.restoreGeometry(self.settings.value("geometry"))
        except:
            pass

        ##################################################
        # Variables
        ##################################################
        if config_values is None:
            config_dialog = ConfigDialog()
            if not config_dialog.exec_():
                sys.exit(0)
            values = config_dialog.get_values()
        else:
            values = config_values
            
        # Assign values from dialog
        self.samp_rate = samp_rate = 20e6
        self.invertVideo = invertVideo = 2 if values['invertVideo'] == 2 else 1
        cf = values['centerFreq'] * 1e6
        pwr = values['power']
        playFile = values['videoFile']
        ipXmitAddr = values['ipXmitAddr']

        ##################################################
        # Blocks
        ##################################################
        self.uhd_usrp_sink_0 = uhd.usrp_sink(
            ",".join((f'addr={ipXmitAddr}', '')),
            uhd.stream_args(
                cpu_format="fc32",
                args='',
                channels=list(range(0,1)),
            ),
            "",
        )
        self.uhd_usrp_sink_0.set_samp_rate(samp_rate)
        self.uhd_usrp_sink_0.set_time_now(uhd.time_spec(time.time()), uhd.ALL_MBOARDS)

        self.uhd_usrp_sink_0.set_center_freq(cf, 0)
        self.uhd_usrp_sink_0.set_antenna("TX/RX", 0)
        self.uhd_usrp_sink_0.set_gain(pwr, 0)
        self.rational_resampler_xxx_0 = filter.rational_resampler_ccc(
                interpolation=10,
                decimation=9,
                taps=[],
                fractional_bw=0)
        self.qtgui_freq_sink_x_0 = qtgui.freq_sink_c(
            4096, #size
            window.WIN_BLACKMAN_hARRIS, #wintype
            0, #fc
            samp_rate, #bw
            'AM Static Video Transmitter', #name
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

        # Use qwidget() for Qt compatibility
        self._qtgui_freq_sink_x_0_win = sip.wrapinstance(self.qtgui_freq_sink_x_0.qwidget(), Qt.QWidget)
        self.top_layout.addWidget(self._qtgui_freq_sink_x_0_win)
        self.blocks_null_source_0 = blocks.null_source(gr.sizeof_float*1)
        self.blocks_multiply_const_vxx_0 = blocks.multiply_const_ff(invertVideo)
        self.blocks_float_to_complex_0 = blocks.float_to_complex(1)
        self.blocks_file_source_0 = blocks.file_source(gr.sizeof_float*1, playFile, True, 0, 0)
        self.blocks_file_source_0.set_begin_tag(pmt.PMT_NIL)



        ##################################################
        # Connections
        ##################################################
        self.connect((self.blocks_file_source_0, 0), (self.blocks_multiply_const_vxx_0, 0))
        self.connect((self.blocks_float_to_complex_0, 0), (self.rational_resampler_xxx_0, 0))
        self.connect((self.blocks_multiply_const_vxx_0, 0), (self.blocks_float_to_complex_0, 0))
        self.connect((self.blocks_null_source_0, 0), (self.blocks_float_to_complex_0, 1))
        self.connect((self.rational_resampler_xxx_0, 0), (self.qtgui_freq_sink_x_0, 0))
        self.connect((self.rational_resampler_xxx_0, 0), (self.uhd_usrp_sink_0, 0))


    def closeEvent(self, event):
        self.settings = Qt.QSettings("GNU Radio", "amVideoRecordedXmitter")
        self.settings.setValue("geometry", self.saveGeometry())
        self.stop()
        self.wait()

        event.accept()

    def get_samp_rate(self):
        return self.samp_rate

    def set_samp_rate(self, samp_rate):
        self.samp_rate = samp_rate
        self.qtgui_freq_sink_x_0.set_frequency_range(0, self.samp_rate)
        self.uhd_usrp_sink_0.set_samp_rate(self.samp_rate)

    def get_invertVideo(self):
        return self.invertVideo

    def set_invertVideo(self, invertVideo):
        self.invertVideo = invertVideo
        self.blocks_multiply_const_vxx_0.set_k(self.invertVideo)




def main(top_block_cls=amVideoRecordedXmitter, *, app=None, config_values=None):  # Remove unused options parameter

    if app is None:
        if StrictVersion("4.5.0") <= StrictVersion(Qt.qVersion()) < StrictVersion("5.0.0"):
            style = gr.prefs().get_string('qtgui', 'style', 'raster')
            Qt.QApplication.setGraphicsSystem(style)
        app = Qt.QApplication(sys.argv)

    tb = top_block_cls(config_values)
    tb.start()
    tb.show()

    def sig_handler(*_):  # Catch any arguments but don't use them
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
