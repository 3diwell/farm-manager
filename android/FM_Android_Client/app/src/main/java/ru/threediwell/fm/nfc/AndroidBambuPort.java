// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.nfc;

import ru.threediwell.fm.i18n.I18n;
import android.nfc.tech.MifareClassic;
import java.io.IOException;

/** Only authenticated reads of data blocks; trailer/key/value operations are not exposed. */
public final class AndroidBambuPort implements BambuReader.Port {
    private final MifareClassic tag;
    public AndroidBambuPort(MifareClassic tag){this.tag=tag;}
    @Override public void connect() throws IOException {
        if(tag.getSize()!=1024||tag.getSectorCount()!=16)throw new IOException(I18n.t("Этот тест поддерживает только MIFARE Classic 1K (16 секторов)."));
        tag.connect();tag.setTimeout(2000);
    }
    @Override public boolean authenticate(int sector,byte[] key) throws IOException {
        if(sector!=0&&sector!=1)throw new IOException(I18n.t("Сектор вне области теста"));
        return tag.authenticateSectorWithKeyA(sector,key);
    }
    @Override public byte[] read(int block) throws IOException {
        if(block!=0&&block!=1&&block!=2&&block!=4&&block!=5)throw new IOException(I18n.t("Блок вне области теста"));
        return tag.readBlock(block);
    }
    @Override public void close() throws IOException {tag.close();}
}
