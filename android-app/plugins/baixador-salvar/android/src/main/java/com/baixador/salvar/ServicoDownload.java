package com.baixador.salvar;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;
import androidx.core.app.NotificationCompat;

/**
 * Serviço em primeiro plano que mantém o download vivo com o app em segundo plano e mostra a notificação com progresso
 * e o botão Cancelar. Só existe enquanto houver download: quando o último termina, ele para e a notificação some.
 */
public class ServicoDownload extends Service {
    static final String CANAL = "baixador_downloads";
    static final int NOTIFICACAO = 4711;
    static final String ACAO_CANCELAR = "com.baixador.salvar.CANCELAR";
    static final ControleDownloads CONTROLE = new ControleDownloads();

    static void iniciar(Context ctx, String texto) {
        Intent i = new Intent(ctx, ServicoDownload.class).putExtra("texto", texto);
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                ctx.startForegroundService(i);
            } else {
                ctx.startService(i);
            }
        } catch (RuntimeException e) {
            // sem permissão de serviço em primeiro plano agora (app em 2º plano restrito): o download segue só enquanto o app viver
        }
    }

    static void atualizar(Context ctx, String texto, long recebido, long total) {
        NotificationManager nm = (NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm != null) {
            try {
                nm.notify(NOTIFICACAO, montar(ctx, texto, recebido, total));
            } catch (RuntimeException e) {
                // notificação bloqueada pelo usuário: o download continua
            }
        }
    }

    static void parar(Context ctx) {
        ctx.stopService(new Intent(ctx, ServicoDownload.class));
    }

    private static Notification montar(Context ctx, String texto, long recebido, long total) {
        Intent cancelar = new Intent(ctx, ServicoDownload.class).setAction(ACAO_CANCELAR);
        int flags = PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M ? PendingIntent.FLAG_IMMUTABLE : 0);
        PendingIntent pi = PendingIntent.getService(ctx, 0, cancelar, flags);
        NotificationCompat.Builder b = new NotificationCompat.Builder(ctx, CANAL)
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle("Baixador Leitor")
            .setContentText(texto)
            .setOnlyAlertOnce(true)
            .setOngoing(true)
            .addAction(0, "Cancelar", pi);
        if (total > 0) {
            b.setProgress(100, (int) Math.min(100, recebido * 100 / total), false);
        } else {
            b.setProgress(0, 0, true);
        }
        return b.build();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACAO_CANCELAR.equals(intent.getAction())) {
            CONTROLE.cancelarTodos();
            return START_NOT_STICKY;
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
            if (nm != null) {
                nm.createNotificationChannel(new NotificationChannel(CANAL, "Downloads de capítulos", NotificationManager.IMPORTANCE_LOW));
            }
        }
        String texto = intent == null ? "Baixando capítulos…" : intent.getStringExtra("texto");
        Notification n = montar(this, texto == null ? "Baixando…" : texto, 0, 0);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIFICACAO, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
        } else {
            startForeground(NOTIFICACAO, n);
        }
        return START_NOT_STICKY;                // se o sistema matar o app, nada fica "baixando": o arquivo incompleto é descartado
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
