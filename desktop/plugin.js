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
    characterStrength: characterStrengthPercent(pack.character_strength)
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
    character_strength: characterStrengthPercent(fields.characterStrength)
  };
  if (isUpdate) body.id = id;
  return {
    method: isUpdate ? 'PUT' : 'POST',
    url: isUpdate ? `/personas/${encodeURIComponent(id)}` : '/personas',
    body: body
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

function resolveActiveGatewayProfile(state, routes) {
  const fromState = readStateField(state, 'activeGatewayProfile')
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

function refreshLiveSessionPersonalityPlan(personaKey, hostApi, state, fallbackProfile, route, routes) {
  const sid = resolveLiveSessionId(state);
  const profile = resolveLiveSessionProfile(state, fallbackProfile);
  const fullRoute = normalizeProfileRoute(route);
  if (!sid) {
    return { ok: false, attempted: false, skipped: 'no-session', payload: null, via: '', profile: profile, route: null };
  }
  const canProfile = !!fullRoute && hostApi && typeof hostApi.requestProfile === 'function';
  const activeGw = resolveActiveGatewayProfile(state, routes);
  const gatewaySafe = !profile || (!!activeGw && activeGw === profile);
  const canRequest = hostApi && typeof hostApi.request === 'function' && gatewaySafe;
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
        params: {
          key: 'personality',
          value: catalogPersonalityKey(personaKey),
          session_id: sid
        }
      }
    };
  }
  if (canRequest) {
    return {
      ok: true,
      attempted: true,
      skipped: '',
      via: 'request',
      profile: profile,
      route: null,
      payload: {
        method: 'config.set',
        profile: profile,
        route: null,
        params: {
          key: 'personality',
          value: catalogPersonalityKey(personaKey),
          session_id: sid
        }
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
 *    After companion apply/reset, refresh the focused live session via
 *    host.requestProfile(fullRoute, 'config.set', { key:'personality', value, session_id })
 *    where fullRoute comes from host.profileRoutes() (never a bare profile
 *    string). Fall back to host.request only when the focused profile matches
 *    the active gateway profile (or is empty). Live-applied only if result.info != null.
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
    if (!refresh.ok && options && options.notifyOnRefreshFailure) {
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

// ── Root Plugin Host Wrapper ──────────────────────────────────────────────
function PersonaStudioRoot() {
  const [studioOpen, setStudioOpen] = useState(false);
  const [personas, setPersonas] = useState([]);
  const [voices, setVoices] = useState([]);

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

  useEffect(() => {
    refreshPersonas();
    refreshVoices();
    const interval = setInterval(() => {
      refreshPersonas();
      refreshVoices();
    }, 60000);
    const onFocus = () => {
      refreshPersonas();
      refreshVoices();
    };
    window.addEventListener('focus', onFocus);
    return () => {
      clearInterval(interval);
      window.removeEventListener('focus', onFocus);
    };
  }, [refreshPersonas, refreshVoices]);

  return jsxs(React.Fragment, {
    children: [
      jsx(TitlebarPersonaPicker, { openStudio: () => setStudioOpen(true), personas, voices, refreshPersonas, refreshVoices }),
      jsx(StudioModal, { open: studioOpen, onOpenChange: setStudioOpen, refreshPersonas })
    ]
  });
}

// ── Titlebar Persona Picker Component ─────────────────────────────────────
function TitlebarPersonaPicker({ openStudio, personas, voices, refreshPersonas, refreshVoices }) {
  const [activeId, setActiveId] = useState('default');
  const [profileId, setProfileId] = useState(() => focusedProfile());
  const overlayRef = useRef(emptyOverlayState({ profileId: focusedProfile() }));
  const personasRef = useRef(personas);
  personasRef.current = personas;

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
      await resetSessionOverlay(profile, { notifyOnRefreshFailure: true });
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
          provider: voiceMatch ? voiceMatch.provider : (selection.explicit ? selection.provider : null),
          explicit: !!selection.explicit,
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

    beginApplyGate(overlayRef.current);
    let applied = false;
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
          character_strength: characterStrengthPercent(bundle.character_strength)
        })
      });
      applied = applyRes.ok;
      if (applyRes.ok) {
        let applyData = {};
        try { applyData = await applyRes.json(); } catch (_) { applyData = {}; }
        overlayRef.current.active = true;
        overlayRef.current.profileId = profile;
        overlayRef.current.sessionId = focusedSessionId();
        overlayRef.current.storedId = focusedStoredSessionId();
        const appliedStrength = characterStrengthPercent(
          applyData.character_strength != null ? applyData.character_strength : bundle.character_strength
        );
        const personaKey = appliedStrength <= 0
          ? 'none'
          : (applyData.persona || catalogPersonalityKey(bundle.name));
        const refresh = await refreshLiveSessionPersonality(personaKey);
        if (!refresh.ok) {
          notifyHost(
            'warning',
            'Live session not refreshed',
            `Applied ${personaKey} in config, but this open chat may still use the previous personality (${refresh.skipped || refresh.error || 'refresh failed'}).`
          );
        }
      } else {
        console.warn('[PersonaStudio] Session apply failed');
        clearApplyGate(overlayRef.current);
      }
    } catch (e) {
      console.warn('[PersonaStudio] Session apply error:', e);
      clearApplyGate(overlayRef.current);
    }

    const ttsLabel = providerLabel(boundProvider);
    notifyHost(
      applied ? 'success' : 'error',
      `${bundle.avatar || '🎭'} ${bundle.name} · ${ttsLabel}`,
      applied
        ? `Style + ${ttsLabel} voice on this chat — next reply picks it up. New Chat returns to stock.`
        : `Failed to apply speaking persona on "${profile}"`
    );

    window.__ACTIVE_PERSONA_STUDIO__ = applied
      ? { ...bundle, apply_provider: boundProvider, apply_voice_id: boundVoiceId, apply_reason: resolveReason, scope: 'session' }
      : null;
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
      })
    ]
  });
}

