// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
package ru.threediwell.fm.core;

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;

/** Minimal HTTP stand-in for FM: one programmable answer per "METHOD /path". Synthetic data only. */
final class StubFm implements AutoCloseable {
    static final class Reply {
        final int status;final String body;final Map<String,String> headers=new LinkedHashMap<>();
        Reply(int status,String body){this.status=status;this.body=body;}
        Reply header(String name,String value){headers.put(name,value);return this;}
    }
    static final class Request {
        final String method,path,body,cookie;
        Request(String method,String path,String body,String cookie){this.method=method;this.path=path;this.body=body;this.cookie=cookie;}
    }
    private final ServerSocket server;private final Thread worker;
    final Map<String,Reply> replies=new ConcurrentHashMap<>();
    final List<Request> requests=Collections.synchronizedList(new ArrayList<>());
    final String origin;

    StubFm() throws IOException {
        server=new ServerSocket(0,8,InetAddress.getByName("127.0.0.1"));
        origin="http://127.0.0.1:"+server.getLocalPort();
        worker=new Thread(this::serve,"stub-fm");worker.setDaemon(true);worker.start();
    }
    void reply(String key,Reply reply){replies.put(key,reply);}
    Request last(String key){
        synchronized(requests){for(int i=requests.size()-1;i>=0;i--){Request r=requests.get(i);if((r.method+" "+r.path).equals(key))return r;}}
        return null;
    }
    int count(String key){int n=0;synchronized(requests){for(Request r:requests)if((r.method+" "+r.path).equals(key))n++;}return n;}

    private static String line(InputStream in) throws IOException {
        ByteArrayOutputStream b=new ByteArrayOutputStream();int c;
        while((c=in.read())>=0&&c!='\n')if(c!='\r')b.write(c);
        return b.toString(StandardCharsets.ISO_8859_1.name());
    }
    private void serve(){
        while(!server.isClosed()) try(Socket s=server.accept()){
            s.setSoTimeout(3000);InputStream in=s.getInputStream();OutputStream out=s.getOutputStream();
            String[] first=line(in).split(" ");String cookie=null;int length=0;
            for(String h;!(h=line(in)).isEmpty();){
                String lower=h.toLowerCase(Locale.ROOT);
                if(lower.startsWith("cookie:"))cookie=h.substring(7).trim();
                if(lower.startsWith("content-length:"))length=Integer.parseInt(h.substring(15).trim());
            }
            byte[] body=new byte[length];new DataInputStream(in).readFully(body);
            String key=first[0]+" "+first[1];
            requests.add(new Request(first[0],first[1],new String(body,StandardCharsets.UTF_8),cookie));
            Reply reply=replies.getOrDefault(key,new Reply(404,"{\"ok\":false,\"error\":\"not_found\"}"));
            byte[] bytes=reply.body.getBytes(StandardCharsets.UTF_8);
            StringBuilder head=new StringBuilder("HTTP/1.1 "+reply.status+" Stub\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: "+bytes.length+"\r\n");
            for(Map.Entry<String,String> h:reply.headers.entrySet())head.append(h.getKey()).append(": ").append(h.getValue()).append("\r\n");
            out.write(head.append("\r\n").toString().getBytes(StandardCharsets.US_ASCII));out.write(bytes);out.flush();
        }catch(IOException ignored){}
    }
    @Override public void close() throws Exception {server.close();worker.join(3000);}
}
