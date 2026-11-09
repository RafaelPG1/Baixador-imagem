# Baixador de Imagens

Aplicativo web que roda no seu notebook. Baixa os capítulos de histórias em imagens de sites, guarda numa
biblioteca organizada por **obra** e **capítulo**, traduz o texto das imagens (offline) e deixa você ler —
no notebook ou, pelo Wi-Fi de casa, no celular. **O notebook é o servidor**: a biblioteca fica nele e o
celular só lê, sem cópia própria.

Quatro áreas, na barra de cima:

| Área | Onde | O que faz |
|---|---|---|
| **Baixar imagens** | só notebook | abre o site, procura as imagens, baixa (manual ou automático) |
| **Biblioteca** | só notebook | vê as obras, lê, traduz, corrige a organização e abre o editor de tradução |
| **Traduções** | só notebook | escolhe o motor de tradução e acompanha a tradução em andamento: fila de capítulos, progresso (e do refinamento) e registro |
| **Leitura pelo celular** | notebook liga; celular lê | liga o acesso e mostra o QR code; o celular só lê |

## Requisitos

- Windows 10/11 com **Python 3.9 ou superior** (marque "Add python.exe to PATH" na instalação).
- Um navegador Chromium para baixar: **Brave**, **Microsoft Edge** ou **Google Chrome**.
- Dependência principal: `playwright` (não baixa navegador extra se você tiver um dos três).
- Opcional (tradução): `requirements-traducao.txt` (RapidOCR + Argos Translate; o Argos usa `torch`, então são
  centenas de MB).

## Instalação (PowerShell, dentro da pasta do projeto)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
# opcional, para traduzir:
python -m pip install -r requirements-traducao.txt
```

Se o PowerShell recusar o `Activate.ps1`:
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned` e ative de novo.
Só se não tiver Brave, Edge nem Chrome: `python -m playwright install chromium`.

## Abrir o app

```powershell
python -m baixador
```

Abre no navegador padrão (se não abrir, copie o endereço `http://127.0.0.1:...` do PowerShell). Esse endereço só
funciona no próprio notebook. `Ctrl+C` no PowerShell encerra. Opção `--sem-navegador` não abre a janela sozinha.

## Baixar imagens

1. Cole o **endereço do capítulo**. **Obra**, **número** e **nome** vêm da aba do site (e, se faltar, do
   endereço); corrija à mão se precisar. A linha "Será guardado em:" mostra a pasta final.
2. **Como baixar**:
   - **Manual (recomendado)**: abre o site numa janela; você deixa o capítulo aparecer, clica em **Procurar
     imagens na página**, marca o que quer e clica em **Baixar marcadas**.
   - **Automático**: abre, procura, baixa e fecha sozinho. Com **Continuar baixando os próximos capítulos
     automaticamente** ligado, clica em "próximo" e repete; se não achar ou não conseguir baixar o próximo, **para
     onde está**, deixa o navegador aberto e avisa, **sem afirmar que a obra acabou** (pode ser o último capítulo ou
     um erro). Pode ser desligado com o automático rodando: termina o capítulo atual e para.
   - **Traduzir automaticamente após concluir os downloads** (caixa independente): só vale com "Continuar baixando…"
     ligado. A tradução começa uma única vez, quando a sequência termina (não conseguiu avançar para o próximo), com
     os capítulos baixados nessa execução e os idiomas escolhidos na **Biblioteca**. Não traduz se você cancelar, fechar
     o navegador, desligar "Continuar" no meio, se um download falhar ou se já houver tradução em andamento. Desligada,
     nada muda.
   - **Atualizar obra: baixar os capítulos mais recentes**: só aparece com as duas caixas acima desligadas (ligada,
     bloqueia as duas, para não haver duas rotinas ao mesmo tempo). Parte do **último capítulo salvo** da obra escolhida
     no campo "Obra", pula os capítulos que já estão na biblioteca e baixa só os novos; não reaproveita número/nome do
     capítulo digitado. Se a obra ainda não está na biblioteca, começa pelo endereço informado.
3. **Busca** (padrão: **Rápida e adaptativa**, a antiga "opção C"): desce a página rápido e, se detecta carregamento,
   freia e espera. A alternativa **Cuidadosa** (a antiga "B") é mais lenta e mais conservadora. As duas conferem
   números pulados na sequência das imagens no final.
4. **Passar para o próximo capítulo** clica no botão de próximo do site e zera a lista; número e nome se
   atualizam sozinhos.
