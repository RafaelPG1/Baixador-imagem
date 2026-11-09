package com.baixador.salvar;

import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Intent;
import android.os.Build;
import android.provider.Settings;
import androidx.core.content.FileProvider;
import java.io.File;
import java.io.FileOutputStream;
import android.net.Uri;
import android.os.Environment;
import android.provider.MediaStore;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.Iterator;

/**
 * Baixa um ZIP do notebook (HTTPS, com o cabeçalho Authorization) direto para Download/Baixador/&lt;pasta&gt;/ no celular.
 * Usa o MediaStore: não pede permissão de armazenamento e o arquivo aparece no app Arquivos. O download vai em pedaços
 * (não carrega o ZIP inteiro na memória) e avisa o progresso pelo evento "progresso".
 */
@CapacitorPlugin(name = "SalvarZip")
public class SalvarZipPlugin extends Plugin {

    /** Tira caracteres que não podem ir em nome de arquivo/pasta e limita o tamanho. */
    private static String limpar(String texto) {
        if (texto == null) {
            return "";
        }
        String s = texto.replaceAll("[\\\\/:*?\"<>|\\p{Cntrl}]", "_").replaceAll("^[ .]+|[ .]+$", "");
        return s.length() > 120 ? s.substring(0, 120) : s;
    }

