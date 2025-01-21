#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Standard library imports
import json
import os
import signal
import sys
import glob
from math import pi

# Third party imports 
from PyQt5 import Qt, QtCore # type: ignore
from PyQt5.QtCore import pyqtSlot # type: ignore
import sip # type: ignore # type: ignore
from packaging.version import Version # type: ignore

from gnuradio import analog, blocks, filter, gr, qtgui # type: ignore
from gnuradio.fft import window # type: ignore
from gnuradio.filter import firdes # type: ignore
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
        self.setWindowTitle("FM Subcarrier Configuration")
        self.layout = Qt.QVBoxLayout(self)
        self.config_dir = "config"
        self.config_file = os.path.join(self.config_dir, "fmSubcarrier_config.json")

        # Ensure config directory exists
        os.makedirs(self.config_dir, exist_ok=True)
        
        # Initialize default values in case config load fails
        self.default_config = {
            'sub_level': -20,
            'sub_freq': 60,
            'noise_freq': 1000,
            'noise_amp': 0
        }

        # Read settings from window_settings.json
        settings = read_settings()
        self.ipList = settings['ip_addresses']
        self.N = len(self.ipList)

        # Create all input widgets
        self.create_audio_source_control()
        self.create_subcarrier_controls()
        self.create_noise_controls()
        self.create_button_box()

        # Load saved configuration
        self.load_config()

        # Apply dark theme
        apply_dark_theme(self)

    def create_audio_source_control(self):
        self.source_combo = Qt.QComboBox()
        
        # Read media directory setting and get wav files
        settings = read_settings()
        wav_files = get_wav_files(settings)
        
        if wav_files is None:
            self.source_combo.addItem("Error - Setup Media directory in Settings")
            self.source_combo.setEnabled(False)
        else:
            if wav_files:
                for wav_file in wav_files:
                    display_name = os.path.splitext(os.path.basename(wav_file))[0].replace('-', ' ')
                    self.source_combo.addItem(display_name, wav_file)
        
        self.layout.addWidget(Qt.QLabel("Audio Source:"))
        self.layout.addWidget(self.source_combo)

    def create_subcarrier_controls(self):
        # Subcarrier Level slider
        self.sub_level_slider = Qt.QSlider(QtCore.Qt.Horizontal)
        self.sub_level_slider.setMinimum(-50)
        self.sub_level_slider.setMaximum(0)
        self.sub_level_slider.setValue(-20)
        self.layout.addWidget(Qt.QLabel("Subcarrier Level (dB):"))
        self.layout.addWidget(self.sub_level_slider)

        # Subcarrier Frequency slider
        self.sub_freq_slider = Qt.QSlider(QtCore.Qt.Horizontal)
        self.sub_freq_slider.setMinimum(10)
        self.sub_freq_slider.setMaximum(100)
        self.sub_freq_slider.setValue(60)
        self.layout.addWidget(Qt.QLabel("Subcarrier Frequency (kHz):"))
        self.layout.addWidget(self.sub_freq_slider)

    def create_noise_controls(self):
        """Create noise frequency and amplitude controls"""
        # Noise Frequency slider
        self.noise_freq_slider = Qt.QSlider(QtCore.Qt.Horizontal)
        self.noise_freq_slider.setMinimum(100)
        self.noise_freq_slider.setMaximum(2000)
        self.noise_freq_slider.setValue(1000)
        self.layout.addWidget(Qt.QLabel("Noise Frequency (Hz):"))
        self.layout.addWidget(self.noise_freq_slider)

        # Noise Amplitude slider
        self.noise_amp_slider = Qt.QSlider(QtCore.Qt.Horizontal)
        self.noise_amp_slider.setMinimum(0)
        self.noise_amp_slider.setMaximum(20)
        self.noise_amp_slider.setValue(0)
        self.layout.addWidget(Qt.QLabel("Noise Amplitude (dB):"))
        self.layout.addWidget(self.noise_amp_slider)

    def create_button_box(self):
        self.button_box = Qt.QDialogButtonBox(
            Qt.QDialogButtonBox.Ok | Qt.QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.layout.addWidget(self.button_box)

    def load_config(self):
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    # Load values with defaults if missing
                    self.sub_level_slider.setValue(config.get('sub_level', self.default_config['sub_level']))
                    self.sub_freq_slider.setValue(config.get('sub_freq', self.default_config['sub_freq']))
                    self.noise_freq_slider.setValue(config.get('noise_freq', self.default_config['noise_freq']))
                    self.noise_amp_slider.setValue(config.get('noise_amp', self.default_config['noise_amp']))
        except Exception as e:
            print(f"Error loading config: {e}")
            # Use defaults if loading fails
            self.sub_level_slider.setValue(self.default_config['sub_level'])
            self.sub_freq_slider.setValue(self.default_config['sub_freq'])
            self.noise_freq_slider.setValue(self.default_config['noise_freq'])
            self.noise_amp_slider.setValue(self.default_config['noise_amp'])

    def save_config(self):
        config = {
            'sub_level': self.sub_level_slider.value(),
            'sub_freq': self.sub_freq_slider.value(),
            'audio_source': self.source_combo.currentData()
            # ...other settings...
        }
        
        os.makedirs(self.config_dir, exist_ok=True)
        with open(self.config_file, 'w') as f:
            json.dump(config, f, indent=4)

    def get_values(self):
        return {
            'audio_source': self.source_combo.currentData(),
            'sub_level': self.sub_level_slider.value(),
            'sub_freq': self.sub_freq_slider.value(),
            'noise_freq': self.noise_freq_slider.value(),
            'noise_amp': self.noise_amp_slider.value()
            # ...other values...
        }

class fmSubcarrierRecorded(gr.top_block, Qt.QWidget):
    def __init__(self, config_values=None):
        gr.top_block.__init__(self, "FM Subcarrier with Recorded Audio", catch_exceptions=True)
        Qt.QWidget.__init__(self)
        self.setWindowTitle("FM Subcarrier with Recorded Audio")
        
        # Initialize default values
        self.default_config = {
            'audio_source': '',
            'sub_level': -20,
            'sub_freq': 60,
            'noise_freq': 1000,
            'noise_amp': 0
        }

        # Get configuration with safety checks
        if config_values is None:
            config_dialog = ConfigDialog()
            if not config_dialog.exec_():
                sys.exit(0)
            self.config = config_dialog.get_values()
        else:
            self.config = config_values

        # Validate audio source
        if not self.config.get('audio_source') or not os.path.exists(self.config['audio_source']):
            print("Error: Invalid audio source")
            sys.exit(1)

        # Setup the UI and processing blocks using config values
        self.setup_variables()
        self.setup_gui_elements()
        self.create_processing_blocks()
        self.make_connections()

    def setup_variables(self):
        self.subOnOff = 1
        self.subLevel = self.config['sub_level']
        self.subFreq = self.config['sub_freq']
        self.samp_rate = int(2e6)
        self.noiseFreq = 1000
        self.noiseAmp = 0
        self.distortion = 2
        self.cf = 300

    def setup_gui_elements(self):
        # Setup UI layout
        self.top_layout = Qt.QVBoxLayout(self)

        # Subcarrier On/Off radio buttons
        self._subOnOff_group_box = Qt.QGroupBox("Subcarrier On/Off")
        self._subOnOff_box = Qt.QVBoxLayout()
        
        class variable_chooser_button_group(Qt.QButtonGroup):
            def __init__(self, parent=None):
                Qt.QButtonGroup.__init__(self, parent)
            @pyqtSlot(int)
            def updateButtonChecked(self, button_id):
                self.button(button_id).setChecked(True)
                
        self._subOnOff_button_group = variable_chooser_button_group()
        self._subOnOff_group_box.setLayout(self._subOnOff_box)
        for i, label in enumerate(['Subcarrier Off', 'Subcarrier On']):
            radio_button = Qt.QRadioButton(label)
            self._subOnOff_box.addWidget(radio_button)
            self._subOnOff_button_group.addButton(radio_button, i)
        self._subOnOff_button_group.buttonClicked[int].connect(
            lambda i: self.set_subOnOff(i))
        self.top_layout.addWidget(self._subOnOff_group_box)

        # Subcarrier Level slider
        self._subLevel_range = Range(-50, 0, 1, self.subLevel, 200)
        self._subLevel_win = RangeWidget(self._subLevel_range, self.set_subLevel, 
                                       'Subcarrier Level (dB)', "counter_slider", float)
        self.top_layout.addWidget(self._subLevel_win)
        
        # Noise Frequency combo box
        self._noiseFreq_tool_bar = Qt.QToolBar(self)
        self._noiseFreq_tool_bar.addWidget(Qt.QLabel('Noise Frequency: '))
        self._noiseFreq_combo_box = Qt.QComboBox()
        self._noiseFreq_tool_bar.addWidget(self._noiseFreq_combo_box)
        for label in ['Low', 'Mid', 'High']:
            self._noiseFreq_combo_box.addItem(label)
        self._noiseFreq_combo_box.currentIndexChanged.connect(
            lambda i: self.set_noiseFreq([700, 1000, 1500][i]))
        self.top_layout.addWidget(self._noiseFreq_tool_bar)

        # Noise Amplitude slider
        self._noiseAmp_range = Range(0, 20, 0.1, 0, 200)
        self._noiseAmp_win = RangeWidget(self._noiseAmp_range, self.set_noiseAmp,
                                        'Noise Amplitude', "counter_slider", float)
        self.top_layout.addWidget(self._noiseAmp_win)

        # Distortion Level slider
        self._distortion_range = Range(1, 10, 0.1, 2, 200)
        self._distortion_win = RangeWidget(self._distortion_range, self.set_distortion,
                                         'Distortion Level', "counter_slider", float)
        self.top_layout.addWidget(self._distortion_win)

        # Frequency sink
        self.qtgui_freq_sink = qtgui.freq_sink_c(
            1024,
            window.WIN_BLACKMAN_hARRIS,
            self.cf * 1e6,
            self.samp_rate,
            "FM Subcarrier Audio Transmitter (Recorded)",
            1
        )
        self.qtgui_freq_sink.set_update_time(0.10)
        self.qtgui_freq_sink.set_y_axis(-140, 10)
        self.qtgui_freq_sink.set_y_label('Relative Gain', 'dB')
        self.qtgui_freq_sink.enable_autoscale(False)
        self.qtgui_freq_sink.enable_grid(True)

        # Create Qt widget using qwidget() instead of PlotWidget
        self._qtgui_freq_sink_win = sip.wrapinstance(self.qtgui_freq_sink.qwidget(), Qt.QWidget)
        self.top_layout.addWidget(self._qtgui_freq_sink_win)
        
    def create_processing_blocks(self):
        # Resamplers
        self.rational_resampler_0 = filter.rational_resampler_fff(
            interpolation=40,
            decimation=1,
            taps=[],
            fractional_bw=0)
        
        self.rational_resampler_1 = filter.rational_resampler_fff(
            interpolation=40,
            decimation=1,
            taps=[],
            fractional_bw=0)

        # Filters
        self.filter_fft_low_pass_0 = filter.fft_filter_fff(
            1,
            firdes.low_pass(1, 50e3, self.noiseFreq, self.noiseFreq/10, window.WIN_HAMMING, 6.76),
            1)
            
        self.filter_fft_low_pass_1 = filter.fft_filter_fff(
            1,
            firdes.low_pass(1, 50e3, 4500, 500, window.WIN_HAMMING, 6.76),
            1)

        # Source blocks
        self.blocks_wavfile_source = blocks.wavfile_source(
            self.config['audio_source'],
            True)
            
        self.analog_noise_source = analog.noise_source_f(
            analog.GR_GAUSSIAN,
            self.subOnOff * 10**(self.noiseAmp/10),
            0)

        # Signal processing blocks
        self.analog_frequency_modulator_0 = analog.frequency_modulator_fc(2*pi*10e3/self.samp_rate)
        self.analog_frequency_modulator_1 = analog.frequency_modulator_fc(
            (self.subFreq*1000)*2*pi/self.samp_rate)
        
        self.analog_sig_source = analog.sig_source_c(
            self.samp_rate,
            analog.GR_COS_WAVE,
            self.subFreq*1000,
            1,
            0,
            0)

        # Other blocks
        self.blocks_multiply = blocks.multiply_vcc(1)
        self.blocks_multiply_const_0 = blocks.multiply_const_cc(0.9)
        self.blocks_multiply_const_1 = blocks.multiply_const_ff(10**(self.subLevel/10))
        self.blocks_complex_to_real = blocks.complex_to_real(1)
        self.blocks_add = blocks.add_vff(1)
        self.blocks_add_const = blocks.add_const_ff(self.distortion)
        self.blocks_transcendental = blocks.transcendental('log', "float")
        self.dc_blocker = filter.dc_blocker_ff(2000, True)
        self.blocks_throttle = blocks.throttle(gr.sizeof_gr_complex*1, self.samp_rate, True)

    def make_connections(self):
        # Main signal path
        self.connect(self.blocks_wavfile_source, self.filter_fft_low_pass_1)
        self.connect(self.filter_fft_low_pass_1, self.rational_resampler_0)
        self.connect(self.rational_resampler_0, self.analog_frequency_modulator_0)
        
        # Noise path
        self.connect(self.analog_noise_source, self.filter_fft_low_pass_0)
        self.connect(self.filter_fft_low_pass_0, self.rational_resampler_1)
        self.connect(self.rational_resampler_1, self.blocks_add)
        
        # Subcarrier modulation
        self.connect(self.analog_frequency_modulator_0, self.blocks_multiply)
        self.connect(self.analog_sig_source, (self.blocks_multiply, 1))
        self.connect(self.blocks_multiply, self.blocks_complex_to_real)
        self.connect(self.blocks_complex_to_real, self.blocks_add_const)
        self.connect(self.blocks_add_const, self.blocks_transcendental)
        self.connect(self.blocks_transcendental, self.dc_blocker)
        self.connect(self.dc_blocker, self.blocks_multiply_const_1)
        self.connect(self.blocks_multiply_const_1, (self.blocks_add, 1))
        
        # Output path
        self.connect(self.blocks_add, self.analog_frequency_modulator_1)
        self.connect(self.analog_frequency_modulator_1, self.blocks_multiply_const_0)
        self.connect(self.blocks_multiply_const_0, self.blocks_throttle)
        self.connect(self.blocks_throttle, self.qtgui_freq_sink)

    def closeEvent(self, event):
        self.stop()
        self.wait()
        event.accept()

    # Getter and setter methods
    def get_subOnOff(self): return self.subOnOff
    def set_subOnOff(self, subOnOff): 
        self.subOnOff = subOnOff
        self.analog_noise_source.set_amplitude(self.subOnOff * 10**(self.noiseAmp/10))

    def get_subLevel(self): return self.subLevel
    def set_subLevel(self, subLevel):
        self.subLevel = subLevel
        self.blocks_multiply_const_1.set_k(10**(self.subLevel/10))

    def get_subFreq(self): return self.subFreq
    def set_subFreq(self, subFreq):
        self.subFreq = subFreq
        self.analog_frequency_modulator_1.set_sensitivity((self.subFreq*1000)*2*pi/self.samp_rate)
        self.analog_sig_source.set_frequency(self.subFreq*1000)

    def get_samp_rate(self): return self.samp_rate
    def set_samp_rate(self, samp_rate):
        self.samp_rate = samp_rate
        self.analog_frequency_modulator_0.set_sensitivity(2*pi*10e3/self.samp_rate)
        self.analog_frequency_modulator_1.set_sensitivity((self.subFreq*1000)*2*pi/self.samp_rate)
        self.analog_sig_source.set_sampling_freq(self.samp_rate)
        self.blocks_throttle.set_sample_rate(self.samp_rate)
        self.qtgui_freq_sink.set_frequency_range(self.cf*1e6, self.samp_rate)

    def get_noiseFreq(self): return self.noiseFreq
    def set_noiseFreq(self, noiseFreq):
        self.noiseFreq = noiseFreq
        self.filter_fft_low_pass_0.set_taps(
            firdes.low_pass(1, 50e3, self.noiseFreq, self.noiseFreq/10, window.WIN_HAMMING, 6.76))

    def get_noiseAmp(self): return self.noiseAmp
    def set_noiseAmp(self, noiseAmp):
        self.noiseAmp = noiseAmp
        self.analog_noise_source.set_amplitude(self.subOnOff * 10**(self.noiseAmp/10))

    def get_distortion(self): return self.distortion
    def set_distortion(self, distortion):
        self.distortion = distortion
        self.blocks_add_const.set_k(self.distortion)

    def get_cf(self): return self.cf
    def set_cf(self, cf):
        self.cf = cf
        self.qtgui_freq_sink.set_frequency_range(self.cf*1e6, self.samp_rate)

def main(top_block_cls=fmSubcarrierRecorded, options=None, app=None, config_values=None):
    if app is None:
        if Version("4.5.0") <= Version(Qt.qVersion()) < Version("5.0.0"):
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