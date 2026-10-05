from django import forms
from django.contrib import admin
from django.contrib.admin.models import ADDITION, CHANGE, LogEntry
from django.db import transaction
from django.http import HttpResponse
from django.utils.html import escape
from unfold.admin import ModelAdmin

from .exceptions import InviteConsumed
from .models import AvatarAsset, BetaInvite, ExternalIdentity, User, UserProfile
from .services.invites import issue_invite, reset_invite, revoke_invite


@admin.register(User)
class UserAdmin(ModelAdmin):
    list_display = ("id", "is_active", "is_staff", "date_joined")
    search_fields = ("id",)
    readonly_fields = ("id", "date_joined")


@admin.register(ExternalIdentity)
class ExternalIdentityAdmin(ModelAdmin):
    list_display = ("provider", "subject", "user", "created_at")
    search_fields = ("provider", "subject", "user__id")
    readonly_fields = ("provider", "subject", "user", "created_at")


@admin.register(UserProfile)
class UserProfileAdmin(ModelAdmin):
    list_display = ("user", "display_name", "updated_at")
    search_fields = ("user__id", "display_name")
    readonly_fields = ("user", "current_avatar", "updated_at")

    def has_add_permission(self, request):
        return False


@admin.register(AvatarAsset)
class AvatarAssetAdmin(ModelAdmin):
    list_display = ("id", "user", "status", "created_at")
    search_fields = ("id", "user__id")
    readonly_fields = ("id", "object_key", "created_at")


class BetaInviteIssueForm(forms.ModelForm):
    class Meta:
        model = BetaInvite
        fields = ()


def _one_time_code_response(title: str, entries: list[tuple[str, str]]) -> HttpResponse:
    rendered = "".join(
        f"<li><code>{escape(invite_id)}</code>: <code>{escape(code)}</code></li>"
        for invite_id, code in entries
    )
    response = HttpResponse(
        "<!doctype html><html><head><meta charset='utf-8'><title>"
        f"{escape(title)}</title></head><body><h1>{escape(title)}</h1>"
        "<p>Copy these codes now. They are not stored or shown again.</p>"
        f"<ul>{rendered}</ul><p>Return to the admin invite list when done.</p>"
        "</body></html>",
        content_type="text/html; charset=utf-8",
    )
    response["Cache-Control"] = "no-store"
    response["Pragma"] = "no-cache"
    response["Referrer-Policy"] = "no-referrer"
    return response


@admin.action(description="Revoke selected beta invites", permissions=["change"])
def revoke_selected_invites(modeladmin, request, queryset):
    invites = list(queryset)
    for invite in invites:
        revoke_invite(invite.id)
    if invites:
        LogEntry.objects.log_actions(request.user.pk, invites, CHANGE, "revoke invite")
    modeladmin.message_user(request, f"revoked={len(invites)}")


@admin.action(description="Reset selected beta invites", permissions=["change"])
def reset_selected_invites(modeladmin, request, queryset):
    codes = []
    skipped = 0
    reset_rows = []
    with transaction.atomic():
        for invite in queryset.order_by("id"):
            try:
                codes.append((str(invite.id), reset_invite(invite.id)))
                reset_rows.append(invite)
            except InviteConsumed:
                skipped += 1
        if reset_rows:
            LogEntry.objects.log_actions(
                request.user.pk, reset_rows, CHANGE, "reset invite"
            )
        if codes:
            return _one_time_code_response("Beta invite codes", codes)
    modeladmin.message_user(request, f"reset=0 consumed={skipped}")


@admin.register(BetaInvite)
class BetaInviteAdmin(ModelAdmin):
    list_display = (
        "id",
        "claimed_email",
        "claimed_at",
        "revoked_at",
        "consumed_at",
        "created_at",
    )
    search_fields = ("id", "claimed_email")
    list_filter = ("claimed_at", "revoked_at", "consumed_at", "created_at")
    ordering = ("-created_at",)
    fields = (
        "id",
        "code_digest",
        "claimed_email",
        "claimed_at",
        "revoked_at",
        "consumed_at",
        "created_at",
        "updated_at",
    )
    actions = (revoke_selected_invites, reset_selected_invites)

    def get_fields(self, request, obj=None):
        return () if obj is None else self.fields

    def get_readonly_fields(self, request, obj=None):
        return () if obj is None else self.fields

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            return BetaInviteIssueForm
        return super().get_form(request, obj, **kwargs)

    def add_view(self, request, form_url="", extra_context=None):
        if request.method == "POST" and self.has_add_permission(request):
            form = BetaInviteIssueForm(request.POST)
            if form.is_valid():
                invite, raw_code = issue_invite()
                LogEntry.objects.log_actions(
                    request.user.pk,
                    [invite],
                    ADDITION,
                    "issue invite",
                    single_object=True,
                )
                return _one_time_code_response(
                    "Beta invite issued", [(str(invite.id), raw_code)]
                )
        return super().add_view(request, form_url, extra_context)

    def has_delete_permission(self, request, obj=None):
        return False