// ── Voice & Persona Studio Dialog Modal ───────────────────────────────────
function StudioModal({ open, onOpenChange, refreshPersonas }) {
  const [provider, setProvider] = useState('fish_audio');
  const [voices, setVoices] = useState([]);
  const [models, setModels] = useState([]);
  const [selectedModel, setSelectedModel] = useState('chatterbox_turbo');
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
          setSelectedModel(rec.id);
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
  const handleSavePersona = async () => {
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
      characterStrength: characterStrength
    });
    if (plan.error) {
      alert(plan.error);
      return;
    }
    try {
      const res = await fetch(`${API_BASE}${plan.url}`, {
        method: plan.method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(plan.body)
      });
      if (!res.ok) {
        alert('Failed to save persona.');
        return;
      }
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
      notifyHost(
        'success',
        plan.method === 'PUT' ? 'Persona Updated' : 'Persona Saved',
        `${saved.name || plan.body.name} — Character strength ${strength}%`
      );
    } catch (e) {
      alert(`Error saving persona: ${e.message}`);
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

  return jsx(Dialog, {
    open: open,
    onOpenChange: onOpenChange,
    children: jsxs(DialogContent, {
      className: 'max-w-2xl bg-background border border-border p-6 rounded-lg shadow-xl text-foreground',
      children: [
        jsxs(DialogHeader, {
          children: [
            jsx(DialogTitle, { className: 'text-lg font-bold flex items-center gap-2', children: '🎙️ Hermes Voice & Persona Studio' }),
            jsx('p', { className: 'text-xs text-muted-foreground', children: 'Design voices and persona bundles here. Use the titlebar dropdown to apply a speaking persona to the current chat only — new chats stay stock Hermes.' })
          ]
        }),

        jsxs('div', {
          className: 'space-y-4 my-4 max-h-[70vh] overflow-y-auto pr-2',
          children: [
            // 1. Pick / create pack
            jsxs('div', {
              className: 'p-3 border border-border/70 rounded-lg space-y-3 bg-muted/10',
              children: [
                jsx('div', { className: 'text-xs font-bold text-foreground', children: '1. Pick / create pack' }),
                jsx('p', { className: 'text-[10px] text-muted-foreground', children: 'Select an existing persona to edit (name, prompt, and Character strength hydrate from the pack). Choose New to create one.' }),
                jsx('select', {
                  value: editingPackId || '__new__',
                  onChange: (e) => {
                    const id = e.target.value;
                    if (!id || id === '__new__') applyPackToForm(null);
                    else applyPackToForm(studioPacks.find((p) => p.id === id) || null);
                  },
                  className: 'w-full h-9 rounded-md border border-input bg-background px-3 py-1 text-xs shadow-sm font-medium focus:outline-none focus:ring-1 focus:ring-ring',
                  children: [
                    jsx('option', { value: '__new__', children: '✨ New persona pack' }),
                    ...(studioPacks || []).map((p) =>
                      jsx('option', { key: p.id, value: p.id, children: `${p.avatar || '🎭'} ${p.name} (${characterStrengthPercent(p.character_strength)}%)` })
                    )
                  ]
                }),
                jsxs('div', {
                  className: 'grid grid-cols-4 gap-2',
                  children: [
                    jsxs('div', {
                      className: 'col-span-1',
                      children: [
                        jsx('label', { className: 'text-xs font-medium', children: 'Avatar:' }),
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
                        jsx('label', { className: 'text-xs font-medium', children: 'Persona name:' }),
                        jsx(Input, {
                          value: name,
                          onChange: (e) => setName(e.target.value),
                          placeholder: editingPackId ? 'Uses selected pack name if left blank' : 'e.g. Jarvis Butler, Storyteller',
                          className: 'text-xs h-8'
                        })
                      ]
                    })
                  ]
                })
              ]
            }),

            // 2. Personality (LLM)
            jsxs('div', {
              className: 'p-3 border border-primary/30 rounded-lg space-y-3 bg-primary/5',
              children: [
                jsx('div', { className: 'text-xs font-bold text-foreground', children: '2. Personality (LLM)' }),
                jsx('p', { className: 'text-[10px] text-muted-foreground', children: 'Speaking style for replies. Character strength is not TTS Temperature.' }),
                jsxs('div', {
                  children: [
                    jsx('label', { className: 'text-xs font-medium', children: 'Speaking style / prompt:' }),
                    jsx(Textarea, {
                      value: systemPrompt,
                      onChange: (e) => setSystemPrompt(e.target.value),
                      placeholder: 'Define how this assistant speaks, vocabulary rules, mannerisms...',
                      className: 'text-xs min-h-[90px]'
                    })
                  ]
                }),
                jsxs('div', {
                  children: [
                    jsxs('label', {
                      className: 'text-xs font-medium flex justify-between',
                      children: [
                        'Character strength (LLM) — 0% = profile soul only, 100% = character replaces soul for this session:',
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
                      className: 'w-full h-1 bg-border rounded-lg appearance-none cursor-pointer mt-1'
                    }),
                    jsx('p', {
                      className: 'text-[10px] text-muted-foreground mt-1',
                      children: '0% = no style overlay (soul only). Soft 1–40 / Medium 41–70 / Heavy 71–99 blend character vs SOUL. 100% = character eclipses SOUL for this session.'
                    })
                  ]
                })
              ]
            }),

            // 3. Voice (TTS)
            jsxs('div', {
              className: 'p-3 border border-border/70 rounded-lg space-y-3',
              children: [
                jsx('div', { className: 'text-xs font-bold text-foreground', children: '3. Voice (TTS)' }),
            jsxs('div', {
              className: 'flex gap-2 p-1 bg-muted/30 rounded border border-border/40',
              children: [
                jsx(Button, {
                  size: 'sm',
                  variant: provider === 'voicebox' ? 'default' : 'ghost',
                  className: 'flex-1 text-xs h-8',
                  onClick: () => setProvider('voicebox'),
                  children: '⚡ Voicebox (Local GPU - RTX PRO 2000)'
                }),
                jsx(Button, {
                  size: 'sm',
                  variant: provider === 'fish_audio' ? 'default' : 'ghost',
                  className: 'flex-1 text-xs h-8',
                  onClick: () => setProvider('fish_audio'),
                  children: '☁️ Fish Audio (Cloud API & Models)'
                })
              ]
            }),

            // Model Selection Dropdown
            jsxs('div', {
              className: 'space-y-1',
              children: [
                jsx('label', { className: 'text-xs font-semibold text-foreground flex items-center gap-1.5', children: [
                  '🧠 Synthesis & Cloning Engine Model:',
                  jsx('span', { className: 'text-[10px] text-muted-foreground font-normal', children: '(Specifies the neural architecture used for synthesis/cloning)' })
                ] }),
                jsx('select', {
                  value: selectedModel,
                  onChange: (e) => setSelectedModel(e.target.value),
                  className: 'w-full h-9 rounded-md border border-input bg-background px-3 py-1 text-xs shadow-sm font-medium focus:outline-none focus:ring-1 focus:ring-ring',
                  children: models.map(m =>
                    jsx('option', { key: m.id, value: m.id, children: `${m.name}${m.recommended ? ' ★ (Recommended)' : ''}` })
                  )
                })
              ]
            }),

            // Voice Selector Row
            jsxs('div', {
              className: 'space-y-1',
              children: [
                jsxs('label', { className: 'text-xs font-semibold text-foreground flex items-center justify-between', children: [
                  jsx('span', { children: `Select Voice / Clone (${provider === 'fish_audio' ? 'Fish Audio Cloud' : 'Local Voicebox GPU'}):` }),
                  jsx('span', { className: 'text-[10px] text-muted-foreground font-normal', children: `${voices.filter(v => v.voice_type === 'cloned').length} custom clones available` })
                ] }),
                jsxs('div', {
                  className: 'flex gap-2 items-center',
                  children: [
                    jsx('select', {
                      value: selectedVoice,
                      onChange: (e) => setSelectedVoice(e.target.value),
                      className: 'flex-1 h-9 rounded-md border border-input bg-background px-3 py-1 text-xs shadow-sm focus:outline-none focus:ring-1 focus:ring-ring font-medium',
                      children: voices.map(v =>
                        jsx('option', { key: v.id, value: v.id, children: `${v.voice_type === 'cloned' ? '👤 [My Clone] ' : '🌟 [Preset] '}${v.name} · ${providerLabel(v.provider)}` })
                      )
                    }),
                    jsx(Button, {
                      size: 'sm',
                      variant: 'outline',
                      onClick: () => loadData(provider),
                      className: 'h-9 text-xs',
                      title: 'Refresh list from provider',
                      children: '🔄'
                    }),
                    jsx(Button, {
                      size: 'sm',
                      variant: showManager ? 'default' : 'outline',
                      onClick: () => setShowManager(!showManager),
                      className: 'h-9 text-xs',
                      title: 'Manage, delete duplicates, or re-sample voices',
                      children: showManager ? '✕ Close' : '⚙️ Manage'
                    })
                  ]
                })
              ]
            }),

            // Manage Voices Panel (Shown when showManager is true)
            showManager && jsxs('div', {
              className: 'p-3 border border-border/80 rounded-lg bg-muted/20 space-y-2.5',
              children: [
                jsxs('div', {
                  className: 'flex items-center justify-between border-b border-border/40 pb-1.5',
                  children: [
                    jsx('span', { className: 'text-xs font-bold text-foreground', children: `📋 Manage Cloned Voices on ${provider === 'fish_audio' ? 'Fish Cloud' : 'Local GPU'}` }),
                    jsx(Input, {
                      value: filterQuery,
                      onChange: (e) => setFilterQuery(e.target.value),
                      placeholder: 'Filter duplicate names...',
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
                                    title: 'Upload newer/better reference sample for this voice',
                                    children: [
                                      '🎙️ Re-sample',
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
                                    title: 'Delete duplicate or unwanted voice',
                                    children: '🗑️ Delete'
                                  })
                                ]
                              })
                            ]
                          })
                        )
                })
              ]
            }),

            jsxs('div', {
              className: 'grid grid-cols-2 gap-4 p-3 bg-muted/20 border border-border/40 rounded',
              children: [
                jsxs('div', {
                  children: [
                    jsxs('label', { className: 'text-xs font-medium flex justify-between', children: ['Speed (TTS):', `${speed}x`] }),
                    jsx('input', {
                      type: 'range',
                      min: '0.7',
                      max: '1.5',
                      step: '0.05',
                      value: speed,
                      onChange: (e) => setSpeed(e.target.value),
                      className: 'w-full h-1 bg-border rounded-lg appearance-none cursor-pointer mt-1'
                    })
                  ]
                }),
                jsxs('div', {
                  children: [
                    jsxs('label', { className: 'text-xs font-medium flex justify-between', children: ['Temperature / Expressiveness (TTS only):', `${temperature}`] }),
                    jsx('input', {
                      type: 'range',
                      min: '0.1',
                      max: '1.0',
                      step: '0.05',
                      value: temperature,
                      onChange: (e) => setTemperature(e.target.value),
                      className: 'w-full h-1 bg-border rounded-lg appearance-none cursor-pointer mt-1'
                    })
                  ]
                })
              ]
            }),

            // Audition Preview Section
            jsxs('div', {
              className: 'p-3 bg-primary/5 border border-primary/20 rounded space-y-2',
              children: [
                jsx('label', { className: 'text-xs font-semibold text-primary flex items-center gap-1', children: '🎧 Live Audition / Sample Preview' }),
                jsxs('div', {
                  className: 'flex gap-2',
                  children: [
                    jsx(Input, {
                      value: previewText,
                      onChange: (e) => setPreviewText(e.target.value),
                      placeholder: 'Text to speak...',
                      className: 'text-xs h-8'
                    }),
                    jsx(Button, {
                      size: 'sm',
                      onClick: handleAudition,
                      disabled: isAuditioning,
                      className: 'text-xs h-8 px-4',
                      children: isAuditioning ? 'Generating...' : '▶ Audition'
                    })
                  ]
                })
              ]
            })
              ]
            }),

            // 4. Clone new voice
            jsxs('div', {
              className: 'p-3 border border-border/70 rounded-lg bg-card/50 space-y-3',
              children: [
                jsxs('div', {
                  className: 'flex items-center justify-between border-b border-border/40 pb-1.5',
                  children: [
                    jsx('label', { className: 'text-xs font-bold text-foreground flex items-center gap-1.5', children: [
                      '4. Clone new voice — ',
                      provider === 'fish_audio' ? '☁️ Upload to Fish Audio Cloud' : '⚡ Zero-Shot (Local GPU)',
                      jsx('span', { className: 'text-[10px] bg-primary/10 text-primary px-1.5 py-0.5 rounded font-semibold', children: provider === 'fish_audio' ? 'Fish Cloud' : 'RTX PRO 2000' })
                    ] }),
                    jsx('span', { className: 'text-[10px] text-muted-foreground', children: 'WAV, MP3, or M4A audio sample' })
                  ]
                }),
                jsxs('div', {
                  className: 'space-y-2.5',
                  children: [
                    jsxs('div', {
                      className: 'grid grid-cols-2 gap-2',
                      children: [
                        jsxs('div', {
                          className: 'space-y-1',
                          children: [
                            jsx('label', { className: 'text-[11px] font-medium text-foreground', children: 'New Cloned Voice Name:' }),
                            jsx(Input, {
                              value: cloneName,
                              onChange: (e) => setCloneName(e.target.value),
                              placeholder: 'e.g. "Chuck Voice" or "My Persona"',
                              className: 'text-xs h-8'
                            })
                          ]
                        }),
                        jsxs('div', {
                          className: 'space-y-1',
                          children: [
                            jsx('label', { className: 'text-[11px] font-medium text-foreground', children: 'Target Engine / Model:' }),
                            jsx('select', {
                              value: selectedModel,
                              onChange: (e) => setSelectedModel(e.target.value),
                              className: 'w-full h-8 rounded-md border border-input bg-background px-2 text-xs shadow-sm font-medium focus:outline-none focus:ring-1 focus:ring-ring',
                              children: models.map(m =>
                                jsx('option', { key: m.id, value: m.id, children: `${m.name}${m.recommended ? ' ★' : ''}` })
                              )
                            })
                          ]
                        })
                      ]
                    }),
                    jsxs('div', {
                      className: 'space-y-1',
                      children: [
                        jsx('label', { className: 'text-[11px] font-medium text-foreground', children: 'Reference Audio Sample File:' }),
                        jsx('input', {
                          type: 'file',
                          accept: 'audio/*',
                          onChange: (e) => setCloneFile(e.target.files[0]),
                          className: 'w-full text-xs text-muted-foreground file:mr-2 file:py-1 file:px-2.5 file:rounded file:border-0 file:text-xs file:font-semibold file:bg-primary file:text-primary-foreground hover:file:opacity-90'
                        })
                      ]
                    }),
                    jsx(Button, {
                      size: 'sm',
                      onClick: handleCloneUpload,
                      disabled: isCloning || !cloneFile || !cloneName,
                      className: 'text-xs h-8 w-full mt-1 font-semibold',
                      children: isCloning ? `Uploading & Cloning to ${provider === 'fish_audio' ? 'Fish Cloud' : 'Voicebox'}...` : `🚀 Upload & Clone Voice to ${provider === 'fish_audio' ? 'Fish Audio Cloud' : 'Local GPU'}`
                    })
                  ]
                })
              ]
            }),

            // 5. Apply / save
            jsxs('div', {
              className: 'p-3 bg-secondary/15 border border-border/70 rounded space-y-2',
              children: [
                jsx('div', { className: 'text-xs font-bold text-foreground', children: '5. Apply / save' }),
                jsx('p', { className: 'text-[10px] text-muted-foreground', children: 'Save Persona updates the selected pack (or creates a new one). Assign Voice is group-chat TTS only.' }),
                jsxs('div', {
                  className: 'flex items-center justify-between',
                  children: [
                    jsx('label', {
                      className: 'text-xs font-semibold text-foreground flex items-center gap-1.5',
                      children: [
                        '🤖 Assign Voice to Hermes Bot / Profile',
                        jsx('span', {
                          className: 'text-[10px] bg-primary/10 text-primary px-1.5 py-0.5 rounded font-medium',
                          children: 'Group chats only — not a default for new chats'
                        })
                      ]
                    }),
                    botProfiles.length > 0 && selectedBotProfile && jsx('span', {
                      className: 'text-[11px] text-muted-foreground',
                      children: `Current: ${(botProfiles.find(b => b.id === selectedBotProfile)?.voice) || 'none'}`
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
                      onClick: handleAssignVoiceToBot,
                      disabled: isAssigning || !selectedVoice || !selectedBotProfile,
                      className: 'text-xs h-8 px-4 shrink-0 font-medium',
                      children: isAssigning ? 'Applying...' : '🚀 Apply Voice to Bot'
                    })
                  ]
                })
              ]
            }),

            statusMessage && jsx('div', {
              className: 'text-xs px-2.5 py-1.5 rounded bg-muted/60 text-muted-foreground border border-border/50',
              children: statusMessage
            })
          ]
        }),

        jsxs(DialogFooter, {
          className: 'flex justify-end gap-2',
          children: [
            jsx(Button, {
              variant: 'outline',
              size: 'sm',
              onClick: () => onOpenChange(false),
              children: 'Cancel'
            }),
            jsx(Button, {
              size: 'sm',
              onClick: handleSavePersona,
              className: 'bg-primary text-primary-foreground',
              children: editingPackId ? '💾 Update Persona' : '💾 Save Persona'
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
