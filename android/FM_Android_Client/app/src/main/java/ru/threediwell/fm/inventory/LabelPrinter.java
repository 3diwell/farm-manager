// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.inventory;

import ru.threediwell.fm.i18n.I18n;
import android.app.Activity;
import android.graphics.*;
import android.graphics.pdf.PdfDocument;
import android.os.*;
import android.print.*;
import com.google.zxing.*;
import com.google.zxing.common.BitMatrix;
import java.io.*;
import java.util.*;

public final class LabelPrinter {
    public static Bitmap bitmap(String value) throws Exception {
        BitMatrix bits = new MultiFormatWriter().encode(value, BarcodeFormat.QR_CODE, 640, 640,
                Collections.singletonMap(EncodeHintType.MARGIN, 4));
        Bitmap b = Bitmap.createBitmap(640, 640, Bitmap.Config.ARGB_8888);
        int[] pixels=new int[640*640];
        for (int y=0; y<640; y++) for (int x=0; x<640; x++) pixels[y*640+x]=bits.get(x,y)?Color.BLACK:Color.WHITE;
        b.setPixels(pixels,0,640,0,0,640,640);
        return b;
    }
    /** Один файл, 8 этикеток на A4. Каждый QR создаётся только для подтверждённого ID. */
    public static void writeSheet(java.util.List<LabelSheet.Entry> source,OutputStream out) throws Exception {
        java.util.List<LabelSheet.Entry> entries=LabelSheet.validate(source);
        PdfDocument pdf=new PdfDocument();
        try {
            int count=LabelSheet.pages(entries.size());
            for(int n=0;n<count;n++) {
                PdfDocument.Page page=pdf.startPage(new PdfDocument.PageInfo.Builder(LabelSheet.WIDTH,LabelSheet.HEIGHT,n+1).create());
                Canvas c=page.getCanvas();c.drawColor(Color.WHITE);
                Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);p.setColor(Color.BLACK);p.setTextSize(12);p.setTypeface(Typeface.create("sans-serif",Typeface.BOLD));
                c.drawText(I18n.t("FM / Катушки филамента"),24,27,p);
                p.setTextSize(9);p.setTypeface(Typeface.create("sans-serif",Typeface.NORMAL));
                c.drawText(I18n.t("Лист ")+(n+1)+" / "+count+I18n.t("    •    Всего катушек: ")+entries.size(),24,43,p);
                for(int k=0;k<LabelSheet.PER_PAGE;k++) {
                    int index=n*LabelSheet.PER_PAGE+k;if(index>=entries.size()) break;
                    LabelSheet.Entry e=entries.get(index);LabelSheet.Cell cell=LabelSheet.cell(k);float x=cell.x(),y=cell.y();
                    p.setColor(0xFFBBBBBB);p.setStyle(Paint.Style.STROKE);p.setStrokeWidth(.5f);c.drawRoundRect(x,y,x+cell.width(),y+cell.height(),5,5,p);p.setStyle(Paint.Style.FILL);
                    drawVectorQr(c,e.code(),x+8,y+12,114);
                    p.setColor(Color.BLACK);p.setTextSize(10);p.setTypeface(Typeface.create("sans-serif",Typeface.BOLD));
                    // Номер строки PDF не является номером катушки: при перепечатке части партии он меняется.
                    c.drawText(I18n.t("FM · КАТУШКА"),x+130,y+24,p);
                    p.setTypeface(Typeface.create("sans-serif",Typeface.NORMAL));p.setTextSize(9);
                    wrap(c,p,e.caption(),x+130,y+42,129,7);
                    // ID не сокращается: даже при недоступной камере этикетку можно различить вручную.
                    p.setTextSize(7);wrap(c,p,e.id(),x+10,y+135,249,3);
                    p.setColor(0xFF555555);p.setTextSize(7);c.drawText(I18n.t("Наклейте на катушку • QR не содержит остаток"),x+10,y+168,p);
                }
                pdf.finishPage(page);
            }
            pdf.writeTo(out);
        } finally {pdf.close();}
    }
    private static void drawVectorQr(Canvas c,String value,float x,float y,float size) throws Exception {
        // Векторные чёрные модули: резкая печать без хранения сотен полноразмерных Bitmap.
        BitMatrix qr=new MultiFormatWriter().encode(value,BarcodeFormat.QR_CODE,0,0,Collections.singletonMap(EncodeHintType.MARGIN,4));
        Paint p=new Paint();p.setColor(Color.BLACK);float step=size/qr.getWidth();
        for(int row=0;row<qr.getHeight();row++)for(int col=0;col<qr.getWidth();) {
            if(!qr.get(col,row)){col++;continue;}
            int start=col;while(col<qr.getWidth()&&qr.get(col,row))col++;
            c.drawRect(x+start*step,y+row*step,x+col*step,y+(row+1)*step,p);
        }
    }
    private static void wrap(Canvas c,Paint p,String value,float x,float y,float width,int maxLines) {
        String remaining=value.replace('\n',' ').replace('\r',' ').trim();
        for(int line=0;line<maxLines&&!remaining.isEmpty();line++) {
            int take=p.breakText(remaining,true,width,null);if(take<=0) break;
            String part=remaining.substring(0,take);remaining=remaining.substring(take).trim();
            if(line==maxLines-1&&!remaining.isEmpty()) {
                while(!part.isEmpty()&&p.measureText(part+"…")>width) part=part.substring(0,part.length()-1);
                part+="…";
            }
            c.drawText(part,x,y+line*12,p);
        }
    }
    public static void print(Activity activity, String caption, Bitmap code) {
        PrintManager manager = (PrintManager) activity.getSystemService(Activity.PRINT_SERVICE);
        manager.print("FM — " + caption, new PrintDocumentAdapter() {
            @Override public void onLayout(PrintAttributes old, PrintAttributes current, CancellationSignal cancel, LayoutResultCallback cb, Bundle extras) {
                if (cancel.isCanceled()) { cb.onLayoutCancelled(); return; }
                cb.onLayoutFinished(new PrintDocumentInfo.Builder("FM-label.pdf").setPageCount(1)
                        .setContentType(PrintDocumentInfo.CONTENT_TYPE_DOCUMENT).build(), true);
            }
            @Override public void onWrite(PageRange[] ranges, ParcelFileDescriptor dest, CancellationSignal cancel, WriteResultCallback cb) {
                if (cancel.isCanceled()) { cb.onWriteCancelled(); return; }
                PdfDocument pdf = new PdfDocument();
                try {
                    PdfDocument.Page page = pdf.startPage(new PdfDocument.PageInfo.Builder(595,842,1).create());
                    Canvas c = page.getCanvas(); c.drawColor(Color.WHITE);
                    c.drawBitmap(code, null, new Rect(36,50,180,194), null);
                    Paint p = new Paint(Paint.ANTI_ALIAS_FLAG); p.setColor(Color.BLACK); p.setTextSize(10);
                    for (int i=0; i<caption.length(); i+=70) c.drawText(caption.substring(i,Math.min(i+70,caption.length())),36,215+(i/70)*14,p);
                    pdf.finishPage(page);
                    try (FileOutputStream out = new FileOutputStream(dest.getFileDescriptor())) { pdf.writeTo(out); }
                    cb.onWriteFinished(new PageRange[]{new PageRange(0,0)});
                } catch (Exception ex) { cb.onWriteFailed(I18n.t("Не удалось сформировать PDF")); }
                finally { pdf.close(); }
            }
        }, new PrintAttributes.Builder().setMediaSize(PrintAttributes.MediaSize.ISO_A4).build());
    }
}
