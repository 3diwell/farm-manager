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

public class BambuReaderTest {
    static class Port implements BambuReader.Port {
        List<Integer> reads=new ArrayList<>(),auths=new ArrayList<>();Map<Integer,byte[]> blocks=BambuFixture.blocks();
        int failAuth=-1,failRead=-1,closed,connected;boolean lostOnConnect;List<byte[]> keys=new ArrayList<>();
        public void connect() throws IOException {connected++;if(lostOnConnect)throw new IOException("Tag lost");}
        public boolean authenticate(int sector,byte[] key){auths.add(sector);keys.add(key);return sector!=failAuth;}
        public byte[] read(int block) throws IOException {reads.add(block);if(block==failRead)throw new IOException("Tag lost");return blocks.get(block);}
        public void close(){closed++;}
    }
    @Test public void readsOnlyTwoSectorsAndFiveBlocksThenCloses(){Port p=new Port();BambuReader.Result r=BambuReader.read(p,BambuFixture.UID,()->false,x->{});assertNotNull(r.data);assertEquals(Arrays.asList(0,1),p.auths);assertEquals(Arrays.asList(0,1,2,4,5),p.reads);assertEquals(1,p.closed);assertEquals(1,p.connected);}
    @Test public void authFailureDoesNotTryDictionaryOrRead(){Port p=new Port();p.failAuth=0;BambuReader.Result r=BambuReader.read(p,BambuFixture.UID,()->false,x->{});assertNull(r.data);assertEquals(Arrays.asList(0),p.auths);assertTrue(p.reads.isEmpty());assertEquals(1,p.closed);assertTrue(r.details.contains("сектору 0"));}
    @Test public void secondSectorFailureNeverReturnsFirstSectorAsComplete(){Port p=new Port();p.failAuth=1;BambuReader.Result r=BambuReader.read(p,BambuFixture.UID,()->false,x->{});assertNull(r.data);assertEquals(Arrays.asList(0,1,2),p.reads);assertTrue(r.details.contains("НЕ подтверждено"));}
    @Test public void lossDuringReadHasNoSuccess(){Port p=new Port();p.failRead=5;BambuReader.Result r=BambuReader.read(p,BambuFixture.UID,()->false,x->{});assertNull(r.data);assertEquals(1,p.closed);assertFalse(r.details.contains("Прочитано из метки по известному формату"));}
    @Test public void cancelledBeforeConnect(){Port p=new Port();BambuReader.Result r=BambuReader.read(p,BambuFixture.UID,()->true,x->{});assertNull(r.data);assertEquals(0,p.connected);assertTrue(p.auths.isEmpty());assertEquals(1,p.closed);}
    @Test public void cancellationDuringReadStopsNextRead(){AtomicBoolean stop=new AtomicBoolean();Port p=new Port(){@Override public byte[] read(int block) throws IOException {byte[] b=super.read(block);stop.set(true);return b;}};BambuReader.Result r=BambuReader.read(p,BambuFixture.UID,stop::get,x->{});assertNull(r.data);assertEquals(Arrays.asList(0),p.reads);assertEquals(1,p.closed);}
    @Test public void cachedUidMismatchDoesNotSucceed(){Port p=new Port();p.blocks.get(0)[0]=5;assertNull(BambuReader.read(p,BambuFixture.UID,()->false,x->{}).data);assertEquals(1,p.closed);}
    @Test public void keyBuffersAreWiped(){Port p=new Port();BambuReader.read(p,BambuFixture.UID,()->false,x->{});for(byte[] k:p.keys)assertArrayEquals(new byte[6],k);}
    @Test public void connectFailureCloses(){Port p=new Port();p.lostOnConnect=true;assertNull(BambuReader.read(p,BambuFixture.UID,()->false,x->{}).data);assertEquals(1,p.closed);assertTrue(p.auths.isEmpty());}
    @Test public void partialBlockFailsWithoutInventingFields(){Port p=new Port();p.blocks.put(4,new byte[8]);BambuReader.Result r=BambuReader.read(p,BambuFixture.UID,()->false,x->{});assertNull(r.data);assertTrue(r.details.contains("неполный ответ"));}
    @Test public void cancelBeforeAuthenticationDoesNotSendIt(){AtomicBoolean stop=new AtomicBoolean();Port p=new Port();BambuReader.Result r=BambuReader.read(p,BambuFixture.UID,stop::get,x->stop.set(true));assertNull(r.data);assertTrue(p.auths.isEmpty());assertEquals(1,p.closed);}
}
