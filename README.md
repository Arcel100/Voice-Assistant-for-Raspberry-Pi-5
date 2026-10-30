# 🎙️ dictate.py



> A lightweight, hands-free **voice dictation** and **voice command system** built for Raspberry Pi cyberdecks running Linux (Wayland / X11). Powered by *Faster-Whisper*.



---



## ✨ Key Features



- **3 Dynamic Operating Modes**

  - 📝 `Speech Mode`: Standard speech-to-text dictation. Types transcribed text directly into active windows.

  - ⛏️ `Minecraft Mode`: Optimized for Minecraft. Converts speech into chat messages or server commands using custom vocabulary mappings.

  - ⚡ `Command Mode`: System automation for app launching, window management, media control, mouse movement, search queries, and custom shell scripts.

- **🔄 Model Switching**: Hot-swap Whisper models (e.g., `base.en` $\leftrightarrow$ `tiny.en`) via a long key press or voice prompt.

- **🔘 Push-to-Talk & Hardware Controls**: Trigger recording via assigned keyboard key or a physical GPIO button.

- **🛠️ Custom Commands**: Map custom voice phrases to shell scripts via `commands.json`.

- **🧠 On-the-Fly Vocabulary**: Dynamic word learning ("*learn the word...*") saved automatically to `words.json`.

- **📊 System Queries**: Check CPU usage, battery level, temperature, IP address, or tweak brightness hands-free.



---



## 📁 File Structure



| File | Description |

| :--- | :--- |

| `dictate.py` | Main application script handling audio capture, Whisper model inference, and input injection via `evdev`/`uinput`. |

| `config.toml` | Auto-generated settings file for hotkeys, GPIO pins, threads, model choices, and timing. |

| `mcdata.py` | Minecraft-specific vocabulary, entity names, and item prompts. |

| `commands.json` | *(Optional)* Custom JSON file mapping spoken phrases to terminal commands. |

| `words.json` | Auto-created dictionary for custom vocabulary added at runtime. |



---



## 🛠️ Requirements & Setup



### Hardware

- **Single Board Computer**: Raspberry Pi 4, Pi 5, or similar Linux device.

- **Audio Input**: USB Microphone or soundcard input.

- **Hardware Button** *(Optional)*: Momentary push button wired to a GPIO pin (Default: `GPIO 17`).



### System Dependencies

- **OS**: Linux (Raspberry Pi OS / Debian Bookworm)

- **Python**: 3.11+ (includes native `tomllib`)

- **Required Packages**:

  ```bash

  pip install evdev sounddevice numpy

  ```

- **Recommended System Utilities**:

  - `brightnessctl` *(screen brightness)*

  - `playerctl` & `wpctl` *(audio & media control)*

  - `nmcli` *(Wi-Fi management)*

  - `upower` *(battery status)*

  - `grim` *(screenshots on Wayland)*



---



## 🚀 Quick Start



1. **Place Script Files**: Ensure `dictate.py` and `mcdata.py` are in the same folder (e.g., `~/stt/`).

2. **Generate Config**: Run the script once to generate `config.toml`:

   ```bash

   python3 dictate.py

   ```

3. **Launch with Specific Model**:

   ```bash

   python3 dictate.py tiny.en

   ```



---



## 🎮 Controls & Shortcuts



| Action | Control Method |

| :--- | :--- |

| **Cycle Modes** (`speech` $\rightarrow$ `minecraft` $\rightarrow$ `command`) | Tap `mode_key` (Default: `KEY_F13`) |

| **Switch Models** (`base.en` $\leftrightarrow$ `tiny.en`) | Long-press `mode_key` |

| **Push-to-Talk** | Hold GPIO Button or `talk_key` (Default: `KEY_F14`) |

| **Cancel Job / Stopwatch** | Rapidly press Talk Button **5x** |



---



## 💬 Command Mode Examples



### 🖥️ Window & System Management

- *"Open Firefox"* / *"Open terminal"*

- *"Close window"* / *"Switch window"* / *"New tab"*

- *"Volume up"* / *"Mute"*

- *"Brightness up"* / *"Brightness down"*



### 🖱️ Mouse Control

- *"Click"* / *"Right click"* / *"Double click"*

- *"Move mouse left"* / *"Nudge mouse up"* / *"Scroll down"*



### 🔍 System Info & Web Search

- *"Battery level"* / *"CPU temperature"* / *"IP address"*

- *"Search YouTube for mechanical keyboards"*

- *"Search Wikipedia for Raspberry Pi"*



---



## ⚙️ Custom Voice Commands (`commands.json`)



Create a `commands.json` file alongside `dictate.py` to add custom triggers:



```json

{

  "open my project": "code ~/projects/my-deck",

  "update system": "sudo apt update && sudo apt upgrade -y",

  "launch retroarch": {

    "run": "retroarch",

    "dangerous": false

  }

}

```



---



## 📄 License



Open-source under the MIT License. Designed for cyberdeck builders, accessibility hacks, and hands-free Linux terminal operation.
