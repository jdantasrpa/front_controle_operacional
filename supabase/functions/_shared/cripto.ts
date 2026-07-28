// supabase/functions/_shared/cripto.ts
// Cripto de aplicação AES-256-GCM para as Edge Functions do SCO.
// INTEROPERÁVEL com api/cripto.py: mesmo envelope `sco1$<nonce>$<ct>` e
// mesmo PBKDF2 (`pbkdf2_sha256$iter$salt$hash`) de api/domain_usuarios.py.
// A chave-mestra vem do secret SCO_CHAVE_MESTRA (base64 de 32 bytes).

const PREFIXO = 'sco1';
const SEP = '$';

function b64encode(bytes: Uint8Array): string {
  let bin = '';
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin);
}

function b64decode(texto: string): Uint8Array {
  const bin = atob(texto);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function chaveBase64(): string {
  // deno-lint-ignore no-explicit-any
  const k = (globalThis as any).Deno?.env?.get('SCO_CHAVE_MESTRA');
  if (!k) throw new Error('SCO_CHAVE_MESTRA ausente no ambiente.');
  return k;
}

async function importarChave(chaveB64?: string): Promise<CryptoKey> {
  const bruto = b64decode(chaveB64 ?? chaveBase64());
  if (bruto.length !== 32) {
    throw new Error('Chave-mestra deve ter 32 bytes.');
  }
  return crypto.subtle.importKey('raw', bruto, { name: 'AES-GCM' }, false, [
    'encrypt',
    'decrypt',
  ]);
}

export function estaCriptografado(valor: unknown): boolean {
  return typeof valor === 'string' && valor.startsWith(PREFIXO + SEP);
}

export async function criptografar(
  texto: unknown,
  chaveB64?: string,
): Promise<unknown> {
  if (texto === null || texto === undefined || estaCriptografado(texto)) {
    return texto;
  }
  const key = await importarChave(chaveB64);
  const nonce = crypto.getRandomValues(new Uint8Array(12));
  const cifra = new Uint8Array(
    await crypto.subtle.encrypt(
      { name: 'AES-GCM', iv: nonce },
      key,
      new TextEncoder().encode(String(texto)),
    ),
  );
  return [PREFIXO, b64encode(nonce), b64encode(cifra)].join(SEP);
}

export async function descriptografar(
  token: unknown,
  chaveB64?: string,
): Promise<unknown> {
  if (token === null || token === undefined || !estaCriptografado(token)) {
    return token;
  }
  const partes = (token as string).split(SEP);
  if (partes.length !== 3) throw new Error('Envelope cifrado malformado.');

  const key = await importarChave(chaveB64);
  const claro = await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: b64decode(partes[1]) },
    key,
    b64decode(partes[2]),
  );
  return new TextDecoder().decode(claro);
}

export async function criptografarCampos(
  registro: Record<string, unknown>,
  campos: readonly string[],
): Promise<Record<string, unknown>> {
  const saida = { ...registro };
  for (const campo of campos) {
    if (campo in saida) saida[campo] = await criptografar(saida[campo]);
  }
  return saida;
}

export async function descriptografarCampos(
  registro: Record<string, unknown>,
  campos: readonly string[],
): Promise<Record<string, unknown>> {
  const saida = { ...registro };
  for (const campo of campos) {
    if (campo in saida) saida[campo] = await descriptografar(saida[campo]);
  }
  return saida;
}

// Gera o hash PBKDF2 de uma senha (mesmo formato do Python):
// pbkdf2_sha256$<iteracoes>$<salt_b64>$<hash_b64>.
export async function gerarHashSenha(
  senha: string,
  iteracoes = 260000,
): Promise<string> {
  if (!senha) throw new Error('Senha vazia não pode virar hash.');
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const material = await crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(senha),
    'PBKDF2',
    false,
    ['deriveBits'],
  );
  const derivada = new Uint8Array(
    await crypto.subtle.deriveBits(
      { name: 'PBKDF2', salt, iterations: iteracoes, hash: 'SHA-256' },
      material,
      256,
    ),
  );
  return `pbkdf2_sha256$${iteracoes}$${b64encode(salt)}$${b64encode(derivada)}`;
}

// Verifica a senha contra o hash PBKDF2 gravado (mesmo formato do Python).
export async function verificarSenha(
  senha: string,
  hashArmazenado: string,
): Promise<boolean> {
  const partes = String(hashArmazenado ?? '').split('$');
  if (partes.length !== 4 || partes[0] !== 'pbkdf2_sha256') return false;

  const iteracoes = parseInt(partes[1], 10);
  const salt = b64decode(partes[2]);
  const esperado = b64decode(partes[3]);

  const material = await crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(senha),
    'PBKDF2',
    false,
    ['deriveBits'],
  );
  const derivada = new Uint8Array(
    await crypto.subtle.deriveBits(
      { name: 'PBKDF2', salt, iterations: iteracoes, hash: 'SHA-256' },
      material,
      esperado.length * 8,
    ),
  );

  if (derivada.length !== esperado.length) return false;
  let diferenca = 0;
  for (let i = 0; i < derivada.length; i++) {
    diferenca |= derivada[i] ^ esperado[i];
  }
  return diferenca === 0;
}
