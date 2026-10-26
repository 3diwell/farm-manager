[Русский](profile-selection.md) · **English**

# Choosing a validation profile by risk

The tool answers one question: **how much validation is enough for this change.**
It executes nothing — it only classifies the changes and prints a plan.

```bash
python tools/validation/select_profile.py --working-tree
```

---

## 1. What it does and what it does not do

| Does | Does not |
|---|---|
| Determines risk R0–R4 and the profile | Does not run a single check |
| Explains the reason for every file | Does not write files, does not touch config or the database |
| Prints the command plan | Does not build EXEs, does not start a browser |
| Asks Git for the file list (with an explicit flag) | Does not connect to printers or the network |

**A dry run is not a completed check.** Every plan step carries `executes: false`.
Commands are run by a person. There is no executor in the system yet — that is a separate stage.

## 2. Risk and profile

| Risk | What it is | Minimum profile |
|---|---|---|
| **R0** | Documentation, logs, assistant configuration | FAST |
| **R1** | Styles, assets, test harness, utility tools | TARGETED |
| **R2** | Frontend logic and template, routes and permissions, modules | SUBSYSTEM |
| **R3** | Server runtime, shared code, printer adapters, build | RELEASE |
| **R4** | Printing, queue, backup, data migrations | RELEASE |

| Profile | Contents |
|---|---|
| **FAST** | Syntax of the changed file; balance checks for `web/app.css` and `web/index.html` |
| **TARGETED** | FAST + tests directly related to the changed area |
| **SUBSYSTEM** | TARGETED + tests of the whole affected subsystem |
| **RELEASE** | `python tools/release_gate.py` in full, **with no relaxations**; if the build is affected — EXE and packaged proof |
| **HARDWARE** | RELEASE + confirmation on a real printer. **Never passed automatically** |

The `ui_required` / `build_required` / `hardware_required` flags are not a profile but additional
obligations: the interface is checked by eye or on the test stand, the build requires an EXE, hardware
requires the owner at the farm.

## 3. The main rule: maximum, not first match

One file can match several rules, and a change usually contains several files.
Matches are **combined**:

- risk — the **maximum** of the matches;
- profile — the **strictest** of the matches and no weaker than the minimum for the resulting risk;
- the `ui/build/hardware` flags — **logical OR**.

A change to `web/app.css` (R1) together with `app/printer_job_lifecycle.py` (R4) gives **R4 / RELEASE**
and still keeps `ui_required = true`. The "first match wins" principle does not apply here
and would be a hole: it would allow a critical file to hide behind a harmless one.

## 4. What happens to an unknown file

An unfamiliar path **never yields a green fast profile**.

| Situation | Result |
|---|---|
| The path is not described in the map | R3 / RELEASE + an "add a rule" warning |
| The path is not described **and lies in a critical area** | `blocked = true`, exit code 3 |
| The path is outside the repository or contains `..` | `blocked = true` |

The critical area is listed in `fallback.critical_area_globs`: print launching and print files,
the orchestrator, backup, migrations, klipper. Blocking means that
automatic selection is forbidden and the owner makes the decision.

If the map names a test that does not exist on disk, it is **excluded from the plan**, a
warning is issued and the profile is **raised**. Test names are never invented.

## 5. Invocation modes

```bash
python tools/validation/select_profile.py --files web/app.css app/utils.py
python tools/validation/select_profile.py --files-from changed.txt
python tools/validation/select_profile.py --working-tree --json
python tools/validation/select_profile.py --staged
python tools/validation/select_profile.py --base 287b2ea
```

The modes are mutually exclusive. `--working-tree`, `--staged` and `--base` are the only cases
in which a subprocess is started, and only `git`. A backslash is equivalent to a forward slash,
duplicates are collapsed.

Exit codes: **0** — plan built · **2** — input or map error · **3** — `blocked`.

## 6. Examples

```
web/app.css                              -> R1 / TARGETED, ui=true
web/app.js                               -> R2 / SUBSYSTEM, ui=true
app/printer_job_lifecycle.py             -> R4 / RELEASE
app/project_orchestrator.py              -> R4 / HARDWARE, hw=true
3diwell-setup.iss                        -> R3 / RELEASE, build=true
app/some_unmapped_widget.py              -> R3 / RELEASE + warning
app/print_supervisor_unmapped.py         -> blocked, rc=3
```

JSON fields: `risk`, `profile`, `ui_required`, `build_required`, `hardware_required`,
`changed_files`, `matched_rules`, `unmatched_files`, `components`, `targeted_tests`,
`subsystem_tests`, `reasons`, `warnings`, `blocked`, `blocked_reason`, `plan`.

## 7. How to change the map

The map is `tools/validation/risk_map.json`, the single source of truth.

- Risk **must not be lowered** for the sake of speed; any doubt is resolved toward strictness.
- A test added to a rule **must exist** — otherwise check 29 turns red.
- A rule with risk R3/R4 cannot assign a profile weaker than RELEASE — check 30.
- `self_test: true` means that the changed file is itself a test and goes into the plan.
- After editing the map: `python tools/test_select_profile.py`.

## 8. Limits

The selector is **an advisor, not an authority**. It does not override the rules of
CLAUDE.md §3 and does not relax the full release gate. The RELEASE profile
always means the same unchangeable command `python tools/release_gate.py`.

The safe part of the selected profile can be executed by the executor —
[profile-execution.md](profile-execution.en.md). It never runs RELEASE or HARDWARE,
and a dry run does not count as a check. For interface changes the selector
additionally reports diff-based coverage and the qualification status of the UI harness —
[ui-executor-integration.md](ui-executor-integration.en.md).

Related: [frontend.md](frontend.en.md) · [backend.md](backend.en.md) ·
[critical-runtime.md](critical-runtime.en.md) · [release.md](release.en.md) ·
[modules.md](modules.en.md)
