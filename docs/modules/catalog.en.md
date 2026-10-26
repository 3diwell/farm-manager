[Русский](catalog.md) · **English**

# Module catalog

As of 16.10.2026, for 3DIWELL Farm Manager Alpha 3.0. Modules are installed in
*Settings → Modules → Install a module from .zip* ([guide](../user/modules.en.md)).

| Module | id | Version | Core contract | Distribution | License | Source code |
|---|---|---|---|---|---|---|
| Inventory | `inventory` | 1.7.41 | 1.7.29 | paid (sales are being prepared; free until they start) | commercial, 3DiWell Team (third-party parts — MIT, DejaVu) | closed |
| Order calculation | `cost` | 0.2.5 | 0.2.0 | paid (sales are being prepared; free until they start) | commercial, 3DiWell Team | closed |
| Quality analytics | `quality` | 0.2.3 | 0.2.3 | free | MPL 2.0 | `modules/quality` |
| Messenger notifications | `messengers` | 0.1.10 | 0.1.8 | free | MPL 2.0 | `modules/messengers` |
| Appearance and themes | `appearance` | 0.17.6 | 0.17.5 | free | to be confirmed | not yet open |
| Camera Wall | `camera_wall` | 0.4.4 | 0.4.3 | free | to be confirmed | not yet open |
| Demo: free module | `demo_free` | 1.0.0 | — | example for developers | MPL 2.0 | `examples/modules/demo_free` |
| Demo: paid module | `demo_paid` | 1.0.0 | — | example for developers | MPL 2.0 | `examples/modules/demo_paid` |

"Core contract" is the version of the module's routes in the core permission map: a module with a different contract
works, but features that are not in the map are available only to the administrator.

Paid modules (owner's decision of 01.10.2026): Inventory and Order calculation. Until sales
start, they work as before, without a license. Once sales start, their editions,
terms and how to get them will be listed here; a download link for a paid module never leads to its source code.

Ready-made module archives are published in Releases together with the program.
