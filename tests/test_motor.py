"""
Testes determinísticos do MOTOR DE DIVERGÊNCIA e da política SELECTIVE.
(Auditoria P0 #4 — estas são as peças que decidem os jogos interessantes e
quando se gasta dinheiro com o Claude, por isso precisam de testes dedicados.)

Correr: python -m pytest tests/test_motor.py -v
Ou standalone: python tests/test_motor.py
"""
import sys
import os

# permitir importar de src/ tanto em pytest como standalone
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from report_html import _calcular_divergencia, PESOS  # noqa: E402


# ---------- helpers ----------
def _payload(odds_a, odds_b, features, **extra):
    p = {
        "player_a": "A", "player_b": "B",
        "market_odds_decimal": {"A": odds_a, "B": odds_b},
        "features": features,
    }
    p.update(extra)
    return p


# ---------- TESTES: índice de evidência (P0 #1) ----------
def test_indice_nao_e_probabilidade():
    """O índice é 0-100 mas nunca apresentado como probabilidade. Verificamos
    que o campo existe e é coerente (a+b=100)."""
    r = _calcular_divergencia(_payload(2.0, 1.8, {
        "h2h": {"lider": "A", "diff": 3, "a_wins": 3, "b_wins": 0},
        "piso": {"lider": "A", "diff": 12, "amostra_a": 100, "amostra_b": 100},
    }))
    assert r is not None
    assert r["indice_evidencia_a"] + r["indice_evidencia_b"] == 100
    assert 0 <= r["indice_evidencia_a"] <= 100


def test_sem_odds_devolve_none():
    """Sem odds de mercado, não há comparação possível -> None."""
    r = _calcular_divergencia({"player_a": "A", "player_b": "B",
                               "market_odds_decimal": {}, "features": {}})
    assert r is None


# ---------- TESTES: comparação direcional ----------
def test_mercado_e_indice_concordam_direcao():
    """Superfavorito onde os sinais também o favorecem: a DIREÇÃO concorda
    (ambos no mesmo jogador). Isso é alinhamento, não prova valor nem permite
    comparar a magnitude das duas escalas."""
    r = _calcular_divergencia(_payload(1.15, 5.5, {
        "h2h": {"lider": "A", "diff": 2, "a_wins": 2, "b_wins": 0},
        "piso": {"lider": "A", "diff": 10, "amostra_a": 200, "amostra_b": 200},
        "forma_recente": {"lider": "A", "diff": 30},
        "ranking": {"lider": "A", "diff": 27},
    }))
    assert r["tipo"] == "alinhamento"
    assert r["intensidade_indicadores"] == "forte"
    assert r["intensidade_nivel"] == 3
    assert r["classificacao"]["nivel"] == 0
    assert r["favorecido"] is None
    assert r["gap_pp"] is None
    assert r["indice_favorece"] == r["mercado_favorece"]


def test_divergencia_quando_discordam():
    """Sinais fortes num jogador, mercado no outro -> divergência."""
    r = _calcular_divergencia(_payload(2.6, 1.5, {
        "h2h": {"lider": "A", "diff": 3, "a_wins": 3, "b_wins": 0},
        "piso": {"lider": "A", "diff": 18, "amostra_a": 100, "amostra_b": 100},
        "forma_recente": {"lider": "A", "diff": 15},
        "ranking": {"lider": "B", "diff": 20},
    }, rich_stats_a={"scenarios": {"deciding_set_win_pct": 63, "deciding_set_count": 30}},
       rich_stats_b={"scenarios": {"deciding_set_win_pct": 48, "deciding_set_count": 30}}))
    assert r["classificacao"]["nivel"] >= 1
    assert r["tipo"] == "direcao"
    assert r["gap_pp"] is None
    assert r["indice_favorece"] != r["mercado_favorece"]


# ---------- TESTES: salvaguardas contra falsos positivos ----------
def test_h2h_um_jogo_nao_conta():
    """H2H de 1 só jogo não deve gerar divergência forte."""
    r = _calcular_divergencia(_payload(2.75, 1.39, {
        "h2h": {"lider": "A", "diff": 1, "a_wins": 1, "b_wins": 0},
        "ranking": {"lider": "A", "diff": 2},
    }))
    # H2H de 1 jogo é ignorado e ranking diff 2 também -> sem evidência (None)
    # ou, se houver algum sinal, no máximo ligeira. Ambos são corretos.
    assert r is None or r["classificacao"]["nivel"] <= 1


