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
import android.os.*;
import android.provider.Settings;
import android.view.View;
import android.widget.*;
import ru.threediwell.fm.ui.FmActivity;
import ru.threediwell.fm.nfc.*;
import ru.threediwell.fm.ui.FmStyle;
import ru.threediwell.fm.ui.OperationFlow;
import ru.threediwell.fm.ui.OperationHintView;
import java.io.IOException;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

/** Experimental foreground read of user-owned Bambu filament tags; no FM dependency. */
public final class BambuReadActivity extends FmActivity {
    private final Handler handler=new Handler(Looper.getMainLooper());
    private final ExecutorService worker=Executors.newSingleThreadExecutor();
    private final ExecutorService closer=Executors.newSingleThreadExecutor();
    private final ScanGate gate=new ScanGate();
    private NfcAdapter adapter;
    private FmStyle style;
    private LinearLayout page;
    private TextView status,resultView;
    private View swatch;
    private Button start,copy,use;
    private String scanResult="";
    private boolean resumed,readerEnabled;
    private boolean forWarehouse,autoBegin;
    private String report="";
    private Integer color;
    private Probe active;
    private static final class Probe {
        final AtomicBoolean cancelled=new AtomicBoolean();
        final AtomicBoolean completed=new AtomicBoolean();
        final AndroidBambuPort port;
        final byte[] uid;
        Probe(MifareClassic tag,byte[] uid){this.port=new AndroidBambuPort(tag);this.uid=uid.clone();}
    }
    @Override public void onCreate(Bundle saved) {
        setTheme(FmStyle.theme(this));super.onCreate(saved);style=new FmStyle(this);
        ScrollView scroll=new ScrollView(this);scroll.setFillViewport(true);scroll.setBackgroundColor(style.bg);
        page=new LinearLayout(this);page.setOrientation(LinearLayout.VERTICAL);page.setPadding(style.dp(20),style.dp(16),style.dp(20),style.dp(24));
        scroll.addView(page);setContentView(scroll);style.systemBars(this,scroll);
        scroll.setOnApplyWindowInsetsListener((v,i)->{v.setPadding(i.getSystemWindowInsetLeft(),i.getSystemWindowInsetTop(),i.getSystemWindowInsetRight(),i.getSystemWindowInsetBottom());return i;});
        forWarehouse=getIntent().getBooleanExtra("warehouse_read",false);autoBegin=forWarehouse&&saved==null;
        text(forWarehouse?I18n.t("FM / NFC КАТУШКИ"):I18n.t("FM / ЭКСПЕРИМЕНТАЛЬНОЕ ЧТЕНИЕ"),12,style.accent);
        TextView title=text(I18n.t("Данные Bambu"),28,style.text);style.icon(title,"nfc",style.accent);
        if(forWarehouse)page.addView(new OperationHintView(this,style,OperationFlow.fromExtra(getIntent().getStringExtra(OperationFlow.EXTRA)),false));
        text(I18n.t("Только для вашей заводской метки филамента Bambu Lab. Запись в метку отключена. Склад и принтер не изменяются; соединение с FM не требуется."),16,style.text);
        text((forWarehouse?I18n.t("Приложите телефон к заводской метке катушки. Чтение запускается автоматически."):I18n.t("Нажмите кнопку, затем приложите телефон к одной катушке."))+I18n.t(" Держите неподвижно до результата. Не используйте банковские карты или пропуска.\n\nПри ошибке обмена выполняется один повтор полного чтения. Неполные данные не используются."),15,style.muted);
        status=text("",16,style.accent);status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        start=button(I18n.t("Прочитать данные Bambu"),true,this::begin);
        button(I18n.t("Остановить"),false,()->{stopAll();status.setText(I18n.t("Чтение остановлено. Нового результата нет. Склад не изменён."));});
        button(I18n.t("Настройки NFC"),false,()->{stopAll();try{startActivity(new Intent(Settings.ACTION_NFC_SETTINGS));}catch(ActivityNotFoundException ex){status.setText(I18n.t("Откройте настройки NFC вручную."));}});
        resultView=text(I18n.t("Здесь появится отчёт чтения или причина отказа. Название производителя по одному UID не определяется."),15,style.text);
        resultView.setTextIsSelectable(true);resultView.setBackground(style.box(style.card,12));resultView.setPadding(style.dp(14),style.dp(14),style.dp(14),style.dp(14));
        text(I18n.t("Образец основного цвета из метки (оттенок на экране может отличаться):"),13,style.muted);
        swatch=new View(this);swatch.setVisibility(View.GONE);page.addView(swatch,new LinearLayout.LayoutParams(-1,style.dp(48)));
        copy=button(I18n.t("Скопировать отчёт"),false,()->{
            if(report.isEmpty())return;ClipboardManager clipboard=(ClipboardManager)getSystemService(CLIPBOARD_SERVICE);
            if(clipboard==null){status.setText(I18n.t("Буфер обмена недоступен. Пришлите скриншот."));return;}
            clipboard.setPrimaryClip(ClipData.newPlainText(I18n.t("Чтение Bambu FM"),report));Toast.makeText(this,I18n.t("Отчёт скопирован"),Toast.LENGTH_LONG).show();
        });copy.setEnabled(false);
        use=button(I18n.t("Использовать прочитанную метку"),true,this::returnReading);use.setVisibility(forWarehouse?View.VISIBLE:View.GONE);use.setEnabled(false);
        button(I18n.t("Назад"),false,this::finish);
        if(saved!=null){report=saved.getString("report","");scanResult=saved.getString("nfc_data","");use.setEnabled(!scanResult.isEmpty());if(saved.containsKey("color"))color=saved.getInt("color");showReport();}
    }
    private TextView text(String value,int size,int color){TextView t=style.label(value,size,color);t.setPadding(0,style.dp(8),0,style.dp(8));t.setLineSpacing(style.dp(3),1);page.addView(t);return t;}
    private Button button(String name,boolean primary,Runnable action){Button b=new Button(this);b.setText(name);style.button(b,primary);page.addView(b);b.setOnClickListener(v->action.run());return b;}
    private boolean available() {
        try {
            NfcManager manager=(NfcManager)getSystemService(NFC_SERVICE);adapter=manager==null?null:manager.getDefaultAdapter();
            if(adapter==null){start.setEnabled(false);status.setText(I18n.t("Встроенный NFC не обнаружен."));return false;}
            if(!adapter.isEnabled()){start.setEnabled(false);status.setText(I18n.t("Включите NFC в настройках и вернитесь сюда."));return false;}
            start.setEnabled(true);return true;
        }catch(RuntimeException ex){start.setEnabled(false);status.setText(I18n.t("Служба NFC недоступна. Повторите позже."));return false;}
    }
    @Override protected void onResume(){super.onResume();resumed=true;if(available()){
        if(autoBegin){autoBegin=false;begin();}
        else status.setText(I18n.t("Готово к чтению. Нажмите кнопку для новой попытки.")+(report.isEmpty()?"":I18n.t(" Ниже предыдущий отчёт.")));
    }}
    private void returnReading(){
        if(!forWarehouse||scanResult.isEmpty())return;
        stopAll();setResult(RESULT_OK,new Intent().putExtra("nfc_data",scanResult));finish();
    }
    private void begin() {
        stopAll();if(!resumed||!available())return;
        report="";color=null;scanResult="";use.setEnabled(false);copy.setEnabled(false);swatch.setVisibility(View.GONE);resultView.setText(I18n.t("Новая попытка: результат ещё не получен."));
        int token=gate.start();start.setEnabled(false);status.setText(I18n.t("Ожидание заводской метки Bambu — до 45 секунд."));
        try {
            adapter.enableReaderMode(this,tag->runOnUiThread(()->discovered(token,tag)),NfcAdapter.FLAG_READER_NFC_A|NfcAdapter.FLAG_READER_SKIP_NDEF_CHECK,null);
            readerEnabled=true;
            handler.postDelayed(()->{if(gate.waiting(token)){stopAll();status.setText(I18n.t("Метка не найдена за 45 секунд. Измените положение телефона и повторите."));}},45000);
        }catch(RuntimeException ex){stopAll();status.setText(I18n.t("Не удалось включить чтение. Проверьте NFC и повторите."));}
    }
    private void discovered(int token,Tag tag) {
        if(!resumed||!gate.accept(token))return;
        handler.removeCallbacksAndMessages(null);
        byte[] uid=tag.getId();String uidText=NfcReport.hex(uid);
        try {
            MifareClassic classic=MifareClassic.get(tag);
            if(classic==null)throw new IllegalArgumentException(I18n.t("MIFARE Classic не доступен для этой пары телефон/метка."));
            if(classic.getSize()!=1024||classic.getSectorCount()!=16||uid==null||uid.length!=4)
                throw new IllegalArgumentException(I18n.t("Тест рассчитан на MIFARE Classic 1K с UID 4 байта. Этот вариант не поддержан."));
            Probe probe=new Probe(classic,uid);active=probe;
            status.setText(I18n.t("Метка обнаружена. Читаем — не убирайте телефон."));
            // Keep Reader Mode enabled during I/O; disabling it here would disconnect the tag.
            handler.postDelayed(()->{if(active==probe){stopAll();report=header(uidText)+I18n.t("Чтение прервано по тайм-ауту (15 секунд). Данные не подтверждены.")+footer();showReport();status.setText(I18n.t("Время чтения истекло. Попробуйте снова."));}},15000);
            worker.execute(()->{
                BambuReader.Result result=BambuReader.readReliable(probe.port,probe.uid,probe.cancelled::get,
                        message->runOnUiThread(()->{if(resumed&&active==probe)status.setText(message);}));
                probe.completed.set(true);
                runOnUiThread(()->{
                    if(!resumed||active!=probe||probe.cancelled.get())return;
                    stopAll();report=header(uidText)+result.details+footer();color=result.data==null?null:result.data.rgbPreview();showReport();
                    if(result.data!=null)try{scanResult=NfcReading.from(result.data).toString();use.setEnabled(true);}catch(org.json.JSONException ex){scanResult="";use.setEnabled(false);}
                    status.setText(result.data==null?I18n.t("Не удалось прочитать всю метку. Уберите телефон, приложите снова к центру метки и повторите. При необходимости используйте QR."):I18n.t("Данные прочитаны. Сверьте с этикеткой."));
                    if(forWarehouse&&!scanResult.isEmpty())returnReading();
                });
            });
        }catch(RuntimeException ex){stopAll();report=header(uidText)+I18n.t("Чтение не выполнено: ")+ex.getMessage()+footer();showReport();status.setText(I18n.t("Эта попытка не дала данных Bambu."));}
    }
    private String header(String uid){return ru.threediwell.fm.nfc.NfcReport.bambuHeader(Build.MANUFACTURER+" "+Build.MODEL,Build.VERSION.RELEASE,Build.VERSION.SDK_INT,uid);}
    private String footer(){return I18n.t("\n\nТолько чтение. Метка не изменена. Запросы к FM не отправлялись; склад не изменён.\nОжидаемые сведения из переписки не использованы для распознавания.");}
    private void showReport(){if(!report.isEmpty()){resultView.setText(report);copy.setEnabled(true);}swatch.setVisibility(color==null?View.GONE:View.VISIBLE);if(color!=null)swatch.setBackground(style.box(color,8));}
    private void stopAll() {
        gate.stop();handler.removeCallbacksAndMessages(null);
        Probe old=active;active=null;
        if(old!=null){old.cancelled.set(true);if(!old.completed.get())closer.execute(()->{try{old.port.close();}catch(IOException ignored){/* close cancels blocked NFC I/O */}});}
        if(readerEnabled&&adapter!=null){try{adapter.disableReaderMode(this);}catch(RuntimeException ignored){/* Service already stopped. */}}
        readerEnabled=false;if(start!=null)start.setEnabled(resumed);
    }
    @Override protected void onPause(){resumed=false;stopAll();super.onPause();}
    @Override protected void onDestroy(){stopAll();worker.shutdownNow();closer.shutdown();super.onDestroy();}
    @Override protected void onSaveInstanceState(Bundle saved){saved.putString("report",report);saved.putString("nfc_data",scanResult);if(color!=null)saved.putInt("color",color);super.onSaveInstanceState(saved);}
}
