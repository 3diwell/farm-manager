// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.farm;

import org.json.JSONObject;

/** Android optString converts JSON null to the literal string "null". */
public final class FarmValues {
    private FarmValues(){}
    public static String text(JSONObject value,String key){return value==null||value.isNull(key)?"":value.optString(key,"");}
    public static double number(JSONObject value,String key){return value==null||value.isNull(key)?Double.NaN:value.optDouble(key,Double.NaN);}
}
