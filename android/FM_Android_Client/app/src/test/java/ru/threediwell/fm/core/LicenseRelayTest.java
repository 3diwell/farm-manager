// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.core;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.*;
import ru.threediwell.fm.farm.Capabilities;
import ru.threediwell.fm.i18n.I18n;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.atomic.AtomicReference;
import static org.junit.Assert.*;

/** Отметка лицензий через телефон: тот же порядок, что у страницы FM (web/app.js licRelay). */
public class LicenseRelayTest {
    private static final String URL = "https://licenses.3diwell.com/api/v1/mark";

    @After public void reset() { I18n.setLanguage("ru"); }

    // ── заглушки FM и службы ───────────────────────────────────────────────────────────
    static JSONObject mark(String id) throws Exception {
        return new JSONObject().put("schema_version", 1).put("product_id", "fm").put("license_id", id)
                .put("proof", "P".repeat(64)).put("machine", "a".repeat(64)).put("module_id", "paid_mod")
                .put("module_version", "1.0").put("fm_version", "3.0").put("nonce", "n".repeat(32)).put("via", "browser");
    }

    static final class FakeFm implements LicenseRelay.Fm {
        JSONObject auth;
        JSONObject list;
        final List<String> gets = new ArrayList<>();
        final List<Map<String, String>> forms = new ArrayList<>();
        /** Что FM ответит на импорт ответа службы. */
        JSONObject importAnswer;
        FakeFm(String role, String url, JSONObject... marks) throws Exception {
            auth = new JSONObject().put("enabled", true).put("authenticated", true)
                    .put("user", new JSONObject().put("username", "u").put("role", role));
            JSONArray m = new JSONArray();
            for (JSONObject x : marks) m.put(x);
            list = new JSONObject().put("status", "ok").put("service", new JSONObject().put("configured", url != null).put("url", url == null ? "" : url))
                    .put("mark_requests", m).put("licenses", new JSONArray());
            importAnswer = verdict("L1", "ok", "");
        }
        static JSONObject verdict(String id, String state, String reason) throws Exception {
            return new JSONObject().put("status", "ok").put("kind", "verdict").put("license_id", id).put("service_state", state).put("service_reason", reason);
        }
        @Override public JSONObject get(String path) {
            gets.add(path);
            if (path.equals("/api/auth/status")) return auth;
            if (path.equals("/api/licenses?relay=1")) return list;
            throw new AssertionError("unexpected GET " + path);
        }
        @Override public JSONObject postForm(String path, Map<String, String> fields) throws Exception {
            assertEquals("/api/licenses/import", path);
            forms.add(new LinkedHashMap<>(fields));
            return fields.containsKey("text") ? importAnswer : new JSONObject().put("status", "ok").put("kind", "relay_noted");
        }
        List<Map<String, String>> notes() { List<Map<String, String>> out = new ArrayList<>(); for (Map<String, String> f : forms) if (f.containsKey("relay_status")) out.add(f); return out; }
        List<Map<String, String>> imports() { List<Map<String, String>> out = new ArrayList<>(); for (Map<String, String> f : forms) if (f.containsKey("text")) out.add(f); return out; }
    }

    static final class FakeService implements LicenseRelay.Service {
        boolean online = true;
        final Deque<Object> answers = new ArrayDeque<>();   // Answer или IOException
        final List<String> urls = new ArrayList<>();
        final List<String> bodies = new ArrayList<>();
        @Override public boolean online() { return online; }
        @Override public LicenseRelay.Answer post(String url, byte[] body) throws IOException {
            urls.add(url); bodies.add(new String(body, StandardCharsets.UTF_8));
            Object next = answers.isEmpty() ? new LicenseRelay.Answer(200, null, "{\"format\":\"verdict\"}".getBytes(StandardCharsets.UTF_8)) : answers.poll();
            if (next instanceof IOException) throw (IOException) next;
            return (LicenseRelay.Answer) next;
        }
        FakeService then(int code, String retryAfter, String body) { answers.add(new LicenseRelay.Answer(code, retryAfter, body == null ? null : body.getBytes(StandardCharsets.UTF_8))); return this; }
        FakeService thenNetwork() { answers.add(new SocketTimeoutException("timeout")); return this; }
    }

