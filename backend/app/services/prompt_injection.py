import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PromptInjectionRule:
    name: str
    pattern: re.Pattern[str]


class PromptInjectionScanner:
    """Detect prompt-injection style instructions in untrusted knowledge documents."""

    rules: tuple[PromptInjectionRule, ...] = (
        PromptInjectionRule(
            "instruction_override",
            re.compile(
                r"(?i)\b(ignore|disregard|forget)\s+"
                r"(all\s+)?(previous|prior|above|earlier|system|developer)\s+"
                r"(instructions?|rules?|messages?)\b"
                r"|忽略(之前|以上|此前|所有|系统|开发者).{0,12}(指令|规则|要求|消息)"
                r"|无视(之前|以上|此前|所有|系统|开发者).{0,12}(指令|规则|要求|消息)"
            ),
        ),
        PromptInjectionRule(
            "role_reassignment",
            re.compile(
                r"(?i)\b(you\s+are\s+now|act\s+as|pretend\s+to\s+be)\b"
                r"|你现在是|请扮演|扮演一个|角色设定"
            ),
        ),
        PromptInjectionRule(
            "prompt_exfiltration",
            re.compile(
                r"(?i)\b(reveal|print|show|leak|dump)\s+"
                r"(your\s+)?(system\s+prompt|developer\s+message|hidden\s+instructions?|prompt)\b"
                r"|\b(system\s+prompt|developer\s+message|hidden\s+instructions?)\b"
                r"|泄露.{0,8}(提示词|系统提示|开发者消息)"
                r"|输出.{0,8}(提示词|系统提示|开发者消息)"
                r"|系统提示|开发者消息|隐藏指令"
            ),
        ),
        PromptInjectionRule(
            "policy_bypass",
            re.compile(
                r"(?i)\b(do\s+not\s+follow|bypass|jailbreak|disable\s+safety)\b"
                r"|不要遵守|绕过安全|越狱|关闭安全"
            ),
        ),
        PromptInjectionRule(
            "tool_or_code_execution",
            re.compile(
                r"(?i)\b(run|execute)\s+(shell|bash|powershell|python|sql|command|code)\b"
                r"|执行以下(命令|代码|指令)"
                r"|运行(shell|bash|powershell|python|sql|命令|代码)"
            ),
        ),
    )

    def scan_text(self, text: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for rule in self.rules:
            matches = rule.pattern.findall(text)
            if matches:
                counts[rule.name] = len(matches)
        return counts

    def scan_texts(self, texts: list[str]) -> dict[str, int]:
        total: dict[str, int] = {}
        for text in texts:
            counts = self.scan_text(text)
            for name, count in counts.items():
                total[name] = total.get(name, 0) + count
        return total


def get_prompt_injection_scanner() -> PromptInjectionScanner:
    return PromptInjectionScanner()
