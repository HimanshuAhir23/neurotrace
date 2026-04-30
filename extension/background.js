let sessionId = null;
let sessionReady = false;

let activeTabId = null;
let activeUrl = null;

// -----------------------------
// INIT SESSION
// -----------------------------
initSession();

async function initSession() {
    try {
        const result = await chrome.storage.local.get(["sessionId"]);

        if (result.sessionId) {
            sessionId = result.sessionId;
            console.log("Restored session:", sessionId);
        } else {
            await startSession();
        }

        sessionReady = true;
    } catch (err) {
        console.error("Init session error:", err);
    }
}

async function startSession() {
    try {
        const res = await fetch("http://127.0.0.1:8000/api/start-session/", {
            method: "POST",
            credentials: "include",
            headers: { "Content-Type": "application/json" }
        });

        if (!res.ok) throw new Error("Session API failed");

        const data = await res.json();
        sessionId = data.session_id;

        await chrome.storage.local.set({ sessionId });
        console.log("Session started:", sessionId);
    } catch (err) {
        console.error("Session start failed:", err);
    }
}

// -----------------------------
// FILTER
// -----------------------------
function isValidUrl(url) {
    if (!url || url.startsWith("chrome://") || url.startsWith("edge://")) return false;
    return true;
}

// -----------------------------
// TAB SWITCH
// -----------------------------
chrome.tabs.onActivated.addListener(async (activeInfo) => {
    if (!sessionReady || !sessionId) return;

    try {
        // Send exit for the old tab
        if (activeTabId && activeUrl) {
            sendActivity("page_exit", activeUrl, activeTabId);
        }

        const tab = await chrome.tabs.get(activeInfo.tabId);
        activeTabId = activeInfo.tabId;
        activeUrl = tab.url;

        if (isValidUrl(tab.url)) {
            sendActivity("page_enter", tab.url, activeTabId);
        }
    } catch (err) {
        console.error("Tab switch error:", err);
    }
});

// -----------------------------
// URL CHANGE
// -----------------------------
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
    if (!sessionReady || !sessionId) return;

    if (changeInfo.url) {
        // If it's the active tab that changed URL
        if (tabId === activeTabId) {
            if (activeUrl) {
                sendActivity("page_exit", activeUrl, tabId);
            }
            activeUrl = changeInfo.url;
            if (isValidUrl(changeInfo.url)) {
                sendActivity("page_enter", changeInfo.url, tabId);
            }
        }
    }
});

// -----------------------------
// CONTENT MESSAGES
// -----------------------------
chrome.runtime.onMessage.addListener((message, sender) => {
    if (!sessionReady || !sessionId) return;

    const url = message?.payload?.url;
    if (!url) return;

    const tabId = sender.tab ? sender.tab.id : "default";

    if (message.type === "heartbeat") {
        sendActivity("heartbeat", url, tabId);
    }

    if (message.type === "idle") {
        sendActivity("idle", url, tabId);
    }
    
    if (message.type === "active") {
        // User is back from idle
        sendActivity("page_enter", url, tabId);
    }
});

// -----------------------------
// SEND TO BACKEND
// -----------------------------
function sendActivity(eventType, url, tabId = "default") {
    if (!sessionId || !url) return;

    fetch("http://127.0.0.1:8000/api/log-activity/", {
        method: "POST",
        keepalive: true,
        credentials: "include",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            session_id: sessionId,
            tab_id: String(tabId),
            event_type: eventType,
            metadata: { url }
        })
    })
    .then(async (res) => {
        if (!res.ok) {
            const errorText = await res.text();
            console.error("Backend error:", errorText);
            
            // Auto-heal
            if (res.status === 404 || res.status === 400) {
                console.log("Session invalid. Starting a new session...");
                sessionId = null;
                await chrome.storage.local.remove(["sessionId"]);
                await startSession();
            }
            return;
        }
        return res.json();
    })
    .then(data => {
        if (data) console.log(`Logged ${eventType}:`, data);
    })
    .catch(err => console.error("Network error:", err));
}