// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.farm;

import org.json.JSONObject;

/** Порог свежести и явный покой по контракту ядра. Не заменяет серверные проверки. */
public final class PrinterState {
    private PrinterState(){}
    public static boolean fresh(JSONObject s,long snapshotAgeMillis){return s!=null&&snapshotAgeMillis<6500&&s.has("seen_ago")&&!s.isNull("seen_ago")&&s.optDouble("seen_ago",Double.POSITIVE_INFINITY)<60&&s.optDouble("seen_ago",-1)>=0&&!"OFFLINE".equals(s.optString("status"));}
    public static boolean ready(JSONObject p,JSONObject s,long age){
        if(!fresh(s,age)||!"IDLE".equals(s.optString("status")))return false;
        String raw=s.optString("status_raw"),type=p.optString("type");
        return switch(type){case "bambu"->"IDLE".equals(raw);case "klipper"->"standby".equals(raw);case "flashforge"->"idle".equals(raw)||"ready".equals(raw);case "demo"->"idle".equals(raw);default->false;};
    }
    /** A completed file's percentage must not look like an active print on an idle printer. */
    public static int progress(JSONObject s,long age){
        if(!fresh(s,age)||!java.util.Arrays.asList("RUNNING","PREPARE","PAUSED","PAUSE","SLICING").contains(s.optString("status"))||!s.has("percent")||s.isNull("percent"))return -1;
        double percent=s.optDouble("percent",Double.NaN);return Double.isFinite(percent)?(int)Math.max(0,Math.min(100,percent)):-1;
    }
}
