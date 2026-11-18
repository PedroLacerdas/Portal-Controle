import logging

import azure.functions as func

from shared_code import banco


def main(req: func.HttpRequest) -> func.HttpResponse:
    sistema = req.route_params.get("sistema", "")
    if sistema not in banco.SISTEMAS:
        return banco.resposta(func, {"erro": "sistema desconhecido"}, 404)
    if not banco.autorizado(req):
        return banco.resposta(func, {"erro": "faça login"}, 403)
    try:
        corpo = req.get_json()
    except ValueError:
        return banco.resposta(func, {"erro": "corpo inválido"}, 400)
    ops = (corpo or {}).get("ops") or []
    if len(ops) > 2000:
        return banco.resposta(func, {"erro": "envie no máximo 2000 alterações por vez"}, 413)
    try:
        n = banco.gravar_ops(sistema, ops)
        return banco.resposta(func, {"ok": True, "recebidos": n})
    except Exception as e:  # noqa: BLE001
        logging.exception("erro em /sync")
        return banco.resposta(func, {"erro": f"{type(e).__name__}: {e}"}, 500)
