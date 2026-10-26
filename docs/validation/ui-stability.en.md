[Русский](ui-stability.md) · **English**

# Stability qualification of UI verification

A single green run says nothing about whether the check can be relied on. A fragile
browser step connected to automation will start turning harmless changes red — and trust
in the checks will die faster than they bring any benefit. Qualification measures exactly this.

```bash
python tools/validation/ui/run_ui_stability.py
```

```bash
python tools/validation/ui/run_ui_stability.py --execute
```

---

## 1. What exactly is qualified

Two scenarios from [scenarios.json](../../tools/validation/ui/scenarios.json):

| Scenario | Mode | What it proves |
|---|---|---|
| `settings_panel_open_close` | `static_harness` | the real frontend on top of a synthetic backend |
| `settings_panel_open_close_isolated` | `isolated_farm_manager` | the real `server.py` in an isolated folder |

**10 cycles, each with both scenarios — 20 real runs**, strictly sequential.
The order within a cycle alternates: odd cycles run static first, even cycles run isolated first.
This way a cleanup problem is visible in both directions, not just one.

The qualifier **does not duplicate** UI verification: it calls
[run_ui_verification.py](../../tools/validation/ui/run_ui_verification.py) as a subprocess and
parses its artifacts. It has no interpretation of the interface of its own — otherwise it would be measuring
itself.

## 2. The continuous series rule

Only **ten consecutive** green cycles count as qualification. Any red sign —
FAIL, BLOCKED, CONFIG_ERROR, TIMEOUT, a console error or warning, an external request,
a blocked attempt, a leftover process, an occupied port, a change to the working folder or
product files, a mismatch in mandatory checks — **immediately breaks the series**.

Forbidden: retrying only the failed run, excluding it from the statistics, continuing the count
from the previous value, calling the result flaky and counting the series as green. The counter starts
from zero. "Almost qualified" does not exist.

If it is proven that the cause is a defect in the qualifier itself: save the report of the failed series,
fix **only** the qualifier, run its tests, take a new fingerprint of the candidate and
start the series again from the first cycle. **No more than one full restart.** If the cause
is in the product, the verifier, the browser, the network or cannot be explained — the result is `NOT_QUALIFIED`, and nothing
is fixed within the qualification.

## 3. Freezing the candidate

Before the series, the SHA-256 of eleven files is taken: `server.py`, `app/e2e_isolation.py`,
`web/index.html`, `web/app.js`, `web/app.css` and the whole contents of `tools/validation/ui/`.
Plus the commit, `APP_VERSION`, the versions of Python, Node and the engine, the OS and the start time. After the series
the fingerprint is taken again: if even one file has changed, the series is invalid. Otherwise it is unknown
the stability **of what** was measured.

## 4. Criteria

Twenty-two criteria; `QUALIFIED` only when all of them hold at once. Key ones: 10/10 static and 10/10
isolated PASS · zero retries · zero timeouts · zero console errors and warnings ·
zero external requests from the browser and the backend · zero blocked attempts · zero leftover
processes · all 20 ports released · all browser profiles unique · all test data
folders unique · the owner's working folder and product files unchanged · the candidate
fingerprint matched · the DOM and backend check sets unchanged · isolated faster than 60 s, static
faster than 30 s · **every duration within a ±30 % corridor around the median of its mode**.

On the corridor separately: if only the first, cold run violates it, it **must not**
be excluded. The result is `NOT_QUALIFIED`, the cold-start hypothesis is noted in the report, and the decision
to relax the criterion is made by the owner, not by the tool.

## 5. Byte-for-byte screenshot equality — static only

The static stand serves synthetic `/api`, the picture is deterministic, so it
is required that `01_before.png` and `03_restored.png` match **byte for byte**.

This cannot be required of the isolated mode: the page lives between screenshots — the
WebSocket ticks, the background redraws — and byte equality would prove not the restoration
of state but the absence of life. There, restoration is proven by the DOM check
`assert_hidden section.fm-settings-workspace`, not by pixels. Both modes are required
to produce a screenshot of the open panel that differs from the initial one.

The first series of stage 3C broke off exactly on this: the qualifier applied the static rule
to isolated. That was its own defect; it has been fixed, and the rule is pinned by a test.

## 6. Statistics

Computed with the standard library, without third-party packages: count, pass/fail, min, max,
mean, median, p90 and p95 by the nearest-rank method, sample standard deviation,
coefficient of variation and the ratio of maximum to median — separately for each mode.

## 7. Artifacts

`logs/ui_stability/<series-id>/`: `series_summary.json` and `.txt`,
`candidate_fingerprint_before.json` and `_after.json`, `runs.jsonl`, `metrics_static.json`,
`metrics_isolated.json`, `failures.json`, `process_audit.json`, `port_audit.json`,
`network_audit.json`, `data_isolation_audit.json`, `qualification_decision.json`.

Screenshots are **not copied**: relative links to the original `logs/ui_runs/<run-id>/` are stored.
The absolute path of the owner's working folder does not get into the report — only its fingerprint.

## 8. QUALIFIED is not PASS and not a permission

`PASS` refers to one run. `QUALIFIED` refers to a **series** and means exactly one thing:
two verified checks behave predictably on this machine, on this candidate, right now.

What `QUALIFIED` does **not** mean: that printing, hardware, other screens or
behavior on the owner's data have been verified (the isolated instance is always fresh); that the static stand
proved anything about the backend; or that the UI step closes by itself. Qualification is only one
of the conditions: connecting to the executor also requires diff-proven coverage of every
changed hunk — see
[ui-executor-integration.md](ui-executor-integration.en.md).

Related: [ui-verification.md](ui-verification.en.md) · [profile-execution.md](profile-execution.en.md)
