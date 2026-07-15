"""
Chama a API da Anthropic para gerar a análise de cada jogo.

Regra de ouro (igual ao bot de futebol): o prompt só contém dados que
efetivamente recolhemos. Quando um bloco de dados é None, dizemos
explicitamente ao modelo "não temos este dado" em vez de omitir o campo
em silêncio — isso evita que o modelo assuma e "invente" com naturalidade.
"""

from __future__ import annotations

import json
import os

import anthropic

from .config import CLAUDE_MODEL, FLAG_HIGH_SIGNAL, FLAG_UNCERTAIN, FLAG_ROUTINE

_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

SYSTEM_PROMPT = f"""\
És um analista de ténis pré-jogo. Recebes SÓ dados reais recolhidos de fontes
gratuitas (odds de mercado, histórico de confrontos, forma recente, stats por
piso, sinal aproximado de fadiga). Nunca inventas números, lesões, ou factos
que não estejam nos dados fornecidos.

Quando um campo de dados vier marcado como "sem dados", diz isso
explicitamente na tua análise em vez de ignorares a lacuna ou preenchê-la
com um palpite.

Para cada jogo, devolve um objeto JSON com exatamente estes campos:
- "flag": um de "{FLAG_HIGH_SIGNAL}", "{FLAG_UNCERTAIN}", "{FLAG_ROUTINE}"
  ({FLAG_HIGH_SIGNAL} = algo digno de nota / divergência forte vs mercado /
   fadiga clara; {FLAG_UNCERTAIN} = jogo equilibrado ou dados insuficientes
   para concluir; {FLAG_ROUTINE} = sem sinais especiais)
- "summary_line": uma frase curta (máx. ~140 caracteres) para o resumo do
  Telegram, em português
- "full_report_markdown": análise completa em Markdown (H2H, forma, piso,
  fadiga, leitura do mercado, e nota explícita de que dados faltaram, se for
  o caso) — este texto vai para uma página pública no Telegra.ph

Responde APENAS com o JSON, sem texto antes ou depois, sem blocos de código.
"""


def analyze_match(match_data: dict) -> dict:
    """
    match_data deve conter: player_a, player_b, tournament, surface, round,
    commence_time, odds (dict ou None), h2h (dict ou None),
    form_a / form_b (dict ou None), surface_stats_a / surface_stats_b (dict
    ou None), fatigue_a / fatigue_b (dict ou None).
    """
    user_prompt = (
        "Dados do jogo (JSON). Campos a null significam que a fonte não "
        "tinha esse dado disponível:\n\n"
        + json.dumps(match_data, ensure_ascii=False, indent=2, default=str)
    )

    response = _client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw_text = "".join(block.text for block in response.content if block.type == "text")

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        # Fallback defensivo: nunca deixar o pipeline abaixo sem estrutura,
        # mas sinalizamos claramente que houve um problema de formato —
        # não inventamos uma análise.
        return {
            "flag": FLAG_UNCERTAIN,
            "summary_line": (
                f"{match_data.get('player_a', '?')} vs {match_data.get('player_b', '?')}: "
                "erro ao gerar análise (resposta do modelo não era JSON válido)."
            ),
            "full_report_markdown": (
                "Não foi possível gerar a análise completa devido a um erro de "
                "formato na resposta do modelo. Dados brutos recolhidos:\n\n"
                f"```json\n{json.dumps(match_data, ensure_ascii=False, indent=2, default=str)}\n```"
            ),
        }
