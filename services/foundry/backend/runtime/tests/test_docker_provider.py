import base64
from uuid import uuid4

from runtime.providers.docker import DockerProvider, DockerSecretStore
from runtime.providers.domain import MachineState
from runtime.services.workspaces import WorkspaceSpec


class FakeEngine:
    """In-memory Docker Engine covering the calls the provider makes."""

    def __init__(self):
        self.containers = {}
        self.volumes = {}

    def request(self, method, path, *, query=None, body=None, operation):
        parts = path.strip("/").split("/")
        if parts == ["volumes", "create"]:
            self.volumes[body["Name"]] = body
            return 201, body
        if parts == ["volumes"]:
            return 200, {"Volumes": list(self.volumes.values())}
        if parts == ["containers", "json"]:
            return 200, [{"Labels": c["Config"]["Labels"]} for c in self.containers.values()]
        if parts == ["containers", "create"]:
            self.containers[query["name"]] = {
                "Id": query["name"],
                "Config": {"Labels": body["Labels"], "Image": body["Image"], "Env": body["Env"]},
                "HostConfig": body["HostConfig"],
                "State": {"Status": "created"},
            }
            return 201, {"Id": query["name"]}
        name = parts[1]
        if name not in self.containers:
            return 404, None
        if parts[-1] == "json":
            return 200, self.containers[name]
        if parts[-1] == "start":
            self.containers[name]["State"]["Status"] = "running"
        elif parts[-1] == "stop":
            self.containers[name]["State"]["Status"] = "exited"
        elif method == "DELETE":
            del self.containers[name]
        return 204, None


def test_docker_provider_runs_the_two_container_machine(tmp_path):
    secrets = DockerSecretStore(tmp_path)
    engine = FakeEngine()
    provider = DockerProvider(network="allies", secrets=secrets, engine=engine)
    workspace_id = uuid4()
    spec = WorkspaceSpec(
        organization="local",
        region="local",
        hermes_image="hermes:local",
        runtime_image="runtime:local",
        foundry_origin="http://foundry:8000",
        foundry_runtime_credential_ref="file:///run/secrets/foundry-runtime-token",
        foundry_runtime_credential_secret_name="ALLIES_TOKEN",
    )
    app = provider.ensure_app(spec.app_spec(workspace_id))
    assert provider.inspect_app(app.name) is not None
    secrets.stage(app.name, "ALLIES_TOKEN", base64.b64encode(b"secret").decode())

    volume = provider.create_volume(spec.volume_spec(workspace_id))
    machine_spec = spec.machine_spec(workspace_id, volume.id, 1, uuid4())
    machine = provider.create_machine(machine_spec)
    assert machine.state is MachineState.CREATED
    assert machine.ownership.workspace_id == workspace_id
    assert provider.list_volumes(app.name)[0].attached_machine_id == machine.id

    runtime = engine.containers[machine.id + "-runtime"]
    assert runtime["HostConfig"]["NetworkMode"] == f"container:{machine.id}"
    assert f"ALLIES_TOKEN={base64.b64encode(b'secret').decode()}" in runtime["Config"]["Env"]
    assert "FOUNDRY_ORIGIN=http://foundry:8000" in runtime["Config"]["Env"]

    assert provider.start_machine(app.name, machine.id).state is MachineState.STARTED
    assert provider.wait_machine(app.name, machine.id, timeout_seconds=1).health.state is MachineState.STARTED
    assert provider.stop_machine(app.name, machine.id).state is MachineState.STOPPED
    provider.destroy_machine(app.name, machine.id)
    assert provider.inspect_machine(app.name, machine.id) is None
