[Русский](MODULE_LICENSING_FOUNDATION.md) · **English**

# Foundation for paid FM modules: signed packages and licenses

Status as of 26.09.2026 (Alpha 3.0). For module developers and core maintainers.
The user side — [docs/user/licenses.en.md](../user/licenses.en.md).

## 1. What it is and what it does not provide

The FM core is free and open (MPL 2.0). Modules can be free, paid, or have both a free and a
paid part. The foundation exists to:

- install an official module package only whole and unmodified — the signature and every
  file are verified **before** any module code runs;
- sell a module as "perpetual + update period": purchased releases work indefinitely, new ones —
  while the paid period lasts;
- work **completely offline** after receiving the license file: no registration and no
  periodic checks on the vendor's server.

What it does **not** provide or promise:

- The core is open. It can be rebuilt with any check removed. That is why the paid component
  checks the license **itself**, inside its own paid operation, and does not trust the core's answer (section 7).
- An offline program cannot be made uncrackable: the paid component can also be examined and
  modified. The goal is protection against simple copying, forged licenses and bypassing the normal
  interface, not absolute protection.
- A module runs inside the core process. The signature confirms the origin and integrity of the
  package; it is not a sandbox — verified code can do anything the core can.
- A module written entirely in browser JavaScript is less protected: its code sits in the
  user's browser. Keep valuable logic on the module's server side.
- The browser receives the module's `web/` files as plain text — anyone who has
  access to the program's interface can read them. Keys, paid logic and anything else of value are not placed in `web/`.

### SDK license — MPL-2.0 (16.10.2026, R-149)

`app/licensing/fm_license_sdk.py` and `app/licensing/fm_paid_guard.py` are under the Mozilla Public License 2.0,
like the whole core; they have no second license. Each file starts with the same header
(`SPDX-License-Identifier: MPL-2.0`, copyright holder, link to the MPL text) that the open
copy export (`tools/public_export.py`) adds to the other files; it is within the first 600 bytes, so
the export will not add a second one. MPL is a file-level license: a paid module places a
copy of these files **unchanged** into its package (`tools/module_package.py --embed-sdk` copies the bytes), and
the rest of the module's code may be under any license — it is a "Larger Work" under
section 3.3 of the MPL. A modified copy of the SDK may be distributed only together with its source code.
This does not restrict the vendor's own paid modules: the vendor holds the rights to the SDK. Check —
`tools/test_licensing_foundation.py` (V0c: the header is in place, the copy in the package matches byte for byte).

## 2. Who is responsible for what

| Who | What it does |
|---|---|
| FM core (open) | Verifies the package on installation and before every start, stores license files as is, shows statuses, closes paid routes in the normal way (402), does not replace a working version with an unpaid one |
| Paid component | Itself verifies the license signature with its embedded keys, the right to the feature, edition and **its own** release, the binding — before every paid operation |
| Vendor | Holds the private keys (separately from the project), issues licenses and signed packages with the `tools/fm_license_tool.py` and `tools/module_package.py` utilities |

## 3. Signed document

A license and a package passport are JSON documents with the same structure:

```json
{"format": "fm-license | fm-package", "v": 1,
 "payload": { ...signed fields... },
 "sig": {"alg": "Ed25519", "key_id": "<trusted key id>", "value": "<base64url signature>"}}
```

- Ed25519 signature (RFC 8032) over the bytes
  `b"FM-SIGNED-V1\n" + format + b"\n" + canonical(payload)`. Different formats are different signature
  domains: a passport signature cannot be passed off as a license signature.
- `canonical` — JSON with sorted keys, no whitespace, UTF-8; fractional numbers are forbidden.
- `payload.key_id` must match `sig.key_id`. A public key from the document itself is **never**
  accepted: keys are taken only from the trusted set.
- License keys and package keys are different (`purpose`: `license` / `package`).
- Any extra or missing field, unknown value or invalid date means refusal. A missing date
  does not mean "perpetual".

