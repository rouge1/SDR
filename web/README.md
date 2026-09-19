# Web launcher

A browser front end for the app grid, the settings and the icons. It starts
the existing GNU Radio apps as separate processes; the flowgraph and its
configuration dialog are the ones that already exist, unchanged.

```sh
conda activate gnu
python web/server.py            # http://127.0.0.1:8730
```

`RFbenchToolkit.py` is untouched and still works. This is a second front
end onto the same `APP_TILES` table and the same
`config/window_settings.json`, not a replacement - run either, or both.

## Themes

The page and the desktop launcher share one theme, kept in
`config/window_settings.json`. The dot beside "Themes" in the header steps
through them; the page opens in the saved one, and follows a change made at
the desktop on its next refresh. Colours, faces, the tiles' shadows and the
pulse along each row's line all come from `apps/theme.py` through
`/theme.css`, so the two front ends cannot drift apart. See
[the themes](../devnotes/ui.md#the-themes-and-the-disc-that-picks-one).

## Where the window appears

On the display the *server* can reach, not in the browser. Start the server
from the desktop session that owns the screen, so it inherits `DISPLAY` and
`XAUTHORITY`; the page says so plainly when `DISPLAY` is missing rather than
launching apps into nothing.

That makes the useful shape **phone as the control surface, bench monitor as
the display**: pick and configure from anywhere, the flowgraph comes up on
the monitor. It is not remote operation.

## Off the machine

Loopback is open, because sitting at the machine is already the permission.
Anything wider has to be asked for and gets a token:

```sh
python web/server.py --host 0.0.0.0     # prints a URL with a token in it
```

Every tile here keys a transmitter, and the lowest power setting is still
32.5 dB out of the noise at the receiver. The token is the only thing in the
way, so treat the URL as the key it is.

## The pieces

| File | Does |
|------|------|
| `web/server.py` | Serves the page, its icons and fonts, and `/theme.css` - every theme's colours, faces and animation, generated from `apps/theme.py`. Reads and writes the settings file, the theme included, and starts and stops apps. Imports no GNU Radio, no Qt, no SoapySDR. |
| `web/index.html` | The page. Grid, settings, and what is running. |
| `apps/_run.py` | Runs one app module with its own Qt event loop - the piece the desktop launcher usually supplies. |
| `scripts/probe_radio.py` | Asks whether a radio is there, in a process that then exits. |
| `web/prototype/index.html` | A mockup of a browser *panel* for a running app, drawn from simulated AM. Nothing behind it - open it in any browser. It is the design reference for that step, not part of the launcher. |

## Two things that are the way they are on purpose

**The server never opens a radio.** Enumerating a HackRF leaves a USB handle
open in whoever asked, and the app launched next then fails with
`Device::make() no match`. The desktop launcher gets away with it because it
is the same process that goes on to build the flowgraph; a server that lives
for days would hold that handle for days. So every presence check runs in
`scripts/probe_radio.py` and dies with it.

**Single mode means something different here.** The desktop launcher hides
its window while an app runs and shows it again on close, which a browser
cannot do. The server holds the processes instead, so the page lists what is
running with a Stop button, and single mode is an enforced one-at-a-time
rather than an implicit one.

## What is not here yet

The per-app configuration dialogs are still Qt, and appear on the server's
display like the flowgraph does. Moving them into the browser needs no app
edits - `apps/_run.py` already takes `--config values.json` and skips the
dialog when given one.
