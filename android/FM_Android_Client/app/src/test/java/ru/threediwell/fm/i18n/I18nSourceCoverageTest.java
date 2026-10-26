// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.i18n;

import org.json.JSONObject;
import org.junit.Test;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.regex.*;
import java.util.stream.Stream;
import static org.junit.Assert.*;

/** Каждая русская строка интерфейса в исходниках (I18n.t("…")) есть в английском каталоге. */
public class I18nSourceCoverageTest {
    private static final Pattern CALL = Pattern.compile("I18n\\.t\\(\"((?:[^\"\\\\]|\\\\.)*)\"\\)");

    private static Path sources() {
        for (String candidate : new String[]{"src/main/java", "app/src/main/java"}) {
            Path p = Paths.get(candidate);
            if (Files.isDirectory(p)) return p;
        }
        throw new AssertionError("исходники приложения не найдены");
    }

    private static String unescape(String raw) {
        StringBuilder out = new StringBuilder();
        for (int i = 0; i < raw.length(); i++) {
            char c = raw.charAt(i);
            if (c != '\\' || i + 1 >= raw.length()) { out.append(c); continue; }
            char n = raw.charAt(++i);
            switch (n) {
                case 'n' -> out.append('\n');
                case 't' -> out.append('\t');
                case 'u' -> { out.append((char) Integer.parseInt(raw.substring(i + 1, i + 5), 16)); i += 4; }
                default -> out.append(n);
            }
        }
        return out.toString();
    }

    @Test public void everyLiteralPassedToI18nHasAnEnglishEntry() throws Exception {
        JSONObject catalog;
        try (InputStream stream = I18n.class.getResourceAsStream("/i18n/en.json")) {
            assertNotNull(stream);
            catalog = new JSONObject(new String(stream.readAllBytes(), StandardCharsets.UTF_8));
        }
        Set<String> missing = new TreeSet<>();
        int seen = 0;
        try (Stream<Path> files = Files.walk(sources())) {
            for (Path file : (Iterable<Path>) files.filter(f -> f.toString().endsWith(".java"))::iterator) {
                Matcher m = CALL.matcher(new String(Files.readAllBytes(file), StandardCharsets.UTF_8));
                while (m.find()) {
                    seen++;
                    String key = unescape(m.group(1));
                    if (!catalog.has(key)) missing.add(file.getFileName() + ": " + key);
                }
            }
        }
        assertTrue("найдено слишком мало строк: " + seen, seen > 500);
        assertTrue("нет перевода: " + missing, missing.isEmpty());
    }
}