    // ── адрес службы ───────────────────────────────────────────────────────────────────
    @Test public void onlyHttpsOn3diwellComAndSubdomains() {
        for (String ok : new String[]{"https://3diwell.com/api/mark", "https://licenses.3diwell.com/api/v1/mark", "https://a.b.3diwell.com",
                "https://licenses.3diwell.com:443/m", "HTTPS://Licenses.3DIWELL.com/Mark", "https://3diwell.com/m?x=1&y=2"})
            assertTrue(ok, LicenseRelay.allowedServiceUrl(ok));
        for (String bad : new String[]{null, "", "http://licenses.3diwell.com/m", "https://evil.com/3diwell.com", "https://3diwell.com.evil.com/m",
                "https://evil3diwell.com/m", "https://user" + (char) 64 + "3diwell.com/m", "https://3diwell.com:8443/m", "https://3diwell.com/m#frag",
                "https://3diwell.com/m\n", "ftp://3diwell.com/m", "https://licenses.3diwell.com/m?x=<y>", "https://127.0.0.1/m"})
            assertFalse(String.valueOf(bad), LicenseRelay.allowedServiceUrl(bad));
    }

    @Test public void foreignServiceUrlIsNeverContacted() throws Exception {
        FakeFm fm = new FakeFm("admin", "https://evil.example/mark", mark("L1"));
        FakeService service = new FakeService();
        assertEquals(LicenseRelay.Kind.NOTHING, LicenseRelay.run(fm, service).kind);
        assertTrue(service.urls.isEmpty()); assertTrue(fm.forms.isEmpty());
    }

    // ── только администратор ───────────────────────────────────────────────────────────
    @Test public void nonAdminNeverAsksForMarks() throws Exception {
        for (String role : new String[]{"operator", "viewer", ""}) {
            FakeFm fm = new FakeFm(role, URL, mark("L1"));
            FakeService service = new FakeService();
            LicenseRelay.Result r = LicenseRelay.run(fm, service);
            assertEquals(LicenseRelay.Kind.NOT_ADMIN, r.kind);
            assertEquals(Collections.singletonList("/api/auth/status"), fm.gets);
            assertTrue(service.urls.isEmpty());
            assertNull(LicenseRelay.message(r, true, "10:00"));
        }
        // Защита выключена — FM отдаёт лицензии только своему компьютеру; телефон не спрашивает.
        assertFalse(LicenseRelay.isAdmin(new JSONObject().put("enabled", false).put("authenticated", true)));
        assertFalse(LicenseRelay.isAdmin(new JSONObject().put("enabled", true).put("authenticated", false).put("user", new JSONObject().put("role", "admin"))));
        assertTrue(LicenseRelay.isAdmin(new JSONObject().put("enabled", true).put("authenticated", true).put("user", new JSONObject().put("role", "admin"))));
    }

    @Test public void capabilitiesExposeAdminForTheButton() throws Exception {
        JSONObject admin = new JSONObject().put("enabled", true).put("authenticated", true).put("user", new JSONObject().put("username", "a").put("role", "admin"));
        JSONObject operator = new JSONObject().put("enabled", true).put("authenticated", true).put("user", new JSONObject().put("username", "a").put("role", "operator"));
        Capabilities a = new Capabilities(admin, new JSONArray()), o = new Capabilities(operator, new JSONArray());
        assertTrue(a.admin); assertFalse(o.admin); assertTrue(a.operate && o.operate);
        assertFalse("смена роли перерисовывает настройки", a.sameAvailability(o));
    }

