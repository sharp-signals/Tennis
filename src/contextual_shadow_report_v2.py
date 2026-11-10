"""Isolated report view-model and HTML renderer for contextual SHADOW v2."""

from __future__ import annotations

from datetime import datetime
import html
import json
import math
from pathlib import Path
from typing import Any, Mapping

from .contextual_shadow_handicap_v2 import build_market_review


CONTRACT_PATH = Path("data/models/contextual-shadow-report-v2.json")
MODEL_VERSION = "contextual-family-shadow-v2"


def load_report_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    rules = value.get("rules") or {}
    if (
        value.get("contract_version") != "contextual-shadow-report-v2.0"
        or value.get("model_version") != MODEL_VERSION
        or value.get("mode") != "SHADOW_PREVIEW_ONLY"
        or rules.get("market_must_not_enter_model_probability") is not True
        or rules.get("handicap_evidence_must_be_frozen_with_prediction") is not True
        or rules.get("handicap_requires_own_line_probability") is not True
        or rules.get("no_betting_recommendation") is not True
        or rules.get("no_automatic_publication") is not True
    ):
        raise ValueError("invalid contextual SHADOW report contract")
    return value


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _display_name(value: Any) -> str:
    text = " ".join(str(value or "").split())
    return text.title() if text else "Jogador N/D"


def _display_time(value: Any) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return "Data N/D"
    return parsed.strftime("%d/%m/%Y · %H:%M UTC")


def _fair_odd(value: Mapping[str, Any] | None) -> dict[str, float | None]:
    source = value or {}
    return {
        "central": _number(source.get("central")),
        "lower": _number(source.get("lower_odd")),
        "upper": _number(source.get("upper_odd")),
    }


def _state_label(value: Any) -> str:
    return {
        "OBSERVED": "Observado",
        "OBSERVED_NONE": "Consultado · sem ocorrências",
        "INSUFFICIENT_SAMPLE": "Amostra insuficiente",
        "UNAVAILABLE": "Dados indisponíveis",
        "DIAGNOSTIC_ONLY": "Apenas diagnóstico",
        "NOT_APPLICABLE": "Não aplicável",
    }.get(str(value or "").upper(), str(value or "N/D"))


def _quality_label(value: Any) -> str:
    return {
        "PRIMARY_READY_COMPLETE": "Famílias principais completas",
        "PRIMARY_READY_SECONDARY_GAPS": "Principais prontas · lacunas secundárias",
        "PRIMARY_DEGRADED": "Família principal em falta",
    }.get(str(value or ""), str(value or "Qualidade N/D"))


def _surface_label(value: Any) -> str:
    key = str(value or "").strip().casefold()
    return {
        "hard_indoor": "Rápido indoor",
        "hard_outdoor": "Rápido outdoor",
        "clay": "Terra batida",
        "grass": "Relva",
        "carpet": "Carpete",
    }.get(key, str(value or "Contexto N/D").replace("_", " ").title())


def _round_stage_label(value: Any) -> str:
    return {
        "QUALIFYING": "Qualificação",
        "EARLY_ROUNDS": "Primeiras rondas",
        "LATE_STAGES": "Fases finais",
        "ROUND_UNRESOLVED": "Ronda N/D",
    }.get(str(value or ""), str(value or "Ronda N/D"))


def _status_label(value: Any) -> str:
    return {
        "READY_FOR_PROSPECTIVE_SHADOW": "Pronto para validação prospetiva",
        "NOT_OPERATIONALLY_READY": "Ainda não pronto para utilização operacional",
    }.get(str(value or ""), str(value or "Estado N/D"))


def _market_is_valid(
    observation: Mapping[str, Any], market: Mapping[str, Any] | None,
) -> bool:
    if not isinstance(market, Mapping):
        return False
    return (
        market.get("observation_id") == observation.get("observation_id")
        and market.get("model_version") == MODEL_VERSION
        and market.get("first_valid_quote_frozen") is True
        and market.get("production_effect") is False
    )


