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
    coverage = _find_int("data_coverage")
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
        "data_coverage": coverage if coverage is not None else 40,
        "signal_strength": strength if strength is not None else 30,
        "confidence_reason": "Análise recuperada parcialmente (resposta cortada).",
        "summary_line": summary or f"{match_data.get('player_a','?')} vs {match_data.get('player_b','?')}",
        "key_points": key_points or ["Análise parcialmente recuperada — alguns pontos podem faltar."],
        "discrepancies": discrepancies,
        "verdict": verdict or "Veredicto não disponível (resposta cortada) — consultar pontos-chave e dados.",
    }
import hashlib
import os

from json_repair import repair_json

import anthropic

from .config import CLAUDE_MODEL, FLAG_HIGH_SIGNAL, FLAG_UNCERTAIN, FLAG_ROUTINE

_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

# Cache de análises por hash (medida de poupança, 30/07): evita repagar a
# análise de um jogo cujos dados não mudaram (o workflow corre 2x/dia e há
# jogos que aparecem nas duas janelas). Guardada no repositório em
# data/analysis_cache/ para persistir entre execuções.
_ANALYSIS_CACHE_DIR = os.path.join("data", "analysis_cache")
# Versão do prompt: muda esta string sempre que o SYSTEM_PROMPT for alterado
# de forma relevante, para invalidar a cache e forçar reanálise.
PROMPT_VERSION = "2026-08-01-cobertura-calc"


