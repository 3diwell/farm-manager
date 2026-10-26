[Русский](UPDATE_0.11_RU.md) · **English**

# Farm Manager 0.11 — 3diwell intro screen

Install `dist/FM-Client-0.11.0-debug.apk` over 0.10 by choosing **Update**. Do not uninstall the app and do not clear its data. The package and signature are unchanged; the FM address, settings and the log of pending operations are kept. After a full launch, sign-in works as usual — the password and session are not saved to storage.

## What is new

On a fresh launch, the engineering reveal of 3diwell from phone version 06 is shown. From 1.75 to 3.00 s the mark shrinks and moves to the left; at 4 s there is an impact; from 4.042 to 4.333 s the remaining parts fly out to the right. The final composition stays until 7 s. The original logo curves and the final colors #EA5E20 / white are kept.

The #18181B background fills the whole screen, including the area around the logo. There is no rectangular video: outlines, surfaces and edges are drawn natively, and the background and captions are independent. Because the logo is white, the intro stays dark even with the light interface theme; after it, the selected theme returns.

The greeting is chosen by the phone's local time:

| Time | Text |
|---|---|
| 00:00–05:59 | Good night / and peaceful printing |
| 06:00–11:59 | Good morning / and good settings |
| 12:00–17:59 | Good afternoon / and good printing |
| 18:00–23:59 | Good evening / and successful projects |

The connection screen is already prepared underneath the intro. The **Continue** button opens it immediately; watching the whole intro is optional. The Android Back button during the intro also opens the ready screen. When system animations are turned off, the app goes straight to the interface. The intro sends no network requests and does not mean that a connection to the farm has been established.

When the app is minimized, the motion pauses, and it resumes when you return. Rotation does not restart it. After it has finished, it is not repeated on a normal return from the background, the camera or NFC. Android 12+ may first briefly show its own system screen with the previous Farm Manager icon.

## Testing on the phone

1. Update 0.10 without deleting data. Fully close the app in recent apps and open it again.
2. Watch the intro to the end: shrinking until the impact, the quick fly-out, an even background and a logo that is neither stretched nor cut off.
3. On the next full launch, tap "Continue". The connection screen with the saved FM address should open immediately.
4. During the intro, minimize the app and return, then check rotation. After it has finished, return from the background — the intro must not appear again.
5. Check the light theme, an enlarged font, system screen areas and gesture navigation. The greeting and the button must remain accessible.
6. Connect to FM and check the usual transition to inventory and the camera. The server, QR, NFC and inventory operations are not changed by this version.

This is the first native implementation of the agreed motion. Light and volume have been adapted for lightweight vector rendering and are not a frame-by-frame Cycles render. Installation, the system start screen, smoothness and the behavior of a particular phone need to be checked on the device.
