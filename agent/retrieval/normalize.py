"""String normalization for cursed event names.

The taxonomy fires the same concept under wildly different surface forms:
`evt_chkout_init`, `ChkoutInit`, `chckt_strt`, `checkout-start`, `track_begin_checkout`.
Before any signal compares two names, we fold away the noise that carries no meaning —
SDK prefixes, version suffixes, separator style, camelCase boundaries, casing — while
*preserving* the abbreviation damage (`chkout`, `strt`), which is exactly what the
char-ngram / fuzzy signals are meant to see through.

Pure and deterministic. No corpus, no gold.
"""

from __future__ import annotations

import re

# Instrumentation prefixes that mean "this is an event", not which event.
_PREFIXES = ("evt_", "event_", "track_", "log_", "e_", "ev_", "fb_", "ga_")
# Version / migration suffixes.
_SUFFIXES = ("_v1", "_v2", "_v3", "_ios", "_android", "_new", "_old", "_legacy")

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_SEP = re.compile(r"[^a-z0-9]+")


def _split_camel(name: str) -> str:
    return _CAMEL.sub(" ", name)


def normalize(name: str) -> str:
    """Fold a surface name to a canonical whitespace-joined token string.

    `EvtChkoutInit_v1` -> `chkout init`. Abbreviations are deliberately kept intact.
    """
    s = _split_camel(name).lower()
    s = _SEP.sub(" ", s).strip()
    # strip a leading instrumentation prefix (post-normalization, space-separated)
    for p in _PREFIXES:
        pw = p.rstrip("_")
        if s == pw or s.startswith(pw + " "):
            s = s[len(pw):].strip()
            break
    # strip trailing version/platform suffixes
    changed = True
    while changed:
        changed = False
        for suf in _SUFFIXES:
            sw = suf.lstrip("_")
            if s.endswith(" " + sw):
                s = s[: -(len(sw) + 1)].strip()
                changed = True
    return s or _SEP.sub(" ", name.lower()).strip()


_PLACEHOLDER = re.compile(
    r"(^|_)(test|beta|v1|v2|v3|old|legacy|deprecated|tmp|sample)(_|$)|do_not_use",
    re.IGNORECASE,
)


def is_placeholder_name(name: str) -> bool:
    """True for dead/migration placeholder names (`beta_checkout_v1`,
    `test_event_do_not_use`). Their surface strings lie about their concept, so they
    are excluded as lexical anchors — safe because such names never fire in a warehouse.
    Purely lexical; no corpus or gold."""
    return _PLACEHOLDER.search(name) is not None


def tokens(name: str) -> list[str]:
    """Normalized whitespace tokens — the unit BM25 / word-overlap signals consume."""
    n = normalize(name)
    return n.split() if n else []


def charstream(name: str) -> str:
    """Normalized, separator-collapsed char stream for char-ngram vectorization.

    `chckt_strt` -> `chcktstrt`. Removing separators lets ngrams span token bounds so
    `checkout` and `chk out` share ngrams.
    """
    return normalize(name).replace(" ", "")


if __name__ == "__main__":
    samples = [
        "evt_chkout_init", "ChkoutInit", "chckt_strt", "checkout-start",
        "track_begin_checkout", "BeginCheckout", "appOpen", "sssn_strt",
        "add_itm_to_crt", "prdct_dtl_vw", "v1_purchase", "test_event_do_not_use",
    ]
    for s in samples:
        print(f"  {s:26s} -> norm={normalize(s)!r:24s} stream={charstream(s)!r}")
