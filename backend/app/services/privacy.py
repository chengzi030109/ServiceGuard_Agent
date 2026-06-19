import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel


@dataclass(frozen=True)
class RedactionRule:
    name: str
    pattern: re.Pattern[str]
    replacement: str


class PrivacyRedactor:
    """Redact common PII before model calls, responses, and persistence."""

    rules: tuple[RedactionRule, ...] = (
        RedactionRule("phone", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[PHONE_REDACTED]"),
        RedactionRule(
            "email",
            re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
            "[EMAIL_REDACTED]",
        ),
        RedactionRule(
            "id_card",
            re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"),
            "[ID_CARD_REDACTED]",
        ),
        RedactionRule(
            "openai_key",
            re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
            "[OPENAI_KEY_REDACTED]",
        ),
        RedactionRule(
            "jwt",
            re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
            "[JWT_REDACTED]",
        ),
        RedactionRule(
            "bearer_token",
            re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/\-]+=*"),
            "Bearer [TOKEN_REDACTED]",
        ),
        RedactionRule(
            "secret_field",
            re.compile(
                r"(?i)\b(api[_-]?key|secret|token|password|passwd|pwd)"
                r"\s*[:=]\s*['\"]?[A-Za-z0-9_\-./+=]{6,}['\"]?"
            ),
            r"\1=[SECRET_REDACTED]",
        ),
        RedactionRule(
            "bank_card",
            re.compile(r"(?<![A-Za-z0-9])(?:\d[ -]?){15,19}(?![A-Za-z0-9])"),
            "[BANK_CARD_REDACTED]",
        ),
    )

    def redact_text(self, text: str) -> str:
        redacted, _ = self.redact_text_with_counts(text)
        return redacted

    def redact_text_with_counts(self, text: str) -> tuple[str, dict[str, int]]:
        redacted = text
        counts: dict[str, int] = {}
        for rule in self.rules:
            redacted, count = rule.pattern.subn(rule.replacement, redacted)
            if count:
                counts[rule.name] = counts.get(rule.name, 0) + count
        return redacted, counts

    def redact_data(self, data: Any) -> Any:
        if isinstance(data, str):
            return self.redact_text(data)
        if isinstance(data, list):
            return [self.redact_data(item) for item in data]
        if isinstance(data, tuple):
            return tuple(self.redact_data(item) for item in data)
        if isinstance(data, dict):
            return {key: self.redact_data(value) for key, value in data.items()}
        return data

    def redact_model[T: BaseModel](self, model: T, model_type: type[T]) -> T:
        return model_type.model_validate(self.redact_data(model.model_dump()))


def get_privacy_redactor() -> PrivacyRedactor:
    return PrivacyRedactor()