def test_ranking_quase_igual_nao_conta():
    """Ranking #70 vs #72 (diff 2) não deve pesar."""
    r = _calcular_divergencia(_payload(2.0, 1.8, {
        "ranking": {"lider": "A", "diff": 2},
    }))
    # diferença de ranking < 5 é ignorada -> sem evidência -> None ou eficiente
    assert r is None or r["classificacao"]["nivel"] == 0


def test_dados_escassos_nao_geram_forte():
    """Só um fator (ranking) não pode gerar divergência forte."""
    r = _calcular_divergencia(_payload(1.6, 2.4, {
        "ranking": {"lider": "A", "diff": 30},
    }))
    if r:
        assert r["classificacao"]["nivel"] <= 1  # salvaguarda de massa


# ---------- TESTES: confiança de amostra (P0 #3) ----------
def test_amostra_pequena_pesa_menos():
    """Piso com 8 jogos deve pesar menos que com 300 jogos."""
    base_feats = lambda n: {
        "piso": {"lider": "A", "diff": 15, "amostra_a": n, "amostra_b": n},
        "ranking": {"lider": "B", "diff": 40},
    }
    r_pouco = _calcular_divergencia(_payload(2.5, 1.5, base_feats(8)))
    r_muito = _calcular_divergencia(_payload(2.5, 1.5, base_feats(300)))
    # com mais amostra, o índice a favor de A é maior (piso pesa mais)
    assert r_muito["indice_evidencia_a"] > r_pouco["indice_evidencia_a"]


def test_comeback_e_atenuado_pela_menor_amostra():
    r = _calcular_divergencia(_payload(1.55, 2.55, {
        "comeback_set1": {
            "lider": "B", "diff": 12, "valor_a": 21, "valor_b": 33,
            "amostra_a": 141, "amostra_b": 15,
        },
        "ranking": {"lider": "A", "diff": 30},
    }))
    status = r["fatores_status"]["comeback_set1"]
    assert status["confianca_amostra"] == 0.707
    assert status["peso_efetivo"] == 4.95
    assert status["amostra"] == 15


def test_servico_com_zero_observacoes_nao_pontua():
    r = _calcular_divergencia(_payload(1.55, 2.55, {
        "servico_carreira": {
            "lider": "A", "diff": 63, "valor_a": 63, "valor_b": 0,
            "amostra_a": 3, "amostra_b": 0,
        },
        "ranking": {"lider": "A", "diff": 30},
    }))
    status = r["fatores_status"]["servico_carreira"]
    assert status["disponivel"] is False
    assert "amostra em falta" in status["motivo_exclusao"]
    assert not status.get("peso_efetivo")


def test_divergencia_forte_exige_diversidade_estrutura_e_identidade_confirmada():
    r = _calcular_divergencia(_payload(1.32, 3.20, {
        "forma_recente": {"lider": "B", "diff": 10, "valor_a": 60, "valor_b": 70},
        "piso": {"lider": "A", "diff": 2, "valor_a": 64, "valor_b": 62,
                 "amostra_a": 13, "amostra_b": 13},
        "comeback_set1": {"lider": "B", "diff": 12, "valor_a": 21, "valor_b": 33,
                          "amostra_a": 141, "amostra_b": 15},
        "servico_carreira": {"lider": "A", "diff": 63, "valor_a": 63, "valor_b": 0,
                             "amostra_a": 3, "amostra_b": 0},
    }, rich_stats_a={"scenarios": {"deciding_set_win_pct": 59, "deciding_set_count": 110}},
       rich_stats_b={"scenarios": {"deciding_set_win_pct": 75, "deciding_set_count": 8}},
       data_quality={"issues": [{"type": "name_resolution", "severity": "warning"}]}))
    assert r["classificacao"]["nivel"] <= 2
    assert "dados limitados" in r["classificacao"]["texto"]
    assert r["evidence_coverage"]["active_family_count"] == 2
    assert r["evidence_coverage"]["pricing_eligible"] is False
    assert r["evidence_coverage"]["source_reliability"] == 0.5


def test_divergencia_forte_continua_possivel_com_cobertura_diversa():
    r = _calcular_divergencia(_payload(2.6, 1.5, {
        "h2h": {"lider": "A", "diff": 4, "a_wins": 4, "b_wins": 0},
        "piso": {"lider": "A", "diff": 18, "amostra_a": 100, "amostra_b": 100},
        "forma_recente": {"lider": "A", "diff": 20},
        "ranking": {"lider": "A", "diff": 30},
    }))
    assert r["classificacao"]["nivel"] == 3
    assert r["evidence_coverage"]["active_family_count"] >= 3
    assert r["evidence_coverage"]["pricing_eligible"] is True


