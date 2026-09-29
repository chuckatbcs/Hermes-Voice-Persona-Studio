/**
 * Persona Studio desktop-plugin unit tests.
 *
 * These call the real helpers from desktop/lib/persona-helpers.mjs. They do
 * NOT read plugin.js source text — Hermes' own AGENTS.md bans testing a god
 * file by grepping its source, because such a test passes on subtly broken
 * code and fails on correct refactors.
 *
 * Run: node --test tests/
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  slugifyName,
  nameMatchScore,
  namesMatch,
  isFishProvider,
  providerLabel,
  isPlaceholderVoiceId,
  isStubPersonaPrompt,
  isListablePersonaPack,
  characterStrengthPercent,
  characterStrengthLabel,
  characterStrengthBand,
  voiceSelectionKey,
  personaSelectionKey,
  parseSelection,
  lookupSelection,
  resolvePackId
} from '../desktop/lib/persona-helpers.mjs';

test('slugifyName strips a Fish hermes_ prefix', () => {
  assert.equal(slugifyName('Hermes eric_cartman'), 'eric_cartman');
  assert.equal(slugifyName('Eric Cartman'), 'eric_cartman');
  assert.equal(slugifyName('  Jarvis (Tech Butler) '), 'jarvis_tech_butler');
});

test('richer name beats bare id when matching', () => {
  // "Eric Cartman" must outrank the shorter "cartman" twin.
  const full = nameMatchScore('Eric Cartman', 'Hermes eric_cartman');
  const bare = nameMatchScore('Eric Cartman', 'Hermes cartman');
  assert.ok(full > bare, `expected ${full} > ${bare}`);
  assert.ok(namesMatch('Eric Cartman', 'Hermes eric_cartman'));
});

test('unrelated names do not match', () => {
  assert.equal(nameMatchScore('zzz_nobody', 'Eric Cartman'), 0);
  assert.equal(namesMatch('zzz_nobody', 'Eric Cartman'), false);
});

test('isFishProvider accepts both Fish spellings', () => {
  assert.equal(isFishProvider('fish'), true);
  assert.equal(isFishProvider('fish_audio'), true);
  assert.equal(isFishProvider('voicebox'), false);
  assert.equal(providerLabel('fish_audio'), 'Fish');
  assert.equal(providerLabel('voicebox'), 'Voicebox');
});

test('placeholder voice ids are rejected', () => {
  for (const bad of ['', '  ', 'default', 'none', 'null', 'undefined', 'system']) {
    assert.equal(isPlaceholderVoiceId(bad), true, `${JSON.stringify(bad)} should be placeholder`);
  }
  assert.equal(isPlaceholderVoiceId('c9da87b0-19be-49c4-ab44-01cb7943f5c4'), false);
  assert.equal(isPlaceholderVoiceId('0e142644ca7143f887a40f18977b695e'), false);
});

test('stub persona prompts are not listable', () => {
  assert.equal(isStubPersonaPrompt(''), true);
  assert.equal(isStubPersonaPrompt('todo'), true);
  assert.equal(isStubPersonaPrompt('short'), true);
  assert.equal(
    isStubPersonaPrompt('distinctive tone, vocabulary, and cadence associated with Jarvis'),
    true
  );
  assert.equal(
    isStubPersonaPrompt('Aggressive impatient South Park snark while doing the job.'),
    false
  );
});

test('complete pack is listable, stub is not', () => {
  const good = { id: 'cartman', name: 'Eric Cartman', system_prompt: 'A'.repeat(40), voice_id: 'v1' };
  const stub = { id: 'ghost', name: 'Ghost', system_prompt: 'todo', voice_id: 'v2' };
  assert.equal(isListablePersonaPack(good, []), true);
  assert.equal(isListablePersonaPack(stub, []), false);
  assert.equal(isListablePersonaPack(null, []), false);
});

test('character strength coerces legacy labels and clamps', () => {
  assert.equal(characterStrengthPercent(null), 25);
  assert.equal(characterStrengthPercent(''), 25);
  assert.equal(characterStrengthPercent('soft'), 25);
  assert.equal(characterStrengthPercent('medium'), 55);
  assert.equal(characterStrengthPercent('strong'), 85);
  assert.equal(characterStrengthPercent(0), 0);
  assert.equal(characterStrengthPercent(100), 100);
  assert.equal(characterStrengthPercent(-10), 0);
  assert.equal(characterStrengthPercent(999), 100);
  assert.equal(characterStrengthPercent('73'), 73);
});

test('strength bands match the python table', () => {
  assert.equal(characterStrengthBand(0), 'none');
  assert.equal(characterStrengthBand(40), 'soft');
  assert.equal(characterStrengthBand(41), 'medium');
  assert.equal(characterStrengthBand(70), 'medium');
  assert.equal(characterStrengthBand(71), 'heavy');
  assert.equal(characterStrengthBand(99), 'heavy');
  assert.equal(characterStrengthBand(100), 'eclipse');
});

test('strength labels are distinct from bands', () => {
  assert.equal(characterStrengthLabel(0), 'Soul only');
  assert.equal(characterStrengthLabel(25), 'Soft');
  assert.equal(characterStrengthLabel(55), 'Medium');
  assert.equal(characterStrengthLabel(85), 'Heavy');
  assert.equal(characterStrengthLabel(100), 'Full character');
});

test('selection keys round-trip', () => {
  assert.equal(personaSelectionKey({ id: 'cartman' }), 'persona:cartman');
  assert.equal(voiceSelectionKey({ provider: 'fish_audio', id: 'abc' }), 'voice:fish_audio:abc');
});

test('parseSelection understands every stored form', () => {
  assert.deepEqual(parseSelection('persona:cartman'), {
    kind: 'persona', personaId: 'cartman', explicit: false
  });
  assert.deepEqual(parseSelection('voice:voicebox:abc'), {
    kind: 'voice', provider: 'voicebox', voiceId: 'abc', explicit: true
  });
  assert.deepEqual(parseSelection('cartman'), { kind: 'legacy', id: 'cartman', explicit: false });
  assert.deepEqual(parseSelection('default'), { kind: 'default' });
  assert.deepEqual(parseSelection(''), { kind: 'unknown' });
});

test('lookupSelection treats fish and fish_audio as the same provider', () => {
  const personas = [{ id: 'cartman' }];
  const voices = [{ id: 'abc', provider: 'fish_audio' }];
  const hit = lookupSelection('voice:fish:abc', personas, voices);
  assert.equal(hit.voice.id, 'abc');
  assert.equal(lookupSelection('persona:cartman', personas, voices).persona.id, 'cartman');
  assert.deepEqual(lookupSelection('persona:missing', personas, voices).persona, null);
});

test('resolvePackId maps a name-derived slug onto the stored pack', () => {
  const known = ['amanda', 'cartman', 'flirty', 'jarvis', 'vincent_price'];
  // O-1: the live session state held "eric_cartman" while the pack is "cartman".
  assert.equal(resolvePackId(known, 'eric_cartman'), 'cartman');
  assert.equal(resolvePackId(known, 'Eric Cartman'), 'cartman');
  assert.equal(resolvePackId(known, 'cartman'), 'cartman');
});

test('resolvePackId refuses to guess for an unrelated name', () => {
  const known = ['amanda', 'cartman'];
  assert.equal(resolvePackId(known, 'zzz_nobody'), null);
  assert.equal(resolvePackId(known, ''), null);
  assert.equal(resolvePackId([], 'cartman'), null);
});
