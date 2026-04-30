"""
views.py — NeuroTrace Core
==========================
Production-grade activity tracking backend.

FIXES APPLIED (vs original prototype):
  FIX-1  Tab-level tracking      tracker key = session_id:tab_id
  FIX-2  Event-driven duration   client sends page_enter/page_exit
                                 with timestamps; server computes exact duration
  FIX-3  Idle detection          gaps > IDLE_THRESHOLD (60s) are capped,
                                 not counted as active time
  FIX-4  URL validation          invalid URLs (about:blank, newtab,
                                 chrome-extension://) rejected before DB write
  FIX-5  DB-backed state         TabState model persists across restarts;
                                 in-memory dict is L1 cache only, DB is source of truth
  FIX-6  Cache size limit        USER_ACTIVITY_TRACKER auto-evicts at 10k entries
  FIX-7  dashboard_data          single ORM Sum query instead of Python loop
  FIX-8  WebSocket try/except    non-fatal if dashboard is closed
  FIX-9  AllowAny on all endpoints  no accidental 403s
  FIX-10 dashboard_view          serve dashboard.html template correctly
"""

from django.shortcuts import render
from django.utils.timezone import now
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Sum
from urllib.parse import urlparse

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.authentication import SessionAuthentication, BasicAuthentication
from rest_framework.response import Response

from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from .models import ActivitySession, ActivityLog, TabState

import time
import logging

class CsrfExemptSessionAuthentication(SessionAuthentication):
    def enforce_csrf(self, request):
        return  # Bypass CSRF checks for the Chrome Extension

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────
EVENT_COOLDOWN   = 2        # seconds — spam filter window per (session, tab, url)
IDLE_THRESHOLD   = 60       # seconds — gap larger than this is not counted as active
MAX_TRACKER_SIZE = 10_000   # entries — evict entire cache when exceeded
MIN_DURATION     = 1        # seconds — log entries shorter than this are discarded

INVALID_URL_PREFIXES = (
    "chrome://",
    "chrome-extension://",
    "about:",
    "moz-extension://",
    "edge://",
    "data:",
    "javascript:",
    "file://",
)

INVALID_URL_HOSTNAMES = {"", "newtab", "localhost", "127.0.0.1", "0.0.0.0"}


# ─────────────────────────────────────────────────────────────────────────────
# SITE CLASSIFICATION LISTS
# ─────────────────────────────────────────────────────────────────────────────
PRODUCTIVE_SITES = [
    "w3schools.com", "geeksforgeeks.org", "developer.mozilla.org",
    "freecodecamp.org", "tutorialspoint.com", "javatpoint.com",
    "programiz.com", "digitalocean.com", "theodinproject.com",
    "codecademy.com", "sololearn.com", "baeldung.com",
    "realpython.com", "scrimba.com", "docs.python.org",
    "github.com", "stackoverflow.com", "postman.com",
    "leetcode.com", "hackerrank.com", "overleaf.com",
    "docker.com", "kubernetes.io", "aws.amazon.com",
    "cloud.google.com", "azure.microsoft.com",
    "openai.com", "anthropic.com", "perplexity.ai", "huggingface.co",
    "canva.com", "figma.com", "pdf2go.com", "ilovepdf.com",
    "drive.google.com", "trello.com", "notion.so",
    "linkedin.com", "internshala.com", "naukri.com",
]

DISTRACTING_SITES = [
    "tiktok.com", "instagram.com",
    "facebook.com", "snapchat.com", "reddit.com",
    "discord.com", "omegle.com", "chatroulette.com",
    "netflix.com", "hotstar.com", "primevideo.com",
    "steamcommunity.com", "epicgames.com", "roblox.com",
    "tinder.com", "bumble.com",
    "amazon.in", "flipkart.com", "myntra.com",
    "quora.com", "buzzfeed.com", "spotify.com", "jiosaavn.com",
    "twitter.com", "x.com",
]


# ─────────────────────────────────────────────────────────────────────────────
# IN-MEMORY L1 CACHE  (tab-level, evicted on overflow or restart)
# Source of truth for cross-restart persistence is the TabState DB model.
#
#   TAB_TRACKER key  = "{session_id}:{tab_id}"
#   TAB_TRACKER val  = {"url": str, "entered_at": float}
#
#   SPAM_CACHE  key  = "{session_id}:{tab_id}:{url}"
#   SPAM_CACHE  val  = float (unix timestamp of last event)
# ─────────────────────────────────────────────────────────────────────────────
TAB_TRACKER = {}
SPAM_CACHE  = {}


