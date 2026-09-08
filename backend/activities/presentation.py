"""Cloud-owned, content-free activity copy and public correlation."""

import hashlib

from django.core.exceptions import ObjectDoesNotExist


def approval_summary(approval) -> dict:
    """Return the content-free approval projection used by activity/list APIs."""

    return {
        "id": approval.id,
        "message_id": approval.message_id,
        "status": approval.status,
        "expires_at": approval.expires_at,
        "decided_at": approval.decided_at,
        "acknowledgement_deadline_at": approval.acknowledgement_deadline_at,
    }


def approval_activity_summary(approval) -> dict:
    """Return the smaller approval projection safe for generic activities."""

    return {
        "id": approval.id,
        "status": approval.status,
        "expires_at": approval.expires_at,
        "decided_at": approval.decided_at,
    }


def approval_detail(approval) -> dict:
    result = approval_summary(approval)
    result.update(
        {
            "action_label": approval.action_label,
            "action_preview": approval.action_preview,
        }
    )
    return result


ACTIVITY_LABELS = {
    "web_search": ("Searching the web", "Searched the web"),
    "web_extract": ("Reading a webpage", "Read a webpage"),
    "browser_navigate": ("Visiting a webpage", "Visited a webpage"),
    "browser_interact": ("Interacting with a webpage", "Interacted with a webpage"),
    "search_files": ("Searching files", "Searched files"),
    "read_file": ("Reading a file", "Read a file"),
    "write_file": ("Writing a file", "Wrote a file"),
    "patch": ("Editing a file", "Edited a file"),
    "terminal": ("Working", "Finished an activity"),
    "execute_code": ("Working", "Finished an activity"),
    "image_generate": ("Creating an image", "Created an image"),
    "video_generate": ("Creating a video", "Created a video"),
    "text_to_speech": ("Creating audio", "Created audio"),
    "vision_analyze": ("Reviewing an image", "Reviewed an image"),
    "session_search": (
        "Searching conversation history",
        "Searched conversation history",
    ),
    "memory_remember": ("Remembering", "Remembered"),
    "memory_recall": ("Recalling", "Recalled"),
    "memory": ("Working with memory", "Finished working with memory"),
    "skills_list": ("Checking skills", "Checked skills"),
    "skill_view": ("Checking skills", "Checked skills"),
    "skill_manage": ("Updating skills", "Updated skills"),
    "todo": ("Updating the work plan", "Updated the work plan"),
    "cronjob": ("Working with routines", "Finished working with routines"),
    "delegate_task": ("Coordinating delegated work", "Finished delegated work"),
    "unknown": ("Working", "Finished an activity"),
}


def activity_text(kind: str, outcome: str | None) -> str:
    active, completed = ACTIVITY_LABELS.get(kind, ACTIVITY_LABELS["unknown"])
    if outcome == "completed":
        return completed
    if outcome == "failed":
        return f"Could not finish {active.lower()}"
    if outcome == "stopped":
        return f"Stopped while {active.lower()}"
    return active


def activity_metadata(activity) -> dict:
    digest = hashlib.sha256(
        f"allies:activity-attempt:v1:{activity.attempt_id}".encode()
    ).hexdigest()[:32]
    try:
        approval = activity.approval
    except ObjectDoesNotExist:
        approval = None
    return {
        "activity_attempt_id": f"attempt-{digest}",
        "activity_id": activity.activity_id,
        "activity_kind": activity.activity_kind,
        "outcome": activity.outcome,
        "duration_ms": activity.duration_ms,
        "approval": (
            approval_activity_summary(approval) if approval is not None else None
        ),
    }


__all__ = [
    "ACTIVITY_LABELS",
    "activity_metadata",
    "activity_text",
    "approval_activity_summary",
    "approval_detail",
    "approval_summary",
]
