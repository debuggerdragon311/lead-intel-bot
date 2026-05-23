"""Thread-safe global state management.

Provides a centralized, explicitly synchronized state store for a modular
monolithic desktop application running on a free-threaded, GIL-unlocked
Python 3.14t runtime (python3.14t).

GIL-free concurrency context:
    CPython 3.14t disables the Global Interpreter Lock, meaning multiple OS
    threads can execute Python bytecode simultaneously on separate CPU cores.
    Without the GIL acting as an implicit serialization barrier, any shared
    mutable object -- dict, list, or otherwise -- is subject to real data
    races: concurrent reads and writes can interleave at the machine
    instruction level, producing torn reads, lost writes, or a corrupted
    internal hash table state.

    Every public function in this module acquires STATE_LOCK before touching
    SYSTEM_STATE. This turns each logical operation into an atomic, mutually
    exclusive critical section, enforcing a strict single-writer / blocked-reader
    model that is safe under full multicore parallelism.
"""

import copy
import threading
import time
from typing import Any


# =============================================================================
# Global Mutual Exclusion Lock
#
# A single threading.Lock() guards all access to SYSTEM_STATE. On a GIL-free
# runtime, this is the sole mechanism preventing simultaneous writes from
# multiple threads from corrupting the dict's internal structure or producing
# inconsistent partial reads by a consumer thread.
#
# threading.Lock() is the lightest primitive available: it is non-reentrant
# and has no per-thread overhead beyond the acquire/release calls themselves.
# =============================================================================

STATE_LOCK: threading.Lock = threading.Lock()


# =============================================================================
# System State Store
#
# A single dict centralizes all mutable runtime state. Keeping state in one
# place makes the critical sections small and the locking strategy simple:
# one lock, one dict, no nested acquisition, no deadlock risk.
#
# The underscore prefix signals that external modules must never read or
# write this dict directly. All access goes through the exported helpers
# below, which guarantee lock acquisition on every operation.
# =============================================================================

_SYSTEM_STATE: dict[str, Any] = {
    # Whether the main background worker loop is currently active.
    "is_running": False,

    # List of company names or identifiers queued for processing.
    "companies": [],

    # Append-only event log consumed by the UI. Capped at 100 entries.
    "logs": ["[SYSTEM-BOOT] Sandboxed GIL-Unlocked Monitor Active. Initializing..."],

    # Human-readable status string for the local Ollama model state.
    "model_status": "Checking local sandbox...",

    # Holds a progress indicator string during model download operations.
    "model_download_progress": "",

    # Set to True once the first-run setup sequence has completed.
    "setup_completed": False,
}

# Maximum number of log entries retained in memory before oldest are evicted.
_LOG_CAPACITY: int = 100


# =============================================================================
# Thread-Safe Helper Functions
# =============================================================================

def add_log(message: str) -> None:
    """
    Append a timestamped log entry to the shared event log.

    A [HH:MM:SS] prefix derived from the local wall clock is prepended to
    the caller-supplied message before storage. If the log list has reached
    _LOG_CAPACITY, the oldest entry (index 0) is popped before appending,
    keeping memory use bounded regardless of runtime duration.

    Thread safety:
        STATE_LOCK is acquired for the entire read-modify-write sequence.
        Without this, two threads calling add_log() concurrently could both
        pass the capacity check before either has popped an element, leading
        to duplicate pops or an oversized list on a GIL-free runtime.

    Args:
        message: Raw log text. The timestamp prefix is added internally.
    """
    timestamp: str        = time.strftime("[%H:%M:%S]")
    entry:     str        = f"{timestamp} {message}"

    # Acquire the lock before any mutation. On python3.14t this is the only
    # barrier preventing a concurrent thread from writing to the list
    # simultaneously and corrupting its internal length counter or item array.
    with STATE_LOCK:
        if len(_SYSTEM_STATE["logs"]) >= _LOG_CAPACITY:
            # Evict the oldest entry to keep the list within its capacity
            # bound. This pop and append must be atomic from the perspective
            # of all other threads, hence both happen inside the lock.
            _SYSTEM_STATE["logs"].pop(0)

        _SYSTEM_STATE["logs"].append(entry)


def read_state_copy() -> dict[str, Any]:
    """
    Return a deep copy of the current system state.

    Callers (e.g., a Flask response handler on one thread) receive a
    snapshot dict that is fully decoupled from the live _SYSTEM_STATE. This
    prevents data races or RuntimeError exceptions during serialization
    if a background worker thread modifies nested lists/dicts inside
    _SYSTEM_STATE (such as "companies" or "logs") while Flask is converting
    the returned state to JSON.

    Thread safety:
        STATE_LOCK is held for the duration of copy.deepcopy.
        This ensures we get a consistent snapshot of the entire state tree.

    Returns:
        A new dict containing a deep copy of _SYSTEM_STATE at the instant
        of the call.
    """
    # Hold the lock for the full copy construction so the source dict
    # and its nested structures cannot be mutated mid-copy on a GIL-free
    # interpreter core.
    with STATE_LOCK:
        return copy.deepcopy(_SYSTEM_STATE)


def update_state_parameter(key: str, value: Any) -> None:
    """
    Set a single key in the shared system state to the given value.

    Thread safety:
        STATE_LOCK is acquired before the assignment. On a GIL-free runtime
        a dict __setitem__ is not atomic: it involves a hash lookup, a
        possible resize/rehash, and a pointer write. Acquiring the lock
        before the call serializes all writers and prevents a concurrent
        resize from racing with a simultaneous read in read_state_copy().

    Args:
        key:   The _SYSTEM_STATE key to update. Must be an existing key;
               introducing new keys at runtime is not prevented but should
               be avoided to keep state shape predictable.
        value: The new value to assign. Any type is accepted; callers are
               responsible for type consistency with the initial schema.
    """
    # Serialize to write. No other thread can enter a `with STATE_LOCK`
    # block until this assignment completes and the lock is released.
    with STATE_LOCK:
        _SYSTEM_STATE[key] = value