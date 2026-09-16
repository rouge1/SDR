#!/usr/bin/env python3
"""Run one app module on its own, owning the Qt event loop.

An app's ``main()`` ends with::

    if app.instance():
        return tb
    else:
        return app.exec_()

which is the launcher contract in CLAUDE.md - the launcher already owns a
QApplication and its loop, so ``main()`` hands back the top block rather
than blocking. The catch is that ``app.instance()`` is truthy the moment a
QApplication exists, so a module run directly takes that same branch: it
builds the flowgraph, shows the window, returns, and the window never gets
an event loop at all.

This is the piece the desktop launcher supplies, for whoever is not the
desktop launcher. It owns the QApplication, calls ``main()`` exactly as
``launch_application`` does, and runs the loop itself::

    python apps/_run.py amSineGenerator
    python apps/_run.py amSineGenerator --config /tmp/values.json

Without ``--config`` the flowgraph puts up the app's own ``ConfigDialog``,
so this is the same experience as clicking the tile in the desktop grid.
With one, the dialog is skipped and the values are used as they stand.

Run it with the ``gnu`` environment's Python - it imports GNU Radio
through the app module.
"""

import argparse
import ctypes
import importlib.util
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _init_x11_threads():
    """What each app's own ``__main__`` block does before Qt starts.

    Those blocks are guarded by ``__name__ == '__main__'``, so importing
    the module - which is what both launchers do - skips them. It has to
    happen before anything opens a display connection.
    """
    if not sys.platform.startswith('linux'):
        return
    try:
        ctypes.cdll.LoadLibrary('libX11.so').XInitThreads()
    except Exception:
        print("Warning: failed to XInitThreads()", file=sys.stderr)


def load_app(module_name):
    """Import apps/<module_name>.py the way the launcher imports it."""
    path = os.path.join(ROOT, 'apps', f"{module_name}.py")
    if not os.path.isfile(path):
        raise SystemExit(f"_run: no such app module: apps/{module_name}.py")
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    # Registered before exec so a module that imports itself by name - and
    # so that any gr.sync_block it defines can be found later - resolves.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    if not hasattr(module, 'main'):
        raise SystemExit(f"_run: apps/{module_name}.py has no main()")
    return module


def read_config(path):
    if not path:
        return None
    with open(path) as fh:
        values = json.load(fh)
    if not isinstance(values, dict):
        raise SystemExit("_run: --config must hold a JSON object")
    return values


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run one GNU Radio app module with its own Qt event loop.")
    parser.add_argument('module', help="module name under apps/, without .py")
    parser.add_argument('--config', metavar='FILE',
                        help="JSON config values; omit to show the app's own "
                             "configuration dialog")
    args = parser.parse_args(argv)

    # The apps open config/ and icons/ by relative path, exactly as
    # start_app.sh arranges for the desktop launcher.
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    os.chdir(ROOT)

    _init_x11_threads()

    from PyQt5 import Qt  # after XInitThreads, before any widget exists

    # argv[:1] so the app module never re-parses our arguments as Qt's.
    qapp = Qt.QApplication(sys.argv[:1])

    values = read_config(args.config)
    module = load_app(args.module)

    # Cancelling the dialog is sys.exit(0) inside the flowgraph, so this
    # returns only when there is something to run.
    tb = module.main(app=qapp, config_values=values)
    if tb is None:
        return 0
    return qapp.exec_()


if __name__ == '__main__':
    sys.exit(main())
