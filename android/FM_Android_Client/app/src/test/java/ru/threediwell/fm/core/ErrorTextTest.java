// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.core;

import org.junit.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import ru.threediwell.fm.i18n.I18n;
import static org.junit.Assert.*;

/** Коды отказов FM, которые раньше показывались как «FM отклонил операцию: код». */
public class ErrorTextTest {
    @After public void reset(){I18n.setLanguage("ru");}
    private static final String CYRILLIC="(?s).*[А-Яа-яЁё].*";
    private static final String[][] CODES={
        {"printer_held","Принтер занят другой задачей FM"},
        {"printer_send_busy","На этот принтер уже идёт отправка файла"},
        {"printer_busy","Принтер печатает, на паузе или готовится к печати"},
        {"invalid_input","FM не принял данные"},
        {"invalid_diameter","Укажите диаметр филамента от 0,5 до 5 мм"},
        {"printer_not_found","Принтер не найден в FM"},
        {"printer_not_idle","Принтер печатает, на паузе или в сбое"},
        {"file not found","Файл не найден в FM"},
        {"file missing on disk","Файл есть в списке FM, но отсутствует на диске"},
        {"printer not found","Принтер не найден в FM"},
        {"no printer","Принтер не найден в FM"},
        {"read failed","FM не смог прочитать файл"},
        {"send rejected","FM не начал отправку файла на принтер"},
        {"spool_unavailable","Катушка недоступна: удалена со склада, помечена пустой или в архиве либо её остаток 0 г"},
    };
    @Test public void everyNewCodeHasItsOwnTextInBothLanguages(){
        for(String[] c:CODES){
            I18n.setLanguage("ru");FmApi.Rejected r=new FmApi.Rejected(c[0]);
            assertEquals(c[0],r.code);assertTrue(c[0]+": "+r.getMessage(),r.getMessage().startsWith(c[1]));assertFalse(r.getMessage().contains("FM отклонил операцию"));
            I18n.setLanguage("en");String en=new FmApi.Rejected(c[0]).getMessage();
            assertFalse(c[0]+": "+en,en.matches(CYRILLIC));assertFalse(en.startsWith("FM rejected"));assertNotEquals(c[0],en);
        }
    }
    @Test public void notIdleIsNotThePendingPrintText(){
        assertNotEquals(new FmApi.Rejected("pending_print").getMessage(),new FmApi.Rejected("printer_not_idle").getMessage());
        assertEquals("Принтер печатает, на паузе или в сбое. Дождитесь окончания печати и повторите.",new FmApi.Rejected("printer_not_idle").getMessage());
        assertTrue(new FmApi.Rejected("pending_print").getMessage().startsWith("Принтер или катушка участвует в печати"));
    }
    @Test public void spoolUnavailableIsSplitWhenFmNamesTheCause(){
        assertTrue(new FmApi.Rejected("spool_unavailable","deleted").getMessage().startsWith("Катушка удалена со склада"));
        for(String d:new String[]{"status","empty","archived"})assertTrue(d,new FmApi.Rejected("spool_unavailable",d).getMessage().startsWith("Катушка помечена в FM как пустая или убрана в архив"));
        assertTrue(new FmApi.Rejected("spool_unavailable","zero_weight").getMessage().startsWith("Остаток катушки в FM — 0 г"));
        String combined=new FmApi.Rejected("spool_unavailable").getMessage();
        assertEquals(combined,new FmApi.Rejected("spool_unavailable","something_new").getMessage());
        assertEquals(combined,new FmApi.Rejected("spool_unavailable",null).getMessage());
        assertEquals("deleted",new FmApi.Rejected("spool_unavailable","deleted").detail);
        I18n.setLanguage("en");
        for(String d:new String[]{"deleted","status","zero_weight",""})assertFalse(new FmApi.Rejected("spool_unavailable",d).getMessage().matches(CYRILLIC));
    }
    @Test public void unknownCodeStillShowsTheCode(){
        assertEquals("FM отклонил операцию: brand_new_code",new FmApi.Rejected("brand_new_code").getMessage());
        assertNull(FmApi.Rejected.text("brand_new_code",""));assertNull(FmApi.Rejected.text(null,""));
        assertTrue(new FmApi.Rejected("slot_occupied").getMessage().startsWith("Позиция уже занята"));
    }
    /** Тот же разбор на настоящем HTTP-ответе FM: 409 c error и detail. */
    @Test public void transportCarriesCodeAndDetailFromConflictResponse() throws Exception {
        try(ServerSocket server=new ServerSocket(0,1,InetAddress.getByName("127.0.0.1"))){
            Thread worker=new Thread(()->{try(Socket s=server.accept()){
                BufferedReader in=new BufferedReader(new InputStreamReader(s.getInputStream(),StandardCharsets.ISO_8859_1));int length=0;
                for(String h;(h=in.readLine())!=null&&!h.isEmpty();)if(h.toLowerCase().startsWith("content-length:"))length=Integer.parseInt(h.substring(15).trim());
                for(int i=0;i<length;i++)in.read();
                byte[] body="{\"ok\":false,\"error\":\"spool_unavailable\",\"detail\":\"zero_weight\"}".getBytes(StandardCharsets.UTF_8);
                OutputStream out=s.getOutputStream();out.write(("HTTP/1.1 409 Conflict\r\nContent-Type: application/json\r\nContent-Length: "+body.length+"\r\n\r\n").getBytes(StandardCharsets.US_ASCII));out.write(body);out.flush();
            }catch(IOException ignored){}});worker.setDaemon(true);worker.start();
            FmApi api=new FmApi("http://127.0.0.1:"+server.getLocalPort());
            try{api.call("POST","/api/mod/inventory/spool/s1/bind",new org.json.JSONObject());fail();}
            catch(FmApi.Rejected r){assertEquals("spool_unavailable",r.code);assertEquals("zero_weight",r.detail);assertTrue(r.getMessage().startsWith("Остаток катушки в FM — 0 г"));}
            worker.join(3000);
        }
    }
}
