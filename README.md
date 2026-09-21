# Hermes Voice Persona Studio 🎙️⚡

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)](https://fastapi.tiangolo.com)
[![Hermes Desktop](https://img.shields.io/badge/Hermes_Desktop-Plugin-purple.svg)](https://nousresearch.com)
[![GPU Accelerated](https://img.shields.io/badge/GPU-NVIDIA_CUDA-76B900.svg)](https://developer.nvidia.com/cuda-zone)

**The Commercial-Grade Voice & Persona Studio for Hermes Desktop** — a high-performance, non-destructive extension providing instant persona switching, zero-shot voice cloning, live waveform auditioning, provider voice model management, and 1-click voice assignment for **Hermes Group Chats and Multi-Bot discussions**.

Powered seamlessly by **Fish Audio Cloud** and **Local GPU Neural TTS (Voicebox)**.

---

## 🌟 Key Features

### ⚡ Dual-Engine Synthesis (Cloud & Local GPU)
* **Cloud: Fish Audio**: High-fidelity hosted neural synthesis with custom zero-shot voice cloning, automated private model discovery (`self=true`), and cloud model management.
* **Local GPU: Neural Voicebox**: Zero-cloud, 100% private, offline TTS running on local NVIDIA GPUs. Features pre-configured models including **Qwen 3 (0.6B Fast)** delivering **~0.4s instant latency**, Chatterbox Turbo, and Kokoro.

### 🎙️ Zero-Shot Voice Cloning from UI
* Drag-and-drop or upload any 10–30 second reference sample (`.wav`, `.mp3`, `.m4a`).
* Automatically extract reference audio, normalize speech, and register the cloned voice directly to your local GPU Voicebox or Fish Audio account.

### ⚙️ Provider Voice Model Management
* **Filter & Search**: Quickly search and clean up duplicate voice clones across providers.
* **Re-sample on Demand**: Refresh an existing voice profile with newer, clearer studio audio without breaking downstream bot associations.
* **1-Click Deletion**: Safely prune outdated or duplicate clones from both local storage and cloud APIs.

### 🤖 1-Click Bot & Profile Voice Assignment
* Directly assign any cloned voice to your Hermes bots (`PC Maintainence / mechanic`, `Research Agent / magellan`, `critic`, `default`) with a single click.
* **Hermes Group Chat Ready**: When participating in multi-bot group chats (like `Promax Group`), each bot automatically responds with its distinct cloned voice when addressed via `@mention` or round-robin debate.

### 🛡️ 100% Non-Destructive
* Zero edits to the upstream Hermes agent repository (`~/.hermes/hermes-agent` stays a clean git checkout).
* Portable persona bundles saved safely in `~/.hermes/personas/` with isolated manifest and prompt markdown files.
* Built-in Electron single-instance lock recovery for Linux / Pop!_OS COSMIC environments.

---

## 🏗️ Architecture

```mermaid
graph TD
    UI[Hermes Desktop UI<br/>Studio Modal & Persona Picker] -->|HTTP / 127.0.0.1:17495| Server[PersonaStudio Companion Daemon<br/>FastAPI / Python 3]
    Server --> Storage[Persona Storage<br/>~/.hermes/personas/]
    Server --> BotProfiles[Hermes Profile Adapter<br/>~/.hermes/profiles/]
    Server -->|Local HTTP / 127.0.0.1:17493| Voicebox[Local GPU Voicebox<br/>Qwen 0.6B / Chatterbox]
    Server -->|HTTPS Bearer Auth| Fish[Fish Audio Cloud API<br/>api.fish.audio/v1]
    BotProfiles --> HermesConfig[Hermes config.yaml<br/>Per-Bot TTS Configuration]
```

---

## 🚀 Quick Installation

### Prerequisites
* **Hermes Desktop** installed on Linux, macOS, or Windows.
* Python 3.10+ with `pip`.
* Optional: Local NVIDIA GPU with CUDA for local neural Voicebox generation.

### One-Command Installer
```bash
# Clone the repository
git clone https://github.com/chuckatbcs/Hermes-Voice-Persona-Studio.git
cd Hermes-Voice-Persona-Studio

# Run the automated installer
python3 install.py
```

The installer will:
1. Validate Python dependencies (`fastapi`, `uvicorn`, `requests`, `pyyaml`).
2. Verify local Voicebox models (or default to Fish Audio cloud if GPU is absent).
3. Seed factory starter personas (`Jarvis`, `Storyteller`).
4. Deploy the plugin to `~/.hermes/desktop-plugins/hermes-personastudio/`.
5. Launch the background companion service on `http://127.0.0.1:17495`.

---

## 📖 User Guide

### 1. Launching the Studio
1. Open **Hermes Desktop**.
2. In the chat header, click the **`🎙️ Studio`** or **`🎭 Personas`** button.
3. The Voice & Persona Studio dialog will open.

### 2. Auditioning Voices
1. Select your provider (**Voicebox (Local GPU)** or **Fish Audio (Cloud)**).
2. Choose a voice from the dropdown. For near-zero latency on local GPUs, select **`Qwen 3 (0.6B - ⚡ Instant ~0.4s Lag)`**.
3. Type any text in the preview box and click **`▶ Audition`**.
4. Adjust the **Speed** and **Temperature / Expressiveness** sliders to taste.

### 3. Assigning a Voice to a Bot for Group Chats
1. In the Studio dialog, locate the **`🤖 Assign Voice to Hermes Bot / Profile`** section.
2. Select the target bot from the dropdown (e.g., `PC Maintainence (mechanic)`, `Research Agent (magellan)`, `critic`, etc.).
3. Click **`🚀 Apply Voice to Bot`**.
4. That bot's profile is updated immediately. When chatting in a Group Chat, mention `@botname` and it will speak with its individual cloned voice!

### 4. Cloning a New Voice
1. Under **Zero-Shot Voice Cloning**, enter a voice name.
2. Select your base engine model.
3. Choose a reference audio sample (`.wav`, `.mp3`, `.m4a`).
4. Click **`🎙️ Clone Voice & Register`**.

### 5. Managing Duplicates & Re-sampling
1. Click **`[ ⚙️ Manage ]`** next to the voice selector.
2. Filter through your cloned models.
3. Click **`🎙️ Re-sample`** to upload a newer, higher-quality audio file to that voice ID.
4. Click **`🗑️ Delete`** to permanently remove duplicate voices.

---

## 🔌 REST API Reference

The companion service runs at `http://127.0.0.1:17495`.

| Endpoint | Method | Description |
|---|---|---|
| `/api/studio/status` | `GET` | Health check and provider availability |
| `/api/studio/voices?provider={p}` | `GET` | List available voices (custom & presets) |
| `/api/studio/models?provider={p}` | `GET` | List synthesis engines (Qwen, Chatterbox, etc.) |
| `/api/studio/audition` | `POST` | Generate real-time preview audio from text |
| `/api/studio/clone` | `POST` | Upload audio sample and train/register cloned voice |
| `/api/studio/voices/{provider}/{id}` | `DELETE` | Delete a voice model from the provider |
| `/api/studio/voices/{provider}/{id}/resample` | `POST` | Update reference audio for existing voice |
| `/api/studio/profiles` | `GET` | List all Hermes bot profiles with active voices |
| `/api/studio/profiles/{id}/assign-voice` | `POST` | 1-click assign a voice to a bot profile |
| `/api/studio/personas` | `GET` / `POST` | Manage portable persona bundles |

---

## 🧹 Uninstallation

To completely remove the plugin and restore Hermes to its default state:
```bash
python3 install.py --uninstall
```

---

## 📄 License

Distributed under the [MIT License](LICENSE).
