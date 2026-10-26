// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.farm;
import org.json.JSONObject;

/** Same metric as FM ProjectCell: completed part rows / all part rows. */
public record ProjectProgress(long done,long total,int percent) {
    public static ProjectProgress of(JSONObject project){long total=Math.max(0,project.optLong("parts_count"));long done=Math.max(0,Math.min(total,project.optLong("done_count")));return new ProjectProgress(done,total,total==0?0:(int)Math.round(100.0*done/total));}
}
