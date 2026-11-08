# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Python (biblioteca padrão) servindo HTML/CSS/JS puros, sem etapa de build e sem framework. Playwright só para controlar o navegador. Decisão já existente no código; mantida.

## Users

Uma única pessoa (uso pessoal), brasileira, que baixa capítulos de histórias em imagens (webtoon/mangá) de sites que ela usa, organiza por obra e capítulo, traduz o texto das imagens (inglês → português) com Argos no próprio computador e lê depois. Dois cenários de uso:
- No notebook (Windows, PowerShell, navegador Brave): baixar, organizar a biblioteca, corrigir traduções. Tarefa de trabalho, com atenção, mouse e teclado.
- No celular, em casa, no mesmo Wi-Fi: só ler, deitado, de relance, com uma mão, às vezes à noite.

## Product Purpose

Baixar as imagens de um capítulo (manual escolhendo imagens, ou automático e em sequência), guardá-las numa biblioteca local organizada por obra, traduzir e ler. O notebook é o servidor: a biblioteca fica nele e o celular lê pela rede, sem cópia própria. Sucesso: o capítulo certo, na obra certa, com número e nome corretos, traduzido de forma legível, aberto no celular sem fricção.

## Positioning

Ferramenta pessoal e local: nada vai para a nuvem, tudo (OCR, tradução, biblioteca) acontece no computador do usuário. O celular só lê; só o notebook baixa, organiza e edita.

## Constraints

- Tudo gratuito e offline depois da instalação; dependências mínimas.
- O acesso do celular é apenas na rede local (mesmo Wi-Fi), por QR code com chave; a chave pode ser trocada. Acesso de fora de casa (VPN, ex.: Tailscale) é responsabilidade do usuário e fica fora do programa.
- Permissões por formato: Baixar imagens e Biblioteca (com edição) só no notebook; Leitura pelo celular somente leitura, sem nenhuma ação de escrita.
- A opção de busca C ("rápido e adaptativo") é o padrão; a B continua como alternativa cuidadosa.
- Idioma da interface: português do Brasil.
- Acessibilidade: contraste AA, foco visível, alvos de toque ≥44px no celular, respeitar prefers-reduced-motion.

## Open decisions

- Acesso fora de casa: não implementado (decisão do usuário: só em casa).
- Premissas assumidas sem pergunta: uso solo, sem contas de usuário, sem login além da chave do celular.