Verification — `app/licensing/fm_license_sdk.py`. The file is self-contained (standard library +
`cryptography`), without FM imports and without network access: the paid component places its **copy** into its package.

## 4. License (`fm-license`)

| Field | Required | Meaning |
|---|---|---|
| `schema_version` | yes | `1` |
| `product_id` | yes | `3diwell-fm` |
| `license_id` | yes | unique number, file name `<license_id>.fmlic` |
| `customer_ref` | no | internal customer number, up to 128 characters, without unnecessary personal data |
| `grants` | yes | `[{module_id, edition, features}]`; `features: ["*"]` — all features of the edition |
| `use_type` | yes | `perpetual` or `term` (time-limited) |
| `use_valid_from`, `use_valid_until` | only for `term` | the period of use; a perpetual license must not have them |
| `updates_before` | yes | exclusive upper bound on the release date of available updates, UTC |
| `release_scope` | no | `{"max_major": N}` — no higher than major version N |
| `channel` | no | `stable` (default) or `beta` |
| `installation_binding` | no | `{"install_id": "..."}` — the license is only for this installation |
| `issued_at`, `key_id` | yes | issue date and the vendor key |

Dates — strictly `YYYY-MM-DDThh:mm:ssZ`.

### Right to a release

A release is available if

```text
release.released_at < license.updates_before
```

and the module, edition, channel, version limit and binding match, and for a term license the period of
use is current. **Two signed dates** are compared, not the computer's clock: a perpetual license
does not depend on the clock at all. Example: updates until `2027-10-01` — a release of 20.09.2027 works
always, including when reinstalled in 2028; a release of 10.10.2027 requires a renewal.
A renewal is a new license file with a new bound; the previous ones remain and keep working.

The release **must** be passed to the check (`evaluate(..., release=...)`); without it the refusal is
`release_required`. A commercial component passes the release embedded in its code, not a file from disk.

Refusal codes: `no_grant`, `edition_not_granted`, `feature_not_granted`, `use_not_started`,
`use_expired`, `time_required`, `binding_mismatch`, `channel_not_granted`, `release_scope`,
`update_not_covered`, `release_required`, and when parsing — `malformed`, `wrong_format`,
`unknown_key`, `bad_signature`, `wrong_product`, `unknown_field`, `missing_field`, `bad_value`.

## 5. Module package (`fm-package.json`)

The passport is in the root of the module folder. Fields: `schema_version`, `product_id`, `module_id`, `edition`,
`version`, `channel`, `released_at`, `core_contract`, `licensing: {model, paid_features}`
(`model`: `free` | `paid` | `freemium`), `entry: {backend, web}`, `files: {path: sha256}`, `key_id`.
Editing `paid`/`edition`/a file with a regular editor breaks the signature.

A paid package carries copies of `fm_license_sdk.py` and `fm_paid_guard.py` under MPL-2.0 — unmodified, with
their own license header (section 1, "SDK license").

### Package policy in the core

| Package | Installation | Start |
|---|---|---|
| Without a passport (old, third-party, development modules — all 3.0 modules) | as before | as before; no paid features |
| Signed with a trusted key, files match | installed | code runs from verified bytes |
| Signature does not match, a file was changed, added or is missing | **not installed**, the working version is intact | **does not start**, state `integrity_failed`, module data is intact |
| Signed with an unknown key (for example, a test key in a built program) | not installed | does not start, `package_untrusted` |

Installation unpacks the archive into a separate folder (`DATA_DIR/modules_staging`), verifies it there and
only then replaces the working version; the previous one is kept in `DATA_DIR/modules_previous/<id>`
(reinstalling the same release does not overwrite it). The replacement survives a brief Windows file lock
by retrying; if the replacement was nevertheless interrupted, the journal `modules_staging/<id>.swap.json`
puts the previous version back on the next program start.
An archive with names that Windows merges into one file (`backend.py` and `BACKEND.PY`, `backend.py.`),
or with reserved names (`CON`, `NUL`…) is not installed.

