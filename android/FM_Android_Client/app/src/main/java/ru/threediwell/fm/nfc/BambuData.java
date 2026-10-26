// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.nfc;

import ru.threediwell.fm.i18n.I18n;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.*;

/** Decodes only the five explicitly read blocks. No inferred vendor, colour name or stock balance. */
public final class BambuData {
    public final String uid,material,variant,materialId,variantId,rgba;
    public final float diameter;
    public final int weight;
    private BambuData(String uid,String material,String variant,String materialId,String variantId,String rgba,float diameter,int weight) {
        this.uid=uid;this.material=material;this.variant=variant;this.materialId=materialId;this.variantId=variantId;
        this.rgba=rgba;this.diameter=diameter;this.weight=weight;
    }
    public static BambuData parse(byte[] uid,Map<Integer,byte[]> blocks) {
        for(int i:new int[]{0,1,2,4,5})if(blocks.get(i)==null||blocks.get(i).length!=16)throw new IllegalArgumentException(I18n.t("Не все необходимые блоки прочитаны полностью."));
        if(uid==null||uid.length!=4||!Arrays.equals(uid,Arrays.copyOf(blocks.get(0),4)))throw new IllegalArgumentException(I18n.t("UID в блоке 0 не совпадает с обнаруженной меткой. Результат отклонён."));
        byte[] id=blocks.get(1),properties=blocks.get(5);
        String variantId=ascii(id,0,8),materialId=ascii(id,8,8),material=ascii(blocks.get(2),0,16),variant=ascii(blocks.get(4),0,16);
        if(!materialId.matches("GF[A-Za-z0-9_-]{1,6}")||variantId.isEmpty()||material.isEmpty()||variant.isEmpty())
            throw new IllegalArgumentException(I18n.t("Блоки прочитаны, но не соответствуют проверяемому формату Bambu. Автоподстановка отключена."));
        float diameter=ByteBuffer.wrap(properties,8,4).order(ByteOrder.LITTLE_ENDIAN).getFloat();
        int weight=(properties[4]&255)|((properties[5]&255)<<8);
        if(!Float.isFinite(diameter)||diameter<.5f||diameter>5f||weight<=0||weight>10000)
            throw new IllegalArgumentException(I18n.t("Блоки прочитаны, но масса или диаметр вне проверяемого диапазона. Формат требует уточнения."));
        return new BambuData(NfcReport.hex(uid),material,variant,materialId,variantId,
                NfcReport.hex(Arrays.copyOf(properties,4)),diameter,weight);
    }
    private static String ascii(byte[] bytes,int from,int length) {
        StringBuilder text=new StringBuilder();boolean ended=false;
        for(int i=from;i<from+length;i++) {
            int b=bytes[i]&255;
            if(b==0){ended=true;continue;}
            if(b<32||b>126||(ended&&b!=32))throw new IllegalArgumentException(I18n.t("Неизвестное кодирование текстового поля метки; результат не подставлен."));
            text.append((char)b);
        }
        return text.toString().trim();
    }
    public int rgbPreview() {return (int)(0xff000000L|Long.parseLong(rgba.substring(0,6),16));}
    public String report() {
        return I18n.t("Прочитано из метки по известному формату Bambu:\n")
                +I18n.t("Материал: ")+material+I18n.t("\nРазновидность: ")+variant+I18n.t("\nКод материала: ")+materialId+I18n.t("\nКод варианта: ")+variantId
                +I18n.t("\nОсновной цвет RGBA: #")+rgba+I18n.t("\nДиаметр: ")+String.format(Locale.ROOT,"%.3f",diameter)+I18n.t(" мм")
                +I18n.t("\nЗаводская масса: ")+weight+I18n.t(" г (НЕ текущий остаток)")
                +I18n.t("\n\nНазвание цвета не записано в прочитанных полях. Orange не подставляется по ожиданию.")
                +I18n.t("\nДополнительные цвета и RSA-подпись не проверялись; это не проверка подлинности катушки.");
    }
}
