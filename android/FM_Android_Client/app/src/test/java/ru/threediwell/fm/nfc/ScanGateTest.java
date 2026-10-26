// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.nfc;
import org.junit.Test;
import static org.junit.Assert.*;

public class ScanGateTest {
    @Test public void acceptsOnlyOneTag(){ScanGate g=new ScanGate();int t=g.start();assertTrue(g.accept(t));assertFalse(g.accept(t));}
    @Test public void pauseRejectsQueuedCallback(){ScanGate g=new ScanGate();int t=g.start();g.stop();assertFalse(g.accept(t));}
    @Test public void rescanRejectsOldCallback(){ScanGate g=new ScanGate();int old=g.start(),next=g.start();assertFalse(g.accept(old));assertTrue(g.accept(next));}
    @Test public void timerIsOnlyForActiveSession(){ScanGate g=new ScanGate();int t=g.start();assertTrue(g.waiting(t));g.accept(t);assertFalse(g.waiting(t));}
    @Test public void stoppedSessionDoesNotRearm(){ScanGate g=new ScanGate();int t=g.start();g.stop();assertFalse(g.waiting(t));assertFalse(g.accept(t));int next=g.start();assertTrue(g.waiting(next));}
}
