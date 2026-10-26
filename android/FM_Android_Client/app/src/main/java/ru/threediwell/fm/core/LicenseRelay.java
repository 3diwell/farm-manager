// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.core;

import org.json.JSONArray;
import org.json.JSONObject;
import ru.threediwell.fm.i18n.I18n;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.regex.Pattern;

/**
 * Отметка лицензий модулей через этот телефон — то же, что делает страница FM в браузере (web/app.js, licRelay).
 * У компьютера фермы может не быть интернета, а у телефона он есть: FM отдаёт отметки, которым пора
 * (GET /api/licenses?relay=1), телефон относит каждую службе лицензий и возвращает её подписанный ответ FM
 * (POST /api/licenses/import, поле text). Неудача тоже возвращается FM (relay_status) — сроки повтора решает FM.
 *
 * Тела отметок (в них доказательство владения ключом) и ответы службы живут только в памяти этого вызова:
 * их нельзя писать в журналы, файлы, настройки и Intent.
 */
public final class LicenseRelay {
    public static final int MAX_MARK_BYTES = 4096;
    public static final int MAX_ANSWER_BYTES = 512 * 1024;
    public static final int TIMEOUT_MS = 20000;
    public static final String LICENSES_PATH = "/api/licenses?relay=1";
    public static final String IMPORT_PATH = "/api/licenses/import";
    /** Как app/licensing/trust.py _SITE_URL_RE: только https на 3diwell.com и его поддоменах, без логина и чужого порта. */
    private static final Pattern SITE_URL = Pattern.compile(
            "\\Ahttps://((?:[a-z0-9-]+\\.)*3diwell\\.com)(?::443)?(?:/[A-Za-z0-9._~%/+-]*)?(?:\\?[A-Za-z0-9._~%=&+-]*)?\\z");

    private LicenseRelay() {}

    /** Сеанс FM (штатный FmApi). */
    public interface Fm {
        JSONObject get(String path) throws Exception;
        JSONObject postForm(String path, Map<String, String> fields) throws Exception;
    }

    /** Служба лицензий через сеть телефона, у которой есть интернет. */
    public interface Service {
        /** Есть ли у телефона сеть с проверенным интернетом. */
        boolean online();
        /** POST тела отметки. IOException — нет связи, служба молчит дольше срока. */
        Answer post(String url, byte[] body) throws IOException;
    }

    public static final class Answer {
        public final int code;
        public final String retryAfter;
        /** Тело ответа при 200; null — ответ длиннее MAX_ANSWER_BYTES или код не 200. */
        public final byte[] body;
        public Answer(int code, String retryAfter, byte[] body) { this.code = code; this.retryAfter = retryAfter; this.body = body; }
    }

    public enum Kind { NOT_ADMIN, BUSY, NOTHING, NO_INTERNET, DONE }

    public static final class Result {
        public final Kind kind;
        /** Принятые FM ответы службы: {service_state, service_reason}. */
        public final List<String[]> answers = new ArrayList<>();
        /** Коды HTTP, которыми служба отказала (кроме 429/503). */
        public final List<Integer> refused = new ArrayList<>();
        /** Ответ пришёл, но FM его не принял. */
        public int rejected;
        /** 429 или 503: служба просит подождать (круг остановлен). */
        public int waiting;
        /** Связь со службой оборвалась (круг остановлен). */
        public boolean network;
        public Result(Kind kind) { this.kind = kind; }
    }

    public static boolean allowedServiceUrl(String url) {
        if (url == null) return false;
        String u = url.regionMatches(true, 0, "https://", 0, 8) ? url.toLowerCase(Locale.ROOT) : url;
        return SITE_URL.matcher(u).matches();
    }

    /** Список лицензий и отметки FM отдаёт только администратору при включённой защите. */
    public static boolean isAdmin(JSONObject auth) {
        if (auth == null || !auth.optBoolean("enabled", false) || !auth.optBoolean("authenticated", false)) return false;
        JSONObject user = auth.optJSONObject("user");
        return user != null && "admin".equals(user.optString("role"));
    }

