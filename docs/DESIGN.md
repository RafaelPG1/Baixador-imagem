# Design

Derivado do que foi entregue em `web/compartilhado/base.css` e nas páginas do app (notebook) e da leitura (celular).

## Ideia

A biblioteca é um **mapa de linhas**, não uma pasta de arquivos. Cada obra é uma **linha** de metrô; cada capítulo, uma
**estação**. Referência: sinalização do metrô paulistano. Sem grade de cartões iguais, sem ícones decorativos.

## Cor

- Fundo azul-acinzentado frio, claro (`#eef2f6`) e escuro (`#10151c`), seguindo o sistema. Painéis e realces um passo acima.
- Acento de interface: azul (`--acento`). Estados: `--ok`, `--erro`, `--aviso` com fundo próprio.
- **Cor de linha por obra** (6): azul, verde, amarelo, lilás, vermelho, turquesa (`--l0`…`--l5`). Só em faixa lateral da
  obra, trilho e estações e no filete do painel do capítulo; nunca como decoração. Texto nunca usa cor de linha.
- Escolha da cor: estável por nome da obra (hash), igual no notebook e no celular.

## Tipo

`Segoe UI` / system-ui. Títulos de seção 700, rótulos 600, números tabulares nas estações e contagens. Base 15 px no
notebook; 16 px no leitor.

## Forma e espaço

- Seções separadas por filete de 3 px escuro no topo, não por cartões. Painel do capítulo: retangular, filete de 5 px na cor da linha.
- Raio 8 px em campos e botões. Alvos ≥ 40 px no notebook e ≥ 44 px no celular (itens de capítulo ≥ 56 px).
- Máximo 1200 px de largura; gutter 16 px; abas ocupam a largura toda no celular.

## Componente de assinatura: página da obra

Biblioteca e Leitura mostram cada obra como **cartão de capa** (imagem 3:4 e nome; sem capa, a inicial). A **página da
obra** é limpa, sem fundo colorido: botão "‹ Biblioteca", capa, nome, resumo e botões, e a listagem de capítulos em
linhas separadas por filete (mais novo primeiro): `Cap. N`, título em cor suave e "Traduzido" quando for o caso. Números
que faltam viram uma linha discreta. O capítulo atual (último lido no celular, ou selecionado no notebook) tem fundo de
realce e filete na cor de acento.

## Estados

Botões: normal, hover, pressionado (1 px), desabilitado, foco visível (2 px). Chips de estado: pronto, ativo (pulsa),
espera, ok, erro. Carregando: esqueletos. Vazio: mensagem + ação. Erro: faixa/texto vermelho, nunca só cor.

## Movimento

150 ms, só em transições de estado (hover, realce dos itens). `prefers-reduced-motion` desliga tudo.

Ações da obra (notebook): Ler, Traduzir pendentes, **Baixar/Atualizar capa**, **Excluir obra** (vermelho, sempre com
confirmação). No leitor: janela "Capítulos" (título + ✕, linhas `Cap. N`, decrescente, atual destacado, sem busca/volume/data)
e, embaixo, **‹ Obra** + **Próximo ›** ("Último capítulo" desativado quando não há próximo).

## Acessibilidade

Contraste AA nos dois temas; abas com `role=tablist` e setas do teclado; capítulos como botões com texto ("Capítulo 4", "Traduzido");
`aria-live` nas listas; sem informação só por cor (tracejado/anel/rótulo).