**An unpaid update does not replace the working version**: if the previous release of a paid module is covered
by a license and the new one is not (`update_not_covered`), installation is refused and the previous version keeps working.

**Python cache.** Python would run a planted `.pyc` in `__pycache__` instead of the verified
source. For a signed package the core: removes `__pycache__` before starting, loads
`backend.py` and neighbouring files from verified bytes (checking the hash on every read), neither reads nor
writes bytecode, refuses to import a file that is not in the passport. A standalone `.pyc` outside
`__pycache__` is an extra file, and the package fails verification. `web/` resources of a signed package
are served only if they match the passport.

## 6. Core interface for modules

`register(core)` receives a `ModuleCore` object. For licensing (the module needs no new HTTP
routes):

| Method | What it provides |
|---|---|
| `core.license_documents()` | the bytes of all license files exactly as issued by the vendor |
| `core.license_revision()` | a number that changes when a license is added, removed or replaced |
| `core.install_id()` | the ID of this installation (for licenses with a binding) |
| `core.package_document()` | the bytes of the passport verified by the core, or `None` for an unsigned package |
| `core.import_module_file(rel, name)` | load a neighbouring `.py`; for a signed package — only from the passport and from verified bytes |
| `core.add_paid_route(path, handler, feature, methods, policy_id)` | a paid feature route: without a license the core answers 402 and does not call the handler |
| `core.license_verdicts()` | (11.10.2026) the bytes of the signed license service responses — the paid component verifies them itself |
| `core.license_machine()` | (11.10.2026) the computer ID of this computer (64 hex), the one sent in the check-in |
| `core.license_status()`, `core.feature_allowed(feature)` | **the core's view** — for hints and planning, not for protection |

HTTP for the settings window (administrator only): `GET /api/licenses` (licenses, installation ID,
activation request, paid module statuses), `POST /api/licenses/import` (a `.fmlic` file),
`DELETE /api/licenses/{license_id}`. In `GET /api/modules` each module has a `licensing` field.

## 7. Contract of independent verification in the paid component

Before every paid operation (route, background task, report) the component:

1. Takes **its own** copy of the SDK and **its own** embedded data: `fm_license_sdk.py` and `fm_embedded.py`
   (`EMBEDDED_RELEASE` — module, edition, version, channel, release date; `TRUSTED_KEYS` — the vendor's public
   keys). The packager places both files into the package and covers them with the signature.
2. Verifies its package passport (`core.package_document()`) with its package key and
   the match with `EMBEDDED_RELEASE` (`embedded_release_matches`); checks the files of its folder
   (`verify_installed_package`).
3. Verifies each license (`core.license_documents()`) with its license key.
4. Decides with `best_decision(..., feature=..., edition=..., release=EMBEDDED_RELEASE,
   install_id=core.install_id(), now=...)`. No right — refusal; it does not trust the core.

Example — [examples/modules/demo_paid/backend.py](../../examples/modules/demo_paid/backend.py).

**Ready-made self-check (11.10.2026)** — `app/licensing/fm_paid_guard.py`. The packager with `--embed-sdk`
places its copy into the package next to the SDK; `fm_embedded.py` now also carries the model (`EMBEDDED_LICENSING`).
The module, in `register()`:

```python
g = core.import_module_file("fm_paid_guard.py", "fm_<id>_paid_guard")   # no file — the module is free
_paid = g.load(core, "fm_<id>")                                        # None if the model is free
if _paid is not None:
    core.add_route = _paid.route_adder(core.add_route)   # model paid: modifying routes are behind the guard, GET is open
# model freemium: route_adder wraps nothing — the module wraps its paid routes itself: _paid.wrap(handler, feature)
```

