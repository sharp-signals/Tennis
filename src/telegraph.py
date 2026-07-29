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


# Cache em memória do token durante a execução (B2 da auditoria de
# 28/07/2026): com uma página do Telegra.ph POR JOGO, sem esta cache
# criava-se uma conta nova por cada jogo (10 jogos = 10 contas).
_TOKEN_CACHE: dict = {}


def _get_or_create_access_token() -> str:
    if "token" in _TOKEN_CACHE:
        return _TOKEN_CACHE["token"]

    token = os.environ.get("TELEGRAPH_ACCESS_TOKEN", "")
    if token:
        _TOKEN_CACHE["token"] = token
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
        "Para reutilizar entre execuções, guarda o access_token desta conta "
        "como secret TELEGRAPH_ACCESS_TOKEN (não é impresso no log por segurança)."
    )
    _TOKEN_CACHE["token"] = result["access_token"]
    return result["access_token"]


import re


def _parse_inline(text: str) -> list:
    """Converte **negrito** e *itálico* dentro de uma linha em nós do Telegra.ph."""
    pattern = re.compile(r"\*\*(.+?)\*\*|\*(.+?)\*")
    children: list = []
    pos = 0
    for m in pattern.finditer(text):
        if m.start() > pos:
            children.append(text[pos:m.start()])
        if m.group(1) is not None:
            children.append({"tag": "b", "children": [m.group(1)]})
        else:
            children.append({"tag": "i", "children": [m.group(2)]})
        pos = m.end()
    if pos < len(text):
        children.append(text[pos:])
    return children if children else [text]


def _markdown_to_telegraph_nodes(markdown_text: str) -> list[dict]:
    """
    Conversor de Markdown para os nós (Node) que o Telegra.ph espera.
    Suporta: cabeçalhos (#/##/###/####  -> h3/h4, o Telegra.ph só tem
    esses dois níveis), listas com "- "/"* ", **negrito**, *itálico*,
    separadores (---), e parágrafos normais.
    """
    nodes: list[dict] = []
    list_buffer: list[str] = []
    paragraph_buffer: list[str] = []

    def flush_list() -> None:
        if list_buffer:
            nodes.append({
                "tag": "ul",
                "children": [{"tag": "li", "children": _parse_inline(item)} for item in list_buffer],
            })
            list_buffer.clear()

    def flush_paragraph() -> None:
        if paragraph_buffer:
            text = " ".join(paragraph_buffer).strip()
            if text:
                nodes.append({"tag": "p", "children": _parse_inline(text)})
            paragraph_buffer.clear()

    for raw_line in markdown_text.split("\n"):
        line = raw_line.strip()

        if not line:
            flush_list()
            flush_paragraph()
            continue

        if line.startswith("#### ") or line.startswith("### "):
            flush_list(); flush_paragraph()
            text = line.split(" ", 1)[1]
            nodes.append({"tag": "h4", "children": _parse_inline(text)})
        elif line.startswith("## ") or line.startswith("# "):
            flush_list(); flush_paragraph()
            text = line.split(" ", 1)[1]
            nodes.append({"tag": "h3", "children": _parse_inline(text)})
        elif line in ("---", "***", "___"):
            flush_list(); flush_paragraph()
            nodes.append({"tag": "hr"})
        elif line.startswith("- ") or line.startswith("* "):
            flush_paragraph()
            list_buffer.append(line[2:])
        else:
            flush_list()
            paragraph_buffer.append(line)

    flush_list()
    flush_paragraph()
    return nodes


def publish_report(title: str, markdown_text: str) -> str:
    """Devolve o URL da página publicada."""
    access_token = _get_or_create_access_token()
    content = _markdown_to_telegraph_nodes(markdown_text)

    # O Telegra.ph rejeita conteúdo vazio (devolve um erro cuja estrutura
    # não tem 'result', o que rebentava com KeyError mais abaixo). Se a
    # conversão não produziu nós, metemos um parágrafo mínimo.
    if not content:
        content = [{"tag": "p", "children": [title]}]

    resp = requests.post(
        f"{TELEGRAPH_API}/createPage",
        json={
            "access_token": access_token,
            "title": title[:256],  # o Telegra.ph limita o título a 256 chars
            "content": content,
            "author_name": "Tennis Pre-Live Bot",
            "return_content": False,
        },
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        # Erro da API (ex: CONTENT_TEXT_REQUIRED, TITLE_TOO_LONG). Damos a
        # mensagem real do Telegra.ph, em vez de deixar um KeyError opaco.
        raise RuntimeError(f"Telegra.ph recusou a página: {data.get('error', data)}")
    result = data.get("result")
    if not result or "url" not in result:
        raise RuntimeError(f"Telegra.ph respondeu sem URL: {data}")
    return result["url"]
