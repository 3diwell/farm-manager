// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.nfc;

import org.junit.Test;
import java.io.IOException;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;
import static org.junit.Assert.*;

public class BambuRetryTest {
    static class Port extends BambuReaderTest.Port {
        int failBlock=5;
        @Override public byte[] read(int block) throws IOException {
            if(connected==1&&block==failBlock){reads.add(block);throw new IOException("Transceive failed");}
            return super.read(block);
        }
    }
    @Test public void blockFiveTransportFailureRetriesAllBlocksNotPartialMerge() {
        Port p=new Port();BambuReader.Result result=BambuReader.readReliable(p,BambuFixture.UID,()->false,s->{});
        assertNotNull(result.data);assertEquals(2,p.connected);assertEquals(2,p.closed);
        assertEquals(Arrays.asList(0,1,2,4,5,0,1,2,4,5),p.reads);assertEquals(Arrays.asList(0,1,0,1),p.auths);
        assertTrue(result.details.contains("Transceive failed"));assertTrue(result.details.contains("попытка 2 из 2"));
    }
    @Test public void repeatedFailureStopsAfterTwoAttempts() {
        BambuReaderTest.Port p=new BambuReaderTest.Port();p.failRead=5;
        assertNull(BambuReader.readReliable(p,BambuFixture.UID,()->false,s->{}).data);assertEquals(2,p.connected);assertEquals(2,p.closed);
    }
    @Test public void successfulFirstPassNeverRetries() {
        BambuReaderTest.Port p=new BambuReaderTest.Port();assertNotNull(BambuReader.readReliable(p,BambuFixture.UID,()->false,s->{}).data);assertEquals(1,p.connected);
    }
    @Test public void deniedAuthenticationNotRetried() {
        BambuReaderTest.Port p=new BambuReaderTest.Port();p.failAuth=1;
        assertNull(BambuReader.readReliable(p,BambuFixture.UID,()->false,s->{}).data);assertEquals(1,p.connected);
    }
    @Test public void badFormatNotRetried() {
        BambuReaderTest.Port p=new BambuReaderTest.Port();p.blocks.get(0)[0]^=1;
        assertNull(BambuReader.readReliable(p,BambuFixture.UID,()->false,s->{}).data);assertEquals(1,p.connected);
    }
    @Test public void shortBlockNotRetried() {
        BambuReaderTest.Port p=new BambuReaderTest.Port();p.blocks.put(5,new byte[8]);
        assertNull(BambuReader.readReliable(p,BambuFixture.UID,()->false,s->{}).data);assertEquals(1,p.connected);
    }
    @Test public void cancellationBeforeRetryPreventsReconnect() {
        Port p=new Port();AtomicBoolean stop=new AtomicBoolean();
        BambuReader.Result result=BambuReader.readReliable(p,BambuFixture.UID,stop::get,s->{if(s.contains("Повтор 2"))stop.set(true);});
        assertNull(result.data);assertEquals(1,p.connected);
    }
    @Test public void otherUidOnSecondPassFailsRatherThanMixingTags() {
        Port p=new Port(){@Override public void connect() throws IOException {super.connect();if(connected==2)blocks.get(0)[0]^=1;}};
        assertNull(BambuReader.readReliable(p,BambuFixture.UID,()->false,s->{}).data);assertEquals(2,p.connected);
    }
    @Test public void everyAttemptWipesKeys() {
        Port p=new Port();BambuReader.readReliable(p,BambuFixture.UID,()->false,s->{});for(byte[] key:p.keys)assertArrayEquals(new byte[6],key);
    }
}
