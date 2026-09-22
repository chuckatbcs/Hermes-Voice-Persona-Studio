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
      const res = await fetch(`${API_BASE}/voices?provider=voicebox`);
      if (res.ok) {
        const list = await res.json();
        setVoices(list.filter(v => v.voice_type === 'cloned'));
      }
    } catch (_) {}
  }, []);

  useEffect(() => {
    refreshPersonas();
    refreshVoices();
    const interval = setInterval(() => {
      refreshPersonas();
      refreshVoices();
    }, 8000);
    return () => clearInterval(interval);
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

  // No local state — receives from parent

  const onSelectPersona = async (id) => {
    console.log('[PersonaStudio] Selected:', id);
    if (id === '__open_studio__') {
      openStudio();
      return;
    }
    setActiveId(id);
    
    // Check voices first (they have priority since they're what the user created)
    let chosen = voices.find(v => v.id === id);
    if (chosen) {
      // Voice selected - assign it to the active profile
      console.log('[PersonaStudio] Voice selected:', chosen.name);
      const profile = host.state.focusedSessionProfile.get();
      if (profile) {
        try {
          const assignRes = await fetch(`${API_BASE}/profiles/${profile}/assign-voice`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              provider: chosen.provider,
              voice_id: chosen.id,
              voice_name: chosen.name
            })
          });
          if (assignRes.ok) {
            host.toast({
              title: `🎙️ Voice Assigned`,
              message: `${chosen.name} assigned to "${profile}"`
            });
          } else {
            console.warn('[PersonaStudio] Voice assignment failed');
          }
        } catch (e) {
          console.warn('[PersonaStudio] Voice assignment error:', e);
        }
      }
      return;
    }

    // Check personas (seeded/scripted personas with system prompts)
    chosen = personas.find(p => p.id === id);
    if (!chosen) return;

    // Apply persona via backend (writes to config.yaml via Hermes's built-in personality system)
    if (chosen.system_prompt) {
      try {
        const res = await fetch(`${API_BASE}/profiles/${host.state.focusedSessionProfile.get()}/set-persona`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            persona_name: chosen.name,
            persona_prompt: chosen.system_prompt
          })
        });
        if (res.ok) {
          const data = await res.json();
          console.log('[PersonaStudio] Persona set:', data);
          host.toast({
            title: `${chosen.avatar} Persona Switched`,
            message: `${data.message || 'Persona set — restart session to take effect'}`
          });
        } else {
          console.warn('[PersonaStudio] Persona set failed');
        }
      } catch (e) {
        console.warn('[PersonaStudio] Persona set error:', e);
      }
    }

    // Also assign the voice to the active profile
    if (chosen.voice_id && chosen.voice_id !== 'default') {
      try {
        const assignRes = await fetch(`${API_BASE}/profiles/${host.state.focusedSessionProfile.get()}/assign-voice`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            provider: chosen.provider,
            voice_id: chosen.voice_id,
            voice_name: chosen.voice_name
          })
        });
        if (assignRes.ok) {
          console.log('[PersonaStudio] Voice assigned:', chosen.voice_name);
        } else {
          console.warn('[PersonaStudio] Voice assignment failed');
        }
      } catch (e) {
        console.warn('[PersonaStudio] Voice assignment error:', e);
      }
    }

    host.toast({
      title: `${chosen.avatar} Persona Switched`,
      message: `Active persona set to ${chosen.name} (${chosen.provider})`
    });

    window.__ACTIVE_PERSONA_STUDIO__ = chosen;
  };

  const currentPersona = personas.find(p => p.id === activeId);
  const currentVoice = voices.find(v => v.id === activeId);
  const current = currentPersona || currentVoice;
  const triggerLabel = current ? `${current.avatar || '🎙️'} ${current.name}` : '🎭 Personas';

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
                  voices.length > 0 && jsxs('div', {
                    children: [
                      jsx('div', { className: 'text-[10px] font-bold text-muted-foreground px-2 pt-1', children: '🎙️ VOICES' }),
                      voices.map(v =>
                        jsx(SelectItem, {
                          key: v.id,
                          value: v.id,
                          className: 'text-xs py-1.5 px-2 rounded cursor-pointer hover:bg-accent focus:bg-accent',
                          children: `${v.voice_type === 'cloned' ? '👤' : '🌟'} ${v.name}`
                        })
                      )
                    ]
                  }),
                  personas.length > 0 && jsxs('div', {
                    children: [
                      jsx('div', { className: 'text-[10px] font-bold text-muted-foreground px-2 pt-1', children: '🎭 PERSONAS' }),
                      personas.map(p =>
                        jsx(SelectItem, {
                          key: p.id,
                          value: p.id,
                          className: 'text-xs py-1.5 px-2 rounded cursor-pointer hover:bg-accent focus:bg-accent',
                          children: `${p.avatar || '🎭'} ${p.name}`
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
  const [provider, setProvider] = useState('voicebox');
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
        setStatusMessage(`Successfully cloned voice '${data.voice.name}' using model ${selectedModel}!`);
        await loadData(provider);
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
            jsx('p', { className: 'text-xs text-muted-foreground', children: 'Create, clone, audition, and bind speaking personas with Fish Audio & local Voicebox GPU.' })
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
                        jsx('option', { key: v.id, value: v.id, children: `${v.voice_type === 'cloned' ? '👤 [My Clone] ' : '🌟 [Preset] '}${v.name}` })
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
                          children: 'Used in Group Chats & Direct Replies'
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
