"""Application sandbox and resource path configuration.

Handles absolute directory sandboxing, resource path resolution, and
environment variable overrides for both local development and compiled
PyInstaller (frozen) environments. Executes and provisions all required
directories immediately upon import.

Frozen detection logic:
    PyInstaller sets sys.frozen = True and sys.executable to the compiled
    binary path. In dev, the project root is derived from the physical
    location of this source file (__file__), not the shell's CWD. This
    ensures sandbox directories are always created under the real project
    root regardless of which directory the developer invokes Python from.

PyInstaller resource extraction:
    Bundled assets are unpacked at runtime into a temporary directory
    exposed via sys._MEIPASS. resource_path() abstracts this so callers
    never need to branch on frozen state themselves.
"""

import os
import sys


# =============================================================================
# Resource Path Resolution
# =============================================================================

def resource_path(relative_path: str) -> str:
    """
    Resolve the absolute path to a bundled resource file.

    In a PyInstaller-frozen binary, assets are extracted to a temp dir
    referenced by sys._MEIPASS. In development, paths are resolved
    relative to the current working directory.

    Args:
        relative_path: Path to the resource, relative to the project root
                       or the PyInstaller extraction root.

    Returns:
        Absolute path string suitable for open(), os.path.exists(), etc.

    Example:
        icon = resource_path("assets/icon.png")
    """
    base: str = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base, relative_path)


# =============================================================================
# Base Directory Detection
# =============================================================================

def _resolve_base_dir() -> str:
    """
    Determine the application root directory at runtime.

    Frozen (PyInstaller):
        sys.executable points to the compiled binary on the user's disk.
        Its parent directory is the stable root; all sibling data folders
        are created there, co-located with the binary.

    Development:
        The project root is derived from the physical path of this source
        file rather than the shell's Current Working Directory (CWD).

        Layout on disk:
            <project_root>/
                core/
                    config.py   <-- __file__ resolves to here
                data/
                ...

        Resolution chain:
            __file__
              -> os.path.abspath()   : canonical absolute path of config.py
              -> os.path.dirname() x1: resolves to  <project_root>/core/
              -> os.path.dirname() x2: resolves to  <project_root>/

        This guarantees the correct root regardless of which directory the
        developer's terminal session was launched from, eliminating the
        class of bug where `./data/` is created in a foreign directory.

    Returns:
        Absolute path string of the application root directory.
    """
    if getattr(sys, "frozen", False):
        return os.path.abspath(os.path.dirname(sys.executable))

    this_file:    str = os.path.abspath(__file__)
    core_dir:     str = os.path.dirname(this_file)
    project_root: str = os.path.dirname(core_dir)
    return project_root


# =============================================================================
# Path Constants
# =============================================================================

BASE_DIR:        str = _resolve_base_dir()
DATA_DIR:        str = os.path.join(BASE_DIR, "data")
PLAYWRIGHT_PATH: str = os.path.join(DATA_DIR, "ms-playwright")
OLLAMA_PATH:     str = os.path.join(DATA_DIR, "ollama", "models")
REPORTS_PATH:    str = os.path.join(DATA_DIR, "reports")


# =============================================================================
# Environment Overrides
#
# Must be set at module scope, before any downstream module imports
# Playwright. This redirects browser package installation away from the
# OS-level user profile and into the application's own data sandbox.
# =============================================================================

os.environ["PLAYWRIGHT_BROWSERS_PATH"] = PLAYWRIGHT_PATH


# =============================================================================
# Directory Auto-Provisioning
# =============================================================================

def _initialize_sandbox() -> None:
    """
    Ensure all required application directories exist on disk.

    Uses exist_ok=True so this is safe to call on every import, including
    on first run where no directories have been created yet. makedirs()
    creates the full path hierarchy in a single call, so nested paths
    such as OLLAMA_PATH are handled without manual parent creation.

    Raises:
        OSError: If a directory cannot be created due to a permissions
                 error or a path conflict with an existing file.
    """
    sandbox_paths: list[str] = [
        DATA_DIR,
        PLAYWRIGHT_PATH,
        OLLAMA_PATH,
        REPORTS_PATH,
    ]

    for path in sandbox_paths:
        os.makedirs(path, exist_ok=True)


_initialize_sandbox()