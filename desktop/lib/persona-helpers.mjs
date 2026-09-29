/**
 * Pure persona-studio helpers, extracted so they are unit-testable.
 *
 * These mirror the Python implementation in `backend/persona_sync.py`. When a
 * rule changes, it changes in BOTH places — `tests/plugin.test.mjs` asserts
 * the same expectations as `test_backend.py` so the two cannot silently drift
 * apart. (Hermes' own AGENTS.md bans testing a god file by reading its source
 * text; the contract here is behaviour, asserted by calling the functions.)
 *
 * The desktop plugin imports this file; it is the single JS source of truth
 * for name matching, strength bands, and pack listability.
 */

export function slugifyName(value) {
  let slug = String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  while (slug.startsWith('hermes_')) slug = slug.slice(7).replace(/^_+/, '');
  return slug;
}

export function nameTokens(value) {
  const stop = new Set(['the', 'a', 'an', 'of', 'and', 'my', 'voice', 'clone', 'hermes']);
  return new Set(slugifyName(value).split('_').filter((t) => t && !stop.has(t)));
}

export function nameMatchScore(needle, haystack) {
  if (!needle || !haystack) return 0;
  const ns = slugifyName(needle);
  const hs = slugifyName(haystack);
  if (!ns || !hs) return 0;
  if (ns === hs) return 1000;
  const nt = nameTokens(needle);
  const ht = nameTokens(haystack);
  if (!nt.size || !ht.size) return 0;
  const ntArr = [...nt];
  const htArr = [...ht];
  const same = nt.size === ht.size && ntArr.every((t) => ht.has(t));
  if (same) return 900;
  if (ntArr.every((t) => ht.has(t))) return 400 + 20 * nt.size + 5 * ht.size;
  if (htArr.every((t) => nt.has(t))) return 200 + 20 * ht.size;
  let inter = 0;
  nt.forEach((t) => { if (ht.has(t)) inter += 1; });
  return inter ? 50 + 10 * inter : 0;
}

export function namesMatch(left, right) {
  return nameMatchScore(left, right) > 0;
}

export function isFishProvider(provider) {
  const p = String(provider || '').toLowerCase();
  return p === 'fish' || p === 'fish_audio';
}

export function providerLabel(provider) {
  return isFishProvider(provider) ? 'Fish' : 'Voicebox';
}

export function isPlaceholderVoiceId(value) {
  const text = String(value || '').trim().toLowerCase();
  return !text || text === 'default' || text === 'none' || text === 'null' || text === 'undefined' || text === 'system';
}

/** Canonical 0-100 character strength. Mirrors character_strength_percent(). */
export function characterStrengthPercent(value) {
  if (value == null || value === '') return 25;
  if (typeof value === 'string') {
    const lowered = value.trim().toLowerCase();
    if (lowered === 'soft') return 25;
    if (lowered === 'medium') return 55;
    if (lowered === 'strong') return 85;
    const parsed = Number(lowered);
    if (!Number.isFinite(parsed)) return 25;
    value = parsed;
  }
  const number = Math.round(Number(value));
  if (!Number.isFinite(number)) return 25;
  return Math.max(0, Math.min(100, number));
}

export function characterStrengthLabel(value) {
  const percent = characterStrengthPercent(value);
  if (percent <= 0) return 'Soul only';
  if (percent <= 40) return 'Soft';
  if (percent <= 70) return 'Medium';
  if (percent < 100) return 'Heavy';
  return 'Full character';
}

/**
 * Band boundaries, kept identical to character_strength_band() in
 * backend/persona_sync.py. O-5: these were drifting, so both sides assert the
 * same table.
 */
export function characterStrengthBand(value) {
  const percent = characterStrengthPercent(value);
  if (percent <= 0) return 'none';
  if (percent <= 40) return 'soft';
  if (percent <= 70) return 'medium';
  if (percent < 100) return 'heavy';
  return 'eclipse';
}

export function isGenericVoiceDescription(description) {
  const lowered = String(description || '').trim().toLowerCase();
  if (!lowered) return true;
  return ['fish audio clone', '[voicebox sample persona', 'cloned via hermes personastudio', 're-sampled voice reference']
    .some((prefix) => lowered.startsWith(prefix));
}