# ---------- TESTES: pesos coerentes com a decisão do utilizador ----------
def test_pesos_h2h_piso_maiores_que_ranking():
    """H2H e piso devem ter peso maior que ranking (decisão do utilizador)."""
    assert PESOS["h2h"] > PESOS["ranking"]
    assert PESOS["piso"] > PESOS["ranking"]
    assert PESOS["meteo"] < PESOS["ranking"]


def test_fatores_chave_presentes():
    """A divergência deve vir com fatores-chave que a justificam."""
    r = _calcular_divergencia(_payload(2.6, 1.5, {
        "h2h": {"lider": "A", "diff": 3, "a_wins": 3, "b_wins": 0},
        "piso": {"lider": "A", "diff": 18, "amostra_a": 100, "amostra_b": 100},
    }))
    assert r is not None
    assert len(r["fatores_chave"]) >= 1


def test_estado_expoe_a_composicao_do_peso_aplicado():
    """O relatório deve conseguir auditar cada etapa do peso sem recalcular."""
    r = _calcular_divergencia(_payload(2.6, 1.5, {
        "piso": {"lider": "A", "diff": 15, "amostra_a": 20, "amostra_b": 20},
    }))
    assert r is not None
    st = r["fatores_status"]["piso"]
    assert st["peso_base_configurado"] == PESOS["piso"]
    assert st["peso_base_aplicado"] == PESOS["piso"]
    assert st["multiplicador_forca"] == 1.0
    # ATUALIZADO (22/08/2026): confiança de amostra passou a usar raiz
    # quadrada (peça de valor). Para amostra efetiva 15 (min de 20/20 com
    # o cap interno), sqrt(15/30)=0.707, não 0.5 da rampa linear antiga.
    assert st["confianca_amostra"] == 0.707
    assert st["peso_antes_cap"] == 5.657
    assert st["peso_efetivo"] == 5.657
    assert st["direcao_impacto"] == "a"


def test_mudanca_piso_nao_pontua_quando_faltam_dados_de_um_lado():
    r = _calcular_divergencia(_payload(2.1, 1.8, {
        "ranking": {"lider": "A", "diff": 30},
    }, surface_transition_a={"em_transicao": True, "piso_recente_dominante": "Clay"}))
    assert r is not None
    status = r["fatores_status"]["mudanca_piso"]
    assert status["disponivel"] is False
    assert "dados em falta" in status["motivo_exclusao"]
    assert not status.get("peso_efetivo")


def test_regresso_nao_pontua_quando_faltam_dias_de_um_lado():
    r = _calcular_divergencia(_payload(2.1, 1.8, {
        "ranking": {"lider": "A", "diff": 30},
    }, fatigue_signal_a={"days_since_last_match": 70}, fatigue_signal_b={}))
    assert r is not None
    status = r["fatores_status"]["lesao"]
    assert status["disponivel"] is False
    assert "dados em falta" in status["motivo_exclusao"]
    assert not status.get("peso_efetivo")


# ---------- runner standalone ----------
def test_double_counting_cap_familia():
    """A família 'força base' (ranking+época+forma+serviço) não deve dominar só
    por acumular fatores correlacionados. Com A a liderar os 4 mas B a liderar
    o matchup (piso+h2h), o índice de A não deve disparar."""
    r = _calcular_divergencia(_payload(1.5, 2.6, {
        "ranking": {"lider": "A", "diff": 30},
        "epoca_atual": {"lider": "A", "diff": 15},
        "forma_recente": {"lider": "A", "diff": 20},
        "servico": {"lider": "A", "diff": 8},
        "piso": {"lider": "B", "diff": 15, "amostra_a": 100, "amostra_b": 100},
        "h2h": {"lider": "B", "diff": 3, "a_wins": 0, "b_wins": 3},
    }))
    assert r is not None
    # o cap impede que A dispare para valores muito altos só por acumular
    # 4 fatores da mesma família; o matchup de B tem de contrabalançar
    assert r["indice_evidencia_a"] < 65


if __name__ == "__main__":
    testes = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passou = falhou = 0
    for t in testes:
        try:
            t()
            print(f"  PASS {t.__name__}")
            passou += 1
        except AssertionError as e:
            print(f"  FAIL {t.__name__} — FALHOU: {e}")
            falhou += 1
        except Exception as e:
            print(f"  ERROR {t.__name__} — ERRO: {e}")
            falhou += 1
    print(f"\n{passou} passaram, {falhou} falharam (de {len(testes)} testes)")
    sys.exit(1 if falhou else 0)
