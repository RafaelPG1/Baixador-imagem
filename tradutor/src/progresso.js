// Linhas de progresso para o Baixador (Python). Só saem quando TRADUTOR_EVENTOS=1; o formato é uma linha "@@{json}".
// O Python lê essas linhas para mostrar as barras; todo o resto do stdout vira mensagem do registro.
export function progresso(evento) {
  if (process.env.TRADUTOR_EVENTOS === '1') process.stdout.write(`@@${JSON.stringify(evento)}\n`);
}
