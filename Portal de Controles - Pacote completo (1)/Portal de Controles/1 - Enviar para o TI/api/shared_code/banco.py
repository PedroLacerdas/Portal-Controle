"""
Acesso ao banco (Azure Cosmos DB, API NoSQL) e regras comuns da API.

Configurações (Static Web App → Configurações → Variáveis de ambiente):
  COSMOS_CONEXAO   cadeia de conexão da conta Cosmos DB (obrigatória)
  COSMOS_BANCO     nome do banco      (padrão: controles)
  COSMOS_CONTEINER nome do contêiner  (padrão: registros; chave de partição /sistema)
  API_TOKEN        senha usada pela ponte da planilha (cabeçalho x-api-token)
  PAPEL_EXIGIDO    papel do login exigido para usar a API (padrão: authenticated)

Cada documento guardado:
  {"id": "<colecao>__<id>", "sistema": "floculantes", "colecao": "registros",
   "rid": "<id do app>", "dados": {...}, "atualizado": "<ISO de quando o servidor recebeu>"}
"""
import base64
import datetime as dt
import json
import os
import re

SISTEMAS = {"britadores", "floculantes", "ibm", "itm"}
_conteiner = None


def agora_iso():
    n = dt.datetime.now(dt.timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def conteiner():
    """Devolve o contêiner do Cosmos (criado uma vez por instância da função)."""
    global _conteiner
    if _conteiner is None:
        from azure.cosmos import CosmosClient
        cli = CosmosClient.from_connection_string(os.environ["COSMOS_CONEXAO"])
        db = cli.get_database_client(os.environ.get("COSMOS_BANCO", "controles"))
        _conteiner = db.get_container_client(os.environ.get("COSMOS_CONTEINER", "registros"))
    return _conteiner


def id_doc(colecao, rid):
    # o Cosmos não aceita / \ ? # no id
    return re.sub(r"[/\\?#]", "_", f"{colecao}__{rid}")[:255]


def autorizado(req):
    """Libera quem está logado no site (com o papel exigido) ou a ponte com o token."""
    tok = os.environ.get("API_TOKEN", "")
    if tok and req.headers.get("x-api-token") == tok:
        return True
    principal = req.headers.get("x-ms-client-principal")
    if not principal:
        return False
    try:
        info = json.loads(base64.b64decode(principal))
    except Exception:  # noqa: BLE001
        return False
    return os.environ.get("PAPEL_EXIGIDO", "authenticated") in (info.get("userRoles") or [])


def resposta(func, corpo, status=200):
    return func.HttpResponse(json.dumps(corpo, ensure_ascii=False), status_code=status,
                             mimetype="application/json", charset="utf-8",
                             headers={"Cache-Control": "no-store"})


def buscar_mudancas(sistema, desde):
    q = ("SELECT c.colecao, c.rid, c.dados, c.atualizado FROM c "
         "WHERE c.sistema = @s AND c.atualizado > @d")
    itens = conteiner().query_items(q, parameters=[{"name": "@s", "value": sistema},
                                                   {"name": "@d", "value": desde or ""}],
                                    partition_key=sistema)
    regs = sorted(itens, key=lambda x: x["atualizado"])
    return [{"colecao": r["colecao"], "id": r["rid"], "dados": r["dados"]} for r in regs]


def gravar_ops(sistema, ops):
    agora = agora_iso()
    c = conteiner()
    n = 0
    for op in ops:
        col, rid, dados = op.get("colecao"), op.get("id"), op.get("dados") or {}
        if not col or not rid:
            continue
        if op.get("op") == "delete":
            dados = {**dados, "excluido": True}
        dados.setdefault("atualizadoEm", agora)
        c.upsert_item({"id": id_doc(col, rid), "sistema": sistema, "colecao": col, "rid": str(rid),
                       "dados": dados, "atualizado": agora})
        n += 1
    return n
