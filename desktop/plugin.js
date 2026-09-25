/**
 * Hermes PersonaStudio — The Voice & Persona Studio for Hermes Desktop.
 * Provides:
 *  - Titlebar Quick Persona Switcher ([🎭 Persona: Jarvis ▼])
 *  - Complete Voice & Persona Creation Studio with Live Auditioning
 *  - Model Selection for Voice Cloning (Chatterbox Turbo, Qwen, Kokoro, Fish S2.1)
 *  - Support for Fish Audio cloud models, local GPU Voicebox, and custom clones
 *  - Non-destructive session prompt & voice overrides
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Button,
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
  TITLEBAR_AREAS,
  host
} from '@hermes/plugin-sdk';
import { jsx, jsxs } from 'react/jsx-runtime';

const PLUGIN_ID = 'hermes-personastudio';
const API_BASE = 'http://127.0.0.1:17495/api/studio';

function isGenericVoiceDescription(description) {
  const text = (description || '').trim();
  if (!text) return true;
  const lowered = text.toLowerCase();
  return (
    lowered.startsWith('fish audio clone') ||
    lowered.startsWith('[voicebox sample persona') ||
    lowered.startsWith('cloned via hermes personastudio')
  );
}

function mannerismFromPrompt(raw, personaName) {
  const label = (personaName || 'this persona').trim() || 'this persona';
  const text = (raw || '').trim();
  if (!text) {
    return `distinctive tone, vocabulary, and cadence associated with ${label}`;
  }
  const identity = /^\s*(?:you are|you're|i am|i'm)\s+(?:an?\s+)?(.+)$/i;
  const parts = text.split(/(?<=[.!?])\s+/);
  const first = (parts[0] || '').trim();
  const rest = parts.slice(1).join(' ').trim();
  const match = first.replace(/[.!?]+$/, '').match(identity);
  let rewritten = first;
  if (match) {
    let leftover = match[1].trim();
    leftover = leftover.replace(new RegExp('^' + label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\b[\\s,:-]*', 'i'), '').trim();
    leftover = leftover.replace(/^from\s+[^,.:]+[,.:]?\s*/i, '').trim();
    rewritten = leftover ? `mannerisms of ${label}: ${leftover}` : `mannerisms of ${label}`;
  }
  return rest ? `${rewritten}. ${rest}` : rewritten;
}

function fallbackSystemPrompt(name, description) {
  const label = (name || 'this persona').trim() || 'this persona';
  const desc = (description || '').trim();
  if (desc && !isGenericVoiceDescription(desc)) {
    return mannerismFromPrompt(desc, label);
  }
  return `distinctive tone, vocabulary, and cadence associated with ${label}; stay helpful and complete the profile's job`;
}

function slugifyName(value) {
  let slug = String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  while (slug.startsWith('hermes_')) slug = slug.slice(7).replace(/^_+/, '');
  return slug;
}

function nameTokens(value) {
  const stop = new Set(['the', 'a', 'an', 'of', 'and', 'my', 'voice', 'clone', 'hermes']);
  return new Set(slugifyName(value).split('_').filter((t) => t && !stop.has(t)));
}

