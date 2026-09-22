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

function fallbackSystemPrompt(name, description) {
  const label = (name || 'this persona').trim() || 'this persona';
  const desc = (description || '').trim();
  if (desc && !isGenericVoiceDescription(desc)) {
    if (desc.toLowerCase().includes('you are') || desc.length >= 40) return desc;
    return `You are ${label}. ${desc} Stay in character while remaining helpful and answering the user's questions.`;
  }
  return `You are ${label}. Stay in character while remaining helpful and answering the user's questions.`;
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

function subscribeFocusedSession(onChange) {
  try {
    const atom = host.state && host.state.focusedSessionId;
    if (atom && typeof atom.subscribe === 'function') {
      return atom.subscribe(() => onChange());
    }
  } catch (_) {}
  const timer = setInterval(onChange, 400);
  return () => clearInterval(timer);
}

async function startNewChat(profile) {
  if (typeof host.newChat !== 'function') return;
  try {
    await host.newChat(profile);
  } catch (err) {
    console.warn('[PersonaStudio] host.newChat failed:', err);
  }
}

async function resetSessionOverlay(profile) {
  try {
    const res = await fetch(`${API_BASE}/profiles/${encodeURIComponent(profile)}/session/reset`, {
      method: 'POST'
    });
    return res.ok;
  } catch (err) {
    console.warn('[PersonaStudio] session reset failed:', err);
    return false;
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
  const overlayRef = useRef({ active: false, sessionId: null, applyInProgress: false });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      let restored = false;
      try {
        const res = await fetch(`${API_BASE}/session/reset-all`, { method: 'POST' });
        if (res.ok) {
          const data = await res.json();
          restored = (data.profiles || []).some((p) => p.restored || p.leftover_personality_cleared);
        }
      } catch (err) {
        console.warn('[PersonaStudio] startup session reset-all failed:', err);
      }
      if (cancelled) return;
      overlayRef.current = { active: false, sessionId: null, applyInProgress: false };
      setActiveId('default');
      window.__ACTIVE_PERSONA_STUDIO__ = null;
      if (restored) {
        await startNewChat(focusedProfile());
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const onSessionChange = async () => {
      const overlay = overlayRef.current;
      if (overlay.applyInProgress) {
        overlay.sessionId = focusedSessionId();
        return;
      }
      if (!overlay.active) return;
      const sid = focusedSessionId();
      if (!sid || sid === overlay.sessionId) return;
      const stored = focusedStoredSessionId();
      overlay.active = false;
      overlay.sessionId = null;
      setActiveId('default');
      window.__ACTIVE_PERSONA_STUDIO__ = null;
      const profile = focusedProfile();
      const ok = await resetSessionOverlay(profile);
      if (ok && !stored) {
        await startNewChat(profile);
      }
      if (ok) {
        host.toast({
          title: '🤖 Standard Hermes',
          message: 'New chat uses stock Hermes text + voice (Studio overlay cleared)'
        });
      }
    };
    return subscribeFocusedSession(onSessionChange);
  }, []);

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
      overlayRef.current.applyInProgress = true;
      try {
        const ok = await resetSessionOverlay(profile);
        if (ok) {
          await startNewChat(profile);
          overlayRef.current = { active: false, sessionId: focusedSessionId(), applyInProgress: false };
          host.toast({
            title: '🤖 Standard Hermes',
            message: `This session uses stock Hermes on "${profile}"`
          });
        }
      } catch (e) {
        console.warn('[PersonaStudio] Failed to clear persona:', e);
      } finally {
        overlayRef.current.applyInProgress = false;
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
      try {
        const createRes = await fetch(`${API_BASE}/personas`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: voiceMatch.name,
            avatar: '🎙️',
            system_prompt: fallbackSystemPrompt(voiceMatch.name, voiceMatch.description),
            provider: voiceMatch.provider || 'voicebox',
            voice_id: voiceMatch.id,
            voice_name: voiceMatch.name,
            tags: ['synced-from-voice', 'hermes-personastudio']
          })
        });
        if (createRes.ok) {
          const created = await createRes.json();
          bundle = created.persona || created;
          refreshPersonas?.();
        } else {
          console.warn('[PersonaStudio] Failed to create persona for voice', voiceMatch.name);
        }
      } catch (e) {
        console.warn('[PersonaStudio] Persona ensure error:', e);
      }
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

    overlayRef.current.applyInProgress = true;
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
          voice_name: boundVoiceName
        })
      });
      applied = applyRes.ok;
      if (applyRes.ok) {
        await startNewChat(profile);
        overlayRef.current.active = true;
        overlayRef.current.sessionId = focusedSessionId();
      } else {
        console.warn('[PersonaStudio] Session apply failed');
      }
    } catch (e) {
      console.warn('[PersonaStudio] Session apply error:', e);
    } finally {
      setTimeout(() => { overlayRef.current.applyInProgress = false; }, 500);
    }

    const ttsLabel = providerLabel(boundProvider);
    host.toast({
      title: `${bundle.avatar || '🎭'} ${bundle.name} · ${ttsLabel}`,
      message: applied
        ? `Prompt + ${ttsLabel} voice applied to this chat. Next new chat returns to stock Hermes.`
        : `Failed to apply speaking persona on "${profile}"`
    });

    window.__ACTIVE_PERSONA_STUDIO__ = applied
      ? { ...bundle, apply_provider: boundProvider, apply_voice_id: boundVoiceId, apply_reason: resolveReason, scope: 'session' }
      : null;
  };

  const currentLookup = lookupSelection(activeId, personas, voices);
  const currentPersona = currentLookup.persona;
  const currentVoice = currentLookup.voice;
  const current = currentPersona || currentVoice;
  const currentProvider = currentPersona
    ? preferredProviderForPersona(currentPersona, voices)
    : (currentVoice && currentVoice.provider);
  const triggerLabel = current
    ? `${current.avatar || '🎙️'} ${current.name} · ${providerLabel(currentProvider)}`
    : '🎭 Personas';

  return jsxs('div', {
    style: { display: 'flex', alignItems: 'center', gap: '6px', marginRight: '8px' },
    children: [
      jsx(Select, {
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
                  personas.length > 0 && jsxs('div', {
                    children: [
                      jsx('div', { className: 'text-[10px] font-bold text-muted-foreground px-2 pt-1', children: '🎭 PERSONAS (Fish when a twin exists)' }),
                      personas.map(p =>
                        jsx(SelectItem, {
                          key: personaSelectionKey(p),
                          value: personaSelectionKey(p),
                          className: 'text-xs py-1.5 px-2 rounded cursor-pointer hover:bg-accent focus:bg-accent',
                          children: `${p.avatar || '🎭'} ${p.name} · ${providerLabel(preferredProviderForPersona(p, voices))}`
                        })
                      )
                    ]
                  }),
                  voices.length > 0 && jsxs('div', {
                    children: [
                      jsx('div', { className: 'text-[10px] font-bold text-muted-foreground px-2 pt-1', children: '🎙️ CLONES (Fish preferred; Voicebox is explicit/slow)' }),
                      voices.map(v =>
                        jsx(SelectItem, {
                          key: voiceSelectionKey(v),
                          value: voiceSelectionKey(v),
                          className: 'text-xs py-1.5 px-2 rounded cursor-pointer hover:bg-accent focus:bg-accent',
                          children: `${v.voice_type === 'cloned' ? '👤' : '🌟'} ${v.name} · ${providerLabel(v.provider)}`
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
        if (vList.length > 0) setSelectedVoice(vList[0].id);
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

  useEffect(() => {
    if (open) {
      loadData(provider);
    }
  }, [open, provider, loadData]);

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

  // Save full Persona
  const handleSavePersona = async () => {
    if (!name) {
      alert('Please enter a name for the Persona.');
      return;
    }
    const chosenV = voices.find(v => v.id === selectedVoice);
    try {
      const res = await fetch(`${API_BASE}/personas`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name,
          avatar: avatar || '🤖',
          system_prompt: systemPrompt,
          provider: provider,
          voice_id: selectedVoice,
          voice_name: chosenV ? chosenV.name : selectedVoice,
          speed: parseFloat(speed),
          temperature: parseFloat(temperature)
        })
      });
      if (res.ok) {
        host.toast({
          title: 'Persona Saved',
          message: `Created '${name}' with ${chosenV ? chosenV.name : 'voice'} successfully!`
        });
        onOpenChange(false);
        // Refresh the dropdown immediately
        refreshPersonas?.();
      } else {
        alert('Failed to save persona.');
      }
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
        host.toast({
          title: 'Voice Assigned to Bot',
          message: `Assigned "${voiceName}" to Bot "${botTitle}"!`
        });
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
            // Provider Tabs
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

            // Characteristics Sliders
            jsxs('div', {
              className: 'grid grid-cols-2 gap-4 p-3 bg-muted/20 border border-border/40 rounded',
              children: [
                jsxs('div', {
                  children: [
                    jsxs('label', { className: 'text-xs font-medium flex justify-between', children: ['Speed:', `${speed}x`] }),
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
                    jsxs('label', { className: 'text-xs font-medium flex justify-between', children: ['Temperature / Expressiveness:', `${temperature}`] }),
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
            }),

            // Assign Selected Voice to Bot / Profile Section
            jsxs('div', {
              className: 'p-3 bg-secondary/15 border border-border/70 rounded space-y-2',
              children: [
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

            // Voice Cloning / Upload Section
            jsxs('div', {
              className: 'p-3 border border-border/70 rounded-lg bg-card/50 space-y-3',
              children: [
                jsxs('div', {
                  className: 'flex items-center justify-between border-b border-border/40 pb-1.5',
                  children: [
                    jsx('label', { className: 'text-xs font-bold text-foreground flex items-center gap-1.5', children: [
                      provider === 'fish_audio' ? '☁️ Upload Custom Clone to Fish Audio Cloud' : '⚡ Zero-Shot Voice Cloning (Local GPU)',
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

            // Persona Details Section
            jsxs('div', {
              className: 'space-y-2 pt-2 border-t border-border/40',
              children: [
                jsxs('div', {
                  className: 'grid grid-cols-4 gap-2',
                  children: [
                    jsxs('div', {
                      className: 'col-span-1',
                      children: [
                        jsx('label', { className: 'text-xs font-medium', children: 'Avatar Emoji:' }),
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
                        jsx('label', { className: 'text-xs font-medium', children: 'Persona Name:' }),
                        jsx(Input, {
                          value: name,
                          onChange: (e) => setName(e.target.value),
                          placeholder: 'e.g. Jarvis Butler, Storyteller',
                          className: 'text-xs h-8'
                        })
                      ]
                    })
                  ]
                }),
                jsxs('div', {
                  children: [
                    jsx('label', { className: 'text-xs font-medium', children: 'Persona System Prompt / Speaking Style:' }),
                    jsx(Textarea, {
                      value: systemPrompt,
                      onChange: (e) => setSystemPrompt(e.target.value),
                      placeholder: 'Define how this assistant speaks, vocabulary rules, mannerisms...',
                      className: 'text-xs min-h-[90px]'
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
              children: '💾 Save Persona'
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
