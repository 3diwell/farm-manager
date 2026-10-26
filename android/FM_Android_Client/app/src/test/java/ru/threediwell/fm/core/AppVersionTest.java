// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.core;

import org.junit.*;
import ru.threediwell.fm.BuildConfig;
import ru.threediwell.fm.i18n.I18n;
import ru.threediwell.fm.nfc.NfcReport;
import static org.junit.Assert.*;

/** Screens and reports show versionName of the build, not a number typed into the text. */
public class AppVersionTest {
    @After public void reset(){I18n.setLanguage("ru");}
    @Test public void everyVersionTextComesFromTheBuild() {
        String version=BuildConfig.VERSION_NAME;
        assertFalse(version.isEmpty());assertEquals(version,AppVersion.name());
        for(String language:new String[]{"ru","en"}) {
            I18n.setLanguage(language);
            String footer=AppVersion.footer(),settings=AppVersion.withOrigin("http://fm.test:8000");
            String nfc=NfcReport.create("Phone","15",new byte[]{1,2,3,4},new String[]{"android.nfc.tech.NfcA"},false,0,0,"");
            String bambu=NfcReport.bambuHeader("Phone","15",35,"01020304");
            for(String text:new String[]{footer,settings,nfc,bambu}) {
                assertTrue(language+": "+text,text.contains(version));
                assertFalse(text,text.contains("0.14.0"));assertFalse(text,text.contains("0.15.5 "));assertFalse(text,text.endsWith("0.15.5"));
            }
            assertTrue(nfc.startsWith("Farm Manager "+version+" — "));
            assertTrue(bambu.startsWith("Farm Manager "+version+" — "));
            assertTrue(settings.endsWith(" · http://fm.test:8000"));
        }
        I18n.setLanguage("en");
        assertEquals("Mobile FM · "+version,AppVersion.footer());
        assertTrue(NfcReport.bambuHeader("Phone","15",35,"01020304").contains("Bambu reading\nPhone: Phone"));
    }
}
