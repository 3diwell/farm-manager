// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.core;

import org.json.JSONObject;
import org.junit.*;
import java.io.IOException;
import ru.threediwell.fm.i18n.I18n;
import static org.junit.Assert.*;

/** FM "remember_device" protocol 1 (docs/ANDROID_REMEMBER_DEVICE.md) against a stub FM. */
public class RememberDeviceTest {
    private static final String DEVICE_TOKEN="fmd_FIXTURE_device_token";
    private static final String DEVICE_COOKIE="fm_session="+DEVICE_TOKEN+"; Max-Age=315360000; Path=/; HttpOnly; SameSite=Lax";
    private static final String SESSION_COOKIE="fm_session=FIXTURE_session; Max-Age=28800; Path=/; HttpOnly; SameSite=Lax";
    private static final long TEN_YEARS=10L*365*24*60*60*1000;
    private StubFm fm;

    @Before public void setup() throws Exception {fm=new StubFm();}
    @After public void teardown() throws Exception {fm.close();I18n.setLanguage("ru");}

    private static final class MemoryStore implements RememberedLogin.Store {
        SavedSession saved;int clears;
        public SavedSession read(){return saved;}
        public void write(SavedSession value){saved=value;}
        public void clear(){saved=null;clears++;}
    }
    private void statusAnswer(int code,String body){fm.reply("GET /api/auth/status",new StubFm.Reply(code,body));}
    private SavedSession deviceLogin() throws Exception {
        fm.reply("POST /api/auth/login",new StubFm.Reply(200,"{\"ok\":true,\"user\":{\"username\":\"fixture\",\"role\":\"operator\"},"
                +"\"device\":{\"id\":\"dev_fixture\",\"name\":\"Google Pixel 7\",\"persistent\":true}}").header("Set-Cookie",DEVICE_COOKIE));
        FmApi api=new FmApi(fm.origin);
        api.login(LoginRequest.body("fixture","FIXTURE_password",true,"Google Pixel 7"));
        assertTrue(api.loginPersistent());
        return api.exportSession();
    }

    // --- checkbox and request ---

    @Test public void checkboxOffersDeviceOnlyWhenFmAnnouncesProtocol() throws Exception {
        assertEquals(LoginRequest.Mode.DEVICE,LoginRequest.mode(new JSONObject("{\"enabled\":true,\"authenticated\":false,\"remember_device\":1}")));
        assertEquals(LoginRequest.Mode.DEVICE,LoginRequest.mode(new JSONObject("{\"remember_device\":2}")));
        for(String old:new String[]{"{\"enabled\":true,\"authenticated\":false}","{\"remember_device\":0}","{\"remember_device\":\"1\"}","{\"remember_device\":null}"})
            assertEquals(old,LoginRequest.Mode.EIGHT_HOURS,LoginRequest.mode(new JSONObject(old)));
        assertEquals(LoginRequest.Mode.EIGHT_HOURS,LoginRequest.mode(null));
        assertEquals("Запомнить это устройство",LoginRequest.checkboxText(LoginRequest.Mode.DEVICE));
        assertEquals("Вход сохранится, пока вы не выйдете или не отзовёте доступ в FM",LoginRequest.hintText(LoginRequest.Mode.DEVICE));
        assertEquals("Запомнить вход на 8 часов",LoginRequest.checkboxText(LoginRequest.Mode.EIGHT_HOURS));
        assertTrue(LoginRequest.hintText(LoginRequest.Mode.EIGHT_HOURS).startsWith("До 8 часов"));
        I18n.setLanguage("en");
        assertEquals("Remember this device",LoginRequest.checkboxText(LoginRequest.Mode.DEVICE));
    }

    @Test public void loginSendsRememberDeviceAndNameOnlyWhenChosen() throws Exception {
        fm.reply("POST /api/auth/login",new StubFm.Reply(200,"{\"ok\":true}").header("Set-Cookie",SESSION_COOKIE));
        new FmApi(fm.origin).login(LoginRequest.body("fixture","FIXTURE_password",true,"Samsung SM-S918B"));
        JSONObject sent=new JSONObject(fm.last("POST /api/auth/login").body);
        assertEquals(true,sent.get("remember_device"));assertEquals("Samsung SM-S918B",sent.getString("device_name"));
        assertEquals("fixture",sent.getString("username"));
        new FmApi(fm.origin).login(LoginRequest.body("fixture","FIXTURE_password",false,"Samsung SM-S918B"));
        sent=new JSONObject(fm.last("POST /api/auth/login").body);
        assertFalse(sent.has("remember_device"));assertFalse(sent.has("device_name"));
    }