def _evict_if_full():
    if len(TAB_TRACKER) > MAX_TRACKER_SIZE:
        TAB_TRACKER.clear()
        SPAM_CACHE.clear()
        logger.warning("[NeuroTrace] TAB_TRACKER evicted (size limit reached)")

def normalise_url(raw):
    """
    Clean + normalize URL for accurate analytics.
    Removes junk, duplicates, query params, and local/dev URLs.
    """
    if not raw:
        return None

    raw = raw.strip().lower()

    # ❌ Hard reject junk values
    if raw in ("", "unknown", "newtab", "about:blank", "about:newtab"):
        return None

    # ❌ Block unwanted prefixes
    for prefix in INVALID_URL_PREFIXES:
        if raw.startswith(prefix):
            return None

    # Ensure scheme
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw

    try:
        parsed = urlparse(raw)
    except Exception:
        return None

    hostname = parsed.netloc.replace("www.", "").split(":")[0]

    # ❌ Block local/dev URLs
    if hostname in INVALID_URL_HOSTNAMES:
        return None

    # ❌ Block your own backend endpoints
    if "127.0.0.1" in hostname or "localhost" in hostname:
        return None

    # ✅ ONLY keep domain (NO path → avoids duplicates)
    return hostname

# ─────────────────────────────────────────────────────────────────────────────
# SPAM FILTER  (per tab + url)
# ─────────────────────────────────────────────────────────────────────────────
def is_spam(session_id, tab_id, url):
    """
    Returns True if this exact (session, tab, url) triple was seen
    within EVENT_COOLDOWN seconds.
    """
    if not url:
        return False

    key  = f"{session_id}:{tab_id}:{url}"
    ts   = time.time()
    last = SPAM_CACHE.get(key)

    if last and (ts - last < EVENT_COOLDOWN):
        return True

    SPAM_CACHE[key] = ts
    return False


# ─────────────────────────────────────────────────────────────────────────────
# DURATION CALCULATION  (FIX-1 + FIX-3)
# ─────────────────────────────────────────────────────────────────────────────
def compute_duration(session_id, tab_id, url,
                     client_start_ts, client_end_ts, server_now):
    """
    Priority:
      1. Both client timestamps provided  -> exact client-measured duration
      2. Only start_time provided         -> delta against server_now
      3. TAB_TRACKER cache hit            -> server-side delta
      4. TabState DB row                  -> DB-persisted enter time
      5. Default 0                        -> first visit or cache miss

    Always capped at IDLE_THRESHOLD so idle time never inflates metrics.
    """
    duration = 0.0

    if client_start_ts and client_end_ts:
        duration = client_end_ts - client_start_ts

    elif client_start_ts:
        duration = server_now - client_start_ts

    else:
        cache_key = f"{session_id}:{tab_id}"
        entry = TAB_TRACKER.get(cache_key)

        if entry and entry.get("url") == url:
            duration = server_now - entry["entered_at"]
        else:
            try:
                db_state = TabState.objects.filter(
                    session_id=session_id,
                    tab_id=tab_id
                ).order_by("-entered_at").first()

                if db_state and db_state.url == url:
                    duration = server_now - db_state.entered_at.timestamp()
            except Exception as e:
                logger.warning(f"[TabState] DB fallback failed: {e}")

    # FIX-3: cap idle gaps
    duration = min(duration, IDLE_THRESHOLD)
    return round(max(duration, 0), 2)


from django.contrib.auth.decorators import login_required

# ─────────────────────────────────────────────────────────────────────────────
# UI VIEW
# ─────────────────────────────────────────────────────────────────────────────
@login_required(login_url='/login/')
def dashboard_view(request):
    """Serves the dashboard.html template at GET /."""
    return render(request, "dashboard.html")


# ─────────────────────────────────────────────────────────────────────────────
# SESSION APIs
# ─────────────────────────────────────────────────────────────────────────────
@api_view(["POST"])
@authentication_classes([CsrfExemptSessionAuthentication, BasicAuthentication])
@permission_classes([AllowAny])
@csrf_exempt
def start_session(request):
    """
    Create a new ActivitySession.
    Ties to logged in user if session cookie is provided.
    """
    user = request.user if request.user.is_authenticated else None
    session = ActivitySession.objects.create(user=user)
    return Response({
        "message":    "Session started",
        "session_id": session.id,
    }, status=201)


