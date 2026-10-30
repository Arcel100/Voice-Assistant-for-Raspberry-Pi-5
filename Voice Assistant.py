#!/usr/bin/env python3
"""dictate.py - voice dictation + voice commands for a Raspberry Pi cyberdeck.

Files next to this script:
    config.toml     all the settings (created with comments on first run)
    mcdata.py       the Minecraft vocabulary (commands, items, entities, prompt)
    words.json      words you taught it ("learn the word ...")   - created automatically
    commands.json   your own voice commands, {"phrase": "shell command"}   - optional

Modes (tap the mode key to cycle): speech -> minecraft -> command
Long press the mode key to switch between the base and tiny model.
Hold the GPIO button to talk. Press it 5 times fast to cancel the current job.
"""
import difflib
import gc
import json
import math
import os
import re
import shlex
import signal
import subprocess
import sys
import textwrap
import threading
import time
import urllib.parse
import numpy as np
import sounddevice as sd
from selectors import DefaultSelector, EVENT_READ
from evdev import InputDevice, UInput, ecodes as e, list_devices

import mcdata                       # ~/stt/mcdata.py (the Minecraft vocabulary)

try:
    from gpiozero import Button
except Exception:
    Button = None

try:
    import tomllib                # Python 3.11+ (Raspberry Pi OS Bookworm has it)
except ModuleNotFoundError:
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        tomllib = None

signal.signal(signal.SIGCHLD, signal.SIG_IGN)   # don't leave zombie processes from launched apps

# ---------------- settings (config.toml) ----------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORDS_FILE = os.path.join(SCRIPT_DIR, "words.json")
COMMANDS_FILE = os.path.join(SCRIPT_DIR, "commands.json")
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.toml")

# (name, default, allowed types, help). The first run writes all of this into config.toml, with comments.
SETTINGS = [
    ("mode_key", "KEY_F13", (str,),
     "Key that changes mode (tap) or model (long press). keyd maps the ` key to this."),
    ("talk_key", None, (str,),
     "Optional keyboard key that also talks, e.g. KEY_F14 (map it in keyd). false = off."),
    ("long_press", 0.6, (int, float), "Seconds to hold the mode key for a long press."),
    ("models", ["base.en", "tiny.en"], (list,),
     "A long press cycles through these. Only one is kept in memory at a time."),
    ("start_model", "base.en", (str,),
     "Model to start with. A model name on the command line (python3 dictate.py tiny.en) overrides this."),
    ("hf_token", None, (str,),
     "Optional Hugging Face access token (starts with hf_). Only used when a model has to be downloaded; "
     "removes the 'unauthenticated requests' warning. Keep this file private. false = none."),
    ("whisper_threads", 3, (int,),
     "CPU threads for speech recognition. 3 leaves a core free so the animation and your game stay "
     "smooth. 4 is a bit faster but laggier."),
    ("mic", "Kraken", (str, int),
     "Part of the mic's name, or its number. The script waits for it to be plugged in. false = system default."),
    ("sound_device", None, (str, int),
     "Where timer alarms play (name or number). false = system default."),
    ("button_pin", 17, (int,), "GPIO number of the push-to-talk button. false = no button."),
    ("mash_count", 5, (int,), "Press the talk button this many times..."),
    ("mash_window", 2.5, (int, float), "...within this many seconds to cancel the current task."),
    ("max_record_secs", 120, (int, float), "Safety cap in case the talk button gets stuck down."),
    ("show_overlay", True, (bool,), "The on-screen dot and pills."),
    ("close_wait_secs", 8, (int, float),
     "After you say 'close <app>', how long to wait before telling you it is still open (so you can say "
     "'force quit <app>'). 0 = don't check."),
    ("popup_max_width", 760, (int,),
     "Widest a pop-up box may grow, in pixels. The box grows to fit what it says; anything longer wraps "
     "onto more lines. (Never wider than the screen.)"),
    ("show_stopwatch", True, (bool,), "Keep the stopwatch time on screen while it's running."),
    ("cancel_stops_stopwatch", True, (bool,),
     "Pressing the talk button 5 times (cancel) also stops the stopwatch if it's running."),
    ("stopwatch_stop_show_secs", 5.0, (int, float),
     "How long the final time stays on screen after 'stop stopwatch'."),
    ("strip_trailing_period", True, (bool,), "Remove the full stop Whisper puts at the end of a sentence."),
    ("minecraft_auto_send", True, (bool,), "Press Enter after typing in Minecraft mode."),
    ("mc_chat_key", "KEY_ENTER", (str,), "Key that opens chat in Minecraft."),
    ("mc_command_key", "KEY_SLASH", (str,),
     "Key that opens chat with / already typed. false = open chat, then type the /."),
    ("initial_prompt", "Minecraft, creeper, redstone, diamond, Nether, Enderman.", (str,),
     "Words that help speech mode spell things right. false = none."),
    ("browser_cmd", "firefox", (str,), "Used for web searches and 'open <website>'."),
    ("terminal_cmd", "lxterminal -e", (str,), "Used for apps that need a terminal window (htop, vim ...)."),
    ("auto_search_questions", True, (bool,),
     "In command mode, a spoken question ('who created the rubik's cube') becomes a web search."),
    ("chain_delay", 0.4, (int, float), "Pause between chained commands, in seconds."),
    ("chain_delay_after_open", 3.0, (int, float),
     "Pause after opening an app, so it can start before the next step."),
    ("mouse_move_px", 120, (int, float), "How far 'move mouse left' goes (per count)."),
    ("mouse_nudge_px", 30, (int, float), "How far 'nudge mouse left' goes (per count)."),
    ("mouse_scale", 1.0, (int, float), "Tune this if the pointer travels too far or not far enough."),
    ("wheel_notches", 3, (int,), "Scroll amount per 'scroll down'."),
    ("max_repeat", 30, (int,), "Refuse things like 'click 200 times'."),
    ("notes_file", "notes.txt", (str,),
     "Text file your voice notes are saved to. A bare name lives next to dictate.py; a full path also works."),
    ("notes_show_dates", False, (bool,),
     "Show each note's date and time under it on the screen list. They are always saved in the file."),
    ("confirm_mode", "always", (str,),
     'Dangerous commands (shut down, restart): "unsure" = only ask yes/no when it is not sure what you said, '
     '"always" = always ask, "never" = never ask.'),
    ("confirm_sure_score", 0.95, (int, float),
     "How closely what it heard must match the command (0 to 1) to count as sure. "
     "'shut down' is a perfect match. 'shot down' or 'shutting down' are not."),
    ("confirm_min_logprob", -0.8, (int, float),
     "Whisper's own confidence in what it heard (closer to 0 = more confident). Below this it counts as "
     "unsure. The log line for every command prints this number so you can tune it."),
    ("confirm_commands", [], (list,),
     'Extra phrases to treat as dangerous, e.g. ["close window"]. Shut down and restart always are. '
     'In commands.json you can also mark one: {"my command": {"run": "...", "dangerous": true}}'),
]
KEY_SETTINGS = {"mode_key", "talk_key", "mc_chat_key", "mc_command_key"}              # given as KEY_ names
NULLABLE = {"talk_key", "mic", "sound_device", "button_pin", "mc_command_key", "initial_prompt", "hf_token"}  # false = off
CHOICES = {"confirm_mode": ("unsure", "always", "never")}
MINIMUMS = {"popup_max_width": 300, "long_press": 0.1, "whisper_threads": 1, "mash_count": 2, "mash_window": 0.5, "max_repeat": 1,
            "wheel_notches": 1, "confirm_sure_score": 0.0, "max_record_secs": 5}
EXAMPLES = {"talk_key": '"KEY_F14"', "sound_device": '"HDMI"', "hf_token": '"hf_paste_your_token_here"'}                         # for settings that are off

def toml_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    return json.dumps(v)                       # strings and lists of strings are valid TOML this way

def render_default_config():
    lines = ["# Settings for dictate.py. Edit, save, then start the script again (a new start replaces the old).",
             "# Delete a line to go back to its default. Where it says 'false = ...', false turns that setting off.",
             "# Your own voice commands live in commands.json, and the words it learned in words.json.", ""]
    for name, default, _types, help_ in SETTINGS:
        lines += ["# " + ln for ln in textwrap.wrap(help_, 100)]
        lines.append(f"# {name} = {EXAMPLES.get(name, '...')}" if default is None
                     else f"{name} = {toml_value(default)}")
        lines.append("")
    return "\n".join(lines)

def _type_ok(v, types):
    if isinstance(v, bool):                    # True/False must not pass as the numbers 1/0
        return bool in types
    return isinstance(v, types)

def _check_value(key, val):
    """Returns a problem description, or None if the value is fine."""
    if val is None:
        return None
    if key in KEY_SETTINGS and not isinstance(getattr(e, val, None), int):
        return f"'{val}' is not a key name (examples: KEY_F13, KEY_ENTER, KEY_SLASH)"
    if key in ("models", "confirm_commands") and not all(isinstance(x, str) and x.strip() for x in val):
        return "must be a list of text values"
    if key == "models" and not val:
        return "needs at least one model"
    if key == "hf_token" and not val.strip().startswith("hf_"):
        return "doesn't look like a Hugging Face token (they start with hf_)"
    if key in CHOICES and val not in CHOICES[key]:
        return "must be one of: " + ", ".join(CHOICES[key])
    if key in MINIMUMS and val < MINIMUMS[key]:
        return f"must be at least {MINIMUMS[key]}"
    return None

def load_config():
    cfg = {name: default for name, default, _t, _h in SETTINGS}
    spec = {name: (default, types) for name, default, types, _h in SETTINGS}
    data, changed = {}, []
    if tomllib is None:
        print("config.toml needs Python 3.11+ (or: pip install tomli). Using the default settings.")
    else:
        try:
            with open(CONFIG_FILE, "rb") as f:
                data = tomllib.load(f)
        except FileNotFoundError:
            try:
                with open(CONFIG_FILE, "w") as f:
                    f.write(render_default_config())
                print(f"Created {CONFIG_FILE} with the default settings. Edit it to change them.")
            except OSError as err:
                print("Couldn't create config.toml:", err)
        except Exception as err:
            print("Problem reading config.toml (using the default settings):", err)
    for key, val in data.items():
        if key not in spec:
            near = difflib.get_close_matches(key, list(spec), n=1)
            print(f"config.toml: unknown setting '{key}'" + (f" - did you mean '{near[0]}'?" if near else "")
                  + " (ignored)")
            continue
        default, types = spec[key]
        if val is False and key in NULLABLE:
            val = None
        elif not _type_ok(val, types):
            print(f"config.toml: '{key}' has the wrong kind of value (using the default)")
            continue
        problem = _check_value(key, val)
        if problem:
            print(f"config.toml: '{key}' {problem} (using the default)")
            continue
        if val != default:
            changed.append(key)
        cfg[key] = val
    if cfg["hf_token"]:
        cfg["hf_token"] = cfg["hf_token"].strip()
    for key in KEY_SETTINGS:                   # "KEY_F13" -> the key code
        cfg[key] = getattr(e, cfg[key]) if cfg[key] else None
    if changed:
        print("Config:", os.path.basename(CONFIG_FILE), "- changed from the defaults:", ", ".join(changed))
    return cfg

CFG = load_config()
if CFG["hf_token"]:
    os.environ["HF_TOKEN"] = CFG["hf_token"]    # the Hugging Face library reads this (never printed or logged)
MODE_KEY = CFG["mode_key"]
TALK_KEY = CFG["talk_key"]
LONG_PRESS = CFG["long_press"]
MODELS = CFG["models"]
START_MODEL = sys.argv[1] if len(sys.argv) > 1 else CFG["start_model"]
WHISPER_THREADS = CFG["whisper_threads"]
MIC = CFG["mic"]
SOUND_DEVICE = CFG["sound_device"]
BUTTON_PIN = CFG["button_pin"]
MASH_COUNT = CFG["mash_count"]
MASH_WINDOW = CFG["mash_window"]
MAX_RECORD_SECS = CFG["max_record_secs"]
SHOW_OVERLAY = CFG["show_overlay"]
POPUP_MAX_WIDTH = CFG["popup_max_width"]
CLOSE_WAIT_SECS = CFG["close_wait_secs"]
SHOW_STOPWATCH = CFG["show_stopwatch"]
CANCEL_STOPS_STOPWATCH = CFG["cancel_stops_stopwatch"]
STOPWATCH_STOP_SHOW_SECS = CFG["stopwatch_stop_show_secs"]
STRIP_TRAILING_PERIOD = CFG["strip_trailing_period"]
MINECRAFT_AUTO_SEND = CFG["minecraft_auto_send"]
MC_CHAT_KEY = CFG["mc_chat_key"]
MC_COMMAND_KEY = CFG["mc_command_key"]
INITIAL_PROMPT = CFG["initial_prompt"]
BROWSER_CMD = CFG["browser_cmd"]
TERMINAL_CMD = CFG["terminal_cmd"]
AUTO_SEARCH_QUESTIONS = CFG["auto_search_questions"]
CHAIN_DELAY = CFG["chain_delay"]
CHAIN_DELAY_AFTER_OPEN = CFG["chain_delay_after_open"]
MOUSE_MOVE_PX = CFG["mouse_move_px"]
MOUSE_NUDGE_PX = CFG["mouse_nudge_px"]
MOUSE_SCALE = CFG["mouse_scale"]
WHEEL_NOTCHES = CFG["wheel_notches"]
MAX_REPEAT = CFG["max_repeat"]
NOTES_FILE = os.path.join(SCRIPT_DIR, os.path.expanduser(CFG["notes_file"]))
NOTES_SHOW_DATES = CFG["notes_show_dates"]
CONFIRM_MODE = CFG["confirm_mode"]
CONFIRM_SURE_SCORE = CFG["confirm_sure_score"]
CONFIRM_MIN_LOGPROB = CFG["confirm_min_logprob"]
CONFIRM_COMMANDS_RAW = CFG["confirm_commands"]
PANEL_MAX = 12                     # most lines in a list panel (the overlay window is sized for this)
# ------------------------------------------

if START_MODEL not in MODELS:      # checked early, before an old copy of the script gets stopped
    raise SystemExit(f"start_model must be one of {MODELS}")

MODE_ORDER = ["speech", "minecraft", "command"]   # short press cycles through these

BATTERY_CMD = ('bat=$(upower -e 2>/dev/null | grep -m1 -i battery); '
               '[ -n "$bat" ] && upower -i "$bat" | awk \'/percentage/ {print "battery " $2}\' '
               '|| echo "no battery found"')
CTRL, ALT, SHFT, META = e.KEY_LEFTCTRL, e.KEY_LEFTALT, e.KEY_LEFTSHIFT, e.KEY_LEFTMETA

# ---------------- built-in command-mode actions ----------------
# Apps, websites, searches, "press <keys>", "type <text>", volume/brightness levels, timers, the stopwatch
# and chaining are handled separately and don't need to be listed here.
# "run" = shell command   "keys" = key combo   "click" = mouse click   "down"/"up" = hold/release button
# "wheel" = scroll   "move" = move mouse   "corner" = mouse to corner   "info" = show command output
# "mode"/"model" = switch   "confirm" = asks "yes or no" first
ACTIONS = {
    # mouse
    "click": ("click", (e.BTN_LEFT, 1)),
    "left click": ("click", (e.BTN_LEFT, 1)),
    "right click": ("click", (e.BTN_RIGHT, 1)),
    "middle click": ("click", (e.BTN_MIDDLE, 1)),
    "double click": ("click", (e.BTN_LEFT, 2)),
    "triple click": ("click", (e.BTN_LEFT, 3)),
    "hold click": ("down", e.BTN_LEFT),
    "release click": ("up", e.BTN_LEFT),
    "move mouse left": ("move", (-MOUSE_MOVE_PX, 0)),
    "move mouse right": ("move", (MOUSE_MOVE_PX, 0)),
    "move mouse up": ("move", (0, -MOUSE_MOVE_PX)),
    "move mouse down": ("move", (0, MOUSE_MOVE_PX)),
    "nudge mouse left": ("move", (-MOUSE_NUDGE_PX, 0)),
    "nudge mouse right": ("move", (MOUSE_NUDGE_PX, 0)),
    "nudge mouse up": ("move", (0, -MOUSE_NUDGE_PX)),
    "nudge mouse down": ("move", (0, MOUSE_NUDGE_PX)),
    "mouse top left": ("corner", (-1, -1)),
    "mouse top right": ("corner", (1, -1)),
    "mouse bottom left": ("corner", (-1, 1)),
    "mouse bottom right": ("corner", (1, 1)),
    "scroll down": ("wheel", -WHEEL_NOTCHES),
    "scroll up": ("wheel", WHEEL_NOTCHES),
    # windows and browser
    "close window": ("keys", [ALT, e.KEY_F4]),
    "switch window": ("keys", [ALT, e.KEY_TAB]),
    "full screen": ("keys", [e.KEY_F11]),
    "new tab": ("keys", [CTRL, e.KEY_T]),
    "close tab": ("keys", [CTRL, e.KEY_W]),
    "next tab": ("keys", [CTRL, e.KEY_PAGEDOWN]),
    "previous tab": ("keys", [CTRL, e.KEY_PAGEUP]),
    "reopen tab": ("keys", [CTRL, SHFT, e.KEY_T]),
    "new window": ("keys", [CTRL, e.KEY_N]),
    "private window": ("keys", [CTRL, SHFT, e.KEY_P]),
    "reload page": ("keys", [CTRL, e.KEY_R]),
    "go back": ("keys", [ALT, e.KEY_LEFT]),
    "go forward": ("keys", [ALT, e.KEY_RIGHT]),
    "address bar": ("keys", [CTRL, e.KEY_L]),
    "bookmark this": ("keys", [CTRL, e.KEY_D]),
    "find": ("keys", [CTRL, e.KEY_F]),
    "zoom in": ("keys", [CTRL, e.KEY_EQUAL]),
    "zoom out": ("keys", [CTRL, e.KEY_MINUS]),
    "reset zoom": ("keys", [CTRL, e.KEY_0]),
    "page down": ("keys", [e.KEY_PAGEDOWN]),
    "page up": ("keys", [e.KEY_PAGEUP]),
    "go to top": ("keys", [e.KEY_HOME]),
    "go to bottom": ("keys", [e.KEY_END]),
    # editing
    "copy": ("keys", [CTRL, e.KEY_C]),
    "cut": ("keys", [CTRL, e.KEY_X]),
    "paste": ("keys", [CTRL, e.KEY_V]),
    "select all": ("keys", [CTRL, e.KEY_A]),
    "undo": ("keys", [CTRL, e.KEY_Z]),
    "redo": ("keys", [CTRL, SHFT, e.KEY_Z]),
    "save": ("keys", [CTRL, e.KEY_S]),
    "delete word": ("keys", [CTRL, e.KEY_BACKSPACE]),
    "backspace": ("keys", [e.KEY_BACKSPACE]),
    # sound and media
    "volume up": ("run", "wpctl set-volume -l 1.0 @DEFAULT_AUDIO_SINK@ 5%+"),
    "volume down": ("run", "wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-"),
    "max volume": ("run", "wpctl set-volume @DEFAULT_AUDIO_SINK@ 100%"),
    "half volume": ("run", "wpctl set-volume @DEFAULT_AUDIO_SINK@ 50%"),
    "mute": ("run", "wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"),
    "play pause": ("run", "playerctl play-pause"),
    "next track": ("run", "playerctl next"),
    "previous track": ("run", "playerctl previous"),
    # Pi controls
    "brightness up": ("run", "brightnessctl set 10%+"),
    "brightness down": ("run", "brightnessctl set 10%-"),
    "max brightness": ("run", "brightnessctl set 100%"),
    "half brightness": ("run", "brightnessctl set 50%"),
    "min brightness": ("run", "brightnessctl set 5%"),
    "wifi on": ("run", "nmcli radio wifi on"),
    "wifi off": ("run", "nmcli radio wifi off"),
    "bluetooth on": ("run", "bluetoothctl power on"),
    "bluetooth off": ("run", "bluetoothctl power off"),
    "airplane mode on": ("run", "nmcli radio all off; bluetoothctl power off"),
    "airplane mode off": ("run", "nmcli radio all on; bluetoothctl power on"),
    "wifi name": ("info", "nmcli -t -f ACTIVE,SSID dev wifi | awk -F: '$1==\"yes\" {print \"wifi: \" $2}'"),
    "battery level": ("info", BATTERY_CMD),
    "cpu usage": ("info", "vmstat 1 2 | tail -1 | awk '{print 100-$15 \"% cpu\"}'"),
    "memory usage": ("info", "free -h | awk '/Mem:/ {print $3 \" of \" $2 \" used\"}'"),
    "disk space": ("info", "df -h / | awk 'NR==2 {print $4 \" free\"}'"),
    "uptime": ("info", "uptime -p"),
    "fan speed": ("info", "cat /sys/devices/platform/cooling_fan/hwmon/*/fan1_input 2>/dev/null | head -1 | awk '{print $1 \" rpm\"}'"),
    "power status": ("info", "vcgencmd get_throttled"),
    "what time is it": ("info", "date '+%-I:%M %p'"),
    "what is the date": ("info", "date '+%A, %B %-d'"),
    "cpu temperature": ("info", "vcgencmd measure_temp"),
    "ip address": ("info", "hostname -I | awk '{print $1}'"),
    # misc
    "take screenshot": ("run", "grim ~/Pictures/screenshot-$(date +%s).png"),
    "speech mode": ("mode", "speech"),
    "minecraft mode": ("mode", "minecraft"),
    "tiny model": ("model", "tiny.en"),
    "base model": ("model", "base.en"),
    "shut down": ("confirm", "systemctl poweroff"),
    "restart": ("confirm", "systemctl reboot"),
}
BUILTIN_ACTIONS = dict(ACTIONS)    # kept so "reload commands" can restore anything a custom command replaced

