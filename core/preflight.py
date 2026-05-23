"""Sandbox dependency checker and auto-installer.

Responsible for checking the local environment on startup:
    1. Check if an Ollama server is running. If port 11434 is free and the
        'ollama' CLI binary is in the system PATH, spawn an isolated local
        Ollama sandbox server with models stored inside:
        data/ollama/models/
    2. Query Ollama's tags API to verify if the 1.3 GB 'llama3.2:1b' model
        is loaded. If absent, pull the model asynchronously, streaming
        download percentages to the operator console.
    3. Verify Playwright Chromium browser binaries. If missing from the
        isolated directory (data/ms-playwright/), invoke the Playwright
        installer to pull binaries into the sandbox.

GIL-Free Threading Safety:
    Since preflight operations run on a background daemon thread, all
    updates to shared state parameters are executed through thread-safe
    mutators to prevent multicore memory races [1.2.6, 1.2.8].
"""

import os
import sys
import json
import time
import socket
import shutil
import asyncio
import subprocess
from typing import Any

import requests

from core.config import OLLAMA_PATH
from core.state import add_log, update_state_parameter


# =============================================================================
# Local Sandbox Service Starters
# =============================================================================

def _is_port_free(host: str, port: int) -> bool:
    """Check if a network socket port is currently unassigned.

    The socket is unconditionally closed in a finally block to prevent
    file descriptor leaks regardless of whether the bind succeeds.
    """
    s: socket.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _start_local_ollama_daemon() -> None:
    """
    Spawns an isolated local Ollama daemon if the default port is free.

    If port 11434 is already occupied, we assume a global system-wide
    Ollama instance is running and connect to it. If the port is free, we
    check the system PATH for the 'ollama' CLI and spawn a private sandbox
    process, redirecting model storage to our ./data/ollama/models directory.
    """
    if not _is_port_free("127.0.0.1", 11434):
        add_log("[OLLAMA] Port 11434 is occupied. Connecting to system daemon.")
        return

    ollama_bin: str | None = shutil.which("ollama")
    if not ollama_bin:
        add_log(
            "[OLLAMA] 'ollama' executable not found on PATH. "
            "Isolated local sandbox daemon launch bypassed."
        )
        return

    add_log("[OLLAMA] Port 11434 is free. Launching private local sandbox daemon...")

    # Isolate environment variables for the subprocess
    local_env: dict[str, str] = os.environ.copy()
    local_env["OLLAMA_MODELS"] = OLLAMA_PATH
    local_env["OLLAMA_HOST"] = "127.0.0.1:11434"

    try:
        # Cross-platform windowless execution flag (0x08000000 avoids CMD popups on Windows)
        creationflags: int = 0x08000000 if os.name == 'nt' else 0

        subprocess.Popen(
            [ollama_bin, "serve"],
            env=local_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags
        )
        add_log(
            f"[OLLAMA] Local sandbox daemon booted. "
            f"Model directory bound to: {OLLAMA_PATH}"
        )
        # Give the background server a brief window to bind to the port
        time.sleep(2.0)
    except Exception as exc:
        add_log(f"[OLLAMA-WARN] Local sandbox boot sequence failed: {exc}")
        update_state_parameter(
            "model_status",
            "Ollama daemon failed to start.",
        )


# =============================================================================
# Playwright Browser Installer
# =============================================================================

async def _test_playwright_launch() -> None:
    """Asynchronously attempts a dry-run Chromium launch inside ms-playwright."""
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        await browser.close()


def _install_playwright_binaries() -> None:
    """
    Spawns Playwright auto-installer to pull Chromium into the local sandbox.

    Directs downloading progress output from Playwright's installation subprocess
    and pipes it line-by-line into the system console log.
    """
    try:
        add_log(
            "[BROWSER-INSTALL] Downloading Chromium binaries to sandbox: "
            "data/ms-playwright/..."
        )

        creationflags: int = 0x08000000 if os.name == 'nt' else 0

        process = subprocess.Popen(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=creationflags
        )

        # Read installer stdout line-by-line
        while True:
            output: str = process.stdout.readline()  # type: ignore[union-attr]
            if output == '' and process.poll() is not None:
                break
            if output:
                clean_line: str = output.strip()
                # Only log download-rich feedback lines to keep logs clean
                if "%" in clean_line or "Downloading" in clean_line:
                    add_log(f"[BROWSER-INSTALL] {clean_line}")

        rc: int | None = process.poll()
        if rc == 0:
            add_log("[BROWSER-INSTALL] Sandboxed Chromium package registered successfully.")
        else:
            add_log(f"[BROWSER-INSTALL-ERROR] Installer process exited with code {rc}")

    except Exception as exc:
        add_log(f"[BROWSER-INSTALL-ERROR] Auto-installer failed: {exc}")


# =============================================================================
# Ollama Model Downloader
# =============================================================================

