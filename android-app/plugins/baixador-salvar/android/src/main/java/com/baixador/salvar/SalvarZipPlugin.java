package com.baixador.salvar;

import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.content.pm.SigningInfo;
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
import java.util.HashMap;
import java.util.Iterator;
import java.util.Map;
import android.content.Context;
import android.content.SharedPreferences;
import android.util.Base64;

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
        final String chave = id.isEmpty() ? nome : id;
        if (!ServicoDownload.CONTROLE.iniciar(chave)) {
            call.reject("Este capítulo já está sendo baixado.");          // sem download duplicado
            return;
        }
        ServicoDownload.iniciar(getContext(), "Baixando " + nome);          // serviço em primeiro plano: o download sobrevive ao app em 2º plano
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
                                if (ServicoDownload.CONTROLE.cancelado(chave)) {
                                    throw new java.io.IOException("cancelado");
                                }
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
                                    ServicoDownload.atualizar(getContext(), "Baixando " + nome, recebido, total);
                                }
                            }
                        }
                        if (total > 0 && recebido != total) {
                            throw new java.io.IOException("Download incompleto (" + recebido + " de " + total + " bytes).");   // nunca aparece como concluído
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
                        call.reject("cancelado".equals(motivo) ? "cancelado" : "Falha ao baixar: " + motivo);
                    } finally {
                        if (conexao != null) {
                            conexao.disconnect();
                        }
                        if (ServicoDownload.CONTROLE.terminar(chave) == 0) {
                            ServicoDownload.parar(getContext());
                        }
                    }
                }
            }
        ).start();
    }

    /** Cancela o download em andamento desse id (o arquivo parcial é apagado pelo próprio download). */
    @PluginMethod
    public void cancelar(final PluginCall call) {
        ServicoDownload.CONTROLE.cancelar(call.getString("id", ""));
        call.resolve();
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
                        try {
                            conferirAtualizacao(arquivo);
                        } catch (Conferencia.Recusa recusa) {
                            arquivo.delete();
                            call.reject(recusa.getMessage(), recusa.codigo);
                            return;
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

    // ------------------------------------------------------------------ conferência do APK antes de instalar

    private static String sha256(byte[] dados) throws java.security.NoSuchAlgorithmException {
        StringBuilder hex = new StringBuilder();
        for (byte b : java.security.MessageDigest.getInstance("SHA-256").digest(dados)) hex.append(String.format("%02x", b));
        return hex.toString();
    }

    /** Impressões digitais das assinaturas; historico=true inclui as anteriores da linhagem de rotação (como o Android faz ao atualizar). */
    private static java.util.Set<String> assinaturas(SigningInfo info, boolean historico) throws java.security.NoSuchAlgorithmException {
        java.util.Set<String> saida = new java.util.LinkedHashSet<>();
        if (info == null) return saida;
        Signature[] lista = historico && !info.hasMultipleSigners() ? info.getSigningCertificateHistory() : info.getApkContentsSigners();
        if (lista != null) for (Signature a : lista) saida.add(sha256(a.toByteArray()));
        return saida;
    }

    /** Lê o APK baixado como o Android lê (pacote, versionCode, assinatura) e compara com o app instalado. */
    private void conferirAtualizacao(File apk) throws Conferencia.Recusa {
        try {
            PackageManager pm = getContext().getPackageManager();
            PackageInfo novo = pm.getPackageArchiveInfo(apk.getAbsolutePath(), PackageManager.GET_SIGNING_CERTIFICATES);
            if (novo == null) {
                throw new Conferencia.Recusa("APK_INVALIDO", "O arquivo baixado não é um APK válido (corrompido ou incompleto). Tente baixar de novo.");
            }
            PackageInfo atual = pm.getPackageInfo(getContext().getPackageName(), PackageManager.GET_SIGNING_CERTIFICATES);
            Conferencia.verificar(atual.packageName, atual.getLongVersionCode(), assinaturas(atual.signingInfo, false),
                novo.packageName, novo.getLongVersionCode(), assinaturas(novo.signingInfo, true));
        } catch (Conferencia.Recusa recusa) {
            throw recusa;
        } catch (Exception erro) {
            throw new Conferencia.Recusa("CONFERENCIA", "Não consegui conferir o APK baixado: " + erro.getClass().getSimpleName() + ".");
        }
    }

    /** Pacote, versão e impressão digital da assinatura do app instalado (aparece em Ajustes, para comparar com a chave do GitHub). */
    @PluginMethod
    public void infoApp(PluginCall call) {
        try {
            PackageInfo p = getContext().getPackageManager().getPackageInfo(getContext().getPackageName(), PackageManager.GET_SIGNING_CERTIFICATES);
            java.util.Set<String> a = assinaturas(p.signingInfo, false);
            JSObject r = new JSObject();
            r.put("pacote", p.packageName);
            r.put("versionCode", p.getLongVersionCode());
            r.put("versionName", p.versionName);
            r.put("assinatura", a.isEmpty() ? "" : Conferencia.curta(a.iterator().next()));
            call.resolve(r);
        } catch (Exception erro) {
            call.reject("Não consegui ler os dados do app.");
        }
    }

    // ------------------------------------------------------------------ rede nativa (fora do WebView)

    private Map<String, String> cabecalhosDe(PluginCall call) {
        Map<String, String> mapa = new HashMap<>();
        JSObject h = call.getObject("headers", new JSObject());
        Iterator<String> chaves = h.keys();
        while (chaves.hasNext()) {
            String chave = chaves.next();
            mapa.put(chave, h.getString(chave));
        }
        return mapa;
    }

    private static void rejeitar(PluginCall call, Rede.Falha f) {
        call.reject(f.getMessage(), f.codigo);
    }

    /** GET com o corpo na memória (JSON; imagem pequena em base64 com binario=true). Qualquer status HTTP volta em "status". */
    @PluginMethod
    public void requisitar(final PluginCall call) {
        final String endereco = call.getString("url");
        final boolean binario = Boolean.TRUE.equals(call.getBoolean("binario", false));
        final int limite = call.getInt("limite", 20000);
        final Map<String, String> cabecalhos = cabecalhosDe(call);
        if (endereco == null || !endereco.startsWith("https://")) {
            call.reject("Endereço inválido: só HTTPS.", "ENDERECO");
            return;
        }
        new Thread(
            new Runnable() {
                @Override
                public void run() {
                    try {
                        Rede.Resposta r = Rede.obter(endereco, cabecalhos, limite, 32L * 1024 * 1024);
                        JSObject saida = new JSObject();
                        saida.put("status", r.status);
                        saida.put("tipo", r.tipo);
                        saida.put("corpo", binario ? Base64.encodeToString(r.corpo, Base64.NO_WRAP) : new String(r.corpo, java.nio.charset.StandardCharsets.UTF_8));
                        call.resolve(saida);
                    } catch (Rede.Falha f) {
                        rejeitar(call, f);
                    }
                }
            }
        ).start();
    }

    /** GET para um arquivo na pasta de cache do app (o app lê depois pelo endereço do Capacitor e chama apagarCache). */
    @PluginMethod
    public void baixarParaCache(final PluginCall call) {
        final String endereco = call.getString("url");
        final String id = call.getString("id", "");
        final Map<String, String> cabecalhos = cabecalhosDe(call);
        if (endereco == null || !endereco.startsWith("https://")) {
            call.reject("Endereço inválido: só HTTPS.", "ENDERECO");
            return;
        }
        new Thread(
            new Runnable() {
                @Override
                public void run() {
                    File pasta = new File(getContext().getCacheDir(), "dl");
                    if (!pasta.isDirectory() && !pasta.mkdirs()) {
                        call.reject("Sem espaço para guardar o download.", "ESPACO");
                        return;
                    }
                    File[] antigos = pasta.listFiles();
                    if (antigos != null) {
                        for (File antigo : antigos) {
                            if (System.currentTimeMillis() - antigo.lastModified() > 3600_000L) antigo.delete();
                        }
                    }
                    File arquivo = new File(pasta, "d" + System.nanoTime() + ".bin");
                    try {
                        long bytes = Rede.baixar(endereco, cabecalhos, arquivo, 120000, new Rede.Progresso() {
                            @Override
                            public void aoReceber(long recebido, long total) {
                                JSObject evento = new JSObject();
                                evento.put("id", id);
                                evento.put("recebido", recebido);
                                evento.put("total", total);
                                notifyListeners("progresso", evento);
                            }
                        });
                        JSObject saida = new JSObject();
                        saida.put("caminho", arquivo.getAbsolutePath());
                        saida.put("bytes", bytes);
                        call.resolve(saida);
                    } catch (Rede.Falha f) {
                        rejeitar(call, f);
                    }
                }
            }
        ).start();
    }

    @PluginMethod
    public void apagarCache(PluginCall call) {
        String caminho = call.getString("caminho", "");
        try {
            File pasta = new File(getContext().getCacheDir(), "dl").getCanonicalFile();
            File alvo = new File(caminho).getCanonicalFile();
            if (alvo.getParentFile() != null && alvo.getParentFile().equals(pasta)) alvo.delete();   // só apaga dentro de cache/dl
        } catch (java.io.IOException ignorado) {
            // arquivo temporário: o próximo download limpa o que sobrou
        }
        call.resolve();
    }

    // ------------------------------------------------------------------ configuração guardada fora do WebView
    // O localStorage do WebView pode ser limpo pelo sistema (pouco espaço, "limpar dados"); isto fica em SharedPreferences privado do app
    // (allowBackup=false: não vai para a nuvem).

    private SharedPreferences prefs() {
        return getContext().getSharedPreferences("baixador-conexao", Context.MODE_PRIVATE);
    }

    @PluginMethod
    public void guardarConfig(PluginCall call) {
        String valor = call.getString("valor");
        if (valor == null) {
            call.reject("Sem valor.", "ARGUMENTO");
            return;
        }
        boolean ok = prefs().edit().putString("conexao", valor).commit();
        if (!ok) {
            call.reject("Não consegui gravar a conexão.", "GRAVAR");
            return;
        }
        call.resolve();
    }

    @PluginMethod
    public void lerConfig(PluginCall call) {
        JSObject saida = new JSObject();
        saida.put("valor", prefs().getString("conexao", ""));
        call.resolve(saida);
    }

    @PluginMethod
    public void apagarConfig(PluginCall call) {
        prefs().edit().remove("conexao").commit();
        call.resolve();
    }
}
