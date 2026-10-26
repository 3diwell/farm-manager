[Русский](install.md) · **English**

# Installation and updates

Applies to 3DIWELL Farm Manager Beta 3.71 (October 2026).

## Requirements

- Windows 10 or 11, 64-bit.
- Administrator rights for the duration of the installation.
- Printers on the same local network as the farm computer.

The program does not need an internet connection to work.

## First check that the files are intact (SHA-256)

The installer does not have a digital signature yet, so Windows cannot confirm on its own that the file is intact.
Next to the installer there is `SHA256SUMS.txt` — checksums of all the release files: they
show that the files were downloaded without corruption. The checksums are in the same folder as the installer, so
they do not protect against the whole folder being replaced — get the release only from a link provided by 3DIWELL. Open the release folder in File Explorer, type
`powershell` in the address bar, press Enter and paste one line:

```powershell
Get-Content SHA256SUMS.txt -Encoding UTF8 | ForEach-Object { $h, $f = $_ -split '  ', 2; if ((Get-FileHash -LiteralPath $f).Hash -eq $h) { 'OK   ' + $f } else { 'BAD  ' + $f } }
```

Every file should show `OK`. If you see `BAD` or an error, do not run the file; download it again
and contact support. `-Encoding UTF8` is required: without it Windows PowerShell 5.1 garbles
the Russian name of the client folder. A single file can be checked with `Get-FileHash <file>`, then
compare the value with its line in `SHA256SUMS.txt` (letter case does not matter).

## Installation

1. Run `3DIWELL_Farm_Manager_Setup_<version>.exe` with a normal double-click, not with
   "Run as administrator": this way the port is written to the settings of your user account, even
   if the administrator rights belong to another account. Windows will ask for administrator permission itself.
2. Read the license page: the program core is distributed under the Mozilla Public License 2.0.
3. Choose the installation folder (by default `C:\Program Files\3DIWELL Farm Manager`).
4. The "Application port" page: "Automatic" — port 8000, or the nearest free port if it is taken;
   "Set the port manually" — any number from 1024 to 65535. The installer opens exactly the resulting
   port in Windows Firewall. You can see which port was chosen in *Settings → System → Network & access*,
   in the "Server port" line.
5. If the computer does not have .NET Framework 4.7.2+ or Microsoft Edge WebView2 Runtime, the installer
   installs them itself.

## If Windows does not let you run the installer

- **SmartScreen** — the "Windows protected your PC" window (unknown publisher): this is how
  Windows greets any program without a digital signature. If the checksums matched (section above),
  click "More info" → "Run anyway".
- **Smart App Control** — Windows says that the launch was
  blocked. You cannot allow an individual program in it: Microsoft states directly that this
  protection currently cannot be bypassed for a single app
  ([What is Smart App Control](https://support.microsoft.com/en-us/topic/what-is-smart-app-control-285ea03d-fa88-4d56-882e-6698afdb7003)).
  The program can be installed only by turning the protection off: *Settings → Privacy & security →
  Windows Security → App & browser control → Smart App Control*. This protects the whole
  computer — the decision is yours. According to Microsoft, after the latest Windows updates it can be
  turned back on without reinstalling the system. On a freshly installed Windows 11 it first
  runs in evaluation mode and does not block the installation. Only a digital signature
  of the program will fully remove this difficulty — it is planned.

After installation a "3DIWELL Farm Manager" shortcut appears on the desktop and in the Start menu — it
opens the program in its own window. A second shortcut, whose name ends with the Russian word for
"browser", opens it in your regular web browser.

`LICENSE.txt` (the MPL 2.0 text) and `THIRD_PARTY_NOTICES.txt`
(third-party components and their licenses) are installed next to the program.

## Where the data is stored

Printers, projects, settings, logs and module data are stored in the folder
`%LOCALAPPDATA%\3DIWELL`, not in the program folder. That is why updates and reinstallation do not
touch them. The data folder can be changed in *Settings → System → Data storage*.

## Updating

Run the installer of the new version over the installed one. The data folder, printers and modules
are kept. It is a good idea to make a settings backup before updating —
[backup.en.md](backup.en.md).

**Port during an update.** If the program ran on its own port (not 8000), on the "Application
port" page choose "Set the port manually" and enter that number. "Automatic" starts again from
8000 and may change the port — then other computers and the client will no longer open the program at
the previous address.

## Access from other computers

Right after installation the program opens only on this computer. To open it from
other computers on the network or from the client: turn on password sign-in and create an administrator
(*Settings → System → Access & audit*), then turn on "Local network access" (*Settings →
System → Network & access*). "Address for other computers" appears there as well. The installer creates the firewall
rule for the port chosen during installation; if you later change the port in the program, allow the new
port in the firewall manually.

## Client for a second computer

`3DIWELL_Farm_Manager_Client_Setup_<version>.exe` installs only the program window, which
connects to Farm Manager on another computer on the network. The server, databases and printers stay on
the farm computer.