    @PluginMethod
    public void salvar(final PluginCall call) {
        final String endereco = call.getString("url");
        final String pasta = limpar(call.getString("pasta", ""));
        String pedido = limpar(call.getString("nome", "baixador.zip"));
        final String nome = pedido.isEmpty() ? "baixador.zip" : pedido;
        final String id = call.getString("id", "");
        final JSObject cabecalhos = call.getObject("headers", new JSObject());
        if (endereco == null || !endereco.startsWith("https://")) {
            call.reject("Endereço inválido: só HTTPS.");
            return;
        }
        new Thread(
            new Runnable() {
                @Override
                public void run() {
                    ContentResolver resolver = getContext().getContentResolver();
                    Uri destino = null;
                    HttpURLConnection conexao = null;
                    try {
                        conexao = (HttpURLConnection) new URL(endereco).openConnection();
                        conexao.setRequestMethod("GET");
                        conexao.setConnectTimeout(20000);
                        conexao.setReadTimeout(120000);
                        Iterator<String> chaves = cabecalhos.keys();
                        while (chaves.hasNext()) {
                            String chave = chaves.next();
                            conexao.setRequestProperty(chave, cabecalhos.getString(chave));
                        }
                        int status = conexao.getResponseCode();
                        if (status != 200) {
                            call.reject("O notebook respondeu " + status + ".");
                            return;
                        }
                        long total = conexao.getContentLengthLong();
                        String relativo = Environment.DIRECTORY_DOWNLOADS + "/Baixador" + (pasta.isEmpty() ? "" : "/" + pasta);
                        ContentValues valores = new ContentValues();
                        valores.put(MediaStore.MediaColumns.DISPLAY_NAME, nome);
                        valores.put(MediaStore.MediaColumns.MIME_TYPE, "application/zip");
                        valores.put(MediaStore.MediaColumns.RELATIVE_PATH, relativo);
                        valores.put(MediaStore.MediaColumns.IS_PENDING, 1);
                        destino = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, valores);
                        if (destino == null) {
                            call.reject("Não consegui criar o arquivo em Downloads.");
                            return;
                        }
                        long recebido = 0;
                        long ultimoAviso = 0;
                        byte[] buffer = new byte[64 * 1024];
                        try (InputStream entrada = conexao.getInputStream(); OutputStream saida = resolver.openOutputStream(destino)) {
                            if (saida == null) {
                                throw new java.io.IOException("Sem acesso para gravar o arquivo.");
                            }
                            int lidos;
                            while ((lidos = entrada.read(buffer)) != -1) {
                                saida.write(buffer, 0, lidos);
                                recebido += lidos;
                                long agora = System.currentTimeMillis();
                                if (agora - ultimoAviso > 250) {
                                    ultimoAviso = agora;
                                    JSObject evento = new JSObject();
                                    evento.put("id", id);
                                    evento.put("recebido", recebido);
                                    evento.put("total", total);
                                    notifyListeners("progresso", evento);
                                }
                            }
                        }
                        ContentValues pronto = new ContentValues();
                        pronto.put(MediaStore.MediaColumns.IS_PENDING, 0);
                        resolver.update(destino, pronto, null, null);
                        JSObject resultado = new JSObject();
                        resultado.put("nome", nome);
                        resultado.put("pasta", relativo);
                        resultado.put("bytes", recebido);
                        call.resolve(resultado);
                    } catch (Exception erro) {
                        if (destino != null) {
                            try {
                                resolver.delete(destino, null, null);
                            } catch (Exception ignorado) {
                                // sem o que fazer: o arquivo incompleto fica marcado como pendente e o sistema o limpa
                            }
                        }
                        String motivo = erro.getMessage() == null ? erro.getClass().getSimpleName() : erro.getMessage();
                        call.reject("Falha ao baixar: " + motivo);
                    } finally {
                        if (conexao != null) {
                            conexao.disconnect();
                        }
                    }
                }
            }
        ).start();
    }

    /**
     * Atualização do app: baixa o APK do notebook (HTTPS, cabeçalho Authorization) para a pasta de cache e abre o instalador
     * do Android. O sistema sempre pede a confirmação do usuário ("Atualizar") e só aceita o APK se tiver a MESMA assinatura
     * do app instalado. Na primeira vez o Android pede para liberar "instalar apps desconhecidos" para o Baixador Leitor:
     * abrimos essa tela e rejeitamos com o código "permissao" (o app explica e o usuário toca de novo).
     */
    @PluginMethod
    public void instalarApk(final PluginCall call) {
        final String endereco = call.getString("url");
        final String id = call.getString("id", "apk");
        final JSObject cabecalhos = call.getObject("headers", new JSObject());
        if (endereco == null || !endereco.startsWith("https://")) {
            call.reject("Endereço inválido: só HTTPS.");
            return;
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && !getContext().getPackageManager().canRequestPackageInstalls()) {
            try {
                Intent tela = new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + getContext().getPackageName()));
                tela.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                getContext().startActivity(tela);
            } catch (Exception ignorado) {
                // sem a tela de permissão, o app só mostra a explicação
            }
            call.reject("permissao");
            return;
        }
        new Thread(
            new Runnable() {
                @Override
                public void run() {
                    HttpURLConnection conexao = null;
                    try {
                        File pasta = new File(getContext().getCacheDir(), "apk");
                        if (!pasta.isDirectory() && !pasta.mkdirs()) {
                            throw new java.io.IOException("Sem espaço para guardar o APK.");
                        }
                        File[] antigos = pasta.listFiles();
                        if (antigos != null) {
                            for (File antigo : antigos) {
                                antigo.delete();
                            }
                        }
                        File arquivo = new File(pasta, "atualizacao.apk");
                        conexao = (HttpURLConnection) new URL(endereco).openConnection();
                        conexao.setRequestMethod("GET");
                        conexao.setConnectTimeout(20000);
                        conexao.setReadTimeout(180000);
                        Iterator<String> chaves = cabecalhos.keys();
                        while (chaves.hasNext()) {
                            String chave = chaves.next();
                            conexao.setRequestProperty(chave, cabecalhos.getString(chave));
                        }
                        int status = conexao.getResponseCode();
                        if (status != 200) {
                            call.reject("O notebook respondeu " + status + ".");
                            return;
                        }
                        long total = conexao.getContentLengthLong();
                        long recebido = 0;
                        long ultimoAviso = 0;
                        byte[] buffer = new byte[64 * 1024];
                        try (InputStream entrada = conexao.getInputStream(); OutputStream saida = new FileOutputStream(arquivo)) {
                            int lidos;
                            while ((lidos = entrada.read(buffer)) != -1) {
                                saida.write(buffer, 0, lidos);
                                recebido += lidos;
                                long agora = System.currentTimeMillis();
                                if (agora - ultimoAviso > 250) {
                                    ultimoAviso = agora;
                                    JSObject evento = new JSObject();
                                    evento.put("id", id);
                                    evento.put("recebido", recebido);
                                    evento.put("total", total);
                                    notifyListeners("progresso", evento);
                                }
                            }
                        }
                        if (total > 0 && recebido != total) {
                            arquivo.delete();
                            throw new java.io.IOException("download incompleto");
                        }
                        Uri uri = FileProvider.getUriForFile(getContext(), getContext().getPackageName() + ".baixadorfp", arquivo);
                        Intent instalar = new Intent(Intent.ACTION_VIEW);
                        instalar.setDataAndType(uri, "application/vnd.android.package-archive");
                        instalar.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
                        getContext().startActivity(instalar);
                        JSObject resultado = new JSObject();
                        resultado.put("bytes", recebido);
                        call.resolve(resultado);
                    } catch (Exception erro) {
                        String motivo = erro.getMessage() == null ? erro.getClass().getSimpleName() : erro.getMessage();
                        call.reject("Falha ao baixar a atualização: " + motivo);
                    } finally {
                        if (conexao != null) {
                            conexao.disconnect();
                        }
                    }
                }
            }
        ).start();
    }
}
