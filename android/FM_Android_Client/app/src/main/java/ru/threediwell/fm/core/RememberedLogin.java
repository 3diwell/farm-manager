// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.core;

import ru.threediwell.fm.i18n.I18n;
import org.json.JSONObject;
import java.io.IOException;

/** Server validation is mandatory; transport failures do not destroy a valid local login.
 * The saved login is forgotten only when GET /api/auth/status answers authenticated:false
 * (an 8-hour login also ends by its own deadline). 401 of the status call itself, 503,
 * network errors and timeouts keep it: the caller shows "retry" and asks again later.
 */
public final class RememberedLogin {
    public interface Store {
        SavedSession read() throws Exception;
        void write(SavedSession session) throws Exception;
        void clear() throws Exception;
    }
    private final Store store;
    public RememberedLogin(Store store) { this.store=store; }
    public void forget() throws Exception { store.clear(); }
    public void save(SavedSession session) throws Exception { store.write(session); }

    public FmApi restore(String expectedOrigin, long now) throws Exception {
        SavedSession saved=store.read();
        if(saved==null) return null;
        // validAt is always true for a remembered device: the phone clock never ends it.
        if(!saved.validAt(now) || !saved.origin.equals(new FmApi(expectedOrigin).origin)) {
            store.clear(); return null;
        }
        FmApi api=new FmApi(saved.origin);
        api.restoreSession(saved,now);
        JSONObject result;
        try { result=api.call("GET","/api/auth/status",null); }
        catch(FmApi.Unauthorized ex) {
            // Not an authenticated:false answer: keep the saved login, the user can retry.
            api.clearSession();
            throw new IOException(I18n.t("FM не подтвердил состояние входа. Повторите подключение."));
        }
        catch(Exception ex) { api.clearSession(); throw ex; }
        switch(AuthCheck.classify(result)) {
            case SIGNED_IN: return api;
            case SIGNED_OUT: store.clear(); api.clearSession(); return null;
            default:
                api.clearSession();
                throw new IOException(I18n.t("FM не подтвердил состояние входа. Повторите подключение."));
        }
    }
}
