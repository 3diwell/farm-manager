// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.ui;
import android.app.Activity;
import android.app.Instrumentation;
import android.content.Context;
import android.content.res.Configuration;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.os.Bundle;
import android.view.ContextThemeWrapper;
import android.view.View;
import android.widget.*;

/** Separate device-only check of actual View measurement and drawables. No FM or printer requests. */
public final class GlassUiInstrumentation extends Instrumentation {
    private int checks;
    @Override public void onCreate(Bundle args){super.onCreate(args);start();}
    @Override public void onStart(){
        Bundle result=new Bundle();java.util.concurrent.atomic.AtomicReference<Throwable> error=new java.util.concurrent.atomic.AtomicReference<>();
        runOnMainSync(()->{try{verify();}catch(Throwable t){error.set(t);}});
        result.putString("stream",error.get()==null?"PASS: "+checks+" UI checks":"FAIL: "+error.get());
        finish(error.get()==null?Activity.RESULT_OK:Activity.RESULT_CANCELED,result);
    }
    private void verify(){
        Context base=getTargetContext();boolean previous=FmStyle.isDark(base);
        try{for(boolean dark:new boolean[]{true,false}){
            base.getSharedPreferences("fm-client",0).edit().putBoolean("dark",dark).commit();
            for(float font:new float[]{1,1.5f,2})for(int width:new int[]{320,360,393,600}){
                Configuration config=new Configuration(base.getResources().getConfiguration());config.fontScale=font;
                Context context=new ContextThemeWrapper(base.createConfigurationContext(config),FmStyle.theme(base));FmStyle style=new FmStyle(context);
                ScrollView scroll=new ScrollView(context);scroll.setFillViewport(true);LinearLayout page=new LinearLayout(context);page.setOrientation(1);scroll.addView(page);
                BrandHeader empty=new BrandHeader(context,style);page.addView(empty);
                TextView title=style.label("Labels / NFC",25,style.text);page.addView(title);
                page.addView(style.actionCard("Scan","Read spool code","scan",true));
                measure(scroll,style.dp(width),style.dp(640));
                require(empty.getHeight()==style.dp(56),"Header expanded on a short form");require(title.getTop()<style.dp(100),"Form moved below viewport");
                ConnectionRow row=new ConnectionRow(context,style,()->{});row.status.setText("Connected");
                BrandHeader live=new BrandHeader(context,style,row,new NotificationButton(context,style,()->{}));
                live.measure(exact(style.dp(width-24)),View.MeasureSpec.makeMeasureSpec(style.dp(640),View.MeasureSpec.AT_MOST));
                live.layout(0,0,live.getMeasuredWidth(),live.getMeasuredHeight());
                require(live.getHeight()<=style.dp(120),"Live header expanded");require(row.getMeasuredWidth()<=live.getMeasuredWidth(),"Status row clipped");
                require(row.getChildAt(1).getMeasuredWidth()>=style.dp(48),"Refresh tap target too small");
                LinearLayout nav=new LinearLayout(context);style.navigationBar(nav);
                for(String id:new String[]{"printer","projects","tasks","warehouse","more"})nav.addView(style.navigationItem(id,id,id.equals("printer"),()->{}));
                measure(nav,style.dp(width-16),style.dp(96));
                Bitmap image=Bitmap.createBitmap(style.dp(width),style.dp(640),Bitmap.Config.ARGB_8888);Canvas canvas=new Canvas(image);
                scroll.draw(canvas);live.draw(canvas);nav.draw(canvas);image.recycle();checks++;
            }
            FmStyle style=new FmStyle(base);
            for(String kind:new String[]{"scan","nfc","send_print","repeat","pause","play","stop","qr","video","file"}){
                final int[] clicks={0};ImageButton button=style.iconButton(kind,kind,()->clicks[0]++);button.performClick();require(clicks[0]==1,"Listener lost");
                require(button.getContentDescription().equals(kind),"Accessible name lost");button.setEnabled(false);
                Bitmap image=Bitmap.createBitmap(style.dp(64),style.dp(64),Bitmap.Config.ARGB_8888);measure(button,style.dp(48),style.dp(48));button.draw(new Canvas(image));image.recycle();checks++;
            }
        }}finally{base.getSharedPreferences("fm-client",0).edit().putBoolean("dark",previous).commit();}
    }
    private static int exact(int value){return View.MeasureSpec.makeMeasureSpec(value,View.MeasureSpec.EXACTLY);}
    private static void measure(View view,int width,int height){view.measure(exact(width),exact(height));view.layout(0,0,width,height);}
    private static void require(boolean value,String reason){if(!value)throw new AssertionError(reason);}
}
