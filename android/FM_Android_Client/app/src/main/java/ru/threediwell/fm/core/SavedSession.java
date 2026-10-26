// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.core;

import ru.threediwell.fm.i18n.I18n;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;

/** Contains credentials: do not log.
 * Two kinds of saved login:
 * - 8-hour login (format 1, written by every version since 0.13): a fixed deadline, never sliding;
 * - remembered device (format 2, FM "remember_device" 1): no deadline on the phone clock. It lasts
 *   until logout or revocation in FM and is validated by GET /api/auth/status on every start.
 */
public final class SavedSession {
    public static final long MAX_AGE_MILLIS = 8 * 60 * 60 * 1000L;
    /** Cookie lifetime given to a restored remembered-device token (FM itself sends 10 years). */
    public static final long PERSISTENT_COOKIE_SECONDS = 315360000L;
    public final String origin, token;
    /** For a remembered device expiresAt is 0: the phone clock does not end it. */
    public final long issuedAt, expiresAt;
    public final boolean secure, persistent;

    /** 8-hour login, unchanged since format 1. */
    public SavedSession(String origin, String token, long issuedAt, long expiresAt, boolean secure) {
        this(origin, token, issuedAt, expiresAt, secure, false);
    }

    private SavedSession(String origin, String token, long issuedAt, long expiresAt, boolean secure, boolean persistent) {
        if (!new FmApi(origin).origin.equals(origin) || token == null || !token.matches("[A-Za-z0-9_-]{1,512}")
                || issuedAt <= 0 || (secure && !origin.startsWith("https://"))
                || (persistent ? expiresAt != 0 : (expiresAt <= issuedAt || expiresAt - issuedAt > MAX_AGE_MILLIS)))
            throw new IllegalArgumentException(I18n.t("Некорректный сохранённый вход"));
        this.origin=origin; this.token=token; this.issuedAt=issuedAt; this.expiresAt=expiresAt; this.secure=secure;
        this.persistent=persistent;
    }

    /** Remembered device: FM answered device.persistent == true. */
    public static SavedSession persistent(String origin, String token, long issuedAt, boolean secure) {
        return new SavedSession(origin, token, issuedAt, 0, secure, true);
    }

    /** A remembered device is never ended by the phone clock: only FM decides (GET /api/auth/status). */
    public boolean validAt(long now) { return persistent || (now >= issuedAt && now < expiresAt); }

    public byte[] encode() throws Exception {
        // An 8-hour login stays in format 1 byte-for-byte, so files keep the shape older builds read.
        JSONObject value=new JSONObject().put("version",persistent?2:1).put("origin",origin).put("token",token)
                .put("issuedAt",issuedAt).put("expiresAt",expiresAt).put("secure",secure);
        if(persistent) value.put("persistent",true);
        return value.toString().getBytes(StandardCharsets.UTF_8);
    }

    public static SavedSession decode(byte[] bytes) throws Exception {
        JSONObject value=new JSONObject(new String(bytes,StandardCharsets.UTF_8));
        int version=value.getInt("version");
        if(version==1)
            return new SavedSession(value.getString("origin"),value.getString("token"),value.getLong("issuedAt"),
                    value.getLong("expiresAt"),value.getBoolean("secure"));
        if(version==2) {
            boolean persistent=value.getBoolean("persistent");
            return new SavedSession(value.getString("origin"),value.getString("token"),value.getLong("issuedAt"),
                    value.getLong("expiresAt"),value.getBoolean("secure"),persistent);
        }
        throw new IllegalArgumentException(I18n.t("Неизвестный формат сохранённого входа"));
    }
}
