from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, models, transaction
from django.db.utils import IntegrityError

from allies.models import Ally, AllyBinding
from allies.services.onboarding import digest_value
from auths.exceptions import WorkspaceAccessDenied
from auths.models import User
from chat.models import Conversation
from routines.models import (
    ROUTINE_PROMPT_MAX_BYTES,
    ROUTINE_TITLE_MAX_LENGTH,
    Routine,
    RoutineDeletionConfirmation,
    RoutineDeletionConfirmationState,
    RoutineManagementReceipt,
    RoutineState,
)
from routines.services.management import (
    CONFIRMATION_REPLAYED,
    CONFIRMATION_REQUIRED,
    CONFIRMATION_STALE,
    CONFIRMATION_WRONG_ALLY,
    CONFIRMATION_WRONG_BINDING,
    CONFIRMATION_WRONG_CONVERSATION,
    CONFIRMATION_WRONG_OWNER,
    CONFIRMATION_WRONG_ROUTINE,
    CONFIRMATION_WRONG_WORKSPACE,
    RoutineConfirmationError,
    RoutineRevisionConflict,
    RoutineStateError,
    create_routine_intent,
    delete_routine_intent,
    issue_deletion_confirmation,
    owner_routine,
    owner_routines,
    update_routine_intent,
)
from workspaces.models import Membership, Workspace


@pytest.fixture
def account(db):
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="Routine workspace")
    Membership.objects.create(
        workspace=workspace,
        user=user,
        role="owner",
        status="active",
    )
    ally = Ally.objects.create(
        workspace=workspace,
        name="Mira",
        job="Study partner",
        personality="Calm and specific.",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )
    binding = AllyBinding.objects.create(ally=ally)
    Conversation.objects.create(ally=ally)
    return user, workspace, ally, binding


def daily_schedule(local_time="09:00:00"):
    return {
        "kind": "recurring",
        "frequency": "daily",
        "local_time": local_time,
        "timezone": "Europe/Berlin",
    }


def create_intent(account, *, title="Check the inbox", prompt="Review new mail"):
    user, workspace, ally, _ = account
    conversation = Conversation.objects.get_or_create(ally=ally)[0]
    return create_routine_intent(
        user=user,
        workspace_id=workspace.id,
        ally_id=ally.id,
        main_conversation_id=conversation.id,
        title=title,
        execution_prompt=prompt,
        schedule=daily_schedule(),
        now=datetime(2026, 9, 10, 6, tzinfo=UTC),
    )


@pytest.mark.django_db
def test_fresh_migration_creates_routine_table_with_uuid_ancestry_columns():
    assert Routine._meta.db_table in connection.introspection.table_names()
    assert isinstance(Routine._meta.get_field("id"), models.UUIDField)
    for name in ("workspace", "owner", "ally", "binding"):
        assert isinstance(Routine._meta.get_field(name).target_field, models.UUIDField)


@pytest.mark.django_db
def test_create_and_discovery_are_owner_scoped_and_preserve_ancestry(account):
    routine = create_intent(account)
    user, workspace, ally, binding = account

    assert routine.owner_id == user.id
    assert routine.workspace_id == workspace.id
    assert routine.ally_id == ally.id
    assert routine.binding_id == binding.id
    assert routine.revision == 1
    assert routine.schedule_generation == 1
    assert routine.state == RoutineState.ACTIVE
    assert routine.next_run_at == datetime(2026, 9, 10, 7, tzinfo=UTC)
    create_receipt = RoutineManagementReceipt.objects.get(operation="create")
    assert create_receipt.revision == 1
    assert create_receipt.schedule_generation == 1
    assert create_receipt.schedule_state == RoutineState.ACTIVE
    assert create_receipt.next_run_at == routine.next_run_at
    assert create_receipt.command_id != create_receipt.idempotency_key

    other = User.objects.create_user()
    Membership.objects.create(
        workspace=workspace,
        user=other,
        role="owner",
        status="active",
    )
    assert list(owner_routines(user=other, workspace_id=workspace.id)) == []
    with pytest.raises(Routine.DoesNotExist):
        owner_routine(
            user=other,
            workspace_id=workspace.id,
            routine_id=routine.id,
        )

    outsider = User.objects.create_user()
    with pytest.raises(WorkspaceAccessDenied):
        list(owner_routines(user=outsider, workspace_id=workspace.id))


