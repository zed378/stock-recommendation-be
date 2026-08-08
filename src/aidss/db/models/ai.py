"""Group E - AI Conversation, Prompt, Knowledge Base (Section 6.2).

``ai_providers`` plus ``ai_messages.provider_id`` answer the question "which
model produced this output?" - the prerequisite for reproducibility and for
multi-provider cost tracking (Section 16.9).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aidss.db.base import Base, Embedding, new_uuid, utcnow


class AIProviderConfig(Base):
    """Configured AI providers - the basis of multi-model routing (Section 16.10).

    A row points at a registered adapter through ``adapter_name`` and carries
    everything needed to reach it: its own base URL, model, timeout and
    credential. That last one is a deliberate change from "credentials stay in
    the environment": an operator has to be able to add a model from the admin
    screen, and a row whose key came from `.env` would mean every provider
    shares one key - which is the same as having one provider.

    The credential is encrypted at rest (`aidss.security.secrets`) and never
    returned by the API; `api_key_hint` is what the interface shows so a
    reader can tell *which* key is stored without being told the key.
    """

    __tablename__ = "ai_providers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    adapter_name: Mapped[str] = mapped_column(String(80), default="openai_compatible")
    base_url: Mapped[str | None] = mapped_column(String(500), default=None)
    default_model: Mapped[str | None] = mapped_column(String(120), default=None)
    role: Mapped[str] = mapped_column(String(40), default="general")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    #: Position in the fallback chain (Section 16.10); lower wins.
    priority: Mapped[int] = mapped_column(default=100)
    #: Fernet ciphertext, or null when this provider needs no key - which is
    #: the normal case for Ollama, vLLM and LM Studio.
    api_key_ciphertext: Mapped[str | None] = mapped_column(Text, default=None)
    #: What the interface shows in place of the key.
    api_key_hint: Mapped[str | None] = mapped_column(String(40), default=None)
    #: Per provider, because they differ by an order of magnitude: a hosted API
    #: answers in seconds and a self-hosted model on modest hardware needs
    #: minutes for the same prompt.
    timeout_seconds: Mapped[float | None] = mapped_column(default=None)
    #: Set by the operator when inference runs on infrastructure they control
    #: but is published at a public domain - indistinguishable from a
    #: third-party API by inspection, and the difference decides whether
    #: personal financial data may be sent there (Section 26).
    self_hosted: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Result of the last reachability check, so a provider that stopped
    #: answering is distinguishable from one nobody has tried.
    last_status: Mapped[str | None] = mapped_column(String(20), default=None)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    last_checked_at: Mapped[datetime | None] = mapped_column(default=None)
    #: Pricing for cost estimates (Section 16.9), per 1K tokens.
    input_cost_per_1k: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), default=None)
    output_cost_per_1k: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AIConversation(Base):
    __tablename__ = "ai_conversations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    context_type: Mapped[str] = mapped_column(String(60), default="free_chat")
    title: Mapped[str | None] = mapped_column(String(200), default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    messages: Mapped[list[AIMessage]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class AIMessage(Base):
    __tablename__ = "ai_messages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_conversations.id", ondelete="CASCADE"), index=True
    )
    agent_name: Mapped[str | None] = mapped_column(String(60), default=None)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    provider_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_providers.id", ondelete="SET NULL"), default=None
    )
    model_used: Mapped[str | None] = mapped_column(String(120), default=None)
    prompt_template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompt_templates.id", ondelete="SET NULL"), default=None
    )
    prompt_tokens: Mapped[int] = mapped_column(default=0)
    completion_tokens: Mapped[int] = mapped_column(default=0)
    cost_estimate: Mapped[Decimal | None] = mapped_column(Numeric(14, 6), default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    conversation: Mapped[AIConversation] = relationship(back_populates="messages")

    __table_args__ = (Index("ix_ai_message_created", "created_at"),)


class PromptTemplate(Base):
    """Versioning is mandatory - every ai_message records the version it used
    (Section 15.2), which is what makes an output reproducible."""

    __tablename__ = "prompt_templates"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(60))
    template_text: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(String(40))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (UniqueConstraint("name", "version", name="uq_prompt_name_version"),)


class KnowledgeBaseDocument(Base):
    __tablename__ = "knowledge_base"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    title: Mapped[str] = mapped_column(String(300))
    source: Mapped[str | None] = mapped_column(String(500), default=None)
    category: Mapped[str | None] = mapped_column(String(80), default=None)
    storage_uri: Mapped[str | None] = mapped_column(String(1000), default=None)
    uploaded_at: Mapped[datetime] = mapped_column(default=utcnow)

    chunks: Mapped[list[KnowledgeChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_base.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(default=0)
    chunk_text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Embedding(), default=None)
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict)

    document: Mapped[KnowledgeBaseDocument] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("knowledge_base_id", "chunk_index", name="uq_knowledge_chunk_index"),
    )
