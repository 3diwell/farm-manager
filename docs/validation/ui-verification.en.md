[Русский](ui-verification.md) · **English**

# Interface verification in an isolated environment

The verifier opens the real interface in a headless browser, runs one declarative
scenario and answers a question that reading the source cannot settle: **was it
actually rendered, and does the state change in response to user actions.**

```bash
python tools/validation/ui/run_ui_verification.py --scenario settings_panel_open_close
```

```bash
python tools/validation/ui/run_ui_verification.py --scenario settings_panel_open_close --execute
```

---

## 1. Two application modes

| Mode | What is started | What this proves |
|---|---|---|
| **static_harness** | a local static server serves the **real** `web/index.html`, `app.js`, `app.css` and the vendored Vue; `/api` responses are synthetic | the frontend really mounts and reacts; server logic is **not** verified |
| **isolated_farm_manager** | the real `server.py` in a separate data folder via the standard `--fm-packaged-e2e` flag | the whole application |

The mode is written to `summary.json` verbatim and **is not embellished**. The `coverage_scope` of the two
modes differs, and a static run is never passed off as a backend check.

### The official isolation contract

`isolated_farm_manager` starts the real `server.py` **only** through the product's standard
mechanism — `app/e2e_isolation.py`. The verifier invents not a single new flag and not a single new
variable.

| Parameter | Value for the verifier | What it disables |
|---|---|---|
| `--fm-packaged-e2e` | mandatory argument | without it `FM_E2E_*` are ignored entirely |
| `FM_E2E_SENTINEL` | a one-time token, also in `.fm-e2e-marker` | proves that the folder was prepared by this very launch |
| `FM_E2E_DATA_DIR` | `logs/ui_runs/<run-id>/test_data` | the owner's working folder is not used |
| `FM_E2E_CONFIG_PATH` | `<data_dir>/config.json` | the owner's settings are neither read nor written |
| `FM_E2E_MUTEX_NAME` | `Local\3DIWELL_FM_UI_<run-id>` | the test does not compete with the running program |
| `FM_E2E_PORT` | a random free loopback port | the owner's usual port is not occupied |
| `FM_E2E_DISABLE_TRAY` | `1` | the system tray |
| `FM_E2E_DISABLE_BROWSER` | `1` | automatic opening of the owner's browser |
| `FM_E2E_DISABLE_DISCOVERY` | `1` | printer discovery on the network |
| `FM_E2E_DISABLE_PRINTERS` | `1` | printer polling |
| `FM_E2E_DISABLE_MODULES` | `1` | module loading |

The contract is **fail-closed**: the product refuses to start (`E2E isolation rejected: <code>`,
exit 3) if the token is shorter than 16 characters, the folder does not exist, contains a link/junction, coincides
with the working folder or lies inside it, the marker does not match, the mutex is the working one or the config is outside the folder.
Separately there is `tools/test_packaged_restart_end_to_end.py`, which checks this same contract.

Dispatch and transport are not controlled by official variables: they are proven by their default
values `False` and by the test config not containing `project_print_enabled`.
The product has no read-only endpoint for the state of the safety switches — the method of proof is stated
verbatim in `backend_assertions.json`.

**Update check.** The accepted isolation contract itself forbids external requests:
`Isolation.disable_update_check` is a property of the accepted isolation, not an environment variable,
so it cannot be enabled other than by passing the whole official contract. The
`/api/update-check` handler asks the contract object for the decision and returns a response of the same shape
as when the website is unreachable. **A normal launch does not change at all**: the manifest address, timeout,
cache, response parsing and the banner in the interface are the same, and no separate update switch
has appeared for the user. The network guard remains independent proof: it has no exception for
the update domain, and must not have one.

## 2. Isolation

Every launch gets its own directory `logs/ui_runs/<run-id>/` (the `logs/` directory is ignored by
Git) with the structure `test_data/`, `browser_profile/`, `artifacts/`, `process_logs/`.

Before the browser and server start, everything listed below is proven; **any unmet condition
blocks the launch** rather than lowering the requirements:

- the test data folder and the browser profile lie **inside** the run directory;
- the run directory lies inside the ignored `logs/`;
- the test data folder is created empty — it is **not copied** from the working one;
- the owner's working folder is neither a parent nor a descendant of the test folder
  (its path does not get into the artifacts — only a SHA-256 fingerprint is saved);
