"""
Chama a API da Anthropic para gerar a análise de cada jogo.

Regra de ouro (igual ao bot de futebol): o prompt só contém dados que
efetivamente recolhemos. Quando um bloco de dados é None, dizemos
explicitamente ao modelo "não temos este dado" em vez de omitir o campo
em silêncio — isso evita que o modelo assuma e "invente" com naturalidade.
"""

from __future__ import annotations

import json
import re


def _extract_partial_fields(raw_text: str, match_data: dict) -> dict | None:
    """
    Recuperação parcial de uma resposta JSON cortada/inválida. Extrai os
    campos que vieram completos antes do corte, por regex tolerante. Só
    devolve algo se conseguir pelo menos flag+summary ou key_points úteis;
    caso contrário None (cai no fallback total). Nunca inventa conteúdo —
    só recupera o que o modelo escreveu.
    """
    if not raw_text or not raw_text.strip():
        return None

    def _find_str(field):
        m = re.search(rf'"{field}"\s*:\s*"((?:[^"\\]|\\.)*)"', raw_text)
        return m.group(1).replace('\\"', '"').replace('\\n', ' ') if m else None

    def _find_int(field):
        m = re.search(rf'"{field}"\s*:\s*(\d+)', raw_text)
        return int(m.group(1)) if m else None

    def _find_str_list(field):
        # captura o array [...] do campo e extrai as strings de topo
        m = re.search(rf'"{field}"\s*:\s*\[(.*?)(?:\]|$)', raw_text, re.DOTALL)
        if not m:
            return []
        return [s.replace('\\"', '"').replace('\\n', ' ')
                for s in re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))]

    flag = _find_str("flag")
    summary = _find_str("summary_line")
    key_points = _find_str_list("key_points")
    verdict = _find_str("verdict")
    strength = _find_int("signal_strength")

    # discrepâncias: extrair objetos {weight, text} que estejam completos
    discrepancies = []
    disc_block = re.search(r'"discrepancies"\s*:\s*\[(.*?)(?:\]|$)', raw_text, re.DOTALL)
    if disc_block:
        for obj in re.finditer(r'\{\s*"weight"\s*:\s*"([^"]*)"\s*,\s*"text"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}', disc_block.group(1)):
            discrepancies.append({"weight": obj.group(1), "text": obj.group(2).replace('\\"', '"')})

    # só vale a pena se recuperámos conteúdo analítico real
    if not (key_points or discrepancies or verdict):
        return None

    return {
        "flag": flag or FLAG_UNCERTAIN,
        "signal_strength": strength if strength is not None else 30,
        "confidence_reason": "Análise recuperada parcialmente (resposta cortada).",
        "summary_line": summary or f"{match_data.get('player_a','?')} vs {match_data.get('player_b','?')}",
        "key_points": key_points or ["Análise parcialmente recuperada — alguns pontos podem faltar."],
        "discrepancies": discrepancies,
        "risks": [], "markets": [],
        "verdict": verdict or "Veredicto não disponível (resposta cortada) — consultar pontos-chave e dados.",
    }
import hashlib
import os

from json_repair import repair_json

from .config import (
    ANALYSIS_OUTPUT_SCHEMA_VERSION,
    CLAUDE_MODEL,
    FLAG_HIGH_SIGNAL,
    FLAG_ROUTINE,
    FLAG_UNCERTAIN,
    LLM_MODE,
    LLM_POLICY,
)
from .llm_provider import get_llm_provider

# Cache de análises por hash (medida de poupança, 30/07): evita repagar a
# análise de um jogo cujos dados não mudaram (o workflow corre 2x/dia e há
# jogos que aparecem nas duas janelas). Guardada no repositório em
# data/analysis_cache/ para persistir entre execuções.
_ANALYSIS_CACHE_DIR = os.path.join("data", "analysis_cache")
# Versão do prompt: muda esta string sempre que o SYSTEM_PROMPT for alterado
# de forma relevante, para invalidar a cache e forçar reanálise.
PROMPT_VERSION = "2026-08-06-trading-report"


