/* Criptografia do arquivo de acesso (dados.enc.json) do Portal de Controles.
   Sem servidor e sem banco: os dados vão para o GitHub embaralhados (AES-GCM 256)
   e só abrem com um usuário e senha válidos.

   - Uma chave aleatória (chave dos dados) cifra a cópia de segurança, comprimida com gzip.
   - Para cada usuário, a chave dos dados é guardada cifrada com uma chave tirada da senha
     (PBKDF2-SHA256). O nome do usuário fica só como hash, não aparece no arquivo.
   Usado por login.html (abrir) e por ../gerar-acesso.html (gerar). */
(function (g) {
  "use strict";
  const ITERACOES = 310000;
  const te = new TextEncoder(), td = new TextDecoder();

  function b64(buf) {
    const u = new Uint8Array(buf); let s = "";
    for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode.apply(null, u.subarray(i, i + 0x8000));
    return btoa(s);
  }
  function deB64(s) {
    const bin = atob(s), u = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
    return u;
  }
  const aleatorio = n => crypto.getRandomValues(new Uint8Array(n));
  const normUsuario = u => String(u || "").trim().toLowerCase();

  async function idUsuario(usuario) {
    const h = await crypto.subtle.digest("SHA-256", te.encode("portal-controles:" + normUsuario(usuario)));
    return Array.from(new Uint8Array(h), b => b.toString(16).padStart(2, "0")).join("");
  }
  async function chaveDaSenha(senha, sal, iteracoes) {
    const base = await crypto.subtle.importKey("raw", te.encode(senha), "PBKDF2", false, ["deriveKey"]);
    return crypto.subtle.deriveKey({ name: "PBKDF2", salt: sal, iterations: iteracoes, hash: "SHA-256" },
      base, { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
  }
  async function processar(bytes, stream) {
    const s = new Blob([bytes]).stream().pipeThrough(stream);
    return new Uint8Array(await new Response(s).arrayBuffer());
  }
  const comprimir = b => processar(b, new CompressionStream("gzip"));
  const descomprimir = b => processar(b, new DecompressionStream("gzip"));

  /* usuarios: [{usuario, senha}] · backup: objeto da Cópia de segurança do Portal (ou null) */
  async function gerar(usuarios, backup) {
    const chaveBruta = aleatorio(32);
    const chave = await crypto.subtle.importKey("raw", chaveBruta, "AES-GCM", false, ["encrypt"]);
    const saida = { formato: "portal-controles-acesso", v: 1, iteracoes: ITERACOES, publicadoEm: new Date().toISOString(), usuarios: {}, dados: null };
    for (const { usuario, senha } of usuarios) {
      const sal = aleatorio(16), iv = aleatorio(12);
      const kek = await chaveDaSenha(senha, sal, ITERACOES);
      const k = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, kek, chaveBruta);
      saida.usuarios[await idUsuario(usuario)] = { sal: b64(sal), iv: b64(iv), chave: b64(k) };
    }
    if (backup) {
      const iv = aleatorio(12);
      const gz = await comprimir(te.encode(JSON.stringify(backup)));
      saida.dados = { iv: b64(iv), conteudo: b64(await crypto.subtle.encrypt({ name: "AES-GCM", iv }, chave, gz)) };
    }
    return saida;
  }

  /* Confere usuário e senha. Devolve a chave dos dados, ou null se não conferir. */
  async function entrar(arquivo, usuario, senha) {
    const u = arquivo.usuarios[await idUsuario(usuario)];
    if (!u) return null;
    try {
      const kek = await chaveDaSenha(senha, deB64(u.sal), arquivo.iteracoes || ITERACOES);
      const bruta = await crypto.subtle.decrypt({ name: "AES-GCM", iv: deB64(u.iv) }, kek, deB64(u.chave));
      return crypto.subtle.importKey("raw", bruta, "AES-GCM", false, ["decrypt"]);
    } catch (e) { return null; }
  }

  async function abrirDados(arquivo, chave) {
    if (!arquivo.dados) return null;
    const gz = await crypto.subtle.decrypt({ name: "AES-GCM", iv: deB64(arquivo.dados.iv) }, chave, deB64(arquivo.dados.conteudo));
    return JSON.parse(td.decode(await descomprimir(new Uint8Array(gz))));
  }

  g.PortalCripto = { gerar, entrar, abrirDados, normUsuario };
})(window);
