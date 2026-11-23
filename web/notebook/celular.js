/* Aba "Leitura pelo celular": liga o servidor somente leitura e mostra o QR code com a chave. */
let celular = {ligado: false};
let celularVisto = false;

// Dois QR, cada um com o destino do seu cartão: o do app (endereço do Tailscale) e o do site (endereço do Wi-Fi de casa).
function desenharQR(id, url, vazio) {
  const alvo = $(id);
  if (!url) { alvo.className = 'qr vazio'; alvo.replaceChildren(Object.assign(document.createElement('span'), {textContent: vazio})); return; }
  const qr = qrcode(0, 'M'); qr.addData(url); qr.make();
  const svg = new DOMParser().parseFromString(qr.createSvgTag({cellSize: 4, margin: 0, scalable: true}), 'image/svg+xml').documentElement;
  alvo.className = 'qr'; alvo.replaceChildren(svg);
}

function aplicarCelular(e) {
  celular = e;
  if (!celularVisto) { celularVisto = true; $('cel-app').open = !e.tailscale; }   // configuração aberta só enquanto falta o Tailscale
  const temApp = !!e.url_app, temLocal = !!e.url;
  $('cel-comando').textContent = e.comando_tailscale || '';
  if (document.activeElement !== $('cel-ts')) $('cel-ts').value = e.tailscale || '';
  $('cel-app-url').textContent = e.url_app || 'Configure o Tailscale abaixo';
  $('cel-url').textContent = e.url || 'Ligue o acesso e conecte ao Wi-Fi';
  $('cel-app-copiar').disabled = !temApp; $('cel-copiar').disabled = !temLocal;
  $('cel-cartao-app').classList.toggle('ativo', !!e.ligado && temApp); $('cel-cartao-site').classList.toggle('ativo', !!e.ligado && temLocal);
  $('cel-app-msg').textContent = e.tailscale && !e.ligado ? 'Ligue o acesso do celular (botão acima) para gerar o QR.' : '';
  $('cel-ligar').hidden = e.ligado; $('cel-desligar').hidden = !e.ligado;
  $('cel-sem-rede').hidden = !(e.ligado && !temApp && !temLocal);
  $('cel-lembrar').checked = !!e.ligar_ao_abrir;
  $('cel-controle').dataset.ligado = e.ligado ? '1' : '0';
  $('cel-estado-txt').textContent = e.ligado ? 'Acesso ligado' : 'Acesso desligado';
  desenharQR('qr-app', e.ligado && temApp ? e.url_app : '', e.ligado ? 'Configure o Tailscale para gerar este QR' : 'Ligue o acesso para gerar o QR');
  desenharQR('qr-site', e.ligado && temLocal ? e.url : '', e.ligado ? 'Sem endereço de Wi-Fi no notebook' : 'Ligue o acesso para gerar o QR');
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
