// Live terminal surface — connects to /ws/terminal/<token>, renders ANSI
// frames into an xterm.js instance, and re-fits on viewport changes.
//
// Read-only in v3.0: keystrokes are not forwarded; user input is deferred
// to v3.1.

(function () {
    "use strict";

    const XTERM_CSS = "https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.css";
    const XTERM_JS = "https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.js";
    const FIT_JS = "https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.js";

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

    // Shared global promise so panes.js and terminal.js never race when both
    // need xterm. First caller wins; subsequent callers reuse the same
    // in-flight or resolved promise. A rejected promise is evicted so the
    // next caller can retry — otherwise a transient CDN blip would brick
    // every later xterm consumer for the rest of the page lifetime.
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

    function tokenFromLocation() {
        const m = window.location.pathname.match(/^\/app\/([^/]+)/);
        return m ? m[1] : null;
    }

    function initDataRaw() {
        const tg = window.Telegram && window.Telegram.WebApp;
        return tg && tg.initData ? tg.initData : "";
    }

    function wsUrlFor(token) {
        const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
        return proto + "//" + window.location.host + "/ws/terminal/" + token;
    }

    // The browser WebSocket API hides the HTTP status that rejected the
    // upgrade (403 vs network blip both surface as onclose without onopen).
    // After this many consecutive pre-open failures we disambiguate via an
    // HTTP probe to /api/panes/<token>; only a real 403 from the probe
    // earns a hard stop. Server-driven 4001/4002/4003 close codes are an
    // authoritative auth signal and short-circuit this path.
    const PROBE_AFTER_FAILS = 3;

    // Server WS close codes for auth failures (mirror terminal.py).
    const WS_AUTH_CODES = new Set([4001, 4002, 4003]);

    function initDataHeaders() {
        const raw = initDataRaw();
        return raw ? { "X-Telegram-Init-Data": raw } : {};
    }

    async function probeAuth(token) {
        try {
            const resp = await fetch("/api/panes/" + encodeURIComponent(token), {
                credentials: "same-origin",
                headers: initDataHeaders(),
            });
            if (resp.status === 403) return "auth-failed";
            return "ok";
        } catch (e) {
            return "transport";
        }
    }

    async function bootTerminal(container, statusEl) {
        if (window.__ccgramAuthFailed) {
            statusEl.textContent = window.__ccgramAuthMessage
                || "Authentication required — open from Telegram.";
            return;
        }

        await ensureXtermLoaded();

        const Terminal = window.Terminal;
        const FitAddon = window.FitAddon && window.FitAddon.FitAddon;
        if (!Terminal || !FitAddon) {
            statusEl.textContent = "xterm.js failed to load";
            return;
        }

        const term = new Terminal({
            convertEol: true,
            cursorBlink: false,
            disableStdin: true,
            fontFamily: 'ui-monospace, "SF Mono", Menlo, monospace',
            fontSize: 13,
            theme: {
                background: getComputedStyle(document.body).backgroundColor || "#0e1116",
                foreground: getComputedStyle(document.body).color || "#e6edf3",
            },
        });
        const fit = new FitAddon();
        term.loadAddon(fit);
        term.open(container);
        try { fit.fit(); } catch (e) { /* ignore initial fit failures */ }

        const onResize = () => { try { fit.fit(); } catch (e) { /* ignore */ } };
        window.addEventListener("resize", onResize);

        const token = tokenFromLocation();
        if (!token) {
            statusEl.textContent = "no token in URL";
            return;
        }

        let ws;
        let reconnectDelay = 500;
        let preOpenFails = 0;
        let stopped = false;
        const MAX_DELAY = 8000;

        function scheduleReconnect() {
            statusEl.textContent = "Disconnected — reconnecting in "
                + (reconnectDelay / 1000).toFixed(1) + "s";
            window.setTimeout(connect, reconnectDelay);
            reconnectDelay = Math.min(MAX_DELAY, reconnectDelay * 2);
        }

        function connect() {
            if (stopped) return;
            statusEl.textContent = "Connecting…";
            ws = new WebSocket(wsUrlFor(token));
            let opened = false;
            ws.onopen = () => {
                opened = true;
                preOpenFails = 0;
                statusEl.textContent = "Authenticating…";
                reconnectDelay = 500;
                // Server reads initData from the first frame after upgrade —
                // the WebSocket browser API can't carry custom headers, and
                // putting initData in the URL would leak it into access logs.
                try {
                    ws.send(JSON.stringify({ init_data: initDataRaw() }));
                } catch (e) {
                    // Send failure here means the socket is already gone —
                    // onclose will follow and drive reconnect.
                }
            };
            ws.onmessage = (ev) => {
                let msg;
                try { msg = JSON.parse(ev.data); } catch (e) { return; }
                if (msg.type === "frame" && typeof msg.text === "string") {
                    // Whole-screen replacement: clear, write, no scrollback churn.
                    term.reset();
                    term.write(msg.text);
                } else if (msg.type === "hello") {
                    statusEl.textContent = "Live · " + (msg.window_id || "");
                } else if (msg.type === "error") {
                    statusEl.textContent = "stream error: " + (msg.message || "?");
                }
            };
            ws.onclose = async (ev) => {
                if (stopped) return;
                // Server-driven auth-failure codes are authoritative — stop
                // immediately so we don't churn through retries with bad creds.
                if (ev && WS_AUTH_CODES.has(ev.code)) {
                    stopped = true;
                    statusEl.textContent =
                        "Authentication failed — reopen from Telegram.";
                    return;
                }
                if (!opened) {
                    preOpenFails += 1;
                    if (preOpenFails >= PROBE_AFTER_FAILS) {
                        // The WS API hides the HTTP status — disambiguate
                        // auth from transport via an HTTP probe.
                        const result = await probeAuth(token);
                        if (result === "auth-failed") {
                            stopped = true;
                            statusEl.textContent =
                                "Authentication failed — reopen from Telegram.";
                            return;
                        }
                        // Probe says auth is fine (or itself failed) — assume
                        // transient, reset the counter and keep retrying.
                        preOpenFails = 0;
                    }
                }
                if (stopped) return;
                scheduleReconnect();
            };
            ws.onerror = () => {
                // onclose follows; let it handle reconnect.
            };
        }

        connect();
    }

    function init() {
        const container = document.getElementById("ccgram-terminal");
        const statusEl = document.getElementById("ccgram-status");
        if (!container || !statusEl) return;
        bootTerminal(container, statusEl).catch((err) => {
            statusEl.textContent = "boot failed: " + err.message;
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
