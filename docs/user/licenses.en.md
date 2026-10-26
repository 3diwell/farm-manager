[Русский](licenses.md) · **English**

# Licenses for paid modules

The program itself and the free modules work without licenses. A license is needed only for paid modules
or the paid features of a module.

## How a license works

- A license is a `.fmlic` file from the module vendor. The program checks the vendor's signature and
  keeps the file. A forged or damaged file is not accepted.
- **No internet connection is needed** either when adding a license or afterwards.
- A purchased version of a module works **perpetually**. New versions are available while the paid
  update period lasts ("updates until …"). When it ends, the installed version keeps
  working and can be reinstalled; new versions require a renewal.
- There are also time-limited licenses ("use until …"): after the term ends the paid features close, while the data
  stays.

## Adding a license

*Settings → Modules → Module licenses*: paste the key from the email (text starting with `FMK1.`),
tick the consent to sending the license number and the computer ID, and press "Add the key". A
`.fmlic` file is added with the "Add a license from a file" button. The paid features open immediately, without
a restart. A renewal is a new key or file: add it the same way.

## Check-in with the license service

When the farm computer has internet access (or an administrator opened the program from a phone that
has it), the program tells the license service: this key is installed on the computer with this ID. The license
row shows the response: "license service: OK (time)", "STOPPED" (the key already works on another
computer — the transfer is confirmed in your account on the website) or "REVOKED". What exactly is sent is shown
in the "What is sent to the license service" section: the license number, the computer ID, the module and versions — without names, printers or
farm data. Without internet access the license works as usual.

## Without a license

A paid module without a valid license opens **in view-only mode**: the data is visible and
can be exported, but you cannot change it or calculate an order. The module window shows a "View only" banner. Printing
always works; without a license, Inventory simply does not deduct filament.

## Activation request

If the license must be bound to this computer, the vendor needs the installation ID.
*Module licenses → Save an activation request* saves a small file with the installation ID,
the program version and the list of modules — without names, addresses or farm data. Send it to the vendor
in any way; you will receive a license file in reply.

## If a new version does not install

"This version was released after your paid updates ended" — the program will not replace the working
version with an unpaid one. The previous version keeps working. A new version requires a license renewal.

## Removing a license

The "Remove" button in the license row. The paid features covered by it close immediately; module and
program data is not deleted. You can restore the license with the same file.

## Moving to another computer

Keep the `.fmlic` files separately — they are not included in the settings backup yet. An unbound license
moves together with its file. For a license bound to an installation, the vendor reissues it for the
new computer based on a new activation request.
