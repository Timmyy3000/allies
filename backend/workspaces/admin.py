from django.contrib import admin

from .models import Membership, Workspace


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ("public_id", "name", "kind", "owner", "is_active")
    search_fields = ("public_id", "name", "owner__public_id")
    readonly_fields = ("public_id",)


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("workspace", "actor", "role", "status", "created_at")
    search_fields = ("workspace__public_id", "actor__public_id")
