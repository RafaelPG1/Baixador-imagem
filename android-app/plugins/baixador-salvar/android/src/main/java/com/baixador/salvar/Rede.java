package com.baixador.salvar;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.ConnectException;
import java.net.HttpURLConnection;
import java.net.NoRouteToHostException;
import java.net.SocketTimeoutException;
import java.net.URL;
import java.net.UnknownHostException;
import java.util.Map;
import javax.net.ssl.SSLException;

/**
 * HTTP nativo (fora do WebView) para falar com o notebook. O fetch() do WebView depende de CORS, de regras de rede local e de
 * conteúdo misto, e quando algo disso barra a chamada ele só diz "Failed to fetch". Aqui a falha vem com um código que diz
 * qual etapa quebrou: DNS, TIMEOUT, RECUSADA, SEM_ROTA, SSL, REDE, INCOMPLETO. Sem dependência do Android (testável com a JVM).
 */
final class Rede {

    static final class Resposta {
        int status;
        String tipo = "";
        byte[] corpo = new byte[0];
    }

    static final class Falha extends Exception {
        final String codigo;

        Falha(String codigo, String mensagem, Throwable causa) {
            super(mensagem, causa);
            this.codigo = codigo;
        }
    }

    interface Progresso {
        void aoReceber(long recebido, long total);
    }

    private Rede() {}

    static Falha classificar(Exception e) {
        String m = e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage();
        if (e instanceof UnknownHostException) return new Falha("DNS", m, e);
        if (e instanceof SocketTimeoutException) return new Falha("TIMEOUT", m, e);
        if (e instanceof ConnectException) return new Falha("RECUSADA", m, e);
        if (e instanceof NoRouteToHostException) return new Falha("SEM_ROTA", m, e);
        if (e instanceof SSLException) return new Falha("SSL", m, e);
        return new Falha("REDE", m, e);
    }

    private static HttpURLConnection abrir(String url, Map<String, String> cabecalhos, int limiteMs) throws IOException {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setRequestMethod("GET");
        c.setConnectTimeout(15000);
        c.setReadTimeout(limiteMs > 0 ? limiteMs : 120000);
        c.setUseCaches(false);
        for (Map.Entry<String, String> h : cabecalhos.entrySet()) c.setRequestProperty(h.getKey(), h.getValue());
        return c;
    }

    /** GET que devolve o corpo na memória (JSON, capas). Qualquer status HTTP volta como resposta; só falha de rede vira Falha. */
    static Resposta obter(String url, Map<String, String> cabecalhos, int limiteMs, long maxBytes) throws Falha {
        HttpURLConnection c = null;
        try {
            c = abrir(url, cabecalhos, limiteMs);
            Resposta r = new Resposta();
            r.status = c.getResponseCode();
            r.tipo = c.getContentType() == null ? "" : c.getContentType();
            InputStream e = r.status >= 400 ? c.getErrorStream() : c.getInputStream();
            if (e != null) {
                try (InputStream in = e) {
                    ByteArrayOutputStream saida = new ByteArrayOutputStream();
                    byte[] b = new byte[16 * 1024];
                    int n;
                    while ((n = in.read(b)) != -1) {
                        saida.write(b, 0, n);
                        if (saida.size() > maxBytes) throw new Falha("GRANDE", "Resposta grande demais.", null);
                    }
                    r.corpo = saida.toByteArray();
                }
            }
            return r;
        } catch (Falha f) {
            throw f;
        } catch (Exception e) {
            throw classificar(e);
        } finally {
            if (c != null) c.disconnect();
        }
    }

    /** GET que grava direto em arquivo (ZIPs grandes: nada fica inteiro na memória). Devolve o status e confere o tamanho. */
    static long baixar(String url, Map<String, String> cabecalhos, File destino, int limiteMs, Progresso p) throws Falha {
        HttpURLConnection c = null;
        try {
            c = abrir(url, cabecalhos, limiteMs);
            int status = c.getResponseCode();
            if (status != 200) throw new Falha("HTTP_" + status, "O notebook respondeu " + status + ".", null);
            long total = c.getContentLengthLong(), recebido = 0, ultimo = 0;
            try (InputStream in = c.getInputStream(); OutputStream out = new FileOutputStream(destino)) {
                byte[] b = new byte[64 * 1024];
                int n;
                while ((n = in.read(b)) != -1) {
                    out.write(b, 0, n);
                    recebido += n;
                    long agora = System.currentTimeMillis();
                    if (p != null && agora - ultimo > 250) {
                        ultimo = agora;
                        p.aoReceber(recebido, total);
                    }
                }
            }
            if (total > 0 && recebido != total) throw new Falha("INCOMPLETO", "Download incompleto.", null);
            return recebido;
        } catch (Falha f) {
            destino.delete();
            throw f;
        } catch (Exception e) {
            destino.delete();
            throw classificar(e);
        } finally {
            if (c != null) c.disconnect();
        }
    }
}
