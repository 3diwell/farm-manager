// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm;

import android.app.AlertDialog;
import android.content.*;
import android.graphics.*;
import android.os.*;
import android.text.TextUtils;
import android.view.*;
import android.widget.*;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import ru.threediwell.fm.core.*;
import ru.threediwell.fm.farm.*;
import ru.threediwell.fm.i18n.I18n;
import ru.threediwell.fm.ui.*;
import ru.threediwell.fm.scan.ScanPolicy;
import org.json.*;
import java.io.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Consumer;

/** Самостоятельные экраны ядра. Склад открывается отдельно через прежний клиент. */
public final class FarmActivity extends FmActivity {
    private FmApi api;private FarmRepository repo;private FmStyle style;
    private LinearLayout page,root,content;private TextView connection,notice;
    private ScrollView scroll;private String renderedRoute="";
    private SharedPreferences prefs;private PrintJournal journal;private NotificationBook notifications;
    private NotificationButton notificationButton;private MaterialSlotsView materialSlots;private String alertScope="",previousRoute="printers";private long noticeUntil;private String noticeText="";
    private final Map<String,TextView> notificationRows=new HashMap<>();private boolean notificationRenderPending;
    private final ExecutorService network=Executors.newSingleThreadExecutor(),images=Executors.newFixedThreadPool(2);
    private final Handler handler=new Handler(Looper.getMainLooper());private TelemetryClient telemetry;
    private boolean active,busy,polling,connected;private volatile long receivedAt;private long lastSlowRefresh;
    private volatile JSONObject states=new JSONObject();private JSONObject filament=new JSONObject(),badges=new JSONObject(),sends=new JSONObject(),tree=new JSONObject();private volatile long sendsAt;
    private JSONArray printers=new JSONArray(),projects=new JSONArray(),tasks=new JSONArray();
    private String route="printers",selectedPrinter="",selectedProject="",projectName="";
    private final Map<String,PrinterTile> liveTiles=new HashMap<>();private TextView detailLive;
    private LinearLayout printerRows;private final List<String> printerOrder=new ArrayList<>();private long lastInteraction;
    private PreheatPresets preheatPresets;private boolean presetsFailed;
    private ImageButton pauseButton,stopButton;private TextView controlStatus;
    private ImageButton repeatButton;private TextView repeatStatus;private String labelServer="",pendingPrinterQr="";
    private ActivityResultLauncher<Intent> printerScan;
    private final List<Button> heatButtons=new ArrayList<>();private Button coolButton;private TextView coolNote;
    private volatile int revision;private int streamGeneration;
    private int dp(int n){return style.dp(n);}
    private boolean canPrint(){return repo.capabilities!=null&&repo.capabilities.operate;}
    private boolean hasInventory(){return repo.capabilities!=null&&repo.capabilities.inventory;}
    @Override public void onCreate(Bundle state){
        setTheme(FmStyle.theme(this));super.onCreate(state);api=SessionRegistry.get();if(api==null){finish();return;}
        repo=new FarmRepository(api);style=new FmStyle(this);prefs=getSharedPreferences("fm-client",MODE_PRIVATE);
        journal=new PrintJournal(new PrintJournal.Store(){public String read(){return prefs.getString("farm_print_journal","");}public boolean write(String value){return prefs.edit().putString("farm_print_journal",value).commit();}public boolean clear(){return prefs.edit().remove("farm_print_journal").commit();}});
        notifications=new NotificationBook(new NotificationBook.Store(){public String read(){return prefs.getString("farm_notifications_v1","[]");}public void write(String value){prefs.edit().putString("farm_notifications_v1",value).apply();}});
        printerScan=registerForActivityResult(new ActivityResultContracts.StartActivityForResult(),result->{
            if(result.getResultCode()==RESULT_OK&&result.getData()!=null){String code=result.getData().getStringExtra("code");if(code!=null){pendingPrinterQr=code;if(active&&!busy)openScannedPrinter();}}
        });
        if(state!=null){route=state.getString("farm_route","printers");selectedPrinter=state.getString("farm_printer","");selectedProject=state.getString("farm_project","");projectName=state.getString("farm_project_name","");}
        if(state!=null){pendingPrinterQr=state.getString("farm_printer_qr","");previousRoute=state.getString("farm_previous_route","printers");}
        render();
        getOnBackPressedDispatcher().addCallback(this,new androidx.activity.OnBackPressedCallback(true){@Override public void handleOnBackPressed(){if(busy)return;if(route.equals("alerts")){route=previousRoute;render();loadRoute();}else if(route.equals("printer")){route="printers";render();loadRoute();}else if(route.equals("project")){route="projects";render();}else if(!route.equals("printers")){route="printers";render();loadRoute();}else finish();}});
    }
    private TextView label(LinearLayout parent,String value,int size,int color){TextView v=style.label(value,size,color);v.setPadding(0,dp(4),0,dp(4));if(size>=20){v.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));v.setPadding(0,dp(14),0,dp(8));}parent.addView(v);return v;}
    private void showNotice(String value){
        noticeText=value;noticeUntil=SystemClock.elapsedRealtime()+6000;
        if(!value.isEmpty()&&!value.equals(I18n.t("Загрузка…"))){String key="notice:"+value,signature=value;for(var row:notifications.entries(notificationScope()))if(row.key().equals(key)){signature=System.currentTimeMillis()-row.time()<30000?row.signature():value+"\n"+System.currentTimeMillis();break;}recordNotification(key,signature,I18n.t("Сообщение FM"),value);}
        if(notificationButton!=null)notificationButton.update(notifications.unread(notificationScope()),journal.pending(api.origin));
        refreshNotice();handler.removeCallbacks(expireNotice);if(!value.isEmpty())handler.postDelayed(expireNotice,6000);
    }
    private final Runnable expireNotice=()->{if(!busy){noticeText="";refreshNotice();}};
    private void refreshNotice(){if(notice==null)return;String value=busy?I18n.t("Загрузка…"):SystemClock.elapsedRealtime()<noticeUntil?noticeText:"";notice.setText(value);notice.setVisibility(value.isEmpty()?View.GONE:View.VISIBLE);}
    private String notificationScope(){Capabilities caps=repo.capabilities;if(caps!=null&&caps.authenticated)alertScope=api.origin+"\n"+caps.accountKey;return alertScope;}
    private boolean recordNotification(String key,String signature,String title,String message){return notifications.upsert(notificationScope(),key,signature,title,message,System.currentTimeMillis());}
    private void openNotifications(){if(busy)return;if(!route.equals("alerts")){previousRoute=route;route="alerts";}render();}
    private boolean captureNotifications(){
        if(busy||polling||repo.capabilities==null||!repo.capabilities.authenticated)return false;
        boolean changed=false;
        for(JSONObject send:FarmRepository.rows(sends.optJSONArray("jobs"))){
            String id=FarmValues.text(send,"job_id"),status=FarmValues.text(send,"state"),error=FarmValues.text(send,"error");if(id.isEmpty())continue;
            String title=FarmValues.text(send,"printer_name")+" · "+FarmValues.text(send,"file_name");String message=sendState(status);
            if(!send.isNull("progress")&&send.has("progress"))message+=" · "+send.optInt("progress")+"%";if(!error.isEmpty())message+="\n"+error;
            changed|=recordNotification("send:"+id,status+"\n"+error,title,message);
        }
        for(JSONObject printer:FarmRepository.rows(printers)){
            String id=printer.optString("id");JSONObject live=state(id);if(!PrinterState.fresh(live,age()))continue;
            Set<String> present=new HashSet<>();String prefix="printer:"+id+":";for(JSONObject message:FarmRepository.rows(live.optJSONArray("hms"))){JSONObject localized=message.optJSONObject("text");String text=localized==null?FarmValues.text(message,"text"):FarmValues.text(localized,I18n.language());if(text.isEmpty())text=localized==null?FarmValues.text(message,"code"):FarmValues.text(localized,"ru");if(text.isEmpty())continue;String key=FarmValues.text(message,"code");if(key.isEmpty())key="text:"+text;key=prefix+key;present.add(key);changed|=recordNotification(key,text,printer.optString("name"),text);}
            notifications.markAbsent(notificationScope(),prefix,present);
        }
        return changed;
    }
    private void notificationScreen(){
        LinearLayout header=new LinearLayout(this);header.setGravity(Gravity.CENTER_VERTICAL);content.addView(header);
        header.addView(style.iconButton(I18n.t("Назад"),"back",()->{if(!busy){route=previousRoute;render();loadRoute();}}));TextView title=label(header,I18n.t("Оповещения"),22,style.text);title.setLayoutParams(new LinearLayout.LayoutParams(0,-2,1));
        if(journal.pending(api.origin))sendPanel();
        List<NotificationBook.Entry> rows=notifications.entries(notificationScope());if(rows.isEmpty())label(content,I18n.t("Оповещений пока нет."),15,style.muted);
        for(var entry:rows){LinearLayout c=card();label(c,entry.title(),15,style.text);TextView message=label(c,entry.message(),14,style.muted);notificationRows.put(entry.key(),message);String date=java.text.DateFormat.getDateTimeInstance(java.text.DateFormat.SHORT,java.text.DateFormat.SHORT,Locale.forLanguageTag(I18n.language())).format(new Date(entry.time()));label(c,date,12,style.muted);}
        notifications.readAll(notificationScope());
    }
    private Button button(LinearLayout parent,String text,boolean primary,Runnable action){Button b=new Button(this);b.setText(text);style.button(b,primary);b.setOnClickListener(v->{if(!busy)action.run();});parent.addView(b);return b;}
    private LinearLayout card(){LinearLayout c=new LinearLayout(this);c.setOrientation(LinearLayout.VERTICAL);c.setPadding(dp(14),dp(12),dp(14),dp(12));c.setBackground(style.box(style.card,16));LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,-2);p.setMargins(0,dp(6),0,dp(6));content.addView(c,p);return c;}
    private void action(String title,String subtitle,String icon,Runnable runnable){LinearLayout c=style.compactAction(title,subtitle,icon);c.setOnClickListener(v->{if(!busy)runnable.run();});content.addView(c);}
    private void render(){
        if(isDestroyed())return;int scrollY=scroll!=null&&route.equals(renderedRoute)?scroll.getScrollY():0;renderedRoute=route;revision++;liveTiles.clear();printerRows=null;printerOrder.clear();detailLive=null;coolButton=null;coolNote=null;pauseButton=null;stopButton=null;controlStatus=null;repeatButton=null;repeatStatus=null;heatButtons.clear();materialSlots=null;notificationRows.clear();captureNotifications();
        root=new LinearLayout(this);root.setOrientation(LinearLayout.VERTICAL);root.setBackgroundColor(style.bg);
        scroll=new ScrollView(this);scroll.setFillViewport(true);page=new LinearLayout(this);page.setOrientation(LinearLayout.VERTICAL);page.setPadding(dp(12),dp(8),dp(12),dp(16));scroll.addView(page);root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));setContentView(root);style.systemBars(this,root);
        scroll.setOnScrollChangeListener((View.OnScrollChangeListener)(v,x,y,oldX,oldY)->{if(y!=oldY)lastInteraction=SystemClock.elapsedRealtime();});
        root.setOnApplyWindowInsetsListener((v,i)->{v.setPadding(i.getSystemWindowInsetLeft(),i.getSystemWindowInsetTop(),i.getSystemWindowInsetRight(),i.getSystemWindowInsetBottom());return i;});
        ConnectionRow connectionRow=new ConnectionRow(this,style,this::loadRoute);connection=connectionRow.status;
        notificationButton=new NotificationButton(this,style,this::openNotifications);
        page.addView(new BrandHeader(this,style,connectionRow,notificationButton));
        notice=label(page,"",14,style.warning);notice.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);notice.setVisibility(View.GONE);
        content=new LinearLayout(this);content.setOrientation(LinearLayout.VERTICAL);page.addView(content);
        switch(route){case "alerts"->notificationScreen();case "printer"->printerDetails();case "projects"->projectList();case "project"->projectFiles();case "tasks"->taskList();case "settings"->settings();default->printerList();}
        LinearLayout tabs=new LinearLayout(this);style.navigationBar(tabs);root.addView(tabs);
        tab(tabs,I18n.t("Принтеры"),"printer","printers");tab(tabs,I18n.t("Проекты"),"projects","projects");tab(tabs,I18n.t("Задачи"),"tasks","tasks");
        if(hasInventory())tabs.addView(style.navigationItem(I18n.t("Склад"),"warehouse",false,()->{if(!busy)openInventory();}));
        tab(tabs,I18n.t("Ещё"),"more","settings");
        updateLive();refreshNotice();if(repo.capabilities!=null&&!repo.capabilities.modulesKnown)recordNotification("modules","unknown",I18n.t("Сообщение FM"),I18n.t("Не удалось проверить модули FM. Обновите данные, чтобы открыть склад."));
        ScrollView currentScroll=scroll;currentScroll.post(()->currentScroll.scrollTo(0,scrollY));
    }
    private void tab(LinearLayout nav,String caption,String icon,String next){boolean selected=route.equals(next)||("printers".equals(next)&&route.equals("printer"))||("projects".equals(next)&&route.equals("project"));nav.addView(style.navigationItem(caption,icon,selected,()->{if(!busy){route=next;render();loadRoute();}}));}
    private interface Work<T>{T run() throws Exception;}
    private <T>void work(Work<T> action,Consumer<T> done){
        if(busy||!active)return;busy=true;showNotice(I18n.t("Загрузка…"));updateLive();
        network.execute(()->{try{T value=action.run();runOnUiThread(()->{busy=false;if(!isDestroyed()){showNotice("");try{done.accept(value);}catch(Exception ex){error(ex);}}});}catch(Exception ex){Exception shown=checkedUnauthorized(ex);runOnUiThread(()->{busy=false;if(!isDestroyed())error(shown);});}});
    }
    private void error(Exception ex){
        if(ex instanceof FmApi.Unauthorized){returnToLogin();return;}
        if(ex instanceof PrinterCommand.NeedsForce){askForce((PrinterCommand.NeedsForce)ex);return;}
        // FM точно сказал, что команда не дошла или не подтверждена: показываем это, состояние на экране не трогаем.
        if(ex instanceof PrinterCommand.Failure&&((PrinterCommand.Failure)ex).delivery){showNotice(ex.getMessage());return;}
        if(ex instanceof PrinterCommand.Failure||ex instanceof PrintJournal.Unknown)render();
        showNotice(I18n.t("Не удалось подтвердить операцию. ")+safeError(ex));
    }
    private String safeError(Exception ex){if(ex instanceof PrinterCommand.Failure||ex instanceof PrintJournal.Unknown)return ex.getMessage();String message=ex.getMessage();if(message==null||message.isEmpty())return I18n.t("Проверьте связь с FM.");return message.length()>400?message.substring(0,400):message;}
    /** Worker thread. A 401 is proof of nothing until GET /api/auth/status says authenticated:false;
     * otherwise the saved login stays and the screen shows a retry notice. */
    private Exception checkedUnauthorized(Exception ex){
        if(!(ex instanceof FmApi.Unauthorized))return ex;
        return AuthCheck.afterUnauthorized(AuthCheck.ask(api),ex);
    }
    /** /ws refused (401/403) or closed with 1008: FM sends that on a temporary failure too. */
    private void telemetryUnauthorized(int generation,Exception ex){
        network.execute(()->{Exception shown=checkedUnauthorized(ex);runOnUiThread(()->{
            if(!active||generation!=streamGeneration)return;
            if(shown instanceof FmApi.Unauthorized){returnToLogin();return;}
            showNotice(shown.getMessage());
            handler.postDelayed(()->{if(active&&generation==streamGeneration)startTelemetry();},5000);
        });});
    }
    private void startTelemetry(){
        if(telemetry!=null)telemetry.close();
        int generation=++streamGeneration;
        telemetry=new TelemetryClient(api,new TelemetryClient.Listener(){public void snapshot(JSONObject next){runOnUiThread(()->{if(!active||generation!=streamGeneration)return;states=next;receivedAt=SystemClock.elapsedRealtime();connected=true;updateLive();});}public void disconnected(Exception ex){runOnUiThread(()->{if(!active||generation!=streamGeneration)return;connected=false;receivedAt=0;updateLive();if(ex instanceof FmApi.Unauthorized)telemetryUnauthorized(generation,ex);});}});
        telemetry.start();
    }
    private void returnToLogin(){
        if(isFinishing()||isDestroyed())return;
        SessionRegistry.clear();network.execute(()->{try{new RememberedLogin(new EncryptedSessionStore(this)).forget();}catch(Exception ignored){}});
        setResult(RESULT_OK,new Intent().putExtra("farm_action","login"));finish();
    }
    private void openInventory(){
        work(()->{repo.refreshCapabilities();repo.requireInventory();return true;},ok->{setResult(RESULT_OK,new Intent().putExtra("farm_action","inventory"));finish();});
    }
    private void loadRoute(){
        work(()->{
            repo.refreshCapabilities();printers=repo.printers();
            switch(route){case "projects"->projects=repo.projects();case "project"->tree=repo.project(selectedProject);case "tasks"->tasks=repo.tasks();}
            refreshExtras();return true;
        },ok->{render();if(!pendingPrinterQr.isEmpty())openScannedPrinter();});
    }
    private void refreshExtras() throws Exception {
        try{JSONObject next=repo.filament();filament=next==null?new JSONObject():next;}catch(FmApi.Unauthorized ex){throw ex;}catch(Exception ex){filament=new JSONObject();}
        try{JSONObject next=repo.badges();badges=next==null?new JSONObject():next;}catch(FmApi.Unauthorized ex){throw ex;}catch(Exception ex){badges=new JSONObject();}
        long at=System.currentTimeMillis();sends=repo.sends();sendsAt=at;
        if(route.equals("printers")&&hasInventory()){
            try{labelServer=repo.printerLabelServer();}catch(FmApi.Unauthorized ex){throw ex;}catch(Exception ex){labelServer="";}
        }else labelServer="";
        if(route.equals("printer")&&canPrint()){
            try{preheatPresets=repo.presets();presetsFailed=false;}catch(FmApi.Unauthorized ex){throw ex;}catch(Exception ex){preheatPresets=null;presetsFailed=true;}
        }else{preheatPresets=null;presetsFailed=false;}
    }
    private JSONObject find(JSONArray rows,String key,String value){for(JSONObject row:FarmRepository.rows(rows))if(value.equals(row.optString(key)))return row;return null;}
    private long age(){return receivedAt==0?Long.MAX_VALUE:SystemClock.elapsedRealtime()-receivedAt;}
    private JSONObject state(String id){return states.optJSONObject(id);}
    private String stateText(JSONObject s){
        if(!PrinterState.fresh(s,age()))return I18n.t("Нет свежих данных");
        return switch(s.optString("status")){case "IDLE"->I18n.t("Свободен");case "RUNNING"->I18n.t("Печатает");case "PREPARE"->I18n.t("Подготовка");case "PAUSED","PAUSE"->I18n.t("Пауза");case "FINISH"->I18n.t("Печать завершена");case "FAILED","ERROR"->I18n.t("Требует внимания");case "SLICING"->I18n.t("Подготовка файла");default->s.optString("status",I18n.t("Неизвестно"));};
    }
    private void updateTile(String id,PrinterTile tile){
        JSONObject s=state(id);boolean fresh=PrinterState.fresh(s,age());String status=fresh?s.optString("status"):"";
        int color=switch(status){case "IDLE","FINISH"->style.success;case "RUNNING","PREPARE","SLICING"->style.accent;default->style.warning;};
        int progress=PrinterState.progress(s,age());String remaining=fresh&&s.optDouble("remaining_time")>0?I18n.t("осталось ")+time(s.optDouble("remaining_time")):"";
        tile.update(stateText(s),color,fresh&&!"IDLE".equals(status)?s.optString("file_name"):"",progress,remaining);
    }
    private String time(double minutes){if(minutes<=0)return "—";long value=Math.round(minutes);return value>=60?(value/60)+I18n.t(" ч ")+(value%60)+I18n.t(" мин"):value+I18n.t(" мин");}
    private void printerList(){
        sectionHeader(I18n.t("Принтеры фермы"),"printers",true);
        if(printers.length()==0)label(content,I18n.t("Принтеров пока нет. Нажмите «Обновить»."),15,style.muted);
        printerRows=new LinearLayout(this);printerRows.setOrientation(LinearLayout.VERTICAL);content.addView(printerRows);
        for(JSONObject p:sortedPrinters()){
            String id=p.optString("id");PrinterTile c=new PrinterTile(this,style,p,()->{if(!busy){selectedPrinter=id;route="printer";render();loadRoute();}});printerRows.addView(c);liveTiles.put(id,c);printerOrder.add(id);StringJoiner extra=new StringJoiner(", ");
            if(Arrays.asList("bambu","klipper").contains(p.optString("type")))c.camera(()->{if(!busy)startActivity(new Intent(this,CameraActivity.class).putExtra("printer_id",id).putExtra("printer_name",p.optString("name")).putExtra("printer_type",p.optString("type")));});
            String cover=p.optString("cover_url");if(!cover.isEmpty())loadImage(c.cover,cover,false);
            if(hasInventory()){JSONObject f=filament.optJSONObject(id);if(f!=null){String stock=stockText(f);TextView stockLabel=label(c,stock,13,style.muted);stockLabel.setMaxLines(2);stockLabel.setEllipsize(TextUtils.TruncateAt.END);stockLabel.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);extra.add(stock);}}
            JSONArray marks=badges.optJSONArray(id);if(marks!=null)for(JSONObject mark:FarmRepository.rows(marks)){label(c,mark.optString("text"),13,style.warning).setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);extra.add(mark.optString("text"));}c.supplementary(extra.toString());
        }
    }
    private String sortMode(String key,boolean printer){return FarmSort.mode(prefs.getString("farm_sort_"+key,printer?"status":"name"),printer);}
    private boolean sortReverse(String key){return prefs.getBoolean("farm_sort_reverse_"+key,false);}
    private List<JSONObject> sortedPrinters(){return FarmSort.printers(printers,states,age(),sortMode("printers",true),sortReverse("printers"));}
    private void sectionHeader(String title,String key,boolean printer){
        LinearLayout row=new LinearLayout(this);row.setGravity(Gravity.CENTER_VERTICAL);content.addView(row);
        TextView heading=style.label(title,22,style.text);heading.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));heading.setPadding(0,dp(8),dp(8),dp(4));row.addView(heading,new LinearLayout.LayoutParams(0,-2,1));
        if(printer&&hasInventory()&&!labelServer.isEmpty()){ImageButton scan=style.iconButton(I18n.t("Найти принтер по QR"),"scan",()->{if(!busy)scanPrinter();});LinearLayout.LayoutParams bounds=new LinearLayout.LayoutParams(dp(64),dp(64));row.addView(scan,bounds);}
        String mode=sortMode(key,printer),caption=switch(mode){case "status"->I18n.t("По статусу");case "model"->I18n.t("По модели");case "ready"->I18n.t("По готовности");default->I18n.t("По имени");};
        LinearLayout sorting=new LinearLayout(this);sorting.setGravity(Gravity.CENTER_VERTICAL);content.addView(sorting);
        TextView sortCaption=label(sorting,caption+(sortReverse(key)?" ↓":" ↑"),13,style.muted);sortCaption.setPadding(0,dp(4),dp(6),dp(4));
        sorting.addView(style.iconButton(I18n.t("Сортировка")+": "+caption,"sort",()->showSort(key,printer)));
    }
    private void showSort(String key,boolean printer){
        String[] modes=printer?new String[]{"status","model","name"}:new String[]{"name","ready"};
        String[] labels=printer?new String[]{I18n.t("По статусу"),I18n.t("По модели"),I18n.t("По имени")}:new String[]{I18n.t("По имени"),I18n.t("По готовности")};
        LinearLayout form=new LinearLayout(this);form.setOrientation(LinearLayout.VERTICAL);form.setPadding(dp(16),dp(8),dp(16),0);
        RadioGroup choices=new RadioGroup(this);String current=sortMode(key,printer);for(int i=0;i<modes.length;i++){RadioButton b=new RadioButton(this);b.setId(View.generateViewId());b.setText(labels[i]);b.setTextColor(style.text);b.setTextSize(16);b.setMinHeight(dp(48));choices.addView(b);if(modes[i].equals(current))b.setChecked(true);}form.addView(choices);
        CheckBox reverse=new CheckBox(this);reverse.setText(I18n.t("Обратный порядок"));reverse.setTextColor(style.text);reverse.setMinHeight(dp(48));reverse.setChecked(sortReverse(key));form.addView(reverse);
        label(form,printer?I18n.t("По статусу: ошибки, пауза, завершённые, печатающие, подготовка, свободные, без связи."):I18n.t("По готовности: готовые к печати, печатающиеся, план выполнен, нужна подготовка, нет файла."),13,style.muted);
        ScrollView options=new ScrollView(this);options.addView(form);new AlertDialog.Builder(this).setTitle(I18n.t("Сортировка")).setView(options).setPositiveButton(I18n.t("Применить"),(d,w)->{int index=-1;for(int i=0;i<choices.getChildCount();i++)if(((RadioButton)choices.getChildAt(i)).isChecked())index=i;if(index<0||index>=modes.length)return;prefs.edit().putString("farm_sort_"+key,modes[index]).putBoolean("farm_sort_reverse_"+key,reverse.isChecked()).apply();render();ScrollView currentScroll=scroll;currentScroll.post(()->currentScroll.scrollTo(0,0));}).setNegativeButton(I18n.t("Отмена"),null).show();
    }
    @Override public boolean dispatchTouchEvent(MotionEvent event){lastInteraction=SystemClock.elapsedRealtime();return super.dispatchTouchEvent(event);}
    private void reorderPrinters(){
        if(printerRows==null||!route.equals("printers")||!sortMode("printers",true).equals("status")||SystemClock.elapsedRealtime()-lastInteraction<2500)return;
        for(PrinterTile tile:liveTiles.values())if(tile.isAccessibilityFocused())return;
        List<String> next=new ArrayList<>();for(JSONObject p:sortedPrinters())next.add(p.optString("id"));if(next.equals(printerOrder))return;
        int[] position=new int[2];scroll.getLocationOnScreen(position);int viewport=position[1];PrinterTile anchor=null;int anchorY=0;
        if(scroll.getScrollY()>0)for(String id:printerOrder){PrinterTile tile=liveTiles.get(id);if(tile==null)continue;tile.getLocationOnScreen(position);if(position[1]+tile.getHeight()>viewport){anchor=tile;anchorY=position[1];break;}}
        printerRows.removeAllViews();for(String id:next){PrinterTile tile=liveTiles.get(id);if(tile!=null)printerRows.addView(tile);}printerOrder.clear();printerOrder.addAll(next);
        PrinterTile savedAnchor=anchor;int savedY=anchorY,token=revision;ScrollView savedScroll=scroll;printerRows.post(()->{if(token!=revision||savedAnchor==null)return;int[] now=new int[2];savedAnchor.getLocationOnScreen(now);savedScroll.scrollBy(0,now[1]-savedY);});
    }
    private void scanPrinter(){
        work(()->{repo.refreshCapabilities();repo.requireInventory();labelServer=repo.printerLabelServer();printers=repo.printers();return PrinterQr.catalog(printers).toString();},catalog->{
            if(active)printerScan.launch(new Intent(this,ScannerActivity.class).putExtra("purpose",I18n.t("Найти принтер по QR"))
                .putExtra("scan_kind",ScanPolicy.PRINTER).putExtra("server_id",labelServer).putExtra("slot_catalog",catalog));
        });
    }
    private void openScannedPrinter(){
        String code=pendingPrinterQr;if(code.isEmpty()||busy||!active)return;pendingPrinterQr="";
        work(()->{JSONObject p=repo.scannedPrinter(code);printers=repo.printers();if(find(printers,"id",p.optString("id"))==null)throw new IOException(I18n.t("Принтер не найден."));return p.optString("id");},id->{
            selectedPrinter=id;route="printer";preheatPresets=null;render();loadRoute();
        });
    }
    private void printerDetails(){
        JSONObject p=find(printers,"id",selectedPrinter);if(p==null){label(content,I18n.t("Принтер не найден."),17,style.warning);return;}
        label(content,I18n.t("Карточка принтера"),25,style.text);PrinterTile tile=new PrinterTile(this,style,p,null);content.addView(tile);liveTiles.put(selectedPrinter,tile);
        String cover=p.optString("cover_url");if(!cover.isEmpty())loadImage(tile.cover,cover,false);
        if(Arrays.asList("bambu","klipper").contains(p.optString("type")))tile.camera(()->{if(!busy)startActivity(new Intent(this,CameraActivity.class).putExtra("printer_id",selectedPrinter).putExtra("printer_name",p.optString("name")).putExtra("printer_type",p.optString("type")));});
        LinearLayout c=card();label(c,I18n.t("Температуры и состояние"),18,style.text);detailLive=label(c,"",15,style.muted);detailLive.setLineSpacing(dp(3),1);
        if(canPrint()&&PrinterCommand.supported(p)){printerControls(p);preheatCard(p);}
        LinearLayout materials=card();label(materials,I18n.t("Материал на принтере"),16,style.text);materialSlots=new MaterialSlotsView(this,style);materials.addView(materialSlots);
        action(I18n.t("Выбрать файл из проектов"),I18n.t("Файлы и детали проекта"),"batch",()->{route="projects";render();loadRoute();});
        action(I18n.t("Выбрать файл из задач"),I18n.t("Подготовленные файлы для печати"),"tasks",()->{route="tasks";render();loadRoute();});
    }
    private void repeatControls(LinearLayout c,LinearLayout row){
        repeatButton=style.iconButton(I18n.t("Повторить последнюю печать"),"repeat",()->{if(busy)return;
            String pid=selectedPrinter;work(()->repo.repeatTarget(pid,()->state(pid),this::age),target->{
                JSONObject p=find(printers,"id",pid);if(p==null)throw new IllegalStateException(I18n.t("Принтер не найден."));printOptions(target.file,target.projectId,p,target);
            });
        });LinearLayout.LayoutParams repeatBounds=new LinearLayout.LayoutParams(dp(48),dp(48));repeatBounds.setMargins(dp(12),0,0,0);row.addView(repeatButton,repeatBounds);
        repeatStatus=label(c,"",13,style.muted);repeatStatus.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
    }
    private void updateRepeat(){
        if(repeatButton==null)return;JSONObject p=find(printers,"id",selectedPrinter),s=state(selectedPrinter);
        // Повтор — только печати, которую FM отправил сам; узнать это можно лишь из журнала качества.
        boolean eligible=p!=null&&RepeatPrint.eligible(p,s,age()),known=p!=null&&repo.capabilities!=null&&repo.capabilities.moduleAvailable("quality");
        boolean reserved=true;try{reserved=RepeatPrint.reserved(sends,selectedPrinter);}catch(Exception ignored){}
        boolean marked=journal.blocks(api.origin,selectedPrinter);
        repeatButton.setEnabled(!busy&&canPrint()&&eligible&&known&&!reserved&&!marked);
        String message=marked?I18n.t("Сначала проверьте предыдущую отправку в FM."):!eligible?I18n.t("Для повтора нужны свежие данные и завершённая печать либо свободный принтер."):!known?I18n.t("Повтор доступен только для печати, которую отправил FM. Нужен модуль «Аналитика качества»; иначе откройте файл из проектов или задач."):reserved?I18n.t("FM уже отправляет задание на этот принтер."):I18n.t("Перед запуском подтвердите, что деталь снята и стол свободен.");
        repeatStatus.setText(message);
    }
    private void printerControls(JSONObject p){
        LinearLayout c=card();label(c,I18n.t("Управление печатью"),18,style.text);LinearLayout row=new LinearLayout(this);c.addView(row);
        pauseButton=style.iconButton(I18n.t("Поставить печать на паузу"),"pause",()->{if(!busy)sendControl(PrinterCommand.paused(state(selectedPrinter))?"resume":"pause");});row.addView(pauseButton);
        stopButton=style.iconButton(I18n.t("Остановить печать?"),"stop",()->{if(!busy)new AlertDialog.Builder(this).setTitle(I18n.t("Остановить печать?"))
            .setMessage(p.optString("name")+"\n\n"+I18n.t("Текущая печать будет прервана. Продолжить её после остановки нельзя."))
            .setPositiveButton(I18n.t("Остановить"),(dialog,which)->sendControl("stop")).setNegativeButton(I18n.t("Отмена"),null).show();});
        LinearLayout.LayoutParams stopBounds=new LinearLayout.LayoutParams(dp(48),dp(48));stopBounds.setMargins(dp(12),0,0,0);row.addView(stopButton,stopBounds);stopButton.setImageTintList(new android.content.res.ColorStateList(new int[][]{new int[]{-android.R.attr.state_enabled},new int[]{}},new int[]{style.muted,style.warning}));
        controlStatus=label(c,"",13,style.muted);controlStatus.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        repeatControls(c,row);
    }
    private void sendControl(String action){
        String pid=selectedPrinter;work(()->{repo.control(pid,action,()->state(pid),this::age);return true;},ok->{
            updateLive();showNotice(I18n.t("FM обработал команду. Проверьте новое состояние принтера в карточке."));
        });
    }
    private String heatDetails(JSONObject p,PreheatPresets.Preset preset){
        StringJoiner out=new StringJoiner("\n");for(PrinterCommand command:PrinterCommand.preheat(p,state(p.optString("id")),preset))out.add(command.caption()+": "+command.temperature+" °C");return out.toString();
    }
    private void preheatCard(JSONObject p){
        LinearLayout c=card();LinearLayout heading=new LinearLayout(this);heading.setGravity(Gravity.CENTER_VERTICAL);c.addView(heading);TextView title=style.label(I18n.t("Пресеты прогрева"),16,style.text);heading.addView(title,new LinearLayout.LayoutParams(0,-2,1));if(preheatPresets!=null)heading.addView(style.iconButton(I18n.t("Изменить пресеты"),"settings",()->{if(!busy)editPresets();}));
        if(preheatPresets==null)label(c,presetsFailed?I18n.t("Не удалось прочитать пресеты FM. Нажмите «Обновить»."):I18n.t("Загрузка пресетов…"),14,style.muted);
        else{
            if(preheatPresets.values.isEmpty())label(c,I18n.t("Пресетов пока нет. Их можно добавить ниже."),14,style.muted);
            LinearLayout row=null;for(int i=0;i<preheatPresets.values.size();i++){
                PreheatPresets.Preset preset=preheatPresets.values.get(i);if(i%2==0){row=new LinearLayout(this);c.addView(row);}
                String temperatures=preset.nozzle+" / "+preset.bed+(PrinterCommand.chamber(p,state(selectedPrinter))&&preset.chamber!=null?" / "+preset.chamber:"")+" °C";
                Button b=button(row,preset.name+"\n"+temperatures,false,()->confirmHeat(p,preset,false));b.setTextSize(14);b.setContentDescription(preset.name+", "+heatDetails(p,preset));
                LinearLayout.LayoutParams bounds=new LinearLayout.LayoutParams(0,-2,1);bounds.setMargins(i%2==0?0:dp(8),dp(4),0,dp(4));b.setLayoutParams(bounds);heatButtons.add(b);
            }
        }
        PreheatPresets.Preset cool=new PreheatPresets.Preset("Off",0,0,0);
        coolButton=button(c,I18n.t("Остыть — выключить нагрев"),false,()->confirmHeat(p,cool,true));
        coolNote=label(c,I18n.t("Во время печати нагрев с телефона не выключается: печать сорвётся. Поставьте печать на паузу или остановите её."),13,style.muted);coolNote.setVisibility(View.GONE);
    }
    private void confirmHeat(JSONObject p,PreheatPresets.Preset preset,boolean cool){
        String title=cool?I18n.t("Выключить нагрев?"):I18n.t("Прогреть принтер?");String pid=p.optString("id");
        String message=p.optString("name")+(cool?"":" · "+preset.name)+"\n\n"+heatDetails(p,preset);
        String warning=HeaterPolicy.warning(state(pid),preset,cool);if(!warning.isEmpty())message+="\n\n"+warning;
        new AlertDialog.Builder(this).setTitle(title).setMessage(message).setPositiveButton(cool?I18n.t("Выключить нагрев"):I18n.t("Прогреть"),(dialog,which)->
            work(()->{repo.preheat(pid,preset,cool,()->state(pid),this::age);return true;},ok->{updateLive();showNotice(I18n.t("FM обработал команды температур. Проверьте текущие цели в карточке."));}))
            .setNegativeButton(I18n.t("Отмена"),null).show();
    }
    /** FM отказал (409 heater_off_while_printing): спросить и только по согласию повторить тот же запрос с force. */
    private void askForce(PrinterCommand.NeedsForce refused){
        JSONObject p=find(printers,"id",refused.printerId);String message=(p==null?refused.printerId:p.optString("name"))+"\n\n"+I18n.t("FM сообщает, что принтер печатает. Выключение нагрева сопла или стола сорвёт текущую печать.");
        if(!refused.accepted.isEmpty())message+="\n\n"+I18n.t("FM принял команды: ")+String.join(", ",refused.accepted)+".";
        new AlertDialog.Builder(this).setTitle(I18n.t("Печать сорвётся — выключить нагрев?")).setMessage(message)
            .setPositiveButton(I18n.t("Выключить нагрев"),(dialog,which)->work(()->{repo.preheatForced(refused,()->state(refused.printerId),this::age);return true;},ok->{updateLive();showNotice(I18n.t("FM обработал команды температур. Проверьте текущие цели в карточке."));}))
            .setNegativeButton(I18n.t("Отмена"),(dialog,which)->showNotice(I18n.t("Нагрев не выключен.")))
            .show();
    }
    private void editPresets(){
        work(repo::presets,current->{preheatPresets=current;PreheatEditor.show(this,style,current,(edited,close)->{
            if(!busy)work(()->repo.savePresets(current,edited),saved->{preheatPresets=saved;presetsFailed=false;close.run();render();showNotice(I18n.t("Пресеты сохранены для всей фермы."));});
        });});
    }
    private void updateControls(){
        if(pauseButton==null)return;JSONObject p=find(printers,"id",selectedPrinter),s=state(selectedPrinter);boolean enabled=canPrint()&&!busy;
        pauseButton.setImageDrawable(new FmStyle.Icon(PrinterCommand.paused(s)?"play":"pause",style.accent));String pauseCaption=PrinterCommand.paused(s)?I18n.t("Продолжить печать"):I18n.t("Поставить печать на паузу");pauseButton.setContentDescription(pauseCaption);pauseButton.setTooltipText(pauseCaption);
        pauseButton.setEnabled(enabled&&PrinterCommand.allowed(p,s,age(),PrinterCommand.paused(s)?"resume":"pause"));stopButton.setEnabled(enabled&&PrinterCommand.allowed(p,s,age(),"stop"));
        for(Button b:heatButtons)b.setEnabled(enabled&&PrinterCommand.allowed(p,s,age(),"heat"));
        if(coolButton!=null){boolean printingNow=HeaterPolicy.activePrint(s);coolButton.setVisibility(printingNow?View.GONE:View.VISIBLE);coolButton.setEnabled(enabled&&HeaterPolicy.offOffered(p,s,age()));coolNote.setVisibility(printingNow?View.VISIBLE:View.GONE);}
        String message=PrinterState.fresh(s,age())?I18n.t("Пауза и остановка доступны во время печати."):I18n.t("Для команд нужны свежие данные принтера.");controlStatus.setText(message);
    }
    private String stockText(JSONObject value){
        StringBuilder out=new StringBuilder();
        for(JSONObject slot:FarmRepository.rows(value.optJSONArray("slots"))){
            JSONObject spool=slot.optJSONObject("spool");if(spool==null)continue;if(out.length()>0)out.append("\n");
            String position=MaterialSlots.positionName(slot);
            StringJoiner material=new StringJoiner(" · ");for(String field:new String[]{"vendor_name","material","color_name","label"}){String part=spool.optString(field);if(!part.isEmpty())material.add(part);}
            out.append(position).append(": ").append(material.toString());
            if(spool.has("weight_remaining_g"))out.append(" · ").append(Math.round(spool.optDouble("weight_remaining_g"))).append(I18n.t(" г"));
            if(PrintRequest.flag(slot,"offline")||PrintRequest.flag(slot,"unconfirmed"))out.append(" · ").append(I18n.t("Нет свежих данных"));
        }
        return out.length()==0?I18n.t("Катушки не привязаны"):out.toString();
    }
    private String temp(JSONObject s,String key,String target){if(!s.has(key)||s.isNull(key))return "—";return Math.round(s.optDouble(key))+" °C"+(s.has(target)?" / "+Math.round(s.optDouble(target))+" °C":"");}
    private void updateLive(){
        if(connection==null)return;
        boolean fresh=connected&&age()<6500;connection.setText(fresh?I18n.t("● Подключено"):I18n.t("○ Нет связи"));connection.setContentDescription((fresh?I18n.t("● Подключено · "):I18n.t("○ Связь потеряна · "))+api.origin);connection.setTooltipText(api.origin);connection.setTextColor(fresh?style.success:style.warning);
        for(var e:liveTiles.entrySet())updateTile(e.getKey(),e.getValue());
        reorderPrinters();
        if(detailLive!=null){JSONObject s=state(selectedPrinter);String text=I18n.t("Нет свежих данных");if(s!=null&&PrinterState.fresh(s,age())){
            text=I18n.t("Сопло: ")+temp(s,"nozzle_temp","nozzle_target")+"\n"+I18n.t("Стол: ")+temp(s,"bed_temp","bed_target");
            if(s.has("chamber_temp"))text+="\n"+I18n.t("Термокамера: ")+temp(s,"chamber_temp","chamber_target");
            JSONArray nozzles=s.optJSONArray("nozzles");if(nozzles!=null&&nozzles.length()>1)for(int i=0;i<nozzles.length();i++){JSONObject nozzle=nozzles.optJSONObject(i);if(nozzle!=null)text+="\n"+I18n.t("Сопло ")+(i+1)+": "+temp(nozzle,"temp","target");}
        }detailLive.setText(text);}
        if(materialSlots!=null)materialSlots.update(MaterialSlots.of(find(printers,"id",selectedPrinter),state(selectedPrinter),age(),hasInventory()?filament.optJSONObject(selectedPrinter):null));
        boolean notificationChanged=captureNotifications();notificationButton.update(notifications.unread(notificationScope()),journal.pending(api.origin));
        for(var entry:notifications.entries(notificationScope())){TextView row=notificationRows.get(entry.key());if(row!=null&&!entry.message().contentEquals(row.getText()))row.setText(entry.message());}
        if(notificationChanged&&route.equals("alerts")&&!notificationRenderPending){notificationRenderPending=true;handler.post(()->{notificationRenderPending=false;if(active&&!isDestroyed()&&route.equals("alerts"))render();});}
        refreshNotice();
        updateControls();
        updateRepeat();
    }
    private void projectList(){
        label(content,I18n.t("Проекты"),22,style.text);
        if(projects.length()==0)label(content,I18n.t("Проектов пока нет."),15,style.muted);
        for(JSONObject project:FarmRepository.rows(projects)){String id=project.optString("id");content.addView(new ProjectTile(this,style,project,()->{if(!busy){selectedProject=id;projectName=project.optString("name");route="project";tree=new JSONObject();render();loadRoute();}}));}
    }
    private void projectFiles(){
        sectionHeader(projectName,"project_files",false);JSONArray nodes=tree.optJSONArray("nodes");if(nodes==null||nodes.length()==0)label(content,I18n.t("Файлов пока нет."),15,style.muted);
        for(JSONObject file:FarmSort.files(FarmSort.projectFiles(nodes),sortMode("project_files",false),sortReverse("project_files")))fileRow(file,selectedProject);
    }
    private void taskList(){
        sectionHeader(I18n.t("Задачи"),"task_files",false);if(tasks.length()==0)label(content,I18n.t("Задач пока нет."),15,style.muted);
        for(JSONObject file:FarmSort.files(tasks,sortMode("task_files",false),sortReverse("task_files")))fileRow(file,"");
    }
    private String fileSummary(JSONObject file,String project){
        StringJoiner summary=new StringJoiner(" · ");if(project.isEmpty())summary.add(file.optLong("printed_qty")+" / "+file.optLong("required_qty"));
        else {JSONArray parts=file.optJSONArray("children");if(parts!=null&&parts.length()>0){long printed=0,required=0;for(JSONObject part:FarmRepository.rows(parts)){printed+=Math.max(0,part.optLong("printed_qty"));required+=Math.max(0,part.optLong("required_qty"));}summary.add(I18n.t("Детали: ")+printed+" / "+required);}}
        if(!file.optString("target_model").isEmpty())summary.add(file.optString("target_model"));return summary.toString();
    }
    private String thumbnailPath(JSONObject file,String project){return project.isEmpty()?"/api/staging/"+FarmRepository.segment(file.optString("filename"))+"/thumb":"/api/projects2/files/"+FarmRepository.segment(file.optString("file_id"))+"/thumb";}
    private void fileRow(JSONObject file,String project){
        Runnable print=canPrint()&&PrintRequest.flag(file,"is_printable")&&!PrintRequest.flag(file,"missing")?()->{if(!busy)choosePrint(file,project);}:null;
        CompactFileRow row=new CompactFileRow(this,style,file,fileSummary(file,project),()->{if(!busy)fileDetails(file,project);},print,false);content.addView(row);
        if(!PrintRequest.flag(file,"missing"))loadImage(row.thumbnail,thumbnailPath(file,project),false);
    }
    private void fileDetails(JSONObject file,String project){
        LinearLayout details=new LinearLayout(this);details.setOrientation(LinearLayout.VERTICAL);details.setPadding(dp(16),dp(8),dp(16),dp(12));
        label(details,file.optString("filename"),18,style.text);label(details,FarmSort.fileCaption(file),14,style.accent);label(details,fileSummary(file,project),14,style.muted);
        if(!file.optString("project_name").isEmpty())label(details,I18n.t("Проект: ")+file.optString("project_name"),14,style.muted);
        if(PrintRequest.flag(file,"missing"))label(details,I18n.t("Файл отсутствует на сервере."),14,style.warning);else image(details,thumbnailPath(file,project),180);
        for(JSONObject part:FarmRepository.rows(file.optJSONArray("children")))label(details,part.optString("part_name",part.optString("name"))+" · "+part.optLong("printed_qty")+" / "+part.optLong("required_qty"),14,style.text);
        if(!file.optString("notes").isEmpty())label(details,file.optString("notes"),14,style.muted);
        ScrollView scroller=new ScrollView(this);scroller.addView(details);AlertDialog dialog=new AlertDialog.Builder(this).setTitle(I18n.t("Сведения о файле")).setView(scroller).setNegativeButton(I18n.t("Закрыть"),null).create();
        if(canPrint()&&PrintRequest.flag(file,"is_printable")&&!PrintRequest.flag(file,"missing")){
            button(details,I18n.t("На печать"),true,()->{dialog.dismiss();choosePrint(file,project);});
        }dialog.show();
    }
    private void printButton(LinearLayout c,JSONObject file,String project){
        if(!canPrint())return;
        if(!PrintRequest.flag(file,"is_printable")||PrintRequest.flag(file,"missing")){label(c,I18n.t("Нет готового файла для печати."),13,style.muted);return;}
        button(c,I18n.t("На печать"),true,()->choosePrint(file,project));
    }
    private void choosePrint(JSONObject original,String project){
        work(()->{
            repo.refreshCapabilities();if(!canPrint())throw new IOException(I18n.t("Нет права на печать."));
            printers=repo.printers();long at=System.currentTimeMillis();sends=repo.sends();sendsAt=at;
            JSONObject file=project.isEmpty()?find(repo.tasks(),"filename",original.optString("filename")):find(repo.project(project).optJSONArray("nodes"),"file_id",original.optString("file_id"));
            if(file==null)throw new IOException(I18n.t("Файл не найден в FM."));return file;
        },file->{
            List<JSONObject> choices=new ArrayList<>();List<String> names=new ArrayList<>();boolean marked=false;
            for(JSONObject p:FarmRepository.rows(printers)){String id=p.optString("id");JSONObject s=state(id);
                if(!PrintChoice.offered(file,p,s,age(),sends))continue;
                if(journal.blocks(api.origin,id)){marked=true;continue;}
                choices.add(p);names.add(p.optString("name")+" · "+p.optString("model")+(PrintChoice.needsPlateConfirmation(p,s,age())?" · "+I18n.t("печать завершена — снимите деталь"):""));}
            if(choices.isEmpty()){error(new IOException(marked?I18n.t("Сначала проверьте предыдущую отправку в FM."):I18n.t("Нет свободных совместимых принтеров со свежими данными. Проверьте состояние принтеров в FM.")));return;}
            new AlertDialog.Builder(this).setTitle(I18n.t("Выберите принтер")).setItems(names.toArray(new String[0]),(dialog,index)->printOptions(file,project,choices.get(index))).setNegativeButton(I18n.t("Отмена"),null).show();
        });
    }
    private void printOptions(JSONObject file,String project,JSONObject p){
        printOptions(file,project,p,null);
    }
    private void printOptions(JSONObject file,String project,JSONObject p,RepeatPrint.Target repeat){
        // Klipper: шаги подготовки, которые владелец включил в FM. Нет ответа — печать «как в файле», запуск не блокируется.
        if("klipper".equals(p.optString("type"))){String pid=p.optString("id");work(()->{try{return repo.klipperPrestart(pid);}catch(FmApi.Unauthorized ex){throw ex;}catch(Exception ex){return new JSONObject();}},prestart->printDialog(file,project,p,repeat,prestart));}
        else printDialog(file,project,p,repeat,null);
    }
    private CheckBox check(LinearLayout form,String text,boolean checked){CheckBox box=new CheckBox(this);box.setText(text);box.setTextColor(style.text);box.setChecked(checked);form.addView(box);return box;}
    private void printDialog(JSONObject file,String project,JSONObject p,RepeatPrint.Target repeat,JSONObject prestart){
        LinearLayout form=new LinearLayout(this);form.setOrientation(LinearLayout.VERTICAL);form.setPadding(dp(18),dp(8),dp(18),dp(8));String filename=FarmValues.text(file,"filename");label(form,filename+"\n"+p.optString("name"),17,style.text);
        String type=p.optString("type"),pid=p.optString("id");JSONObject s=state(pid);
        List<PrintChoice.Source> sources="bambu".equals(type)?PrintChoice.bambuSources(s):"klipper".equals(type)?PrintChoice.cfsSources(s):new ArrayList<>();
        boolean cfs="klipper".equals(type)&&sources.size()>1;
        if(!"bambu".equals(type)&&!cfs)sources=List.of(new PrintChoice.Source(I18n.t("Подача по настройкам FM"),null));
        List<String> sourceLabels=new ArrayList<>();for(PrintChoice.Source source:sources)sourceLabels.add(source.label());List<PrintChoice.Source> sourceList=sources;
        label(form,cfs?I18n.t("Ячейка CFS"):I18n.t("Источник материала"),14,style.muted);Spinner sourcePicker=new Spinner(this);sourcePicker.setAdapter(new ArrayAdapter<>(this,android.R.layout.simple_spinner_dropdown_item,sourceLabels));form.addView(sourcePicker);
        CheckBox bed=new CheckBox(this),flow=new CheckBox(this),timelapse=new CheckBox(this);
        if("bambu".equals(type)){bed=check(form,I18n.t("Выравнивание стола"),true);flow=check(form,I18n.t("Калибровка потока"),false);timelapse=check(form,I18n.t("Таймлапс"),false);}
        List<KlipperStart.Step> steps=KlipperStart.steps(prestart);Map<String,CheckBox> stepBoxes=new LinkedHashMap<>();
        if("klipper".equals(type)){
            label(form,I18n.t("Подготовка перед печатью"),14,style.muted);
            for(KlipperStart.Step step:steps){stepBoxes.put(step.id(),check(form,step.label(),step.selected()));if(!step.explain().isEmpty())label(form,step.explain(),12,style.muted);}
            if(steps.isEmpty())label(form,KlipperStart.reachable(prestart)?I18n.t("Дополнительных шагов подготовки нет — печать как в файле."):I18n.t("Шаги подготовки из FM недоступны: принтер не ответил. Печать пойдёт как в файле."),13,style.muted);
        }
        label(form,I18n.t("Проверьте, что стол свободен и материал установлен. FM повторно проверит файл и принтер."),14,style.warning);
        PrintJournal.Mark mark=journal.find(api.origin,pid);
        if(mark!=null&&mark.soft())label(form,I18n.t("Напоминание: результат прошлого запуска с телефона на этом принтере не подтверждён. Убедитесь, что принтер свободен."),14,style.warning);
        boolean plate=repeat!=null||PrintChoice.needsPlateConfirmation(p,s,age());
        CheckBox cleared=new CheckBox(this);
        if(repeat!=null)label(form,project.isEmpty()?I18n.t("Учёт: задача FM"):I18n.t("Учёт: проект ")+repeat.projectName,14,style.muted);
        if(plate)cleared=check(form,I18n.t("Деталь снята, стол свободен и готов к новой печати"),false);
        ScrollView scroll=new ScrollView(this);scroll.addView(form);
        AlertDialog dialog=new AlertDialog.Builder(this).setTitle(repeat==null?I18n.t("Подтвердите печать"):I18n.t("Повторить последнюю печать?")).setView(scroll).setPositiveButton(I18n.t("Начать печать"),null).setNegativeButton(I18n.t("Отмена"),null).create();
        CheckBox bedBox=bed,flowBox=flow,timelapseBox=timelapse,clearedBox=cleared;
        dialog.setOnShowListener(d->{
            if(plate){dialog.getButton(AlertDialog.BUTTON_POSITIVE).setEnabled(clearedBox.isChecked());clearedBox.setOnCheckedChangeListener((b,value)->dialog.getButton(AlertDialog.BUTTON_POSITIVE).setEnabled(value));}
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v->{
            try{
                JSONObject now=state(pid);boolean plateCleared=plate&&clearedBox.isChecked();
                if(repeat==null?!PrintChoice.startAllowed(p,now,age(),plateCleared):!plateCleared||!RepeatPrint.eligible(p,now,age()))throw new IOException(I18n.t("Состояние принтера изменилось. Выберите его заново."));
                Set<String> checked=new HashSet<>();for(var e:stepBoxes.entrySet())if(e.getValue().isChecked())checked.add(e.getKey());
                Integer slot=sourceList.get(sourcePicker.getSelectedItemPosition()).slot();
                JSONObject opts=PrintChoice.options(type,bedBox.isChecked(),flowBox.isChecked(),timelapseBox.isChecked(),cfs?slot:null,KlipperStart.chosen(steps,checked));
                PrintRequest request=new PrintRequest(project,FarmValues.text(file,"file_id"),filename,pid,"bambu".equals(type)?slot:null,opts);
                JSONObject prefs="klipper".equals(type)?KlipperStart.prefs(prestart,checked):null;
                dialog.dismiss();if(repeat==null)sendPrint(request,prefs);else sendRepeat(repeat,request,plateCleared,prefs);
            }catch(Exception ex){error(ex);}
        });});dialog.show();
    }
    private void sendRepeat(RepeatPrint.Target target,PrintRequest request,boolean plateCleared,JSONObject klipperPrefs){
        work(()->{JSONObject result=repo.repeat(target,request,plateCleared,()->state(target.printerId),this::age,journal);repo.saveKlipperPrefs(request.printerId,klipperPrefs);return result;},this::printResult);
    }
    private void printResult(JSONObject result){
        render();showNotice(PrintOutcome.text(result));
    }
    private void sendPrint(PrintRequest request,JSONObject klipperPrefs){
        work(()->{JSONObject result=repo.launch(request,journal);repo.saveKlipperPrefs(request.printerId,klipperPrefs);return result;},this::printResult);
    }
    private boolean hasSends(){JSONArray jobs=sends.optJSONArray("jobs");return journal.pending(api.origin)||(jobs!=null&&jobs.length()>0);}
    private void sendPanel(){
        List<PrintJournal.Mark> marks=journal.marks(api.origin);if(marks.isEmpty())return;LinearLayout c=card();label(c,I18n.t("Отправки на печать"),18,style.text);
        for(PrintJournal.Mark mark:marks){
            if(!mark.printerId().isEmpty()){JSONObject p=find(printers,"id",mark.printerId());label(c,mark.filename()+"\n"+(p==null?mark.printerId():p.optString("name")),14,style.text);}
            label(c,PrintJournal.describe(mark),14,mark.soft()?style.muted:style.warning);
            button(c,I18n.t("Я проверил результат в FM"),false,()->new AlertDialog.Builder(this).setTitle(I18n.t("Снять отметку ожидания?")).setMessage(I18n.t("Убедитесь в FM и на принтере, началась ли печать. Эта кнопка только убирает отметку на телефоне: она не отменяет и не повторяет печать.")).setPositiveButton(I18n.t("Результат проверен"),(d,w)->{try{journal.clear(mark.origin(),mark.printerId());render();}catch(Exception ex){error(ex);}}).setNegativeButton(I18n.t("Отмена"),null).show());
        }
    }
    private String sendState(String value){return switch(value){case "completed"->I18n.t("Старт подтверждён");case "failed"->I18n.t("Отправка завершилась ошибкой");case "uploading"->I18n.t("Загрузка файла");case "waiting_confirmation"->I18n.t("Ожидание подтверждения принтера");case "queued"->I18n.t("Ожидание отправки");default->I18n.t("Подготовка и отправка");};}
    /** Свои отметки этого FM: снять по своей отправке, по печати файла или сделать напоминанием. */
    private boolean resolveJournal(){return journal.resolve(api.origin,sends,sendsAt,this::state,age());}
    private void settings(){
        label(content,I18n.t("Настройки приложения"),25,style.text);label(content,ru.threediwell.fm.core.AppVersion.withOrigin(api.origin),13,style.muted);
        if(hasInventory())action(I18n.t("Склад фермы"),I18n.t("Катушки, приёмка, установка и этикетки"),"receive",this::openInventory);
        else label(content,repo.capabilities==null||!repo.capabilities.modulesKnown?I18n.t("Не удалось проверить модули FM. Обновите данные, чтобы открыть склад."):I18n.t("Модуль склада недоступен. Его функции скрыты."),14,style.muted);
        label(content,canPrint()?I18n.t("Доступна печать."):I18n.t("Доступен просмотр. Печать требует права оператора."),14,style.muted);
        action(I18n.t("Тема оформления"),FmStyle.isDark(this)?I18n.t("Тёмная"):I18n.t("Светлая"),"settings",()->
            new AlertDialog.Builder(this).setTitle(I18n.t("Тема оформления")).setSingleChoiceItems(new String[]{I18n.t("Тёмная"),I18n.t("Светлая")},FmStyle.isDark(this)?0:1,(dialog,which)->{
                prefs.edit().putBoolean("dark",which==0).apply();dialog.dismiss();redrawSettings();
            }).setNegativeButton(I18n.t("Отмена"),null).show());
        action(I18n.t("Язык приложения"),I18n.language().equals("en")?"English":I18n.t("Русский"),"settings",()->
            new AlertDialog.Builder(this).setTitle(I18n.t("Язык приложения")).setSingleChoiceItems(new String[]{I18n.t("Русский"),"English"},I18n.language().equals("en")?1:0,(dialog,which)->{
                prefs.edit().putString("language",which==1?"en":"ru").apply();dialog.dismiss();redrawSettings();
            }).setNegativeButton(I18n.t("Отмена"),null).show());
        Switch intro=new Switch(this);intro.setText(R.string.intro_setting_title);intro.setTextSize(16);intro.setMinHeight(dp(56));intro.setSwitchPadding(dp(16));intro.setTextColor(style.text);intro.setChecked(prefs.getBoolean("show_intro",true));intro.setOnCheckedChangeListener((b,value)->prefs.edit().putBoolean("show_intro",value).apply());content.addView(intro,new LinearLayout.LayoutParams(-1,-2));
        label(content,getString(R.string.intro_setting_hint),14,style.muted);
        action(I18n.t("Проверка NFC"),I18n.t("Диагностика метки катушки — только чтение"),"nfc",()->startActivity(new Intent(this,NfcCheckActivity.class)));
        if(repo.capabilities!=null&&repo.capabilities.admin)action(I18n.t("Лицензии модулей: отметить через этот телефон"),I18n.t("Когда у компьютера фермы нет интернета"),"check",this::relayLicenses);
        button(content,I18n.t("Выйти"),false,()->work(()->{new RememberedLogin(new EncryptedSessionStore(this)).forget();try{api.call("POST","/api/auth/logout",new JSONObject());}catch(Exception ignored){}SessionRegistry.clear();return true;},ok->{setResult(RESULT_OK,new Intent().putExtra("farm_action","login"));finish();}));
    }
    private void redrawSettings(){refreshPresentation();style=new FmStyle(this);render();}
    /** Лицензии модулей через этот телефон (как страница FM в браузере): по кнопке — с итогом в окне. */
    private void relayLicenses(){
        work(()->{repo.refreshCapabilities();if(!repo.capabilities.admin)throw new IOException(I18n.t("У пользователя нет права на эту операцию в FM."));return PhoneLicenseRelay.runNow(this,api);},result->{
            String text=PhoneLicenseRelay.message(result,true);if(text==null)return;
            new AlertDialog.Builder(this).setTitle(I18n.t("Лицензии модулей")).setMessage(text).setPositiveButton(I18n.t("Понятно"),null).show();
        });
    }
    private void autoRelayLicenses(){
        PhoneLicenseRelay.auto(this,api,result->{if(!active||isDestroyed())return;String text=PhoneLicenseRelay.message(result,false);if(text!=null)showNotice(I18n.t("Лицензии модулей")+"\n"+text);});
    }
    private void image(LinearLayout parent,String path,int height){
        ImageView image=new ImageView(this);image.setScaleType(ImageView.ScaleType.FIT_CENTER);parent.addView(image,new LinearLayout.LayoutParams(-1,dp(height)));loadImage(image,path,true);
    }
    private void loadImage(ImageView image,String path,boolean hideOnFailure){
        int token=revision;
        images.execute(()->{if(revision!=token)return;try(FmApi.Media media=api.openMedia(path);ByteArrayOutputStream bytes=new ByteArrayOutputStream()){
            byte[] buffer=new byte[8192];int n;while((n=media.input.read(buffer))!=-1){if(bytes.size()+n>4*1024*1024)throw new IOException("Image too large");bytes.write(buffer,0,n);}byte[] data=bytes.toByteArray();BitmapFactory.Options opts=new BitmapFactory.Options();opts.inJustDecodeBounds=true;BitmapFactory.decodeByteArray(data,0,data.length,opts);if(opts.outWidth<=0||opts.outHeight<=0||opts.outWidth>16000||opts.outHeight>16000)return;opts.inJustDecodeBounds=false;opts.inSampleSize=1;while(Math.max(opts.outWidth,opts.outHeight)/opts.inSampleSize>800)opts.inSampleSize*=2;Bitmap bitmap=BitmapFactory.decodeByteArray(data,0,data.length,opts);
            runOnUiThread(()->{if(!isDestroyed()&&revision==token)image.setImageBitmap(bitmap);else if(bitmap!=null)bitmap.recycle();});
        }catch(Exception ignored){runOnUiThread(()->{if(hideOnFailure&&!isDestroyed()&&revision==token)image.setVisibility(View.GONE);});}});
    }
    private final Runnable tick=new Runnable(){public void run(){if(!active)return;if(api.sessionExpired()){returnToLogin();return;}updateLive();if(!busy&&!polling){polling=true;network.execute(()->{
        try{
            boolean hadSends=hasSends();long nextSendsAt=System.currentTimeMillis();JSONObject nextSends=repo.sends();boolean slow=SystemClock.elapsedRealtime()-lastSlowRefresh>10000;Capabilities previousCaps=repo.capabilities;PreheatPresets previousPresets=preheatPresets;boolean previousPresetFailure=presetsFailed;String previousStock=filament.toString(),previousBadges=badges.toString(),previousLabelServer=labelServer,previousProjects=projects.toString();if(slow){repo.refreshCapabilities();lastSlowRefresh=SystemClock.elapsedRealtime();refreshExtras();if(route.equals("projects"))projects=repo.projects();}else{sends=nextSends;sendsAt=nextSendsAt;}boolean presetChanged=(previousPresets==null)!=(preheatPresets==null)||(previousPresets!=null&&!previousPresets.same(preheatPresets))||previousPresetFailure!=presetsFailed;boolean changed=slow&&(previousCaps==null||!previousCaps.sameAvailability(repo.capabilities)||!previousStock.equals(filament.toString())||!previousBadges.equals(badges.toString())||!previousLabelServer.equals(labelServer)||presetChanged||!previousProjects.equals(projects.toString()));boolean resolved=resolveJournal();changed|=hadSends!=hasSends();
            final boolean renderNeeded=changed||resolved;
            runOnUiThread(()->{polling=false;if(!isDestroyed()){if(renderNeeded)render();else updateLive();}});
        }catch(Exception caught){Exception ex=checkedUnauthorized(caught);runOnUiThread(()->{polling=false;if(ex instanceof FmApi.Unauthorized)returnToLogin();else if(!isDestroyed()){boolean had=hasInventory()||canPrint();repo.capabilities=null;if(had)render();showNotice(I18n.t("Не удалось обновить возможности FM."));}});}
    });}handler.postDelayed(this,2000);}};
    @Override protected void onStart(){super.onStart();if(api==null)return;active=true;startTelemetry();loadRoute();handler.postDelayed(tick,2000);autoRelayLicenses();}
    @Override protected void onStop(){active=false;streamGeneration++;handler.removeCallbacksAndMessages(null);if(telemetry!=null){telemetry.close();telemetry=null;}connected=false;receivedAt=0;super.onStop();}
    @Override public void onDestroy(){network.shutdown();images.shutdownNow();super.onDestroy();}
    @Override protected void onSaveInstanceState(Bundle out){out.putString("farm_previous_route",previousRoute);out.putString("farm_route",route);out.putString("farm_printer",selectedPrinter);out.putString("farm_project",selectedProject);out.putString("farm_project_name",projectName);out.putString("farm_printer_qr",pendingPrinterQr);super.onSaveInstanceState(out);}
}
