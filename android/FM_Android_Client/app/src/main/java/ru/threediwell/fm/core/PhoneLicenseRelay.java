// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.core;

import android.content.Context;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import org.json.JSONObject;
import java.io.IOException;
import java.io.OutputStream;
import java.net.URL;
import java.net.URLConnection;
import java.util.Map;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Consumer;
import javax.net.ssl.HttpsURLConnection;

/**
 * Android-часть отметки лицензий через телефон: выбор сети с интернетом и запуск круга LicenseRelay.
 * Ничего из отметок и ответов не пишется в журнал, файлы или Intent.
 */
public final class PhoneLicenseRelay {
    private static final ExecutorService WORKER = Executors.newSingleThreadExecutor(r -> { Thread t = new Thread(r, "fm-license-relay"); t.setDaemon(true); return t; });
    private static final ScheduledExecutorService WATCHDOG = Executors.newSingleThreadScheduledExecutor(r -> { Thread t = new Thread(r, "fm-license-relay-timeout"); t.setDaemon(true); return t; });
    private static final AtomicBoolean RUNNING = new AtomicBoolean();
    /** Переходы между экранами приложения — не новый «вход»: автоматически не чаще раза в минуту. */
    private static final long AUTO_GAP_MS = 60_000;
    private static volatile long lastAuto;
    private static volatile String lastAutoOrigin = "";

    private PhoneLicenseRelay() {}

    /** Автоматический круг при открытии приложения или возврате в него. Молчит, если сказать нечего. */
    public static void auto(Context context, FmApi api, Consumer<LicenseRelay.Result> onUi) {
        if (api == null || api.sessionExpired()) return;
        long now = SystemClock.elapsedRealtime();
        if (api.origin.equals(lastAutoOrigin) && lastAuto != 0 && now - lastAuto < AUTO_GAP_MS) return;
        lastAuto = now; lastAutoOrigin = api.origin;
        Context app = context.getApplicationContext();
        Handler main = new Handler(Looper.getMainLooper());
        WORKER.execute(() -> {
            LicenseRelay.Result result;
            try { result = runNow(app, api); }
            catch (Exception ignored) { return; }   // автоматический круг ошибок не показывает
            LicenseRelay.Result shown = result;
            main.post(() -> onUi.accept(shown));
        });
    }

    /** Круг сейчас — для кнопки; вызывать из фонового потока. */
    public static LicenseRelay.Result runNow(Context context, FmApi api) throws Exception {
        if (!RUNNING.compareAndSet(false, true)) return new LicenseRelay.Result(LicenseRelay.Kind.BUSY);
        try { return LicenseRelay.run(fm(api), new InternetService(context.getApplicationContext())); }
        finally { RUNNING.set(false); }
    }

    /** Итог словами со временем телефона «чч:мм»; null — молчать. */
    public static String message(LicenseRelay.Result result, boolean manual) {
        return LicenseRelay.message(result, manual, new java.text.SimpleDateFormat("HH:mm", java.util.Locale.ROOT).format(new java.util.Date()));
    }

    static LicenseRelay.Fm fm(FmApi api) {
        return new LicenseRelay.Fm() {
            public JSONObject get(String path) throws Exception { return api.call("GET", path, null); }
            public JSONObject postForm(String path, Map<String, String> fields) throws Exception { return api.callForm(path, fields); }
        };
    }

    /** Служба лицензий через сеть с интернетом (Wi-Fi фермы может быть без интернета — тогда мобильная сеть). */
    static final class InternetService implements LicenseRelay.Service {
        private final ConnectivityManager connectivity;
        InternetService(Context context) { connectivity = context.getSystemService(ConnectivityManager.class); }
        private boolean usable(Network network) {
            if (network == null || connectivity == null) return false;
            NetworkCapabilities caps = connectivity.getNetworkCapabilities(network);
            return caps != null && caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                    && caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED);
        }
        private Network pick() {
            if (connectivity == null) return null;
            Network active = connectivity.getActiveNetwork();
            if (usable(active)) return active;
            for (Network n : connectivity.getAllNetworks()) if (usable(n)) return n;
            return null;
        }
        @Override public boolean online() { return pick() != null; }
        @Override public LicenseRelay.Answer post(String url, byte[] body) throws IOException {
            if (!LicenseRelay.allowedServiceUrl(url)) throw new IOException("license service address is not allowed");
            Network network = pick();
            if (network == null) throw new IOException("no internet");
            URLConnection raw = network.openConnection(new URL(url));
            if (!(raw instanceof HttpsURLConnection)) throw new IOException("https required");
            HttpsURLConnection c = (HttpsURLConnection) raw;
            // Служба молчит — не ждём дольше 20 с в сумме (соединение, отправка, ответ).
            ScheduledFuture<?> timeout = WATCHDOG.schedule(c::disconnect, LicenseRelay.TIMEOUT_MS, TimeUnit.MILLISECONDS);
            try {
                c.setInstanceFollowRedirects(false); c.setUseCaches(false);
                c.setConnectTimeout(LicenseRelay.TIMEOUT_MS); c.setReadTimeout(LicenseRelay.TIMEOUT_MS);
                c.setRequestMethod("POST"); c.setDoOutput(true);
                c.setRequestProperty("Content-Type", "application/json");
                c.setRequestProperty("Accept", "application/json");
                c.setFixedLengthStreamingMode(body.length);
                try (OutputStream out = c.getOutputStream()) { out.write(body); }
                int code = c.getResponseCode();
                if (code != 200) return new LicenseRelay.Answer(code, c.getHeaderField("Retry-After"), null);
                return new LicenseRelay.Answer(code, null, LicenseRelay.readLimited(c.getInputStream(), LicenseRelay.MAX_ANSWER_BYTES));
            } catch (RuntimeException ex) {
                throw new IOException("license service connection failed", ex);
            } finally {
                timeout.cancel(false);
                c.disconnect();
            }
        }
    }
}
