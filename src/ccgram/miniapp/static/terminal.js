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

    function tokenFromLocation() {
        const m = window.location.pathname.match(/^\/app\/([^/]+)/);
        return m ? m[1] : null;
    }

    function wsUrlFor(token) {
        const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
        return proto + "//" + window.location.host + "/ws/terminal/" + token;
    }

    async function bootTerminal(container, statusEl) {
        await Promise.all([loadStyle(XTERM_CSS), loadScript(XTERM_JS)]);
        await loadScript(FIT_JS);

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
        const MAX_DELAY = 8000;

        function connect() {
            statusEl.textContent = "Connecting…";
            ws = new WebSocket(wsUrlFor(token));
            ws.onopen = () => {
                statusEl.textContent = "Live";
                reconnectDelay = 500;
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
            ws.onclose = () => {
                statusEl.textContent = "Disconnected — reconnecting in " + (reconnectDelay / 1000).toFixed(1) + "s";
                window.setTimeout(connect, reconnectDelay);
                reconnectDelay = Math.min(MAX_DELAY, reconnectDelay * 2);
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
