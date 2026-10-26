[Русский](backup.md) · **English**

# Backups

## Settings backup

*Settings → System → Settings backup* (available to the administrator).

The backup includes: Farm Manager settings, printers and their connection data, and the data of installed
modules that support backups: Inventory (together with QR codes, NFC tags and
prepared labels), Order calculation orders with their rates and settings, and the
Messenger notifications settings. Disabled modules are included in the backup too. Projects and tasks are not
included in the backup and are not changed on restore. The window shows which data of each module is included
right before the backup is created.

- The backup can be protected with a password. A lost password cannot be recovered.
- A backup without a password contains printer connection data — keep the file in a safe place.
- The data folder, the archive folder and the server port belong to the computer and are not
  changed on restore.
- Users and sign-in passwords are not included in the backup. If sign-in protection is turned on in the backup, but this
  computer has no administrator, protection stays off — the restore plan says so;
  create an administrator in "Access & audit".
- If a module's data cannot be restored here — an order number from the backup is already used on this computer by another
  order, the module here is older than the backup, or it has never been started — the plan names the reason, and
  the "Restore" button becomes unavailable. You can remove the cause and select the backup again, or you can
  press "Restore without the "…" module": everything else is restored, and this module's data on the
  computer stays as it is. "Include again" cancels the exclusion.
- After a restore the program must be restarted.

## What the backup does not include yet

- model files attached to Order calculation orders (the orders themselves are included);
- data of the former "Print cost" module from old 2.x backups — program 3.0 does not use it;
- themes from the Appearance and themes module and cameras from the Camera Wall module (they are stored in the browser of the computer);
- notification bot keys — on another computer the channels are connected again;
- the module files themselves — modules are installed again from `.zip`;
- `.fmlic` license files — keep them separately.

## Daily database backups

Every day the program itself saves copies of all its databases — both the main ones and the module databases
(inventory, order calculation, quality, notifications) — to the `backups` folder inside the data folder
(by default `%LOCALAPPDATA%\3DIWELL\backups`). A copy is made at startup and checked once
an hour, so a farm that runs for weeks without a restart also gets a copy every
day. The last 30 copies are kept for each database.

The copy of the notifications database includes the messenger bot keys — they stay in the same data folder
of this computer and are not sent anywhere.

## Changing the data folder

*Settings → System → Data storage → Data folder → Choose…* (available to the administrator).

- Choose an empty folder: if it already contains Farm Manager databases, the program refuses, so that
  old data does not replace the working data.
- The change takes effect after a restart. The program moves the databases, modules, licenses, the installation
  ID, project, task and order files, database copies and the log. Each file is first
  copied, the copy is compared with the original, and only then is the original deleted.
- The move needs free space of at least the size of the data folder — **even if the new folder
  is on the same drive**: the program first copies everything and verifies the copies, and deletes the originals only
  afterwards. If there is not enough space, the program shows in "Data storage" how much is needed and how much is free.
- The move runs at startup, before the program opens. A large folder (gigabytes of project
  and task files, a slow or network drive) takes several minutes to move. During this time
  the restart window shows "The data folder is being moved"; do not close the program and do not
  end it in Task Manager. If the window still says that it could not connect,
  wait and press "Retry connection".
- If something fails (not enough space, a file could not be read), nothing is deleted:
  the program keeps working from the previous folder, shows the reason in "Data storage" and
  retries the move at the next startup. To cancel the move, choose the current
  folder again.
- Not moved: the `config.json` startup settings (they are always in
  `%LOCALAPPDATA%\3DIWELL`), the preview cache and temporary files. Files that do not belong to the program
  stay where they are.
- A detailed summary is in the `data-move-report.json` file in the new folder (with a copy in the previous one).
