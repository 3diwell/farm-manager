// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.nfc;

import ru.threediwell.fm.i18n.I18n;
import java.io.IOException;
import java.util.*;
import java.util.function.BooleanSupplier;
import java.util.function.Consumer;

/** Bounded read-only protocol. No arbitrary commands, no dictionary/brute-force or write interface. */
public final class BambuReader {
    public interface Port {
        void connect() throws IOException;
        boolean authenticate(int sector,byte[] key) throws IOException;
        byte[] read(int block) throws IOException;
        void close() throws IOException;
    }
    public static final class Result {
        public final BambuData data;
        public final String details;
        public final boolean retryable;
        private Result(BambuData data,String details){this(data,details,false);}
        private Result(BambuData data,String details,boolean retryable){this.data=data;this.details=details;this.retryable=retryable;}
    }
    private static void check(BooleanSupplier cancelled) throws IOException {
        if(cancelled.getAsBoolean()||Thread.currentThread().isInterrupted())throw new IOException(I18n.t("Чтение остановлено."));
    }
    /** One full retry after transport I/O only. Each attempt reconnects and discards all prior blocks. */
    public static Result readReliable(Port port,byte[] uid,BooleanSupplier cancelled,Consumer<String> progress) {
        Result first=read(port,uid,cancelled,progress);
        if(!first.retryable||cancelled.getAsBoolean()||Thread.currentThread().isInterrupted())return first;
        progress.accept(I18n.t("Связь с меткой прервалась. Повтор 2 из 2 — держите телефон неподвижно."));
        Result second=read(port,uid,cancelled,progress);
        return new Result(second.data,I18n.t("Попытка 1 (данные отброшены):\n")+first.details
                +I18n.t("\n\nПовтор полного чтения — попытка 2 из 2:\n")+second.details,false);
    }
    public static Result read(Port port,byte[] uid,BooleanSupplier cancelled,Consumer<String> progress) {
        StringBuilder log=new StringBuilder();Map<Integer,byte[]> blocks=new LinkedHashMap<>();byte[][] keys=null;
        try {
            check(cancelled);keys=BambuKeys.derive(uid);check(cancelled);port.connect();check(cancelled);
            int[][] groups={{0,1,2},{4,5}};
            for(int sector=0;sector<groups.length;sector++) {
                check(cancelled);progress.accept(I18n.t("Доступ к сектору ")+sector+I18n.t("… Держите телефон неподвижно."));
                check(cancelled);
                if(!port.authenticate(sector,keys[sector]))throw new IllegalArgumentException(I18n.t("Доступ к сектору ")+sector+I18n.t(" не получен. Метка может иметь другой формат/ключи либо связь была потеряна."));
                log.append(I18n.t("Сектор ")).append(sector).append(I18n.t(": доступ получен.\n"));
                for(int block:groups[sector]) {
                    check(cancelled);byte[] value=port.read(block);check(cancelled);
                    if(value==null||value.length!=16)throw new IllegalArgumentException(I18n.t("Блок ")+block+I18n.t(": неполный ответ."));
                    blocks.put(block,value.clone());log.append(I18n.t("Блок ")).append(block).append(I18n.t(": прочитано 16 байт.\n"));
                }
            }
            check(cancelled);BambuData data=BambuData.parse(uid,blocks);
            return new Result(data,log+"\n"+data.report());
        }catch(Exception ex) {
            String reason=ex.getMessage();
            if(reason==null||reason.isBlank())reason=I18n.t("Связь прервана или формат метки не поддержан.");
            // Do not expose keys or raw protected blocks in reports/logcat.
            return new Result(null,log+I18n.t("\nЧтение данных НЕ подтверждено: ")+reason
                    +I18n.t("\nМатериал, цвет и диаметр не подставлены. При повторном отказе уберите телефон и повторите по кнопке."),
                    ex instanceof IOException&&!cancelled.getAsBoolean()&&!Thread.currentThread().isInterrupted());
        }finally {
            if(keys!=null)for(byte[] key:keys)Arrays.fill(key,(byte)0);
            for(byte[] block:blocks.values())Arrays.fill(block,(byte)0);
            try{port.close();}catch(IOException|RuntimeException ignored){/* Read-only connection already gone. */}
        }
    }
}
