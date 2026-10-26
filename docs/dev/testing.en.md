[Русский](testing.md) · **English**

# Checks

Checks are plain scripts in `tools/`: `python tools/test_<name>.py` or `node tools/test_<name>.mjs`,
exit code 0 means passed. The suites do not touch the network, real printers or the live data folder:
live data is replaced with temporary data, and the server is started in isolated mode
(`app/e2e_isolation.py`: its own folder, port and lock).

## What to run

```bash
python tools/validation/select_profile.py --working-tree
```

Based on the changed files and the risk map (`tools/validation/risk_map.json`), the selector prints a list of
suites. Run it **in full** — picking suites "by eye" has already missed red results.

Quick checks after any edit: syntax (`python -m py_compile`, `node --check`), bracket
balance in `web/app.css`, tags in `web/index.html`.

## Suite catalog

`tools/validation/test_catalog.json` is a derived file with suite hashes. If you changed a suite,
rebuild the catalog, otherwise the profile runner will refuse to run the checks:

```bash
python tools/validation/build_test_catalog.py --write
```

## Interface

`tools/_fm_ui_stage.py` is a test stand: the real `web/index.html`, `app.js`, `app.css` and Vue, with
mocked `/api` responses. Interface changes are checked at four window sizes (1600×1000,
1280×800, 1024×640, 853×533) and with no errors in the console.

## In the open repository

Some suites of the private repository are not included here: they compare against commits of the former private
history (proving that a change was intentional relative to a specific commit), check
the layout of the private repository, or use the real printer cover images. They remain in the private
development repository. Suites that need a module or file missing here print
`SKIP` with the reason.

`tools/test_camera_fmp4.py` parses a real stream from ffmpeg, and ffmpeg is not part of the repository.
Put `ffmpeg.exe` next to `server.py` or make `ffmpeg` available on `PATH`. Without it the suite
is intentionally red: parsing the stream has not been proven without real bytes.
