"""Prompt engineering layer (Phase 4, Section 11)."""

from aidss.prompts.catalog import ALL_TEMPLATES, BY_NAME, CATALOG_VERSION, PromptTemplate
from aidss.prompts.language import (
    LANGUAGE_RULE,
    LanguageViolation,
    find_execution_language,
    is_compliant,
)
from aidss.prompts.manager import (
    ComposedPrompt,
    PromptComposer,
    PromptManager,
    PromptNotFoundError,
    schema_hint,
)
from aidss.prompts.schemas import (
    OUTPUT_MODELS,
    AgentOutput,
    Bias,
    DataSufficiency,
    FundamentalOutput,
    MarketContextOutput,
    NewsSentimentOutput,
    SynthesisOutput,
    TechnicalOutput,
)
from aidss.prompts.validator import ValidationFailure, ValidationReport, validate

__all__ = [
    "ALL_TEMPLATES",
    "BY_NAME",
    "CATALOG_VERSION",
    "LANGUAGE_RULE",
    "OUTPUT_MODELS",
    "AgentOutput",
    "Bias",
    "ComposedPrompt",
    "DataSufficiency",
    "FundamentalOutput",
    "LanguageViolation",
    "MarketContextOutput",
    "NewsSentimentOutput",
    "PromptComposer",
    "PromptManager",
    "PromptNotFoundError",
    "PromptTemplate",
    "SynthesisOutput",
    "TechnicalOutput",
    "ValidationFailure",
    "ValidationReport",
    "find_execution_language",
    "is_compliant",
    "schema_hint",
    "validate",
]
