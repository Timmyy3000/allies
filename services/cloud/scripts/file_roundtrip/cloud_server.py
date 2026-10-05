import json
import os
import sys
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, make_server

backend = Path(sys.argv[1])
sys.path.insert(0, str(backend))
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
os.environ["DJANGO_DEBUG"] = "true"
os.environ.pop("DATABASE_URL", None)
from django.conf import settings

settings.DATABASES["default"]["NAME"] = str(Path(sys.argv[3]) / "cloud.sqlite3")
settings.ALLOWED_HOSTS = ["127.0.0.1", "testserver"]
settings.ALLIES_AUTH_DIGEST_KEY = "d" * 32
settings.ALLIES_FOUNDRY_EVENT_SERVICE_TOKEN = "f" * 32
settings.ALLIES_FILE_STORAGE_ENABLED = True
settings.ALLIES_FILE_INSPECTION_ENABLED = True
settings.ALLIES_FILE_STORAGE_CAPACITY_BYTES = 100_000_000
import django

django.setup()
from django.core.management import call_command

call_command("migrate", verbosity=0)
from allies.models import Ally, AllyBinding, BindingStatus
from auths.models import User
from chat.models import Conversation, Message, MessageOrigin, MessageSender
from django.core.wsgi import get_wsgi_application
from django.utils import timezone
from files.exceptions import FileConflict
from files.models import FileState, FileStorageAccount, FileVersion
from files.services.cleanup import cleanup_files
from files.services.intake import InspectionResult, promote_inspected_file
from files.services.publication import (
    publication_view,
    reconcile_publication,
    retry_publication,
)
from files.storage import InMemoryFileObjectStore, set_file_store
from workspaces.models import Membership, Workspace

owner = User.objects.create_user()
workspace = Workspace.objects.create(owner=owner, name="Roundtrip")
Membership.objects.create(
    workspace=workspace, user=owner, role="owner", status="active"
)
ally = Ally.objects.create(
    workspace=workspace,
    name="Test",
    job="Test",
    personality="Calm",
    appearance_catalog_version="v1",
    appearance_key="sunrise",
)
binding = AllyBinding.objects.create(
    ally=ally, status=BindingStatus.BOUND, receipt_digest="b" * 64
)
conversation = Conversation.objects.create(ally=ally)
message = Message.objects.create(
    conversation=conversation,
    sequence=1,
    sender=MessageSender.USER,
    origin=MessageOrigin.SEND,
    content="return a file",
    send_key_digest="a" * 64,
    content_fingerprint="c" * 64,
    execution_claimed_at=timezone.now(),
    foundry_binding_id=binding.id,
)
store = InMemoryFileObjectStore()
set_file_store(store)
application = get_wsgi_application()
fail_first_scan = True
received = []
stopping = False


def app(environ, start_response):
    global fail_first_scan, stopping
    path = environ["PATH_INFO"]
    if path == "/test/stop":
        stopping = True
        start_response("200 OK", [("Content-Type", "application/json")])
        return [b"{}"]
    if path == "/test/state":
        rows = list(FileVersion.objects.all())
        account = FileStorageAccount.objects.get(workspace=workspace)
        payload = {
            "received": received,
            "storage": {
                "reserved_bytes": account.reserved_bytes,
                "retained_bytes": account.retained_bytes,
            },
            "files": [
                {
                    "id": str(f.id),
                    "state": f.state,
                    "sha256": f.sha256,
                    "generation": f.generation,
                    "bytes": store.open_stream(key=f.object_key).read().hex()
                    if f.object_key and f.state == FileState.READY
                    else None,
                }
                for f in rows
            ],
        }
        start_response("200 OK", [("Content-Type", "application/json")])
        return [json.dumps(payload).encode()]
    if path == "/test/retry":
        f = FileVersion.objects.first()
        view = publication_view(publication_id=f.publication_id)
        arguments = {
            "user": owner,
            "workspace_id": workspace.id,
            "ally_id": ally.id,
            "message_id": message.id,
            "publication_id": f.publication_id,
            "revision": view["revision"],
        }
        try:
            retry_publication(**arguments)
        except FileConflict as error:
            assert str(error) == "publication cleanup pending"
        else:
            raise AssertionError("retry started before staging cleanup")
        assert (
            publication_view(publication_id=f.publication_id)["revision"]
            == view["revision"]
        )
        cleanup_files(limit=20)
        result = retry_publication(**arguments)
        result["cleanup_confirmed"] = True
        start_response("200 OK", [("Content-Type", "application/json")])
        return [json.dumps(result).encode()]
    captured = []

    def capture(status, headers, exc_info=None):
        captured.extend([status, headers])

    response = application(environ, capture)
    try:
        body = b"".join(response)
    finally:
        if hasattr(response, "close"):
            response.close()
    if (
        environ["REQUEST_METHOD"] == "PUT"
        and path.endswith("/content")
        and captured[0].startswith("202")
    ):
        f = FileVersion.objects.get(pk=path.split("/")[-2])
        received.append({"sha256": f.sha256, "generation": f.generation})
        if fail_first_scan:
            f.state = FileState.FAILED
            f.save(update_fields=["state"])
            fail_first_scan = False
        else:
            promote_inspected_file(
                file_id=f.id,
                generation=f.generation,
                result=InspectionResult(f.expected_size, f.sha256, "text/csv", True),
            )
        reconcile_publication(publication_id=f.publication_id)
    start_response(*captured)
    return [body]


class Quiet(WSGIRequestHandler):
    def log_message(self, *_args):
        pass


with make_server("127.0.0.1", 0, app, handler_class=Quiet) as server:
    Path(sys.argv[2]).write_text(
        json.dumps(
            {
                "url": f"http://127.0.0.1:{server.server_port}",
                "binding_id": str(binding.id),
                "message_id": str(message.id),
            }
        )
    )
    while not stopping:
        server.handle_request()
    from django.db import connections

    connections.close_all()
