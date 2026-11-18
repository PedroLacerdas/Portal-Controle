"""
API Planilha -> App (Controle de Floculantes / Britadores)

Lê uma planilha Excel do OneDrive e entrega os dados para o app no formato
que ele já usa para sincronizar:

  GET  /mudancas?desde=<ISO>   -> o que mudou desde a última sincronização
  POST /sync                   -> recebe o que foi lançado no tablet
  GET  /saude                  -> mostra se a API está lendo a planilha

Os lançamentos feitos no app ficam guardados num banco SQLite (arquivo
dados.db, nesta pasta). A planilha é só lida, nunca alterada.

Configuração: arquivo config.json (veja o LEIA-ME.md).
"""
import datetime as dt
import hashlib
import io
import json
import os
import re
import sqlite3
import sys
import threading
import time
from collections import Counter

import warnings

from flask import Flask, jsonify, request

warnings.filterwarnings("ignore", module="openpyxl")   # avisos de validação/desenhos do Excel não afetam a leitura
from openpyxl import load_workbook

PASTA = os.path.dirname(os.path.abspath(__file__))
CONFIG_ARQ = os.path.join(PASTA, "config.json")
DB_ARQ = os.path.join(PASTA, "dados.db")


# ---------------------------------------------------------------- config
def carregar_config():
    with open(CONFIG_ARQ, encoding="utf-8-sig") as f:
        texto = f.read()
    # caminhos colados do Windows (C:\Users\...) viram C:/Users/... para o JSON aceitar
    def _barras(m):
        return m[0].replace("\\\\", "/").replace("\\", "/")
    # caminhos colados do Windows (C:\Users\...) em "arquivo" (texto ou lista) e "caminho_no_onedrive"
    texto = re.sub(r'"(?:arquivo|caminho_no_onedrive)"\s*:\s*(\[[^\]]*\]|"[^"]*")', _barras, texto)
    try:
        cfg = json.loads(texto)
    except json.JSONDecodeError as e:
        sys.exit(f"\nErro no config.json, linha {e.lineno}, coluna {e.colno}: {e.msg}\n"
                 "Confira vírgulas, aspas e chaves nessa linha.\n")
    cfg.setdefault("modo", "local")
    cfg.setdefault("intervalo_leitura_seg", 300)
    cfg.setdefault("token_app", "")
    cfg.setdefault("porta", 8000)
    cfg.setdefault("mapeamentos", [])
    return cfg


CFG = carregar_config()


