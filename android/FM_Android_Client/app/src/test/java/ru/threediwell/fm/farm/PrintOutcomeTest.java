// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.farm;

import org.json.*;
import org.junit.*;
import java.util.*;
import ru.threediwell.fm.i18n.I18n;
import static org.junit.Assert.*;

/** Уведомления склада после запуска (`notes`, server.py part_print / _do_project2_file_print) и причины отказа печати. */
public class PrintOutcomeTest {
    @After public void reset(){I18n.setLanguage("ru");}
    private static final String CYRILLIC="(?s).*[А-Яа-яЁё].*";
    private static JSONObject accepted()throws Exception{return new JSONObject().put("status","ok").put("accepted",true).put("job_id","j1");}
    private static JSONObject replaced()throws Exception{return new JSONObject().put("status","advice").put("kind","spool_replaced").put("printer_id","p1").put("printer_name","P2S")
            .put("resolved",new JSONArray().put(new JSONObject().put("material","PETG").put("color_name","Чёрный").put("left_in_stock",2))).put("tight",new JSONArray());}
    private static JSONObject tight()throws Exception{return new JSONObject().put("status","advice").put("kind","filament_tight").put("printer_name","X1C")
            .put("resolved",new JSONArray()).put("tight",new JSONArray().put(new JSONObject().put("material","PLA").put("color_name","Белый")));}
    private static JSONObject unavailable(String reason)throws Exception{return new JSONObject().put("status","advice").put("kind","check_unavailable").put("printer_name","K2")
            .put("module_id","inventory").put("module_name","Складской учёт").put("module_name_en","Inventory").put("reason",reason);}
    @Test public void noNotesKeepsPlainAcceptedMessage()throws Exception{
        assertTrue(PrintOutcome.notes(accepted()).isEmpty());
        assertEquals("FM принял отправку. Ожидаем подтверждение запуска принтером.",PrintOutcome.text(accepted()));
    }
    @Test public void stockNotesAreListedUnderTheAcceptedMessage()throws Exception{
        JSONObject r=accepted().put("notes",new JSONArray().put(replaced()).put(tight()).put(unavailable("timeout")));
        List<String> notes=PrintOutcome.notes(r);
        assertEquals(List.of("P2S: PETG Чёрный закончился — поставлена катушка со склада, осталось 2",
                "X1C: PLA Белый на исходе — катушку скоро менять",
                "K2: модуль «Складской учёт» не ответил вовремя — печать запущена без проверки остатка"),notes);
        String text=PrintOutcome.text(r);assertTrue(text.startsWith("FM принял отправку."));
        for(String note:notes)assertTrue(text.contains("\n• "+note));
    }
    @Test public void moduleCheckReasonsAndEnglishModuleName()throws Exception{
        assertTrue(PrintOutcome.note(unavailable("license")).contains("работает без действующей лицензии"));
        assertTrue(PrintOutcome.note(unavailable("error")).contains("не смог выполнить проверку"));
        I18n.setLanguage("en");String note=PrintOutcome.note(unavailable("timeout"));
        assertEquals("K2: module \"Inventory\" did not answer in time — the print started without the stock check",note);assertFalse(note.matches(CYRILLIC));
    }
    @Test public void missingMaterialAndUnknownNotesStayHonest()throws Exception{
        JSONObject n=new JSONObject().put("kind","spool_replaced").put("printer_id","p9").put("resolved",new JSONArray().put(new JSONObject()));
        assertEquals("p9: материал закончился — поставлена катушка со склада",PrintOutcome.note(n));
        assertEquals("p9: FM прислал уведомление о запуске — подробности в FM",PrintOutcome.note(new JSONObject().put("kind","future_kind").put("printer_id","p9")));
        assertEquals(0,PrintOutcome.notes(accepted().put("notes",new JSONArray().put("text").put(new JSONObject()))).size());
        I18n.setLanguage("en");assertEquals("X1C: PLA Белый is running low — replace the spool soon",PrintOutcome.note(tight()));
    }
    @Test public void notesAreShownEvenWhenStartIsNotConfirmed()throws Exception{
        JSONObject r=new JSONObject().put("status","error").put("reason","send rejected").put("notes",new JSONArray().put(tight()));
        String text=PrintOutcome.text(r);assertTrue(text.startsWith("Запуск не подтверждён. FM не начал отправку файла на принтер."));assertTrue(text.contains("\n• X1C: PLA Белый на исходе"));
    }
    @Test public void englishPrintReasonsAreTranslated()throws Exception{
        Map<String,String> ru=Map.of("file not found","Файл не найден в FM","file missing on disk","Файл есть в списке FM, но отсутствует на диске компьютера FM",
                "printer not found","Принтер не найден в FM","no printer","Принтер не найден в FM","read failed","FM не смог прочитать файл","send rejected","FM не начал отправку файла");
        for(var e:ru.entrySet()){
            I18n.setLanguage("ru");assertTrue(e.getKey(),PrintOutcome.reason(new JSONObject().put("status","error").put("reason",e.getKey())).startsWith(e.getValue()));
            I18n.setLanguage("en");String en=PrintOutcome.message(new JSONObject().put("status","error").put("reason",e.getKey()));assertFalse(en,en.matches(CYRILLIC));assertFalse(en,en.contains(e.getKey()));
        }
    }
    @Test public void conflictCodesAndUnknownReasons()throws Exception{
        assertTrue(PrintOutcome.reason(new JSONObject().put("status","error").put("reason","printer_held")).startsWith("Принтер занят другой задачей FM"));
        assertTrue(PrintOutcome.reason(new JSONObject().put("status","error").put("error","printer_send_busy")).startsWith("На этот принтер уже идёт отправка"));
        assertEquals("Слот AMS пуст",PrintOutcome.reason(new JSONObject().put("status","error").put("reason","Слот AMS пуст")));
        assertEquals("Проверьте результат в FM.",PrintOutcome.reason(new JSONObject().put("status","error")));
        assertEquals("Файл несовместим с принтером. Файл нарезан для X1C",PrintOutcome.reason(new JSONObject().put("status","incompatible").put("reason","Файл нарезан для X1C")));
        assertEquals("Файл несовместим с принтером.",PrintOutcome.reason(new JSONObject().put("status","incompatible")));
    }
}
