# Tradutor (sistema do projeto Tradução, usado pelo Baixador)

Núcleo de tradução do Baixador de Imagens, em Node.js 22.9+. Traduz **inglês para português (pt-BR)** páginas de mangá/manhwa:
acha os balões, lê o texto de cada um, traduz, apaga o texto original e entrega os dados para o leitor escrever a tradução por cima.
O Python do Baixador só chama este código (`src/processar-capitulo.js`), um capítulo por vez.

## Instalar (uma vez)

```powershell
cd tradutor
npm install
```

`npm install` fica isolado aqui (`tradutor\node_modules`); o `postinstall` remove os binários do onnxruntime de outros sistemas.
Para o motor local: `ollama pull translategemma:4b`.

## Uso sem o Baixador

```powershell
node src/processar-capitulo.js --capitulo "..\obras\Obra\Cap 001" --motor local
node src/processar-capitulo.js --verificar --motor deepl      # só confere se o motor está pronto
```

- Lê as imagens de `<capítulo>\img\` (ou do próprio capítulo, no formato antigo); **nunca as altera nem copia**.
- Resultado: `<capítulo>\traducao.json` e `<capítulo>\traducao\limpeza\*.png`.
- O trabalho fica em `<capítulo>\traducao.nova\` até o fim; cancelar/falhar e rodar de novo continua de onde parou, e a
  tradução anterior vale até a nova terminar. `--refazer` apenas dispensa o aviso "já traduzido".
- Motores: `local` (TranslateGemma via Ollama), `deepl`, `gemini`, `mymemory`. Sempre explícito (`--motor` ou `TRANSLATION_ENGINE`),
  sem fallback. Variáveis: `OLLAMA_URL`, `LOCAL_MODEL`, `DEEPL_API_KEY`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `MYMEMORY_EMAIL`.
- Opcional por capítulo: `<obra>\glossario.json` (`{"TERMO": "tradução"}`) e `<capítulo>\correcoes.json` (`{"p001-b3": "texto"}`).
- `TRADUTOR_EVENTOS=1` faz o Node escrever linhas `@@{json}` de progresso (é como o Baixador mostra as barras).

## Etapas (cada uma grava na sua pasta dentro de `traducao.nova\`)

| Etapa | Código | O que faz |
|---|---|---|
| 3 | `src/vision/detect.js`, `run.js` | balões e regiões de texto (OpenCV) |
| 8 | `src/vision/textstage.js`, `textdet.js` | detecção de texto por modelo (PP-OCRv4, opcional) |
| 4a | `src/vision/ocr.js`, `src/ocr/` | OCR por região (Tesseract; PaddleOCR de reserva) |
| 4b | `src/vision/translate.js`, `src/services/` | tradução em lotes com contexto e cache |
| 4c | `src/vision/translation-view.js` | junta tudo por página |
| 6 | `src/vision/clean.js`, `clean-free.js` | limpeza do texto original (PNG por página) e caixa de cada fala |
| leitor | `src/obra/pipeline.js` | consolida o `traducao.json` (campo `formato: 2`) |

No fim, só `traducao.json` e `traducao\limpeza\` ficam; as pastas das etapas e o cache são removidos.

## Testes

```powershell
npm test
```

`test/processar-capitulo.test.js` roda o fluxo completo (detecção, OCR e limpeza de verdade) com um Ollama de mentira.
O encaixe de texto (`web/leitor/layout.js`) é testado aqui também, porque o leitor usa o mesmo código no navegador.
