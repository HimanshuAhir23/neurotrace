let lastActivity = Date.now();
let isUserActive = true;

// -----------------------------
// ACTIVITY UPDATE (CONTROLLED)
// -----------------------------
function updateActivity() {
  lastActivity = Date.now();

  // mark user as active again
  if (!isUserActive) {
    isUserActive = true;

    // ✅ send "active again" signal (NEW - improves tracking accuracy)
    chrome.runtime.sendMessage({
      type: "active",
      payload: {
        url: window.location.href
      }
    });
  }
}

// -----------------------------
// EVENT LISTENERS (OPTIMIZED)
// -----------------------------
document.addEventListener("click", updateActivity, { passive: true });
document.addEventListener("scroll", updateActivity, { passive: true });
document.addEventListener("keydown", updateActivity);

// -----------------------------
// SAFE MESSAGE SENDER (MV3 FIX)
// -----------------------------
function safeSend(message) {
  try {
    chrome.runtime.sendMessage(message, () => {
      // ✅ prevents "Receiving end does not exist" error
      if (chrome.runtime.lastError) {
        // silent fail (service worker might be inactive)
      }
    });
  } catch (err) {
    console.error("Message send error:", err);
  }
}

// -----------------------------
// IDLE DETECTION (ANTI-AFK CORE)
// -----------------------------
setInterval(() => {
  const now = Date.now();
  const idleTime = now - lastActivity;

  // if idle > 60 sec → mark AFK
  if (idleTime > 60000 && isUserActive) {
    isUserActive = false;

    safeSend({
      type: "idle",
      payload: {
        url: window.location.href,
        idleTime: idleTime
      }
    });
  }
}, 5000);

// -----------------------------
// HEARTBEAT (SENDS CLEAN SIGNAL)
// -----------------------------
setInterval(() => {
  safeSend({
    type: "heartbeat",
    payload: {
      url: window.location.href,
      lastActiveTime: lastActivity,
      isActive: isUserActive
    }
  });
}, 30000);

// -----------------------------
// PAGE VISIBILITY (IMPORTANT FIX)
// -----------------------------
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    // tab not visible → treat as idle
    safeSend({
      type: "idle",
      payload: {
        url: window.location.href,
        idleTime: Date.now() - lastActivity
      }
    });
  } else {
    // tab visible again → mark active
    updateActivity();
  }
});