def _payload_hash(match_data: dict) -> str:
    """Hash estável do que, se mudar, justifica reanalisar. Ignora campos
    voláteis irrelevantes; foca-se nos dados materiais."""
    material = {
        "players": [match_data.get("player_a"), match_data.get("player_b")],
        "odds": match_data.get("market_odds_decimal"),
        "h2h": match_data.get("h2h"),
        "form_a": match_data.get("recent_form_a"),
        "form_b": match_data.get("recent_form_b"),
        "rank_a": match_data.get("ranking_a"),
        "rank_b": match_data.get("ranking_b"),
        "surface": match_data.get("surface"),
        "round": match_data.get("round"),
        "model": CLAUDE_MODEL,
        "prompt_version": PROMPT_VERSION,
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
- `h2h`: `overall` (carreira) e `on_surface` (só este piso, pode ser null).
  Comenta os dois; destaca quando divergem (é o sinal mais interessante).
- `h2h_rich_stats` (só WTA, fonte matchstat): serviço/resposta, BP, sets
  decisivos, tiebreaks ESPECÍFICOS do confronto, em `player1Stats`/
  `player2Stats` (cruza `id` com `ranking_a/b`). null p/ ATP.
- `injury_signal_*`: desistências/walkovers reais recentes — facto, não
  diagnóstico. Lista vazia = não encontrámos, não "está saudável".
- `surface_stats_*`: perfil nos 3 pisos (Hard/Clay/Grass); usa p/ comentar
  especialização. Cada piso pode ser null.
- `current_season_*`: jogos/vitórias na época atual. CHAVE p/ o aviso de
  fim de carreira abaixo.
- `handedness_matchup_*`, `layoff_return_stats_*` (1º jogo após pausa 60+
  dias), `round_stage_stats_*`: dados reais de contexto, não previsões.
  (Nota: recuperação de 1º set e set decisivo estão em rich_stats.scenarios.)
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

FORMATO DE SAÍDA — objeto JSON com EXATAMENTE estes campos. NÃO escreves o
relatório completo nem secções de dados (H2H, forma, piso, etc.) — essas
são montadas automaticamente a partir dos dados. Tu produzes SÓ a ANÁLISE:
- "flag": "{FLAG_HIGH_SIGNAL}" (nota/divergência forte/fadiga clara),
  "{FLAG_UNCERTAIN}" (equilibrado ou dados insuficientes), ou
  "{FLAG_ROUTINE}" (sem sinais especiais).
- "signal_strength": inteiro 0-100 = quão CLARO e forte é o sinal de leitura
  (há divergências marcantes com amostra grande? ou está tudo alinhado/
  ambíguo?). É a FORÇA da evidência — um JUÍZO qualitativo, não uma medida
  exata. (A cobertura de dados é calculada automaticamente, não a devolvas.)
- "confidence_reason": UMA frase a justificar o signal_strength (porque é
  forte/fraco o sinal), para dar transparência à leitura.
- "summary_line": 1 frase (máx ~140 chars), direta, sinal mais importante primeiro.
- "key_points": lista de 3-4 strings CURTAS (máx ~18 palavras cada, 1
  frase telegráfica). Número/facto primeiro. **negrito** nos valores. NÃO
  escrevas parágrafos. Nota de redundância: ranking/forma/época/piso são
  correlacionados — se apontam no mesmo sentido, di-lo UMA vez como "força
  geral". Taxas não ajustadas à qualidade do adversário (usa `vs_rank_level`).
- "verdict": a LEITURA DE TRADER — a conclusão mais útil do relatório, e o
  campo MAIS importante. 2-4 frases densas (não verbosas). Diz onde está
  (ou não está) o valor, pré-live ou ao vivo. Aplica os padrões QUANDO se
  aplicam (com a amostra que os sustenta); se nenhum se aplica, di-lo
  ("mercado alinhado, sem valor claro"). Padrões a caçar:
  1. RECUPERAÇÃO DE 1º SET: jogador recupera bem de 1º set perdido (alta %,
     amostra grande) → se perder o 1º set, a odd dele dispara ao vivo mas
     historicamente volta → observar entrada após perder o 1º set.
  2. VAI A 3 SETS: ambos fortes em set decisivo e/ou H2H com muitos 3 sets
     → observar "mais de 2.5 sets" / "vai a set decisivo".
  3. DOMÍNIO FRÁGIL: favorito ganha sobretudo por erro alheio
     (opp_unforced_errors alto, poucos winners) vs adversário consistente →
     favoritismo frágil → observar valor no underdog.
  4. FADIGA vs FRESCO: um leva muitos jogos/sets seguidos
     (matches_this_tournament, sets_last_7d) e o outro teve caminho leve →
     em jogo longo o desgaste pode não estar na odd → observar o mais
     fresco / "over games".
  5. ENTRADA AO VIVO: se a estatística de base (amostra 100+) contraria a
     reação esperada do mercado ao vivo → "se [evento], a odd de X
     inflaciona face aos dados — observar entrada em X".
  Regra de ouro: o mercado corresponde EXATO à estatística. "Ganha o jogo"
  ≠ "vence 2-0" (inclui 2-1); "% set decisivo" só se for a set decisivo.
  Sem saltos lógicos. Sempre OBSERVAÇÃO, nunca "aposta"/"recomendo".
  HONESTIDADE: escreve "favorito do mercado" (não "justo"); não afirmes que
  há "valor" como facto — no máximo "possível valor a observar". O bot NÃO
  quantifica edge; se o mercado parece alinhado com os dados, di-lo
  ("mercado alinhado; sem sinal claro para observar").
- "discrepancies": lista de objetos {{"weight": "forte"|"moderado"|"fraco",
  "text": "..."}}, ordenada de forte para fraco. Aqui são CURTAS e
  FACTUAIS (o dado + o mercado que sugere, 1 frase) — o raciocínio
  elaborado já está no verdict, NÃO o repitas. Regras:
   * "forte": amostra 100+ E divergência clara vs mercado. "moderado":
     30-100 ou divergência menor. "fraco": <30 ou só contexto.
   * % alta com amostra pequena é "fraco", nunca "forte".
   * Concreto e acionável: "observar handicap -3.5 games de A", "observar
     'A vence o jogo'", "observar 'vai a set decisivo'".
   * NÃO DUPLIQUES: dois lados do mesmo estado de jogo são UMA discrepância,
     não duas. Ex: "A fecha 90% após ganhar 1º set" e "B só recupera 20%
     de 1º set perdido" descrevem o MESMO cenário (o que acontece após o 1º
     set) — combina-os numa só entrada, não os contes como dois sinais.
   * Liga sempre a um número com amostra; sem suporte, não incluas. Se não
     houver discrepância real, devolve [].

