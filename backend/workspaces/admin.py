from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Membership, Workspace


@admin.register(Workspace)
class WorkspaceAdmin(ModelAdmin):
    list_display = ("public_id", "name", "kind", "owner", "is_active")
    search_fields = ("public_id", "name", "owner__public_id")
    readonly_fields = ("public_id",)


@admin.register(Membership)
class MembershipAdmin(ModelAdmin):
    list_display = ("workspace", "user", "role", "status", "created_at")
    search_fields = ("workspace__public_id", "user__public_id")
