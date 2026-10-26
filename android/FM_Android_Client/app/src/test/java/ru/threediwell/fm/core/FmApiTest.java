// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.core;

import java.io.*;
import org.json.JSONObject;
import org.junit.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicReference;
import static org.junit.Assert.*;

public class FmApiTest {
    private ServerSocket server;
    private Thread worker;
    private FmApi api;
    private volatile int status=200;
    private volatile String response="{\"ok\":true}";
    private volatile String setCookie="fm_session=example; Max-Age=28800; Path=/; HttpOnly; SameSite=Lax";
    private final AtomicReference<String> cookie=new AtomicReference<>();
    @Before public void setup() throws Exception {
        server=new ServerSocket(0,8,InetAddress.getByName("127.0.0.1"));
        worker=new Thread(() -> {
            while(!server.isClosed()) try(Socket socket=server.accept()) {
                socket.setSoTimeout(3000);
                BufferedReader in=new BufferedReader(new InputStreamReader(socket.getInputStream(),StandardCharsets.UTF_8));
                String line=in.readLine(); int length=0; cookie.set(null);
                while((line=in.readLine())!=null && !line.isEmpty()) {
                    if(line.toLowerCase().startsWith("cookie:")) cookie.set(line.substring(7).trim());
                    if(line.toLowerCase().startsWith("content-length:")) length=Integer.parseInt(line.substring(15).trim());
                }
                for(int i=0;i<length;i++) in.read();
                byte[] body=response.getBytes(StandardCharsets.UTF_8);
                String head="HTTP/1.1 "+status+" Test\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: "+body.length
                        +"\r\n"+(setCookie==null?"":"Set-Cookie: "+setCookie+"\r\n")+"Location: http://127.0.0.1:1/api/stolen\r\n\r\n";
                socket.getOutputStream().write(head.getBytes(StandardCharsets.UTF_8)); socket.getOutputStream().write(body); socket.getOutputStream().flush();
            } catch(IOException ignored) { }
        }); worker.setDaemon(true);worker.start();
        api=new FmApi("http://127.0.0.1:"+server.getLocalPort());
    }
    @After public void teardown() throws Exception {server.close();worker.join(3000);}
    @Test public void cookiesRetainedInMemoryAndCleared() throws Exception {
        api.call("GET","/api/test",null); assertNull(cookie.get());
        api.call("GET","/api/test",null); assertTrue(cookie.get().replace("\"", "").contains("fm_session=example"));
        api.clearSession(); api.call("GET","/api/test",null); assertNull(cookie.get());
    }
    @Test public void sessionsNotSharedAcrossApiInstances() throws Exception {
        api.call("GET","/api/test",null);
        new FmApi(api.origin).call("GET","/api/test",null); assertNull(cookie.get());
    }
    @Test public void serverFailureIsUncertainNotRejection() {
        status=500; response="{\"ok\":false,\"error\":\"internal\"}";
        try {api.call("POST","/api/test",new JSONObject());fail();}
        catch(Exception e){assertFalse(e instanceof FmApi.Rejected);}
    }
    @Test public void conflictIsExplicitRejection() {
        status=409;response="{\"ok\":false,\"error\":\"slot_occupied\"}";
        try {api.call("POST","/api/test",new JSONObject());fail();}
        catch(Exception e){assertTrue(e instanceof FmApi.Rejected);}
    }
    @Test public void redirectNeverFollowed() {
        status=302;
        try {api.call("POST","/api/test",new JSONObject());fail();}
        catch(Exception e){assertTrue(e.getMessage().contains("перенаправление"));}
    }
    @Test public void loginExpiryDoesNotClearPendingAsRejection() {
        status=401;
        try {api.call("POST","/api/test",new JSONObject());fail();}
        catch(Exception e){assertFalse(e instanceof FmApi.Rejected);}
    }
    @Test public void malformedSuccessIsUncertain() {
        response="<html>proxy error</html>";
        try {api.call("POST","/api/test",new JSONObject());fail();}
        catch(Exception e){assertFalse(e instanceof FmApi.Rejected);}
    }
    @Test(expected=IllegalArgumentException.class) public void embeddedPasswordRejected(){new FmApi("http://name:password@example.test");}
    @Test(expected=IllegalArgumentException.class) public void fileSchemeRejected(){new FmApi("file:///etc/file");}
    @Test(expected=IllegalArgumentException.class) public void basePathRejected(){new FmApi("http://example.test/api");}