    @Test public void phoneWithoutInternetDoesNotTakeMarksFromFm() throws Exception {
        FakeFm fm = new FakeFm("admin", URL, mark("L1"));
        FakeService service = new FakeService(); service.online = false;
        LicenseRelay.Result r = LicenseRelay.run(fm, service);
        assertEquals(LicenseRelay.Kind.NO_INTERNET, r.kind);
        assertFalse(fm.gets.contains("/api/licenses?relay=1"));
        assertEquals("У этого телефона нет связи со службой лицензий", LicenseRelay.message(r, true, "10:00"));
        assertNull(LicenseRelay.message(r, false, "10:00"));
    }

    // ── исход каждого ответа ───────────────────────────────────────────────────────────
    @Test public void acceptedAnswerGoesToFmAsTextExactlyAsReceived() throws Exception {
        JSONObject m = mark("L1");
        FakeFm fm = new FakeFm("admin", URL, m);
        FakeService service = new FakeService().then(200, null, "{\"format\":\"fm-verdict\",\"sig\":\"x y+z&=\"}");
        LicenseRelay.Result r = LicenseRelay.run(fm, service);
        assertEquals(LicenseRelay.Kind.DONE, r.kind);
        assertEquals(Collections.singletonList(URL), service.urls);
        JSONObject sent = new JSONObject(service.bodies.get(0));
        assertEquals("тело отметки — ровно объект FM", m.length(), sent.length());
        assertEquals(10, sent.length());
        for (Iterator<String> it = m.keys(); it.hasNext(); ) { String k = it.next(); assertEquals(k, String.valueOf(m.get(k)), String.valueOf(sent.get(k))); }
        assertEquals(1, fm.imports().size());
        assertEquals("{\"format\":\"fm-verdict\",\"sig\":\"x y+z&=\"}", fm.imports().get(0).get("text"));
        assertTrue(fm.notes().isEmpty());
        assertEquals(1, r.answers.size());
        assertEquals("Служба лицензий ответила через этот телефон — работает (14:05)", LicenseRelay.message(r, false, "14:05"));
        assertFalse(LicenseRelay.warning(r));
    }

    @Test public void answerRejectedByFmIsReportedAsRejected() throws Exception {
        FakeFm fm = new FakeFm("admin", URL, mark("L1"));
        fm.importAnswer = new JSONObject().put("status", "error").put("reason", "license_rejected").put("code", "bad_signature");
        LicenseRelay.Result r = LicenseRelay.run(fm, new FakeService());
        assertEquals(1, r.rejected);
        assertEquals(Collections.singletonList(note("L1", "rejected", null)), fm.notes());
        assertEquals("Ответ службы лицензий не принят — лицензии работают как прежде", LicenseRelay.message(r, false, "10:00"));
        assertTrue(LicenseRelay.warning(r));
    }

    @Test public void tooLongAnswerIsNotImported() throws Exception {
        FakeFm fm = new FakeFm("admin", URL, mark("L1"));
        LicenseRelay.Result r = LicenseRelay.run(fm, new FakeService().then(200, null, null));
        assertTrue(fm.imports().isEmpty());
        assertEquals(Collections.singletonList(note("L1", "rejected", null)), fm.notes());
        assertEquals(1, r.rejected);
    }

    @Test public void tooManyRequestsStopsTheLoopAndPassesRetryAfter() throws Exception {
        FakeFm fm = new FakeFm("admin", URL, mark("L1"), mark("L2"), mark("L3"));
        FakeService service = new FakeService().then(429, "120", null);
        LicenseRelay.Result r = LicenseRelay.run(fm, service);
        assertEquals("после 429 остальные не пробуем", 1, service.urls.size());
        assertEquals(Collections.singletonList(note("L1", "429", "120")), fm.notes());
        assertEquals(429, r.waiting);
        assertNull("автоматический круг о «подождите» молчит", LicenseRelay.message(r, false, "10:00"));
        assertEquals("Служба лицензий просит подождать (HTTP 429) — программа попробует ещё раз позже", LicenseRelay.message(r, true, "10:00"));
    }

