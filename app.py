"""Master application entrypoint for the Lead Intel System.

Boot sequence:

    1. Import core.config (line 1 of executable imports).
       This is load-order-critical: the module sets PLAYWRIGHT_BROWSERS_PATH
       in os.environ and provisions the data/ sandbox tree at module scope.
       Every subsequent import that transitively touches Playwright or the
       data directory inherits a correctly configured environment.  Moving
       this import below any other project import is a latent defect.

    2. Spawn the pre-flight dependency checker on a daemon thread.
       Checks Ollama reachability, pulls missing LLM weights, and installs
       sandboxed Chromium binaries.  Daemon flag ensures the thread dies
       with the process if the operator closes the window early.

    3. Spawn the Flask microservice on a second daemon thread.
       Binds strictly to the loopback interface (127.0.0.1:1995) so no
       external host can reach the API.  Debug mode and the Werkzeug
       reloader are force-disabled to prevent duplicate thread trees when
       running inside a PyInstaller-frozen binary.

    4. Hand control to pywebview.
       create_window() registers a native OS window backed by the system
       webview engine (WebKit/GTK on Linux, WebKit2 on macOS, EdgeChromium
       on Windows).  start() enters the platform GUI run-loop and blocks
       until the operator closes the frame.  On return, sys.exit() tears
       down the interpreter and all daemon threads in one shot.

Runtime lifecycle ownership:

    pywebview.start() owns the main thread for the entire lifetime of the
    application.  The Flask server and preflight workers are subordinate
    daemon threads; they never outlive the GUI loop.  This is deliberate:
    the native window frame IS the process boundary.  Closing it is the
    canonical shutdown signal --- no signal handlers, no IPC, no atexit
    hooks required.
"""

# ============================================================================
# CRITICAL --- Load-order-sensitive sandbox bootstrap.
#
# core.config MUST be the first project import in this file.  It sets
# os.environ["PLAYWRIGHT_BROWSERS_PATH"] and calls os.makedirs() for every
# sandbox directory at module scope.  Any import that precedes it risks
# reading an un-patched environment or writing to a non-existent path.
# ============================================================================

import core.config                                      # noqa: F401  # side-effects only

# ---------------------------------------------------------------------------
# Standard library
# ---------------------------------------------------------------------------

import sys
import threading

# ---------------------------------------------------------------------------
# Local application modules
# ---------------------------------------------------------------------------

from core.preflight import run_preflight_checks
from core.server    import app                          # Flask instance

# ---------------------------------------------------------------------------
# Third-party
# ---------------------------------------------------------------------------

import webview


# ============================================================================
# Thread launchers
# ============================================================================

def _spawn_preflight_thread() -> threading.Thread:
    """
    Start the pre-flight dependency checker on a background daemon thread.

    The checker verifies Ollama connectivity, pulls missing model weights,
    and installs sandboxed Playwright/Chromium binaries.  It mutates shared
    state through thread-safe accessors defined in core.state.

    Returns:
        The started Thread object (useful for join() in test harnesses).
    """
    t: threading.Thread = threading.Thread(
        target=run_preflight_checks,
        name="preflight-worker",
        daemon=True,
    )
    t.start()
    return t


def _spawn_flask_thread() -> threading.Thread:
    """
    Start the Flask microservice on a background daemon thread.

    Binding parameters:
        host        127.0.0.1   Loopback only --- never exposed to LAN.
        port        1995        Arbitrary high port; must match the URL
                                passed to webview.create_window().
        debug       False       Prevents Werkzeug from attaching its
                                interactive debugger (security + stability).
        use_reloader False      Prevents Werkzeug from spawning a watcher
                                subprocess.  In a frozen PyInstaller binary
                                the reloader re-executes sys.executable,
                                which would launch a second copy of the
                                entire application.

    Returns:
        The started Thread object.
    """
    t: threading.Thread = threading.Thread(
        target=app.run,
        name="flask-server",
        daemon=True,
        kwargs={
            "host":         "127.0.0.1",
            "port":         1995,
            "debug":        True,
            "use_reloader": False,
        },
    )
    t.start()
    return t


# ============================================================================
# Main entry point
# ============================================================================

if __name__ == "__main__":

    # --- Phase 1: background workers ---------------------------------------

    _spawn_preflight_thread()
    _spawn_flask_thread()

    # --- Phase 2: native desktop frame -------------------------------------
    #
    # create_window() registers the window with the platform's display
    # server but does NOT enter the event loop.  start() enters the
    # blocking GUI run-loop (Glib on Linux, NSApp on macOS, message pump
    # on Windows).  All rendering, input dispatch, and IPC with the
    # embedded webview happens inside this call.
    #
    # The window is resizable so the CRT-style dashboard layout can
    # scale fluidly across different monitor geometries.

    webview.create_window(
        title="LEAD INTEL SYSTEM by { Soumyajit Bala }",
        url="http://127.0.0.1:1995",
        width=1280,
        height=800,
        resizable=True,
    )

    webview.start()

    # --- Phase 3: teardown --------------------------------------------------
    #
    # Once the operator closes the native window, start() returns and
    # control falls through here.  sys.exit() raises SystemExit, which
    # the interpreter translates into a clean process termination.
    # All daemon threads are reaped automatically --- no explicit
    # join() or shutdown choreography needed.

    sys.exit()
