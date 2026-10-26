// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.core;

import ru.threediwell.fm.i18n.I18n;
import org.json.JSONObject;
import org.json.JSONArray;
import org.json.JSONTokener;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** Shared FM transport: future printer/project screens use the same authenticated session. */
public final class FmApi {
    public final String origin;
    private final CookieManager cookies = new CookieManager(null, CookiePolicy.ACCEPT_ORIGINAL_SERVER);
    private long loginIssuedAt;
    private boolean loginPersistent;
    private SavedSession deadline;
    public FmApi(String address) {
        URI u = URI.create(address.trim());
        if (!Arrays.asList("http", "https").contains(u.getScheme()) || u.getHost() == null || u.getUserInfo() != null
                || u.getQuery() != null || u.getFragment() != null || !(u.getPath().isEmpty() || u.getPath().equals("/")))
            throw new IllegalArgumentException(I18n.t("Укажите адрес FM, например http://192.168.1.10:8000 — без пути и пароля"));
        origin = u.getScheme() + "://" + u.getRawAuthority();
    }
    public synchronized JSONObject call(String method, String path, JSONObject body) throws Exception {
        Object value=request(method,path,body);
        if(value instanceof JSONObject) return (JSONObject)value;
        throw new IOException(I18n.t("FM вернул неожиданный формат данных."));
    }
    public synchronized JSONArray callArray(String path) throws Exception {
        Object value=request("GET",path,null);
        if(value instanceof JSONArray) return (JSONArray)value;
        throw new IOException(I18n.t("FM вернул неожиданный формат данных."));
    }
    /** Актуальный список модулей обёрнут в {modules:[...], restart_needed:...}. */
    public synchronized JSONArray callArray(String path,String member) throws Exception {
        Object value=request("GET",path,null);
        if(value instanceof JSONArray)return (JSONArray)value;
        if(value instanceof JSONObject){JSONArray rows=((JSONObject)value).optJSONArray(member);if(rows!=null)return rows;}
        throw new IOException(I18n.t("FM вернул неожиданный формат данных."));
    }
    /** POST формой application/x-www-form-urlencoded — как FormData страницы FM для маршрутов с полями Form. */
    public synchronized JSONObject callForm(String path, Map<String,String> fields) throws Exception {
        Object value=request("POST",path,formEncode(fields).getBytes(StandardCharsets.UTF_8),"application/x-www-form-urlencoded; charset=utf-8");
        if(value instanceof JSONObject) return (JSONObject)value;
        throw new IOException(I18n.t("FM вернул неожиданный формат данных."));
    }
    /** Поля формы в порядке добавления; поле со значением null не передаётся. */
    public static String formEncode(Map<String,String> fields) {
        StringBuilder out=new StringBuilder();
        if(fields!=null) for(Map.Entry<String,String> e:fields.entrySet()) {
            if(e.getKey()==null||e.getValue()==null) continue;
            if(out.length()>0) out.append('&');
            out.append(URLEncoder.encode(e.getKey(),StandardCharsets.UTF_8)).append('=').append(URLEncoder.encode(e.getValue(),StandardCharsets.UTF_8));
        }
        return out.toString();
    }
    private Object request(String method, String path, JSONObject body) throws Exception {
        return request(method,path,body==null?null:body.toString().getBytes(StandardCharsets.UTF_8),"application/json; charset=utf-8");
    }
    private Object request(String method, String path, byte[] body, String contentType) throws Exception {
        if(deadline!=null && !deadline.validAt(System.currentTimeMillis())) throw new SessionExpired();
        long startedAt=System.currentTimeMillis();
        if (!path.startsWith("/api/") && !path.equals("/version")) throw new IOException(I18n.t("Недопустимый путь"));
        URI uri = URI.create(origin + path);
        HttpURLConnection c = (HttpURLConnection) uri.toURL().openConnection();
        c.setConnectTimeout(8000); c.setReadTimeout(15000); c.setInstanceFollowRedirects(false);
        c.setRequestMethod(method); c.setRequestProperty("Accept", "application/json");
        for (var header : cookies.get(uri, Collections.emptyMap()).entrySet()) {
            String value = String.join("; ", header.getValue());
            if (!value.isEmpty()) c.setRequestProperty(header.getKey(), value);
        }
        try {
            if (body != null) {
                c.setDoOutput(true); c.setRequestProperty("Content-Type", contentType);
                byte[] bytes = body;
                c.setFixedLengthStreamingMode(bytes.length);
                try (OutputStream out = c.getOutputStream()) { out.write(bytes); }
            }
            int status = c.getResponseCode();
            cookies.put(uri, c.getHeaderFields());
            if (status == 401) throw new Unauthorized();
            long retryAfter=LoginRequest.retryAfterSeconds(c.getHeaderField("Retry-After"));
            if (status == 403) throw new IOException(I18n.t("У пользователя нет права на эту операцию в FM."));
            if (status >= 300 && status < 400) throw new IOException(I18n.t("FM вернул перенаправление. Проверьте адрес подключения."));
            InputStream stream = status < 400 ? c.getInputStream() : c.getErrorStream();
            if (stream == null) throw new IOException("FM: HTTP " + status);
            String raw;
            try (stream; ByteArrayOutputStream buffer = new ByteArrayOutputStream()) {
                byte[] block = new byte[8192]; int n;
                while ((n = stream.read(block)) != -1) {
                    if (buffer.size() + n > 16 * 1024 * 1024) throw new IOException(I18n.t("Ответ FM слишком велик"));
                    buffer.write(block, 0, n);
                }
                raw = buffer.toString(StandardCharsets.UTF_8.name());
            }
            Object value;
            try { value = new JSONTokener(raw).nextValue(); if(!(value instanceof JSONObject)&&!(value instanceof JSONArray))throw new IOException(); }
            catch (Exception ex) { throw new IOException(I18n.t("FM вернул не JSON. Проверьте адрес и наличие модуля склада.")); }
            JSONObject result=value instanceof JSONObject?(JSONObject)value:new JSONObject();
            if (status >= 500) throw new ServerError(status, result.optString("reason", result.optString("error", "")), retryAfter);
            if (status >= 400 || (result.has("ok") && !result.optBoolean("ok")))
                throw new Rejected(result.optString("error", result.optString("reason", "HTTP " + status)), result.isNull("detail") ? "" : result.optString("detail", ""), status, retryAfter);
            if(method.equals("POST") && path.equals("/api/auth/login")) {
                loginIssuedAt=startedAt;loginPersistent=LoginRequest.persistent(result);
            }
            return value;
        } finally { c.disconnect(); }
    }
    /** Только тот же сервер. Используется независимыми каналами медиа и телеметрии. */
    public synchronized Map<String,List<String>> sessionHeaders(String path) throws IOException {
        if(sessionExpired()) throw new SessionExpired();
        URI uri=mediaUri(path);
        return new HashMap<>(cookies.get(uri,Collections.emptyMap()));
    }
    public synchronized String browserSessionCookie() throws IOException {
        if(sessionExpired())throw new SessionExpired();
        for(HttpCookie cookie:cookies.getCookieStore().get(URI.create(origin+"/")))
            if("fm_session".equals(cookie.getName())&&!cookie.hasExpired())return "fm_session="+cookie.getValue()+"; Path=/; HttpOnly; SameSite=Lax"+(cookie.getSecure()?"; Secure":"");
        return "fm_session=; Path=/; Max-Age=0";
    }
    private URI mediaUri(String path) throws IOException {
        if(path==null || !(path.equals("/ws")||path.startsWith("/api/")||path.startsWith("/covers/"))
                || path.contains("\\") || path.contains("..") || path.contains("#"))throw new IOException(I18n.t("Недопустимый путь"));
        URI uri=URI.create(origin+path);
        if(!uri.getRawAuthority().equals(URI.create(origin).getRawAuthority()))throw new IOException(I18n.t("Недопустимый путь"));
        return uri;
    }
    public Media openMedia(String path) throws IOException {
        URI uri=mediaUri(path);
        HttpURLConnection connection=(HttpURLConnection)uri.toURL().openConnection();
        connection.setConnectTimeout(8000);connection.setReadTimeout(15000);connection.setInstanceFollowRedirects(false);
        try {
            for(var h:sessionHeaders(path).entrySet())connection.setRequestProperty(h.getKey(),String.join("; ",h.getValue()));
            int status=connection.getResponseCode();
            if(status==401)throw new Unauthorized();
            if(status!=200)throw new IOException(I18n.t("Не удалось открыть изображение или камеру. HTTP ")+status);
            return new Media(connection,connection.getInputStream(),connection.getContentType());
        }catch(IOException|RuntimeException ex){connection.disconnect();throw ex;}
    }
    public static final class Media implements AutoCloseable {
        private final HttpURLConnection connection;
        public final InputStream input;public final String type;
        private Media(HttpURLConnection c,InputStream i,String t){connection=c;input=i;type=t==null?"":t;}
        @Override public void close(){try{input.close();}catch(IOException ignored){}finally{connection.disconnect();}}
    }
    /** POST /api/auth/login with errors the user can act on: wrong password, wait N minutes. */
    public synchronized JSONObject login(JSONObject body) throws Exception {
        try { return call("POST","/api/auth/login",body); }
        catch(Exception ex) { throw LoginRequest.failure(ex); }
    }
    /** The last login answered device.persistent == true. */
    public synchronized boolean loginPersistent() { return loginIssuedAt>0 && loginPersistent; }
    public synchronized SavedSession exportSession() throws IOException {
        if(deadline!=null) return deadline;
        if(loginIssuedAt<=0) throw new IOException(I18n.t("FM не выдал сеанс для сохранения"));
        for(HttpCookie cookie:cookies.getCookieStore().get(URI.create(origin+"/"))) {
            if(!cookie.getName().equals("fm_session") || cookie.hasExpired() || !"/".equals(cookie.getPath())) continue;
            long seconds=cookie.getMaxAge();
            if(seconds<=0) continue; // Never invent a lifetime for an unbounded session cookie.
            try {
                if(loginPersistent) {
                    // Remembered device: no 8-hour clamp; FM status decides at every start.
                    deadline=SavedSession.persistent(origin,cookie.getValue(),loginIssuedAt,cookie.getSecure());
                    return deadline;
                }
                deadline=new SavedSession(origin,cookie.getValue(),loginIssuedAt,
                        loginIssuedAt+Math.min(seconds,28800L)*1000L,cookie.getSecure());
                return deadline;
            } catch(IllegalArgumentException ex) { throw new IOException(I18n.t("FM выдал неподдерживаемый сеанс")); }
        }
        throw new IOException(I18n.t("FM не выдал сеанс с известным сроком действия"));
    }
    public synchronized void restoreSession(SavedSession session,long now) throws IOException {
        if(!origin.equals(session.origin) || !session.validAt(now)) throw new Unauthorized();
        clearSession();
        HttpCookie cookie=new HttpCookie("fm_session",session.token);
        cookie.setPath("/");cookie.setVersion(0);cookie.setHttpOnly(true);cookie.setSecure(session.secure);
        cookie.setMaxAge(session.persistent?SavedSession.PERSISTENT_COOKIE_SECONDS:Math.max(1,(session.expiresAt-now)/1000));
        cookies.getCookieStore().add(URI.create(origin+"/"),cookie);deadline=session;
    }
    public synchronized boolean sessionExpired() { return deadline!=null && !deadline.validAt(System.currentTimeMillis()); }
    public synchronized void clearSession() { cookies.getCookieStore().removeAll();deadline=null;loginIssuedAt=0;loginPersistent=false; }
    public static class Unauthorized extends IOException {
        public Unauthorized() { super(I18n.t("Нужен вход в FM. Выполните вход повторно; незавершённая операция сохранена.")); }
    }
    /** The 8-hour login passed its own deadline on this phone: no request was sent. */
    public static final class SessionExpired extends Unauthorized {}
    /** 5xx: результат неизвестен (не отказ). code — причина из ответа FM, например command_not_delivered;
     *  retryAfterSeconds = -1, если FM не сказал, когда повторить. */
    public static final class ServerError extends IOException {
        public final int status; public final String code; public final long retryAfterSeconds;
        public ServerError(int status, long retryAfterSeconds) { this(status, "", retryAfterSeconds); }
        public ServerError(int status, String code) { this(status, code, -1); }
        public ServerError(int status, String code, long retryAfterSeconds) {
            super(I18n.t("Ошибка сервера FM. Результат неизвестен — повторите сохранённую операцию."));
            this.status = status; this.code = code == null ? "" : code; this.retryAfterSeconds = retryAfterSeconds;
        }
    }
    public static final class Rejected extends IOException {
        public final String code, detail;
        public final int status;
        public final long retryAfterSeconds;
        public Rejected(String code) { this(code, "", 0, -1); }
        /** detail — уточнение причины, если FM его прислал (поле "detail" ответа); иначе пусто. */
        public Rejected(String code, String detail) { this(code, detail, 0, -1); }
        public Rejected(String code, int status, long retryAfterSeconds) { this(code, "", status, retryAfterSeconds); }
        public Rejected(String code, String detail, int status, long retryAfterSeconds) {
            super(message(code, detail)); this.code = code; this.detail = detail == null ? "" : detail;
            this.status = status; this.retryAfterSeconds = retryAfterSeconds;
        }
        private static String message(String code, String detail) {
            String known = text(code, detail);
            return known != null ? known : I18n.t("FM отклонил операцию: ") + code;
        }
        /** Понятный текст известного кода или причины отказа FM; null — код незнаком (вызывающий решает, что показать). */
        public static String text(String code, String detail) {
            if (code == null) return null;
            return switch (code) {
                case "spool_unavailable" -> spoolUnavailable(detail);
                case "printer_not_idle" -> I18n.t("Принтер печатает, на паузе или в сбое. Дождитесь окончания печати и повторите.");
                case "printer_busy" -> I18n.t("Принтер печатает, на паузе или готовится к печати. Новая печать не отправлена.");
                case "printer_held" -> I18n.t("Принтер занят другой задачей FM (например, детали проектного плана на столе). Печать не отправлена; освободите принтер в FM.");
                case "printer_send_busy" -> I18n.t("На этот принтер уже идёт отправка файла. Дождитесь её окончания в FM и повторите.");
                case "invalid_input" -> I18n.t("FM не принял данные: поле пустое или слишком длинное. Проверьте введённые значения.");
                case "invalid_diameter" -> I18n.t("Укажите диаметр филамента от 0,5 до 5 мм (обычно 1,75).");
                case "printer_not_found", "printer not found", "no printer" -> I18n.t("Принтер не найден в FM: его удалили или переименовали. Обновите данные.");
                case "file not found" -> I18n.t("Файл не найден в FM: его удалили или переместили. Обновите список файлов.");
                case "file missing on disk" -> I18n.t("Файл есть в списке FM, но отсутствует на диске компьютера FM. Загрузите его в FM заново.");
                case "read failed" -> I18n.t("FM не смог прочитать файл с диска. Проверьте файл на компьютере FM.");
                case "send rejected" -> I18n.t("FM не начал отправку файла на принтер. Проверьте принтер и отправки в FM.");
                default -> table(code);
            };
        }
        private static String spoolUnavailable(String detail) {
            return switch (detail == null ? "" : detail) {
                case "deleted", "spool_deleted" -> I18n.t("Катушка удалена со склада. Обновите данные склада.");
                case "status", "empty", "archived", "spool_status" -> I18n.t("Катушка помечена в FM как пустая или убрана в архив. Обновите данные склада.");
                case "zero_weight", "no_weight", "weight" -> I18n.t("Остаток катушки в FM — 0 г. Исправьте остаток в FM или выберите другую катушку.");
                default -> I18n.t("Катушка недоступна: удалена со склада, помечена пустой или в архиве либо её остаток 0 г. Обновите данные склада.");
            };
        }
        private static String table(String code) {
            return switch (code) {
                case "invalid_nfc_uid" -> I18n.t("Некорректный UID NFC. Повторите чтение метки.");
                case "invalid_nfc_color" -> I18n.t("Укажите основной цвет нового материала в виде #FF671F.");
                case "nfc_identifier_conflict" -> I18n.t("NFC уже связан с другой катушкой или конфликтует с кодом товара. Перенос и объединение не выполнены.");
                case "nfc_spool_changed" -> I18n.t("Материал карточки изменился. Обновите данные и заново подтвердите связь NFC.");
                case "spool_not_found" -> I18n.t("Катушка удалена или не найдена. Связь NFC не создана.");
                case "slot_occupied" -> I18n.t("Позиция уже занята. Сначала освободите её в FM; катушка не заменена.");
                case "invalid_label_quantity" -> I18n.t("Укажите целое количество этикеток от 1 до 500.");
                case "invalid_weight" -> I18n.t("Укажите положительную массу филамента, не более 100000 г.");
                case "invalid_prepared_label", "prepared_label_not_found" -> I18n.t("Подготовленная этикетка не найдена в FM. Обычный QR уже принятой катушки не создаёт новый приход.");
                case "prepared_label_wrong_batch" -> I18n.t("QR относится к другой партии. Выберите нужную партию перед приёмкой.");
                case "prepared_label_cancelled" -> I18n.t("Этикетка отменена. Катушка не принята; используйте действующую метку.");
                case "prepared_material_changed" -> I18n.t("Характеристики материала изменились после подготовки QR. Проверьте каталог; неверные ожидающие метки отмените и подготовьте заново.");
                case "prepared_batch_not_found" -> I18n.t("Партия этикеток не найдена. Обновите данные FM.");
                case "invalid_label_selection" -> I18n.t("Неверный список этикеток для отмены. Обновите данные.");
                case "label_id_conflict" -> I18n.t("Номер этикетки уже занят. Операция отменена без изменения остатков.");
                case "location_not_found" -> I18n.t("Место хранения удалено или не найдено. Выберите действующую полку.");
                case "filament_not_found" -> I18n.t("Материал удалён или не найден. Этикетка не принята; проверьте каталог FM.");
                case "binding_changed" -> I18n.t("Содержимое позиции изменилось после подтверждения. Ничего не изменено. Обновите данные и повторите выбор.");
                case "replacement_spool_changed" -> I18n.t("Данные новой катушки изменились. Замена не выполнена. Проверьте катушки заново.");
                case "invalid_replace_writeoff" -> I18n.t("Не удалось подтвердить замену со списанием. Выберите слот и катушки заново.");
                case "writeoff_spool_changed" -> I18n.t("Остаток, материал или привязка катушки изменились. Списание не выполнено. Обновите данные и проверьте катушку заново.");
                case "invalid_writeoff_confirmation", "invalid_writeoff_weight" -> I18n.t("Не удалось подтвердить списание пустой катушки. Обновите данные и повторите выбор.");
                case "slot_ambiguous" -> I18n.t("На одну позицию записано несколько катушек. Сначала исправьте привязки в FM.");
                case "replacement_invalid" -> I18n.t("Для замены нужны две разные катушки и занятая позиция. Обновите данные.");
                case "unsupported_mobile_protocol", "unsupported_mobile_operation" -> I18n.t("Модуль склада не поддерживает эту операцию. Для NFC требуется расширение 0.7, для подготовленных этикеток — 0.4, для снятия/замены — 0.2 или новее.");
                case "pending_data_invalid" -> I18n.t("Не удалось проверить незавершённые печати. Снятие и замена заблокированы; проверьте склад в FM.");
                case "pending_print" ->I18n.t("Принтер или катушка участвует в печати. Операция заблокирована.");
                case "printer_offline_or_stale", "slot_not_found", "legacy_external_ambiguous" -> I18n.t("Позиция не подтверждена свежими данными принтера. Проверьте подключение в FM.");
                case "spool_bound_elsewhere" -> I18n.t("Катушка уже установлена в другой позиции. Сначала отвяжите её в FM.");
                case "spool_already_received", "existing_spool_tag" -> I18n.t("Эта индивидуальная метка уже есть на складе. Повторная приёмка запрещена.");
                case "product_mapping_conflict", "code_kind_conflict" -> I18n.t("Код уже связан с другим товаром или типом метки. Проверьте выбор.");
                case "wrong_server" -> I18n.t("Метка или операция принадлежит другому складу FM.");
                case "request_id_reused" -> I18n.t("Обнаружено изменение уже отправленной операции. Повтор заблокирован.");
                case "invalid" -> I18n.t("Неверный логин или пароль.");
                case "auth_rate_limited" -> I18n.t("Слишком много попыток. Подождите несколько минут и повторите вход.");
                default -> null;
            };
        }
    }
}