Responde APENAS com o JSON, sem texto antes/depois, sem blocos de código.
"""


def analyze_match(match_data: dict) -> dict:
    """
    match_data deve conter: player_a, player_b, tournament, surface, round,
    commence_time, odds (dict ou None), h2h (dict ou None),
    form_a / form_b (dict ou None), surface_stats_a / surface_stats_b (dict
    ou None), fatigue_a / fatigue_b (dict ou None).
    """
    # Onda C (poupança de input): o payload que vai ao Claude é enxugado —
    # removemos campos DUPLICADOS que já vêm dentro de rich_stats.scenarios
    # (set1_comeback e deciding_set já estão lá como first_set_lose_then_win_pct
    # e deciding_set_win_pct). O payload COMPLETO continua a ir para o
    # report_html (que monta as secções), por isso não se perde nada visual.
    _REDUNDANT_FOR_LLM = (
        "set1_comeback_stats_a", "set1_comeback_stats_b",
        "deciding_set_stats_a", "deciding_set_stats_b",
    )
    llm_data = {k: v for k, v in match_data.items() if k not in _REDUNDANT_FOR_LLM}

    user_prompt = (
        "Dados do jogo (JSON). Campos a null significam que a fonte não "
        "tinha esse dado disponível:\n\n"
        + json.dumps(llm_data, ensure_ascii=False, indent=2, default=str)
    )

    # Cache por hash: se já analisámos este jogo com estes mesmos dados
    # materiais (e o mesmo prompt/modelo), reutilizamos — não repagamos.
    cache_key = _payload_hash(match_data)
    cache_path = os.path.join(_ANALYSIS_CACHE_DIR, f"{cache_key}.json")
    try:
        if os.path.exists(cache_path):
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            print(f"[cache_hit] {match_data.get('player_a','?')} vs {match_data.get('player_b','?')} — análise reutilizada (sem custo).")
            return cached
    except Exception:
        pass  # se a cache falhar, segue para a chamada normal

    response = _client.messages.create(
        model=CLAUDE_MODEL,
        # 3000 (30/07, medida de poupança): os relatórios reais rondam
        # 1500-2500 tokens de output; 3000 dá margem confortável sem
        # deixar espaço a excessos. Era 8000, uma rede larga demais.
        # 5000: 3000 revelou-se curto demais para os relatórios ricos
        # (Onda 2 com dados de resposta + qualidade do adversário) — estavam
        # a ser cortados a meio (stop_reason=max_tokens), gerando JSON
        # inválido. 5000 dá folga; mais vale pagar o output completo do que
        # gerar relatórios truncados que falham. As outras poupanças (cache
        # do prompt, cache por hash) mantêm-se.
        max_tokens=5500,
        # Cache do prompt de sistema (medida de poupança, 30/07): o
        # SYSTEM_PROMPT é idêntico em todos os jogos e é grande (~14k
        # caracteres). Marcá-lo como cacheable faz com que, a partir da 2ª
        # análise da mesma execução, o input do prompt custe ~10% do preço
        # (as análises correm em sequência, dentro da janela de cache).
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_prompt}],
    )

    # Logging de custo real (medida de poupança, 30/07): regista o consumo
    # de tokens de cada chamada, para sabermos exatamente onde vai o custo
    # (input grande? output? cache a funcionar?) em vez de adivinhar.
    try:
        u = response.usage
        cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
        cache_creation = getattr(u, "cache_creation_input_tokens", 0) or 0
        print(
            f"[anthropic_usage] {match_data.get('player_a','?')} vs {match_data.get('player_b','?')} | "
            f"input={u.input_tokens} output={u.output_tokens} "
            f"cache_read={cache_read} cache_creation={cache_creation}"
        )
    except Exception:
        pass

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

    def _save_and_return(res: dict) -> dict:
        """Grava o resultado na cache (só sucessos) e devolve-o."""
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
            "data_coverage": 0,
            "signal_strength": 0,
            "confidence_reason": "Erro ao gerar a análise — sem base para avaliar.",
            "summary_line": (
                f"{match_data.get('player_a', '?')} vs {match_data.get('player_b', '?')}: "
                "erro ao gerar análise (resposta do modelo não era JSON válido)."
            ),
            "key_points": ["Não foi possível gerar a análise devido a um erro de formato na resposta do modelo. As secções de dados abaixo continuam válidas."],
            "discrepancies": [],
            "verdict": "Análise indisponível nesta execução — consultar os dados factuais acima.",
        }