    @Test public void unavailableStopsTheLoopWithoutRetryAfter() throws Exception {
        FakeFm fm = new FakeFm("admin", URL, mark("L1"), mark("L2"));
        FakeService service = new FakeService().then(503, null, null);
        LicenseRelay.Result r = LicenseRelay.run(fm, service);
        assertEquals(1, service.urls.size());
        assertEquals("без Retry-After поле не передаётся", Collections.singletonList(note("L1", "503", null)), fm.notes());
        assertFalse(fm.notes().get(0).containsKey("relay_retry_after"));
        assertEquals(503, r.waiting);
    }

    @Test public void refusalIsNotedAndTheNextMarkIsTried() throws Exception {
        FakeFm fm = new FakeFm("admin", URL, mark("L1"), mark("L2"));
        fm.importAnswer = FakeFm.verdict("L2", "ok", "");
        FakeService service = new FakeService().then(404, null, null);
        LicenseRelay.Result r = LicenseRelay.run(fm, service);
        assertEquals(2, service.urls.size());
        assertEquals(Collections.singletonList(note("L1", "404", null)), fm.notes());
        assertEquals(Collections.singletonList(404), r.refused);
        assertEquals("Служба лицензий ответила через этот телефон — работает (09:30)\n"
                + "Служба лицензий отказала (HTTP 404) — лицензии работают как прежде", LicenseRelay.message(r, false, "09:30"));
    }

    @Test public void networkFailureIsNotedAndStopsTheLoop() throws Exception {
        FakeFm fm = new FakeFm("admin", URL, mark("L1"), mark("L2"));
        FakeService service = new FakeService().thenNetwork();
        LicenseRelay.Result r = LicenseRelay.run(fm, service);
        assertEquals(1, service.urls.size());
        assertEquals(Collections.singletonList(note("L1", "network", null)), fm.notes());
        assertTrue(r.network);
        assertNull(LicenseRelay.message(r, false, "10:00"));
        assertEquals("У этого телефона нет связи со службой лицензий", LicenseRelay.message(r, true, "10:00"));
    }

    @Test public void unauthorizedFromFmIsNotSwallowed() throws Exception {
        FakeFm fm = new FakeFm("admin", URL, mark("L1"));
        LicenseRelay.Fm strict = new LicenseRelay.Fm() {
            public JSONObject get(String path) { return fm.get(path); }
            public JSONObject postForm(String path, Map<String, String> fields) throws Exception { throw new FmApi.Unauthorized(); }
        };
        try { LicenseRelay.run(strict, new FakeService()); fail(); } catch (FmApi.Unauthorized expected) { }
    }

    @Test public void nothingDueOrNotConfigured() throws Exception {
        FakeFm none = new FakeFm("admin", URL);
        LicenseRelay.Result r = LicenseRelay.run(none, new FakeService());
        assertEquals(LicenseRelay.Kind.NOTHING, r.kind);
        assertEquals("Отмечать нечего: программа отметится сама, когда придёт время", LicenseRelay.message(r, true, "10:00"));
        assertNull("автоматический круг молчит", LicenseRelay.message(r, false, "10:00"));
        FakeFm unconfigured = new FakeFm("admin", null, mark("L1"));
        FakeService service = new FakeService();
        assertEquals(LicenseRelay.Kind.NOTHING, LicenseRelay.run(unconfigured, service).kind);
        assertTrue(service.urls.isEmpty());
        // Отметка больше 4096 байт не отправляется.
        FakeFm huge = new FakeFm("admin", URL, mark("L1").put("proof", "x".repeat(5000)));
        FakeService s2 = new FakeService();
        assertEquals(LicenseRelay.Kind.NOTHING, LicenseRelay.run(huge, s2).kind);
        assertTrue(s2.urls.isEmpty());
    }