    /** Один круг отметки. Unauthorized от FM пробрасывается; прочие сбои FM при записи итога не останавливают круг. */
    public static Result run(Fm fm, Service service) throws Exception {
        if (!isAdmin(fm.get("/api/auth/status"))) return new Result(Kind.NOT_ADMIN);
        // Без интернета у телефона FM не спрашиваем вовсе: выданная отметка 15 минут не повторяется,
        // а программа фермы в это время могла бы отметиться сама.
        if (!service.online()) return new Result(Kind.NO_INTERNET);
        JSONObject list = fm.get(LICENSES_PATH);
        JSONObject svc = list.optJSONObject("service");
        JSONArray marks = list.optJSONArray("mark_requests");
        String url = svc == null ? "" : svc.optString("url", "");
        if (!"ok".equals(list.optString("status")) || svc == null || !svc.optBoolean("configured", false)
                || url.isEmpty() || marks == null || marks.length() == 0 || !allowedServiceUrl(url))
            return new Result(Kind.NOTHING);
        Result result = new Result(Kind.DONE);
        int sent = 0;
        for (int i = 0; i < marks.length(); i++) {
            JSONObject mark = marks.optJSONObject(i);
            if (mark == null) continue;
            byte[] body = mark.toString().getBytes(StandardCharsets.UTF_8);
            if (body.length > MAX_MARK_BYTES) continue;   // таких FM не выдаёт; чужое не отправляем
            String id = mark.optString("license_id", "");
            sent++;
            Answer answer;
            try {
                answer = service.post(url, body);
            } catch (IOException ex) {
                note(fm, id, "network", null);
                result.network = true;
                break;
            }
            if (answer.code != 200) {
                note(fm, id, String.valueOf(answer.code), answer.retryAfter);
                if (answer.code == 429 || answer.code == 503) { result.waiting = answer.code; break; }
                result.refused.add(answer.code);
                continue;
            }
            if (answer.body == null) {
                result.rejected++;
                note(fm, id, "rejected", null);
                continue;
            }
            JSONObject accepted;
            try {
                Map<String, String> form = new LinkedHashMap<>();
                form.put("text", new String(answer.body, StandardCharsets.UTF_8));
                accepted = fm.postForm(IMPORT_PATH, form);
            } catch (FmApi.Unauthorized ex) {
                throw ex;
            } catch (Exception ex) {
                result.rejected++;   // FM не подтвердил приём; отметку он выдаст снова сам
                continue;
            }
            if ("ok".equals(accepted.optString("status"))) {
                if ("verdict".equals(accepted.optString("kind")))
                    result.answers.add(new String[]{accepted.optString("service_state", ""), accepted.optString("service_reason", "")});
            } else {
                result.rejected++;
                note(fm, id, "rejected", null);
            }
        }
        return sent == 0 ? new Result(Kind.NOTHING) : result;
    }

    private static void note(Fm fm, String licenseId, String status, String retryAfter) throws FmApi.Unauthorized {
        Map<String, String> form = new LinkedHashMap<>();
        form.put("relay_license_id", licenseId);
        form.put("relay_status", status);
        if (retryAfter != null && !retryAfter.trim().isEmpty()) form.put("relay_retry_after", retryAfter.trim());
        try { fm.postForm(IMPORT_PATH, form); }
        catch (FmApi.Unauthorized ex) { throw ex; }
        catch (Exception ignored) { /* итог не дошёл до FM — он сам повторит позже */ }
    }

