[Русский](privacy-and-network.md) · **English**

# Where Farm Manager connects to the network

This page is for those whose farm has restricted internet access or a configured firewall. It
lists all of the program's connections: to printers on the farm network and to the internet.

## The program itself

- The program window and the phone connect to it on the port chosen during installation (usually 8000).
- While "Local network access" is turned off in "Settings → System → Network & access", the program
  listens only on this computer. Turning access on opens the same port to other devices on
  the farm network.

## Printers (farm network only)

| Printers | How the program talks to them |
|---|---|
| Bambu Lab | MQTT over TLS, port 8883; files — FTPS, port 990; camera — over the manufacturer's protocol |
| Klipper (Moonraker) | HTTP, port 7125 (or the one set in the printer card); Creality K1/K2 camera — WebRTC: the Creality service, port 9999, and HTTPS 443 or HTTP 8000/80 |
| FlashForge Adventurer 5M / 5M Pro | HTTP, port 8898; 5M Pro camera — HTTP, port 8080 |
| Creality on stock firmware | the native Creality service, port 9999; print file — HTTP, port 80; camera — WebRTC (HTTPS 443 or HTTP 8000/80) or MJPEG, port 8080 |

WebRTC camera video goes directly between the program window and the printer on the farm network: the program does not
contact external servers (STUN) either in the camera window or in the Camera Wall.

The "Find on the network" button listens for printer announcements: UDP 2021 and 1990 (Bambu Lab), 5353
(mDNS) and 1900 (SSDP), and sends the standard "identify yourself" query (the same one that Windows itself
and the manufacturers' own programs send). There is no scanning of addresses or ports and no commands to printers.

## Internet

| What | Where | When | How to turn it off |
|---|---|---|---|
| Update check | https://3diwell.com/farm/latest.json | while the program window is open — once every 6 hours | "Settings → General → Check for updates" |
| Bambu Lab message texts | https://e.bambulab.com/query.php | at most once a week | no switch; without internet the program uses the saved texts |
| Messenger notifications module | Telegram, MAX, VK, WhatsApp — only the configured channels | on farm events | turn off the channel or the module |
| License service | not connected yet | — | — |

The update check sends only a plain file request: it contains no farm data and no information about
printers. The Bambu Lab text request downloads a shared table from the manufacturer's
website, with no information about your printers.

## Printer access codes on this computer (accepted risk)

The program stores printer access codes (for Bambu Lab — the "Access Code") in plain text in the
`farm_printers.db` database and in its daily copies in the `backups` folder. Bambu Studio,
OrcaSlicer and Home Assistant store them the same way: the program connects to the printers by itself after a restart, so
the encryption key would be on this same computer anyway. Encryption with Windows tools (DPAPI)
is deliberately not used: after reinstalling Windows or resetting the account password, all the codes
would become unreadable and would have to be entered again for every printer.

What this means in practice:

- the data folder (by default `%LOCALAPPDATA%\3DIWELL`) can be read only by your Windows account
  and the computer's administrators;
- do not send `farm_printers.db` or the `backups` folder to outsiders, and do not put the data folder on
  a cloud drive;
- to move to another computer, use a password-protected settings backup — inside it
  the codes are encrypted (see [backup.en.md](backup.en.md));
- a Bambu Lab code gives access to the printer only from the farm network.

## Phone app

The phone talks to the program on the farm network. About the app's own connections — see
[android.en.md](android.en.md).
