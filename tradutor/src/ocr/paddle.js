import sharp from 'sharp';

// Segundo leitor, só como reserva: PaddleOCR (modelos PP-OCRv4 em ONNX, pacote opcional @gutenye/ocr-node).
// Lê melhor que o Tesseract as falas em letra grossa de pincel e as exclamações curtas ("IMPOSSIBLE!", "?!"), que o
// Tesseract devolve vazias; em texto corrido ele cola palavras ("HEWON'TIMAGINE"), por isso só entra quando o Tesseract falha.
// Sem o pacote instalado, devolve null e o resto funciona só com o Tesseract.
const MIN_SCORE = 0.75;
const PAD = 20; // o detector do Paddle perde texto colado na borda da imagem

export async function createPaddle() {
  let ocr;
  try {
    const { default: Ocr } = await import('@gutenye/ocr-node');
    ocr = await Ocr.create();
  } catch {
    return null;
  }
  return {
    name: 'PaddleOCR',
    async read(png) {
      const { data, info } = await sharp(png).flatten({ background: '#fff' })
        .extend({ top: PAD, bottom: PAD, left: PAD, right: PAD, background: '#fff' })
        .ensureAlpha(1).raw().toBuffer({ resolveWithObject: true });
      const { texts } = await ocr.detect({ data, width: info.width, height: info.height });
      const lines = texts.filter((t) => t.mean >= MIN_SCORE).map((t) => t.text.normalize('NFKC').trim()).filter(Boolean);
      const text = lines.join(' ');
      const real = /[A-Za-z0-9]/.test(text) || /^[?!.…]+$/.test(text);
      return real ? { text, confidence: Math.round(100 * Math.min(...texts.map((t) => t.mean))) } : { text: '', confidence: 0 };
    },
  };
}
