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
        agora = banco.agora_iso()
        regs = banco.buscar_mudancas(sistema, req.params.get("desde", ""))
        return banco.resposta(func, {"agora": agora, "registros": regs})
    except Exception as e:  # noqa: BLE001
        logging.exception("erro em /mudancas")
        return banco.resposta(func, {"erro": f"{type(e).__name__}: {e}"}, 500)
