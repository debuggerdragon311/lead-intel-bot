"""Local AI entity extraction via Ollama.

Submits raw scraped text to a locally running Ollama daemon and extracts
three structured fields using a constrained, deterministic prompt:

    FOUNDER  -- Full name of the company founder or CEO.
    TECH     -- Comma-separated list of the top 3 technologies or frameworks.
    NEED     -- One sentence describing the core problem the business solves.

Model & runtime assumptions:
    Target model : llama3.2:1b (Meta Llama 3.2, 1.3 GB quantized variant).
    Ollama must be running on the local host at the default port (11434).
    The model is invoked with temperature=0.0 and top_p=0.1 to suppress
    creative variance and produce strictly reproducible extractions. A
    4096-token context window (num_ctx) is the ceiling for the combined
    system prompt + scraped payload to protect resident memory footprint.

Parsing resilience:
    Small local LLMs frequently deviate from the requested output format:
    they may add Markdown fences, vary label casing (Founder: vs FOUNDER:),
    or emit preamble sentences before the structured block. _parse_ollama_
    response() addresses each of these failure modes independently using
    case-insensitive regex matching on a per-line scan so that any partial
    output that does contain valid key-value pairs is recovered correctly.
"""

import re
import requests

from core.state import add_log


# =============================================================================
# Module-Level Constants
# =============================================================================

# Ollama local HTTP generation endpoint. Assumes default installation port.
_OLLAMA_ENDPOINT: str = "http://localhost:11434/api/generate"

# Quantized 1B parameter Llama 3.2 variant. Balances extraction quality
# against VRAM / RAM footprint on consumer-grade developer machines.
_MODEL_ID: str = "llama3.2:1b"

# HTTP request timeout in seconds. Ollama cold-loads the model on first
# call; 120 s gives the daemon enough time to page the weights from disk.
_REQUEST_TIMEOUT_S: int = 120

# Inference hyper-parameters. temperature=0.0 forces greedy decoding for
# strictly deterministic output. top_p=0.1 further collapses the sampling
# distribution as a secondary guard. num_ctx caps the KV-cache size.
_TEMPERATURE:  float = 0.0
_TOP_P:        float = 0.1
_NUM_CTX:      int   = 4096

# Output keys present in both the prompt template and the parsed result dict.
_KEY_FOUNDER: str = "FOUNDER"
_KEY_TECH:    str = "TECH"
_KEY_NEED:    str = "NEED"

# Safe fallback value returned for any key that is absent from model output.
_UNKNOWN: str = "Unknown"

# System prompt template. The {scraped_text} placeholder is substituted at
# call time with the raw payload from the web scraping pipeline.
_SYSTEM_PROMPT_TEMPLATE: str = """\
You are a business intelligence extraction engine. Analyze the raw text \
provided and extract exactly three data points. Output ONLY the three lines \
below, with no introduction, no commentary, no markdown backticks, no \
pleasantries, and no additional text before or after:

FOUNDER: <full name of the founder or CEO>
TECH: <comma-separated list of the top 3 technologies or frameworks mentioned>
NEED: <one concise sentence summarizing the core problem the business solves>

Rules:
- If a value cannot be determined from the text, write exactly: Unknown
- Do not invent or hallucinate values that are not present in the source text.
- Do not wrap output in code fences or markdown.
- Output exactly three lines. No more. No less.

Source text to analyze:
\"\"\"
{scraped_text}
\"\"\"\
"""


# =============================================================================
# Internal Parser
# =============================================================================

def _parse_ollama_response(raw_output: str) -> dict[str, str]:
    """
    Parse structured key-value pairs from raw Ollama model output.

    Iterates the output line by line and applies a case-insensitive regex
    to each line to match labels of the form "FOUNDER:", "TECH:", "NEED:"
    and their lowercase or mixed-case variants. The value following the
    colon is stripped of leading/trailing whitespace, Markdown backtick
    characters, and trailing commas.

    Any key that is absent from the model output -- either because the
    model omitted it entirely or because the line was malformed -- is
    defaulted to _UNKNOWN ("Unknown") so the caller always receives a
    fully populated dict regardless of model compliance.

    Args:
        raw_output: The raw response string from the Ollama API.

    Returns:
        A dict with exactly three keys: "FOUNDER", "TECH", "NEED".
        Each value is a stripped string or "Unknown".
    """
    # Initialize all keys to the fallback so partial outputs still produce
    # a complete result dict without KeyError risk in the caller.
    result: dict[str, str] = {
        _KEY_FOUNDER: _UNKNOWN,
        _KEY_TECH:    _UNKNOWN,
        _KEY_NEED:    _UNKNOWN,
    }

    # One compiled pattern per key. re.IGNORECASE handles casing variance.
    # The value group captures everything after the colon on the same line.
    patterns: dict[str, re.Pattern[str]] = {
        _KEY_FOUNDER: re.compile(r"^\s*founder\s*:\s*(.+)$",  re.IGNORECASE),
        _KEY_TECH:    re.compile(r"^\s*tech\s*:\s*(.+)$",     re.IGNORECASE),
        _KEY_NEED:    re.compile(r"^\s*need\s*:\s*(.+)$",     re.IGNORECASE),
    }

    for line in raw_output.splitlines():
        for key, pattern in patterns.items():
            match: re.Match[str] | None = pattern.match(line)
            if match:
                raw_value: str = match.group(1)

                # Strip markdown backticks, trailing commas, and whitespace.
                # Small models frequently wrap values in `backticks` or add
                # a trailing comma when mimicking JSON-like output.
                clean_value: str = (
                    raw_value
                    .strip()
                    .strip("`")
                    .rstrip(",")
                    .strip()
                )

                # Only store a non-empty extraction; keep the fallback if
                # the model emitted the label but left the value blank.
                if clean_value:
                    result[key] = clean_value

                # Each key appears at most once; break the inner loop once
                # a match is found for this line to avoid double-assignment.
                break

    return result