function nameMatchScore(needle, haystack) {
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

function namesMatch(left, right) {
  return nameMatchScore(left, right) > 0;
}

function isFishProvider(provider) {
  const p = String(provider || '').toLowerCase();
  return p === 'fish' || p === 'fish_audio';
}

function providerLabel(provider) {
  return isFishProvider(provider) ? 'Fish' : 'Voicebox';
}

function voiceSelectionKey(voice) {
  return `voice:${voice.provider || 'voicebox'}:${voice.id}`;
}

function personaSelectionKey(persona) {
  return `persona:${persona.id}`;
}

function parseSelection(id) {
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

function lookupSelection(id, personas, voices) {
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

// TITLEBAR_PACK_BEGIN
function characterStrengthPercent(value) {
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

function characterStrengthLabel(value) {
  const percent = characterStrengthPercent(value);
  if (percent <= 0) return 'Soul only';
  if (percent <= 40) return 'Soft';
  if (percent <= 70) return 'Medium';
  if (percent < 100) return 'Heavy';
  return 'Full character';
}

function isPlaceholderVoiceId(value) {
  const text = String(value || '').trim().toLowerCase();
  return !text || text === 'default' || text === 'none' || text === 'null' || text === 'undefined' || text === 'system';
}

function isStubPersonaPrompt(prompt) {
  const text = String(prompt || '').trim();
  if (!text || text.length < 24) return true;
  const lowered = text.toLowerCase();
  if (lowered === 'todo' || lowered === 'placeholder' || lowered === 'tbd' || lowered === 'stub') return true;
  if (lowered.startsWith('distinctive tone, vocabulary, and cadence associated with')) return true;
  return isGenericVoiceDescription(text);
}

function isListablePersonaPack(persona, voices) {
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
// TITLEBAR_PACK_END

// STUDIO_FORM_BEGIN
function hydrateFormFromPack(pack) {
  if (!pack) return null;
  const provider = isFishProvider(pack.provider) ? 'fish_audio' : (pack.provider || 'voicebox');
  return {
    id: pack.id || '',
    name: pack.name || '',
    avatar: pack.avatar || '🤖',
    systemPrompt: pack.system_prompt || '',
    provider: provider,
    selectedVoice: pack.voice_id && pack.voice_id !== 'default' ? pack.voice_id : '',
    speed: pack.speed != null ? pack.speed : 1.0,
    temperature: pack.temperature != null ? pack.temperature : 0.7,
    characterStrength: characterStrengthPercent(pack.character_strength),
    // Voice model = Voicebox default_engine / Fish model id (Synthesis engine dropdown).
    engine: pack.engine || pack.default_engine || ''
  };
}

function resolvePersonaSaveName(name, selectedPack) {
  const typed = String(name || '').trim();
  if (typed) return typed;
  if (selectedPack && selectedPack.name) return String(selectedPack.name).trim();
  return '';
}

function personaSaveRequest(fields) {
  const selectedPack = fields.selectedPack || null;
  const resolvedName = resolvePersonaSaveName(fields.name, selectedPack);
  if (!resolvedName) return { error: 'Please enter a name for the Persona.' };
  const id = String(fields.editingId || (selectedPack && selectedPack.id) || '').trim();
  const isUpdate = !!id;
  const body = {
    name: resolvedName,
    avatar: fields.avatar || '🤖',
    system_prompt: fields.systemPrompt || '',
    provider: fields.provider || 'voicebox',
    voice_id: fields.selectedVoice || (selectedPack && selectedPack.voice_id) || 'default',
    voice_name: fields.voiceName || fields.selectedVoice || resolvedName,
    speed: parseFloat(fields.speed),
    temperature: parseFloat(fields.temperature),
    character_strength: characterStrengthPercent(fields.characterStrength),
    engine: fields.engine || fields.selectedModel || (selectedPack && selectedPack.engine) || null
  };
  if (isUpdate) body.id = id;
  return {
    method: isUpdate ? 'PUT' : 'POST',
    url: isUpdate ? `/personas/${encodeURIComponent(id)}` : '/personas',
    body: body
  };
}

function formatStudioLiveStatus(status) {
  const profile = status && status.profile_id ? String(status.profile_id) : '';
  if (!status || !status.active || !status.applied_persona) {
    return {
      headline: profile ? `Stock Hermes on "${profile}"` : 'Stock Hermes',
      detail: 'No Studio overlay on this profile. This chat uses the profile soul and stock TTS.'
    };
  }
  const parts = [String(status.applied_persona)];
  if (status.provider) parts.push(providerLabel(status.provider));
  if (status.voice_name && String(status.voice_name) !== String(status.applied_persona)) {
    parts.push(String(status.voice_name));
  }
  const strength = status.character_strength == null ? null : characterStrengthPercent(status.character_strength);
  const strengthNote = strength == null
    ? 'Overlay is live on this profile. Next reply in this chat uses it.'
    : `Character strength ${strength}% (${characterStrengthLabel(strength)}). Next reply in this chat uses this overlay.`;
  return {
    headline: `Live: ${parts.join(' · ')}`,
    detail: strengthNote
  };
}

function notifyHost(kind, title, message, hostApi) {
  const payload = {
    kind: kind || 'info',
    message: String(message || title || '')
  };
  if (title) payload.title = String(title);
  try {
    if (hostApi !== undefined) {
      if (hostApi && typeof hostApi.notify === 'function') {
        hostApi.notify(payload);
        return true;
      }
    } else if (typeof host !== 'undefined' && host && typeof host.notify === 'function') {
      host.notify(payload);
      return true;
    }
  } catch (_) {}
  try {
    const label = payload.title ? `${payload.title} — ${payload.message}` : payload.message;
    console.log(`[PersonaStudio] ${payload.kind}: ${label}`);
  } catch (_) {}
  return false;
}
// STUDIO_FORM_END

// LIVE_SESSION_REFRESH_BEGIN
function catalogPersonalityKey(value) {
  const key = slugifyName(value);
  if (!key || key === 'default' || key === 'none' || key === 'neutral') return 'none';
  return key;
}

function readStateField(state, key) {
  try {
    const raw = state && state[key];
    if (raw && typeof raw.get === 'function') return raw.get();
    return raw == null ? null : raw;
  } catch (_) {
    return null;
  }
}

function resolveLiveSessionId(state) {
  const focused = readStateField(state, 'focusedSessionId');
  if (focused) return String(focused).trim();
  const active = readStateField(state, 'activeSessionId');
  if (active) return String(active).trim();
  return '';
}

function resolveLiveSessionProfile(state, fallbackProfile) {
  const owner = readStateField(state, 'focusedSessionOwner');
  if (owner && typeof owner === 'object') {
    const fromOwner = owner.profile || owner.profile_id || '';
    if (fromOwner) return String(fromOwner).trim();
  }
  if (typeof owner === 'string' && owner.trim()) return owner.trim();
  const focused = readStateField(state, 'focusedSessionProfile');
  if (focused) return String(focused).trim();
  if (fallbackProfile) return String(fallbackProfile).trim();
  return '';
}

function interpretLiveSessionRefreshResult(result) {
  if (result && result.info != null) {
    return { ok: true, attempted: true, skipped: '' };
  }
  return {
    ok: false,
    attempted: true,
    skipped: '',
    error: result && result.history_reset != null
      ? 'history_reset without live info'
      : 'gateway returned no live apply info'
  };
}

function focusedSessionOwnerRecord(state) {
  const owner = readStateField(state, 'focusedSessionOwner');
  return owner && typeof owner === 'object' ? owner : null;
}

function normalizeProfileRoute(route) {
  if (!route || typeof route !== 'object' || Array.isArray(route)) return null;
  const connectionId = String(route.connectionId || '').trim();
  const profile = String(route.profile || route.targetProfile || '').trim();
  const targetProfile = String(route.targetProfile || route.profile || '').trim();
  if (!connectionId || !profile) return null;
  return {
    connectionId: connectionId,
    mode: String(route.mode || 'local').trim() || 'local',
    profile: profile,
    targetProfile: targetProfile || profile
  };
}

function isFullProfileRoute(route) {
  return !!normalizeProfileRoute(route);
}

function matchProfileRoute(routes, owner, profileName) {
  const list = (Array.isArray(routes) ? routes : []).map(normalizeProfileRoute).filter(Boolean);
  const connectionId = owner && owner.connectionId ? String(owner.connectionId).trim() : '';
  const wanted = String(profileName || (owner && (owner.profile || owner.profile_id)) || '').trim();
  if (connectionId) {
    const byConn = list.filter((route) => route.connectionId === connectionId);
    if (wanted) {
      const exact = byConn.find((route) => route.profile === wanted || route.targetProfile === wanted);
      if (exact) return exact;
    }
    if (byConn.length === 1) return byConn[0];
  }
  if (wanted) {
    const byName = list.filter((route) => route.profile === wanted || route.targetProfile === wanted);
    if (byName.length === 1) return byName[0];
  }
  return null;
}

function synthesizeProfileRoute(owner, profileName) {
  const profile = String(profileName || (owner && (owner.profile || owner.profile_id)) || '').trim();
  const connectionId = owner && owner.connectionId ? String(owner.connectionId).trim() : '';
  if (!connectionId || !profile) return null;
  return {
    connectionId: connectionId,
    mode: String((owner && owner.mode) || 'local').trim() || 'local',
    profile: profile,
    targetProfile: profile
  };
}

function resolveFocusedProfileRouteFromList(routes, state, profileName) {
  const owner = focusedSessionOwnerRecord(state);
  const wanted = String(profileName || resolveLiveSessionProfile(state, '') || '').trim();
  return matchProfileRoute(routes, owner, wanted) || synthesizeProfileRoute(owner, wanted);
}

async function listProfileRoutes(api) {
  if (!api || typeof api.profileRoutes !== 'function') return [];
  try {
    const listed = await api.profileRoutes();
    if (Array.isArray(listed)) return listed;
    if (listed && Array.isArray(listed.routes)) return listed.routes;
  } catch (_) {}
  return [];
}

async function resolveFocusedProfileRoute(api, state, profileName) {
  const routes = await listProfileRoutes(api);
  return resolveFocusedProfileRouteFromList(routes, state, profileName);
}

function profileNamesMatch(left, right) {
  const a = String(left || '').trim().toLowerCase();
  const b = String(right || '').trim().toLowerCase();
  return !!a && a === b;
}

function resolveActiveGatewayProfile(state, routes) {
  const fromState = readStateField(state, 'profile')
    || readStateField(state, 'activeGatewayProfile')
    || readStateField(state, 'activeSessionProfile')
    || readStateField(state, 'activeProfile');
  if (fromState) return String(fromState).trim();
  const raw = (Array.isArray(routes) ? routes : []).find((route) => route && (route.active || route.isActive || route.current));
  if (raw) {
    const normalized = normalizeProfileRoute(raw);
    if (normalized) return normalized.targetProfile || normalized.profile;
  }
  return '';
}

function isGatewaySafe(profile, activeGw, route) {
  if (!profile) return true;
  if (profileNamesMatch(profile, activeGw)) return true;
  if (activeGw) return false;
  return !!(route && (profileNamesMatch(profile, route.profile) || profileNamesMatch(profile, route.targetProfile)));
}

function refreshLiveSessionPersonalityPlan(personaKey, hostApi, state, fallbackProfile, route, routes) {
  const sid = resolveLiveSessionId(state);
  const profile = resolveLiveSessionProfile(state, fallbackProfile);
  const fullRoute = normalizeProfileRoute(route);
  if (!sid) {
    return { ok: false, attempted: false, skipped: 'no-session', payload: null, via: '', profile: profile, route: null };
  }
  const canProfile = !!fullRoute && hostApi && typeof hostApi.requestProfile === 'function';
  const activeGw = resolveActiveGatewayProfile(state, routes);
  const gatewaySafe = isGatewaySafe(profile, activeGw, fullRoute);
  const canRequest = hostApi && typeof hostApi.request === 'function' && gatewaySafe;
  const params = {
    key: 'personality',
    value: catalogPersonalityKey(personaKey),
    session_id: sid
  };
  if (canRequest) {
    return {
      ok: true,
      attempted: true,
      skipped: '',
      via: 'request',
      profile: profile,
      route: fullRoute,
      payload: {
        method: 'config.set',
        profile: profile,
        route: fullRoute,
        params: params
      }
    };
  }
  if (canProfile) {
    return {
      ok: true,
      attempted: true,
      skipped: '',
      via: 'requestProfile',
      profile: fullRoute.profile,
      route: fullRoute,
      payload: {
        method: 'config.set',
        profile: fullRoute.profile,
        route: fullRoute,
        params: params
      }
    };
  }
  const skipped = (hostApi && typeof hostApi.requestProfile === 'function' && !fullRoute)
    ? 'no-route'
    : ((hostApi && typeof hostApi.request === 'function' && !gatewaySafe) ? 'wrong-gateway' : 'no-request');
  return { ok: false, attempted: false, skipped: skipped, payload: null, via: '', profile: profile, route: null };
}

async function dispatchLivePersonalityRefresh(api, plan) {
  if (!plan || !plan.attempted || !plan.payload) return plan || { ok: false, attempted: false, skipped: 'no-plan' };
  try {
    if (plan.via === 'requestProfile') {
      if (typeof plan.route === 'string' || !isFullProfileRoute(plan.route)) {
        return { ok: false, attempted: true, skipped: '', error: 'bare profile string rejected' };
      }
      const result = await api.requestProfile(plan.route, plan.payload.method, plan.payload.params);
      return interpretLiveSessionRefreshResult(result);
    }
    if (!api || typeof api.request !== 'function') {
      return { ok: false, attempted: false, skipped: 'no-request' };
    }
    const result = await api.request(plan.payload.method, plan.payload.params);
    return interpretLiveSessionRefreshResult(result);
  } catch (err) {
    console.warn('[PersonaStudio] live personality refresh failed:', err);
    return { ok: false, attempted: true, skipped: '', error: String((err && err.message) || err) };
  }
}

async function refreshLiveSessionPersonality(personaKey, hostApi) {
  const api = hostApi !== undefined ? hostApi : (typeof host !== 'undefined' ? host : null);
  const state = (api && api.state) || (typeof host !== 'undefined' && host && host.state) || {};
  let fallback = '';
  try { fallback = focusedProfile(); } catch (_) { fallback = ''; }
  const profileName = resolveLiveSessionProfile(state, fallback);
  const routes = await listProfileRoutes(api);
  const route = resolveFocusedProfileRouteFromList(routes, state, profileName);
  const plan = refreshLiveSessionPersonalityPlan(personaKey, api, state, fallback, route, routes);
  return dispatchLivePersonalityRefresh(api, plan);
}
// LIVE_SESSION_REFRESH_END

function preferredProviderForPersona(persona, voices) {
  if (!persona) return 'voicebox';
  if (isFishProvider(persona.provider) && persona.voice_id && persona.voice_id !== 'default') {
    return persona.provider;
  }
  const names = [persona.name, persona.id, persona.voice_name].filter(Boolean);
  const richest = [...names].sort((a, b) => nameTokens(b).size - nameTokens(a).size || slugifyName(b).length - slugifyName(a).length)[0];
  let best = null;
  let bestScore = 0;
  (voices || []).forEach((v) => {
    if (!isFishProvider(v.provider) || v.voice_type !== 'cloned' || !v.id || v.id === 'default') return;
    const score = Math.max(nameMatchScore(richest, v.name), nameMatchScore(richest, v.id));
    if (score > bestScore) {
      bestScore = score;
      best = v;
    }
  });
  if (best) return best.provider;
  return persona.provider || 'voicebox';
}

function focusedProfile() {
  try {
    return host.state.focusedSessionProfile.get() || 'default';
  } catch (_) {
    return 'default';
  }
}

function focusedSessionId() {
  try {
    const atom = host.state && host.state.focusedSessionId;
    return atom && typeof atom.get === 'function' ? (atom.get() || null) : null;
  } catch (_) {
    return null;
  }
}

function focusedStoredSessionId() {
  try {
    const atom = host.state && host.state.focusedStoredSessionId;
    return atom && typeof atom.get === 'function' ? (atom.get() || null) : null;
  } catch (_) {
    return null;
  }
}

function subscribeAtom(atom, onChange) {
  try {
    if (atom && typeof atom.subscribe === 'function') {
      return atom.subscribe(() => onChange());
    }
  } catch (_) {}
  return null;
}

function subscribeFocusedSession(onChange) {
  const unsubs = [];
  try {
    const state = host.state || {};
    const sidUnsub = subscribeAtom(state.focusedSessionId, onChange);
    const storedUnsub = subscribeAtom(state.focusedStoredSessionId, onChange);
    const profileUnsub = subscribeAtom(state.focusedSessionProfile, onChange);
    if (sidUnsub) unsubs.push(sidUnsub);
    if (storedUnsub) unsubs.push(storedUnsub);
    if (profileUnsub) unsubs.push(profileUnsub);
  } catch (_) {}
  if (unsubs.length) {
    return () => unsubs.forEach((u) => { try { if (typeof u === 'function') u(); } catch (_) {} });
  }
  const timer = setInterval(onChange, 400);
  return () => clearInterval(timer);
}

// SESSION_WATCH_BEGIN
/**
 * Promax double-blank race (Charles 2026-09-22):
 * Hermes persists/renumbers focusedSessionId on the first prompt (~5–18s after
 * apply). The old watcher treated ANY focusedSessionId change while overlay.active
 * as New Chat, then resetSessionOverlay + sometimes host.newChat again.
 *
 * Rules (Mechanic Promax hotfix reconciled here — do not regress):
 * 1. Reset overlay ONLY on focusedStoredSessionId non-null → null/empty (user New Chat).
 *    Ignore focusedSessionId string churn (first-prompt persist).
 * 2. After that reset, do NOT call host.newChat (user already has the blank chat).
 * 3. applyInProgress stays true across apply until session atoms settle
 *    (APPLY_GATE_MS), refreshing sessionId/storedId while gated.
 * 4. Persona/clone apply and Standard Hermes clear do NOT call host.newChat.
 *    After companion apply/reset, refresh the focused live session.
 *    Prefer ambient host.request when the focused profile matches
 *    host.state.profile (active gateway). Use requestProfile(fullRoute)
 *    only when that is not gateway-safe. Never pass a bare profile string.
 *    Live-applied only if result.info != null.
 * 5. focusedSessionProfile change is per-profile Studio state (Promax Magellan):
 *    do not keep another profile's persona selected without applying it.
 *    A profile without its own active overlay becomes stock (no leaked TTS).
 */
const APPLY_GATE_MS = 8000;

function isEmptySessionId(id) {
  if (id == null) return true;
  const text = String(id).trim();
  return text === '' || text === 'null' || text === 'undefined';
}

function isUserNewChatTransition(prevStored, nextStored) {
  return !isEmptySessionId(prevStored) && isEmptySessionId(nextStored);
}

function selectionForAppliedPersona(appliedPersona, personas) {
  if (!appliedPersona) return 'default';
  const slug = String(appliedPersona || '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  const match = (personas || []).find((p) => {
    const id = String(p.id || '');
    const nameSlug = String(p.name || '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
    return id === appliedPersona || id === slug || nameSlug === slug;
  });
  return match ? `persona:${match.id}` : `persona:${slug}`;
}

function decideProfileSwitchTick(overlay, nextProfile, nextStatus) {
  if (overlay && overlay.applyInProgress) {
    return { action: 'gate-refresh', selection: null, resetNewProfile: false, profileId: nextProfile };
  }
  const prev = overlay && overlay.profileId;
  if (!nextProfile || nextProfile === prev) {
    return { action: 'same', selection: null, resetNewProfile: false, profileId: nextProfile || prev || null };
  }
  if (nextStatus && nextStatus.active && nextStatus.applied_persona) {
    return {
      action: 'restore-own',
      selection: nextStatus.applied_persona,
      resetNewProfile: false,
      profileId: nextProfile
    };
  }
  return { action: 'stock', selection: 'default', resetNewProfile: true, profileId: nextProfile };
}

function decideSessionWatchTick(overlay, nextSessionId, nextStoredId, nextProfile) {
  const sessionId = isEmptySessionId(nextSessionId) ? null : nextSessionId;
  const storedId = isEmptySessionId(nextStoredId) ? null : nextStoredId;
  if (overlay && overlay.applyInProgress) {
    return {
      action: 'gate-refresh',
      overlayPatch: { sessionId, storedId, profileId: nextProfile || overlay.profileId || null },
      callNewChat: false
    };
  }
  if (nextProfile && overlay && overlay.profileId && nextProfile !== overlay.profileId) {
    return {
      action: 'profile-switch',
      overlayPatch: { sessionId, storedId },
      callNewChat: false
    };
  }
  if (overlay && overlay.active && isUserNewChatTransition(overlay.storedId, storedId)) {
    return {
      action: 'reset-stock',
      overlayPatch: { active: false, sessionId, storedId, applyInProgress: false },
      callNewChat: false
    };
  }
  return {
    action: 'track',
    overlayPatch: { sessionId, storedId },
    callNewChat: false
  };
}
// SESSION_WATCH_END

function emptyOverlayState(extra) {
  return Object.assign({
    active: false,
    sessionId: null,
    storedId: null,
    profileId: null,
    applyInProgress: false,
    applyGateTimer: null
  }, extra || {});
}

function beginApplyGate(overlay) {
  overlay.applyInProgress = true;
  if (overlay.applyGateTimer) {
    try { clearTimeout(overlay.applyGateTimer); } catch (_) {}
  }
  overlay.applyGateTimer = setTimeout(() => {
    overlay.applyInProgress = false;
    overlay.applyGateTimer = null;
    overlay.sessionId = focusedSessionId();
    overlay.storedId = focusedStoredSessionId();
    overlay.profileId = focusedProfile();
  }, APPLY_GATE_MS);
}

function clearApplyGate(overlay) {
  overlay.applyInProgress = false;
  if (overlay.applyGateTimer) {
    try { clearTimeout(overlay.applyGateTimer); } catch (_) {}
    overlay.applyGateTimer = null;
  }
}

async function resetSessionOverlay(profile, options) {
  try {
    const res = await fetch(`${API_BASE}/profiles/${encodeURIComponent(profile)}/session/reset`, {
      method: 'POST'
    });
    if (!res.ok) return false;
    const refresh = await refreshLiveSessionPersonality('none');
    if (!refresh.ok && options && options.notifyOnRefreshFailure && refresh.skipped !== 'no-session') {
      notifyHost(
        'warning',
        'Live session not refreshed',
        `Stock Hermes restored in config, but this open chat may still use the previous personality (${refresh.skipped || refresh.error || 'refresh failed'}).`
      );
    }
    return true;
  } catch (err) {
    console.warn('[PersonaStudio] session reset failed:', err);
    return false;
  }
}

async function fetchOverlayStatus(profile) {
  try {
    const res = await fetch(`${API_BASE}/session/state?profile_id=${encodeURIComponent(profile)}`);
    if (!res.ok) return { active: false, applied_persona: '', profile_id: profile };
    return await res.json();
  } catch (err) {
    console.warn('[PersonaStudio] session state failed:', err);
    return { active: false, applied_persona: '', profile_id: profile };
  }
}

// STUDIO_APPLY_BEGIN
async function applySpeakingBundleToProfile({
  overlay,
  profile,
  bundle,
  voiceMatch,
  explicit,
  characterStrengthOverride
}) {
  const prompt = (bundle.system_prompt || '').trim() || fallbackSystemPrompt(bundle.name, voiceMatch && voiceMatch.description);
  let boundProvider = bundle.provider || (voiceMatch && voiceMatch.provider) || 'voicebox';
  let boundVoiceId = (bundle.voice_id && bundle.voice_id !== 'default') ? bundle.voice_id : (voiceMatch && voiceMatch.id);
  let boundVoiceName = bundle.voice_name || (voiceMatch && voiceMatch.name) || boundVoiceId;
  let resolveReason = 'bundle';
  try {
    const resolveRes = await fetch(`${API_BASE}/resolve-tts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        persona_id: bundle.id,
        voice_id: voiceMatch ? voiceMatch.id : (bundle.voice_id || null),
        provider: voiceMatch ? voiceMatch.provider : (explicit ? boundProvider : null),
        explicit: !!explicit,
        profile_id: profile
      })
    });
    if (resolveRes.ok) {
      const resolved = await resolveRes.json();
      if (resolved.voice_id) {
        boundProvider = resolved.provider || boundProvider;
        boundVoiceId = resolved.voice_id;
        boundVoiceName = resolved.voice_name || boundVoiceName;
        resolveReason = resolved.reason || resolveReason;
      }
    }
  } catch (e) {
    console.warn('[PersonaStudio] TTS resolve error, using bundle voice:', e);
  }

  const applyStrength = characterStrengthOverride != null
    ? characterStrengthPercent(characterStrengthOverride)
    : characterStrengthPercent(bundle.character_strength);

  beginApplyGate(overlay);
  let applied = false;
  let liveRefreshed = false;
  let refreshNote = '';
  try {
    const applyRes = await fetch(`${API_BASE}/profiles/${encodeURIComponent(profile)}/session/apply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        persona_id: bundle.id,
        persona_name: bundle.name,
        persona_prompt: prompt,
        provider: boundProvider,
        voice_id: boundVoiceId && boundVoiceId !== 'default' ? boundVoiceId : null,
        voice_name: boundVoiceName,
        character_strength: applyStrength
      })
    });
    applied = applyRes.ok;
    if (applyRes.ok) {
      let applyData = {};
      try { applyData = await applyRes.json(); } catch (_) { applyData = {}; }
      overlay.active = true;
      overlay.profileId = profile;
      overlay.sessionId = focusedSessionId();
      overlay.storedId = focusedStoredSessionId();
      const appliedStrength = characterStrengthPercent(
        applyData.character_strength != null ? applyData.character_strength : applyStrength
      );
      const personaKey = appliedStrength <= 0
        ? 'none'
        : (applyData.persona || catalogPersonalityKey(bundle.name));
      const refresh = await refreshLiveSessionPersonality(personaKey);
      liveRefreshed = !!refresh.ok;
      refreshNote = refresh.skipped || refresh.error || '';
      if (!refresh.ok && refresh.skipped !== 'no-session') {
        notifyHost(
          'warning',
          'Live session not refreshed',
          `Applied ${personaKey} in config only — this open chat may still use the previous personality (${refreshNote || 'refresh failed'}).`
        );
      }
    } else {
      console.warn('[PersonaStudio] Session apply failed');
      clearApplyGate(overlay);
    }
  } catch (e) {
    console.warn('[PersonaStudio] Session apply error:', e);
    clearApplyGate(overlay);
  }

  const ttsLabel = providerLabel(boundProvider);
  if (applied && (liveRefreshed || refreshNote === 'no-session')) {
    notifyHost(
      'success',
      `${bundle.avatar || '🎭'} ${bundle.name} · ${ttsLabel}`,
      refreshNote === 'no-session'
        ? `Applied ${bundle.name} + ${ttsLabel} to "${profile}". Next chat message will use this persona.`
        : `Live session refreshed — next reply in this chat uses ${bundle.name} + ${ttsLabel}. New Chat returns to stock.`
    );
  } else if (applied) {
    notifyHost(
      'warning',
      `${bundle.avatar || '🎭'} ${bundle.name} · ${ttsLabel}`,
      `Config only — ${bundle.name} is saved, but this open chat was not live-refreshed${refreshNote ? ` (${refreshNote})` : ''}.`
    );
  } else {
    notifyHost(
      'error',
      `${bundle.avatar || '🎭'} ${bundle.name} · ${ttsLabel}`,
      `Failed to apply speaking persona on "${profile}"`
    );
  }

  window.__ACTIVE_PERSONA_STUDIO__ = applied
    ? { ...bundle, apply_provider: boundProvider, apply_voice_id: boundVoiceId, apply_reason: resolveReason, scope: 'session' }
    : null;

  return {
    applied,
    liveRefreshed,
    refreshNote,
    boundProvider,
    boundVoiceId,
    boundVoiceName,
    resolveReason
  };
}
// STUDIO_APPLY_END

// ── Audio Preview Helper (Robust Blob-URL playback) ────────────────────────
let activeAudio = null;
function playAudioBase64(b64, mime = 'audio/wav') {
  try {
    if (activeAudio) {
      activeAudio.pause();
      activeAudio.src = '';
      activeAudio = null;
    }

    const byteCharacters = atob(b64);
    const byteNumbers = new Array(byteCharacters.length);
    for (let i = 0; i < byteCharacters.length; i++) {
      byteNumbers[i] = byteCharacters.charCodeAt(i);
    }
    const byteArray = new Uint8Array(byteNumbers);
    const blob = new Blob([byteArray], { type: mime });
    const blobUrl = URL.createObjectURL(blob);

    const snd = new Audio(blobUrl);
    activeAudio = snd;
    snd.onended = () => {
      URL.revokeObjectURL(blobUrl);
      if (activeAudio === snd) activeAudio = null;
    };
    snd.onerror = (e) => {
      console.error('[PersonaStudio] Audio playback error:', e);
      URL.revokeObjectURL(blobUrl);
      if (activeAudio === snd) activeAudio = null;
    };
    
    const playPromise = snd.play();
    if (playPromise !== undefined) {
      playPromise.catch(err => {
        console.warn('[PersonaStudio] Autoplay blocked, retrying on interaction:', err);
      });
    }
  } catch (err) {
    console.error('[PersonaStudio] Failed to prepare audio playback:', err);
  }
}

// ── Group Chat Voice & Speech Sanitizer ──────────────────────────────────
const SPEECH_EMOJI_RE = /(?:[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}]|[\u{FE0F}\u{200D}]|[\u{E0020}-\u{E007F}])+/gu;
const SPEECH_FENCED_CODE_RE = /```[\s\S]*?(?:```|$)/g;
const SPEECH_INLINE_CODE_RE = /`([^`]+)`/g;
const SPEECH_MARKDOWN_LINK_RE = /\[([^\]]+)\]\(([^)]+)\)/g;
const SPEECH_PARAGRAPH_BREAK_RE = /[ \t]*\n{2,}[ \t]*/g;
const SPEECH_PUNCTUATED_PARAGRAPH_BREAK_RE = /([.!?])([*_~`>"'’”)}\]]*)[ \t]*\n{2,}[ \t]*/g;
const SPEECH_SOFT_BREAK_RE = /[ \t]*\n[ \t]*/g;
const SPEECH_MEDIA_PATH_RE = /[ \t]*MEDIA:\S+?(?=[.,;:!?)\]]*(?:\s|$))/g;
const SPEECH_LINE_FINAL_COLON_RE = /:\s*$/gm;
const SPEECH_THINKING_PREFIX_RE = /^\s*(?:\([^)\n]{1,48}\)\s*)?(?:processing|thinking|reasoning|analyzing|pondering|contemplating|musing|cogitating|ruminating|deliberating|mulling|reflecting|computing|synthesizing|formulating|brainstorming)\.\.\.\s*/i;
const SPEECH_URL_RE = /\bhttps?:\/\/\S+/gi;

