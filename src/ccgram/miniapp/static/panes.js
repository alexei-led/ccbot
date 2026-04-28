// Multi-pane grid surface — fetches /api/panes/<token>, lays panes out as a
// responsive grid (1/2/4-up), and connects one websocket per pane to render
// a small live terminal preview. Click a tile to expand into a focused
// single-pane view; click again (or the "Back" link) to return to the grid.
//
// Subscription lifecycle: each tile owns one xterm.js Terminal + WebSocket;
// closing the grid (or focusing one tile) tears the others down so we never
// hold more sockets than tiles currently visible.

(function () {
    "use strict";

    const REFRESH_INTERVAL_MS = 5000;
    // The refresh loop below already polls /api/panes/<token> at this cadence
    // and treats HTTP 403 as the authoritative auth-failure signal. Per-tile
    // WebSockets therefore back off transport failures forever — the refresh
    // loop will tear them down within one tick if the server is rejecting us.
    const XTERM_CSS = "https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.css";
    const XTERM_JS = "https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.js";
    const FIT_JS = "https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.js";

    function tokenFromLocation() {
        const m = window.location.pathname.match(/^\/app\/([^/]+)/);
        return m ? m[1] : null;
    }

    function initDataRaw() {
        const tg = window.Telegram && window.Telegram.WebApp;
        return tg && tg.initData ? tg.initData : "";
    }

    function initDataHeaders() {
        const raw = initDataRaw();
        return raw ? { "X-Telegram-Init-Data": raw } : {};
    }

    // Server WS close codes for auth failures (mirror terminal.py).
    const WS_AUTH_CODES = new Set([4001, 4002, 4003]);

    function wsUrlFor(token, paneId) {
        const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
        const base = proto + "//" + window.location.host + "/ws/terminal/" + token;
        return paneId ? base + "?pane=" + encodeURIComponent(paneId) : base;
    }

    function gridColumnsFor(count) {
        if (count <= 1) return 1;
        if (count === 2) return 2;
        if (count <= 4) return 2;
        return 3;
    }

    function loadStyle(href) {
        return new Promise((resolve, reject) => {
            const link = document.createElement("link");
            link.rel = "stylesheet";
            link.href = href;
            link.onload = () => resolve();
            link.onerror = () => reject(new Error("css load failed: " + href));
            document.head.appendChild(link);
        });
    }

    function loadScript(src) {
        return new Promise((resolve, reject) => {
            const s = document.createElement("script");
            s.src = src;
            s.async = false;
            s.onload = () => resolve();
            s.onerror = () => reject(new Error("script load failed: " + src));
            document.head.appendChild(s);
        });
    }

    // Single shared promise that resolves once xterm.js + fit-addon are
    // available on window. Both terminal.js and panes.js reuse the same
    // global so the second caller never re-issues the script tags or races
    // the first loader. A rejected promise is evicted so the next caller
    // can retry — otherwise a transient CDN blip would brick every later
    // xterm consumer for the rest of the page lifetime.
    function ensureXtermLoaded() {
        if (window.__ccgramXtermReady) return window.__ccgramXtermReady;
        if (window.Terminal && window.FitAddon && window.FitAddon.FitAddon) {
            window.__ccgramXtermReady = Promise.resolve();
            return window.__ccgramXtermReady;
        }
        const p = (async () => {
            await Promise.all([loadStyle(XTERM_CSS), loadScript(XTERM_JS)]);
            await loadScript(FIT_JS);
        })();
        p.catch(() => {
            if (window.__ccgramXtermReady === p) {
                window.__ccgramXtermReady = null;
            }
        });
        window.__ccgramXtermReady = p;
        return window.__ccgramXtermReady;
    }

    function authError(message) {
        const err = new Error(message);
        err.authFailed = true;
        return err;
    }

    async function fetchPanes(token) {
        const resp = await fetch("/api/panes/" + token, {
            credentials: "same-origin",
            headers: initDataHeaders(),
        });
        if (resp.status === 403) {
            throw authError("authentication failed");
        }
        if (!resp.ok) throw new Error("panes fetch failed: " + resp.status);
        const data = await resp.json();
        return Array.isArray(data.panes) ? data.panes : [];
    }

    function makeTile(pane) {
        const tile = document.createElement("div");
        tile.className = "ccgram-pane-tile";
        tile.dataset.paneId = pane.pane_id;
        tile.tabIndex = 0;
        tile.setAttribute("role", "button");
        tile.setAttribute(
            "aria-label",
            "pane " + (pane.name || pane.pane_id) + " — click to focus"
        );

        const header = document.createElement("div");
        header.className = "ccgram-pane-header";
        const label = document.createElement("span");
        label.className = "ccgram-pane-label";
        label.textContent = (pane.name || pane.pane_id) + (
            pane.command ? " · " + pane.command : ""
        );
        const stateBadge = document.createElement("span");
        stateBadge.className = "ccgram-pane-state ccgram-pane-state-" + pane.state;
        stateBadge.textContent = pane.state;
        header.append(label, stateBadge);

        const term = document.createElement("div");
        term.className = "ccgram-pane-term";

        tile.append(header, term);
        return { tile, term };
    }

    async function attachTerminal(termEl, token, paneId, statusEl) {
        try {
            await ensureXtermLoaded();
        } catch (err) {
            statusEl.textContent = "xterm.js failed to load: " + err.message;
            return null;
        }
        const Terminal = window.Terminal;
        const FitAddon = window.FitAddon && window.FitAddon.FitAddon;
        if (!Terminal || !FitAddon) {
            statusEl.textContent = "xterm.js not ready";
            return null;
        }
        const term = new Terminal({
            convertEol: true,
            cursorBlink: false,
            disableStdin: true,
            fontFamily: 'ui-monospace, "SF Mono", Menlo, monospace',
            fontSize: 11,
        });
        const fit = new FitAddon();
        term.loadAddon(fit);
        term.open(termEl);
        try { fit.fit(); } catch (e) { /* tile may be 0×0 momentarily */ }

        let closed = false;
        let reconnectDelay = 500;
        let ws = null;

        const connect = () => {
            if (closed) return;
            ws = new WebSocket(wsUrlFor(token, paneId));
            ws.onopen = () => {
                reconnectDelay = 500;
                // Server reads initData from the first WS frame. The
                // browser WebSocket API can't carry custom headers, and
                // putting initData in the URL would leak it into access
                // logs alongside the token.
                try {
                    ws.send(JSON.stringify({ init_data: initDataRaw() }));
                } catch (e) {
                    // Socket already gone — onclose will drive reconnect.
                }
            };
            ws.onmessage = (ev) => {
                let msg;
                try { msg = JSON.parse(ev.data); } catch (e) { return; }
                if (msg.type === "frame" && typeof msg.text === "string") {
                    term.reset();
                    term.write(msg.text);
                }
                reconnectDelay = 500;
            };
            ws.onerror = () => { /* close handler will follow */ };
            ws.onclose = (ev) => {
                if (closed) return;
                // Server-driven auth-failure codes are authoritative —
                // stop immediately so we don't churn through retries with
                // bad credentials.
                if (ev && WS_AUTH_CODES.has(ev.code)) {
                    closed = true;
                    return;
                }
                // The refresh loop's HTTP 403 detection covers the rest;
                // here we just back off and keep retrying transport blips.
                setTimeout(() => {
                    if (!closed) connect();
                }, reconnectDelay);
                reconnectDelay = Math.min(reconnectDelay * 2, 8000);
            };
        };
        connect();

        return {
            close() {
                closed = true;
                try { if (ws) ws.close(); } catch (e) { /* ignore */ }
                try { term.dispose(); } catch (e) { /* ignore */ }
            },
            refit() {
                try { fit.fit(); } catch (e) { /* ignore */ }
            },
        };
    }

    function renderGrid(container, panes, token, statusEl, onFocus) {
        container.innerHTML = "";
        container.style.setProperty(
            "--ccgram-grid-cols", String(gridColumnsFor(panes.length))
        );
        const tiles = [];
        let tornDown = false;
        for (const pane of panes) {
            const { tile, term } = makeTile(pane);
            container.appendChild(tile);
            attachTerminal(term, token, pane.pane_id, statusEl).then((handle) => {
                if (!handle) return;
                if (tornDown) {
                    // Teardown happened while attach was pending — close
                    // the late-arriving handle so we don't leak the WS.
                    handle.close();
                    return;
                }
                tiles.push(handle);
            });
            tile.addEventListener("click", () => onFocus(pane));
            tile.addEventListener("keydown", (ev) => {
                if (ev.key === "Enter" || ev.key === " ") {
                    ev.preventDefault();
                    onFocus(pane);
                }
            });
        }
        return {
            teardown() {
                tornDown = true;
                for (const t of tiles) t.close();
                tiles.length = 0;
            },
            refit() {
                for (const t of tiles) t.refit();
            },
        };
    }

    function renderFocused(container, pane, token, statusEl, onBack) {
        container.innerHTML = "";
        const back = document.createElement("button");
        back.type = "button";
        back.className = "ccgram-pane-back";
        back.textContent = "← back to grid";
        back.addEventListener("click", onBack);

        const { tile, term } = makeTile(pane);
        tile.classList.add("ccgram-pane-focused");
        container.append(back, tile);

        const handlePromise = attachTerminal(term, token, pane.pane_id, statusEl);
        return {
            async teardown() {
                const h = await handlePromise;
                if (h) h.close();
            },
            async refit() {
                const h = await handlePromise;
                if (h) h.refit();
            },
        };
    }

    async function init() {
        const container = document.getElementById("ccgram-panes-grid");
        const statusEl = document.getElementById("ccgram-status");
        if (!container) return;
        if (window.__ccgramAuthFailed) {
            container.style.display = "none";
            return;
        }
        const token = tokenFromLocation();
        if (!token) return;

        let panes = [];
        try {
            panes = await fetchPanes(token);
        } catch (err) {
            if (err.authFailed) {
                container.textContent =
                    "Authentication failed — reopen from Telegram.";
                if (statusEl) {
                    statusEl.textContent =
                        "Authentication failed — reopen from Telegram.";
                }
                return;
            }
            container.textContent = "panes unavailable: " + err.message;
            return;
        }

        // Hide the grid entirely when only one pane exists — the main terminal
        // viewer above already covers that case.
        if (panes.length <= 1) {
            container.style.display = "none";
            return;
        }

        let active = null;
        let focusedPaneId = null;
        const showGrid = () => {
            if (active) active.teardown();
            focusedPaneId = null;
            active = renderGrid(container, panes, token, statusEl, (p) => {
                if (active) active.teardown();
                focusedPaneId = p.pane_id;
                active = renderFocused(container, p, token, statusEl, showGrid);
            });
        };

        showGrid();

        // Per-pane fingerprint covers every property visible in tile/header:
        // rename, command, state, active flag, subscription badge. Used both
        // to decide whether the grid needs rebuilding and whether a focused
        // pane's header needs refreshing.
        const fingerprintPane = (p) => [
            p.pane_id,
            p.active ? "1" : "0",
            p.name || "",
            p.command || "",
            p.state || "",
            p.subscribed ? "s" : "",
        ].join("|");

        const fingerprintPanes = (list) => list
            .map(fingerprintPane)
            .sort()
            .join(",");

        const refreshTimer = window.setInterval(async () => {
            try {
                const fresh = await fetchPanes(token);
                if (fingerprintPanes(panes) === fingerprintPanes(fresh)) {
                    return;
                }
                const previousPanes = panes;
                panes = fresh;
                if (panes.length <= 1) {
                    container.style.display = "none";
                    if (active) active.teardown();
                    active = null;
                    focusedPaneId = null;
                    return;
                }
                container.style.display = "";
                if (focusedPaneId !== null) {
                    const focusedPane = panes.find(
                        (p) => p.pane_id === focusedPaneId
                    );
                    if (!focusedPane) {
                        // Focused pane disappeared — fall back to the grid.
                        showGrid();
                        return;
                    }
                    const previous = previousPanes.find(
                        (p) => p.pane_id === focusedPaneId
                    );
                    if (
                        !previous ||
                        fingerprintPane(previous) !== fingerprintPane(focusedPane)
                    ) {
                        // Focused pane's own metadata changed — re-render so
                        // the header label/state badge stay fresh. Other
                        // panes' changes are invisible in focused view, so
                        // leave the WebSocket untouched in that case.
                        if (active) active.teardown();
                        active = renderFocused(
                            container, focusedPane, token, statusEl, showGrid
                        );
                    }
                    return;
                }
                showGrid();
            } catch (e) {
                if (e && e.authFailed) {
                    window.clearInterval(refreshTimer);
                    if (active) active.teardown();
                    container.textContent =
                        "Authentication expired — reopen from Telegram.";
                    if (statusEl) {
                        statusEl.textContent =
                            "Authentication expired — reopen from Telegram.";
                    }
                }
                /* otherwise transient — try again */
            }
        }, REFRESH_INTERVAL_MS);

        window.addEventListener("beforeunload", () => {
            window.clearInterval(refreshTimer);
            if (active) active.teardown();
        });
        window.addEventListener("resize", () => {
            if (active) active.refit();
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
