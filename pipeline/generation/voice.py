"""Editorial voice validation — flags guideline violations in draft posts."""

LAZY_ADJECTIVES = [
    "unprecedented", "important", "critical", "crucial",
    "significant", "transformative", "revolutionary",
]

FLUFF_PHRASES = [
    "in an era of", "it is worth noting", "it goes without saying",
    "needless to say", "at the end of the day", "in today's world",
]

DATA_GAP_PHRASES = [
    "no data available", "data not available", "not yet publicly",
    "data gap", "no figures", "not publicly confirmed",
    "data is limited", "data was not", "information is not available",
    "figures are not yet", "not yet released", "no real-time",
    "data limitations", "absence of data", "absence of real-time",
]


def check_voice(draft: str) -> list[str]:
    """Return a list of editorial guideline violations found in the draft."""
    violations = []
    lower = draft.lower()
    for adj in LAZY_ADJECTIVES:
        if adj in lower:
            violations.append(f"Lazy adjective: '{adj}' — earn it or remove it")
    for phrase in FLUFF_PHRASES:
        if phrase in lower:
            violations.append(f"Fluff phrase: '{phrase}' — cut it")
    for phrase in DATA_GAP_PHRASES:
        if phrase in lower:
            violations.append(
                f"Data gap language: '{phrase}' — omit the topic instead of discussing missing data"
            )
    return violations
