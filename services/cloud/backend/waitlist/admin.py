import json
import logging
from datetime import UTC, datetime

from django.contrib import admin
from django.template.response import TemplateResponse
from unfold.admin import ModelAdmin

from .models import WaitlistEntry

logger = logging.getLogger("allies.waitlist")


def _emit_admin_access(
    event_name: str,
    *,
    actor_ref: str,
    entry_ref: str = "",
    search_used: bool = False,
) -> None:
    envelope = {
        "event_name": event_name,
        "actor_ref": actor_ref,
        "entry_ref": entry_ref,
        "search_used": search_used,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    logger.info(
        "waitlist admin access %s",
        json.dumps(envelope, separators=(",", ":"), sort_keys=True),
        extra={"waitlist_admin_access": envelope},
    )


@admin.register(WaitlistEntry)
class WaitlistEntryAdmin(ModelAdmin):
    list_display = (
        "id",
        "name",
        "email_normalized",
        "joined_at",
        "expires_at",
        "created_at",
    )
    search_fields = ("id", "name", "email_normalized")
    list_filter = ("created_at", "joined_at", "consent_version")
    ordering = ("-created_at",)
    fields = (
        "id",
        "generation_claimed_at",
        "name",
        "appearance_catalog_version",
        "appearance_key",
        "job",
        "personality",
        "greeting_text",
        "greeting_policy_version",
        "greeting_generated_at",
        "reply_text",
        "reply_recorded_at",
        "email_normalized",
        "consent_version",
        "joined_at",
        "expires_at",
        "created_at",
        "updated_at",
    )
    readonly_fields = fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        opts = self.opts
        return request.user.has_perm(f"{opts.app_label}.view_{opts.model_name}")

    def delete_model(self, request, obj):
        actor_ref = str(request.user.id)
        entry_ref = str(obj.id)
        super().delete_model(request, obj)
        _emit_admin_access(
            "waitlist_admin_entry_deleted",
            actor_ref=actor_ref,
            entry_ref=entry_ref,
        )

    def delete_queryset(self, request, queryset):
        actor_ref = str(request.user.id)
        entry_refs = [
            str(entry_id) for entry_id in queryset.values_list("id", flat=True)
        ]
        super().delete_queryset(request, queryset)
        for entry_ref in entry_refs:
            _emit_admin_access(
                "waitlist_admin_entry_deleted",
                actor_ref=actor_ref,
                entry_ref=entry_ref,
            )

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context)
        if (
            request.method == "GET"
            and response.status_code == 200
            and isinstance(response, TemplateResponse)
        ):
            actor_ref = str(request.user.id)
            search_used = bool(request.GET.get("q"))
            response.add_post_render_callback(
                lambda rendered_response: _emit_admin_access(
                    "waitlist_admin_list_viewed",
                    actor_ref=actor_ref,
                    search_used=search_used,
                )
            )
        return response

    def change_view(self, request, object_id, form_url="", extra_context=None):
        response = super().change_view(request, object_id, form_url, extra_context)
        if (
            request.method == "GET"
            and response.status_code == 200
            and isinstance(response, TemplateResponse)
            and (entry := response.context_data.get("original")) is not None
        ):
            actor_ref = str(request.user.id)
            entry_ref = str(entry.id)
            response.add_post_render_callback(
                lambda rendered_response: _emit_admin_access(
                    "waitlist_admin_entry_viewed",
                    actor_ref=actor_ref,
                    entry_ref=entry_ref,
                )
            )
        return response
