/* Aba "Leitura pelo celular": liga o servidor somente leitura e mostra o QR code com a chave. */
let celular = {ligado: false};

function desenharQR(url) {
  const alvo = $('qr');
  if (!url) { alvo.replaceChildren(Object.assign(document.createElement('span'), {className: 'nota', textContent: 'Desligado'})); return; }
  const qr = qrcode(0, 'M'); qr.addData(url); qr.make();
  const svg = new DOMParser().parseFromString(qr.createSvgTag({cellSize: 4, margin: 0, scalable: true}), 'image/svg+xml').documentElement;
  alvo.replaceChildren(svg);
}

function desenharQRApp(url) {
  const alvo = $('qr-app');
  if (!url) { alvo.replaceChildren(); return; }
  const qr = qrcode(0, 'M'); qr.addData(url); qr.make();
  alvo.replaceChildren(new DOMParser().parseFromString(qr.createSvgTag({cellSize: 4, margin: 0, scalable: true}), 'image/svg+xml').documentElement);
}

function aplicarCelular(e) {
  celular = e;
  $('cel-comando').textContent = e.comando_tailscale || '';
  if (document.activeElement !== $('cel-ts')) $('cel-ts').value = e.tailscale || '';
  $('cel-app-ok').hidden = !e.url_app;
  $('cel-app-url').textContent = e.url_app || '';
  desenharQRApp(e.url_app || '');
  $('cel-app-msg').textContent = e.tailscale && !e.ligado ? 'Ligue o acesso do celular (botão acima) para gerar o QR do app.' : '';
  $('cel-ligar').hidden = e.ligado; $('cel-desligar').hidden = !e.ligado;
  $('cel-ligado').hidden = !e.ligado || !e.url;
  $('cel-sem-rede').hidden = !(e.ligado && !e.url);
  $('cel-lembrar').checked = !!e.ligar_ao_abrir;
  $('cel-url').textContent = e.url || '';
  desenharQR(e.ligado ? e.url : '');
  $('cel-msg').textContent = e.erro || '';
  $('chip-celular').className = 'chip' + (e.ligado ? ' ok' : '');
  $('chip-celular').textContent = e.ligado ? 'Celular ligado' : 'Celular desligado';
}
async function celularChamar(caminho, corpo) {
  $('cel-msg').textContent = '';
  try { aplicarCelular(await chamar(caminho, corpo)); } catch (e) { $('cel-msg').textContent = e.message; }
}
$('cel-ligar').addEventListener('click', () => celularChamar('/api/celular/ligar', {lembrar: $('cel-lembrar').checked}));
$('cel-desligar').addEventListener('click', () => celularChamar('/api/celular/desligar'));
$('cel-lembrar').addEventListener('change', () => {
  if (celular.ligado) celularChamar('/api/celular/ligar', {lembrar: $('cel-lembrar').checked});
  else celularChamar('/api/celular/desligar', {lembrar: $('cel-lembrar').checked});
});
$('cel-trocar').addEventListener('click', () => {
  if (confirm('Trocar a chave? O QR code atual e os celulares já autorizados deixam de funcionar; será preciso ler o novo QR.')) celularChamar('/api/celular/trocar-chave');
});
$('cel-copiar').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText(celular.url); aviso('Endereço copiado.'); } catch (_) { aviso('Selecione o endereço e copie com Ctrl+C.'); }
});
async function tailscaleChamar(corpo) {
  $('cel-app-msg').textContent = '';
  try { aplicarCelular(await chamar('/api/celular/tailscale', corpo)); } catch (e) { $('cel-app-msg').textContent = e.message; }
}
$('cel-ts-salvar').addEventListener('click', () => tailscaleChamar({host: $('cel-ts').value}));
$('cel-ts-detectar').addEventListener('click', () => tailscaleChamar({detectar: true}));
$('cel-app-copiar').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText(celular.url_app); aviso('Código copiado.'); } catch (_) { aviso('Selecione o código e copie com Ctrl+C.'); }
});
ler('/api/celular/estado').then(aplicarCelular).catch(() => {});
