# Quick Translate · Global Selection Translation / Screenshot OCR / AI Assistant for Windows

[简体中文](README.md) | **English**

A small Windows utility that lives in the system tray. In **any application and on any screen**, just select English text (or draw a box on the screen) and press a hotkey to look up words, translate, or ask AI. It ships as a **single, portable exe — no installation and no runtime prerequisites**, and can be copied to any Windows 10/11 machine and used directly.

## Features

- **Global selection translation**: select a word, phrase, sentence, or whole paragraph with the mouse and press the hotkey; the result pops up next to the cursor.
- **Region-screenshot OCR**: for text that can't be selected (scanned PDFs, images, video, apps that block copying) — just drag a box. The screen is **frozen at the exact moment the hotkey is pressed**, so even right-click menus and dropdowns that normally vanish can be captured. OCR runs on the **local Windows engine — no network calls and no images uploaded**.
- **Line-by-line view for multi-line text**: multi-line / paragraph content is shown as paired source-line → translated-line; blank lines keep paragraph breaks, and copied translations preserve line breaks.
- **Aggregated dictionary results for words**: abbreviations (e.g. *TEC*) return every meaning — domain definitions from the paper corpus, dictionary full forms, web definitions — so specialized meanings are never missed.
- **AI assistant**: ask freely in a chat window (Enter to send, Shift+Enter for a newline). In the result popup you can also **AI-refine** a sentence/paragraph (more natural wording, more accurate terms) and **AI-explain** a word/abbreviation.
- Auto-copy translation, launch on startup, lookup history, US/UK pronunciation, and a graphical settings window.

## Quick Start (end users)

1. Download the latest `快捷翻译.exe` from the **Releases** page.
2. Double-click it; the app waits in the system tray (no Python or runtime needed).
3. Select English text and press a hotkey. On first run a blank `config.ini` is created next to the exe.

| Function | Default hotkey (changeable in Settings, e.g. F1/F2/F3) |
| --- | --- |
| Translate selection | `Ctrl + Alt + E` |
| Screenshot OCR translation | `Ctrl + Alt + S` |
| Ask AI | `Ctrl + Alt + A` |

A detailed (Chinese) guide is available at [`docs/使用说明.md`](docs/使用说明.md).

## Optional Configuration (via right-click tray → Settings)

- **AI assistant**: any OpenAI-compatible endpoint — DeepSeek, Doubao (Volcano Ark), OpenAI, or custom. Enter an API Key and model to enable AI chat, AI-refine, and AI-explain.
- **Baidu Translate official API**: the standard tier is free and improves long-sentence quality; if left blank, the built-in free channel is used.

## Running from Source

Requires Windows 10/11 and Python 3.11+:

```powershell
pip install -r requirements.txt
python src/fanyi.py
```

> When run from source, `config.ini`, `history.csv`, and `cache/` are created in the project root.

## Building the Single-File exe

Install dependencies and PyInstaller first (or use the project's `.build_env` virtualenv — the script detects it automatically):

```powershell
pip install -r requirements.txt pyinstaller
# Windows PowerShell:
& scripts/build_exe.ps1
```

The build script locates the project root relative to its own location, so it works after copying the project to any folder or machine. The resulting `快捷翻译.exe` is written to `build_pkg/dist/` and copied to the project root.

## Project Layout

```
.
├─ src/
│  ├─ fanyi.py            # Main application source
│  └─ app.ico             # Application icon
├─ scripts/
│  ├─ build_exe.ps1       # PyInstaller build script (auto-locates paths)
│  └─ make_icon.py        # Icon generator
├─ docs/
│  └─ 使用说明.md          # Detailed (Chinese) usage guide
├─ README.md              # Chinese README
├─ README.en.md           # English README (this file)
├─ LICENSE                # MIT License
├─ requirements.txt       # Python dependencies
├─ config.example.ini     # Config template (keys blank)
├─ .gitignore
├─ 快捷翻译.exe            # Built artifact (distribute via Releases, not committed)
├─ config.ini             # Your real config (contains keys; ignored)
└─ history.csv            # Your personal lookup history (ignored)
```

## Security & Privacy (important)

- **`config.ini` stores your API key in plaintext — never commit it to GitHub or send it to anyone.** It is listed in `.gitignore`.
- When sharing with others, **send only `快捷翻译.exe` (optionally with `docs/使用说明.md`)**. A blank config is generated automatically on first run; do not include your own `config.ini` or `history.csv`.
- `.build_env/` (virtualenv), `build_pkg/` (build intermediates), and `cache/` (runtime cache) are machine-specific and should not be committed.
- If an API key is ever leaked, **revoke and rotate it immediately** in the provider's console.

## License

[MIT](LICENSE)

## Disclaimer

This is a personal learning project. The free translation relies on public interfaces; please comply with the relevant services' terms of use.
