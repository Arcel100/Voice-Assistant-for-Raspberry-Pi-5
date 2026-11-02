<div align="center">

# Cyberdeck Voice Control

**Talk to your Raspberry Pi 5. Dictate text, run voice commands, and fire off Minecraft commands, all offline.**

![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)
![Raspberry Pi 5](https://img.shields.io/badge/Raspberry%20Pi-5-C51A4A?logo=raspberrypi&logoColor=white)
![Whisper](https://img.shields.io/badge/speech--to--text-faster--whisper-4B8BBE)
![Wayland](https://img.shields.io/badge/display-Wayland-FFBC00)
![Status](https://img.shields.io/badge/status-hobby%20project-lightgrey)

<!-- Add a screenshot or GIF of it in action, then uncomment:
<img src="docs/demo.gif" alt="Demo" width="600">
-->

</div>

`dictate.py` is a single-file voice assistant built for a hand-made Raspberry Pi 5 cyberdeck. Hold a button, say something, let go, and it types it, runs it, or sends it to Minecraft chat. Speech recognition runs **locally** on the Pi with [faster-whisper](https://github.com/SYSTRAN/faster-whisper), so nothing you say leaves the device.

---

## Table of contents

- [Features](#features)
- [How it works](#how-it-works)
- [What you need](#what-you-need)
- [Installation tutorial](#installation-tutorial)
- [Using it](#using-it)
- [Voice command cheat sheet](#voice-command-cheat-sheet)
- [Minecraft mode](#minecraft-mode)
- [Your own commands and words](#your-own-commands-and-words)
- [Configuration reference](#configuration-reference)
- [Troubleshooting](#troubleshooting)
- [Project layout](#project-layout)
- [Safety and privacy](#safety-and-privacy)
- [Credits](#credits)

---

## Features

- **Three modes**, cycled with one key: **Speech** (types what you say), **Minecraft** (chat and slash commands), **Command** (control the Pi by voice).
- **Offline speech-to-text** with the `base.en` or `tiny.en` Whisper model. Only one model is loaded at a time to save RAM, and you can swap models with a long press.
- **Push-to-talk** with a physical GPIO button (or an optional keyboard key).
- **On-screen indicator** showing recording, working, and what it did. Popups grow to fit long messages.
- **Open and close apps by voice**, several at once: *"open firefox and terminal"*, *"close firefox and terminal"*.
- **Web search, websites, timers, a stopwatch, voice notes**, volume, brightness, Wi-Fi, Bluetooth, screenshots, mouse and keyboard control.
- **Minecraft helpers**: say *"slash give me a stack of diamonds"* and it types `/give @s diamond 64`.
- **Chaining**: *"open browser and search northern lights then close tab"*.
- **Safety**: shutting down or restarting asks you to confirm; the script checks how sure it is of what it heard.
- **Teach it words** it keeps mishearing, and **add your own voice commands** in a JSON file.
- **Everything configurable** in a commented `config.toml` that is created for you on first run.

---

## How it works


The script reads your mode key through [`keyd`](https://github.com/rvaiya/keyd), listens to the mic while the button is held, transcribes it, and then either types characters through a virtual keyboard (`/dev/uinput`) or runs the matching command.

---

## What you need

### Hardware

| Part | Notes |
|---|---|
| Raspberry Pi 5 | Built and used on the 4 GB model |
| USB microphone or headset | Any mic works fine (I use this https://amzn.to/4iqYrIz). The Pi 5 has no mic input of its own though |
| Push button *(optional)* | Wired between **GPIO17** and **GND** (Physical pin 11 and 9 https://bit.ly/4jOluzz). Or you can use a keyboard key instead |
| Keyboard | Needed for the mode key |
| Display | The on-screen overlay needs a desktop session |

### Software

- Raspberry Pi OS **64-bit with desktop** (current releases use Wayland)
- **Python 3.11 or newer** (older versions need `pip install tomli`)
- `keyd`, for the mode key
- A Minecraft vocabulary file, `mcdata.py`, next to the script (included in this repo)

---

## Installation tutorial

> [!NOTE]
> These steps assume you put everything in `~/stt/`. You can use another folder, but keep the files together.

### 1. Get the files

```bash
cd ~
git clone https://github.com/Arcel100/Voice-Assistant-for-Raspberry-Pi-5.git stt
cd stt
```

### 2. Install system packages

```bash
sudo apt update
sudo apt install -y python3-venv python3-gi python3-gi-cairo gir1.2-gtk-3.0 \
  python3-evdev python3-numpy python3-sounddevice python3-gpiozero python3-lgpio \
  libportaudio2 brightnessctl playerctl grim upower lxterminal
```

What the extras are for:

| Package | Used for |
|---|---|
| `python3-gi`, `python3-gi-cairo`, `gir1.2-gtk-3.0` | The on-screen overlay |
| `python3-evdev` | Reading the mode key and typing through a virtual keyboard |
| `python3-sounddevice`, `libportaudio2` | Microphone input |
| `python3-gpiozero`, `python3-lgpio` | The push-to-talk button on a Pi 5 |
| `brightnessctl` | "brightness up", "set brightness to 70" |
| `playerctl` | "play pause", "next track" |
| `grim` | "take screenshot" on Wayland |
| `upower` | "battery level" |
| `lxterminal` | Apps that need a terminal window (`terminal_cmd`) |

Volume uses `wpctl` (PipeWire) and Wi-Fi and Bluetooth use `nmcli` and `bluetoothctl`. All three are already on a standard Raspberry Pi OS desktop.

### 3. Create the Python environment

The overlay uses system GTK packages, so the virtual environment must be allowed to see them:

```bash
python3 -m venv --system-site-packages ~/stt/venv
source ~/stt/venv/bin/activate
pip install faster-whisper
```

### 4. Give your user access to the input devices

The script types by creating a virtual keyboard, which needs access to `/dev/uinput`:

```bash
echo uinput | sudo tee /etc/modules-load.d/uinput.conf
echo 'KERNEL=="uinput", MODE="0660", GROUP="input", OPTIONS+="static_node=uinput"' | sudo tee /etc/udev/rules.d/99-uinput.rules
sudo usermod -aG input $USER
sudo reboot
```

### 5. Set up the mode key with keyd

Install `keyd`:

```bash
sudo apt install keyd
```

<details>
<summary>If apt can't find keyd (older Raspberry Pi OS), build it from source</summary>

```bash
sudo apt install -y git build-essential
git clone https://github.com/rvaiya/keyd
cd keyd && make && sudo make install
sudo systemctl enable --now keyd
```

</details>

Then make the `` ` `` / `~` key send `F13`. Edit `/etc/keyd/default.conf`:

```ini
[ids]
*
-1234:5678

[main]
grave = f13
```

The `-1234:5678` line stops keyd from grabbing the script's own virtual keyboard, which can break typing.

```bash
sudo systemctl enable --now keyd
sudo keyd reload
```

### 6. Wire the push-to-talk button

Connect a normal momentary push button between two pins. No resistor is needed, because the script turns on the Pi's internal pull-up.

| Button side | Pi pin |
|---|---|
| One side | **GPIO17**, physical pin **11** |
| Other side | **GND**, physical pin **9** (right next to pin 11) |

> [!WARNING]
> Never wire the button to a 3.3 V or 5 V pin (physical pins 1, 2, 4, 17).

Want a different pin? Set `button_pin` in `config.toml` to the **GPIO number**, not the physical pin number.

### 7. Check your microphone

```bash
python3 -m sounddevice
```

Find your mic in the list. By default the script looks for a device whose name contains `PnP`. If yours is different, set `mic` in `config.toml` (part of the name, or its number) after the first run.

### 8. First run

```bash
~/stt/venv/bin/python ~/stt/dictate.py
```

On the first run it will:

1. Write a fully commented **`config.toml`** next to the script.
2. Download the Whisper model (this needs internet once, and can take a minute).
3. Start listening for the mode key and the button.

Starting it again replaces the old copy, so you never end up with two running.

You can also pick a model on the command line: `python3 dictate.py tiny.en`

### 9. Start it automatically on boot

Add one line to your desktop session's autostart. On current Raspberry Pi OS (labwc), edit `~/.config/labwc/autostart`:

```bash
/home/YOUR-USERNAME/stt/venv/bin/python /home/YOUR-USERNAME/stt/dictate.py &
```

---

## Using it

### The basics

| Do this | What happens |
|---|---|
| **Hold the button**, speak, **release** | Your speech is transcribed and handled by the current mode |
| **Tap the `` ` `` key** (the mode key) | Cycles **Speech → Minecraft → Command**. A popup shows the new mode |
| **Long-press the `` ` `` key** | Switches between the `base.en` (more accurate) and `tiny.en` (faster) models |
| **Press the button 5 times fast** | Cancels whatever it is doing (and stops a running stopwatch) |

You can also add a keyboard key that talks, by mapping it in keyd and setting `talk_key = "KEY_F14"` in `config.toml`.

### A five-minute walkthrough

1. **Speech mode.** Click into any text box. Hold the button and say *"hello from my cyberdeck"*. It types the text where your cursor is.
2. **Tap the mode key twice** to get to **Command** mode.
3. Hold the button and say **"open firefox and terminal"**. Both open.
4. Say **"set a timer for ten minutes"**, then later **"how much time is left"**.
5. Say **"make a note buy more batteries"**, then **"show notes"**.
6. Say **"help"** for the on-screen help, or **"help timers"** for one topic.
7. Say **"close firefox and terminal"** to tidy up.

> [!TIP]
> Speak naturally, with a short pause before you let go of the button. If it keeps mishearing a word, teach it: *"learn the word Enderman"*.

---

## Voice command cheat sheet

These all work in **Command** mode. Numbers can be spoken ("three") or digits.

<details open>
<summary><b>Apps and websites</b></summary>

| Say | Result |
|---|---|
| `open firefox` / `open terminal` / `open files` | Opens that app. Any installed app works by name |
| `open firefox and terminal` | Opens several at once (also `open a, b and c`) |
| `go to youtube.com` / `open reddit` | Opens a website |
| `close firefox` / `quit terminal` | Closes that specific app (a normal close request) |
| `close firefox and terminal` | Closes several apps |
| `force quit firefox` / `kill firefox` | Stops it immediately, with no chance to save |
| `close minecraft` | Closes the **game**, not the launcher (`close minecraft launcher` closes the launcher) |
| `reload apps` | Re-scan installed apps after installing something (also `reload commands`, `reload words`, `reload everything`) |

If an app ignores a normal close, a popup says so after a few seconds and suggests *"force quit"*.

</details>

<details>
<summary><b>Search</b></summary>

| Say | Result |
|---|---|
| `search <anything>` | Web search |
| `search youtube for <thing>` / `search wikipedia for <thing>` | Searches that site |
| *"who created the rubik's cube"* | A spoken question becomes a web search (`auto_search_questions`) |
| `open browser and search <thing>` | Chained |

</details>

<details>
<summary><b>Browser and windows</b></summary>

`new tab` · `close tab` · `next tab` · `previous tab` · `reopen tab` · `reload page` · `go back` · `go forward` · `zoom in` · `zoom out` · `full screen` · `close window` · `switch window` · `close two tabs`

</details>

<details>
<summary><b>Mouse and keyboard</b></summary>

| Say | Result |
|---|---|
| `click`, `right click`, `double click`, `click three times` | Clicks |
| `move mouse left`, `nudge mouse left` | Big move / small move |
| `mouse top left` (the corners) | Jumps the pointer to a corner |
| `scroll up`, `scroll down` | Scrolls |
| `hold click` ... `release click` | Drag |
| `press control c`, `press alt f4`, `press enter 3 times` | Key presses |
| `type hello world` | Types text |
| `copy`, `paste`, `cut`, `undo`, `redo`, `select all`, `save` | Editing |

</details>

<details>
<summary><b>Sound, screen, and the Pi itself</b></summary>

| Say | Result |
|---|---|
| `volume up`, `volume down`, `mute`, `set volume to 40 percent` | Volume (PipeWire) |
| `play pause`, `next track`, `previous track` | Media keys |
| `brightness up`, `brightness down`, `set brightness to 70` | Screen brightness |
| `take screenshot` | Saves to `~/Pictures/` |
| `wifi on` / `wifi off`, `bluetooth on` / `off`, `airplane mode on` | Radios |
| `cpu temperature`, `cpu usage`, `memory usage`, `disk space` | Shown as a popup |
| `battery level`, `uptime`, `wifi name`, `what time is it` | Shown as a popup |
| `shut down`, `restart` | Asks you to confirm first (say **yes**) |

</details>

<details>
<summary><b>Timers and stopwatch</b></summary>

`set a timer for 10 minutes` · `how much time is left` · `cancel timer`

`start stopwatch` · `lap` · `stop stopwatch` · `resume stopwatch` · `reset stopwatch` · `show times` · `clear times`

</details>

<details>
<summary><b>Notes</b></summary>

| Say | Result |
|---|---|
| `make a note buy more batteries` | Saves it (also `jot this down ...`, `note: ...`) |
| `make a note` | Then say the note in your next sentence |
| `show notes` | Lists newest first, with paging |
| `older notes` / `newer notes` | Page through |
| `close notes` | Hides the list |

Notes are saved one per line, with a timestamp, in `notes.txt`.

</details>

<details>
<summary><b>Chaining and repeating</b></summary>

`open browser and search northern lights` · `close tab then new tab` · `close two tabs` · `do that again`

</details>

---

## Minecraft mode

Switch to **Minecraft** mode (tap the mode key) and talk.

- **Anything you say** is typed into Minecraft chat and sent (`minecraft_auto_send`), so you can talk to other players normally.
- **Start with "slash"** to run a command or a shortcut. It opens chat with `/` already typed, and fixes up item names, entities, coordinates and selectors. Item and mob names come from the vocabulary in `mcdata.py`.

| Say | Types |
|---|---|
| `slash give me sixty four diamonds` | `/give @s diamond 64` |
| `slash give me a stack of cobblestone` | `/give @s cobblestone 64` |
| `slash summon three zombies` | `/summon zombie` (three times) |
| `slash teleport me to 100 64 minus 200` | `/tp @s 100 64 -200` |
| `slash kill all creepers` | `/kill @e[type=creeper]` |
| `slash set time to 1000` | `/time set 1000` |
| `slash gamemode creative` | `/gamemode creative` |

**Shortcuts** (say "slash" first): `creative mode`, `survival mode`, `adventure mode`, `spectator mode`, `make it day`, `make it night`, `make it rain`, `clear weather`, `peaceful mode`, `hard mode`, `keep inventory on`, `heal me`, `feed me`, `night vision on`, `clear effects`, `set spawn`.

**Game keys** (say "slash" first): `open inventory`, `drop item`, `swap hands`, `debug screen`, `take screenshot`, `hide hud`, `change view`, `pause game`. Add a number to repeat, like *"slash drop item three times"*.

**Repeat:** *"slash repeat command"* resends the last chat line, and *"slash do that again"* repeats the last command.

> [!IMPORTANT]
> Commands listed in `MC_DANGEROUS` in `mcdata.py` are typed but **never sent automatically**. A popup tells you to press Enter yourself.

Brackets, braces, `@e[type=zombie]`-style selectors and `~ ~ ~` coordinates are all typed correctly. Say **"tilde"** for `~` and **"caret"** for `^`.

---

## Your own commands and words

### Custom voice commands: `commands.json`

Create `~/stt/commands.json` (it is optional). Each phrase maps to a shell command:

```json
{
  "open my notes folder": "pcmanfm ~/Documents/notes",
  "start the music": "playerctl play",
  "clean screenshots": { "run": "rm -f ~/Pictures/screenshot-*.png", "dangerous": true }
}
```

- A plain string runs as a shell command.
- Add `"dangerous": true` to make it ask for a **yes** before running.
- Your phrases override built-in ones with the same name.
- After editing the file, say **"reload commands"** (or restart the script) to pick up the changes.

### Teach it words: `words.json`

Created automatically as you teach it, so there is normally no need to edit it by hand:

| Say | Result |
|---|---|
| `learn the word Enderman` | Remembers the spelling |
| `spelled: e n d e r m a n` | For words it can't guess |
| `say capital D for a capital letter` | Capital letters |
| `forget the word <word>` | Removes it |
| `how many words` | Shows how many it knows |

---

## Configuration reference

All settings live in **`config.toml`**, next to `dictate.py`. It is created, with comments, the first time you run the script. Delete any line to go back to its default; start the script again to apply changes. Mistakes (wrong type, typo in a name, out-of-range number) are reported and fall back to the default instead of crashing.

For settings marked **off**, write `false` to turn them off.

| Setting | Default | What it does |
|---|---|---|
| `mode_key` | `"KEY_F13"` | Key that changes mode (tap) or model (long press). keyd maps the backtick key to this. |
| `talk_key` | off | Optional keyboard key that also talks, e.g. KEY_F14 (map it in keyd). false = off. |
| `long_press` | `0.6` | Seconds to hold the mode key for a long press. |
| `models` | `["base.en", "tiny.en"]` | A long press cycles through these. Only one is kept in memory at a time. |
| `start_model` | `"base.en"` | Model to start with. A model name on the command line (python3 dictate.py tiny.en) overrides this. |
| `hf_token` | off | Optional Hugging Face access token (starts with hf_). Only used when a model has to be downloaded; removes the 'unauthenticated requests' warning. Keep this file private. false = none. |
| `whisper_threads` | `3` | CPU threads for speech recognition. 3 leaves a core free so the animation and your game stay smooth. 4 is a bit faster but laggier. |
| `mic` | `"PnP"` | Part of the mic's name, or its number. The script waits for it to be plugged in. false = system default. |
| `sound_device` | off | Where timer alarms play (name or number). false = system default. |
| `button_pin` | `17` | GPIO number of the push-to-talk button. false = no button. |
| `mash_count` | `5` | Press the talk button this many times... |
| `mash_window` | `2.5` | ...within this many seconds to cancel the current task. |
| `max_record_secs` | `120` | Safety cap in case the talk button gets stuck down. |
| `show_overlay` | `true` | The on-screen dot and pills. |
| `close_wait_secs` | `8` | After you say 'close <app>', how long to wait before telling you it is still open (so you can say 'force quit <app>'). 0 = don't check. |
| `popup_max_width` | `760` | Widest a pop-up box may grow, in pixels. The box grows to fit what it says; anything longer wraps onto more lines. (Never wider than the screen.) |
| `show_stopwatch` | `true` | Keep the stopwatch time on screen while it's running. |
| `cancel_stops_stopwatch` | `true` | Pressing the talk button 5 times (cancel) also stops the stopwatch if it's running. |
| `stopwatch_stop_show_secs` | `5.0` | How long the final time stays on screen after 'stop stopwatch'. |
| `strip_trailing_period` | `true` | Remove the full stop Whisper puts at the end of a sentence. |
| `minecraft_auto_send` | `true` | Press Enter after typing in Minecraft mode. |
| `mc_chat_key` | `"KEY_ENTER"` | Key that opens chat in Minecraft. |
| `mc_command_key` | `"KEY_SLASH"` | Key that opens chat with / already typed. false = open chat, then type the /. |
| `initial_prompt` | `"Minecraft, creeper, redstone, diamond, Nether, Enderman."` | Words that help speech mode spell things right. false = none. |
| `browser_cmd` | `"firefox"` | Used for web searches and 'open <website>'. |
| `terminal_cmd` | `"lxterminal -e"` | Used for apps that need a terminal window (htop, vim ...). |
| `auto_search_questions` | `true` | In command mode, a spoken question ('who created the rubik's cube') becomes a web search. |
| `chain_delay` | `0.4` | Pause between chained commands, in seconds. |
| `chain_delay_after_open` | `3.0` | Pause after opening an app, so it can start before the next step. |
| `mouse_move_px` | `120` | How far 'move mouse left' goes (per count). |
| `mouse_nudge_px` | `30` | How far 'nudge mouse left' goes (per count). |
| `mouse_scale` | `1.0` | Tune this if the pointer travels too far or not far enough. |
| `wheel_notches` | `3` | Scroll amount per 'scroll down'. |
| `max_repeat` | `30` | Refuse things like 'click 200 times'. |
| `notes_file` | `"notes.txt"` | Text file your voice notes are saved to. A bare name lives next to dictate.py; a full path also works. |
| `notes_show_dates` | `false` | Show each note's date and time under it on the screen list. They are always saved in the file. |
| `confirm_mode` | `"always"` | Dangerous commands (shut down, restart): "unsure" = only ask yes/no when it is not sure what you said, "always" = always ask, "never" = never ask. |
| `confirm_sure_score` | `0.95` | How closely what it heard must match the command (0 to 1) to count as sure. 'shut down' is a perfect match. 'shot down' or 'shutting down' are not. |
| `confirm_min_logprob` | `-0.8` | Whisper's own confidence in what it heard (closer to 0 = more confident). Below this it counts as unsure. The log line for every command prints this number so you can tune it. |
| `confirm_commands` | `[]` | Extra phrases to treat as dangerous, e.g. ["close window"]. Shut down and restart always are. In commands.json you can also mark one: {"my command": {"run": "...", "dangerous": true}} |

---

## Troubleshooting

| Problem | Try this |
|---|---|
| **Tapping `` ` `` does nothing** | Check keyd sees the key: run `sudo keyd monitor` and press it. You should see `f13`. Re-check `/etc/keyd/default.conf`, then `sudo keyd reload` |
| **Mode key or typing breaks after setting up keyd** | Add `-1234:5678` under `[ids]` in `default.conf` so keyd ignores the script's own virtual keyboard |
| **"Permission denied" on `/dev/uinput`, or nothing gets typed** | Redo [step 4](#4-give-your-user-access-to-the-input-devices). Your user must be in the `input` group, and you need to **reboot or log out and in** after adding it |
| **It waits for the mic** | Run `python3 -m sounddevice` and set `mic` in `config.toml` to part of your mic's name. The script notices when you plug it in or unplug it |
| **The button does nothing** | Check the wiring (GPIO17 = physical pin 11, ground = pin 9). Make sure `python3-lgpio` is installed. The startup log should say `Push-to-talk button on GPIO17` |
| **No on-screen popups** | The overlay needs a desktop session. Start the script from your desktop's autostart, not over SSH. You can also set `show_overlay = false` |
| **It is slow or laggy** | Long-press the mode key to switch to `tiny.en`. Lower `whisper_threads` to leave more CPU for your game |
| **It types things you did not say** (like "Thank you.") | Whisper sometimes invents text from silence or breath. Press the button just before you speak and let go right after |
| **It keeps mishearing a word** | Say *"learn the word ..."*, or add it to `initial_prompt` in `config.toml` |
| **Minecraft text goes to the wrong place** | The game window must have focus. Check `mc_chat_key` and `mc_command_key` match your Minecraft controls |
| **A warning about unauthenticated Hugging Face requests** | Only appears when a model has to be downloaded. Set `hf_token` in `config.toml`, or ignore it |
| **`close <app>` did not close it** | Wait for the popup, then say *"force quit <app>"* |
| **A setting seems ignored** | Read the terminal output on start. Bad values are reported and replaced by the default |
| **`tomllib` missing** | You are on Python older than 3.11. Run `pip install tomli` in the venv |

To see exactly what it heard, run it in a terminal instead of autostart. Each command prints a log line with the mode, the model, how long it took, and Whisper's confidence.

---

## Project layout

```text
stt/
├── dictate.py        the whole program
├── mcdata.py         Minecraft vocabulary: commands, items, entities, speech prompt
├── config.toml       settings (created on first run)
├── commands.json     your own voice commands (optional)
├── words.json        words you taught it (created automatically)
├── notes.txt         your voice notes (created automatically)
└── venv/             Python environment
```

> [!CAUTION]
> `config.toml` can contain your Hugging Face token, and `notes.txt` is personal. Keep them out of git.
>
> ```gitignore
> config.toml
> words.json
> notes.txt
> commands.json
> venv/
> __pycache__/
> ```

---

## Safety and privacy

- **Speech recognition is local.** Audio is processed on the Pi. The internet is only used to download a model the first time, and when a command opens a website or search.
- **It only listens while you hold the button** (and for a short cap if the button sticks, `max_record_secs`).
- **Voice commands run real things.** `shut down` and `restart` always ask first (`confirm_mode`). You can mark your own commands as dangerous, or list extra built-ins in `confirm_commands`.
- **Closing an app sends it a normal quit request.** Some apps quit without asking to save, so save your work first. `force quit` and `kill` do not give the app any chance to save.
- It never closes itself, the terminal it is running in, your shell, or the desktop and compositor.

---

## Credits

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) and [OpenAI Whisper](https://github.com/openai/whisper) for speech recognition
- [keyd](https://github.com/rvaiya/keyd) for key remapping
- [python-evdev](https://github.com/gvalkov/python-evdev), [gpiozero](https://gpiozero.readthedocs.io/), [sounddevice](https://python-sounddevice.readthedocs.io/), and GTK / PyGObject

## License

Add your license here, for example MIT, and a `LICENSE` file to the repo.