@pytest.mark.django_db
def test_prompt_and_title_bounds_are_enforced_before_persistence(account):
    user, workspace, ally, binding = account
    routine = Routine(
        workspace=workspace,
        owner=user,
        ally=ally,
        binding=binding,
        main_conversation_id=uuid4(),
        title="t" * (ROUTINE_TITLE_MAX_LENGTH + 1),
        execution_prompt="prompt",
        schedule=daily_schedule(),
    )
    with pytest.raises(ValidationError, match="title"):
        routine.full_clean()

    routine.title = "Valid title"
    routine.execution_prompt = "💡" * (ROUTINE_PROMPT_MAX_BYTES // 4 + 1)
    with pytest.raises(ValidationError, match="byte limit"):
        routine.full_clean()


@pytest.mark.django_db
def test_schedule_generation_matches_revision9_management_sequence(account):
    routine = create_intent(account)
    user, workspace, _, _ = account

    updated = update_routine_intent(
        user=user,
        workspace_id=workspace.id,
        routine_id=routine.id,
        expected_revision=1,
        schedule=daily_schedule("10:00:00"),
    )
    assert updated.revision == 2
    assert updated.schedule_generation == 2

    paused = update_routine_intent(
        user=user,
        workspace_id=workspace.id,
        routine_id=routine.id,
        expected_revision=2,
        state=RoutineState.PAUSED,
    )
    assert paused.revision == 3
    assert paused.schedule_generation == 3

    resumed = update_routine_intent(
        user=user,
        workspace_id=workspace.id,
        routine_id=routine.id,
        expected_revision=3,
        state=RoutineState.ACTIVE,
        now=datetime(2026, 9, 10, 7, 1, tzinfo=UTC),
    )
    assert resumed.revision == 4
    assert resumed.schedule_generation == 4
    assert list(
        RoutineManagementReceipt.objects.order_by("created_at").values_list(
            "operation", "schedule_generation"
        )
    ) == [("create", 1), ("update", 2), ("pause", 3), ("resume", 4)]


@pytest.mark.django_db
def test_owner_ancestry_is_checked_and_immutable(account):
    routine = create_intent(account)
    _, workspace, _, _ = account
    other_workspace = Workspace.objects.create(
        owner=User.objects.create_user(),
        name="Other",
    )
    other_ally = Ally.objects.create(
        workspace=other_workspace,
        name="Other",
        job="Other",
        personality="Other",
        appearance_catalog_version="v1",
        appearance_key="other",
    )
    other_binding = AllyBinding.objects.create(ally=other_ally)

    routine.ally = other_ally
    routine.binding = other_binding
    with pytest.raises(ValidationError, match="owner ancestry"):
        routine.save(update_fields=("ally", "binding"))

    invalid = Routine(
        workspace=workspace,
        owner=routine.owner,
        ally=other_ally,
        binding=other_binding,
        main_conversation_id=uuid4(),
        title="Invalid ancestry",
        execution_prompt="Prompt",
        schedule=daily_schedule(),
    )
    with pytest.raises(ValidationError, match="workspace"):
        invalid.full_clean()


@pytest.mark.django_db
def test_create_rejects_a_conversation_outside_the_selected_ally(account):
    user, workspace, ally, _ = account
    other_ally = Ally.objects.create(
        workspace=workspace,
        name="Other ally",
        job="Other",
        personality="Other",
        appearance_catalog_version="v1",
        appearance_key="other",
    )
    AllyBinding.objects.create(ally=other_ally)
    other_conversation = Conversation.objects.create(ally=other_ally)

    with pytest.raises(ValidationError, match="main_conversation_id"):
        create_routine_intent(
            user=user,
            workspace_id=workspace.id,
            ally_id=ally.id,
            main_conversation_id=other_conversation.id,
            title="Wrong conversation",
            execution_prompt="Do not save this",
            schedule=daily_schedule(),
            now=datetime(2026, 9, 10, 6, tzinfo=UTC),
        )


@pytest.mark.django_db
def test_deleted_state_constraint_is_bidirectional(account):
    routine = create_intent(account)

    with pytest.raises(IntegrityError), transaction.atomic():
        Routine.objects.filter(pk=routine.pk).update(
            deleted_at=datetime(2026, 9, 10, 8, tzinfo=UTC)
        )

    with pytest.raises(IntegrityError), transaction.atomic():
        Routine.objects.filter(pk=routine.pk).update(
            state=RoutineState.DELETED,
            deleted_at=None,
        )


@pytest.mark.django_db
def test_revision_cas_and_schedule_generation_are_separate(account):
    routine = create_intent(account)
    user, workspace, _, _ = account

    updated = update_routine_intent(
        user=user,
        workspace_id=workspace.id,
        routine_id=routine.id,
        expected_revision=1,
        title="Updated title",
    )
    assert updated.revision == 2
    assert updated.schedule_generation == 1

    updated = update_routine_intent(
        user=user,
        workspace_id=workspace.id,
        routine_id=routine.id,
        expected_revision=2,
        schedule=daily_schedule("10:00:00"),
        now=datetime(2026, 9, 10, 6, tzinfo=UTC),
    )
    assert updated.revision == 3
    assert updated.schedule_generation == 2
    assert updated.next_run_at == datetime(2026, 9, 10, 8, tzinfo=UTC)

    with pytest.raises(RoutineRevisionConflict):
        update_routine_intent(
            user=user,
            workspace_id=workspace.id,
            routine_id=routine.id,
            expected_revision=2,
            title="Stale title",
        )
    routine.refresh_from_db()
    assert routine.title == "Updated title"
    assert routine.revision == 3


@pytest.mark.django_db
def test_pause_resume_and_delete_keep_history_and_increment_generation(account):
    routine = create_intent(account)
    user, workspace, ally, _ = account
    paused = update_routine_intent(
        user=user,
        workspace_id=workspace.id,
        routine_id=routine.id,
        expected_revision=1,
        state=RoutineState.PAUSED,
    )
    assert paused.state == RoutineState.PAUSED
    assert paused.revision == 2
    assert paused.schedule_generation == 2
    assert paused.next_run_at is None

    resumed = update_routine_intent(
        user=user,
        workspace_id=workspace.id,
        routine_id=routine.id,
        expected_revision=2,
        state=RoutineState.ACTIVE,
        now=datetime(2026, 9, 10, 7, 1, tzinfo=UTC),
    )
    assert resumed.revision == 3
    assert resumed.schedule_generation == 3
    assert resumed.resume_boundary == datetime(2026, 9, 10, 7, 1, tzinfo=UTC)
    assert resumed.next_run_at == datetime(2026, 9, 11, 7, tzinfo=UTC)
    assert (
        RoutineManagementReceipt.objects.get(operation="pause").schedule_generation == 2
    )
    resume_receipt = RoutineManagementReceipt.objects.get(operation="resume")
    assert resume_receipt.schedule_generation == 3
    assert resume_receipt.resume_effective_at == resumed.resume_boundary

    conversation = Conversation.objects.get(ally=ally)
    with pytest.raises(RoutineConfirmationError) as missing:
        update_routine_intent(
            user=user,
            workspace_id=workspace.id,
            routine_id=routine.id,
            expected_revision=3,
            state=RoutineState.DELETED,
        )
    assert missing.value.result_code == CONFIRMATION_REQUIRED

    challenge = issue_deletion_confirmation(
        user=user,
        workspace_id=workspace.id,
        routine_id=routine.id,
        expected_revision=3,
        main_conversation_id=conversation.id,
        now=datetime(2026, 9, 10, 7, 59, tzinfo=UTC),
    )
    deleted = delete_routine_intent(
        user=user,
        workspace_id=workspace.id,
        routine_id=routine.id,
        expected_revision=3,
        main_conversation_id=conversation.id,
        confirmation_ref=challenge["confirmation_ref"],
        now=datetime(2026, 9, 10, 8, tzinfo=UTC),
    )
    assert deleted.deleted_at == datetime(2026, 9, 10, 8, tzinfo=UTC)
    assert deleted.schedule_generation == 3
    assert list(owner_routines(user=user, workspace_id=workspace.id)) == []
    history = list(
        owner_routines(user=user, workspace_id=workspace.id, include_history=True)
    )
    assert history == [deleted]
    assert history[0].execution_prompt == "Review new mail"
    confirmation = RoutineDeletionConfirmation.objects.get(
        reference_digest__isnull=False,
    )
    assert confirmation.state == RoutineDeletionConfirmationState.CONSUMED
    assert confirmation.consumed_at == datetime(2026, 9, 10, 8, tzinfo=UTC)
    receipt = RoutineManagementReceipt.objects.get(operation="delete")
    assert receipt.confirmation_id == confirmation.id
    assert receipt.result_code == "MANAGEMENT_SAVED"
    assert receipt.operation == "delete"
    assert receipt.revision == 4
    assert receipt.schedule_generation == 3
    assert receipt.schedule_state == RoutineState.DELETED


@pytest.mark.django_db
def test_deletion_confirmation_missing_and_stale_are_zero_mutation(account):
    routine = create_intent(account)
    user, workspace, ally, _ = account
    conversation = Conversation.objects.get(ally=ally)

    with pytest.raises(RoutineConfirmationError) as missing:
        delete_routine_intent(
            user=user,
            workspace_id=workspace.id,
            routine_id=routine.id,
            expected_revision=1,
            main_conversation_id=conversation.id,
            confirmation_ref=None,
        )
    assert missing.value.result_code == CONFIRMATION_REQUIRED
    routine.refresh_from_db()
    assert routine.state == RoutineState.ACTIVE
    assert routine.revision == 1
    assert not RoutineDeletionConfirmation.objects.exists()
    assert not RoutineManagementReceipt.objects.filter(operation="delete").exists()

    challenge = issue_deletion_confirmation(
        user=user,
        workspace_id=workspace.id,
        routine_id=routine.id,
        expected_revision=1,
        main_conversation_id=conversation.id,
    )
    update_routine_intent(
        user=user,
        workspace_id=workspace.id,
        routine_id=routine.id,
        expected_revision=1,
        title="Changed before delete",
    )
    with pytest.raises(RoutineConfirmationError) as stale:
        delete_routine_intent(
            user=user,
            workspace_id=workspace.id,
            routine_id=routine.id,
            expected_revision=1,
            main_conversation_id=conversation.id,
            confirmation_ref=challenge["confirmation_ref"],
        )
    assert stale.value.result_code == CONFIRMATION_STALE
    routine.refresh_from_db()
    assert routine.state == RoutineState.ACTIVE
    assert routine.revision == 2
    assert (
        RoutineDeletionConfirmation.objects.get().state
        == RoutineDeletionConfirmationState.UNCONSUMED
    )
    assert not RoutineManagementReceipt.objects.filter(operation="delete").exists()


@pytest.mark.django_db
def test_deletion_confirmation_replay_is_zero_mutation(account):
    routine = create_intent(account)
    user, workspace, ally, _ = account
    conversation = Conversation.objects.get(ally=ally)
    challenge = issue_deletion_confirmation(
        user=user,
        workspace_id=workspace.id,
        routine_id=routine.id,
        expected_revision=1,
        main_conversation_id=conversation.id,
    )
    delete_routine_intent(
        user=user,
        workspace_id=workspace.id,
        routine_id=routine.id,
        expected_revision=1,
        main_conversation_id=conversation.id,
        confirmation_ref=challenge["confirmation_ref"],
    )
    with pytest.raises(RoutineConfirmationError) as replayed:
        delete_routine_intent(
            user=user,
            workspace_id=workspace.id,
            routine_id=routine.id,
            expected_revision=1,
            main_conversation_id=conversation.id,
            confirmation_ref=challenge["confirmation_ref"],
        )
    assert replayed.value.result_code == CONFIRMATION_REPLAYED
    routine.refresh_from_db()
    assert routine.state == RoutineState.DELETED
    assert routine.revision == 2
    assert (
        RoutineDeletionConfirmation.objects.get().state
        == RoutineDeletionConfirmationState.CONSUMED
    )
    assert RoutineManagementReceipt.objects.filter(operation="delete").count() == 1


@pytest.mark.django_db
def test_deletion_confirmation_stores_only_a_keyed_digest(account):
    routine = create_intent(account)
    user, workspace, ally, _ = account
    conversation = Conversation.objects.get(ally=ally)
    challenge = issue_deletion_confirmation(
        user=user,
        workspace_id=workspace.id,
        routine_id=routine.id,
        expected_revision=1,
        main_conversation_id=conversation.id,
    )
    confirmation = RoutineDeletionConfirmation.objects.get()
    assert confirmation.reference_digest == digest_value(challenge["confirmation_ref"])
    assert challenge["confirmation_ref"] not in confirmation.reference_digest


@pytest.mark.django_db
def test_receipt_failure_rolls_back_delete_and_confirmation(account, monkeypatch):
    routine = create_intent(account)
    user, workspace, ally, _ = account
    conversation = Conversation.objects.get(ally=ally)
    challenge = issue_deletion_confirmation(
        user=user,
        workspace_id=workspace.id,
        routine_id=routine.id,
        expected_revision=1,
        main_conversation_id=conversation.id,
    )

    def fail_receipt_save(*args, **kwargs):
        raise RuntimeError("receipt persistence failed")

    monkeypatch.setattr(RoutineManagementReceipt, "save", fail_receipt_save)
    with pytest.raises(RuntimeError, match="receipt persistence"):
        delete_routine_intent(
            user=user,
            workspace_id=workspace.id,
            routine_id=routine.id,
            expected_revision=1,
            main_conversation_id=conversation.id,
            confirmation_ref=challenge["confirmation_ref"],
        )

    routine.refresh_from_db()
    confirmation = RoutineDeletionConfirmation.objects.get()
    assert routine.state == RoutineState.ACTIVE
    assert routine.revision == 1
    assert confirmation.state == RoutineDeletionConfirmationState.UNCONSUMED
    assert not RoutineManagementReceipt.objects.filter(operation="delete").exists()


@pytest.mark.postgresql
@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="requires PostgreSQL row-lock semantics",
)
@pytest.mark.django_db(transaction=True)
def test_concurrent_delete_confirmation_has_one_winner(account):
    routine = create_intent(account)
    user, workspace, ally, _ = account
    conversation = Conversation.objects.get(ally=ally)
    challenge = issue_deletion_confirmation(
        user=user,
        workspace_id=workspace.id,
        routine_id=routine.id,
        expected_revision=1,
        main_conversation_id=conversation.id,
    )
    gate = Barrier(2)

    def delete_once(_index):
        close_old_connections()
        try:
            gate.wait(timeout=10)
            try:
                delete_routine_intent(
                    user=user,
                    workspace_id=workspace.id,
                    routine_id=routine.id,
                    expected_revision=1,
                    main_conversation_id=conversation.id,
                    confirmation_ref=challenge["confirmation_ref"],
                )
                return "saved"
            except RoutineConfirmationError as exc:
                return exc.result_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(delete_once, (1, 2)))

    assert sorted(outcomes) == [CONFIRMATION_REPLAYED, "saved"]
    routine.refresh_from_db()
    assert routine.state == RoutineState.DELETED
    assert routine.revision == 2
    assert RoutineDeletionConfirmation.objects.get().state == (
        RoutineDeletionConfirmationState.CONSUMED
    )
    assert RoutineManagementReceipt.objects.filter(operation="delete").count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "result_code"),
    [
        ("owner_id", CONFIRMATION_WRONG_OWNER),
        ("workspace_id", CONFIRMATION_WRONG_WORKSPACE),
        ("ally_id", CONFIRMATION_WRONG_ALLY),
        ("binding_id", CONFIRMATION_WRONG_BINDING),
        ("routine_id", CONFIRMATION_WRONG_ROUTINE),
    ],
)
def test_foreign_deletion_confirmation_scope_is_zero_mutation(
    account,
    field,
    result_code,
):
    routine = create_intent(account)
    user, workspace, ally, _ = account
    conversation = Conversation.objects.get(ally=ally)
    challenge = issue_deletion_confirmation(
        user=user,
        workspace_id=workspace.id,
        routine_id=routine.id,
        expected_revision=1,
        main_conversation_id=conversation.id,
    )
    confirmation = RoutineDeletionConfirmation.objects.get()
    if field == "owner_id":
        confirmation.owner_id = User.objects.create_user().id
    elif field == "workspace_id":
        confirmation.workspace_id = Workspace.objects.create(
            owner=User.objects.create_user(),
            name="Foreign workspace",
        ).id
    elif field == "ally_id":
        foreign_ally = Ally.objects.create(
            workspace=workspace,
            name="Foreign ally",
            job="Other",
            personality="Other",
            appearance_catalog_version="v1",
            appearance_key="other",
        )
        confirmation.ally_id = foreign_ally.id
    elif field == "binding_id":
        foreign_ally = Ally.objects.create(
            workspace=workspace,
            name="Binding ally",
            job="Other",
            personality="Other",
            appearance_catalog_version="v1",
            appearance_key="binding",
        )
        confirmation.binding_id = AllyBinding.objects.create(ally=foreign_ally).id
    else:
        other_routine = create_intent(account, title="Other routine")
        confirmation.routine_id = other_routine.id
    confirmation.save(update_fields=(field.removesuffix("_id"),))

    with pytest.raises(RoutineConfirmationError) as foreign:
        delete_routine_intent(
            user=user,
            workspace_id=workspace.id,
            routine_id=routine.id,
            expected_revision=1,
            main_conversation_id=conversation.id,
            confirmation_ref=challenge["confirmation_ref"],
        )
    assert foreign.value.result_code == result_code
    routine.refresh_from_db()
    assert routine.state == RoutineState.ACTIVE
    assert routine.revision == 1
    assert (
        RoutineDeletionConfirmation.objects.get(pk=confirmation.pk).state
        == RoutineDeletionConfirmationState.UNCONSUMED
    )
    assert not RoutineManagementReceipt.objects.filter(operation="delete").exists()


