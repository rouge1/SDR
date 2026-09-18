# The web launcher

One of the notes in `devnotes/`. What applies everywhere, and which
file covers what, is in [CLAUDE.md](../CLAUDE.md).

## Web launcher (a second front end)

`web/server.py` serves the grid, the settings and the icons to a browser and
starts each app as its own process. The flowgraph and its configuration
dialog are the ones that already exist, unchanged: this is a second front end
onto the same `APP_TILES` table and the same `window_settings.json`, not a
replacement, and `RFbenchToolkit.py` is untouched. Run either, or both.

```sh
conda activate gnu
python web/server.py                 # http://127.0.0.1:8730
python web/server.py --host 0.0.0.0  # prints a URL with a token in it
```

| File | Does |
|------|------|
| `web/server.py` | Serves the page, its icons and its fonts, reads and writes the settings file, starts and stops apps. Imports no GNU Radio, no Qt, no SoapySDR. |
| `web/index.html` | The page: grid, settings, and what is running. |
| `apps/theme.py` | The palette, the type scale and the faces, for both front ends. Stdlib only, which is why the server may import it. |
| `apps/_run.py` | Runs one app module with its own Qt event loop. |
| `scripts/probe_radio.py` | Asks whether a radio is there, in a process that then exits. |
| `web/prototype/index.html` | A mockup of a browser *panel* for a running app, drawn from simulated AM. Nothing behind it - it is the design reference for that step, not part of the launcher. |

The window opens on the display the **server** can reach, not in the browser,
so start the server from the desktop session that owns the screen and it
inherits `DISPLAY` and `XAUTHORITY`. That makes the useful shape phone as the
control surface, bench monitor as the display - it is not remote operation.
The page says so plainly when `DISPLAY` is missing rather than launching apps
into nothing. On Windows this is the session-0 problem already described
under [Running on Windows](machines.md#running-on-windows).

Things worth knowing before changing it:

- **The server must never open a radio.** `launch_application` enumerates the
  HackRF before launching, and the process that asks keeps a USB handle
  afterwards - which is why a launcher sitting on a config dialog already
  makes the app that follows fail with `Device::make() no match`. The desktop
  launcher gets away with it because it is the same process that goes on to
  build the flowgraph. A server that lives for days would hold that handle
  for days and break every launch after the first. So every presence check -
  HackRF, BB60D, VSG - runs in `scripts/probe_radio.py`, a process that exits
  and takes its handles with it. Its refusals repeat the desktop launcher's
  wording so both front ends say the same thing.
- **`apps/_run.py` exists because a module cannot run itself.** Each app's
  `main()` ends `if app.instance(): return tb else: return app.exec_()`,
  which is the [launcher contract](../CLAUDE.md#app-module-contract) - the launcher already owns a
  QApplication and its loop. But `app.instance()` is truthy the moment a
  QApplication exists, so a module run directly takes that same branch: it
  builds the flowgraph, shows the window, returns, and the window never gets
  an event loop. `_run.py` is the piece the desktop launcher usually
  supplies. It also does the `XInitThreads()` each app's own `__main__` block
  does, since importing a module skips that block.
- **Single mode means something different here.** The desktop launcher hides
  its window while an app runs and shows it again on close, which a browser
  cannot do. The server holds the processes instead, so the page lists what
  is running with a Stop button - something the desktop launcher cannot do -
  and single mode is an enforced one-at-a-time rather than an implicit one.
  Stop is `terminate`, and **that is not yet enough to stop an app started
  through `apps/_run.py`.** Every app installs a `SIGTERM` handler in its
  `main()`, and run under `_run.py` on TVAdemo the FM video transmitter
  ignored both `SIGTERM` and `SIGINT`: five minutes after the first one it
  was still on the air on 419% of a core across 53 threads, its main thread
  parked in Qt's poll, and only `SIGKILL` ended it - on two separate runs.
  **It is not that app.** The NTSC transmitter, launched the same way for
  the receiver's off-air re-test, did exactly the same thing: still on the
  air six seconds after `SIGTERM`, 479% of a core across 61 threads, gone
  on `SIGKILL`. So whatever swallows the signal is in the shared path -
  `_run.py`, the app contract's `main()`, or Qt - and not in one
  flowgraph.
  It is *not* the obvious cause: each `main()` starts a 500 ms timer so the
  interpreter gets control to run the handler, and then returns, dropping
  the only reference to it - but a stripped-down reproduction with the timer
  collected still took `SIGTERM` immediately, so something else is
  swallowing it. Until this is found, the browser's Stop button should be
  assumed not to stop an app, and anything launched through `_run.py` by
  hand needs its PID. A killed transmitter leaves `config/.vsg60.lock`
  behind, and that is only harmless because the lock is keyed by a PID and a
  dead one is treated as stale.
- **Loopback is open, wider is not.** Sitting at the machine is already the
  permission, so `127.0.0.1` needs no token. `--host` anything else mints one
  and puts it in the printed URL. Every tile keys a transmitter and 0 % power
  is not off, so treat that URL as the key it is.
- **The grid is `APP_TILES`, read with `ast`.** The server never imports the
  launcher - that would open a window and pull in PyQt5. It reads the table
  out of the source the same way `scripts/test_launcher_gui.py` does and for
  the same reason, so keep `APP_TILES` a plain literal and all three keep
  working.
- **Settings are merged, not replaced.** `window_position`, `dialog_position`
  and the tile-face state the desktop app keeps in the same file all survive
  being edited from a browser. Which side a tile is showing is per-viewer
  here, in `localStorage`, rather than fought over in the shared file.

Exercised so far: the tile table parsing, the settings round trip and its
merge, every launch refusal (wrong direction, single mode, unknown module,
radio absent), spawn, the running list, reaping, Stop, and the token. All of
it against a stubbed interpreter, because it was written on a machine without
the `gnu` environment. **Not yet exercised: the assumption the whole design
rests on**, that the probe subprocess releases the USB handle in time for
the app that follows - neither machine here has a HackRF, which is the radio
that trap belongs to.

`apps/_run.py` itself has now run a real app against a real radio: it
started the FM video transmitter on TVAdemo's VSG60 from a `--config` file,
headless, and transmitted correctly - see the Stop note above for the one
thing that did not work. `scripts/test_app_close.py` used to fail on
`_run.py`, which lives in `apps/` and has a `main()` of its own; it skips
names beginning with an underscore now, since a leading underscore there
means a helper rather than an app.

The per-app configuration dialogs are still Qt, and appear on the server's
display like the flowgraph does. Moving them into the browser needs no app
edits: `apps/_run.py` already takes `--config values.json` and skips the
dialog when given one. What it needs is a parameter manifest per app, which
would also retire the duplication where a range is stated once in
`ConfigDialog` and again in the flowgraph's `RangeWidget`.
