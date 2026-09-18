# The desktop launcher, its dialogs and its windows

One of the notes in `devnotes/`. What applies everywhere, and which
file covers what, is in [CLAUDE.md](../CLAUDE.md).

## The launcher grid, and tiles that flip

Every tile is declared in `APP_TILES` at the top of `RFbenchToolkit.py`
as `(row, column, [face, ...])`, where a face is
`(label, module, icon, direction)` and direction is `'tx'` or `'rx'`.
A tile with more than one face is a **flip tile**: a badge in its corner
turns it over, and the icon and the caption both change with it. That is
how the two ends of one standard share a square - the ATSC, NTSC and
FM + RDS transmitters and their receivers - instead of sitting apart as
though they were unrelated apps. All three video standards
now have both ends on one tile, FM video included.

**The grid follows the radio.** `RADIO_DIRECTIONS` says which way each of
the four can go, and `apply_radio_directions()` runs on startup and again
every time Settings closes:

| Radio | What the grid does |
|-------|--------------------|
| HackRF One, Ettus USRP | both directions - the two pairs stay flippable |
| Signal Hound VSG60 | every tile turns to transmit; badges disappear |
| Signal Hound BB60D | every tile turns to receive; the ten transmit-only tiles dim out |

- **A dimmed tile says why.** Its tooltip names the direction it needs and
  the radio that cannot do it ("AM Sine Generator needs a radio that can
  transmit. The Signal Hound BB60D cannot."). A greyed square that explains
  itself beats an app that opens and then fails on a device it was never
  going to be able to use. `launch_application` still checks, as a
  backstop, but reads the direction off `APP_TILES` rather than keeping a
  second list in step with it.
- **A turn the radio forces is not remembered.** `tile_faces` records what
  the *user* chose with the badge; capability turns pass `remember=False`.
  So flip ATSC to receive on a HackRF, switch to the VSG and watch it turn
  to transmit, switch back - and it returns to receive. Saving the forced
  turn instead would quietly destroy the preference every time the radio
  changed.
- **Dimming is painted, not an effect.** The caption already carries a
  `QGraphicsOpacityEffect` for the fade, and effects do not nest
  predictably, so `_draw` sets the painter's opacity instead.

- **The turn is drawn, not faked with a swap.** `FlipTile` animates a
  `flip_phase` property from 0 to 1 and squeezes the icon horizontally by
  `cos` of it, through zero width and back out, changing face at the moment
  it is edge on - which is exactly when none of it is visible. The caption
  fades on the same curve rather than being squeezed, because squeezed text
  reads as a rendering fault.
- **The property is `flip_phase`, not `flip`.** `flip()` is the method that
  starts a turn; naming the `pyqtProperty` the same thing replaces the
  method with the property object and the badge stops working.
- **Every face is cropped to the same 4:3 box**, so two icons with
  different aspect ratios cannot clip one another or shove the caption
  around mid-turn. The caption is given the height of the longest name on
  the grid, for the same reason: otherwise one long name makes its own
  tile taller than the rest of its row.
- **Which side is up lives in `window_settings.json`** under `tile_faces`,
  keyed by the tile's first module name, so a tile left showing the
  receiver is still showing it next time.
- **The single-face path is the same code.** `create_app_button` is kept as
  a one-face call into `create_tile`, so nothing else had to change.

## Where the windows come back

Three windows remember where they were left, and all three keep it the same
way: plain `x`, `y`, `width`, `height` in JSON, applied size-first, and only
when the saved position would land somewhere still reachable
(`geometry_is_reachable` in `apps/utils.py`, which looks across every
screen rather than just the primary one).

**The launcher and every flowgraph window also remember being
maximized**, as `"maximized": true` beside the other four - which then hold
the *normal* geometry (`normal_geometry` in `apps/utils.py`, from Qt's
`normalGeometry()`), so un-maximizing after a restart gives back the size
the window had. Saved as `pos()` and `size()` while maximized, as the
launcher once did, they held the whole screen instead. A config saved
before the flag existed has no `maximized` and comes back normal. Three
things about it:

- **On GNOME a window cannot be maximized before it is on screen.** Set on
  the hidden window, the state never reaches the window manager: Qt reports
  the window maximized, GNOME maps it at its normal size, and a moment later
  Qt agrees with GNOME. Qt's own `showMaximized()` fails the same way,
  measured. So `load_window_position` places the launcher at its normal
  geometry and `showEvent` asks for maximized once it is up - which costs a
  glimpse of the normal-sized window first. The same path serves single
  mode, where the launcher is hidden while an app runs and shown again.
- **"Once it is up" means exposed, not shown** - `when_exposed` in
  `apps/utils.py`. `show()` only asks for a window, and GNOME puts it up,
  title bar and all, a little later. A flowgraph window is restored after
  `main()` has shown it, and done straight away that went wrong twice.
  Until the frame is on, Qt does not know how thick it is, so `move()` put
  the *inside* of the window where the frame's corner was meant to go:
  37 px higher every time it was opened. And a maximize asked for before
  the window is mapped goes out as a property GNOME reads only at map
  time, so it was lost on one run and kept on the next. Both the flowgraph
  restore and the launcher's maximize now wait for Qt to report the window
  exposed (3 s at most, for a window that never is). Verified through the
  window manager on GNOME, three runs of each: a flowgraph window
  maximized by the WM's own `_NET_WM_STATE` request, saved, reopened
  maximized, un-maximized to exactly 1000x700 at (200, 150), and reopened
  there, with no drift.
- **On Windows a flowgraph window came back maximized, but not by this
  code; the launcher's own has not been tried.** Nothing started over SSH
  can show it: the laptop runs those in session 0, where Windows reports
  no window as visible, and Qt only asks Windows to maximize a window it
  believes is visible - so nothing there can be maximized from inside,
  whatever the code does. It was checked by hand on the laptop's own
  desktop instead, on 2026-09-18: a flowgraph window left maximized came
  back maximized. It was found later the same day that the dialog's OK
  had been deleting the saved position before the window could read it
  (see [what the window's own controls were left
  at](#what-the-windows-own-controls-were-left-at)), so what brought it
  back was the app's own `QSettings` `restoreGeometry`, which works there
  because that screen never changes size. Through the launcher, on
  Windows, the JSON path has not been looked at since the fix. The
  launcher's own window sends the same request - the `ShowWindow` a click on the
  maximize button makes - but nobody has looked. On GNOME both are
  verified through the window manager rather than through Qt: the
  launcher maximized, closed, reopened maximized, restored to exactly the
  geometry it had, and through single mode's hide and show, with no
  drift. The flowgraph window's check there called the save and restore
  directly, which is why it did not catch the dialog.

| Window | Where it is kept |
|--------|------------------|
| The launcher | `window_position` in `config/window_settings.json` |
| An app's config dialog | `dialog_position` in `config/<module>_config.json` |
| An app's flowgraph window | `flowgraph_position`, in that same per-app file, with `maximized` |

**The flowgraph's was the one that did not work, and it looked like it was
never being saved.** Every app already calls Qt's own
`saveGeometry`/`restoreGeometry` against `QSettings("GNU Radio", <app>)`,
and the *saving* half works - the stored blobs hold real geometries, 1782
x1161 at (215, 258) and so on. Two things stopped them coming back:

- **Qt 5 refuses to restore at all when the screen has changed size.**
  `restoreGeometry` compares the screen width the blob was saved on against
  the current one and returns false, restoring nothing, if they differ by
  more than a quarter. The blobs here were written on screens 2880 and 3840
  wide - a laptop with an external monitor does that every time it is
  plugged in - so 3840/2880 = 1.33 tripped it.
- **It runs before the window exists.** Each app calls it at the top of its
  `__init__`, which is the GRC-generated idiom, and then builds every
  control, box and plot afterwards. The layout can overrule the restored
  size once the widgets are in.

So the geometry is applied *after* `main()` has shown the window - and
after the window manager has put it up, see above - by whichever launcher
started it: `RFbenchToolkit.py` for the desktop grid, `apps/_run.py` for
the browser. It is saved from the close-event wrapper the launcher already
installs, read before the app's own `closeEvent` stops the flowgraph. Each
app keeps its `QSettings` calls, which is what an app run directly still
uses. `scripts/test_flowgraph_windows.py` checks the round trip, maximized
and not, into a throwaway folder - and that a dialog's OK leaves the saved
position alone, which for the first day it did not.

The saved size is clamped to the current screen but the position is not:
a window deliberately parked against an edge, or on a second monitor,
should come back there.

**Where each of them goes the first time, before anything is saved:**

- The launcher **works out its own size** (`natural_size`): wide enough
  for the widest bank's five tiles in one row at `PREFERRED_TILE`, 185 px,
  and exactly tall enough for every bank - which on this machine is
  **997x826**, centred on the primary screen at (941, 397) on a 2880x1620
  display. The width is arithmetic; the height is *measured*, by laying
  the grid out at that width and asking the column how tall it came out,
  because it depends on how tall the machine sets a line of text. A size
  written down by hand, 1000x820, fitted here by 2 px and would have
  scrolled on any machine whose fonts run a pixel taller; measured, it is
  right wherever it runs - make the type a pixel taller and it picks 835,
  four pixels and the captions wrap and it picks 928, with nothing to
  scroll and 2 px less scrolling every time. It is then clamped to the
  screen's *available* geometry, so a 1366x768 laptop, which cannot show
  all three banks, gets as much as fits and a scroll bar rather than a
  window partly under the panel. Before any of this there was no default
  at all: with no `window_position` it fell back to its 800x600
  *minimum*, which wrapped the first bank onto two rows on a screen with
  room to spare.
- A config dialog opens **in the middle of the launcher**, which is where
  the eye already is, having just clicked a tile. It used to be the
  launcher's top-left corner plus fifty pixels, which on a wide window put
  it well off to one side of what was clicked. `centre_on` in
  `apps/utils.py` does it, and has to `adjustSize()` first: the dialog has
  not been shown yet, so its size must be asked for rather than read.
  It clamps into the screen the launcher is on, because a launcher parked
  against an edge would otherwise centre part of the dialog off it -
  measured, a launcher at (2600, 1300) on a 2880x1620 screen wants a
  centre of (3099, 1739) and the dialog is pulled back to (2497, 1111).
- The settings dialog needs none of this: it is built with `parent=self`,
  so Qt centres it on the launcher already. The config dialogs cannot be,
  because each app's `ConfigDialog()` takes no parent - which is why Qt
  would otherwise drop them in the middle of the *screen*, nowhere near
  the launcher on a wide desktop.

### What the window's own controls were left at

**The power and the centre frequency set in a flowgraph window are kept
too** - gain, on a receiver - so the dialog opens next time on what the
window was left at. Before, a change made in the window lasted only as
long as the window: the dialog opened on its own last value, and pressing
OK put that back on the air. They go into the same per-app file, under the
keys the dialog already reads:

| Apps | Power key | Frequency key | Window attributes |
|------|-----------|---------------|-------------------|
| The other eleven transmitters | `power_level` | `center_freq` | `rfPwr`, and `cf` or `centerFreq` - and on FM video, `deviation_mhz` from `deviation_mhz` too |
| FM + RDS Transmitter | `power_percent` | `frequency_mhz` | `power_percent`, `freq_mhz` |
| RDS Receiver | `gain_percent` | `frequency_mhz` | `gain_percent`, `freq_mhz` |
| The three video receivers | `gain_percent` | `center_mhz` | `gain_percent`, `center_mhz` |

Each flowgraph class names what it keeps in `SAVED_SETTINGS`, from that
key to the attribute its setter keeps current, and `save_flowgraph_settings`
in `apps/utils.py` writes them from the same close hook as the geometry, in
both launchers. **Only what was changed in the window is written**: each
launcher takes `flowgraph_settings` as the window opens and passes it as
`since`, so a control nobody touched is left as the dialog saved it - and
two windows of one app open at once, in multi mode, cannot put back each
other's unchanged values. To keep another control, add it to that dict.
The dialog must read the key and the setter must update the attribute, or
it saves the value the window started with.

**A saved value has to fit the dialog control that reads it back**, and
for frequency most of them did not:

- **A window's counter takes two more decimals than its step.** GNU
  Radio's `Range` sets its counter's precision that way, and a typed value
  is not snapped to the step. So a window stepping in 0.01 MHz takes
  433.9234, one stepping in 0.1 takes 533.012, and the NTSC transmitter's,
  stepping in 0.001, takes 10 Hz. `FrequencyChooser` held 0.1 MHz; it now
  holds `FREQ_DECIMALS`, five, and its box shows only the digits a value
  needs - 533.0, 433.92 - so the television dialogs look as they did.
- **Seven dialogs chose frequency with a whole-MHz `QSlider`** - ASK, FSK,
  PSK, AM Sine, AM Audio, FM Audio and PPM-OOK - while their windows tune
  in 0.01. They use `FrequencyChooser` now, as the ATSC, NTSC and FM video
  dialogs already did. That is a looks change the user chose on
  2026-09-18, over rounding what the window saved to what the slider
  could show.
- **`QSlider.setValue` raises on a float, and `load_config`'s bare
  `except` then drops every setting after it** - power included, since it
  is loaded after frequency. The subcarrier dialog kept its whole-MHz
  slider, because its window steps in whole megahertz, but it loads the
  frequency through `int(round(...))` all the same.

**Everything that writes an app's file merges into it**, through
`update_app_config` in `apps/utils.py`. Three things share each file and
none of them owns it: the dialog writes its settings, the launcher the
dialog's position, the window its geometry and its controls. Every
dialog's `save_config` used to write the whole file from its own dict, so
OK deleted `flowgraph_position` a moment before the window came up to
read it. This was found on 2026-09-18 while adding the power saving: the
JSON restore described above had never once run through either launcher.
A dialog's `load_config` defaults whatever the file lacks, so a key left
over from an older version does no harm.

`scripts/test_flowgraph_windows.py` sets each window's own controls to a
new value in their finest digit - 301.0007 on a 0.01 window - and saves
them the way the launchers do. Only what it changed may be in the file,
a fresh dialog must open on exactly those values, and its OK must keep
the window's position. It was also driven through
`RFbenchToolkit.launch_application` and `apps/_run.py` themselves, in a
copy of the repo with its own `config/`. That covered a whole-MHz dialog
turned `FrequencyChooser`, the two RDS apps, a video receiver and three
video transmitters. Each opened on the power and frequency its window
closed at, two opens running, and a window closed untouched left another
save of the frequency alone.

## How every dialog gets laid out

Each of the fifteen `ConfigDialog`s is assembled by hand out of
`QVBoxLayout` and `QHBoxLayout`, and they were all crooked in the same
ways - which is why `apply_dark_theme` now ends by calling `tidy_dialog`
rather than fifteen dialogs each being fixed on their own. Four faults, all
of them visible in a screenshot, all measured across all fifteen:

- **The label in a row sat four or five pixels below the control beside
  it.** The stylesheet gave every `QLabel` a `margin-top: 10px`, to space a
  caption off whatever was above it. Inside a row that margin pushes the
  *text* down within the label's own rectangle while the spin box or slider
  beside it stays centred, so the box reads as sitting high - which is
  exactly how it was reported ("the 177 box is higher than the text next to
  it"). The margin is gone; vertical space comes from layout spacing, which
  is what layout spacing is for, and a caption gets its extra room above
  through `setContentsMargins` on the caption alone.
- **The controls started at a different x in every row**, because each one
  began wherever its label's text happened to end - four different
  positions in one dialog. Every label that leads a row is given the width
  of the widest of them. It has to be `QSizePolicy.Fixed` as well as a
  minimum width: a label is `Preferred` by default, so in a row with a spin
  box - which is `Expanding` - the two share the slack and that row's
  control still starts 26 px right of every other.
- **A nested row was indented.** Sub-layouts and the plain `QWidget`
  containers that exist only to carry a `QGraphicsOpacityEffect` keep their
  own default 9 px margins, so "Sine Frequency" sat ten pixels right of
  every other label in the same dialog.
- **Short dialogs spread their contents out.** A forced 400 px minimum
  height left the receiver dialogs half empty, and a `QVBoxLayout` hands
  the slack to whatever can grow - which is the labels, so the gaps came
  out uneven. There is no minimum height now, and a stretch before the
  button box collects any slack in one place.

Two things about doing it centrally:

- **A group box is entered for its nested layouts but not for its rows.**
  Its contents are indented from the dialog's column by the frame, so
  pulling its rows into that column would push them back out of the box.
  The RDS box in the FM + RDS transmitter is the one that has both.
- **Anything a stylesheet touches stops drawing its own sub-controls.**
  Styling `QAbstractSpinBox` so it matches the combo boxes - and without
  that it falls through to the plain `QWidget` rule and comes out as a flat
  dark box - leaves the up and down buttons as empty rectangles. Qt's CSS
  subset will not draw a triangle out of borders either; it renders the
  four borders as a rectangle. So they are images - `icons/spin-up.png`,
  `icons/spin-down.png`, which the combo boxes use for their own arrow
  too, and `icons/check.png` for a ticked box - referenced through
  `icon_url()` by absolute path: a stylesheet resolves `url()` against the
  process's working directory, and forward slashes are required on Windows
  because a backslash is an escape to the stylesheet parser.

```sh
python scripts/test_dialog_layout.py                  # all 15, all 4 radios
python scripts/test_dialog_layout.py --radio vsg
python scripts/test_dialog_layout.py --save /tmp/shots
```

opens every dialog on Qt's offscreen platform - no radio, no display - and
measures the four things above, plus that no combo box lists the same entry
twice and that nothing is bigger than the 1366x768 laptop. Sixty dialogs in
about twenty seconds. It patches `read_settings` rather than the settings
file, because a test must never write into the user's own configuration.

## Testing the launcher end to end

The `scripts/test_*.py` in these notes all bypass the GUI. `scripts/test_launcher_gui.py`
covers what they cannot - that `linux/start_app.sh` starts, that a button press
reaches `launch_application`, that the dialog accepts, that the flowgraph
window appears, and that closing it brings the launcher back - by driving real
X input through xdotool (`apt install xdotool`):

```sh
python scripts/test_launcher_gui.py "FM + RDS Receiver"
python scripts/test_launcher_gui.py "FM + RDS Transmitter" --hold 30
python scripts/test_launcher_gui.py "ATSC Video Receiver"
```

`scripts/test_app_close.py` checks the last of those for every app at once,
with no radio, no display and no launcher to close first. It calls each
app's real `main()` the way `launch_application` does, with a stand-in
window for the flowgraph, closes the window, and requires the launcher to be
visible again with its event loop still running. The ATSC transmitter failed
it (see [its notes](atsc.md#atsc-transmitter)); nothing else did.

- **Close any running launcher first.** A launcher process keeps a USB handle
  on the HackRF - `/proc/<pid>/fd` shows `/dev/bus/usb/...` - even while it is
  only *sitting on a config dialog*. `SoapySDR.Device.enumerate` then returns
  zero devices and the app under test fails with `Device::make() no match`,
  which surfaces as a modal error box that nothing dismisses, so an automated
  run just hangs. The script refuses to start if it finds one.
- **Button coordinates are found, not computed.** High-DPI scaling moves the
  grid, so `button_grid()` locates the icons as bright blobs in a screenshot
  and `registered_apps()` reads the launcher's own `APP_TILES` table. A
  button that moves takes the click with it.
- **That table is parsed with `ast`, not a regex and not an import.** A flip
  tile's faces are a nested list, which is the shape a regex reads wrongly;
  and importing the launcher opens a window, when the whole point is to
  drive the one `linux/start_app.sh` starts. `RADIO_DIRECTIONS` comes out the
  same way, so the test knows which apps the selected radio can run and
  says so up front rather than failing later like a broken button.
- **A blob's position in its row is not its grid column.** Row 2 ends at
  column 3 now that the RDS receiver has moved onto the transmitter's tile,
  and screenshot blobs come back packed left to right knowing nothing about
  gaps. `registered_apps()` works out each tile's position among the tiles
  its row actually has.
- **An app on the back of a flip tile is reached through the saved
  setting**, not by clicking the badge: `tile_showing()` writes the same
  `tile_faces` entry the badge writes, so the launcher comes up already
  showing the app under test, and puts it back afterwards. Clicking the
  badge would test the animation rather than the app, and would mean
  finding a 32-pixel circle in a screenshot. Only that one key is restored,
  because the launcher saves its window position into the same file while
  the test runs.
- Screenshots are grabbed with Qt rather than scrot/import/maim, none of which
  are guaranteed present, while PyQt5 is already a hard dependency.
- `Return` activates the dialog's default button, which is OK - cheaper than
  hunting for its pixels. Window close buttons sit at `(X + WIDTH - 33,
  Y + 30)` from the frame geometry xdotool reports, *not* at its corner.

## One design, two front ends

The desktop launcher and the browser page are meant to look like one
program, and for a while they did not: the page was drawn to a design and
the launcher kept the grey stylesheet it had always had. So the palette,
the type scale and the faces live in **`apps/theme.py`** and both sides
read them - `apply_launcher_theme` and `apply_dark_theme` take Qt style
sheets from it, and `web/server.py` generates `/theme.css` from the same
`TOKENS` and the page links that instead of declaring its own `:root`.
Edit a colour there and both front ends move.

`apps/theme.py` **imports nothing but the standard library at module
level**, which is what lets the server import it: everything else in
`apps/` pulls GNU Radio or Qt, and a web server must have neither. It is
the one import the server makes from `apps/`; the tile tables it still
reads out of the launcher's *source* with `ast`, as before.

```sh
python scripts/test_theme.py    # no radio, no display, no GNU Radio
```

checks that every `var()` the page uses is a name `/theme.css` defines,
that the page asks nothing of the network, that neither Qt stylesheet has
an unsubstituted token, that the six faces and their licence are in
`fonts/`, and that every row of tiles has a heading. That is the check
that stops the two drifting, which is the whole point of the arrangement.

**A Qt stylesheet is not CSS, and four of the things the page does have no
QSS equivalent at all.** They are done to the pixels instead, in
`RFbenchToolkit.py`:

| The page says | Qt has no such thing, so |
|---|---|
| `--ground` and the rest of `:root` | Python formats the tokens into the sheet, the way `icon_url()` already got absolute paths into a `url()` |
| `object-fit: cover` with `filter: saturate(.82)` | `cover_pixmap()` crops each icon to 4:3 about its middle and pulls the colour back, once, with PIL and numpy |
| `letter-spacing` on the TRANSMIT/RECEIVE line | `token_font()`, because only a QFont has it |
| `.bank-name::after`, the hairline running off the heading | a `QFrame` in the row - Qt's `::` are sub-controls of a known widget, not pseudo-elements anyone can invent |

A fifth, `opacity` on a tile the radio cannot run, was already solved: the
picture is dimmed by the painter in `_draw` and the caption by the
stylesheet's own `:disabled` colours, because the two caption labels carry
an opacity effect each for the flip and effects do not nest predictably.

**The grid wraps now**, which is the page's
`repeat(auto-fill, minmax(150px, 1fr))` done by hand in `_relayout` -
a stylesheet does no layout at all. Tiles are at least 150 px wide, as
many to a row as fit, inside a column capped at 1080 and centred in the
window, as the page's `max-width: 1080px; margin: 0 auto` does for both
the rail's contents and the body (`centred_column`). Without the centring
a maximised launcher kept its tiles in the leftmost 1080 px while the
rail and the bank hairlines ran on across the whole screen.

**It never makes more columns than the widest bank has tiles**, which is
five. A sixth column could only ever be empty, and it arrived right at
the default width: 980 px of window gave five tiles of 181, 1000 gave six
of 153 - three pixels off the minimum, the sixth slot holding nothing in
any bank. Capped, a wider window widens the five instead, until the
column reaches 1080 and they stop at 208. Measured: four columns below
about 840 px of window, five from there to a full 1920, and at the
launcher's own size five of 185 with nothing to scroll. The cap is read off
`APP_TILES` rather than written down as 5, so a bank that gains a sixth
tile gets a sixth column. Two more things worth knowing:

- **Watch the scroll area's viewport, not the window.** The viewport
  changes width without the window being resized - the scroll bar
  appearing is enough - so a `resizeEvent` on the window alone left the
  grid laid out for whatever width it had before it was first shown: six
  columns of room, three columns of tiles, measured. It is an event filter
  on `viewport()` instead.
- **`scripts/test_launcher_gui.py` finds tiles as bright blobs**, and a
  wrapped bank puts one row of tiles on two rows of blobs, after which
  every click lands on the wrong tile. It compares the blob rows against
  `APP_TILES` now and says the window is too narrow, rather than failing
  several steps later like a broken button. The size window it accepts
  also had to come down: a picture is 4:3 rather than a 200 px square, and
  as short as 111 px at the width where a fifth column has only just
  fitted.

Two smaller traps, both found by looking at a screenshot:

- **A child widget paints its own background over its parent's border.**
  The rail's `border-bottom` came out interrupted under the wordmark, and
  would have vanished under the centred column its contents now sit in,
  so everything inside `#rail` is transparent.
- **A QFont sizes in points and a stylesheet in pixels.** A font built the
  obvious way from a token meant for QSS comes out about a third too big
  on a 96 dpi screen; `token_font()` calls `setPixelSize`.
- **A layout does not know a stylesheet drew a border.** The tile's layout
  began at the button's edge, so its picture sat on the 1 px border at the
  top and left and left a strip of panel before the one on the right. The
  layout is inset by 1 px all round.

Three more, all found making the launcher measure its own height before
it is shown - each one made it come out at its 600 px minimum:

- **A QPushButton ignores the layout it holds.** It sizes itself from its
  own text and icon, and a tile has neither, so its size hint was a small
  empty button. On screen that never showed, because showing a window
  activates each layout and pushes the real size on as a minimum - too
  late to measure from. `FlipTile.sizeHint` returns its layout's.
- **Qt invalidates a layout by posting an event.** Before the event loop
  has run, the outer widget answers from its cache: 143x196 for a page
  really 997x766. `natural_size` asks the column's own layout.
- **A stylesheet's type sizes arrive when a widget is polished**, which is
  otherwise on first show; `ensurePolished()` first, or every label is
  measured in the default font.

The launcher also gained a **header rail** - wordmark, the radio Settings
has chosen, and the gear - and a **scroll area**, which it badly needed:
the old grid had none, so on a 768-high laptop the video row sat below the
bottom edge with no way to reach it. The gear is the page's own SVG of
three faders, rendered through QtSvg, which retired twenty lines of PIL
that brightened a photograph of a cog and keyed its background out.

The one part of the browser page deliberately **not** carried across is the
ON AIR panel. That is not paint, it is a running-apps list the desktop
launcher has never kept - and in single mode it hides itself while an app
runs, so there would be nothing to show it to.

### The flowgraph windows wear it too

The windows an app opens once OK is pressed were the last thing still in
Qt's light grey, with GNU Radio's white plots and black and blue traces.
They now take the page's panel view (`web/prototype/index.html`): the
window on the ground, each group of controls or readout a panel card,
each plot a well with a rule round it, the first trace in `trace` and the
second (Imag) in `ink_3`, as the prototype draws I and Q. Every control and
every plot is the app's own - it is paint only, `theme.flowgraph_qss()`,
which shares its buttons, inputs, sliders and ticks with the dialogs'
(`_CONTROLS_QSS`), so a dialog and the window it opens read as one app.

Each app's `__init__` calls **`apply_flowgraph_theme(self)`** first thing,
where GRC put `qtgui.util.check_set_qss()` (which applied a GNU Radio
theme from the user's GNU Radio preferences, and is gone). First thing
matters, twice:

- **The plots' axis titles keep the application font they were built
  with.** GNU Radio sets their size as a font of their own, copied from the
  application's at that moment, and nothing in PyQt can reach a Qwt title
  afterwards. Themed after the plots were built, the titles stayed in Noto
  Sans with Barlow all round them. So the application font becomes Barlow
  before any plot exists.
- **A stylesheet's properties go on when a widget is polished**, which is
  when it is shown - after the app's own `set_line_color` calls. That is
  how the traces are recoloured without touching any app's colour lists:
  the plots expose `line_color1`-`9`, `palette_color` (the canvas),
  `zoomer_color` and the frequency plot's markers as Qt properties, and
  the sheet sets them.

Three things worth knowing before changing it:

- **No `font-family` or `font-size` on `QWidget` or `QLabel`**, unlike the
  dialog's sheet. A stylesheet font beats `setFont()`, and the receivers
  set fonts that mean something: the RadioText and the program list in
  monospace, so a gap or a stray character shows where it is, and the lock
  status large. The face comes from the application font instead, which a
  widget's own `setFont()` still overrides.
- **`qproperty-marker_peak_amplitude_color` segfaults GNU Radio 3.10.12's
  frequency plot**, with no Python frame at all - found by bisecting the
  sheet one property at a time on a lone `freq_sink_c`. Every other
  property it sets is safe on every plot kind the apps use.
- **The receivers' status colours are tokens now** - `good`, `warn` and
  `bad`, added to `TOKENS` and to `/theme.css`. The old green and red were
  picked for Qt's light grey and read 3.2:1 and 3.0:1 on the new panel;
  the tokens read 8.5, 8.2 and 5.6:1 there - and 1.6-2.4:1 on the old
  grey, so the colours and the panel only work together.

```sh
python scripts/test_flowgraph_windows.py                 # all 16, twice, ~80 s
python scripts/test_flowgraph_windows.py --save /tmp/shots
```

builds every app's real window the way `launch_application` does, with a
stand-in radio (a throttle into nothing for a transmitter, noise and a tone
for a receiver) and no sound card, so it needs no radio and runs beside a
launcher. It renders the whole scroll content, fold and all, and checks
that the window carries the sheet, that little outside the plots is near
white, that the well shows on every canvas, that each trace in use has
3:1 against it, that every label has 4.5:1 against what is behind it, and
that the axes are in Barlow. Run with the theme switched off, every one
of the sixteen fails, on 6 to 13 counts each, so a passing run means
something. No
window is ever closed, because an app's `closeEvent` writes into the
user's own `QSettings`.

It then builds all sixteen again with **no media folder**, which is how a
machine starts before Settings has been opened, and only requires each
to build and run. The dialog greys out OK there, but `apps/_run.py
--config` goes straight to `main()`, and the FM Subcarrier Generator
handed no file died on `None` where the other audio apps play silence.
The first pass caught that only because it ran on a new machine; the
second pass fails on it on any machine.

**The stylesheet made the sliders follow the mouse, and the fix lives
beside it.** A Qt stylesheet with hover rules turns on mouse tracking, so
a slider hears every movement of the pointer across it, button or not:
off with no stylesheet, on with this one, measured. GNU Radio's
`RangeWidget` slider has its own `mouseMoveEvent`, which jumps to wherever
the pointer is without asking whether a button is down. So once the
windows were themed, passing the mouse over a power slider set the
power, from 50 % to 89 % on the way across, on every window with one:
AM Sine, ASK, FSK and PSK, the NTSC, ATSC and FM video transmitters,
and the rest. The user found it on 2026-09-18. The scroll wheel did the same by
another route: most windows scroll on the laptop, and a scroll that
passed over a slider, spin box or combo box moved that instead, and a
spin box took focus from the wheel alone.

`ClickToMove` in `apps/utils.py`, which `apply_flowgraph_theme` installs,
takes on every slider, spin box and combo box when the window is first
shown:

- a mouse move with no button down is dropped;
- a wheel turn over one that has not been clicked is passed on to the
  scroll area;
- the wheel no longer gives focus.

Clicking gives focus, and dragging, typing and the wheel then work as
before. The scroll bars are left out: scrolling is what the wheel is
for. `test_flowgraph_windows.py` sends every control a buttonless move
and a wheel turn each way, requires it to stay put, and requires a press
and drag to still move a slider. With the guard switched off it fails
on all of them, the power slider included. It sends the events to the
controls directly. On a real display, and a real scroll reaching the
scroll area, it has not been tried.

## The typefaces

`fonts/` holds Barlow and Barlow Semi Condensed as six static TTFs, beside
the SIL OFL they are licensed under. They are *vendored* rather than
installed, for the same reason `vendor/libvsg_api.so.1` is: Google Fonts is
only where Barlow happens to ship.

- **There is no apt package.** `fonts-barlow` is not in the Ubuntu archive
  at all, and an apt install would only ever fix one of the three machines
  anyway - the Windows laptop has no apt, and TVAdemo has no git and is kept
  in step by copying files. A system font install is a per-machine step that
  nothing checks, and a missing face does not raise: the app renders in
  something else, which is the kind of wrongness only ever found by looking
  at the screen.
- **The browser front end serves them itself**, from a `/fonts/` route in
  `web/server.py` with the same containment check as the icons, so the page
  needs no network. It used to link `fonts.googleapis.com`, which on a bench
  with no connection falls back to Helvetica without a word - and the two
  front ends then stop matching for a reason nobody would guess.
  `web/prototype/index.html` refers to them relatively, since that mockup is
  opened as a file rather than served. Nothing else in the tree reaches the
  network at run time: the two URLs left in `windows/bootstrap.ps1`
  are for installing Windows from scratch.
- **Qt loads them with `QFontDatabase.addApplicationFont`**, so the desktop
  side needs no system install either and both platforms render the same.
- **Qt clamps to the heaviest face shipped rather than synthesising one.**
  Asking for weight 700 in Barlow measures exactly what 600 does, because
  SemiBold is the heaviest of the three cut here; a synthesiser would have
  smeared it wider. So asking for a weight the set does not carry is not an
  error and does not look like one - it is silently the nearest that is
  there.
- **The whole directory travels together.** The OFL requires the licence
  alongside the fonts wherever they are passed on, which is the same rule
  `media/VIDEO-CREDITS.txt` follows for the CC BY clips: copying `fonts/` to
  TVAdemo means copying `OFL.txt` with it.