    private SavedSession login() throws Exception {
        api.call("POST","/api/auth/login",new JSONObject());return api.exportSession();
    }
    @Test public void exportedCookieRestoresIntoFreshClient() throws Exception {
        SavedSession saved=login();setCookie=null;
        FmApi fresh=new FmApi(api.origin);fresh.restoreSession(saved,System.currentTimeMillis());
        fresh.call("GET","/api/auth/status",null);
        assertTrue(cookie.get().contains("fm_session=example"));assertEquals(saved.expiresAt,fresh.exportSession().expiresAt);
    }
    @Test public void serverCanShortenButNotExtendEightHourDeadline() throws Exception {
        setCookie="fm_session=example; Max-Age=999999; Path=/; HttpOnly";
        SavedSession capped=login();assertEquals(SavedSession.MAX_AGE_MILLIS,capped.expiresAt-capped.issuedAt);
        api.clearSession();setCookie="fm_session=example; Max-Age=60; Path=/; HttpOnly";
        SavedSession shortSession=login();assertEquals(60000,shortSession.expiresAt-shortSession.issuedAt);
    }
    @Test public void unboundedCookieNotPersisted() throws Exception {
        setCookie="fm_session=example; Path=/; HttpOnly";
        try {login();fail();}catch(IOException expected){}
    }
    @Test public void expiredOrUnrelatedCookiesNotPersisted() throws Exception {
        for(String header:new String[]{"fm_session=example; Max-Age=0; Path=/", "other=example; Max-Age=28800; Path=/",
                "fm_session=example; Max-Age=28800; Path=/; Domain=other.test", "fm_session=example; Max-Age=28800; Path=/other"}) {
            api.clearSession();setCookie=header;
            try {login();fail(header);}catch(IOException expected){}
        }
    }
    @Test public void restoredCookieCannotCrossOriginPortOrScheme() throws Exception {
        SavedSession saved=login();
        for(String target:new String[]{"http://localhost:"+server.getLocalPort(),"http://127.0.0.1:1",api.origin.replace("http:","https:")}) {
            try {new FmApi(target).restoreSession(saved,System.currentTimeMillis());fail();}catch(FmApi.Unauthorized expected){}
        }
    }
    @Test public void expiredCookieRejectedBeforeNetworkRequest() throws Exception {
        long now=System.currentTimeMillis();
        SavedSession expired=new SavedSession(api.origin,"example",now-2000,now-1000,false);
        api.restoreSession(expired,now-1500);
        try {api.call("POST","/api/test",new JSONObject());fail();}catch(FmApi.Unauthorized expected){}
        assertNull(cookie.get());
    }
    private static class MemoryStore implements RememberedLogin.Store {
        SavedSession saved;
        int writes;
        public SavedSession read(){return saved;}
        public void write(SavedSession value){saved=value;writes++;}
        public void clear(){saved=null;}
    }
    private MemoryStore remembered() throws Exception {MemoryStore store=new MemoryStore();store.saved=login();setCookie=null;return store;}
    @Test public void restoreRequiresServerAuthenticationAndDoesNotRewriteDeadline() throws Exception {
        MemoryStore store=remembered();long deadline=store.saved.expiresAt;
        response="{\"enabled\":true,\"authenticated\":true}";
        FmApi restored=new RememberedLogin(store).restore(api.origin,System.currentTimeMillis());
        assertNotNull(restored);assertTrue(cookie.get().contains("fm_session=example"));assertEquals(0,store.writes);assertEquals(deadline,store.saved.expiresAt);
    }
    @Test public void revokedSessionAndServerRestartForgetLogin() throws Exception {
        MemoryStore store=remembered();response="{\"enabled\":true,\"authenticated\":false}";
        assertNull(new RememberedLogin(store).restore(api.origin,System.currentTimeMillis()));assertNull(store.saved);
    }
    @Test public void onlyAuthenticatedFalseForgetsNotAnHttpErrorOfStatus() throws Exception {
        // docs/ANDROID_REMEMBER_DEVICE.md item 4: 401/403/5xx of status are no proof of revocation.
        MemoryStore store=remembered();SavedSession original=store.saved;
        for(int code:new int[]{401,403,500,503}) {
            status=code;
            try {new RememberedLogin(store).restore(api.origin,System.currentTimeMillis());fail();}
            catch(FmApi.Unauthorized ex){fail("status "+code+" must not look like a sign-out");}
            catch(IOException expected){}
            assertSame(original,store.saved);
        }
        status=200;response="{\"enabled\":true,\"authenticated\":false}";
        assertNull(new RememberedLogin(store).restore(api.origin,System.currentTimeMillis()));assertNull(store.saved);
    }
    @Test public void malformedAuthResponseDoesNotGrantAccessOrForgetLogin() throws Exception {
        MemoryStore store=remembered();
        for(String invalid:new String[]{"{}","<html>proxy</html>","{\"enabled\":true,\"authenticated\":\"true\"}"}) {
            response=invalid;
            try {new RememberedLogin(store).restore(api.origin,System.currentTimeMillis());fail();}catch(IOException expected){}
            assertNotNull(store.saved);
        }
    }
    @Test public void connectionFailureRetainsLoginAndOfflineLogoutClearsIt() throws Exception {
        MemoryStore store=remembered();server.close();worker.join(3000);
        RememberedLogin login=new RememberedLogin(store);
        try {login.restore(api.origin,System.currentTimeMillis());fail();}catch(IOException expected){}
        assertNotNull(store.saved);login.forget();assertNull(store.saved);
    }
    @Test public void expiredOrWrongOriginRecordNeverReachesServer() throws Exception {
        MemoryStore store=remembered();SavedSession saved=store.saved;cookie.set(null);
        assertNull(new RememberedLogin(store).restore(api.origin,saved.expiresAt));assertNull(cookie.get());assertNull(store.saved);
        store.saved=saved;
        assertNull(new RememberedLogin(store).restore("http://other.test",System.currentTimeMillis()));assertNull(cookie.get());assertNull(store.saved);
    }
    @Test public void noSavedSessionDoesNotUseNetwork() throws Exception {
        assertNull(new RememberedLogin(new MemoryStore()).restore(api.origin,System.currentTimeMillis()));assertNull(cookie.get());
    }
}
