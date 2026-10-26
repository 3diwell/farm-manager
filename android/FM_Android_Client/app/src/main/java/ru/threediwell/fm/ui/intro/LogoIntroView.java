// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.ui.intro;

import android.animation.*;
import android.content.Context;
import android.graphics.*;
import android.view.*;
import android.view.animation.LinearInterpolator;
import android.widget.*;
import androidx.core.view.*;
import ru.threediwell.fm.R;
import ru.threediwell.fm.ui.FmStyle;
import java.util.Calendar;

/** Full-screen native launch presentation; background/text are independent of the logo. */
public final class LogoIntroView extends FrameLayout {
    public static final int BACKGROUND=0xFF18181B;
    private final FmStyle style;
    private final boolean light;
    private final Drawing drawing;
    private final LinearLayout greeting;
    private final TextView hello,wish;
    private final Button skip;
    private final ValueAnimator animator;
    private Runnable finished;
    private long elapsed;
    private boolean closed;
    public LogoIntroView(Context context,IntroModel model,long elapsed,Runnable finished) {
        super(context);this.finished=finished;this.elapsed=Math.max(0,Math.min(IntroModel.DURATION_MS,elapsed));
        style=new FmStyle(context);light=!FmStyle.isDark(context);
        setBackgroundColor(style.bg);setClickable(true);setFocusable(true);
        drawing=new Drawing(context,model);addView(drawing,new LayoutParams(-1,-1));
        greeting=new LinearLayout(context);greeting.setOrientation(LinearLayout.VERTICAL);greeting.setGravity(Gravity.CENTER);
        hello=new TextView(context);hello.setTextColor(light?style.text:Color.WHITE);hello.setTextSize(20);hello.setGravity(Gravity.CENTER);
        hello.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));greeting.addView(hello);
        wish=new TextView(context);wish.setTextColor(light?style.muted:0xFFC4C4CC);wish.setTextSize(16);wish.setGravity(Gravity.CENTER);
        wish.setPadding(0,dp(6),0,0);greeting.addView(wish);
        LayoutParams copy=new LayoutParams(-1,-2,Gravity.TOP);copy.leftMargin=dp(24);copy.rightMargin=dp(24);addView(greeting,copy);
        skip=new Button(context);skip.setText(R.string.intro_continue);skip.setAllCaps(false);skip.setTextSize(15);skip.setTextColor(style.text);
        skip.setBackgroundTintList(android.content.res.ColorStateList.valueOf(style.card));skip.setMinHeight(dp(48));skip.setPadding(dp(24),0,dp(24),0);
        LayoutParams button=new LayoutParams(-2,dp(48),Gravity.BOTTOM|Gravity.CENTER_HORIZONTAL);button.bottomMargin=dp(16);addView(skip,button);
        skip.setOnClickListener(v->finish());
        ViewCompat.setOnApplyWindowInsetsListener(this,(v,insets)-> {
            androidx.core.graphics.Insets safe=insets.getInsets(WindowInsetsCompat.Type.systemBars()|WindowInsetsCompat.Type.displayCutout());
            setPadding(safe.left,safe.top,safe.right,safe.bottom);return insets;
        });
        animator=ValueAnimator.ofFloat(0,1);animator.setDuration(IntroModel.DURATION_MS);animator.setInterpolator(new LinearInterpolator());
        animator.addUpdateListener(a->{this.elapsed=Math.round((Float)a.getAnimatedValue()*IntroModel.DURATION_MS);update();});
        animator.addListener(new AnimatorListenerAdapter(){@Override public void onAnimationEnd(Animator a){if(!closed)finish();}});
        refreshGreeting();update();
    }
    private int dp(int n){return Math.round(n*getResources().getDisplayMetrics().density);}
    public int backgroundColor(){return style.bg;}
    private void refreshGreeting() {
        int hour=Calendar.getInstance().get(Calendar.HOUR_OF_DAY);hello.setText(IntroModel.greeting(hour));wish.setText(IntroModel.wish(hour));
    }
    public long elapsedMillis(){return elapsed;}
    public void resume() {
        if(closed)return;refreshGreeting();
        if(!ValueAnimator.areAnimatorsEnabled()||elapsed>=IntroModel.DURATION_MS){finish();return;}
        if(animator.isPaused())animator.resume();
        else if(!animator.isStarted()){long restore=elapsed;animator.start();animator.setCurrentPlayTime(restore);}
    }
    public void pause(){if(animator.isStarted()&&!animator.isPaused())animator.pause();}
    public void dispose(){closed=true;finished=null;animator.removeAllListeners();animator.removeAllUpdateListeners();animator.cancel();}
    public void finish(){if(closed)return;Runnable done=finished;dispose();if(done!=null)done.run();}
    private void update(){drawing.invalidate();positionGreeting();}
    @Override protected void onLayout(boolean changed,int l,int t,int r,int b){super.onLayout(changed,l,t,r,b);positionGreeting();}
    private void positionGreeting() {
        float t=Math.max(0,Math.min(1,(elapsed-1750)/1250f));t=t*t*(3-2*t);
        float top=drawing.centerY+(250-180*t)*drawing.scale+dp(18);
        float limit=drawing.getHeight()-greeting.getMeasuredHeight()-dp(84);
        greeting.setTranslationY(Math.max(dp(12),Math.min(top,limit)));
    }
    private final class Drawing extends View implements IntroRenderer.Surface {
        private final IntroRenderer renderer;
        private final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Path path=new Path();private final RectF bounds=new RectF();
        private final Matrix shaderMatrix=new Matrix();
        private final LinearGradient[] gradients=new LinearGradient[16];
        private final int[] tops=new int[16],middles=new int[16],bottoms=new int[16];
        private int fillIndex;private Canvas target;float scale,centerY;
        Drawing(Context c,IntroModel model){super(c);renderer=new IntroRenderer(model);setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);}
        @Override protected void onSizeChanged(int w,int h,int oldw,int oldh) {
            super.onSizeChanged(w,h,oldw,oldh);
            scale=Math.max(0,Math.min((w-dp(32))/720f,(h-greeting.getMeasuredHeight()-dp(112))/600f));
            centerY=h*.43f;positionGreeting();
        }
        @Override protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);target=canvas;fillIndex=0;
            canvas.save();canvas.translate(getWidth()/2f-360*scale,centerY-640*scale);canvas.scale(scale,scale);
            renderer.draw(this,elapsed);canvas.restore();target=null;
        }
        public void begin(){path.rewind();}public void move(float x,float y){path.moveTo(x,y);}public void line(float x,float y){path.lineTo(x,y);}
        public void cubic(float a,float b,float c,float d,float e,float f){path.cubicTo(a,b,c,d,e,f);}public void close(){path.close();}
        public void fill(int top,int middle,int bottom,float alpha) {
            if(light && Color.red(middle)>190 && Math.abs(Color.red(middle)-Color.blue(middle))<20) {
                // A quiet shadow under white faces; the registered fill and path stay unchanged.
                paint.setShader(null);paint.setStyle(Paint.Style.STROKE);paint.setStrokeJoin(Paint.Join.ROUND);
                paint.setColor(0xFF59616D);paint.setStrokeWidth(6);paint.setAlpha(Math.round(alpha*26));target.drawPath(path,paint);
                paint.setStrokeWidth(3);paint.setAlpha(Math.round(alpha*82));target.drawPath(path,paint);
            }
            paint.setStyle(Paint.Style.FILL);paint.setColor(top);paint.setShader(null);
            if(top!=middle||middle!=bottom) {
                int i=fillIndex;
                if(gradients[i]==null||tops[i]!=top||middles[i]!=middle||bottoms[i]!=bottom) {
                    gradients[i]=new LinearGradient(0,0,0,1,new int[]{top,middle,bottom},new float[]{0,.5f,1},Shader.TileMode.CLAMP);
                    tops[i]=top;middles[i]=middle;bottoms[i]=bottom;
                }
                path.computeBounds(bounds,true);shaderMatrix.setScale(1,Math.max(.01f,bounds.height()));shaderMatrix.postTranslate(0,bounds.top);
                gradients[i].setLocalMatrix(shaderMatrix);paint.setShader(gradients[i]);
            }
            paint.setAlpha(Math.round(alpha*255));target.drawPath(path,paint);fillIndex++;
        }
        public void stroke(int color,float width,float alpha) {
            paint.setShader(null);paint.setColor(color);paint.setAlpha(Math.round(alpha*255));paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeWidth(width);paint.setStrokeJoin(Paint.Join.ROUND);target.drawPath(path,paint);
        }
        public void clipLeft(float x){target.save();target.clipRect(x,-10000,10000,10000);}public void unclip(){target.restore();}
    }
}
