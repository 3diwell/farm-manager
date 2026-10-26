[Русский](ui-executor-integration.md) · **English**

# Connecting UI verification to the executor

The UI step is closed only when **everything at once** is proven: the harness is qualified,
the qualification applies to the current environment, and every changed part of the interface is covered
by a registered scenario. A single settings scenario does not become proof
of the whole interface.

```bash
python tools/validation/run_profile.py --working-tree --execute --with-ui
```

---

## 1. Two different proofs

| | Qualification of the TOOL | Proof of the TASK |
|---|---|---|
| What it confirms | the verifier, driver, network guard and scenarios behave predictably | the specific changed candidate works |
| Where it comes from | the stage 3C series, ten cycles | new UI runs after every change |
| Inherited | yes, as long as the harness and environment have not changed | **never** |
| Lives in | [qualification.json](../../tools/validation/ui/qualification.json) | `logs/ui_runs/<run-id>/` of the specific task |

There is no need to repeat ten cycles after every product change. But declaring a task
verified on the basis of an old series is not allowed either: a change to `web/*` requires new runs.

## 2. The certificate and what kills it

`qualification.json` is issued **only** from the actually verified artifacts of a series:
status `QUALIFIED`, ten cycles, twenty runs, zero individual retries, an empty
list of unmet criteria. It is bound to the fingerprint of the source artifacts
(`source_artifact_digest`) and to the fingerprints of the harness itself.

The qualification is **invalidated** by a change to: `run_ui_verification.py`, `_ui_driver.mjs`,
`_stage_server.py`, `network_guard/sitecustomize.py`, `scenarios.json`,
`select_ui_coverage.py`, `ui_coverage_map.json`, as well as to the format of mandatory checks,
the process cleanup order and the network policy.

The qualification is **not invalidated** by a change to `server.py`, `app/`, `web/`, `modules/` — but such
a change requires a new run for the task.

### Environment policy

| What | Rule | Why |
|---|---|---|
| Windows build | must match | a different build means different process and port behavior |
| Python | `major.minor` must match | a minor version change changes standard library behavior |
| Node | the major version must match | the CDP bridge lives on its `fetch` and `WebSocket` |
| browser engine, major | must match → otherwise `STALE_ENVIRONMENT` | an Edge update has already broken automation: `--dump-dom` started printing nothing |
| browser engine, patch | does **not** kill the qualification, but issues a warning | a patch is usually harmless, but after that incident it must not go unmentioned |

Check: `python tools/validation/ui/verify_qualification.py`. Statuses: `VALID`,
`STALE_TOOLING`, `STALE_SCENARIOS`, `STALE_ENVIRONMENT`, `MISSING`, `INVALID`.

## 3. Coverage map

[ui_coverage_map.json](../../tools/validation/ui/ui_coverage_map.json) is a **separate**
source of truth, not mixed with the risk map. The risk map decides which profile is needed;
the coverage map decides which piece of the interface is actually verified.

One unit is registered: **`settings_panel_shell`** — the shell of the settings screen. It
requires **both** scenarios: `settings_panel_open_close` and `settings_panel_open_close_isolated`.

The allowed markers are taken from the real code: `openSettings`, `closeSettings`,
`showSettings`, `fm-settings-workspace`, `fm-set-title`, `fm-set-x`, `data-tour="settings"`,
`fm-boot-fallback`. Broad words like `settings`, `button` or `app` are not among them.

Explicitly **not covered**: the panel contents (`fm-set-nav`, tabs, groups, controls,
module installation), closing by clicking the backdrop, window geometry and sticky navigation, the shared
overlay manager, the top bar, navigation between screens, global CSS tokens, any
backend changes.

## 4. Coverage is computed from the diff, not from the path

[select_ui_coverage.py](../../tools/validation/ui/select_ui_coverage.py) parses the real
unified diff and decides for each changed hunk separately. A hunk is covered if:

1. the file belongs to the paths of a coverage unit, **and**
2. the hunk contains no forbidden marker (neither in the changed lines nor in the context), **and**
3. **every** changed line contains an allowed marker — **or** the hunk sits inside the
   settings shell (an anchor in the context) and does not add a new interactive element.

