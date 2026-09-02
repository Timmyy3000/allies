import logging
from datetime import datetime

import pytest
from auths.models import User
from django.contrib import admin
from django.contrib.admin.models import DELETION, LogEntry
from django.contrib.auth.models import Permission
from django.http import HttpResponse
from django.template import TemplateDoesNotExist
from django.template.response import TemplateResponse
from django.test import override_settings
from django.test.client import RequestFactory
from django.urls import reverse
from django.utils import timezone
from unfold.admin import ModelAdmin

from waitlist.models import WaitlistEntry

TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@pytest.fixture
def waitlist_entry(db):
    return WaitlistEntry.objects.create(
        attempt_id_digest="a" * 64,
        attempt_token_digest="b" * 64,
        completion_digest="c" * 64,
        name="Ari",
        appearance_catalog_version="v1",
        appearance_key="ghosty:fd304f",
        job="Planning",
        personality="Warm",
        greeting_text="Hello",
        greeting_policy_version="v1",
        greeting_generated_at=timezone.now(),
        reply_text="Help me plan this week.",
        reply_recorded_at=timezone.now(),
        email_normalized="person@example.com",
        consent_version="consent-v1",
        joined_at=timezone.now(),
        expires_at=timezone.now(),
    )


@pytest.fixture
def staff_user(db):
    user = User.objects.create_user()
    user.is_staff = True
    user.save(update_fields=("is_staff",))
    return user


