// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.core;

import ru.threediwell.fm.BuildConfig;
import ru.threediwell.fm.i18n.I18n;

/** The only source of the version shown to the user: versionName from app/build.gradle. */
public final class AppVersion {
    private AppVersion() {}
    public static String name() { return BuildConfig.VERSION_NAME; }
    /** Login screen footer. */
    public static String footer() { return I18n.t("Мобильный FM · ")+name(); }
    /** Settings line: "Farm Manager 0.15.15-prototype · http://…". */
    public static String withOrigin(String origin) { return "Farm Manager "+name()+" · "+origin; }
    /** First words of the NFC and Bambu diagnostic reports. */
    public static String reportTitle() { return "Farm Manager "+name(); }
}