    /** Тело ответа не длиннее max байт; длиннее — null. */
    public static byte[] readLimited(InputStream in, int max) throws IOException {
        try (InputStream stream = in; ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] block = new byte[8192];
            int n;
            while ((n = stream.read(block)) != -1) {
                if (out.size() + n > max) return null;
                out.write(block, 0, n);
            }
            return out.toByteArray();
        }
    }

    /** Почему служба остановила ключ — те же слова, что на странице FM (licStopWhy). */
    public static String stopWhy(String reason) {
        if ("seat_taken".equals(reason)) return I18n.t("ключ уже работает на другом компьютере — подтвердите перенос в личном кабинете на сайте 3diwell.com");
        if ("moved".equals(reason)) return I18n.t("лицензия перенесена на другой компьютер");
        if ("blocked".equals(reason)) return I18n.t("владелец лицензии не подтвердил этот компьютер");
        return I18n.t("служба лицензий остановила ключ на этом компьютере");
    }

    private static int rank(String state) { return "ok".equals(state) ? 0 : "revoked".equals(state) ? 2 : 1; }

    /**
     * Итог словами. manual — по кнопке: тогда говорим и «нечего отмечать», и «нет связи», и «подождите».
     * Автоматический круг о них молчит, как страница FM: лицензии от этого не меняются. null — молчать.
     * time — время телефона «чч:мм».
     */
    public static String message(Result r, boolean manual, String time) {
        if (r == null || r.kind == Kind.NOT_ADMIN) return null;
        if (r.kind == Kind.BUSY) return manual ? I18n.t("Отметка уже идёт — подождите несколько секунд") : null;
        if (r.kind == Kind.NOTHING) return manual ? I18n.t("Отмечать нечего: программа отметится сама, когда придёт время") : null;
        if (r.kind == Kind.NO_INTERNET) return manual ? I18n.t("У этого телефона нет связи со службой лицензий") : null;
        List<String> lines = new ArrayList<>();
        if (!r.answers.isEmpty()) {
            String[] worst = r.answers.get(0);
            for (String[] a : r.answers) if (rank(a[0]) > rank(worst[0])) worst = a;
            int top = rank(worst[0]), n = r.answers.size(), same = 0;
            for (String[] a : r.answers) if (rank(a[0]) == top) same++;
            String of = n > 1 && top > 0 ? " (" + same + I18n.t(" из ") + n + ")" : "";
            String head = I18n.t("Служба лицензий ответила через этот телефон — ");
            if (top == 0) lines.add(head + I18n.t("работает (") + time + ")");
            else if (top == 2) lines.add(head + I18n.t("АННУЛИРОВАНА") + of + I18n.t(" — платные функции закрыты"));
            else lines.add(head + I18n.t("ОСТАНОВЛЕНА") + of + ": " + stopWhy(worst[1]));
        }
        if (!r.refused.isEmpty()) {
            StringBuilder codes = new StringBuilder();
            for (Integer c : new LinkedHashSet<>(r.refused)) { if (codes.length() > 0) codes.append(", "); codes.append(c); }
            lines.add(I18n.t("Служба лицензий отказала (HTTP ") + codes + I18n.t(") — лицензии работают как прежде"));
        }
        if (r.rejected > 0) lines.add(I18n.t("Ответ службы лицензий не принят — лицензии работают как прежде"));
        if (manual && r.waiting > 0) lines.add(I18n.t("Служба лицензий просит подождать (HTTP ") + r.waiting + I18n.t(") — программа попробует ещё раз позже"));
        if (manual && r.network) lines.add(I18n.t("У этого телефона нет связи со службой лицензий"));
        if (lines.isEmpty()) return manual ? I18n.t("Отмечать нечего: программа отметится сама, когда придёт время") : null;
        return String.join("\n", lines);
    }

    /** Предупреждение, а не обычная новость: остановка, аннулирование, отказ. */
    public static boolean warning(Result r) {
        if (r == null || r.kind != Kind.DONE) return r != null && r.kind == Kind.NO_INTERNET;
        for (String[] a : r.answers) if (rank(a[0]) > 0) return true;
        return !r.refused.isEmpty() || r.rejected > 0 || r.waiting > 0 || r.network;
    }
}
