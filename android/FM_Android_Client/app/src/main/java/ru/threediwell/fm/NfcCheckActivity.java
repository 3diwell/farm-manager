// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm;

import ru.threediwell.fm.i18n.I18n;
import android.content.*;
import android.nfc.*;
import android.nfc.tech.MifareClassic;
import android.nfc.tech.NfcA;
import android.os.*;
import android.provider.Settings;
import android.view.View;
import android.widget.*;
import ru.threediwell.fm.ui.FmActivity;
import ru.threediwell.fm.nfc.NfcReport;
import ru.threediwell.fm.nfc.ScanGate;
import ru.threediwell.fm.ui.FmStyle;
import java.util.Locale;

/** Cached discovery metadata ONLY: no connect/auth/readBlock/transceive/write or FM API. */
public final class NfcCheckActivity extends FmActivity {
    private final ScanGate gate=new ScanGate();
    private final Handler handler=new Handler(Looper.getMainLooper());
    private NfcAdapter adapter;
    private FmStyle style;
    private LinearLayout page;
    private TextView status,reportView;
    private Button start,copy;
    private boolean resumed,readerEnabled;
    private String report="";
    @Override public void onCreate(Bundle state) {
        setTheme(FmStyle.theme(this));super.onCreate(state);style=new FmStyle(this);
        ScrollView scroll=new ScrollView(this);scroll.setFillViewport(true);scroll.setBackgroundColor(style.bg);
        page=new LinearLayout(this);page.setOrientation(LinearLayout.VERTICAL);page.setPadding(style.dp(20),style.dp(16),style.dp(20),style.dp(24));
        scroll.addView(page);setContentView(scroll);style.systemBars(this,scroll);
        scroll.setOnApplyWindowInsetsListener((v,i)->{v.setPadding(i.getSystemWindowInsetLeft(),i.getSystemWindowInsetTop(),i.getSystemWindowInsetRight(),i.getSystemWindowInsetBottom());return i;});
        label(I18n.t("FM / ДИАГНОСТИКА"),12,style.accent);
        TextView title=label(I18n.t("Проверка NFC"),28,style.text);style.icon(title,"nfc",style.accent);
        label(I18n.t("Без подключения к FM. Ничего не записывается в метку и не добавляется на склад."),16,style.muted);
        label(I18n.t("1. Разблокируйте телефон и включите NFC.\n2. Нажмите «Начать проверку».\n3. Поднесите заднюю часть телефона к метке одной катушки и медленно перемещайте его. Держите рядом несколько секунд.\n\nЕсли метка не находится, уберите другие метки и металлический чехол, попробуйте другую сторону катушки. Не используйте банковскую карту для этого теста."),16,style.text);
        status=label("",16,style.accent);status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        start=button(I18n.t("Начать проверку"),true,this::begin);
        button(I18n.t("Прочитать данные Bambu"),false,()->{stopReader();startActivity(new Intent(this,BambuReadActivity.class));});
        button(I18n.t("Остановить проверку"),false,()->{stopReader();status.setText(I18n.t("Проверка остановлена. Склад не изменён."));});
        button(I18n.t("Настройки NFC"),false,()->{
            stopReader();
            try {startActivity(new Intent(Settings.ACTION_NFC_SETTINGS));}
            catch(ActivityNotFoundException ex){status.setText(I18n.t("Откройте настройки телефона и найдите NFC вручную."));}
        });
        reportView=label(I18n.t("После считывания здесь появится отчёт. Доступность MIFARE Classic не означает, что данные Bambu уже прочитаны."),15,style.text);
        reportView.setTextIsSelectable(true);reportView.setBackground(style.box(style.card,12));
        reportView.setPadding(style.dp(14),style.dp(14),style.dp(14),style.dp(14));
        copy=button(I18n.t("Скопировать отчёт"),false,()->{
            if(report.isEmpty())return;
            ClipboardManager cb=(ClipboardManager)getSystemService(CLIPBOARD_SERVICE);
            if(cb==null){status.setText(I18n.t("Буфер обмена недоступен. Пришлите скриншот отчёта."));return;}
            cb.setPrimaryClip(ClipData.newPlainText(I18n.t("Проверка NFC FM"),report));
            Toast.makeText(this,I18n.t("Отчёт скопирован. Вставьте его в переписку."),Toast.LENGTH_LONG).show();
        });copy.setEnabled(false);
        button(I18n.t("Назад"),false,this::finish);
        if(state!=null){report=state.getString("report","");showReport();}
    }
    private TextView label(String value,int size,int color) {
        TextView v=style.label(value,size,color);v.setPadding(0,style.dp(8),0,style.dp(8));v.setLineSpacing(style.dp(3),1);page.addView(v);return v;
    }
    private Button button(String caption,boolean primary,Runnable action) {
        Button b=new Button(this);b.setText(caption);style.button(b,primary);page.addView(b);b.setOnClickListener(v->action.run());return b;
    }
    private boolean available() {
        try {
            NfcManager manager=(NfcManager)getSystemService(NFC_SERVICE);
            adapter=manager==null?null:manager.getDefaultAdapter();
            if(adapter==null){start.setEnabled(false);status.setText(I18n.t("Встроенный NFC не обнаружен. Камера и QR продолжают работать."));return false;}
            if(!adapter.isEnabled()){start.setEnabled(false);status.setText(I18n.t("NFC выключен. Включите его в настройках и вернитесь сюда."));return false;}
            start.setEnabled(true);return true;
        }catch(RuntimeException ex){start.setEnabled(false);status.setText(I18n.t("Служба NFC недоступна. Закройте проверку и попробуйте снова."));return false;}
    }
    @Override protected void onResume() {
        super.onResume();resumed=true;
        if(available())status.setText(I18n.t("NFC включён. Нажмите «Начать проверку».")+(report.isEmpty()?"":I18n.t(" Ниже сохранён предыдущий результат.")));
    }
    private void begin() {
        stopReader();if(!resumed||!available())return;
        final int token=gate.start();start.setEnabled(false);
        status.setText(I18n.t("Ожидание метки — до 45 секунд. Поднесите телефон к катушке.")+(report.isEmpty()?"":I18n.t(" Ниже пока предыдущий отчёт.")));
        try {
            // Skip Android's automatic NDEF read: only discovery metadata is needed.
            adapter.enableReaderMode(this,tag->runOnUiThread(()->discovered(token,tag)),
                    NfcAdapter.FLAG_READER_NFC_A|NfcAdapter.FLAG_READER_NFC_B|NfcAdapter.FLAG_READER_NFC_F|
                    NfcAdapter.FLAG_READER_NFC_V|NfcAdapter.FLAG_READER_SKIP_NDEF_CHECK,null);
            readerEnabled=true;
            handler.postDelayed(()->{if(gate.waiting(token)){stopReader();status.setText(I18n.t("За 45 секунд метка не обнаружена. Измените положение телефона и повторите. Это не доказывает несовместимость.") );}},45000);
        }catch(RuntimeException ex){stopReader();status.setText(I18n.t("Не удалось включить считывание. Проверьте NFC в настройках и повторите."));}
    }
    private void discovered(int token,Tag tag) {
        if(!resumed||!gate.accept(token))return;
        stopReader();
        try {
            MifareClassic classic=MifareClassic.get(tag);NfcA a=NfcA.get(tag);
            String radio=a==null?"":"NFC-A: ATQA="+NfcReport.hex(a.getAtqa())+", SAK="+String.format(Locale.ROOT,"%02X",a.getSak()&255);
            report=NfcReport.create(Build.MANUFACTURER+" "+Build.MODEL,Build.VERSION.RELEASE+" (API "+Build.VERSION.SDK_INT+")",
                    tag.getId(),tag.getTechList(),classic!=null,classic==null?0:classic.getSize(),classic==null?0:classic.getSectorCount(),radio);
            showReport();status.setText(I18n.t("Метка обнаружена. Отчёт готов; считывание остановлено."));
            start.setText(I18n.t("Проверить ещё раз"));
        }catch(RuntimeException ex){status.setText(I18n.t("Не удалось получить свойства метки. Уберите катушку и повторите проверку. Предыдущий отчёт, если есть, оставлен ниже."));}
    }
    private void showReport(){if(!report.isEmpty()){reportView.setText(report);copy.setEnabled(true);}}
    private void stopReader() {
        gate.stop();handler.removeCallbacksAndMessages(null);
        if(readerEnabled&&adapter!=null){try{adapter.disableReaderMode(this);}catch(RuntimeException ignored){/* NFC service may have stopped. */}}
        readerEnabled=false;if(start!=null)start.setEnabled(resumed);
    }
    @Override protected void onPause(){resumed=false;stopReader();super.onPause();}
    @Override protected void onDestroy(){stopReader();super.onDestroy();}
    @Override protected void onSaveInstanceState(Bundle state){state.putString("report",report);super.onSaveInstanceState(state);}
}
