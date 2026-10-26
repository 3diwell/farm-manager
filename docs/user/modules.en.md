[Русский](modules.md) · **English**

# Modules

A module is an extension of the program: filament inventory, quality analytics, messenger notifications,
order calculation and others. Everything is managed in *Settings → Modules*.

## Installing and updating

1. *Settings → Modules → Install and update → Install a module from .zip*.
2. In the built-in Explorer, select the module's `.zip` file.
3. Restart the program with the "Restart the app" button.

Any version can be installed — newer or older than the installed one; the module's data is kept.
If the program knows of a newer version, it warns you but does not cancel the installation. The previous version
of the module is kept in the data folder (`modules_previous`).

A module from a **signed** package is checked by the program first: the vendor's signature and every file.
A damaged or modified package is not installed — the working version stays in place.

## Labels in the module list

| Label | What it means |
|---|---|
| newer: vX | the program knows a newer version; this module works |
| newer than app / some features admin-only | the module is newer than the program: its new features are available only to the administrator for now; update the program |
| some features not connected | the program could not connect some features of the module; install the current version |
| signed | the package is signed by the vendor and verified |
| license active | the paid features work |
| paid features need a license | the free part works; the paid part needs a license |
| release outside paid updates | this version was released after the update period ended — [licenses.en.md](licenses.en.md) |
| Package damaged | the files of a signed module changed after installation; the module is not started, its data is intact — install it again |
| Unknown signature | the package is signed with a key this program does not know |

## Turning off and removing

The switch in the module's row turns it off; the same switch turns it back on. Removing
deletes the module's files, while its data in the data folder stays.
