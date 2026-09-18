#!/usr/bin/env python3
"""Closing an app's window brings the launcher back - for every app, no radio.

    python scripts/test_app_close.py                # every app in apps/
    python scripts/test_app_close.py atscXmitter    # just the ones named

In single mode the launcher hides while an app runs, and gets itself back by
wrapping the ``closeEvent`` of whatever the app's ``main()`` returns. That
only works if ``main()`` returns the window. The ATSC transmitter's called
``app.exec_()`` instead - which, with the launcher's loop already running,
returns -1 at once - and replaced the window's ``closeEvent`` with one that
called ``app.quit()``. So the launcher got an int, never hooked the close,
and closing the window quit the launcher's own event loop: the tile grid
never came back, because the launcher was gone.

This runs each app's real ``main()`` the way ``launch_application`` does -
the launcher's QApplication already running its loop, the launcher window
hidden, the launcher's wrapper applied to what comes back - with a stand-in
window in place of the flowgraph, so no radio and no display are needed.
Then it closes the window and requires the launcher to be visible again and
its loop still running.

Each app runs in its own process: one that gets this wrong ends the event
loop, and ``main()`` installs signal handlers that should not leak into the
next app's run.
"""
import importlib.util
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def apps_with_main():
    found = []
    for name in sorted(os.listdir(os.path.join(ROOT, 'apps'))):
        # A leading underscore means a helper rather than an app. `_run.py`
        # has a `main()` of its own - it is the thing that *runs* an app for
        # the web launcher - and taking it for one failed here on every run
        # with a signature error that said nothing about any app.
        if not name.endswith('.py') or name.startswith('_'):
            continue
        with open(os.path.join(ROOT, 'apps', name)) as f:
            if re.search(r'^def main\(', f.read(), re.MULTILINE):
                found.append(name[:-3])
    return found


def child(name):
    """One app, in this process. Prints one result line."""
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    os.chdir(ROOT)
    sys.path.insert(0, ROOT)
    from PyQt5 import Qt, QtCore

    app = Qt.QApplication([])

    class StandIn(Qt.QWidget):
        """Takes the flowgraph's place: a window with start/stop/wait."""

        def __init__(self, config_values=None):
            super().__init__()
            self.setWindowTitle(name)

        def start(self):
            pass

        def stop(self):
            pass

        def wait(self):
            pass

        def closeEvent(self, event):
            event.accept()

        def __getattr__(self, attr):
            # Anything else main() calls on the flowgraph - apply_gain(),
            # close_stream() - does nothing.
            if attr.startswith('_'):
                raise AttributeError(attr)
            return lambda *args, **kwargs: None

    spec = importlib.util.spec_from_file_location(name, f'apps/{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    launcher = Qt.QWidget()
    launcher.show()
    state = {'returned': '-', 'loop_survived': False, 'launcher_back': False}

    def open_app():
        launcher.hide()
        tb = module.main(top_block_cls=StandIn, app=app, config_values={})
        state['returned'] = type(tb).__name__
        # As RFbenchToolkit.py launch_application does, in single mode.
        if hasattr(tb, 'closeEvent'):
            original_close_event = tb.closeEvent

            def new_close_event(event):
                original_close_event(event)
                launcher.show()
            tb.closeEvent = new_close_event
        QtCore.QTimer.singleShot(300, close_app)

    def close_app():
        for w in app.topLevelWidgets():
            if isinstance(w, StandIn) and w.isVisible():
                w.close()
        QtCore.QTimer.singleShot(300, look)

    def look():
        state['loop_survived'] = True
        state['launcher_back'] = launcher.isVisible()
        app.exit(0)

    QtCore.QTimer.singleShot(0, open_app)
    app.exec_()
    ok = state['loop_survived'] and state['launcher_back']
    print(f"  {'ok  ' if ok else 'FAIL'} {name:30} main() returned "
          f"{state['returned']:9} launcher back: "
          f"{'yes' if state['launcher_back'] else 'NO '}  still running: "
          f"{'yes' if state['loop_survived'] else 'NO - the app quit it'}",
          flush=True)


def main():
    names = sys.argv[1:] or apps_with_main()
    failed = []
    for name in names:
        try:
            out = subprocess.run(
                [sys.executable, os.path.abspath(__file__), '--child', name],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                timeout=120).stdout
        except subprocess.TimeoutExpired:
            out = ''
        line = next((l for l in out.splitlines()
                     if l.startswith(('  ok', '  FAIL'))), None)
        if line is None:
            line = f"  FAIL {name:30} no result - its output ended:\n" + \
                   '\n'.join('       ' + l for l in out.splitlines()[-5:])
        print(line, flush=True)
        if not line.startswith('  ok'):
            failed.append(name)
    print(f"\n{len(names)} apps checked")
    if failed:
        print("closing does not bring the launcher back: " + ', '.join(failed))
        sys.exit(1)
    print("all checks passed")


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--child':
        child(sys.argv[2])
    else:
        main()
