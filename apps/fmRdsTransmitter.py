#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# SPDX-License-Identifier: GPL-3.0
#
# FM broadcast transmitter with RDS - plays audio from the media folder and
# carries a live-editable station name, RadioText and now-playing tags on the
# 57 kHz subcarrier, exactly as a real FM station does.
#
# Test it with the RDS Receiver app (or a car radio): everything this sends is
# something apps/rds_core.py can read back.

import glob
import json
import os
import signal
import sys
import time
import wave

import numpy as np  # type: ignore
try:
    import sip  # type: ignore
except ImportError:  # pragma: no cover - depends on the PyQt5 build
    from PyQt5 import sip  # type: ignore
from gnuradio import analog, blocks, filter, gr, qtgui, soapy, uhd  # type: ignore
from gnuradio.fft import window  # type: ignore
from gnuradio.filter import firdes  # type: ignore
from PyQt5 import Qt, QtCore  # type: ignore

from apps.rds_core import PTY_RBDS
from apps.rds_encode import RdsEncoder, RdsSubcarrier
from apps.utils import (apply_dark_theme, power_percent, read_settings,
                        resolve_power_range, scale_power, SPECTRUM_Y_AXIS)

MPX_RATE = 200e3          # everything below 100 kHz fits comfortably
TX_RATE = 2e6             # MPX interpolated by 10
AUDIO_RATE = 48000        # what the media folder holds
MAX_DEVIATION = 75e3

#: Shares of peak deviation. Audio is kept well back from the limit so the
#: pilot and the RDS subcarrier fit underneath it.
AUDIO_LEVEL = 0.55
PILOT_LEVEL = 0.09        # 9% of 75 kHz, the standard pilot injection
RDS_INJECTION = 0.04


def call_to_pi(call):
    """RBDS call letters -> PI code, or None if it is not a 4-letter K/W call."""
    call = (call or '').strip().upper()
    if len(call) != 4 or call[0] not in 'KW' or not call.isalpha():
        return None
    base = 4096 if call[0] == 'K' else 21672
    a, b, c = (ord(ch) - 65 for ch in call[1:])
    return base + a * 676 + b * 26 + c


def track_name(path):
    """A readable track name from a media filename."""
    if not path:
        return ''
    return os.path.splitext(os.path.basename(path))[0].replace('-', ' ')


def wav_channels(path):
    """Channel count of a WAV file, or 0 if it is not a readable WAV."""
    try:
        w = wave.open(path)
    except Exception:
        return 0
    try:
        return w.getnchannels()
    finally:
        w.close()


def wav_files(settings):
    media = settings.get('media_directory', '')
    if not media or not os.path.isdir(media):
        return []
    return sorted(glob.glob(os.path.join(media, '*.wav')))


