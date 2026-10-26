// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.farm;

import org.json.*;
import org.junit.*;
import ru.threediwell.fm.i18n.I18n;
import static org.junit.Assert.*;

public class ReadOnlyNoticeTest {
    @After public void reset(){I18n.setLanguage("ru");}
    private static Capabilities caps(String role,boolean enabled,boolean authenticated)throws Exception{
        JSONObject auth=new JSONObject().put("enabled",enabled).put("authenticated",authenticated).put("user",new JSONObject().put("role",role).put("id","1").put("username","u"));
        return new Capabilities(auth,new JSONArray().put(new JSONObject().put("id","inventory").put("state","loaded")));
    }
    @Test public void assemblerAndObserverSeeWhyButtonsAreMissing()throws Exception{
        for(String role:new String[]{"assembler","observer","storekeeper",""}){
            Capabilities c=caps(role,true,true);assertFalse(c.operate);assertEquals("Только просмотр: нужна роль Оператор или Администратор",c.readOnlyNotice());
        }
        I18n.setLanguage("en");assertEquals("View only: the Operator or Administrator role is required",caps("observer",true,true).readOnlyNotice());
    }
    @Test public void operatingRolesAndSharedFarmHaveNoNotice()throws Exception{
        assertEquals("",caps("admin",true,true).readOnlyNotice());assertEquals("",caps("operator",true,true).readOnlyNotice());
        assertEquals("",caps("observer",false,true).readOnlyNotice());
    }
    @Test public void signedOutUserGetsLoginNotRoleNotice()throws Exception{assertEquals("",caps("observer",true,false).readOnlyNotice());}
}
