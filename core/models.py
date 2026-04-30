from django.db import models
from django.contrib.auth.models import User


# ─────────────────────────────────────────────────────────────────────────────
# SESSION MODEL
# ─────────────────────────────────────────────────────────────────────────────
class ActivitySession(models.Model):

    STATUS_ACTIVE    = "active"
    STATUS_COMPLETED = "completed"
    STATUS_CHOICES   = [
        (STATUS_ACTIVE,    "Active"),
        (STATUS_COMPLETED, "Completed"),
    ]

    user     = models.ForeignKey(
        User, on_delete=models.CASCADE,
        null=True, blank=True
    )
    status   = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
        db_index=True
    )
    start_time       = models.DateTimeField(auto_now_add=True)
    end_time         = models.DateTimeField(null=True, blank=True)
    duration_minutes = models.FloatField(null=True, blank=True)
    created_at       = models.DateTimeField(auto_now_add=True, null=True, blank=True)

    class Meta:
        ordering = ["-start_time"]

    def __str__(self):
        user_label = self.user.username if self.user else "anonymous"
        return f"Session #{self.id} | {user_label} | {self.status}"


# ─────────────────────────────────────────────────────────────────────────────
# ACTIVITY LOG MODEL
# ─────────────────────────────────────────────────────────────────────────────
class ActivityLog(models.Model):

    session  = models.ForeignKey(
        ActivitySession,
        on_delete=models.CASCADE,
        related_name="logs"
    )
    event_type       = models.CharField(max_length=50, db_index=True)
    timestamp        = models.DateTimeField(auto_now_add=True, db_index=True)
    metadata         = models.JSONField(null=True, blank=True)
    url              = models.CharField(max_length=2048, null=True, blank=True, db_index=True)
    duration_seconds = models.FloatField(null=True, blank=True)
    category = models.CharField(max_length=20, default="neutral")

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"[{self.event_type}] {self.url or 'no-url'} @ {self.timestamp:%Y-%m-%d %H:%M}"


# ─────────────────────────────────────────────────────────────────────────────
# TAB STATE MODEL  (NEW — FIX-5)
#
# Replaces USER_ACTIVITY_TRACKER = {} in-memory dict.
# Persists across server restarts; safe under multiple Gunicorn workers.
# One row per (session, tab_id) pair — updated on every page_enter/exit.
# ─────────────────────────────────────────────────────────────────────────────
class TabState(models.Model):

    session    = models.ForeignKey(
        ActivitySession,
        on_delete=models.CASCADE,
        related_name="tab_states"
    )

    # Chrome's tab.id as string — unique within a browser session
    tab_id     = models.CharField(max_length=64, db_index=True)

    # Current or most recent URL on this tab
    url        = models.CharField(max_length=2048, null=True, blank=True)

    # When the user navigated to this URL
    entered_at = models.DateTimeField(null=True, blank=True)

    # None = tab still open; populated when user leaves the page
    exited_at  = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("session", "tab_id")]
        ordering        = ["-entered_at"]
        indexes         = [
            models.Index(fields=["session", "tab_id"]),
        ]

    def __str__(self):
        status = "open" if self.exited_at is None else "closed"
        return f"Tab {self.tab_id} | {self.url or 'no-url'} | {status}"

    @property
    def duration_seconds(self):
        from django.utils.timezone import now
        end = self.exited_at or now()
        if self.entered_at:
            return round((end - self.entered_at).total_seconds(), 2)
        return 0.0