function sanitizeTextForSpeech(text) {
  if (!text) return '';
  let str = String(text);
  str = str.replace(SPEECH_FENCED_CODE_RE, '');
  // Remove markdown tables (lines starting with | or separator rows)
  str = str.split('\n').filter(line => !line.trim().startsWith('|') && !line.includes('|-')).join('\n');
  str = str.replace(SPEECH_THINKING_PREFIX_RE, ' ');
  str = str.replace(SPEECH_LINE_FINAL_COLON_RE, '.');
  str = str.replace(/\r\n?/g, '\n')
           .replace(SPEECH_PUNCTUATED_PARAGRAPH_BREAK_RE, '$1$2 ')
           .replace(SPEECH_PARAGRAPH_BREAK_RE, '. ')
           .replace(SPEECH_SOFT_BREAK_RE, ' ');
  str = str.replace(SPEECH_MARKDOWN_LINK_RE, '$1');
  str = str.replace(SPEECH_INLINE_CODE_RE, '$1');
  str = str.replace(SPEECH_URL_RE, '');
  str = str.replace(SPEECH_MEDIA_PATH_RE, '');
  str = str.replace(SPEECH_EMOJI_RE, ' ');
  str = str.replace(/^#{1,6}\s+/gm, '')
           .replace(/[*_~>#]/g, '')
           .replace(/^\s*[-+*]\s+/gm, '')
           .replace(/:\s*$/, '.')
           .replace(/\s+/g, ' ')
           .trim();
  return str;
}

function resolveProfileForSpeaker(speakerName, profiles) {
  if (!speakerName || !profiles || !profiles.length) return null;
  const raw = String(speakerName).trim().replace(/^@/, '');
  const clean = raw.toLowerCase().replace(/[-_]/g, ' ');
  const cleanSlug = slugifyName(raw);

  // 1. Direct exact id or title match
  for (const p of profiles) {
    if (p.id && (p.id.toLowerCase() === clean || slugifyName(p.id) === cleanSlug)) return p;
    if (p.title && (p.title.toLowerCase() === clean || slugifyName(p.title) === cleanSlug)) return p;
  }

  // 2. Token / substring containment
  for (const p of profiles) {
    const pTitle = (p.title || '').toLowerCase();
    const pId = (p.id || '').toLowerCase();
    if (pId && (clean.includes(pId) || pId.includes(clean))) return p;
    if (pTitle && (clean.includes(pTitle) || pTitle.includes(clean))) return p;
  }

  // 3. Name match score
  let bestScore = 0;
  let bestProfile = null;
  for (const p of profiles) {
    const sId = nameMatchScore(raw, p.id || '');
    const sTitle = nameMatchScore(raw, p.title || '');
    const score = Math.max(sId, sTitle);
    if (score > bestScore) {
      bestScore = score;
      bestProfile = p;
    }
  }
  if (bestScore > 50) return bestProfile;

  // 4. Fallback to default or first
  const def = profiles.find(p => p.id === 'default');
  return def || profiles[0];
}

const SVG_SPEAKER_ICON = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><path d="M15.54 8.46a5 5 0 0 1 0 7.07"></path><path d="M19.07 4.93a10 10 0 0 1 0 14.14"></path></svg>';
const SVG_STOP_ICON = '<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"></rect></svg>';
const SVG_LOADING_ICON = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="animate-spin"><circle cx="12" cy="12" r="9" stroke-dasharray="32" stroke-dashoffset="12"></circle></svg>';

class GroupSpeechQueue {
  constructor() {
    this.queue = [];
    this.isPlaying = false;
    this.currentTask = null;
    this.activeAudio = null;
  }

  isSpeakingTask(taskRef) {
    return this.isPlaying && this.currentTask && this.currentTask.id === taskRef;
  }

  enqueue(task) {
    this.queue.push(task);
    this.process();
  }

  stopAll() {
    this.queue = [];
    if (this.activeAudio) {
      try {
        this.activeAudio.pause();
        this.activeAudio.src = '';
      } catch (_) {}
      this.activeAudio = null;
    }
    if (this.currentTask && this.currentTask.onEnd) {
      try { this.currentTask.onEnd(); } catch (_) {}
    }
    this.currentTask = null;
    this.isPlaying = false;
  }

  async process() {
    if (this.isPlaying) return;
    if (this.queue.length === 0) return;

    this.isPlaying = true;
    const task = this.queue.shift();
    this.currentTask = task;

    if (task.onStart) {
      try { task.onStart(); } catch (_) {}
    }

    try {
      const resp = await fetch(`${API_BASE}/speak-profile`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ profile_id: task.profileId, text: task.text })
      });
      if (!resp.ok) {
        throw new Error(`Synthesis HTTP error: ${resp.status}`);
      }
      const data = await resp.json();
      if (!data.ok || !data.audio_base64) {
        throw new Error(data.error || 'Empty audio returned');
      }

      await new Promise((resolve) => {
        try {
          const byteChars = atob(data.audio_base64);
          const byteNumbers = new Uint8Array(byteChars.length);
          for (let i = 0; i < byteChars.length; i++) {
            byteNumbers[i] = byteChars.charCodeAt(i);
          }
          const blob = new Blob([byteNumbers], { type: data.format || 'audio/wav' });
          const blobUrl = URL.createObjectURL(blob);
          const audio = new Audio(blobUrl);
          this.activeAudio = audio;

          const finish = () => {
            URL.revokeObjectURL(blobUrl);
            if (this.activeAudio === audio) this.activeAudio = null;
            resolve();
          };

          audio.onended = finish;
          audio.onerror = (e) => {
            console.error('[PersonaStudio] Group audio playback error:', e);
            finish();
          };

          const p = audio.play();
          if (p !== undefined) {
            p.catch((err) => {
              console.warn('[PersonaStudio] Audio play interrupted/blocked:', err);
              finish();
            });
          }
        } catch (err) {
          console.error('[PersonaStudio] Failed to play audio:', err);
          resolve();
        }
      });
    } catch (err) {
      console.warn('[PersonaStudio] Group speech error:', err);
      if (task.onError) {
        try { task.onError(err); } catch (_) {}
      }
    } finally {
      if (task.onEnd) {
        try { task.onEnd(); } catch (_) {}
      }
      this.currentTask = null;
      this.isPlaying = false;
      this.process();
    }
  }
}

