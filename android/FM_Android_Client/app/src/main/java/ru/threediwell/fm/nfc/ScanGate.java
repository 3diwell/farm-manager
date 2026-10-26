// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.nfc;

/** Main-thread only. Ignore duplicate or late callbacks from a paused/previous scan. */
public final class ScanGate {
    private int epoch;
    private boolean armed;
    public int start() { armed=true; return ++epoch; }
    public void stop() { armed=false; ++epoch; }
    public boolean waiting(int token) { return armed && epoch==token; }
    public boolean accept(int token) { if(!waiting(token))return false;armed=false;return true; }
}
