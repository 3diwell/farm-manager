// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.core;

import ru.threediwell.fm.i18n.I18n;
import android.content.Context;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.AtomicFile;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import java.io.*;
import java.security.KeyStore;
import java.util.Arrays;

/** Call on the network worker. No credentials in preferences, backups, logs or saved UI state. */
public final class EncryptedSessionStore implements RememberedLogin.Store {
    private static final String ALIAS="fm.session.aes.v1";
    private static final Object LOCK=new Object();
    private final AtomicFile file;
    public EncryptedSessionStore(Context context) {
        file=new AtomicFile(new File(context.getNoBackupFilesDir(),"fm_session.enc"));
    }
    private SecretKey key(boolean create) throws Exception {
        KeyStore store=KeyStore.getInstance("AndroidKeyStore");store.load(null);
        if(store.containsAlias(ALIAS)) return (SecretKey)store.getKey(ALIAS,null);
        if(!create) throw new IOException(I18n.t("Ключ сохранённого входа недоступен"));
        KeyGenerator generator=KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(ALIAS,KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256).build());
        return generator.generateKey();
    }
    @Override public SavedSession read() throws Exception {
        synchronized(LOCK) {
            if(!exists()) return null;
            byte[] plain=null;
            try(InputStream input=file.openRead(); ByteArrayOutputStream buffer=new ByteArrayOutputStream()) {
                byte[] block=new byte[2048];int n;
                while((n=input.read(block))!=-1) {
                    if(buffer.size()+n>16384) throw new IOException(I18n.t("Повреждён сохранённый вход"));
                    buffer.write(block,0,n);
                }
                plain=SessionCipher.open(key(false),buffer.toByteArray());
                return SavedSession.decode(plain);
            } catch(Exception ex) {
                clear();
                throw new Unavailable();
            } finally { if(plain!=null) Arrays.fill(plain,(byte)0); }
        }
    }
    @Override public void write(SavedSession session) throws Exception {
        synchronized(LOCK) {
            byte[] plain=session.encode();FileOutputStream output=null;
            try {
                byte[] envelope=SessionCipher.seal(key(true),plain);
                output=file.startWrite();output.write(envelope);file.finishWrite(output);
                output=null;
                if(!Arrays.equals(envelope,file.readFully())) throw new IOException(I18n.t("Сохранение входа не подтверждено"));
            } catch(Exception ex) {
                if(output!=null) file.failWrite(output);
                throw new IOException(I18n.t("Не удалось сохранить вход на телефоне"));
            } finally { Arrays.fill(plain,(byte)0); }
        }
    }
    @Override public void clear() throws IOException {
        synchronized(LOCK) {
            file.delete();
            if(exists()) throw new IOException(I18n.t("Не удалось удалить сохранённый вход с телефона"));
        }
    }
    private boolean exists() {
        File base=file.getBaseFile();
        return base.exists() || new File(base.getPath()+".bak").exists() || new File(base.getPath()+".new").exists();
    }
    public static final class Unavailable extends IOException {
        public Unavailable() { super(I18n.t("Сохранённый вход недоступен. Введите логин и пароль заново.")); }
    }
}
