// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.i18n;

import org.json.JSONObject;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.Locale;

/** Shared by native views, plain-Java validation, NFC reports and PDF output.
 * Only application-owned literals are passed here; server/user data is never translated.
 * Russian source text is the stable catalog key and the backwards-compatible default.
 */
public final class I18n {
    private static volatile String language="ru";
    private I18n() {}
    public static String language() { return language; }
    public static Locale locale() { return Locale.forLanguageTag(language); }
    public static void setLanguage(String value) { language="en".equals(value)?"en":"ru"; }
    public static String t(String source) {
        return language.equals("en") ? English.CATALOG.optString(source,source) : source;
    }
    private static final class English {
        static final JSONObject CATALOG=load();
        private static JSONObject load() {
            try(InputStream input=I18n.class.getResourceAsStream("/i18n/en.json");
                    ByteArrayOutputStream bytes=new ByteArrayOutputStream()) {
                if(input==null) throw new IOException("Missing English catalog");
                byte[] block=new byte[8192];int count;
                while((count=input.read(block))!=-1)bytes.write(block,0,count);
                return new JSONObject(bytes.toString(StandardCharsets.UTF_8.name()));
            } catch(Exception ex) { throw new IllegalStateException("Cannot load packaged language catalog",ex); }
        }
    }
}
