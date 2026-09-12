#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# SPDX-License-Identifier: GPL-3.0
#
# RDS / RBDS Receiver - tunes an FM broadcast station and decodes the data
# carried on its 57 kHz subcarrier (station ID, program service name,
# RadioText, program type, clock time).
#
# This is the only receiving application in the launcher, so unlike the
# transmitters it picks its own radio: the Signal Hound VSG60 can only
# transmit, and the global radio_type setting may well be set to it.

import json
import os
import signal
import sys
import threading

import numpy as np  # type: ignore
try:                 # PyQt5 ships sip inside the package; some builds also
    import sip       # expose it at the top level.
except ImportError:  # pragma: no cover - depends on the PyQt5 build
    from PyQt5 import sip  # type: ignore
from gnuradio import analog, audio, blocks, filter, gr, qtgui, soapy, uhd  # type: ignore
from gnuradio.fft import window  # type: ignore
from gnuradio.filter import firdes  # type: ignore
from PyQt5 import Qt, QtCore  # type: ignore

from apps.rds_core import RdsDemod, RdsProtocol
from apps.utils import apply_dark_theme, read_settings, SPECTRUM_Y_AXIS

SAMP_RATE = 2e6
MPX_RATE = 250e3          # 2 MS/s / 8
DECIM = int(SAMP_RATE // MPX_RATE)
LO_OFFSET = 300e3         # keep the station clear of the radio's DC spike
AUDIO_RATE = 48000
MAX_DEVIATION = 75e3


def rx_gain_plan(percent, radio_type):
    """Map the 0-100% slider onto a receiver's own gain controls.

    HackRF splits its receive gain across three stages, so spread the slider
    over them: the preamp first (it improves the noise figure), then the LNA in
    its 8 dB steps, then the baseband VGA in 2 dB steps.

    How much gain is right depends almost entirely on the antenna, so the
    slider covers a wide span and both failure modes are worth recognising:
    a pilot that locks while RDS stays buried means too little gain, whereas
    samples pinned near full scale mean too much. On a modest antenna ~68 dB
    (preamp + LNA 24 + VGA 30) was needed; on a good one that clips, and
    ~54 dB (preamp + LNA 16 + VGA 24) is right.
    """
    percent = min(max(float(percent), 0.0), 100.0)
    if radio_type != 'hackrf':
        return {}
    amp = 14.0 if percent >= 20 else 0.0
    total = percent / 100.0 * 102.0
    lna = min(40.0, round(total * 0.45 / 8.0) * 8.0)
    vga = min(62.0, max(0.0, round((total - lna) / 2.0) * 2.0))
    return {'AMP': amp, 'LNA': lna, 'VGA': vga}


class ConfigDialog(Qt.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("RDS Receiver Configuration")
        self.layout = Qt.QVBoxLayout(self)
        self.config_dir = "config"
        self.config_file = os.path.join(self.config_dir, "rdsReceiver_config.json")

        settings = read_settings()
        self.ipList = settings.get('ip_addresses', [])

        self.button_box = Qt.QDialogButtonBox(
            Qt.QDialogButtonBox.Ok | Qt.QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        self.create_receiver_selector(settings)
        self.create_frequency_control()
        self.create_gain_control()
        self.create_options()

        self.layout.addWidget(self.button_box)
        self.load_config()
        self.update_ok_state()
        apply_dark_theme(self)

    def create_receiver_selector(self, settings):
        self.layout.addWidget(Qt.QLabel("Receiver:"))
        self.radio_combo = Qt.QComboBox()
        self.radio_combo.addItem("HackRF One (USB)", "hackrf")
        self.radio_combo.addItem("Ettus USRP (Network)", "usrp")
        # The VSG60 transmits only, so fall back to the HackRF when it is the
        # configured radio rather than offering something that cannot receive.
        current = settings.get('radio_type', 'hackrf')
        self.radio_combo.setCurrentIndex(1 if current == 'usrp' else 0)
        self.radio_combo.currentIndexChanged.connect(self.update_ok_state)
        self.layout.addWidget(self.radio_combo)

        self.usrp_combo = Qt.QComboBox()
        if self.ipList:
            for i, ip in enumerate(self.ipList):
                self.usrp_combo.addItem(f"USRP {i+1} ({ip.strip()})", ip.strip())
        else:
            self.usrp_combo.addItem("IP addr missing - Go to Settings")
        self.layout.addWidget(self.usrp_combo)

        note = Qt.QLabel("The Signal Hound VSG60 cannot receive, so it is not listed.")
        note.setWordWrap(True)
        self.layout.addWidget(note)

    def create_frequency_control(self):
        row = Qt.QHBoxLayout()
        row.addWidget(Qt.QLabel("Station Frequency (MHz):"))
        self.freq_spin = Qt.QDoubleSpinBox()
        self.freq_spin.setDecimals(1)
        self.freq_spin.setSingleStep(0.1)
        self.freq_spin.setRange(87.5, 108.0)
        self.freq_spin.setValue(98.7)
        row.addWidget(self.freq_spin)
        self.layout.addLayout(row)

    def create_gain_control(self):
        row = Qt.QHBoxLayout()
        self.gain_slider = Qt.QSlider(QtCore.Qt.Horizontal)
        self.gain_slider.setRange(0, 100)
        self.gain_slider.setValue(40)
        self.gain_label = Qt.QLabel("RF Gain: 40%")
        self.gain_slider.valueChanged.connect(
            lambda v: self.gain_label.setText(f"RF Gain: {v}%"))
        row.addWidget(self.gain_label)
        row.addWidget(self.gain_slider)
        self.layout.addLayout(row)

    def create_options(self):
        self.layout.addWidget(Qt.QLabel("Data Standard:"))
        self.region_combo = Qt.QComboBox()
        self.region_combo.addItem("RBDS (North America)", "RBDS")
        self.region_combo.addItem("RDS (Europe / rest of world)", "RDS")
        self.layout.addWidget(self.region_combo)

        self.audio_check = Qt.QCheckBox("Play station audio")
        self.audio_check.setChecked(True)
        self.layout.addWidget(self.audio_check)

    def update_ok_state(self):
        needs_ip = self.radio_combo.currentData() == 'usrp'
        ok = self.button_box.button(Qt.QDialogButtonBox.Ok)
        enabled = (not needs_ip) or bool(self.ipList)
        ok.setEnabled(enabled)
        if enabled:
            ok.setGraphicsEffect(None)
        else:
            dim = Qt.QGraphicsOpacityEffect()
            dim.setOpacity(0.30)
            ok.setGraphicsEffect(dim)

    def load_config(self):
        if not os.path.exists(self.config_file):
            os.makedirs(self.config_dir, exist_ok=True)
            return
        try:
            with open(self.config_file) as f:
                config = json.load(f)
        except Exception as exc:
            print(f"RDS receiver: could not read saved config: {exc}",
                  file=sys.stderr)
            return
        # Restore each setting independently: one unreadable value must not
        # discard everything saved after it.
        for key, apply in (
            ('radio_type', lambda v: self.radio_combo.setCurrentIndex(
                1 if v == 'usrp' else 0)),
            ('usrp_index', lambda v: self.usrp_combo.setCurrentIndex(int(v))),
            ('frequency_mhz', lambda v: self.freq_spin.setValue(float(v))),
            ('gain_percent', lambda v: self.gain_slider.setValue(int(v))),
            ('region', lambda v: self.region_combo.setCurrentIndex(
                1 if v == 'RDS' else 0)),
            ('audio', lambda v: self.audio_check.setChecked(bool(v))),
        ):
            if key in config:
                try:
                    apply(config[key])
                except Exception as exc:
                    print(f"RDS receiver: ignoring saved {key!r}: {exc}",
                          file=sys.stderr)

    def save_config(self):
        config = {
            'radio_type': self.radio_combo.currentData(),
            'usrp_index': max(self.usrp_combo.currentIndex(), 0),
            'frequency_mhz': self.freq_spin.value(),
            'gain_percent': self.gain_slider.value(),
            'region': self.region_combo.currentData(),
            'audio': self.audio_check.isChecked(),
        }
        os.makedirs(self.config_dir, exist_ok=True)
        with open(self.config_file, 'w') as f:
            json.dump(config, f, indent=4)

    def accept(self):
        self.save_config()
        super().accept()

    def get_values(self):
        radio_type = self.radio_combo.currentData()
        ip = self.usrp_combo.currentData() if self.ipList else ''
        return {
            'radio_type': radio_type,
            'ipXmitAddr': ip or '',
            'ipNum': self.usrp_combo.currentIndex() + 1 if self.ipList else 0,
            'frequency_mhz': self.freq_spin.value(),
            'gain_percent': self.gain_slider.value(),
            'region': self.region_combo.currentData(),
            'audio': self.audio_check.isChecked(),
        }


class rds_sink(gr.sync_block):
    """Bridges the flowgraph to the RDS decoder in apps/rds_core.py.

    Takes the MPX baseband and the PLL's 19 kHz pilot reference. All the
    per-sample work is vectorised numpy, and the protocol layer only sees
    1187.5 bits per second, so this keeps up with real time comfortably.
    """

    def __init__(self, mpx_rate, region):
        gr.sync_block.__init__(self, name='rds_sink',
                               in_sig=[np.float32, np.complex64], out_sig=None)
        self.demod = RdsDemod(mpx_rate)
        self.proto = RdsProtocol(region=region)
        self._lock = threading.Lock()

    def work(self, input_items, output_items):
        n = min(len(input_items[0]), len(input_items[1]))
        # Hold the lock across both stages: retuning swaps them out from the Qt
        # thread, which must not happen midway through a chunk.
        with self._lock:
            bits = self.demod.feed(input_items[0][:n], input_items[1][:n])
            if len(bits):
                self.proto.feed(bits)
        return n

    def reset(self, mpx_rate, region):
        """Throw away decoded state and re-measure timing, after a retune."""
        with self._lock:
            self.demod = RdsDemod(mpx_rate)
            self.proto = RdsProtocol(region=region)

    def snapshot(self):
        with self._lock:
            return self.proto.snapshot()


class rdsReceiver(gr.top_block, Qt.QWidget):
    def __init__(self, config_values=None):
        gr.top_block.__init__(self, "RDS Receiver", catch_exceptions=True)
        Qt.QWidget.__init__(self)
        self.setWindowTitle("RDS / RBDS Receiver")
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

        self.settings = Qt.QSettings("GNU Radio", "rdsReceiver")
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
        self.freq_mhz = float(values.get('frequency_mhz', 98.7))
        self.gain_percent = float(values.get('gain_percent', 40))
        self.region = values.get('region', 'RBDS')
        self.want_audio = bool(values.get('audio', True))
        self.usrp_ip = values.get('ipXmitAddr', '')

        self._build_controls()
        self._build_flowgraph()
        self._build_readout()

        self.status_timer = Qt.QTimer(self)
        self.status_timer.timeout.connect(self.refresh_readout)
        self.status_timer.start(400)

    # ------------------------------------------------------------------ UI
    def _build_controls(self):
        row = Qt.QHBoxLayout()
        row.addWidget(Qt.QLabel("Station (MHz):"))
        self.freq_spin = Qt.QDoubleSpinBox()
        self.freq_spin.setDecimals(1)
        self.freq_spin.setSingleStep(0.1)
        self.freq_spin.setRange(87.5, 108.0)
        self.freq_spin.setValue(self.freq_mhz)
        self.freq_spin.valueChanged.connect(self.set_frequency)
        row.addWidget(self.freq_spin)

        row.addSpacing(20)
        row.addWidget(Qt.QLabel("RF Gain:"))
        self.gain_slider = Qt.QSlider(QtCore.Qt.Horizontal)
        self.gain_slider.setRange(0, 100)
        self.gain_slider.setValue(int(self.gain_percent))
        self.gain_slider.valueChanged.connect(self.set_gain)
        row.addWidget(self.gain_slider)
        self.gain_value = Qt.QLabel(f"{int(self.gain_percent)}%")
        row.addWidget(self.gain_value)

        row.addSpacing(20)
        self.reset_btn = Qt.QPushButton("Clear Decoded Data")
        self.reset_btn.clicked.connect(self.reset_decoder)
        row.addWidget(self.reset_btn)
        row.addStretch()

        holder = Qt.QWidget()
        holder.setLayout(row)
        self.top_grid_layout.addWidget(holder, 0, 0, 1, 10)

    def _build_readout(self):
        box = Qt.QGroupBox("Decoded Station Data")
        grid = Qt.QGridLayout()
        box.setLayout(grid)
        big = Qt.QFont()
        big.setPointSize(15)
        big.setBold(True)
        mono = Qt.QFont("Monospace")
        mono.setStyleHint(Qt.QFont.TypeWriter)
        mono.setPointSize(13)

        self.lbl = {}
        def add(key, caption, row, col, font=None, span=1):
            grid.addWidget(Qt.QLabel(f"<b>{caption}</b>"), row, col * 2)
            value = Qt.QLabel("-")
            if font:
                value.setFont(font)
            value.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            value.setWordWrap(True)
            grid.addWidget(value, row, col * 2 + 1, 1, span)
            self.lbl[key] = value

        add('station_name', "Station", 0, 0, big)
        add('pi', "Station ID (PI)", 0, 1)
        add('pty', "Program Type", 0, 2)
        add('ps', "Now showing (PS)", 1, 0, mono, span=5)
        add('nowplaying', "Now Playing", 2, 0, big, span=5)
        add('radiotext', "RadioText", 3, 0, mono, span=5)
        add('flags', "Flags", 4, 0)
        add('clock', "Station Clock", 4, 1)
        add('quality', "Decode Quality", 4, 2)
        self.top_grid_layout.addWidget(box, 1, 0, 1, 10)

    # ----------------------------------------------------------- flowgraph
    def _build_flowgraph(self):
        lo_hz = self.freq_mhz * 1e6 - LO_OFFSET
        if self.radio_type == 'usrp':
            self.radio_source = uhd.usrp_source(
                ",".join((f"addr={self.usrp_ip}", '')),
                uhd.stream_args(cpu_format="fc32", args='',
                                channels=list(range(0, 1))),
            )
            self.radio_source.set_samp_rate(SAMP_RATE)
            self.radio_source.set_center_freq(lo_hz, 0)
            self.radio_source.set_antenna("RX2", 0)
        else:
            self.radio_source = soapy.source('driver=hackrf', 'fc32', 1, '', '',
                                             [''], [''])
            self.radio_source.set_sample_rate(0, SAMP_RATE)
            self.radio_source.set_frequency(0, lo_hz)
            self.radio_source.set_gain_mode(0, False)

        # Shift the station from the LO offset down to DC and decimate to MPX.
        self.channel = filter.freq_xlating_fir_filter_ccf(
            DECIM, firdes.low_pass(1.0, SAMP_RATE, 100e3, 20e3),
            LO_OFFSET, SAMP_RATE)
        self.demod = analog.quadrature_demod_cf(MPX_RATE / (2 * np.pi * MAX_DEVIATION))

        # Pilot reference: band-pass the 19 kHz tone and lock a PLL to it. Its
        # third harmonic is the RDS subcarrier and its 16th subharmonic is the
        # bit clock, so this one lock drives both.
        self.to_complex = blocks.float_to_complex(1)
        self.pilot_bpf = filter.fir_filter_ccc(
            1, firdes.complex_band_pass(1.0, MPX_RATE, 18.2e3, 19.8e3, 500))
        self.pilot_pll = analog.pll_refout_cc(
            0.001,
            2 * np.pi * 19.2e3 / MPX_RATE,
            2 * np.pi * 18.8e3 / MPX_RATE)
        self.rds = rds_sink(MPX_RATE, self.region)

        self.connect(self.radio_source, self.channel, self.demod)
        self.connect(self.demod, self.to_complex)
        self.connect(self.to_complex, self.pilot_bpf, self.pilot_pll)
        self.connect(self.demod, (self.rds, 0))
        self.connect(self.pilot_pll, (self.rds, 1))

        # Pilot strength, for the stereo indicator.
        self.pilot_mag = blocks.complex_to_mag_squared(1)
        self.pilot_avg = filter.single_pole_iir_filter_ff(1e-4)
        self.pilot_probe = blocks.probe_signal_f()
        self.connect(self.pilot_bpf, self.pilot_mag, self.pilot_avg,
                     self.pilot_probe)

        self._build_spectrum()

        if self.want_audio:
            self._build_audio()

    def _build_audio(self):
        # Mono audio is the 0-15 kHz part of the MPX.
        self.audio_lpf = filter.fir_filter_fff(
            1, firdes.low_pass(1.0, MPX_RATE, 15e3, 3e3))
        self.audio_resamp = filter.rational_resampler_fff(
            interpolation=24, decimation=125, taps=[], fractional_bw=0)
        self.deemph = analog.fm_deemph(AUDIO_RATE, 75e-6)
        self.volume = blocks.multiply_const_ff(0.4)
        try:
            self.audio_out = audio.sink(AUDIO_RATE, '', True)
        except Exception as exc:
            print(f"RDS receiver: audio output unavailable ({exc})",
                  file=sys.stderr)
            self.want_audio = False
            return
        self.connect(self.demod, self.audio_lpf, self.audio_resamp,
                     self.deemph, self.volume, self.audio_out)

    def _build_spectrum(self):
        self.mpx_sink = qtgui.freq_sink_f(
            2048, window.WIN_BLACKMAN_hARRIS, 0, MPX_RATE,
            'FM Baseband (MPX) - pilot 19 kHz, stereo 38 kHz, RDS 57 kHz', 1,
            None)
        self.mpx_sink.set_update_time(0.10)
        self.mpx_sink.set_y_axis(*SPECTRUM_Y_AXIS)
        self.mpx_sink.set_y_label('Relative Gain', 'dB')
        self.mpx_sink.set_trigger_mode(qtgui.TRIG_MODE_FREE, 0.0, 0, "")
        self.mpx_sink.enable_autoscale(True)
        self.mpx_sink.enable_grid(True)
        self.mpx_sink.set_fft_average(0.2)
        self.mpx_sink.enable_axis_labels(True)
        self.mpx_sink.enable_control_panel(False)
        self.mpx_sink.set_plot_pos_half(True)
        self.mpx_sink.disable_legend()
        widget = sip.wrapinstance(self.mpx_sink.qwidget(), Qt.QWidget)
        self.top_grid_layout.addWidget(widget, 2, 0, 6, 10)
        self.connect(self.demod, self.mpx_sink)

    # ------------------------------------------------------------ controls
    def apply_gain(self):
        """Set receive gain. Must run after start() - see below."""
        if self.radio_type == 'usrp':
            try:
                rng = self.radio_source.get_gain_range()
                low, high = float(rng.start()), float(rng.stop())
            except Exception:
                low, high = 0.0, 76.0
            self.radio_source.set_gain(
                low + (high - low) * self.gain_percent / 100.0, 0)
            return
        # SoapyHackRF silently ignores the AMP stage when it is set before the
        # stream is running, so gains are applied once the flowgraph is going.
        for name, value in rx_gain_plan(self.gain_percent, 'hackrf').items():
            self.radio_source.set_gain(0, name, value)

    def set_gain(self, percent):
        self.gain_percent = float(percent)
        self.gain_value.setText(f"{int(percent)}%")
        self.apply_gain()

    def set_frequency(self, mhz):
        self.freq_mhz = float(mhz)
        lo_hz = self.freq_mhz * 1e6 - LO_OFFSET
        if self.radio_type == 'usrp':
            self.radio_source.set_center_freq(lo_hz, 0)
        else:
            self.radio_source.set_frequency(0, lo_hz)
        self.reset_decoder()

    def reset_decoder(self):
        self.rds.reset(MPX_RATE, self.region)

    # ------------------------------------------------------------- readout
    def refresh_readout(self):
        snap = self.rds.snapshot()
        # NRSC-G300 recommends RT+ StationName over anything derived from the
        # PI, so prefer it when the station sends one.
        name = snap['station_short'] or snap['station_name'] or '(waiting)'
        self.lbl['station_name'].setText(name)

        title, artist = snap['title'], snap['artist']
        self.lbl['nowplaying'].setText(
            ' - '.join(x for x in (artist, title) if x) if (title or artist)
            else '-')

        pi_text = snap['pi_hex'] or '-'
        if snap['callsign_confirmed']:
            # Corroborated by the station's own PS/RadioText, so state it plainly.
            pi_text += f"  ({snap['callsign_confirmed']})"
        elif snap['callsign']:
            # Plenty of US stations use a PI that does not follow the call-sign
            # formula, so an uncorroborated mapping stays explicitly a guess.
            pi_text += f"  (maybe {snap['callsign']})"
        self.lbl['pi'].setText(pi_text)
        self.lbl['pty'].setText(snap['pty'] or '-')
        self.lbl['ps'].setText(snap['ps'] or '-')
        self.lbl['radiotext'].setText(snap['radiotext'] or '-')

        flags = []
        if snap['tp']:
            flags.append("Traffic Program")
        if snap['ta']:
            flags.append("Traffic Announcement")
        pilot = self.pilot_probe.level()
        stereo = pilot > 1e-4
        flags.append("Stereo pilot locked" if stereo else "No pilot")
        self.lbl['flags'].setText(", ".join(flags))

        clock = snap['clock']
        if clock:
            self.lbl['clock'].setText(
                f"{clock['year']:04d}-{clock['month']:02d}-{clock['day']:02d} "
                f"{clock['hour']:02d}:{clock['minute']:02d} "
                f"(UTC{clock['utc_offset_hours']:+g})")
        else:
            self.lbl['clock'].setText('-')

        seen = snap['blocks_seen']
        if seen:
            self.lbl['quality'].setText(
                f"{snap['groups']} groups, "
                f"{100*(1-(snap['block_error_rate'] or 0)):.0f}% blocks good")
        else:
            self.lbl['quality'].setText('searching...')

    def closeEvent(self, event):
        self.settings = Qt.QSettings("GNU Radio", "rdsReceiver")
        self.settings.setValue("geometry", self.saveGeometry())
        self.status_timer.stop()
        self.stop()
        self.wait()
        event.accept()


def main(top_block_cls=rdsReceiver, options=None, app=None, config_values=None):
    if app is None:
        app = Qt.QApplication(sys.argv)

    tb = top_block_cls(config_values)
    tb.start()
    # Gains go on after the stream exists: the HackRF's preamp is ignored
    # otherwise.
    tb.apply_gain()
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
