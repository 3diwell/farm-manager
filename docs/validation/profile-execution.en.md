[Русский](profile-execution.md) · **English**

# Validation profile execution

The selector answers the question "what to check". The executor answers the second question:
**which of it is allowed to run unattended.**

```bash
python tools/validation/run_profile.py --working-tree
```

```bash
python tools/validation/run_profile.py --working-tree --execute
```

---

## 1. Selector and executor are different things

| | [select_profile.py](../../tools/validation/select_profile.py) | [run_profile.py](../../tools/validation/run_profile.py) |
|---|---|---|
| Decides | which profile is needed | what of it can be executed |
| Runs | nothing, ever | FAST and provably safe tests |
| Source of truth | `risk_map.json` | `test_catalog.json` + `command_registry.json` |

The executor **does not duplicate** the risk logic: it calls the selector as a module and works with its
result. A classification change is made in one place — the risk map.

## 2. Statuses

| Status | Meaning | Code |
|---|---|---|
| **PASS** | all required checks of the profile were actually executed and are green | 0 |
| **NO_CHANGES** | there are no changes, nothing to check | 0 |
| **DRY_RUN** | the plan is shown, **nothing is executed** | 0 |
| **FAIL** | an executed required check is red | 2 |
| **BLOCKED** | RELEASE, HARDWARE or an invalid configuration — the run did not start | 3 · 5 |
| **PARTIAL** | the safe part was executed, required checks remain | 4 |
| timeout | a step did not fit its budget; the result is red | 6 |

`3` — blocked by profile or risk. `5` — blocked by configuration or input
(a corrupted registry, a stale catalog, a path outside the repository). `6` — timeout.

**PARTIAL is not PASS.** **DRY_RUN is not PASS.** BLOCKED does not mean the product
is broken, but the task is **not considered validated** either.

## 3. What is executed and what is not

| Profile | Behavior |
|---|---|
| **FAST** | `py_compile` of changed `.py`, `node --check` of changed `.js/.mjs`, parsing of changed `.json`, link check of changed `.md`. Does not run the whole project |
| **TARGETED** | FAST + related tests, **only if the catalog has proven them safe** |
| **SUBSYSTEM** | FAST + safe subsystem tests; unsafe ones are deferred, result PARTIAL |
| **RELEASE** | **nothing is executed**, BLOCKED, `release profile requires explicit future release executor` |
| **HARDWARE** | **nothing is executed**, BLOCKED, `manual hardware verification required` |
| `ui_required` | UI tests are never run; the result is no higher than PARTIAL |

Separately from the executor there is an isolated interface check —
[ui-verification.md](ui-verification.en.md). It is **not connected** to `run_profile.py`:
the `ui_required` flag still yields `PARTIAL`, and the UI scenario is run manually.
The stability of its scenarios is confirmed by a series of ten cycles
([ui-stability.md](ui-stability.en.md)). Since stage 3D, the UI step can be executed with the
`--with-ui` flag, but **only** when the qualification is valid and every changed
part of the interface is covered by the diff — the procedure is in
[ui-executor-integration.md](ui-executor-integration.en.md). Without `--with-ui`, with
a stale qualification, or with incomplete coverage, `ui_required` still yields
`PARTIAL`, and a path without a diff does not count as covered.

`web/app.css` and `web/index.html` are deferred: there is no executable command for the balance checks
in the registry, and inventing one is not allowed.

## 4. Why UI, RELEASE and HARDWARE are closed

- **UI** requires a browser. Headless Edge leaves processes behind after a crash, and killing them by
  name is forbidden — that would take down the owner's browser. There is nothing for automation to do here.
- **RELEASE** is an hour of work, 17 mutation proofs and corruption of repository files along the way.
  Running that from a background executor is not allowed: during the run `git status` shows
  someone else's mutations, and parallel work becomes dangerous.
- **HARDWARE** cannot be confirmed programmatically: defect 2.841 showed up only on a live
  K2 Plus. The owner confirms the result on the farm.

These are the boundaries of stage 2B, not permanent ones. They can be lifted only by a separate task.

## 5. How the executor is protected from arbitrary commands

