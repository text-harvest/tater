/* Tell the annotator when their changes stop reaching the server.
 *
 * Dash shows nothing when a callback request fails (outside debug mode): the page keeps
 * working on screen while edits are lost. This watches tater's callback requests and,
 * on the first failure, shows a banner that stays until the page is reloaded (the
 * failed change is gone even if later requests succeed).
 *
 * The project launcher marks its own refusals with an X-Tater-Launcher header:
 * "signed-out" (the person's link was reissued, or they're no longer in the project)
 * or "unavailable" (their tater process couldn't be started or reached).
 */
(function () {
    if (!window.fetch || window._taterRequestGuard) return;
    window._taterRequestGuard = true;

    var MESSAGES = {
        "signed-out": "You've been signed out of this project, so your recent changes weren't saved. " +
                      "Open your current link to carry on.",
        "unavailable": "Your session stopped unexpectedly and your last change wasn't saved. " +
                       "Reload the page to carry on.",
        "network": "Tater can't reach its server, so your changes aren't being saved. " +
                   "Reload the page once it's running again.",
        "error": "Your last change couldn't be saved (error {status}). Reload the page to carry on."
    };

    function showBanner(kind, status) {
        if (document.getElementById("tater-request-error")) return;
        var bar = document.createElement("div");
        bar.id = "tater-request-error";
        bar.setAttribute("role", "alert");
        bar.dataset.kind = kind;
        bar.style.cssText = [
            "position:fixed", "left:0", "right:0", "top:0", "z-index:10000",
            "display:flex", "flex-wrap:wrap", "align-items:center", "justify-content:center", "gap:12px",
            "padding:10px 16px", "font:14px/1.4 var(--mantine-font-family, system-ui, sans-serif)",
            "background:var(--mantine-color-red-filled, #e03131)", "color:#fff",
            "box-shadow:0 2px 6px rgba(0,0,0,.25)"
        ].join(";");
        var text = document.createElement("span");
        text.textContent = MESSAGES[kind].replace("{status}", status);
        bar.appendChild(text);
        if (kind !== "signed-out") {
            var btn = document.createElement("button");
            btn.type = "button";
            btn.textContent = "Reload";
            btn.style.cssText = "font:inherit;font-weight:600;padding:3px 12px;border-radius:4px;" +
                                "border:1px solid #fff;background:transparent;color:#fff;cursor:pointer";
            btn.addEventListener("click", function () { window.location.reload(); });
            bar.appendChild(btn);
        }
        (document.body || document.documentElement).appendChild(bar);
    }

    function isCallback(input) {
        var url = typeof input === "string" ? input : (input && input.url) || "";
        return url.indexOf("_dash-update-component") !== -1;
    }

    var originalFetch = window.fetch;
    window.fetch = function (input, init) {
        var request = originalFetch.apply(this, arguments);
        if (!isCallback(input)) return request;
        return request.then(function (response) {
            if (!response.ok) {
                var mark = response.headers.get("X-Tater-Launcher");
                showBanner(MESSAGES[mark] ? mark : "error", response.status);
            }
            return response;
        }, function (err) {
            // Leaving or reloading the page aborts requests; that isn't a failure.
            if (!(err && err.name === "AbortError")) showBanner("network");
            throw err;
        });
    };
})();
