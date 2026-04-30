from rest_framework import serializers
from .models import ActivitySession, ActivityLog


class ActivitySessionSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ActivitySession
        fields = '__all__'


# FIX: ActivityLog serializer was missing entirely
class ActivityLogSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ActivityLog
        fields = '__all__'