<div align="center">

```
_     _____    _    ____     ___ _   _ _____ _____ _     
| |   | ____|  / \  |  _ \   |_ _| \ | |_   _| ____| |    
| |   |  _|   / _ \ | | | |   | ||  \| | | | |  _| | |    
| |___| |___ / ___ \| |_| |   | || |\  | | | | |___| |___ 
|_____|_____/_/   \_\____/   |___|_| \_| |_| |_____|_____|

```

**Automated company intelligence extraction — local AI, zero cloud dependency.**

[![Python](https://img.shields.io/badge/python-3.14t_%7C_GIL--free-blue?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Ollama](https://img.shields.io/badge/ollama-llama_3.2_1b-33cc55?style=flat-square)](https://ollama.com)
[![Playwright](https://img.shields.io/badge/playwright-stealth_mode-e2562b?style=flat-square&logo=playwright&logoColor=white)](https://playwright.dev)
[![Flask](https://img.shields.io/badge/flask-loopback_only-lightgrey?style=flat-square&logo=flask&logoColor=white)](https://flask.palletsprojects.com)
[![License](https://img.shields.io/badge/license-MIT-yellow?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-linux_%7C_macos_%7C_windows-8a2be2?style=flat-square)](https://github.com/debuggerdragon311/lead-intel-bot)

</div>

---

Drop in a company name or domain. Get structured intelligence back — founder, tech stack, value proposition — scraped and extracted entirely on your machine. No API keys. No subscriptions. No data leaving your network.

---

## Screenshots

<p align="center">
  <img src="assets/ss01.png" alt="Operator Dashboard" width="100%" />
  <br/>
  <img src="assets/ss02.png" alt="Live Extraction Results" width="100%" />
</p>

---

## What it extracts

Three fields per target, every run:

```
+-----------------------+----------------------------------------------------+
| Founder / CEO         | Full name of the founder or chief executive        |
| Tech Stack            | Top 3 technologies the company is built on         |
| Value Proposition     | One sentence -- the core problem the business solves|
+-----------------------+----------------------------------------------------+
```

Results stream live to the dashboard as each target finishes. When the run completes, everything exports to a timestamped CSV automatically.

Built for sales teams and growth engineers who need fast competitive intelligence without paying $500/month for a SaaS tool that runs the same pipeline on someone else's server with your data.

---

## Demo

https://github.com/user-attachments/assets/466a07c7-1953-48f1-9d40-5b631d08b781

35-second live run against `cal.com` -- scrapes, extracts, and returns structured output with zero internet-facing services involved.

Can't see the video? Clone the repo and open `assets/ss.mp4` locally, or [click here](assets/ss.mp4).

---

## Before you start -- uBlock Origin setup

The `extensions/ublock/` directory is **not included in this repository** and must be added manually before running the scraper.

Every browser session loads uBlock Origin to suppress ad networks and tracker scripts during extraction. Without it, many pages will load significantly slower or fail outright on ad-heavy sites.

**Steps:**

1. Download the uBlock Origin Chromium extension (unpacked folder) from
   `https://github.com/gorhill/uBlock/releases`

2. Extract it into:
   ```
   extensions/ublock/
   ```
   Verify the structure -- `manifest.json` must sit directly at `extensions/ublock/manifest.json`.

3. Continue with installation below.

The app will still run without this step, but scraping reliability degrades noticeably on heavy pages.

---

## How the pipeline works

```
Input domain
     |
     v
Phase A  --  DuckDuckGo query for founder and tech signals
     |
     v
Phase B  --  Playwright headless browser visits the company landing page
     |        uBlock Origin active, playwright-stealth fingerprint masking on
     v
Raw text assembled: title + meta tags + visible body content
     |
     v
Ollama HTTP inference  --  Llama 3.2 1B, running locally
     |
     v
Structured output parsed  --  Founder / Tech Stack / Value Prop
     |
     v
Dashboard updated live  --  CSV report auto-saved to data/reports/
```

The dashboard polls every 1.5 seconds. Each target moves through four states:

```
QUEUED  -->  SCANNING  -->  AI-EXTRACTING  -->  DONE
```

The full pipeline runs across daemon threads. Phase A and Phase B are independent -- if the DuckDuckGo query fails, Phase B continues against the direct landing page.

---

## Architecture

```
lead-intel-bot/
|
+-- app.py                   Master entrypoint. Boots all threads, opens native window.
|
+-- core/
|   +-- config.py            Path sandboxing, env variables, PyInstaller path resolution.
|   +-- state.py             Thread-safe global state. Explicit Lock() guards throughout.
|   +-- preflight.py         Boot checks: Ollama health, model pull, Chromium install.
|   +-- scraper.py           Async Playwright scraper. DuckDuckGo + direct page crawl.
|   +-- ai.py                Ollama HTTP client and structured response parser.
|   +-- server.py            Flask REST API: /, /status, /run, /export/csv
|   +-- ui_template.py       Self-contained dashboard. CRT terminal aesthetic, no frameworks.
|
+-- data/
|   +-- ms-playwright/       Sandboxed Chromium binaries. Never touches OS browser dirs.
|   +-- ollama/models/       Sandboxed model weights. Isolated from system Ollama dir.
|   +-- reports/             Timestamped CSV output. Written after every completed run.
|
+-- extensions/
|   +-- ublock/              Add uBlock Origin here (see setup section above).
|
+-- assets/
|   +-- ss.mp4               Demo recording.
|   +-- ss01.png             Dashboard screenshot.
|   +-- ss02.png             Results screenshot.
|
+-- pyproject.toml
+-- requirements.txt
```

### Thread model

The app targets the **GIL-free Python 3.14t runtime** -- the experimental free-threaded CPython build. The Global Interpreter Lock is disabled, which means standard dict and list mutations are no longer serialized by the interpreter. All shared state uses explicit `threading.Lock()` guards as a result.

```
Main Thread       --  pywebview GUI loop. Owns process lifetime.
preflight-worker  --  Ollama health check, model pull, Chromium install.   [daemon]
flask-server      --  REST API bound to 127.0.0.1:1995.                    [daemon]
pipeline-worker   --  Scrape + AI loop. Spawned fresh per execution run.   [daemon]
```

---

## Requirements

**System:**

```
OS        Linux, macOS 12+, Windows 10/11
RAM       4 GB minimum  (8 GB recommended)
Disk      ~2 GB  (Chromium ~130 MB  +  Llama 3.2 1B ~1.3 GB)
Python    3.11+  (3.14t recommended for GIL-free performance)
Network   First run only -- to pull the model and install Chromium
```

**Dependencies:**

```
Ollama          Local AI runtime          Manual install   (see Step 1)
Chromium        Headless browser          Auto on first launch
Llama 3.2 1B    Extraction model          Auto on first launch
uBlock Origin   Ad blocking per session   Manual install   (see setup above)
```

---

## Installation

### Step 1 -- Install Ollama

```bash
# Linux / macOS
curl -fsSL https://ollama.com/install.sh | sh

# Windows
# Download installer from https://ollama.com/download
```

Confirm it's working:

```bash
ollama --version
```

You don't need to pull any model manually. The app pulls `llama3.2:1b` on first launch automatically.

---

### Step 2 -- Add uBlock Origin

Follow the setup steps at the top of this document before continuing.

---

### Step 3 -- Clone the repository

```bash
git clone https://github.com/debuggerdragon311/lead-intel-bot.git
cd lead-intel-bot
```

---

### Step 4 -- Create a virtual environment

```bash
python3 -m venv .venv

# Linux / macOS
source .venv/bin/activate

# Windows (PowerShell)
.venv\Scripts\Activate.ps1
```

---

### Step 5 -- Install Python dependencies

```bash
pip install -r requirements.txt
```

---

### Step 6 -- Run

```bash
python app.py
```

On first launch, the system runs three preflight tasks automatically:

1. Verifies Ollama is reachable on the default port
2. Pulls `llama3.2:1b` (~1.3 GB, one time only)
3. Installs Chromium into `data/ms-playwright/`

Watch the **System Console Feed** panel for live progress. The `[ EXECUTE PIPELINE ]` button stays locked until preflight completes.

First launch takes 2-5 minutes depending on connection speed. Every launch after that is under 3 seconds.

---

## Using the dashboard

**Adding targets**

Type a company name or domain into the Target Acquisition input, then press `[ ADD ]` or Enter.

```
cal.com
stripe.com
notion
openai
```

Names without a `.` are automatically resolved as `.com` domains.

**Running the pipeline**

Click `[ EXECUTE PIPELINE ]`. The status column for each target updates in real time:

```
QUEUED      Waiting in queue
SCANNING    Browser active -- scraping DuckDuckGo and the company page
AI-EXTRACT  Ollama running inference on the scraped payload
DONE        Extraction complete
ERROR       No usable text recovered -- target skipped
```

**Exporting results**

Open `http://127.0.0.1:1995/export/csv` in any browser while the app is running to download `company_intel_report.csv`.

Reports are also written to disk automatically after every run:

```
data/reports/report_20240115-110022.csv
```

---

## Privacy and security

- **Offline inference.** Llama 3.2 runs locally through Ollama. No text payload reaches any external API.
- **Sandboxed Chromium.** Playwright installs Chromium inside `data/ms-playwright/` and never touches the OS browser directory.
- **Sandboxed model storage.** Ollama weights are stored in `data/ollama/models/`, isolated from the system-level Ollama directory.
- **Loopback-only API.** Flask binds exclusively to `127.0.0.1`. The REST API is unreachable from any other machine on the network.
- **Ad and tracker blocking.** uBlock Origin is loaded into every browser session before any page request is made.

---

## Troubleshooting

**The execute button stays disabled**

Preflight is still running. Watch the Console Feed panel. If it prints `Ollama daemon is not reachable`, start the daemon manually in a separate terminal:

```bash
ollama serve
```

**"A scan is already active"**

Wait for all targets to reach `DONE` or `ERROR` status before starting a new run. Concurrent runs are not supported.

**`Phase A WARNING: DuckDuckGo query failed`**

DuckDuckGo's static HTML endpoint is rate-sensitive and occasionally slow. This warning is non-fatal -- Phase B (direct landing page crawl) continues regardless. Extraction will complete as long as the company page itself is reachable.

**Blank screen on launch**

Flask is probably still binding. Wait 2-3 seconds and reload. If it persists, check whether something else is using port 1995:

```bash
lsof -i :1995                  # Linux / macOS
netstat -ano | findstr 1995    # Windows
```

**pywebview fails to open on Linux**

```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.0
```

---

## Tech stack

```
Language      Python 3.14t  --  free-threaded, GIL-disabled
Desktop GUI   pywebview  --  WebKit on Linux/macOS, EdgeChromium on Windows
Scraping      Playwright (async) + playwright-stealth
AI runtime    Ollama  --  Meta Llama 3.2 1B, local, quantized
API layer     Flask, loopback microservice, no external auth surface
Dashboard     Vanilla HTML / CSS / JS  --  CRT phosphor terminal aesthetic
Concurrency   threading.Lock()  --  explicit mutual exclusion, GIL-free safe
Ad blocking   uBlock Origin, loaded per browser session
```

---

## License

MIT -- see [LICENSE](LICENSE).

---

## Author

<div align=center>
  
**Soumyajit Bala**

Systems engineer. I build automation infrastructure, AI pipelines, and local-first tools.

[![Email](https://img.shields.io/badge/email-soumyajit@zelkyr.dev-333?style=flat-square&logo=gmail&logoColor=white)](mailto:soumyajit@zelkyr.dev)
[![GitHub](https://img.shields.io/badge/github-debuggerdragon311-181717?style=flat-square&logo=github&logoColor=white)](https://github.com/debuggerdragon311)

> Need a custom automation pipeline, AI integration, or data extraction system built?
> Reach out at [soumyajit@zelkyr.dev](mailto:soumyajit@zelkyr.dev)

</div>

---

<div align="center">
  <sub>All inference runs locally. Nothing leaves your machine.</sub>
</div>