def _player_market(
    *, probability: float, interval_lower: float, odd: float | None,
    market_probability: float | None,
) -> dict[str, float | None]:
    if odd is None or market_probability is None:
        return {
            "odd": None,
            "probability": None,
            "probability_edge_pp": None,
            "expected_value_pct": None,
            "conservative_expected_value_pct": None,
        }
    return {
        "odd": odd,
        "probability": market_probability,
        "probability_edge_pp": 100.0 * (probability - market_probability),
        "expected_value_pct": 100.0 * (probability * odd - 1.0),
        "conservative_expected_value_pct": 100.0 * (
            interval_lower * odd - 1.0
        ),
    }


def build_report_view_model(
    observation: Mapping[str, Any],
    market: Mapping[str, Any] | None = None,
    outcome: Mapping[str, Any] | None = None,
    handicap_evidence: Mapping[str, Any] | None = None,
    *,
    contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Join frozen ledgers without changing or recalculating the prediction."""
    contract = dict(contract or load_report_contract())
    shadow = observation.get("contextual_shadow") or {}
    if (
        shadow.get("model_version") != MODEL_VERSION
        or shadow.get("market_used") is not False
        or shadow.get("production_effect") is not False
        or observation.get("paper_eligible") is not False
        or observation.get("green_eligible") is not False
    ):
        raise ValueError("contextual SHADOW report isolation violated")
    probability_a = float(shadow["probability_model_a"])
    probability_b = float(shadow["probability_model_b"])
    interval_a = list(map(float, shadow["probability_interval_90_model_a"]))
    interval_b = [1.0 - interval_a[1], 1.0 - interval_a[0]]
    valid_market = _market_is_valid(observation, market)
    market = market if valid_market else None
    odds = (market or {}).get("odds") or {}
    market_probabilities = (market or {}).get("market_probability_devig") or {}
    player_a = (observation.get("players") or {}).get("a") or {}
    player_b = (observation.get("players") or {}).get("b") or {}
    competition = observation.get("competition") or {}
    valid_handicap_evidence = bool(
        isinstance(handicap_evidence, Mapping)
        and handicap_evidence.get("observation_id")
        == observation.get("observation_id")
        and handicap_evidence.get("model_version") == MODEL_VERSION
        and handicap_evidence.get("configuration_fingerprint")
        == shadow.get("configuration_fingerprint")
        and handicap_evidence.get("production_effect") is False
    )

    family_rows = []
    absolute_total = sum(
        abs(float(item.get("logit_contribution") or 0.0))
        for item in shadow.get("families") or []
    )
    for family in shadow.get("families") or []:
        contribution = float(family.get("logit_contribution") or 0.0)
        if contribution > 1e-9:
            direction = "a"
        elif contribution < -1e-9:
            direction = "b"
        else:
            direction = "neutral"
        family_rows.append({
            "key": family.get("key"),
            "label": family.get("label") or family.get("key"),
            "data_state": family.get("data_state"),
            "data_state_label": _state_label(family.get("data_state")),
            "probability_a": _number(family.get("probability_model_a")),
            "logit_contribution": contribution,
            "direction": direction,
            "relative_contribution_pct": (
                100.0 * abs(contribution) / absolute_total
                if absolute_total > 0.0 else 0.0
            ),
        })

    market_a = _player_market(
        probability=probability_a,
        interval_lower=interval_a[0],
        odd=_number(odds.get("a")),
        market_probability=_number(market_probabilities.get("a")),
    )
    market_b = _player_market(
        probability=probability_b,
        interval_lower=interval_b[0],
        odd=_number(odds.get("b")),
        market_probability=_number(market_probabilities.get("b")),
    )
    comparisons = [("a", market_a), ("b", market_b)]
    comparisons = [
        item for item in comparisons
        if item[1]["probability_edge_pp"] is not None
    ]
    benchmark_side = max(
        comparisons,
        key=lambda item: float(item[1]["probability_edge_pp"]),
        default=(None, {}),
    )[0]
    winner_side = None
    if isinstance(outcome, Mapping) and (
        outcome.get("observation_id") == observation.get("observation_id")
    ):
        winner_side = outcome.get("winner_side")
    market_review = build_market_review(
        probabilities={"a": probability_a, "b": probability_b},
        intervals={"a": interval_a, "b": interval_b},
        odds={
            side: float(value) for side, value in odds.items()
            if side in {"a", "b"} and _number(value) is not None
        },
        evidence_record=handicap_evidence if valid_handicap_evidence else None,
    )

    return {
        "contract_version": contract["contract_version"],
        "mode": "SHADOW_PREVIEW_ONLY",
        "observation_id": observation.get("observation_id"),
        "canonical_match_instance_id": observation.get(
            "canonical_match_instance_id"
        ),
        "model_version": shadow.get("model_version"),
        "configuration_fingerprint": shadow.get("configuration_fingerprint"),
        "tour": str(observation.get("tour") or "").upper(),
        "tier": observation.get("tier") or "Tier N/D",
        "tournament_name": competition.get("tournament_name") or "Torneio N/D",
        "round_stage": _round_stage_label(competition.get("round_stage")),
        "surface_context": _surface_label(
            competition.get("surface") or shadow.get("surface_context")
        ),
        "commence_time": _display_time(observation.get("commence_time_utc")),
        "analyzed_at": _display_time(observation.get("analyzed_at_utc")),
        "players": {
            "a": {
                "name": _display_name(player_a.get("name")),
                "id": player_a.get("id"),
                "probability": probability_a,
                "interval": interval_a,
                "fair_odd": _fair_odd(shadow.get("fair_odd_model_a")),
                "market": market_a,
            },
            "b": {
                "name": _display_name(player_b.get("name")),
                "id": player_b.get("id"),
                "probability": probability_b,
                "interval": interval_b,
                "fair_odd": _fair_odd(shadow.get("fair_odd_model_b")),
                "market": market_b,
            },
        },
        "families": family_rows,
        "family_coverage": dict(shadow.get("family_coverage") or {}),
        "quality_group": shadow.get("quality_group"),
        "quality_label": _quality_label(shadow.get("quality_group")),
        "model_status": shadow.get("status"),
        "model_status_label": _status_label(shadow.get("status")),
        "reason_codes": list(shadow.get("reason_codes") or []),
        "calibration_bin_sample": shadow.get("calibration_bin_sample"),
        "interval_source": shadow.get("interval_source"),
        "extrapolation": bool(shadow.get("extrapolation")),
        "market": {
            "available": valid_market,
            "benchmark_side": benchmark_side,
            "bookmaker": (market or {}).get("bookmaker"),
            "source": (market or {}).get("source"),
            "captured_at": _display_time((market or {}).get("captured_at_utc")),
            "overround_pct": (
                100.0 * float(market["overround"])
                if market and market.get("overround") is not None else None
            ),
            "used_for_prediction": False,
        },
        "outcome": {
            "available": winner_side in {"a", "b"},
            "winner_side": winner_side,
        },
        "market_review": market_review,
        "isolation": {
            "production_effect": False,
            "paper_eligible": False,
            "green_eligible": False,
            "notification_eligible": False,
            "published_as_operational_report": False,
        },
    }


def _pct(value: Any, digits: int = 1) -> str:
    number = _number(value)
    return "N/D" if number is None else f"{100.0 * number:.{digits}f}%"


def _signed(value: Any, suffix: str = "") -> str:
    number = _number(value)
    return "N/D" if number is None else f"{number:+.1f}{suffix}"


def _odd(value: Any) -> str:
    number = _number(value)
    return "N/D" if number is None else f"{number:.2f}"


def _e(value: Any) -> str:
    return html.escape(str(value or "N/D"))


def _player_card(side: str, player: Mapping[str, Any]) -> str:
    interval = player["interval"]
    fair = player["fair_odd"]
    market = player["market"]
    edge = market.get("probability_edge_pp")
    edge_class = "positive" if edge is not None and edge > 0 else "negative"
    return f"""
      <article class="player-card side-{side}">
        <div class="player-side">MODELO {side.upper()}</div>
        <h2>{_e(player['name'])}</h2>
        <div class="probability">{_pct(player['probability'])}</div>
        <div class="interval">Intervalo 90% · {_pct(interval[0])}–{_pct(interval[1])}</div>
        <div class="player-grid">
          <div><span>Fair odd</span><strong>{_odd(fair['central'])}</strong></div>
          <div><span>Faixa justa</span><strong>{_odd(fair['lower'])}–{_odd(fair['upper'])}</strong></div>
          <div><span>Odd observada</span><strong>{_odd(market.get('odd'))}</strong></div>
          <div class="{edge_class}"><span>Diferença vs prob. de-vig</span><strong>{_signed(edge, ' p.p.')}</strong></div>
        </div>
        <div class="ev-row">
          <span>EV central <b>{_signed(market.get('expected_value_pct'), '%')}</b></span>
          <span>EV no limite conservador <b>{_signed(market.get('conservative_expected_value_pct'), '%')}</b></span>
        </div>
      </article>"""


def _market_review_html(view: Mapping[str, Any]) -> str:
    review = view.get("market_review") or {}
    status = review.get("status")
    if status == "MARKET_UNAVAILABLE":
        body = (
            '<div class="review-empty"><b>Mercado ainda indisponível.</b> '
            "A previsão permanece guardada; não é formulado qualquer mercado."
            "</div>"
        )
    elif status == "NO_POSITIVE_EDGE":
        body = (
            '<div class="review-empty"><b>Sem edge central positivo.</b> '
            "O relatório mantém a leitura factual, mas não destaca um mercado."
            "</div>"
        )
    else:
        side = str(review.get("candidate_side") or "")
        player = (view.get("players") or {}).get(side) or {}
        confidence = (
            "Edge também positivo no limite conservador"
            if status == "CONSERVATIVE_POSITIVE"
            else "Edge positivo apenas na estimativa central"
        )
        cards = []
        moneyline = review.get("moneyline")
        if isinstance(moneyline, Mapping):
            minimum = moneyline.get("minimum_odd")
            zone = (
                f"{float(minimum):.2f}–{float(moneyline['maximum_odd']):.2f}"
                if minimum is not None else "Fora da janela operacional"
            )
            cards.append(f"""
              <article class="review-card moneyline-card">
                <div class="review-type">MONEYLINE</div>
                <h3>{_e(player.get('name'))}</h3>
                <div class="review-big">{_odd(moneyline.get('observed_odd'))}</div>
                <p>Odd observada · fair odd {_odd(moneyline.get('fair_odd'))}</p>
                <div class="price-zone"><span>FAIXA PARA CONSIDERAR</span><b>{_e(zone)}</b></div>
              </article>""")
        handicap = review.get("handicap")
        if isinstance(handicap, Mapping):
            positive = handicap.get("type") == "positive"
            line_cards = []
            for line in handicap.get("lines") or []:
                price = line.get("price") or {}
                if price.get("status") != "READY":
                    zone = "Sem preço validado · amostra relevante curta"
                elif price.get("minimum_odd") is None:
                    zone = (
                        f"Fair {_odd(price.get('fair_odd'))} · acima da janela"
                    )
                else:
                    zone = (
                        f"{float(price['minimum_odd']):.2f}–"
                        f"{float(price['maximum_odd']):.2f}"
                    )
                if positive:
                    primary = f"{_e(line.get('cover_pct'))}% cobre no total"
                    secondary = (
                        f"Quando vence: {_e(line.get('win_cover_pct'))}% "
                        f"({_e(line.get('win_cover'))}/{_e(line.get('win_total'))})"
                    )
                else:
                    primary = f"{_e(line.get('win_cover_pct'))}% cobre quando vence"
                    secondary = (
                        f"Total: {_e(line.get('cover_pct'))}% "
                        f"({_e(line.get('cover'))}/{_e(line.get('total'))})"
                    )
                line_cards.append(f"""
                  <div class="line-card">
                    <div class="line-name">{_e(player.get('name'))} {_e(line.get('line'))}</div>
                    <strong>{primary}</strong><small>{secondary}</small>
                    <div class="line-zone"><span>ODD PARA CONSIDERAR</span><b>{_e(zone)}</b></div>
                  </div>""")
            cards.append(f"""
              <article class="review-card handicap-card">
                <div class="review-type">HANDICAP {'POSITIVO' if positive else 'NEGATIVO'} · {_e(handicap.get('format'))}</div>
                <div class="line-grid">{''.join(line_cards)}</div>
              </article>""")
        if not cards:
            cards.append(
                '<div class="review-empty">Edge identificado, mas a odd não '
                "está na janela Moneyline e não existe evidência de handicap "
                "congelada para esta observação.</div>"
            )
        body = f"""
          <div class="review-lead"><div><b>{_e(player.get('name'))}</b><span>{_e(confidence)}</span></div>
            <div><strong>{_signed(review.get('central_ev_pct'), '%')}</strong><span>EV central</span></div>
            <div><strong>{_signed(review.get('conservative_ev_pct'), '%')}</strong><span>EV conservador</span></div></div>
          <div class="review-grid">{''.join(cards)}</div>"""
    return f"""
      <section class="section market-review">
        <div class="section-head"><div><div class="eyebrow">VALIDAÇÃO HUMANA</div>
          <h2>Mercados a consultar</h2></div><div class="shadow-badge">SEM ENTRADA AUTOMÁTICA</div></div>
        {body}
        <div class="market-note">A Moneyline usa a fair odd independente. Cada handicap tem probabilidade própria calculada com a cobertura condicional congelada antes do jogo. A odd da linha deve ser confirmada na casa de apostas.</div>
      </section>"""


def render_report_html(view: Mapping[str, Any]) -> str:
    """Render a standalone, responsive preview with no operational actions."""
    players = view["players"]
    families = []
    for family in view["families"]:
        contribution = float(family["logit_contribution"])
        width = min(100.0, float(family["relative_contribution_pct"]))
        direction = family["direction"]
        probability = family.get("probability_a")
        probability_text = _pct(probability) if probability is not None else "Sem probabilidade própria"
        families.append(f"""
          <div class="family-row state-{_e(family['data_state']).lower()}">
            <div class="family-copy">
              <strong>{_e(family['label'])}</strong>
              <small>{_e(family['data_state_label'])} · {probability_text}</small>
            </div>
            <div class="family-scale" aria-label="Contributo relativo da família">
              <span class="axis"></span>
              <span class="bar {direction}" style="--strength:{width:.2f}%"></span>
            </div>
            <div class="family-result {direction}">
              {('+' if contribution > 0 else '')}{contribution:.3f}
              <small>logit</small>
            </div>
          </div>""")
    market = view["market"]
    if market["available"]:
        market_copy = (
            f"Primeira cotação válida congelada · {_e(market['bookmaker'])} · "
            f"{_e(market['source'])} · {_e(market['captured_at'])}"
        )
        benchmark_badge = "BENCHMARK DISPONÍVEL"
    else:
        market_copy = "Cotação pós-previsão ainda indisponível. A previsão mantém-se válida e imutável."
        benchmark_badge = "MERCADO N/D"
    coverage = view.get("family_coverage") or {}
    observed = coverage.get("observed", 0)
    total = coverage.get("total", 5)
    coverage_pct = coverage.get("pct", 0)
    preferred = max(players, key=lambda side: players[side]["probability"])
    preferred_name = players[preferred]["name"]
    if view["model_status"] == "READY_FOR_PROSPECTIVE_SHADOW":
        direct_read = (
            f"O modelo inclina-se para {preferred_name}, mantendo a incerteza "
            "explicitamente visível. A comparação de mercado é posterior e não altera esta leitura."
        )
    else:
        direct_read = (
            "A previsão foi preservada, mas a qualidade disponível ainda não permite "
            "tratá-la como operacionalmente pronta."
        )
    title = f"{players['a']['name']} vs {players['b']['name']}"
    reasons = ", ".join(view["reason_codes"]) or "Sem bloqueios estruturais"
    return f"""<!doctype html>
<html lang="pt-PT">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{_e(title)} · Contextual SHADOW v2</title>
  <style>
    :root{{--ink:#eef7ff;--muted:#8ba9c4;--panel:#0c2035;--panel2:#102a45;--line:#244866;
      --cyan:#43d9d0;--blue:#55a7ff;--orange:#ff9b55;--red:#ff6475;--navy:#061522;--gold:#ffc857}}
    *{{box-sizing:border-box}} body{{margin:0;background:radial-gradient(circle at 15% 0,#113354 0,#061522 42%);
      color:var(--ink);font:15px/1.45 Inter,Segoe UI,Arial,sans-serif}}
    .shell{{max-width:1180px;margin:auto;padding:28px 18px 70px}} .topline{{display:flex;gap:12px;align-items:center;
      justify-content:space-between;margin-bottom:18px}} .brand{{font-weight:900;letter-spacing:.16em;color:var(--cyan)}}
    .shadow-badge,.market-badge{{border:1px solid var(--gold);color:var(--gold);border-radius:999px;padding:7px 11px;
      font-size:11px;font-weight:800;letter-spacing:.09em}} .hero,.section{{background:linear-gradient(145deg,rgba(16,42,69,.96),rgba(8,27,45,.96));
      border:1px solid var(--line);border-radius:22px;box-shadow:0 18px 50px #0005}}
    .hero{{padding:26px}} .context{{text-align:center;color:var(--muted);text-transform:uppercase;letter-spacing:.09em;font-size:12px}}
    .versus{{display:grid;grid-template-columns:1fr auto 1fr;gap:18px;align-items:center;margin-top:8px}}
    .versus h1{{font-size:clamp(23px,4vw,40px);line-height:1.05;margin:8px 0}} .versus .right{{text-align:right}}
    .vs{{color:var(--muted);font-weight:900;font-size:20px}} .summary{{margin:18px 0 0;border-top:1px solid var(--line);
      padding-top:17px;display:flex;gap:14px;justify-content:space-between;align-items:center}}
    .summary strong{{font-size:18px}} .summary span{{color:var(--muted)}} .section{{margin-top:18px;padding:24px}}
    .section-head{{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:18px}}
    .eyebrow{{color:var(--cyan);font-weight:900;letter-spacing:.12em;font-size:12px}} h2,h3,p{{margin-top:0}}
    .pricing-grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}} .player-card{{border:1px solid var(--line);
      border-top:4px solid var(--blue);border-radius:16px;padding:20px;background:#0b2137}} .player-card.side-b{{border-top-color:var(--orange)}}
    .player-side{{font-size:10px;letter-spacing:.14em;color:var(--muted);font-weight:900}} .player-card h2{{margin:6px 0}}
    .probability{{font-size:42px;font-weight:950;letter-spacing:-.04em}} .interval{{color:var(--muted);margin-bottom:18px}}
    .player-grid{{display:grid;grid-template-columns:1fr 1fr;gap:8px}} .player-grid div{{padding:12px;background:#132f4d;border-radius:10px}}
    .player-grid span,.ev-row span{{display:block;color:var(--muted);font-size:11px}} .player-grid strong{{font-size:18px}}
    .positive strong{{color:var(--cyan)}} .negative strong{{color:#b8c9d8}} .ev-row{{display:flex;gap:18px;margin-top:12px}}
    .market-note{{margin-top:14px;padding:13px 15px;border-left:3px solid var(--gold);background:#152a3d;color:#c8d8e7}}
    .review-lead{{display:grid;grid-template-columns:2fr 1fr 1fr;gap:10px;margin-bottom:14px}}.review-lead>div{{padding:14px;background:#132f4d;border-radius:11px}}
    .review-lead b,.review-lead strong{{display:block;font-size:21px}}.review-lead span{{color:var(--muted);font-size:11px}}
    .review-grid{{display:grid;grid-template-columns:minmax(250px,.8fr) minmax(0,2fr);gap:14px}}.review-card{{background:#0b2137;border:1px solid var(--line);border-radius:16px;padding:18px}}
    .review-type{{color:var(--cyan);font-size:10px;font-weight:900;letter-spacing:.12em}}.review-big{{font-size:38px;font-weight:950}}
    .review-card p,.line-card small{{color:var(--muted)}}.price-zone,.line-zone{{margin-top:12px;padding:10px;background:#132f4d;border-radius:9px}}
    .price-zone span,.line-zone span{{display:block;color:var(--muted);font-size:9px;letter-spacing:.08em}}.price-zone b,.line-zone b{{font-size:16px}}
    .line-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;margin-top:12px}}.line-card{{padding:13px;background:#102a45;border:1px solid #285171;border-radius:11px}}
    .line-card strong,.line-card small{{display:block}}.line-name{{font-weight:900;font-size:17px;margin-bottom:7px}}.review-empty{{padding:20px;border:1px dashed #54718a;border-radius:14px;color:var(--muted)}}
    .quality{{display:grid;grid-template-columns:160px 1fr;gap:20px;align-items:center}} .ring{{width:140px;height:140px;border-radius:50%;
      display:grid;place-content:center;text-align:center;background:conic-gradient(var(--cyan) {float(coverage_pct):.1f}%,#16334d 0);
      position:relative}} .ring:after{{content:"";position:absolute;inset:12px;border-radius:50%;background:#0b2137}}
    .ring strong,.ring small{{position:relative;z-index:1}} .ring strong{{font-size:30px}} .quality-copy p{{color:var(--muted)}}
    .family-row{{display:grid;grid-template-columns:minmax(210px,1fr) minmax(240px,2fr) 88px;gap:16px;align-items:center;
      padding:14px 0;border-bottom:1px solid #1b3a55}} .family-row:last-child{{border-bottom:0}} .family-copy small,
    .family-result small{{display:block;color:var(--muted);font-size:11px}} .family-scale{{height:18px;position:relative;background:#091b2c;border-radius:9px}}
    .axis{{position:absolute;left:50%;top:0;bottom:0;width:1px;background:#66829b}} .bar{{position:absolute;top:4px;height:10px;width:calc(var(--strength)/2);border-radius:6px}}
    .bar.a{{right:50%;background:var(--blue)}} .bar.b{{left:50%;background:var(--orange)}} .bar.neutral{{left:50%;width:2px;background:#66829b}}
    .family-result{{text-align:right;font-weight:900}} .family-result.a{{color:var(--blue)}} .family-result.b{{color:var(--orange)}}
    details{{margin-top:18px;border-top:1px solid var(--line);padding-top:14px}} summary{{cursor:pointer;color:var(--muted)}}
    .trace{{margin-top:12px;display:grid;grid-template-columns:repeat(2,1fr);gap:8px;font-family:ui-monospace,Consolas,monospace;font-size:11px}}
    .trace div{{padding:10px;background:#091b2c;border-radius:8px;overflow-wrap:anywhere}} .foot{{color:var(--muted);text-align:center;margin-top:18px;font-size:12px}}
    @media(max-width:760px){{.pricing-grid{{grid-template-columns:1fr}}.quality{{grid-template-columns:1fr}}.ring{{margin:auto}}
      .family-row{{grid-template-columns:1fr}}.family-result{{text-align:left}}.versus{{grid-template-columns:1fr;text-align:center}}
      .versus .right{{text-align:center}}.vs{{display:none}}.summary{{display:block}}.player-grid{{grid-template-columns:1fr}}
      .review-lead,.review-grid,.line-grid{{grid-template-columns:1fr}}}}
  </style>
</head>
<body><main class="shell">
  <div class="topline"><div class="brand">FENZOBOT · CONTEXTUAL V2</div><div class="shadow-badge">SHADOW · SEM DECISÃO</div></div>
  <section class="hero">
    <div class="context">{_e(view['tour'])} · {_e(view['tier'])} · {_e(view['tournament_name'])} · {_e(view['round_stage'])} · {_e(view['surface_context'])} · {_e(view['commence_time'])}</div>
    <div class="versus"><div><h1>{_e(players['a']['name'])}</h1><span>Modelo A</span></div><div class="vs">VS</div>
      <div class="right"><h1>{_e(players['b']['name'])}</h1><span>Modelo B</span></div></div>
    <div class="summary"><div><strong>LEITURA DIRETA</strong><br><span>{_e(direct_read)}</span></div>
      <div class="market-badge">{benchmark_badge}</div></div>
  </section>
  <section class="section">
    <div class="section-head"><div><div class="eyebrow">NÚCLEO DE PRICING</div><h2>Probabilidade e fair odd independentes</h2></div></div>
    <div class="pricing-grid">{_player_card('a', players['a'])}{_player_card('b', players['b'])}</div>
    <div class="market-note"><b>Mercado observado apenas depois da previsão.</b> {_e(market_copy)}</div>
  </section>
  {_market_review_html(view)}
  <section class="section">
    <div class="section-head"><div><div class="eyebrow">QUALIDADE DA EVIDÊNCIA</div><h2>O que foi realmente medido</h2></div></div>
    <div class="quality"><div class="ring"><strong>{float(coverage_pct):.0f}%</strong><small>{observed}/{total} famílias</small></div>
      <div class="quality-copy"><h3>{_e(view['quality_label'])}</h3><p>{_e(view['model_status_label'])}</p>
      <p>Bin histórico de calibração: <b>{_e(view['calibration_bin_sample'])} casos</b>. Dados em falta alargam a incerteza; nunca são tratados como vantagem neutra.</p></div></div>
  </section>
  <section class="section">
    <div class="section-head"><div><div class="eyebrow">MAPA DAS FAMÍLIAS</div><h2>Direção e contributo para a previsão</h2></div></div>
    {''.join(families)}
    <div class="market-note">As barras mostram a participação relativa no movimento do logit deste jogo. Não são percentagens autónomas de vitória nem pesos fixos.</div>
  </section>
  <section class="section">
    <div class="eyebrow">RASTREABILIDADE</div><h2>Contrato e isolamento</h2>
    <p>Razões técnicas: {_e(reasons)}. Este preview não cria entradas, não altera previsões e não é publicado como relatório operacional.</p>
    <details><summary>Ver identificação técnica completa</summary><div class="trace">
      <div>observation_id<br>{_e(view['observation_id'])}</div><div>canonical_match_instance_id<br>{_e(view['canonical_match_instance_id'])}</div>
      <div>model_version<br>{_e(view['model_version'])}</div><div>contract_version<br>{_e(view['contract_version'])}</div>
      <div>configuration_fingerprint<br>{_e(view['configuration_fingerprint'])}</div><div>previsão congelada<br>{_e(view['analyzed_at'])}</div>
    </div></details>
  </section>
  <p class="foot">Protótipo visual isolado · não representa recomendação de aposta · mercado nunca entra na probabilidade Fenzobot.</p>
</main></body></html>"""


def render_index_html(views: list[Mapping[str, Any]]) -> str:
    cards = []
    for view in views:
        a = view["players"]["a"]
        b = view["players"]["b"]
        filename = f"report-{view['observation_id']}.html"
        cards.append(f"""
        <a class="card" href="{_e(filename)}"><small>{_e(view['tour'])} · {_e(view['tier'])}</small>
          <h2>{_e(a['name'])}<span>vs</span>{_e(b['name'])}</h2>
          <div><b>{_pct(a['probability'])}</b><i>{'mercado congelado' if view['market']['available'] else 'mercado N/D'}</i><b>{_pct(b['probability'])}</b></div>
          <p>{_e(view['quality_label'])}</p></a>""")
    return f"""<!doctype html><html lang="pt-PT"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Fenzobot · previews SHADOW v2</title><style>
    body{{margin:0;background:#061522;color:#eef7ff;font:15px Inter,Segoe UI,Arial,sans-serif}}main{{max-width:1120px;margin:auto;padding:35px 18px}}
    h1{{font-size:38px}}header p,.card p,.card small{{color:#8ba9c4}}.notice{{padding:14px 16px;border:1px solid #ffc857;border-radius:12px;color:#ffc857}}
    .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:14px;margin-top:22px}}.card{{display:block;color:inherit;text-decoration:none;
    background:#0c2035;border:1px solid #244866;border-radius:16px;padding:18px;transition:.15s}}.card:hover{{transform:translateY(-2px);border-color:#43d9d0}}
    .card h2{{font-size:19px;display:flex;flex-direction:column;gap:3px}}.card h2 span{{color:#8ba9c4;font-size:11px;text-transform:uppercase}}
    .card div{{display:flex;justify-content:space-between;align-items:center}}.card b{{font-size:23px}}.card i{{font-size:10px;color:#43d9d0}}
    </style></head><body><main><header><small>FENZOBOT · DESIGN LAB</small><h1>Novo relatório contextual</h1>
    <p>Previews construídos exclusivamente a partir das previsões congeladas. Nenhuma página abaixo cria PAPER, GREEN ou decisão.</p></header>
    <div class="notice">SHADOW PREVIEW ONLY · mercado observado posteriormente e nunca usado para formar a fair odd.</div>
    <section class="grid">{''.join(cards) or '<p>Sem observações disponíveis.</p>'}</section></main></body></html>"""
