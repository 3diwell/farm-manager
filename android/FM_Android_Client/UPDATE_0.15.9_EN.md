[Русский](UPDATE_0.15.9_RU.md) · **English**

# FM Android 0.15.9 — "04 Diagrams" and short inventory screens

Install dist/FM-Client-0.15.9-debug.apk over the current app.
There is no need to uninstall the app or clear its data.

All 30 icons are taken from variant 04 "Diagrams" in FM-icon-directions-v2:
the outlines, square line caps and stroke width 2 on a 32 grid are kept.
In the dark theme — silver #C9CDD3, in the light theme — wet asphalt #4F565D.
Unavailable buttons are muted; filled buttons keep their contrast.
The 3D inventory images, the logo and the printer photos are kept.

Fixed the BrandHeader on short screens. When it has no connection
row, the empty View had WRAP_CONTENT. When measured again inside
a ScrollView with fillViewport, it took up the available height: the logo stayed
on the right, roughly in the middle, and the heading and the form were pushed down.
The empty element now has an explicit zero height. The header itself keeps
its minimum of 56dp. The connection row on the printers tab remains visible.
The fix also applies to other short pages with this header.

The measurement contract has been checked against the Android sources:
[View.onMeasure/getDefaultSize](https://raw.githubusercontent.com/aosp-mirror/platform_frameworks_base/android15-release/core/java/android/view/View.java),
[ScrollView.onMeasure](https://raw.githubusercontent.com/aosp-mirror/platform_frameworks_base/android15-release/core/java/android/widget/ScrollView.java).
The owner's symptom matches this defect; without a connected phone,
the behavior of the specific device after the fix has not been tested yet.

Check on the phone:
- Inventory → "Labels and QR codes" and the bottom "Labels" tab: the heading and actions
  must be directly under the compact header.
- Inventory → "Link NFC to spool": the explanation, camera,
  code entry and selection from the list must open. Opening it on its own writes nothing to FM.
- "Spools", the QR download screen and settings, including an enlarged font.
- Connection/refresh/bell/camera/QR in the light and dark themes.

The NFC and label functions still require the inventory module's capabilities
and user rights. Command handlers, confirmations, operation logs,
print accounting, the core and modules have not changed. The real FM and printers were not started.

For developers, an independent test of real Android Views has been added in
app/src/androidTest — BrandHeaderRegressionInstrumentation. It measures
short forms at three widths and font sizes, checks the connection header
and draws all 30 icons in four sizes. The negative control restores
the former WRAP_CONTENT and must reproduce the stretching. The test is built
but has not been run: there is no connected phone/emulator. It is not part of the main
APK and makes no requests to FM. To run it after installing both debug APKs:

    adb shell am instrument -w ru.threediwell.fm.mobile.prototype.test/ru.threediwell.fm.ui.BrandHeaderRegressionInstrumentation

FM-Android-0.15.9-preview/index.html — a preview of the drawings; not an APK screen.
Build results and limitations: VALIDATION_MOBILE_0.15.9.md.