@api_view(["POST"])
@authentication_classes([CsrfExemptSessionAuthentication, BasicAuthentication])
@permission_classes([AllowAny])
@csrf_exempt
def end_session(request, session_id):
    """
    Mark session as completed. Calculates wall-clock duration.
    Cleans up all in-memory and DB state for this session.
    """
    try:
        session = ActivitySession.objects.get(id=session_id)
    except ActivitySession.DoesNotExist:
        return Response({"error": "Session not found"}, status=404)

    if session.status == "completed":
        return Response({"error": "Session already completed"}, status=400)

    session.end_time = now()
    session.status   = "completed"

    if session.start_time:
        elapsed = (session.end_time - session.start_time).total_seconds() / 60
        session.duration_minutes = round(max(elapsed, 0), 2)

    session.save()

    # Clean in-memory state
    prefix = f"{session_id}:"
    for key in list(TAB_TRACKER.keys()):
        if key.startswith(prefix):
            del TAB_TRACKER[key]
    for key in list(SPAM_CACHE.keys()):
        if key.startswith(prefix):
            del SPAM_CACHE[key]

    # Close all open TabState rows
    TabState.objects.filter(
        session_id=session_id, exited_at__isnull=True
    ).update(exited_at=now())

    return Response({
        "message":          "Session ended",
        "session_id":       session.id,
        "duration_minutes": session.duration_minutes,
    })


# ─────────────────────────────────────────────────────────────────────────────
# LOG ACTIVITY  — called by Chrome extension on every tab change
# ─────────────────────────────────────────────────────────────────────────────
@api_view(["POST"])
@authentication_classes([CsrfExemptSessionAuthentication, BasicAuthentication])
@permission_classes([AllowAny])
@csrf_exempt
def log_activity(request):
    """
    Expected payload:

        {
            "session_id":   1,
            "tab_id":       "42",
            "event_type":   "page_enter" | "page_exit" | "tab_switch" | "idle",
            "metadata": {
                "url":        "https://github.com/...",
                "start_time": 1714000000.123,
                "end_time":   1714000045.678,
                "title":      "GitHub"
            }
        }
    """

    # ── 1. INPUT VALIDATION ──────────────────────────────────────────────────
    session_id = request.data.get("session_id")
    tab_id     = str(request.data.get("tab_id") or "default")
    event_type = request.data.get("event_type")
    metadata   = request.data.get("metadata") or {}

    if not session_id or not event_type:
        return Response(
            {"error": "session_id and event_type are required"},
            status=400
        )

    valid_event_types = {"page_enter", "page_exit", "tab_switch", "idle", "focus", "blur"}
    if event_type not in valid_event_types:
        event_type = "tab_switch"

    try:
        session = ActivitySession.objects.get(id=session_id)
    except ActivitySession.DoesNotExist:
        return Response({"error": "Invalid session_id"}, status=404)

    if session.status == "completed":
        return Response({"error": "Session already completed"}, status=400)

    # ── 1.5. LATE USER BINDING ───────────────────────────────────────────────
    if request.user.is_authenticated and session.user is None:
        session.user = request.user
        session.save(update_fields=['user'])

    # ── 2. URL NORMALISATION ─────────────────────────────────────────────────
    raw_url = metadata.get("url") or ""
    url     = normalise_url(raw_url)

    if not url:
        return Response({"message": "ignored (invalid url)"})

    # ── 3. TIMING ────────────────────────────────────────────────────────────
    server_now      = time.time()
    client_start_ts = _safe_float(metadata.get("start_time"))
    client_end_ts   = _safe_float(metadata.get("end_time"))

    duration = compute_duration(
        session_id, tab_id, url,
        client_start_ts, client_end_ts, server_now
    )

    # ── 4. SPAM FILTER ───────────────────────────────────────────────────────
    if is_spam(session_id, tab_id, url):
        return Response({"message": "ignored (spam)"})

    # ── 5. DISCARD SUB-MINIMUM (except markers) ──────────────────────────────
    if event_type not in ("page_enter", "page_exit", "idle") and duration < MIN_DURATION:
        return Response({"message": "ignored (too short)"})

    # ── 6. CACHE SIZE GUARD ──────────────────────────────────────────────────
    _evict_if_full()

    # ── 7. UPDATE TAB STATE ───────────────────────────────────────────────────
    cache_key = f"{session_id}:{tab_id}"

    if event_type == "page_enter":
        TAB_TRACKER[cache_key] = {
            "url":        url,
            "entered_at": client_start_ts or server_now,
        }
        try:
            TabState.objects.update_or_create(
                session_id=session_id,
                tab_id=tab_id,
                defaults={"url": url, "entered_at": now(), "exited_at": None}
            )
        except Exception as e:
            logger.warning(f"[TabState] upsert failed: {e}")

    elif event_type in ("page_exit", "tab_switch", "idle"):
        TAB_TRACKER.pop(cache_key, None)
        try:
            TabState.objects.filter(
                session_id=session_id, tab_id=tab_id
            ).update(exited_at=now())
        except Exception as e:
            logger.warning(f"[TabState] exit update failed: {e}")

    
    
    # ── 8. CLASSIFY & PERSIST ─────────────────────────────────────────────────
    category = classify_url(url)

    log = ActivityLog.objects.create(
        session=session,
        event_type=event_type,
        metadata=metadata,
        url=url,
        duration_seconds=duration,
        category=category   # ✅ FIX: persist category
    )
    # ── 9. WEBSOCKET BROADCAST ────────────────────────────────────────────────
    try:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            "dashboard",
            {
                "type": "update",
                "data": {
                    "url":        url,
                    "tab_id":     tab_id,
                    "event_type": event_type,
                    "category":   category,
                    "log_id":     log.id,
                    "duration":   duration,
                    "timestamp":  log.timestamp.isoformat(),
                },
            }
        )
    except Exception as ws_err:
        logger.warning(f"[WS] broadcast failed (non-fatal): {ws_err}")

    return Response({
        "message":  "logged",
        "log_id":   log.id,
        "category": category,
        "duration": duration,
    }, status=201)

