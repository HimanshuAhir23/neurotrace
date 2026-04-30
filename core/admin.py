from django.contrib import admin
from .models import ActivitySession, ActivityLog, TabState


@admin.register(ActivitySession)
class ActivitySessionAdmin(admin.ModelAdmin):
    list_display    = ('id', 'user', 'status', 'start_time', 'end_time', 'duration_minutes')
    list_filter     = ('status',)
    search_fields   = ('user__username',)
    ordering        = ('-start_time',)
    readonly_fields = ('start_time', 'created_at')


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display    = ('id', 'session', 'event_type', 'url', 'duration_seconds', 'timestamp')
    list_filter     = ('event_type',)
    search_fields   = ('url', 'event_type')
    ordering        = ('-timestamp',)
    readonly_fields = ('timestamp',)


@admin.register(TabState)
class TabStateAdmin(admin.ModelAdmin):
    list_display    = ('id', 'session', 'tab_id', 'url', 'entered_at', 'exited_at')
    list_filter     = ('session__status',)
    search_fields   = ('url', 'tab_id')
    ordering        = ('-entered_at',)
    readonly_fields = ('entered_at',)