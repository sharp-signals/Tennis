"""Providers de LLM com bloqueio explícito de chamadas pagas.

Este módulo não cria clientes externos durante o import. O cliente Anthropic só
é instanciado quando o modo ``anthropic`` está ativo, a execução paga foi
explicitamente autorizada e ``generate`` é chamado.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from .config import (
    ALLOW_PAID_LLM,
    CLAUDE_MODEL,
    FLAG_UNCERTAIN,
    LLM_MODE,
    LLM_POLICY,
)


class PaidLLMDisabledError(RuntimeError):
    """Uma chamada paga foi pedida sem autorização explícita."""


class MissingLLMCredentialError(RuntimeError):
    """Falta a credencial necessária para o provider configurado."""


@dataclass(frozen=True)
class ProviderResponse:
    """Resposta normalizada, independente do SDK do fornecedor."""

    text: str
    stop_reason: str | None = None
    usage: dict[str, int] = field(default_factory=dict)


class LLMProvider(ABC):
    """Contrato mínimo para providers de geração narrativa."""

    name = "base"
    persist_cache = False

    @abstractmethod
    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        metadata: dict[str, Any] | None = None,
    ) -> ProviderResponse:
        """Gera uma resposta textual normalizada."""


class AnthropicProvider(LLMProvider):
    """Provider Anthropic com cliente lazy e guarda de custo."""

    name = "anthropic"
    persist_cache = True

    def __init__(self, *, allow_paid: bool) -> None:
        self._allow_paid = allow_paid
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if not self._allow_paid:
            raise PaidLLMDisabledError(
                "Chamada Anthropic bloqueada. Define ALLOW_PAID_LLM=1 apenas "
                "no workflow de produção que deve efetivamente gastar créditos."
            )

        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise MissingLLMCredentialError(
                "LLM_MODE=anthropic requer ANTHROPIC_API_KEY."
            )

        if self._client is None:
            # Import lazy: modo mock/disabled não carrega nem instancia o SDK.
            import anthropic

            self._client = anthropic.Anthropic(api_key=api_key)
        return self._client

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        metadata: dict[str, Any] | None = None,
    ) -> ProviderResponse:
        client = self._get_client()
        # REVERTIDO (11/08/2026): o prefill assistant "{" partiu 100% das
        # chamadas reais — "This model does not support assistant message
        # prefill. The conversation must end with a user message." (erro
        # 400 confirmado em log real, 30/30 chamadas falharam). O modelo em
        # uso não aceita prefill (comum em modelos com extended thinking).
        # Mantido o resto do reforço (prompt + max_tokens menor).
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=max_tokens,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_prompt}],
        )

        usage_obj = getattr(response, "usage", None)
        usage = {
            "input_tokens": int(getattr(usage_obj, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(usage_obj, "output_tokens", 0) or 0),
            "cache_read_input_tokens": int(
                getattr(usage_obj, "cache_read_input_tokens", 0) or 0
            ),
            "cache_creation_input_tokens": int(
                getattr(usage_obj, "cache_creation_input_tokens", 0) or 0
            ),
        }
        text = "".join(
            block.text
            for block in response.content
            if getattr(block, "type", None) == "text"
        ).strip()
        return ProviderResponse(
            text=text,
            stop_reason=getattr(response, "stop_reason", None),
            usage=usage,
        )


class MockProvider(LLMProvider):
    """Provider determinístico para desenvolvimento sem chamadas externas."""

    name = "mock"
    persist_cache = False

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        metadata: dict[str, Any] | None = None,
    ) -> ProviderResponse:
        match = metadata or {}
        player_a = match.get("player_a", "Jogador A")
        player_b = match.get("player_b", "Jogador B")
        result = {
            "flag": FLAG_UNCERTAIN,
            "signal_strength": 0,
            "confidence_reason": (
                "Resultado MOCK: nenhuma chamada à API da Anthropic foi efetuada."
            ),
            "summary_line": f"[MOCK] {player_a} vs {player_b} — análise sem API.",
            "key_points": [
                "Resultado gerado pelo provider mock para validar o pipeline sem custos.",
                "Os dados factuais do relatório mantêm-se separados desta síntese simulada.",
            ],
            "discrepancies": [],
            "verdict": (
                "Modo de desenvolvimento ativo; não foi produzida interpretação de mercado."
            ),
        }
        return ProviderResponse(text=json.dumps(result, ensure_ascii=False))


class DisabledProvider(LLMProvider):
    """Provider sem geração narrativa, útil para pipelines exclusivamente Python."""

    name = "disabled"
    persist_cache = False

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        metadata: dict[str, Any] | None = None,
    ) -> ProviderResponse:
        match = metadata or {}
        player_a = match.get("player_a", "Jogador A")
        player_b = match.get("player_b", "Jogador B")
        result = {
            "flag": FLAG_UNCERTAIN,
            "signal_strength": 0,
            "confidence_reason": "Geração narrativa desativada por configuração.",
            "summary_line": f"{player_a} vs {player_b} — síntese LLM desativada.",
            "key_points": [
                "A análise narrativa não foi executada; consultar os dados factuais."
            ],
            "discrepancies": [],
            "verdict": "Síntese indisponível porque LLM_MODE=disabled.",
        }
        return ProviderResponse(text=json.dumps(result, ensure_ascii=False))


_DEFAULT_PROVIDER: LLMProvider | None = None


def _build_provider(mode: str, *, allow_paid: bool) -> LLMProvider:
    normalized = mode.strip().lower()
    if normalized == "anthropic":
        return AnthropicProvider(allow_paid=allow_paid)
    if normalized == "mock":
        return MockProvider()
    if normalized == "disabled":
        return DisabledProvider()
    raise ValueError(
        f"LLM_MODE inválido: {mode!r}. Valores permitidos: anthropic, mock, disabled."
    )


def get_llm_provider(
    mode: str | None = None,
    *,
    allow_paid: bool | None = None,
) -> LLMProvider:
    """Obtém o provider configurado.

    A chamada sem argumentos reutiliza uma instância singleton. Argumentos
    explícitos criam uma instância isolada, o que facilita testes offline.
    """

    global _DEFAULT_PROVIDER

    if mode is not None or allow_paid is not None:
        return _build_provider(
            mode or LLM_MODE,
            allow_paid=ALLOW_PAID_LLM if allow_paid is None else allow_paid,
        )

    if _DEFAULT_PROVIDER is None:
        # A política "never" prevalece sobre o provider configurado. A política
        # "selective" será aplicada pelo motor determinístico na fase seguinte;
        # até lá mantém o comportamento de síntese em todos os jogos.
        effective_mode = "disabled" if LLM_POLICY == "never" else LLM_MODE
        _DEFAULT_PROVIDER = _build_provider(
            effective_mode,
            allow_paid=ALLOW_PAID_LLM,
        )
    return _DEFAULT_PROVIDER
