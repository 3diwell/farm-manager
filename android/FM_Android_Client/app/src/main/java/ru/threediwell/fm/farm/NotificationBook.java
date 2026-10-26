// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.farm;

import org.json.*;
import java.util.*;

/** Local, account-scoped message history. Reading it never touches a print journal. */
public final class NotificationBook {
    public interface Store {String read();void write(String value);}
    public record Entry(String key,String signature,String title,String message,long time,boolean read){}
    private final Store store;private final List<JSONObject> entries=new ArrayList<>();
    public NotificationBook(Store store){this.store=store;try{JSONArray saved=new JSONArray(store.read());for(int i=0;i<saved.length();i++){JSONObject row=saved.optJSONObject(i);if(row!=null)entries.add(row);}}catch(Exception ignored){}}
    public boolean upsert(String scope,String key,String signature,String title,String message,long time){
        if(scope.isEmpty()||key.isEmpty())return false;
        JSONObject found=null;for(JSONObject row:entries)if(scope.equals(FarmValues.text(row,"scope"))&&key.equals(FarmValues.text(row,"key"))){found=row;break;}
        boolean changed=found==null||!found.optBoolean("present",true)||!signature.equals(FarmValues.text(found,"signature"));
        try{
            if(found==null){found=new JSONObject().put("scope",scope).put("key",key);entries.add(found);}
            if(changed)found.put("time",time).put("read",false);
            boolean bodyChanged=!message.equals(FarmValues.text(found,"message"))||!title.equals(FarmValues.text(found,"title"));
            found.put("signature",signature).put("title",title).put("message",message).put("present",true);
            // Bound each account's history; keep other accounts isolated and capped too.
            entries.sort(Comparator.comparingLong(r->r.optLong("time")));
            List<JSONObject> scoped=new ArrayList<>();for(JSONObject r:entries)if(scope.equals(FarmValues.text(r,"scope")))scoped.add(r);
            while(scoped.size()>100)entries.remove(scoped.remove(0));
            while(entries.size()>500)entries.remove(0);
            if(changed||bodyChanged)save();return changed;
        }catch(JSONException ex){return false;}
    }
    public List<Entry> entries(String scope){List<Entry> out=new ArrayList<>();for(JSONObject r:entries)if(scope.equals(FarmValues.text(r,"scope")))out.add(new Entry(FarmValues.text(r,"key"),FarmValues.text(r,"signature"),FarmValues.text(r,"title"),FarmValues.text(r,"message"),r.optLong("time"),r.optBoolean("read")));out.sort(Comparator.comparingLong(Entry::time).reversed());return out;}
    public int unread(String scope){int count=0;for(Entry e:entries(scope))if(!e.read())count++;return count;}
    public void readAll(String scope){boolean changed=false;for(JSONObject r:entries)if(scope.equals(FarmValues.text(r,"scope"))&&!r.optBoolean("read")){try{r.put("read",true);changed=true;}catch(JSONException ignored){}}if(changed)save();}
    public void markAbsent(String scope,String prefix,Set<String> present){boolean changed=false;for(JSONObject r:entries){String key=FarmValues.text(r,"key");if(scope.equals(FarmValues.text(r,"scope"))&&key.startsWith(prefix)&&!present.contains(key)&&r.optBoolean("present",true)){try{r.put("present",false);changed=true;}catch(JSONException ignored){}}}if(changed)save();}
    private void save(){store.write(new JSONArray(entries).toString());}
}