    @Test public void deviceNameIsManufacturerAndModelWithinFmLimit() {
        assertEquals("Samsung SM-S918B",LoginRequest.deviceName("samsung","SM-S918B"));
        assertEquals("Google Pixel 7",LoginRequest.deviceName("Google","Pixel 7"));
        assertEquals("Xiaomi 13",LoginRequest.deviceName("Xiaomi","Xiaomi 13"));
        assertEquals("Pixel",LoginRequest.deviceName(null," Pixel "));
        String longName=LoginRequest.deviceName("Maker","M".repeat(200));
        assertTrue(longName.length()<=LoginRequest.DEVICE_NAME_LIMIT);
        assertFalse(LoginRequest.deviceName("Maker","Model\r\nX-Header: 1").contains("\n"));
    }

    // --- persistent vs 8-hour session ---

    @Test public void persistentDeviceLoginIsNotClampedToEightHours() throws Exception {
        SavedSession saved=deviceLogin();
        assertTrue(saved.persistent);assertEquals(DEVICE_TOKEN,saved.token);assertEquals(0,saved.expiresAt);
        assertTrue(saved.validAt(saved.issuedAt+SavedSession.MAX_AGE_MILLIS+1));
        assertTrue(saved.validAt(saved.issuedAt+TEN_YEARS));
        SavedSession reread=SavedSession.decode(saved.encode());
        assertTrue(reread.persistent);assertEquals(DEVICE_TOKEN,reread.token);
    }

    @Test public void longCookieWithoutPersistentDeviceStaysEightHours() throws Exception {
        // FM without remember_device (or which refused it) still gets the old 8-hour clamp.
        fm.reply("POST /api/auth/login",new StubFm.Reply(200,"{\"ok\":true}").header("Set-Cookie",DEVICE_COOKIE));
        FmApi api=new FmApi(fm.origin);api.login(LoginRequest.body("fixture","FIXTURE_password",false,null));
        SavedSession saved=api.exportSession();
        assertFalse(saved.persistent);assertEquals(SavedSession.MAX_AGE_MILLIS,saved.expiresAt-saved.issuedAt);
        for(String answer:new String[]{"{\"ok\":true,\"device\":null,\"remember_device_error\":\"store_failed\"}",
                "{\"ok\":true,\"device\":{\"persistent\":false}}","{\"ok\":true,\"device\":{\"persistent\":\"true\"}}"}) {
            fm.reply("POST /api/auth/login",new StubFm.Reply(200,answer).header("Set-Cookie",SESSION_COOKIE));
            api=new FmApi(fm.origin);api.login(LoginRequest.body("fixture","FIXTURE_password",true,"Pixel"));
            assertFalse(answer,api.loginPersistent());assertFalse(answer,api.exportSession().persistent);
        }
    }

    @Test public void failedDeviceStoreIsReportedNotTreatedAsRemembered() throws Exception {
        assertTrue(LoginRequest.deviceNotStored(new JSONObject("{\"ok\":true,\"device\":null,\"remember_device_error\":\"store_failed\"}")));
        assertFalse(LoginRequest.deviceNotStored(new JSONObject("{\"ok\":true,\"device\":{\"persistent\":true}}")));
        assertFalse(LoginRequest.deviceNotStored(new JSONObject("{\"ok\":true}")));
        assertFalse(LoginRequest.deviceNotStored(null));
    }

    @Test public void restoredDeviceTokenReachesFmYearsLaterAndIsCheckedByStatus() throws Exception {
        MemoryStore store=new MemoryStore();store.saved=deviceLogin();
        statusAnswer(200,"{\"enabled\":true,\"authenticated\":true,\"user\":{\"username\":\"fixture\",\"role\":\"operator\"},"
                +"\"remember_device\":1,\"device\":{\"id\":\"dev_fixture\",\"name\":\"Google Pixel 7\",\"persistent\":true}}");
        long later=store.saved.issuedAt+TEN_YEARS;
        FmApi restored=new RememberedLogin(store).restore(fm.origin,later);
        assertNotNull(restored);assertNotNull(store.saved);assertEquals(0,store.clears);
        assertTrue(fm.last("GET /api/auth/status").cookie.contains("fm_session="+DEVICE_TOKEN));
        assertFalse(restored.sessionExpired());
        // Phone clock set back before the login does not end a remembered device either.
        assertNotNull(new RememberedLogin(store).restore(fm.origin,store.saved.issuedAt-TEN_YEARS));
    }

    // --- wipe only on authenticated:false ---

    @Test public void revokedDeviceIsForgottenOnlyOnAuthenticatedFalse() throws Exception {
        MemoryStore store=new MemoryStore();store.saved=deviceLogin();
        statusAnswer(200,"{\"enabled\":true,\"authenticated\":false,\"user\":null,\"remember_device\":1}");
        assertNull(new RememberedLogin(store).restore(fm.origin,System.currentTimeMillis()));
        assertNull(store.saved);assertEquals(1,store.clears);
    }

