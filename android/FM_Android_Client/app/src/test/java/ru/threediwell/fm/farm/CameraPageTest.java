// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.farm;

import org.junit.Test;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.util.regex.*;
import static org.junit.Assert.*;

public class CameraPageTest {
    @Test public void renderAndExportBothTransportScripts() throws Exception {
        for(String type:new String[]{"bambu","klipper"}){
            String html=CameraPage.render("/api/printer/p1",type,true);
            Matcher script=Pattern.compile("<script[^>]*>([\\s\\S]*?)</script>").matcher(html);assertTrue(script.find());
            assertTrue(html.contains("default-src 'none'"));assertTrue(html.contains("connect-src 'self'"));assertFalse(html.contains("fm_session"));assertFalse(html.contains("192.168"));
            String output=System.getenv("FM_CAMERA_TEST_OUTPUT");if(output!=null){Path folder=Paths.get(output);Files.createDirectories(folder);Files.write(folder.resolve(type+".html"),html.getBytes(StandardCharsets.UTF_8));Files.write(folder.resolve(type+".js"),script.group(1).getBytes(StandardCharsets.UTF_8));Files.write(folder.resolve(type+"-light.html"),CameraPage.render("/api/printer/p1",type,false).getBytes(StandardCharsets.UTF_8));}
        }
    }
    @Test public void onlyKlipperSignalsWebRTCAndNeitherPageCanPrint(){String bambu=CameraPage.render("/api/printer/p1","bambu",false),klipper=CameraPage.render("/api/printer/p1","klipper",false);assertFalse(bambu.contains("RTCPeerConnection"));assertTrue(klipper.contains("credentials:'same-origin'"));assertFalse(klipper.contains("start_print"));assertFalse(klipper.contains("base+'/print'"));assertTrue(bambu.contains("window.stopPlayer"));}
}