@pytest.mark.django_db
def test_foreign_conversation_deletion_confirmation_is_zero_mutation(account):
    routine = create_intent(account)
    user, workspace, ally, _ = account
    conversation = Conversation.objects.get(ally=ally)
    foreign_ally = Ally.objects.create(
        workspace=workspace,
        name="Conversation ally",
        job="Other",
        personality="Other",
        appearance_catalog_version="v1",
        appearance_key="conversation",
    )
    foreign_conversation = Conversation.objects.create(ally=foreign_ally)
    challenge = issue_deletion_confirmation(
        user=user,
        workspace_id=workspace.id,
        routine_id=routine.id,
        expected_revision=1,
        main_conversation_id=conversation.id,
    )

    with pytest.raises(RoutineConfirmationError) as foreign:
        delete_routine_intent(
            user=user,
            workspace_id=workspace.id,
            routine_id=routine.id,
            expected_revision=1,
            main_conversation_id=foreign_conversation.id,
            confirmation_ref=challenge["confirmation_ref"],
        )
    assert foreign.value.result_code == CONFIRMATION_WRONG_CONVERSATION
    routine.refresh_from_db()
    assert routine.state == RoutineState.ACTIVE
    assert routine.revision == 1
    assert (
        RoutineDeletionConfirmation.objects.get().state
        == RoutineDeletionConfirmationState.UNCONSUMED
    )
    assert not RoutineManagementReceipt.objects.filter(operation="delete").exists()


