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

    function tokenFromLocation() {
        const m = window.location.pathname.match(/^\/app\/([^/]+)/);
        return m ? m[1] : null;
    }

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

    async function fetchPanes(token) {
        const resp = await fetch("/api/panes/" + token, {
            credentials: "same-origin",
        });
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

        const ws = new WebSocket(wsUrlFor(token, paneId));
        ws.onmessage = (ev) => {
            let msg;
            try { msg = JSON.parse(ev.data); } catch (e) { return; }
            if (msg.type === "frame" && typeof msg.text === "string") {
                term.reset();
                term.write(msg.text);
            }
        };
        ws.onerror = () => { /* close handler will follow */ };

        return {
            close() {
                try { ws.close(); } catch (e) { /* ignore */ }
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
        for (const pane of panes) {
            const { tile, term } = makeTile(pane);
            container.appendChild(tile);
            attachTerminal(term, token, pane.pane_id, statusEl).then((handle) => {
                if (handle) tiles.push(handle);
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
        const token = tokenFromLocation();
        if (!token) return;

        let panes = [];
        try {
            panes = await fetchPanes(token);
        } catch (err) {
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
        const showGrid = () => {
            if (active) active.teardown();
            active = renderGrid(container, panes, token, statusEl, (p) => {
                if (active) active.teardown();
                active = renderFocused(container, p, token, statusEl, showGrid);
            });
        };

        showGrid();

        const refreshTimer = window.setInterval(async () => {
            try {
                const fresh = await fetchPanes(token);
                // Only rebuild grid when pane composition changes (count or IDs).
                const oldKey = panes.map((p) => p.pane_id).sort().join(",");
                const newKey = fresh.map((p) => p.pane_id).sort().join(",");
                if (oldKey !== newKey) {
                    panes = fresh;
                    if (panes.length <= 1) {
                        container.style.display = "none";
                        if (active) active.teardown();
                        return;
                    }
                    container.style.display = "";
                    showGrid();
                }
            } catch (e) { /* transient — try again */ }
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