    // ── слова итога ────────────────────────────────────────────────────────────────────
    @Test public void stopAndRevokedWords() throws Exception {
        String[][] cases = {
                {"seat_taken", "ключ уже работает на другом компьютере — подтвердите перенос в личном кабинете на сайте 3diwell.com"},
                {"moved", "лицензия перенесена на другой компьютер"},
                {"blocked", "владелец лицензии не подтвердил этот компьютер"},
                {"whatever", "служба лицензий остановила ключ на этом компьютере"}};
        for (String[] c : cases) {
            FakeFm fm = new FakeFm("admin", URL, mark("L1"));
            fm.importAnswer = FakeFm.verdict("L1", "stop", c[0]);
            LicenseRelay.Result r = LicenseRelay.run(fm, new FakeService());
            assertEquals("Служба лицензий ответила через этот телефон — ОСТАНОВЛЕНА: " + c[1], LicenseRelay.message(r, false, "10:00"));
            assertTrue(LicenseRelay.warning(r));
        }
        LicenseRelay.Result r = new LicenseRelay.Result(LicenseRelay.Kind.DONE);
        r.answers.add(new String[]{"ok", ""}); r.answers.add(new String[]{"revoked", "x"});
        assertEquals("Служба лицензий ответила через этот телефон — АННУЛИРОВАНА (1 из 2) — платные функции закрыты", LicenseRelay.message(r, false, "10:00"));
        I18n.setLanguage("en");
        String en = LicenseRelay.message(r, false, "10:00");
        assertEquals("The license service answered via this phone — REVOKED (1 of 2) — paid features are closed", en);
        assertFalse(en.matches("(?s).*[А-Яа-яЁё].*"));
    }

    @Test public void everyResultTextHasEnglish() throws Exception {
        I18n.setLanguage("en");
        List<LicenseRelay.Result> all = new ArrayList<>();
        for (LicenseRelay.Kind k : LicenseRelay.Kind.values()) all.add(new LicenseRelay.Result(k));
        LicenseRelay.Result full = new LicenseRelay.Result(LicenseRelay.Kind.DONE);
        full.answers.add(new String[]{"stop", "seat_taken"}); full.refused.add(410); full.rejected = 1; full.waiting = 503; full.network = true;
        all.add(full);
        for (String reason : new String[]{"seat_taken", "moved", "blocked", "?"}) assertFalse(LicenseRelay.stopWhy(reason).matches("(?s).*[А-Яа-яЁё].*"));
        for (LicenseRelay.Result r : all) for (boolean manual : new boolean[]{true, false}) {
            String text = LicenseRelay.message(r, manual, "10:00");
            if (text != null) assertFalse(text, text.matches("(?s).*[А-Яа-яЁё].*"));
        }
        for (String s : new String[]{"Лицензии модулей", "Лицензии модулей: отметить через этот телефон", "Когда у компьютера фермы нет интернета",
                "Отмечаем лицензии через этот телефон…"})
            assertFalse(s, I18n.t(s).matches("(?s).*[А-Яа-яЁё].*"));
    }

    // ── чтение ответа и форма ──────────────────────────────────────────────────────────
    @Test public void readLimitedStopsAtTheLimit() throws Exception {
        assertArrayEquals(new byte[10], LicenseRelay.readLimited(new ByteArrayInputStream(new byte[10]), 10));
        assertNull(LicenseRelay.readLimited(new ByteArrayInputStream(new byte[11]), 10));
        assertEquals(LicenseRelay.MAX_ANSWER_BYTES, LicenseRelay.readLimited(new ByteArrayInputStream(new byte[LicenseRelay.MAX_ANSWER_BYTES]), LicenseRelay.MAX_ANSWER_BYTES).length);
        assertNull(LicenseRelay.readLimited(new ByteArrayInputStream(new byte[LicenseRelay.MAX_ANSWER_BYTES + 1]), LicenseRelay.MAX_ANSWER_BYTES));
    }

