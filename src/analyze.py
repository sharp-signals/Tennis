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
gratuitas: odds de mercado, histórico de confrontos, forma recente, stats por
piso, stats de serviço/resposta, ranking, sinal aproximado de fadiga, sinal
de lesão/retirement (baseado em desistências reais em jogos passados — não é
um relatório médico oficial), e meteorologia prevista para jogos ao ar livre.
Nunca inventas números, lesões, ou factos que não estejam nos dados
fornecidos.

Quando um campo de dados vier a `null`, diz isso explicitamente na tua
análise em vez de ignorares a lacuna ou preenchê-la com um palpite. O campo
`weather` vem sempre `null` para jogos indoor (não é uma lacuna, é porque
não se aplica) — só trata como "dado em falta" se o jogo for ao ar livre e
mesmo assim vier vazio.

O campo `h2h` tem sempre dois níveis, quando há dados: `overall` (H2H de
carreira completa) e `on_surface` (H2H só neste piso — pode vir `null`
mesmo quando `overall` existe, se nunca se defrontaram neste piso
específico). Comenta sempre os dois quando disponíveis, e destaca
especialmente quando divergem (ex: equilibrados na carreira toda, mas um
domina claramente neste piso, ou vice-versa) — essa divergência é
frequentemente o sinal mais interessante do H2H.

O sinal de lesão (`injury_signal_*`) é baseado em desistências/walkovers
reais nos últimos jogos do próprio histórico consultado — trata isso como
um facto verificável ("desistiu do último jogo, motivo desconhecido"), não
como um diagnóstico. Uma lista vazia de `recent_retirements` significa que
não encontrámos desistências recentes, não que o jogador esteja de certeza
saudável.

Para cada jogo, devolve um objeto JSON com exatamente estes campos:
- "flag": um de "{FLAG_HIGH_SIGNAL}", "{FLAG_UNCERTAIN}", "{FLAG_ROUTINE}"
  ({FLAG_HIGH_SIGNAL} = algo digno de nota / divergência forte vs mercado /
   fadiga clara; {FLAG_UNCERTAIN} = jogo equilibrado ou dados insuficientes
   para concluir; {FLAG_ROUTINE} = sem sinais especiais)
- "summary_line": uma frase curta (máx. ~140 caracteres) para o resumo do
  Telegram, em português
- "full_report_markdown": análise completa em Markdown, otimizada para
  leitura rápida (não um texto corrido). Estrutura obrigatória:
  1. Começa SEMPRE com "## 🔑 Pontos-chave" seguido de 3-5 bullets curtos
     (uma linha cada) com os sinais mais importantes deste jogo — é a
     parte que a maioria das pessoas vai mesmo ler.
  2. Depois, uma secção por tipo de dado (H2H, Forma Recente, Piso,
     Serviço/Resposta, Fadiga, Lesão, Meteorologia, Mercado), cada uma
     com "### " como cabeçalho.
  3. Dentro de cada secção, usa bullets (não parágrafos densos) e põe em
     **negrito** os números/factos mais importantes (ex: "Alcaraz lidera
     **7-3** em piso duro").
  4. Termina com "### 📝 Nota Final" com 1-2 frases sobre o que falta ou
     as maiores incertezas, se aplicável.
  Nunca inventes números — todas as regras acima sobre dados em falta
  continuam a aplicar-se dentro deste formato.

O campo `fatigue_signal_*` agora tem vários indicadores: `days_since_last_match`,
`matches_last_3d`/`_7d`/`_14d`, `minutes_played_last_7d`, `sets_played_last_7d`.
Usa o conjunto para avaliar fadiga (ex: poucos dias de descanso + muitos
sets/minutos recentes = sinal de fadiga real; campos individuais podem
vir `null` se a fonte não tiver essa coluna, mas os outros continuam
válidos).

Os campos `surface_stats_a`/`surface_stats_b` trazem o perfil do jogador
nos TRÊS pisos (Hard/Clay/Grass), não só no piso deste jogo — usa isto
para comentar especialização (ex: muito mais forte em terra do que em
relva) e não só o desempenho no piso da partida atual. Cada piso pode
vir `null` individualmente se o jogador não tiver jogos registados nesse
piso especificamente.

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
        # 6000 (era 4000, era 1500 antes disso): cada vez que acrescentamos
        # mais dados (ex: fadiga rica), o relatório completo fica mais
        # longo. Margem generosa para não voltarmos a cortar o JSON a meio.
        max_tokens=6000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw_text = "".join(block.text for block in response.content if block.type == "text").strip()

    if response.stop_reason == "max_tokens":
        print(
            "[aviso] a resposta do Claude foi CORTADA por limite de tokens "
            f"(stop_reason=max_tokens) — considera aumentar max_tokens ainda mais, "
            f"ou pedir um relatório mais conciso no prompt."
        )

    # Blindagem: se o modelo, apesar da instrução, envolver a resposta em
    # blocos de código markdown (```json ... ```), removemos antes de tentar
    # o parse — mais barato do que gastar uma chamada extra à API.
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1] if "\n" in raw_text else raw_text
        if raw_text.endswith("```"):
            raw_text = raw_text.rsplit("```", 1)[0]
        raw_text = raw_text.strip()

    try:
        # strict=False: tolera caracteres de controlo literais (ex: quebras
        # de linha não escapadas) dentro de strings do JSON — já vimos o
        # Claude fazer isto ocasionalmente num relatório longo, apesar da
        # instrução para não o fazer. Mais barato do que rejeitar a resposta.
        return json.loads(raw_text, strict=False)
    except json.JSONDecodeError as exc:
        # Fallback defensivo: nunca deixar o pipeline abaixo sem estrutura,
        # mas sinalizamos claramente que houve um problema de formato —
        # não inventamos uma análise. Inclui o motivo exato no log (não na
        # mensagem enviada) para facilitar diagnóstico.
        print(f"[aviso] resposta do Claude não era JSON válido: {exc}")
        print(f"[aviso] resposta bruta (primeiros 500 chars): {raw_text[:500]}")
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
