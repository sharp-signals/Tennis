"""
Publica o relatório completo do dia no Telegra.ph.

Telegra.ph não exige conta prévia: cria-se uma "conta anónima" na primeira
vez (grátis, sem email) e guarda-se o access_token como secret do GitHub
para reutilizar nas próximas execuções. Se o secret não existir, o script
cria uma conta nova a cada run — funciona à mesma, só não agrupa as páginas
sob a mesma conta.
"""

from __future__ import annotations

import os

import requests

TELEGRAPH_API = "https://api.telegra.ph"
REQUEST_TIMEOUT = 20


def _get_or_create_access_token() -> str:
    token = os.environ.get("TELEGRAPH_ACCESS_TOKEN", "")
    if token:
        return token

    resp = requests.post(
        f"{TELEGRAPH_API}/createAccount",
        data={"short_name": "TennisPreLiveBot", "author_name": "Tennis Pre-Live Bot"},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    result = resp.json()["result"]
    print(
        "[info] Conta Telegra.ph criada sem token guardado. "
        f"Para reutilizar entre execuções, guarda isto como secret "
        f"TELEGRAPH_ACCESS_TOKEN: {result['access_token']}"
    )
    return result["access_token"]


def _markdown_to_telegraph_nodes(markdown_text: str) -> list[dict]:
    """
    Conversor minimalista: Telegra.ph usa uma lista de nós (Node) em vez de
    Markdown puro. Isto trata só o essencial (parágrafos e cabeçalhos ##);
    para formatação mais rica, considera trocar por uma lib como
    `telegraph` (pip) que já faz Markdown -> nós.
    """
    nodes = []
    for block in markdown_text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        if block.startswith("## "):
            nodes.append({"tag": "h4", "children": [block[3:]]})
        elif block.startswith("# "):
            nodes.append({"tag": "h3", "children": [block[2:]]})
        else:
            nodes.append({"tag": "p", "children": [block]})
    return nodes


def publish_report(title: str, markdown_text: str) -> str:
    """Devolve o URL da página publicada."""
    access_token = _get_or_create_access_token()
    content = _markdown_to_telegraph_nodes(markdown_text)

    resp = requests.post(
        f"{TELEGRAPH_API}/createPage",
        json={
            "access_token": access_token,
            "title": title,
            "content": content,
            "author_name": "Tennis Pre-Live Bot",
            "return_content": False,
        },
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Falha ao publicar no Telegra.ph: {data}")
    return data["result"]["url"]
