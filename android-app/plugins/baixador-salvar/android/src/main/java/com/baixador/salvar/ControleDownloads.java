package com.baixador.salvar;

import java.util.HashSet;
import java.util.Set;

/**
 * Estado dos downloads em andamento (sem Android, testável): impede o mesmo capítulo de baixar duas vezes ao mesmo tempo,
 * guarda os pedidos de cancelamento e diz quando o serviço em primeiro plano pode parar.
 */
final class ControleDownloads {
    private final Set<String> ativos = new HashSet<>();
    private final Set<String> cancelados = new HashSet<>();

    /** false = já existe download desse id em andamento (o chamador deve recusar, não duplicar). */
    synchronized boolean iniciar(String id) {
        if (!ativos.add(id)) {
            return false;
        }
        cancelados.remove(id);
        return true;
    }

    synchronized void cancelar(String id) {
        if (ativos.contains(id)) {
            cancelados.add(id);
        }
    }

    synchronized void cancelarTodos() {
        cancelados.addAll(ativos);
    }

    synchronized boolean cancelado(String id) {
        return cancelados.contains(id);
    }

    /** Termina o id e devolve quantos ainda restam (0 = pode parar o serviço). */
    synchronized int terminar(String id) {
        ativos.remove(id);
        cancelados.remove(id);
        return ativos.size();
    }

    synchronized int quantos() {
        return ativos.size();
    }
}
