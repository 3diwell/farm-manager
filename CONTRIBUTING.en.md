[Русский](CONTRIBUTING.md) · **English**

# Contributing to 3DIWELL Farm Manager

Thank you for wanting to help. Below is how to report a bug, propose a change and check it.

## Reporting a bug

Open an issue using the "Bug" template. Include the program version (the About window),
the printer model and firmware, what you did, what you expected and what you got. A screenshot and
a log help.

**Before attaching a log or a backup**, remove secrets from it: printer access codes, serial
numbers, your network addresses, passwords, bot tokens, license files. FM logs and backups contain
such data by default. Vulnerabilities are not reported in issues but as described in
[SECURITY.en.md](SECURITY.en.md).

## Proposing a change

1. For a notable change, first open an issue and describe the idea — this makes it easier to agree
   before any code is written.
2. Fork the repository and create a branch, make the change, add or update a check in `tools/`.
3. Run the checks (below) and open a pull request using the template.

The project maintainers review and accept changes and publish the official builds. Your fork
remains yours: the MPL 2.0 allows this, and a change gets into an official release once it is accepted.

## License of contributions

The project is distributed under the [MPL 2.0](LICENSE). By submitting a change, you confirm that
you have the right to contribute it under this license (MPL section 2.5) and that it is distributed
under the MPL 2.0. The project does not require copyright assignment. Do not add other people's
code, fonts, images or programs without stating their license and without the right to distribute
them; a third-party component is listed in [THIRD_PARTY_NOTICES.en.md](THIRD_PARTY_NOTICES.en.md).

New first-party source files start with this notice:

```text
SPDX-License-Identifier: MPL-2.0
This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
If a copy of the MPL was not distributed with this file, You can obtain one at
https://mozilla.org/MPL/2.0/.
```

## Checks

- Syntax: `python -m py_compile <file>` for Python, `node --check <file>` for JavaScript.
- Choosing checks for the changed files: `python tools/validation/select_profile.py --working-tree`
  — prints a list of suites; run the whole list.
- A single suite: `python tools/test_<name>.py`.

More details — [docs/dev/testing.en.md](docs/dev/testing.en.md).

## Rules that matter for a live farm

- Checks do not send real commands to printers (print launch, movement, G-code); new checks must
  not either.
- Changes to the database schema, filament deduction, the print queue and backups require a
  separate check and a description in the pull request.
- Secrets, addresses of real printers and personal data are not added to the repository, including
  test data: only made-up values (`FIXTURE_…`, addresses 192.0.2.x).
