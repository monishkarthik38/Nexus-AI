from langdetect import DetectorFactory, LangDetectException, detect_langs

DetectorFactory.seed = 0

UNKNOWN_LANGUAGE = "und"


def detect_language(text: str) -> str:
    """Return a likely ISO language tag, or `und` when the input is too short/ambiguous."""
    normalized = " ".join(text.split())
    if len(normalized) < 12:
        return UNKNOWN_LANGUAGE

    try:
        candidates = detect_langs(normalized[:5000])
    except LangDetectException:
        return UNKNOWN_LANGUAGE

    if not candidates or candidates[0].prob < 0.65:
        return UNKNOWN_LANGUAGE
    return candidates[0].lang
