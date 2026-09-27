"""Cloud-owned, content-free activity copy and public correlation."""

import hashlib

from django.core.exceptions import ObjectDoesNotExist

from .services.approval_explanations import (
    APPROVAL_CONTRACT_VERSION,
    public_explanation,
    technical_details,
)


def _decision_state(approval) -> tuple[str | None, bool]:
    decision = approval.decision if approval.decision in {"approve", "reject"} else None
    return decision, bool(decision and approval.decided_at is not None)


def approval_summary(approval) -> dict:
    """Return the content-free approval projection used by activity/list APIs."""

    decision, decision_recorded = _decision_state(approval)

    return {
        "contract_version": APPROVAL_CONTRACT_VERSION,
        "id": approval.id,
        "message_id": approval.message_id,
        "conversation_turn_ordinal": approval.message.sequence,
        "status": approval.status,
        "decision": decision,
        "decision_recorded": decision_recorded,
        "expires_at": approval.expires_at,
        "decided_at": approval.decided_at,
        "acknowledgement_deadline_at": approval.acknowledgement_deadline_at,
    }


def approval_activity_summary(approval) -> dict:
    """Return the smaller approval projection safe for generic activities."""

    decision, decision_recorded = _decision_state(approval)

    return {
        "contract_version": APPROVAL_CONTRACT_VERSION,
        "id": approval.id,
        "status": approval.status,
        "decision": decision,
        "decision_recorded": decision_recorded,
        "expires_at": approval.expires_at,
        "decided_at": approval.decided_at,
    }


def approval_detail(approval) -> dict:
    result = approval_summary(approval)
    explanation = public_explanation(approval)
    details = technical_details(approval)
    result.update(
        {
            "action_label": approval.action_label,
            "action_preview": details["action_preview"],
            "approval_request_id": approval.approval_request_id,
            "preview_digest": explanation["preview_digest"],
            "explanation": explanation,
            "technical_details": details,
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
    "publish_files": ("Publishing file", "Published file"),
    "patch": ("Editing a file", "Edited a file"),
    "terminal": ("Running a command", "Ran a command"),
    "execute_code": ("Running code", "Ran code"),
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
    "routine_create": ("Creating a routine", "Created a routine"),
    "routine_list": ("Checking routines", "Checked routines"),
    "routine_inspect": ("Checking a routine", "Checked a routine"),
    "routine_update": ("Updating a routine", "Updated a routine"),
    "routine_pause": ("Pausing a routine", "Paused a routine"),
    "routine_resume": ("Resuming a routine", "Resumed a routine"),
    "routine_request_delete": (
        "Preparing to delete a routine",
        "Prepared to delete a routine",
    ),
    "routine_delete": ("Deleting a routine", "Deleted a routine"),
    "routine_result": ("Checking a routine result", "Checked a routine result"),
    "delegate_task": ("Coordinating delegated work", "Finished delegated work"),
    "browser_view": ("Looking at a webpage", "Looked at a webpage"),
    "process": ("Checking a running task", "Checked a running task"),
    "smart_home": ("Working with your smart home", "Worked with your smart home"),
    "tool_lookup": ("Finding the right tool", "Found the right tool"),
    "gmail_read": ("Reading your email", "Read your email"),
    "gmail_send": ("Sending an email", "Sent an email"),
    "gmail_organise": ("Organising your email", "Organised your email"),
    "safe_input_check": ("Checking your Safe inputs", "Checked your Safe inputs"),
    "safe_input_request": ("Asking for a login", "Asked for a login"),
    "safe_input_fill": (
        "Signing in with your Safe input",
        "Signed in with your Safe input",
    ),
    "approval_request": ("Asking for your approval", "Asked for your approval"),
    "unknown": ("Working", "Finished an activity"),
}


# Labels that name what the activity was about; "{}" is the Foundry-bounded subject.
SUBJECT_LABELS = {
    "web_search": ("Searching the web for “{}”", "Searched the web for “{}”"),
    "web_extract": ("Reading {}", "Read {}"),
    "browser_navigate": ("Visiting {}", "Visited {}"),
    "browser_interact": ("Using {}", "Used {}"),
    "browser_view": ("Looking at {}", "Looked at {}"),
    "search_files": ("Searching files for “{}”", "Searched files for “{}”"),
    "read_file": ("Reading {}", "Read {}"),
    "write_file": ("Writing {}", "Wrote {}"),
    "patch": ("Editing {}", "Edited {}"),
    "skill_view": ("Checking the {} skill", "Checked the {} skill"),
    "safe_input_request": ("Asking for your {} login", "Asked for your {} login"),
    "safe_input_check": ("Checking your {} login", "Checked your {} login"),
}


def activity_text(kind: str, outcome: str | None, subject: str | None = None) -> str:
    active, completed = ACTIVITY_LABELS.get(kind, ACTIVITY_LABELS["unknown"])
    if subject and kind in SUBJECT_LABELS:
        active, completed = (
            template.format(subject) for template in SUBJECT_LABELS[kind]
        )
    if outcome == "completed":
        return completed
    if outcome == "failed":
        if kind == "publish_files":
            return "Couldn't publish file"
        return f"Could not finish {active[0].lower()}{active[1:]}"
    if outcome == "stopped":
        return f"Stopped while {active[0].lower()}{active[1:]}"
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