    @Test public void formEncodingMatchesUrlencodedRules() {
        Map<String, String> f = new LinkedHashMap<>();
        f.put("relay_license_id", "L-1"); f.put("relay_status", "429"); f.put("relay_retry_after", "Wed, 21 Oct 2026 07:28:00 GMT"); f.put("skip", null);
        assertEquals("relay_license_id=L-1&relay_status=429&relay_retry_after=Wed%2C+21+Oct+2026+07%3A28%3A00+GMT", FmApi.formEncode(f));
        Map<String, String> t = new LinkedHashMap<>();
        t.put("text", "{\"a\":\"б&c=d+e\"}");
        assertEquals("text=%7B%22a%22%3A%22%D0%B1%26c%3Dd%2Be%22%7D", FmApi.formEncode(t));
        assertEquals("", FmApi.formEncode(null));
    }

    /** callForm на самом деле уходит формой: Content-Type, тело, без JSON. */
    @Test public void callFormSendsUrlencodedBody() throws Exception {
        AtomicReference<String> type = new AtomicReference<>(), body = new AtomicReference<>(), line = new AtomicReference<>();
        try (ServerSocket server = new ServerSocket(0, 4, InetAddress.getByName("127.0.0.1"))) {
            Thread worker = new Thread(() -> {
                try (Socket socket = server.accept()) {
                    socket.setSoTimeout(3000);
                    InputStream in = socket.getInputStream();
                    String head = readHead(in);
                    int length = 0;
                    String[] lines = head.split("\r\n");
                    line.set(lines[0]);
                    for (String l : lines) {
                        if (l.toLowerCase(Locale.ROOT).startsWith("content-type:")) type.set(l.substring(13).trim());
                        if (l.toLowerCase(Locale.ROOT).startsWith("content-length:")) length = Integer.parseInt(l.substring(15).trim());
                    }
                    byte[] b = new byte[length]; int read = 0;
                    while (read < length) { int n = in.read(b, read, length - read); if (n < 0) break; read += n; }
                    body.set(new String(b, 0, read, StandardCharsets.UTF_8));
                    byte[] out = "{\"status\":\"ok\",\"kind\":\"relay_noted\"}".getBytes(StandardCharsets.UTF_8);
                    socket.getOutputStream().write(("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: " + out.length + "\r\n\r\n").getBytes(StandardCharsets.UTF_8));
                    socket.getOutputStream().write(out); socket.getOutputStream().flush();
                } catch (IOException ignored) { }
            });
            worker.setDaemon(true); worker.start();
            FmApi api = new FmApi("http://127.0.0.1:" + server.getLocalPort());
            Map<String, String> f = new LinkedHashMap<>();
            f.put("relay_license_id", "L1"); f.put("relay_status", "network");
            JSONObject answer = api.callForm("/api/licenses/import", f);
            worker.join(3000);
            assertEquals("relay_noted", answer.optString("kind"));
            assertEquals("POST /api/licenses/import HTTP/1.1", line.get());
            assertTrue(type.get(), type.get().startsWith("application/x-www-form-urlencoded"));
            assertEquals("relay_license_id=L1&relay_status=network", body.get());
        }
    }

    private static String readHead(InputStream in) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        int c, state = 0;
        while ((c = in.read()) != -1) {
            out.write(c);
            state = (c == '\r' && (state == 0 || state == 2)) ? state + 1 : (c == '\n' && (state == 1 || state == 3)) ? state + 1 : 0;
            if (state == 4) break;
        }
        return out.toString(StandardCharsets.UTF_8.name());
    }

    private static Map<String, String> note(String id, String status, String retryAfter) {
        Map<String, String> m = new LinkedHashMap<>();
        m.put("relay_license_id", id); m.put("relay_status", status);
        if (retryAfter != null) m.put("relay_retry_after", retryAfter);
        return m;
    }
}