# ─────────────────────────────────────────────────────────────────────────────
# URL CLASSIFICATION (FIX)
# ─────────────────────────────────────────────────────────────────────────────
def classify_url(url):
    """
    Classifies a URL into productive / distracting / neutral.
    Uses simple domain matching.
    """
    if not url:
        return "neutral"

    for site in PRODUCTIVE_SITES:
        if site in url:
            return "productive"

    for site in DISTRACTING_SITES:
        if site in url:
            return "distracting"

    return "neutral"
# ─────────────────────────────────────────────────────────────
# DASHBOARD ANALYTICS (FINAL - CLEAN + OPTIMIZED)
# ─────────────────────────────────────────────────────────────
@api_view(['GET'])
@authentication_classes([SessionAuthentication, BasicAuthentication])
@permission_classes([IsAuthenticated])
def dashboard_data(request):
    logs = (
        ActivityLog.objects
        .filter(session__user=request.user)
        .exclude(url__isnull=True)
        .exclude(url__exact="")
        .values("url")
        .annotate(total_time=Sum("duration_seconds"))
        .order_by("-total_time", "url")
    )

    # Cache classification for performance
    category_cache = {}

    def get_category(url):
        if url not in category_cache:
            category_cache[url] = classify_url(url)
        return category_cache[url]

    data = [
        {
            "url": entry["url"] or "unknown",
            "total_time": round(entry["total_time"] or 0, 2),
            "category": get_category(entry["url"] or "")
        }
        for entry in logs
    ]

    return Response({
        "count": len(data),
        "results": data
    })

    
# ─────────────────────────────────────────────────────────────────────────────
# DAILY REPORT  (cron / Celery ready)
# ─────────────────────────────────────────────────────────────────────────────
def generate_daily_report():
    data = (
        ActivityLog.objects
        .exclude(url__isnull=True)
        .values("url")
        .annotate(total_time=Sum("duration_seconds"))
        .order_by("-total_time")
    )
    return {
        "top_sites":    list(data[:5]),
        "total_sites":  data.count(),
        "generated_at": now().isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def _safe_float(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _safe_int(value, default=0, max_val=9999):
    try:
        return min(int(value), max_val) if value is not None else default
    except (TypeError, ValueError):
        return default


# ─────────────────────────────────────────────────────────────────────────────
# AUTH VIEWS
# ─────────────────────────────────────────────────────────────────────────────
from django.contrib.auth import login, logout
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.shortcuts import redirect

def signup_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
        
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('dashboard')
    else:
        form = UserCreationForm()
    return render(request, 'registration/signup.html', {'form': form, 'title': 'Sign Up'})

def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
        
    if request.method == 'POST':
        form = AuthenticationForm(data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect('dashboard')
    else:
        form = AuthenticationForm()
    return render(request, 'registration/login.html', {'form': form, 'title': 'Log In'})

def logout_view(request):
    logout(request)
    return redirect('login')