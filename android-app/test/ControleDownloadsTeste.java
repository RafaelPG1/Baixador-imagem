// javac -d /tmp/o plugins/baixador-salvar/android/src/main/java/com/baixador/salvar/ControleDownloads.java test/ControleDownloadsTeste.java && java -cp /tmp/o com.baixador.salvar.ControleDownloadsTeste
package com.baixador.salvar;
public class ControleDownloadsTeste {
  public static void main(String[] x){
    ControleDownloads c = new ControleDownloads();
    check(c.iniciar("a"));
    check(!c.iniciar("a"));                 // duplicado recusado
    check(c.iniciar("b"));
    c.cancelar("a"); check(c.cancelado("a")); check(!c.cancelado("b"));
    c.cancelar("zzz"); check(!c.cancelado("zzz"));      // id desconhecido não vira cancelado
    check(c.terminar("a") == 1);
    check(c.iniciar("a")); check(!c.cancelado("a"));    // novo download do mesmo id não herda o cancelamento
    c.cancelarTodos(); check(c.cancelado("a") && c.cancelado("b"));
    check(c.terminar("a") == 1); check(c.terminar("b") == 0);   // 0 = serviço pode parar
    System.out.println("tudo certo");
  }
  static void check(boolean b){ if(!b) throw new AssertionError(); }
}
