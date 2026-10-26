[Русский](UPDATE_0.11.1_RU.md) · **English**

# Farm Manager 0.11.1 — transition to the intro without a large icon

Install `dist/FM-Client-0.11.1-debug.apk` over 0.11.0, without uninstalling the app or clearing its data.

The screenshot you sent shows the Android system start screen, for which the app icon
was set explicitly in 0.11.0. In the Android 12+ launch theme, that resource has been replaced with a separate
transparent drawable; the background of the system screen and the icon area is #18181B, the same as the native intro.
An empty value/null is not used, so that Android does not substitute the default launcher icon.
The home screen icon and the app's brand graphics have not changed.

The system launch stage remains; the fix removes the large picture visible during this stage.
The short window-opening animation on the launcher side is controlled by Android/the firmware.
The logo motion, the current greetings, the "Continue" button, data and inventory functions are unchanged.
New greeting options have been proposed separately and are not included in this build yet.

After installation, fully close the app in recent apps and launch it again. Expected result:
a dark background, then our animation without a separate large FM picture. Also check the launch
with the light theme selected. This fix has not been tested on a developer phone/emulator:
there is no connected device or installed emulator in the environment.

The configuration follows the [official description of the Android splash screen](https://developer.android.com/develop/ui/views/launch/splash-screen).
Sources before the fix and the test logs: `F:/Codex/Intro/Android_Splash_Fix_v02/`.
