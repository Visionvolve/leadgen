"""Deterministic Czech vocative (5. pád) name declension with AI fallback.

Provides a 3-tier approach:
1. Lookup table of ~200 common Czech first names
2. Rule-based declension for names not in the table
3. AI fallback (Anthropic Haiku) for unrecognised names

Usage::

    from api.services.czech_vocative import to_vocative

    to_vocative("Jana")   # ("Jano", "lookup")
    to_vocative("Petr")   # ("Petře", "lookup")
    to_vocative("John")   # ("Johne", "rules")
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier 3 — AI result cache (module-level, survives across calls)
# ---------------------------------------------------------------------------
_ai_cache: dict[str, str] = {}

# ---------------------------------------------------------------------------
# Tier 1 — Lookup table: lowercase nominative -> correctly-cased vocative
# ---------------------------------------------------------------------------
VOCATIVE_MAP: dict[str, str] = {
    # ---- Female names ----
    "adéla": "Adélo",
    "alena": "Aleno",
    "alice": "Alice",
    "alžběta": "Alžběto",
    "andrea": "Andreo",
    "aneta": "Aneto",
    "anežka": "Anežko",
    "anna": "Anno",
    "barbora": "Barboro",
    "blanka": "Blanko",
    "božena": "Boženo",
    "dagmar": "Dagmar",
    "dana": "Dano",
    "daniela": "Danielo",
    "denisa": "Deniso",
    "diana": "Diano",
    "dominika": "Dominiko",
    "edita": "Edito",
    "eliška": "Eliško",
    "eva": "Evo",
    "gabriela": "Gabrielo",
    "hana": "Hanko",
    "helena": "Heleno",
    "ilona": "Ilono",
    "irena": "Ireno",
    "iva": "Ivo",
    "ivana": "Ivano",
    "jaroslava": "Jaroslavo",
    "iveta": "Iveto",
    "jana": "Jano",
    "jarmila": "Jarmilo",
    "jiřina": "Jiřino",
    "jitka": "Jitko",
    "jolana": "Jolano",
    "kamila": "Kamilo",
    "karolína": "Karolíno",
    "kateřina": "Kateřino",
    "klára": "Kláro",
    "kristýna": "Kristýno",
    "květa": "Květo",
    "lenka": "Lenko",
    "libuše": "Libuše",
    "linda": "Lindo",
    "lucie": "Lucie",
    "ludmila": "Ludmilo",
    "marcela": "Marcelo",
    "marie": "Marie",
    "markéta": "Markéto",
    "marta": "Marto",
    "martina": "Martino",
    "michaela": "Michaelo",
    "milada": "Milado",
    "milena": "Mileno",
    "miroslava": "Miroslavo",
    "monika": "Moniko",
    "nadia": "Nadio",
    "natálie": "Natálie",
    "naděžda": "Naděždo",
    "nikola": "Nikolo",
    "olga": "Olgo",
    "pavla": "Pavlo",
    "pavlína": "Pavlíno",
    "petra": "Petro",
    "radka": "Radko",
    "renata": "Renáto",
    "romana": "Romano",
    "růžena": "Růženo",
    "simona": "Simono",
    "silvie": "Silvie",
    "soňa": "Soňo",
    "stanislava": "Stanislavo",
    "šárka": "Šárko",
    "štěpánka": "Štěpánko",
    "táňa": "Táňo",
    "tereza": "Terezo",
    "vendula": "Vendulo",
    "veronika": "Veroniko",
    "věra": "Věro",
    "viola": "Violo",
    "vladimíra": "Vladimíro",
    "vlasta": "Vlasto",
    "zdeňka": "Zdeňko",
    "zuzana": "Zuzano",
    # ---- Male names ----
    "adam": "Adame",
    "aleš": "Aleši",
    "alexandr": "Alexandre",
    "antonín": "Antoníne",
    "bedřich": "Bedřichu",
    "bohumil": "Bohumile",
    "bohdan": "Bohdane",
    "boris": "Borisi",
    "břetislav": "Břetislave",
    "dalibor": "Dalibore",
    "daniel": "Danieli",
    "david": "Davide",
    "dominik": "Dominiku",
    "dušan": "Dušane",
    "eduard": "Eduarde",
    "erik": "Eriku",
    "filip": "Filipe",
    "františek": "Františku",
    "hynek": "Hynku",
    "igor": "Igore",
    "ivan": "Ivane",
    "ivo": "Ivo",
    "jakub": "Jakube",
    "jan": "Jane",
    "jaromír": "Jaromíre",
    "jaroslav": "Jaroslave",
    "jiří": "Jiří",
    "josef": "Josefe",
    "kamil": "Kamile",
    "karel": "Karle",
    "kristián": "Kristiáne",
    "ladislav": "Ladislave",
    "libor": "Libore",
    "lubomír": "Lubomíre",
    "luboš": "Luboši",
    "ludvík": "Ludvíku",
    "lukáš": "Lukáši",
    "marcel": "Marceli",
    "marek": "Marku",
    "martin": "Martine",
    "matěj": "Matěji",
    "matyáš": "Matyáši",
    "michal": "Michale",
    "milan": "Milane",
    "miloš": "Miloši",
    "miroslav": "Miroslave",
    "oldřich": "Oldřichu",
    "ondřej": "Ondřeji",
    "otakar": "Otakare",
    "patrik": "Patriku",
    "pavel": "Pavle",
    "petr": "Petře",
    "přemysl": "Přemysle",
    "radek": "Radku",
    "radim": "Radime",
    "rastislav": "Rastislave",
    "richard": "Richarde",
    "robert": "Roberte",
    "roman": "Romane",
    "rostislav": "Rostislave",
    "rudolf": "Rudolfe",
    "stanislav": "Stanislave",
    "šimon": "Šimone",
    "štefan": "Štefane",
    "štěpán": "Štěpáne",
    "tadeáš": "Tadeáši",
    "tomáš": "Tomáši",
    "václav": "Václave",
    "viktor": "Viktore",
    "vilém": "Viléme",
    "vít": "Víte",
    "vladimír": "Vladimíre",
    "vojtěch": "Vojtěchu",
    "zbyněk": "Zbyňku",
    "zdeněk": "Zdeňku",
}

# Consonants that trigger specific vocative suffixes for male names
_SOFT_CONSONANTS = set("šžčřcjďťňś")
_HARD_K_G_H_CH = {"k", "g", "h"}  # + "ch" handled separately


def _apply_rules(first_name: str) -> str | None:
    """Apply rule-based Czech vocative declension (Tier 2).

    Returns the vocative form, or ``None`` if no rule matches.
    """
    name = first_name.strip()
    if not name:
        return None

    lower = name.lower()

    # ----- Female heuristics -----
    # Names ending in -ie / -cie stay unchanged (Marie, Lucie, Natálie)
    if lower.endswith("ie") or lower.endswith("cie"):
        return name

    # Names ending in -e (non -ie) — typically unchanged (Libuše, Alice)
    if lower.endswith("e") or lower.endswith("ě"):
        return name

    # Names ending in -a → -o (most common feminine pattern)
    if lower.endswith("a"):
        return name[:-1] + "o"

    # ----- Male heuristics -----
    # -ek → -ku (Radek→Radku, Zdeněk→Zdeňku)
    if lower.endswith("ek"):
        return name[:-2] + "ku"

    # -áš / -eš / -oš → +i (Tomáš→Tomáši, Mikeš→Mikeši)
    if lower.endswith(("áš", "eš", "oš")):
        return name + "i"

    # -ěj → -ěji
    if lower.endswith("ěj"):
        return name + "i"

    # -el → -le (Karel→Karle, Daniel→Danieli — though Daniel is in lookup)
    if lower.endswith("el"):
        return name[:-2] + "le"

    # -ec → -če
    if lower.endswith("ec"):
        return name[:-2] + "če"

    # -ík → -íku
    if lower.endswith("ík"):
        return name + "u"

    # Soft consonants → add -i
    if lower[-1:] in _SOFT_CONSONANTS:
        return name + "i"

    # -k / -g / -h → add -u
    if lower[-1:] in _HARD_K_G_H_CH:
        return name + "u"

    # Hard consonants → add -e
    if lower[-1:] in set("rlndbfmptvwxz"):
        return name + "e"

    # No rule matched
    return None


def _ai_vocative(first_name: str) -> str | None:
    """Tier 3 — Call Anthropic Haiku for vocative declension.

    Results are cached in ``_ai_cache`` and validated before returning.
    Returns ``None`` if the AI call fails or produces invalid output.
    """
    stripped = first_name.strip()
    cache_key = stripped.lower()

    if cache_key in _ai_cache:
        return _ai_cache[cache_key]

    try:
        import anthropic  # noqa: F811

        client = anthropic.Anthropic()
        message = client.messages.create(
            model="claude-3-5-haiku-latest",
            max_tokens=32,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Convert this first name to Czech vocative (5. pád). "
                        f"Return ONLY the vocative form: {stripped}"
                    ),
                }
            ],
        )
        result = message.content[0].text.strip()

        # Validate: single word, similar length, no punctuation
        if not result:
            return None
        if len(result.split()) != 1:
            logger.warning(
                "AI vocative returned multiple words for %r: %r", stripped, result
            )
            return None
        if abs(len(result) - len(stripped)) > 3:
            logger.warning(
                "AI vocative length mismatch for %r: %r (diff=%d)",
                stripped,
                result,
                abs(len(result) - len(stripped)),
            )
            return None
        if re.search(r"[.!?,;:\"'()\[\]{}]", result):
            logger.warning("AI vocative has punctuation for %r: %r", stripped, result)
            return None

        _ai_cache[cache_key] = result
        logger.info("AI vocative: %r -> %r (cached for future use)", stripped, result)
        return result

    except Exception:
        logger.warning("AI vocative call failed for %r", stripped, exc_info=True)
        return None


def to_vocative(first_name: str | None, use_ai: bool = True) -> tuple[str, str]:
    """Convert a Czech first name to vocative case (5. pád).

    Uses a 3-tier approach:
    1. **Lookup** — table of ~200 common Czech names
    2. **Rules** — pattern-based declension
    3. **AI** — Anthropic Haiku call (if *use_ai* is ``True``)

    Falls back to nominative (unchanged) if all tiers fail.

    Args:
        first_name: First name in nominative case.
        use_ai: Whether to attempt AI fallback (Tier 3). Defaults to ``True``.

    Returns:
        Tuple of ``(vocative, source)`` where *source* is one of
        ``'lookup'``, ``'rules'``, ``'ai'``, or ``'nominative'``.
    """
    if not first_name or not first_name.strip():
        return ("", "nominative")

    stripped = first_name.strip()

    # Tier 1 — Lookup
    result = VOCATIVE_MAP.get(stripped.lower())
    if result:
        return (result, "lookup")

    # Tier 2 — Rules
    rule_result = _apply_rules(stripped)
    if rule_result is not None:
        return (rule_result, "rules")

    # Tier 3 — AI fallback
    if use_ai:
        ai_result = _ai_vocative(stripped)
        if ai_result is not None:
            return (ai_result, "ai")

    # Fallback — return nominative unchanged
    return (stripped, "nominative")