`PaidGuard.check()` verifies the passport, its own files, the licenses and the service responses for this computer
(`core.license_verdicts`, `core.license_machine`) and caches the decision for 10 seconds (file verification — for 5
minutes; a failed one is rechecked after 10 seconds). Without the right, a modifying route answers 402 with `checked_by: "module"`, viewing works; in print
hooks the paid part is skipped (`not _paid.check()[0]`). This is how "Inventory" 1.7.39 and
"Order calculation" 0.2.3 are connected; the regular builds of these modules (without embedded files — all releases so far) have no
self-check, they are free.
The check `tools/test_licensing_foundation.py` (section 7) fakes a core that says "a license exists" and
makes sure the component still refuses without a real document, with a forged
document, with someone else's release passport and with an added file.

Rules for the paid component:

- Load neighbouring files of a signed module via `core.import_module_file(...)` or a regular
  `import` (the module folder is on `sys.path`), not via `importlib.util.spec_from_file_location`: only
  this way is the file taken from verified bytes. Binary extensions (`.pyd`) are verified before loading,
  but are read from disk once more — that is the limit.
- A license refusal **does not stop printing**: in print hooks (`pre_print_check`,
  `after_dispatch`) the paid part simply does not run, and printing goes on as without the module.
- A license refusal **does not delete or hide data**: the user can export their data
  with regular permissions.
- A long operation started with a valid license completes normally.
- A module with user data must have a backup provider
  (`app/config_backup/module_providers.py`), otherwise a full settings backup will fail.

## 8. Keys

- The program contains only **public** keys: `app/licensing/trust.py`, `PRODUCTION_KEYS`. Currently
  the list is **empty**: the production program accepts no paid license and no "official" package
  until the vendor creates keys and puts their public parts there.
- Test keys are accepted only when running from source and only if the
  `FM_LICENSE_TEST_KEYS` variable points to a file with test public keys. A built program
  does not accept test keys under any settings. The licenses window warns when
  test keys are enabled.
- Private keys are stored outside the project, password-encrypted, in two copies. The utilities refuse
  to read or write a private key inside the project folder and do not write customer licenses there;
  `.gitignore` keeps `*.pem`, `*.key`, `*.fmlic`, `keys/`, `secrets/` out of git.
- Key rotation: a new key is added next to the old one; previous licenses are verified with the previous
  key until it is deliberately removed.

## 9. Vendor utilities

```bash
python tools/fm_license_tool.py keygen --purpose license --key-id vendor-lic-2026 --out D:\keys
python tools/fm_license_tool.py sign-license --key D:\keys\vendor-lic-2026.pem --key-id vendor-lic-2026 --spec spec.json --out D:\issued\L-0001.fmlic
python tools/module_package.py --module-dir modules\quality --out quality-0.2.3.zip
python tools/module_package.py --module-dir examples\modules\demo_paid --out demo_paid.zip --sign-key D:\keys\vendor-pkg.pem --key-id vendor-pkg-2026 --released-at 2026-09-26T00:00:00Z --licensing freemium --paid-feature pro_report --edition pro --embed-sdk --embed-trust D:\keys\trust-public.json
python tools/fm_license_tool.py verify --trusted D:\keys\trust-public.json D:\issued\L-0001.fmlic
```

The packager consistently excludes cache, logs, databases, backups, licenses and keys, and produces
an identical archive from identical sources.

## 10. Offline activation

1. In FM: *Settings → Modules → Module licenses → Save an activation request* — a file with the installation
   ID, the program version and the modules, without names, addresses or farm data.
2. The file is moved to a computer with internet access or sent to the vendor by any means.
3. The vendor issues a signed license (bound to `install_id` if needed).
4. The `.fmlic` file is moved to the farm computer and added: *Add a license from a file*.
5. From then on no internet is needed — neither when restarting the program nor the computer.

A fully offline installation will not learn about a payment refund or revocation until it receives new data.
The installation binding deters simple copying of a license, but not a full clone of the
computer or virtual machine together with the data folder.

## 11. How to connect the next paid module

1. Choose the model: `paid` (everything is paid) or `freemium` (list the paid features).
2. Declare the routes of paid features with `core.add_paid_route(...)`; permission entries go into
   `app/route_policy_registry.py` (otherwise, with login protection on, the route is available only to the
   administrator).
