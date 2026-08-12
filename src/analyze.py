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
PROMPT_VERSION = "2026-08-07-motor-divergencia-v3"


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
- Sê TELEGRÁFICO. Respeita os limites de caracteres — à LETRA, não os
  ultrapasses "um bocadinho". Excesso é sempre cortado e desperdiça tokens.
- Responde IMEDIATAMENTE com o objeto JSON. SEM introdução, SEM explicação
  antes ou depois, SEM revisares/repetires o texto duas vezes.
- APENAS os 4 campos pedidos abaixo. Nenhum campo extra, nenhum comentário
  fora do JSON.
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
- "executive_summary": UMA a DUAS frases, MÁX 200 caracteres. Interpreta a
  leitura já calculada pelo Python (recebes a classificação do motor e os
  fatores). NÃO repitas números de forma/ranking/H2H — já estão nas tabelas.
  NÃO recalcules nem contradigas o motor. Formato:
  "<classificação do motor> a favor de <favorecido>. <2-3 fatores> são os
  principais; mercado mantém <favorito do mercado>." Ou, se eficiente:
  "Mercado eficiente. Sem divergência relevante entre mercado e indicadores."
- "verdict": UMA a DUAS frases, MÁX 200 caracteres, COERENTE com o motor.
  Diz o lado favorecido pelos indicadores e que Moneyline acompanhar (só
  Moneyline — é o único mercado com odds). PROIBIDO: "apostar", "entrar",
  "há valor", "boa entrada", "zona de entrada", "stake", "odd de entrada".
  Usa só "acompanhar"/"monitorizar". "Sinal" significa merece atenção, NÃO
  apostar. Ex: "Bencic é o lado favorecido pelos indicadores, com divergência
  moderada face ao mercado. Acompanhar Moneyline Bencic."

LINGUAGEM (obrigatório): frases curtas e diretas. PROIBIDO narrativo como
"tem vindo a demonstrar", "ao longo da temporada", "é conhecido por". Vai
direto ao mercado.