def _pull_model_stream() -> None:
    """
    Streams a POST pull request from the Ollama service to download Llama 3.2 1B.

    Parses Ollama's stream chunks to evaluate byte downloads, writing progress
    percentages directly to the main header status and the console logs [1.1.2].
    """
    url: str = "http://localhost:11434/api/pull"
    payload: dict[str, Any] = {"name": "llama3.2:1b", "stream": True}

    try:
        resp: requests.Response = requests.post(url, json=payload, stream=True, timeout=1200)
        for line in resp.iter_lines():
            if line:
                data: dict = json.loads(line.decode("utf-8"))
                status: str = data.get("status", "")
                completed: int = data.get("completed", 0)
                total: int = data.get("total", 0)

                if total > 0:
                    percent: int = int((completed / total) * 100)
                    update_state_parameter("model_status", f"Downloading model... {percent}%")
                    update_state_parameter("model_download_progress", f"{percent}%")
                    # Log to console only at 10% progress intervals to avoid noise
                    if percent % 10 == 0:
                        add_log(f"[OLLAMA-PULL] Localizing 'llama3.2:1b': {percent}% completed.")
                else:
                    update_state_parameter("model_status", f"Model status: {status}")

        update_state_parameter("model_status", "Model loaded: Llama 3.2 (Sandbox)")
        update_state_parameter("model_download_progress", "")
        add_log("[OLLAMA-PULL] Localized model compilation complete.")

    except Exception as exc:
        update_state_parameter("model_status", "Failed to pull model.")
        add_log(f"[OLLAMA-ERROR] Pull task aborted: {exc}")


# =============================================================================
# Primary Pre-Flight Orchestration Entry Point
# =============================================================================

def run_preflight_checks() -> None:
    """
    Coordinative preflight loop verifying sandbox dependencies on boot.

    Executes sequential evaluations for both Ollama servers and Playwright.
    Maintains safe state update structures for GIL-free multicore runs [1.2.6, 1.2.8].
    """
    _start_local_ollama_daemon()

    # ------------------------------------------------------------------
    # Ollama readiness probe with exponential back-off.
    #
    # After spawning the daemon (which sleeps 2 s internally), the server
    # may still need additional time to bind and index models — especially
    # on first-run or slow-disk machines.  A single-shot request with a
    # 3 s timeout would permanently mark the daemon as "offline" if it
    # takes 4 seconds to become ready.  Instead, retry up to
    # _OLLAMA_READY_RETRIES times with geometrically increasing delays
    # so the total wait budget is ~14 s (2+4+8) before giving up.
    # ------------------------------------------------------------------
    _OLLAMA_READY_RETRIES:    int   = 3
    _OLLAMA_READY_BACKOFF_S:  float = 2.0
    _OLLAMA_TAGS_TIMEOUT_S:   float = 5.0
    _OLLAMA_TAGS_URL:         str   = "http://localhost:11434/api/tags"

    add_log("[BOOT] Verifying local model files...")

    ollama_reached: bool = False

    for attempt in range(_OLLAMA_READY_RETRIES):
        try:
            resp: requests.Response = requests.get(
                _OLLAMA_TAGS_URL,
                timeout=_OLLAMA_READY_BACKOFF_S + _OLLAMA_TAGS_TIMEOUT_S,
            )

            if resp.status_code == 200:
                models: list[str] = [
                    m.get("name", "") for m in resp.json().get("models", [])
                ]
                if not any("llama3.2:1b" in m or "llama3.2" in m for m in models):
                    add_log(
                        "[OLLAMA] Model 'llama3.2:1b' missing. "
                        "Starting localized background pull (1.3 GB)..."
                    )
                    _pull_model_stream()
                else:
                    update_state_parameter(
                        "model_status",
                        "Model loaded: Llama 3.2 (Sandbox)",
                    )
                    add_log(
                        "[OLLAMA] Local Llama 3.2 (1B) model verified "
                        "inside sandbox."
                    )
                ollama_reached = True
                break

            # Non-200 but reachable — log warning and retry.
            add_log(
                f"[BOOT-WARN] Ollama API returned status "
                f"{resp.status_code} on attempt {attempt + 1}. Retrying..."
            )

        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout):
            wait: float = _OLLAMA_READY_BACKOFF_S * (2 ** attempt)
            add_log(
                f"[BOOT] Ollama not ready (attempt {attempt + 1}/"
                f"{_OLLAMA_READY_RETRIES}). "
                f"Retrying in {wait:.0f}s..."
            )
            time.sleep(wait)

    if not ollama_reached:
        update_state_parameter(
            "model_status",
            "Ollama daemon offline. AI disabled.",
        )
        add_log(
            "[BOOT-WARN] Ollama unreachable after "
            f"{_OLLAMA_READY_RETRIES} attempts. "
            "Inference will return fallback default values."
        )

    add_log("[BOOT] Checking sandboxed Chromium packages...")
    try:
        # Run test launch on a local, isolated event loop
        asyncio.run(_test_playwright_launch())
        add_log("[BROWSER] Localized Playwright Chromium binaries verified.")
    except Exception:
        add_log("[BROWSER-WARN] Localized Chromium missing. Invoking background installer...")
        _install_playwright_binaries()

    # Preflight finished. Unlock dashboard execution [1.1.2]
    update_state_parameter("setup_completed", True)
    add_log("[BOOT-COMPLETE] Pre-flight tasks complete. Operator control unlocked.")