    @Test public void temporaryFailuresKeepTheSavedLogin() throws Exception {
        MemoryStore store=new MemoryStore();SavedSession saved=deviceLogin();store.saved=saved;
        statusAnswer(503,"{\"ok\":false,\"error\":\"temporarily_unavailable\"}");
        fm.replies.get("GET /api/auth/status").header("Retry-After","5");
        try{new RememberedLogin(store).restore(fm.origin,System.currentTimeMillis());fail();}
        catch(FmApi.ServerError ex){assertEquals(503,ex.status);assertEquals(5,ex.retryAfterSeconds);}
        assertSame(saved,store.saved);
        for(int code:new int[]{401,403,500}) {
            statusAnswer(code,"{\"ok\":false,\"error\":\"fixture\"}");
            try{new RememberedLogin(store).restore(fm.origin,System.currentTimeMillis());fail(""+code);}
            catch(FmApi.Unauthorized ex){fail("401 of status must not look like a sign-out");}
            catch(IOException expected){}
            assertSame(""+code,saved,store.saved);
        }
        for(String broken:new String[]{"{}","{\"enabled\":true}","{\"enabled\":true,\"authenticated\":\"false\"}","<html>proxy</html>"}) {
            statusAnswer(200,broken);
            try{new RememberedLogin(store).restore(fm.origin,System.currentTimeMillis());fail(broken);}catch(IOException expected){}
            assertSame(broken,saved,store.saved);
        }
        fm.close();
        try{new RememberedLogin(store).restore(fm.origin,System.currentTimeMillis());fail();}catch(IOException expected){}
        assertSame(saved,store.saved);assertEquals(0,store.clears);
    }

    @Test public void protectionOffKeepsLoginAndOpensFarm() throws Exception {
        MemoryStore store=new MemoryStore();store.saved=deviceLogin();
        statusAnswer(200,"{\"enabled\":false,\"authenticated\":true,\"user\":null,\"remember_device\":1}");
        assertNotNull(new RememberedLogin(store).restore(fm.origin,System.currentTimeMillis()));
        assertNotNull(store.saved);
    }

    @Test public void unauthorizedElsewhereAsksStatusBeforeForgetting() throws Exception {
        SavedSession saved=deviceLogin();FmApi api=new FmApi(fm.origin);api.restoreSession(saved,System.currentTimeMillis());
        fm.reply("GET /api/printers",new StubFm.Reply(401,"{\"ok\":false,\"error\":\"unauthorized\"}"));
        FmApi.Unauthorized original=null;
        try{api.callArray("/api/printers");fail();}catch(FmApi.Unauthorized ex){original=ex;}
        statusAnswer(503,"{\"ok\":false,\"error\":\"temporarily_unavailable\"}");
        assertEquals(AuthCheck.Verdict.UNKNOWN,AuthCheck.ask(api));
        Exception shown=AuthCheck.afterUnauthorized(AuthCheck.ask(api),original);
        assertFalse(shown instanceof FmApi.Unauthorized);assertFalse(shown.getMessage().contains("сохранена"));
        statusAnswer(200,"{\"enabled\":true,\"authenticated\":true}");
        assertEquals(AuthCheck.Verdict.SIGNED_IN,AuthCheck.ask(api));
        assertFalse(AuthCheck.afterUnauthorized(AuthCheck.Verdict.SIGNED_IN,original) instanceof FmApi.Unauthorized);
        statusAnswer(200,"{\"enabled\":true,\"authenticated\":false}");
        assertEquals(AuthCheck.Verdict.SIGNED_OUT,AuthCheck.ask(api));
        assertSame(original,AuthCheck.afterUnauthorized(AuthCheck.Verdict.SIGNED_OUT,original));
        int asked=fm.count("GET /api/auth/status");fm.close();
        assertEquals(AuthCheck.Verdict.UNKNOWN,AuthCheck.ask(api));
        assertEquals(4,asked);
    }

