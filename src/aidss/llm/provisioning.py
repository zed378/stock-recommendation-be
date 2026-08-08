"""Builds a gateway from configuration rather than from code (Section 16.10).

Bindings come from the ``ai_providers`` table when it has rows, so an
administrator can add a model, reorder the fallback chain, or move sensitive
work to self-hosted inference without a redeploy - which is the whole point of
FR-07 applied to the AI layer.

When the table is empty the settings-level provider is used as a single
binding, so a fresh install works before anyone configures anything.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.config import Settings, get_settings
from aidss.db.models import AIProviderConfig
from aidss.llm.gateway import LLMGateway
from aidss.llm.router import ModelRouter, ProviderBinding, TaskComplexity
from aidss.plugins.errors import PluginNotFoundError
from aidss.plugins.registry import get_plugin_class
from aidss.security.secrets import SecretUnreadable, decrypt_secret

logger = logging.getLogger("aidss.llm")

#: Maps a provider's configured role to the complexities it may serve.
#: "general" handles everything, which is the sensible default for a
#: single-provider deployment.
_ROLE_HANDLES: dict[str, frozenset[TaskComplexity]] = {
    "general": frozenset(TaskComplexity),
    "light": frozenset({TaskComplexity.LIGHT}),
    "standard": frozenset({TaskComplexity.LIGHT, TaskComplexity.STANDARD}),
    "reasoning": frozenset({TaskComplexity.STANDARD, TaskComplexity.COMPLEX}),
}

#: Adapters that run on infrastructure we control, and may therefore receive
#: sensitive data in high-privacy mode (Section 16.10, 13).
SELF_HOSTED_ADAPTERS = frozenset({"fixture"})


def provider_from_row(row: AIProviderConfig, settings: Settings):  # noqa: ANN201
    """Build the adapter this row describes, using *this row's* credentials.

    Previously every row was built with `from_settings`, so all of them shared
    the one base URL and key in the environment. Several rows could then differ
    only by model name against a single endpoint - which is not multi-provider,
    it is one provider listed several times, and it made the fallback chain
    unable to fail over to anywhere else.

    Falls back to the environment field by field rather than all-or-nothing, so
    a row that only overrides the model still works on a deployment that
    configured its endpoint the old way.
    """
    # Defaulted here rather than relied on from the column: a row that has not
    # been flushed yet has no column defaults applied, and this builder is used
    # on unsaved rows by the provider test endpoint.
    adapter_name = row.adapter_name or "openai_compatible"
    cls = get_plugin_class("ai", adapter_name)
    if adapter_name != "openai_compatible":
        # Adapters without a URL/key shape (the fixture) are built the plain
        # way; there is nothing per-row to give them.
        factory = getattr(cls, "from_settings", None)
        return factory(settings) if factory else cls()  # type: ignore[call-arg]

    api_key: str | None = settings.ai_api_key
    if row.api_key_ciphertext:
        api_key = decrypt_secret(row.api_key_ciphertext, settings)

    return cls(  # type: ignore[call-arg]
        base_url=row.base_url or settings.ai_base_url,
        api_key=api_key,
        chat_model=row.default_model or settings.ai_chat_model,
        embedding_model=settings.ai_embedding_model,
        timeout=row.timeout_seconds or settings.ai_timeout_seconds,
    )


def _binding_from_row(row: AIProviderConfig, settings: Settings) -> ProviderBinding | None:
    try:
        provider = provider_from_row(row, settings)
    except PluginNotFoundError:
        # A row naming an adapter that no longer exists is skipped rather than
        # fatal: one stale row must not take the whole AI layer offline.
        return None
    except SecretUnreadable:
        # The secret rotated. Skipped for the same reason, and loudly: the row
        # is visibly present and visibly unusable on the admin screen rather
        # than silently authenticating as nobody.
        logger.warning(
            "provider skipped: stored credential could not be decrypted",
            extra={"provider": row.name},
        )
        return None

    return ProviderBinding(
        name=row.name,
        provider=provider,
        model=row.default_model or settings.ai_chat_model,
        handles=_ROLE_HANDLES.get(row.role, _ROLE_HANDLES["general"]),
        priority=row.priority,
        self_hosted=(row.adapter_name or "openai_compatible") in SELF_HOSTED_ADAPTERS
        or bool(row.base_url and _is_local(row.base_url))
        or row.self_hosted,
        input_cost_per_1k=row.input_cost_per_1k or Decimal("0"),
        output_cost_per_1k=row.output_cost_per_1k or Decimal("0"),
    )


def _is_local(base_url: str) -> bool:
    lowered = base_url.lower()
    local_hosts = ("localhost", "127.0.0.1", "::1", "host.docker.internal")
    return any(host in lowered for host in local_hosts)


def build_bindings(
    session: Session | None, settings: Settings | None = None
) -> list[ProviderBinding]:
    settings = settings or get_settings()

    if session is not None:
        rows = session.scalars(
            select(AIProviderConfig)
            .where(AIProviderConfig.is_active.is_(True))
            .order_by(AIProviderConfig.priority)
        ).all()
        bindings = [b for b in (_binding_from_row(row, settings) for row in rows) if b is not None]
        if bindings:
            return bindings

    # Fallback: the single provider named in settings.
    cls = get_plugin_class("ai", settings.ai_provider)
    factory = getattr(cls, "from_settings", None)
    provider = factory(settings) if factory else cls()  # type: ignore[call-arg]
    return [
        ProviderBinding(
            name=settings.ai_provider,
            provider=provider,
            model=settings.ai_chat_model,
            handles=frozenset(TaskComplexity),
            priority=10,
            # Three ways to be self-hosted, in order of how much they can be
            # trusted: the adapter is a local fixture, the URL is demonstrably
            # local, or the operator says so. The last one exists because a
            # self-hosted model published at a public domain is indisting-
            # uishable from a third-party API by inspection - and without it,
            # every agent handling personal financial data is unreachable for
            # anyone whose inference is not literally on localhost.
            self_hosted=settings.ai_provider in SELF_HOSTED_ADAPTERS
            or _is_local(settings.ai_base_url)
            or settings.ai_self_hosted,
        )
    ]


def build_gateway(session: Session | None = None, settings: Settings | None = None) -> LLMGateway:
    return LLMGateway(ModelRouter(build_bindings(session, settings)))
