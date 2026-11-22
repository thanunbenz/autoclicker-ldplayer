# LDPlayer Auto Clicker

A small Windows auto-clicker engine for apps running on LDPlayer. It captures
the emulator screen over ADB, matches template images with OpenCV, and taps,
swipes, or types according to a JSON flow. A visual Flow Editor is included for
building and testing those flows.

Use this project only with apps and accounts you own or are authorized to
automate, and follow the terms of service of the apps you use.

## Features

- ADB screen capture, tap, swipe, text input, and app launch
- Multi-scale OpenCV template matching with per-resolution autofit
- JSON flow engine with tap, wait, sleep, swipe, text input, loops, watches,
  guards, and jumps
- Visual Flow Editor with live capture, match scores, run, stop, and failure
  screenshots
- Offline unit tests that never touch ADB, LDPlayer, or the network

## Requirements

- Windows 10 or 11
- Python 3.14 (tested); other 3.x versions may work
- LDPlayer 9 or 14 with ADB debugging enabled on each instance
- Python packages listed in `requirements.txt`

Install the dependencies with either command:

```bash
python -m pip install -r requirements.txt
```

```bash
make install
```

## Quick start

```bash
git clone <repository-url>
cd ldplayer-auto-clicker
```

Open the Flow Editor:

```bash
make flow
make flow INDEX=1
```

Or run it directly:

```bash
python editor/floweditor.py --index 0
```

On first launch, point the editor at the LDPlayer folder that contains
`ldconsole.exe` and `adb.exe`. Enable ADB debugging in each LDPlayer instance
(Settings > Others > ADB > Open local connection) and restart the instance.

Run the tests:

```bash
make test
```

## Project layout

```text
bot/                  Core engine
  config.py           Paths, settings, button and template metadata
  device.py           ADB wrapper for one emulator
  ldconsole.py        LDPlayer launch, quit, and instance listing
  vision.py           OpenCV template matching
  bot.py              Device, buttons, and autofit
  flow.py             Flow model and runner
  assets.py           Optional sealed asset loader
  vault.py            File sealing helpers
  version.py          Application name and version
data/
  config/
    buttons.json      Button names to template files and coordinates
    settings.json     Local settings, created at runtime
    flows/default.json  Starter flow, empty by default
    templates/        Template PNGs, created when you calibrate a button
editor/
  floweditor.py       pywebview bridge and editor window
  flow.html           Single-page UI with inline CSS and JavaScript
  font/               Noto Sans Thai
  calibrate_gui.py    Tkinter template cropper
  pick_folder.py      Folder picker subprocess
tests/                Offline unit tests
```

`data/config/settings.json`, `data/config/autofit.json`, and
`data/config/floweditor-ui.json` are local state and are ignored by git. A
fresh clone creates the settings it needs on first run.

`data/config/flows/default.json` and `data/config/buttons.json` start almost
empty. Use the Flow Editor to add steps, and use the calibrator to crop
templates and add buttons for the app you want to automate.

## How it works

1. `Device` talks to one LDPlayer instance over ADB.
2. `Bot` loads `data/config/buttons.json` and the template images.
3. On the first screenshot, the engine measures the screen scale once and
   caches it in `data/config/autofit.json`.
4. `FlowRunner` walks the steps in a flow. A `tap` step waits for its template,
   taps the matched point, and continues.
5. The Flow Editor exposes the same runner through a standard pywebview
   `js_api` bridge.

Coordinates and template images use the 1600x900 base resolution. Other
16:9 resolutions are scaled at runtime, so 1280x720 and 1920x1080 do not need
recalibration. Screens with a different aspect ratio still work, but matching
is slower because the engine has to search the full screen instead of a region.

## Flow format

A flow is a JSON file in `data/config/flows/`:

```json
{
  "name": "example",
  "description": "Open the app and wait",
  "group_defs": ["setup"],
  "jump": {"start": -1, "end": -1},
  "steps": [
    {"action": "tap", "target": "play_button", "group": "setup", "timeout": 8},
    {"action": "sleep", "seconds": 1}
  ]
}
```

Supported actions:

| Action | Purpose |
|---|---|
| `tap` | Wait for a template, then tap it |
| `wait_for` | Wait until a template appears |
| `wait_gone` | Wait until a template disappears |
| `sleep` | Wait for a number of seconds |
| `tap_xy` | Tap fixed base-resolution coordinates |
| `swipe` | Swipe from a template or a fixed point |
| `type_text` | Type ASCII text into an input field |
| `repeat_until` | Repeat a body until a template appears |
| `watch_until` | Watch the screen and tap any matched template until one appears |
| `watch_choice` | Watch and tap a selected subset of templates |
| `if_seen` | Run a body once if a template is visible |
| `guard` | Jump to another step when a template is not visible |
| `skip_if_seen` | Jump when a template is visible |
| `goto_step` | Jump unconditionally |

Every step also accepts `optional`, `enabled`, `after`, and `note`.

## Settings

`data/config/settings.json` is created by the editor. Main keys:

```json
{
  "ldplayer_dir": "C:\\LDPlayer\\LDPlayer14",
  "ldplayer_dirs": ["C:\\LDPlayer\\LDPlayer14"]
}
```

## Tests

```bash
make test
```

Or:

```bash
python -m unittest discover -s tests -t . -p "test_*.py"
```

All tests are offline. They use fake devices and never start LDPlayer or touch
ADB.

## Limitations

- Windows only. The engine shells out to `adb.exe` and `ldconsole.exe`.
- The Flow Editor interface is currently in Thai.
- This repository contains the engine and editor only. There is no license
  server, updater, or packaging pipeline.
- Template matching is not OCR. It can only find images that you have cropped
  and saved under `data/templates/`.

## Contributing

Issues and pull requests are welcome. Run `make test` before sending a change.

## Third-party notices

- Tailwind CSS preflight is included in `editor/flow.html` under the MIT
  License. The original notice is preserved in the page.
- Noto Sans Thai is included under the SIL Open Font License 1.1. See
  `editor/font/noto-sans-thai-OFL.txt`.
- OpenCV, NumPy, Pillow, and pywebview are runtime dependencies, each under
  its own license.

## License

MIT. See [LICENSE](LICENSE).
