// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm;

import android.os.*;
import android.webkit.*;
import android.widget.*;
import android.net.Uri;
import ru.threediwell.fm.core.*;
import ru.threediwell.fm.farm.FarmRepository;
import ru.threediwell.fm.i18n.I18n;
import ru.threediwell.fm.ui.*;
import org.json.JSONObject;
import java.util.UUID;

/** Одна камера через штатные маршруты FM. Собственный документ, без интерфейса команд. */
public final class CameraActivity extends FmActivity {
    private WebView web;private FmApi api;private final Handler handler=new Handler(Looper.getMainLooper());
    private boolean active;private String path,type;private long lastAuth;private boolean validating;
    private final java.util.concurrent.ExecutorService authWorker=java.util.concurrent.Executors.newSingleThreadExecutor();
    private final Runnable expiry=new Runnable(){public void run(){if(!active)return;if(api.sessionExpired()||SessionRegistry.get()!=api){finish();return;}if(!validating&&SystemClock.elapsedRealtime()-lastAuth>10000){validating=true;lastAuth=SystemClock.elapsedRealtime();authWorker.execute(()->{try{boolean valid=api.call("GET","/api/auth/status",null).optBoolean("authenticated");runOnUiThread(()->{validating=false;if(!valid)finish();});}catch(FmApi.Unauthorized ex){runOnUiThread(()->{validating=false;finish();});}catch(Exception ex){runOnUiThread(()->validating=false);}});}handler.postDelayed(this,1000);}};
    @Override public void onCreate(Bundle state){
        setTheme(FmStyle.theme(this));super.onCreate(state);api=SessionRegistry.get();
        if(api==null){finish();return;}
        String pid=getIntent().getStringExtra("printer_id");type=getIntent().getStringExtra("printer_type");
        if(pid==null||pid.isEmpty()||!("bambu".equals(type)||"klipper".equals(type))){finish();return;}
        path="/api/printer/"+FarmRepository.segment(pid);
        FmStyle style=new FmStyle(this);LinearLayout root=new LinearLayout(this);root.setOrientation(LinearLayout.VERTICAL);root.setPadding(style.dp(12),style.dp(12),style.dp(12),style.dp(12));root.setBackgroundColor(style.bg);setContentView(root);style.systemBars(this,root);
        root.setOnApplyWindowInsetsListener((v,insets)->{v.setPadding(style.dp(12)+insets.getSystemWindowInsetLeft(),style.dp(12)+insets.getSystemWindowInsetTop(),style.dp(12)+insets.getSystemWindowInsetRight(),style.dp(12)+insets.getSystemWindowInsetBottom());return insets;});
        LinearLayout toolbar=new LinearLayout(this);toolbar.setGravity(android.view.Gravity.CENTER_VERTICAL);toolbar.setPadding(0,0,0,style.dp(12));root.addView(toolbar);
        toolbar.addView(style.iconButton(I18n.t("Закрыть камеру"),"back",this::finish));
        TextView title=style.label(getIntent().getStringExtra("printer_name"),20,style.text);title.setPadding(style.dp(12),0,style.dp(8),0);toolbar.addView(title,new LinearLayout.LayoutParams(0,-2,1));
        toolbar.addView(style.headerIconButton(I18n.t("Подключить заново"),"refresh",this::startPlayer));
        web=new WebView(this);web.setBackgroundColor(style.bg);root.addView(web,new LinearLayout.LayoutParams(-1,0,1));
        WebSettings settings=web.getSettings();settings.setJavaScriptEnabled(true);settings.setAllowFileAccess(false);settings.setAllowContentAccess(false);settings.setDomStorageEnabled(false);settings.setMediaPlaybackRequiresUserGesture(false);settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web,false);
        web.setWebViewClient(new WebViewClient(){
            @Override public boolean shouldOverrideUrlLoading(WebView view,WebResourceRequest request){return true;}
            @Override public WebResourceResponse shouldInterceptRequest(WebView view,WebResourceRequest request){
                Uri uri=request.getUrl();Uri origin=Uri.parse(api.origin);
                if(!origin.getScheme().equals(uri.getScheme())||!origin.getAuthority().equals(uri.getAuthority())||!uri.getPath().startsWith(path+"/"))return new WebResourceResponse("text/plain","UTF-8",new java.io.ByteArrayInputStream(new byte[0]));
                return null;
            }
        });
        web.setWebChromeClient(new WebChromeClient(){@Override public void onPermissionRequest(PermissionRequest request){request.deny();}});
    }
    private void startPlayer(){
        if(web==null||!active)return;
        web.evaluateJavascript("window.stopPlayer&&window.stopPlayer()",null);web.stopLoading();web.loadUrl("about:blank");
        try{CookieManager.getInstance().setCookie(api.origin,api.browserSessionCookie(),ok->{if(active&&!isDestroyed())web.loadDataWithBaseURL(api.origin+"/",document(),"text/html","UTF-8",null);});}
        catch(Exception ex){finish();}
    }
    private String document(){return ru.threediwell.fm.farm.CameraPage.render(path,type,FmStyle.isDark(this));}
    @Override protected void onStart(){super.onStart();active=true;if(api!=null){startPlayer();handler.post(expiry);}}
    @Override protected void onStop(){active=false;handler.removeCallbacksAndMessages(null);if(web!=null){web.evaluateJavascript("window.stopPlayer&&window.stopPlayer()",null);web.stopLoading();web.loadUrl("about:blank");}if(api!=null)CookieManager.getInstance().setCookie(api.origin,"fm_session=; Path=/; Max-Age=0");super.onStop();}
    @Override public void onDestroy(){authWorker.shutdown();if(web!=null){web.destroy();web=null;}super.onDestroy();}
}
