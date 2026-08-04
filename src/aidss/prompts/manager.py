"""Prompt Manager and Prompt Composer (Section 11).

The Manager owns which template version is active; the Composer turns a
template plus context into the messages the gateway sends.

Templates resolve from the database first and fall back to the built-in
catalog. That ordering matters in both directions: a fresh install works
before anyone seeds anything, and an operator can edit a prompt in the
database without a redeploy. Either way the version that was used is recorded
on the message, so an output stays explainable (Section 11.2).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.db.models import PromptTemplate as PromptTemplateRow
from aidss.domain.types import ChatMessage
from aidss.prompts import catalog
from aidss.prompts.catalog import PromptTemplate


class PromptNotFoundError(LookupError):
    """No template with that name exists in the database or the catalog."""


@dataclass(frozen=True, slots=True)
class ComposedPrompt:
    messages: list[ChatMessage]
    template_name: str
    template_version: str


def schema_hint(model: type[BaseModel]) -> str:
    """A compact description of the expected JSON, for the system prompt.

    Pydantic's full JSON Schema is accurate but verbose, and every token of it
    is paid for on each call. This renders field names, types, and constraints
    only - enough to shape the answer, and cheap.
    """
    lines: list[str] = ["{"]
    for name, field in model.model_fields.items():
        annotation = field.annotation
        type_name = getattr(annotation, "__name__", str(annotation))
        # StrEnum fields: list the permitted values, otherwise the model has to
        # guess at the vocabulary and will invent its own.
        choices = getattr(annotation, "__members__", None)
        if choices:
            rendered = " | ".join(f'"{m.value}"' for m in choices.values())
        else:
            rendered = {
                "str": '"..."',
                "float": "0.0",
                "int": "0",
                "bool": "true",
                "list": "[...]",
            }.get(type_name, f"<{type_name}>")
            if str(annotation).startswith("list["):
                rendered = '["...", "..."]'
        suffix = "" if field.is_required() else "   // optional"
        lines.append(f'  "{name}": {rendered},{suffix}')
    lines.append("}")
    return "\n".join(lines)


class PromptManager:
    """Resolves the active version of a template."""

    def __init__(self, session: Session | None = None) -> None:
        self._session = session

    def get(self, name: str) -> PromptTemplate:
        if self._session is not None:
            row = self._session.scalar(
                select(PromptTemplateRow)
                .where(PromptTemplateRow.name == name, PromptTemplateRow.is_active.is_(True))
                .order_by(PromptTemplateRow.created_at.desc())
            )
            if row is not None:
                builtin = catalog.BY_NAME.get(name)
                return PromptTemplate(
                    name=row.name,
                    category=row.category,
                    version=row.version,
                    system=row.template_text,
                    # The database stores the system prompt, which is the part
                    # operators tune. The user-message shape stays in code
                    # because it is bound to the context keys the agents build.
                    user=builtin.user if builtin else "{context}",
                )

        template = catalog.BY_NAME.get(name)
        if template is None:
            raise PromptNotFoundError(
                f"No prompt template named {name!r}. Available: {sorted(catalog.BY_NAME)}"
            )
        return template

    def seed_catalog(self) -> int:
        """Persist any built-in template version not already stored.

        Idempotent: re-running adds nothing. Existing rows are never modified,
        because an operator's edit must not be silently reverted by a deploy.
        """
        if self._session is None:
            raise RuntimeError("seed_catalog requires a database session")

        existing = {
            (row.name, row.version)
            for row in self._session.scalars(select(PromptTemplateRow)).all()
        }
        added = 0
        for template in catalog.ALL_TEMPLATES:
            if (template.name, template.version) in existing:
                continue
            self._session.add(
                PromptTemplateRow(
                    name=template.name,
                    category=template.category,
                    template_text=template.system,
                    version=template.version,
                    is_active=True,
                )
            )
            added += 1
        self._session.flush()
        return added


class PromptComposer:
    """Template + context -> the exact messages sent to the model."""

    def __init__(self, manager: PromptManager | None = None) -> None:
        self.manager = manager or PromptManager()

    def compose(
        self,
        template_name: str,
        context: dict[str, Any],
        output_model: type[BaseModel],
        *,
        corrective_instruction: str | None = None,
    ) -> ComposedPrompt:
        template = self.manager.get(template_name)
        system = template.render_system(schema_hint(output_model))
        user = template.user.format(**{k: _render(v) for k, v in context.items()})

        messages = [
            ChatMessage(role="system", content=system),
            ChatMessage(role="user", content=user),
        ]
        if corrective_instruction:
            # Appended as a separate turn rather than edited into the original
            # prompt, so the retry reads as a correction to a specific answer.
            messages.append(ChatMessage(role="user", content=corrective_instruction))

        return ComposedPrompt(
            messages=messages,
            template_name=template.name,
            template_version=template.version,
        )


def _render(value: Any) -> str:
    """Render a context value for prompt interpolation."""
    if isinstance(value, str):
        return value
    if value is None:
        return "(not available)"
    if isinstance(value, (dict, list)):
        return json.dumps(value, indent=2, default=str, ensure_ascii=False)
    return str(value)