# =============================================================================
# Primary Entry Point
# =============================================================================

def query_local_ollama(scraped_text: str) -> dict[str, str]:
    """
    Submit scraped text to the local Ollama daemon and extract entities.

    Builds a deterministic, constrained prompt around the provided scraped
    text, sends it to the Ollama /api/generate endpoint as a non-streaming
    POST request, and parses the structured response into a three-key dict.

    The request uses greedy decoding (temperature=0.0, top_p=0.1) to
    eliminate stochastic variance between runs on the same input, ensuring
    reproducible extraction results in the production pipeline.

    Args:
        scraped_text: Raw concatenated text block from the scraping pipeline.
                        May contain noise, HTML artefacts, or duplicate lines;
                        the model prompt instructs the LLM to ignore irrelevant
                        content and extract only the three named fields.

    Returns:
        A dict with keys "FOUNDER", "TECH", "NEED". Each value is a
        non-empty string or "Unknown" if extraction was not possible.
        Returns a fully-populated fallback dict on any request failure.
    """
    _FALLBACK: dict[str, str] = {
        _KEY_FOUNDER: _UNKNOWN,
        _KEY_TECH:    _UNKNOWN,
        _KEY_NEED:    _UNKNOWN,
    }

    add_log(
        f"[AI] Submitting payload to Ollama ({_MODEL_ID}). "
        f"Payload length: {len(scraped_text)} characters."
    )

    prompt: str = _SYSTEM_PROMPT_TEMPLATE.format(scraped_text=scraped_text)

    request_body: dict = {
        "model":  _MODEL_ID,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": _TEMPERATURE,
            "num_ctx":     _NUM_CTX,
            "top_p":       _TOP_P,
        },
    }

    try:
        response: requests.Response = requests.post(
            _OLLAMA_ENDPOINT,
            json=request_body,
            timeout=_REQUEST_TIMEOUT_S,
        )

        # Raise an HTTPError for 4xx / 5xx status codes so the except
        # block below provides a uniform error path for all HTTP failures.
        response.raise_for_status()

        response_json: dict = response.json()

        # Ollama's non-streaming response places the full generation string
        # under the "response" key of the returned JSON object.
        raw_output: str = response_json.get("response", "").strip()

        if not raw_output:
            add_log(
                "[AI] WARNING: Ollama returned an empty response body. "
                "Returning fallback dictionary."
            )
            return _FALLBACK

        add_log("[AI] Ollama inference complete. Parsing structured output.")

        parsed: dict[str, str] = _parse_ollama_response(raw_output)

        add_log(
            f"[AI] Extraction result -- "
            f"FOUNDER: {parsed[_KEY_FOUNDER]} | "
            f"TECH: {parsed[_KEY_TECH]} | "
            f"NEED: {parsed[_KEY_NEED]}"
        )

        return parsed

    except requests.exceptions.ConnectionError:
        add_log(
            "[AI] ERROR: Cannot reach Ollama daemon at "
            f"{_OLLAMA_ENDPOINT}. Ensure Ollama is running locally."
        )
        return _FALLBACK

    except requests.exceptions.Timeout:
        add_log(
            f"[AI] ERROR: Ollama request timed out after "
            f"{_REQUEST_TIMEOUT_S}s. Model may still be loading weights."
        )
        return _FALLBACK

    except requests.exceptions.HTTPError as exc:
        add_log(
            f"[AI] ERROR: Ollama returned HTTP {exc.response.status_code}. "
            f"Details: {exc}"
        )
        return _FALLBACK

    except Exception as exc:
        add_log(
            f"[AI] ERROR: Unexpected failure during Ollama query. "
            f"Reason: {exc}"
        )
        return _FALLBACK