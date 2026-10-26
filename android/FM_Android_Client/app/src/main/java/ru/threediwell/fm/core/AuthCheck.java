// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.core;

import ru.threediwell.fm.i18n.I18n;
import org.json.JSONObject;
import java.io.IOException;

/** Single rule for the saved login (docs/ANDROID_REMEMBER_DEVICE.md, item 4):
 * the phone forgets it ONLY when GET /api/auth/status answers authenticated:false
 * (or the 8-hour login ran out by its own deadline). A 401 from another request, a closed /ws,
 * 503, a timeout or a broken answer are not proof: FM returns them on a temporary failure too.
 */
public final class AuthCheck {
    public enum Verdict {
        /** FM confirmed the login (or access protection is off and no login is needed). */
        SIGNED_IN,
        /** FM answered authenticated:false: the login is revoked, the saved copy must go. */
        SIGNED_OUT,
        /** No proof either way: keep the saved login and ask again later. */
        UNKNOWN
    }
    public interface StatusSource { JSONObject status() throws Exception; }
    private AuthCheck() {}

    /** Reads one GET /api/auth/status answer. Only booleans count: "true" or a missing field is no proof. */
    public static Verdict classify(JSONObject status) {
        if(status==null) return Verdict.UNKNOWN;
        Object enabled=status.opt("enabled"), authenticated=status.opt("authenticated");
        if(!(enabled instanceof Boolean) || !(authenticated instanceof Boolean)) return Verdict.UNKNOWN;
        return (Boolean)authenticated ? Verdict.SIGNED_IN : Verdict.SIGNED_OUT;
    }

    public static Verdict ask(StatusSource source) {
        try { return classify(source.status()); }
        catch(FmApi.SessionExpired ex) { return Verdict.SIGNED_OUT; }
        catch(Exception ex) { return Verdict.UNKNOWN; }   // 401 of status itself, 503, network, timeout
    }

    /** Call on a worker thread. */
    public static Verdict ask(FmApi api) {
        if(api==null) return Verdict.UNKNOWN;
        if(api.sessionExpired()) return Verdict.SIGNED_OUT;   // 8-hour login past its own deadline
        return ask(() -> api.call("GET","/api/auth/status",null));
    }

    /** What the screen shows after a 401 elsewhere once status was asked.
     * SIGNED_OUT keeps the original Unauthorized (screens go to login and forget the saved login);
     * otherwise a plain IOException: the saved login stays and nothing navigates away. */
    public static Exception afterUnauthorized(Verdict verdict, Exception original) {
        return switch(verdict) {
            case SIGNED_OUT -> original;
            case SIGNED_IN -> new IOException(I18n.t("FM не принял запрос, но вход действует. Повторите действие."));
            case UNKNOWN -> new IOException(I18n.t("Не удалось проверить вход в FM. Сохранённый вход оставлен — повторите позже."));
        };
    }

    public static boolean shouldForget(Verdict verdict) { return verdict==Verdict.SIGNED_OUT; }
}
