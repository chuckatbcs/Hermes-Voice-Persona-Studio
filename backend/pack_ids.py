"""Canonical persona pack id resolution.

The pack catalog, the session overlay, and the Hermes profile config all
refer to a persona by id, but they used to derive those ids independently:
``storage`` persisted whatever slug the pack was created with while
``bot_profiles._clean_key`` slugified the *name*. A pack named "Eric Cartman"
therefore landed as ``cartman`` on disk but applied as ``eric_cartman`` into
``agent.personalities`` — the applied overlay pointed at a catalog key that
did not exist, and only worked because the name happened to round-trip.

This module is the single place that answers "which pack id is this?".
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Sequence

from .persona_sync import (
    name_match_score,
    normalize_voice_slug,
    slugify_persona_id,
)


def candidate_pack_ids(*values: Optional[str]) -> List[str]:
    """Every id a value could legitimately have been stored under.

    Ordered most-specific first so an exact pack id wins over a name-derived
    guess: ``("cartman", "Eric Cartman")`` yields ``cartman`` before
    ``eric_cartman``.
    """
    out: List[str] = []
    seen = set()

    def _add(raw: Optional[str]) -> None:
        if not raw:
            return
        text = str(raw).strip()
        if not text:
            return
        if text not in seen:
            seen.add(text)
            out.append(text)

    # Explicit ids first, verbatim.
    for value in values:
        _add(value)
    # Then the slug of each value, which is what storage persists.
    for value in values:
        slug = slugify_persona_id(value) if value else ""
        if slug and slug != "persona":
            _add(slug)
    # Then name/label slugs, stripped of a Fish ``hermes_`` prefix.
    for value in values:
        if not value:
            continue
        slug = normalize_voice_slug(value)
        if slug and slug != "persona":
            _add(slug)
    return out


def resolve_pack_id(
    known_ids: Iterable[str],
    *values: Optional[str],
) -> Optional[str]:
    """Map any of *values* onto an id that exists in *known_ids*.

    Resolution order, strongest evidence first:

    1. exact id match (an overlay that already holds a pack id)
    2. exact slug match on any value
    3. best token-overlap match, so ``eric_cartman`` still finds a pack stored
       as ``cartman`` — but only when nothing better exists

    Returns ``None`` when nothing matches, so callers can surface the
    orphan rather than guessing.
    """
    known: Sequence[str] = [k for k in known_ids if k]
    if not known:
        return None
    known_set = set(known)

    for value in values:
        text = str(value or "").strip()
        if text and text in known_set:
            return text

    known_slugs = {slugify_persona_id(k): k for k in known}
    for value in values:
        if not value:
            continue
        slug = slugify_persona_id(value)
        if slug in known_slugs:
            return known_slugs[slug]
        stripped = normalize_voice_slug(value)
        if stripped in known_slugs:
            return known_slugs[stripped]

    # Token overlap fallback: richest needle first so a bare id cannot beat a
    # full name.
    best_id: Optional[str] = None
    best_score = 0
    for value in values:
        if not value:
            continue
        for key in known:
            score = name_match_score(value, key)
            if score > best_score:
                best_score = score
                best_id = key
    # 200+ means a real token relationship, not an incidental letter overlap.
    return best_id if best_score >= 200 else None


def reconcile_applied_persona(
    applied: Optional[str],
    known_ids: Iterable[str],
) -> Optional[str]:
    """Re-point an ``applied_persona`` at the real pack id, or ``None``.

    ``None`` means the overlay is genuinely orphaned and the caller should
    report it instead of leaving a dangling reference behind.
    """
    if not applied:
        return None
    return resolve_pack_id(known_ids, applied, applied.replace("_", " "), applied)
