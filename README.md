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



## 🛠️ Foolproof Setup Tutorial



Follow these step-by-step instructions to get `dictate.py` installed and running on your Raspberry Pi.



### Step 1: Install System Dependencies

Open your terminal and install all required system utilities for audio, input simulation, and hardware controls:



```bash

sudo apt update && sudo apt install -y \

    python3-pip \

    python3-sounddevice \

    python3-numpy \

    python3-evdev \

    brightnessctl \

    playerctl \

    wireplumber \

    nmcli \

    upower \

    grim

```



### Step 2: Set Up Workspace & Files

Create a dedicated directory for your voice tools and place your script files inside:



```bash

mkdir -p ~/stt

cd ~/stt

```



> 📌 **Note:** Ensure both `dictate.py` and `mcdata.py` are saved in this `~/stt/` folder.



### Step 3: Install Python Packages

Install the required Python libraries. On modern Debian/Raspberry Pi OS, use `--break-system-packages` if you are not using a virtual environment:



```bash

pip install sounddevice numpy evdev tomli --break-system-packages

```



### Step 4: Generate Configuration File

Run the script for the first time to auto-generate `config.toml` with default settings and helpful inline comments:



```bash

python3 dictate.py

```

*(Press `Ctrl + C` after it creates the configuration file).*



### Step 5: Customize `config.toml`

Open `config.toml` in your preferred text editor:



```bash

nano config.toml

```



Key options to check:

- `mic`: Set to part of your USB microphone's name (e.g., `"Kraken"` or `"USB Audio"`). Set to `false` for system default.

- `button_pin`: Set to your hardware push-to-talk GPIO pin number (default: `17`). Set to `false` if not using a GPIO pin.

- `talk_key`: Keyboard key to trigger talking if no physical GPIO button is used (e.g., `"KEY_F14"`).

- `mode_key`: Key to cycle modes / long-press to switch models (default: `"KEY_F13"`).



### Step 6: Launch the Script

Start the voice assistant with your preferred Whisper model:



```bash

# Start with default settings

python3 dictate.py



# Or start directly with the tiny model

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



Create a `commands.json` file alongside `dictate.py` to add custom spoken actions:



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



Open-source under the MIT License. Built for cyberdeck builders, accessibility hacks, and hands-free Linux terminal operation.