@pytest.mark.django_db
def test_one_time_pause_is_rejected(account):
    user, workspace, ally, _ = account
    routine = create_routine_intent(
        user=user,
        workspace_id=workspace.id,
        ally_id=ally.id,
        main_conversation_id=Conversation.objects.get(ally=ally).id,
        title="One time",
        execution_prompt="Do it once",
        schedule={
            "kind": "once",
            "local_at": "2026-09-11T09:00:00",
            "timezone": "Europe/Berlin",
        },
        now=datetime(2026, 9, 10, 6, tzinfo=UTC),
    )
    with pytest.raises(RoutineStateError, match="cannot be paused"):
        update_routine_intent(
            user=user,
            workspace_id=workspace.id,
            routine_id=routine.id,
            expected_revision=1,
            state=RoutineState.PAUSED,
        )


@pytest.mark.django_db
def test_paused_routine_cannot_be_changed_to_one_time(account):
    routine = create_intent(account)
    user, workspace, _, _ = account
    update_routine_intent(
        user=user,
        workspace_id=workspace.id,
        routine_id=routine.id,
        expected_revision=1,
        state=RoutineState.PAUSED,
    )

    with pytest.raises(RoutineStateError, match="one-time"):
        update_routine_intent(
            user=user,
            workspace_id=workspace.id,
            routine_id=routine.id,
            expected_revision=2,
            schedule={
                "kind": "once",
                "local_at": "2026-09-11T09:00:00",
                "timezone": "Europe/Berlin",
            },
        )
