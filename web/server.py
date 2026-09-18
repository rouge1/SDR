#!/usr/bin/env python3
"""A web front end for the launcher grid, settings and icons.

This is the app picker only. It never imports GNU Radio, Qt or SoapySDR,
never opens a radio, and never builds a flowgraph: it serves a page, reads
and writes ``config/window_settings.json``, and starts each app as its own
process through ``apps/_run.py``. The flowgraph and its configuration
dialog are the ones that already exist, unchanged, and they open on the
display this server can reach - a browser on a phone picks and configures,
the window comes up on the bench monitor.

``RFbenchToolkit.py`` is untouched and still works; this is a second
front end onto the same tables and the same settings file, not a
replacement.

    python web/server.py                 # http://127.0.0.1:8730
    python web/server.py --host 0.0.0.0  # prints a URL with a token in it

Two things this deliberately does not do:

* **Touch a radio.** The presence checks run in ``scripts/probe_radio.py``,
  a process that exits - see the note there about the USB handle that a
  HackRF enumerate leaves behind. A server that lives for days must not be
  the one holding it.
* **Listen off the machine without a token.** Every tile here keys a
  transmitter, and CLAUDE.md is blunt that the lowest power setting is
  still 32.5 dB out of the noise. Loopback is open because sitting at the
  machine is already the permission; anything wider has to be asked for.

Run it with the ``gnu`` environment's Python, so the children it spawns
inherit an interpreter that has GNU Radio.
"""

import argparse
import ast
import json
import mimetypes
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# The one import from apps/, and a deliberate one: theme.py is the palette
# and the type scale that the desktop launcher paints from, and it brings
# in nothing but the standard library at module level. Everything else in
# apps/ pulls GNU Radio or Qt, which is why this server reads the tile
# tables out of the launcher's source rather than importing it.
from apps import theme  # noqa: E402
WEB = os.path.join(ROOT, 'web')
SETTINGS = os.path.join(ROOT, 'config', 'window_settings.json')
PROBE = os.path.join(ROOT, 'scripts', 'probe_radio.py')
RUNNER = os.path.join(ROOT, 'apps', '_run.py')

DIRECTION_WORDS = {'tx': 'transmit', 'rx': 'receive'}
RADIO_LABELS = {
    'hackrf': 'HackRF One', 'usrp': 'Ettus USRP',
    'vsg': 'Signal Hound VSG60', 'bb60': 'Signal Hound BB60D',
}