COMMAND_PROMPT = ("open firefox, open terminal, open visual studio code, open prism launcher, click, right click, "
                  "double click, move mouse left, scroll down, close two tabs, press control c, search youtube "
                  "for, search who created, go to youtube.com, volume up, set volume to forty percent, "
                  "wifi off, brightness up, set a timer for ten minutes, start stopwatch, show times, "
                  "do that again, make a note, show my notes, learn the word, help.")

# nicknames for apps (the real app list is read from your installed apps automatically)
APP_ALIASES = {"command prompt": "terminal", "cmd": "terminal", "shell": "terminal", "console": "terminal",
               "vs code": "visual studio code", "code editor": "visual studio code",
               "files": "file manager", "file explorer": "file manager", "explorer": "file manager",
               "minecraft": "prism launcher", "minecraft launcher": "prism launcher", "prism": "prism launcher",
               "notepad": "text editor"}
BROWSER_WORDS = {"browser", "web browser", "firefox", "internet", "the internet", "web", "firefox browser"}

SITES = {   # name: (home page, search page with {q})
    "youtube": ("https://www.youtube.com", "https://www.youtube.com/results?search_query={q}"),
    "google": ("https://www.google.com", "https://www.google.com/search?q={q}"),
    "wikipedia": ("https://en.wikipedia.org", "https://en.wikipedia.org/w/index.php?search={q}"),
    "amazon": ("https://www.amazon.com", "https://www.amazon.com/s?k={q}"),
    "github": ("https://github.com", "https://github.com/search?q={q}"),
    "reddit": ("https://www.reddit.com", "https://www.reddit.com/search/?q={q}"),
    "twitch": ("https://www.twitch.tv", "https://www.twitch.tv/search?term={q}"),
    "imdb": ("https://www.imdb.com", "https://www.imdb.com/find/?q={q}"),
    "ebay": ("https://www.ebay.com", "https://www.ebay.com/sch/i.html?_nkw={q}"),
    "google maps": ("https://www.google.com/maps", "https://www.google.com/maps/search/{q}"),
    "minecraft wiki": ("https://minecraft.wiki", "https://minecraft.wiki/?search={q}"),
    "stack overflow": ("https://stackoverflow.com", "https://stackoverflow.com/search?q={q}"),
    "netflix": ("https://www.netflix.com", "https://www.netflix.com/search?q={q}"),
    "spotify": ("https://open.spotify.com", "https://open.spotify.com/search/{q}"),
    "gmail": ("https://mail.google.com", "https://mail.google.com/mail/u/0/#search/{q}"),
}

# kinds that can be repeated ("close two tabs"), and the pause between repeats
REPEATABLE = {"run", "keys", "click", "wheel", "move"}
REPEAT_DELAY = {"run": 0.3, "keys": 0.12, "click": 0.12, "wheel": 0.05, "move": 0.05}

NUMW = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
        "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
        "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
        "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
NUM_WORDS = dict(NUMW, once=1, twice=2, thrice=3)
COUNT_FILLER = {"times", "time", "pages", "steps", "notches"}
FILLERS = {"the", "a", "an", "my", "this", "that", "current", "please", "just", "now", "me", "it", "can",
           "you", "could", "would", "will", "kindly", "for", "to", "of", "some", "thanks"}

def to_number(s):
    """'forty five' / '45' / 'one hundred twenty' -> int, or None"""
    toks = s.replace("-", " ").split()
    if not toks:
        return None
    total, cur, seen = 0, 0, False
    for tk in toks:
        if tk.isdigit():
            cur += int(tk)
            seen = True
        elif tk in NUMW:
            cur += NUMW[tk]
            seen = True
        elif tk == "hundred":
            cur = max(cur, 1) * 100
            seen = True
        elif tk == "thousand":
            total += max(cur, 1) * 1000
            cur = 0
            seen = True
        elif tk == "and":
            continue
        else:
            return None
    return total + cur if seen else None

def split_count(heard):
    """'close two tabs' -> (2, 'close tabs'); 'click twice' -> (2, 'click'); no number -> (None, same)"""
    count, rest = None, []
    for w in heard.split():
        m = re.fullmatch(r"(\d+)x?", w)
        if m and count is None:
            count = int(m.group(1))
        elif m:
            continue
        elif w in NUM_WORDS and count is None:
            count = NUM_WORDS[w]
        elif (w in NUM_WORDS and count is not None and count >= 20
              and count % 10 == 0 and NUM_WORDS[w] < 10):
            count += NUM_WORDS[w]                       # "twenty five"
        else:
            rest.append(w)
    if count is not None:
        rest = [w for w in rest if w not in COUNT_FILLER]
    return count, " ".join(rest)

def clean_phrase(text):
    text = re.sub(r"[^a-z0-9 ]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()

CONFIRM_COMMANDS = {clean_phrase(p) for p in CONFIRM_COMMANDS_RAW}   # extra "dangerous" phrases from config.toml

def stem(w):
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w

# words that mean the same thing (close = exit = quit = delete ...). The first word is the one used.
SYN_GROUPS = {
    "close": "close exit quit delete remove kill terminate dismiss",
    "open": "open launch start run load",
    "new": "new fresh another blank",
    "next": "next forward",
    "previous": "previous back prior last",
    "reload": "reload refresh",
    "up": "up raise increase higher louder boost",
    "down": "down lower decrease reduce quieter softer dim",
    "mute": "mute silence unmute",
    "click": "click tap",
    "volume": "volume sound audio",
    "mouse": "mouse cursor pointer",
    "wifi": "wifi wireless wlan",
    "copy": "copy duplicate",
    "undo": "undo revert",
    "go": "go navigate jump",
    "restart": "restart reboot",
    "screenshot": "screenshot screengrab",
}
SYN_CANON = {stem(w): canon for canon, ws in SYN_GROUPS.items() for w in ws.split()}

def tok(w):
    s = stem(w)
    return SYN_CANON.get(s, s)

# ---------------- understanding different ways of saying things ----------------
PRE_RE = re.compile(r"^\W*(?:(?:hey|ok|okay|please|could you|can you|would you|will you|i want to|"
                    r"i would like to|i'd like to|i need to|let's|lets|go ahead and|just)\s+)+", re.I)
POST_RE = re.compile(r"\s+(?:please|for me|now|thanks|thank you)\W*$", re.I)
CLOSE_OBJ = r"(?:the\s+|this\s+|that\s+|current\s+|my\s+)*"
OPT_WORD = r"(?:\w+\s+)?"           # lets a spoken count sit in the middle: "close two tabs"
SYNONYMS = [
    (r"\bwi fi\b|\bwireless\b|\bwlan\b", "wifi"),
    (r"\bstop watch\b", "stopwatch"),
    (r"\b(?:launch|fire up|boot up|bring up|pull up|start up|execute)\b", "open"),
    # volume
    (r"\b(?:turn|bump|crank|bring)\s+(?:the\s+|it\s+)?(?:volume|sound|audio)\s+up\b"
     r"|\b(?:increase|raise)\s+(?:the\s+)?(?:volume|sound)\b|\b(?:volume|sound)\s+louder\b|\blouder\b", "volume up"),
    (r"\b(?:turn|bring)\s+(?:the\s+|it\s+)?(?:volume|sound|audio)\s+down\b"
     r"|\b(?:decrease|lower|reduce)\s+(?:the\s+)?(?:volume|sound)\b|\b(?:volume|sound)\s+(?:quieter|softer)\b"
     r"|\bquieter\b|\bsofter\b", "volume down"),
    (r"\bunmute\b|\bsilence\b|\bshut up\b", "mute"),
    # brightness
    (r"\b(?:turn|bring)\s+(?:the\s+)?(?:screen\s+)?brightness\s+up\b"
     r"|\b(?:increase|raise)\s+(?:the\s+)?(?:screen\s+)?brightness\b|\bbrighter\b"
     r"|\bbrighten(?:\s+the\s+screen)?\b", "brightness up"),
    (r"\b(?:turn|bring)\s+(?:the\s+)?(?:screen\s+)?brightness\s+down\b"
     r"|\b(?:decrease|lower|reduce)\s+(?:the\s+)?(?:screen\s+)?brightness\b|\bdimmer\b"
     r"|\bdim(?:\s+the\s+screen)?\b", "brightness down"),
    # wifi / bluetooth
    (r"\bturn (on|off) (?:the )?(wifi|bluetooth)\b", r"\2 \1"),
    (r"\bturn (?:the )?(wifi|bluetooth) (on|off)\b", r"\1 \2"),
    # screenshots
    (r"\bscreen ?capture\b|\bcapture (?:the )?screen\b|\bscreen ?grab\b", "screenshot"),
    (r"\b(?:take\s+(?:a\s+|the\s+)?)?screenshot\b", "take screenshot"),
    # page / window
    (r"\b(?:refresh|reload)(?:\s+(?:the|this))?(?:\s+(?:page|tab))?$", "reload page"),
    (r"\b(?:go\s+)?(?:maximize|fullscreen|full screen)\b", "full screen"),
    (r"\b(?:exit|quit|kill|terminate|dismiss|delete|remove)\s+(?=" + CLOSE_OBJ + OPT_WORD +
     r"(?:tabs?|windows?|apps?|programs?|pages?|browser|application)\b)", "close "),
    (r"^(?:exit|quit)$", "close window"),
    (r"\bclose\s+" + CLOSE_OBJ + r"(" + OPT_WORD + r")(?:apps?|programs?|application)\b", r"close \1window"),
    (r"\bclose\s+" + CLOSE_OBJ + r"(" + OPT_WORD + r")pages?\b", r"close \1tab"),
    (r"\b(?:open|make|create|add)\s+(?:a\s+|an\s+)?(?:new\s+|another\s+|blank\s+)?tab\b|\banother tab\b", "new tab"),
    (r"\b(?:open|make|create)\s+(?:a\s+|an\s+)?(?:new|another)\s+window\b", "new window"),
    (r"\bnavigate back\b|\bprevious page\b|\bpage back\b|\bback a page\b", "go back"),
    (r"\bnavigate forward\b|\bnext page\b|\bpage forward\b|\bforward a page\b", "go forward"),
    (r"\bsave\s+(?:this\s+|the\s+|my\s+)?(?:file|document|work)\b", "save"),
    (r"\brevert\b|\btake that back\b", "undo"),
    # power
    (r"\bpower ?off\b|\bpower ?down\b|\bshut ?down\b|\bturn off (?:the |my )?(?:computer|pi|deck|cyberdeck|"
     r"system|device|machine|raspberry pi)\b", "shut down"),
    (r"\breboot\b|\bpower cycle\b|\brestart (?:the |my )?(?:computer|pi|deck|cyberdeck|system|device|"
     r"machine|raspberry pi)\b", "restart"),
    # mouse
    (r"\b(?:the|my) mouse\b", "mouse"),
    (r"\b(?:cursor|pointer)\b", "mouse"),
    (r"(?<!move )(?<!nudge )\bmouse\s+(left|right|up|down)\b", r"move mouse \1"),
    (r"\bmouse\s+to(?:\s+the)?\s+(top|bottom)\s+(left|right)(?:\s+corner)?\b", r"mouse \1 \2"),
    (r"\bdouble tap\b", "double click"),
    (r"\bcontext menu\b", "right click"),
    (r"\b(?:tap|mouse click)\b", "click"),
    # info
    (r"\bcurrent time\b|\btime now\b|\b(?:what s|whats|what is|tell me|show me)\s+(?:the\s+)?(?:current\s+)?time\b",
     "what time is it"),
    (r"\bwhat day is it\b|\btodays? date\b|\b(?:what s|whats|what is|tell me|show me)\s+(?:the\s+|todays\s+)?date\b",
     "what is the date"),
    (r"\bcpu temp(?:erature)?\b|\bhow hot(?: is it)?\b|\btemperature\b", "cpu temperature"),
    (r"\bmy ip(?: address)?\b|\bip address\b", "ip address"),
    (r"\bhow much battery(?: is left| do i have)?\b|\bbattery (?:percentage|percent|status|left|life)\b",
     "battery level"),
    (r"\bhow much ram\b|\bram(?: usage)?\b", "memory usage"),
    (r"\bfree space\b|\bhow much (?:disk )?space\b|\bstorage\b", "disk space"),
]

def strip_fillers(seg):
    seg = PRE_RE.sub("", seg.strip())
    return POST_RE.sub("", seg).strip()

def normalize_heard(t):
    h = clean_phrase(t)
    for pat, rep in SYNONYMS:
        h = re.sub(pat, rep, h)
    return re.sub(r"\s+", " ", h).strip()

ACTION_TOKENS = {}

def rebuild_action_index():
    ACTION_TOKENS.clear()
    for p in ACTIONS:
        ACTION_TOKENS[p] = {tok(w) for w in p.split() if w not in FILLERS}

def best_action(heard):
    """Finds the closest known action even if the wording is different."""
    if not heard:
        return None, 0.0
    m = difflib.get_close_matches(heard, list(ACTIONS), n=1, cutoff=0.8)
    if m:
        return m[0], difflib.SequenceMatcher(None, heard, m[0]).ratio()   # 1.0 only for an exact match
    hs = {tok(w) for w in heard.split() if w not in FILLERS}
    if not hs:
        return None, 0.0
    best, best_s = None, 0.0
    for phrase, pt in ACTION_TOKENS.items():
        c = len(hs & pt)
        if not c:
            continue
        p, r = c / len(hs), c / len(pt)
        s = 2 * p * r / (p + r)
        if s > best_s + 1e-9:
            best, best_s = phrase, s
    return (best, best_s) if best_s >= 0.7 else (None, 0.0)

def suggest_actions(heard, n=3):
    """Nearest commands when nothing matched well: [(score, phrase), ...]"""
    hs = {tok(w) for w in heard.split() if w not in FILLERS}
    scored = []
    for phrase, pt in ACTION_TOKENS.items():
        c = len(hs & pt)
        tk = 0.0
        if c:
            p, r = c / len(hs), c / len(pt)
            tk = 2 * p * r / (p + r)
        s = max(tk, difflib.SequenceMatcher(None, heard, phrase).ratio() * 0.9)
        if s >= 0.4:
            scored.append((s, phrase))
    scored.sort(reverse=True)
    return scored[:n]

# ---------------- chaining: "open browser and search ..." ----------------
CONNECTOR_RE = re.compile(r"\s*,?\s*\b(and then|and also|after that|afterwards|then|also|plus|and)\b\s+", re.I)
ALWAYS_SPLIT = {"then", "and then", "after that", "afterwards"}
CMD_VERBS = {"open", "launch", "start", "run", "close", "search", "google", "go", "click", "double", "triple",
             "right", "left", "middle", "scroll", "press", "type", "volume", "mute", "unmute", "brightness",
             "wifi", "bluetooth", "airplane", "set", "timer", "stopwatch", "play", "pause", "next", "previous",
             "zoom", "new", "switch", "reload", "refresh", "copy", "paste", "cut", "undo", "redo", "save",
             "select", "move", "nudge", "take", "minecraft", "speech", "show", "hold", "release", "learn",
             "forget", "do", "repeat", "cancel", "stop", "lap", "reset", "turn", "shut", "restart", "reboot",
             "find", "bookmark", "full", "fullscreen", "maximize", "visit", "browse", "look", "lower", "raise",
             "increase", "decrease", "exit", "quit", "delete", "remove", "kill", "tap", "execute", "help",
             "make", "add", "write", "jot", "note", "view", "read"}

def looks_like_command(rest):
    h = normalize_heard(strip_fillers(rest))
    w = h.split()
    if not w:
        return False
    if w[0] in CMD_VERBS:
        return True
    return best_action(split_count(h)[1])[0] is not None

def split_chain(t):
    t = t.strip()
    cuts = []
    for m in CONNECTOR_RE.finditer(t):
        if m.group(1).lower() in ALWAYS_SPLIT or looks_like_command(t[m.end():]):
            cuts.append((m.start(), m.end()))
    segs, pos = [], 0
    for a, b in cuts:
        segs.append(t[pos:a])
        pos = b
    segs.append(t[pos:])
    segs = [s.strip(" ,.!?") for s in segs]
    return [s for s in segs if s]

# ---------------- timers, stopwatch ----------------
# All timing uses time.monotonic(): a Pi has no battery clock, so the wall clock can jump when the
# network time arrives, which would make timers and the stopwatch fire early or show nonsense.
UNIT_SECS = {"hour": 3600, "hours": 3600, "hr": 3600, "hrs": 3600,
             "minute": 60, "minutes": 60, "min": 60, "mins": 60,
             "second": 1, "seconds": 1, "sec": 1, "secs": 1}

def parse_duration(s):
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    s = (s.replace("an hour and a half", "90 minutes").replace("a minute and a half", "90 seconds")
          .replace("half an hour", "30 minutes").replace("half a hour", "30 minutes"))
    total, val, used = 0, None, False
    for tk in s.split():
        if tk.isdigit():
            val = (val or 0) + int(tk)
        elif tk in NUMW:
            val = (val or 0) + NUMW[tk]
        elif tk in ("a", "an") and val is None:
            val = 1
        elif tk in UNIT_SECS and val is not None:
            total += val * UNIT_SECS[tk]
            val, used = None, True
    return total if used and 0 < total <= 86400 else None

def fmt_duration(secs):
    h, rem = divmod(int(secs), 3600)
    m, s = divmod(rem, 60)
    parts = ([f"{h} h"] if h else []) + ([f"{m} min"] if m else []) + ([f"{s} sec"] if s else [])
    return " ".join(parts) or "0 sec"

# start = when the current run began, base = time already counted, history = every stop and lap
sw = {"start": None, "base": 0.0, "laps": [], "history": [], "shown_until": 0.0}

def sw_elapsed():
    start = sw["start"]            # read once: another thread may stop the stopwatch at any moment
    return sw["base"] + (time.monotonic() - start if start else 0.0)

def stop_stopwatch():
    """Stops the stopwatch if it's running, keeps the time and shows it for a few seconds.
    Returns True if it was running."""
    if not sw["start"]:
        return False
    sw["base"] = sw_elapsed()
    sw["start"] = None
    sw["history"].append({"kind": "stop", "t": sw["base"]})
    sw["shown_until"] = time.monotonic() + STOPWATCH_STOP_SHOW_SECS     # stays up a few seconds, then closes
    return True

def fmt_sw(sec):
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:04.1f}" if h >= 1 else f"{int(m)}:{s:04.1f}"

