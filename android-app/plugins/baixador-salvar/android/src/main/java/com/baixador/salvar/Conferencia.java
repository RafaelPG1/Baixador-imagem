package com.baixador.salvar;

import java.util.Set;

/**
 * Confere, ANTES de abrir o instalador, as três coisas que o Android exige para aceitar um APK como atualização:
 * mesmo pacote, versionCode maior e assinatura igual (ou da mesma linhagem de rotação). Lógica pura, sem classes do Android,
 * para ser testada com javac. As impressões digitais são SHA-256 do certificado, em hexadecimal.
 */
final class Conferencia {
    /** Motivo da recusa: código curto para o app e texto para o usuário. */
    static final class Recusa extends Exception {
        final String codigo;

        Recusa(String codigo, String mensagem) {
            super(mensagem);
            this.codigo = codigo;
        }
    }

    private Conferencia() {}

    /** Formata "aabbcc…" como "AA:BB:CC:DD:EE:FF:00:11" (8 primeiros bytes: dá para comparar a olho). */
    static String curta(String hex) {
        StringBuilder s = new StringBuilder();
        for (int i = 0; i + 1 < hex.length() && i < 16; i += 2) {
            if (s.length() > 0) s.append(':');
            s.append(hex, i, i + 2);
        }
        return s.toString().toUpperCase(java.util.Locale.ROOT);
    }

    private static String lista(Set<String> hexes) {
        StringBuilder s = new StringBuilder();
        for (String h : hexes) {
            if (s.length() > 0) s.append(" + ");
            s.append(curta(h));
        }
        return s.toString();
    }

    /**
     * @param instaladas assinaturas atuais do app instalado
     * @param historicoNovo assinaturas do APK novo, incluindo as anteriores da linhagem de rotação (se houver)
     * @throws Recusa se o Android rejeitaria a atualização
     */
    static void verificar(String pacoteInstalado, long versaoInstalada, Set<String> instaladas,
                          String pacoteNovo, long versaoNova, Set<String> historicoNovo) throws Recusa {
        if (!pacoteInstalado.equals(pacoteNovo)) {
            throw new Recusa("PACOTE", "O APK baixado é do pacote " + pacoteNovo + ", mas o app instalado é " + pacoteInstalado + ".");
        }
        if (versaoNova <= versaoInstalada) {
            throw new Recusa("VERSAO", versaoNova == versaoInstalada
                ? "A versão " + versaoNova + " já está instalada."
                : "O APK baixado (versão " + versaoNova + ") é mais antigo que o instalado (versão " + versaoInstalada + ").");
        }
        if (instaladas.isEmpty() || historicoNovo.isEmpty()) {
            throw new Recusa("ASSINATURA", "Não consegui ler a assinatura do APK baixado ou do app instalado.");
        }
        if (!historicoNovo.containsAll(instaladas)) {
            throw new Recusa("ASSINATURA", "O APK novo foi assinado com outra chave que o app instalado, então o Android não aceita como atualização. "
                + "Chave do app instalado: " + lista(instaladas) + ". Chave do APK novo: " + lista(historicoNovo) + ".");
        }
    }
}
