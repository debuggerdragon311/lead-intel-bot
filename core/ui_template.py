"""Static CRT terminal operator dashboard template.

Exports a single module-level string constant, HTML_TEMPLATE, containing
the complete self-contained HTML/CSS/JS source for the Operator Dashboard.

Rendering contract:
    The template is served as-is by the Flask route handler. It contains
    no server-side template directives (no Jinja2 placeholders). All live
    data is fetched client-side via a 1500 ms setInterval() AJAX poll
    against the /status JSON endpoint.

JavaScript escape note:
    All JS newline sequences are written as \\n (double-escaped) so that
    Python's raw string parser emits the literal two-character sequence
    backslash-n into the HTML output, which the browser's JS engine then
    interprets correctly as a newline at runtime.
"""

# =============================================================================
# Operator Dashboard HTML Template
# =============================================================================

HTML_TEMPLATE: str = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>LEAD-INTEL // OPERATOR CONSOLE</title>

  <!-- =========================================================
       TYPOGRAPHY
       VT323      : primary display font — authentic dot-matrix feel
       Share Tech Mono : body monospace — clean terminal readability
  ========================================================= -->
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link
    href="https://fonts.googleapis.com/css2?family=VT323&family=Share+Tech+Mono&display=swap"
    rel="stylesheet"
  />

  <style>
    /* ================================================================
       CSS CUSTOM PROPERTIES — single source of truth for every color,
       glow, and timing value used across the entire dashboard.
    ================================================================ */
    :root {
      --phosphor:        #33ff33;         /* primary CRT green           */
      --phosphor-dim:    #1a8c1a;         /* dimmed / inactive green     */
      --phosphor-bright: #80ff80;         /* highlight / hover green     */
      --bg-terminal:     #010501;         /* deepest black-green         */
      --bg-panel:        #051a05;         /* panel surface               */
      --bg-panel-raised: #071f07;         /* slightly lifted panel card  */
      --border:          #0d4d0d;         /* subtle panel border         */
      --border-bright:   #1a7a1a;         /* active / focused border     */
      --glow-soft:       rgba(51, 255, 51, 0.40);
      --glow-medium:     rgba(51, 255, 51, 0.65);
      --glow-hard:       rgba(51, 255, 51, 0.90);
      --glow-text:       0 0 8px var(--glow-soft);
      --glow-text-md:    0 0 12px var(--glow-medium);
      --font-display:    'VT323', monospace;
      --font-mono:       'Share Tech Mono', monospace;
      --flicker-speed:   8s;
      --scanline-size:   3px;
    }

    /* ================================================================
       RESET & BASE
    ================================================================ */
    *, *::before, *::after {
      box-sizing: border-box;
      margin:     0;
      padding:    0;
    }

    /* ================================================================
       BODY — viewport lock, CRT scanline overlay, flicker animation
       The scanlines are a repeating linear-gradient pseudo-texture
       rendered directly in CSS — no external image files required.
       The overlay sits on top of all content via a fixed ::before
       pseudo-element so it never disrupts layout flow.
    ================================================================ */
    body {
      width:       100vw;
      height:      100vh;
      overflow:    hidden;
      background:  var(--bg-terminal);
      color:       var(--phosphor);
      font-family: var(--font-mono);
      font-size:   13px;
      line-height: 1.5;

      /* Subtle full-body screen flicker */
      animation: crt-flicker var(--flicker-speed) infinite;
    }

    /* CRT scanline overlay — fixed, pointer-events off so clicks pass through */
    body::before {
      content:          '';
      position:         fixed;
      inset:            0;
      z-index:          9999;
      pointer-events:   none;

      /* Alternating transparent / semi-opaque bands = scanlines */
      background: repeating-linear-gradient(
        to bottom,
        transparent                      0px,
        transparent                      calc(var(--scanline-size) - 1px),
        rgba(0, 0, 0, 0.18)              calc(var(--scanline-size) - 1px),
        rgba(0, 0, 0, 0.18)              var(--scanline-size)
      );
    }

    /* Screen vignette — darkens corners like a real CRT bezel */
    body::after {
      content:        '';
      position:       fixed;
      inset:          0;
      z-index:        9998;
      pointer-events: none;
      background: radial-gradient(
        ellipse at center,
        transparent          55%,
        rgba(0, 0, 0, 0.55)  100%
      );
    }

    /* ================================================================
       CRT FLICKER KEYFRAMES
       Subtly modulates opacity in an irregular cadence that mimics the
       phosphor persistence fluctuation of vintage CRT monitors.
    ================================================================ */
    @keyframes crt-flicker {
      0%,  19%,  21%,  23%,  25%,  54%,  56%,  100% { opacity: 1.00; }
      20%,  24%,  55%                                 { opacity: 0.94; }
      22%                                             { opacity: 0.88; }
    }

    /* ================================================================
       BLINKING ANIMATIONS
    ================================================================ */
    @keyframes blink {
      0%, 100% { opacity: 1; }
      50%       { opacity: 0; }
    }

    @keyframes status-pulse {
      0%, 100% { opacity: 1;    box-shadow: 0 0 4px  var(--glow-soft);   }
      50%       { opacity: 0.55; box-shadow: 0 0 14px var(--glow-medium); }
    }

    @keyframes error-pulse {
      0%, 100% { opacity: 1;    border-color: #ff3333; box-shadow: 0 0 6px rgba(255,51,51,0.5); }
      50%       { opacity: 0.6; border-color: #881111; box-shadow: none; }
    }

    @keyframes scan-sweep {
      from { background-position: 0 0; }
      to   { background-position: 0 100%; }
    }

    /* ================================================================
       ROOT LAYOUT GRID
       Two columns: fixed 460 px left panel | flex-fill right panel.
       Height locked to 100vh, no overflow to the document body.
    ================================================================ */
    #app-grid {
      display:               grid;
      grid-template-columns: 460px 1fr;
      grid-template-rows:    1fr;
      width:                 100vw;
      height:                100vh;
      overflow:              hidden;
    }

    /* ================================================================
       LEFT COLUMN — target list + console feed stacked vertically
    ================================================================ */
    #left-column {
      display:        flex;
      flex-direction: column;
      height:         100vh;
      border-right:   1px solid var(--border);
      overflow:       hidden;
    }

    /* ================================================================
       PANEL SHARED STYLES
    ================================================================ */
    .panel {
      background:  var(--bg-panel);
      border:      1px solid var(--border);
      padding:     12px 14px;
      overflow:    hidden;
    }

    .panel-header {
      font-family:   var(--font-display);
      font-size:     22px;
      letter-spacing: 2px;
      color:         var(--phosphor);
      text-shadow:   var(--glow-text-md);
      border-bottom: 1px solid var(--border);
      padding-bottom: 6px;
      margin-bottom: 10px;
      display:       flex;
      align-items:   center;
      gap:           8px;
    }

    .panel-header .header-icon {
      opacity: 0.75;
    }

    /* ================================================================
       TOP-BAR — single-line system status strip across full width
    ================================================================ */
    #top-bar {
      grid-column:     1 / -1;
      display:         flex;
      align-items:     center;
      justify-content: space-between;
      padding:         5px 18px;
      background:      var(--bg-panel);
      border-bottom:   1px solid var(--border-bright);
      font-family:     var(--font-display);
      font-size:       18px;
      letter-spacing:  3px;
      color:           var(--phosphor);
      text-shadow:     var(--glow-text-md);
      flex-shrink:     0;
    }

    #top-bar .sys-id {
      font-size:    24px;
      letter-spacing: 4px;
    }

    #top-bar .model-status-strip {
      font-size:   15px;
      color:       var(--phosphor-dim);
      letter-spacing: 1px;
    }

    #top-bar .clock {
      font-size: 18px;
    }

    /* ================================================================
       TARGET INPUT PANEL (left column, fixed height)
    ================================================================ */
    #target-panel {
      flex-shrink: 0;
      border-left:   none;
      border-top:    none;
      border-right:  none;
    }

    #target-input-row {
      display:     flex;
      gap:         6px;
      margin-bottom: 10px;
    }

    #target-input {
      flex:        1;
      background:  var(--bg-terminal);
      border:      1px solid var(--border-bright);
      color:       var(--phosphor);
      font-family: var(--font-mono);
      font-size:   13px;
      padding:     6px 10px;
      outline:     none;
      caret-color: var(--phosphor);
      text-shadow: var(--glow-text);
      transition:  border-color 0.15s, box-shadow 0.15s;
    }

    #target-input:focus {
      border-color: var(--phosphor);
      box-shadow:   0 0 10px var(--glow-soft);
    }

    #target-input::placeholder {
      color:   var(--phosphor-dim);
      opacity: 0.6;
    }

    /* ================================================================
       BUTTONS
    ================================================================ */
    .btn {
      font-family:    var(--font-display);
      font-size:      18px;
      letter-spacing: 2px;
      background:     transparent;
      border:         1px solid var(--border-bright);
      color:          var(--phosphor);
      padding:        4px 14px;
      cursor:         pointer;
      text-shadow:    var(--glow-text);
      transition:     background 0.12s, box-shadow 0.12s, color 0.12s;
      white-space:    nowrap;
    }

    .btn:hover:not(:disabled) {
      background:  rgba(51, 255, 51, 0.08);
      box-shadow:  0 0 12px var(--glow-soft);
      color:       var(--phosphor-bright);
    }

    .btn:active:not(:disabled) {
      background: rgba(51, 255, 51, 0.18);
    }

    .btn:disabled {
      opacity:      0.45;
      cursor:       not-allowed;
      border-color: var(--border);
    }

    .btn-danger {
      border-color: #5a1a1a;
      color:        #ff5555;
      text-shadow:  0 0 8px rgba(255, 85, 85, 0.4);
    }

    .btn-danger:hover:not(:disabled) {
      background:  rgba(255, 51, 51, 0.08);
      box-shadow:  0 0 12px rgba(255, 51, 51, 0.4);
      color:       #ff8888;
    }

    #run-btn {
      width: 100%;
    }

    /* ================================================================
       TARGET LIST (within target panel)
    ================================================================ */
    #target-list-box {
      max-height:  130px;
      overflow-y:  auto;
      border:      1px solid var(--border);
      padding:     4px 6px;
      background:  var(--bg-terminal);
      margin-bottom: 10px;
      font-size:   12px;
    }

    .target-tag {
      display:         inline-flex;
      align-items:     center;
      gap:             5px;
      background:      rgba(51, 255, 51, 0.06);
      border:          1px solid var(--border-bright);
      color:           var(--phosphor);
      padding:         2px 8px;
      margin:          2px 3px;
      font-size:       12px;
      font-family:     var(--font-mono);
      cursor:          default;
    }

    .target-tag .remove-tag {
      cursor:     pointer;
      color:      var(--phosphor-dim);
      font-size:  14px;
      line-height: 1;
      transition: color 0.1s;
    }

    .target-tag .remove-tag:hover { color: #ff5555; }

    #target-empty-msg {
      color:      var(--phosphor-dim);
      font-size:  12px;
      padding:    4px 2px;
      opacity:    0.6;
    }

    /* ================================================================
       CONSOLE FEED PANEL (left column, grows to fill remaining height)
    ================================================================ */
    #console-panel {
      flex:        1 1 0;
      display:     flex;
      flex-direction: column;
      min-height:  0;           /* critical: allows flex children to shrink */
      border-left: none;
      border-right: none;
      border-bottom: none;
    }

    #console-logs {
      flex:        1 1 0;
      overflow-y:  auto;
      background:  var(--bg-terminal);
      border:      1px solid var(--border);
      padding:     8px 10px;
      font-size:   11px;
      line-height: 1.6;
      color:       var(--phosphor-dim);
      white-space: pre-wrap;
      word-break:  break-word;
      min-height:  0;
    }

    /* Blinking block cursor appended after log stream */
    .cursor {
      display:          inline-block;
      width:            8px;
      height:           13px;
      background:       var(--phosphor);
      vertical-align:   middle;
      margin-left:      2px;
      animation:        blink 1s step-end infinite;
    }

    /* ================================================================
       RIGHT COLUMN — main data table
    ================================================================ */
    #right-column {
      display:        flex;
      flex-direction: column;
      height:         100vh;
      overflow:       hidden;
    }

    #data-panel {
      flex:        1 1 0;
      display:     flex;
      flex-direction: column;
      min-height:  0;
      border:      none;
      border-left: 1px solid var(--border);
    }

    /* ================================================================
       DATA TABLE
    ================================================================ */
    #table-container {
      flex:      1 1 0;
      overflow-y: auto;
      min-height: 0;
    }

    #results-table {
      width:           100%;
      border-collapse: collapse;
      font-size:       12px;
      font-family:     var(--font-mono);
      table-layout:    fixed;
    }

    #results-table thead {
      position:    sticky;
      top:         0;
      z-index:     10;
      background:  var(--bg-panel);
    }

    #results-table th {
      font-family:    var(--font-display);
      font-size:      16px;
      letter-spacing: 2px;
      color:          var(--phosphor);
      text-shadow:    var(--glow-text);
      text-align:     left;
      padding:        8px 12px;
      border-bottom:  2px solid var(--border-bright);
      border-right:   1px solid var(--border);
      white-space:    nowrap;
      overflow:       hidden;
      text-overflow:  ellipsis;
    }

    #results-table th:last-child { border-right: none; }

    #results-table td {
      padding:        7px 12px;
      border-bottom:  1px solid var(--border);
      border-right:   1px solid var(--border);
      vertical-align: top;
      overflow:       hidden;
      text-overflow:  ellipsis;
      color:          var(--phosphor-dim);
      transition:     color 0.2s;
    }

    #results-table td:last-child { border-right: none; }

    #results-table tbody tr:hover td {
      background: rgba(51, 255, 51, 0.03);
      color:      var(--phosphor);
    }

    /* Column width hints */
    .col-domain   { width: 170px; }
    .col-status   { width: 150px; }
    .col-founder  { width: 160px; }
    .col-tech     { width: 180px; }
    .col-need     { width: auto;  }

    .cell-domain {
      color:       var(--phosphor);
      text-shadow: var(--glow-text);
      font-weight: bold;
    }

    /* ================================================================
       STATUS BADGES
    ================================================================ */
    .badge {
      display:         inline-block;
      padding:         2px 9px;
      font-family:     var(--font-display);
      font-size:       15px;
      letter-spacing:  1px;
      border:          1px solid;
      white-space:     nowrap;
    }

    .badge-queued {
      border-color: #2a4a2a;
      color:        #4a7a4a;
    }

    .badge-scanning {
      border-color: #7a7a00;
      color:        #dddd00;
      animation:    status-pulse 1.2s ease-in-out infinite;
    }

    .badge-extracting {
      border-color: #7a5a00;
      color:        #ffaa00;
      animation:    status-pulse 1.0s ease-in-out infinite;
    }

    .badge-finished {
      border-color: var(--border-bright);
      color:        var(--phosphor);
      text-shadow:  var(--glow-text);
    }

    .badge-error {
      border-color: #881111;
      color:        #ff4444;
      animation:    error-pulse 0.9s ease-in-out infinite;
    }

    /* ================================================================
       EMPTY TABLE STATE
    ================================================================ */
    #table-empty-row td {
      text-align:  center;
      padding:     40px 12px;
      color:       var(--phosphor-dim);
      opacity:     0.45;
      font-family: var(--font-display);
      font-size:   20px;
      letter-spacing: 3px;
    }

    /* ================================================================
       SCROLLBAR STYLING — keep the CRT aesthetic inside scroll regions
    ================================================================ */
    ::-webkit-scrollbar              { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track        { background: var(--bg-terminal); }
    ::-webkit-scrollbar-thumb        { background: var(--border-bright); }
    ::-webkit-scrollbar-thumb:hover  { background: var(--phosphor-dim); }

    /* ================================================================
       UTILITY
    ================================================================ */
    .dim      { opacity: 0.55; }
    .bright   { color: var(--phosphor-bright); text-shadow: var(--glow-text-md); }
    .mono-sm  { font-family: var(--font-mono); font-size: 11px; }

  </style>
</head>

<body>

<!-- ================================================================
     APP GRID ROOT
     Two-column layout: 460px left column | flex-fill right column.
     Top bar spans both columns via grid-column: 1 / -1.
================================================================ -->
<div id="app-grid">

  <!-- ============================================================
       TOP BAR — system identification + live model status
  ============================================================ -->
  <div id="top-bar">
    <span class="sys-id">&#9632; LEAD-INTEL // OPS CONSOLE</span>
    <span class="model-status-strip">
      ENGINE: <span id="model-status">INITIALIZING...</span>
    </span>
    <span class="clock" id="clock">--:--:--</span>
  </div>

  <!-- ============================================================
       LEFT COLUMN
  ============================================================ -->
  <div id="left-column">

    <!-- TARGET INPUT PANEL -->
    <div id="target-panel" class="panel">
      <div class="panel-header">
        <span class="header-icon">&#9654;</span> TARGET ACQUISITION
      </div>

      <!-- Domain input + add button -->
      <div id="target-input-row">
        <input
          id="target-input"
          type="text"
          placeholder="enter domain or company name..."
          autocomplete="off"
          spellcheck="false"
        />
        <button class="btn" id="add-btn" onclick="addTarget()">[ ADD ]</button>
      </div>

      <!-- Live target tag list -->
      <div id="target-list-box">
        <span id="target-empty-msg">// no targets queued</span>
      </div>

      <!-- Execute + Clear buttons -->
      <button class="btn" id="run-btn" onclick="runPipeline()" style="margin-bottom:6px;">
        [ EXECUTE PIPELINE ]
      </button>
      <button class="btn btn-danger" id="clear-btn" onclick="clearTargets()">
        [ CLEAR QUEUE ]
      </button>
    </div>

    <!-- CONSOLE FEED PANEL -->
    <div id="console-panel" class="panel">
      <div class="panel-header">
        <span class="header-icon">&#9632;</span> SYSTEM CONSOLE FEED
      </div>
      <!-- Log stream — content written by JS pollSystemState() -->
      <div id="console-logs">// awaiting system boot...</div>
    </div>

  </div><!-- /left-column -->

  <!-- ============================================================
       RIGHT COLUMN — live results data table
  ============================================================ -->
  <div id="right-column">
    <div id="data-panel" class="panel">
      <div class="panel-header">
        <span class="header-icon">&#9632;</span> EXTRACTION RESULTS
        <span class="dim mono-sm" style="margin-left:auto;" id="result-count">//  0 records</span>
      </div>

      <div id="table-container">
        <table id="results-table">
          <colgroup>
            <col class="col-domain"  />
            <col class="col-status"  />
            <col class="col-founder" />
            <col class="col-tech"    />
            <col class="col-need"    />
          </colgroup>
          <thead>
            <tr>
              <th>DOMAIN</th>
              <th>STATUS</th>
              <th>FOUNDER / CEO</th>
              <th>TECH STACK</th>
              <th>VALUE PROPOSITION</th>
            </tr>
          </thead>
          <tbody id="results-tbody">
            <!-- Empty state row — hidden once data arrives -->
            <tr id="table-empty-row">
              <td colspan="5">// NO EXTRACTION DATA — QUEUE TARGETS AND EXECUTE</td>
            </tr>
          </tbody>
        </table>
      </div><!-- /table-container -->

    </div><!-- /data-panel -->
  </div><!-- /right-column -->

</div><!-- /app-grid -->


<script>
  /* ==================================================================
     OPERATOR DASHBOARD — CLIENT-SIDE STATE POLLING ENGINE
     Polls /status every 1500 ms and re-renders all dynamic UI regions.
  ================================================================== */

  /* ------------------------------------------------------------------
     MODULE STATE
     Mirrors relevant slices of the server-side SYSTEM_STATE dict.
     Kept in plain JS variables — no framework, no virtual DOM.
  ------------------------------------------------------------------ */
  let _targets      = [];   // Domains queued by the operator
  let _isRunning    = false; // Reflects server is_running flag
  let _userScrolled = false; // True when user manually scrolled console up


  /* ==================================================================
     CLOCK — updates every second independently of the poll cycle
  ================================================================== */
  function _updateClock() {
    const now = new Date();
    const hh  = String(now.getHours()).padStart(2, '0');
    const mm  = String(now.getMinutes()).padStart(2, '0');
    const ss  = String(now.getSeconds()).padStart(2, '0');
    document.getElementById('clock').textContent = hh + ':' + mm + ':' + ss;
  }
  setInterval(_updateClock, 1000);
  _updateClock();


  /* ==================================================================
     CONSOLE SCROLL SENTINEL
     Detects manual upward scroll so the auto-scroll logic does not
     hijack the operator's view while they are reviewing old logs.
  ================================================================== */
  (function attachScrollSentinel() {
    const logBox = document.getElementById('console-logs');
    logBox.addEventListener('scroll', function () {
      const atBottom = logBox.scrollHeight - logBox.scrollTop - logBox.clientHeight < 6;
      _userScrolled  = !atBottom;
    });
  })();


  /* ==================================================================
     STATUS BADGE RENDERER
     Maps server-side status strings to styled HTML badge strings.

     Status contract (from server):
       "QUEUED"        -> grey   (inactive)
       "SCANNING"      -> yellow (pulsing, phase A active)
       "AI-EXTRACTING" -> amber  (pulsing, phase B active)
       "FINISHED"      -> green  (complete)
       "ERROR"         -> red    (pulsing, failed)
  ================================================================== */
  function _renderBadge(status) {
    const s = (status || 'QUEUED').toUpperCase().trim();

    if (s === 'QUEUED')        return '<span class="badge badge-queued">QUEUED</span>';
    if (s === 'SCANNING')      return '<span class="badge badge-scanning">SCANNING</span>';
    if (s === 'AI-EXTRACTING') return '<span class="badge badge-extracting">AI-EXTRACT</span>';
    if (s === 'FINISHED')      return '<span class="badge badge-finished">&#10003; DONE</span>';
    if (s === 'ERROR')         return '<span class="badge badge-error">&#9888; ERROR</span>';

    /* Fallback for any unexpected status value from the server */
    return '<span class="badge badge-queued">' + s + '</span>';
  }


  /* ==================================================================
     TABLE RENDERER
     Rebuilds the tbody content from the companies array returned
     by the /status endpoint. Each company object is expected to
     have: { domain, status, founder, tech, need }
  ================================================================== */
  function _renderTable(companies) {
    const tbody     = document.getElementById('results-tbody');
    const countEl   = document.getElementById('result-count');

    // Safe direct template string write replaces dynamic appendChild [4]
    if (!companies || companies.length === 0) {
      tbody.innerHTML = '<tr id="table-empty-row"><td colspan="5">// NO EXTRACTION DATA — QUEUE TARGETS AND EXECUTE</td></tr>';
      countEl.textContent = '//  0 records';
      return;
    }

    let html = '';
    companies.forEach(function (c) {
      html += '<tr>';
      html += '<td class="cell-domain">' + _esc(c.domain   || '--') + '</td>';
      html += '<td>'                      + _renderBadge(c.status)   + '</td>';
      html += '<td>'                      + _esc(c.founder || '--')  + '</td>';
      html += '<td>'                      + _esc(c.tech    || '--')  + '</td>';
      html += '<td>'                      + _esc(c.need    || '--')  + '</td>';
      html += '</tr>';
    });

    tbody.innerHTML = html;
    countEl.textContent = '//  ' + companies.length + ' record' +
                          (companies.length === 1 ? '' : 's');
  }


  /* ==================================================================
     CONSOLE RENDERER
     Joins the log array with newline characters and appends a blinking
     block cursor. Scrolls to the bottom only when the operator is not
     manually reviewing previous log entries.
  ================================================================== */
  function _renderConsole(logs) {
    const logBox = document.getElementById('console-logs');

    /* Join entries with literal newline for pre-wrap rendering.
       \\n is double-escaped in the Python source so the browser
       receives the correct backslash-n JS sequence here.         */
    const text = (logs || []).join('\\n');

    logBox.innerHTML = _esc(text) + '<span class="cursor"></span>';

    /* Auto-scroll to tail only if the operator has not scrolled up */
    if (!_userScrolled) {
      logBox.scrollTop = logBox.scrollHeight;
    }
  }


  /* ==================================================================
     MODEL STATUS RENDERER
     Updates the top-bar engine status label with color coding based
     on keyword presence in the status string.
  ================================================================== */
  function _renderModelStatus(statusText) {
    const el   = document.getElementById('model-status');
    const text = (statusText || '').toUpperCase();

    el.textContent = statusText || 'UNKNOWN';

    /* Remove any previously injected inline style before re-applying */
    el.removeAttribute('style');

    if (text.includes('READY') || text.includes('LOADED') || text.includes('OK')) {
      el.style.color      = 'var(--phosphor)';
      el.style.textShadow = 'var(--glow-text-md)';
    } else if (text.includes('ERROR') || text.includes('FAIL') || text.includes('OFFLINE')) {
      el.style.color      = '#ff4444';
      el.style.textShadow = '0 0 8px rgba(255,68,68,0.5)';
    } else {
      /* Neutral / in-progress state */
      el.style.color   = '#dddd00';
      el.style.opacity = '0.85';
    }
  }


  /* ==================================================================
     CONTROL BUTTON STATE
     Disables the execute button and changes its label while the
     pipeline is active to prevent duplicate submissions.
  ================================================================== */
  function _renderControlState(isRunning) {
    const runBtn = document.getElementById('run-btn');

    if (isRunning) {
      runBtn.disabled     = true;
      runBtn.textContent  = '[ PIPELINE RUNNING... ]';
    } else {
      runBtn.disabled     = false;
      runBtn.textContent  = '[ EXECUTE PIPELINE ]';
    }

    _isRunning = isRunning;
  }


  /* ==================================================================
     POLL SYSTEM STATE — primary polling loop, 1500 ms interval
     Fetches /status and fans the response out to each renderer.
  ================================================================== */
  function pollSystemState() {
    fetch('/status')
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function (state) {
        _renderModelStatus(state.model_status);
        _renderConsole(state.logs);
        _renderTable(state.companies);
        _renderControlState(state.is_running);
      })
      .catch(function (err) {
        /* Server unreachable — update status strip, leave table intact */
        document.getElementById('model-status').textContent =
          'DAEMON OFFLINE — ' + err.message;
      });
  }

  /* Kick off the polling loop immediately on page load, then every 1500 ms */
  pollSystemState();
  setInterval(pollSystemState, 1500);


  /* ==================================================================
     TARGET QUEUE MANAGEMENT
     Client-side only — targets are accumulated in _targets[] and
     submitted to the server in a batch when the operator clicks Execute.
  ================================================================== */

  /* Render the current _targets array as interactive tag chips */
  function _renderTargetList() {
    const box      = document.getElementById('target-list-box');

    // Safe fallback template string write [4]
    if (_targets.length === 0) {
      box.innerHTML = '<span id="target-empty-msg">// no targets queued</span>';
      return;
    }

    let html = '';
    _targets.forEach(function (t, idx) {
      html += '<span class="target-tag">' + _esc(t) +
              '<span class="remove-tag" onclick="removeTarget(' + idx + ')">&#10005;</span>' +
              '</span>';
    });
    box.innerHTML = html;
  }

  /* Add a domain entry from the input field */
  function addTarget() {
    const input = document.getElementById('target-input');
    const raw   = (input.value || '').trim();
    if (!raw) return;

    /* Deduplicate — silently ignore if already queued */
    if (_targets.indexOf(raw.toLowerCase()) === -1) {
      _targets.push(raw.toLowerCase());
      _renderTargetList();
    }
    input.value = '';
    input.focus();
  }

  /* Remove a single target by its index in _targets */
  function removeTarget(idx) {
    _targets.splice(idx, 1);
    _renderTargetList();
  }

  /* Flush the entire target queue */
  function clearTargets() {
    _targets = [];
    _renderTargetList();
  }

  /* Allow pressing Enter inside the input field to trigger addTarget() */
  document.getElementById('target-input').addEventListener('keydown', function (e) {
    if (e.key === 'Enter') addTarget();
  });


  /* ==================================================================
     PIPELINE EXECUTION
     POSTs the accumulated target list to /run as JSON.
     The server-side route places them into SYSTEM_STATE["companies"]
     and sets is_running = True to begin processing.
  ================================================================== */
  function runPipeline() {
    if (_isRunning || _targets.length === 0) return;

    fetch('/run', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ targets: _targets }),
    })
    .then(function (res) {
      if (!res.ok) throw new Error('HTTP ' + res.status);
      /* Clear the local queue after successful submission */
      _targets = [];
      _renderTargetList();
    })
    .catch(function (err) {
      console.error('[PIPELINE] Submission failed:', err);
    });
  }


  /* ==================================================================
     HTML ESCAPE UTILITY
     Prevents XSS when inserting server-supplied strings as innerHTML.
     Applied to every value rendered into the DOM from server data.
  ================================================================== */
  function _esc(str) {
    return String(str)
      .replace(/&/g,  '&amp;')
      .replace(/</g,  '&lt;')
      .replace(/>/g,  '&gt;')
      .replace(/"/g,  '&quot;')
      .replace(/'/g,  '&#39;');
  }

</script>

</body>
</html>"""