def stopwatch_text():
    """What the on-screen pill shows: running time, or the final time for a few seconds after stopping."""
    if sw["start"]:
        return "STOPWATCH " + fmt_sw(sw_elapsed())
    if time.monotonic() < sw["shown_until"]:
        return "STOPPED " + fmt_sw(sw["base"])
    return None

# ---------------- help (so you don't have to memorize commands) ----------------
HELP_OVERVIEW = [
    "Just say what you want, like:",
    "  open firefox",
    "  search who made the rubik's cube",
    "  close two tabs",
    "  set volume to 40 percent",
    "  open browser and search youtube.com",
    "",
    "Say  help <topic>  for examples:",
    "  apps  search  browser  mouse",
    "  keyboard  sound  screen  system",
    "  timers  stopwatch  notes  words  chain",
]
HELP_TOPICS = [   # (name, words that point to it, title, lines)
    ("apps", "app apps open program programs website websites site sites firefox quit force kill", "OPEN APPS AND SITES",
     ["open <any app name>", "open firefox / terminal / files", "go to youtube.com", "open reddit",
      "open firefox and terminal   (several at once)", "close <app name>   (close firefox, close minecraft)",
      "close firefox and terminal",
      "force quit <app>   (if it won't close)", "reload apps   (after installing one)"]),
    ("search", "search google look question web find", "SEARCH",
     ["search <anything>", "search youtube for <thing>", "search wikipedia for <thing>",
      "ask a question: who / what / how ...", "open browser and search <thing>"]),
    ("browser", "browser tab tabs window windows zoom bookmark page", "BROWSER AND WINDOWS",
     ["new tab / close tab", "next tab / previous tab / reopen tab", "reload page", "go back / go forward",
      "zoom in / zoom out", "full screen", "close window / switch window"]),
    ("mouse", "mouse click cursor scroll drag pointer", "MOUSE",
     ["click / right click / double click", "move mouse left (or nudge mouse left)",
      "mouse top left  (the corners)", "scroll up / scroll down", "hold click ... release click",
      "add a number: click three times"]),
    ("keyboard", "keyboard key keys press type typing copy paste undo editing", "KEYBOARD",
     ["press control c", "press alt f4", "press enter 3 times", "type hello world",
      "copy / paste / cut / undo / redo", "select all / save"]),
    ("sound", "sound volume audio mute music media track", "SOUND",
     ["volume up / volume down", "set volume to 40 percent", "mute", "play pause / next track"]),
    ("screen", "screen brightness display screenshot", "SCREEN",
     ["brightness up / brightness down", "set brightness to 70", "take screenshot"]),
    ("system", "system wifi bluetooth pi battery cpu memory temperature info status power network airplane",
     "PI AND SYSTEM",
     ["wifi off / wifi on", "bluetooth on / off", "cpu temperature / cpu usage", "memory usage / disk space",
      "battery level / uptime", "what time is it", "shut down / restart  (asks only if unsure)"]),
    ("timers", "timer timers alarm countdown", "TIMERS",
     ["set a timer for 10 minutes", "how much time is left", "cancel timer"]),
    ("stopwatch", "stopwatch lap laps times", "STOPWATCH",
     ["start stopwatch", "lap", "stop stopwatch", "resume stopwatch / reset stopwatch",
      "show times / clear times"]),
    ("notes", "note notes memo write list read jot", "NOTES",
     ["make a note <anything>", "make a note   (then say the note)", "show notes / view all notes",
      "older notes / newer notes", "close notes"]),
    ("words", "word words vocabulary learn teach spell", "TEACH IT WORDS",
     ["learn the word Enderman", "spelled: e n d e r m a n", "say capital D for a capital letter",
      "forget the word <word>", "how many words"]),
    ("chain", "chain chaining combine multiple then repeat again", "CHAINING AND REPEATING",
     ["open browser and search <thing>", "close tab then new tab", "close two tabs", "do that again"]),
]

def find_help_topic(text):
    toks = {stem(w) for w in clean_phrase(text).split()}
    best, best_n = None, 0
    for _, kws, title, lines in HELP_TOPICS:
        n = len(toks & {stem(k) for k in kws.split()})
        if n > best_n:
            best, best_n = (title, lines), n
    return best

# ---------------- Minecraft knowledge ----------------
MC_COMMAND_SET = set(mcdata.MC_COMMANDS)
GAMERULES = mcdata.gamerule_phrases()
mc_entities = set(mcdata.ENTITY_IDS)
mc_nospace, mc_keys = {}, []
SPECIAL_RE = re.compile(r"^(?:[-~^]?\d*\.?\d+|[~^]|@[a-z](?:\[.*\])?|.*[A-Z].*|.*[:\[\]{}=].*)$")
MC_FIXES = [
    (r"^game\s*(?:mode|with|more|mood|made|mold|moat|mod)\b", "gamemode"),
    (r"^default\s*game\s*mode\b", "defaultgamemode"),
    (r"^game\s*rule\b", "gamerule"),
    (r"^set\s*block\b", "setblock"),
    (r"^set\s*world\s*spawn\b", "setworldspawn"),
    (r"^spawn\s*point\b", "spawnpoint"),
    (r"^de\s*op\b", "deop"),
    (r"^white\s*list\b", "whitelist"),
    (r"^world\s*border\b", "worldborder"),
    (r"^ban\s*ip\b", "ban-ip"),
    (r"^pardon\s*ip\b", "pardon-ip"),
    (r"^save\s*(all|off|on)\b", r"save-\1"),
    (r"^fill\s*biome\b", "fillbiome"),
    (r"^play\s*sound\b", "playsound"),
    (r"^stop\s*sound\b", "stopsound"),
    (r"^spread\s*players\b", "spreadplayers"),
    (r"^t\s*p\b", "tp"),
]
MC_MACROS = {
    "creative mode": ("cmd", "gamemode creative"),
    "survival mode": ("cmd", "gamemode survival"),
    "adventure mode": ("cmd", "gamemode adventure"),
    "spectator mode": ("cmd", "gamemode spectator"),
    "make it day": ("cmd", "time set day"),
    "make it night": ("cmd", "time set night"),
    "make it noon": ("cmd", "time set noon"),
    "clear weather": ("cmd", "weather clear"),
    "make it rain": ("cmd", "weather rain"),
    "make it thunder": ("cmd", "weather thunder"),
    "peaceful mode": ("cmd", "difficulty peaceful"),
    "easy mode": ("cmd", "difficulty easy"),
    "normal mode": ("cmd", "difficulty normal"),
    "hard mode": ("cmd", "difficulty hard"),
    "keep inventory on": ("cmd", "gamerule keepInventory true"),
    "keep inventory off": ("cmd", "gamerule keepInventory false"),
    "heal me": ("cmd", "effect give @s instant_health 1 10"),
    "feed me": ("cmd", "effect give @s saturation 1 10"),
    "night vision on": ("cmd", "effect give @s night_vision 99999 1 true"),
    "clear effects": ("cmd", "effect clear @s"),
    "set spawn": ("cmd", "spawnpoint"),
    "open inventory": ("keys", [e.KEY_E]),
    "drop item": ("keys", [e.KEY_Q]),
    "swap hands": ("keys", [e.KEY_F]),
    "debug screen": ("keys", [e.KEY_F3]),
    "take screenshot": ("keys", [e.KEY_F2]),
    "hide hud": ("keys", [e.KEY_F1]),
    "change view": ("keys", [e.KEY_F5]),
    "pause game": ("keys", [e.KEY_ESC]),
    "repeat command": ("again", None),
    "run that again": ("again", None),
    "tiny model": ("model", "tiny.en"),
    "base model": ("model", "base.en"),
}
for _n, _w in enumerate(["one", "two", "three", "four", "five", "six", "seven", "eight", "nine"], start=1):
    MC_MACROS[f"slot {_w}"] = ("keys", [getattr(e, f"KEY_{_n}")])
    MC_MACROS[f"slot {_n}"] = ("keys", [getattr(e, f"KEY_{_n}")])

COLORS = {
    "speech": (0.18, 0.80, 0.44),      # green
    "minecraft": (0.62, 0.42, 1.00),   # purple
    "command": (0.25, 0.65, 1.00),     # blue
    "busy": (1.00, 0.70, 0.00),        # yellow
    "rec": (1.00, 0.23, 0.19),         # red
    "err": (1.00, 0.45, 0.20),         # orange
}