5. **Limpar tudo** zera a operação atual (endereço, obra, número, nome, lista de imagens, andamento, última pasta). **Não
   apaga nada da biblioteca.** Se houver imagens encontradas e não salvas, ou o navegador estiver aberto, pede
   confirmação (e fecha o navegador); um endereço novo começa do zero, sem misturar com o anterior.
6. "Navegador e destino" (recolhido): escolha do navegador, perfil (o **próprio** guarda extensões e logins; o
   **temporário** é limpo), pasta de destino (padrão `obras\`) e o fechamento automático de abas de anúncio.

## Biblioteca

**Layout (repaginado):** barra fixa no topo com busca, menu **Tradução** (idiomas, motor, Refinar) e menu **⋯** (abrir
pasta de saída, excluir tudo). O andamento da tradução aparece numa faixa compacta logo abaixo da barra (com *Registro* e
*Cancelar*; some quando termina ou ao fechar) e não empurra mais a obra. Na obra, a ficha fica à esquerda e os capítulos
numa linha do tempo à direita, com o estado de cada um (traduzido, na fila, traduzindo). Clicar num capítulo abre um
painel lateral, sem sair do lugar da lista (**Esc** fecha); em tela estreita ele sobe de baixo. Ações menos usadas da obra
ficam em **Mais ações**.

**Cancelar um capítulo da fila:** durante uma tradução em lote, cada capítulo "Na fila" ou "Traduzindo" ganha um botão
**Cancelar** (na Biblioteca e na aba Traduções). Ele tira só aquele capítulo; a fila continua. O **Cancelar tradução** da faixa
continua parando tudo. (No capítulo que estava sendo traduzido, a tradução parcial é descartada.)

**Leitura pelo celular** usa o mesmo visual: busca de obras, capas com progresso de tradução e a obra com a linha do tempo
dos capítulos (mostra "Parou aqui" no último capítulo lido).

A tela inicial mostra cada **obra só com a capa e o nome**. Tocar numa obra abre a **página da obra** (o botão do
livro, no leitor, também volta para ela): botão **‹ Biblioteca** no topo, a capa com o nome e os botões da obra, e embaixo
só a **listagem de capítulos** (`Cap. 136`, com o título quando houver e "Traduzido" nos já traduzidos), do mais novo ao mais
antigo. Números que faltam entre o primeiro e o último aparecem como "Faltam na biblioteca: 174".

- No notebook, clique num capítulo para abrir o painel dele (no celular, o toque abre a leitura):
  **Ler**, **Traduzir / Traduzir de novo**, **Reajustar caixas e cores** (refaz só o desenho, sem retraduzir),
  **Abrir pasta** e **organização** (obra, número, nome; **Salvar organização** move a pasta;
  **Renomear a obra inteira** move todos os capítulos, e se o nome já existir as duas se juntam).
- **Capa da obra**: é o arquivo `capa.jpg` (ou `.png`, `.webp`) dentro da pasta da obra, ao lado dos capítulos
  (`obras\Nome da obra\capa.jpg`). Você pode colocar à mão. Além disso, ao baixar, o programa tenta pegar sozinho a capa
  na página da obra do site: do endereço do capítulo ele corta até o nome da obra
  (`…/title/nome-da-obra/123-capitulo` → `…/title/nome-da-obra/`) e usa a imagem de `/covers/` dessa página. Nunca
  troca uma capa que já existe; se não achar, a obra aparece com a inicial do nome.
- **Atualizar** (página da obra, no notebook): parte do último capítulo salvo (o endereço do `capitulo.json`). Se a aba
  Baixar imagens estiver livre, vai para ela, liga **sozinho o modo automático** (qualquer que seja o modo escolhido, sem precisar clicar em
  "Procurar páginas") abre o último capítulo salvo, **não o baixa de novo**, aperta em "próximo" sozinho e baixa só os capítulos novos (os já salvos são pulados). Se a aba estiver baixando,
  com o navegador aberto ou com imagens aguardando você, avisa para esperar (ou use "Limpar tudo").
- **Navegador fechado na janela**: o programa reconhece, volta para "fechado", limpa os dados daquela aba e deixa abrir
  outro site na hora (sem precisar de F5 nem reiniciar o programa).
- **Obra que você já tem**: ao abrir um capítulo, o programa compara o endereço da obra (`obra.json`) e o nome
  (sem acentos, símbolos nem maiúsculas; "eieom One Piece" casa com "One Piece") com as obras da biblioteca. Se **uma**
  obra serve, ela é selecionada sozinha (com um aviso); se **mais de uma** serve, aparecem botões para você escolher
  (ou "É uma obra nova"). No modo automático a regra é a mesma, e em dúvida o nome do site é mantido.
- **Sem capítulo duplicado**: um capítulo já salvo (mesmo endereço, ou mesma obra + mesmo número; traduzido ou não)
  não é baixado de novo. No manual o botão avisa e o servidor recusa; no automático ele pula e segue para o próximo.
  Salvar o mesmo capítulo em várias levas na mesma lista continua permitido.
- **Gerenciar a biblioteca** (Biblioteca): *Renomear obra* (renomeia a pasta inteira; capa, `obra.json` e os
  `capitulo.json` acompanham; se o nome já existe, funde as duas obras e recusa sem mexer em nada se algum capítulo
  colidir), *Renomear capítulo* (painel do capítulo), *Excluir obra* e *Excluir todas as obras* (confirmação com
  aviso de que TODA a biblioteca será apagada e digitação de APAGAR TUDO).
- **Baixar capa / Atualizar capa** (página da obra, no notebook): busca a capa na página da obra do site, na maior
  resolução, usando o **navegador que você deixou aberto na aba Baixar** (com o seu login/verificação). Lê o
  `.poster img` da página já carregada, escolhe a maior imagem do `srcset` (ex.: 600w) e resolve links relativos pela
  URL da obra. Salva `capa.*` na pasta da obra. Depois de baixar um capítulo sem capa na obra, o programa tenta isso
  sozinho uma vez. Sem navegador aberto, tenta direto e, se não der, **abre sozinho** o navegador na página da obra (e o fecha se der certo; se falhar, deixa aberto para você resolver o login/verificação e clicar de novo). Só troca uma capa existente quando você pede "Atualizar capa" (e confirma). Se falhar
  (navegador fechado, página sem capa, site bloqueou), mostra o motivo e não mexe em nada da biblioteca.
- **Endereço da obra**: cada pasta de obra guarda um `obra.json` com a página principal da obra
  (`https://site/title/nome-da-obra/`). O endereço do capítulo fica só no `capitulo.json` de cada capítulo. Obras
  antigas ganham o `obra.json` na abertura do programa, a partir dos endereços dos capítulos já salvos.
- **Excluir obra** (página da obra, no notebook): pede confirmação e apaga do disco os capítulos, traduções, capa e
  `obra.json` **só dessa obra**. Recusa durante tradução ou salvamento. Não pode ser desfeito.
- **Estrutura sempre `obras\Obra\Capítulo\`**, mesmo com um capítulo só (sem obra: `Sem obra\…`; sem número nem
  nome: `…\Sem número`). Ao abrir o programa, pastas antigas (`nexustoons - capítulo 12` direto em `obras\`, ou
  imagens soltas dentro da pasta da obra) são **movidas** para `Obra\Capítulo`: nunca apaga nem sobrescreve; o que não
  puder ser movido fica onde está (e continua aparecendo) e o programa avisa no terminal.
- **Dentro de cada capítulo: imagens em `img\`, `.json` na raiz do capítulo.** Ex.: `obras\Obra\Cap 032\img\001.webp` e
  `obras\Obra\Cap 032\traducao.json` (também `capitulo.json`, `traducao.aviso.json` etc.). Assim dá para pegar só os `.json`
  sem as imagens. Ao abrir o programa, capítulos antigos com imagens soltas na pasta têm as imagens **movidas** para `img\`
  (só move; nunca apaga nem sobrescreve; se já existir um arquivo igual em `img\`, o solto fica onde está e o programa avisa).
  Os downloads novos já vão direto para `img\`. Para devolver imagens que você colocou à mão na pasta do capítulo, basta
  reabrir o programa. O `traducao.json` guarda só o nome de cada imagem (`001.webp`), então traduções antigas continuam valendo.
- Em cima: **Traduzir tudo que falta** (idiomas de/para) e **Abrir pasta da biblioteca**. A biblioteca atualiza
  sozinha em até ~3 s quando chega capítulo novo.
- **Ler** abre o **leitor global**: uma só página (`/leitor?c=Obra/Capítulo`) que carrega o capítulo escolhido; nada de
  `leitor.html` é gerado por capítulo. Só as imagens, uma embaixo da outra, sem cabeçalho. Controles:
  - **Barra de progresso** colada na esquerda, do topo ao fim da tela: parada é uma risca fina e discreta, **uma faixa por
    página** (as lidas mais claras, a atual em destaque). Tocar ou **arrastar** nela leva à página naquela altura: a barra fica
    **selecionada** (retângulo mais largo, com o número da página, que acompanha a rolagem) até você tocar em outro lugar.
  - **Dois cliques** (ou dois toques) na leitura, **com a página parada**, mostram/escondem os botões flutuantes (cliques durante ou logo depois de rolar, ou com a página deslocada entre os dois, são ignorados). Há também o botão **idioma** (Aa): alterna entre a tradução e a imagem original, mantendo o ponto de leitura (a escolha fica lembrada; desabilitado em capítulo sem tradução). Os demais: **casa** (volta à biblioteca),
    **livro** (página da obra), **lista** (janela "Capítulos" com ✕ para fechar: `Cap. N`, do mais novo ao mais antigo,
    o capítulo atual destacado; toque num para abrir). No canto **direito** fica **‹ 172/175 ›**: capítulo anterior/próximo e a posição real do capítulo na obra
    (número do capítulo / maior número da obra; sem números nos nomes, usa a posição na lista). Atualiza sozinho quando
    chegam capítulos novos. No fim do capítulo há **‹ Obra** (volta à página da obra) e **Próximo ›** (próximo capítulo disponível; no
    último, aparece "Último capítulo" desativado). Trocar de página não é isso: é só rolar ou usar a barra.
  - O editor de tradução (corrigir texto, caixas e cores) **não tem botão no leitor atual**; o código continua no projeto
    (`web/leitor/edicao.js`), inativo, esperando um botão para chamá-lo.

Estrutura no disco:

```
obras\
└── Solo Leveling\
    ├── Cap 001 - O despertar\   (imagens, capitulo.json, traducao.json)
    └── Cap 002\
```

## Leitura pelo celular

1. Na aba **Leitura pelo celular**, clique em **Ligar acesso do celular**. (Opcional: marque ligar automaticamente.)
2. Celular **no mesmo Wi-Fi**: aponte a câmera para o QR code. A chave fica salva no celular (cookie).
3. Escolha a obra (capa e nome) e, na página dela, o capítulo. **Continuar** volta ao último capítulo lido (guardado no próprio celular). Capítulos novos
   baixados no notebook aparecem sozinhos.

No Windows, na primeira vez o firewall pergunta se o Python pode receber conexões: permita em **Redes privadas**.
**Trocar chave** invalida o QR antigo e todos os celulares já autorizados.
Se o celular mostrar "Chave inválida ou ausente" depois de **Trocar chave**, escaneie o QR novo. Desconexões do celular
(tela apagada, Wi-Fi caindo) não geram mais erros no terminal.

O celular **só lê**: o servidor dele só aceita GET, não tem rota de baixar, traduzir, editar ou reorganizar, e o
leitor global chega sem o botão de edição. O acesso **fora de casa não está implementado** (se quiser, use uma VPN como
Tailscale por conta própria).

## Tradução (opcional, grátis, offline)

Lê o texto dentro das imagens (OCR) e traduz com Argos; mostra por cima da imagem, sem alterar o original.
Idiomas de origem: inglês, espanhol, francês, italiano, alemão, português. Japonês, coreano e chinês **não** são lidos.
**O destino é sempre o português** (fixo no programa; nada o deduz nem o troca). Se um trecho traduzido ainda trouxer
palavras do espanhol, ele passa por uma segunda tradução es→pt (baixa esse modelo na primeira vez que precisar);
se a segunda passada não melhorar, o trecho fica como está e é marcado para revisão no leitor.
Em lote ("Traduzir tudo que falta", "Traduzir N pendentes" ou a tradução automática), **cada capítulo fica liberado
para leitura assim que termina** (no notebook e no celular), enquanto os demais seguem em segundo plano; o botão
**Ler** da obra abre o capítulo que você selecionou nela; sem seleção, o último já traduzido.

**Traduzir de novo**: num capítulo já traduzido, o botão pede confirmação e refaz a tradução. A atual continua valendo
(e legível) até a nova terminar; só então é substituída por inteiro, sem sobras da antiga. Se a nova falhar, for cancelada,
tiver imagens com erro ou não achar texto, a antiga é mantida. As imagens baixadas nunca são alteradas. As correções que você
salvou no editor são reaproveitadas.
Na primeira vez de cada par de idiomas o modelo é baixado (centenas de MB) e depois funciona sem internet. É
tradução automática: erra gírias, nomes e efeitos sonoros; trate como rascunho e corrija no editor.
Acabamento do texto: a caixa cobre também pontuação/acentos soltos e o halo do original; o texto não é cortado
nem tem palavras partidas, as linhas são equilibradas (palavras curtas ficam coladas à seguinte e a última não fica
sozinha), a letra não passa muito do tamanho da original e, se a frase não cabe, usa o espaço livre do balão.
Memória: correções suas continuam valendo (também para o mesmo balão lido com pequeno erro de OCR) e, quando a troca
é de um termo/nome reconhecível, ele é reaplicado em outros balões (`memoria_termos.json`, só quando o termo de origem
aparece e a forma antiga está no resultado). Nomes do glossário saem sempre com a grafia do glossário.
Pelo terminal: `python -m baixador --traduzir "obras\Obra\Cap 001" --de en` (destino sempre `pt`).

## Outros comandos

- `python -m baixador --sem-navegador`: não abre a janela sozinha.
- `python -m baixador --traduzir PASTA --de en`: traduz uma pasta de imagens pelo terminal.
- `python -m baixador --apagar-perfil`: apaga o perfil próprio do navegador (extensões e logins).

## Segurança e privacidade

- Servidor do notebook: só `127.0.0.1`, token aleatório por execução, confere Host (DNS rebinding) e Origin (CSRF),
  JSON de até 16 KB, CSP restritiva. Páginas de sites são sempre exibidas como texto.
- Servidor do celular: só liga quando você manda; só GET; chave longa e aleatória (vira cookie e sai da URL); só aceita
  clientes de endereços de rede local; confere Host; bloqueia por 1 min após 8 chaves erradas; entrega só as páginas do programa
  (leitor e telas), os dados do capítulo pedido e imagens de dentro de `obras\` (nunca `traducao.json`, `capitulo.json`,
  nem caminhos fora da pasta).
- Nada é enviado à nuvem. A única conexão externa é o download dos modelos de tradução, uma vez por par de idiomas.
- A chave do celular fica em `dados\celular.json` (uma `celular.json` antiga na raiz do projeto é movida para lá sozinha) (não compartilhe esse arquivo).

## Limitações

- A biblioteca mostra a pasta `obras\`. Capítulos baixados para outra pasta não aparecem nela.
- Sites com proteção forte (login, captcha, DRM) podem exigir que você prepare a página manualmente.
- OCR e tradução automáticos erram; revise.
- A atualização do celular é por consulta a cada ~3 s (não é push): o celular precisa estar com a tela ligada.

## Estrutura do projeto

```
baixador-imagens\
├── baixador\                  # programa (Python)
│   ├── __main__.py, cli.py    # ponto de entrada e linha de comando
│   ├── configuracao.py        # caminhos: pasta do projeto, obras\, web\, dados\
│   ├── servidor\
│   │   ├── notebook.py        # servidor local do notebook (API, segurança, leitor global)
│   │   ├── celular.py         # servidor somente leitura do celular
│   │   └── base.py            # peças comuns aos dois (página do leitor, arquivos estáticos)
│   ├── biblioteca\
│   │   ├── acervo.py          # obras/capítulos, versão para sincronizar, reorganizar
│   │   ├── obra.py            # obra.json: nome e endereço principal da obra
│   │   ├── estrutura.py       # leva pastas antigas para Obra\Capítulo (só move)
│   │   ├── capa.py            # capa da obra (capa.jpg) e como achá-la na página da obra do site
│   │   ├── capitulo.py        # dados de um capítulo para o leitor (imagens e trechos traduzidos)
│   │   └── organizacao.py     # identifica obra/número/nome (aba do site e endereço)
│   ├── navegador\
│   │   ├── manual.py          # abrir, procurar (B/C), baixar, automático, próximo
│   │   ├── captura.py         # abre o navegador (Playwright) com perfil e bloqueios
│   │   └── navegadores.py     # acha Brave/Edge/Chrome e gerencia perfis
│   ├── traducao\
│   │   ├── pipeline.py        # OCR + tradução + gravação segura do traducao.json
│   │   ├── inteligencia.py    # contexto, glossário, memória e alertas
│   │   └── edicao.py          # edição de blocos traduzidos (API do editor)
│   └── nucleo\                # imagens.py, sequencia.py, seguranca.py, erros.py
├── web\                       # interface (HTML/CSS/JS), servida pelos servidores
│   ├── notebook\              # app.html, baixar.js, biblioteca.js, celular.js, comum.js
│   ├── celular\               # leitura.html, leitura.js (tela do celular)
│   ├── leitor\                # leitor.html, leitor.css, leitor.js (+ edicao.js/css, inativo)
│   └── compartilhado\         # base.css, diagrama.js, qrcode.js
├── docs\                      # PRODUCT.md, DESIGN.md
├── dados\                     # criada ao usar: celular.json (chave do celular)
├── obras\                     # criada ao usar: a biblioteca
├── requirements.txt, requirements-traducao.txt
└── LEIA-ME.md
```

`web\compartilhado\qrcode.js` é a biblioteca `qrcode-generator` (Kazuhiko Arase, licença MIT), incluída localmente.
Os testes automáticos não fazem parte da entrega.


## Pasta da biblioteca

A biblioteca fica em `obras\` (antes `saida\`). Se ao abrir só existir `saida\`, o programa a renomeia sozinho para `obras\`, sem copiar nem apagar nada. Se existirem as duas, ele usa só `obras\` e avisa no console.

## Motor de tradução (aba Traduções)

- **Híbrido (recomendado)**: o Argos traduz rápido e o capítulo já pode ser lido; em segundo plano o **Hy-MT2-7B** (via Ollama) refina balão a balão (português do Brasil mais natural). O leitor aberto troca os textos sozinho, sem mexer na posição de leitura.
- **Somente Argos**: como antes (rápido; sai mais português de Portugal).
- **Somente Hy-MT2 — Modo A (balão por balão)**: tudo pelo Hy-MT2, uma fala por chamada (lento: ~10 s por fala em CPU).
- **Somente Hy-MT2 — Modo B (página inteira com contexto)**: os balões da página vão numerados, em ordem de leitura, numa única chamada. Se a lista volta com quantidade/numeração diferente, todos os balões da página são refeitos um a um (Modo A); se só um item vem vazio ou inválido, só ele é refeito. Texto e balão nunca se desalinham.
- **Gemini**: mesma lógica do Modo B, na nuvem. Envia **só o texto** extraído, nunca a imagem. A chave fica no arquivo `.env` da raiz do projeto (`key_gemini = "sua-chave"`); ela não vai para código, log nem mensagem de erro, e **o `.env` não deve ser compartilhado nem enviado a um repositório**. O modelo é a constante `MODELO_GEMINI` em `baixador/traducao/gemini.py`; se a chave não enxerga esse modelo (erro 404), o programa consulta a lista de modelos da própria chave e passa sozinho para um Flash disponível. Cada página vai em JSON estruturado, com as falas anteriores como contexto. Chave vazia, recusada, limite de uso ou internet fora aparecem como aviso claro, sem travar o programa.

- **OpenRouter**: mesma lógica do Gemini (página inteira em JSON estruturado, só texto, nunca a imagem), com a API compatível com OpenAI. No `.env` acrescente `key_openrouter = "sua-chave"` e, se quiser trocar o modelo, `modelo_openrouter = "fornecedor/modelo"` (ids em openrouter.ai/models; o padrão é `nvidia/nemotron-3.5-super-vl:free`, constante `MODELO_OPENROUTER` em `baixador/traducao/openrouter.py`). **Só modelos `:free` são aceitos** (o programa recusa qualquer outro, para nunca gastar créditos) e cada pedido leva um teto de tokens de saída. Atenção: modelos `:free` têm limite de 20 pedidos/min e **50/dia** (1000/dia com pelo menos US$ 10 de créditos comprados) e o programa faz **1 pedido por página**, então um capítulo longo não cabe no limite diário gratuito sem créditos. Erro 401 = chave recusada; 402 = sem saldo; 404/400 = modelo inexistente; 429 = limite (a página é adiada e tentada de novo).
- O tempo de cada página/motor aparece no console (`[tempo] …`) para comparar os modos.
- **Refinar capítulos já traduzidos** (botão na aba Traduções): passa o Hy-MT2 pelos capítulos que já têm tradução do Argos e ainda não foram refinados; mostra quantos são. Pode ser cancelado a qualquer momento.
- A escolha vale para as próximas traduções; uma já em andamento termina com o motor com que começou. Fica salva em `dados/traducao.json`.
- O Hy-MT2 nunca é baixado pelo programa. Uma vez, no terminal: `ollama pull hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M` (o botão **Verificar Ollama e Hy-MT2** mostra o que falta). Sem Ollama/modelo, o Híbrido avisa e entrega só o Argos; o "Somente Hy-MT2" mostra o erro e não traduz.
- O refinamento só troca um texto por outro válido (não vazio, não copiado do original, em português). Se você editou o balão enquanto o Hy trabalhava, ou ele veio da memória de correções, o seu texto vence. Cancelar interrompe na hora (inclusive no meio de uma fala) e mantém a tradução do Argos. O texto original, a posição e o tamanho dos balões nunca mudam.
- Antes do tradutor, o texto lido pelo OCR é corrigido (palavras coladas, hifenização) e frases que continuam entre balões são traduzidas juntas e repartidas de volta, sem inventar palavras.

## Traduzir de novo e excluir traduções

- **Traduzir de novo** guarda a tradução antiga como backup até a nova terminar. Se a nova falhar ou for cancelada, a antiga é **restaurada** automaticamente. Glossário e memória de correções são mantidos.
- **Retomada por página:** o progresso de cada página é salvo em `traducao.parcial.json`. Se a tradução for cancelada, falhar ou o programa fechar, traduzir o mesmo capítulo de novo (mesmo motor e idiomas) continua da página em que parou, sem refazer as prontas.
- **Efeitos sonoros não são traduzidos** (VROOM, TAP, FLASH, AHH...). O programa trata como efeito um texto de **até 2 palavras e 16 letras, maior que as letras das falas e escrito direto sobre a arte** (sem balão nem caixa lisa atrás). Fala em balão, legenda lisa e frases de 3+ palavras são sempre traduzidas; na dúvida, traduz. Se algum efeito escapar (ou uma fala for pulada), selecione a área no modo edição: a área escolhida pelo usuário é sempre traduzida.
- **Caixas que não se sobrepõem:** quando dois balões estão colados, a letra de um não é mais puxada para a caixa do outro, e, se duas caixas ainda se cruzarem, o corte passa no meio do vão entre os textos originais. Releituras repetidas da mesma linha (lixo do OCR, ex. "I7....") são descartadas.
- **Capítulo incompleto:** se alguma página ficar sem tradução (Gemini instável, por exemplo), o capítulo aparece como *Incompleto · N páginas sem tradução* na Biblioteca (e no celular), e o painel ganha o botão **Completar N páginas sem tradução**, que traduz só essas páginas.
- **Excluir tradução** (Biblioteca, no capítulo ou na obra): apaga o `traducao.json` e os arquivos auxiliares (`traducao.parcial.json`, `traducao.anterior.json`, `traducao.aviso.json`); as imagens originais e as correções salvas ficam.
- A Biblioteca também tem o seletor de motor e o botão **Refinar**, iguais aos da aba Traduções (a configuração é a mesma).
- **Glossário único por obra:** os nomes detectados automaticamente vão para `obras/<Obra>/glossario.json`, um só para todos os capítulos (só acrescenta; `manter` e `termos` escritos à mão são preservados). Os `glossario.json` antigos dentro de cada capítulo são incorporados ao da obra na próxima tradução, e o arquivo do capítulo é removido se estiver só com nomes automáticos.
- **Reajustar caixas e cores** agora também aplica a correção de sobreposição entre balões, sem ler nem traduzir de novo. O que depende do OCR (efeitos sonoros e linhas duplicadas) só muda com uma nova tradução.
- **Retraduzir / Reajustar capítulos escolhidos:** na página da obra, **Mais ações → Retraduzir capítulos…** ou **Reajustar capítulos…** abre uma seleção na lista de capítulos (só os traduzidos podem ser marcados; há **Selecionar todos** e **Cancelar**). Retraduzir mantém a tradução antiga até a nova terminar (e a restaura se falhar); Reajustar refaz só caixas e cores, sem OCR nem tradução.
- **Migração dos glossários antigos:** ao iniciar, o programa leva o `glossario.json` de cada capítulo para o glossário único da obra (`obras/<Obra>/glossario.json`), juntando nomes automáticos, `manter` e `termos` (em conflito de termo, vale o que já estava na obra) e só apagando o arquivo do capítulo depois de confirmar que o da obra foi gravado.

## App Android (acesso de qualquer lugar pelo Tailscale)

O app é um APK próprio (Capacitor), instalado como qualquer aplicativo, sem depender do Chrome. Ele fala com o notebook por um **HTTPS privado do Tailscale** (sem abrir portas no roteador e sem expor o notebook à internet), mostra as obras do notebook, baixa capítulos para ler **offline** e salva **ZIPs** em `Download/Baixador/<Obra>/`.

**1. Tailscale (uma vez)**
1. Instale o Tailscale no notebook e no celular e entre com a **mesma conta** nos dois (ative verificação em duas etapas na conta Google/Microsoft que você usar).
2. No painel https://login.tailscale.com/admin/dns ative **MagicDNS** e **HTTPS Certificates**.
3. No notebook, abra o programa → **Leitura pelo celular** → **Ligar acesso do celular**. Depois rode no PowerShell (uma vez; mostra o comando exato na tela):
   ```powershell
   tailscale serve --bg 8765
   ```
   (`tailscale serve status` confere; `tailscale serve reset` desfaz.) O servidor do programa fica só neste notebook e o Tailscale entrega o HTTPS.
4. Ainda na aba **Leitura pelo celular**, em *App Android*, clique **Detectar** (ou digite o nome `….ts.net`) e **Salvar**. Aparece o QR de pareamento.
5. Teste: no navegador do celular (Tailscale ligado), abra `https://SEU-NOME.ts.net/`: se aparecer "Chave inválida ou ausente", o caminho está funcionando.

**2. Gerar o APK (na nuvem do GitHub, sem Android Studio)**
1. Suba o projeto (veja "Publicar no GitHub" abaixo). Em **Actions → Compilar APK** o fluxo roda sozinho (ou **Run workflow**). Leva alguns minutos.
2. *Recomendado:* gere a chave de assinatura uma vez para poder **atualizar o app por cima** sem perder as obras baixadas: na pasta `android-app`, rode `pip install cryptography` e `python scripts/gerar_chave_apk.py`. Copie o conteúdo de `chave-apk.base64.txt` para **Settings → Secrets and variables → Actions → New repository secret** com o nome `KEYSTORE_BASE64`; guarde o arquivo num backup e apague-o da pasta. Sem esse segredo o APK sai com chave temporária e, a cada versão nova, é preciso desinstalar o app antes (as baixadas se perdem).
3. Quando o fluxo ficar verde, abra a página **Releases** do repositório no celular, baixe `BaixadorLeitor.apk` e instale (o Android pede para permitir "instalar apps desta fonte").

**3. Usar**
- **Conectar:** toque em **Escanear QR do notebook** (ou cole o código). A chave fica guardada só neste aparelho.
- **Notebook (online):** lista as obras do notebook com capa. Dentro da obra, marque capítulos (**Todos**, **Não baixados**, **Limpar**) e escolha **Baixar para ler offline** (guarda no app) ou **Salvar ZIP no celular** (um ZIP por capítulo em `Download/Baixador/<Obra>/`, que o app também importa depois em **Ajustes → Importar ZIP**).
- **Baixadas:** lê sem internet e sem o notebook; excluir capítulo/obra libera espaço. O leitor tem tradução sobreposta, alternar original/tradução e capítulo anterior/próximo (dois cliques mostram a barra) e volta de onde você parou.
- **Fora de casa:** deixe o **Tailscale ligado no celular** e o notebook **ligado, conectado e sem suspender** (Configurações de energia do Windows). O Android reserva o espaço de VPN para o Tailscale (não dá para usar outra VPN ao mesmo tempo).

**Segurança:** só aparelhos da sua conta Tailscale chegam ao servidor, e ainda é preciso a chave do QR (que **Trocar chave** invalida). O servidor só lê a biblioteca; não escreve, apaga ou traduz nada. Chaves de IA (Gemini/OpenRouter) ficam só no `.env` do notebook e nunca vão ao celular.

**Limites conhecidos:** em redes de operadora com CGNAT o Tailscale usa um relé e o download pode ser mais lento; o app não se atualiza sozinho (instale o APK novo por cima); o leitor do app é simplificado (sem barra de progresso lateral nem edição); testei o servidor e o app em navegador com HTTPS local, mas o APK em si só pode ser validado no seu celular.

## Publicar no GitHub (PowerShell, na pasta do projeto)

O `.gitignore` bloqueia `.env`, `obras/`, `dados/`, `*.zip`, chaves e builds. As obras nunca sobem.
```powershell
git init
git add .
git status      # CONFIRA: .env e obras/ NÃO podem aparecer na lista
git commit -m "Baixador de imagens + app Android"
git branch -M main
git remote add origin https://github.com/SEU-USUARIO/baixador-imagens.git
git push -u origin main
```
- O repositório pode ser **privado**: o fluxo funciona igual e você baixa o APK na página Releases já logado no GitHub (no celular, entre no GitHub pelo navegador antes). Em repositório público qualquer pessoa com o link baixaria o APK (ele não contém chaves, só o app).
- Se você **já commitou** o `.env` ou `obras/` alguma vez, o `.gitignore` não os remove do histórico: rode `git rm -r --cached .env obras dados` e, se já deu push, **gere novas chaves** (Gemini/OpenRouter).
- O projeto não usa GitHub Pages nem PWA em nenhuma parte. O GitHub serve apenas para guardar o código e, pelo Actions, compilar o APK (publicado em Releases).
