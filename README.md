<div align="center">

# ⬛ LEAD INTEL SYSTEM

### Automated company intelligence extraction — powered by local AI, zero cloud dependency.

[![Python](https://img.shields.io/badge/Python-3.14t%20GIL--Free-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Ollama](https://img.shields.io/badge/Ollama-Llama%203.2%201B-33ff33?style=for-the-badge&logo=ollama&logoColor=black)](https://ollama.com)
[![Playwright](https://img.shields.io/badge/Playwright-Stealth%20Mode-E2562B?style=for-the-badge&logo=playwright&logoColor=white)](https://playwright.dev)
[![Flask](https://img.shields.io/badge/Flask-Loopback%20API-grey?style=for-the-badge&logo=flask&logoColor=white)](https://flask.palletsprojects.com)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20macOS%20%7C%20Windows-8A2BE2?style=for-the-badge&logo=windows&logoColor=white)](https://github.com/debuggerdragon311/lead-intel-bot)

---

**Drop in a domain. Get the founder, tech stack, and value proposition — instantly, offline, free.**

</div>

---

<p align="center">
  <img src="assets/ss01.png" alt="Lead Intel System — Operator Dashboard" width="100%" />
</p>

<p align="center">
  <img src="assets/ss02.png" alt="Lead Intel System — Live Extraction Results" width="100%" />
</p>

---

## What does it do?

You give it a company name or domain. It opens a hidden browser, visits the company website, pulls all public text, and runs it through a local AI model — **on your machine, with no API keys, no subscriptions, and no data leaving your network.**

Three fields extracted per target, every time:

| Field | What you get |
|---|---|
| **Founder / CEO** | Full name of the founder or chief executive |
| **Tech Stack** | Top 3 technologies the company is built on |
| **Value Proposition** | One sentence — the core problem the business solves |

Results appear live on the dashboard as each target is processed. When done, everything exports to a clean CSV report automatically.

> **Built for sales teams, growth ops, and founders** who need fast competitive intelligence without paying $500/month for tools that do the same thing on a remote server with your data.

---

## Demo

https://github.com/user-attachments/assets/466a07c7-1953-48f1-9d40-5b631d08b781

> **35-second demo** — live run against `cal.com`. Scrapes, extracts, and presents structured intelligence with zero internet-facing services.
>
> ℹ️ **Can't see the video?** Clone the repo and open `assets/ss.mp4` locally, or [click here](assets/ss.mp4).

---

## ⚠️ Before You Run — Required Setup

> **The `extensions/ublock/` directory is intentionally not included in this repository.**
>
> The scraper loads **uBlock Origin** into every browser session to block ad networks and tracker requests during extraction. Without it, many target pages will load significantly slower or fail outright due to bloated ad scripts.
>
> **You must add the uBlock Origin extension files manually:**
>
> 1. Download the uBlock Origin Chromium extension (`.crx` or unpacked folder) from [https://github.com/gorhill/uBlock/releases](https://github.com/gorhill/uBlock/releases)
> 2. Unpack/extract it into:
>    ```
>    extensions/ublock/
>    ```
>    The directory should contain `manifest.json` directly at `extensions/ublock/manifest.json`.
> 3. Continue with the normal installation steps below.
>
> If you skip this step, the app will still run — but scraping quality and speed will degrade on ad-heavy pages.

---

## How It Works

```
Input domain
    │
    ▼
Phase A — DuckDuckGo search query for founder / tech info
    │
    ▼
Phase B — Playwright headless browser visits the company landing page
    │         (uBlock Origin loaded, stealth mode active)
    ▼
Raw text payload assembled (title, meta, visible body content)
    │
    ▼
Ollama HTTP inference — Llama 3.2 1B running locally
    │
    ▼
Structured output parsed → Founder / Tech Stack / Value Prop
    │
    ▼
Dashboard updated live → CSV report auto-saved to data/reports/
```

The entire pipeline runs concurrently across daemon threads. The dashboard polls every 1.5 seconds and shows live status badges:

```
QUEUED → SCANNING → AI-EXTRACTING → ✓ DONE
```

---

## Architecture

```
lead-intel-bot/
├── app.py                   # Master entrypoint — boots all threads, opens native window
├── core/
│   ├── config.py            # Path sandboxing, env variables, PyInstaller compatibility
│   ├── state.py             # Thread-safe global state (GIL-free safe, explicit locks)
│   ├── preflight.py         # Boot checks: Ollama health, model pull, Chromium install
│   ├── scraper.py           # Async Playwright scraper — DuckDuckGo + direct page crawl
│   ├── ai.py                # Ollama HTTP client + structured response parser
│   ├── server.py            # Flask REST API (/, /status, /run, /export/csv)
│   └── ui_template.py       # Self-contained CRT terminal dashboard (HTML/CSS/JS)
├── data/
│   ├── ms-playwright/       # Sandboxed Chromium binaries (never written to OS dirs)
│   ├── ollama/models/       # Sandboxed LLM weights
│   └── reports/             # Auto-generated timestamped CSV reports
├── extensions/
│   └── ublock/              # ← ADD uBlock Origin here (see setup warning above)
├── assets/
│   ├── ss.mp4               # Demo video
│   ├── ss01.png             # Dashboard screenshot
│   └── ss02.png             # Results screenshot
├── pyproject.toml
└── requirements.txt
```

### Thread model

The app runs on a **GIL-free Python 3.14t runtime** — the experimental free-threaded build with the Global Interpreter Lock disabled. All shared state is protected by explicit `threading.Lock()` guards, which are required in this mode since standard dict/list mutations are no longer serialized by the interpreter.

```
Main Thread        →  pywebview GUI loop (owns process lifetime)
preflight-worker   →  Ollama health check, model pull, Chromium install  [daemon]
flask-server       →  REST API at 127.0.0.1:1995                         [daemon]
pipeline-worker    →  Scrape + AI loop, spawned per execution run        [daemon]
```

---

## Requirements

| Requirement | Minimum |
|---|---|
| OS | Linux, macOS 12+, Windows 10/11 |
| RAM | 4 GB (8 GB recommended) |
| Disk | ~2 GB (Chromium ~130 MB + Llama 3.2 1B ~1.3 GB) |
| Python | 3.11+ (3.14t recommended for GIL-free performance) |
| Network | First run only — to download model and Chromium |

| Dependency | Purpose | Auto-installed? |
|---|---|---|
| **Ollama** | Local AI runtime | ❌ Manual (see Step 1) |
| **Chromium** | Headless browser | ✅ Auto on first launch |
| **Llama 3.2 1B** | Extraction model | ✅ Auto on first launch |
| **uBlock Origin** | Ad blocking during scrape | ❌ Manual (see warning above) |

---

## Installation

### Step 1 — Install Ollama

```bash
# Linux / macOS
curl -fsSL https://ollama.com/install.sh | sh

# Windows — download from https://ollama.com/download
```

Verify it works:

```bash
ollama --version
```

You do **not** need to pull a model manually — the app handles that on first launch.

---

### Step 2 — Add uBlock Origin

See the [⚠️ Required Setup](#️-before-you-run--required-setup) section above before proceeding.

---

### Step 3 — Clone the repository

```bash
git clone https://github.com/debuggerdragon311/lead-intel-bot.git
cd lead-intel-bot
```

---

### Step 4 — Create a virtual environment

```bash
python3 -m venv .venv

# Linux / macOS
source .venv/bin/activate

# Windows (PowerShell)
.venv\Scripts\Activate.ps1
```

---

### Step 5 — Install dependencies

```bash
pip install -r requirements.txt
```

---

### Step 6 — Run

```bash
python app.py
```

On **first launch**, the system will:
1. Verify Ollama is reachable
2. Pull `llama3.2:1b` (~1.3 GB — one-time only)
3. Install sandboxed Chromium into `data/ms-playwright/`

Watch the **System Console Feed** panel for real-time progress. The `[ EXECUTE PIPELINE ]` button activates once preflight is complete.

> First launch: **2–5 minutes** depending on connection speed. All subsequent launches: **under 3 seconds.**

---

## Using the Dashboard

### Add targets

Type a company name or domain into the **Target Acquisition** input and press `[ ADD ]` or `Enter`.

```
cal.com
stripe.com
notion
openai
```

Names without a `.` are automatically treated as `.com` domains.

### Execute the pipeline

Click `[ EXECUTE PIPELINE ]`. Each target moves through:

| Status | Meaning |
|---|---|
| `QUEUED` | Waiting to be processed |
| `SCANNING` | Browser live — scraping DuckDuckGo and the company page |
| `AI-EXTRACT` | Ollama running inference on scraped text |
| `✓ DONE` | Extraction complete |
| `⚠ ERROR` | No usable text found — target skipped |

### Export results

While the app is running, open `http://127.0.0.1:1995/export/csv` in any browser to download `company_intel_report.csv`.

Reports are also auto-saved to `data/reports/` after every run:
```
data/reports/report_20240115-110022.csv
```

---

## Privacy & Security

- **100% offline inference** — Llama 3.2 runs locally via Ollama. No text is sent to any external AI API.
- **Sandboxed browser** — Playwright Chromium lives in `data/ms-playwright/`, never touching OS browser directories.
- **Sandboxed model weights** — Ollama models stored in `data/ollama/models/`, not the system Ollama directory.
- **Loopback-only API** — Flask binds to `127.0.0.1` exclusively. Not reachable from any other machine.
- **Ad blocking** — uBlock Origin loaded into every browser session to suppress tracker and ad network requests during scraping.

---

## Troubleshooting

**Button stays disabled / "Pre-flight installs are active"**
> Preflight is still running. Watch the Console Feed. If it shows `Ollama daemon is not reachable`, run `ollama serve` in a separate terminal.

**"A scan is already active"**
> Wait for all targets to reach `DONE` or `ERROR` before starting a new run.

**`Phase A WARNING: DuckDuckGo query failed`**
> DuckDuckGo's static HTML endpoint has occasional slow response times. Phase B (direct page crawl) continues regardless — extraction will still complete if the landing page is reachable.

**Blank screen on launch**
> Flask may still be starting. Wait 2–3 seconds. If it persists, check port `1995`:
> ```bash
> lsof -i :1995   # Linux / macOS
> ```

**Linux: pywebview fails to open**
> ```bash
> sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.0
> ```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.14t — free-threaded, GIL-disabled |
| Desktop GUI | pywebview (WebKit / EdgeChromium native frame) |
| Scraping | Playwright (async) + playwright-stealth |
| AI Inference | Ollama — Meta Llama 3.2 1B, local, quantized |
| API | Flask, loopback microservice |
| Dashboard | Vanilla HTML / CSS / JS — CRT phosphor terminal aesthetic |
| Concurrency | `threading.Lock()` — explicit mutual exclusion, GIL-free safe |
| Ad blocking | uBlock Origin, packaged per session |

---

## License

MIT — see [LICENSE](LICENSE).

---

## Author

<div align="center">

**Soumyajit Bala**

*Systems engineer. I build automation infrastructure, AI pipelines, and local-first tools.*

[![Email](https://img.shields.io/badge/Email-soumyajit@zelkyr.dev-333?style=for-the-badge&logo=gmail&logoColor=white)](mailto:soumyajit@zelkyr.dev)
[![GitHub](https://img.shields.io/badge/GitHub-debuggerdragon311-181717?style=for-the-badge&logo=github&logoColor=white)](https://github.com/debuggerdragon311)

**Need a custom automation pipeline, AI integration, or data extraction system built?**
Reach out at [soumyajit@zelkyr.dev](mailto:soumyajit@zelkyr.dev)

</div>

---

<div align="center">
  <sub>All inference runs locally. Nothing leaves your machine.</sub>
</div>
