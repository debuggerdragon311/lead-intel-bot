"""Flask REST API server and pipeline orchestration layer.

Responsibilities:
    1. Serve the CRT Operator Dashboard HTML via GET /.
    2. Expose a live JSON state feed at GET /status, consumed by the
       dashboard's 1500 ms AJAX poll loop.
    3. Accept a pipeline execution request at POST /run, validate it, and
       spawn the scraping + AI extraction loop on a daemon thread.
    4. Stream a CSV export of current results at GET /export/csv.

Concurrency model:
    The application runs on a free-threaded Python 3.14t interpreter with
    the GIL disabled. Three concurrent OS threads operate simultaneously:

        - Flask request thread   : handles incoming HTTP requests
        - Background worker thread: runs the async scraping/AI loop
        - (optional) Ollama thread: Ollama's own HTTP server process

    Every read or write to _SYSTEM_STATE is serialised behind STATE_LOCK.
    A critical invariant maintained throughout this module:

        STATE_LOCK must NEVER be held when calling add_log().

    add_log() acquires STATE_LOCK internally. Since threading.Lock() is
    non-reentrant, calling add_log() while already holding STATE_LOCK
    would cause an immediate deadlock. The pattern used consistently here
    is: acquire lock -> extract/mutate -> release lock -> call add_log().
"""

import asyncio
import csv
import io
import os
import threading
import time
from typing import Any

from flask import Flask, Response, jsonify, render_template_string, request

from core.config import DATA_DIR
from core.state  import (
    _SYSTEM_STATE,   # direct mutable access required for sub-dict writes
    STATE_LOCK,
    add_log,
    read_state_copy,
    update_state_parameter,
)
from core.scraper     import harvest_company_data
from core.ai          import query_local_ollama
from core.ui_template import HTML_TEMPLATE


# =============================================================================
# Flask Application Instance
# =============================================================================

app: Flask = Flask(__name__)

# Silence Flask's default request logger to keep the operator console feed
# clean; all meaningful events are written via add_log() instead.
import logging as _logging
_logging.getLogger("werkzeug").setLevel(_logging.ERROR)


# =============================================================================
# Route: GET /
# Renders the static CRT dashboard HTML template.
# =============================================================================

@app.route("/", methods=["GET"])
def index() -> str:
    """
    Serve the Operator Dashboard.

    render_template_string() renders HTML_TEMPLATE as a Jinja2 template.
    The template contains no Jinja2 directives; all live data is fetched
    client-side via /status, so this route is a pure static HTML delivery.

    Returns:
        Rendered HTML string response.
    """
    return render_template_string(HTML_TEMPLATE)


# =============================================================================
# Route: GET /status
# Returns a thread-safe snapshot of the current system state as JSON.
# =============================================================================

@app.route("/status", methods=["GET"])
def status() -> Response:
    """
    Return a shallow-copied snapshot of SYSTEM_STATE as a JSON payload.

    Uses read_state_copy() so the Flask thread never iterates the live
    dict while the background worker thread may be mutating it. The copy
    is decoupled from _SYSTEM_STATE and safe to serialize without holding
    the lock during jsonify's traversal.

    Returns:
        Flask JSON Response with the full state snapshot.
    """
    state_snapshot: dict[str, Any] = read_state_copy()
    return jsonify(state_snapshot)


# =============================================================================
# Route: POST /run
# Validates the request, then spawns the background pipeline on a daemon
# thread so the HTTP response returns immediately without blocking.
# =============================================================================

@app.route("/run", methods=["POST"])
def run() -> tuple[Response, int]:
    """
    Accept a pipeline execution request from the dashboard.

    Expected JSON body:
        { "targets": ["domain1.com", "company-name", ...] }

    Pre-flight guards (all checked under STATE_LOCK):
        1. setup_completed must be True before any scan is allowed.
        2. is_running must be False; duplicate submissions are rejected.
        3. The targets list must contain at least one entry.

    On success, a daemon thread is spawned and the route returns
    immediately with {"success": true} so the browser does not block.

    Returns:
        Tuple of (JSON Response, HTTP status code).
    """
    # ------------------------------------------------------------------
    # Guard 1 & 2: read volatile flags atomically under the lock.
    # We extract both values in one critical section to avoid a TOCTOU
    # race where is_running changes between two separate lock acquisitions.
    # ------------------------------------------------------------------
    with STATE_LOCK:
        setup_done: bool = _SYSTEM_STATE["setup_completed"]
        is_running: bool = _SYSTEM_STATE["is_running"]

    if not setup_done:
        return jsonify({
            "success": False,
            "message": "Pre-flight installs are active. Please wait.",
        }), 400

    if is_running:
        return jsonify({
            "success": False,
            "message": "A scan is already active. Wait for it to finish.",
        }), 400

    # ------------------------------------------------------------------
    # Guard 3: validate payload.
    # request.get_json() returns None if Content-Type is missing or body
    # is malformed; the or {} fallback prevents an AttributeError on None.
    # ------------------------------------------------------------------
    payload:        dict        = request.get_json(silent=True) or {}
    companies_list: list[str]   = payload.get("targets", [])

    if not companies_list:
        return jsonify({
            "success": False,
            "message": "Targets list cannot be empty.",
        }), 400

    # ------------------------------------------------------------------
    # Spawn the background pipeline on a daemon thread.
    # daemon=True ensures the thread does not prevent interpreter shutdown
    # if the application window is closed before the scan completes.
    # ------------------------------------------------------------------
    thread: threading.Thread = threading.Thread(
        target=start_background_loop,
        args=(companies_list,),
        name="pipeline-worker",
    )
    thread.daemon = True
    thread.start()

    add_log(
        f"[SERVER] Pipeline dispatched for "
        f"{len(companies_list)} target(s) on thread '{thread.name}'."
    )

    return jsonify({"success": True}), 200


