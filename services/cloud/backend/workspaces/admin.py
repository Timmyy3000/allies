from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Membership, Workspace


@admin.register(Workspace)
class WorkspaceAdmin(ModelAdmin):
    list_display = ("id", "name", "kind", "owner", "is_active", "runtime_intent_mode")
    search_fields = ("id", "name", "owner__id")
    readonly_fields = ("id",)


@admin.register(Membership)
class MembershipAdmin(ModelAdmin):
    list_display = ("workspace", "user", "role", "status", "created_at")
    search_fields = ("workspace__id", "user__id")