3. Inside each paid operation — the check from section 7 (a ready-made sample is `demo_paid`).
4. A backup provider for the module's data.
5. Build a signed package with the packager using `--embed-sdk --embed-trust`, specifying the release date.
6. Issue a license with `updates_before`; test it on an isolated server
   (`tools/test_licensing_process.py` is a sample scenario).

## 12. Existing modules

16.10.2026: this section was brought in line with the owner's decision of 01.10.2026. The earlier phrase
"existing features are not made paid" (26.09.2026) contradicted that decision.

- **"Inventory" (`inventory`) and "Order calculation" (`cost`) are paid modules of the 3DiWell team**
  since 01.10.2026. They become paid only in a **signed paid build** (`--licensing
  paid`, section 11), which is released after the production keys and license service addresses
  are put into the program (`app/licensing/trust.py`). While `PRODUCTION_KEYS` is empty, the production program
  contacts nothing and both modules work for free.
- **Free builds of inventory and order calculation already handed out** (without a signature and without the self-check) keep
  working indefinitely: paid status is not applied retroactively and does not switch off a copy already issued.
- **The other Alpha 3.0 modules** ("Quality analytics", "Messenger notifications", "Appearance and themes", "Camera Wall") are
  free and unsigned; nothing has changed for them. A free module can be signed
  (`--licensing free`) so that the core verifies its integrity — it still does not need a license.

## 13. Checks

- `tools/test_licensing_foundation.py` — SDK, packages, loader, license service, packager,
  utility, independent verification of the component, absence of network access, the MPL-2.0 header of the SDK (97 checks).
- `tools/test_licensing_process.py` — the real program process: installation, license,
  restart, package substitution, unpaid update, manual copying, license removal,
  interrupted module replacement.
- `tools/test_licensing_variant3.py` — text key, service response, decision taking responses into account, computer
  ID, core service (consent, renewal, check-in, response only to its own check-in).
- `tools/test_licensing_stand043.py` — compatibility with license service stand 043: strict parsing
  (SDK 1.3), check-in schedule and pauses, renewal in the response, self-check in the paid inventory build,
  environment separation.
- `tools/licensing_test/stand043.py` — acceptance on the received test licenses (L01–L10) and a test
  program for the owner's checks on the stand (H01–H10); instructions —
  `docs/release_prep/LICENSE_STAND_043_RU.md`. The stand kit is private and is not placed in the project.

## 14. Sales "option 3": key, check-in, service response (10.10.2026)

Concept — `docs/release_prep/PAID_MODULES_SALES_CONCEPT.md`, the agreement with the website —
`docs/release_prep/SITE_LICENSING_BRIEF.md` (the website, payment and customer account are built by the second developer).

- **Text key.** `FMK1.` + base64url(zlib(JSON of the `fm-license` document)). It is pasted in the
  *Settings → Modules → Module licenses* window; the signature is verified immediately, no internet needed. A
  `.fmlic` file is accepted as before. A renewal is the same `license_id` with a later `issued_at`;
  an older document does not overwrite a newer one. SDK 1.3 (11.10.2026): a duplicate JSON key, NaN, a signature
  not in canonical base64url, compression other than zlib, data after the end of the stream and decompression beyond 64 KiB mean
  refusal; grants in a license are unique, `customer_ref` — only `[A-Za-z0-9][A-Za-z0-9_.-]`.
- **Consent.** A license (key or file) is accepted only with consent to sending the license
  number and the computer ID (`consent=1`, given once, `licenses/consent.json`).
- **Computer ID.** Three parts: the Windows `MachineGuid`, the motherboard UUID from SMBIOS, the serial number of the
  system volume — each as a salted hash; the ID is a hash of the parts. The motherboard decides: the same
  motherboard UUID means the same computer (reinstalling Windows or replacing the disk does not change the ID); if the motherboard cannot be
  read, it is the same computer only if both other parts match (`licenses/machine.json`); a copy of the disk with
  the whole data folder on a different motherboard gives a new ID. People are shown `XXXX-XXXX`.