# =============================================================================
# Route: GET /export/csv
# Streams a CSV export of the current extraction results as an attachment.
# =============================================================================

@app.route("/export/csv", methods=["GET"])
def export_csv() -> Response:
    """
    Export current results as a downloadable CSV file.

    Acquires STATE_LOCK for the minimum time required to snapshot the
    companies list, then releases it before performing the (non-mutating)
    CSV serialisation. This prevents the worker thread from being blocked
    behind a slow I/O or encoding operation.

    Returns:
        Flask Response with Content-Disposition: attachment header and
        text/csv content type, prompting the browser to save the file.
    """
    # Snapshot the companies list atomically; release lock immediately.
    with STATE_LOCK:
        companies_snapshot: list[dict] = list(_SYSTEM_STATE["companies"])

    output: io.StringIO = io.StringIO()
    writer: csv.writer  = csv.writer(output)  # type: ignore[type-arg]

    writer.writerow(["Domain", "Status", "Founder / CEO", "Tech Stack", "Value Proposition"])

    for company in companies_snapshot:
        writer.writerow([
            company.get("domain",  ""),
            company.get("status",  ""),
            company.get("founder", ""),
            company.get("tech",    ""),
            company.get("need",    ""),
        ])

    csv_payload: str = output.getvalue()

    return Response(
        csv_payload,
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=company_intel_report.csv",
        },
    )


# =============================================================================
# Async Worker Job
# Core pipeline coroutine: scrapes each company, runs AI extraction,
# writes results back to shared state, and saves a timestamped CSV backup.
# =============================================================================

async def async_worker_job(companies_list: list[str]) -> None:
    """
    Execute the full scrape + AI extraction pipeline for all targets.

    Lifecycle per target:
        QUEUED  ->  SCANNING  ->  AI-EXTRACTING  ->  FINISHED | ERROR

    Each status transition is serialised behind STATE_LOCK. add_log()
    is always called AFTER releasing the lock to avoid deadlock (add_log
    internally acquires the same non-reentrant STATE_LOCK).

    After all targets complete, a timestamped CSV backup is written to
    DATA_DIR/reports/ and is_running is reset to False.

    Args:
        companies_list: List of raw domain or company name strings
                        received from the POST /run payload.
    """

    # ------------------------------------------------------------------
    # Phase 0: Initialise all company records and set is_running = True.
    # All insertions happen in one critical section so the dashboard
    # never sees a partial company list.
    # ------------------------------------------------------------------
    with STATE_LOCK:
        _SYSTEM_STATE["companies"] = [
            {
                "domain":  name,
                "status":  "QUEUED",
                "founder": "",
                "tech":    "",
                "need":    "",
            }
            for name in companies_list
        ]
        _SYSTEM_STATE["is_running"] = True

    add_log(
        f"[PIPELINE] Initialised {len(companies_list)} target(s). "
        "Pipeline is now ACTIVE."
    )

    # ------------------------------------------------------------------
    # Phase 1: Process each target sequentially.
    # Sequential processing avoids saturating the local Ollama daemon
    # with concurrent inference requests, which would thrash RAM on
    # consumer-grade hardware running a 1.3 GB model.
    # ------------------------------------------------------------------
    for index, name in enumerate(companies_list):

        # --- SCANNING: update status, then log outside the lock -------
        with STATE_LOCK:
            _SYSTEM_STATE["companies"][index]["status"] = "SCANNING"

        add_log(f"[PIPELINE] [{index + 1}/{len(companies_list)}] Scanning: {name}")

        # --- Web harvest (async, does not hold the lock) --------------
        raw_text: str = await harvest_company_data(name)

        if not raw_text.strip():
            # Scraping produced nothing usable — mark as error and skip.
            with STATE_LOCK:
                _SYSTEM_STATE["companies"][index]["status"] = "ERROR"

            add_log(
                f"[PIPELINE] [{index + 1}/{len(companies_list)}] "
                f"WARN: Empty scrape payload for '{name}'. Marking ERROR."
            )
            continue

        # --- AI-EXTRACTING: update status, then log outside lock ------
        with STATE_LOCK:
            _SYSTEM_STATE["companies"][index]["status"] = "AI-EXTRACTING"

        add_log(
            f"[PIPELINE] [{index + 1}/{len(companies_list)}] "
            f"Running Ollama inference for '{name}'..."
        )

        # --- Ollama inference (synchronous blocking call) -------------
        # query_local_ollama() is a synchronous HTTP call. Running it
        # directly inside the async coroutine is acceptable here because
        # this coroutine executes on a dedicated event loop that owns the
        # entire worker thread — it blocks only the worker thread, never
        # the Flask request thread.
        extracted: dict[str, str] = query_local_ollama(raw_text)

        # --- FINISHED: commit all extracted fields atomically ---------
        # Ensure bare company names without a TLD receive .com suffix
        # so the domain column always holds a valid-looking URL label.
        domain_label: str = (
            name if "." in name else f"{name}.com"
        )

        with STATE_LOCK:
            _SYSTEM_STATE["companies"][index].update({
                "status":  "FINISHED",
                "domain":  domain_label,
                "founder": extracted.get("FOUNDER", "Unknown"),
                "tech":    extracted.get("TECH",    "Unknown"),
                "need":    extracted.get("NEED",    "Unknown"),
            })

        add_log(
            f"[PIPELINE] [{index + 1}/{len(companies_list)}] "
            f"DONE: {domain_label} — "
            f"Founder: {extracted.get('FOUNDER', 'Unknown')}"
        )

    # ------------------------------------------------------------------
    # Phase 2: Automated workspace backup.
    # Write a timestamped CSV to DATA_DIR/reports/ so results survive
    # an application restart. The file name embeds the epoch timestamp
    # for chronological sorting in the file system.
    # ------------------------------------------------------------------
    _write_report_backup()

    # ------------------------------------------------------------------
    # Phase 3: Reset running flag so the dashboard re-enables the button.
    # ------------------------------------------------------------------
    with STATE_LOCK:
        _SYSTEM_STATE["is_running"] = False

    add_log("[PIPELINE] All targets processed. Pipeline is now IDLE.")


