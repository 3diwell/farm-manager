// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.farm;

import org.json.*;
import java.util.*;

/** Возможности текущего сервера. Неизвестный или незагруженный модуль недоступен. */
public final class Capabilities {
    public final boolean authenticated, operate, inventory,modulesKnown;
    /** Администратор FM при включённой защите: только ему FM отдаёт лицензии и отметки. */
    public final boolean admin;
    public final String role,accountKey;
    private final Set<String> availableModules;
    public Capabilities(JSONObject auth,JSONArray modules){
        this(auth,modules,true);
    }
    public Capabilities(JSONObject auth,JSONArray modules,boolean modulesKnown){
        this.modulesKnown=modulesKnown;
        authenticated=auth.optBoolean("authenticated",false);
        JSONObject user=auth.optJSONObject("user");role=user==null?"":user.optString("role");
        accountKey=!authenticated?"":!auth.optBoolean("enabled",true)?"shared":FarmValues.text(user,"id")+"/"+FarmValues.text(user,"username");
        admin=ru.threediwell.fm.core.LicenseRelay.isAdmin(auth);
        operate=authenticated&&(!auth.optBoolean("enabled",true)||Arrays.asList("admin","operator").contains(role));
        Set<String> available=new HashSet<>();
        for(int i=0;i<modules.length();i++){
            JSONObject m=modules.optJSONObject(i);if(m==null||m.optString("id").isEmpty())continue;
            if(modulesKnown&&!m.optBoolean("disabled")&&"loaded".equals(m.optString("state")))available.add(m.optString("id"));
        }
        availableModules=Collections.unmodifiableSet(available);
        inventory=moduleAvailable("inventory");
    }
    /** Пояснение вместо молча скрытых кнопок: у Сборщика, Наблюдателя и любой другой роли без управления — только просмотр. */
    public String readOnlyNotice(){return authenticated&&!operate?ru.threediwell.fm.i18n.I18n.t("Только просмотр: нужна роль Оператор или Администратор"):"";}
    public boolean moduleAvailable(String id){return authenticated&&availableModules.contains(id);}
    public boolean sameAvailability(Capabilities other){return other!=null&&authenticated==other.authenticated&&accountKey.equals(other.accountKey)&&operate==other.operate&&admin==other.admin&&modulesKnown==other.modulesKnown&&availableModules.equals(other.availableModules);}
}