The third rule is the reason why a CSS change inside `.fm-settings-workspace`
is covered, while adding a new button with `@click` inside the same section is not: the scenario does not
click it.

Rules: every hunk must be covered; one covered hunk does not hide an uncovered neighbor;
a rename is analyzed by both paths; deleting UI code also requires coverage;
anything unknown always stays uncovered.

Statuses: `COVERED`, `PARTIALLY_COVERED`, `UNCOVERED`, `NO_UI_CHANGES`, `UNKNOWN`,
`INVALID_DIFF`.

## 5. Why the path is not enough

`--files web/app.css` does not say **what** changed in the file. A single `web/app.js` contains
the settings, the print queue and the overlay manager. That is why the mode without a diff gives
`ui_coverage_status = UNKNOWN`, no scenarios are issued, the UI is not run, and the requirement
stays open — the result is no higher than `PARTIAL`.

## 6. Behavior of `--with-ui`

| Condition | What happens | UI status |
|---|---|---|
| change without UI | nothing | `UI_NOT_REQUIRED` |
| without `--with-ui` | the UI is not run, the requirement remains | `UI_NOT_REQUESTED` |
| qualification is not `VALID` | the UI is not run, overall `BLOCKED` | `UI_QUALIFICATION_STALE` |
| coverage `UNKNOWN` | the UI is not run | `UI_COVERAGE_UNKNOWN` |
| coverage `UNCOVERED` | the UI is not run, the hunks are listed | `UI_UNCOVERED` |
| partial coverage | the UI is not run | `UI_PARTIALLY_COVERED` |
| everything is proven | both scenarios in sequence, static → isolated | `UI_PASS` / `UI_FAIL` |

**Scenarios are chosen by the coverage map, not by the user and not by the agent.** The executor has no
`--ui-scenario` argument and no way to pass a URL. There are no retries: the first red scenario
stops the second.

`UI_PASS` closes **only** the `ui_required` flag. It does not replace SUBSYSTEM, RELEASE,
HARDWARE, the build, mutation proof or hardware verification. With the RELEASE or HARDWARE profile
the executor still returns `BLOCKED`, and `--with-ui` is not a bypass.

## 7. Artifacts

`logs/validation_runs/<run-id>/` receives `ui_qualification.json`, `ui_coverage.json`,
`ui_execution_plan.json`, `ui_results.json` and relative links to
`logs/ui_runs/<ui-run-id>/`. Screenshots are **not copied**. The absolute path of the owner's working
folder is not saved.

`summary.json` is extended with the fields `ui_requested`, `ui_qualification_status`,
`ui_coverage_status`, `ui_coverage_units`, `ui_required_scenarios`, `ui_executed_scenarios`,
`ui_passed_scenarios`, `ui_failed_scenarios`, `ui_uncovered_hunks`, `ui_status`,
`ui_artifact_paths`.

## 8. Maintenance smoke run

`--ui-maintenance-smoke --execute` proves only the "executor → verifier" wiring.
It accepts no paths, scenarios or URLs, requires a `VALID` qualification, runs the
qualified pair and returns `UI_INTEGRATION_SMOKE_PASS` or
`UI_INTEGRATION_SMOKE_FAIL`. **It never becomes the overall `PASS` of a task** — the result
stays `PARTIAL`.

## 9. Limits

What is covered is **the shell of one screen**. Not covered: the settings contents, the other screens,
printing, the queue, printers, files, inventory, modules, responsiveness, zoom and the language matrix.
The static scenario proves nothing about the backend — the isolated one does that.
The isolated instance is always fresh, so behavior on the owner's data is not verified.

The qualification is bound to the machine and the environment: a different PC or a major Edge update requires
a new series ([ui-stability.md](ui-stability.en.md)).

Related: [ui-verification.md](ui-verification.en.md) · [ui-stability.md](ui-stability.en.md) ·
[profile-execution.md](profile-execution.en.md) · [profile-selection.md](profile-selection.en.md)