def test_waitlist_admin_has_a_read_only_operator_surface():
    model_admin = admin.site.get_model_admin(WaitlistEntry)

    assert model_admin.list_display == (
        "id",
        "name",
        "email_normalized",
        "joined_at",
        "expires_at",
        "created_at",
    )
    assert model_admin.search_fields == ("id", "name", "email_normalized")
    assert model_admin.list_filter == ("created_at", "joined_at", "consent_version")
    assert model_admin.ordering == ("-created_at",)
    assert model_admin.fields == (
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
    assert model_admin.readonly_fields == model_admin.fields
    assert {
        "attempt_id_digest",
        "attempt_token_digest",
        "completion_digest",
    }.isdisjoint(model_admin.fields)


@pytest.mark.django_db
@override_settings(STORAGES=TEST_STORAGES)
def test_waitlist_admin_uses_normal_permissions_and_disables_add(
    client, staff_user, waitlist_entry
):
    client.force_login(staff_user)
    changelist_url = reverse("admin:waitlist_waitlistentry_changelist")
    change_url = reverse(
        "admin:waitlist_waitlistentry_change", args=(waitlist_entry.pk,)
    )
    add_url = reverse("admin:waitlist_waitlistentry_add")
    delete_url = reverse(
        "admin:waitlist_waitlistentry_delete", args=(waitlist_entry.pk,)
    )

    assert client.get(changelist_url).status_code == 403

    staff_user.user_permissions.add(
        Permission.objects.get(codename="view_waitlistentry")
    )
    assert client.get(changelist_url).status_code == 200
    change_response = client.get(change_url)
    assert change_response.status_code == 200
    assert b'name="_save"' not in change_response.content
    assert b"attempt_id_digest" not in change_response.content
    assert b"attempt_token_digest" not in change_response.content
    assert b"completion_digest" not in change_response.content
    assert client.get(add_url).status_code == 403
    assert client.get(delete_url).status_code == 403

    staff_user.user_permissions.add(
        Permission.objects.get(codename="delete_waitlistentry")
    )
    assert client.get(delete_url).status_code == 200


@pytest.mark.django_db
@override_settings(STORAGES=TEST_STORAGES)
def test_waitlist_change_permission_does_not_grant_read_or_write_access(
    client, staff_user, waitlist_entry
):
    staff_user.user_permissions.add(
        Permission.objects.get(codename="change_waitlistentry")
    )
    client.force_login(staff_user)
    change_url = reverse(
        "admin:waitlist_waitlistentry_change", args=(waitlist_entry.pk,)
    )
    updated_at = waitlist_entry.updated_at

    assert client.get(change_url).status_code == 403
    assert client.post(change_url, data={}).status_code == 403
    waitlist_entry.refresh_from_db()
    assert waitlist_entry.updated_at == updated_at


@pytest.mark.django_db
@override_settings(STORAGES=TEST_STORAGES)
def test_waitlist_admin_audits_pii_reads_without_logging_pii(
    client, staff_user, waitlist_entry, caplog
):
    staff_user.user_permissions.add(
        Permission.objects.get(codename="view_waitlistentry")
    )
    client.force_login(staff_user)
    changelist_url = reverse("admin:waitlist_waitlistentry_changelist")
    change_url = reverse(
        "admin:waitlist_waitlistentry_change", args=(waitlist_entry.pk,)
    )

    logger = logging.getLogger("allies.waitlist")
    logger.addHandler(caplog.handler)
    try:
        assert (
            client.get(changelist_url, {"q": "person@example.com"}).status_code == 200
        )
        assert client.get(change_url).status_code == 200
    finally:
        logger.removeHandler(caplog.handler)

    events = [record.waitlist_admin_access for record in caplog.records]
    timestamps = [event.pop("timestamp") for event in events]
    assert all(datetime.fromisoformat(timestamp).tzinfo for timestamp in timestamps)
    assert events == [
        {
            "event_name": "waitlist_admin_list_viewed",
            "actor_ref": str(staff_user.id),
            "entry_ref": "",
            "search_used": True,
        },
        {
            "event_name": "waitlist_admin_entry_viewed",
            "actor_ref": str(staff_user.id),
            "entry_ref": str(waitlist_entry.id),
            "search_used": False,
        },
    ]
    assert '"event_name":"waitlist_admin_list_viewed"' in caplog.records[0].getMessage()
    assert "person@example.com" not in caplog.text
    assert "Help me plan this week." not in caplog.text


@pytest.mark.django_db
@override_settings(STORAGES=TEST_STORAGES)
def test_waitlist_admin_audits_single_and_bulk_deletions_without_logging_pii(
    client, staff_user, waitlist_entry, caplog
):
    second_entry = WaitlistEntry.objects.create(
        attempt_id_digest="d" * 64,
        attempt_token_digest="e" * 64,
        completion_digest="f" * 64,
        name="Bea",
        email_normalized="bea@example.com",
        consent_version="consent-v1",
        joined_at=timezone.now(),
        expires_at=timezone.now(),
    )
    staff_user.user_permissions.add(
        Permission.objects.get(codename="view_waitlistentry"),
        Permission.objects.get(codename="delete_waitlistentry"),
    )
    client.force_login(staff_user)
    logger = logging.getLogger("allies.waitlist")
    logger.addHandler(caplog.handler)
    try:
        delete_url = reverse(
            "admin:waitlist_waitlistentry_delete", args=(waitlist_entry.pk,)
        )
        assert client.post(delete_url, {"post": "yes"}).status_code == 302
        changelist_url = reverse("admin:waitlist_waitlistentry_changelist")
        assert (
            client.post(
                changelist_url,
                {
                    "action": "delete_selected",
                    "_selected_action": [second_entry.pk],
                    "post": "yes",
                },
            ).status_code
            == 302
        )
    finally:
        logger.removeHandler(caplog.handler)

    deletion_events = [
        record.waitlist_admin_access
        for record in caplog.records
        if record.waitlist_admin_access["event_name"] == "waitlist_admin_entry_deleted"
    ]
    timestamps = [event.pop("timestamp") for event in deletion_events]
    assert all(datetime.fromisoformat(timestamp).tzinfo for timestamp in timestamps)
    assert deletion_events == [
        {
            "event_name": "waitlist_admin_entry_deleted",
            "actor_ref": str(staff_user.id),
            "entry_ref": str(waitlist_entry.id),
            "search_used": False,
        },
        {
            "event_name": "waitlist_admin_entry_deleted",
            "actor_ref": str(staff_user.id),
            "entry_ref": str(second_entry.id),
            "search_used": False,
        },
    ]
    assert "person@example.com" not in caplog.text
    assert "bea@example.com" not in caplog.text
    assert (
        LogEntry.objects.filter(
            action_flag=DELETION,
            object_id__in=(str(waitlist_entry.pk), str(second_entry.pk)),
        ).count()
        == 2
    )


@pytest.mark.django_db
def test_waitlist_admin_does_not_audit_failed_render(staff_user, monkeypatch, caplog):
    request = RequestFactory().get("/admin/waitlist/waitlistentry/")
    request.user = staff_user
    model_admin = admin.site.get_model_admin(WaitlistEntry)

    def failed_changelist_view(model_admin, request, extra_context=None):
        return TemplateResponse(request, "missing-waitlist-admin-template.html", {})

    monkeypatch.setattr(ModelAdmin, "changelist_view", failed_changelist_view)
    logger = logging.getLogger("allies.waitlist")
    logger.addHandler(caplog.handler)
    try:
        response = model_admin.changelist_view(request)
        assert not caplog.records
        with pytest.raises(TemplateDoesNotExist):
            response.render()
    finally:
        logger.removeHandler(caplog.handler)

    assert not caplog.records


@pytest.mark.django_db
def test_waitlist_admin_tolerates_non_template_responses(
    staff_user, monkeypatch, caplog
):
    request = RequestFactory().get("/admin/waitlist/waitlistentry/")
    request.user = staff_user
    model_admin = admin.site.get_model_admin(WaitlistEntry)

    monkeypatch.setattr(
        ModelAdmin,
        "changelist_view",
        lambda model_admin, request, extra_context=None: HttpResponse("list"),
    )
    monkeypatch.setattr(
        ModelAdmin,
        "change_view",
        lambda model_admin, request, object_id, form_url="", extra_context=None: (
            HttpResponse("detail")
        ),
    )
    logger = logging.getLogger("allies.waitlist")
    logger.addHandler(caplog.handler)
    try:
        assert model_admin.changelist_view(request).content == b"list"
        assert model_admin.change_view(request, "1").content == b"detail"
    finally:
        logger.removeHandler(caplog.handler)

    assert not caplog.records
