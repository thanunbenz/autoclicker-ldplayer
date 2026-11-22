# Contributing

Thanks for your interest in improving LDPlayer Auto Clicker.

## Scope

This repository is a Windows engine that drives LDPlayer over ADB, plus a
pywebview Flow Editor. Keep changes focused on that scope.

Do not add game-specific templates, flows, or button names to `data/`. Users
supply their own screenshots and flows. `data/config/buttons.json` and
`data/config/flows/default.json` should stay generic.

## Before you start

- Open an issue for a large change or a new flow action so we can agree on the
  shape first.
- Keep each pull request to one topic.

## Setup

- Windows 10 or 11
- Python 3.14
- LDPlayer 9 or 14 with ADB debugging enabled

Install dependencies with either command:

```bash
python -m pip install -r requirements.txt
```

```bash
make install
```

The test suite is offline. You do not need LDPlayer or ADB to run it. LDPlayer
is only needed for manual checks of the editor or the device layer.

## Run tests

```bash
make test
```

Or:

```bash
python -m unittest discover -s tests -t . -p "test_*.py"
```

CI runs `python -m compileall -q bot editor tests` and the same test command on
Windows for every pull request.

## Project layout

```text
bot/      Engine: ADB, LDPlayer, vision, flow model and runner
editor/   Flow Editor, HTML page, fonts, calibrator, folder picker
data/     Runtime data: buttons, flows, templates
tests/    Offline unit tests
```

## Coding guidelines

- Keep `bot/` free of UI imports. `editor/` may import `bot/`, not the other
  way around.
- Use short English docstrings. Do not narrate code mechanics in comments.
- Do not add em-dash characters to any file.
- Every `adb` or `ldconsole` subprocess call must pass `timeout=`.
- Write settings with `config.write_json` so files are replaced atomically.
- Keep the Flow Editor offline. No CDN, no Google Fonts, no remote scripts.
- Do not commit secrets, keys, tokens, local settings, or captured logs.
- Add or update a test for behavior changes. Do not weaken an existing
  assertion to make a test pass.
- Keep tests offline. Use fake devices instead of a real emulator.

## Pull requests

1. Fork the repository and branch from `main`.
2. Make the change and run `make test`.
3. Fill in the pull request template.
4. Link the issue the change addresses.
5. Wait for CI and review.

Small, focused pull requests are reviewed faster than large mixed changes.

## Commit messages

Use a short imperative subject. English is preferred. Examples:

```text
fix: clamp remembered window size to the screen
feat: add wait_gone action to the flow runner
docs: explain how to calibrate the first button
```

## License

By contributing, you agree that your contribution is licensed under the MIT
License. See [LICENSE](LICENSE).
