// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.core;

import org.json.JSONObject;
import javax.net.ssl.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.util.*;

/** Узкий RFC6455-клиент для /ws. Только чтение состояний, ping/pong и закрытие. */
public final class TelemetryClient implements AutoCloseable {
    public interface Listener {void snapshot(JSONObject states);void disconnected(Exception error);}
    private final FmApi api;private final Listener listener;
    private volatile boolean closed;private volatile Socket socket;private Thread worker;
    public TelemetryClient(FmApi api,Listener listener){this.api=api;this.listener=listener;}
    public synchronized void start(){if(worker!=null)return;worker=new Thread(this::loop,"fm-telemetry");worker.setDaemon(true);worker.start();}
    private void loop(){
        while(!closed){
            try{readConnection();}catch(Exception ex){if(!closed)listener.disconnected(ex);if(ex instanceof FmApi.Unauthorized)break;}
            finally{Socket s=socket;socket=null;if(s!=null)try{s.close();}catch(IOException ignored){}}
            if(!closed)try{Thread.sleep(3000);}catch(InterruptedException ex){break;}
        }
    }
    private void readConnection() throws Exception {
        URI origin=URI.create(api.origin);boolean tls="https".equals(origin.getScheme());int port=origin.getPort();if(port<0)port=tls?443:80;
        Socket raw=new Socket();socket=raw;raw.connect(new InetSocketAddress(origin.getHost(),port),8000);raw.setSoTimeout(10000);
        if(closed)throw new IOException("closed");
        if(tls){SSLSocket secure=(SSLSocket)((SSLSocketFactory)SSLSocketFactory.getDefault()).createSocket(raw,origin.getHost(),port,true);SSLParameters params=secure.getSSLParameters();params.setEndpointIdentificationAlgorithm("HTTPS");secure.setSSLParameters(params);secure.startHandshake();socket=secure;}
        InputStream input=socket.getInputStream();OutputStream output=socket.getOutputStream();
        byte[] nonce=new byte[16];new SecureRandom().nextBytes(nonce);String key=Base64.getEncoder().encodeToString(nonce);
        StringBuilder request=new StringBuilder("GET /ws HTTP/1.1\r\nHost: ").append(origin.getRawAuthority()).append("\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: ").append(key).append("\r\n");
        for(var header:api.sessionHeaders("/ws").entrySet())request.append(header.getKey()).append(": ").append(String.join("; ",header.getValue())).append("\r\n");
        request.append("\r\n");output.write(request.toString().getBytes(StandardCharsets.ISO_8859_1));output.flush();
        String status=line(input);if(status.contains(" 401 ")||status.contains(" 403 "))throw new FmApi.Unauthorized();if(!status.startsWith("HTTP/1.1 101 "))throw new IOException("FM: WebSocket unavailable");
        String accept="";int headerBytes=status.length();for(String value;!(value=line(input)).isEmpty();){headerBytes+=value.length();if(headerBytes>16384)throw new IOException("WS headers too large");int colon=value.indexOf(':');if(colon>0&&"sec-websocket-accept".equalsIgnoreCase(value.substring(0,colon)))accept=value.substring(colon+1).trim();}
        String expected=Base64.getEncoder().encodeToString(MessageDigest.getInstance("SHA-1").digest((key+"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").getBytes(StandardCharsets.US_ASCII)));
        if(!expected.equals(accept))throw new IOException("Invalid WS handshake");
        ByteArrayOutputStream fragments=null;
        while(!closed){
            if(api.sessionExpired())throw new FmApi.SessionExpired();
            int first=readByte(input),second=readByte(input),opcode=first&15;boolean fin=(first&128)!=0;
            if((first&112)!=0||(second&128)!=0)throw new IOException("Invalid server frame");
            long size=second&127;if(size==126)size=(readByte(input)<<8)|readByte(input);else if(size==127){size=0;for(int i=0;i<8;i++)size=(size<<8)|readByte(input);}
            if(size<0||size>16*1024*1024||(opcode>=8&&(!fin||size>125)))throw new IOException("WS frame too large");
            byte[] data=new byte[(int)size];new DataInputStream(input).readFully(data);
            if(opcode==8){int code=data.length>=2?((data[0]&255)<<8)|(data[1]&255):1000;if(code==1008||code==4401||code==4403)throw new FmApi.Unauthorized();throw new EOFException("WS closed");}
            if(opcode==9){pong(output,data);continue;}if(opcode==10)continue;
            if(opcode==1){if(fragments!=null)throw new IOException("Unexpected WS text frame");fragments=new ByteArrayOutputStream();}
            else if(opcode!=0||fragments==null)throw new IOException("Unexpected WS continuation");
            if(fragments.size()+data.length>16*1024*1024)throw new IOException("WS message too large");fragments.write(data);
            if(fin){listener.snapshot(new JSONObject(fragments.toString(StandardCharsets.UTF_8.name())));fragments=null;}
        }
    }
    private static String line(InputStream input) throws IOException {ByteArrayOutputStream line=new ByteArrayOutputStream();int b;while((b=readByte(input))!='\n'){if(line.size()>8192)throw new IOException("WS header too large");if(b!='\r')line.write(b);}return line.toString(StandardCharsets.ISO_8859_1.name());}
    private static int readByte(InputStream input) throws IOException {int b=input.read();if(b<0)throw new EOFException();return b;}
    private static void pong(OutputStream output,byte[] data) throws IOException {byte[] mask=new byte[4];new SecureRandom().nextBytes(mask);output.write(0x8a);output.write(0x80|data.length);output.write(mask);for(int i=0;i<data.length;i++)output.write(data[i]^mask[i%4]);output.flush();}
    @Override public void close(){closed=true;Socket s=socket;if(s!=null)try{s.close();}catch(IOException ignored){}Thread t=worker;if(t!=null)t.interrupt();}
}
