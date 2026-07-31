"""
Chama a API da Anthropic para gerar a análise de cada jogo.

Regra de ouro (igual ao bot de futebol): o prompt só contém dados que
efetivamente recolhemos. Quando um bloco de dados é None, dizemos
explicitamente ao modelo "não temos este dado" em vez de omitir o campo
em silêncio — isso evita que o modelo assuma e "invente" com naturalidade.
"""

from __future__ import annotations

import json
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
PROMPT_VERSION = "2026-07-31-medida6b"


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
- `set1_comeback_stats_*`, `deciding_set_stats_*`, `handedness_matchup_*`,
  `layoff_return_stats_*` (1º jogo após pausa 60+ dias), `round_stage_stats_*`:
  dados reais de contexto, não previsões.
- `fatigue_signal_*`: `days_since_last_match`, `matches_last_3/7/14d`,
  `minutes/sets_played_last_7d`. Usa o conjunto. Métricas usam a data de
  INÍCIO do torneio (não a exata) — trata como aproximação.
- `rich_stats_*` (pode ser null): dados ricos da matchstat. `response_stats`
  = métricas de RESPOSTA de carreira (pontos de resposta ganhos, break
  points convertidos) — usa-as na secção Serviço/Resposta para
  complementar o serviço. `vs_rank_level` = desempenho SEPARADO por nível
  de ranking do adversário (top5/10/50/100), com vitórias e %. Isto é
  importante para o ponto da QUALIDADE DO ADVERSÁRIO: um jogador pode ter
  boa taxa geral mas fraca contra o top-10 (ex: 66% vs top-100 mas 20% vs
  top-5 = enche estatísticas com adversários fracos). Usa isto para
  qualificar as taxas de vitória e nas discrepâncias quando relevante.

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
- "confidence_score": inteiro 0-100 = força/fiabilidade da LEITURA (não a
  probabilidade de vitória). 0-33 baixo, 34-66 médio, 67-100 alto. Reflete
  os 3 princípios (amostra pequena e dados em falta baixam; presente sólido sobe).
- "confidence_reason": UMA frase a justificar o score.
- "summary_line": 1 frase (máx ~140 chars), direta, sinal mais importante primeiro.
- "key_points": lista de 3-5 strings CURTAS (máx ~20 palavras cada, 1
  frase telegráfica). Número/facto primeiro. **negrito** nos valores. NÃO
  escrevas parágrafos — se precisas de vírgulas a mais, corta. Aplica a
  nota de redundância: ranking/forma/época/piso são correlacionados — se
  apontam todos no mesmo sentido, di-lo UMA vez como "força geral", não
  como provas independentes. Lembra que as taxas não estão ajustadas à
  qualidade do adversário (usa `vs_rank_level` quando útil).
- "discrepancies": lista de objetos {{"weight": "forte"|"moderado"|"fraco",
  "text": "..."}}, ordenada de forte para fraco. Cada uma liga uma
  divergência entre os dados e o mercado a um MERCADO A OBSERVAR (nunca
  "aposta"/"recomendo"). Regras:
   * weight "forte": amostra grande (100+ jogos) E divergência clara vs mercado.
   * weight "moderado": amostra 30-100 ou divergência menos vincada.
   * weight "fraco": amostra <30 ou só contexto.
   * O "text" liga o dado (com número e amostra) ao mercado a observar. Ex:
     "Tsitsipas lidera H2H **12-1** (13 jogos) — observar handicap de games de Tsitsipas."
   * Percentagem alta com amostra pequena é "fraco", nunca "forte".
   * Liga sempre a um número com amostra; sem suporte, não incluas.
   * Tipos de raciocínio: underdog com bom perfil → handicap/"ganha 1 set";
     favorito vs quem recupera bem → observar se perde 1º set ao vivo;
     forte em set decisivo → "vai a set decisivo"/total de sets.
   * Se não houver discrepância real, devolve lista vazia [].
- "verdict": 1-2 frases MÁX, leitura conclusiva simples e objetiva para
  quem só quer o essencial (ex: "Mercado alinhado — favoritismo de Sinner
  justificado." ou "Divergência a favor de Tabilo; observar handicap de
  games."). NÃO repitas a lista de discrepâncias.

Responde APENAS com o JSON, sem texto antes/depois, sem blocos de código.
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
        max_tokens=4000,
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

        # Fallback defensivo: nunca deixar o pipeline abaixo sem estrutura,
        # mas sinalizamos claramente que houve um problema de formato —
        # não inventamos uma análise. Inclui o motivo exato no log (não na
        # mensagem enviada) para facilitar diagnóstico.
        print(f"[aviso] resposta bruta (primeiros 500 chars): {raw_text[:500]}")
        return {
            "flag": FLAG_UNCERTAIN,
            "confidence_score": 0,
            "confidence_reason": "Erro ao gerar a análise — sem base para avaliar.",
            "summary_line": (
                f"{match_data.get('player_a', '?')} vs {match_data.get('player_b', '?')}: "
                "erro ao gerar análise (resposta do modelo não era JSON válido)."
            ),
            "key_points": ["Não foi possível gerar a análise devido a um erro de formato na resposta do modelo. As secções de dados abaixo continuam válidas."],
            "discrepancies": [],
            "verdict": "Análise indisponível nesta execução — consultar os dados factuais acima.",
        }