const groupSpeechQueue = new GroupSpeechQueue();

function useGroupChatVoiceEnhancer({ autoReadGroup, botProfiles }) {
  const autoReadRef = useRef(autoReadGroup);
  autoReadRef.current = autoReadGroup;

  const botProfilesRef = useRef(botProfiles);
  botProfilesRef.current = botProfiles;

  const initializedRef = useRef(false);

  useEffect(() => {
    // 1. Initial scan: mark existing messages so historical chat is not spoken aloud on load
    const existing = document.querySelectorAll('div[data-slot="group-chat-message-content"]');
    existing.forEach((el) => {
      el.dataset.personastudioSeen = '1';
    });
    // Short delay before enabling auto-read to avoid catching messages rendering during initial mount
    const timer = setTimeout(() => {
      initializedRef.current = true;
    }, 1200);

    const checkAndEnhanceMessage = (contentEl) => {
      if (!contentEl || !contentEl.isConnected) return;
      const entryRow = contentEl.closest('.group') || contentEl.parentElement;
      if (!entryRow) return;

      // Determine speaker
      const replyBtn = entryRow.querySelector('button[aria-label^="Reply to "]');
      let speaker = '';
      if (replyBtn) {
        const aria = replyBtn.getAttribute('aria-label') || '';
        speaker = aria.replace(/^Reply to\s+/i, '').trim();
      } else {
        const nameBtn = entryRow.querySelector('button.text-left');
        if (nameBtn) speaker = (nameBtn.textContent || '').trim();
      }

      // If user message, skip
      if (!speaker || speaker.toLowerCase() === 'you') return;

      // Inject Read Aloud button into action bar if not already present
      const actionBar = entryRow.querySelector('div.ml-auto');
      if (actionBar && !actionBar.querySelector('.personastudio-group-speak')) {
        const btn = document.createElement('button');
        btn.className = 'personastudio-group-speak inline-flex items-center justify-center rounded text-xs transition-colors hover:bg-muted text-muted-foreground hover:text-foreground h-6 w-6 p-0 shrink-0';
        btn.setAttribute('type', 'button');
        btn.setAttribute('title', `Read aloud with ${speaker}`);
        btn.setAttribute('aria-label', `Read aloud with ${speaker}`);
        btn.innerHTML = SVG_SPEAKER_ICON;

        btn.onclick = (e) => {
          e.stopPropagation();
          e.preventDefault();

          if (groupSpeechQueue.isSpeakingTask(contentEl)) {
            groupSpeechQueue.stopAll();
            return;
          }

          const rawText = contentEl.innerText || contentEl.textContent || '';
          const text = sanitizeTextForSpeech(rawText);
          if (!text) return;

          const profile = resolveProfileForSpeaker(speaker, botProfilesRef.current);
          const profileId = profile ? profile.id : 'default';

          btn.innerHTML = SVG_LOADING_ICON;
          btn.classList.add('text-primary');

          groupSpeechQueue.enqueue({
            id: contentEl,
            speaker,
            profileId,
            text,
            buttonEl: btn,
            onStart: () => {
              btn.innerHTML = SVG_STOP_ICON;
              btn.classList.add('text-primary');
              btn.setAttribute('title', 'Stop reading');
            },
            onEnd: () => {
              btn.innerHTML = SVG_SPEAKER_ICON;
              btn.classList.remove('text-primary');
              btn.setAttribute('title', `Read aloud with ${speaker}`);
            },
            onError: () => {
              btn.innerHTML = SVG_SPEAKER_ICON;
              btn.classList.remove('text-primary');
              btn.setAttribute('title', `Read aloud with ${speaker}`);
            }
          });
        };

        actionBar.appendChild(btn);
      }

      // Auto-read logic for new incoming messages
      if (initializedRef.current && autoReadRef.current && !contentEl.dataset.personastudioSpoken) {
        if (!contentEl.dataset.personastudioSeen) {
          contentEl.dataset.personastudioSeen = '1';
          contentEl.dataset.personastudioSpoken = '1';

          // Delay slightly (350ms) to ensure full message turn has landed
          setTimeout(() => {
            const rawText = contentEl.innerText || contentEl.textContent || '';
            const text = sanitizeTextForSpeech(rawText);
            if (!text) return;

            const profile = resolveProfileForSpeaker(speaker, botProfilesRef.current);
            const profileId = profile ? profile.id : 'default';
            const btn = entryRow.querySelector('.personastudio-group-speak');

            groupSpeechQueue.enqueue({
              id: contentEl,
              speaker,
              profileId,
              text,
              buttonEl: btn,
              onStart: () => {
                if (btn) {
                  btn.innerHTML = SVG_STOP_ICON;
                  btn.classList.add('text-primary');
                  btn.setAttribute('title', 'Stop reading');
                }
              },
              onEnd: () => {
                if (btn) {
                  btn.innerHTML = SVG_SPEAKER_ICON;
                  btn.classList.remove('text-primary');
                  btn.setAttribute('title', `Read aloud with ${speaker}`);
                }
              },
              onError: () => {
                if (btn) {
                  btn.innerHTML = SVG_SPEAKER_ICON;
                  btn.classList.remove('text-primary');
                  btn.setAttribute('title', `Read aloud with ${speaker}`);
                }
              }
            });
          }, 350);
        }
      }
    };

    const scanAll = () => {
      const messages = document.querySelectorAll('div[data-slot="group-chat-message-content"]');
      messages.forEach(checkAndEnhanceMessage);
    };
    scanAll();

    const observer = new MutationObserver(() => {
      scanAll();
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true
    });

    return () => {
      clearTimeout(timer);
      observer.disconnect();
    };
  }, []);
}

