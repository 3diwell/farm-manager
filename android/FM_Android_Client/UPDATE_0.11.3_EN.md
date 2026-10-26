[Русский](UPDATE_0.11.3_RU.md) · **English**

# Farm Manager 0.11.3 — turning off the welcome screen

Install `dist/FM-Client-0.11.3-debug.apk` over the previous version without uninstalling the app/deleting its data.

The **"Welcome screen"** switch is available:

- before sign-in: "Connect to FM → App settings";
- after sign-in: "More → Welcome screen".

It is on by default. If you turn it off, on the next launch the app immediately shows
the connection screen without creating the animator or loading the intro data. The state is stored
in the phone's settings and is kept after a restart and an APK update. You can turn it back on
the same way. The short Android system launch stage remains, with a plain background.

The animation and the four approved greetings are kept. Automatic sign-in is not implemented in this version:
the document `AUTH_PERSISTENCE_PLAN_RU.md` describes a solution that takes into account the FM core session limitation.
The password and session are still kept only in memory while the app is running.

Testing on the phone: turn the switch off, fully close the app in recent apps,
launch it again — the connection screen should open. Check that the switch stayed
off. Turn it back on and launch again — the intro should return.
Also check the Android Back button on the settings screen before sign-in: it returns you to the connection screen.