1. **The plan string is not executed.** Steps are built from the structured fields of the selector result
   (`changed_files`, `targeted_tests`, `subsystem_tests`), not from the `command` text.
2. **Registry only.** Only a `command_id` from
   [command_registry.json](../../tools/validation/command_registry.json) can be executed.
3. **An argv array, not a string.** `shell=True` is not used anywhere, so pipes, `&&`,
   `>` and shell substitutions are impossible in principle.
4. **Literal alphabet.** A registry argument must consist of `A-Za-z0-9._/-`. A space,
   a quote and any metacharacter are rejected when the registry is loaded.
5. **The program is not chosen by the user.** `argv[0]` is always `sys.executable` or the located
   `node`. A substituted value can only be a parameter, never a program.
6. **The path is checked.** Inside the repository, exists, correct extension; `..` and an external
   absolute path are rejected.
7. **Tests only from the catalog.** Only what has proven safety can be run.
8. **Minimal environment.** The child process receives a list of allowed variables;
   tokens and keys do not get into it, and therefore do not get into the artifacts.
9. **One process at a time.** Parallelism at this stage is always 1.
10. **Timeout and termination by PID.** The process tree is killed via `taskkill /PID … /T /F`;
    termination by process name is forbidden.

## 6. Safety catalog

[test_catalog.json](../../tools/validation/test_catalog.json) is built statically —
**no test is run while building it**:

```bash
python tools/validation/build_test_catalog.py --check
```

```bash
python tools/validation/build_test_catalog.py --write
```

Classification is based on content: for Python — by the code tree, for `.mjs` — by text.
A capability closes autorun if the test launches a browser or a server, accesses the network,
corrupts files, builds an EXE, touches a database, starts a shell, calls an unknown program,
writes via git, or **imports `server.py`** — the last one is especially insidious: when the program
is running, such a test exits with code 0 on the named mutex before the first
check, so it looks green without having checked anything.

**Unproven safety is not safety.** Anything that could not be analyzed
gets `unknown capability`.

The catalog must be up to date: a stale one stops the run with code 5. Manual
exceptions — [test_catalog_overrides.json](../../tools/validation/test_catalog_overrides.json);
an exception removes **only the listed** capabilities and must state a reason.

## 7. Artifacts

With `--execute`, the result is written to `logs/validation_runs/<run_id>/` (the directory is ignored by
Git): `summary.json`, `summary.txt`, `selector_result.json`, `execution_plan.json`,
`durations.json`, `environment.json`, as well as `steps/NN_<id>.stdout.txt` and `.stderr.txt`.

Only a summary is printed to the console — the full test output is in the files and does not consume
context. `environment.json` contains only the list of allowed variable names: there are no values from
the owner's environment, DATA_DIR or printer data in it.

## 8. Examples

```
docs/validation/*.md            -> R0 FAST      PASS      link check, ~0.05 s
tools/validation/*.py + *.json  -> R1 TARGETED  PASS      4 steps, ~11 s
web/app.css                     -> R1 TARGETED  PARTIAL   UI is checked by a human
web/app.js                      -> R2 SUBSYSTEM PARTIAL   tests launch a browser
app/project_orchestrator.py     -> R4 HARDWARE  BLOCKED   confirmation on a printer
unknown app/*.py                -> R3 RELEASE   BLOCKED   the full gate is run by a human
empty list                      -> NO_CHANGES
```

## 9. Limitations of stage 2B

- The executor does not run UI, RELEASE, HARDWARE, mutation proofs, the build or the installer.
- **30 tests out of 186** are recognized as safe: the rest are closed by proven capabilities.
  This is not an assessment of their quality — only of their suitability for unattended autorun.
- `expected_max_seconds` is an assigned time budget, not a measurement: the tests were not run.
- There is not a single `.mjs` among the safe ones: JS is analyzed as text, and that is not enough for
  proof.
- There is no parallelism, task queue, worktrees or result caching, and none is planned at this
  stage.

Related: [profile-selection.md](profile-selection.en.md) · [frontend.md](frontend.en.md) ·
[backend.md](backend.en.md) · [critical-runtime.md](critical-runtime.en.md) ·
[release.md](release.en.md)