# --------------------------------------------------------------- the tables
def launcher_literal(name):
    """Read a module-level literal out of the launcher without importing it.

    Importing it would open a window and pull in PyQt5, neither of which
    belongs in a web server. ``scripts/test_launcher_gui.py`` reads the
    same tables the same way and for the same reason - keep APP_TILES a
    plain literal and both keep working.
    """
    with open(os.path.join(ROOT, 'RFbenchToolkit.py')) as fh:
        src = fh.read()
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(
                getattr(t, 'id', None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise RuntimeError(f"no {name} in RFbenchToolkit.py")


def banks():
    """APP_TILES as the page wants it: rows of tiles, each with its faces."""
    # The headings live beside APP_TILES now, so the desktop grid and this
    # page cannot end up calling the same row different things.
    names = launcher_literal('BANK_NAMES')
    rows = {}
    for row, col, faces in launcher_literal('APP_TILES'):
        rows.setdefault(row, []).append((col, [
            {'label': f[0], 'module': f[1], 'icon': f[2], 'dir': f[3]}
            for f in faces]))
    out = []
    for row in sorted(rows):
        tiles = [faces for _col, faces in sorted(rows[row])]
        out.append({'name': names.get(row, f"Row {row}"), 'tiles': tiles})
    return out


def face_directions():
    return {f['module']: f['dir'] for b in banks()
            for t in b['tiles'] for f in t}


# ------------------------------------------------------------- the settings
def read_settings():
    try:
        with open(SETTINGS) as fh:
            data = json.load(fh)
    except Exception:
        data = {}
    data.setdefault('media_directory', '')
    data.setdefault('ip_addresses', [])
    data.setdefault('radio_mode', 'single')
    data.setdefault('radio_type', 'hackrf')
    return data


def write_settings(changes):
    """Merge into the file the desktop launcher also reads and writes.

    Merged rather than replaced so window_position, dialog_position and
    the per-tile flip state the desktop app keeps here all survive being
    edited from a browser.
    """
    data = {}
    try:
        with open(SETTINGS) as fh:
            data = json.load(fh)
    except Exception:
        pass
    data.update(changes)
    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    tmp = SETTINGS + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(data, fh, indent=4)
    os.replace(tmp, SETTINGS)
    return data


# -------------------------------------------------------- what is running
class Running:
    """The apps this server started, and whether they are still up.

    The desktop launcher hides itself in single mode and reappears when
    the app closes, which a browser cannot do. Holding the processes
    instead gives the page something better: a list of what is on, and a
    button that stops it.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._procs = {}

    def add(self, proc, module, label):
        with self._lock:
            self._procs[proc.pid] = {
                'proc': proc, 'module': module, 'label': label,
                'started': time.time()}

    def list(self):
        with self._lock:
            for pid in [p for p, e in self._procs.items()
                        if e['proc'].poll() is not None]:
                del self._procs[pid]
            return [{'pid': pid, 'module': e['module'], 'label': e['label'],
                     'seconds': int(time.time() - e['started'])}
                    for pid, e in sorted(self._procs.items())]

    def stop(self, pid):
        with self._lock:
            entry = self._procs.get(pid)
        if entry is None:
            return False
        # Each app installs a SIGTERM handler that stops the flowgraph,
        # waits for it and quits Qt, so terminate is the clean exit.
        try:
            entry['proc'].terminate()
        except Exception:
            return False
        return True


RUNNING = Running()


def probe_radio(radio_type, python=None):
    """Presence check, in a process that exits and takes its handles with it."""
    try:
        out = subprocess.run(
            [python or sys.executable, PROBE, radio_type],
            cwd=ROOT, capture_output=True, text=True, timeout=30)
        return json.loads(out.stdout.strip().splitlines()[-1])
    except subprocess.TimeoutExpired:
        return {'ok': False, 'title': 'Radio Check Timed Out',
                'detail': "Looking for the radio took more than 30 seconds. "
                          "It may be held open by another program."}
    except Exception as exc:
        return {'ok': False, 'title': 'Radio Check Failed',
                'detail': f"{PROBE} did not answer: {exc}"}


def launch(module, app_python=None):
    """Everything launch_application checks, then a subprocess instead."""
    settings = read_settings()
    radio_type = settings.get('radio_type', 'hackrf')

    directions = launcher_literal('RADIO_DIRECTIONS').get(
        radio_type, {'tx', 'rx'})
    wanted = face_directions().get(module)
    if wanted is None:
        return {'ok': False, 'title': 'Unknown App',
                'detail': f"{module} is not in the launcher's tile table."}
    if wanted not in directions:
        word = DIRECTION_WORDS.get(wanted, wanted)
        radio = RADIO_LABELS.get(radio_type, 'The selected radio')
        return {'ok': False, 'title': f"This Radio Cannot {word.capitalize()}",
                'detail': f"{radio} cannot {word}, so it cannot run this "
                          f"application.\n\nChoose a different radio in "
                          f"Settings, or a tile that this one can run."}

    if settings.get('radio_mode', 'single') == 'single':
        already = RUNNING.list()
        if already:
            return {'ok': False, 'title': 'Already Running',
                    'detail': f"{already[0]['label']} is running, and the "
                              f"radio is in single mode.\n\nStop it first, or "
                              f"switch to multi mode in Settings."}

    if sys.platform.startswith('linux') and not os.environ.get('DISPLAY'):
        return {'ok': False, 'title': 'No Display',
                'detail': "This server has no DISPLAY, so the app would have "
                          "nowhere to put its window.\n\nStart the server "
                          "from the desktop session that owns the screen."}

    check = probe_radio(radio_type, app_python)
    if not check.get('ok'):
        return {'ok': False, 'title': check.get('title', 'Radio Not Found'),
                'detail': check.get('detail', '')}

    label = next((f['label'] for b in banks() for t in b['tiles']
                  for f in t if f['module'] == module), module)
    try:
        proc = subprocess.Popen([app_python or sys.executable, RUNNER, module],
                                cwd=ROOT, env=os.environ.copy())
    except Exception as exc:
        return {'ok': False, 'title': 'Could Not Start',
                'detail': f"{module} would not start: {exc}"}

    RUNNING.add(proc, module, label)
    return {'ok': True, 'pid': proc.pid, 'label': label}


# ----------------------------------------------------------------- serving
class Handler(BaseHTTPRequestHandler):
    server_version = "SDRLauncher/1.0"
    token = None
    app_python = None

    def log_message(self, fmt, *args):
        if self.path.startswith('/api/'):
            sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    # ------------------------------------------------------------ plumbing
    def _json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, status=200):
        try:
            with open(path, 'rb') as fh:
                body = fh.read()
        except OSError:
            return self._json({'error': 'not found'}, 404)
        ctype = mimetypes.guess_type(path)[0] or 'application/octet-stream'
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        try:
            n = int(self.headers.get('Content-Length', 0))
            return json.loads(self.rfile.read(n) or b'{}')
        except Exception:
            return {}

    def _authorised(self, query):
        if not self.token:
            return True
        given = self.headers.get('X-Launch-Token') or (query.get('t') or [''])[0]
        return secrets.compare_digest(given, self.token)

    # --------------------------------------------------------------- routes
    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        path = url.path

        if path in ('/', '/index.html'):
            return self._file(os.path.join(WEB, 'index.html'))

        # Generated rather than a file: the page's :root and its @font-face
        # rules come from apps/theme.py, the same tokens the launcher
        # window is painted with, so the two front ends cannot drift.
        if path == '/theme.css':
            body = theme.css().encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/css; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            return self.wfile.write(body)

        if path == '/favicon.ico':
            return self._file(os.path.join(ROOT, 'icons', 'gnuradio.jpg'))

        if path.startswith('/icons/'):
            name = os.path.basename(path)
            target = os.path.join(ROOT, 'icons', name)
            if os.path.dirname(os.path.abspath(target)) != os.path.join(ROOT, 'icons'):
                return self._json({'error': 'not found'}, 404)
            return self._file(target)

        # The page's typefaces, served from the repo rather than fetched
        # from a font CDN: the bench is not always on a network, and a page
        # that silently falls back to Helvetica stops matching the desktop
        # launcher for a reason nobody would guess. Same containment check
        # as the icons.
        if path.startswith('/fonts/'):
            name = os.path.basename(path)
            target = os.path.join(ROOT, 'fonts', name)
            if os.path.dirname(os.path.abspath(target)) != os.path.join(ROOT, 'fonts'):
                return self._json({'error': 'not found'}, 404)
            return self._file(target)

        if path == '/api/state':
            if not self._authorised(query):
                return self._json({'error': 'bad token'}, 403)
            settings = read_settings()
            return self._json({
                'banks': banks(),
                'settings': settings,
                'running': RUNNING.list(),
                'directions': {k: sorted(v) for k, v in
                               launcher_literal('RADIO_DIRECTIONS').items()},
                'radio_labels': RADIO_LABELS,
                'display': bool(os.environ.get('DISPLAY'))
                           or not sys.platform.startswith('linux'),
                'host': socket.gethostname(),
            })

        return self._json({'error': 'not found'}, 404)

    def do_POST(self):
        url = urlparse(self.path)
        if not self._authorised(parse_qs(url.query)):
            return self._json({'error': 'bad token'}, 403)
        body = self._body()

        if url.path == '/api/launch':
            module = str(body.get('module', ''))
            result = launch(module, self.app_python)
            return self._json(result, 200 if result.get('ok') else 409)

        if url.path == '/api/stop':
            try:
                pid = int(body.get('pid'))
            except (TypeError, ValueError):
                return self._json({'ok': False, 'detail': 'no pid'}, 400)
            return self._json({'ok': RUNNING.stop(pid)})

        if url.path == '/api/settings':
            changes = {}
            for key in ('media_directory', 'radio_mode', 'radio_type'):
                if key in body:
                    changes[key] = body[key]
            if 'ip_addresses' in body:
                changes['ip_addresses'] = [
                    str(a).strip() for a in body['ip_addresses'] if str(a).strip()]
            # The same rule the desktop settings dialog enforces: multi mode
            # is meaningless without a second radio to point at.
            merged = {**read_settings(), **changes}
            if merged['radio_mode'] == 'multi' and len(merged['ip_addresses']) < 2:
                return self._json(
                    {'ok': False, 'title': 'Multi Mode Needs Two Addresses',
                     'detail': "Multi mode drives more than one USRP, so it "
                               "needs at least two IP addresses."}, 400)
            return self._json({'ok': True, 'settings': write_settings(changes)})

        return self._json({'error': 'not found'}, 404)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8730)
    parser.add_argument('--token', help="required when --host is not loopback")
    parser.add_argument('--app-python', default=sys.executable,
                        help="interpreter for the apps (default: this one)")
    args = parser.parse_args(argv)

    loopback = args.host in ('127.0.0.1', 'localhost', '::1')
    token = args.token
    if not loopback and not token:
        # Off-machine means anyone on the network could key a transmitter.
        token = secrets.token_urlsafe(16)

    Handler.token = None if loopback and not token else token
    Handler.app_python = args.app_python

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    where = f"http://{args.host}:{args.port}/"
    if Handler.token:
        where += f"?t={Handler.token}"
    print(f"Launcher on {where}")
    if not loopback:
        print("Open to the network - this page starts transmitters. The "
              "token above is the only thing in the way.")
    if sys.platform.startswith('linux') and not os.environ.get('DISPLAY'):
        print("No DISPLAY here: apps would have nowhere to draw. Start this "
              "from the desktop session that owns the screen.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
        for entry in RUNNING.list():
            RUNNING.stop(entry['pid'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