export function isStubPersonaPrompt(prompt) {
  const text = String(prompt || '').trim();
  if (!text || text.length < 24) return true;
  const lowered = text.toLowerCase();
  if (lowered === 'todo' || lowered === 'placeholder' || lowered === 'tbd' || lowered === 'stub') return true;
  if (lowered.startsWith('distinctive tone, vocabulary, and cadence associated with')) return true;
  return isGenericVoiceDescription(text);
}

export function isListablePersonaPack(persona, voices) {
  if (!persona) return false;
  if (isStubPersonaPrompt(persona.system_prompt)) return false;
  if (!isPlaceholderVoiceId(persona.voice_id)) return true;
  const names = [persona.name, persona.id, persona.voice_name].filter(Boolean);
  return (voices || []).some((voice) => {
    if (!voice || isPlaceholderVoiceId(voice.id)) return false;
    if (voice.voice_type && voice.voice_type !== 'cloned' && voice.voice_type !== 'custom') return false;
    if (persona.voice_id && voice.id === persona.voice_id) return true;
    return names.some((name) => nameMatchScore(name, voice.name) > 0 || nameMatchScore(name, voice.id) > 0);
  });
}

export function voiceSelectionKey(voice) {
  return `voice:${voice.provider || 'voicebox'}:${voice.id}`;
}

export function personaSelectionKey(persona) {
  return `persona:${persona.id}`;
}

export function parseSelection(id) {
  if (!id) return { kind: 'unknown' };
  if (id === 'default' || id === '__open_studio__') return { kind: id };
  if (id.startsWith('persona:')) return { kind: 'persona', personaId: id.slice('persona:'.length), explicit: false };
  if (id.startsWith('voice:')) {
    const rest = id.slice('voice:'.length);
    const splitAt = rest.indexOf(':');
    if (splitAt <= 0) return { kind: 'unknown' };
    return {
      kind: 'voice',
      provider: rest.slice(0, splitAt),
      voiceId: rest.slice(splitAt + 1),
      explicit: true
    };
  }
  return { kind: 'legacy', id, explicit: false };
}

export function lookupSelection(id, personas, voices) {
  const sel = parseSelection(id);
  if (sel.kind === 'persona') {
    return { persona: (personas || []).find(p => p.id === sel.personaId) || null, voice: null };
  }
  if (sel.kind === 'voice') {
    return {
      persona: null,
      voice: (voices || []).find(v =>
        v.id === sel.voiceId &&
        (v.provider === sel.provider || (isFishProvider(v.provider) && isFishProvider(sel.provider)))
      ) || null
    };
  }
  if (sel.kind === 'legacy') {
    return {
      persona: (personas || []).find(p => p.id === sel.id) || null,
      voice: (voices || []).find(v => v.id === sel.id) || null
    };
  }
  return { persona: null, voice: null };
}

/**
 * O-1: resolve an applied/selected persona reference onto a real pack id.
 * Mirrors backend/pack_ids.py resolve_pack_id() — exact id, then slug, then a
 * token-overlap match strong enough to be a real relationship (>= 200).
 */
export function resolvePackId(knownIds, ...values) {
  const known = (knownIds || []).filter(Boolean);
  if (!known.length) return null;
  for (const value of values) {
    const text = String(value || '').trim();
    if (text && known.includes(text)) return text;
  }
  const bySlug = new Map(known.map((k) => [slugifyName(k), k]));
  for (const value of values) {
    if (!value) continue;
    const slug = slugifyName(value);
    if (bySlug.has(slug)) return bySlug.get(slug);
    let stripped = slugifyName(value);
    while (stripped.startsWith('hermes_')) stripped = stripped.slice(7).replace(/^_+/, '');
    if (bySlug.has(stripped)) return bySlug.get(stripped);
  }
  let bestId = null;
  let bestScore = 0;
  for (const value of values) {
    if (!value) continue;
    for (const key of known) {
      const score = nameMatchScore(value, key);
      if (score > bestScore) {
        bestScore = score;
        bestId = key;
      }
    }
  }
  return bestScore >= 200 ? bestId : null;
}