def _payload_hash(llm_data: dict, provider_name: str) -> str:
    """Hash estável de todo o conteúdo efetivamente enviado ao provider.

    A versão anterior omitia fadiga, dados ricos, época e outros campos
    materiais, podendo devolver uma análise desatualizada. A fingerprint
    passa agora a cobrir integralmente o payload LLM e o contrato de saída.
    """
    material = {
        "llm_payload": llm_data,
        "provider": provider_name,
        "llm_mode": LLM_MODE,
        "model": CLAUDE_MODEL,
        "prompt_version": PROMPT_VERSION,
        "output_schema_version": ANALYSIS_OUTPUT_SCHEMA_VERSION,
    }
    blob = json.dumps(material, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

SYSTEM_PROMPT = f"""\
És um analista de ténis pré-jogo. Recebes SÓ dados reais (odds, H2H, forma,
stats por piso, serviço/resposta, ranking, fadiga aproximada, sinal de
lesão baseado em desistências reais, meteorologia p/ jogos ao ar livre).
NUNCA inventes números, lesões ou factos fora dos dados. Campo a `null` =
diz explicitamente que falta (não preenchas com palpite). `weather` null em
indoor não é lacuna (não se aplica).

TRÊS PRINCÍPIOS DE LEITURA (aplicam-se a tudo):
1. AMOSTRA PEQUENA (<~15-20 jogos) = ausência de sinal, não sinal fraco.
   Não a uses para sustentar leitura/discrepância; di-lo insuficiente.
   Nunca compares "50% em 12 jogos" com "66% em 400" como iguais.
2. RECÊNCIA MANDA: quando o presente (forma, ranking ao vivo, jogos na
   época atual) contradiz a carreira, o presente ganha.
3. "SEM DADOS" ≠ "EQUILÍBRIO": falta de H2H/forma é LACUNA (di-lo como
   tal), nunca informação de equilíbrio.
4. HONESTIDADE SOBRE O QUE SABEMOS (crítico): NÃO calculamos probabilidade
   própria nem "edge". O bot sinaliza informação para observação humana,
   não diz "há valor de X%". Por isso:
   - Diz "favorito do MERCADO" (nunca "favorito justo" — não temos preço
     justo próprio).
   - NUNCA compares uma taxa histórica (ex. "46% vs top-20 na carreira")
     com a probabilidade implícita do mercado (ex. "63%") como se fossem
     a mesma medida — não são (uma é histórico agregado não ajustado, a
     outra é a avaliação atual deste jogo). Podes apresentar a taxa
     histórica como CONTEXTO, dizendo explicitamente que não é diretamente
     comparável com a odd.
   - Uma estatística histórica pode SUGERIR algo a observar, mas não PROVA
     que o mercado está errado. Não concluas subavaliação/sobreavaliação a
     partir de dados históricos não ajustados.
5. CARREIRA vs ATUAL: dados de carreira (cenários, estilo, vs-rank, piso)
   misturam fases diferentes (início, auge, pausas, regresso). Para
   jogadores com carreira longa, marca-os como "carreira — relevância
   temporal limitada para o estado atual" quando não houver o recorte
   recente. Não os trates como retrato do momento presente.

CAMPOS E COMO USÁ-LOS:
- `features`: SINAIS JÁ CALCULADOS pelo bot (usa-os como BASE, não refaças as
  contas). Cada um diz quem LIDERA e a magnitude:
  * `ranking`, `forma_recente`, `epoca_atual`, `piso`, `servico`: cada um tem
    `lider`, `diff` (magnitude), `valor_a`/`valor_b` e `amostra_a`/`amostra_b`
    quando aplicável. Aplica o Princípio 1 (amostra pequena = sinal fraco).
  * `frescura`: quem está `mais_fresco` (menos jogos/sets nos últimos 7 dias).
  * `h2h`: quem `lidera` o confronto direto e o registo.
  Nota: vários apontam no mesmo sentido (ranking+forma+época+piso) por serem
  correlacionados — trata-os como UMA "força geral", não provas independentes.
- `h2h`: `overall` (carreira) e `on_surface` (só este piso, pode ser null).
  Destaca quando divergem (sinal interessante). O `features.h2h` já resume quem lidera.
- `h2h_rich_stats` (só WTA, fonte matchstat): serviço/resposta, BP, sets
  decisivos, tiebreaks ESPECÍFICOS do confronto, em `player1Stats`/
  `player2Stats` (cruza `id` com `ranking_a/b`). null p/ ATP.
- `injury_signal_*`: desistências/walkovers reais recentes — facto, não
  diagnóstico. Lista vazia = não encontrámos, não "está saudável".
- `fatigue_signal_*`: se `fatigue_source: "api_recent"`, os dados são
  FIÁVEIS e incluem os jogos do torneio em curso: `days_since_last_match`
  (real), `matches_this_tournament` (jogos já disputados nesta semana —
  CARGA acumulada, o sinal mais importante em fases finais),
  `matches_last_3/7/14d`, `sets_last_7d`. Um jogador com muitos jogos/sets
  nos últimos dias pode estar desgastado; poucos dias de descanso após um
  jogo longo é sinal de fadiga. Se NÃO tiver `fatigue_source` (veio do
  histórico), trata `days_since_last_match` como APROXIMAÇÃO grosseira
  (pode estar desatualizado, ignora se parecer absurdo — ex. "25 dias"
  para quem está em fase final).
- `rich_stats_*` (pode ser null): dados ricos da matchstat (carreira).
  * `response_stats`: resposta (pontos de resposta ganhos %, break points
    convertidos %).
  * `vs_rank_level`: desempenho por nível de ranking do adversário
    (top5/10/50/100). CHAVE para a qualidade do adversário: boa taxa geral
    mas fraca vs top-10 = enche stats com adversários fracos.
  * `by_surface`: desempenho de CARREIRA por piso (hard, clay, hard_indoor,
    grass, carpet), com win_pct e nº de jogos. Mais fiável que a secção de
    piso do histórico (carreira completa, distingue hard indoor/outdoor).
    Usa o piso DESTE jogo para a leitura; grande diferença entre pisos é
    sinal (ex: forte em hard mas fraco em clay num torneio de terra).
  * `by_level`: desempenho por NÍVEL de torneio (grand_slam, masters,
    main_tour), win_pct e nº de jogos. Sinal útil: um jogador pode render
    bem no tour mas mal em Masters/GS (sobe o nível da oposição). Usa o
    nível DESTE torneio; se rende claramente pior neste nível que no geral,
    o favoritismo pode ser mais frágil do que a forma geral sugere.
  * `scenarios`: cenários de jogo em % de carreira — `first_set_win_then_win_pct`
    (ganha 1º set → ganha o JOGO, que pode ser 2-0 OU 2-1),
    `first_set_lose_then_win_pct` (recupera de 1º set perdido),
    `deciding_set_win_pct`, `tiebreak_win_pct` (+ contagens `_count` para a
    amostra). CUIDADO COM O RACIOCÍNIO: "fecha X% após ganhar o 1º set"
    significa ganhar o JOGO, NÃO ganhar 2-0 (parte dessas vitórias foi
    2-1). Por isso, o mercado correto é "vence o jogo" / "handicap de sets
    +1.5" / "observar ao vivo se ganhar o 1º set", e NUNCA "vence 2-0"
    (para 2-0 precisarias de dados de sets sem resposta, que não temos).
    Da mesma forma, quem recupera pouco de 1º set perdido → se perde o 1º
    set, o jogo tende a ficar mais decidido do que a odd ao vivo sugere.
  * `style`: `net_success_pct` (sucesso na rede), `avg_time` (duração média),
    `winners`/`unforced_errors` (agressividade), `aces`/`double_faults`.
    Usa para caracterizar ESTILO (agressivo vs consistente) e ligar a
    mercados (ex. jogo longo/curto, total de games).
  * `domination`: compara o jogador com os ADVERSÁRIOS dele (own_ vs opp_):
    `own_first_serve_won_pct`/`opp_first_serve_won_pct` (quem serve melhor),
    `own_winners`/`opp_winners` (quem ataca mais), `own_unforced_errors`/
    `opp_unforced_errors` (quem erra mais). Se ganha com muitos winners
    próprios → domina; se ganha sobretudo porque os adversários erram muito
    (opp_unforced_errors alto) → vitória mais frágil contra quem erra pouco.
  Usa TODOS estes nos pontos-chave e discrepâncias quando forem relevantes
  e tiverem amostra suficiente (aplica o Princípio 1 — amostra pequena não
  sustenta leitura).

AVISO FADIGA DESATUALIZADA: se `fatigue_data_maybe_stale: true` (último
jogo conhecido há +20 dias), o histórico provavelmente NÃO tem os jogos
recentes deste torneio (a fonte tem atraso). NÃO afirmes "há X dias sem
jogar" nem "sem ritmo" — seria falso (pode ter jogado e vencido há 1-2
dias). Diz que o histórico pode não refletir os jogos recentes, e não uses
a fadiga contra ele. Quem está em ronda avançada já jogou esta semana.

AVISO FIM DE CARREIRA: stats de carreira (piso, set decisivo, serviço)
acumulam TODA a carreira e podem descrever quem o jogador já não é. Ex-top
com ranking agora baixo + forma fraca + poucos jogos na época = as suas
stats de carreira refletem o AUGE, não o presente (amostra grande aqui =
engano, não fiabilidade). Inverso: jovem em ascensão com amostra pequena
pode ter nível real superior. Quando presente (forma/ranking/época atual)
contradiz a carreira, dá muito mais peso ao presente. Se o mercado
favorece o jogador com pior carreira mas melhor momento, isso NÃO é
divergência — o mercado pode estar a ler bem o presente. Não sinalizes
discrepância a favor do jogador em declínio só porque a carreira parece
melhor no papel.

LIMITAÇÃO CHALLENGER/ITF: a fonte só tem ATP principal, não Challenger/ITF.
Jogador com ranking baixo (fora do top ~150) pode jogar nesses níveis sem
aparecer — um "hiato" longo (4-5+ meses) + ranking alto pode ser só falta
de cobertura, não inatividade. Assinala como transparência, não diagnóstico.

FORMATO DE SAÍDA — objeto JSON, APENAS a leitura de mercado de alto nível. Os
factos (ranking, forma, piso, H2H, serviço), o Market Overview (interesse de
cada mercado) e os fatores decisivos são gerados AUTOMATICAMENTE pelo sistema e
já aparecem no relatório. NÃO os repitas. Tu escreves só DOIS textos de
interpretação. A tua pergunta: "onde há (ou não) valor face às odds?".

⚠️ REGRAS (obrigatórias — respostas longas são cortadas e perdem-se):
- Sê TELEGRÁFICO. Respeita os limites de caracteres.
- NUNCA cites números de ranking/forma/época (ex: "#72 vs #218", "60% vs 30%").
  Já estão no relatório. Escreve CONCLUSÕES de mercado, não factos.
- NÃO expliques o teu raciocínio nem comentes as features.
- Linguagem de OBSERVAÇÃO: "favorito do mercado" (não "justo"), "possível valor
  a acompanhar" (nunca "há valor" ou "apostar"/"recomendo").

Campos (todos obrigatórios):
- "flag": "{FLAG_HIGH_SIGNAL}" (divergência forte face ao mercado),
  "{FLAG_UNCERTAIN}" (equilibrado/dados insuficientes) ou "{FLAG_ROUTINE}"
  (mercado alinhado, sem sinal).
- "signal_strength": inteiro 0-100 (força da evidência de divergência; juízo).
- "executive_summary": 2-4 frases (MÁX 350 caracteres). Visão geral: o mercado
  está ajustado? há divergência? onde está o maior interesse? Linguagem de trader.
- "verdict": a conclusão final de mercado (MÁX 400 caracteres, ≈4 frases). Onde
  está (ou não) o valor, pré-live ou ao vivo. Se o mercado está alinhado, di-lo.
  Padrões a considerar quando se aplicam: recuperação de 1º set → entrada ao
  vivo; ambos fortes em set decisivo → "vai a set decisivo"; favorito ganha por
  erro alheio → valor no underdog; um muito mais fresco → "over games".

Responde APENAS com o JSON, sem texto antes/depois, sem blocos de código.
"""



_SELECTIVE_FEATURE_LABELS = {
    "ranking": "ranking",
    "forma_recente": "forma recente",
    "epoca_atual": "época atual",
    "piso": "desempenho no piso",
    "servico": "serviço",
    "frescura": "frescura física",
    "h2h": "confronto direto",
}


def _selective_number(value):
    """Converte um valor numérico sem lançar exceções."""
    if isinstance(value, bool):
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _collect_selective_signals(features: object) -> list[dict]:
    """
    Extrai apenas sinais materialmente relevantes para decidir se vale a pena
    pagar uma interpretação LLM.

    Os limiares são intencionalmente conservadores: diferenças pequenas ou
    amostras frágeis não justificam uma chamada paga.
    """
    if not isinstance(features, dict):
        return []

    signals: list[dict] = []

    # nome -> (diferença mínima, amostra mínima por jogador)
    thresholds = {
        "ranking": (25.0, 0),
        "forma_recente": (15.0, 5),
        "epoca_atual": (10.0, 10),
        "piso": (10.0, 10),
        "servico": (5.0, 0),
    }

    for name, (minimum_diff, minimum_sample) in thresholds.items():
        feature = features.get(name)
        if not isinstance(feature, dict):
            continue

        leader = feature.get("lider")
        if not leader or leader == "igual":
            continue

        diff = _selective_number(feature.get("diff"))
        if diff is None or diff < minimum_diff:
            continue

        if minimum_sample:
            sample_a = _selective_number(feature.get("amostra_a"))
            sample_b = _selective_number(feature.get("amostra_b"))

            # Sem amostra verificável, o sinal não deve provocar despesa.
            if (
                sample_a is None
                or sample_b is None
                or min(sample_a, sample_b) < minimum_sample
            ):
                continue

        signals.append(
            {
                "name": name,
                "label": _SELECTIVE_FEATURE_LABELS[name],
                "leader": leader,
                "magnitude": diff,
            }
        )

    # Frescura: dois jogos ou quatro sets de diferença na última semana.
    freshness = features.get("frescura")
    if isinstance(freshness, dict):
        leader = freshness.get("mais_fresco")

        games_a = _selective_number(freshness.get("jogos_7d_a"))
        games_b = _selective_number(freshness.get("jogos_7d_b"))
        sets_a = _selective_number(freshness.get("sets_7d_a"))
        sets_b = _selective_number(freshness.get("sets_7d_b"))

        games_diff = (
            abs(games_a - games_b)
            if games_a is not None and games_b is not None
            else 0.0
        )
        sets_diff = (
            abs(sets_a - sets_b)
            if sets_a is not None and sets_b is not None
            else 0.0
        )

        if leader and leader != "igual" and (games_diff >= 2 or sets_diff >= 4):
            signals.append(
                {
                    "name": "frescura",
                    "label": _SELECTIVE_FEATURE_LABELS["frescura"],
                    "leader": leader,
                    "magnitude": max(games_diff, sets_diff),
                }
            )

    # H2H: pelo menos três confrontos e vantagem mínima de duas vitórias.
    h2h = features.get("h2h")
    if isinstance(h2h, dict):
        leader = h2h.get("lider")
        wins_a = _selective_number(h2h.get("a_wins")) or 0.0
        wins_b = _selective_number(h2h.get("b_wins")) or 0.0
        total = _selective_number(h2h.get("total")) or 0.0

        if (
            leader
            and leader != "igual"
            and total >= 3
            and abs(wins_a - wins_b) >= 2
        ):
            signals.append(
                {
                    "name": "h2h",
                    "label": _SELECTIVE_FEATURE_LABELS["h2h"],
                    "leader": leader,
                    "magnitude": abs(wins_a - wins_b),
                }
            )

    return signals


def _evaluate_selective_policy(
    features: object,
    match_data: dict,
) -> tuple[bool, str, list[dict]]:
    """
    Decide se a interpretação paga acrescenta valor.

    A LLM é reservada para divergências materiais. Quando os sinais estão
    alinhados, Python já consegue produzir uma leitura factual suficiente.
    """
    signals = _collect_selective_signals(features)

    if not signals:
        return (
            False,
            "sem sinais materiais com amostra suficiente",
            signals,
        )

    leaders = {
        str(signal["leader"])
        for signal in signals
        if signal.get("leader") and signal.get("leader") != "igual"
    }

    if len(leaders) >= 2:
        dimensions = ", ".join(signal["label"] for signal in signals)
        return (
            True,
            f"divergência material entre dimensões: {dimensions}",
            signals,
        )

    return (
        False,
        "sinais materiais alinhados; síntese determinística suficiente",
        signals,
    )


def _build_selective_result(
    match_data: dict,
    signals: list[dict],
    reason: str,
) -> dict:
    """Produz o contrato normal do relatório sem recorrer a uma LLM."""
    player_a = str(match_data.get("player_a") or "Jogador A")
    player_b = str(match_data.get("player_b") or "Jogador B")

    if not signals:
        return {
            "flag": FLAG_UNCERTAIN,
            "signal_strength": 15,
            "confidence_reason": (
                "Dados comparativos insuficientes para uma leitura robusta."
            ),
            "summary_line": (
                f"{player_a} vs {player_b} — não existem sinais comparativos "
                "materiais suficientes."
            ),
            "key_points": [
                "Os dados disponíveis não permitem distinguir uma vantagem robusta.",
                "A leitura deve permanecer prudente até existirem melhores amostras.",
            ],
            "discrepancies": [],
            "risks": [
                "A ausência de dados pode ocultar diferenças relevantes entre os jogadores."
            ],
            "markets": [],
            "verdict": (
                "Leitura inconclusiva: não existe base factual suficiente "
                "para uma interpretação adicional."
            ),
        }

    counts: dict[str, int] = {}
    for signal in signals:
        leader = str(signal["leader"])
        counts[leader] = counts.get(leader, 0) + 1

    dominant = max(counts, key=counts.get)
    strength = min(70, 30 + 10 * len(signals))

    key_points = [
        f"{signal['label'].capitalize()}: vantagem de {signal['leader']}."
        for signal in signals[:4]
    ]

    if len(key_points) == 1:
        key_points.append(
            "As restantes dimensões não apresentam divergências materiais."
        )

    return {
        "flag": FLAG_ROUTINE,
        "signal_strength": strength,
        "confidence_reason": (
            "Sinais materiais alinhados; síntese determinística suficiente."
        ),
        "summary_line": (
            f"{player_a} vs {player_b} — os indicadores materiais disponíveis "
            f"estão alinhados a favor de {dominant}."
        ),
        "key_points": key_points,
        "discrepancies": [],
        "risks": [
            "A síntese automática não incorpora contexto qualitativo não presente nos dados."
        ],
        "markets": [],
        "verdict": (
            f"Leitura de rotina favorável a {dominant}; não foram encontradas "
            "divergências materiais entre os principais indicadores."
        ),
    }


def analyze_match(match_data: dict) -> dict:
    """
    match_data deve conter: player_a, player_b, tournament, surface, round,
    commence_time, odds (dict ou None), h2h (dict ou None),
    form_a / form_b (dict ou None), surface_stats_a / surface_stats_b (dict
    ou None), fatigue_a / fatigue_b (dict ou None).
    """
    # Poupança de input (Frentes 4/5): o payload que vai ao Claude é enxugado.
    # As `features` (pré-calculadas pelo bot) já resumem ranking/forma/época/
    # piso/serviço/fadiga/h2h em comparações prontas — por isso removemos os
    # campos BRUTOS correspondentes do que enviamos ao Claude (ele usa as
    # features). Também removemos duplicados e campos-nicho pouco usados na
    # leitura. O payload COMPLETO continua a ir para o report_html (que monta
    # as secções visuais), por isso não se perde nada no relatório.
    _REDUNDANT_FOR_LLM = (
        # duplicados (já em rich_stats.scenarios)
        "set1_comeback_stats_a", "set1_comeback_stats_b",
        "deciding_set_stats_a", "deciding_set_stats_b",
        # brutos já resumidos nas features (quem lidera + magnitude + amostra)
        "recent_form_a", "recent_form_b",
        "current_season_a", "current_season_b",
        "surface_stats_a", "surface_stats_b",
        "serve_return_stats_a", "serve_return_stats_b",
        # nicho (raramente muda a leitura de mercado)
        "handedness_matchup_a", "handedness_matchup_b",
        "layoff_return_stats_a", "layoff_return_stats_b",
        "round_stage_stats_a", "round_stage_stats_b",
    )
    llm_data = {k: v for k, v in match_data.items() if k not in _REDUNDANT_FOR_LLM}
    provider = get_llm_provider()

    # Enxugar ainda mais os rich_stats que vão ao Claude: manter só os
    # `scenarios` (recuperação de 1º set, set decisivo, tiebreak — que o Claude
    # USA para os padrões de trading ao vivo). O resto (style, domination,
    # by_surface, by_level, vs_rank_level) é factual que o Python já mostra no
    # relatório e já está resumido em `features` — não precisa de ir ao Claude.
    for _k in ("rich_stats_a", "rich_stats_b"):
        rs = llm_data.get(_k)
        if isinstance(rs, dict):
            scen = rs.get("scenarios")
            llm_data[_k] = {"scenarios": scen} if scen else None

    user_prompt = (
        "Dados do jogo (JSON). O campo 'features' traz sinais JÁ CALCULADOS "
        "(quem lidera cada dimensão e a magnitude) — usa-os como base. Campos "
        "a null significam que a fonte não tinha esse dado:\n\n"
        + json.dumps(llm_data, ensure_ascii=False, indent=2, default=str)
    )

    # Cache por hash: se já analisámos este jogo com estes mesmos dados
    # materiais (e o mesmo prompt/modelo), reutilizamos — não repagamos.
    cache_key = _payload_hash(llm_data, provider.name)
    cache_path = os.path.join(_ANALYSIS_CACHE_DIR, f"{cache_key}.json")
    try:
        if provider.persist_cache and os.path.exists(cache_path):
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            print(f"[cache_hit] {match_data.get('player_a','?')} vs {match_data.get('player_b','?')} — análise reutilizada (sem custo).")
            return cached
    except Exception:
        pass  # se a cache falhar, segue para a chamada normal


    llm_call_reason = f"política {LLM_POLICY}"

    if LLM_POLICY == "selective":
        should_call_llm, llm_call_reason, selective_signals = (
            _evaluate_selective_policy(
                llm_data.get("features"),
                match_data,
            )
        )

        if not should_call_llm:
            print(
                f"[llm_skipped:selective] "
                f"{match_data.get('player_a', '?')} vs "
                f"{match_data.get('player_b', '?')} | "
                f"{llm_call_reason}"
            )
            return _build_selective_result(
                match_data,
                selective_signals,
                llm_call_reason,
            )

    print(
        f"[llm_call:{provider.name}] "
        f"{match_data.get('player_a', '?')} vs "
        f"{match_data.get('player_b', '?')} | "
        f"{llm_call_reason}"
    )

    provider_response = provider.generate(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        # Teto de output: 1500. O novo formato pede só 2 textos curtos
        # (executive_summary ≤350 chars + verdict ≤400 chars) + flag/signal —
        # o output legítimo ronda os ~400-600 tokens. 1500 dá margem larga
        # sem cortar, e trava qualquer divagação. A poupança real vem de o
        # Claude escrever MENOS (2 campos, não 6), não só do teto.
        max_tokens=1500,
        metadata=match_data,
    )
    # Logging de custo real, normalizado entre providers.
    try:
        usage = provider_response.usage
        if usage:
            print(
                f"[llm_usage:{provider.name}] {match_data.get('player_a','?')} vs {match_data.get('player_b','?')} | "
                f"input={usage.get('input_tokens', 0)} output={usage.get('output_tokens', 0)} "
                f"cache_read={usage.get('cache_read_input_tokens', 0)} "
                f"cache_creation={usage.get('cache_creation_input_tokens', 0)}"
            )
    except Exception:
        pass
    raw_text = provider_response.text.strip()

    if provider_response.stop_reason == "max_tokens":
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

    def _save_and_return(res: dict) -> dict:
        """Grava o resultado na cache persistente apenas quando aplicável.
        Aplica limites por código aos textos do Claude (garante output curto)."""
        def _cut(s, n):
            s = str(s or "")
            return s if len(s) <= n else s[:n].rstrip() + "…"
        if res.get("executive_summary"):
            res["executive_summary"] = _cut(res["executive_summary"], 350)
        if res.get("verdict"):
            res["verdict"] = _cut(res["verdict"], 400)
        if provider.persist_cache:
            try:
                os.makedirs(_ANALYSIS_CACHE_DIR, exist_ok=True)
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(res, f, ensure_ascii=False)
            except Exception:
                pass
        return res
    try:
        # strict=False: tolera caracteres de controlo literais (ex: quebras
        # de linha não escapadas) dentro de strings do JSON — já vimos o
        # Claude fazer isto ocasionalmente num relatório longo, apesar da
        # instrução para não o fazer. Mais barato do que rejeitar a resposta.
        return _save_and_return(json.loads(raw_text, strict=False))
    except json.JSONDecodeError as exc:
        print(f"[aviso] resposta do Claude não era JSON válido: {exc}")
        print("[info] a tentar reparar automaticamente com json_repair...")
        try:
            repaired = repair_json(raw_text)
            result = json.loads(repaired, strict=False)
            print("[info] reparação de JSON bem-sucedida — a análise não foi perdida.")
            return _save_and_return(result)
        except Exception as repair_exc:
            print(f"[aviso] reparação de JSON também falhou: {repair_exc}")

        # Recuperação PARCIAL: mesmo com JSON partido (resposta cortada),
        # tentar extrair os campos que vieram completos antes do corte.
        # Assim, se key_points/discrepancies vieram inteiros mas o verdict
        # cortou, aproveitamos o que há em vez de perder tudo.
        partial = _extract_partial_fields(raw_text, match_data)
        if partial:
            print("[info] recuperação parcial: aproveitados campos que vieram completos antes do corte.")
            return _save_and_return(partial)

        # Fallback defensivo total: só quando nem sequer há campos parciais.
        print(f"[aviso] resposta bruta (primeiros 500 chars): {raw_text[:500]}")
        return {
            "flag": FLAG_UNCERTAIN,
            "signal_strength": 0,
            "confidence_reason": "Erro ao gerar a análise — sem base para avaliar.",
            "summary_line": (
                f"{match_data.get('player_a', '?')} vs {match_data.get('player_b', '?')}: "
                "erro ao gerar análise (resposta do modelo não era JSON válido)."
            ),
            "key_points": ["Não foi possível gerar a análise devido a um erro de formato na resposta do modelo. As secções de dados abaixo continuam válidas."],
            "discrepancies": [],
            "risks": [], "markets": [],
            "verdict": "Análise indisponível nesta execução — consultar os dados factuais acima.",
        }
