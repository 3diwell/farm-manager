// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.inventory;

import ru.threediwell.fm.i18n.I18n;
import java.net.URI;
import java.util.regex.Pattern;

/** Stable versioned labels. No URLs are opened or executed from scanned content. */
public final class Labels {
    private static final Pattern ID = Pattern.compile("[A-Za-z0-9_-]{1,100}");
    public record Label(String kind, String server, String id, int slot) {}
    private static String id(String value) {
        if (value == null || !ID.matcher(value).matches()) throw new IllegalArgumentException(I18n.t("Некорректная метка FM"));
        return value;
    }
    public static String spool(String server, String sid) { return "fm1:spool:" + id(server) + ":" + id(sid); }
    public static String slot(String server, String pid, int index) {
        if (index < -1) throw new IllegalArgumentException(I18n.t("Некорректный слот"));
        return "fm1:slot:" + id(server) + ":" + id(pid) + ":" + index;
    }
    public static Label parse(String raw, String expectedServer) {
        String[] p = raw.split(":", -1);
        if (p.length < 4 || !p[0].equals("fm1") || !id(p[2]).equals(expectedServer))
            throw new IllegalArgumentException(I18n.t("Это не метка выбранного склада FM"));
        if (p[1].equals("spool") && p.length == 4) return new Label("spool", p[2], id(p[3]), -1);
        if (p[1].equals("slot") && p.length == 5) {
            int slot = Integer.parseInt(p[4]);
            if (slot >= -1) return new Label("slot", p[2], id(p[3]), slot);
        }
        throw new IllegalArgumentException(I18n.t("Неподдерживаемая метка FM"));
    }
    public static String normalize(String raw) {
        if (raw == null || raw.trim().isEmpty() || raw.length() > 2048)
            throw new IllegalArgumentException(I18n.t("Пустой или слишком длинный код"));
        return raw.trim(); // Preserve leading zeroes, case and vendor URL semantics.
    }
    public static boolean productBarcode(String code) {
        if (!code.matches("[0-9]{8}|[0-9]{12}|[0-9]{13}|[0-9]{14}")) return false;
        int sum = 0;
        for (int i = code.length() - 2, pos = 0; i >= 0; i--, pos++)
            sum += (code.charAt(i) - '0') * (pos % 2 == 0 ? 3 : 1);
        return (10 - sum % 10) % 10 == code.charAt(code.length() - 1) - '0';
    }
}
