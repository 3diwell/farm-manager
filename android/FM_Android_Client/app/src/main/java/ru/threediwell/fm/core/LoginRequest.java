// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.core;

import ru.threediwell.fm.i18n.I18n;
import org.json.JSONObject;
import java.io.IOException;
import java.util.Locale;

/** Sign-in contract with FM: what the checkbox promises, what is sent, how errors read.
 * Source: docs/ANDROID_REMEMBER_DEVICE.md (protocol 1) and server.py auth_login/auth_status.
 */
public final class LoginRequest {
    public static final int DEVICE_NAME_LIMIT = 64;
    private LoginRequest() {}

    /** What the "remember" checkbox means on this FM. */
    public enum Mode {
        /** Older FM: the phone keeps the session for at most 8 hours. */
        EIGHT_HOURS,
        /** FM with remember_device >= 1: kept until logout or revocation in FM. */
        DEVICE
    }

    public static Mode mode(JSONObject status) {
        if(status==null) return Mode.EIGHT_HOURS;
        Object value=status.opt("remember_device");
        return value instanceof Number && ((Number)value).intValue()>=1 ? Mode.DEVICE : Mode.EIGHT_HOURS;
    }

    public static String checkboxText(Mode mode) {
        return mode==Mode.DEVICE ? I18n.t("Запомнить это устройство") : I18n.t("Запомнить вход на 8 часов");
    }

    public static String hintText(Mode mode) {
        return mode==Mode.DEVICE ? I18n.t("Вход сохранится, пока вы не выйдете или не отзовёте доступ в FM")
                : I18n.t("До 8 часов с момента входа. Перезапуск FM или отзыв доступа потребует нового входа.");
    }

    /** "Samsung SM-S918B", "Google Pixel 7"; the maker is not repeated when the model already has it. */
    public static String deviceName(String manufacturer, String model) {
        String maker=manufacturer==null?"":manufacturer.trim(), name=model==null?"":model.trim();
        if(!maker.isEmpty()) maker=maker.substring(0,1).toUpperCase(Locale.ROOT)+maker.substring(1);
        String value=name.toLowerCase(Locale.ROOT).startsWith(maker.toLowerCase(Locale.ROOT)) ? name
                : (maker+" "+name).trim();
        value=value.replaceAll("[\\p{Cntrl}]","").replaceAll("\\s+"," ").trim();
        return value.length()>DEVICE_NAME_LIMIT ? value.substring(0,DEVICE_NAME_LIMIT).trim() : value;
    }

    /** Body of POST /api/auth/login. remember_device only when the user chose it on an FM that offers it. */
    public static JSONObject body(String username, String password, boolean rememberDevice, String deviceName) throws Exception {
        JSONObject body=new JSONObject().put("username",username).put("password",password);
        if(rememberDevice) {
            body.put("remember_device",true);
            if(deviceName!=null && !deviceName.isEmpty()) body.put("device_name",deviceName);
        }
        return body;
    }

    /** FM answered device.persistent == true: the cookie is a device token without a phone-side limit. */
    public static boolean persistent(JSONObject answer) {
        JSONObject device=answer==null?null:answer.optJSONObject("device");
        return device!=null && Boolean.TRUE.equals(device.opt("persistent"));
    }

    /** Remember was asked, but FM could not store the permission and issued an ordinary session. */
    public static boolean deviceNotStored(JSONObject answer) {
        return answer!=null && answer.has("remember_device_error") && !persistent(answer);
    }

    /** Error of POST /api/auth/login, never "operation saved": nothing is pending at sign-in. */
    public static final class Failed extends IOException {
        public final int status;
        public Failed(int status, String message) { super(message); this.status=status; }
    }

    public static Failed wrongPassword() { return new Failed(401, I18n.t("Неверный логин или пароль")); }

    /** Retry-After is seconds (FM sends an integer); minutes are rounded up, at least 1. */
    public static Failed tooManyAttempts(long retryAfterSeconds) {
        if(retryAfterSeconds<=0)
            return new Failed(429, I18n.t("Слишком много попыток. Подождите несколько минут и повторите вход."));
        long minutes=Math.max(1,(retryAfterSeconds+59)/60);
        return new Failed(429, I18n.t("Слишком много попыток. Подождите ")+minutes+I18n.t(" мин."));
    }

    /** Maps a failure of the login call. Other failures (network, 5xx) pass unchanged. */
    public static Exception failure(Exception error) {
        if(error instanceof FmApi.Unauthorized) return wrongPassword();
        if(error instanceof FmApi.Rejected) {
            FmApi.Rejected rejected=(FmApi.Rejected)error;
            if(rejected.status==429 || "auth_rate_limited".equals(rejected.code)) return tooManyAttempts(rejected.retryAfterSeconds);
            if(rejected.status==401 || "invalid".equals(rejected.code)) return wrongPassword();
        }
        return error;
    }

    /** Parses Retry-After; -1 when absent or not a number of seconds. */
    public static long retryAfterSeconds(String header) {
        if(header==null) return -1;
        try { long value=Long.parseLong(header.trim()); return value<0?-1:value; }
        catch(NumberFormatException ex) { return -1; }
    }
}