# ---------------- only one copy at a time ----------------
def _alive(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False

def kill_other_instances():
    me, parent = os.getpid(), os.getppid()
    others = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        pid = int(name)
        if pid in (me, parent):
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                args = f.read().decode(errors="ignore").split("\0")
        except OSError:
            continue
        if (args and os.path.basename(args[0]).startswith("python")
                and any(os.path.basename(a) == "dictate.py" for a in args[1:])):
            others.append(pid)
    for pid in others:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and any(_alive(p) for p in others):
        time.sleep(0.1)
    for pid in others:
        if _alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    if others:
        print(f"Stopped old instance(s): {others}")

kill_other_instances()
# ---------------------------------------------------------

def to_16k(audio, rate):
    if rate == 16000:
        return audio
    if rate % 16000 == 0:
        n = rate // 16000
        audio = audio[: len(audio) // n * n]
        return audio.reshape(-1, n).mean(axis=1).astype(np.float32)
    n_new = int(len(audio) * 16000 / rate)
    x_new = np.linspace(0, len(audio) - 1, n_new)
    return np.interp(x_new, np.arange(len(audio)), audio).astype(np.float32)

# Only one model lives in memory at a time. Switching loads the new one, then lets go of the old one.
loaded = {}

def load_whisper(name):
    """Loads from the local copy when there is one, so no internet (and no Hugging Face warning) is needed.
    Only the very first time, when the model isn't downloaded yet, does it go online."""
    from faster_whisper import WhisperModel    # imported here so hf_token (config.toml) is set before it loads
    kwargs = dict(device="cpu", compute_type="int8", cpu_threads=WHISPER_THREADS)
    try:
        return WhisperModel(name, local_files_only=True, **kwargs)
    except Exception:
        return WhisperModel(name, **kwargs)

def get_model(name):
    """Returns the model, loading it if needed. Call it with tlock held (or before any threads start)."""
    if name not in loaded:
        new = load_whisper(name)
        loaded.clear()                      # drop the old model so its memory can be freed
        loaded[name] = new
        gc.collect()
    return loaded[name]

print(f"Loading {START_MODEL}...")
get_model(START_MODEL)

# ---------------- keyboards (listen without grabbing, and notice plug / unplug / keyd restart) ----------------
sel = DefaultSelector()
kb_devs = {}          # path -> InputDevice that we are listening to
kb_skipped = set()    # paths already checked that can't send the mode key

def scan_keyboards():
    """Finds every input device that can send the mode key. Safe to call over and over: it also picks up
    devices that appear later (keyd restarting recreates its virtual keyboard, a keyboard being plugged in)."""
    try:
        paths = list_devices()
    except Exception as err:
        print("Couldn't list input devices:", err)
        return
    kb_skipped.intersection_update(paths)          # forget paths that vanished
    for p in paths:
        if p in kb_devs or p in kb_skipped:
            continue
        kb_skipped.add(p)                          # re-added to kb_devs below if it's a keyboard we want
        try:
            d = InputDevice(p)
        except PermissionError:
            print(f"No permission to read {p} (add your user to the 'input' group, or run as root)")
            continue
        except OSError:
            continue
        try:
            wanted = "dictate-virtual" not in d.name and MODE_KEY in d.capabilities().get(e.EV_KEY, [])
        except OSError:
            wanted = False
        if not wanted:
            d.close()
            continue
        kb_skipped.discard(p)
        kb_devs[p] = d
        sel.register(d, EVENT_READ)
        print("Listening on:", d.name)

def drop_keyboard(dev):
    try:
        sel.unregister(dev)
    except Exception:
        pass
    kb_devs.pop(dev.path, None)
    try:
        dev.close()
    except Exception:
        pass

scan_keyboards()
if not kb_devs and BUTTON_PIN is None:
    raise SystemExit("No keyboard with the mode key found and no GPIO button set.")

ui = UInput(name="dictate-virtual", vendor=0x1234, product=0x5678)          # virtual keyboard
mouse = UInput({e.EV_KEY: [e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE],
                e.EV_REL: [e.REL_X, e.REL_Y, e.REL_WHEEL, e.REL_HWHEEL]},
               name="dictate-virtual-mouse", vendor=0x1234, product=0x5678)  # virtual mouse

BASE = {c: getattr(e, f"KEY_{c.upper()}") for c in "abcdefghijklmnopqrstuvwxyz0123456789"}
BASE.update({" ": e.KEY_SPACE, ",": e.KEY_COMMA, ".": e.KEY_DOT, "/": e.KEY_SLASH,
             "'": e.KEY_APOSTROPHE, "-": e.KEY_MINUS, ";": e.KEY_SEMICOLON, "=": e.KEY_EQUAL,
             "[": e.KEY_LEFTBRACE, "]": e.KEY_RIGHTBRACE, "\\": e.KEY_BACKSLASH, "`": e.KEY_GRAVE})
SHIFT = {"?": e.KEY_SLASH, "!": e.KEY_1, ":": e.KEY_SEMICOLON, '"': e.KEY_APOSTROPHE,
         "(": e.KEY_9, ")": e.KEY_0, "_": e.KEY_MINUS, "@": e.KEY_2, "#": e.KEY_3,
         "$": e.KEY_4, "%": e.KEY_5, "&": e.KEY_7, "*": e.KEY_8, "+": e.KEY_EQUAL,
         "~": e.KEY_GRAVE, "^": e.KEY_6,
         "{": e.KEY_LEFTBRACE, "}": e.KEY_RIGHTBRACE, "|": e.KEY_BACKSLASH,
         "<": e.KEY_COMMA, ">": e.KEY_DOT}
KEYNAMES = {"enter": e.KEY_ENTER, "return": e.KEY_ENTER, "escape": e.KEY_ESC, "esc": e.KEY_ESC,
            "tab": e.KEY_TAB, "space": e.KEY_SPACE, "spacebar": e.KEY_SPACE, "backspace": e.KEY_BACKSPACE,
            "delete": e.KEY_DELETE, "home": e.KEY_HOME, "end": e.KEY_END, "pageup": e.KEY_PAGEUP,
            "pagedown": e.KEY_PAGEDOWN, "up": e.KEY_UP, "down": e.KEY_DOWN, "left": e.KEY_LEFT,
            "right": e.KEY_RIGHT, "insert": e.KEY_INSERT, "capslock": e.KEY_CAPSLOCK}
MODKEYS = {"control": CTRL, "ctrl": CTRL, "alt": ALT, "shift": SHFT, "super": META, "windows": META,
           "meta": META, "command": META}

def tap(k):
    ui.write(e.EV_KEY, k, 1)
    ui.syn()                                # press and release in separate frames: more reliable in games
    ui.write(e.EV_KEY, k, 0)
    ui.syn()

def combo(keys):
    for k in keys:
        ui.write(e.EV_KEY, k, 1)
    ui.syn()
    time.sleep(0.03)
    for k in reversed(keys):
        ui.write(e.EV_KEY, k, 0)
    ui.syn()

def parse_keys(s):
    """'control shift t' -> [CTRL, SHIFT, T]; 'f 5' -> [F5]; 'page down' -> [PAGEDOWN]"""
    s = s.replace("page up", "pageup").replace("page down", "pagedown").replace("caps lock", "capslock")
    s = re.sub(r"\bf\s+(\d{1,2})\b", r"f\1", s)
    mods, key = [], None
    for tk in s.split():
        if tk in ("plus", "and", "then", "the", "key"):
            continue
        if tk in MODKEYS:
            mods.append(MODKEYS[tk])
        elif tk in KEYNAMES:
            key = KEYNAMES[tk]
        elif re.fullmatch(r"f\d{1,2}", tk) and 1 <= int(tk[1:]) <= 12:
            key = getattr(e, f"KEY_F{int(tk[1:])}")
        elif len(tk) == 1 and tk in BASE:
            key = BASE[tk]
        elif tk in NUMW and NUMW[tk] < 10:
            key = BASE[str(NUMW[tk])]
        else:
            return None
    if key is None and not mods:
        return None
    return mods + ([key] if key else [])

# ---------------- mouse ----------------
def mouse_button(btn, value):
    mouse.write(e.EV_KEY, btn, value)
    mouse.syn()

def mouse_click(btn, n=1):
    for i in range(n):
        mouse_button(btn, 1)
        time.sleep(0.03)
        mouse_button(btn, 0)
        if i < n - 1:
            time.sleep(0.06)

def mouse_wheel(notches):
    step = 1 if notches > 0 else -1
    for _ in range(abs(notches)):
        mouse.write(e.EV_REL, e.REL_WHEEL, step)
        mouse.syn()
        time.sleep(0.02)

def mouse_move(dx, dy, scale=True):
    """Moves in small steps so the pointer glides instead of jumping."""
    if scale:
        dx, dy = dx * MOUSE_SCALE, dy * MOUSE_SCALE
    dx, dy = int(dx), int(dy)
    steps = max(1, min(80, max(abs(dx), abs(dy)) // 8))
    done_x = done_y = 0
    for i in range(1, steps + 1):
        tx, ty = round(dx * i / steps), round(dy * i / steps)
        sx, sy = tx - done_x, ty - done_y
        done_x, done_y = tx, ty
        if sx:
            mouse.write(e.EV_REL, e.REL_X, sx)
        if sy:
            mouse.write(e.EV_REL, e.REL_Y, sy)
        mouse.syn()
        time.sleep(0.004)

def mouse_release_all():
    for b in (e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE):
        mouse.write(e.EV_KEY, b, 0)
    mouse.syn()

# ---------------- shared state ----------------
# phase: idle / rec / busy      mode: speech / minecraft / command
# gen goes up every time you cancel, so work from an older job knows to stop
state = {"phase": "idle", "mode": "speech", "level": 0.0, "model": START_MODEL,
         "toast": None, "panel": None, "gen": 0}
# pending = a question waiting for yes / no ("Shut down? Say yes or no", "close window? say yes")
pending = {"kind": None, "phrase": "", "count": 1, "until": 0.0}
lock = threading.Lock()          # protects the recording stream
tlock = threading.Lock()         # one transcription at a time
chunks, stream = [], None
rec = {"rate": 16000, "frames": 0}
last_cmd = {"kind": None, "payload": None, "count": 1, "label": ""}
last_mc = {"type": None, "cmd": "", "phrase": "", "count": 1}

# Names that need a special capital: "wifi off" -> "Wi-Fi off", "open youtube" -> "Open YouTube"
PROPER = {"wifi": "Wi-Fi", "bluetooth": "Bluetooth", "cpu": "CPU", "ram": "RAM", "ip": "IP", "gpio": "GPIO",
          "ok": "OK", "minecraft": "Minecraft", "firefox": "Firefox", "youtube": "YouTube", "google": "Google",
          "google maps": "Google Maps", "wikipedia": "Wikipedia", "amazon": "Amazon", "github": "GitHub",
          "reddit": "Reddit", "twitch": "Twitch", "imdb": "IMDb", "ebay": "eBay", "netflix": "Netflix",
          "spotify": "Spotify", "gmail": "Gmail", "stack overflow": "Stack Overflow",
          "minecraft wiki": "Minecraft Wiki"}
PROPER_RE = re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted(PROPER, key=len, reverse=True)) + r")\b",
                       re.I)

def pretty(text):
    """Capitalizes a pop-up message the way you'd write it. ALL-CAPS labels (CANCELLED, MIC MISSING)
    are left alone, and so is anything that starts with a symbol or digit (/gamemode, 12% cpu)."""
    if not text or text.upper() == text:
        return text
    if text[0].islower():
        text = text[0].upper() + text[1:]
    return PROPER_RE.sub(lambda m: PROPER[m.group(1).lower()], text)

def show_toast(text, color, secs=1.6):
    state["panel"] = None
    state["toast"] = {"text": pretty(text)[:1000], "color": color, "until": time.monotonic() + secs}

def show_panel(title, lines, color="command", secs=12.0):
    """A small list on screen (help, stopwatch times, suggestions)."""
    state["toast"] = None
    state["panel"] = {"title": title[:60], "lines": [x[:240] for x in lines[:PANEL_MAX]],
                      "color": color, "until": time.monotonic() + secs}

def announce():
    short = state["model"].split(".")[0]
    label = {"speech": f"SPEECH - {short}", "minecraft": f"MINECRAFT - {short}",
             "command": f"COMMAND - {short} - say help"}[state["mode"]]
    print(f">>> {label}")
    show_toast(label, state["mode"], 2.2)

def preload_model(name):
    """Runs in the background after you switch models, so it's ready by the time you talk."""
    with tlock:                             # never swap while a transcription is running
        if state["model"] != name:          # you've already switched again
            return
        had = name in loaded
        if not had:
            show_toast("LOADING " + name.split(".")[0], "busy", 30.0)
        try:
            get_model(name)
        except Exception as err:            # e.g. not downloaded yet and no internet
            print("Couldn't load", name, "-", err)
            if loaded:
                state["model"] = next(iter(loaded))
            show_toast("MODEL LOAD FAILED", "err", 3.0)
            return
    if not had:
        show_toast("MODEL READY - " + name.split(".")[0], state["mode"], 1.8)

def set_model(name):
    state["model"] = name
    label = "MODEL - " + name.split(".")[0]
    print(f">>> {label}")
    show_toast(label, state["mode"])
    threading.Thread(target=preload_model, args=(name,), daemon=True).start()

# ---------------- the microphone: waits for it, notices plug/unplug ----------------
mic = {"ok": False, "index": None, "rate": 16000, "name": ""}
mic_watch = {"cards": None, "last_reinit": 0.0}

def read_cards():
    try:
        with open("/proc/asound/cards") as f:
            return f.read()
    except OSError:
        return ""

def find_mic():
    try:
        if MIC is None:
            d = sd.query_devices(kind="input")
            return d.get("index", sd.default.device[0]), d
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] < 1:
                continue
            if isinstance(MIC, int):
                if i == MIC:
                    return i, d
            elif MIC.lower() in d["name"].lower():
                return i, d
    except Exception:
        pass
    return None

def refresh_mic(tell=True):
    found = find_mic()
    if found:
        i, d = found
        was = mic["ok"]
        mic.update(ok=True, index=i, rate=int(d["default_samplerate"]), name=d["name"])
        if not was and tell:
            print(f"Mic connected: {d['name']} @ {mic['rate']} Hz")
            show_toast("MIC CONNECTED", "speech", 2.0)
    else:
        if mic["ok"] and tell:
            print("Mic lost. Waiting for it to come back...")
            show_toast("MIC MISSING", "err", 3.0)
        mic.update(ok=False, index=None)

def mic_watch_loop():
    while True:
        time.sleep(1.5)
        try:
            cards = read_cards()
            changed = cards != mic_watch["cards"]
            stale = (not mic["ok"]) and time.monotonic() - mic_watch["last_reinit"] > 5
            if changed or stale:
                mic_watch["cards"] = cards
                with lock:
                    idle = stream is None and not alarm_active.is_set()
                    if idle:
                        try:
                            sd._terminate()          # makes PortAudio re-read the device list
                            sd._initialize()
                        except Exception as err:
                            print("Couldn't refresh audio devices:", err)
                        mic_watch["last_reinit"] = time.monotonic()
                if idle:
                    refresh_mic()
        except Exception as err:
            print("Mic watcher:", err)

# ---------------- your words (words.json) ----------------
words = {"vocab": []}

def save_words():
    try:
        tmp = WORDS_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(words, f, indent=2, ensure_ascii=False)
        os.replace(tmp, WORDS_FILE)
    except Exception as err:
        print("Couldn't save words.json:", err)

def load_words():
    try:
        with open(WORDS_FILE) as f:
            words["vocab"] = list(json.load(f).get("vocab", []))
        print(f"Words: {len(words['vocab'])} learned ({WORDS_FILE})")
    except FileNotFoundError:
        save_words()
    except Exception as err:
        print("Problem reading words.json:", err)

def add_vocab(w):
    if not w:
        return
    low = [v.lower() for v in words["vocab"]]
    if w.lower() in low:
        i = low.index(w.lower())
        if words["vocab"][i] == w:
            return
        words["vocab"][i] = w                      # same word, new capitalization
    else:
        words["vocab"].append(w)
    save_words()
    rebuild_mc_index()

def forget_word(w):
    kept = [v for v in words["vocab"] if v.lower() != w.lower()]
    removed = len(words["vocab"]) - len(kept)
    if removed:
        words["vocab"] = kept
        save_words()
        rebuild_mc_index()
    return removed

def prompt_for(mode):
    base = {"command": COMMAND_PROMPT, "minecraft": mcdata.MC_PROMPT}.get(mode, INITIAL_PROMPT) or ""
    return (base + " " + ", ".join(words["vocab"][-40:])).strip() or None

CAP_WORDS = {"capital", "capitalize", "capitalized", "cap", "caps", "uppercase", "upper"}
SPELL_SYMBOLS = {"space": " ", "dash": "-", "hyphen": "-", "underscore": "_"}

def spell_join(arg):
    """'e n d e r' -> 'ender'.  'capital D r a g o n' -> 'Dragon'.  Letters stay lowercase unless
    you say capital / capitalize right before them."""
    arg = re.sub(r"^\s*spelled?\b[\s:,-]*", "", arg.strip(), flags=re.I)
    toks = [x.lower() for x in re.split(r"[^A-Za-z0-9]+", arg) if x]
    toks = [x for x in toks if x not in ("case", "letter")]
    letters = [x for x in toks if len(x) == 1]
    spelled = all(len(x) == 1 or x in CAP_WORDS or x in SPELL_SYMBOLS for x in toks)
    if not (spelled and len(letters) >= 2):
        s = arg.strip()
        # one all-caps blob like "DRAGON" is almost certainly spelled-out letters
        return s.lower() if len(s) > 2 and s.isalpha() and s.isupper() else s
    out, cap = [], False
    for tk in toks:
        if tk in CAP_WORDS:
            cap = True
        elif tk in SPELL_SYMBOLS:
            out.append(SPELL_SYMBOLS[tk])
        else:
            out.append(tk.upper() if cap else tk)
            cap = False
    return "".join(out)

# your own commands: ~/stt/commands.json  ->  {"cyberdeck monitor": "lxterminal -e htop"}
custom_phrases = set()
custom_dangerous = set()      # custom commands marked "dangerous": true

def load_custom_commands():
    for p in custom_phrases:                       # undo the last load, restoring any built-in it replaced
        if p in BUILTIN_ACTIONS:
            ACTIONS[p] = BUILTIN_ACTIONS[p]
        else:
            ACTIONS.pop(p, None)
    custom_phrases.clear()
    custom_dangerous.clear()
    try:
        with open(COMMANDS_FILE) as f:
            data = json.load(f)
        for phrase, cmd in data.items():
            p = clean_phrase(phrase)
            dangerous = False
            if isinstance(cmd, dict):                    # {"run": "...", "dangerous": true}
                dangerous = bool(cmd.get("dangerous"))
                cmd = cmd.get("run")
            if p and isinstance(cmd, str):
                ACTIONS[p] = ("run", cmd)
                custom_phrases.add(p)
                if dangerous:
                    custom_dangerous.add(p)
        if custom_phrases:
            print(f"Custom commands: {len(custom_phrases)} ({COMMANDS_FILE})")
    except FileNotFoundError:
        pass
    except Exception as err:
        print("Problem reading commands.json:", err)
    rebuild_action_index()

# ---------------- installed apps (so "open <anything>" works) ----------------
app_index = []
APP_DIRS = ["/usr/share/applications", "/usr/local/share/applications", "~/.local/share/applications",
            "/var/lib/flatpak/exports/share/applications", "~/.local/share/flatpak/exports/share/applications",
            "/var/lib/snapd/desktop/applications"]

def build_app_index():
    found, seen = [], set()
    for folder in APP_DIRS:
        folder = os.path.expanduser(folder)
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for fn in names:
            if not fn.endswith(".desktop") or fn in seen:
                continue
            try:
                with open(os.path.join(folder, fn), errors="ignore") as f:
                    lines = f.read().splitlines()
            except OSError:
                continue
            entry, in_main = {}, False
            for ln in lines:
                if ln.startswith("["):
                    in_main = ln.strip() == "[Desktop Entry]"
                    continue
                if in_main and "=" in ln:
                    k, v = ln.split("=", 1)
                    if k in ("Name", "GenericName", "Keywords", "Exec", "NoDisplay", "Hidden", "Type", "Terminal"):
                        entry.setdefault(k, v.strip())
            if (entry.get("Type", "Application") != "Application" or "Exec" not in entry
                    or "Name" not in entry or entry.get("NoDisplay", "").lower() == "true"
                    or entry.get("Hidden", "").lower() == "true"):
                continue
            seen.add(fn)
            keys = {entry["Name"].lower(), fn[:-8].split(".")[-1].lower()}
            if entry.get("GenericName"):
                keys.add(entry["GenericName"].lower())
            for kw in entry.get("Keywords", "").split(";"):
                if kw.strip():
                    keys.add(kw.strip().lower())
            found.append({"name": entry["Name"], "exec": entry["Exec"], "keys": keys,
                          "terminal": entry.get("Terminal", "").lower() == "true"})
    app_index[:] = found

def find_app(query):
    q = APP_ALIASES.get(query, query)
    qn = re.sub(r"[^a-z0-9]", "", q)
    if not qn:
        return None
    best, best_s = None, 0.0
    for app in list(app_index):
        for k in app["keys"]:
            kn = re.sub(r"[^a-z0-9]", "", k)
            if not kn:
                continue
            if kn == qn:
                s = 1.0
            elif min(len(kn), len(qn)) >= 4 and (qn in kn or kn in qn):
                s = 0.9
            else:
                s = difflib.SequenceMatcher(None, qn, kn).ratio()
            if s > best_s:
                best, best_s = app, s
    return best if best_s >= 0.8 else None

# ---------------- websites ----------------
TLDS = "com|org|net|io|gg|tv|dev|app|co|edu|gov|me|ai|us|uk|ca|de|fr|xyz|info|wiki"
DOMAIN_RE = re.compile(r"(?<![\w.@-])((?:[a-z0-9-]+\.)+(?:" + TLDS + r"))(?![\w-])(/\S*)?", re.I)
SPOKEN_DOMAIN_RE = re.compile(r"\b([a-z0-9-]+)\s+dot\s+(" + TLDS + r")\b", re.I)

def find_domain(s):
    m = DOMAIN_RE.search(s)
    if m:
        return (m.group(1) + (m.group(2) or "")).lower()
    m = SPOKEN_DOMAIN_RE.search(s)
    return (m.group(1) + "." + m.group(2)).lower() if m else None

def site_match(name):
    n = re.sub(r"\b(?:dot com|dot org|dot net)\b|\.(?:com|org|net|tv|gg|io)\b|^www\.?", "", name.lower())
    n = re.sub(r"[^a-z0-9]", "", n)
    if not n:
        return None
    keys = {re.sub(r"[^a-z0-9]", "", k): k for k in SITES}
    if n in keys:
        return keys[n]
    m = difflib.get_close_matches(n, list(keys), n=1, cutoff=0.88)
    return keys[m[0]] if m else None

def google_url(q):
    return "https://www.google.com/search?q=" + urllib.parse.quote_plus(q)

def open_url(url):
    shell_run([BROWSER_CMD, "--new-tab", url])

def parse_search(t):
    """Returns (url, label) for 'search ...' phrases, or None."""
    s = t.strip().rstrip(".!?")
    m = re.match(r"^(?:search|look up|find|google)\s+(?:for\s+)?(.+?)\s+(?:on|in|at)\s+(.+)$", s, re.I)
    if m and site_match(m.group(2)):
        site, q = site_match(m.group(2)), m.group(1).strip()
        return SITES[site][1].format(q=urllib.parse.quote_plus(q)), q
    m = re.match(r"^(?:search|look up|find)\s+(.+?)\s+for\s+(.+)$", s, re.I)
    if m and site_match(m.group(1)):
        site, q = site_match(m.group(1)), m.group(2).strip()
        return SITES[site][1].format(q=urllib.parse.quote_plus(q)), q
    m = re.match(r"^(?:search(?:\s+for)?|look up|google)\s+(.+)$", s, re.I)
    if m:
        q = m.group(1).strip()
        dom = find_domain(q)
        if dom and len(q.split()) <= 3:
            return "https://" + dom, dom
        site = site_match(q)
        if site:
            return SITES[site][0], site
        return google_url(q), q
    return None

# ---------------- sound + timers ----------------
timers = []
timer_lock = threading.Lock()
alarm_active = threading.Event()
alarm_stop = threading.Event()

def play_tones(seq):
    """seq = [(frequency_hz, seconds), ...]; frequency 0 = silence"""
    sr = 22050
    parts = []
    for freq, dur in seq:
        n = int(sr * dur)
        if freq <= 0:
            parts.append(np.zeros(n, dtype=np.float32))
            continue
        w = 0.35 * np.sin(2 * np.pi * freq * np.arange(n) / sr)
        k = min(n // 8, 400)
        if k > 0:
            ramp = np.linspace(0, 1, k)
            w[:k] *= ramp
            w[-k:] *= ramp[::-1]
        parts.append(w.astype(np.float32))
    try:
        sd.play(np.concatenate(parts), sr, device=SOUND_DEVICE)
    except Exception as err:
        print("Couldn't play sound:", err)

def stop_alarm():
    alarm_stop.set()
    try:
        sd.stop()
    except Exception:
        pass
    if alarm_active.is_set():
        state["toast"] = None
    alarm_active.clear()

def alarm(label):
    alarm_stop.clear()
    alarm_active.set()
    show_toast("TIMER DONE - " + label, "err", 14.0)
    for _ in range(5):
        if alarm_stop.is_set():
            break
        play_tones([(880, 0.15), (0, 0.08), (880, 0.15), (0, 0.08), (1175, 0.30)])
        if alarm_stop.wait(2.2):
            break
    alarm_active.clear()

def timer_loop():
    while True:
        time.sleep(0.5)
        now = time.monotonic()
        due = []
        with timer_lock:
            for t in timers[:]:
                if now >= t["end"]:
                    timers.remove(t)
                    due.append(t)
        for t in due:
            threading.Thread(target=alarm, args=(t["label"],), daemon=True).start()

def add_timer(secs):
    label = fmt_duration(secs)
    with timer_lock:
        timers.append({"end": time.monotonic() + secs, "label": label})
    return label

def cancel_timers():
    with timer_lock:
        n = len(timers)
        timers.clear()
    was_ringing = alarm_active.is_set()
    stop_alarm()
    return n or (1 if was_ringing else 0)

def timer_status():
    with timer_lock:
        if not timers:
            return "no timers"
        soonest = min(timers, key=lambda x: x["end"])
        total = len(timers)
    left = max(0, int(soonest["end"] - time.monotonic()))
    h, rem = divmod(left, 3600)
    m, s = divmod(rem, 60)
    txt = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
    return f"{txt} left" + (f" (+{total - 1} more)" if total > 1 else "")

# ---------------- typing ----------------
def type_text(text, gen=None):
    text = (text.replace("\u2019", "'").replace("\u2018", "'")
                .replace("\u201c", '"').replace("\u201d", '"')
                .replace("\u2013", "-").replace("\u2014", "-").replace("\u2026", "..."))
    for ch in text:
        if gen is not None and state["gen"] != gen:      # cancelled
            return
        if ch in BASE:
            k, shift = BASE[ch], False
        elif ch.isalpha() and ch.lower() in BASE:
            k, shift = BASE[ch.lower()], True
        elif ch in SHIFT:
            k, shift = SHIFT[ch], True
        else:
            continue                                     # a character the keyboard can't type
        if shift:
            ui.write(e.EV_KEY, SHFT, 1)
            ui.syn()
        tap(k)
        if shift:
            ui.write(e.EV_KEY, SHFT, 0)
            ui.syn()
        time.sleep(0.004)

# ---------------- mode key: tap = mode, long press = model ----------------
press = {"timer": None, "long": False}

def tap_mode():
    i = MODE_ORDER.index(state["mode"])
    state["mode"] = MODE_ORDER[(i + 1) % len(MODE_ORDER)]
    pending["kind"] = None                   # a yes/no question belongs to command mode only
    announce()

def long_press_action():
    press["long"] = True
    i = MODELS.index(state["model"])
    set_model(MODELS[(i + 1) % len(MODELS)])

def mode_key_down():
    old = press["timer"]
    if old:
        old.cancel()                         # a second keyboard sending the same press
    press["long"] = False
    t = threading.Timer(LONG_PRESS, long_press_action)
    t.daemon = True
    press["timer"] = t
    t.start()

def mode_key_up():
    t = press["timer"]
    if t:
        t.cancel()
    press["timer"] = None
    if not press["long"]:
        tap_mode()

# ---------------- running things ----------------
def shell_run(cmd):
    """cmd can be a shell string or a list of arguments. Programs are detached,
    so cancelling or restarting this script never closes them."""
    env = {k: v for k, v in os.environ.items() if k != "GDK_BACKEND"}
    try:
        subprocess.Popen(cmd, shell=isinstance(cmd, str), cwd=os.path.expanduser("~"), env=env,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except Exception as err:
        print("Couldn't run:", cmd, err)

def shell_output(cmd):
    env = {k: v for k, v in os.environ.items() if k != "GDK_BACKEND"}
    try:
        out = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                             timeout=3, env=env).stdout.strip()
        return out.split("\n")[0] if out else ""
    except Exception:
        return ""

def launch_app(app):
    cmd = re.sub(r"@@\w*|%[a-zA-Z]", "", app["exec"]).strip()
    shell_run(f"{TERMINAL_CMD} {cmd}" if app.get("terminal") else cmd)

# ---------------- closing one specific app ----------------
# "close firefox" / "quit terminal" / "close minecraft" / "force quit firefox" / "close firefox and terminal"
NAME_SPLIT_RE = re.compile(r"\s*,\s*(?:and\s+)?|\s+and\s+|\s+plus\s+", re.I)
CLOSE_RE = re.compile(r"^(force\s+(?:quit|close|kill)|quit|close|exit|kill|terminate)\s+(?:the\s+|my\s+)?(.+)$", re.I)
CLOSE_GENERIC = {"tab", "tabs", "page", "pages", "window", "windows", "app", "apps", "program", "programs",
                 "application", "applications", "note", "notes", "help", "timer", "stopwatch", "popup", "panel",
                 "this", "that", "it", "everything", "all", "both", "these", "those", "other", "others", "current"}
CLOSE_PROTECTED = {"systemd", "init", "labwc", "wayfire", "sway", "hyprland", "xorg", "xwayland", "pipewire",
                   "wireplumber", "pulseaudio", "dbus-daemon", "dbus-broker", "networkmanager", "sshd", "keyd",
                   "login", "agetty", "bash", "sh", "zsh", "fish", "python", "python3", "wf-panel-pi", "lxpanel",
                   "polkit-gnome-au", "gnome-keyring-d"}
BROWSER_PROCS = {"firefox", "firefox-esr", "chromium", "chromium-browser", "google-chrome", "chrome"}
CLOSE_SPECIAL = {   # the Minecraft *game* is a java process, not the launcher
    "minecraft": {"label": "Minecraft", "exes": {"java"},
                  "cmd_re": re.compile(r"minecraft|knotclient|quiltloader|net\.fabricmc|cpw\.mods|forge", re.I)},
    "minecraft game": None,
}
CLOSE_SPECIAL["minecraft game"] = CLOSE_SPECIAL["minecraft"]

def parse_close(t):
    """'force quit firefox and terminal' -> (True, ['firefox', 'terminal']); None if it isn't about apps
    ('close two tabs', 'close the window', 'close this' ... stay with the normal commands)."""
    m = CLOSE_RE.match(t.strip(" .!?"))
    if not m:
        return None
    verb = m.group(1).lower()
    force = verb in ("kill", "terminate") or verb.startswith("force")
    names = []
    for part in NAME_SPLIT_RE.split(m.group(2)):
        name = re.sub(r"^(?:the|my)\s+", "", clean_phrase(part))
        name = re.sub(r"\s+(?:app|application|program|window)s?$", "", name).strip()     # "firefox app" -> "firefox"
        toks = name.split()
        if not toks or toks[0].isdigit() or toks[0] in NUM_WORDS or any(w in CLOSE_GENERIC for w in toks):
            return None
        names.append(name)
    return (force, names) if names else None

def exec_process_name(cmd):
    """Which process does a desktop entry's Exec line start?  -> ('flatpak', appid) or ('exe', 'name') or None"""
    clean = re.sub(r"@@\w*|%[a-zA-Z]", "", cmd).strip()
    try:
        parts = shlex.split(clean)
    except ValueError:
        parts = clean.split()
    while parts and (parts[0] == "env" or re.match(r"^\w+=", parts[0])):
        parts.pop(0)
    if not parts:
        return None
    exe = os.path.basename(parts[0]).lower()
    if exe == "flatpak" and "run" in parts:
        rest = [p for p in parts[parts.index("run") + 1:] if not p.startswith("-")]
        return ("flatpak", rest[0]) if rest else None
    if exe in ("sh", "bash", "zsh", "python", "python3", "env", "sudo"):
        return None
    return ("exe", exe)

def resolve_close(name):
    """Turns a spoken name into what to look for.  -> (label, spec, known)
    known = we are sure it is an app name (so 'it isn't running' is a useful answer)."""
    if name in CLOSE_SPECIAL:
        sp = CLOSE_SPECIAL[name]
        return sp["label"], {"names": set(), "exes": sp["exes"], "cmd_re": sp["cmd_re"], "flatpak": None}, True
    if name in BROWSER_WORDS or name == "browser":
        names = set(BROWSER_PROCS) | {os.path.basename(str(BROWSER_CMD).split()[0]).lower()}
        return name, {"names": names, "exes": None, "cmd_re": None, "flatpak": None}, True      # say what you said
    app = find_app(name)
    if not app:
        build_app_index()                              # maybe you just installed it
        app = find_app(name)
    if app:
        names = {app["name"].lower().replace(" ", "-"), app["name"].lower().replace(" ", "")}
        flat = None
        proc = exec_process_name(app["exec"])
        if proc and proc[0] == "flatpak":
            flat = proc[1]
        elif proc:
            names.add(proc[1])
        return app["name"], {"names": names, "exes": None, "cmd_re": None, "flatpak": flat}, True
    names = {name, name.replace(" ", "-"), name.replace(" ", "")}
    return name, {"names": names, "exes": None, "cmd_re": None, "flatpak": None}, False

def ancestor_pids():
    """This script and whatever started it (a terminal, say) - these are never closed."""
    pids, pid = {os.getpid()}, os.getpid()
    for _ in range(64):
        try:
            with open(f"/proc/{pid}/stat") as f:
                pid = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
        if pid <= 1:
            break
        pids.add(pid)
    return pids

def find_close_pids(spec):
    """-> (pids to close, True if a match was skipped because it is what this script runs inside)"""
    mine, me_uid = ancestor_pids(), os.getuid()
    names = {n.lower() for n in spec["names"]}
    found, skipped_self = [], False
    try:
        entries = os.listdir("/proc")
    except OSError:
        return [], False
    for d in entries:
        if not d.isdigit():
            continue
        try:
            if os.stat(f"/proc/{d}").st_uid != me_uid:
                continue
            with open(f"/proc/{d}/comm") as f:
                comm = f.read().strip().lower()
            with open(f"/proc/{d}/cmdline", "rb") as f:
                args = [a.decode("utf-8", "ignore") for a in f.read().split(b"\0") if a]
        except OSError:
            continue
        exe = os.path.basename(args[0]).lower() if args else comm
        if comm in CLOSE_PROTECTED or exe in CLOSE_PROTECTED or "--desktop" in args:
            continue
        cmdline = " ".join(args)
        if spec["cmd_re"] is not None:
            hit = (spec["exes"] and exe in spec["exes"]) and spec["cmd_re"].search(cmdline) and "nogui" not in args
        else:
            hit = any(comm == n or comm == n[:15] or exe == n or exe.startswith(n + ".") for n in names)
        if not hit:
            continue
        try:
            with open(f"/proc/{d}/stat") as f:
                if f.read().rsplit(")", 1)[1].split()[0] == "Z":       # already finished, just not tidied up yet
                    continue
        except (OSError, IndexError):
            continue
        if int(d) in mine:
            skipped_self = True
            continue
        found.append(int(d))
    return found, skipped_self

def close_app(label, spec, force):
    """-> 'closed' / 'none' / 'self'.  Normal close asks nicely (SIGTERM); force quit does not (SIGKILL)."""
    sig = signal.SIGKILL if force else signal.SIGTERM
    if spec["flatpak"]:
        try:
            r = subprocess.run(["flatpak", "kill", spec["flatpak"]], capture_output=True, timeout=5)
            if r.returncode == 0:
                return "closed"
        except Exception:
            pass
    pids, skipped_self = find_close_pids(spec)
    done = 0
    for pid in pids:
        try:
            os.kill(pid, sig)
            done += 1
        except OSError:
            pass
    if done:
        return "closed"
    return "self" if skipped_self else "none"

def watch_closing(label, spec):
    """If an app ignores a normal close, say so and offer 'force quit'."""
    deadline = time.monotonic() + CLOSE_WAIT_SECS
    while time.monotonic() < deadline:
        time.sleep(0.5)
        if not find_close_pids(spec)[0]:
            return
    show_toast(f"{label} is still open. Say force quit {label}", "err", 5.0)

def handle_close_app(t, gen):
    parsed = parse_close(t)
    if not parsed:
        return False
    force, names = parsed
    results = []
    for name in names:
        label, spec, known = resolve_close(name)
        if state["gen"] != gen:
            return True
        r = close_app(label, spec, force)
        if r == "none" and not known:
            if len(names) == 1:
                return False                           # not a real app name: let the normal commands try
            continue
        results.append((label, spec, r))
    if not results:
        return False
    closed = [lb for lb, _, r in results if r == "closed"]
    selfs = [lb for lb, _, r in results if r == "self"]
    none = [lb for lb, _, r in results if r == "none"]
    parts = []
    if closed:
        parts.append(("force closed " if force else "closed ") + ", ".join(closed))
    if selfs:
        parts.append("can't close " + ", ".join(selfs) + " (this script runs inside it)")
    if none:
        parts.append(", ".join(none) + (" isn't running" if len(none) == 1 else " aren't running"))
    show_toast("; ".join(parts), "command" if closed else "err", 2.5 if closed else 3.0)
    if closed and not force and CLOSE_WAIT_SECS > 0:
        for lb, spec, r in results:
            if r == "closed":
                threading.Thread(target=watch_closing, args=(lb, spec), daemon=True).start()
    return True

def perform(kind, payload, count, gen):
    """Does one action `count` times. Stops early if you cancel."""
    delay = REPEAT_DELAY.get(kind, 0.1)
    for i in range(count):
        if state["gen"] != gen:
            return
        if kind == "run":
            shell_run(payload)
        elif kind == "keys":
            combo(payload)
        elif kind == "click":
            mouse_click(payload[0], payload[1])
        elif kind == "down":
            mouse_button(payload, 1)
        elif kind == "up":
            mouse_button(payload, 0)
        elif kind == "wheel":
            mouse_wheel(payload)
        elif kind == "move":
            mouse_move(payload[0], payload[1])
        elif kind == "corner":
            mouse_move(payload[0] * 6000, payload[1] * 6000, scale=False)
        if i < count - 1:
            time.sleep(delay)

def is_sure(score, conf):
    """Sure = what it heard matches the command closely AND Whisper itself was confident."""
    return score >= CONFIRM_SURE_SCORE and (conf is None or conf >= CONFIRM_MIN_LOGPROB)

def needs_confirm(phrase, sure):
    dangerous = ACTIONS[phrase][0] == "confirm" or phrase in CONFIRM_COMMANDS or phrase in custom_dangerous
    if not dangerous or CONFIRM_MODE == "never":
        return False
    return CONFIRM_MODE == "always" or not sure

def exec_action(phrase, count, gen, sure=True, confirmed=False):
    kind, payload = ACTIONS[phrase]
    if not confirmed and needs_confirm(phrase, sure):      # "Shut down? Say yes or no"
        pending.update(kind="confirm", phrase=phrase, count=count or 1, until=time.monotonic() + 15)
        show_toast(f"{phrase.capitalize()}? Say yes or no", "err", 15.0)
        return
    if kind in REPEATABLE:
        n = max(1, count or 1)
        if n > MAX_REPEAT:
            show_toast(f"max {MAX_REPEAT} times", "err")
            return
        show_toast(phrase if n == 1 else f"{phrase} x{n}", "command")
        last_cmd.update(kind=kind, payload=payload, count=n, label=phrase)
        perform(kind, payload, n, gen)
    elif kind in ("down", "up", "corner"):
        show_toast(phrase, "command")
        last_cmd.update(kind=kind, payload=payload, count=1, label=phrase)
        perform(kind, payload, 1, gen)
    elif kind == "info":
        last_cmd.update(kind=kind, payload=payload, count=1, label=phrase)
        show_toast(shell_output(payload)[:200] or "no info", "command", 3.5)
    elif kind == "mode":
        state["mode"] = payload
        pending["kind"] = None
        announce()
    elif kind == "model":
        set_model(payload)
    elif kind == "confirm":                 # shut down / restart (it was sure, or you said yes)
        show_toast(phrase.capitalize() + "...", "command", 3.0)
        shell_run(payload)

# ---------------- yes / no answers ----------------
YES_WORDS = ["yes", "yeah", "yep", "yup", "sure", "confirm", "do it", "go ahead", "okay", "ok",
             "affirmative", "yes please", "please do", "yes do it"]
NO_WORDS = ["no", "nope", "nah", "cancel", "never mind", "nevermind", "stop", "dont", "don t",
            "negative", "no thanks"]

def answer_pending(text, gen):
    """If a yes/no question is waiting, handle the answer. Returns True if the text was an answer."""
    if not pending["kind"]:
        return False
    if time.monotonic() > pending["until"]:
        pending["kind"] = None
        return False
    h = clean_phrase(text)
    if pending["kind"] == "note":                # you said "make a note" and are now saying the note itself
        pending["kind"] = None
        if h in ("cancel", "never mind", "nevermind", "stop", "no", "forget it"):
            show_toast("OK, cancelled", "command")
        elif h:
            save_note(text, gen)
        return True
    short = len(h.split()) <= 2
    yes = h in YES_WORDS or (short and bool(difflib.get_close_matches(h, YES_WORDS, n=1, cutoff=0.8)))
    no = h in NO_WORDS or (short and bool(difflib.get_close_matches(h, NO_WORDS, n=1, cutoff=0.8)))
    kind = pending["kind"]
    if yes and not no:
        pending["kind"] = None
        if state["gen"] != gen:
            return True
        if kind in ("confirm", "suggest"):
            exec_action(pending["phrase"], pending["count"], gen, confirmed=True)    # you said yes: no more asking
        return True
    if no:
        pending["kind"] = None
        show_toast("ok, cancelled", "command")
        return True
    pending["kind"] = None                  # you said something else: forget the question
    return False

# ---------------- notes ----------------
# notes.txt holds one note per line:  2026-10-25 14:32  Buy batteries
# You can also edit the file by hand; a line without a date is still shown as a note.
notes_lock = threading.Lock()
notes_view = {"page": 0}
NOTE_LINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s{2}(.+)$")
NOTE_ADD_RES = [
    re.compile(r"^(?:make|take|add|write|create|save)\s+(?:a\s+|an\s+|new\s+)*(?:note|node)\b[\s:,.-]*"
               r"(?:(?:that|to|saying|says)\b[\s:,.-]*)?(.*)$", re.I),
    re.compile(r"^(?:jot|write)\s+(?:this\s+|that\s+|it\s+)?down\b[\s:,.-]*(.*)$", re.I),
    re.compile(r"^note\b[\s:,.-]+(?:(?:that|to)\b[\s:,.-]*)?(.+)$", re.I),
]
NOTES_SHOW_RE = re.compile(r"^(?:(?:show|view|see|read|list|display|open|check|what are|what s|whats)\s+)?"
                           r"(?:me\s+|my\s+|all\s+|the\s+|of\s+)*notes$")
NOTES_OLDER_RE = re.compile(r"^(?:show\s+|go to\s+)?(?:more|older|earlier)\s+notes$")
NOTES_NEWER_RE = re.compile(r"^(?:show\s+|go to\s+|back to\s+)?(?:newer|newest|latest|recent)\s+notes$")
NOTES_HIDE_RE = re.compile(r"^(?:close|hide|dismiss|clear)\s+(?:the\s+|my\s+)*notes?$")

def load_notes():
    """-> [(date text or None, note text), ...], oldest first"""
    out = []
    try:
        with open(NOTES_FILE, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line:
                    m = NOTE_LINE_RE.match(line)
                    out.append((m.group(1), m.group(2)) if m else (None, line))
    except FileNotFoundError:
        pass
    except OSError as err:
        print("Couldn't read the notes file:", err)
    return out

def add_note(text):
    """Appends one note to the file and returns the text as saved (one line, starts with a capital)."""
    text = " ".join(text.split())
    if text[:1].islower():
        text = text[0].upper() + text[1:]
    line = f"{time.strftime('%Y-%m-%d %H:%M')}  {text}\n"
    with notes_lock:
        lead = ""
        try:                                     # a hand-edited file might not end with a newline
            with open(NOTES_FILE, "rb") as f:
                f.seek(0, os.SEEK_END)
                if f.tell() > 0:
                    f.seek(-1, os.SEEK_END)
                    lead = "" if f.read(1) == b"\n" else "\n"
        except FileNotFoundError:
            pass
        with open(NOTES_FILE, "a", encoding="utf-8") as f:
            f.write(lead + line)
    return text

def save_note(text, gen):
    text = text.strip()
    if STRIP_TRAILING_PERIOD and text.endswith("."):
        text = text[:-1].rstrip()
    if not text or state["gen"] != gen:
        return
    try:
        saved = add_note(text)
    except OSError as err:
        print("Couldn't save the note:", err)
        show_toast("Couldn't save the note", "err", 3.0)
        return
    print(f"Note saved to {NOTES_FILE}: {saved}")
    show_toast("Saved: " + saved, "command", 2.5)

def fmt_stamp(stamp):
    try:
        return time.strftime("%b %-d, %-I:%M %p", time.strptime(stamp, "%Y-%m-%d %H:%M"))
    except ValueError:
        return stamp

def note_block(n, stamp, text):
    """One note as screen lines: numbered, wrapped to fit the panel, optional date underneath."""
    lines = textwrap.wrap(f"{n}. {text}", width=42, subsequent_indent="    ") or [f"{n}."]
    if NOTES_SHOW_DATES and stamp:
        lines.append("    " + fmt_stamp(stamp))
    return lines[:PANEL_MAX]

def note_pages(notes, capacity):
    """Packs notes, newest first, into pages of at most `capacity` screen lines. -> [[(index, lines), ...], ...]"""
    pages, cur, used = [], [], 0
    for i in range(len(notes) - 1, -1, -1):
        block = note_block(i + 1, *notes[i])
        if cur and used + len(block) > capacity:
            pages.append(cur)
            cur, used = [], 0
        cur.append((i, block))
        used += len(block)
    if cur:
        pages.append(cur)
    return pages

def show_notes(page=0):
    """Shows one page of notes on the screen panel (page 0 = the newest). False if that page doesn't exist."""
    notes = load_notes()
    if not notes:
        show_toast("No notes yet", "err")
        return True
    pages = note_pages(notes, PANEL_MAX)
    many = len(pages) > 1
    if many:
        pages = note_pages(notes, PANEL_MAX - 1)       # leave one line for the "older / newer" hint
    if page < 0 or page >= len(pages):
        return False
    notes_view["page"] = page
    lines = [ln for _, block in pages[page] for ln in block]
    if many:
        hints = (["older notes"] if page < len(pages) - 1 else []) + (["newer notes"] if page > 0 else [])
        lines.append("Say: " + " / ".join(hints))
        title = f"NOTES {pages[page][-1][0] + 1}-{pages[page][0][0] + 1} OF {len(notes)}"
    else:
        title = f"NOTES ({len(notes)})"
    show_panel(title, lines, "command", 20.0)
    return True

def handle_notes(t, heard, gen):
    for rx in NOTE_ADD_RES:
        m = rx.match(t)
        if m:
            text = m.group(1).strip()
            if text:
                save_note(text, gen)
            else:                               # just "make a note": the next thing you say is the note
                pending.update(kind="note", phrase="", count=1, until=time.monotonic() + 15)
                show_toast("Say your note...", "command", 15.0)
            return True
    if NOTES_SHOW_RE.match(heard):
        show_notes(0)
    elif NOTES_OLDER_RE.match(heard):
        if not show_notes(notes_view["page"] + 1):
            show_toast("No older notes", "err")
    elif NOTES_NEWER_RE.match(heard):
        if not show_notes(notes_view["page"] - 1):
            show_toast("No newer notes", "err")
    elif NOTES_HIDE_RE.match(heard):
        state["panel"] = None
    else:
        return False
    return True

# ---------------- COMMAND mode: each kind of thing you can say ----------------
def handle_timer(heard):
    if re.match(r"^(?:test sound|play a sound|beep)$", heard):
        play_tones([(660, 0.15), (0, 0.05), (880, 0.2)])
        show_toast("test sound", "command")
        return True
    if re.match(r"^(?:cancel|stop|clear|delete)\s+(?:all\s+|the\s+|my\s+)*(?:timers?|alarms?)$", heard):
        n = cancel_timers()
        show_toast("timers cancelled" if n else "no timers", "command" if n else "err")
        return True
    if re.match(r"^(?:how much time(?: is)? left|time left|timer status|how long(?: is)? left)$", heard):
        show_toast(timer_status(), "command", 3.0)
        return True
    m = re.match(r"^(?:set\s+)?(?:an?\s+)?(?:timer|alarm)\s+(?:for\s+)?(.+)$", heard)
    if m:
        secs = parse_duration(m.group(1))
        if secs:
            show_toast("timer: " + add_timer(secs), "command", 2.5)
        else:
            show_toast("couldn't read the time", "err", 2.5)
        return True
    m = re.match(r"^(?:set\s+)?(?:an?\s+)?(.+?)\s+(?:timer|alarm)$", heard)
    if m:
        secs = parse_duration(m.group(1))
        if secs:
            show_toast("timer: " + add_timer(secs), "command", 2.5)
            return True
    return False

def handle_stopwatch(heard):
    # "show times" -> list of every stop and lap
    if re.match(r"^(?:show|list|display|view|see|check|what are)\s+(?:me\s+|my\s+|the\s+|all\s+)*"
                r"(?:stopwatch\s+)?(?:times|laps|lap times|results|history)$", heard):
        if not sw["history"]:
            show_toast("no times yet", "err")
        else:
            lines = [f"{i}. {h['kind'].capitalize()}   {fmt_sw(h['t'])}" for i, h in enumerate(sw["history"], 1)]
            show_panel("STOPWATCH TIMES", lines[-PANEL_MAX:], "command", 12.0)
        return True
    if re.match(r"^(?:clear|delete|erase|reset)\s+(?:my\s+|the\s+|all\s+)*(?:stopwatch\s+)?"
                r"(?:times|laps|lap times|results|history)$", heard):
        sw["history"].clear()
        sw["laps"] = []
        show_toast("times cleared", "command")
        return True
    if not re.search(r"\bstopwatch\b|^(?:lap|split|mark lap|take a lap)$", heard):
        return False

    if re.match(r"^(?:start|begin|resume|run)\s+(?:the\s+)?stopwatch$", heard) or \
            (heard == "stopwatch" and not sw["start"] and sw["base"] == 0):
        if sw["start"]:
            show_toast("already running", "err")
        else:
            sw["start"] = time.monotonic()
            sw["shown_until"] = 0.0
            show_toast("stopwatch started", "command")
    elif re.match(r"^(?:stop|pause|freeze|end)\s+(?:the\s+)?stopwatch$", heard):
        if not stop_stopwatch():
            show_toast("not running", "err")
    elif re.match(r"^(?:reset|clear|restart|zero)\s+(?:the\s+)?stopwatch$", heard):
        sw.update(start=None, base=0.0, laps=[], shown_until=0.0)           # the saved list stays
        show_toast("stopwatch reset", "command")
    elif heard in ("lap", "split", "mark lap", "take a lap") or re.match(r"^stopwatch (?:lap|split)$", heard):
        if sw["start"]:
            t = sw_elapsed()
            sw["laps"].append(t)
            sw["history"].append({"kind": "lap", "t": t})
            show_toast(f"lap {len(sw['laps'])}: {fmt_sw(t)}", "command", 3.5)
        else:
            show_toast("stopwatch not running", "err")
    else:                                   # "stopwatch time", "check stopwatch"
        if sw["start"]:
            show_toast("running " + fmt_sw(sw_elapsed()), "command", 3.0)
        elif sw["base"] > 0:
            show_toast("paused " + fmt_sw(sw["base"]), "command", 3.0)
        else:
            show_toast("stopwatch not started", "err")
    return True

def handle_words(t):
    m = re.match(r"^(?:learn|remember|add)\s+(?:the\s+)?(?:word|phrase|name)\s+(?:spelled\b[\s:,-]*)?(.+?)[\s.!?,]*$",
                 t, re.I)
    if m:
        w = spell_join(m.group(1))
        add_vocab(w)
        show_toast("learned: " + w, "command", 2.5)
        return True
    m = re.match(r"^forget\s+(?:the\s+)?(?:word\s+)?(.+?)[\s.!?,]*$", t, re.I)
    if m:
        ok = forget_word(m.group(1).strip()) > 0
        show_toast("forgot " + m.group(1).strip() if ok else "not in my words", "command" if ok else "err")
        return True
    if re.match(r"^(?:how many words|list (?:my )?words|show (?:my )?words)[\s.!?]*$", t, re.I):
        show_toast(f"{len(words['vocab'])} learned words", "command", 3.0)
        return True
    return False

def handle_reload(heard):
    m = re.match(r"^(?:reload|refresh|rescan)\s+(?:my\s+)?(words|commands|apps|applications|everything)$", heard)
    if not m:
        return False
    what = m.group(1)
    if what in ("words", "everything"):
        load_words()
        rebuild_mc_index()
    if what in ("commands", "everything"):
        load_custom_commands()
    if what in ("apps", "applications", "everything"):
        build_app_index()
    show_toast("reloaded " + what, "command")
    return True

HELP_PATTERNS = [
    r"^help\b\s*(.*)$",
    r"^(?:show|list|display|see)\s+(?:me\s+)?(.+?)\s+commands$",
    r"^(?:show|list|display|see|what are)\s+(?:me\s+|all\s+|the\s+|my\s+|available\s+)*(?:voice\s+)?commands\s*(.*)$",
    r"^what (?:can|could) i (?:say|do)\s*(.*)$",
    r"^what can you do\s*(.*)$",
    r"^(?:i need help|instructions|how do i use this)\s*(.*)$",
]

def handle_help(heard):
    m = None
    for pat in HELP_PATTERNS:
        m = re.match(pat, heard)
        if m:
            break
    if not m:
        m2 = re.match(r"^how (?:do|can|would) i (.+)$", heard)        # "how do I close a tab"
        if m2 and find_help_topic(m2.group(1)):
            m = m2
        else:
            return False
    rest = m.group(1).strip()
    topic = find_help_topic(rest) if rest else None
    if topic:
        show_panel(topic[0], topic[1], "command", 14.0)
    else:
        show_panel("COMMAND HELP", HELP_OVERVIEW, "command", 14.0)
    return True

def handle_again(heard, gen):
    if not re.match(r"^(?:do (?:that|it) again|repeat(?: that| it)?|again|same again|one more time)\b", heard):
        return False
    if not last_cmd["kind"]:
        show_toast("nothing to repeat", "err")
        return True
    count, _ = split_count(heard)
    n = max(1, count or last_cmd["count"])
    if n > MAX_REPEAT:
        show_toast(f"max {MAX_REPEAT} times", "err")
        return True
    kind, payload, label = last_cmd["kind"], last_cmd["payload"], last_cmd["label"]
    if kind == "info":
        show_toast(shell_output(payload)[:200] or "no info", "command", 3.5)
        return True
    show_toast("again: " + label, "command")
    perform(kind, payload, n if kind in REPEATABLE else 1, gen)
    return True

def handle_press_type(t, heard, gen):
    m = re.match(r"^type\s+(.+)$", t, re.I)
    if m:
        text = m.group(1).strip()
        type_text(text[:-1] if text.endswith(".") else text, gen)
        show_toast("typed", "command")
        return True
    m = re.match(r"^(?:press|hit|push)\s+(.+)$", heard)
    if m:
        rest, n = m.group(1), 1
        c = re.match(r"^(.*?)\s+(?:(\w+)\s+times?|(twice|thrice))$", rest)
        if c:
            rest = c.group(1)
            word = c.group(2) or c.group(3)
            n = int(word) if word.isdigit() else NUM_WORDS.get(word, 1)
        keys = parse_keys(rest)
        if not keys:
            return False
        n = max(1, min(n, MAX_REPEAT))
        label = "press " + rest + (f" x{n}" if n > 1 else "")
        show_toast(label, "command")
        last_cmd.update(kind="keys", payload=keys, count=n, label=label)
        perform("keys", keys, n, gen)
        return True
    return False

def handle_levels(heard):
    m = re.match(r"^(?:set\s+)?(?:the\s+)?(volume|brightness)\s+(?:to\s+)?(.+?)(?:\s+percent)?$", heard)
    if not m:
        return False
    n = to_number(m.group(2))
    if n is None:
        return False
    n = max(0, min(100, n))
    if m.group(1) == "volume":
        shell_run(f"wpctl set-volume @DEFAULT_AUDIO_SINK@ {n}%")
    else:
        shell_run(f"brightnessctl set {max(n, 1)}%")
    show_toast(f"{m.group(1)} {n}%", "command")
    return True

OPEN_VERBS = (r"open|launch|go to|visit|browse to|load|start|run|fire up|boot up|bring up|pull up|"
              r"start up|execute|switch to")

MULTI_OPEN_PAUSE = 1.0        # between the things in "open firefox and terminal" (lets a browser start before a 2nd page)

def app_key_exact(query):
    """True if the whole phrase is exactly one installed app's name (so 'and' is part of its name)."""
    qn = re.sub(r"[^a-z0-9]", "", APP_ALIASES.get(query, query))
    return bool(qn) and any(re.sub(r"[^a-z0-9]", "", k) == qn for a in list(app_index) for k in a["keys"])

def resolve_open(what):
    """What does one spoken name open?  -> (label, kind, run) or None.  kind is 'browser', 'web' or 'app'."""
    whatn = clean_phrase(what)
    if whatn in BROWSER_WORDS:
        return "browser", "browser", lambda: shell_run(BROWSER_CMD)
    dom = find_domain(what)
    if dom:
        return dom, "web", lambda: open_url("https://" + dom)
    app = find_app(whatn)
    if not app:
        build_app_index()                      # maybe you just installed it
        app = find_app(whatn)
    if app:
        return app["name"], "app", lambda: launch_app(app)
    site = site_match(whatn)
    if site:
        return site, "web", lambda: open_url(SITES[site][0])
    return None

def open_several(parts, gen):
    """'open firefox and terminal': every name is looked up on its own. Returns the kind, or None to let the
    normal single-name matching have a go."""
    found, missing = [], []
    for p in parts:
        p = re.sub(r"^\s*(?:the|my|up)\s+", "", p, flags=re.I)
        r = resolve_open(p)
        if r is None:
            missing.append(clean_phrase(p))
        elif r[0] not in [f[0] for f in found]:
            found.append(r)
    if not found:
        return None
    if any(f[1] == "web" for f in found):
        found = [f for f in found if f[1] != "browser"]      # a website opens the browser by itself
    for i, (label, kind, run) in enumerate(found):
        if gen is not None and state["gen"] != gen:
            return "other"
        run()
        if i + 1 < len(found):
            end = time.monotonic() + MULTI_OPEN_PAUSE
            while time.monotonic() < end:
                if gen is not None and state["gen"] != gen:
                    return "other"
                time.sleep(0.05)
    msg = "open " + ", ".join(f[0] for f in found)
    if missing:
        msg += "; can't find " + ", ".join(missing)
    show_toast(msg, "err" if missing else "command", 3.0 if missing else 2.0)
    return "app" if any(f[1] in ("app", "browser") for f in found) else "web"

def handle_open_search(t, heard, gen=None):
    """Web searches, websites, and any installed app. Returns 'web' / 'app' / 'browser' or None."""
    q = parse_search(t)
    if q:
        open_url(q[0])
        show_toast("search: " + q[1], "command", 2.5)
        return "web"
    m = re.match(r"^(?:" + OPEN_VERBS + r")\s+(?:the\s+|up\s+)?(.+)$", t.strip(" .!?"), re.I)
    if not m:
        return None
    what = m.group(1).strip()
    parts = [p for p in NAME_SPLIT_RE.split(what) if p.strip()]
    if len(parts) > 1 and not app_key_exact(clean_phrase(what)):
        kind = open_several(parts, gen)
        if kind:
            return kind
    r = resolve_open(what)
    if not r:
        return None
    label, kind, run = r
    run()
    show_toast("open " + label, "command")
    return kind

QUESTION_RE = re.compile(r"^(?:who|what|whats|when|where|why|how|which|whose|is|are|was|were|can|could|"
                         r"does|do|did|will|should|tell me)\b")

def run_segment(seg, gen, conf=None):
    t = strip_fillers(seg)
    heard = normalize_heard(t)
    if not heard:
        show_toast("didn't catch that", "err")
        return None
    if (handle_timer(heard) or handle_stopwatch(heard) or handle_notes(t, heard, gen)
            or handle_words(t) or handle_reload(heard)):
        return "other"
    if handle_help(heard) or handle_again(heard, gen) or handle_press_type(t, heard, gen) or handle_levels(heard):
        return "other"

    count, rest = split_count(heard)
    # An exact command wins over "open <app>" matching: "go to top" must not launch htop, and your own
    # commands.json phrases that start with "open" or "go to" now work.
    if rest in ACTIONS:
        if state["gen"] == gen:
            exec_action(rest, count, gen, sure=is_sure(1.0, conf))
        return "other"

    if handle_close_app(t, gen):
        return "other"

    kind = handle_open_search(t, heard, gen)
    if kind:
        return kind

    phrase, score = best_action(rest)
    if phrase:
        if state["gen"] == gen:
            exec_action(phrase, count, gen, sure=is_sure(score, conf))
        return "other"

    if AUTO_SEARCH_QUESTIONS and QUESTION_RE.match(heard) and len(heard.split()) >= 3:
        open_url(google_url(t.strip(" .!?")))
        show_toast("search: " + t, "command", 2.5)
        return "web"

    # not sure what was meant: offer the closest commands instead of just failing
    print("No command matched:", heard)
    sugg = suggest_actions(rest)
    if sugg and sugg[0][0] >= 0.55:
        pending.update(kind="suggest", phrase=sugg[0][1], count=count or 1, until=time.monotonic() + 12)
        show_toast(f"{sugg[0][1]}? Say yes", "err", 12.0)
        return "other"
    if sugg:
        show_panel("NOT SURE - TRY:", [p for _, p in sugg] + ["", "Say 'help' for ideas"], "err", 8.0)
        return None
    show_toast("no match. say help", "err", 2.5)
    return None

def is_browser_open(seg):
    return bool(re.match(r"^\W*(?:please\s+)?(?:open|launch|start|run)\s+(?:the\s+|up\s+)?"
                         r"(?:web\s+)?(?:browser|firefox|internet|web)\W*$", seg, re.I))

def is_web_segment(seg):
    s = strip_fillers(seg)
    if re.match(r"^(?:search|google|look up|go to|visit|browse to)\b", s, re.I) or find_domain(s):
        return True
    m = re.match(r"^(?:open|go to)\s+(.+)$", s, re.I)
    return bool(m and site_match(clean_phrase(m.group(1))))

def run_command(text, gen, conf=None):
    if answer_pending(text, gen):                # "yes" / "no" to a question it asked
        return
    segs = split_chain(text)
    if not segs:
        show_toast("didn't catch that", "err")
        return
    for i, seg in enumerate(segs):
        if state["gen"] != gen:
            return
        nxt = segs[i + 1] if i + 1 < len(segs) else None
        if nxt and is_browser_open(seg) and is_web_segment(nxt):
            continue                                       # the search opens the browser by itself
        kind = run_segment(seg, gen, conf)
        if nxt:
            end = time.monotonic() + (CHAIN_DELAY_AFTER_OPEN if kind in ("app", "browser") else CHAIN_DELAY)
            while time.monotonic() < end:
                if state["gen"] != gen:
                    return
                time.sleep(0.05)

# ---------------- MINECRAFT mode ----------------
def rebuild_mc_index():
    ids = mcdata.build_ids(w.lower() for w in words["vocab"])
    mc_nospace.clear()
    for i in ids:
        mc_nospace[i.replace("_", "")] = i
    mc_keys[:] = list(mc_nospace)

def mc_literal(tk):
    return bool(SPECIAL_RE.match(tk))

def mc_special(tk):
    return mc_literal(tk) or tk in mcdata.MC_KEYWORDS or tk in MC_COMMAND_SET

def match_id(span):
    """['diamond', 'pick', 'axe'] -> 'diamond_pickaxe'; plurals and small mishearings are fine."""
    joined = "".join(span)
    last = span[-1]
    cands = [joined]
    if last.endswith("s") and len(last) > 3:
        cands.append("".join(span[:-1]) + last[:-1])
    if last.endswith("ves"):
        cands.append("".join(span[:-1]) + last[:-3] + "f")
    for c in cands:
        if c in mc_nospace:
            return mc_nospace[c]
    if len(joined) >= 5:
        for c in cands:
            m = difflib.get_close_matches(c, mc_keys, n=1, cutoff=0.88)
            if m:
                return mc_nospace[m[0]]
    return None

def fix_keyword(tk):
    if not tk.isalpha() or len(tk) < 4 or mc_special(tk):
        return tk
    m = difflib.get_close_matches(tk, list(mcdata.MC_KEYWORDS), n=1, cutoff=0.85)
    return m[0] if m else tk

def mc_resolve(tokens, start):
    out, i = tokens[:start], start
    while i < len(tokens):
        tk = tokens[i]
        if mc_literal(tk):
            out.append(tk)
            i += 1
            continue
        hit = None
        for n in (4, 3, 2, 1):
            span = tokens[i:i + n]
            if len(span) < n or any(mc_literal(x) for x in span):
                continue
            if n == 1 and mc_special(span[0]):
                continue
            idm = match_id(span)
            if idm:
                hit = (idm, n)
                break
        if hit:
            out.append(hit[0])
            i += hit[1]
        else:
            out.append(fix_keyword(tk))
            i += 1
    return out

def words_to_digits(s):
    """'sixty four' -> '64', 'minus twenty' -> '-20'"""
    toks, out, i = s.split(), [], 0
    while i < len(toks):
        neg = (toks[i] in ("minus", "negative") and i + 1 < len(toks)
               and (toks[i + 1] in NUMW or toks[i + 1] in ("hundred", "thousand") or toks[i + 1].isdigit()))
        j = i + (1 if neg else 0)
        k = j
        while k < len(toks) and (toks[k] in NUMW or toks[k] in ("hundred", "thousand")):
            k += 1
        if k > j:
            out.append(("-" if neg else "") + str(to_number(" ".join(toks[j:k]))))
            i = k
        elif neg:
            out.append("-" + toks[j])
            i = j + 1
        else:
            out.append(toks[i])
            i += 1
    return " ".join(out)

def normalize_mc_command(body_raw):
    raw = body_raw.strip()
    low = re.sub(r"[,;!?]+", " ", raw.lower())
    low = re.sub(r"\.+(?=\s|$)", "", low)
    low = words_to_digits(low)
    low = re.sub(r"\btilde\s+(-?\d)", r"~\1", low)
    low = re.sub(r"\bcaret\s+(-?\d)", r"^\1", low)
    low = low.replace("tilde", "~").replace("caret", "^")
    low = re.sub(r"\bat\s+(?:s|self|me|myself)\b", "@s", low)
    low = re.sub(r"\bat\s+(?:e|all entities|entities|everything)\b", "@e", low)
    low = re.sub(r"\bat\s+(?:p|player|nearest player|nearest)\b", "@p", low)
    low = re.sub(r"\bat\s+(?:a|all players|all|everyone|everybody)\b", "@a", low)
    low = re.sub(r"\bat\s+(?:r|random)\b", "@r", low)
    low = re.sub(r"\s+", " ", low).strip()
    for pat, rep in MC_FIXES:
        low = re.sub(pat, rep, low)
    tokens = low.split(" ") if low else []
    if not tokens:
        return ""

    if tokens[0] not in MC_COMMAND_SET:                      # fix the command name
        c = difflib.get_close_matches(tokens[0], mcdata.MC_COMMANDS, n=1, cutoff=0.7)
        if c:
            tokens[0] = c[0]
        elif len(tokens) > 1:
            c = difflib.get_close_matches(tokens[0] + tokens[1], mcdata.MC_COMMANDS, n=1, cutoff=0.75)
            if c:
                tokens = [c[0]] + tokens[2:]
    cmd = tokens[0]

    if cmd in mcdata.MC_FREE_TEXT:                           # /say, /msg ...: keep your exact words
        rest = re.sub(r"^\W*\S+\s*", "", raw, count=1).strip()
        return (cmd + " " + (rest[:-1] if rest.endswith(".") else rest)).strip()

    if cmd == "gamerule":                                    # "keep inventory" -> keepInventory
        rest = " ".join(tokens[1:])
        for phrase in sorted(GAMERULES, key=len, reverse=True):
            rest = rest.replace(phrase, GAMERULES[phrase])
        tokens = ["gamerule"] + rest.split()
    return " ".join(mc_resolve(tokens, 1))

def mc_entity(phrase):
    idm = match_id(phrase.split())
    return idm if idm in mc_entities else None

COORD_RE = re.compile(r"[~^]?-?\d*\.?\d+|[~^]")

def mc_natural(heard):
    """'give me sixty four diamonds' etc. -> list of commands, or None.
    `heard` is lowercase text that still has its minus signs and decimal points."""
    h = words_to_digits(heard)
    h = re.sub(r"\btilde\s+(-?\d)", r"~\1", h).replace("tilde", "~")
    m = re.match(r"^give me (\d+) (?:experience )?levels?$", h)
    if m:
        return [f"experience add @s {m.group(1)} levels"]
    m = re.match(r"^give me (?:(a stack of|stack of|a|an|some)\s+|(\d+)\s+)?(.+)$", h)
    if m:
        count = int(m.group(2)) if m.group(2) else (64 if m.group(1) and "stack" in m.group(1) else 1)
        item = match_id(m.group(3).split())
        if item:
            return [f"give @s {item} {count}"]
    m = re.match(r"^(?:summon|spawn)\s+(?:(\d+)\s+)?(.+)$", h)
    if m:
        ent = mc_entity(m.group(2))
        if ent:
            return [f"summon {ent}"] * min(int(m.group(1) or 1), 10)
    m = re.match(r"^(?:teleport|tp) me to (.+)$", h)
    if m:
        parts = m.group(1).split()
        if parts and all(COORD_RE.fullmatch(p) for p in parts):
            target = " ".join(parts)             # coordinates keep their spaces: "100 64 -200"
        else:
            target = "".join(parts)              # a player name
        return [f"tp @s {target}"]
    m = re.match(r"^kill (?:all|every) (?:the )?(.+)$", h)
    if m:
        what = m.group(1)
        if what in ("everything", "entities", "mobs"):
            return ["kill @e[type=!player]"]
        ent = mc_entity(what)
        if ent:
            return [f"kill @e[type={ent}]"]
    if re.match(r"^clear (?:my )?inventory$", h):
        return ["clear @s"]
    m = re.match(r"^set (?:the )?time to (\d+)$", h)
    if m:
        return [f"time set {m.group(1)}"]
    return None

def mc_send_command(cmd, gen):
    first = cmd.split(" ", 1)[0]
    if MC_COMMAND_KEY is not None:
        tap(MC_COMMAND_KEY)                 # opens chat with "/" already typed
        time.sleep(0.25)
        type_text(cmd, gen)
    else:
        tap(MC_CHAT_KEY)
        time.sleep(0.25)
        type_text("/" + cmd, gen)
    if first in mcdata.MC_DANGEROUS:
        show_toast("press Enter to send /" + first, "err", 5.0)     # never sent automatically
    elif MINECRAFT_AUTO_SEND and state["gen"] == gen:
        time.sleep(0.05)
        tap(e.KEY_ENTER)

def run_mc_macro(phrase, gen, count=1):
    kind, payload = MC_MACROS[phrase]
    if state["gen"] != gen:
        return
    if kind in ("cmd", "keys"):
        last_mc.update(type="macro", phrase=phrase, count=count)
    if kind == "cmd":
        mc_send_command(payload, gen)
    elif kind == "keys":
        for i in range(count):
            if state["gen"] != gen:
                return
            combo(payload)
            if i < count - 1:
                time.sleep(0.12)
    elif kind == "again":                   # reopen chat, recall the last message, send
        tap(MC_CHAT_KEY)
        time.sleep(0.25)
        tap(e.KEY_UP)
        time.sleep(0.05)
        tap(e.KEY_ENTER)
    elif kind == "model":
        set_model(payload)
        return
    show_toast(phrase if count == 1 else f"{phrase} x{count}", "minecraft", 2.0)

def minecraft_chat(t, gen):
    if STRIP_TRAILING_PERIOD and t.endswith("."):
        t = t[:-1]
    tap(MC_CHAT_KEY)
    time.sleep(0.25)
    type_text(t, gen)
    if MINECRAFT_AUTO_SEND and state["gen"] == gen:
        time.sleep(0.05)
        tap(e.KEY_ENTER)

def minecraft_send(text, gen):
    t = text.strip()
    # Only things that start with "slash" are commands or shortcuts. Everything else is plain chat,
    # so you can still say "heal me" or "creative mode" to other players.
    m = re.match(r"^(?:/|slash\b)[\s,:]*(.*)$", t, re.I)
    if not m:
        minecraft_chat(t, gen)
        return
    body = m.group(1).strip()
    heard = clean_phrase(body)
    if not heard:
        return

    macro = difflib.get_close_matches(heard, list(MC_MACROS), n=1, cutoff=0.85)
    if macro:                                                # "slash heal me"
        run_mc_macro(macro[0], gen)
        return

    if re.match(r"^do (?:that|it) again\b", heard):          # "slash do that again"
        if last_mc["type"] == "cmd":
            mc_send_command(last_mc["cmd"], gen)
            show_toast("again: /" + last_mc["cmd"], "minecraft", 2.0)
        elif last_mc["type"] == "macro":
            cnt, _ = split_count(heard)
            run_mc_macro(last_mc["phrase"], gen, max(1, cnt or last_mc["count"]))
        else:
            show_toast("nothing to repeat", "err")
        return

    count, rest = split_count(heard)                         # "slash drop item three times"
    if count:
        key_macros = [k for k, v in MC_MACROS.items() if v[0] == "keys"]
        macro = difflib.get_close_matches(rest, key_macros, n=1, cutoff=0.85)
        if macro:
            if count > MAX_REPEAT:
                show_toast(f"max {MAX_REPEAT} times", "err")
                return
            run_mc_macro(macro[0], gen, max(1, count))
            return

    loose = re.sub(r"[,;!?]+", " ", body.lower())            # like `heard`, but keeps "-" and "." in numbers
    loose = re.sub(r"\.+(?=\s|$)", "", loose)
    loose = re.sub(r"\s+", " ", loose).strip()
    cmds = mc_natural(loose)                                 # "slash give me sixty four diamonds"
    if cmds:
        for c in cmds:
            if state["gen"] != gen:
                return
            mc_send_command(c, gen)
            time.sleep(0.15)
        last_mc.update(type="cmd", cmd=cmds[-1])
        show_toast("/" + cmds[0], "minecraft", 2.5)
        return

    cmd = normalize_mc_command(body)                         # "slash gamemode creative"
    if cmd:
        mc_send_command(cmd, gen)
        last_mc.update(type="cmd", cmd=cmd)
        show_toast("/" + cmd, "minecraft", 2.5)

# ---------------- SPEECH mode ----------------
def speech_type(text, gen):
    press_enter = False
    m = re.search(r"[\s,.!?]*press enter[\s.!?]*$", text, re.I)
    if m:
        text = text[: m.start()]
        press_enter = True
    if STRIP_TRAILING_PERIOD and text.endswith("."):
        text = text[:-1]
    if text:
        type_text(text if press_enter else text + " ", gen)
    if press_enter and state["gen"] == gen:
        tap(e.KEY_ENTER)

# ---------------- transcribe + dispatch ----------------
def transcribe_and_handle(audio, mode, model, gen):
    peak = float(np.abs(audio).max())
    if 0.01 < peak < 0.5:                       # boost quiet recordings
        audio = (audio * (0.7 / peak)).astype(np.float32)

    start = time.monotonic()
    with tlock:
        segs, _ = get_model(model).transcribe(
            audio, language="en", beam_size=1, vad_filter=True,
            condition_on_previous_text=False, initial_prompt=prompt_for(mode))
        seg_list = list(segs)
        text = "".join(s.text for s in seg_list).strip()
        conf = min((s.avg_logprob for s in seg_list), default=None)    # Whisper's own confidence (0 = certain)
    print(f"[{mode}/{model}] {time.monotonic() - start:.1f}s"
          + (f" (conf {conf:.2f})" if conf is not None else "") + f": {text}")

    if state["gen"] != gen:
        print("(cancelled, result thrown away)")
        return
    if not text:
        if mode == "command":
            show_toast("didn't catch that", "err")
        return
    if mode == "command":
        run_command(text, gen, conf)
    elif mode == "minecraft":
        minecraft_send(text, gen)
    else:
        speech_type(text, gen)

# ---------------- recording ----------------
def audio_cb(indata, frames, t, status):
    if rec["frames"] < MAX_RECORD_SECS * rec["rate"]:      # stuck button? stop collecting, don't eat all the RAM
        chunks.append(indata.copy())
        rec["frames"] += frames
    state["level"] = float(np.sqrt(np.mean(indata ** 2)))

def process(data, mode, model, gen, rate):
    try:
        if data:
            audio = to_16k(np.concatenate(data).flatten(), rate)
            if len(audio) > 8000:               # ignore taps under 0.5s
                transcribe_and_handle(audio, mode, model, gen)
    except Exception as err:
        print("Error while handling speech:", err)
    finally:
        if state["gen"] == gen:
            state["phase"] = "idle"

def start_recording():
    global stream
    with lock:
        if stream is not None or state["phase"] != "idle":
            return
        if not mic["ok"]:
            show_toast("no mic connected", "err", 2.0)
            return
        try:
            chunks.clear()
            rec["rate"] = mic["rate"]
            rec["frames"] = 0
            stream = sd.InputStream(device=mic["index"], samplerate=mic["rate"], channels=1,
                                    dtype="float32", callback=audio_cb)
            stream.start()
            state["phase"] = "rec"
            state["panel"] = None               # a list panel makes way for the recording pill
        except Exception as err:
            stream = None
            print("Couldn't start recording:", err)
            mic["ok"] = False                   # the watcher will look for it again
            mic_watch["cards"] = None
            show_toast("MIC MISSING", "err", 3.0)

def stop_recording():
    global stream
    with lock:
        if stream is None:
            return
        try:
            stream.stop()
            stream.close()
        except Exception as err:                # mic unplugged mid-recording
            print("Mic problem while stopping:", err)
            mic["ok"] = False
            mic_watch["cards"] = None
        stream = None
        data = list(chunks)
        mode, model, gen = state["mode"], state["model"], state["gen"]
        state["phase"] = "busy"
    state["level"] = 0.0
    threading.Thread(target=process, args=(data, mode, model, gen, rec["rate"]), daemon=True).start()

def cancel_all():
    """Stops the current voice job: recording, transcription, typing, repeats, chains, pending questions,
    any ringing alarm, and (if cancel_stops_stopwatch is on) the stopwatch. Programs already launched and
    running timers are NOT touched."""
    global stream
    state["gen"] += 1
    pending["kind"] = None
    stop_alarm()
    stopped_sw = CANCEL_STOPS_STOPWATCH and stop_stopwatch()
    with lock:
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
            stream = None
        chunks.clear()
        state["phase"] = "idle"
    state["level"] = 0.0
    state["panel"] = None
    mouse_release_all()                         # never leave a mouse button stuck down
    print(">>> CANCELLED")
    show_toast("CANCELLED - stopwatch stopped" if stopped_sw else "CANCELLED", "err", 1.8)

# ---------------- talk button (GPIO) with 5-press cancel ----------------
mash = []

def talk_down():
    if alarm_active.is_set():                   # first press just silences a ringing alarm
        stop_alarm()
        return
    now = time.monotonic()
    mash.append(now)
    while mash and now - mash[0] > MASH_WINDOW:
        mash.pop(0)
    if len(mash) >= MASH_COUNT:
        mash.clear()
        cancel_all()
        return
    start_recording()

def talk_up():
    stop_recording()

# ---------------- inputs ----------------
def input_loop():
    next_scan = time.monotonic() + 3.0
    while True:
        if time.monotonic() >= next_scan:       # pick up keyboards that appeared later (keyd restart, plug-in)
            scan_keyboards()
            next_scan = time.monotonic() + 3.0
        for key, _ in sel.select(timeout=1.0):
            dev = key.fileobj
            try:
                events = list(dev.read())
            except BlockingIOError:
                continue
            except OSError:                     # keyboard unplugged, or keyd recreated its device
                print("Keyboard gone:", dev.name)
                drop_keyboard(dev)
                continue
            for ev in events:
                if ev.type != e.EV_KEY:
                    continue
                if ev.code == MODE_KEY:
                    if ev.value == 1:
                        mode_key_down()
                    elif ev.value == 0:
                        mode_key_up()
                elif TALK_KEY is not None and ev.code == TALK_KEY:
                    if ev.value == 1:
                        talk_down()
                    elif ev.value == 0:
                        talk_up()

button = None
if Button is not None and BUTTON_PIN is not None:
    try:
        button = Button(BUTTON_PIN, bounce_time=0.03)
        button.when_pressed = talk_down
        button.when_released = talk_up
        print(f"Push-to-talk button on GPIO{BUTTON_PIN} (press it {MASH_COUNT}x fast to cancel)")
    except Exception as err:
        print("GPIO button unavailable:", err)

# ---------------- animated on-screen indicator (GTK, transparent + round) ----------------
def run_overlay():
    try:
        os.environ["GDK_BACKEND"] = "x11"
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        from gi.repository import Gtk, Gdk, GLib
        import cairo
    except Exception as err:
        print("Overlay unavailable. Try: sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0")
        print("Reason:", err)
        return False

    PAD = 12
    WIN_W, WIN_H = 420, 336     # fixed transparent canvas (tall enough for a full list panel)
    DOT = 22                    # size of the dot
    PILL_H = 40                 # height of the pills
    REC_W = 240                 # width of the recording pill
    MARGIN = 10
    RING_R = 9.5                # radius of the spinner ring around the dot
    GLOW = 28                   # how far glow / ripples reach past the shape (for partial redraws)

    screen = Gdk.Screen.get_default()
    sw_px, sh_px = screen.get_width(), screen.get_height()
    WIN_W = int(max(300, min(POPUP_MAX_WIDTH, sw_px - 2 * MARGIN)))   # boxes can grow up to this wide

    win = Gtk.Window(type=Gtk.WindowType.POPUP)    # no title bar, never takes focus
    win.set_app_paintable(True)
    visual = screen.get_rgba_visual()
    if visual is not None:
        win.set_visual(visual)                     # allows see-through background
    win.set_default_size(WIN_W, WIN_H)
    win.move(max(0, sw_px - WIN_W - MARGIN + PAD), max(0, sh_px - WIN_H - MARGIN + PAD))

    scratch = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))

    def text_w(text, size, bold):
        scratch.select_font_face("Sans", cairo.FONT_SLANT_NORMAL,
                                 cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
        scratch.set_font_size(size)
        return scratch.text_extents(text).x_advance

    width_cache = {}

    def cached_width(text, size, bold):         # measuring text every frame is wasted work
        key = (text, size, bold)
        if key not in width_cache:
            if len(width_cache) > 300:
                width_cache.clear()
            width_cache[key] = text_w(text, size, bold)
        return width_cache[key]

    def toast_width(text):
        return int(min(WIN_W - 2 * PAD, max(150, cached_width(text, 14, True) + 62)))

    LINE_H = 20                                     # spacing between the lines of a long message
    TOAST_MAX_LINES = 6
    ROWS_MAX = (WIN_H - 2 * PAD - 54) // 21         # list rows that fit inside a panel

    def wrap_px(text, size, bold, max_px, sub_indent=""):
        """Word-wraps text so every line fits max_px wide. Leading spaces are kept; nothing is dropped."""
        if not text.strip():
            return [""]
        lead = text[:len(text) - len(text.lstrip())]
        n = max(8, int(max_px / max(4.0, cached_width("e", size, bold))))      # first guess: characters per line
        while True:
            lines = textwrap.wrap(text.strip(), width=n, initial_indent=lead, subsequent_indent=lead + sub_indent,
                                  break_long_words=True, break_on_hyphens=False) or [lead]
            if n <= 8 or all(cached_width(x, size, bold) <= max_px for x in lines):
                return lines
            n -= 1

    def layout_toast(text):
        """-> (lines, box width, box height): a short message is one pill, a long one grows wider, then taller."""
        lines = wrap_px(text, 14, True, (WIN_W - 2 * PAD) - 62)
        if len(lines) > TOAST_MAX_LINES:
            lines = lines[:TOAST_MAX_LINES]
            lines[-1] = lines[-1][:max(0, len(lines[-1]) - 3)] + "..."
        w = int(min(WIN_W - 2 * PAD, max(150, max(cached_width(x, 14, True) for x in lines) + 62)))
        return lines, w, PILL_H + LINE_H * (len(lines) - 1), ""

    def layout_panel(panel):
        """-> (rows, box width, box height, title) for a list panel; long lines wrap instead of being cut."""
        maxw = WIN_W - 2 * PAD
        title = panel["title"]
        while len(title) > 1 and cached_width(title, 14, True) > maxw - 68:
            title = title[:-1]
        rows = []
        for ln in panel["lines"][:PANEL_MAX]:
            rows += wrap_px(ln, 13, False, maxw - 48, sub_indent="  ")
        if len(rows) > ROWS_MAX:
            rows = rows[:ROWS_MAX]
            rows[-1] = "..."
        mw = max([cached_width(title, 14, True) + 20] + [cached_width(x, 13, False) for x in rows])
        return rows, int(min(maxw, max(220, mw + 48))), 44 + 21 * len(rows) + 10, title

    layout = {"key": None, "val": None}

    def cached_layout(key, fn, *args):              # work out the layout once per message, not every frame
        if layout["key"] != key:
            layout["key"], layout["val"] = key, fn(*args)
        return layout["val"]

    anim = {"w": float(DOT), "h": float(DOT), "color": COLORS["speech"],
            "content": "toast", "lines": [], "title": "", "lvl": 0.0, "wave": [0.0] * 16,
            "a_idle": 1.0, "a_rec": 0.0,
            "spin_a": 0.0, "spin_len": 0.0, "ring_vis": 0.0, "closing": False, "prev_busy": False,
            "ping": -10.0, "last": time.monotonic(), "rect": None, "skip": 0, "sig": None}

    def lerp(a, b, k):
        return a + (b - a) * k

    def rounded_rect(cr, x, y, w, h, r):
        r = min(r, w / 2, h / 2)
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()

    def glow_dot(cr, cx, cy, r, col, alpha=1.0):
        g = cairo.RadialGradient(cx, cy, r * 0.6, cx, cy, r * 1.8)
        g.add_color_stop_rgba(0, col[0], col[1], col[2], 0.55 * alpha)
        g.add_color_stop_rgba(1, col[0], col[1], col[2], 0.0)
        cr.set_source(g)
        cr.arc(cx, cy, r * 1.8, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgba(col[0], col[1], col[2], alpha)
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.fill()

    def on_draw(widget, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)     # start fully transparent
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)

        t = time.monotonic()
        w, h = anim["w"], anim["h"]
        R, B = WIN_W - PAD, WIN_H - PAD            # shapes grow up and left from the bottom-right corner
        L, T = R - w, B - h
        cx = L + min(h, PILL_H) / 2                # the dot sits at the top-left of whatever is showing
        cy = T + min(h, PILL_H) / 2
        col = anim["color"]
        grow = max(w - DOT, h - DOT)
        pill_amt = max(0.0, min(1.0, grow / 30.0))        # 0 = just a dot, 1 = full pill / panel

        if pill_amt > 0.01:                        # dark rounded background (fades in as the dot stretches)
            rounded_rect(cr, L, T, w, h, min(h / 2, 20))
            cr.set_source_rgba(0.08, 0.08, 0.08, 0.92 * pill_amt)
            cr.fill_preserve()
            cr.set_source_rgba(1, 1, 1, 0.14 * pill_amt)
            cr.set_line_width(1)
            cr.stroke()

        # the dot: every effect is blended in/out by its own eased amount, so nothing cuts
        a_idle, a_rec = anim["a_idle"], anim["a_rec"]
        breathe = 0.5 + 0.5 * math.sin(t * 2.2)
        pulse = 0.5 + 0.5 * math.sin(t * 6)
        radius = (5.5 + 1.5 * pill_amt) * (1 + 0.10 * breathe * a_idle)
        alpha = 1.0 - 0.25 * (1 - breathe) * a_idle - 0.30 * (1 - pulse) * a_rec
        glow_dot(cr, cx, cy, radius, col, alpha)

        if a_rec > 0.02:                            # recording ripple
            ripple = (t * 1.2) % 1.0
            cr.set_source_rgba(col[0], col[1], col[2], 0.5 * (1 - ripple) * a_rec)
            cr.set_line_width(1.5)
            cr.arc(cx, cy, radius + ripple * 11, 0, 2 * math.pi)
            cr.stroke()

        if anim["ring_vis"] > 0.02 and anim["spin_len"] > 0.02:   # working spinner (or the ring closing up)
            a0 = anim["spin_a"]
            cr.set_line_width(2)
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            cr.set_source_rgba(col[0], col[1], col[2], 0.95 * anim["ring_vis"])
            cr.arc(cx, cy, RING_R, a0, a0 + anim["spin_len"])
            cr.stroke()

        p = (t - anim["ping"]) / 0.7                # the "done" wave grows out of the closed ring
        if 0.0 <= p < 1.0:
            cr.set_source_rgba(col[0], col[1], col[2], 0.9 * (1 - p) ** 1.5)
            cr.set_line_width(2.2 - 1.0 * p)
            cr.arc(cx, cy, RING_R + p * 12, 0, 2 * math.pi)
            cr.stroke()

        text_amt = max(0.0, min(1.0, (grow - 40) / 60.0))   # text fades in as the shape opens
        if text_amt > 0.02:
            tx = L + min(h, PILL_H) - 2
            cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            cr.set_font_size(14)
            cr.set_source_rgba(1, 1, 1, 0.92 * text_amt)
            if anim["content"] == "rec":
                cr.move_to(tx, cy + 5)
                cr.show_text("REC  " + state["model"].split(".")[0])
                wave = anim["wave"]
                bw, gap = 3.0, 3.0
                x0 = R - 16 - len(wave) * (bw + gap) + gap
                for i, v in enumerate(wave):
                    bh = 3 + v * 22
                    rounded_rect(cr, x0 + i * (bw + gap), cy - bh / 2, bw, bh, bw / 2)
                    cr.set_source_rgba(COLORS["rec"][0], COLORS["rec"][1],
                                       COLORS["rec"][2], 0.9 * text_amt)
                    cr.fill()
            elif anim["content"] == "panel":
                cr.move_to(tx, cy + 5)
                cr.show_text(anim["title"])
                cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
                cr.set_font_size(13)
                cr.set_source_rgba(1, 1, 1, 0.85 * text_amt)
                for i, line in enumerate(anim["lines"]):
                    cr.move_to(L + 24, T + 59 + 21 * i)
                    cr.show_text(line)
            else:
                for i, line in enumerate(anim["lines"]):          # one line, or several for a long message
                    cr.move_to(tx, cy + 5 + LINE_H * i)
                    cr.show_text(line)
        return False

    win.connect("draw", on_draw)
    win.show_all()
    try:                                            # let mouse clicks pass straight through
        win.get_window().input_shape_combine_region(cairo.Region(), 0, 0)
    except Exception:
        pass

    def tick_body():
        now = time.monotonic()
        dt = min(0.1, max(0.001, now - anim["last"]))
        anim["last"] = now

        def ease(k):                                # same speed at any frame rate (k was tuned for 25 fps)
            return 1 - (1 - k) ** (dt * 25)

        toast, panel = state["toast"], state["panel"]
        if toast and now > toast["until"]:
            state["toast"] = toast = None
        if panel and now > panel["until"]:
            state["panel"] = panel = None
        sw_txt = stopwatch_text() if SHOW_STOPWATCH else None

        phase = state["phase"]
        if phase == "rec":
            kind, tw, th, tcol = "rec", REC_W, PILL_H, COLORS["rec"]
            anim["content"] = "rec"
        elif panel:
            anim["lines"], tw, th, anim["title"] = cached_layout(
                ("panel", panel["title"], tuple(panel["lines"])), layout_panel, panel)
            kind, tcol = "panel", COLORS[panel["color"]]
            anim["content"] = "panel"
        elif toast:
            anim["lines"], tw, th, _ = cached_layout(("toast", toast["text"]), layout_toast, toast["text"])
            kind, tcol = "toast", COLORS[toast["color"]]
            anim["content"] = "toast"
        elif phase == "busy":
            kind, tw, th, tcol = "busy", DOT, DOT, COLORS["busy"]
        elif sw_txt:                                # stopwatch stays on screen while running (and a few
            kind, tw, th, tcol = "toast", toast_width("STOPWATCH 0:00:00.0"), PILL_H, COLORS["command"]
            anim["content"] = "toast"               # seconds after you stop it)
            anim["lines"] = [sw_txt]
        else:
            kind, tw, th = "idle", DOT, DOT
            tcol = COLORS[state["mode"]] if mic["ok"] else COLORS["err"]   # orange = waiting for mic

        # working spinner: an arc that spins. When work ends, its front point races forward until it
        # meets its own back point (a closed ring), and that ring then expands as the "done" wave.
        busy = kind == "busy"
        if busy:
            anim["closing"] = False
            anim["spin_len"] = lerp(anim["spin_len"], 1.9, ease(0.25))
            anim["spin_a"] += 7.0 * dt
            anim["ring_vis"] = lerp(anim["ring_vis"], 1.0, ease(0.3))
        elif anim["prev_busy"]:
            anim["closing"] = True
        if anim["closing"]:
            anim["spin_len"] = lerp(anim["spin_len"], 2 * math.pi, ease(0.45))
            anim["spin_a"] += 7.0 * dt
            if anim["spin_len"] > 2 * math.pi - 0.1:        # closed: hand over to the expanding wave
                anim["closing"] = False
                anim["spin_len"] = 0.0
                anim["ring_vis"] = 0.0
                anim["ping"] = now
        anim["prev_busy"] = busy

        for key, target in (("w", tw), ("h", th)):  # ease size, color and effects toward targets
            anim[key] = target if abs(anim[key] - target) < 0.5 else lerp(anim[key], target, ease(0.3))
        anim["color"] = tuple(lerp(c, tc, ease(0.15)) for c, tc in zip(anim["color"], tcol))
        for k in ("idle", "rec"):
            anim["a_" + k] = lerp(anim["a_" + k], 1.0 if kind == k else 0.0, ease(0.15))

        anim["lvl"] = lerp(anim["lvl"], min(1.0, state["level"] * 10), ease(0.5))   # live waveform
        anim["wave"].append(anim["lvl"])
        del anim["wave"][0]

        # When nothing is moving except the slow idle "breathing", draw at ~10 fps instead of full speed.
        moving = (kind in ("rec", "busy") or anim["closing"] or anim["ring_vis"] > 0.02
                  or abs(anim["w"] - tw) > 0.5 or abs(anim["h"] - th) > 0.5
                  or now - anim["ping"] < 0.8 or anim["a_rec"] > 0.02
                  or any(abs(c - tc) > 0.01 for c, tc in zip(anim["color"], tcol)))
        sig = None                                  # a settled toast / panel only needs repainting when it changes
        if kind == "panel":
            sig = ("panel", tuple(anim["lines"]))
        elif kind == "toast":
            sig = ("toast", tuple(anim["lines"]))
        if moving:
            anim["skip"], anim["sig"] = 0, None
        elif sig is not None:
            if sig == anim["sig"]:
                return True
            anim["sig"] = sig
        else:
            anim["sig"] = None
            anim["skip"] = (anim["skip"] + 1) % 3
            if anim["skip"]:
                return True

        # Only repaint the corner where something is drawn (old + new position), not the whole window.
        R, B = WIN_W - PAD, WIN_H - PAD
        new = (max(0, int(R - anim["w"] - GLOW)), max(0, int(B - anim["h"] - GLOW)),
               min(WIN_W, int(R + GLOW)), min(WIN_H, int(B + GLOW)))
        old = anim["rect"] or new
        anim["rect"] = new
        x0, y0 = min(new[0], old[0]), min(new[1], old[1])
        x1, y1 = max(new[2], old[2]), max(new[3], old[3])
        win.queue_draw_area(x0, y0, x1 - x0, y1 - y0)
        return True

    def tick():
        # A GLib timer that raises an error is removed for good, which would freeze the overlay.
        # Catch everything so one bad frame can never kill it.
        try:
            return tick_body()
        except Exception as err:
            print("Overlay frame error:", err)
            return True

    def quit_gtk():
        Gtk.main_quit()
        return False

    GLib.timeout_add(33, tick)                      # about 30 frames per second
    for sig in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, quit_gtk)
    Gtk.main()
    return True

# ---------------- go ----------------
def _stop_on_sigterm(signum, frame):
    raise KeyboardInterrupt                         # lets the headless loop clean up on "kill"

load_words()
load_custom_commands()                              # also builds the action index
rebuild_mc_index()
threading.Thread(target=build_app_index, daemon=True).start()
mic_watch["cards"] = read_cards()
refresh_mic(False)

threading.Thread(target=input_loop, daemon=True).start()
threading.Thread(target=timer_loop, daemon=True).start()
threading.Thread(target=mic_watch_loop, daemon=True).start()

hints = []
if button is not None:
    hints.append("Hold the GPIO button to talk.")
if TALK_KEY is not None:
    hints.append("Hold the talk key to talk.")
print("Ready.", " ".join(hints) or "No talk button available!",
      "Tap ` = change mode, long press ` = switch base/tiny. Ctrl+C to quit.")
announce()
if not mic["ok"]:
    print(f"Waiting for a microphone matching '{MIC}'... it will connect automatically when it appears.")
    show_toast("WAITING FOR MIC", "err", 4.0)

signal.signal(signal.SIGTERM, _stop_on_sigterm)
try:
    ran_overlay = False
    if SHOW_OVERLAY and os.environ.get("DISPLAY"):
        try:
            ran_overlay = run_overlay()
        except Exception as err:                    # e.g. no usable display: carry on without the dot
            print("Overlay crashed:", err)
    if not ran_overlay:                             # headless fallback
        while True:
            time.sleep(1)
except KeyboardInterrupt:
    print("\nExiting.")
finally:
    try:
        stop_alarm()
        mouse_release_all()
    except Exception:
        pass
    mouse.close()
    ui.close()