Responde APENAS com o JSON, sem texto antes/depois, sem blocos de código.
Começa a resposta diretamente por "{{" — primeiro caráter, sem preâmbulo.
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
    Decide se a interpretação paga (Claude) acrescenta valor.

    NOVA LÓGICA (auditoria P0 #2): o gatilho é o MOTOR DE DIVERGÊNCIA, não os
    líderes dos sinais. O Claude é chamado quando o motor deteta divergência
    RELEVANTE contra o mercado (nível >=2) — que são os jogos economicamente
    interessantes. Antes decidíamos pelos líderes dos sinais, o que ignorava o
    motor e podia saltar precisamente o jogo mais interessante (todos os sinais
    num jogador, mercado forte no outro = 1 só líder -> não chamava, quando é
    uma divergência forte).
    """
    signals = _collect_selective_signals(features)

    # 1. Ler a classificação do motor (já calculada pelo main e posta no payload)
    div = match_data.get("divergencia") or {}
    clf = div.get("classificacao") or {}
    nivel = clf.get("nivel")

    # NOTA (correção): o payload["divergencia"] guardado pelo main.py é o
    # dict CRU de _calcular_divergencia (prob_mercado_a/b), NÃO o formato
    # normalizado do report_html (que tem "market"). Verificar "market" aqui
    # fazia esta condição falhar SEMPRE, mesmo com odds reais — o Claude
    # nunca era chamado e o relatório caía sempre no fallback determinístico
    # (_build_selective_result), que por sua vez tinha a sua própria lógica
    # de "dominante", divergente da conclusão do motor. Corrigido para olhar
    # à chave que realmente existe.
    if nivel is not None and div.get("prob_mercado_a") is not None:
        # temos motor com odds -> decidir pelo nível de divergência
        # LIMIAR SUBIDO (12/08/2026, a pedido): só nível 3 (divergência/
        # convicção FORTE) chama o Claude — é o único onde a interpretação
        # paga acrescenta claramente sobre o fallback determinístico, que já
        # está alinhado com o motor (classificação, favorecido, fatores).
        # Nível 2 (moderado/reforçado) passou a usar só o fallback — poupa
        # ~65% das chamadas (confirmado em log real: 28/43 chamadas eram
        # nível 2). "Contraditórios" abaixo continua a chamar, é um caso à
        # parte onde a interpretação vale mesmo com gap de mercado baixo.
        if nivel >= 3:
            return (
                True,
                f"divergência {clf.get('texto', 'relevante')} detetada pelo motor (nível {nivel})",
                signals,
            )
        # nível 0-1: mercado eficiente ou divergência ligeira -> Python chega.
        # EXCEÇÃO (auditoria): sinais fortemente contraditórios entre si +
        # dados suficientes -> vale a interpretação mesmo com gap de mercado baixo.
        leaders = {
            str(s["leader"]) for s in signals
            if s.get("leader") and s.get("leader") != "igual"
        }
        if len(leaders) >= 2 and len(signals) >= 4:
            return (
                True,
                "sinais fortemente contraditórios entre si com amostra suficiente",
                signals,
            )
        return (
            False,
            f"nível {nivel} (abaixo do limiar de nível 3); síntese Python suficiente"
            if nivel == 2 else
            f"sem divergência relevante (motor nível {nivel}); síntese Python suficiente",
            signals,
        )

    # 2. Sem motor/odds -> NÃO chamar o Claude. Sem odds de mercado, o motor
    # não consegue avaliar divergência (que é o propósito da análise paga), e
    # o Claude tende a divagar sem esse contexto (chegava a bater no limite de
    # tokens). Poupa-se a chamada e evita-se o corte. O relatório sai na mesma,
    # em modo "análise parcial / sem odds" (só dados factuais).
    return (
        False,
        "sem odds de mercado — sem divergência a avaliar; relatório factual sem LLM",
        signals,
    )


def _build_selective_result(
    match_data: dict,
    signals: list[dict],
    reason: str,
) -> dict:
    """Produz o contrato normal do relatório sem recorrer a uma LLM.

    CORREÇÃO: quando existe motor de divergência com odds (div com
    prob_mercado_a), o veredicto/summary têm de vir da CLASSIFICAÇÃO DO
    MOTOR (favorecido, classificacao, fatores_chave) — a mesma fonte que a
    "Leitura" e os "Mercados a acompanhar" usam no relatório. Antes,
    calculava-se aqui um "dominante" à parte, a partir dos sinais crus
    (h2h/forma/fadiga), que podia apontar um jogador diferente do que o
    motor concluía — daí o Veredoto por vezes contradizer a Leitura no
    mesmo relatório. Só cai no cálculo antigo (por sinais) quando não há
    motor/odds de todo.
    """
    player_a = str(match_data.get("player_a") or "Jogador A")
    player_b = str(match_data.get("player_b") or "Jogador B")

    div = match_data.get("divergencia") or {}
    clf = div.get("classificacao") or {}
    nivel = clf.get("nivel")

    if nivel is not None and div.get("prob_mercado_a") is not None:
        # --- Caminho correto: alinhado 100% com o motor ---
        favorecido = div.get("favorecido")
        mercado_favorece = div.get("mercado_favorece")
        texto_clf = clf.get("texto", "Mercado eficiente")
        fatores = div.get("fatores_chave") or []
        fatores_txt = ", ".join(f"{nome} ({quem})" for nome, quem in fatores[:3])

        if nivel == 0:
            summary = f"{player_a} vs {player_b} — mercado eficiente, sem divergência relevante face aos indicadores."
            verdict = "Mercado eficiente. Sem divergência relevante entre mercado e indicadores."
            key_points = [f"Mercado e indicadores alinhados a favor de {mercado_favorece}." if mercado_favorece else "Sem vantagem clara de nenhum lado."]
        else:
            summary = f"{player_a} vs {player_b} — {texto_clf.lower()} a favor de {favorecido}."
            verdict = (
                f"{texto_clf} a favor de {favorecido}. "
                f"Mercado mantém {mercado_favorece}. "
                f"Acompanhar Moneyline {favorecido}."
            )
            key_points = [f"Fatores que sustentam: {fatores_txt}."] if fatores_txt else [f"{texto_clf} a favor de {favorecido}."]

        return {
            "flag": FLAG_ROUTINE if nivel <= 1 else FLAG_UNCERTAIN,
            "signal_strength": 20 + nivel * 20,
            "confidence_reason": "Classificação determinística do motor; síntese Python suficiente (sem LLM).",
            "summary_line": summary,
            "key_points": key_points,
            "discrepancies": [],
            "risks": [],
            "markets": [],
            "verdict": verdict,
        }

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
    llm_data = {k: v for k, v in match_data.items() if k not in _REDUNDANT_FOR_LLM and k != "divergencia"}
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

    # DIVERGÊNCIA JÁ CLASSIFICADA PELO MOTOR (Python): o Claude NÃO decide se
    # há divergência nem a sua intensidade — isso é calculado pelo motor
    # ponderado. O Claude recebe a classificação PRONTA e limita-se a
    # INTERPRETÁ-LA em linguagem de trader. Isto garante que o texto do Claude
    # nunca contradiz a bola/Model vs Market (fonte única de verdade).
    _div = match_data.get("divergencia")
    _div_bloco = ""
    if _div and _div.get("classificacao"):
        _clf = _div["classificacao"]
        _fav = _div.get("favorecido")
        _tipo = _div.get("tipo", "")
        _fatores = _div.get("fatores_chave") or []
        _fat_txt = ", ".join(f"{f} (favorece {q})" for f, q in _fatores) if _fatores else "n/d"
        # REGRA DE VOCABULÁRIO (bug real observado 11/08/2026: o Claude usou
        # "divergência forte" num caso de CONVICÇÃO, confundindo os dois
        # conceitos apesar da classificação estar correta). São coisas
        # diferentes e a palavra errada muda o significado:
        #   - "conviccao": mercado E índice apontam para O MESMO jogador, só
        #     que o índice é mais forte. NÃO é um desacordo — é um reforço.
        #   - "direcao": mercado e índice apontam para JOGADORES DIFERENTES —
        #     aqui sim é um desacordo genuíno.
        if _tipo == "conviccao":
            _regra_vocab = (
                "ESTE É UM CASO DE CONVICÇÃO, NÃO DE DIVERGÊNCIA: o mercado e "
                f"o índice concordam no MESMO lado ({_fav}), o índice só é mais "
                "forte do que a odd sugere. Usa APENAS a palavra 'convicção' "
                "(ex: 'convicção forte'). PROIBIDO escrever 'divergência' ou "
                "'diverge' neste texto — não é o caso, e confundir os dois é "
                "um erro grave de leitura."
            )
        elif _tipo == "direcao":
            _regra_vocab = (
                "ESTE É UM CASO DE DIVERGÊNCIA DE DIREÇÃO: mercado e índice "
                f"apontam para jogadores DIFERENTES (mercado favorece "
                f"{_div.get('mercado_favorece')}, índice favorece {_fav}). "
                "Usa a palavra 'divergência'."
            )
        else:
            _regra_vocab = "Mercado eficiente — não uses 'divergência' nem 'convicção'."
        _div_bloco = (
            "\n\n### CLASSIFICAÇÃO DO MOTOR (já decidida — NÃO a contradigas):\n"
            f"- Classificação: **{_clf['texto']}** (nível {_clf['nivel']}/3, tipo={_tipo})\n"
            f"- Gap modelo vs mercado: {_div.get('gap_pp', 0)} p.p.\n"
            f"- Modelo inclina para: {_fav or 'nenhum (mercado eficiente)'}\n"
            f"- Fatores que sustentam: {_fat_txt}\n"
            f"- {_regra_vocab}\n"
            "REGRA GERAL: escreve o executive_summary e o verdict COERENTES com "
            "esta classificação. Se o motor diz 'Mercado eficiente', NÃO "
            "inventes divergência nem convicção. Interpreta, não recalcules."
        )

    user_prompt = (
        "Dados do jogo (JSON). O campo 'features' traz sinais JÁ CALCULADOS "
        "(quem lidera cada dimensão e a magnitude) — usa-os como base. Campos "
        "a null significam que a fonte não tinha esse dado:\n\n"
        + json.dumps(llm_data, ensure_ascii=False, indent=2, default=str)
        + _div_bloco
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
    selective_signals: list[dict] = []  # default seguro; preenchido abaixo se LLM_POLICY="selective"

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

    # CORREÇÃO CRÍTICA (11/08/2026 — log real): provider.generate() não tinha
    # try/except. Quando a API falha por QUALQUER razão (rede, rate limit,
    # incompatibilidade de parâmetros, etc.), a exceção propagava até ao
    # main.py, que APAGA O JOGO INTEIRO do relatório (não é um fallback de
    # texto — o jogo desaparece). Confirmado ao vivo: um bug no prefill fez
    # TODAS as 30 chamadas falharem, e os ~30 jogos com divergência/convicção
    # (os mais interessantes) simplesmente não saíram no relatório final,
    # silenciosamente. Agora cai sempre no fallback determinístico (alinhado
    # com o motor), como acontece deliberadamente quando o Claude é saltado.
    try:
        provider_response = provider.generate(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            # Teto de output: 1500 (revertido de 600 — 12/08/2026, log real).
            # Descoberta: o teto só pesa no custo quando é MESMO atingido —
            # a maioria das chamadas reais usa só 128-180 tokens de output,
            # bem abaixo de qualquer um dos dois valores. Com 600, 2/73 jogos
            # nesta execução esgotaram o teto e ficaram com JSON vazio
            # (stop_reason=max_tokens, texto visível vazio — consistente com
            # o modelo a gastar orçamento em raciocínio interno antes do JSON
            # visível, o que também explica a rejeição do prefill). Subir o
            # teto de volta não aumenta o custo típico, só evita esta falha
            # nos casos-limite que precisam de mais espaço.
            max_tokens=1500,
            metadata=match_data,
        )
    except Exception as exc:
        print(
            f"[aviso] falha na chamada à API do Claude para "
            f"{match_data.get('player_a', '?')} vs {match_data.get('player_b', '?')}: "
            f"{exc} — a usar fallback determinístico (jogo NÃO é descartado)."
        )
        return _build_selective_result(
            match_data, selective_signals, f"falha na API: {exc}",
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
        Aplica limites por código aos textos do Claude (garante output curto)
        e VALIDA a coerência com o motor (auditoria 2, ponto 6)."""
        def _cut(s, n):
            s = str(s or "")
            return s if len(s) <= n else s[:n].rstrip() + "…"

        # VALIDAÇÃO PÓS-CLAUDE (sem 2ª chamada): se o Claude contradiz o motor
        # (aponta o favorecido errado, ou nega divergência que existe), rejeita
        # a interpretação e usa um fallback determinístico curto gerado pelo
        # Python. Zero contradições entre Python, Claude, HTML e Telegram.
        div = match_data.get("divergencia") or {}
        clf = div.get("classificacao") or {}
        favorecido = div.get("favorecido")
        nivel = clf.get("nivel")
        merc_fav = div.get("mercado_favorece")
        # NOTA (correção — mesmo bug já corrigido em _evaluate_selective_policy
        # e _build_selective_result): "market" não existe no dict cru de
        # _calcular_divergencia (só "prob_mercado_a"). Com a chave errada,
        # esta validação NUNCA corria — nenhuma contradição era detetada.
        if nivel is not None and div.get("prob_mercado_a") is not None:
            texto_motor = clf.get("texto", "")
            contradiz = False
            blob = f"{res.get('executive_summary','')} {res.get('verdict','')}".lower()
            # (a) motor diz divergência a favor de X, mas o Claude favorece o outro
            if nivel >= 1 and favorecido:
                outro = match_data.get("player_a") if favorecido == match_data.get("player_b") else match_data.get("player_b")
                if outro and outro.lower() in blob and favorecido.lower() not in blob:
                    contradiz = True
            # (b) motor diz divergência, mas o Claude diz "eficiente/rotina/sem divergência"
            if nivel >= 2 and any(t in blob for t in ["eficiente", "rotina", "sem divergência", "sem divergencia", "alinhad"]):
                contradiz = True
            # (c) motor é CONVICÇÃO (mercado e índice concordam, só magnitude
            # difere), mas o Claude escreve "divergência"/"diverge" — confusão
            # terminológica real observada 11/08/2026 (caso Jodar vs Fils: a
            # Leitura dizia corretamente "Convicção forte", mas o veredito do
            # Claude dizia "divergência forte face ao mercado", o que sugere
            # incorretamente um desacordo de direção que não existe).
            tipo = div.get("tipo", "")
            if tipo == "conviccao" and any(t in blob for t in ["divergência", "divergencia", "diverge"]):
                contradiz = True
            # (d) motor é DIREÇÃO (desacordo genuíno), mas o Claude escreve
            # "convicção"/"reforçada" sem mencionar divergência — mistura o
            # conceito inverso.
            if tipo == "direcao" and any(t in blob for t in ["convicção", "conviccao"]) and not any(t in blob for t in ["divergência", "divergencia", "diverge"]):
                contradiz = True
            if contradiz:
                # fallback determinístico curto, 100% coerente com o motor
                if nivel == 0:
                    fb = "Mercado eficiente. Sem divergência relevante entre mercado e indicadores."
                else:
                    fb = (f"{texto_motor} a favor de {favorecido}. "
                          f"Mercado mantém {merc_fav}. Acompanhar Moneyline {favorecido}.")
                res["executive_summary"] = fb
                res["verdict"] = fb
                res["_validacao"] = "fallback_determinístico (Claude contradizia o motor)"

        if res.get("executive_summary"):
            res["executive_summary"] = _cut(res["executive_summary"], 200)
        if res.get("verdict"):
            res["verdict"] = _cut(res["verdict"], 200)
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
