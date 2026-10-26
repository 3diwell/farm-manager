// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm;

import ru.threediwell.fm.i18n.I18n;
import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.graphics.*;
import android.view.*;
import android.widget.*;
import ru.threediwell.fm.ui.FmActivity;
import androidx.camera.core.*;
import androidx.camera.lifecycle.ProcessCameraProvider;
import androidx.camera.view.PreviewView;
import androidx.camera.view.transform.*;
import androidx.core.content.ContextCompat;
import com.google.mlkit.vision.barcode.BarcodeScanning;
import com.google.mlkit.vision.common.InputImage;
import com.google.mlkit.vision.text.TextRecognition;
import com.google.mlkit.vision.text.latin.TextRecognizerOptions;
import ru.threediwell.fm.ui.FmStyle;
import ru.threediwell.fm.ui.OperationFlow;
import ru.threediwell.fm.ui.OperationHintView;
import ru.threediwell.fm.scan.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

/** Native local recognition of a cropped image, never the entire camera frame. */
public class ScannerActivity extends FmActivity {
    private final ExecutorService frames=Executors.newSingleThreadExecutor();
    private final AtomicBoolean busy=new AtomicBoolean();
    private final com.google.mlkit.vision.barcode.BarcodeScanner barcode=BarcodeScanning.getClient();
    private final com.google.mlkit.vision.text.TextRecognizer text=TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS);
    private final StableCode stable=new StableCode();
    private ProcessCameraProvider provider;
    private Preview cameraPreview;
    private ImageAnalysis cameraAnalysis;
    private PreviewView preview;
    private ImageView frozen;
    private Guide guide;
    private TextView hint,result;
    private LinearLayout choices, toolsRow;
    private Button confirm,again,torch,mode;
    private FmStyle style;
    private ScanPolicy policy;
    private volatile boolean ocr,choosing,finished,paused=true;
    private volatile int generation;
    private long lastFrame;
    private String selected;
    private Bitmap snapshot;
    private List<Candidate> candidates=Collections.emptyList();
    private record Candidate(String code,String caption,RectF bounds){}

    @Override public void onCreate(Bundle state) {
        setTheme(FmStyle.theme(this));super.onCreate(state);style=new FmStyle(this);
        try{policy=new ScanPolicy(getIntent().getStringExtra("scan_kind"),getIntent().getStringExtra("server_id"),getIntent().getStringExtra("slot_catalog"));}
        catch(Exception e){finish();return;}
        ocr=!policy.qrOnly()&&state!=null&&state.getBoolean("ocr",false);
        boolean landscape=getResources().getConfiguration().orientation==android.content.res.Configuration.ORIENTATION_LANDSCAPE;
        LinearLayout host=new LinearLayout(this);host.setOrientation(landscape?LinearLayout.HORIZONTAL:LinearLayout.VERTICAL);host.setBackgroundColor(style.bg);
        LinearLayout root=new LinearLayout(this);root.setOrientation(LinearLayout.VERTICAL);root.setPadding(style.dp(16),style.dp(12),style.dp(16),style.dp(12));
        ScrollView controls=new ScrollView(this);controls.setFillViewport(true);controls.addView(root);
        host.addView(controls,new LinearLayout.LayoutParams(landscape?style.dp(320):-1,landscape?-1:0,landscape?0:1));
        setContentView(host);style.systemBars(this,host);
        host.setOnApplyWindowInsetsListener((v,insets)->{v.setPadding(insets.getSystemWindowInsetLeft(),insets.getSystemWindowInsetTop(),insets.getSystemWindowInsetRight(),insets.getSystemWindowInsetBottom());return insets;});
        TextView title=style.label(policy.printerOnly()?I18n.t("Сканирование принтера"):policy.slotOnly()?I18n.t("Выберите позицию"):ScanPolicy.ANY.equals(getIntent().getStringExtra("scan_kind"))?I18n.t("Сканирование"):I18n.t("Сканирование катушки"),23,style.text);root.addView(title);
        TextView purpose=style.label(getIntent().getStringExtra("purpose"),14,style.accent);purpose.setPadding(0,style.dp(8),0,style.dp(12));root.addView(purpose);
        FrameLayout cameraFrame=new FrameLayout(this);cameraFrame.setBackground(style.box(Color.BLACK,18));cameraFrame.setClipToOutline(true);
        if(landscape)host.addView(cameraFrame,0,new LinearLayout.LayoutParams(0,-1,1));
        else root.addView(cameraFrame,new LinearLayout.LayoutParams(-1,style.dp(240)));
        preview=new PreviewView(this);preview.setImplementationMode(PreviewView.ImplementationMode.COMPATIBLE);preview.setScaleType(PreviewView.ScaleType.FILL_CENTER);
        cameraFrame.addView(preview,new FrameLayout.LayoutParams(-1,-1));
        frozen=new ImageView(this);frozen.setScaleType(ImageView.ScaleType.FIT_XY);frozen.setVisibility(View.GONE);cameraFrame.addView(frozen,new FrameLayout.LayoutParams(-1,-1));
        guide=new Guide();cameraFrame.addView(guide,new FrameLayout.LayoutParams(-1,-1));
        hint=style.label("",14,style.muted);hint.setPadding(0,style.dp(10),0,style.dp(10));hint.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);root.addView(hint);
        root.addView(new OperationHintView(this,style,OperationFlow.fromExtra(getIntent().getStringExtra(OperationFlow.EXTRA)),true));
        result=style.label("",17,style.text);result.setPadding(style.dp(16),style.dp(14),style.dp(16),style.dp(14));result.setBackground(style.box(style.card,16));root.addView(result);
        choices=new LinearLayout(this);choices.setOrientation(LinearLayout.VERTICAL);root.addView(choices);
        confirm=control(root,I18n.t("Выбрать этот слот"),true,()->{String code=selected;if(code!=null&&choosing)complete(code);});
        again=control(root,I18n.t("Навести на другую метку"),false,this::resetScan);
        LinearLayout tools=new LinearLayout(this);toolsRow=tools;root.addView(tools);
        torch=control(tools,I18n.t("Фонарик"),false,()->{});torch.setEnabled(false);compact(torch);
        if(getIntent().getBooleanExtra("allow_nfc",false)) {
            Button nfc=control(tools,"NFC Bambu",false,()->{if(finished)return;finished=true;setResult(RESULT_OK,new Intent().putExtra("nfc_requested",true));finish();});compact(nfc);style.icon(nfc,"nfc",style.accent);
        }
        if(!policy.qrOnly())mode=control(root,"",false,()->{ocr=!ocr;resetScan();});
        control(root,policy.printerOnly()?I18n.t("Назад"):I18n.t("Назад / ручной ввод"),false,this::finish);
        resetScan();
        preview.addOnLayoutChangeListener((v,l,t,r,b,ol,ot,or,ob)->{if(r-l!=or-ol||b-t!=ob-ot)resetScan();});
        if(checkSelfPermission(Manifest.permission.CAMERA)==PackageManager.PERMISSION_GRANTED)preview.post(this::startCamera);
        else requestPermissions(new String[]{Manifest.permission.CAMERA},51);
    }
    private Button control(LinearLayout parent,String label,boolean primary,Runnable action) {
        Button b=new Button(this);b.setText(label);style.button(b,primary);parent.addView(b);b.setOnClickListener(v->action.run());return b;
    }
    private void compact(Button b){LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(0,-2,1);p.setMargins(style.dp(3),style.dp(4),style.dp(3),style.dp(4));b.setLayoutParams(p);b.setTextSize(14);}
    private void resetScan() {
        generation++;stable.reset();selected=null;choosing=false;candidates=Collections.emptyList();
        if(frozen==null)return;
        frozen.setImageDrawable(null);frozen.setVisibility(View.GONE);if(snapshot!=null){snapshot.recycle();snapshot=null;}
        choices.removeAllViews();confirm.setEnabled(false);confirm.setVisibility(View.GONE);again.setVisibility(View.GONE);result.setVisibility(View.GONE);
        if(toolsRow!=null)toolsRow.setVisibility(View.VISIBLE);
        if(mode!=null)mode.setVisibility(View.VISIBLE);
        hint.setText(ocr?I18n.t("Только текст внутри рамки · латиница. Результат нужно проверить."):policy.printerOnly()?I18n.t("Наведите на QR позиции принтера. Откроется его карточка."):policy.slotOnly()?I18n.t("Поместите один QR в рамку. После чтения выберите слот кнопкой."):I18n.t("Только код внутри рамки. Удержите телефон неподвижно."));
        if(mode!=null)mode.setText(ocr?I18n.t("Вернуться к QR / штрихкодам"):I18n.t("На этикетке только текст (латиница)"));
        if(guide!=null)guide.invalidate();
    }
    @Override public void onRequestPermissionsResult(int request,String[] permissions,int[] grants){super.onRequestPermissionsResult(request,permissions,grants);
        if(request==51&&grants.length>0&&grants[0]==PackageManager.PERMISSION_GRANTED)preview.post(this::startCamera);
        else hint.setText(policy.printerOnly()?I18n.t("Камера не разрешена. Вернитесь и выберите принтер из списка."):I18n.t("Камера не разрешена. Доступен ручной ввод по кнопке «Назад»."));}

    private void startCamera() {
        if(isDestroyed()||isFinishing())return;
        if(preview.getWidth()==0||preview.getHeight()==0){preview.post(this::startCamera);return;}
        var future=ProcessCameraProvider.getInstance(this);
        future.addListener(()->{
            try {
                if(isDestroyed()||isFinishing())return;provider=future.get();
                int rotation=preview.getDisplay().getRotation();
                Preview view=new Preview.Builder().setTargetRotation(rotation).build();cameraPreview=view;view.setSurfaceProvider(preview.getSurfaceProvider());
                ImageAnalysis analysis=new ImageAnalysis.Builder().setTargetRotation(rotation).setTargetResolution(new android.util.Size(1280,720))
                        .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST).build();
                cameraAnalysis=analysis;analysis.setAnalyzer(frames,this::analyze);
                // Shared viewport: analysis and preview may have different resolutions/crops.
                ViewPort viewport=preview.getViewPort();if(viewport==null)throw new IllegalStateException("No viewport");
                androidx.camera.core.Camera camera=provider.bindToLifecycle(this,CameraSelector.DEFAULT_BACK_CAMERA,new UseCaseGroup.Builder()
                        .setViewPort(viewport).addUseCase(view).addUseCase(analysis).build());
                if(camera.getCameraInfo().hasFlashUnit()){
                    torch.setEnabled(true);torch.setOnClickListener(v->{boolean on=Integer.valueOf(TorchState.ON).equals(camera.getCameraInfo().getTorchState().getValue());camera.getCameraControl().enableTorch(!on);});
                    camera.getCameraInfo().getTorchState().observe(this,s->torch.setText(s==TorchState.ON?I18n.t("Свет: вкл"):I18n.t("Фонарик")));
                }
                guide.setOnTouchListener((v,event)->{
                    if(event.getAction()==android.view.MotionEvent.ACTION_UP){
                        if(choosing){for(Candidate c:candidates)if(c.bounds.contains(event.getX(),event.getY())){choose(c);break;}}
                        else {var point=preview.getMeteringPointFactory().createPoint(event.getX(),event.getY());camera.getCameraControl().startFocusAndMetering(new FocusMeteringAction.Builder(point).build());}
                        v.performClick();
                    }return true;
                });
            }catch(Exception ex){hint.setText(I18n.t("Камера недоступна. Вернитесь к ручному вводу."));}
        },ContextCompat.getMainExecutor(this));
    }
    private RectF aim(){AimWindow.Box b=AimWindow.inView(preview.getWidth(),preview.getHeight(),policy.qrOnly());return new RectF(b.left(),b.top(),b.right(),b.bottom());}
    private static AimWindow.Box box(RectF r){return new AimWindow.Box(r.left,r.top,r.right,r.bottom);}
    private boolean active(int ticket){return ticket==generation&&!finished&&!paused&&!choosing&&!isFinishing()&&!isDestroyed();}

    @androidx.annotation.OptIn(markerClass=androidx.camera.view.TransformExperimental.class)
    private void analyze(ImageProxy frame) {
        long now=android.os.SystemClock.elapsedRealtime();
        if(finished||paused||choosing||now-lastFrame<180||!busy.compareAndSet(false,true)){frame.close();return;}
        lastFrame=now;int ticket=generation;
        runOnUiThread(()->{
            if(!active(ticket)){frame.close();busy.set(false);return;}
            try {
                OutputTransform target=preview.getOutputTransform();
                if(target==null){frame.close();busy.set(false);return;}
                int displayRotation=preview.getDisplay().getRotation();
                if(cameraAnalysis.getTargetRotation()!=displayRotation){
                    cameraAnalysis.setTargetRotation(displayRotation);cameraPreview.setTargetRotation(displayRotation);resetScan();frame.close();busy.set(false);return;
                }
                ImageProxyTransformFactory factory=new ImageProxyTransformFactory();factory.setUsingRotationDegrees(true);factory.setUsingCropRect(false);
                Matrix toView=new Matrix();new CoordinateTransform(factory.getOutputTransform(frame),target).transform(toView);
                Matrix inverse=new Matrix();if(!toView.invert(inverse))throw new IllegalStateException("Invalid camera transform");
                RectF region=aim(),mapped=new RectF(region);inverse.mapRect(mapped);
                boolean textMode=ocr;
                frames.execute(()->recognize(frame,toView,mapped,region,ticket,textMode));
            }catch(Exception e){frame.close();busy.set(false);stable.reset();}
        });
    }
    private void recognize(ImageProxy frame,Matrix toView,RectF mapped,RectF region,int ticket,boolean textMode) {
        Bitmap raw=null,upright=null,crop=null;
        try {
            int rotation=frame.getImageInfo().getRotationDegrees();raw=frame.toBitmap();
            Matrix rotate=new Matrix();rotate.postRotate(rotation);
            upright=Bitmap.createBitmap(raw,0,0,raw.getWidth(),raw.getHeight(),rotate,true);
            if(raw!=upright)raw.recycle();raw=null;
            AimWindow.Box b=AimWindow.inward(box(mapped),upright.getWidth(),upright.getHeight());
            int left=(int)b.left(),top=(int)b.top();crop=Bitmap.createBitmap(upright,left,top,(int)b.width(),(int)b.height());
            final Bitmap full=upright,inputBitmap=crop;
            // ONLY the crop reaches ML Kit. No full-frame fallback for either barcode or OCR.
            InputImage input=InputImage.fromBitmap(inputBitmap,0);
            if(textMode) {
                text.process(input).addOnSuccessListener(r->{if(active(ticket)&&!r.getText().trim().isEmpty()){
                    freeze(full,toView);editText(r.getText().trim());
                }}).addOnFailureListener(e->{if(active(ticket)){stable.reset();hint.setText(I18n.t("Не удалось прочитать текст. Повторите наведение или введите вручную."));}})
                        .addOnCompleteListener(t->release(full,inputBitmap));
            } else {
                barcode.process(input).addOnSuccessListener(codes->{
                    if(!active(ticket))return;
                    List<Candidate> found=new ArrayList<>();String rejected="";
                    for(var code:codes){
                        Rect bounds=code.getBoundingBox();String value=code.getRawValue();if(bounds==null||value==null)continue;
                        RectF r=new RectF(bounds);r.offset(left,top);toView.mapRect(r);if(!box(region).contains(box(r)))continue;
                        try{found.add(new Candidate(value,policy.caption(value),r));}catch(Exception e){rejected=e.getMessage();}
                    }
                    candidates=found;guide.invalidate();
                    if(found.size()>1){stable.reset();freeze(full,toView);showChoices();}
                    else if(found.size()==1){Candidate c=found.get(0);
                        if(stable.observe(c.code,box(c.bounds),android.os.SystemClock.elapsedRealtime())) {
                            if(policy.needsConfirmation(c.code)){freeze(full,toView);choose(c);}else complete(c.code);
                        }else hint.setText(I18n.t("Метка в прицеле · удержите телефон неподвижно"));
                    }else {stable.reset();hint.setText(rejected.isEmpty()?I18n.t("Наведите весь код внутрь рамки · касание для фокуса"):rejected);}
                }).addOnFailureListener(e->{if(active(ticket)){stable.reset();hint.setText(I18n.t("Не удалось прочитать код. Повторите наведение или введите вручную."));}})
                        .addOnCompleteListener(t->release(full,inputBitmap));
            }
        }catch(Exception e){
            if(crop!=null&&crop!=upright)crop.recycle();if(upright!=null)upright.recycle();if(raw!=null&&!raw.isRecycled())raw.recycle();busy.set(false);
            runOnUiThread(()->{if(active(ticket)){stable.reset();hint.setText(I18n.t("Не удалось подготовить область камеры. Повторите наведение или используйте ручной ввод."));}});
        }finally{frame.close();}
    }
    private void release(Bitmap full,Bitmap cropped){if(cropped!=full)cropped.recycle();full.recycle();busy.set(false);}
    private void freeze(Bitmap full,Matrix toView){
        choosing=true;stable.reset();snapshot=Bitmap.createBitmap(preview.getWidth(),preview.getHeight(),Bitmap.Config.ARGB_8888);
        Canvas c=new Canvas(snapshot);c.drawBitmap(full,toView,new Paint(Paint.FILTER_BITMAP_FLAG));
        frozen.setImageBitmap(snapshot);frozen.setVisibility(View.VISIBLE);again.setVisibility(View.VISIBLE);
        toolsRow.setVisibility(View.GONE);if(mode!=null)mode.setVisibility(View.GONE);
    }
    private void showChoices(){
        hint.setText(I18n.t("В рамке несколько меток. Кадр зафиксирован."));result.setText(I18n.t("Коснитесь нужного QR или выберите подпись ниже"));result.setVisibility(View.VISIBLE);
        choices.removeAllViews();confirm.setVisibility(View.GONE);
        for(Candidate c:candidates)control(choices,c.caption,false,()->choose(c));
    }
    private void choose(Candidate c){
        selected=c.code;choices.removeAllViews();result.setVisibility(View.VISIBLE);result.setText(c.caption);
        hint.setText(policy.printerOnly()?I18n.t("Проверьте название принтера перед открытием карточки."):policy.needsConfirmation(c.code)?I18n.t("Проверьте позицию. Склад пока не изменён."):I18n.t("Проверьте выбранную метку перед продолжением."));
        confirm.setText(policy.printerOnly()?I18n.t("Открыть карточку принтера"):policy.needsConfirmation(c.code)?I18n.t("Выбрать этот слот"):I18n.t("Использовать этот код"));confirm.setEnabled(true);confirm.setVisibility(View.VISIBLE);guide.invalidate();
    }
    private void editText(String raw){
        EditText value=new EditText(this);value.setText(raw);int ticket=generation;
        new android.app.AlertDialog.Builder(this).setTitle(I18n.t("Оставьте SKU или уникальный ID"))
                .setMessage(I18n.t("Проверьте текст: особенно 0/O и 1/I. Русский текст пока вводится вручную.")).setView(value)
                .setPositiveButton(I18n.t("Использовать"),(d,w)->{if(ticket!=generation||paused)return;try{String code=value.getText().toString().trim();policy.caption(code);
                    if(policy.needsConfirmation(code)){choose(new Candidate(code,policy.caption(code),new RectF()));}else complete(code);
                }catch(Exception e){resetScan();hint.setText(e.getMessage());}})
                .setNegativeButton(I18n.t("Повторить"),(d,w)->resetScan()).setOnCancelListener(d->resetScan()).show();
    }
    private void complete(String value){if(finished||paused)return;finished=true;generation++;setResult(RESULT_OK,new Intent().putExtra("code",value));finish();}
    @Override protected void onResume(){super.onResume();paused=false;}
    @Override protected void onPause(){paused=true;resetScan();super.onPause();}
    @Override protected void onSaveInstanceState(Bundle state){state.putBoolean("ocr",ocr);super.onSaveInstanceState(state);}
    @Override public void onDestroy(){finished=true;generation++;if(provider!=null&&cameraPreview!=null&&cameraAnalysis!=null)provider.unbind(cameraPreview,cameraAnalysis);frames.shutdown();barcode.close();text.close();super.onDestroy();}

    private final class Guide extends View {
        private final Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);
        Guide(){super(ScannerActivity.this);setContentDescription(I18n.t("Прицел камеры. Касание для фокуса; на зафиксированном кадре — выбор метки."));}
        @Override public boolean performClick(){super.performClick();return true;}
        @Override protected void onDraw(Canvas canvas){
            if(getWidth()==0||getHeight()==0)return;RectF r=aim();p.setStyle(Paint.Style.FILL);p.setColor(0xB3000000);
            canvas.drawRect(0,0,getWidth(),r.top,p);canvas.drawRect(0,r.bottom,getWidth(),getHeight(),p);
            canvas.drawRect(0,r.top,r.left,r.bottom,p);canvas.drawRect(r.right,r.top,getWidth(),r.bottom,p);
            p.setStyle(Paint.Style.STROKE);p.setColor(style.accent);p.setStrokeWidth(style.dp(2));canvas.drawRoundRect(r,style.dp(10),style.dp(10),p);
            for(Candidate c:candidates){p.setStrokeWidth(style.dp(c.code.equals(selected)?4:2));canvas.drawRect(c.bounds,p);}
        }
    }
}
