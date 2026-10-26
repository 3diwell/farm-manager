// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm;

import ru.threediwell.fm.i18n.I18n;
import android.app.AlertDialog;
import android.content.*;
import android.graphics.Color;
import android.os.Bundle;
import android.text.InputType;
import android.view.*;
import android.widget.*;
import ru.threediwell.fm.ui.FmActivity;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import org.json.*;
import ru.threediwell.fm.core.FmApi;
import ru.threediwell.fm.core.LicenseRelay;
import ru.threediwell.fm.core.PhoneLicenseRelay;
import ru.threediwell.fm.core.SessionRegistry;
import ru.threediwell.fm.farm.FarmRepository;
import ru.threediwell.fm.farm.MaterialSlots;
import ru.threediwell.fm.core.SavedSession;
import ru.threediwell.fm.core.RememberedLogin;
import ru.threediwell.fm.core.EncryptedSessionStore;
import ru.threediwell.fm.core.AuthCheck;
import ru.threediwell.fm.core.LoginRequest;
import ru.threediwell.fm.core.AppVersion;
import ru.threediwell.fm.inventory.*;
import ru.threediwell.fm.nfc.NfcReading;
import ru.threediwell.fm.ui.FmStyle;
import ru.threediwell.fm.ui.BrandHeader;
import ru.threediwell.fm.ui.OperationFlow;
import ru.threediwell.fm.ui.OperationHintView;
import ru.threediwell.fm.ui.intro.IntroModel;
import ru.threediwell.fm.ui.intro.LogoIntroView;
import ru.threediwell.fm.scan.ScanPolicy;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Consumer;