# =============================================================================
# Report Backup Helper
# Writes a physical CSV to the reports sandbox directory. Called at the
# end of async_worker_job after all targets have been processed.
# =============================================================================

def _write_report_backup() -> None:
    """
    Persist the current extraction results as a timestamped CSV file.

    The report is written to DATA_DIR/reports/ (sandboxed by core.config,
    guaranteed to exist via _initialize_sandbox()). The filename embeds
    the current local date-time so multiple runs produce distinct files
    that sort chronologically in any file browser.

    File naming: report_YYYYMMDD-HHMMSS.csv

    Thread safety:
        STATE_LOCK is held only for the initial snapshot copy. The file
        I/O itself runs outside the lock so the worker thread does not
        block the Flask request thread during a slow write.
    """
    # Snapshot the companies list before any file I/O touches the lock.
    with STATE_LOCK:
        companies_snapshot: list[dict] = list(_SYSTEM_STATE["companies"])

    timestamp:   str = time.strftime("%Y%m%d-%H%M%S")
    report_dir:  str = os.path.join(DATA_DIR, "reports")
    report_path: str = os.path.join(report_dir, f"report_{timestamp}.csv")

    try:
        with open(report_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow([
                "Domain", "Status", "Founder / CEO",
                "Tech Stack", "Value Proposition",
            ])
            for company in companies_snapshot:
                writer.writerow([
                    company.get("domain",  ""),
                    company.get("status",  ""),
                    company.get("founder", ""),
                    company.get("tech",    ""),
                    company.get("need",    ""),
                ])

        add_log(f"[BACKUP] Report saved to: {report_path}")

    except OSError as exc:
        add_log(f"[BACKUP] ERROR: Could not write report — {exc}")


# =============================================================================
# Background Loop Bootstrap
# Creates an isolated event loop on the daemon thread and drives the
# async pipeline coroutine to completion inside it.
# =============================================================================

def start_background_loop(companies_list: list[str]) -> None:
    """
    Bootstrap an asyncio event loop on the current daemon thread and run
    async_worker_job() to completion inside it.

    Why a new event loop per invocation?
        Flask's WSGI request threads have no event loop associated with
        them by default. asyncio.get_event_loop() on Python 3.10+ raises
        DeprecationWarning (and on 3.12+ raises RuntimeError) when called
        from a non-main thread with no current loop. Creating a fresh loop
        explicitly via asyncio.new_event_loop() and registering it with
        asyncio.set_event_loop() avoids both the warning and the error,
        and gives the worker thread complete ownership of its loop.

    The loop is closed in a finally block to release file descriptor and
    selector resources regardless of whether the coroutine completes
    normally or raises an unhandled exception.

    Args:
        companies_list: List of raw target strings forwarded from /run.
    """
    loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(async_worker_job(companies_list))
    except Exception as exc:
        # Surface unexpected crashes to the operator console so they are
        # not silently swallowed inside the daemon thread.
        add_log(f"[PIPELINE] CRITICAL: Worker loop terminated unexpectedly — {exc}")
    finally:
        loop.close()
        asyncio.set_event_loop(None)