    @Test public void verdictRules() throws Exception {
        assertEquals(AuthCheck.Verdict.SIGNED_IN,AuthCheck.classify(new JSONObject("{\"enabled\":true,\"authenticated\":true}")));
        assertEquals(AuthCheck.Verdict.SIGNED_IN,AuthCheck.classify(new JSONObject("{\"enabled\":false,\"authenticated\":true}")));
        assertEquals(AuthCheck.Verdict.SIGNED_OUT,AuthCheck.classify(new JSONObject("{\"enabled\":true,\"authenticated\":false}")));
        for(String unclear:new String[]{"{}","{\"authenticated\":false}","{\"enabled\":true,\"authenticated\":0}","{\"enabled\":\"true\",\"authenticated\":false}"})
            assertEquals(unclear,AuthCheck.Verdict.UNKNOWN,AuthCheck.classify(new JSONObject(unclear)));
        assertEquals(AuthCheck.Verdict.UNKNOWN,AuthCheck.classify(null));
        assertEquals(AuthCheck.Verdict.UNKNOWN,AuthCheck.ask(()->{throw new FmApi.Unauthorized();}));
        assertEquals(AuthCheck.Verdict.UNKNOWN,AuthCheck.ask(()->{throw new FmApi.ServerError(503,5);}));
        assertEquals(AuthCheck.Verdict.UNKNOWN,AuthCheck.ask(()->{throw new java.net.SocketTimeoutException();}));
        assertEquals(AuthCheck.Verdict.SIGNED_OUT,AuthCheck.ask(()->{throw new FmApi.SessionExpired();}));
        assertTrue(AuthCheck.shouldForget(AuthCheck.Verdict.SIGNED_OUT));
        assertFalse(AuthCheck.shouldForget(AuthCheck.Verdict.UNKNOWN));assertFalse(AuthCheck.shouldForget(AuthCheck.Verdict.SIGNED_IN));
        assertEquals(AuthCheck.Verdict.UNKNOWN,AuthCheck.ask((FmApi)null));
    }

    @Test public void expiredEightHourLoginIsSignedOutWithoutAskingFm() throws Exception {
        long now=System.currentTimeMillis();
        FmApi api=new FmApi(fm.origin);
        api.restoreSession(new SavedSession(fm.origin,"FIXTURE_session",now-2000,now-1000,false),now-1500);
        assertEquals(AuthCheck.Verdict.SIGNED_OUT,AuthCheck.ask(api));
        assertEquals(0,fm.count("GET /api/auth/status"));
        try{api.callArray("/api/printers");fail();}catch(FmApi.SessionExpired expected){}
    }

    // --- login errors ---

    @Test public void wrongPasswordIsPlainAndNeverSaysOperationSaved() throws Exception {
        fm.reply("POST /api/auth/login",new StubFm.Reply(401,"{\"ok\":false,\"error\":\"invalid\"}"));
        try{new FmApi(fm.origin).login(LoginRequest.body("fixture","wrong",false,null));fail();}
        catch(FmApi.Unauthorized ex){fail("login 401 must not be a session loss");}
        catch(LoginRequest.Failed ex){assertEquals(401,ex.status);assertEquals("Неверный логин или пароль",ex.getMessage());}
        I18n.setLanguage("en");
        try{new FmApi(fm.origin).login(LoginRequest.body("fixture","wrong",false,null));fail();}
        catch(LoginRequest.Failed ex){assertEquals("Incorrect username or password",ex.getMessage());}
    }

    @Test public void rateLimitWaitsRetryAfterRoundedUpToMinutes() throws Exception {
        long[][] cases={{1,1},{30,1},{60,1},{61,2},{600,10},{901,16}};
        for(long[] c:cases) {
            fm.reply("POST /api/auth/login",new StubFm.Reply(429,"{\"ok\":false,\"error\":\"auth_rate_limited\"}").header("Retry-After",""+c[0]));
            try{new FmApi(fm.origin).login(LoginRequest.body("fixture","wrong",false,null));fail();}
            catch(LoginRequest.Failed ex){
                assertEquals(429,ex.status);
                assertEquals("Слишком много попыток. Подождите "+c[1]+" мин.",ex.getMessage());
                assertFalse(ex.getMessage().contains("сохранена"));
            }
        }
        fm.reply("POST /api/auth/login",new StubFm.Reply(429,"{\"ok\":false,\"error\":\"auth_rate_limited\"}"));
        try{new FmApi(fm.origin).login(LoginRequest.body("fixture","wrong",false,null));fail();}
        catch(LoginRequest.Failed ex){assertEquals("Слишком много попыток. Подождите несколько минут и повторите вход.",ex.getMessage());}
        I18n.setLanguage("en");
        assertEquals("Too many attempts. Wait 2 min.",LoginRequest.tooManyAttempts(90).getMessage());
    }

    @Test public void otherLoginFailuresPassUnchanged() throws Exception {
        fm.reply("POST /api/auth/login",new StubFm.Reply(500,"{\"ok\":false,\"error\":\"invalid\"}"));
        try{new FmApi(fm.origin).login(LoginRequest.body("fixture","FIXTURE_password",false,null));fail();}
        catch(FmApi.ServerError expected){}
        assertEquals(-1,LoginRequest.retryAfterSeconds(null));assertEquals(-1,LoginRequest.retryAfterSeconds("Wed, 21 Oct 2026 07:28:00 GMT"));
        assertEquals(120,LoginRequest.retryAfterSeconds(" 120 "));
    }
}