- the port is chosen on `127.0.0.1` and is free;
- `DISPATCH_ENABLED` and `TRANSPORT_ENABLED` are confirmed as `False`;
- the scenario contains no addresses of real devices and no credentials;
- the browser engine is found in a **controlled list** of installed paths.

The owner's working folder is read only to compare paths; its contents and database are
never opened.

## 3. Network policy

Only `127.0.0.1`, `localhost`, the launch's own random port, and also
`data:`, `about:` and `blob:` are allowed. Everything else is a **FAIL**, not a line in the log.

**Browser.** It is started with `--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1`,
so a foreign name physically cannot be resolved. In parallel, a log is kept: Resource Timing
covers everything the page loaded from the very beginning, and wrappers around `fetch`, `XMLHttpRequest`,
`WebSocket` and `EventSource` cover the action phase. The full result is in `network_attempts.json`.

**Backend.** The browser log says nothing about the Python process itself. That is why in the isolated
mode the guard `tools/validation/ui/network_guard/sitecustomize.py` is attached: Python itself
imports it at startup, and the directory is supplied **only** to this subprocess via
`PYTHONPATH`. The guard replaces `connect`, `connect_ex` and `sendto` and lets through only
loopback; everything else is blocked **before** execution. Name resolution is not blocked but
is logged — the connection will not happen anyway.

The guard's safety catch: without the variables `FM_UI_GUARD_LOG` and `FM_UI_GUARD_SENTINEL` it does
nothing, so it cannot be slipped into the working program to replace its network. The global Python
is not modified. The log records only the time, PID, host, port, decision and reason —
not a single byte of transmitted data.

**A missing guard attestation blocks the launch**: without proof that it loaded,
backend isolation cannot be proven.

## 4. Processes and cleanup

All processes are started without a visible window, `stdout`/`stderr` go to separate files,
sequentially, with a hard timeout, and the PID is recorded in `process_manifest.json`.

Cleanup order: browser session → own browser → own local server →
check that the port is released → check that none of its own processes remain.

**Processes are not looked up by name.** `taskkill` is called only as `/PID <pid> /T /F`;
`/IM` is not used anywhere. The owner's browser and python cannot be affected: only
PIDs recorded by this launch are killed. The owner's browser profile is not used — the profile is always
created inside the run directory.

If the server exits before becoming ready, this is a **FAIL**, and exit code `0` does not count as
success: this is exactly what a program looks like that crashed on a named mutex without running
a single check.

## 5. Statuses and exit codes

| Status | Meaning | Code |
|---|---|---|
| **PASS** | all mandatory DOM checks passed, the console is clean, no outbound requests | 0 |
| **DRY_RUN** | the plan is shown, **nothing is started** | 0 |
| **FAIL** | a red check, a console error, an external request or an abnormal exit | 2 |
| **BLOCKED** | isolation not proven, or the mode is not executed at this stage | 3 |
| **TIMEOUT** | the scenario did not fit into its budget | 4 |
| **CONFIG_ERROR** | the scenario was not found, the registry is damaged or forbidden by its contents | 5 |

## 6. Scenario format

A scenario is **data**, not a program. In
[scenarios.json](../../tools/validation/ui/scenarios.json) arbitrary Python,
arbitrary JavaScript, shell commands, external URLs and printer addresses are forbidden; the loader rejects
such a scenario. The user selects a scenario **only by `id`** — passing one's own URL, one's own
command or one's own browser path is impossible.

Allowed actions: `wait_for_selector`, `click`, `fill`, `press`, `set_viewport`,
`screenshot`, `read_text`, `assert_visible`, `assert_hidden`, `assert_text`,
`assert_attribute`. A selector reaches the page only via `JSON.stringify`.

Besides the list of actions, a scenario declares `assertions` — mandatory checks with
identifiers. The verifier confirms that **each** of them was actually executed and is
green. This is double-entry bookkeeping: a silently skipped check will not turn into a green result.

## 7. Why a screenshot proves nothing

A page can render a loading placeholder, show an empty container or freeze on
a previous frame — in a screenshot this looks plausible. That is why screenshots **do not affect the verdict**:
without passed mandatory DOM checks the result cannot be `PASS`, and a separate check
pins down that screenshots alone give `FAIL`.

Screenshots are evidence for a human, not an argument for automation. The pilot takes three:
before the action, after the panel opens and after it closes; the first and the third match byte for byte —
that is exactly what a restored state looks like.

