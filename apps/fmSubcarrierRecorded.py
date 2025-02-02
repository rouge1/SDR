#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#
# SPDX-License-Identifier: GPL-3.0
#
# GNU Radio Python Flow Graph
# Title: FM Subcarrier with Recorded Audio
# Author: instructor
# GNU Radio version: 3.10.10.0

from PyQt5 import Qt
from gnuradio import qtgui
from PyQt5 import QtCore
from PyQt5.QtCore import QObject, pyqtSlot
from gnuradio import analog
from gnuradio import blocks
from gnuradio import filter
from gnuradio.filter import firdes
from gnuradio import gr
from gnuradio.fft import window
import sys
import signal
from PyQt5 import Qt
from argparse import ArgumentParser
from gnuradio.eng_arg import eng_float, intx
from gnuradio import eng_notation
from gnuradio import uhd
import time
from math import pi
import numpy as np
import sip
import json
import os
from apps.utils import apply_dark_theme, read_settings
import glob


class ConfigDialog(Qt.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("FM Subcarrier Configuration")
        self.layout = Qt.QVBoxLayout(self)
        self.config_dir = "config"
        self.config_file = os.path.join(self.config_dir, "fmSubcarrier_config.json")
        
        # Read settings from window_settings.json
        settings = read_settings()
        self.ipList = settings['ip_addresses']
        self.N = len(self.ipList)
        
        # Add OK/Cancel buttons
        self.button_box = Qt.QDialogButtonBox(
            Qt.QDialogButtonBox.Ok | Qt.QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        
        # Create controls
        self.create_usrp_selector()
        self.create_frequency_control()
        self.create_audio_source_control()
        self.create_subcarrier_controls()
        self.create_noise_controls()
        self.create_distortion_control()
        
        self.layout.addWidget(self.button_box)
        
        # Load saved configuration
        self.load_config()
        
        # Apply dark theme
        apply_dark_theme(self)
    
    def create_usrp_selector(self):
        # Similar to other apps...
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

    def create_audio_source_control(self):
        self.audio_layout = Qt.QHBoxLayout()
        self.audio_combo = Qt.QComboBox()
        
        settings = read_settings()
        media_dir = settings.get('media_directory', '')
        
        if not media_dir or not os.path.exists(media_dir):
            self.audio_combo.addItem("Error - Setup Media directory in Settings")
            self.audio_combo.setEnabled(False)
        else:
            wav_files = glob.glob(os.path.join(media_dir, "*.wav"))
            if wav_files:
                for wav_file in wav_files:
                    display_name = os.path.splitext(os.path.basename(wav_file))[0].replace('-', ' ')
                    self.audio_combo.addItem(display_name, wav_file)
            else:
                self.audio_combo.addItem("No WAV files found in media directory")
                self.audio_combo.setEnabled(False)
                
        self.layout.addWidget(Qt.QLabel("Audio Source:"))
        self.layout.addWidget(self.audio_combo)

    def create_subcarrier_controls(self):
        # Subcarrier On/Off
        self.subcarrier_combo = Qt.QComboBox()
        self.subcarrier_combo.addItems(['Subcarrier Off', 'Subcarrier On'])
        self.layout.addWidget(Qt.QLabel("Subcarrier:"))
        self.layout.addWidget(self.subcarrier_combo)

        # Subcarrier Level
        self.sublevel_slider = Qt.QSlider(QtCore.Qt.Horizontal)
        self.sublevel_slider.setMinimum(-50)
        self.sublevel_slider.setMaximum(0)
        self.sublevel_slider.setValue(0)
        self.layout.addWidget(Qt.QLabel("Subcarrier Level (dB):"))
        self.layout.addWidget(self.sublevel_slider)

    def create_noise_controls(self):
        self.noise_freq_combo = Qt.QComboBox()
        self.noise_freq_combo.addItems(['700 Hz', '1000 Hz', '1500 Hz'])
        self.layout.addWidget(Qt.QLabel("Noise Frequency:"))
        self.layout.addWidget(self.noise_freq_combo)

        self.noise_amp_slider = Qt.QSlider(QtCore.Qt.Horizontal)
        self.noise_amp_slider.setMinimum(0)
        self.noise_amp_slider.setMaximum(20)
        self.noise_amp_slider.setValue(0)
        self.layout.addWidget(Qt.QLabel("Noise Amplitude:"))
        self.layout.addWidget(self.noise_amp_slider)

    def create_distortion_control(self):
        self.distortion_slider = Qt.QSlider(QtCore.Qt.Horizontal)
        self.distortion_slider.setMinimum(10)
        self.distortion_slider.setMaximum(100)
        self.distortion_slider.setValue(20)
        self.layout.addWidget(Qt.QLabel("Distortion Level:"))
        self.layout.addWidget(self.distortion_slider)

    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    
                self.usrp_combo.setCurrentIndex(config.get('usrp_index', 0))
                self.cf_slider.setValue(config.get('center_freq', 300))
                self.subcarrier_combo.setCurrentIndex(config.get('subcarrier_on', 1))
                self.sublevel_slider.setValue(config.get('sublevel', 0))
                self.noise_freq_combo.setCurrentIndex(config.get('noise_freq_index', 1))
                self.noise_amp_slider.setValue(config.get('noise_amp', 0))
                self.distortion_slider.setValue(config.get('distortion', 20))
                
                # Load saved audio file selection
                saved_audio = config.get('audio_file', '')
                if saved_audio:
                    for i in range(self.audio_combo.count()):
                        if self.audio_combo.itemData(i) == saved_audio:
                            self.audio_combo.setCurrentIndex(i)
                            break
            except:
                pass
        else:
            os.makedirs(self.config_dir, exist_ok=True)

    def save_config(self):
        config = {
            'usrp_index': self.usrp_combo.currentIndex(),
            'center_freq': self.cf_slider.value(),
            'subcarrier_on': self.subcarrier_combo.currentIndex(),
            'sublevel': self.sublevel_slider.value(),
            'noise_freq_index': self.noise_freq_combo.currentIndex(),
            'noise_amp': self.noise_amp_slider.value(),
            'distortion': self.distortion_slider.value(),
            'audio_file': self.audio_combo.currentData()
        }
        
        with open(self.config_file, 'w') as f:
            json.dump(config, f, indent=4)

    def accept(self):
        self.save_config()
        super().accept()

    def get_values(self):
        noise_freqs = [700, 1000, 1500]
        ipNum = self.usrp_combo.currentIndex() + 1
        ipXmitAddr = self.ipList[self.usrp_combo.currentIndex()].strip()
        
        values = {
            'ipNum': ipNum,
            'ipXmitAddr': ipXmitAddr,
            'cf': self.cf_slider.value(),
            'audio_file': self.audio_combo.currentData(),
            'subcarrier_on': self.subcarrier_combo.currentIndex(),
            'sublevel': self.sublevel_slider.value(),
            'noise_freq': noise_freqs[self.noise_freq_combo.currentIndex()],
            'noise_amp': self.noise_amp_slider.value(),
            'distortion': self.distortion_slider.value() / 10.0  # Scale to 1-10 range
        }
        return values

class fmSubcarrierRecorded(gr.top_block, Qt.QWidget):

    def __init__(self, config_values=None):
        gr.top_block.__init__(self, "FM Subcarrier with Recorded Audio", catch_exceptions=True)
        Qt.QWidget.__init__(self)
        self.setWindowTitle("FM Subcarrier with Recorded Audio")
        qtgui.util.check_set_qss()
        try:
            self.setWindowIcon(Qt.QIcon.fromTheme('gnuradio-grc'))
        except BaseException as exc:
            print(f"Qt GUI: Could not set Icon: {str(exc)}", file=sys.stderr)
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

        self.settings = Qt.QSettings("GNU Radio", "fmSubcarrierRecorded")

        try:
            geometry = self.settings.value("geometry")
            if geometry:
                self.restoreGeometry(geometry)
        except BaseException as exc:
            print(f"Qt GUI: Could not restore geometry: {str(exc)}", file=sys.stderr)

        # Use provided config values or get them from dialog
        if config_values is None:
            config_dialog = ConfigDialog()
            if not config_dialog.exec_():
                sys.exit(0)
            values = config_dialog.get_values()
        else:
            values = config_values

        # Get configuration values
        ipNum = values['ipNum']
        ipXmitAddr = values['ipXmitAddr']
        cf = values['cf']
        audio_file = values.get('audio_file')
        subOnOff = values['subcarrier_on']
        subLevel = values['sublevel']
        noiseFreq = values['noise_freq']
        noiseAmp = values['noise_amp']
        distortion = values['distortion']

        ##################################################
        # Variables
        ##################################################
        self.subOnOff = subOnOff
        self.subLevel = subLevel
        self.subFreq = subFreq = 60
        self.samp_rate = samp_rate = 2e6
        self.noiseFreq = noiseFreq
        self.noiseAmp = noiseAmp
        self.distortion = distortion
        self.cf = cf

        ##################################################
        # Blocks
        ##################################################

        # Create the options list
        self._subOnOff_options = [0, 1]
        # Create the labels list
        self._subOnOff_labels = ['Subcarrier Off', 'Subcarrier On']
        # Create the combo box
        # Create the radio buttons
        self._subOnOff_group_box = Qt.QGroupBox("Subcarrier On/Off" + ": ")
        self._subOnOff_box = Qt.QVBoxLayout()
        class variable_chooser_button_group(Qt.QButtonGroup):
            def __init__(self, parent=None):
                Qt.QButtonGroup.__init__(self, parent)
            @pyqtSlot(int)
            def updateButtonChecked(self, button_id):
                self.button(button_id).setChecked(True)
        self._subOnOff_button_group = variable_chooser_button_group()
        self._subOnOff_group_box.setLayout(self._subOnOff_box)
        for i, _label in enumerate(self._subOnOff_labels):
            radio_button = Qt.QRadioButton(_label)
            self._subOnOff_box.addWidget(radio_button)
            self._subOnOff_button_group.addButton(radio_button, i)
        self._subOnOff_callback = lambda i: Qt.QMetaObject.invokeMethod(self._subOnOff_button_group, "updateButtonChecked", Qt.Q_ARG("int", self._subOnOff_options.index(i)))
        self._subOnOff_callback(self.subOnOff)
        self._subOnOff_button_group.buttonClicked[int].connect(
            lambda i: self.set_subOnOff(self._subOnOff_options[i]))
        self.top_layout.addWidget(self._subOnOff_group_box)
        # Create the options list
        self._noiseFreq_options = [700, 1000, 1500]
        # Create the labels list
        self._noiseFreq_labels = ['Noise Frequency - Low', 'Noise Frequency - Mid', 'Noise Frequency - High']
        # Create the combo box
        self._noiseFreq_tool_bar = Qt.QToolBar(self)
        self._noiseFreq_tool_bar.addWidget(Qt.QLabel("Noise Frequency (Low/Mid/High)" + ": "))
        self._noiseFreq_combo_box = Qt.QComboBox()
        self._noiseFreq_tool_bar.addWidget(self._noiseFreq_combo_box)
        for _label in self._noiseFreq_labels: self._noiseFreq_combo_box.addItem(_label)
        self._noiseFreq_callback = lambda i: Qt.QMetaObject.invokeMethod(self._noiseFreq_combo_box, "setCurrentIndex", Qt.Q_ARG("int", self._noiseFreq_options.index(i)))
        self._noiseFreq_callback(self.noiseFreq)
        self._noiseFreq_combo_box.currentIndexChanged.connect(
            lambda i: self.set_noiseFreq(self._noiseFreq_options[i]))
        # Create the radio buttons
        self.top_layout.addWidget(self._noiseFreq_tool_bar)
        self._noiseAmp_range = qtgui.Range(0, 20, 0.1, noiseAmp, 200)  # Use noiseAmp directly
        self._noiseAmp_win = qtgui.RangeWidget(self._noiseAmp_range, self.set_noiseAmp, "Noise Amplitude", "counter_slider", float, QtCore.Qt.Horizontal)
        self.top_layout.addWidget(self._noiseAmp_win)
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

        self.uhd_usrp_sink_0.set_center_freq(cf*1e6, 0)
        self.uhd_usrp_sink_0.set_antenna("TX/RX", 0)
        self.uhd_usrp_sink_0.set_gain(20, 0)
        self._subLevel_range = qtgui.Range(-50, 0, 1, subLevel, 200)  # Use subLevel directly
        self._subLevel_win = qtgui.RangeWidget(self._subLevel_range, self.set_subLevel, "Subcarrier Level (dB)", "counter_slider", float, QtCore.Qt.Horizontal)
        self.top_layout.addWidget(self._subLevel_win)
        self.rational_resampler_xxx_0_0 = filter.rational_resampler_fff(
                interpolation=40,
                decimation=1,
                taps=[],
                fractional_bw=0)
        self.rational_resampler_xxx_0 = filter.rational_resampler_fff(
                interpolation=125,
                decimation=3,
                taps=[],
                fractional_bw=0)
        self.qtgui_freq_sink_x_0 = qtgui.freq_sink_c(
            1024, #size
            window.WIN_BLACKMAN_hARRIS, #wintype
            (cf*1e6), #fc
            samp_rate, #bw
            'FM Subcarrier Audio Transmitter (Recorded)', #name
            1,
            None # parent
        )
        self.qtgui_freq_sink_x_0.set_update_time(0.10)
        self.qtgui_freq_sink_x_0.set_y_axis((-140), 10)
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
        self.top_layout.addWidget(self._qtgui_freq_sink_x_0_win)
        self.filter_fft_low_pass_filter_1 = filter.fft_filter_fff(1, firdes.low_pass(1, 48000, 4500, 500, window.WIN_HAMMING, 6.76), 1)
        self.filter_fft_low_pass_filter_0 = filter.fft_filter_fff(1, firdes.low_pass(1, 50e3, noiseFreq, (noiseFreq/10), window.WIN_HAMMING, 6.76), 1)
        self._distortion_range = qtgui.Range(1, 10, 0.1, distortion, 200)  # Use distortion directly
        self._distortion_win = qtgui.RangeWidget(self._distortion_range, self.set_distortion, "Distortion Level", "counter_slider", float, QtCore.Qt.Horizontal)
        self.top_layout.addWidget(self._distortion_win)
        self.blocks_wavfile_source_0 = blocks.wavfile_source(audio_file, True)
        self.blocks_throttle_0 = blocks.throttle(gr.sizeof_gr_complex*1, samp_rate,True)
        self.blocks_multiply_xx_0 = blocks.multiply_vcc(1)
        self.blocks_multiply_const_vxx_0 = blocks.multiply_const_cc(0.9)
        self.blocks_complex_to_real_0 = blocks.complex_to_real(1)
        self.blocks_add_xx_0 = blocks.add_vff(1)
        self.analog_sig_source_x_0 = analog.sig_source_c(samp_rate, analog.GR_COS_WAVE, (subFreq*1000), 1, 0, 0)
        self.analog_noise_source_x_0 = analog.noise_source_f(analog.GR_GAUSSIAN, (subOnOff*10**(noiseAmp/10)), 0)
        self.analog_frequency_modulator_fc_1 = analog.frequency_modulator_fc(((subFreq*1000)*2*pi/samp_rate))
        self.analog_frequency_modulator_fc_0 = analog.frequency_modulator_fc((2*pi*10e3/(samp_rate)))


        ##################################################
        # Connections
        ##################################################
        self.connect((self.analog_frequency_modulator_fc_0, 0), (self.blocks_multiply_xx_0, 0))
        self.connect((self.analog_frequency_modulator_fc_1, 0), (self.blocks_multiply_const_vxx_0, 0))
        self.connect((self.analog_noise_source_x_0, 0), (self.filter_fft_low_pass_filter_0, 0))
        self.connect((self.analog_sig_source_x_0, 0), (self.blocks_multiply_xx_0, 1))
        self.connect((self.blocks_add_xx_0, 0), (self.analog_frequency_modulator_fc_1, 0))
        self.connect((self.blocks_complex_to_real_0, 0), (self.blocks_add_xx_0, 1))
        self.connect((self.blocks_multiply_const_vxx_0, 0), (self.blocks_throttle_0, 0))
        self.connect((self.blocks_multiply_const_vxx_0, 0), (self.uhd_usrp_sink_0, 0))
        self.connect((self.blocks_multiply_xx_0, 0), (self.blocks_complex_to_real_0, 0))
        self.connect((self.blocks_throttle_0, 0), (self.qtgui_freq_sink_x_0, 0))
        self.connect((self.blocks_wavfile_source_0, 0), (self.filter_fft_low_pass_filter_1, 0))
        self.connect((self.filter_fft_low_pass_filter_0, 0), (self.rational_resampler_xxx_0_0, 0))
        self.connect((self.filter_fft_low_pass_filter_1, 0), (self.rational_resampler_xxx_0, 0))
        self.connect((self.rational_resampler_xxx_0, 0), (self.analog_frequency_modulator_fc_0, 0))
        self.connect((self.rational_resampler_xxx_0_0, 0), (self.blocks_add_xx_0, 0))

        # Update UI elements to match config values
        self._subOnOff_callback(subOnOff)
        self._noiseFreq_callback(noiseFreq)


    def closeEvent(self, event):
        self.settings = Qt.QSettings("GNU Radio", "fmSubcarrierRecorded")
        self.settings.setValue("geometry", self.saveGeometry())
        self.stop()
        self.wait()

        event.accept()

    def get_subOnOff(self):
        return self.subOnOff

    def set_subOnOff(self, subOnOff):
        self.subOnOff = subOnOff
        self._subOnOff_callback(self.subOnOff)
        self.analog_noise_source_x_0.set_amplitude((self.subOnOff*10**(self.noiseAmp/10)))

    def get_subLevel(self):
        return self.subLevel

    def set_subLevel(self, subLevel):
        self.subLevel = subLevel

    def get_subFreq(self):
        return self.subFreq

    def set_subFreq(self, subFreq):
        self.subFreq = subFreq
        self.analog_frequency_modulator_fc_1.set_sensitivity(((self.subFreq*1000)*2*pi/self.samp_rate))
        self.analog_sig_source_x_0.set_frequency((self.subFreq*1000))

    def get_samp_rate(self):
        return self.samp_rate

    def set_samp_rate(self, samp_rate):
        self.samp_rate = samp_rate
        self.analog_frequency_modulator_fc_0.set_sensitivity((2*pi*10e3/(self.samp_rate)))
        self.analog_frequency_modulator_fc_1.set_sensitivity(((self.subFreq*1000)*2*pi/self.samp_rate))
        self.analog_sig_source_x_0.set_sampling_freq(self.samp_rate)
        self.blocks_throttle_0.set_sample_rate(self.samp_rate)
        self.qtgui_freq_sink_x_0.set_frequency_range((self.cf*1e6), self.samp_rate)
        self.uhd_usrp_sink_0.set_samp_rate(self.samp_rate)

    def get_noiseFreq(self):
        return self.noiseFreq

    def set_noiseFreq(self, noiseFreq):
        self.noiseFreq = noiseFreq
        self._noiseFreq_callback(self.noiseFreq)
        self.filter_fft_low_pass_filter_0.set_taps(firdes.low_pass(1, 50e3, self.noiseFreq, (self.noiseFreq/10), window.WIN_HAMMING, 6.76))

    def get_noiseAmp(self):
        return self.noiseAmp

    def set_noiseAmp(self, noiseAmp):
        self.noiseAmp = noiseAmp
        self.analog_noise_source_x_0.set_amplitude((self.subOnOff*10**(self.noiseAmp/10)))

    def get_distortion(self):
        return self.distortion

    def set_distortion(self, distortion):
        self.distortion = distortion

    def get_cf(self):
        return self.cf

    def set_cf(self, cf):
        self.cf = cf
        self.qtgui_freq_sink_x_0.set_frequency_range((self.cf*1e6), self.samp_rate)
        self.uhd_usrp_sink_0.set_center_freq(self.cf*1e6, 0)




def main(top_block_cls=fmSubcarrierRecorded, options=None, app=None, config_values=None):
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