class ConfigDialog(Qt.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("FM + RDS Transmitter Configuration")
        self.layout = Qt.QVBoxLayout(self)
        self.config_dir = "config"
        self.config_file = os.path.join(self.config_dir,
                                        "fmRdsTransmitter_config.json")
        settings = read_settings()
        self.ipList = settings.get('ip_addresses', [])
        self.radio_type = settings.get('radio_type', 'hackrf')

        self.button_box = Qt.QDialogButtonBox(
            Qt.QDialogButtonBox.Ok | Qt.QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        self.create_radio_selector()
        self.create_frequency_control()
        self.create_power_control()
        self.create_audio_control(settings)
        self.create_rds_controls()

        self.layout.addWidget(self.button_box)
        self.load_config()
        apply_dark_theme(self)

    def create_radio_selector(self):
        if self.radio_type in ('hackrf', 'vsg'):
            label = ("Radio: Signal Hound VSG60 (USB)" if self.radio_type == 'vsg'
                     else "Radio: HackRF One (USB)")
            self.layout.addWidget(Qt.QLabel(label))
            self.button_box.button(Qt.QDialogButtonBox.Ok).setEnabled(True)
            return
        self.usrp_combo = Qt.QComboBox()
        ok = self.button_box.button(Qt.QDialogButtonBox.Ok)
        if not self.ipList:
            self.usrp_combo.addItem("IP addr missing - Go to Settings")
            ok.setEnabled(False)
            dim = Qt.QGraphicsOpacityEffect()
            dim.setOpacity(0.30)
            ok.setGraphicsEffect(dim)
        else:
            for i, ip in enumerate(self.ipList):
                self.usrp_combo.addItem(f"USRP {i+1} ({ip.strip()})", ip.strip())
            ok.setEnabled(True)
            ok.setGraphicsEffect(None)
        self.layout.addWidget(Qt.QLabel("Select USRP:"))
        self.layout.addWidget(self.usrp_combo)

    def create_frequency_control(self):
        row = Qt.QHBoxLayout()
        row.addWidget(Qt.QLabel("Transmit Frequency (MHz):"))
        self.freq_spin = Qt.QDoubleSpinBox()
        self.freq_spin.setDecimals(1)
        self.freq_spin.setSingleStep(0.1)
        self.freq_spin.setRange(87.5, 108.0)
        self.freq_spin.setValue(101.3)
        row.addWidget(self.freq_spin)
        self.layout.addLayout(row)
        warn = Qt.QLabel("Pick an empty channel and keep power low - this is a "
                         "real broadcast-band transmitter.")
        warn.setWordWrap(True)
        self.layout.addWidget(warn)

    def create_power_control(self):
        row = Qt.QHBoxLayout()
        self.pwr_slider = Qt.QSlider(QtCore.Qt.Horizontal)
        self.pwr_slider.setRange(0, 100)
        self.pwr_slider.setValue(0)
        self.pwr_label = Qt.QLabel("Power Level: 0%")
        self.pwr_slider.valueChanged.connect(
            lambda v: self.pwr_label.setText(f"Power Level: {v}%"))
        row.addWidget(self.pwr_label)
        row.addWidget(self.pwr_slider)
        self.layout.addLayout(row)

    def create_audio_control(self, settings):
        self.layout.addWidget(Qt.QLabel("Audio Source:"))
        self.audio_combo = Qt.QComboBox()
        for path in wav_files(settings):
            self.audio_combo.addItem(track_name(path), path)
        self.audio_combo.addItem("1 kHz Tone", "tone")
        self.audio_combo.addItem("Silence (RDS only)", "silence")
        self.layout.addWidget(self.audio_combo)

    def create_rds_controls(self):
        box = Qt.QGroupBox("RDS")
        form = Qt.QFormLayout()
        box.setLayout(form)

        self.call_edit = Qt.QLineEdit("KTST")
        self.call_edit.setMaxLength(4)
        self.pi_label = Qt.QLabel()
        self.call_edit.textChanged.connect(self._update_pi_label)
        row = Qt.QHBoxLayout()
        row.addWidget(self.call_edit)
        row.addWidget(self.pi_label)
        holder = Qt.QWidget()
        holder.setLayout(row)
        form.addRow("Call sign:", holder)

        self.ps_edit = Qt.QLineEdit("GNURADIO")
        self.ps_edit.setMaxLength(8)
        form.addRow("Station name (8 chars):", self.ps_edit)

        self.rt_edit = Qt.QLineEdit("GNU Radio FM with RDS")
        self.rt_edit.setMaxLength(64)
        form.addRow("RadioText:", self.rt_edit)

        self.pty_combo = Qt.QComboBox()
        for i, name in enumerate(PTY_RBDS):
            self.pty_combo.addItem(f"{i} - {name}", i)
        self.pty_combo.setCurrentIndex(5)
        form.addRow("Program type:", self.pty_combo)

        self.track_check = Qt.QCheckBox("Put the track name in RadioText")
        self.track_check.setChecked(True)
        form.addRow(self.track_check)

        self.layout.addWidget(box)
        self._update_pi_label()

    def _update_pi_label(self):
        pi = call_to_pi(self.call_edit.text())
        self.pi_label.setText(f"PI {pi:#06x}" if pi else "PI - (need 4 letters)")

    def load_config(self):
        if not os.path.exists(self.config_file):
            os.makedirs(self.config_dir, exist_ok=True)
            return
        try:
            with open(self.config_file) as f:
                config = json.load(f)
        except Exception as exc:
            print(f"FM+RDS: could not read saved config: {exc}", file=sys.stderr)
            return
        for key, apply in (
            ('frequency_mhz', lambda v: self.freq_spin.setValue(float(v))),
            ('power_percent', lambda v: self.pwr_slider.setValue(
                power_percent(v, 0))),
            ('call', lambda v: self.call_edit.setText(str(v))),
            ('ps', lambda v: self.ps_edit.setText(str(v))),
            ('radiotext', lambda v: self.rt_edit.setText(str(v))),
            ('pty', lambda v: self.pty_combo.setCurrentIndex(int(v))),
            ('track_in_rt', lambda v: self.track_check.setChecked(bool(v))),
            ('audio', lambda v: self._select_audio(v)),
        ):
            if key in config:
                try:
                    apply(config[key])
                except Exception as exc:
                    print(f"FM+RDS: ignoring saved {key!r}: {exc}",
                          file=sys.stderr)

    def _select_audio(self, value):
        for i in range(self.audio_combo.count()):
            if self.audio_combo.itemData(i) == value:
                self.audio_combo.setCurrentIndex(i)
                return

    def save_config(self):
        config = {
            'frequency_mhz': self.freq_spin.value(),
            'power_percent': self.pwr_slider.value(),
            'call': self.call_edit.text(),
            'ps': self.ps_edit.text(),
            'radiotext': self.rt_edit.text(),
            'pty': self.pty_combo.currentIndex(),
            'track_in_rt': self.track_check.isChecked(),
            'audio': self.audio_combo.currentData(),
        }
        os.makedirs(self.config_dir, exist_ok=True)
        with open(self.config_file, 'w') as f:
            json.dump(config, f, indent=4)

    def accept(self):
        self.save_config()
        super().accept()

    def get_values(self):
        ip = ''
        if hasattr(self, 'usrp_combo') and self.ipList:
            ip = self.usrp_combo.currentData() or ''
        return {
            'radio_type': self.radio_type,
            'ipXmitAddr': ip,
            'ipNum': (self.usrp_combo.currentIndex() + 1
                      if hasattr(self, 'usrp_combo') and self.ipList else 0),
            'frequency_mhz': self.freq_spin.value(),
            'power_percent': self.pwr_slider.value(),
            'call': self.call_edit.text().strip().upper(),
            'ps': self.ps_edit.text(),
            'radiotext': self.rt_edit.text(),
            'pty': self.pty_combo.currentData(),
            'track_in_rt': self.track_check.isChecked(),
            'audio': self.audio_combo.currentData(),
            'audio_list': [self.audio_combo.itemData(i)
                           for i in range(self.audio_combo.count())
                           if self.audio_combo.itemData(i) not in ('tone', 'silence')],
        }


class rds_source(gr.sync_block):
    """Streams the subcarriers from apps/rds_encode.py.

    Output 0 is the 19 kHz pilot plus the 57 kHz RDS subcarrier. Output 1 is a
    bare 38 kHz carrier for the stereo difference signal, generated from the
    same sample counter so it is exactly twice the pilot. It is produced even
    in mono, where the flowgraph simply discards it.
    """

    def __init__(self, encoder, rate):
        gr.sync_block.__init__(self, name='rds_source', in_sig=None,
                               out_sig=[np.float32, np.float32])
        self.sub = RdsSubcarrier(encoder, rate, rds_injection=RDS_INJECTION,
                                 pilot_level=PILOT_LEVEL)

    def work(self, input_items, output_items):
        n = len(output_items[0])
        subcarriers, carrier38 = self.sub.generate_all(n)
        output_items[0][:] = subcarriers
        output_items[1][:] = carrier38
        return n


class fmRdsTransmitter(gr.top_block, Qt.QWidget):
    def __init__(self, config_values=None):
        gr.top_block.__init__(self, "FM + RDS Transmitter", catch_exceptions=True)
        Qt.QWidget.__init__(self)
        self.setWindowTitle("FM + RDS Transmitter")
        qtgui.util.check_set_qss()
        try:
            self.setWindowIcon(Qt.QIcon.fromTheme('gnuradio-grc'))
        except BaseException as exc:
            print(f"Qt GUI: Could not set Icon: {exc}", file=sys.stderr)

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

        self.settings = Qt.QSettings("GNU Radio", "fmRdsTransmitter")
        try:
            geometry = self.settings.value("geometry")
            if geometry:
                self.restoreGeometry(geometry)
        except BaseException as exc:
            print(f"Qt GUI: Could not restore geometry: {exc}", file=sys.stderr)

        if config_values is None:
            dialog = ConfigDialog()
            if not dialog.exec_():
                sys.exit(0)
            values = dialog.get_values()
        else:
            values = config_values

        self.radio_type = values.get('radio_type', 'hackrf')
        self.freq_mhz = float(values.get('frequency_mhz', 101.3))
        self.power_percent = float(values.get('power_percent', 0))
        self.usrp_ip = values.get('ipXmitAddr', '')
        self.track_in_rt = bool(values.get('track_in_rt', True))
        self.playlist = [p for p in values.get('audio_list', []) if p]
        self.audio_choice = values.get('audio', 'silence')
        self.track_index = (self.playlist.index(self.audio_choice)
                            if self.audio_choice in self.playlist else 0)

        pi = call_to_pi(values.get('call', '')) or 0x4413
        self.encoder = RdsEncoder(
            pi=pi,
            ps=values.get('ps', 'GNURADIO'),
            radiotext=values.get('radiotext', ''),
            pty=int(values.get('pty', 5) or 0),
        )
        if self.track_in_rt and self.audio_choice not in ('tone', 'silence'):
            self.encoder.set_now_playing('', track_name(self.audio_choice))

        self._build_controls()
        self._build_flowgraph()
        self._build_spectrum()

    # ------------------------------------------------------------------ UI
    def _build_controls(self):
        grid = Qt.QGridLayout()
        holder = Qt.QWidget()
        holder.setLayout(grid)

        grid.addWidget(Qt.QLabel("<b>Frequency (MHz)</b>"), 0, 0)
        self.freq_spin = Qt.QDoubleSpinBox()
        self.freq_spin.setDecimals(1)
        self.freq_spin.setSingleStep(0.1)
        self.freq_spin.setRange(87.5, 108.0)
        self.freq_spin.setValue(self.freq_mhz)
        self.freq_spin.valueChanged.connect(self.set_frequency)
        grid.addWidget(self.freq_spin, 0, 1)

        grid.addWidget(Qt.QLabel("<b>Power</b>"), 0, 2)
        self.pwr_slider = Qt.QSlider(QtCore.Qt.Horizontal)
        self.pwr_slider.setRange(0, 100)
        self.pwr_slider.setValue(int(self.power_percent))
        self.pwr_slider.valueChanged.connect(self.set_power)
        grid.addWidget(self.pwr_slider, 0, 3)
        self.pwr_value = Qt.QLabel(f"{int(self.power_percent)}%")
        grid.addWidget(self.pwr_value, 0, 4)

        grid.addWidget(Qt.QLabel("<b>Station name</b>"), 1, 0)
        self.ps_edit = Qt.QLineEdit(self.encoder.snapshot()['ps'].strip())
        self.ps_edit.setMaxLength(8)
        grid.addWidget(self.ps_edit, 1, 1)

        grid.addWidget(Qt.QLabel("<b>RadioText</b>"), 1, 2)
        self.rt_edit = Qt.QLineEdit(self.encoder.snapshot()['radiotext'])
        self.rt_edit.setMaxLength(64)
        grid.addWidget(self.rt_edit, 1, 3)

        apply_btn = Qt.QPushButton("Send Text")
        apply_btn.clicked.connect(self.apply_text)
        grid.addWidget(apply_btn, 1, 4)

        self.track_label = Qt.QLabel("-")
        grid.addWidget(Qt.QLabel("<b>Track</b>"), 2, 0)
        grid.addWidget(self.track_label, 2, 1, 1, 3)
        next_btn = Qt.QPushButton("Next Track")
        next_btn.clicked.connect(self.next_track)
        grid.addWidget(next_btn, 2, 4)

        self.top_grid_layout.addWidget(holder, 0, 0, 1, 10)

    def apply_text(self):
        """Push the edited station name and RadioText on to the air."""
        self.encoder.set_ps(self.ps_edit.text())
        self.encoder.set_radiotext(self.rt_edit.text())

    # ----------------------------------------------------------- flowgraph
    def _audio_branch(self, path):
        if path and path not in ('tone', 'silence') and os.path.exists(path):
            return blocks.wavfile_source(path, True)
        if path == 'tone':
            return analog.sig_source_f(AUDIO_RATE, analog.GR_COS_WAVE, 1000,
                                       0.5, 0, 0)
        return blocks.null_source(gr.sizeof_float)

    def _build_audio(self):
        """Create the audio blocks for the current track, mono or stereo.

        A stereo file is matrixed into mid (L+R)/2 and side (L-R)/2, because FM
        does not transmit left and right: it sends the sum as ordinary audio and
        the difference on the 38 kHz subcarrier, which is what keeps the signal
        listenable on a mono receiver.
        """
        self.audio_src = self._audio_branch(self.audio_choice)
        self.stereo = wav_channels(self.audio_choice or '') == 2
        # 48 kHz media up to the 200 kHz multiplex rate: 200/48 = 25/6.
        def resampler():
            return filter.rational_resampler_fff(
                interpolation=25, decimation=6, taps=[], fractional_bw=0)

        def audio_shaping():
            # AUDIO_LEVEL rides in the filter gain, so peak deviation stays
            # within budget once the pilot and RDS are added on top.
            return (analog.fm_preemph(MPX_RATE, 75e-6),
                    filter.fir_filter_fff(
                        1, firdes.low_pass(AUDIO_LEVEL, MPX_RATE, 15e3, 2e3)))

        if not self.stereo:
            self.audio_resamp = resampler()
            self.preemph, self.audio_lpf = audio_shaping()
            return
        self.resamp_l, self.resamp_r = resampler(), resampler()
        self.lr_add, self.lr_sub = blocks.add_ff(1), blocks.sub_ff(1)
        self.mid_half = blocks.multiply_const_ff(0.5)
        self.side_half = blocks.multiply_const_ff(0.5)
        self.mid_preemph, self.mid_lpf = audio_shaping()
        self.side_preemph, self.side_lpf = audio_shaping()
        self.side_mix = blocks.multiply_ff(1)     # side x 38 kHz carrier
        self.audio_sum = blocks.add_vff(1)        # mid + modulated side

    def _connect_audio(self):
        if not self.stereo:
            self.connect(self.audio_src, self.audio_resamp, self.preemph,
                         self.audio_lpf, (self.mpx_sum, 0))
            # The stereo carrier is still produced; nothing wants it in mono.
            self.connect((self.rds, 1), self.null_carrier)
            return
        self.connect((self.audio_src, 0), self.resamp_l)
        self.connect((self.audio_src, 1), self.resamp_r)
        self.connect(self.resamp_l, (self.lr_add, 0))
        self.connect(self.resamp_r, (self.lr_add, 1))
        self.connect(self.resamp_l, (self.lr_sub, 0))
        self.connect(self.resamp_r, (self.lr_sub, 1))
        self.connect(self.lr_add, self.mid_half, self.mid_preemph,
                     self.mid_lpf, (self.audio_sum, 0))
        self.connect(self.lr_sub, self.side_half, self.side_preemph,
                     self.side_lpf, (self.side_mix, 0))
        self.connect((self.rds, 1), (self.side_mix, 1))
        self.connect(self.side_mix, (self.audio_sum, 1))
        self.connect(self.audio_sum, (self.mpx_sum, 0))

    def _connect_all(self):
        self._connect_audio()
        self.connect((self.rds, 0), (self.mpx_sum, 1))
        self.connect(self.mpx_sum, self.mpx_resamp, self.modulator,
                     self.radio_sink)
        if hasattr(self, 'mpx_sink'):
            self.connect(self.mpx_sum, self.mpx_sink)

    def _build_flowgraph(self):
        self.rds = rds_source(self.encoder, MPX_RATE)
        self.null_carrier = blocks.null_sink(gr.sizeof_float)
        self.mpx_sum = blocks.add_vff(1)
        self._build_audio()
        # MPX up to the radio's rate, then frequency modulate. Doing it in this
        # order matters: the modulated signal is far wider than the multiplex.
        self.mpx_resamp = filter.rational_resampler_fff(
            interpolation=int(TX_RATE // MPX_RATE), decimation=1, taps=[],
            fractional_bw=0)
        self.modulator = analog.frequency_modulator_fc(
            2 * np.pi * MAX_DEVIATION / TX_RATE)

        self._power_range = resolve_power_range(self.radio_type)
        level = scale_power(self.power_percent, self._power_range)
        if self.radio_type == 'vsg':
            from apps.vsg_sink import vsg_sink
            self.radio_sink = vsg_sink(center_freq=self.freq_mhz * 1e6,
                                       sample_rate=TX_RATE, level_dbm=level)
        elif self.radio_type == 'usrp':
            self.radio_sink = uhd.usrp_sink(
                ",".join((f"addr={self.usrp_ip}", '')),
                uhd.stream_args(cpu_format="fc32", args='',
                                channels=list(range(0, 1))), "")
            self.radio_sink.set_samp_rate(TX_RATE)
            self.radio_sink.set_time_now(uhd.time_spec(time.time()),
                                         uhd.ALL_MBOARDS)
            self.radio_sink.set_center_freq(self.freq_mhz * 1e6, 0)
            self.radio_sink.set_antenna("TX/RX", 0)
            self._power_range = resolve_power_range(self.radio_type,
                                                    self.radio_sink)
            self.radio_sink.set_gain(
                scale_power(self.power_percent, self._power_range), 0)
        else:
            self.radio_sink = soapy.sink('driver=hackrf', 'fc32', 1, '', '',
                                         [''], [''])
            self.radio_sink.set_sample_rate(0, TX_RATE)
            self.radio_sink.set_frequency(0, self.freq_mhz * 1e6)

        self._connect_all()
        self._update_track_label()

    def _build_spectrum(self):
        self.mpx_sink = qtgui.freq_sink_f(
            2048, window.WIN_BLACKMAN_hARRIS, 0, MPX_RATE,
            'Transmitted baseband (MPX) - pilot 19 kHz, RDS 57 kHz', 1, None)
        self.mpx_sink.set_update_time(0.10)
        self.mpx_sink.set_y_axis(*SPECTRUM_Y_AXIS)
        self.mpx_sink.enable_grid(True)
        self.mpx_sink.enable_autoscale(False)
        self.mpx_sink.set_plot_pos_half(True)
        self.mpx_sink.disable_legend()
        self.top_grid_layout.addWidget(
            sip.wrapinstance(self.mpx_sink.qwidget(), Qt.QWidget), 1, 0, 6, 10)
        self.mpx_sink.set_line_label(0, 'MPX')
        self.connect(self.mpx_sum, self.mpx_sink)

    # ------------------------------------------------------------ controls
    def apply_power(self):
        """Set output power. On HackRF this must run after start()."""
        level = scale_power(self.power_percent, self._power_range)
        if self.radio_type == 'vsg':
            self.radio_sink.set_level(level)
        elif self.radio_type == 'usrp':
            self.radio_sink.set_gain(level, 0)
        else:
            # SoapyHackRF ignores the AMP stage before the stream is running;
            # keep it off here and drive level with the VGA alone.
            self.radio_sink.set_gain(0, 'VGA', level)
            self.radio_sink.set_gain(0, 'AMP', 0)

    def set_power(self, percent):
        self.power_percent = float(percent)
        self.pwr_value.setText(f"{int(percent)}%")
        self.apply_power()

    def set_frequency(self, mhz):
        self.freq_mhz = float(mhz)
        if self.radio_type == 'usrp':
            self.radio_sink.set_center_freq(self.freq_mhz * 1e6, 0)
        elif self.radio_type == 'vsg':
            self.radio_sink.set_frequency(0, self.freq_mhz * 1e6)
        else:
            self.radio_sink.set_frequency(0, self.freq_mhz * 1e6)

    def _update_track_label(self):
        name = track_name(self.audio_choice) if self.audio_choice not in (
            'tone', 'silence') else self.audio_choice
        self.track_label.setText(name or '-')

    def next_track(self):
        """Swap the audio file, and say so over RDS."""
        if not self.playlist:
            return
        self.track_index = (self.track_index + 1) % len(self.playlist)
        path = self.playlist[self.track_index]
        self.audio_choice = path
        # Rebuild rather than swap one block: the next track may be stereo
        # where this one was mono, which is a different chain entirely.
        self.lock()
        self.disconnect_all()
        self._build_audio()
        self._connect_all()
        self.unlock()
        self._update_track_label()
        if self.track_in_rt:
            self.encoder.set_now_playing('', track_name(path))
            self.rt_edit.setText(self.encoder.snapshot()['radiotext'])

    def closeEvent(self, event):
        self.settings = Qt.QSettings("GNU Radio", "fmRdsTransmitter")
        self.settings.setValue("geometry", self.saveGeometry())
        self.stop()
        self.wait()
        event.accept()


def main(top_block_cls=fmRdsTransmitter, options=None, app=None,
         config_values=None):
    if app is None:
        app = Qt.QApplication(sys.argv)

    tb = top_block_cls(config_values)
    tb.start()
    tb.apply_power()      # after start(), or the HackRF ignores part of it
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
    return app.exec_()


if __name__ == '__main__':
    main()