// ── Root Plugin Host Wrapper ──────────────────────────────────────────────
function PersonaStudioRoot() {
  const [studioOpen, setStudioOpen] = useState(false);
  const [personas, setPersonas] = useState([]);
  const [voices, setVoices] = useState([]);
  const [botProfiles, setBotProfiles] = useState([]);

  const [autoReadGroup, setAutoReadGroup] = useState(() => {
    try {
      return localStorage.getItem('hermes_personastudio_group_auto_read') === 'true';
    } catch (_) {
      return false;
    }
  });

  const toggleAutoReadGroup = useCallback(() => {
    setAutoReadGroup(prev => {
      const next = !prev;
      try {
        localStorage.setItem('hermes_personastudio_group_auto_read', String(next));
      } catch (_) {}
      return next;
    });
  }, []);

  const refreshPersonas = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/personas`);
      if (res.ok) {
        const list = await res.json();
        setPersonas(list);
      }
    } catch (_) {}
  }, []);

  const refreshVoices = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/voices`);
      if (res.ok) {
        const list = await res.json();
        setVoices((list || []).filter(v => v.voice_type === 'cloned' && v.id && v.id !== 'default')
          .sort((a, b) => {
            const ar = isFishProvider(a.provider) ? 0 : 1;
            const br = isFishProvider(b.provider) ? 0 : 1;
            if (ar !== br) return ar - br;
            return String(a.name || '').localeCompare(String(b.name || ''));
          }));
      }
    } catch (_) {}
  }, []);

  const refreshBotProfiles = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/profiles`);
      if (res.ok) {
        const list = await res.json();
        setBotProfiles(list || []);
      }
    } catch (_) {}
  }, []);

  useEffect(() => {
    refreshPersonas();
    refreshVoices();
    refreshBotProfiles();
    const interval = setInterval(() => {
      refreshPersonas();
      refreshVoices();
      refreshBotProfiles();
    }, 60000);
    const onFocus = () => {
      refreshPersonas();
      refreshVoices();
      refreshBotProfiles();
    };
    window.addEventListener('focus', onFocus);
    return () => {
      clearInterval(interval);
      window.removeEventListener('focus', onFocus);
    };
  }, [refreshPersonas, refreshVoices, refreshBotProfiles]);

  useGroupChatVoiceEnhancer({ autoReadGroup, botProfiles });

  const overlayRef = useRef(emptyOverlayState({ profileId: focusedProfile() }));
  const titlebarApiRef = useRef({ setActiveId: () => {} });

  return jsxs(React.Fragment, {
    children: [
      jsx(TitlebarPersonaPicker, {
        openStudio: () => setStudioOpen(true),
        personas,
        voices,
        refreshPersonas,
        refreshVoices,
        overlayRef,
        titlebarApiRef,
        autoReadGroup,
        toggleAutoReadGroup
      }),
      jsx(StudioModal, {
        open: studioOpen,
        onOpenChange: setStudioOpen,
        refreshPersonas,
        overlayRef,
        titlebarApiRef,
        autoReadGroup,
        toggleAutoReadGroup
      })
    ]
  });
}

// ── Titlebar Persona Picker Component ─────────────────────────────────────
function TitlebarPersonaPicker({ openStudio, personas, voices, refreshPersonas, refreshVoices, overlayRef, titlebarApiRef, autoReadGroup, toggleAutoReadGroup }) {
  const [activeId, setActiveId] = useState('default');
  const [profileId, setProfileId] = useState(() => focusedProfile());
  const personasRef = useRef(personas);
  personasRef.current = personas;
  if (titlebarApiRef) titlebarApiRef.current = { setActiveId };

  const syncTitlebarToFocusedProfile = useCallback(async () => {
    const profile = focusedProfile();
    const overlay = overlayRef.current;
    beginApplyGate(overlay);
    overlay.profileId = profile;
    overlay.sessionId = focusedSessionId();
    overlay.storedId = focusedStoredSessionId();
    setProfileId(profile);
    const status = await fetchOverlayStatus(profile);
    if (status && status.active && status.applied_persona) {
      overlay.active = true;
      setActiveId(selectionForAppliedPersona(status.applied_persona, personasRef.current));
      window.__ACTIVE_PERSONA_STUDIO__ = { id: status.applied_persona, scope: 'session', profile };
    } else {
      overlay.active = false;
      setActiveId('default');
      window.__ACTIVE_PERSONA_STUDIO__ = null;
      await resetSessionOverlay(profile, { notifyOnRefreshFailure: false });
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await fetch(`${API_BASE}/session/reset-all`, { method: 'POST' });
      } catch (err) {
        console.warn('[PersonaStudio] startup session reset-all failed:', err);
      }
      if (cancelled) return;
      overlayRef.current = emptyOverlayState({
        sessionId: focusedSessionId(),
        storedId: focusedStoredSessionId(),
        profileId: focusedProfile()
      });
      setActiveId('default');
      setProfileId(focusedProfile());
      window.__ACTIVE_PERSONA_STUDIO__ = null;
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    overlayRef.current.sessionId = focusedSessionId();
    overlayRef.current.storedId = focusedStoredSessionId();
    overlayRef.current.profileId = focusedProfile();
    const onSessionChange = async () => {
      const overlay = overlayRef.current;
      const profile = focusedProfile();
      const decision = decideSessionWatchTick(overlay, focusedSessionId(), focusedStoredSessionId(), profile);
      Object.assign(overlay, decision.overlayPatch);
      if (decision.action === 'profile-switch') {
        await syncTitlebarToFocusedProfile();
        return;
      }
      if (decision.action !== 'reset-stock') return;
      setActiveId('default');
      window.__ACTIVE_PERSONA_STUDIO__ = null;
      const ok = await resetSessionOverlay(profile);
      // User already has the blank New Chat. Do not call host.newChat again.
      if (ok) {
        notifyHost('info', '🤖 Standard Hermes', 'New chat uses stock Hermes text + voice (Studio overlay cleared)');
      }
    };
    return subscribeFocusedSession(onSessionChange);
  }, [syncTitlebarToFocusedProfile]);

  const onSelectPersona = async (id) => {
    console.log('[PersonaStudio] Selected:', id);
    const selection = parseSelection(id);
    if (selection.kind === '__open_studio__') {
      openStudio();
      return;
    }
    setActiveId(id);

    const profile = focusedProfile();
    const personaMatch = selection.kind === 'persona'
      ? personas.find(p => p.id === selection.personaId)
      : (selection.kind === 'legacy' ? personas.find(p => p.id === selection.id) : null);
    const voiceMatch = selection.kind === 'voice'
      ? voices.find(v => v.id === selection.voiceId && (v.provider === selection.provider || (isFishProvider(v.provider) && isFishProvider(selection.provider))))
      : (selection.kind === 'legacy' ? voices.find(v => v.id === selection.id) : null);

    if (selection.kind === 'default' || id === 'default') {
      beginApplyGate(overlayRef.current);
      try {
        const ok = await resetSessionOverlay(profile, { notifyOnRefreshFailure: true });
        if (ok) {
          overlayRef.current.active = false;
          overlayRef.current.profileId = profile;
          overlayRef.current.sessionId = focusedSessionId();
          overlayRef.current.storedId = focusedStoredSessionId();
          notifyHost('info', '🤖 Standard Hermes', `Stock profile soul on "${profile}" — next reply in this chat, no new session`);
        } else {
          clearApplyGate(overlayRef.current);
        }
      } catch (e) {
        console.warn('[PersonaStudio] Failed to clear persona:', e);
        clearApplyGate(overlayRef.current);
      }
      window.__ACTIVE_PERSONA_STUDIO__ = null;
      return;
    }

    let bundle = personaMatch || null;
    if (!bundle && voiceMatch) {
      bundle = personas.find(p => p.voice_id && p.voice_id === voiceMatch.id)
        || personas.find(p => namesMatch(p.name, voiceMatch.name) || namesMatch(p.id, voiceMatch.name));
    }

    if (!bundle && voiceMatch) {
      notifyHost('warning', '🎙️ Voice-only clone', 'This clone has no persona pack. Open Studio to finish style + voice before applying.');
      setActiveId('default');
      return;
    }

    if (!bundle) return;

    await applySpeakingBundleToProfile({
      overlay: overlayRef.current,
      profile,
      bundle,
      voiceMatch,
      explicit: !!selection.explicit,
      characterStrengthOverride: null
    });
  };

  const listablePersonas = (personas || []).filter((p) => isListablePersonaPack(p, voices));
  const currentLookup = lookupSelection(activeId, listablePersonas, []);
  const currentPersona = currentLookup.persona;
  const current = currentPersona;
  const currentProvider = currentPersona
    ? preferredProviderForPersona(currentPersona, voices)
    : null;
  const triggerLabel = current
    ? `${current.avatar || '🎭'} ${current.name} · ${providerLabel(currentProvider)}`
    : '🎭 Personas';

  return jsxs('div', {
    style: { display: 'flex', alignItems: 'center', gap: '6px', marginRight: '8px' },
    children: [
      jsx(Select, {
        key: `persona-select-${profileId}`,
        value: activeId,
        onValueChange: onSelectPersona,
        children: jsxs('div', {
          children: [
            jsx(SelectTrigger, {
              className: 'h-7 text-xs px-2.5 rounded bg-muted/40 hover:bg-muted border border-border/50 text-foreground font-medium flex items-center gap-1.5 shadow-none transition-colors',
              children: jsx(SelectValue, { placeholder: triggerLabel, children: triggerLabel })
            }),
            jsx(SelectContent, {
              className: 'min-w-[200px] bg-popover text-popover-foreground border border-border shadow-lg rounded-md p-1',
              children: jsxs('div', {
                children: [
                  jsx(SelectItem, {
                    value: 'default',
                    className: 'text-xs py-1.5 px-2 rounded cursor-pointer hover:bg-accent focus:bg-accent',
                    children: '🤖 Standard Hermes'
                  }),
                  listablePersonas.length > 0 && jsxs('div', {
                    children: [
                      jsx('div', { className: 'text-[10px] font-bold text-muted-foreground px-2 pt-1', children: '🎭 PERSONAS (complete packs · Fish when a twin exists)' }),
                      listablePersonas.map(p =>
                        jsx(SelectItem, {
                          key: personaSelectionKey(p),
                          value: personaSelectionKey(p),
                          className: 'text-xs py-1.5 px-2 rounded cursor-pointer hover:bg-accent focus:bg-accent',
                          children: `${p.avatar || '🎭'} ${p.name} · ${providerLabel(preferredProviderForPersona(p, voices))}`
                        })
                      )
                    ]
                  }),
                  jsx('div', { style: { height: '1px', background: 'var(--border)', margin: '4px 0' } }),
                  jsx(SelectItem, {
                    value: '__open_studio__',
                    className: 'text-xs py-1.5 px-2 rounded cursor-pointer hover:bg-primary/20 text-primary font-medium',
                    children: '✨ Open Studio...'
                  })
                ]
              })
            })
          ]
        })
      }),
      jsx(Button, {
        size: 'sm',
        variant: 'ghost',
        className: 'h-7 px-2 text-xs text-muted-foreground hover:text-foreground',
        onClick: openStudio,
        title: 'Open Persona & Voice Studio',
        children: '🎙️ Studio'
      }),
      jsx(Button, {
        size: 'sm',
        variant: autoReadGroup ? 'default' : 'ghost',
        className: `h-7 px-2 text-xs flex items-center gap-1 transition-colors ${
          autoReadGroup
            ? 'bg-primary/20 text-primary border border-primary/40 hover:bg-primary/30 font-semibold'
            : 'text-muted-foreground hover:text-foreground'
        }`,
        onClick: toggleAutoReadGroup,
        title: autoReadGroup
          ? 'Group Chat Voice: Auto-read ON (Click to disable)'
          : 'Group Chat Voice: Auto-read OFF (Click to enable)',
        children: [
          jsx('span', { className: 'text-[11px]', children: autoReadGroup ? '🔊' : '🔈' }),
          jsx('span', { className: 'text-[11px]', children: autoReadGroup ? 'Group: ON' : 'Group Voice' })
        ]
      })
    ]
  });
}

// ── Voice & Persona Studio Dialog Modal ───────────────────────────────────
function StudioModal({ open, onOpenChange, refreshPersonas, overlayRef, titlebarApiRef, autoReadGroup, toggleAutoReadGroup }) {
  const [activeTab, setActiveTab] = useState('apply'); // 'apply' | 'builder'
  const [provider, setProvider] = useState('fish_audio');
  const [voices, setVoices] = useState([]);
  const [models, setModels] = useState([]);
  const [selectedModel, setSelectedModel] = useState('luxtts');
  const [selectedVoice, setSelectedVoice] = useState('');
  const [name, setName] = useState('');
  const [avatar, setAvatar] = useState('🤖');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [speed, setSpeed] = useState(1.0);
  const [temperature, setTemperature] = useState(0.7);
  const [characterStrength, setCharacterStrength] = useState(25);
  const [studioPacks, setStudioPacks] = useState([]);
  const [editingPackId, setEditingPackId] = useState('');
  const pendingVoiceRef = useRef('');

  // Audition state
  const [previewText, setPreviewText] = useState('Hello Chuck! This is your voice persona ready to roll.');
  const [isAuditioning, setIsAuditioning] = useState(false);
  const [statusMessage, setStatusMessage] = useState('');

  // Voice cloning upload state
  const [cloneName, setCloneName] = useState('');
  const [cloneFile, setCloneFile] = useState(null);
  const [isCloning, setIsCloning] = useState(false);

  // Model & Voice management state
  const [showManager, setShowManager] = useState(false);
  const [filterQuery, setFilterQuery] = useState('');
  const [isManagingVoice, setIsManagingVoice] = useState(false);

  // Bot Profiles assignment state
  const [botProfiles, setBotProfiles] = useState([]);
  const [selectedBotProfile, setSelectedBotProfile] = useState('');
  const [isAssigning, setIsAssigning] = useState(false);
  const [isApplying, setIsApplying] = useState(false);
  const [targetProfile, setTargetProfile] = useState(() => focusedProfile());
  const [liveStatus, setLiveStatus] = useState({ active: false, applied_persona: '', profile_id: focusedProfile() });

  // Load voices, models, and bot profiles
  const loadData = useCallback(async (prov) => {
    try {
      setStatusMessage('Loading voices, models, and bot profiles...');
      const [vRes, mRes, pRes] = await Promise.all([
        fetch(`${API_BASE}/voices?provider=${prov}`),
        fetch(`${API_BASE}/models?provider=${prov}`),
        fetch(`${API_BASE}/profiles`)
      ]);
      
      if (vRes.ok) {
        const vList = await vRes.json();
        setVoices(vList);
        if (vList.length > 0) {
          setSelectedVoice((prev) => {
            const pending = pendingVoiceRef.current;
            if (pending) {
              pendingVoiceRef.current = '';
              if (vList.some((v) => v.id === pending)) return pending;
            }
            if (prev && vList.some((v) => v.id === prev)) return prev;
            return vList[0].id;
          });
        }
      }
      
      if (mRes.ok) {
        const mList = await mRes.json();
        setModels(mList);
        if (mList.length > 0) {
          const rec = mList.find(m => m.recommended) || mList[0];
          // Keep an in-list selection (incl. pack-hydrated engine). Only default to recommended when unset.
          setSelectedModel((prev) => {
            if (prev && mList.some((m) => m.id === prev)) return prev;
            return rec.id;
          });
        }
      }

      if (pRes.ok) {
        const pList = await pRes.json();
        setBotProfiles(pList);
        if (pList.length > 0) {
          setSelectedBotProfile(prev => prev || pList[0].id);
        }
      }
      setStatusMessage('');
    } catch (e) {
      setStatusMessage('Backend companion unreachable at 127.0.0.1:17495');
    }
  }, []);

  const loadStudioPacks = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/personas`);
      if (res.ok) setStudioPacks(await res.json());
    } catch (_) {}
  }, []);

  useEffect(() => {
    if (open) {
      loadStudioPacks();
      loadData(provider);
    }
  }, [open, provider, loadData, loadStudioPacks]);

  const refreshLiveStatus = useCallback(async () => {
    const profile = focusedProfile();
    setTargetProfile(profile);
    setLiveStatus(await fetchOverlayStatus(profile));
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    refreshLiveStatus();
    return subscribeFocusedSession(() => { refreshLiveStatus(); });
  }, [open, refreshLiveStatus]);

  const applyPackToForm = (pack) => {
    const hydrated = hydrateFormFromPack(pack);
    if (!hydrated) {
      setEditingPackId('');
      setName('');
      setAvatar('🤖');
      setSystemPrompt('');
      setCharacterStrength(25);
      setSpeed(1.0);
      setTemperature(0.7);
      return;
    }
    setEditingPackId(hydrated.id);
    setName(hydrated.name);
    setAvatar(hydrated.avatar);
    setSystemPrompt(hydrated.systemPrompt);
    setCharacterStrength(hydrated.characterStrength);
    setSpeed(hydrated.speed);
    setTemperature(hydrated.temperature);
    // Prefer pack.engine; else Voicebox profile default_engine for the bound voice.
    const voiceEngine = (() => {
      if (hydrated.engine) return hydrated.engine;
      const vid = hydrated.selectedVoice;
      if (!vid) return '';
      const match = (voices || []).find((v) => v && v.id === vid);
      return (match && (match.default_engine || (match.extra && match.extra.engine))) || '';
    })();
    if (voiceEngine) setSelectedModel(voiceEngine);
    if (hydrated.provider && hydrated.provider !== provider) {
      pendingVoiceRef.current = hydrated.selectedVoice;
      setProvider(hydrated.provider);
    } else if (hydrated.selectedVoice) {
      setSelectedVoice(hydrated.selectedVoice);
    }
  };

  // Delete voice from provider
  const handleDeleteVoice = async (voiceId, voiceName) => {
    if (!confirm(`Are you sure you want to permanently delete voice "${voiceName}" from ${provider}?`)) {
      return;
    }
    setIsManagingVoice(true);
    setStatusMessage(`Deleting voice ${voiceName}...`);
    try {
      const res = await fetch(`${API_BASE}/voices/${provider}/${voiceId}`, {
        method: 'DELETE',
      });
      if (res.ok) {
        setStatusMessage(`Successfully deleted "${voiceName}"`);
        await loadData(provider);
      } else {
        const err = await res.json();
        alert(`Failed to delete: ${err.detail || 'Unknown error'}`);
      }
    } catch (e) {
      alert(`Error deleting voice: ${e.message}`);
    } finally {
      setIsManagingVoice(false);
    }
  };

  // Re-sample voice reference audio
  const handleResampleVoice = async (voiceId, voiceName, file) => {
    if (!file) return;
    setIsManagingVoice(true);
    setStatusMessage(`Updating reference audio for ${voiceName}...`);
    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('reference_text', 'Updated high quality reference voice sample.');

      const res = await fetch(`${API_BASE}/voices/${provider}/${voiceId}/resample`, {
        method: 'POST',
        body: formData,
      });
      if (res.ok) {
        setStatusMessage(`Successfully re-sampled "${voiceName}" with new audio sample!`);
        await loadData(provider);
      } else {
        const err = await res.json();
        alert(`Failed to re-sample: ${err.detail || 'Error'}`);
      }
    } catch (e) {
      alert(`Error re-sampling voice: ${e.message}`);
    } finally {
      setIsManagingVoice(false);
    }
  };

  // Audition preview
  const handleAudition = async () => {
    if (!selectedVoice) {
      setStatusMessage('Please select a voice first.');
      return;
    }
    setIsAuditioning(true);
    setStatusMessage('Generating voice preview on GPU / Cloud...');
    try {
      const res = await fetch(`${API_BASE}/audition`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: previewText,
          provider: provider,
          voice_id: selectedVoice,
          engine: selectedModel,
          speed: parseFloat(speed),
          temperature: parseFloat(temperature)
        })
      });
      const data = await res.json();
      if (data.ok && data.audio_base64) {
        playAudioBase64(data.audio_base64, data.format || 'audio/wav');
        setStatusMessage('Playing sample preview 🔊');
      } else {
        setStatusMessage(`Synthesis failed: ${data.detail || 'Unknown error'}`);
      }
    } catch (e) {
      setStatusMessage(`Audition error: ${e.message}`);
    } finally {
      setIsAuditioning(false);
    }
  };

  // Create clone with chosen model
  const handleCloneUpload = async () => {
    if (!cloneName || !cloneFile) {
      alert('Please specify a voice name and select an audio file.');
      return;
    }
    setIsCloning(true);
    setStatusMessage(`Uploading sample and cloning with model '${selectedModel}'...`);
    try {
      const formData = new FormData();
      formData.append('name', cloneName);
      formData.append('provider', provider);
      formData.append('engine', selectedModel);
      formData.append('file', cloneFile);

      const res = await fetch(`${API_BASE}/clone`, {
        method: 'POST',
        body: formData
      });
      const data = await res.json();
      if (data.ok && data.voice) {
        const personaName = data.persona ? data.persona.name : data.voice.name;
        setStatusMessage(
          data.persona
            ? `Cloned '${data.voice.name}' and saved speaking persona '${personaName}' (prompt + bound voice).`
            : `Successfully cloned voice '${data.voice.name}' using model ${selectedModel}!`
        );
        await loadData(provider);
        refreshPersonas?.();
        setSelectedVoice(data.voice.id);
        setCloneName('');
        setCloneFile(null);
      } else {
        setStatusMessage(`Cloning failed: ${data.detail || 'Error'}`);
      }
    } catch (e) {
      setStatusMessage(`Cloning error: ${e.message}`);
    } finally {
      setIsCloning(false);
    }
  };

  // Save full Persona (PUT existing pack, POST new). Keep Studio open.
  const persistStudioPack = async () => {
    const selectedPack = studioPacks.find((p) => p.id === editingPackId) || null;
    const chosenV = voices.find(v => v.id === selectedVoice);
    const plan = personaSaveRequest({
      editingId: editingPackId,
      name: name,
      selectedPack: selectedPack,
      avatar: avatar,
      systemPrompt: systemPrompt,
      provider: provider,
      selectedVoice: selectedVoice,
      voiceName: chosenV ? chosenV.name : selectedVoice,
      speed: speed,
      temperature: temperature,
      characterStrength: characterStrength,
      engine: selectedModel,
      selectedModel: selectedModel
    });
    if (plan.error) return { ok: false, error: plan.error, plan };
    const res = await fetch(`${API_BASE}${plan.url}`, {
      method: plan.method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(plan.body)
    });
    if (!res.ok) return { ok: false, error: 'Failed to save persona.', plan };
    let data = {};
    try {
      data = await res.json();
    } catch (_) {
      data = {};
    }
    const saved = (data && data.persona) || {};
    const strength = characterStrengthPercent(saved.character_strength != null ? saved.character_strength : plan.body.character_strength);
    try {
      if (saved.id) {
        setEditingPackId(saved.id);
        setName(saved.name || plan.body.name);
        if (saved.character_strength != null) setCharacterStrength(characterStrengthPercent(saved.character_strength));
      }
      await loadStudioPacks();
      refreshPersonas?.();
    } catch (refreshErr) {
      console.warn('[PersonaStudio] Post-save refresh failed:', refreshErr);
    }
    return { ok: true, saved, plan, strength };
  };

  const handleSavePersona = async () => {
    try {
      const result = await persistStudioPack();
      if (!result.ok) {
        alert(result.error);
        return;
      }
      notifyHost(
        'success',
        result.plan.method === 'PUT' ? 'Persona Updated' : 'Persona Saved',
        `${result.saved.name || result.plan.body.name} — Character strength ${result.strength}%`
      );
    } catch (e) {
      alert(`Error saving persona: ${e.message}`);
    }
  };

  const handleApplyToChat = async () => {
    const profile = focusedProfile();
    setTargetProfile(profile);
    setIsApplying(true);
    setStatusMessage(`Applying to "${profile}"…`);
    try {
      const persist = await persistStudioPack();
      if (!persist.ok) {
        alert(persist.error);
        setStatusMessage(persist.error);
        return;
      }
      const packs = await (async () => {
        try {
          const res = await fetch(`${API_BASE}/personas`);
          if (res.ok) return await res.json();
        } catch (_) {}
        return studioPacks;
      })();
      const bundleId = persist.saved.id || editingPackId;
      const bundle = (packs || []).find((p) => p.id === bundleId) || persist.saved;
      if (!bundle || !bundle.id) {
        setStatusMessage('Save a persona pack before applying.');
        return;
      }
      const voiceMatch = voices.find((v) => v.id === selectedVoice) || null;
      const applyResult = await applySpeakingBundleToProfile({
        overlay: overlayRef.current,
        profile,
        bundle: {
          ...bundle,
          system_prompt: systemPrompt || bundle.system_prompt,
          avatar: avatar || bundle.avatar,
          name: name || bundle.name
        },
        voiceMatch,
        explicit: true,
        characterStrengthOverride: characterStrength
      });
      if (applyResult.applied && titlebarApiRef && titlebarApiRef.current && typeof titlebarApiRef.current.setActiveId === 'function') {
        titlebarApiRef.current.setActiveId(personaSelectionKey(bundle));
      }
      await refreshLiveStatus();
      const live = formatStudioLiveStatus(await fetchOverlayStatus(profile));
      setStatusMessage(applyResult.applied ? live.headline : `Apply failed on "${profile}"`);
    } catch (e) {
      setStatusMessage(`Apply error: ${e.message}`);
    } finally {
      setIsApplying(false);
    }
  };

  const handleResetStock = async () => {
    const profile = focusedProfile();
    setTargetProfile(profile);
    beginApplyGate(overlayRef.current);
    try {
      const ok = await resetSessionOverlay(profile, { notifyOnRefreshFailure: true });
      if (ok) {
        overlayRef.current.active = false;
        overlayRef.current.profileId = profile;
        overlayRef.current.sessionId = focusedSessionId();
        overlayRef.current.storedId = focusedStoredSessionId();
        window.__ACTIVE_PERSONA_STUDIO__ = null;
        if (titlebarApiRef && titlebarApiRef.current && typeof titlebarApiRef.current.setActiveId === 'function') {
          titlebarApiRef.current.setActiveId('default');
        }
        notifyHost('info', '🤖 Standard Hermes', `Stock profile soul on "${profile}" — next reply in this chat, no new session`);
        await refreshLiveStatus();
        setStatusMessage(`Stock Hermes restored on "${profile}"`);
      } else {
        clearApplyGate(overlayRef.current);
        setStatusMessage('Could not reset to stock Hermes.');
      }
    } catch (e) {
      clearApplyGate(overlayRef.current);
      setStatusMessage(`Reset error: ${e.message}`);
    }
  };

  // Assign current selected voice to a Hermes Bot Profile
  const handleAssignVoiceToBot = async () => {
    if (!selectedBotProfile) {
      alert('Please select a bot profile to assign this voice to.');
      return;
    }
    const chosenV = voices.find(v => v.id === selectedVoice);
    const voiceName = chosenV ? chosenV.name : selectedVoice;
    setIsAssigning(true);
    setStatusMessage(`Assigning ${voiceName} to profile '${selectedBotProfile}'...`);
    try {
      const res = await fetch(`${API_BASE}/profiles/${selectedBotProfile}/assign-voice`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider: provider,
          voice_id: selectedVoice,
          voice_name: voiceName
        })
      });
      const data = await res.json();
      if (res.ok && data.ok) {
        const bot = botProfiles.find(b => b.id === selectedBotProfile);
        const botTitle = bot ? bot.title : selectedBotProfile;
        notifyHost('success', 'Voice Assigned to Bot', `Assigned "${voiceName}" to Bot "${botTitle}"!`);
        setStatusMessage(`✓ Assigned "${voiceName}" to "${botTitle}"!`);
        const pRes = await fetch(`${API_BASE}/profiles`);
        if (pRes.ok) setBotProfiles(await pRes.json());
      } else {
        setStatusMessage(`Assignment failed: ${data.detail || 'Error'}`);
      }
    } catch (e) {
      setStatusMessage(`Assignment error: ${e.message}`);
    } finally {
      setIsAssigning(false);
    }
  };

  if (!open) return null;

  const liveCopy = formatStudioLiveStatus(liveStatus);
  const selectedVoiceRecord = voices.find((v) => v.id === selectedVoice) || null;
  const selectedPack = studioPacks.find((p) => p.id === editingPackId) || null;

  return jsx(Dialog, {
    open: open,
    onOpenChange: onOpenChange,
    children: jsxs(DialogContent, {
      className: 'max-w-2xl bg-background border border-border p-6 rounded-lg shadow-xl text-foreground',
      children: [
        jsxs(DialogHeader, {
          children: [
            jsx(DialogTitle, { className: 'text-lg font-bold flex items-center gap-2', children: '🎙️ Hermes Voice & Persona Studio' }),
            jsx('p', { className: 'text-xs text-muted-foreground', children: 'Speaking personas, voice cloning, and live session apply for Hermes Desktop.' })
          ]
        }),

        jsxs('div', {
          className: 'flex border-b border-border/80 my-2 gap-1 bg-muted/20 p-1 rounded-lg',
          children: [
            jsx('button', {
              type: 'button',
              onClick: () => setActiveTab('apply'),
              className: `flex-1 py-1.5 px-3 text-xs font-semibold rounded transition-colors flex items-center justify-center gap-1.5 ${
                activeTab === 'apply'
                  ? 'bg-background text-primary shadow-sm border border-border/50'
                  : 'text-muted-foreground hover:text-foreground hover:bg-muted/30'
              }`,
              children: [
                jsx('span', { children: '🎯' }),
                jsx('span', { children: 'Apply & Persona Selection' })
              ]
            }),
            jsx('button', {
              type: 'button',
              onClick: () => setActiveTab('builder'),
              className: `flex-1 py-1.5 px-3 text-xs font-semibold rounded transition-colors flex items-center justify-center gap-1.5 ${
                activeTab === 'builder'
                  ? 'bg-background text-primary shadow-sm border border-border/50'
                  : 'text-muted-foreground hover:text-foreground hover:bg-muted/30'
              }`,
              children: [
                jsx('span', { children: '🛠️' }),
                jsx('span', { children: 'Voice Builder & Creation' })
              ]
            })
          ]
        }),

        jsxs('div', {
          className: 'space-y-3 my-2 max-h-[68vh] overflow-y-auto pr-2',
          children: activeTab === 'apply'
            ? [
              // ── Tab 1: Apply & Persona Selection ──
              jsxs('div', {
                className: 'p-3 border border-primary/40 rounded-lg space-y-2 bg-primary/5',
                children: [
                  jsx('div', { className: 'text-xs font-bold text-foreground', children: 'Target profile' }),
                  jsx('p', { className: 'text-[10px] text-muted-foreground', children: 'Apply writes to this focused Hermes profile’s current chat only. Switching bots changes the target.' }),
                  jsxs('div', {
                    className: 'flex items-baseline justify-between gap-2',
                    children: [
                      jsx('label', { className: 'text-xs font-medium', children: 'Focused Hermes profile' }),
                      jsx('span', { className: 'text-sm font-semibold text-foreground', children: targetProfile || 'default' })
                    ]
                  })
                ]
              }),

              jsxs('div', {
                className: 'p-3 border border-border/70 rounded-lg space-y-3 bg-muted/10',
                children: [
                  jsx('div', { className: 'text-xs font-bold text-foreground', children: 'Choose persona' }),
                  jsx('p', { className: 'text-[10px] text-muted-foreground', children: 'Select an existing persona pack to apply. Labels show Fish (cloud) vs Voicebox (local GPU).' }),
                  jsxs('div', {
                    className: 'space-y-1',
                    children: [
                      jsx('label', { className: 'text-xs font-medium', children: 'Persona pack' }),
                      jsx('select', {
                        value: editingPackId || '__new__',
                        onChange: (e) => {
                          const id = e.target.value;
                          if (!id || id === '__new__') applyPackToForm(null);
                          else applyPackToForm(studioPacks.find((p) => p.id === id) || null);
                        },
                        className: 'w-full h-9 rounded-md border border-input bg-background px-3 py-1 text-xs shadow-sm font-medium focus:outline-none focus:ring-1 focus:ring-ring',
                        children: [
                          jsx('option', { value: '__new__', children: '✨ New persona pack (create in Builder)' }),
                          ...(studioPacks || []).map((p) =>
                            jsx('option', {
                              key: p.id,
                              value: p.id,
                              children: `${p.avatar || '🎭'} ${p.name} · ${providerLabel(p.provider)} · ${characterStrengthPercent(p.character_strength)}%`
                            })
                          )
                        ]
                      })
                    ]
                  }),
                  jsxs('div', {
                    className: 'flex items-center justify-between pt-1 text-xs',
                    children: [
                      selectedPack
                        ? jsxs('div', {
                          className: 'flex items-center gap-1.5 text-muted-foreground text-[11px]',
                          children: [
                            jsx('span', { className: 'text-base', children: selectedPack.avatar || '🎭' }),
                            jsx('span', { className: 'font-semibold text-foreground', children: selectedPack.name }),
                            jsx('span', { children: `· ${providerLabel(selectedPack.provider)} (${selectedPack.voice_name || 'Bound Voice'})` })
                          ]
                        })
                        : jsx('span', { className: 'text-[11px] text-muted-foreground', children: 'No saved pack selected (select one or create in Builder)' }),
                      jsx(Button, {
                        size: 'sm',
                        variant: 'outline',
                        onClick: () => setActiveTab('builder'),
                        className: 'text-xs h-7 gap-1',
                        children: [
                          jsx('span', { children: '🛠️' }),
                          jsx('span', { children: 'Edit in Builder →' })
                        ]
                      })
                    ]
                  })
                ]
              }),

              jsxs('div', {
                className: 'p-3 border border-primary/30 rounded-lg space-y-2 bg-primary/5',
                children: [
                  jsx('div', { className: 'text-xs font-bold text-foreground', children: 'Character strength' }),
                  jsxs('label', {
                    className: 'text-xs font-medium flex justify-between',
                    children: [
                      'Character strength (LLM) — 0% = profile soul only, 100% = character replaces soul for this session',
                      `${characterStrengthLabel(characterStrength)} (${characterStrength}%)`
                    ]
                  }),
                  jsx('input', {
                    type: 'range',
                    min: '0',
                    max: '100',
                    step: '1',
                    value: characterStrength,
                    onChange: (e) => setCharacterStrength(e.target.value),
                    className: 'w-full h-1 bg-border rounded-lg appearance-none cursor-pointer mt-1',
                    'aria-label': 'Character strength'
                  }),
                  jsx('p', {
                    className: 'text-[10px] text-muted-foreground',
                    children: '0% = no style overlay (soul only). Soft 1–40 / Medium 41–70 / Heavy 71–99 blend character vs SOUL. 100% = character eclipses SOUL for this session. This is not TTS Temperature.'
                  })
                ]
              }),

              jsxs('div', {
                className: 'p-3 border border-primary/50 rounded-lg space-y-2 bg-primary/10',
                children: [
                  jsx('div', { className: 'text-xs font-bold text-foreground', children: 'Apply' }),
                  jsx('p', { className: 'text-[10px] text-muted-foreground', children: 'Primary action: overlay this persona + voice on the focused profile’s current chat. Save pack and preview are secondary.' }),
                  jsx(Button, {
                    size: 'sm',
                    onClick: handleApplyToChat,
                    disabled: isApplying,
                    className: 'w-full h-10 text-sm font-semibold bg-primary text-primary-foreground',
                    children: isApplying ? 'Applying…' : 'Apply to this chat'
                  }),
                  jsxs('div', {
                    className: 'flex flex-wrap gap-2',
                    children: [
                      jsx(Button, {
                        size: 'sm',
                        variant: 'outline',
                        onClick: handleAudition,
                        disabled: isAuditioning || !selectedVoice,
                        className: 'text-xs h-8',
                        children: isAuditioning ? 'Generating preview…' : 'Preview voice'
                      }),
                      jsx(Button, {
                        size: 'sm',
                        variant: 'outline',
                        onClick: handleSavePersona,
                        className: 'text-xs h-8',
                        children: editingPackId ? 'Save pack' : 'Save as new pack'
                      }),
                      jsx(Button, {
                        size: 'sm',
                        variant: 'ghost',
                        onClick: handleResetStock,
                        className: 'text-xs h-8 text-muted-foreground',
                        children: 'Reset to stock Hermes'
                      })
                    ]
                  }),
                  (selectedPack || selectedVoiceRecord)
                    ? jsx('p', {
                      className: 'text-[10px] text-muted-foreground',
                      children: `Will apply ${name || (selectedPack && selectedPack.name) || 'this pack'} · ${providerLabel(provider)}${selectedVoiceRecord ? ` (${selectedVoiceRecord.name})` : ''} at ${characterStrength}%`
                    })
                    : null
                ]
              }),

              jsxs('div', {
                className: 'p-3 border border-border/70 rounded-lg space-y-1 bg-muted/10',
                children: [
                  jsx('div', { className: 'text-xs font-bold text-foreground', children: 'Current applied state' }),
                  jsx('p', { className: 'text-xs font-medium text-foreground', children: liveCopy.headline }),
                  jsx('p', { className: 'text-[10px] text-muted-foreground', children: liveCopy.detail }),
                  statusMessage && jsx('div', {
                    className: 'text-xs px-2.5 py-1.5 rounded bg-muted/60 text-muted-foreground border border-border/50 mt-1',
                    children: statusMessage
                  })
                ]
              }),

              jsxs('div', {
                className: 'p-3 bg-muted/10 border border-border/50 rounded space-y-3',
                children: [
                  jsxs('div', {
                    className: 'flex items-center justify-between',
                    children: [
                      jsxs('div', {
                        children: [
                          jsx('div', { className: 'text-xs font-bold text-foreground', children: '👥 Group-chat Voice & Auto-read' }),
                          jsx('p', { className: 'text-[10px] text-muted-foreground', children: 'Multi-bot group chat voice support. Each bot speaks using its configured voice identity.' })
                        ]
                      }),
                      jsx(Button, {
                        size: 'sm',
                        variant: autoReadGroup ? 'default' : 'outline',
                        onClick: toggleAutoReadGroup,
                        className: `text-xs h-7 px-2.5 font-medium ${autoReadGroup ? 'bg-primary text-primary-foreground' : ''}`,
                        title: autoReadGroup ? 'Auto-read group replies is enabled (Click to disable)' : 'Auto-read group replies is disabled (Click to enable)',
                        children: autoReadGroup ? '🔊 Auto-read: ON' : '🔈 Auto-read: OFF'
                      })
                    ]
                  }),
                  jsxs('div', {
                    className: 'flex items-center justify-between',
                    children: [
                      jsx('label', { className: 'text-xs font-medium text-foreground', children: 'Hermes bot / profile' }),
                      botProfiles.length > 0 && selectedBotProfile && jsx('span', {
                        className: 'text-[11px] text-muted-foreground',
                        children: `Current TTS: ${(botProfiles.find(b => b.id === selectedBotProfile)?.voice) || 'none'}`
                      })
                    ]
                  }),
                  jsxs('div', {
                    className: 'flex gap-2 items-center',
                    children: [
                      jsx('select', {
                        value: selectedBotProfile,
                        onChange: (e) => setSelectedBotProfile(e.target.value),
                        className: 'flex-1 h-8 rounded border border-border bg-background px-2 text-xs text-foreground',
                        children: botProfiles.length === 0
                          ? jsx('option', { value: '', children: 'No profiles detected' })
                          : botProfiles.map(b =>
                              jsx('option', {
                                key: b.id,
                                value: b.id,
                                children: `${b.title} (${b.id}) [TTS: ${b.provider || 'none'}]`
                              })
                            )
                      }),
                      jsx(Button, {
                        size: 'sm',
                        variant: 'outline',
                        onClick: handleAssignVoiceToBot,
                        disabled: isAssigning || !selectedVoice || !selectedBotProfile,
                        className: 'text-xs h-8 px-3 shrink-0',
                        children: isAssigning ? 'Assigning…' : 'Assign voice to bot'
                      })
                    ]
                  })
                ]
              })
            ]
            : [
              // ── Tab 2: Voice Builder & Creation ──
              jsxs('div', {
                className: 'p-3 border border-border/50 rounded-lg bg-card/40 space-y-3',
                children: [
                  jsxs('div', {
                    className: 'flex items-center justify-between border-b border-border/40 pb-1.5',
                    children: [
                      jsx('div', { className: 'text-xs font-bold text-foreground', children: `🎙️ Clone a new voice — ${provider === 'fish_audio' ? 'Fish Audio (cloud)' : 'Voicebox (local GPU)'}` }),
                      jsx('span', { className: 'text-[10px] text-muted-foreground', children: 'WAV, MP3, or M4A' })
                    ]
                  }),
                  jsxs('div', {
                    className: 'space-y-1',
                    children: [
                      jsx('label', { className: 'text-xs font-medium', children: 'Voice provider for cloning' }),
                      jsxs('div', {
                        className: 'flex gap-2 p-1 bg-muted/30 rounded border border-border/40',
                        children: [
                          jsx(Button, {
                            size: 'sm',
                            variant: provider === 'fish_audio' ? 'default' : 'ghost',
                            className: 'flex-1 text-xs h-8',
                            onClick: () => setProvider('fish_audio'),
                            children: 'Fish Audio (cloud)'
                          }),
                          jsx(Button, {
                            size: 'sm',
                            variant: provider === 'voicebox' ? 'default' : 'ghost',
                            className: 'flex-1 text-xs h-8',
                            onClick: () => setProvider('voicebox'),
                            children: 'Voicebox (local GPU)'
                          })
                        ]
                      })
                    ]
                  }),
                  jsxs('div', {
                    className: 'grid grid-cols-2 gap-2',
                    children: [
                      jsxs('div', {
                        className: 'space-y-1',
                        children: [
                          jsx('label', { className: 'text-[11px] font-medium text-foreground', children: 'New cloned voice name' }),
                          jsx(Input, {
                            value: cloneName,
                            onChange: (e) => setCloneName(e.target.value),
                            placeholder: 'e.g. Chuck Voice',
                            className: 'text-xs h-8'
                          })
                        ]
                      }),
                      jsxs('div', {
                        className: 'space-y-1',
                        children: [
                          jsx('label', { className: 'text-[11px] font-medium text-foreground', children: 'Target engine / model' }),
                          jsx('select', {
                            value: selectedModel,
                            onChange: (e) => setSelectedModel(e.target.value),
                            className: 'w-full h-8 rounded-md border border-input bg-background px-2 text-xs shadow-sm font-medium focus:outline-none focus:ring-1 focus:ring-ring',
                            children: models.map(m =>
                              jsx('option', { key: m.id, value: m.id, children: `${m.name}${m.recommended ? ' ★ (Recommended)' : ''}` })
                            )
                          })
                        ]
                      })
                    ]
                  }),
                  jsxs('div', {
                    className: 'space-y-1',
                    children: [
                      jsx('label', { className: 'text-[11px] font-medium text-foreground', children: 'Reference audio sample' }),
                      jsx('input', {
                        type: 'file',
                        accept: 'audio/*',
                        onChange: (e) => setCloneFile(e.target.files[0]),
                        className: 'w-full text-xs text-muted-foreground file:mr-2 file:py-1 file:px-2.5 file:rounded file:border-0 file:text-xs file:font-semibold file:bg-muted file:text-foreground hover:file:opacity-90'
                      })
                    ]
                  }),
                  jsx(Button, {
                    size: 'sm',
                    variant: 'default',
                    onClick: handleCloneUpload,
                    disabled: isCloning || !cloneFile || !cloneName,
                    className: 'text-xs h-8 w-full mt-1',
                    children: isCloning ? `Cloning on ${provider === 'fish_audio' ? 'Fish Audio' : 'Voicebox'}…` : `Upload & clone to ${provider === 'fish_audio' ? 'Fish Audio' : 'Voicebox'}`
                  })
                ]
              }),

              jsxs('div', {
                className: 'p-3 border border-border/70 rounded-lg space-y-2 bg-muted/10',
                children: [
                  jsxs('div', {
                    className: 'flex items-center justify-between',
                    children: [
                      jsx('div', { className: 'text-xs font-bold text-foreground', children: `Voice Library & Clones (${provider === 'fish_audio' ? 'Fish Audio' : 'Voicebox'})` }),
                      jsx('span', { className: 'text-[10px] text-muted-foreground font-normal', children: `${voices.filter(v => v.voice_type === 'cloned').length} clones available` })
                    ]
                  }),
                  jsxs('div', {
                    className: 'flex gap-2 items-center',
                    children: [
                      jsx('select', {
                        value: selectedVoice,
                        onChange: (e) => setSelectedVoice(e.target.value),
                        className: 'flex-1 h-9 rounded-md border border-input bg-background px-3 py-1 text-xs shadow-sm focus:outline-none focus:ring-1 focus:ring-ring font-medium',
                        children: voices.map(v =>
                          jsx('option', { key: v.id, value: v.id, children: `${v.voice_type === 'cloned' ? 'Clone' : 'Preset'} · ${v.name} · ${providerLabel(v.provider)}` })
                        )
                      }),
                      jsx(Button, {
                        size: 'sm',
                        variant: 'outline',
                        onClick: () => loadData(provider),
                        className: 'h-9 text-xs',
                        title: 'Refresh voice list from the selected provider',
                        children: 'Refresh'
                      }),
                      jsx(Button, {
                        size: 'sm',
                        variant: showManager ? 'default' : 'outline',
                        onClick: () => setShowManager(!showManager),
                        className: 'h-9 text-xs',
                        title: 'Manage, delete, or re-sample voices',
                        children: showManager ? 'Close manager' : 'Manage voices'
                      })
                    ]
                  }),
                  showManager && jsxs('div', {
                    className: 'p-3 border border-border/80 rounded-lg bg-muted/20 space-y-2.5 mt-2',
                    children: [
                      jsxs('div', {
                        className: 'flex items-center justify-between border-b border-border/40 pb-1.5',
                        children: [
                          jsx('span', { className: 'text-xs font-bold text-foreground', children: `Manage cloned voices on ${provider === 'fish_audio' ? 'Fish Audio' : 'Voicebox'}` }),
                          jsx(Input, {
                            value: filterQuery,
                            onChange: (e) => setFilterQuery(e.target.value),
                            placeholder: 'Filter by name…',
                            className: 'h-7 w-44 text-[11px]'
                          })
                        ]
                      }),
                      jsxs('div', {
                        className: 'max-h-52 overflow-y-auto space-y-1.5 pr-1',
                        children: voices.filter(v => v.voice_type === 'cloned' && (!filterQuery || v.name.toLowerCase().includes(filterQuery.toLowerCase()))).length === 0
                          ? jsx('div', { className: 'text-center py-3 text-xs text-muted-foreground', children: 'No cloned voices match filter.' })
                          : voices
                              .filter(v => v.voice_type === 'cloned' && (!filterQuery || v.name.toLowerCase().includes(filterQuery.toLowerCase())))
                              .map(v =>
                                jsxs('div', {
                                  key: v.id,
                                  className: 'flex items-center justify-between p-2 rounded bg-background border border-border/60 text-xs shadow-sm',
                                  children: [
                                    jsxs('div', {
                                      className: 'flex flex-col overflow-hidden mr-2',
                                      children: [
                                        jsx('span', { className: 'font-semibold truncate text-foreground', children: v.name }),
                                        jsx('span', { className: 'text-[10px] text-muted-foreground truncate font-mono', children: `ID: ${v.id.substring(0, 16)}...` })
                                      ]
                                    }),
                                    jsxs('div', {
                                      className: 'flex items-center gap-1.5 shrink-0',
                                      children: [
                                        jsx('label', {
                                          className: 'cursor-pointer px-2 py-1 bg-muted hover:bg-muted/80 rounded text-[11px] font-medium border border-border/60 transition-colors',
                                          title: 'Upload a newer reference sample for this voice',
                                          children: [
                                            'Re-sample',
                                            jsx('input', {
                                              type: 'file',
                                              accept: 'audio/*',
                                              className: 'hidden',
                                              onChange: (e) => {
                                                if (e.target.files && e.target.files[0]) {
                                                  handleResampleVoice(v.id, v.name, e.target.files[0]);
                                                }
                                              }
                                            })
                                          ]
                                        }),
                                        jsx(Button, {
                                          size: 'sm',
                                          variant: 'destructive',
                                          className: 'h-6 px-2 text-[11px]',
                                          onClick: () => handleDeleteVoice(v.id, v.name),
                                          disabled: isManagingVoice,
                                          title: 'Delete this cloned voice',
                                          children: 'Delete'
                                        })
                                      ]
                                    })
                                  ]
                                })
                              )
                      })
                    ]
                  })
                ]
              }),

              jsxs('div', {
                className: 'p-3 border border-border/60 rounded-lg space-y-3 bg-card/40',
                children: [
                  jsx('div', { className: 'text-xs font-bold text-foreground', children: '🎭 Persona Pack Definition' }),
                  jsxs('div', {
                    className: 'space-y-1',
                    children: [
                      jsx('label', { className: 'text-xs font-medium', children: 'Select Pack to Edit or Create New' }),
                      jsx('select', {
                        value: editingPackId || '__new__',
                        onChange: (e) => {
                          const id = e.target.value;
                          if (!id || id === '__new__') applyPackToForm(null);
                          else applyPackToForm(studioPacks.find((p) => p.id === id) || null);
                        },
                        className: 'w-full h-8 rounded-md border border-input bg-background px-3 py-1 text-xs shadow-sm font-medium focus:outline-none focus:ring-1 focus:ring-ring',
                        children: [
                          jsx('option', { value: '__new__', children: '✨ Create brand new persona pack' }),
                          ...(studioPacks || []).map((p) =>
                            jsx('option', {
                              key: p.id,
                              value: p.id,
                              children: `Edit: ${p.avatar || '🎭'} ${p.name}`
                            })
                          )
                        ]
                      })
                    ]
                  }),
                  jsxs('div', {
                    className: 'grid grid-cols-4 gap-2',
                    children: [
                      jsxs('div', {
                        className: 'col-span-1',
                        children: [
                          jsx('label', { className: 'text-xs font-medium', children: 'Avatar' }),
                          jsx(Input, {
                            value: avatar,
                            onChange: (e) => setAvatar(e.target.value),
                            className: 'text-xs h-8 text-center'
                          })
                        ]
                      }),
                      jsxs('div', {
                        className: 'col-span-3',
                        children: [
                          jsx('label', { className: 'text-xs font-medium', children: 'Persona name' }),
                          jsx(Input, {
                            value: name,
                            onChange: (e) => setName(e.target.value),
                            placeholder: editingPackId ? 'Pack name' : 'e.g. Jarvis Butler, Storyteller',
                            className: 'text-xs h-8'
                          })
                        ]
                      })
                    ]
                  }),
                  jsxs('div', {
                    className: 'space-y-1',
                    children: [
                      jsx('label', { className: 'text-xs font-medium', children: 'Speaking style / system prompt' }),
                      jsx(Textarea, {
                        value: systemPrompt,
                        onChange: (e) => setSystemPrompt(e.target.value),
                        placeholder: 'Define how this assistant speaks, vocabulary rules, mannerisms...',
                        className: 'text-xs min-h-[75px]'
                      })
                    ]
                  })
                ]
              }),

              jsxs('div', {
                className: 'p-3 border border-border/60 rounded-lg space-y-3 bg-card/40',
                children: [
                  jsx('div', { className: 'text-xs font-bold text-foreground', children: '🔊 Voice Tuning & Live Audition' }),
                  jsxs('div', {
                    className: 'space-y-1',
                    children: [
                      jsx('label', { className: 'text-xs font-medium', children: 'Synthesis engine (saved with pack)' }),
                      jsx('select', {
                        value: selectedModel,
                        onChange: (e) => setSelectedModel(e.target.value),
                        className: 'w-full h-8 rounded-md border border-input bg-background px-3 py-1 text-xs shadow-sm font-medium focus:outline-none focus:ring-1 focus:ring-ring',
                        children: models.map(m =>
                          jsx('option', { key: m.id, value: m.id, children: `${m.name}${m.recommended ? ' ★ (Recommended)' : ''}` })
                        )
                      })
                    ]
                  }),
                  jsxs('div', {
                    className: 'grid grid-cols-2 gap-4',
                    children: [
                      jsxs('div', {
                        children: [
                          jsxs('label', { className: 'text-xs font-medium flex justify-between', children: ['Speed (TTS)', `${speed}x`] }),
                          jsx('input', {
                            type: 'range',
                            min: '0.7',
                            max: '1.5',
                            step: '0.05',
                            value: speed,
                            onChange: (e) => setSpeed(e.target.value),
                            className: 'w-full h-1 bg-border rounded-lg appearance-none cursor-pointer mt-1',
                            'aria-label': 'TTS speed'
                          })
                        ]
                      }),
                      jsxs('div', {
                        children: [
                          jsxs('label', { className: 'text-xs font-medium flex justify-between', children: ['Temperature / Expressiveness (TTS only)', `${temperature}`] }),
                          jsx('input', {
                            type: 'range',
                            min: '0.1',
                            max: '1.0',
                            step: '0.05',
                            value: temperature,
                            onChange: (e) => setTemperature(e.target.value),
                            className: 'w-full h-1 bg-border rounded-lg appearance-none cursor-pointer mt-1',
                            'aria-label': 'TTS temperature'
                          })
                        ]
                      })
                    ]
                  }),
                  jsxs('div', {
                    className: 'space-y-1',
                    children: [
                      jsx('label', { className: 'text-xs font-medium', children: 'Preview text' }),
                      jsxs('div', {
                        className: 'flex gap-2 items-center',
                        children: [
                          jsx(Input, {
                            value: previewText,
                            onChange: (e) => setPreviewText(e.target.value),
                            placeholder: 'Text to speak…',
                            className: 'text-xs h-8 flex-1'
                          }),
                          jsx(Button, {
                            size: 'sm',
                            variant: 'outline',
                            onClick: handleAudition,
                            disabled: isAuditioning || !selectedVoice,
                            className: 'text-xs h-8 shrink-0',
                            children: isAuditioning ? 'Generating…' : '🔊 Preview voice'
                          })
                        ]
                      })
                    ]
                  })
                ]
              }),

              jsxs('div', {
                className: 'p-3 border border-primary/40 rounded-lg bg-primary/5 space-y-2',
                children: [
                  jsx('div', { className: 'text-xs font-bold text-foreground', children: 'Save & Proceed' }),
                  jsx('p', { className: 'text-[10px] text-muted-foreground', children: 'Save your pack changes to disk. It will be immediately available in the Apply tab and titlebar.' }),
                  jsxs('div', {
                    className: 'flex gap-2 items-center',
                    children: [
                      jsx(Button, {
                        size: 'sm',
                        variant: 'default',
                        onClick: handleSavePersona,
                        className: 'flex-1 text-xs h-9 font-semibold',
                        children: editingPackId ? '💾 Save Pack Changes' : '💾 Save as New Pack'
                      }),
                      jsx(Button, {
                        size: 'sm',
                        variant: 'outline',
                        onClick: () => setActiveTab('apply'),
                        className: 'text-xs h-9',
                        children: '🎯 Go to Apply →'
                      })
                    ]
                  }),
                  statusMessage && jsx('div', {
                    className: 'text-xs px-2.5 py-1.5 rounded bg-muted/60 text-muted-foreground border border-border/50 mt-1',
                    children: statusMessage
                  })
                ]
              })
            ]
        }),

        jsxs(DialogFooter, {
          className: 'flex justify-end gap-2',
          children: [
            jsx(Button, {
              variant: 'ghost',
              size: 'sm',
              className: 'text-muted-foreground',
              onClick: () => onOpenChange(false),
              children: 'Close'
            })
          ]
        })
      ]
    })
  });
}

// ── Export Default Hermes Plugin ──────────────────────────────────────────

export default {
  id: PLUGIN_ID,
  name: 'Hermes PersonaStudio',
  description: 'Voice & Persona Creation Studio with Fish Audio, Voicebox GPU, zero-shot cloning, live auditioning, and quick switching.',
  defaultEnabled: true,
  register(ctx) {
    ctx.register({
      id: 'personastudio-titlebar',
      area: TITLEBAR_AREAS.right,
      render: () => jsx(PersonaStudioRoot, {})
    });

    console.log('[PersonaStudio] Registered successfully into Hermes Desktop titlebar');
  }
};
