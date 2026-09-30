"""Safe, bounded diagnostic candidates; never save arbitrary model output."""
from .names import PROVINCES

_VOCABULARY = frozenset(PROVINCES) | {"A", "F", "H", "S", "C", "-", "R", "B", "D", "VIA", "WAIVE"} | {
    f"{province}/{coast}" for province in PROVINCES for coast in ("NC", "SC", "EC", "WC")
}


def safe_order_candidate(value) -> dict:
    """This validates the logging vocabulary, not geographic order legality.

    Invalid moves using known map words are precisely the candidates we need
    to diagnose. Coast tokens match completely, never by a partial split.
    """
    text = " ".join(str(value).upper().replace("-", " - ").split())
    if text.isascii() and text.isdigit() and len(text) <= 6:
        return {"candidate_index": int(text)}
    if len(text) <= 64:
        words = text.split()
        if 3 <= len(words) <= 9 and words[0] in {"A", "F"} and all(w in _VOCABULARY for w in words):
            return {"candidate": text}
    return {"candidate_omitted": "not_bounded_game_vocabulary"}
