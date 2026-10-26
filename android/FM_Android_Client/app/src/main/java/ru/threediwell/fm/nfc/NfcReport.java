// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.nfc;

import ru.threediwell.fm.core.AppVersion;
import ru.threediwell.fm.i18n.I18n;
import java.util.*;

/** Pure diagnostic formatting. UID is not a brand/authenticity or stock identity assertion. */
public final class NfcReport {
    private NfcReport() {}
    /** First lines of the Bambu reading report. */
    public static String bambuHeader(String device,String androidRelease,int sdk,String uid) {
        return AppVersion.reportTitle()+I18n.t(" — чтение Bambu\nТелефон: ")+device+"\nAndroid: "+androidRelease+" (API "+sdk+")\nUID (HEX Android): "+uid+"\n\n";
    }
    public static String hex(byte[] bytes) {
        if(bytes==null||bytes.length==0)return I18n.t("не предоставлен");
        StringBuilder out=new StringBuilder();
        for(byte b:bytes)out.append(String.format(Locale.ROOT,"%02X",b&255));
        return out.toString();
    }
    public static String create(String device,String androidVersion,byte[] uid,String[] technologies,
                                boolean classicAvailable,int size,int sectors,String radioInfo) {
        List<String> tech=technologies==null?Collections.emptyList():Arrays.asList(technologies);
        String support;
        if(classicAvailable) support=I18n.t("MIFARE Classic: доступен для обнаруженной метки на этом телефоне.\n")
                +I18n.t("Память: ")+size+I18n.t(" байт; секторов: ")+sectors+".\n"
                +I18n.t("Можно перейти к отдельному тесту защищённых данных. Успешное чтение этих данных пока НЕ подтверждено.");
        else if(tech.contains("android.nfc.tech.MifareClassic")) support=I18n.t("MIFARE Classic: объявлен системой, но интерфейс недоступен. Повторите проверку.");
        else support=I18n.t("MIFARE Classic: не предоставлен для этой метки. Это может быть другой тип метки или ограничение телефона.\n")
                +I18n.t("По этому результату нельзя объявить весь телефон несовместимым.");
        return AppVersion.reportTitle()+I18n.t(" — проверка NFC\nТелефон: ")+device+"\nAndroid: "+androidVersion
                +I18n.t("\n\nМетка обнаружена\nUID (HEX, порядок байтов Android): ")+hex(uid)
                +I18n.t("\nТехнологии: ")+(tech.isEmpty()?I18n.t("не предоставлены"):String.join(", ",tech))
                +(radioInfo.isEmpty()?"":"\n"+radioInfo)+"\n\n"+support
                +I18n.t("\n\nBambu Lab: производитель не определён по UID. Материал и цвет не считывались; ключи не проверялись.")
                +I18n.t("\nUID не доказывает подлинность или уникальность катушки.")
                +I18n.t("\n\nТолько диагностика. Метка не изменена. Запросы к FM не отправлялись; склад не изменён.");
    }
}
