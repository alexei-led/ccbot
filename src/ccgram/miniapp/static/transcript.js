// Transcript surface — paginated history + substring search.
//
// Reads its token from the URL path (mirrors terminal.js) and talks to
// /api/transcript/<token>. Renders a threaded view with date markers and a
// simple search input that hits /api/transcript/<token>/search?q=...
//
// Phase 3 read-only; no input forwarding.

(function () {
    "use strict";

    const PAGE_SIZE = 50;

    function tokenFromPath() {
        const m = location.pathname.match(/\/app\/([^/]+)/);
        return m ? m[1] : null;
    }

    function initDataHeaders() {
        const tg = window.Telegram && window.Telegram.WebApp;
        const raw = tg && tg.initData ? tg.initData : "";
        return raw ? { "X-Telegram-Init-Data": raw } : {};
    }

    function fmtDate(iso) {
        if (!iso) return "";
        const d = new Date(iso);
        if (isNaN(d.getTime())) return "";
        return d.toLocaleDateString(undefined, {
            year: "numeric",
            month: "short",
            day: "numeric",
        });
    }

    function fmtTime(iso) {
        if (!iso) return "";
        const d = new Date(iso);
        if (isNaN(d.getTime())) return "";
        return d.toLocaleTimeString(undefined, {
            hour: "2-digit",
            minute: "2-digit",
        });
    }

    function el(tag, opts) {
        const node = document.createElement(tag);
        if (opts) {
            if (opts.cls) node.className = opts.cls;
            if (opts.text != null) node.textContent = opts.text;
        }
        return node;
    }

    function renderEntry(msg) {
        const wrap = el("div", { cls: "ccgram-msg ccgram-msg-" + (msg.role || "assistant") });
        const head = el("div", { cls: "ccgram-msg-head" });
        const role = msg.role === "user" ? "👤" : "🤖";
        head.appendChild(el("span", { cls: "ccgram-msg-role", text: role }));
        const time = fmtTime(msg.timestamp);
        if (time) head.appendChild(el("span", { cls: "ccgram-msg-time", text: time }));
        if (msg.content_type && msg.content_type !== "text") {
            head.appendChild(el("span", { cls: "ccgram-msg-kind", text: msg.content_type }));
        }
        wrap.appendChild(head);
        wrap.appendChild(el("pre", { cls: "ccgram-msg-body", text: msg.text || "" }));
        return wrap;
    }

    function renderPage(container, messages, opts) {
        let lastDate = opts && opts.lastDate ? opts.lastDate : "";
        for (const msg of messages) {
            const date = fmtDate(msg.timestamp);
            if (date && date !== lastDate) {
                container.appendChild(el("div", { cls: "ccgram-date-marker", text: date }));
                lastDate = date;
            }
            container.appendChild(renderEntry(msg));
        }
        return lastDate;
    }

    function authError(message) {
        const err = new Error(message);
        err.authFailed = true;
        return err;
    }

    async function fetchPage(token, cursor) {
        const url = "/api/transcript/" + encodeURIComponent(token) +
            "?cursor=" + cursor + "&limit=" + PAGE_SIZE;
        const resp = await fetch(url, { credentials: "omit", headers: initDataHeaders() });
        if (resp.status === 403) throw authError("authentication failed");
        if (resp.status === 404) {
            return { messages: [], total: 0, next_cursor: null, missing: true };
        }
        if (!resp.ok) throw new Error("transcript fetch failed: " + resp.status);
        return await resp.json();
    }

    async function fetchSearch(token, query) {
        const url = "/api/transcript/" + encodeURIComponent(token) +
            "/search?q=" + encodeURIComponent(query);
        const resp = await fetch(url, { credentials: "omit", headers: initDataHeaders() });
        if (resp.status === 403) throw authError("authentication failed");
        if (resp.status === 404) return { matches: [], missing: true };
        if (!resp.ok) throw new Error("search failed: " + resp.status);
        return await resp.json();
    }

    function ensureStyles() {
        if (document.getElementById("ccgram-transcript-styles")) return;
        const style = document.createElement("style");
        style.id = "ccgram-transcript-styles";
        style.textContent = `
        #ccgram-transcript {
            margin-top: 1.5rem;
            font-family: ui-monospace, "SF Mono", Menlo, monospace;
            font-size: 0.85rem;
        }
        .ccgram-transcript-controls {
            display: flex;
            gap: 0.5rem;
            margin-bottom: 0.5rem;
        }
        .ccgram-transcript-controls input {
            flex: 1;
            padding: 0.4rem 0.6rem;
            background: var(--bg);
            color: var(--fg);
            border: 1px solid var(--hint);
            border-radius: 4px;
        }
        .ccgram-transcript-controls button {
            padding: 0.4rem 0.8rem;
            background: var(--accent);
            color: var(--fg);
            border: none;
            border-radius: 4px;
            cursor: pointer;
        }
        .ccgram-date-marker {
            text-align: center;
            color: var(--hint);
            margin: 1rem 0 0.5rem;
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        .ccgram-msg {
            margin: 0.5rem 0;
            padding: 0.5rem 0.75rem;
            border-radius: 6px;
            background: rgba(127, 127, 127, 0.08);
        }
        .ccgram-msg-user { border-left: 3px solid var(--accent); }
        .ccgram-msg-assistant { border-left: 3px solid var(--hint); }
        .ccgram-msg-head {
            display: flex;
            gap: 0.5rem;
            font-size: 0.75rem;
            color: var(--hint);
            margin-bottom: 0.25rem;
        }
        .ccgram-msg-body {
            margin: 0;
            white-space: pre-wrap;
            word-break: break-word;
            font-family: inherit;
            font-size: inherit;
        }
        .ccgram-status {
            color: var(--hint);
            text-align: center;
            margin: 1rem 0;
        }`;
        document.head.appendChild(style);
    }

    function renderSearchResults(host, data) {
        host.innerHTML = "";
        if (data.missing) {
            host.appendChild(el("div", { cls: "ccgram-status", text: "No session for this window." }));
            return;
        }
        if (!data.matches || data.matches.length === 0) {
            host.appendChild(el("div", { cls: "ccgram-status", text: "No matches." }));
            return;
        }
        const headerText = data.matches.length + " match"
            + (data.matches.length === 1 ? "" : "es")
            + (data.truncated ? " (more — refine your query)" : "");
        const header = el("div", { cls: "ccgram-status", text: headerText });
        host.appendChild(header);
        for (const match of data.matches) {
            if (match.before) host.appendChild(renderEntry(match.before));
            const main = renderEntry(match.entry);
            main.style.outline = "2px solid var(--accent)";
            host.appendChild(main);
            if (match.after) host.appendChild(renderEntry(match.after));
        }
    }

    async function init() {
        const token = tokenFromPath();
        const root = document.getElementById("ccgram-transcript");
        if (!token || !root) return;
        if (window.__ccgramAuthFailed) return;

        ensureStyles();

        const controls = el("div", { cls: "ccgram-transcript-controls" });
        const input = document.createElement("input");
        input.type = "search";
        input.placeholder = "Search transcript…";
        input.setAttribute("aria-label", "search transcript");
        const searchBtn = el("button", { text: "Search" });
        const moreBtn = el("button", { text: "Load older" });
        controls.appendChild(input);
        controls.appendChild(searchBtn);
        controls.appendChild(moreBtn);
        root.appendChild(controls);

        const status = el("div", { cls: "ccgram-status", text: "Loading transcript…" });
        root.appendChild(status);

        const list = el("div", { cls: "ccgram-transcript-list" });
        root.appendChild(list);

        let cursor = 0;
        let lastDate = "";
        let total = 0;
        let mode = "list";

        async function loadMore() {
            try {
                const data = await fetchPage(token, cursor);
                if (data.missing) {
                    status.textContent = "No session for this window yet.";
                    moreBtn.disabled = true;
                    return;
                }
                total = data.total;
                lastDate = renderPage(list, data.messages || [], { lastDate });
                if (data.next_cursor == null) {
                    moreBtn.disabled = true;
                    status.textContent = total
                        ? "Loaded " + total + " message" + (total === 1 ? "" : "s") + "."
                        : "No messages.";
                } else {
                    cursor = data.next_cursor;
                    status.textContent = "Loaded " + cursor + " of " + total + ".";
                }
            } catch (err) {
                if (err && err.authFailed) {
                    status.textContent =
                        "Authentication expired — reopen from Telegram.";
                    moreBtn.disabled = true;
                    searchBtn.disabled = true;
                    input.disabled = true;
                    return;
                }
                status.textContent = "Error: " + err.message;
            }
        }

        async function runSearch(query) {
            try {
                status.textContent = "Searching for " + JSON.stringify(query) + "…";
                const data = await fetchSearch(token, query);
                list.innerHTML = "";
                renderSearchResults(list, data);
                status.textContent = "";
                mode = "search";
                moreBtn.disabled = true;
            } catch (err) {
                if (err && err.authFailed) {
                    status.textContent =
                        "Authentication expired — reopen from Telegram.";
                    moreBtn.disabled = true;
                    searchBtn.disabled = true;
                    input.disabled = true;
                    return;
                }
                status.textContent = "Error: " + err.message;
            }
        }

        function resetToList() {
            mode = "list";
            cursor = 0;
            lastDate = "";
            list.innerHTML = "";
            status.textContent = "Loading transcript…";
            moreBtn.disabled = false;
            loadMore();
        }

        searchBtn.addEventListener("click", () => {
            const q = input.value.trim();
            if (!q) {
                if (mode === "search") resetToList();
                return;
            }
            runSearch(q);
        });
        input.addEventListener("keydown", (ev) => {
            if (ev.key === "Enter") {
                ev.preventDefault();
                searchBtn.click();
            }
            if (ev.key === "Escape" && mode === "search") {
                input.value = "";
                resetToList();
            }
        });
        moreBtn.addEventListener("click", loadMore);

        await loadMore();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
