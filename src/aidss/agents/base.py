"""Agent definitions and the runner that executes them (Section 5).

Agents are declarative: each states which template it uses, which schema its
answer must satisfy, how much reasoning it needs, and how to turn the shared
context into prompt variables. Everything procedural - composing, calling,
validating, retrying, recording - happens once in ``AgentRunner``.

That split is what keeps the guarantees uniform. Validation and the
execution-language check cannot be forgotten by an individual agent, because
no individual agent performs them.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.orm import Session

from aidss.agents.memory import InvestorMemory
from aidss.db.models import AIMessage
from aidss.llm.cost import Usage
from aidss.llm.gateway import LLMGateway, LLMRequest
from aidss.llm.router import Sensitivity, TaskComplexity
from aidss.prompts.language import OutputLanguage
from aidss.prompts.manager import PromptComposer
from aidss.prompts.schemas import AgentOutput
from aidss.prompts.validator import ValidationFailure, validate


class AgentContext(Protocol):
    """What every agent context must provide.

    Asset analysis and portfolio analysis assemble different evidence, but both
    carry the investor's memory and both flow through the same runner. Typing
    the runner against this rather than one concrete context is what lets a
    portfolio agent reuse the validation, retry, and recording path unchanged.
    """

    memory: InvestorMemory


class Agent(ABC):
    """One specialised analyst in the multi-agent flow."""

    name: str
    template_name: str
    output_model: type[AgentOutput]
    complexity: TaskComplexity = TaskComplexity.STANDARD
    #: Agents that read portfolio positions or journal entries override this,
    #: which forces routing to self-hosted inference in high-privacy mode.
    sensitivity: Sensitivity = Sensitivity.PUBLIC

    @abstractmethod
    def prompt_context(self, context: AgentContext) -> dict[str, Any]:
        """Turn the shared context into this template's variables."""

    def is_applicable(self, context: AgentContext) -> bool:
        """Whether running this agent makes sense given the evidence.

        Skipping is a real outcome, not a failure. Asking an analyzer to
        comment on data that does not exist produces fluent, ungrounded text -
        the exact failure the AI-quality risk in Section 17 describes.
        """
        return True

    def skip_reason(self, context: AgentContext) -> str:
        return "not applicable to the available data"


@dataclass(frozen=True, slots=True)
class AgentRun:
    """The result of running one agent."""

    agent: str
    output: AgentOutput
    usage: Usage
    template_name: str
    template_version: str
    #: 1 when the first answer validated; higher means a corrective retry ran.
    attempts: int
    fallbacks_used: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AgentSkip:
    agent: str
    reason: str


class ConversationRecorder:
    """Writes every model exchange to ``ai_messages`` (Sections 8.2, 12.9).

    Recording provider, model, prompt version, tokens, and estimated cost is
    what lets someone later ask "which model produced this, from which prompt,
    and what did it cost?" and get an answer.
    """

    def __init__(self, session: Session, conversation_id: uuid.UUID) -> None:
        self._session = session
        self._conversation_id = conversation_id

    def record(self, run: AgentRun, *, prompt_text: str, response_text: str) -> None:
        self._session.add(
            AIMessage(
                conversation_id=self._conversation_id,
                agent_name=run.agent,
                role="user",
                content=prompt_text,
                model_used=run.usage.model,
                prompt_tokens=run.usage.prompt_tokens,
                completion_tokens=0,
            )
        )
        self._session.add(
            AIMessage(
                conversation_id=self._conversation_id,
                agent_name=run.agent,
                role="assistant",
                content=response_text,
                model_used=run.usage.model,
                prompt_tokens=0,
                completion_tokens=run.usage.completion_tokens,
                cost_estimate=run.usage.cost_estimate,
            )
        )
        self._session.flush()


class AgentRunner:
    """Executes an agent: compose, call, validate, retry once, record."""

    def __init__(
        self,
        gateway: LLMGateway,
        composer: PromptComposer | None = None,
        *,
        recorder: ConversationRecorder | None = None,
        max_validation_retries: int = 1,
        high_privacy: bool = False,
    ) -> None:
        self._gateway = gateway
        self._composer = composer or PromptComposer()
        self._recorder = recorder
        self._max_validation_retries = max_validation_retries
        self._high_privacy = high_privacy

    @property
    def language(self) -> OutputLanguage:
        """The language the prompts ask for, so callers can record it.

        Read off the composer rather than from settings again: the two could
        drift, and what a stored analysis needs is the language it was actually
        asked to write in.
        """
        return self._composer.language

    def run(
        self,
        agent: Agent,
        context: AgentContext,
        *,
        extra_instruction: str | None = None,
    ) -> AgentRun:
        """Run one agent.

        ``extra_instruction`` seeds the corrective turn on the first attempt.
        It exists so a caller enforcing rules of its own - the Recommendation
        Engine checking Section 5.4 - can feed a correction back through this
        same path rather than building a second retry mechanism beside it.
        """
        variables = agent.prompt_context(context)
        sensitivity = (
            Sensitivity.SENSITIVE
            if self._high_privacy or agent.sensitivity is Sensitivity.SENSITIVE
            else Sensitivity.PUBLIC
        )

        corrective: str | None = extra_instruction
        last_failure: ValidationFailure | None = None

        for attempt in range(1, self._max_validation_retries + 2):
            prompt = self._composer.compose(
                agent.template_name,
                variables,
                agent.output_model,
                corrective_instruction=corrective,
            )
            response = self._gateway.complete(
                LLMRequest(
                    messages=prompt.messages,
                    complexity=agent.complexity,
                    sensitivity=sensitivity,
                    expects_json=True,
                    agent=agent.name,
                )
            )

            try:
                output, _ = validate(response.content, agent.output_model)
            except ValidationFailure as exc:
                # Feed the specific problem back rather than simply asking
                # again: an identical prompt usually produces an identical
                # mistake, so a blind retry just costs a second call.
                last_failure = exc
                corrective = exc.corrective_instruction
                continue

            run = AgentRun(
                agent=agent.name,
                output=output,
                usage=response.usage,
                template_name=prompt.template_name,
                template_version=prompt.template_version,
                attempts=attempt,
                fallbacks_used=response.fallbacks_used,
            )
            if self._recorder is not None:
                self._recorder.record(
                    run,
                    prompt_text=prompt.messages[-1].content,
                    response_text=response.content,
                )
            return run

        assert last_failure is not None
        raise last_failure
