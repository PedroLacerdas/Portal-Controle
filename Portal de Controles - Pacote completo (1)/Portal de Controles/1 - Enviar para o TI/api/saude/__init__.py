import os

import azure.functions as func

from shared_code import banco


def main(req: func.HttpRequest) -> func.HttpResponse:
    """Mostra se a API alcança o banco. Não exige login e não mostra dados."""
    info = {"api": "ok", "banco_configurado": bool(os.environ.get("COSMOS_CONEXAO")),
            "token_ponte_configurado": bool(os.environ.get("API_TOKEN"))}
    try:
        banco.conteiner().read()
        info["banco"] = "ok"
    except Exception as e:  # noqa: BLE001
        info["banco"] = f"erro: {type(e).__name__}"
    return banco.resposta(func, info)