/** Application shell. Inventory is the first feature, not the application's identity. */
public class MainActivity extends FmActivity {
    private static final Object JOURNAL_LOCK=new Object();
    private LinearLayout page;
    private TextView status;
    private SharedPreferences preferences;
    private FmApi api;
    private InventoryRepository inventory;
    private volatile boolean inventoryWriteAllowed;
    private volatile String inventoryReadOnlyNotice="";
    private volatile boolean licenseAdmin;
    private boolean inventoryVisible;
    private final android.os.Handler moduleWatcher=new android.os.Handler(android.os.Looper.getMainLooper());
    private final ExecutorService network = Executors.newSingleThreadExecutor();
    /** GET /api/auth/status before sign-in: separate from network so a slow address never delays a login. */
    private final ExecutorService loginProbe = Executors.newSingleThreadExecutor();
    private final android.os.Handler restoreRetry=new android.os.Handler(android.os.Looper.getMainLooper());
    /** The "could not check the saved login" screen is shown and will retry by itself. */
    private boolean restoreRetryPending;
    private int loginScreenGeneration;
    private LoginRequest.Mode knownRememberMode=LoginRequest.Mode.EIGHT_HOURS;
    private String knownRememberOrigin="";
    private boolean busy;
    private Consumer<String> scanCallback;
    private Runnable cameraNfcCallback;
    private ActivityResultLauncher<Intent> scan;
    private ActivityResultLauncher<Intent> nfcScan;
    private Consumer<NfcReading> nfcCallback;
    private String location = "";
    private FmStyle style;
    private String section=I18n.t("Склад");
    private boolean loggedIn;
    private LogoIntroView launchIntro;
    private View preparedLogin;
    private boolean introCompleted;
    private boolean localSettingsOpen;
    private RememberedLogin rememberedLogin;
    private Runnable preparedConnectionResult;
    private ActivityResultLauncher<String> savePdf;
    private ActivityResultLauncher<Intent> farm;
    private ArrayList<LabelSheet.Entry> exportLabels=new ArrayList<>();
    @Override public void onCreate(Bundle state) {
        setTheme(FmStyle.theme(this));
        super.onCreate(state);
        style=new FmStyle(this);
        preferences = getSharedPreferences("fm-client", MODE_PRIVATE);
        rememberedLogin=new RememberedLogin(new EncryptedSessionStore(this));
        farm=registerForActivityResult(new ActivityResultContracts.StartActivityForResult(),result->{
            refreshPresentation();style=new FmStyle(this);
            String action=result.getData()==null?"":result.getData().getStringExtra("farm_action");
            if("login".equals(action)||SessionRegistry.get()==null){api=null;inventory=null;loggedIn=false;if(!busy)loginScreen();return;}
            if("inventory".equals(action))openInventory();
            else if(inventory!=null)home();else if(!busy)finish();
        });
        if(state!=null) location=state.getString("location","");
        try { JSONArray rows=new JSONArray(preferences.getString("export_labels","[]"));
            for(int i=0;i<rows.length();i++) { JSONObject e=rows.getJSONObject(i);exportLabels.add(new LabelSheet.Entry(e.getString("id"),e.getString("caption"),e.getString("code"))); }
        } catch(Exception ignored) {exportLabels.clear();}
        savePdf=registerForActivityResult(new ActivityResultContracts.CreateDocument("application/pdf"),uri -> {
            if(uri==null) {exportLabels.clear();preferences.edit().remove("export_labels").apply();return;}
            ArrayList<LabelSheet.Entry> snapshot=new ArrayList<>(exportLabels);
            task(I18n.t("Сохраняем PDF с ")+snapshot.size()+I18n.t(" этикетками…"),()-> {
                LabelSheet.validate(snapshot);
                try(java.io.OutputStream out=getContentResolver().openOutputStream(uri,"wt")) {
                    if(out==null) throw new java.io.IOException(I18n.t("Не удалось открыть выбранный файл"));
                    LabelPrinter.writeSheet(snapshot,out);
                }
                return snapshot.size();
            },count -> {exportLabels.clear();preferences.edit().remove("export_labels").apply();new AlertDialog.Builder(this).setTitle(I18n.t("PDF сохранён"))
                    .setMessage(I18n.t("Этикеток: ")+count+I18n.t(". Все QR находятся в одном файле. Печатайте на A4 в масштабе 100%."))
                    .setPositiveButton(I18n.t("Готово"),null).show();});
        });
        scan = registerForActivityResult(new ActivityResultContracts.StartActivityForResult(), result -> {
            Consumer<String> callback=scanCallback;Runnable nfcAlternative=cameraNfcCallback;
            scanCallback=null;cameraNfcCallback=null;
            if(result.getResultCode()==RESULT_OK&&result.getData()!=null&&result.getData().getBooleanExtra("nfc_requested",false)) {
                if(nfcAlternative!=null)nfcAlternative.run();
                else error(new Exception(I18n.t("Экран был пересоздан. Повторите выбор операции и чтение NFC.")));
            } else if (result.getResultCode() == RESULT_OK && result.getData() != null && callback != null) {
                try { callback.accept(Labels.normalize(result.getData().getStringExtra("code"))); }
                catch (Exception ex) { error(ex); }
            } else if (result.getResultCode() == RESULT_OK) {
                new AlertDialog.Builder(this).setMessage(I18n.t("Экран был пересоздан. Повторите сканирование; склад не изменён."))
                        .setPositiveButton(I18n.t("Понятно"), null).show();
            }
        });
        nfcScan=registerForActivityResult(new ActivityResultContracts.StartActivityForResult(),result->{
            Consumer<NfcReading> callback=nfcCallback;nfcCallback=null;
            if(result.getResultCode()!=RESULT_OK)return;
            try {
                if(callback==null||result.getData()==null)throw new Exception(I18n.t("Экран был пересоздан. Войдите в FM и повторите чтение; склад не изменён."));
                callback.accept(new NfcReading(new JSONObject(result.getData().getStringExtra("nfc_data"))));
            }catch(Exception ex){error(ex);}
        });
        introCompleted=!preferences.getBoolean("show_intro",true)
                ||(state!=null&&state.getBoolean("intro_completed",true));
        connectionScreen();
        if(!introCompleted) showLaunchIntro(state==null?0:state.getLong("intro_elapsed",0));
        restoreLogin();
        getOnBackPressedDispatcher().addCallback(this,new androidx.activity.OnBackPressedCallback(true) {
            @Override public void handleOnBackPressed() {
                if(launchIntro!=null){launchIntro.finish();return;}
                if(localSettingsOpen){loginScreen();return;}
                if(busy) return;
                if(loggedIn) new AlertDialog.Builder(MainActivity.this).setTitle(I18n.t("Вернуться на склад?"))
                        .setMessage(I18n.t("Незаполненная форма будет закрыта. Подтверждённые приёмки и незавершённые запросы сохранятся."))
                        .setPositiveButton(I18n.t("На главный экран"),(d,w)->home()).setNegativeButton(I18n.t("Остаться"),null).show();
                else finish();
            }
        });
    }
    private void showLaunchIntro(long elapsed) {
        try(java.io.InputStream input=getAssets().open("intro_v06.json")) {
            java.io.ByteArrayOutputStream bytes=new java.io.ByteArrayOutputStream();byte[] buffer=new byte[8192];int count;
            while((count=input.read(buffer))!=-1)bytes.write(buffer,0,count);
            IntroModel model=new IntroModel(bytes.toString("UTF-8"));
            FrameLayout content=findViewById(android.R.id.content);
            preparedLogin=content.getChildAt(0);
            launchIntro=new LogoIntroView(this,model,elapsed,this::finishLaunchIntro);
            preparedLogin.setVisibility(View.INVISIBLE);
            androidx.core.view.WindowCompat.setDecorFitsSystemWindows(getWindow(),false);
            getWindow().setStatusBarColor(launchIntro.backgroundColor());
            getWindow().setNavigationBarColor(android.os.Build.VERSION.SDK_INT>=27?launchIntro.backgroundColor():LogoIntroView.BACKGROUND);
            androidx.core.view.WindowInsetsControllerCompat bars=new androidx.core.view.WindowInsetsControllerCompat(getWindow(),launchIntro);
            bars.setAppearanceLightStatusBars(!FmStyle.isDark(this));bars.setAppearanceLightNavigationBars(!FmStyle.isDark(this));
            content.addView(launchIntro,new FrameLayout.LayoutParams(-1,-1));
            launchIntro.requestApplyInsets();
        } catch(Exception ex) {
            android.util.Log.w("FM.Intro","Skipping unavailable launch presentation",ex);
            finishLaunchIntro();
        }
    }
    private void finishLaunchIntro() {
        introCompleted=true;
        if(launchIntro!=null){launchIntro.dispose();if(launchIntro.getParent() instanceof ViewGroup)((ViewGroup)launchIntro.getParent()).removeView(launchIntro);launchIntro=null;}
        androidx.core.view.WindowCompat.setDecorFitsSystemWindows(getWindow(),true);
        if(preparedLogin!=null){preparedLogin.setVisibility(View.VISIBLE);style.systemBars(this,preparedLogin);preparedLogin.requestApplyInsets();preparedLogin=null;}
        if(preparedConnectionResult!=null){Runnable result=preparedConnectionResult;preparedConnectionResult=null;result.run();}
    }
    private void connectionScreen() {
        loggedIn=false;screen(I18n.t("Подключение к FM"));
        text(I18n.t("Проверяем сохранённый вход…")).setTextColor(style.muted);
    }
    private void afterIntro(Runnable result) {
        if(isDestroyed() || isFinishing()) return;
        if(!introCompleted) preparedConnectionResult=result; else result.run();
    }
    private void restoreLogin() {
        if(busy) return;
        busy=true;
        String origin=preferences.getString("origin","http://192.168.1.10:8000");
        network.execute(()-> {
            try {
                FmApi restored=rememberedLogin.restore(origin,System.currentTimeMillis());
                FmApi readyApi=restored;
                runOnUiThread(()->afterIntro(()-> {
                    busy=false;
                    if(readyApi!=null && readyApi.sessionExpired()) {
                        readyApi.clearSession();connectionScreen();restoreLogin();return;
                    }
                    if(readyApi==null) loginScreen();
                    else {api=readyApi;inventory=null;loggedIn=true;openFarm();}
                }));
            } catch(Exception ex) {
                runOnUiThread(()->afterIntro(()-> {
                    busy=false;
                    if(ex instanceof EncryptedSessionStore.Unavailable) {loginScreen();text(ex.getMessage()).setTextColor(style.warning);}
                    else restoreFailed(ex);
                }));
            }
        });
    }
    private void restoreFailed(Exception ex) {
        loggedIn=false;screen(I18n.t("Не удалось подключиться к FM"));
        text(preferences.getString("origin","")).setTextColor(style.muted);
        text(I18n.t("Проверка входа не завершена. При временной потере связи вводить пароль заново не нужно."));
        text(ex.getMessage()==null?I18n.t("Проверьте сеть и доступность FM."):ex.getMessage()).setTextColor(style.warning);
        // 503 (FM database busy), network errors and timeouts keep the saved login: check again by itself.
        long retryAfter=ex instanceof FmApi.ServerError?((FmApi.ServerError)ex).retryAfterSeconds:-1;
        long delaySeconds=Math.max(5,Math.min(60,retryAfter>0?retryAfter:15));
        TextView retryNote=text(I18n.t("Повторим проверку автоматически через ")+delaySeconds+I18n.t(" с."));retryNote.setTextSize(14);retryNote.setTextColor(style.muted);
        restoreRetryPending=true;scheduleRestoreRetry(delaySeconds*1000L);
        button(I18n.t("Повторить подключение"),()->{connectionScreen();restoreLogin();});
        button(I18n.t("Войти с другим аккаунтом или адресом"),()->task(I18n.t("Удаляем сохранённый вход…"),()->{
            rememberedLogin.forget();return true;
        },ok->loginScreen()));
    }
    private void scheduleRestoreRetry(long delayMillis) {
        restoreRetry.removeCallbacksAndMessages(null);
        restoreRetry.postDelayed(()->{
            if(!restoreRetryPending||busy||isDestroyed()||isFinishing())return;
            connectionScreen();restoreLogin();
        },delayMillis);
    }
    private int dp(int n) { return Math.round(n * getResources().getDisplayMetrics().density); }
    private void screen(String title) {
        localSettingsOpen=false;restoreRetryPending=false;restoreRetry.removeCallbacksAndMessages(null);loginScreenGeneration++;
        LinearLayout root=new LinearLayout(this);root.setOrientation(LinearLayout.VERTICAL);root.setBackgroundColor(style.bg);
        ScrollView scroll = new ScrollView(this); scroll.setFillViewport(true);
        page = new LinearLayout(this); page.setOrientation(LinearLayout.VERTICAL); page.setPadding(dp(20),dp(18),dp(20),dp(24));
        scroll.addView(page);root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));setContentView(root);style.systemBars(this,root);
        root.setOnApplyWindowInsetsListener((v, insets) -> {
            v.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(), insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });
        page.addView(new BrandHeader(this,style));
        TextView h = text(title); h.setTextSize(25);h.setTypeface(android.graphics.Typeface.create("sans-serif-medium",android.graphics.Typeface.NORMAL));
        status = text(""); status.setTextSize(14);status.setTextColor(style.accent);status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);status.setVisibility(View.GONE);
        if(loggedIn) {
            LinearLayout nav=new LinearLayout(this);style.navigationBar(nav);root.addView(nav);
            navItem(nav,I18n.t("Ферма"),"printer",this::openFarm);
            navItem(nav,I18n.t("Склад"),"warehouse",this::home);navItem(nav,I18n.t("Катушки"),"spool",this::spools);
            if(inventory!=null&&!inventory.server.isEmpty())navItem(nav,I18n.t("Этикетки"),"qr",this::batchesScreen);navItem(nav,I18n.t("Ещё"),"more",this::settingsScreen);
        }
    }
    private void navItem(LinearLayout nav,String title,String icon,Runnable action) {
        nav.addView(style.navigationItem(title,icon,title.equals(section),()->{if(!busy){try{action.run();}catch(Exception ex){error(ex);}}}));
    }
    private TextView text(String value) {
        TextView t = style.label(value,16,style.text); t.setPadding(0,dp(8),0,dp(8));t.setLineSpacing(dp(3),1); page.addView(t); return t;
    }
    private Button button(String caption, Runnable action) {
        Button b = new Button(this); b.setText(caption);style.button(b,false);page.addView(b);
        b.setOnClickListener(v -> { if (!busy) { try { action.run(); } catch(Exception ex) { error(ex); } } }); return b;
    }
    private LinearLayout action(String title,String subtitle,String icon,boolean primary,Runnable action) {
        LinearLayout row=style.actionCard(title,subtitle,icon,primary);page.addView(row);
        row.setOnClickListener(v->{if(!busy){try{action.run();}catch(Exception ex){error(ex);}}});return row;
    }
    private void contextCard(String title,String details,String icon) {
        LinearLayout card=style.actionCard(title,details,icon,false);card.setClickable(false);card.setFocusable(false);page.addView(card);
    }
    private void groupTitle(String title) {
        TextView t=text(title);t.setTextSize(12);t.setLetterSpacing(.08f);t.setTextColor(style.muted);t.setPadding(0,dp(18),0,dp(6));
    }
    private EditText field(String hint, String value, int type) {
        text(hint); EditText e = new EditText(this); e.setText(value); e.setInputType(type); e.setSingleLine(true);
        e.setTextColor(style.text);e.setTextSize(17);e.setPadding(dp(14),dp(12),dp(14),dp(12));e.setBackground(style.box(style.card,12));
        e.setMinHeight(dp(52)); page.addView(e); return e;
    }
    private Spinner spinner(List<String> labels) {
        Spinner s = new Spinner(this); s.setAdapter(new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, labels));
        s.setMinimumHeight(dp(56));s.setPopupBackgroundDrawable(style.box(style.card,8)); page.addView(s); return s;
    }
    private interface Work<T> { T run() throws Exception; }
    private <T> void task(String message, Work<T> work, Consumer<T> done) {
        if (busy) return; busy=true; status.setVisibility(View.VISIBLE);status.setTextColor(style.accent);status.setText(message);
        FmApi current=api;
        network.execute(() -> {
            try { T result = work.run(); runOnUiThread(() -> { busy=false; if (!isDestroyed()) { status.setText("");status.setVisibility(View.GONE); try { done.accept(result); } catch(Exception ex) { error(ex); } } }); }
            catch (Exception ex) {
                Exception shown=ex;
                if(ex instanceof FmApi.Unauthorized) {
                    // A 401 is not proof of revocation: FM answers it on a temporary failure too.
                    AuthCheck.Verdict verdict=current==null?AuthCheck.Verdict.SIGNED_OUT:AuthCheck.ask(current);
                    if(AuthCheck.shouldForget(verdict)) {
                        try { rememberedLogin.forget(); }
                        catch(Exception clearError) { ex.addSuppressed(clearError); }
                    }
                    shown=AuthCheck.afterUnauthorized(verdict,ex);
                }
                Exception result=shown;
                runOnUiThread(() -> { busy=false; if (!isDestroyed()) error(result); });
            }
        });
    }
    private void error(Exception ex) {
        if(ex instanceof FmApi.Unauthorized) {
            SessionRegistry.clear();if(api!=null)api.clearSession();inventory=null;loginScreen();
        }
        String message = ex.getMessage(); if (message == null || message.isEmpty()) message = I18n.t("Не удалось выполнить операцию");
        if(ex.getSuppressed().length>0) message+=I18n.t("\nНе удалось удалить сохранённый вход с телефона. Повторите выход при следующем подключении.");
        if (status != null) {status.setText(message);status.setTextColor(style.warning);status.setVisibility(View.VISIBLE);}
        new AlertDialog.Builder(this).setTitle(I18n.t("Операция не подтверждена")).setMessage(message).setPositiveButton(I18n.t("Понятно"), null).show();
    }
    private void loginScreen() {
        loggedIn=false;screen(I18n.t("Подключение к FM"));
        TextView intro=text(I18n.t("Подключитесь к той же сети, что и FM."));intro.setTextSize(14);intro.setTextColor(style.muted);
        EditText address = field(I18n.t("Адрес FM"), preferences.getString("origin", "http://192.168.1.10:8000"), InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_URI);
        EditText user = field(I18n.t("Пользователь FM"), "", InputType.TYPE_CLASS_TEXT);
        EditText password = field(I18n.t("Пароль"), "", InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_PASSWORD);
        password.setSaveEnabled(false);
        // The checkbox promises what this FM can do: remember_device >= 1 in GET /api/auth/status.
        LoginRequest.Mode[] shownMode={rememberModeFor(address.getText().toString())};
        CheckBox remember=new CheckBox(this);remember.setText(LoginRequest.checkboxText(shownMode[0]));remember.setTextColor(style.text);
        remember.setTextSize(16);remember.setMinHeight(dp(52));remember.setChecked(preferences.getBoolean("remember_login",false));page.addView(remember);
        TextView rememberHint=text(LoginRequest.hintText(shownMode[0]));rememberHint.setTextColor(style.muted);
        int generation=loginScreenGeneration;
        Runnable probe=()->probeRememberMode(generation,address.getText().toString(),mode->{
            shownMode[0]=mode;remember.setText(LoginRequest.checkboxText(mode));rememberHint.setText(LoginRequest.hintText(mode));
        });
        address.setOnFocusChangeListener((view,focused)->{if(!focused)probe.run();});
        address.addTextChangedListener(new android.text.TextWatcher(){
            public void beforeTextChanged(CharSequence text,int start,int count,int after){}
            public void onTextChanged(CharSequence text,int start,int before,int count){}
            public void afterTextChanged(android.text.Editable text){moduleWatcher.removeCallbacks(probe);moduleWatcher.postDelayed(probe,800);}
        });
        probe.run();
        TextView security=text(I18n.t("HTTP не шифрует вход и данные. Используйте только доверенную сеть фермы. Пароль не сохраняется. При включённой опции сеанс хранится на телефоне в зашифрованном виде."));
        security.setTextSize(14);security.setTextColor(style.muted);
        action(I18n.t("Подключиться"),"","check",true, () -> {
            FmApi next = new FmApi(address.getText().toString());
            String username = user.getText().toString().trim(), secret = password.getText().toString();
            boolean saveLogin=remember.isChecked();
            LoginRequest.Mode promised=shownMode[0];
            String deviceName=LoginRequest.deviceName(android.os.Build.MANUFACTURER,android.os.Build.MODEL);
            String[] saveWarning={null};
            password.setText("");
            task(I18n.t("Подключение к FM…"), () -> {
                rememberedLogin.forget();
                // Persist the address before the credential file, on this background worker.
                boolean connectionStored=preferences.edit().putString("origin",next.origin).putBoolean("remember_login",saveLogin).commit();
                JSONObject auth = next.call("GET", "/api/auth/status", null);
                // Remember the device only when the checkbox said so AND this FM still offers it.
                boolean rememberDevice=saveLogin && promised==LoginRequest.Mode.DEVICE && LoginRequest.mode(auth)==LoginRequest.Mode.DEVICE;
                JSONObject answer=null;
                if (auth.optBoolean("enabled")) answer=next.login(LoginRequest.body(username,secret,rememberDevice,deviceName));
                SavedSession saved=null;
                if(rememberDevice && LoginRequest.deviceNotStored(answer)) {
                    // FM could not store the permission and gave an ordinary session: do not pretend.
                    saveWarning[0]=I18n.t("FM не смог запомнить это устройство. Вход действует только до закрытия приложения.");
                } else if(saveLogin && auth.optBoolean("enabled")) {
                    try {saved=next.exportSession();}
                    catch(Exception ex){saveWarning[0]=I18n.t("FM не выдал сеанс для сохранения. Вход действует только до закрытия приложения.");}
                }
                if(saved!=null) {
                    try {
                        if(!connectionStored) throw new java.io.IOException(I18n.t("Адрес подключения не сохранён"));
                        rememberedLogin.save(saved);
                    }
                    catch(Exception ex){saveWarning[0]=I18n.t("Не удалось сохранить вход на телефоне. Вход действует только до закрытия приложения.");}
                }
                return true;
            }, ready -> {
                if (api != null) api.clearSession(); api=next; inventory=null;
                preferences.edit().putString("origin",api.origin).apply();loggedIn=true; openFarm();
                if(saveWarning[0]!=null) new AlertDialog.Builder(this).setTitle(I18n.t("Вход выполнен"))
                        .setMessage(saveWarning[0]).setPositiveButton(I18n.t("Понятно"),null).show();
            });
        });
        action(I18n.t("Проверка NFC"),I18n.t("Без входа в FM и изменений склада"),"nfc",false,()->startActivity(new Intent(this,NfcCheckActivity.class)));
        action(I18n.t("Настройки приложения"),I18n.t("Тема, язык и приветственный экран"),"settings",false,this::appSettingsScreen);
        if (preferences.contains("pending")) text(I18n.t("Есть операция с неподтверждённым результатом. После входа повторите её с тем же номером — дубликата не будет."));
        TextView footer=text(AppVersion.footer());footer.setTextSize(12);footer.setTextColor(style.muted);
        footer.setGravity(Gravity.CENTER);footer.setPadding(0,dp(20),0,0);
    }
    private LoginRequest.Mode rememberModeFor(String address) {
        try { return new FmApi(address).origin.equals(knownRememberOrigin)?knownRememberMode:LoginRequest.Mode.EIGHT_HOURS; }
        catch(RuntimeException ex) { return LoginRequest.Mode.EIGHT_HOURS; }
    }
    /** Reads remember_device of the typed FM without signing in. Stale answers are dropped. */
    private void probeRememberMode(int generation,String address,Consumer<LoginRequest.Mode> apply) {
        FmApi probe;
        try { probe=new FmApi(address); } catch(RuntimeException ex) { return; }
        loginProbe.execute(()->{
            LoginRequest.Mode mode;
            try { mode=LoginRequest.mode(probe.call("GET","/api/auth/status",null)); }
            catch(Exception ex) { return; }   // unknown: keep what the checkbox says now
            finally { probe.clearSession(); }
            LoginRequest.Mode result=mode;
            runOnUiThread(()->{
                knownRememberOrigin=probe.origin;knownRememberMode=result;
                if(!isDestroyed()&&generation==loginScreenGeneration)apply.accept(result);
            });
        });
    }
    private void openFarm() {
        if(api==null){loginScreen();return;}
        SessionRegistry.set(api);farm.launch(new Intent(this,FarmActivity.class));
    }
    private void openInventory() {
        section=I18n.t("Склад");screen(I18n.t("Склад фермы"));
        task(I18n.t("Обновление данных склада…"),()->{
            FarmRepository core=new FarmRepository(api);core.refreshCapabilities();
            core.requireInventory();
            inventoryWriteAllowed=core.capabilities.operate;inventoryReadOnlyNotice=core.capabilities.readOnlyNotice();licenseAdmin=core.capabilities.admin;
            InventoryRepository next=new InventoryRepository(api);next.refresh();return next;
        },next->{inventory=next;home();});
    }
    private void home() {
        if(inventory==null){openFarm();return;}
        section=I18n.t("Склад");screen(I18n.t("Склад фермы")); text(api.origin).setTextColor(style.muted);
        if (inventory.server.isEmpty()) {
            text(I18n.t("Склад доступен для чтения. Для мобильных операций обновите модуль «Складской учёт» в FM."));
        } else text(I18n.t("● Подключено к FM")).setTextColor(style.success);
        List<JSONObject> stock=inventory.rows(inventory.data,"spools");int installed=0;for(JSONObject s:stock)if(!s.optString("ams_printer_id").isEmpty())installed++;
        TextView summary=text(stock.size()+I18n.t(" катушек    /    ")+installed+I18n.t(" установлено"));summary.setBackground(style.box(style.card,12));summary.setPadding(dp(16),dp(16),dp(16),dp(16));
        if(!inventoryWriteAllowed&&!inventoryReadOnlyNotice.isEmpty())text(inventoryReadOnlyNotice).setTextColor(style.warning);
        if (preferences.contains("pending")) {
            text(I18n.t("Сначала завершите ранее отправленную операцию. При обрыве связи нельзя считать её отменённой."));
            if(inventoryWriteAllowed)button(I18n.t("Проверить / повторить незавершённую операцию"), this::resume);
        } else if(inventoryWriteAllowed && !inventory.server.isEmpty()) {
            groupTitle(I18n.t("БЫСТРЫЕ ОПЕРАЦИИ"));
            action(I18n.t("Принять на склад"),I18n.t("Полка → сканирование любого кода"),"receive",true, () -> { if (writable()) receiptLocation(); });
            action(inventory.supportsSlotExchange()?I18n.t("Установить / заменить"):I18n.t("Установить"),inventory.supportsNfc()?I18n.t("QR позиции → QR или NFC катушки"):I18n.t("QR позиции → QR катушки"),"printer",false, () -> { if (writable()) bindStart(); });
            groupTitle(I18n.t("ДРУГИЕ ДЕЙСТВИЯ"));
            if(inventory.supportsSlotExchange())action(I18n.t("Снять катушку"),inventory.supportsWriteOff()?I18n.t("Вернуть на склад или списать пустую"):I18n.t("Освободить позицию без списания"),"remove",false, () -> { if (exchangeAvailable()) unbindStart(); });
            if(inventory.supportsWriteOff())action(I18n.t("Списать катушку"),I18n.t("QR катушки → списание как пустой"),"discard",false,this::writeOffStart);
            if(inventory.supportsNfc())action(I18n.t("Привязать NFC к катушке"),I18n.t("Уже на складе · без повторного прихода"),"nfc",false,this::attachNfcStart);
        }
        if(!inventory.server.isEmpty())action(I18n.t("Этикетки и QR"),I18n.t("Подготовить, скачать или распечатать"),"qr",false,this::batchesScreen);
        button(I18n.t("Обновить данные"), () -> refresh(this::home));
    }
    private void introPreference() {
        Switch toggle=new Switch(this);
        toggle.setText(R.string.intro_setting_title);toggle.setTextColor(style.text);toggle.setTextSize(16);
        toggle.setMinHeight(dp(56));toggle.setPadding(0,dp(8),0,dp(8));toggle.setSwitchPadding(dp(16));
        toggle.setChecked(preferences.getBoolean("show_intro",true));
        toggle.setOnCheckedChangeListener((button,checked)->preferences.edit().putBoolean("show_intro",checked).apply());
        page.addView(toggle,new LinearLayout.LayoutParams(-1,-2));
        TextView hint=text(getString(R.string.intro_setting_hint));hint.setTextSize(14);hint.setTextColor(style.muted);
    }
    private void appSettingsScreen() {
        screen(I18n.t("Настройки приложения"));localSettingsOpen=true;appearancePreferences();introPreference();
        button(I18n.t("К подключению"),this::loginScreen);
    }
    private void appearancePreferences() {
        groupTitle(I18n.t("ОФОРМЛЕНИЕ И ЯЗЫК"));
        action(I18n.t("Тема оформления"),FmStyle.isDark(this)?I18n.t("Тёмная"):I18n.t("Светлая"),"settings",false,()->
                new AlertDialog.Builder(this).setTitle(I18n.t("Тема оформления"))
                        .setSingleChoiceItems(new String[]{I18n.t("Тёмная"),I18n.t("Светлая")},FmStyle.isDark(this)?0:1,(dialog,which)-> {
                            preferences.edit().putBoolean("dark",which==0).apply();dialog.dismiss();redrawSettings();
                        }).setNegativeButton(I18n.t("Отмена"),null).show());
        action(I18n.t("Язык приложения"),I18n.language().equals("en")?"English":"Русский","settings",false,()->
                new AlertDialog.Builder(this).setTitle(I18n.t("Язык приложения"))
                        .setSingleChoiceItems(new String[]{"Русский","English"},I18n.language().equals("en")?1:0,(dialog,which)-> {
                            preferences.edit().putString("language",which==1?"en":"ru").apply();dialog.dismiss();redrawSettings();
                        }).setNegativeButton(I18n.t("Отмена"),null).show());
        text(I18n.t("Тема и язык сохраняются и применяются ко всем экранам приложения.")).setTextColor(style.muted);
    }
    private void redrawSettings() {
        refreshPresentation();style=new FmStyle(this);
        if(loggedIn)settingsScreen();else appSettingsScreen();
    }
    private void settingsScreen() {
        section=I18n.t("Ещё");screen(I18n.t("Настройки и метки"));
        appearancePreferences();introPreference();
        action(I18n.t("Проверка NFC"),I18n.t("Диагностика метки катушки — только чтение"),"nfc",false,()->startActivity(new Intent(this,NfcCheckActivity.class)));
        if(inventoryWriteAllowed&&!inventory.server.isEmpty())action(I18n.t("QR позиций принтеров"),I18n.t("AMS / CFS / внешний держатель"),"qr",false, () -> { if (writable()) positions(); });
        if(licenseAdmin)action(I18n.t("Лицензии модулей: отметить через этот телефон"),I18n.t("Когда у компьютера фермы нет интернета"),"check",false,this::relayLicenses);
        text(AppVersion.withOrigin(api.origin)).setTextColor(style.muted);
        button(I18n.t("Другие разделы FM"), this::openFarm);
        button(I18n.t("Выйти"), () -> task(I18n.t("Завершение сеанса…"), () -> {
            rememberedLogin.forget();
            try { api.call("POST", "/api/auth/logout", new JSONObject()); }
            catch(Exception ignored) { /* Forget local credentials even when the server is unreachable. */ }
            finally { SessionRegistry.clear();api.clearSession(); }
            return true;
        }, ok -> loginScreen()));
    }
    /** Лицензии модулей через этот телефон (как страница FM в браузере): по кнопке — с итогом в окне. */
    private void relayLicenses() {
        task(I18n.t("Отмечаем лицензии через этот телефон…"),()->{
            FarmRepository core=new FarmRepository(api);core.refreshCapabilities();licenseAdmin=core.capabilities.admin;
            if(!licenseAdmin)throw new java.io.IOException(I18n.t("У пользователя нет права на эту операцию в FM."));
            return PhoneLicenseRelay.runNow(this,api);
        },result->{
            String text=PhoneLicenseRelay.message(result,true);if(text==null)return;
            new AlertDialog.Builder(this).setTitle(I18n.t("Лицензии модулей")).setMessage(text).setPositiveButton(I18n.t("Понятно"),null).show();
        });
    }
    private void autoRelayLicenses() {
        if(!loggedIn||api==null||api.sessionExpired())return;
        PhoneLicenseRelay.auto(this,api,result->{
            if(!inventoryVisible||isDestroyed()||busy||status==null)return;
            String text=PhoneLicenseRelay.message(result,false);if(text==null)return;
            status.setText(I18n.t("Лицензии модулей")+"\n"+text);status.setTextColor(LicenseRelay.warning(result)?style.warning:style.success);status.setVisibility(View.VISIBLE);
        });
    }
    private boolean writable() {
        if(!inventoryWriteAllowed){error(new Exception(I18n.t("У пользователя нет права на эту операцию в FM.")));return false;}
        if (inventory.server.isEmpty()) { error(new Exception(I18n.t("Для мобильных операций обновите модуль «Складской учёт» в FM."))); return false; }
        return true;
    }
    private boolean exchangeAvailable() {
        if (!writable()) return false;
        if (!inventory.supportsSlotExchange()) { error(new Exception(I18n.t("Для снятия и замены обновите модуль склада до мобильной версии 0.2. Обычная приёмка и привязка остаются доступны."))); return false; }
        return true;
    }
    private void refresh(Runnable done) { task(I18n.t("Обновление данных склада…"), () -> { inventory.refresh(); return true; }, ok -> done.run()); }
    private boolean nfcAvailable() {
        if(!writable())return false;
        if(preferences.contains("pending")){error(new Exception(I18n.t("Сначала завершите ранее отправленную операцию на главном экране.")));return false;}
        if(!inventory.supportsNfc()){error(new Exception(I18n.t("Для NFC установите обновление модуля склада 0.7. Приёмка по QR и остальные операции остаются доступны.")));return false;}
        return true;
    }
    private void readNfc(Consumer<NfcReading> callback) {
        readNfc(callback,OperationFlow.NONE);
    }
    private void readNfc(Consumer<NfcReading> callback,OperationFlow flow) {
        if(!nfcAvailable())return;
        nfcCallback=callback;nfcScan.launch(new Intent(this,BambuReadActivity.class).putExtra("warehouse_read",true).putExtra(OperationFlow.EXTRA,flow.name()));
    }
    private void operationHint(OperationFlow flow,boolean scanning) {
        page.addView(new OperationHintView(this,style,flow,scanning));
    }
    private View confirmationHint(OperationFlow flow,String message) {
        // Keep the illustration and all operation details reachable on short screens / large fonts.
        ScrollView scroll=new ScrollView(this);
        LinearLayout content=new LinearLayout(this);content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(style.dp(20),style.dp(8),style.dp(20),style.dp(12));
        content.addView(new OperationHintView(this,style,flow,false));
        TextView details=style.label(message,16,style.text);details.setLineSpacing(style.dp(3),1);
        content.addView(details,new LinearLayout.LayoutParams(-1,-2));
        scroll.addView(content);return scroll;
    }
    private void operationConfirmed(JSONObject pending) {
        operationHint(OperationFlow.fromRequest(pending.optString("path"),pending.optJSONObject("body")),false);
        page.addView(OperationHintView.confirmed(this,style));
    }
    private void receiptScan(String title) {
        screen(I18n.t("Принять на склад"));contextCard(preparedPlaceName(location),I18n.t("Место приёмки · можно изменить ниже"),"receive");
        operationHint(OperationFlow.RECEIVE,true);
        text(I18n.t("Ваш подготовленный QR → сразу на склад. Заводской код или текст → проверка карточки.")).setTextColor(style.muted);
        action(I18n.t("Сканировать"),I18n.t("Любой QR, штрихкод или текст этикетки"),"scan",true,()->scanReceiptCamera());
        if(inventory.supportsNfc())action(I18n.t("Считать NFC Bambu"),I18n.t("Приложите телефон к катушке"),"nfc",false,this::receiptNfc);
        button(I18n.t("Ввести код вручную"),()->readCode(title,"",code->refresh(()->receiveCode(code)),ScanPolicy.SPOOL,OperationFlow.RECEIVE));
        button(I18n.t("Сменить полку"),this::receiptLocation);
    }
    private void scanReceiptCamera() {
        launchCamera(I18n.t("Приёмка · ")+preparedPlaceName(location)+I18n.t("\nГотовый QR принимается сразу"),code->refresh(()->receiveCode(code)),this::receiptNfc,ScanPolicy.SPOOL,OperationFlow.RECEIVE);
    }
    private void receiptNfc() {
        readNfc(tag->refresh(()->{
            JSONObject existing=inventory.nfcSpool(tag.uid);
            if(existing!=null){spoolDetails(existing.optString("id"));text(I18n.t("Эта NFC-метка уже принята. Нового прихода нет.")).setTextColor(style.accent);return;}
            receiptForm(NfcReading.code(tag.uid),tag);
        }),OperationFlow.RECEIVE);
    }
    private void receiveCode(String code) {
        try {
            InventoryRepository.ReceiptTarget target=inventory.receiptTarget(code);
            switch(target.kind()) {
                case "prepared" -> send("/api/mod/inventory/spool",inventory.automaticClaimRequest(code,location),"receipt_scan");
                case "existing" -> {
                    screen(I18n.t("Катушка уже на складе"));text(spoolTitle(inventory.spool(target.spoolId())));
                    text(I18n.t("Повторного прихода нет. Остаток и место хранения не изменены."));receiptContinue(location);
                }
                default -> receiptForm(code);
            }
        }catch(Exception ex){error(ex);}
    }
    private void receiptContinue(String place) {
        action(I18n.t("Сканировать следующую"),I18n.t("Та же полка · любая партия или заводской код"),"scan",true,()->{
            location=place;receiptScan(I18n.t("Приёмка · ")+preparedPlaceName(place));
            scanReceiptCamera();
        });
        button(I18n.t("Сменить полку"),this::receiptLocation);
        button(I18n.t("Завершить приёмку"),()->refresh(this::home));
    }
    private void spoolDetails(String sid) {
        JSONObject s=inventory.spool(sid);screen(I18n.t("Карточка катушки"));text(spoolTitle(s));
        if(!inventory.server.isEmpty())button(I18n.t("Показать / напечатать QR"),()->showLabel(spoolTitle(s),Labels.spool(inventory.server,sid)));
        if(inventoryWriteAllowed&&inventory.supportsNfc())action(I18n.t("Привязать NFC"),I18n.t("Без изменения материала и остатка"),"nfc",false,()->readNfc(tag->refresh(()->confirmNfcAttach(sid,tag))));
        JSONObject mobile=inventory.data.optJSONObject("mobile");
        if(mobile!=null)for(JSONObject r:inventory.rows(mobile,"nfc_tags"))if(sid.equals(r.optString("spool_id")))text("NFC: "+r.optString("uid"));
        button(I18n.t("Назад к катушкам"),this::spools);
    }
    private void attachNfcStart() {
        if(!nfcAvailable())return;
        readCode(I18n.t("Привязка NFC · QR существующей катушки"),I18n.t("Используйте собственный QR FM уже принятой катушки. Либо выберите её в разделе «Катушки»."),raw->refresh(()->{
            Labels.Label label=Labels.parse(raw,inventory.server);
            if(!label.kind().equals("spool"))throw new IllegalArgumentException(I18n.t("Нужен собственный QR катушки, не позиции и не общий товарный код."));
            spoolDetails(label.id());
        }));
        button(I18n.t("Выбрать в списке катушек"),this::spools);
    }
    private void confirmNfcAttach(String sid,NfcReading tag) {
        try {
            if(!nfcAvailable())return;
            JSONObject s=inventory.spool(sid),owner=inventory.nfcSpool(tag.uid);
            if(owner!=null&&!sid.equals(owner.optString("id")))throw new Exception(I18n.t("Эта NFC-метка уже связана с другой катушкой. Перенос и объединение запрещены."));
            JSONObject body=inventory.nfcAttachRequest(sid,tag.uid);
            new AlertDialog.Builder(this).setTitle(I18n.t("Связать NFC с этой катушкой?"))
                    .setMessage(I18n.t("Карточка FM:\n")+spoolTitle(s)+I18n.t("\n\nПрочитано из метки:\n")+tag.caption()
                            +I18n.t("\n\nСверьте материал, цвет и диаметр. При несовпадении отмените операцию. Изменится только связь NFC: остаток, материал, полка, QR и установка на принтер останутся прежними."))
                    .setPositiveButton(I18n.t("Это та же катушка — связать"),(d,w)->send("/api/mod/inventory/spool",body)).setNegativeButton(I18n.t("Отмена"),null).show();
        }catch(Exception ex){error(ex);}
    }
    private void readCode(String title, Consumer<String> callback) {
        readCode(title,"",callback);
    }
    private void readCode(String title, String details, Consumer<String> callback) {
        readCode(title,details,callback,ScanPolicy.SPOOL);
    }
    private void readCode(String title,String details,Consumer<String> callback,String scanKind) {
        readCode(title,details,callback,scanKind,OperationFlow.NONE);
    }
    private void readCode(String title,String details,Consumer<String> callback,String scanKind,OperationFlow flow) {
        screen(title); text(ScanPolicy.SLOT.equals(scanKind)?I18n.t("Выберите слот AMS / CFS или внешний держатель по его QR."):I18n.t("Можно сканировать заводской штрихкод, QR или ввести код с этикетки."));
        if(title.startsWith(I18n.t("Приёмка")))text(I18n.t("ШАГ 2 / 3 · СКАНИРОВАНИЕ")).setTextColor(style.accent);
        if(!details.isEmpty()) text(details);
        operationHint(flow,false);
        action(I18n.t("Открыть камеру"),ScanPolicy.SLOT.equals(scanKind)?I18n.t("Прицел → проверка названия → выбор слота"):I18n.t("QR, штрихкод или текст этикетки"),"scan",true, () -> launchCamera(title,callback,null,scanKind,flow));
        EditText raw = field(ScanPolicy.SLOT.equals(scanKind)?I18n.t("QR позиции — ручной ввод"):I18n.t("Код / SKU / индивидуальный ID"), "", InputType.TYPE_CLASS_TEXT);
        button(I18n.t("Использовать введённый код"), () -> callback.accept(Labels.normalize(raw.getText().toString())));
        button(I18n.t("На главный экран"), this::home);
    }
    private void launchCamera(String title,Consumer<String> callback) {
        launchCamera(title,callback,null);
    }
    private void launchCamera(String title,Consumer<String> callback,Runnable nfcAlternative) {
        launchCamera(title,callback,nfcAlternative,ScanPolicy.SPOOL);
    }
    private void launchCamera(String title,Consumer<String> callback,Runnable nfcAlternative,String scanKind) {
        launchCamera(title,callback,nfcAlternative,scanKind,OperationFlow.NONE);
    }
    private void launchCamera(String title,Consumer<String> callback,Runnable nfcAlternative,String scanKind,OperationFlow flow) {
        if(inventory!=null&&!inventory.supportsNfc())nfcAlternative=null;
        if(preferences.contains("pending")){error(new Exception(I18n.t("Сначала завершите ранее отправленную операцию.")));return;}
        try {
            JSONArray catalog=new JSONArray();
            if(!ScanPolicy.SPOOL.equals(scanKind))for(JSONObject p:inventory.rows(inventory.ams,"printers"))for(JSONObject s:inventory.rows(p,"slots")) {
                if(s.optBoolean("offline")||s.optBoolean("unconfirmed"))continue;
                JSONObject current=s.optJSONObject("spool");
                String caption=p.optString("printer_name")+" · "+slotName(s)+"\n"+(current==null?I18n.t("Свободно по данным FM"):I18n.t("Сейчас: ")+InventoryRepository.title(current));
                catalog.put(new JSONObject().put("code",Labels.slot(inventory.server,p.optString("printer_id"),s.optInt("index",-99))).put("caption",caption));
            }
            String catalogText=catalog.toString();
            if(catalogText.length()>120000)throw new IllegalArgumentException(I18n.t("Слишком много позиций для камеры. Используйте ручной ввод."));
            scanCallback=callback;cameraNfcCallback=nfcAlternative;
            scan.launch(new Intent(this,ScannerActivity.class).putExtra("purpose",title).putExtra("allow_nfc",nfcAlternative!=null)
                    .putExtra("scan_kind",scanKind).putExtra("server_id",inventory.server).putExtra("slot_catalog",catalogText).putExtra(OperationFlow.EXTRA,flow.name()));
        }catch(Exception e){scanCallback=null;cameraNfcCallback=null;error(e);}
    }
    private void receiptLocation() {
        refresh(() -> {
            screen(I18n.t("Куда принимаем?"));text(I18n.t("ШАГ 1 / 3 · МЕСТО ХРАНЕНИЯ")).setTextColor(style.accent);
            List<JSONObject> rows=inventory.rows(inventory.places,"locations");
            if (rows.isEmpty()) { text(I18n.t("Сначала создайте место хранения в FM.")); button(I18n.t("Назад"),this::home); return; }
            for (JSONObject r:rows) button(locationName(r,rows), () -> {
                location=r.optString("id");
                receiptScan(I18n.t("Приёмка · ") + locationName(r,rows));
            });
            button(I18n.t("Назад"),this::home);
        });
    }
    private String locationName(JSONObject r,List<JSONObject> rows) {
        String value=r.optString("name"), parent=r.optString("parent_id"); Set<String> seen=new HashSet<>();
        while (!parent.isEmpty() && seen.add(parent)) {
            JSONObject match=null; for(JSONObject p:rows) if(p.optString("id").equals(parent)) {match=p;break;}
            if(match==null) break; value=match.optString("name")+" / "+value; parent=match.optString("parent_id");
        }
        return value;
    }
    private void receiptForm(String code) {
        receiptForm(code,null);
    }
    private void receiptForm(String code,NfcReading tag) {
        if (code.startsWith("fm1:")) { receiveCode(code); return; }
        JSONObject mapped=inventory.mapping(code);
        if(mapped!=null && mapped.optString("kind").equals("unique")) { error(new Exception(I18n.t("Катушка с этим кодом уже принята."))); return; }
        screen(I18n.t("Проверьте катушку"));text(I18n.t("ШАГ 3 / 3 · ПОДТВЕРЖДЕНИЕ")).setTextColor(style.accent);text(I18n.t("Код: ")+code);
        operationHint(OperationFlow.RECEIVE,false);
        List<JSONObject> items=inventory.rows(inventory.data,"filaments"); List<String> titles=new ArrayList<>(); titles.add(I18n.t("Новый материал — заполнить ниже"));
        for(JSONObject f:items) titles.add(InventoryRepository.title(f));
        text(I18n.t("Товар / материал")); Spinner product=spinner(titles);
        if(mapped!=null) { for(int i=0;i<items.size();i++) if(items.get(i).optString("id").equals(mapped.optString("filament_id"))) product.setSelection(i+1); product.setEnabled(false); }
        text(I18n.t("Тип заводского кода")); Spinner kind=spinner(Arrays.asList(I18n.t("Общий код товара (EAN / UPC / SKU)"),I18n.t("Уникальный код именно этой катушки")));
        if(mapped!=null) kind.setEnabled(false);
        text(tag!=null?I18n.t("NFC используется как индивидуальная метка катушки, не как общий код товара."):Labels.productBarcode(code) ? I18n.t("Контрольная цифра товарного штрихкода корректна.") : I18n.t("Тип кода автоматически не установлен. QR может быть общим для товара — проверьте этикетку."));
        int newFieldsStart=page.getChildCount();
        EditText vendor=field(I18n.t("Для нового материала: производитель"), "",InputType.TYPE_CLASS_TEXT);
        EditText material=field(I18n.t("Материал (PLA / PETG / …)"),"",InputType.TYPE_CLASS_TEXT);
        EditText color=field(I18n.t("Цвет"), "",InputType.TYPE_CLASS_TEXT);
        EditText diameter=field(I18n.t("Диаметр, мм — проверьте 1,75 или 2,85"), "1.75",InputType.TYPE_CLASS_NUMBER|InputType.TYPE_NUMBER_FLAG_DECIMAL);
        EditText nfcHex=tag==null?null:field(I18n.t("Основной цвет HEX (для образца цвета в FM)"),"#"+tag.rgba.substring(0,6),InputType.TYPE_CLASS_TEXT);
        List<View> newFields=new ArrayList<>();for(int i=newFieldsStart;i<page.getChildCount();i++)newFields.add(page.getChildAt(i));
        product.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            public void onItemSelected(AdapterView<?> parent,View view,int position,long id) {for(View v:newFields)v.setVisibility(position==0?View.VISIBLE:View.GONE);}
            public void onNothingSelected(AdapterView<?> parent) {}
        });
        for(View v:newFields)v.setVisibility(product.getSelectedItemPosition()==0?View.VISIBLE:View.GONE);
        EditText weight=field(I18n.t("Масса филамента новой полной катушки, г"), "1000",InputType.TYPE_CLASS_NUMBER|InputType.TYPE_NUMBER_FLAG_DECIMAL);
        EditText label=field(I18n.t("Подпись катушки (необязательно)"), "",InputType.TYPE_CLASS_TEXT);
        if(tag!=null) {
            kind.setSelection(1);kind.setEnabled(false);
            vendor.setText("Bambu Lab");material.setText(tag.variant);color.setText("#"+tag.rgba.substring(0,6));
            diameter.setText(String.format(Locale.ROOT,"%.3f",tag.diameter));weight.setText(Integer.toString(tag.weight));
            text("NFC: "+tag.uid+I18n.t("\nПрочитано: ")+tag.caption()+I18n.t("\nЗаводская масса: ")+tag.weight+I18n.t(" г. Это НЕ текущий остаток. Цвет указан кодом из метки; его название можно уточнить вручную. Выберите существующий материал или проверьте поля нового. Подлинность метки не проверена."));
            text(I18n.t("Если эта катушка уже внесена по QR, отмените приёмку и используйте «Привязать NFC к катушке». По цвету и материалу существующая катушка автоматически не определяется."));
        }
        text(I18n.t("Приёмка предназначена для новых полных катушек. Для начатой катушки используйте редактирование остатка в FM. Общий код товара не заменяет индивидуальный QR."));
        action(I18n.t("Принять 1 катушку"),I18n.t("QR попадёт в текущую партию"),"receive",true, () -> {
            try {
                double grams=Double.parseDouble(weight.getText().toString().replace(',','.'));
                if(!Double.isFinite(grams)||grams<=0||grams>100000) throw new IllegalArgumentException(I18n.t("Укажите массу от 0 до 100000 г, больше нуля"));
                JSONObject d=new JSONObject().put("mobile",tag==null?inventory.envelope(code,kind.getSelectedItemPosition()==0?"product":"unique"):inventory.nfcEnvelope("nfc_receipt",tag.uid))
                        .put("location",location).put("weight_total_g",grams).put("label",label.getText().toString());
                if(product.getSelectedItemPosition()>0) d.put("filament_id",items.get(product.getSelectedItemPosition()-1).optString("id"));
                else d.put("filament",new JSONObject().put("vendor_name",vendor.getText().toString()).put("material",material.getText().toString())
                        .put("color_name",color.getText().toString()).put("diameter",Double.parseDouble(diameter.getText().toString().replace(',','.'))));
                if(tag!=null&&d.has("filament")) {
                    String hex=nfcHex.getText().toString().trim();
                    if(!hex.matches("#[0-9a-fA-F]{6}"))throw new IllegalArgumentException(I18n.t("Укажите цвет в виде #FF671F"));
                    d.getJSONObject("filament").put("color_hex",hex);
                }
                send("/api/mod/inventory/spool",d);
            } catch(Exception ex) { error(ex); }
        });
        button(I18n.t("Отмена"),this::home);
    }
    private void bindStart() {
        refresh(() -> readCode(I18n.t("1 / 2 · Выберите позицию"), I18n.t("Наведите прицел на нужный QR слота AMS / CFS или внешнего держателя. Проверьте название перед выбором."),code -> {
            Labels.Label target=Labels.parse(code,inventory.server);
            if(!target.kind().equals("slot")) throw new IllegalArgumentException(I18n.t("Сначала отсканируйте QR позиции принтера"));
            refresh(() -> printerSlots(target));
        },ScanPolicy.SLOT,OperationFlow.SELECT_PRINTER));
    }
    private void printerSlots(Labels.Label scanned) {
        inventory.position(scanned);
        screen(I18n.t("Выберите слот принтера"));
        for(JSONObject printer:inventory.rows(inventory.ams,"printers"))if(printer.optString("printer_id").equals(scanned.id())) {
            text(printer.optString("printer_name"));
            for(JSONObject slot:inventory.rows(printer,"slots"))if(!slot.optBoolean("offline")&&!slot.optBoolean("unconfirmed")) {
                Labels.Label target=new Labels.Label("slot",inventory.server,scanned.id(),slot.optInt("index",-99));
                JSONObject spool=slot.optJSONObject("spool");
                button(slotName(slot)+" · "+(spool==null?I18n.t("Позиция свободна."):spoolTitle(spool)),()->refresh(()->slotActions(target)));
            }
        }
        button(I18n.t("Назад"),this::home);
    }
    private void slotActions(Labels.Label target) {
        JSONObject current=inventory.position(target).optJSONObject("spool");
        if(current==null){chooseSlotAction(target,"",false);return;}
        screen(I18n.t("Замена катушки"));contextCard(targetCaption(target),I18n.t("Сейчас установлена:\n")+spoolTitle(current),"printer");
        if(!inventory.supportsSlotExchange()){button(I18n.t("Назад"),this::home);return;}
        text(I18n.t("Что сделать со старой катушкой? После выбора отсканируйте новую. Изменения сохранятся только после подтверждения замены."));
        String oldId=current.optString("id");
        action(I18n.t("Вернуть на склад"),I18n.t("Сохранить остаток старой катушки"),"warehouse",true,()->chooseSlotAction(target,oldId,false));
        if(inventory.supportsReplaceWriteOff())action(I18n.t("Списать как пустую"),I18n.t("Обнулить остаток и убрать старую катушку из активного склада"),"discard",false,()->chooseSlotAction(target,oldId,true));
        button(I18n.t("Снять текущую катушку без замены"),()->refresh(()->confirmUnbind(oldId)));
        button(I18n.t("Назад"),()->refresh(()->printerSlots(target)));
    }
    private void chooseSlotAction(Labels.Label target,String oldId,boolean discard) {
        refresh(()->{
            try {startSlotScan(inventory.selectSlot(target,oldId,discard));}
            catch(Exception ex){error(ex);}
        });
    }
    private void startSlotScan(InventoryRepository.SlotSelection choice) {
        Labels.Label target=choice.target();
        screen(I18n.t("2 / 2 · Выберите катушку"));contextCard(targetCaption(target),I18n.t("Позиция выбрана · установка ещё не выполнена"),"printer");
        operationHint(OperationFlow.INSTALL,true);
        if(!choice.expectedSpoolId().isEmpty())text((choice.discard()?I18n.t("Списать как пустую"):I18n.t("Вернуть на склад"))+" · "+spoolTitle(inventory.spool(choice.expectedSpoolId())));
        text(I18n.t("Сканирование позиции ничего не меняет. Замена выполняется только после выбора новой катушки и подтверждения."));
        button(I18n.t("Сканировать новую катушку"),()->launchCamera(I18n.t("Катушка → ")+targetCaption(target),raw->refresh(()->bindChoose(choice,raw)),()->slotNfc(choice),ScanPolicy.SPOOL,OperationFlow.INSTALL));
        button(I18n.t("Ввести код катушки вручную"),()->readCode(I18n.t("Установка · ")+targetCaption(target),"",raw->refresh(()->bindChoose(choice,raw)),ScanPolicy.SPOOL,OperationFlow.INSTALL));
        if(inventory.supportsNfc())action(I18n.t("Считать NFC катушки"),I18n.t("Установка или замена после подтверждения"),"nfc",false,()->slotNfc(choice));
        button(I18n.t("Назад"),()->refresh(()->printerSlots(target)));
        launchCamera(I18n.t("Сканируйте катушку → ")+targetCaption(target),raw->refresh(()->bindChoose(choice,raw)),()->slotNfc(choice),ScanPolicy.SPOOL,OperationFlow.INSTALL);
    }
    private void slotNfc(InventoryRepository.SlotSelection choice) {
        readNfc(tag->refresh(()->{
            JSONObject s=inventory.nfcSpool(tag.uid);
            if(s==null)throw new IllegalArgumentException(I18n.t("Эта NFC-метка ещё не связана со складом. Примите новую катушку либо привяжите NFC к уже существующей. Затем повторите установку."));
            confirmBind(choice,s.optString("id"),NfcReading.code(tag.uid));
        }),OperationFlow.INSTALL);
    }
    private String targetCaption(Labels.Label target) {
        for(JSONObject p:inventory.rows(inventory.ams,"printers")) if(p.optString("printer_id").equals(target.id())) {
            for(JSONObject s:inventory.rows(p,"slots")) if(s.optInt("index",-99)==target.slot() && !s.optBoolean("unconfirmed") && !s.optBoolean("offline"))
                return p.optString("printer_name")+" · "+slotName(s);
        }
        throw new IllegalArgumentException(I18n.t("Позиция отсутствует или не подтверждена. Обновите данные FM."));
    }
    private String slotName(JSONObject s) {
        if(s.optInt("index",-99)==-1&&s.optString("ext_side").isEmpty()) return I18n.t("Внешний держатель");
        return MaterialSlots.positionName(s);
    }
    private void bindChoose(InventoryRepository.SlotSelection choice,String raw) {
        Labels.Label target=choice.target();
        List<JSONObject> matches=inventory.findSpools(raw);
        if(matches.isEmpty()) { error(new Exception(I18n.t("Катушка не найдена. Сначала примите её на склад или используйте её собственный QR."))); return; }
        if(matches.size()==1){confirmBind(choice,matches.get(0).optString("id"),raw);return;}
        screen(I18n.t("Установка · выбор катушки")); text(targetCaption(target));
        operationHint(OperationFlow.INSTALL,false);
        if(matches.size()>1) text(I18n.t("Код общий для нескольких катушек. Выберите конкретную по подписи, месту и остатку. Для однозначного сканирования наклейте собственный QR."));
        for(JSONObject s:matches) button(spoolTitle(s), () -> {
            refresh(() -> confirmBind(choice,s.optString("id"),raw));
        });
        button(I18n.t("Назад"),this::home);
    }
    private void confirmBind(InventoryRepository.SlotSelection choice,String sid,String raw) {
        Labels.Label target=choice.target();
        try {
            inventory.validateSelection(choice);
            JSONObject s=inventory.spool(sid), old=inventory.position(target).optJSONObject("spool");
            if(s.optBoolean("pending") || (old!=null && old.optBoolean("pending"))) throw new Exception(I18n.t("Катушка участвует в незавершённой печати"));
            if(old!=null && old.optString("id").equals(sid)) throw new Exception(I18n.t("Эта катушка уже установлена в выбранной позиции. Ничего менять не нужно."));
            if(!s.optString("ams_printer_id").isEmpty()) throw new Exception(I18n.t("Новая катушка установлена в другом месте. Сначала снимите её через «Снять катушку с принтера»."));
            boolean replace=old!=null;
            if(replace && !exchangeAvailable()) return;
            JSONObject body=choice.discard()?inventory.replaceWriteOffRequest(choice,sid):inventory.supportsSlotExchange()
                    ? inventory.slotRequest(target,replace?"replace":"bind",choice.expectedSpoolId())
                    : new JSONObject().put("mobile",inventory.envelope(raw,"unique")).put("printer_id",target.id()).put("ams_slot",target.slot()).put("external",target.slot()==-1);
            String message=targetCaption(target)+"\n\n"+(replace?I18n.t("Снять:\n")+spoolTitle(old)+"\n\n":"")+I18n.t("Установить:\n")+spoolTitle(s)
                    +(choice.discard()?I18n.t("\n\nСтарая катушка будет списана как пустая: остаток обнулится, история сохранится. Подтвердите, что она снята и пуста."):replace?I18n.t("\n\nОстаток старой катушки сохранится. Списание и повторная приёмка не выполняются. Место хранения не меняется."):"");
            new AlertDialog.Builder(this).setTitle(replace?I18n.t("Заменить катушку?"):I18n.t("Установить катушку?"))
                    .setView(confirmationHint(OperationFlow.INSTALL,message))
                    .setPositiveButton(replace?I18n.t("Подтвердить замену"):I18n.t("Установить"),(dialog,which) -> {
                        if(choice.discard())confirmHeavyWriteOff(body,()->send("/api/mod/inventory/spools/bulk-delete",body));
                        else send("/api/mod/inventory/spool/"+sid+"/bind",body);
                    })
                    .setNegativeButton(I18n.t("Отмена"),null).show();
        } catch(Exception ex){error(ex);}
    }
    private void unbindStart() {
        refresh(() -> {
            if(!exchangeAvailable()) return;
            readCode(I18n.t("Снять катушку с принтера"),I18n.t("Сканируйте QR позиции либо код катушки. Затем подтвердите снятие."),raw -> refresh(() -> {
                if(raw.startsWith("fm1:")) {
                    Labels.Label label=Labels.parse(raw,inventory.server);
                    if(label.kind().equals("slot")) {
                        JSONObject spool=inventory.position(label).optJSONObject("spool");
                        if(spool==null) throw new IllegalArgumentException(I18n.t("Позиция уже свободна. Снимать нечего."));
                        confirmUnbind(spool.optString("id")); return;
                    }
                }
                chooseUnbind(inventory.findSpools(raw));
            }),ScanPolicy.ANY,OperationFlow.REMOVE);
            button(I18n.t("Выбрать из установленных катушек"),()->refresh(()->chooseUnbind(inventory.rows(inventory.data,"spools"))));
        });
    }
    private void chooseUnbind(List<JSONObject> spools) {
        screen(I18n.t("Снятие · выбор катушки")); boolean any=false;
        operationHint(OperationFlow.REMOVE,false);
        for(JSONObject s:spools) if(!s.optString("ams_printer_id").isEmpty()) {
            any=true; button(spoolTitle(s),()->refresh(()->confirmUnbind(s.optString("id"))));
        }
        if(!any) text(I18n.t("Установленных катушек по этому коду не найдено."));
        button(I18n.t("Назад"),this::home);
    }
    private void confirmUnbind(String sid) {
        if(!exchangeAvailable())return;
        if(!inventory.supportsWriteOff()){confirmReturnToStock(sid);return;}
        new AlertDialog.Builder(this).setTitle(I18n.t("Снять катушку"))
                .setItems(new String[]{I18n.t("Вернуть на склад"),I18n.t("Списать как пустую")},(dialog,which)->
                        refresh(()->{if(which==0)confirmReturnToStock(sid);else confirmWriteOff(sid);}))
                .setNegativeButton(I18n.t("Отмена"),null).show();
    }
    private void confirmReturnToStock(String sid) {
        try {
            if(!exchangeAvailable()) return;
            JSONObject s=inventory.spool(sid);
            if(s.optString("ams_printer_id").isEmpty()) throw new Exception(I18n.t("Катушка уже снята. Обновите данные."));
            if(s.optBoolean("pending")) throw new Exception(I18n.t("Катушка участвует в незавершённой печати"));
            Labels.Label target=new Labels.Label("slot",inventory.server,s.optString("ams_printer_id"),s.getInt("ams_slot"));
            JSONObject current=inventory.position(target).optJSONObject("spool");
            if(current==null || !sid.equals(current.optString("id"))) throw new Exception(I18n.t("Привязка изменилась или неоднозначна. Обновите данные."));
            JSONObject body=inventory.slotRequest(target,"unbind",sid);
            new AlertDialog.Builder(this).setTitle(I18n.t("Снять катушку?"))
                    .setView(confirmationHint(OperationFlow.REMOVE,targetCaption(target)+"\n\n"+spoolTitle(s)+I18n.t("\n\nБудет удалена только привязка. Остаток и история сохранятся; место хранения останется прежним.")))
                    .setPositiveButton(I18n.t("Снять катушку"),(dialog,which)->send("/api/mod/inventory/spool/"+sid+"/bind",body))
                    .setNegativeButton(I18n.t("Отмена"),null).show();
        } catch(Exception ex){error(ex);}
    }
    private boolean writeOffAvailable() {
        if(!writable())return false;
        if(preferences.contains("pending")){error(new Exception(I18n.t("Сначала завершите ранее отправленную операцию на главном экране.")));return false;}
        if(!inventory.supportsWriteOff()){error(new Exception(I18n.t("Модуль склада не поддерживает списание пустых катушек. Обновите модуль FM.")));return false;}
        return true;
    }
    private void writeOffStart() {
        refresh(()->{
            if(!writeOffAvailable())return;
            readCode(I18n.t("Списать катушку"),I18n.t("Сканируйте индивидуальный QR пустой катушки. Перед списанием проверьте её данные."),raw->refresh(()->{
                if(writeOffAvailable())confirmWriteOff(inventory.writeOffSpool(raw).optString("id"));
            }),ScanPolicy.SPOOL,OperationFlow.NONE);
        });
    }
    private void confirmWriteOff(String sid) {
        try {
            if(!writeOffAvailable())return;
            JSONObject spool=inventory.spool(sid),body=inventory.writeOffRequest(sid);
            String message=spoolTitle(spool);
            if(!spool.optString("ams_printer_id").isEmpty())message+="\n\n"+targetCaption(new Labels.Label("slot",inventory.server,spool.getString("ams_printer_id"),spool.getInt("ams_slot")));
            message+=I18n.t("\n\nПодтвердите, что катушка пустая и физически снята с принтера. Учтённый остаток будет списан в ноль, привязка снята, катушка удалена из активного склада. История сохранится. Возврата на склад не будет.");
            new AlertDialog.Builder(this).setTitle(I18n.t("Списать как пустую?"))
                    .setMessage(message).setPositiveButton(I18n.t("Списать"),(dialog,which)->confirmHeavyWriteOff(body,()->send("/api/mod/inventory/spools/bulk-delete",body)))
                    .setNegativeButton(I18n.t("Отмена"),null).show();
        }catch(Exception ex){error(ex);}
    }
    /** «Списать как пустую» с остатком выше порога — отдельный вопрос с числом граммов; ниже порога — прежний путь. */
    private void confirmHeavyWriteOff(JSONObject request,Runnable sendRequest) {
        String question;
        try{question=inventory.heavyWriteOffQuestion(request);}catch(Exception ex){error(ex);return;}
        if(question.isEmpty()){sendRequest.run();return;}
        new AlertDialog.Builder(this).setTitle(I18n.t("Катушка не пустая"))
                .setMessage(question+I18n.t("\n\nПроверьте, что отсканирована нужная катушка: весь учтённый остаток будет списан в ноль."))
                .setPositiveButton(InventoryRepository.heavyWriteOffButton(request.optDouble("expected_weight_remaining_g")),(dialog,which)->sendRequest.run())
                .setNegativeButton(I18n.t("Отмена"),null).show();
    }
    private String spoolTitle(JSONObject s) {
        return InventoryRepository.title(s)+"\n"+s.optString("label")+" · "+s.optString("weight_remaining_g")+I18n.t(" г\n")+s.optString("id")
                +(s.optString("ams_printer_id").isEmpty()?"":I18n.t(" · установлена"));
    }
    @android.annotation.SuppressLint("ApplySharedPref") // Durability must precede transmission; apply() is unsafe here.
    private void send(String path,JSONObject body) {
        send(path,body,"");
    }
    @android.annotation.SuppressLint("ApplySharedPref")
    private void send(String path,JSONObject body,String uiFlow) {
        try {
            synchronized(JOURNAL_LOCK) {
                if(preferences.contains("pending")) {resume();return;}
                JSONObject pending=new JSONObject().put("origin",api.origin).put("path",path).put("body",body).put("ui_flow",uiFlow);
                SharedPreferences.Editor editor=preferences.edit();
                if(ordinaryReceipt(path,body)) {
                    ReceiptBook book=book();JSONObject active=book.active(inventory.server);
                    if(active==null)active=book.start(inventory.server,UUID.randomUUID().toString(),batchName());
                    pending.put("batch_id",active.getString("id")).put("batch_name",active.getString("name"))
                            .put("label_caption",receiptCaption(body));
                    editor.putString("receipt_book",book.toString());
                }
                // Партия и запрос сохраняются совместно до обращения к серверу.
                if(!editor.putString("pending",pending.toString()).commit())throw new Exception(I18n.t("Не удалось сохранить операцию на телефоне"));
            }
            resume();
        } catch(Exception ex){error(ex);}
    }
    @android.annotation.SuppressLint("ApplySharedPref") // Commit runs on network executor; preserve durable operation outcome.
    private void resume() {
        if(!writable()) return;
        try {
            JSONObject p=new JSONObject(preferences.getString("pending","{}"));
            if(!api.origin.equals(p.getString("origin"))) throw new Exception(I18n.t("Незавершённая операция относится к другому адресу FM. Подключитесь к нему."));
            if(!inventory.server.equals(p.getJSONObject("body").getJSONObject("mobile").getString("server_id"))) throw new Exception(I18n.t("Это другой склад. Нельзя повторить здесь старую операцию."));
            task(I18n.t("Отправка операции. Не сканируйте следующую катушку…"), () -> {
                try {
                    FarmRepository core=new FarmRepository(api);core.refreshCapabilities();
                    core.requireInventory();
                    if(!core.capabilities.operate)throw new java.io.IOException(I18n.t("У пользователя нет права на эту операцию в FM."));
                    String operation=p.getJSONObject("body").getJSONObject("mobile").optString("operation");
                    if("writeoff".equals(operation)||"replace_writeoff".equals(operation)) {
                        InventoryRepository current=new InventoryRepository(api);current.refresh();
                        if("replace_writeoff".equals(operation)&&!current.supportsReplaceWriteOff())throw new java.io.IOException(I18n.t("Модуль склада не поддерживает замену со списанием. Обновите модуль FM."));
                        if(!current.supportsWriteOff())throw new java.io.IOException(I18n.t("Модуль склада не поддерживает списание пустых катушек. Обновите модуль FM."));
                        if(!current.server.equals(p.getJSONObject("body").getJSONObject("mobile").getString("server_id")))throw new java.io.IOException(I18n.t("Это другой склад. Нельзя повторить здесь старую операцию."));
                    }
                    JSONObject result=api.call("POST",p.getString("path"),p.getJSONObject("body"));
                    synchronized(JOURNAL_LOCK) {
                        SharedPreferences.Editor editor=preferences.edit();
                        if(isCurrentPending(p))editor.putString("last_result",result.toString()).remove("pending");
                        if(ordinaryReceipt(p.getString("path"),p.getJSONObject("body"))) {
                            ReceiptBook book=book();JSONObject body=p.getJSONObject("body");
                            book.record(inventory.server,p.optString("batch_id",body.getJSONObject("mobile").getString("request_id")),
                                    p.optString("batch_name",I18n.t("Восстановленная приёмка")),result,body,p.optString("label_caption",receiptCaption(body)));
                            editor.putString("receipt_book",book.toString());
                        }
                        if(!editor.commit())throw new Exception(I18n.t("FM подтвердил операцию, но телефон не сохранил результат. Повтор безопасен."));
                    }
                    return result;
                } catch(FmApi.Rejected rejected) {
                    synchronized(JOURNAL_LOCK) {if(isCurrentPending(p))preferences.edit().remove("pending").commit();}throw rejected;
                }
            }, result -> {
                if(Arrays.asList("prepare_labels","claim_label","cancel_labels").contains(result.optString("operation"))) {
                    preparedResult(p,result);return;
                }
                screen(I18n.t("Готово"));operationConfirmed(p);
                text(result.optBoolean("replayed")?I18n.t("Сервер вернул результат ранее выполненной операции. Дубликат не создан."):I18n.t("Изменение сохранено на складе."));
                text(I18n.t("Катушка: ")+result.optString("id"));
                if(result.optString("operation").equals("unbind")) text(I18n.t("Катушка снята с принтера. Остаток сохранён: ")+result.optString("weight_remaining_g")+I18n.t(" г. Место хранения не изменено."));
                if(result.optString("operation").equals("replace")) text(I18n.t("Новая катушка установлена. Снята: ")+result.optString("removed_spool_id")
                        +I18n.t("\nЕё остаток сохранён: ")+result.optString("removed_weight_remaining_g")+I18n.t(" г. Место хранения не изменено."));
                if(result.optString("operation").equals("replace_writeoff"))text(I18n.t("Новая катушка установлена. Старая списана как пустая; история сохранена."));
                if(result.optString("operation").equals("nfc_attach"))text(I18n.t("NFC связан с существующей катушкой. Остаток, материал, полка, QR и установка на принтер не изменены."));
                if(result.optString("operation").equals("writeoff")) {
                    text(I18n.t("Катушка списана как пустая и удалена из активного склада. История сохранена."));
                    text(I18n.t("Списанный остаток: ")+result.optString("written_off_g")+I18n.t(" г"));
                    action(I18n.t("Списать следующую катушку"),I18n.t("Сканировать индивидуальный QR"),"discard",true,this::writeOffStart);
                } else button(I18n.t("Показать / напечатать QR катушки"), () -> showLabel(result.optString("id"),Labels.spool(inventory.server,result.optString("id"))));
                if(ordinaryReceipt(p.optString("path"),p.optJSONObject("body"))) {
                    location=p.optJSONObject("body").optString("location");
                    receiptContinue(location);
                    action(I18n.t("QR всей партии"),I18n.t("Сохранить одним PDF"),"batch",false,this::batchesScreen);
                }
                button(I18n.t("Продолжить"),()->refresh(this::home));
            });
        } catch(Exception ex){error(ex);}
    }
    private void spools() {
        refresh(() -> {
            section=I18n.t("Катушки");screen(I18n.t("Катушки"));
            if(inventoryWriteAllowed&&!inventory.server.isEmpty())action(I18n.t("Скачать несколько QR"),I18n.t("Выбрать катушки → один PDF"),"qr",true,()->chooseLabels(inventory.rows(inventory.data,"spools")));
            EditText search=field(I18n.t("Поиск по материалу, цвету, подписи или ID"),"",InputType.TYPE_CLASS_TEXT);
            Spinner filter=spinner(Arrays.asList(I18n.t("Все катушки"),I18n.t("Не установлены"),I18n.t("На принтерах")));
            LinearLayout list=new LinearLayout(this);list.setOrientation(LinearLayout.VERTICAL);page.addView(list);
            Runnable render=()->{
                list.removeAllViews();LinearLayout outer=page;page=list;
                String q=search.getText().toString().toLowerCase(Locale.ROOT);int count=0;
                int state=filter.getSelectedItemPosition();
                for(JSONObject s:inventory.rows(inventory.data,"spools")) if(spoolTitle(s).toLowerCase(Locale.ROOT).contains(q)
                        &&(state==0||(state==1)==s.optString("ams_printer_id").isEmpty())) {
                    count++;spoolRow(s);
                }
                if(count==0)text(I18n.t("Катушки не найдены. Попробуйте другой запрос."));page=outer;
            };watch(search,render);
            filter.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener(){
                public void onItemSelected(AdapterView<?> a,View v,int p,long id){render.run();}
                public void onNothingSelected(AdapterView<?> a){}
            });render.run();
        });
    }
    private void watch(EditText field,Runnable changed) {
        field.addTextChangedListener(new android.text.TextWatcher() {
            public void beforeTextChanged(CharSequence s,int start,int count,int after){}
            public void onTextChanged(CharSequence s,int start,int before,int count){changed.run();}
            public void afterTextChanged(android.text.Editable s){}
        });
    }
    private void spoolRow(JSONObject s) {
        String name=(s.optString("vendor_name")+" "+s.optString("material")).trim();
        String place=s.optString("ams_printer_id").isEmpty()?preparedPlaceName(s.optString("location_id")):I18n.t("На принтере");
        String details=s.optString("color_name")+" · "+s.optString("weight_remaining_g")+I18n.t(" г\n")+place;
        if(!s.optString("label").isEmpty())details+=" · "+s.optString("label");
        LinearLayout row=action(name,details,"spool",false,()->spoolDetails(s.optString("id")));
        String hex=s.optString("color_hex");
        if(hex.matches("#[0-9a-fA-F]{6}")) {
            View swatch=new View(this);swatch.setBackground(style.box(Color.parseColor(hex),8));
            LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(dp(20),dp(32));p.setMargins(dp(8),0,0,0);row.addView(swatch,p);
            swatch.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        }
    }
    private ReceiptBook book() throws JSONException {return new ReceiptBook(preferences.getString("receipt_book","{}"));}
    private boolean ordinaryReceipt(String path,JSONObject body) {
        return path.equals("/api/mod/inventory/spool")&&body!=null&&body.optJSONObject("mobile")!=null
                &&(!body.optJSONObject("mobile").has("operation")||"nfc_receipt".equals(body.optJSONObject("mobile").optString("operation")));
    }
    private boolean isCurrentPending(JSONObject p) throws JSONException {
        if(!preferences.contains("pending"))return false;
        JSONObject current=new JSONObject(preferences.getString("pending","{}"));
        return current.getJSONObject("body").getJSONObject("mobile").getString("request_id")
                .equals(p.getJSONObject("body").getJSONObject("mobile").getString("request_id"));
    }
    private String batchName() {return I18n.t("Приёмка ")+java.text.DateFormat.getDateTimeInstance(java.text.DateFormat.SHORT,java.text.DateFormat.SHORT,I18n.locale()).format(new Date());}
    private String receiptCaption(JSONObject body) {
        JSONObject f=body.optJSONObject("filament");
        if(f==null) for(JSONObject row:inventory.rows(inventory.data,"filaments")) if(row.optString("id").equals(body.optString("filament_id"))) {f=row;break;}
        return (f==null?I18n.t("Филамент"):InventoryRepository.title(f))+"\n"+body.optString("label")+"\n"+body.optString("weight_total_g")+I18n.t(" г при приёмке");
    }
    private void batchesScreen() {
        try {
            section=I18n.t("Этикетки");screen(I18n.t("Этикетки и QR"));
            if(inventoryWriteAllowed&&inventory.supportsPreparedLabels())action(I18n.t("Этикетки до приёмки"),I18n.t("Общие для всех телефонов · хранятся в FM"),"qr",true,this::preparedScreen);
            text(I18n.t("Подтверждённые катушки с этого телефона. Партии сохраняются после закрытия приложения; коды разных складов не смешиваются.")).setTextColor(style.muted);
            if(inventoryWriteAllowed)action(I18n.t("Начать новую партию"),I18n.t("Предыдущие QR останутся в истории"),"receive",false,()-> {
                if(!writable())return;
                if(preferences.contains("pending")) {error(new Exception(I18n.t("Сначала завершите неподтверждённую операцию")));return;}
                new AlertDialog.Builder(this).setTitle(I18n.t("Новая партия приёмки?")).setMessage(I18n.t("Текущая партия останется в истории. Новые катушки будут собираться в отдельный PDF."))
                        .setPositiveButton(I18n.t("Начать"),(d,w)->startBatch()).setNegativeButton(I18n.t("Отмена"),null).show();
            });
            List<JSONObject> rows=book().list(inventory.server);
            if(rows.isEmpty())text(I18n.t("Пока нет партий. Примите первую катушку — она появится здесь. Для ранее принятых выберите «Катушки → Скачать несколько QR»."));
            for(JSONObject b:rows) action(b.getString("name"),(b.optBoolean("active")?I18n.t("Текущая · "):"")+b.getJSONArray("entries").length()+I18n.t(" катушек"),"batch",false,()->batchDetails(b.optString("id")));
        } catch(Exception ex){error(ex);}
    }
    @android.annotation.SuppressLint("ApplySharedPref")
    private void startBatch() {
        try {synchronized(JOURNAL_LOCK) {
            if(preferences.contains("pending"))throw new Exception(I18n.t("Сначала завершите неподтверждённую операцию"));
            ReceiptBook b=book();b.start(inventory.server,UUID.randomUUID().toString(),batchName());
            if(!preferences.edit().putString("receipt_book",b.toString()).commit())throw new Exception(I18n.t("Не удалось сохранить партию"));
            }
            receiptLocation();
        }catch(Exception ex){error(ex);}
    }
    private void batchDetails(String id) {
        try {
            JSONObject batch=book().get(inventory.server,id);JSONArray entries=batch.getJSONArray("entries");
            screen(batch.getString("name"));text(I18n.t("Принято: ")+entries.length()+I18n.t(" · Один QR на каждую катушку"));
            List<LabelSheet.Entry> labels=new ArrayList<>();
            for(int i=0;i<entries.length();i++) {JSONObject e=entries.getJSONObject(i);labels.add(new LabelSheet.Entry(e.getString("id"),e.getString("caption"),Labels.spool(inventory.server,e.getString("id"))));}
            if(!labels.isEmpty())action(I18n.t("Скачать все QR одним PDF"),I18n.t("A4 · 8 этикеток на странице"),"qr",true,()->exportSheet(labels));
            if(inventoryWriteAllowed&&batch.optBoolean("active"))button(I18n.t("Продолжить приёмку в эту партию"),()-> {if(preferences.contains("pending"))resume();else receiptLocation();});
            text(I18n.t("История приёмки не отражает последующее списание или удаление катушки. Экспорт ничего не меняет на складе.")).setTextColor(style.muted);
            for(LabelSheet.Entry e:labels)button(e.caption()+"\n"+e.id(),()->showLabel(e.caption(),e.code()));
            button(I18n.t("К списку партий"),this::batchesScreen);
        } catch(Exception ex){error(ex);}
    }
    private boolean preparedAvailable() {
        if(!writable())return false;
        if(!inventory.supportsPreparedLabels()) {error(new Exception(I18n.t("Установите модуль склада с мобильным расширением 0.4. Только APK недостаточно для подготовки этикеток.")));return false;}
        return true;
    }
    private void preparedScreen() {
        refresh(()-> {
            if(!preparedAvailable())return;
            section=I18n.t("Этикетки");screen(I18n.t("Этикетки до приёмки"));
            text(I18n.t("1. Подготовьте QR → 2. Наклейте → 3. Примите сканированием. До сканирования остаток склада не увеличивается.")).setTextColor(style.muted);
            if(preferences.contains("pending"))action(I18n.t("Завершить запрос"),I18n.t("Проверить сохранённую операцию"),"check",true,this::resume);
            else action(I18n.t("Подготовить новые этикетки"),I18n.t("Материал, масса одной катушки и количество"),"qr",true,this::prepareForm);
            List<JSONObject> batches=inventory.preparedBatches();
            if(batches.isEmpty())text(I18n.t("Пока нет подготовленных этикеток."));
            for(JSONObject b:batches)action(b.optString("name"),preparedSummary(b.optString("id")),"batch",false,()->refresh(()->preparedDetails(b.optString("id"))));
            text(I18n.t("Партии хранятся в FM и доступны другим подключённым телефонам. Это отдельный список от истории обычной приёмки на телефоне.")).setTextColor(style.muted);
        });
    }
    private String preparedSummary(String id) {
        int pending=0,received=0,cancelled=0;
        for(JSONObject l:inventory.preparedLabels(id))switch(l.optString("status")) {
            case "prepared":pending++;break;case "received":received++;break;case "cancelled":cancelled++;break;default:break;
        }
        return I18n.t("Ожидает: ")+pending+I18n.t(" · Принято: ")+received+I18n.t(" · Отменено: ")+cancelled;
    }
    private void prepareForm() {
        if(!preparedAvailable())return;screen(I18n.t("Подготовить этикетки"));
        text(I18n.t("Одинаковый материал и масса для всей партии. Будут созданы разные QR для каждой физической катушки, без прихода на склад."));
        EditText name=field(I18n.t("Название партии"),batchName(),InputType.TYPE_CLASS_TEXT);
        List<JSONObject> items=inventory.rows(inventory.data,"filaments");List<String> names=new ArrayList<>();names.add(I18n.t("Новый материал — заполнить ниже"));
        for(JSONObject f:items)names.add(InventoryRepository.title(f));text(I18n.t("Товар / материал"));Spinner materialChoice=spinner(names);
        int start=page.getChildCount();
        EditText vendor=field(I18n.t("Производитель"),"",InputType.TYPE_CLASS_TEXT);
        EditText material=field(I18n.t("Тип пластика"),"PETG",InputType.TYPE_CLASS_TEXT);
        EditText color=field(I18n.t("Цвет"),"",InputType.TYPE_CLASS_TEXT);
        EditText diameter=field(I18n.t("Диаметр, мм"),"1.75",InputType.TYPE_CLASS_NUMBER|InputType.TYPE_NUMBER_FLAG_DECIMAL);
        List<View> newFields=new ArrayList<>();for(int i=start;i<page.getChildCount();i++)newFields.add(page.getChildAt(i));
        materialChoice.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener(){
            public void onItemSelected(AdapterView<?> p,View v,int pos,long id){for(View f:newFields)f.setVisibility(pos==0?View.VISIBLE:View.GONE);}
            public void onNothingSelected(AdapterView<?> p){}
        });
        EditText grams=field(I18n.t("Масса филамента в одной полной катушке, г"),"1000",InputType.TYPE_CLASS_NUMBER|InputType.TYPE_NUMBER_FLAG_DECIMAL);
        EditText quantity=field(I18n.t("Количество катушек / разных QR (1–500)"),"10",InputType.TYPE_CLASS_NUMBER);
        EditText prefix=field(I18n.t("Общая подпись катушек (необязательно)"),"",InputType.TYPE_CLASS_TEXT);
        text(I18n.t("Масса без веса пустой катушки. Для начатых катушек этот режим не предназначен. После печати параметры партии не редактируются: неверные метки отменяются и создаются заново.")).setTextColor(style.muted);
        action(I18n.t("Создать этикетки"),I18n.t("Остатки пока не изменятся"),"qr",true,()-> {
            try {
                int count=Integer.parseInt(quantity.getText().toString().trim());double weight=Double.parseDouble(grams.getText().toString().replace(',','.'));
                if(count<1||count>500)throw new IllegalArgumentException(I18n.t("Укажите целое количество от 1 до 500"));
                if(!Double.isFinite(weight)||weight<=0||weight>100000)throw new IllegalArgumentException(I18n.t("Укажите положительную массу до 100000 г"));
                String title=name.getText().toString().trim(),label=prefix.getText().toString().trim();
                if(title.isEmpty()||title.length()>120||label.length()>100)throw new IllegalArgumentException(I18n.t("Название обязательно (до 120 знаков), подпись — до 100 знаков"));
                JSONObject d=new JSONObject().put("mobile",inventory.preparedEnvelope("prepare_labels")).put("name",title)
                        .put("label",label).put("quantity",count).put("weight_total_g",weight);
                String caption;
                if(materialChoice.getSelectedItemPosition()>0) {
                    JSONObject f=items.get(materialChoice.getSelectedItemPosition()-1);d.put("filament_id",f.optString("id"));caption=InventoryRepository.title(f);
                } else {
                    JSONObject f=new JSONObject().put("vendor_name",vendor.getText().toString().trim()).put("material",material.getText().toString().trim())
                            .put("color_name",color.getText().toString().trim()).put("diameter",Double.parseDouble(diameter.getText().toString().replace(',','.')));
                    if(f.getString("vendor_name").isEmpty()||f.getString("material").isEmpty()||f.getString("color_name").isEmpty())throw new IllegalArgumentException(I18n.t("Заполните производителя, тип пластика и цвет"));
                    d.put("filament",f);caption=InventoryRepository.title(f);
                }
                new AlertDialog.Builder(this).setTitle(I18n.t("Подготовить ")+count+I18n.t(" разных QR?"))
                        .setMessage(caption+I18n.t("\nМасса одной катушки: ")+weight+I18n.t(" г\n\nСоздаются только метки. Приход будет при сканировании на выбранную полку."))
                        .setPositiveButton(I18n.t("Создать"),(dialog,w)->send("/api/mod/inventory/spool",d)).setNegativeButton(I18n.t("Проверить поля"),null).show();
            }catch(Exception ex){error(ex);}
        });
    }
    private String preparedCaption(JSONObject batch,JSONObject label) {
        return "№"+String.format(Locale.ROOT,"%03d",label.optInt("ordinal"))+" · "+batch.optString("caption")+"\n"
                +batch.optString("label")+" · "+batch.optString("weight_total_g")+I18n.t(" г при приёмке");
    }
    private void preparedDetails(String id) {
        if(!preparedAvailable())return;
        JSONObject b=inventory.preparedBatch(id);List<JSONObject> rows=inventory.preparedLabels(id);
        section=I18n.t("Этикетки");screen(b.optString("name"));text(b.optString("caption")+"\n"+b.optString("weight_total_g")+I18n.t(" г в каждой катушке"));text(preparedSummary(id)).setTextColor(style.accent);
        List<LabelSheet.Entry> labels=new ArrayList<>();List<String> waiting=new ArrayList<>();
        for(JSONObject l:rows) {
            if(!l.optString("status").equals("cancelled"))labels.add(new LabelSheet.Entry(l.optString("id"),preparedCaption(b,l),Labels.spool(inventory.server,l.optString("id"))));
            if(l.optString("status").equals("prepared"))waiting.add(l.optString("id"));
        }
        if(!labels.isEmpty())action(I18n.t("Скачать QR одним PDF"),I18n.t("Повторная печать сохраняет прежние номера"),"qr",true,()->exportSheet(labels));
        if(!waiting.isEmpty())action(I18n.t("Принять по этим QR"),I18n.t("Выберите полку, затем сканируйте катушки"),"receive",false,()->preparedLocation(id));
        text(I18n.t("Отменённые метки не печатаются и не принимаются. Принятые остаются пригодны для идентификации катушки, но не создают повторный приход.")).setTextColor(style.muted);
        if(!waiting.isEmpty())button(I18n.t("Отменить все ожидающие метки (")+waiting.size()+")",()->confirmCancelLabels(id,waiting));
        for(JSONObject l:rows) {
            String state=l.optString("status");String statusName=state.equals("received")?I18n.t("Принята"):state.equals("cancelled")?I18n.t("Отменена"):I18n.t("Ожидает приёмки");
            button("№"+l.optInt("ordinal")+" · "+statusName+"\n"+l.optString("id"),()-> {
                if(state.equals("cancelled")){new AlertDialog.Builder(this).setMessage(I18n.t("Метка отменена и не может быть принята.")).setPositiveButton(I18n.t("Понятно"),null).show();return;}
                AlertDialog.Builder dialog=new AlertDialog.Builder(this).setTitle(I18n.t("Этикетка №")+l.optInt("ordinal"))
                        .setMessage(statusName+"\n"+preparedCaption(b,l))
                        .setPositiveButton(I18n.t("Показать QR"),(d,w)->showLabel(preparedCaption(b,l),Labels.spool(inventory.server,l.optString("id"))))
                        .setNegativeButton(I18n.t("Назад"),null);
                if(state.equals("prepared"))dialog.setNeutralButton(I18n.t("Отменить метку"),(d,w)->confirmCancelLabels(id,Collections.singletonList(l.optString("id"))));dialog.show();
            });
        }
        button(I18n.t("Обновить партию"),()->refresh(()->preparedDetails(id)));
    }
    private void confirmCancelLabels(String batchId,List<String> ids) {
        try {
            JSONObject d=new JSONObject().put("mobile",inventory.preparedEnvelope("cancel_labels")).put("batch_id",batchId).put("label_ids",new JSONArray(ids));
            new AlertDialog.Builder(this).setTitle(I18n.t("Отменить неиспользованные метки?"))
                    .setMessage(I18n.t("Выбрано: ")+ids.size()+I18n.t(". Их QR больше нельзя будет принять на склад. Если другой оператор уже принял катушку, она останется на складе без изменений. Отмена необратима."))
                    .setPositiveButton(I18n.t("Отменить метки"),(dialog,w)->send("/api/mod/inventory/spool",d)).setNegativeButton(I18n.t("Оставить"),null).show();
        }catch(Exception ex){error(ex);}
    }
    private void preparedLocation(String id) {
        refresh(()-> {
            if(!preparedAvailable())return;JSONObject b=inventory.preparedBatch(id);screen(I18n.t("Куда принять катушки?"));text(b.optString("name"));
            List<JSONObject> places=inventory.rows(inventory.places,"locations");
            if(places.isEmpty())text(I18n.t("Сначала создайте место хранения в FM."));
            for(JSONObject place:places)button(locationName(place,places),()->new AlertDialog.Builder(this).setTitle(I18n.t("Включить приёмку по QR?"))
                    .setMessage(I18n.t("Партия: ")+b.optString("name")+"\n"+b.optString("caption")+"\n"+b.optString("weight_total_g")+I18n.t(" г на катушку\nПолка: ")+locationName(place,places)
                            +I18n.t("\n\nСканирование действующей метки этой партии сразу выполнит приход, без подтверждения каждой катушки."))
                    .setPositiveButton(I18n.t("Включить"),(d,w)->preparedReceiving(id,place.optString("id"))).setNegativeButton(I18n.t("Отмена"),null).show());
        });
    }
    private void preparedReceiving(String id,String place) {
        JSONObject b=inventory.preparedBatch(id);screen(I18n.t("Приёмка по QR включена"));text(b.optString("name"));text(preparedSummary(id)).setTextColor(style.accent);
        operationHint(OperationFlow.RECEIVE,true);
        text(I18n.t("Полка: ")+preparedPlaceName(place)+"\n"+b.optString("weight_total_g")+I18n.t(" г на катушку"));
        text(I18n.t("Сканируйте только наклеенные на катушки метки этой партии. Каждый новый QR сразу создаёт один приход. Повторный QR не увеличит остаток."));
        action(I18n.t("Сканировать катушку"),I18n.t("Приход после чтения QR"),"scan",true,()->scanPrepared(id,place));
        button(I18n.t("Ввести содержимое QR вручную"),()->readCode(I18n.t("Приёмка подготовленной катушки"), I18n.t("При использовании кода приход выполнится сразу."),raw->claimPrepared(raw,id,place),ScanPolicy.SPOOL,OperationFlow.RECEIVE));
        button(I18n.t("Сменить полку"),()->preparedLocation(id));button(I18n.t("Завершить приёмку"),()->refresh(()->preparedDetails(id)));
    }
    private String preparedPlaceName(String id) {
        List<JSONObject> places=inventory.rows(inventory.places,"locations");for(JSONObject p:places)if(id.equals(p.optString("id")))return locationName(p,places);return id;
    }
    private void scanPrepared(String id,String place) {
        if(preferences.contains("pending")){resume();return;}
        launchCamera(I18n.t("Приёмка сразу после QR · ")+preparedPlaceName(place),raw->claimPrepared(raw,id,place),null,ScanPolicy.SPOOL,OperationFlow.RECEIVE);
    }
    private void claimPrepared(String raw,String id,String place) {
        try {send("/api/mod/inventory/spool",inventory.claimRequest(raw,id,place));}catch(Exception ex){error(ex);}
    }
    private void preparedResult(JSONObject pending,JSONObject result) {
        String op=result.optString("operation"),id=result.optString("batch_id");
        if(op.equals("claim_label")&&"receipt_scan".equals(pending.optString("ui_flow"))) {
            section=I18n.t("Склад");screen(result.optBoolean("already_received")?I18n.t("Катушка уже принята"):I18n.t("Катушка принята"));
            operationConfirmed(pending);
            text(result.optBoolean("already_received")||result.optBoolean("replayed")?I18n.t("Повторного прихода нет. Остаток и прежняя полка сохранены."):I18n.t("Один приход сохранён в FM."));
            text(I18n.t("Катушка: ")+result.optString("id")+I18n.t("\nПолка при приёмке: ")+preparedPlaceName(result.optString("location_id")));
            location=pending.optJSONObject("body").optString("location");receiptContinue(location);
            return;
        }
        section=I18n.t("Этикетки");screen(op.equals("prepare_labels")?I18n.t("Этикетки готовы"):op.equals("cancel_labels")?I18n.t("Отмена выполнена"):result.optBoolean("already_received")?I18n.t("Катушка уже принята"):I18n.t("Катушка принята"));
        if(op.equals("claim_label"))operationConfirmed(pending);
        JSONObject counts=result.optJSONObject("counts");
        if(counts!=null)text(I18n.t("Принято ")+counts.optInt("received")+I18n.t(" из ")+counts.optInt("total")+I18n.t(" · Ожидает ")+counts.optInt("prepared")+I18n.t(" · Отменено ")+counts.optInt("cancelled"));
        if(op.equals("prepare_labels"))text(I18n.t("Остатки склада не изменились. Скачайте PDF, наклейте по одной метке на каждую катушку и включите приёмку по QR."));
        if(op.equals("cancel_labels"))text(I18n.t("Отменено новых меток: ")+result.optInt("cancelled_count")+I18n.t(". Уже принятые катушки и их остатки не менялись."));
        if(op.equals("claim_label")) {
            text(result.optBoolean("already_received")||result.optBoolean("replayed")?I18n.t("Повторного прихода нет. QR уже учтён; катушка не перемещена и не восстановлена после возможного удаления."):I18n.t("Один приход сохранён в FM."));
            text(I18n.t("Катушка: ")+result.optString("id")+I18n.t("\nПолка при приёмке: ")+preparedPlaceName(result.optString("location_id")));
            String place=pending.optJSONObject("body").optString("location");
            if(counts==null||counts.optInt("prepared")>0)action(I18n.t("Сканировать следующую"),I18n.t("Та же партия · ")+preparedPlaceName(place),"scan",true,()->refresh(()->scanPrepared(id,place)));
            else text(I18n.t("Все метки партии обработаны.")).setTextColor(style.success);
        }
        action(I18n.t("Открыть партию / скачать PDF"),I18n.t("Актуальное состояние из FM"),"batch",false,()->refresh(()->preparedDetails(id)));
        button(I18n.t("Все подготовленные партии"),this::preparedScreen);
    }
    private void chooseLabels(List<JSONObject> spools) {
        if(!writable())return;screen(I18n.t("QR одним файлом"));text(I18n.t("Выберите катушки. Экспорт не создаёт приёмку и не меняет остатки."));
        LinkedHashMap<String,LabelSheet.Entry> selected=new LinkedHashMap<>();List<CheckBox> checks=new ArrayList<>();
        TextView count=text(I18n.t("Выбрано: 0"));
        action(I18n.t("Скачать PDF"),I18n.t("8 этикеток на A4"),"qr",true,()->exportSheet(new ArrayList<>(selected.values())));
        button(I18n.t("Выбрать все / снять выбор"),()-> {boolean all=selected.size()==spools.size();for(CheckBox c:checks)c.setChecked(!all);});
        EditText search=field(I18n.t("Найти катушки"),"",InputType.TYPE_CLASS_TEXT);
        for(JSONObject s:spools) {
            CheckBox c=new CheckBox(this);c.setText(spoolTitle(s));c.setTextColor(style.text);c.setTextSize(15);c.setMinHeight(dp(64));c.setPadding(dp(8),dp(10),dp(8),dp(10));
            c.setButtonTintList(android.content.res.ColorStateList.valueOf(style.accent));page.addView(c);checks.add(c);
            c.setOnCheckedChangeListener((v,on)-> {String sid=s.optString("id");
                if(on)selected.put(sid,new LabelSheet.Entry(sid,InventoryRepository.title(s)+"\n"+s.optString("label"),Labels.spool(inventory.server,sid)));else selected.remove(sid);
                count.setText(I18n.t("Выбрано: ")+selected.size());
            });
        }
        watch(search,()-> {String q=search.getText().toString().toLowerCase(Locale.ROOT);for(CheckBox c:checks)c.setVisibility(c.getText().toString().toLowerCase(Locale.ROOT).contains(q)?View.VISIBLE:View.GONE);});
        text(I18n.t("«Выбрать все» включает весь список, в том числе скрытые поиском катушки.")).setTextColor(style.muted);
    }
    @android.annotation.SuppressLint("ApplySharedPref")
    private void exportSheet(List<LabelSheet.Entry> labels) {
        try {
            exportLabels=new ArrayList<>(LabelSheet.validate(labels));
            JSONArray rows=new JSONArray();for(LabelSheet.Entry e:exportLabels)rows.put(new JSONObject().put("id",e.id()).put("caption",e.caption()).put("code",e.code()));
            if(!preferences.edit().putString("export_labels",rows.toString()).commit())throw new Exception(I18n.t("Не удалось сохранить набор этикеток на телефоне"));
            savePdf.launch("FM-QR-"+new java.text.SimpleDateFormat("yyyyMMdd-HHmmss",Locale.ROOT).format(new Date())+".pdf");
        } catch(Exception ex){error(ex);}
    }
    private void positions() {
        refresh(() -> {
            screen(I18n.t("Метки позиций принтеров")); text(I18n.t("Каждая метка закреплена за конкретным принтером и индексом подачи. Внешний держатель не является слотом 1."));
            for(JSONObject p:inventory.rows(inventory.ams,"printers")) {
                text(p.optString("printer_name"));
                for(JSONObject s:inventory.rows(p,"slots")) {
                    if(s.optBoolean("offline")||s.optBoolean("unconfirmed")) continue;
                    String caption=p.optString("printer_name")+" · "+slotName(s);
                    button(caption,()->showLabel(caption,Labels.slot(inventory.server,p.optString("printer_id"),s.optInt("index"))));
                }
            }
            button(I18n.t("Назад"),this::home);
        });
    }
    private void showLabel(String caption,String code) {
        try {
            var bitmap=LabelPrinter.bitmap(code); screen(I18n.t("Собственный QR FM")); text(caption);
            ImageView image=new ImageView(this); image.setImageBitmap(bitmap); image.setAdjustViewBounds(true); page.addView(image,new LinearLayout.LayoutParams(-1,dp(280)));
            text(code); text(I18n.t("Для катушки наклейте метку на саму катушку, не только на коробку. QR не содержит паролей и изменяемого остатка."));
            button(I18n.t("Печать / сохранить PDF"),()->LabelPrinter.print(this,caption.replace('\n',' '),bitmap));
            button(I18n.t("Назад"),()->refresh(this::home));
        } catch(Exception ex){error(ex);}
    }
    @Override protected void onResume() {
        super.onResume();if(launchIntro!=null)launchIntro.resume();
        inventoryVisible=true;moduleWatcher.postDelayed(checkInventoryModule,1000);
        if(loggedIn && !busy && api!=null && api.sessionExpired())
            task(I18n.t("Срок входа истёк…"),()->{throw new FmApi.SessionExpired();},ignored->{});
        else autoRelayLicenses();
        if(restoreRetryPending) scheduleRestoreRetry(1000);
    }
    private final Runnable checkInventoryModule=new Runnable(){public void run(){
        if(!inventoryVisible)return;
        if(loggedIn&&!busy&&api!=null&&inventory!=null){
            FmApi checkedApi=api;
            network.execute(()->{try{FarmRepository core=new FarmRepository(checkedApi);core.refreshCapabilities();runOnUiThread(()->{
                if(!inventoryVisible||isDestroyed()||api!=checkedApi)return;
                boolean roleChanged=inventoryWriteAllowed!=core.capabilities.operate||licenseAdmin!=core.capabilities.admin;inventoryWriteAllowed=core.capabilities.operate;inventoryReadOnlyNotice=core.capabilities.readOnlyNotice();licenseAdmin=core.capabilities.admin;
                if(!core.capabilities.inventory){inventory=null;openFarm();}
                else if(roleChanged)home();
            });}catch(FmApi.Unauthorized ex){
                // Forget and show sign-in only when FM status says authenticated:false.
                if(!AuthCheck.shouldForget(AuthCheck.ask(checkedApi)))return;
                try{rememberedLogin.forget();}catch(Exception clearError){ex.addSuppressed(clearError);}
                runOnUiThread(()->{if(inventoryVisible&&!isDestroyed()&&api==checkedApi)error(ex);});}catch(Exception ignored){runOnUiThread(()->{if(api==checkedApi)inventoryWriteAllowed=false;});}});
        }
        moduleWatcher.postDelayed(this,10000);
    }};
    @Override protected void onPause() {inventoryVisible=false;moduleWatcher.removeCallbacksAndMessages(null);restoreRetry.removeCallbacksAndMessages(null);if(launchIntro!=null)launchIntro.pause();super.onPause();}
    @Override public void onDestroy() { if(launchIntro!=null)launchIntro.dispose();network.shutdown();loginProbe.shutdownNow();restoreRetry.removeCallbacksAndMessages(null); super.onDestroy(); }
    @Override public void onConfigurationChanged(android.content.res.Configuration configuration) {
        super.onConfigurationChanged(configuration);
        // Native layouts are size-flexible: relayout the existing form, retaining its values,
        // authenticated transport, pending callbacks and any active confirmation dialog.
        getWindow().getDecorView().requestLayout();
        getWindow().getDecorView().requestApplyInsets();
    }
    @Override protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);out.putString("location",location);
        out.putBoolean("intro_completed",introCompleted);if(launchIntro!=null)out.putLong("intro_elapsed",launchIntro.elapsedMillis());
    }
}