- **Check-in.** `POST <service address>` with the body `{schema_version, product_id, license_id, proof,
  machine, module_id, module_version, fm_version, nonce, via}`; `proof` = sha256 of the license document's
  signature string; versions follow the service's pattern (`wire_version`, empty — "0"). One check-in per
  license (the modules of one license take one seat). Directly — a background thread of the core; through the browser —
  the FM page of an administrator carries the check-in to the service (CORS) and returns its response to
  `/api/licenses/import`. **Schedule (11.10.2026, stand 043).** Each check-in has a new random
  number and is sent once (`LicenseService.take_due`): after it neither the direct channel nor the browser repeats it
  before it is due. Intervals: response received — 6 hours; a new key or renewal — immediately; no connection —
  15 minutes (both directly and through the browser: the page reports "no connection" — `relay_status=network`; without its
  report a check-in handed to the browser also waits 15 minutes); a service refusal (4xx) or a rejected response —
  6 hours; 429/503 — a pause for ALL check-ins of both channels according to Retry-After, in seconds or as an HTTP date (RFC
  9110, 10.2.3; a date in the past — 30 seconds). **Since 17.10.2026 (service 043 response)** the pause is exactly what
  the service asked for, including longer than a day: the program does not contact it earlier; without the header,
  with "0" or garbage — 15 / 5 minutes; no less than 30 seconds; the limit is a year (protection against an obvious error). Next to
  the end of the pause the program stores when it was set and for how long (`marks.json`: `backoff_set_at`, `backoff_s`):
  if the record does not match or is missing, a term longer than a day is considered corrupted; if the clock is behind (the
  computer started before time synchronization, a clock reset), the end of the pause is not recalculated or shortened, and after
  the clock is corrected the program does not contact the service before its term. Re-entering the key, "Remove" and "Add", frequently opening
  the licenses window and switching the channel do not bypass the pause. The browser reports the outcome to the program with the `relay_*` fields of
  the same `/api/licenses/import`; it sees Retry-After only if the service exposed the header
  (`Access-Control-Expose-Headers: Retry-After`), otherwise — 15 / 5 minutes. No more than 10 check-ins per minute
  for both channels together (stand 043: 20 per minute from one network). The thread looks every 15 minutes and goes to the network
  only when it is due. No connection error changes the rights. Address — `app/licensing/trust.py`,
  `LICENSE_SERVICE_URL` (only https on 3diwell.com and subdomains); **while it is empty, the program contacts
  nothing**. From source, for checks — the `FM_LICENSE_TEST_SERVICE` variable.
- **Service response `fm-verdict`.** Signed with the license key, with its own signature domain. It is accepted
  only for the last check-in of this computer (the same `nonce`, the same `machine`, a known
  license, not older than the stored one) and no later than a day after it. "Stop"/"revoked" for this
  computer closes the paid features (code `license_stopped`/`license_revoked`) — both in the core and in the
  module itself; no response — the license works. The last accepted response is stored, including after the license is
  removed. An embedded license (renewal) is verified by its own signature and number BEFORE being saved: if it fails,
  the whole response is rejected; an older one does not roll back a newer one; the write is atomic.
- **Licenses window.** Key, consent, computer ID, state according to the service response (and "OK" with
  the response time), the section "What is sent to the license service" — check-ins in the form in which they are sent; `proof`
  is shown on screen only by its beginning.
- **Limits.** A knowledgeable person can block the program's access to the website or delete the stored
  response — a copy of the key will then not be detected (owner's decision: a farm without internet keeps working).
  The protection detects a copy of the key when there is a connection; it does not prevent entering one key on several
  computers without internet and does not revoke an offline copy instantly.
- **Development check.** From source: `FM_LICENSE_TEST_KEYS` (test public keys),
  `FM_LICENSE_TEST_SERVICE` (test service address — 127.0.0.1 or https on 3diwell.com),
  `FM_LICENSE_TEST_RELAY_ONLY=1` (no direct check-in — only through the browser). A built program does not
  read them.