## 8. Artifacts

`logs/ui_runs/<run-id>/`: `summary.json`, `summary.txt`, `scenario.json`, `console.json`,
`network_attempts.json`, `dom_assertions.json`, `environment.json`, `process_manifest.json`,
`artifacts/*.png`, `process_logs/*.stdout.txt` and `*.stderr.txt`.

Artifacts are created **only** with `--execute`. Secrets cannot get into them: child
processes receive only an allowlist of environment variables, and the working data path
is saved as a fingerprint, not as text.

## 8a. Readiness, backend and file system (isolated mode)

**Readiness.** An open port does not count as readiness. Ten conditions are confirmed:
the process is alive; the official `/version` response has been received; the response came from this launch's port;
the isolation contract has been accepted by the product; the network guard attestation is present; the test data folder
was actually used; the working folder was not used; dispatch and transport are effectively
disabled; the output contains no `E2E isolation rejected` and no tracebacks; all of this happened within the time limit.
The evidence is `readiness.json`. **An early server exit with any code, including 0, is a FAIL**,
and the browser is not started after that.

**Backend checks.** They are performed **before** the browser starts and only against existing read-only
endpoints: `/version` (response and version), `/api/printers` (empty), `/api/send-jobs` (no
queue and no reservations), `/api/modules` (a response from the local port). Nothing is created,
deleted or changed. Where no read-only endpoint exists (isolation mode,
state of the safety switches), the method of proof is named directly: the files created in the test folder
and the absence of `project_print_enabled` in the test config.

**File system.** After the scenario the following is checked: the test folder was created; the config path is inside
the run directory; all databases found lie inside the test folder and by size correspond to
a fresh installation, not a copy of the working one; all runtime files are inside the run directory; the fingerprint
of the owner's working folder **matched before and after**; the repository's product files have not changed.
The fingerprint is taken from names, sizes and times — contents are not read, the absolute path
does not get into the artifacts.

## 9. Pilot limits and what stage 3B needs

The `settings_panel_open_close` pilot checks the rendering of the root screen, the availability of a real
interactive element, the opening of the settings panel, its contents and the restoration of the initial
state. This is **one screen**, not the whole interface.

Stage 3B added a second scenario — `settings_panel_open_close_isolated`, the same in meaning but
on the real `server.py`. Comparing the two runs is the whole point of the pair: a discrepancy shows
where the static stand lies.

Known limitations:

- **one screen is verified** — this is not a verification of the product, printing or hardware;
- in `static_harness` the `/api` responses are synthetic, so a static run **is not**
  proof that the backend works; the `test_data/` directory is created there but stays empty;
- the isolated instance is a fresh installation: an empty database, no printers, no projects.
  Behavior on the owner's data is not verified and will not be;
- there are no layout, zoom or responsiveness checks;
- the verifier is **not connected** to [run_profile.py](profile-execution.en.md): the `ui_required` flag
  still gives `PARTIAL`. Making UI verification a mandatory step is possible only after
  it has accumulated stability statistics — otherwise a fragile browser step will start turning
  harmless changes red.

**What the first real run found and how it ended.** The isolated instance, with
the tray, browser, discovery, printers and modules disabled, still tried to
open an outgoing HTTPS connection to the website for the update manifest; the guard blocked it,
and the launch honestly got `FAIL`. The defect was closed by a separate task: the accepted isolation now itself
forbids the update check. The confirming run is `PASS`: 0 blocked attempts,
backend outgoing connections only to loopback, the site name was not even resolved.

The suppression is confirmed in **two independent ways**, not only by the guard
letting nothing through: the `/api/update-check` response (`ok=false`, with no new connection attempts) and
the line `E2E isolation: update check disabled` in the output of the accepted contract.

Stage 3C will need: a stability criterion before connecting the UI step to the executor,
and several scenarios instead of one.

The stability of these scenarios is measured separately — [ui-stability.md](ui-stability.en.md):
ten consecutive cycles without a single retry. `QUALIFIED` refers to a series,
`PASS` — to a single run. How these scenarios are connected to the executor and why
a file path does not count as coverage — [ui-executor-integration.md](ui-executor-integration.en.md).

Related: [profile-execution.md](profile-execution.en.md) ·
[profile-selection.md](profile-selection.en.md) · [frontend.md](frontend.en.md)