def agora_iso():
    # mesmo formato do app (JavaScript toISOString): 2026-10-21T11:14:05.123Z
    n = dt.datetime.now(dt.timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------- banco
_lock = threading.Lock()


def conectar():
    con = sqlite3.connect(DB_ARQ, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def criar_banco():
    with conectar() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS registros (
                colecao      TEXT NOT NULL,
                id           TEXT NOT NULL,
                dados        TEXT NOT NULL,
                atualizado   TEXT NOT NULL,
                origem       TEXT NOT NULL,          -- 'excel' ou 'app'
                hash_excel   TEXT,                   -- último conteúdo lido da planilha
                PRIMARY KEY (colecao, id)
            )""")
        con.execute("CREATE INDEX IF NOT EXISTS ix_atual ON registros(atualizado)")
        con.execute("CREATE TABLE IF NOT EXISTS meta (chave TEXT PRIMARY KEY, valor TEXT)")
        try:
            con.execute("ALTER TABLE registros ADD COLUMN fonte TEXT")   # bancos criados antes desta versão
        except sqlite3.OperationalError:
            pass


# ---------------------------------------------------------------- leitura da planilha
_ultima_copia = {}   # caminho -> (mtime, bytes) da última leitura bem-sucedida


def ler_bytes(caminho):
    """Lê o arquivo mesmo se estiver aberto no Excel (no Windows, pede compartilhamento total)."""
    try:
        with open(caminho, "rb") as f:
            return f.read()
    except PermissionError:
        if os.name != "nt":
            raise
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateFileW.restype = wintypes.HANDLE
        h = k32.CreateFileW(caminho, 0x80000000, 0x7, None, 3, 0x80, None)   # GENERIC_READ, share R|W|D
        if h in (None, wintypes.HANDLE(-1).value):
            raise
        try:
            tam = os.path.getsize(caminho)
            buf = ctypes.create_string_buffer(tam)
            lidos = wintypes.DWORD(0)
            if not k32.ReadFile(h, buf, tam, ctypes.byref(lidos), None):
                raise PermissionError(13, "arquivo bloqueado", caminho)
            return buf.raw[:lidos.value]
        finally:
            k32.CloseHandle(h)


def baixar_planilha():
    """Devolve [(nome, bytes)] e uma marca de versão, conforme o modo configurado.
    No modo local, "arquivo" aceita * para ler vários arquivos (ex.: um por mês)."""
    if CFG["modo"] == "graph":
        return [("onedrive", baixar_via_graph())], time.time()
    if CFG["modo"] != "local":
        raise ValueError('modo deve ser "local" ou "graph"')
    import glob
    entradas = CFG["local"]["arquivo"]
    entradas = entradas if isinstance(entradas, list) else [entradas]   # aceita um caminho ou uma lista
    caminhos = []
    for e in entradas:
        padrao = os.path.expandvars(os.path.expanduser(e))
        achados = sorted(p for p in glob.glob(padrao) if not os.path.basename(p).startswith("~$")) \
            if any(ch in padrao for ch in "*?") else [padrao]
        if not achados and not any(ch in padrao for ch in "*?"):
            raise FileNotFoundError(f"Arquivo não encontrado: {padrao}")
        caminhos += [p for p in achados if p not in caminhos]   # padrão com * sem arquivos ainda: segue sem erro
    if not caminhos:
        raise FileNotFoundError("Nenhum arquivo encontrado nos caminhos de \"arquivo\" do config.json")
    arquivos, avisos, versao = [], [], []
    for p in caminhos:
        mt = os.path.getmtime(p)
        versao.append((p, mt))
        ant = _ultima_copia.get(p)
        if ant and ant[0] == mt:
            arquivos.append((os.path.basename(p), ant[1]))
            continue
        try:
            dados = ler_bytes(p)
            _ultima_copia[p] = (mt, dados)
            arquivos.append((os.path.basename(p), dados))
        except PermissionError:
            if ant:
                arquivos.append((os.path.basename(p), ant[1]))
                avisos.append(f"{os.path.basename(p)} está bloqueado (aberto no Excel?); usando a última leitura")
            else:
                avisos.append(f"{os.path.basename(p)} está bloqueado (aberto no Excel?); será lido na próxima tentativa")
            versao[-1] = (p, time.time())   # força nova tentativa na próxima leitura
    _estado["avisos_arquivo"] = avisos
    _estado["parcial"] = len(arquivos) < len(caminhos)   # algum arquivo não pôde ser lido
    if not arquivos:
        raise PermissionError(13, "Nenhum arquivo pôde ser lido. " + "; ".join(avisos))
    return arquivos, tuple(versao)


def baixar_via_graph():
    """Baixa o arquivo do OneDrive pela API Microsoft Graph (login de usuário,
    feito uma única vez com o comando: python app.py --login)."""
    import msal
    import requests

    g = CFG["graph"]
    cache = msal.SerializableTokenCache()
    cache_arq = os.path.join(PASTA, "token_cache.bin")
    if os.path.exists(cache_arq):
        cache.deserialize(open(cache_arq, encoding="utf-8").read())
    app = msal.PublicClientApplication(
        g["client_id"], authority=f"https://login.microsoftonline.com/{g['tenant_id']}",
        token_cache=cache)
    contas = app.get_accounts()
    res = app.acquire_token_silent(["Files.Read"], account=contas[0]) if contas else None
    if not res or "access_token" not in res:
        raise RuntimeError("Sem login no Microsoft 365. Rode uma vez: python app.py --login")
    if cache.has_state_changed:
        open(cache_arq, "w", encoding="utf-8").write(cache.serialize())
    caminho = g["caminho_no_onedrive"].strip("/")
    url = f"https://graph.microsoft.com/v1.0/me/drive/root:/{caminho}:/content"
    r = requests.get(url, headers={"Authorization": "Bearer " + res["access_token"]}, timeout=60)
    r.raise_for_status()
    return r.content


def login_graph():
    import msal
    g = CFG["graph"]
    cache = msal.SerializableTokenCache()
    app = msal.PublicClientApplication(
        g["client_id"], authority=f"https://login.microsoftonline.com/{g['tenant_id']}",
        token_cache=cache)
    flow = app.initiate_device_flow(scopes=["Files.Read"])
    if "user_code" not in flow:
        sys.exit("Não foi possível iniciar o login: " + json.dumps(flow, ensure_ascii=False))
    print(flow["message"])
    res = app.acquire_token_by_device_flow(flow)
    if "access_token" not in res:
        sys.exit("Login falhou: " + str(res.get("error_description")))
    open(os.path.join(PASTA, "token_cache.bin"), "w", encoding="utf-8").write(cache.serialize())
    print("Login salvo. Agora rode: python app.py")


def normaliza(txt):
    return re.sub(r"[^a-z0-9]", "", str(txt or "").lower()
                  .translate(str.maketrans("áàâãäéêèíìóôõòúùüç", "aaaaaeeeiioooouuuc")))


def converte(valor, tipo):
    if valor is None or valor == "":
        return None
    if tipo == "data":
        if isinstance(valor, (dt.datetime, dt.date)):
            return valor.strftime("%Y-%m-%d")
        m = re.match(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})", str(valor))
        if m:
            d, mes, a = int(m[1]), int(m[2]), int(m[3])
            a = a + 2000 if a < 100 else a
            return f"{a:04d}-{mes:02d}-{d:02d}"
        return str(valor)[:10]
    if tipo == "simnao":                               # Sim/Não, S/N, X, 1/0 -> true/false
        return normaliza(valor) in ("sim", "s", "x", "1", "true", "verdadeiro", "yes")
    if tipo == "numero":
        if isinstance(valor, (int, float)):
            return float(valor)
        s = str(valor).strip().replace(" ", "")
        if "," in s:                                   # 9.100,5 -> 9100.5
            s = s.replace(".", "").replace(",", ".")
        elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):  # 2.300 -> 2300 (ponto de milhar)
            s = s.replace(".", "")
        try:
            return float(s)
        except ValueError:
            return None
    return str(valor).strip()


def ler_mapeamento(wb, mp):
    """Lê uma aba em formato de tabela e devolve {id: dados} para uma coleção do app."""
    if mp["aba"] not in wb.sheetnames:
        raise ValueError(f'Aba "{mp["aba"]}" não encontrada. Abas: {", ".join(wb.sheetnames)}')
    ws = wb[mp["aba"]]
    linha_cab = int(mp.get("linha_cabecalho", 1))
    cab = [normaliza(c.value) for c in ws[linha_cab]]

    def col(nome, obrigatoria=True):
        n = normaliza(nome)
        if n in cab:
            return cab.index(n)
        if obrigatoria:
            raise ValueError(f'Coluna "{nome}" não encontrada na aba "{mp["aba"]}" (linha {linha_cab}).')
        return None

    colunas = mp.get("colunas", {})   # {"Título na planilha": {"campo", "tipo", "mapa"?, "opcional"?}}
    idx = {}
    for nome, destino in colunas.items():
        i = col(nome, not destino.get("opcional"))
        if i is not None:
            mapa = {normaliza(k): v for k, v in (destino.get("mapa") or {}).items()}
            idx[nome] = (i, destino["campo"], destino.get("tipo", "texto"), mapa)
    # granulometria: colunas de malha viram as listas peneiras/retidos que o app usa
    malhas = [(col(nome), float(mm)) for nome, mm in (mp.get("malhas") or {}).items()]
    i_fundo = col(mp["coluna_fundo"]) if mp.get("coluna_fundo") else None
    corte = float(mp.get("corte", 1.4))
    fixos = mp.get("valores_fixos", {})
    chave = mp["chave"]
    saida = {}
    for row in ws.iter_rows(min_row=linha_cab + 1, values_only=True):
        if row is None or all(v is None or str(v).strip() == "" for v in row):
            continue
        if any(isinstance(v, str) and v.strip().upper().startswith("EXEMPLO") for v in row):
            continue                     # linha de exemplo do modelo
        pega = lambda i: row[i] if i is not None and i < len(row) else None  # noqa: E731
        dados = {}
        for _, (i, campo, tipo, mapa) in idx.items():
            v = pega(i)
            if mapa and v not in (None, ""):
                v = mapa.get(normaliza(v), v)
                dados[campo] = v if tipo == "texto" else converte(v, tipo)
            elif tipo == "id":
                dados[campo] = normaliza(v) or None
            else:
                dados[campo] = converte(v, tipo)
        if any(dados.get(colunas[k]["campo"]) in (None, "") for k in chave):
            continue                     # linha sem os campos-chave: ignora
        if malhas:
            ret = [converte(pega(i), "numero") or 0.0 for i, _ in malhas]
            fundo = converte(pega(i_fundo), "numero") or 0.0
            total = sum(ret) + fundo
            if total <= 0:
                continue                 # coleta ainda sem valores
            fino = sum(r for r, (_, mm) in zip(ret, malhas) if mm <= corte + 1e-9) + fundo
            dados.update(peneiras=[mm for _, mm in malhas], retidos=ret, fundo=fundo, total=total,
                         corte=corte, passante=round(fino / total * 100, 2))
        dados.update(fixos)
        txt_chave = "|".join(str(dados[colunas[k]["campo"]]) for k in chave)
        rid = "xl-" + hashlib.sha1(f'{mp["colecao"]}|{txt_chave}'.encode()).hexdigest()[:16]
        saida[rid] = dados
    return saida


def ler_relatorios(wb, mp):
    """Lê planilhas no formato "Relatório de Produção e Operação": uma aba por turno
    (ex.: 21-10X), com Data:/Turno: no cabeçalho e colunas com linha de Total.
    Cada aba vira um registro de turno no app."""
    padrao = re.compile(mp.get("abas_padrao", r"^\d{2}-\d{2}[XYZ]$"), re.I)
    saida, avisos, lidos = {}, [], []
    for nome in wb.sheetnames:
        if not padrao.match(nome.strip()):
            continue                     # ignora MODELO (55) etc.
        ws = wb[nome]
        celulas = [(c.row, c.column, c.value) for row in ws.iter_rows() for c in row if c.value not in (None, "")]
        texto = {(r, k): normaliza(v) for r, k, v in celulas if isinstance(v, str)}
        valor = {(r, k): v for r, k, v in celulas}

        def ao_lado(rotulo):
            alvo = normaliza(rotulo)
            for (r, k), t in sorted(texto.items()):
                if t == alvo:
                    for kk in range(k + 1, k + 8):
                        v = valor.get((r, kk))
                        if v not in (None, ""):
                            return v
            return None

        def achar_coluna(rotulo):
            alvo = normaliza(rotulo)
            iguais = sorted(p for p, t in texto.items() if t == alvo)
            parecidos = sorted(p for p, t in texto.items() if t.startswith(alvo))
            return (iguais or parecidos or [None])[0]

        def total_coluna(pos, so_positivos=False):
            r0, k = pos
            # linha de Total: primeira linha abaixo do cabeçalho com "Total" à esquerda da coluna
            linha_total = next((r for (r, kk), t in sorted(texto.items())
                                if r > r0 and kk < k and t == "total"), None)
            fim = linha_total if linha_total else r0 + 40
            if linha_total and not so_positivos:
                v = converte(valor.get((linha_total, k)), "numero")
                if v is not None:
                    return v
            nums = [converte(valor.get((r, k)), "numero") for r in range(r0 + 1, fim)]
            nums = [n for n in nums if n is not None and (n > 0 or not so_positivos)]
            return sum(nums) if nums else None

        data = converte(ao_lado(mp.get("rotulo_data", "Data:")), "data")
        turno = str(ao_lado(mp.get("rotulo_turno", "Turno:")) or nome.strip()[-1]).strip().upper()[:1]
        p_vol = achar_coluna(mp["coluna_volume"])
        col_ton = mp["coluna_toneladas"]                 # um título ou uma lista (usa o primeiro que existir na aba)
        p_ton = next((p for p in (achar_coluna(c) for c in (col_ton if isinstance(col_ton, list) else [col_ton])) if p), None)
        if not data and not re.match(r"^\d{2}-\d{2}[XYZ]$", nome.strip(), re.I):
            continue                     # aba MODELO ainda em branco
        if turno not in ("X", "Y", "Z"):
            avisos.append(f"{nome}: turno não identificado")
            continue
        if not data or not p_vol or not p_ton:
            avisos.append(f'{nome}: {"data" if not data else "coluna de volume" if not p_vol else "coluna de toneladas"} não encontrada')
            continue
        litros = total_coluna(p_vol)
        # toneladas: soma das horas com valor positivo (horas sem operação aparecem negativas na planilha)
        ton = total_coluna(p_ton, so_positivos=mp.get("toneladas_so_positivos", True))
        if litros is None or not ton:
            continue                     # turno ainda sem lançamentos
        lidos.append({"data": data, "turno": turno, "litros": litros, "ton": ton,
                      "conc": float(mp.get("concentracao", 0.1)), "aba": nome.strip()})

    # Abas com nome dd-mm + turno (02-01Z): se a Data digitada não bater com o nome, vale o nome,
    # com o ano mais comum do arquivo (pega 07/01/2025 ou 27/01/2027 digitados numa planilha de jan/2026).
    anos = Counter(d["data"][:4] for d in lidos if re.match(r"^\d{2}-\d{2}[XYZ]$", d["aba"], re.I))
    ano = anos.most_common(1)[0][0] if anos else None
    for d in lidos:
        m = re.match(r"^(\d{2})-(\d{2})[XYZ]$", d["aba"], re.I)
        if m and ano:
            certa = f"{ano}-{m[2]}-{m[1]}"
            if d["data"] != certa:
                try:
                    dt.date.fromisoformat(certa)
                    avisos.append(f'{d["aba"]}: data {d["data"]} corrigida para {certa} (nome da aba)')
                    d["data"] = certa
                except ValueError:
                    pass
        rid = "xl-" + hashlib.sha1(f'{mp["colecao"]}|{d["data"]}|{d["turno"]}'.encode()).hexdigest()[:16]
        saida[rid] = d
    if avisos:
        print("Avisos:", "; ".join(avisos), file=sys.stderr)
        _estado.setdefault("avisos", []).extend(avisos)
    return saida


_estado = {"ultima_leitura": 0.0, "mtime": None, "erro": "", "linhas": 0, "lida_em": None, "avisos": []}


def sincronizar_planilha(forcar=False):
    """Relê a planilha (no máximo a cada intervalo_leitura_seg) e grava as mudanças no banco."""
    if not forcar and time.time() - _estado["ultima_leitura"] < CFG["intervalo_leitura_seg"]:
        return
    with _lock:
        _estado["ultima_leitura"] = time.time()
        try:
            arquivos, mtime = baixar_planilha()
            if CFG["modo"] == "local" and mtime == _estado["mtime"] and not forcar:
                return                   # arquivos não mudaram
            livros = [(n, load_workbook(io.BytesIO(b), data_only=True, read_only=False)) for n, b in arquivos]
            agora = agora_iso()
            total = 0
            with conectar() as con:
                _estado["avisos"] = []
                for mp in CFG["mapeamentos"]:
                    if mp.get("ativo") is False:
                        continue
                    fonte = mp.get("nome") or f'{mp["colecao"]}|{mp.get("aba") or mp.get("tipo")}'
                    filtro = normaliza(mp.get("arquivo_contem", ""))
                    usar = [(n, wb) for n, wb in livros if filtro in normaliza(n)]
                    linhas, falhas = {}, []
                    for nome_arq, wb in usar:          # vários arquivos (ex.: um por mês) viram uma lista só
                        try:
                            linhas.update(ler_relatorios(wb, mp) if mp.get("tipo") == "relatorio_turno"
                                          else ler_mapeamento(wb, mp))
                        except ValueError as e:
                            falhas.append(f"{nome_arq}: {e}")
                    if falhas and len(falhas) == len(usar):
                        raise ValueError("; ".join(falhas))
                    total += len(linhas)
                    existentes = {r["id"]: r for r in con.execute(
                        "SELECT id, hash_excel, origem FROM registros WHERE colecao=? AND hash_excel IS NOT NULL AND fonte=?",
                        (mp["colecao"], fonte))}
                    for rid, dados in linhas.items():
                        h = hashlib.sha1(json.dumps(dados, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                        ant = existentes.pop(rid, None)
                        if ant and ant["hash_excel"] == h:
                            continue     # linha igual à última leitura: não mexe (preserva edições do app)
                        corpo = {**dados, "id": rid, "atualizadoEm": agora, "excluido": False, "origem": "planilha"}
                        con.execute("""INSERT INTO registros(colecao,id,dados,atualizado,origem,hash_excel,fonte)
                                       VALUES(?,?,?,?, 'excel', ?, ?)
                                       ON CONFLICT(colecao,id) DO UPDATE SET dados=excluded.dados,
                                       atualizado=excluded.atualizado, origem='excel', hash_excel=excluded.hash_excel,
                                       fonte=excluded.fonte""",
                                    (mp["colecao"], rid, json.dumps(corpo, ensure_ascii=False), agora, h, fonte))
                    # linhas que sumiram da planilha: marca como excluídas no app
                    for rid, ant in existentes.items():
                        if _estado.get("parcial"):
                            break                # leitura incompleta: não apaga nada
                        if ant["origem"] != "excel":
                            continue
                        row = con.execute("SELECT dados FROM registros WHERE colecao=? AND id=?",
                                          (mp["colecao"], rid)).fetchone()
                        corpo = {**json.loads(row["dados"]), "excluido": True, "atualizadoEm": agora}
                        con.execute("UPDATE registros SET dados=?, atualizado=?, hash_excel=NULL WHERE colecao=? AND id=?",
                                    (json.dumps(corpo, ensure_ascii=False), agora, mp["colecao"], rid))
            _estado.update(mtime=mtime, erro="", linhas=total, lida_em=agora)
            print(f"[{agora}] planilha lida: {total} linha(s)")
        except Exception as e:  # noqa: BLE001
            _estado["erro"] = f"{type(e).__name__}: {e}"
            print("ERRO ao ler a planilha:", _estado["erro"], file=sys.stderr)


# ---------------------------------------------------------------- ponte para a nuvem
def enviar_nuvem():
    """Envia para a API na nuvem (Azure) os turnos lidos da planilha que mudaram desde o último envio."""
    nv = CFG.get("nuvem") or {}
    if not nv.get("url"):
        return
    import urllib.request
    with conectar() as con:
        row = con.execute("SELECT valor FROM meta WHERE chave='ultimo_envio_nuvem'").fetchone()
        desde = row["valor"] if row else ""
        regs = con.execute("SELECT colecao, id, dados, atualizado FROM registros "
                           "WHERE origem='excel' AND atualizado > ? ORDER BY atualizado", (desde,)).fetchall()
    if not regs:
        return
    url = nv["url"].rstrip("/") + "/sync"
    for i in range(0, len(regs), 500):
        lote = regs[i:i + 500]
        ops = [{"op": "upsert", "colecao": r["colecao"], "id": r["id"], "dados": json.loads(r["dados"])} for r in lote]
        req = urllib.request.Request(url, data=json.dumps({"ops": ops}).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "x-api-token": nv.get("token", "")})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                resp.read()
        except Exception as e:  # noqa: BLE001
            _estado["erro_nuvem"] = f"{type(e).__name__}: {e}"
            print("ERRO ao enviar para a nuvem:", _estado["erro_nuvem"], file=sys.stderr)
            return
        with conectar() as con:
            con.execute("INSERT INTO meta(chave,valor) VALUES('ultimo_envio_nuvem',?) "
                        "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor", (lote[-1]["atualizado"],))
    _estado["erro_nuvem"] = ""
    _estado["enviado_nuvem_em"] = agora_iso()
    print(f"[{agora_iso()}] {len(regs)} registro(s) enviados para a nuvem")


def rotina_fundo():
    """Relê a planilha e envia para a nuvem de tempos em tempos, mesmo sem ninguém acessar a API."""
    while True:
        time.sleep(max(30, CFG["intervalo_leitura_seg"]))
        try:
            sincronizar_planilha()
            enviar_nuvem()
        except Exception as e:  # noqa: BLE001
            print("ERRO na rotina:", e, file=sys.stderr)


# ---------------------------------------------------------------- servidor web
api = Flask(__name__)


@api.after_request
def cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


def autorizado():
    tok = CFG["token_app"]
    return not tok or request.headers.get("Authorization", "") == "Bearer " + tok


@api.route("/<path:_p>", methods=["OPTIONS"])
def preflight(_p):
    return ("", 204)


@api.get("/saude")
def saude():
    nv = CFG.get("nuvem") or {}
    extra = {"nuvem": {"url": nv.get("url"), "enviado_em": _estado.get("enviado_nuvem_em"),
                       "erro": _estado.get("erro_nuvem") or None}} if nv.get("url") else {}
    return jsonify(**extra, modo=CFG["modo"], planilha_lida_em=_estado["lida_em"],
                   linhas_lidas=_estado["linhas"], erro=_estado["erro"] or None,
                   avisos=(_estado.get("avisos_arquivo") or []) + (_estado.get("avisos") or []) or None)


def _chave(sistema, col):
    # Floculantes usa os nomes simples (compatível com a planilha); os outros apps ganham prefixo
    return col if sistema == "floculantes" else f"{sistema}:{col}"


@api.get("/mudancas")
@api.get("/<sistema>/mudancas")
def mudancas(sistema="floculantes"):
    if not autorizado():
        return jsonify(erro="token inválido"), 401
    sincronizar_planilha()
    desde = request.args.get("desde", "")
    agora = agora_iso()
    if sistema == "floculantes":
        filtro, arg = "colecao NOT LIKE '%:%'", ()
    else:
        filtro, arg = "colecao LIKE ?", (sistema + ":%",)
    with conectar() as con:
        rows = con.execute(f"SELECT colecao, id, dados FROM registros WHERE atualizado > ? AND {filtro} ORDER BY atualizado",
                           (desde, *arg)).fetchall()
    return jsonify(agora=agora, registros=[
        {"colecao": r["colecao"].split(":", 1)[-1], "id": r["id"], "dados": json.loads(r["dados"])} for r in rows])


@api.post("/sync")
@api.post("/<sistema>/sync")
def sync(sistema="floculantes"):
    if not autorizado():
        return jsonify(erro="token inválido"), 401
    corpo = request.get_json(silent=True) or {}
    ops = corpo.get("ops", [])
    agora = agora_iso()
    with _lock, conectar() as con:
        for op in ops:
            col, rid, dados = op.get("colecao"), op.get("id"), op.get("dados") or {}
            if not col or not rid:
                continue
            if op.get("op") == "delete":
                dados = {**dados, "excluido": True}
            dados.setdefault("atualizadoEm", agora)
            # 'atualizado' = hora em que o servidor recebeu; é o que /mudancas usa para entregar aos outros aparelhos
            con.execute("""INSERT INTO registros(colecao,id,dados,atualizado,origem,hash_excel)
                           VALUES(?,?,?,?,'app',NULL)
                           ON CONFLICT(colecao,id) DO UPDATE SET dados=excluded.dados, atualizado=excluded.atualizado,
                           origem=CASE WHEN registros.origem='excel' THEN 'excel' ELSE 'app' END""",
                        (_chave(sistema, col), rid, json.dumps(dados, ensure_ascii=False), agora))
    return jsonify(ok=True, recebidos=len(ops))


@api.get("/")
def inicio():
    return ("API da planilha funcionando. Veja /saude para o status da leitura.", 200,
            {"Content-Type": "text/plain; charset=utf-8"})


if __name__ == "__main__":
    if "--login" in sys.argv:
        login_graph()
        sys.exit()
    criar_banco()
    sincronizar_planilha(forcar=True)
    enviar_nuvem()
    threading.Thread(target=rotina_fundo, daemon=True).start()
    print(f"API rodando em http://0.0.0.0:{CFG['porta']}  (Ctrl+C para parar)")
    try:
        from waitress import serve        # servidor de produção, também gratuito
        serve(api, host="0.0.0.0", port=CFG["porta"])
    except ImportError:
        api.run(host="0.0.0.0", port=CFG["porta"])
