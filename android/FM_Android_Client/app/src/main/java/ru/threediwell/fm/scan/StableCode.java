// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.scan;

/** Consecutive observations of one stationary code, not a blanket startup delay. */
public final class StableCode {
    public static final long HOLD_MS=700,MAX_GAP_MS=500;
    private String value;
    private AimWindow.Box bounds;
    private long start,last;
    private int count;
    public void reset(){value=null;bounds=null;count=0;}
    public boolean observe(String code,AimWindow.Box box,long now) {
        if(code==null||box==null){reset();return false;}
        if(!code.equals(value)||now<last||now-last>MAX_GAP_MS||bounds==null||bounds.overlap(box)<.55f) {
            value=code;bounds=box;start=last=now;count=1;return false;
        }
        last=now;bounds=box;count++;
        return count>=3&&now-start>=HOLD_MS;
    }
}
