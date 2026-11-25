// Roda sem Android: javac -d /tmp/o plugins/baixador-salvar/android/src/main/java/com/baixador/salvar/Conferencia.java test/ConferenciaTeste.java && java -cp /tmp/o com.baixador.salvar.ConferenciaTeste
package com.baixador.salvar;
import java.util.*;
public class ConferenciaTeste {
  static String r(String p1,long v1,Set<String> a,String p2,long v2,Set<String> b){ try{ Conferencia.verificar(p1,v1,a,p2,v2,b); return "OK"; }catch(Conferencia.Recusa e){ return e.codigo+": "+e.getMessage(); } }
  public static void main(String[] x){
    Set<String> A=Set.of("aabbccddeeff00112233"), B=Set.of("112233445566778899aa");
    String p="com.baixador.leitor";
    check(r(p,18,A,p,19,A).equals("OK"));
    check(r(p,18,A,p,19,B).startsWith("ASSINATURA"));
    check(r(p,18,A,p,19,new HashSet<>(List.of("aabbccddeeff00112233","112233445566778899aa"))).equals("OK")); // rotação: A na linhagem de B
    check(r(p,18,A,p,18,A).startsWith("VERSAO: A versão 18 já"));
    check(r(p,18,A,p,17,A).startsWith("VERSAO: O APK baixado"));
    check(r(p,18,A,"outro",19,A).startsWith("PACOTE"));
    check(r(p,18,A,p,19,Set.of()).startsWith("ASSINATURA: Não consegui"));
    System.out.println(r(p,18,A,p,19,B)); System.out.println("tudo certo");
  }
  static void check(boolean b){ if(!b) throw new AssertionError(); }
}
