"""Apply and verify a paired desired runtime release using the optional Railway API."""

import argparse
import http.client
import json
import os
import re
import sys
import time
from uuid import UUID

KEYS = ("HERMES_IMAGE", "RUNTIME_IMAGE")
IMAGE = re.compile(r"[a-z0-9][a-z0-9._:/-]*@sha256:[0-9a-f]{64}")


class PairUpdateError(Exception):
    pass


def validate_pair(values):
    if not isinstance(values, dict):
        raise PairUpdateError("Image configuration is not an object")
    pair = {key: values[key] for key in KEYS if key in values}
    if not pair:
        return None
    if len(pair) != 2 or any(
        not isinstance(value, str) or len(value) > 512 or not IMAGE.fullmatch(value)
        for value in pair.values()
    ):
        raise PairUpdateError(
            "Image configuration must contain two immutable references"
        )
    return pair


def graphql(query, variables):
    connection = http.client.HTTPSConnection("backboard.railway.com", timeout=10)
    try:
        connection.connect()
        connection.sock.settimeout(30)
        connection.request(
            "POST",
            "/graphql/v2",
            json.dumps({"query": query, "variables": variables}),
            {
                "Authorization": f"Bearer {os.environ['RAILWAY_API_TOKEN']}",
                "Content-Type": "application/json",
            },
        )
        response = connection.getresponse()
        raw = response.read(1_048_577)
        if response.status != 200 or len(raw) > 1_048_576:
            raise PairUpdateError("Configuration API request failed")
        payload = json.loads(raw)
        if (
            not isinstance(payload, dict)
            or payload.get("errors")
            or not isinstance(payload.get("data"), dict)
        ):
            raise PairUpdateError("Configuration API rejected the request")
        return payload["data"]
    except (OSError, http.client.HTTPException, ValueError) as exc:
        raise PairUpdateError(
            "Configuration API response could not be verified"
        ) from exc
    finally:
        connection.close()


def update_pair(project, environment, desired, *, request=graphql, sleep=time.sleep):
    desired = validate_pair(desired)
    if environment not in ("staging", "production") or desired is None:
        raise PairUpdateError("Invalid target or image pair")
    data = request(
        "query($id: String!) { project(id: $id) { environments { edges { node { id name } } } } }",
        {"id": project},
    )
    try:
        matches = [
            edge["node"]["id"]
            for edge in data["project"]["environments"]["edges"]
            if edge["node"]["name"] == environment
        ]
        if len(matches) != 1:
            raise ValueError
        environment_id = str(UUID(matches[0]))
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise PairUpdateError("Expected exactly one target environment") from exc
    scope = {"projectId": project, "environmentId": environment_id}

    def read_pair():
        result = request(
            "query($projectId: String!, $environmentId: String!) { variables(projectId: $projectId, environmentId: $environmentId) }",
            scope,
        )
        return validate_pair(result.get("variables"))

    previous = read_pair()
    current = previous
    for attempt in range(3):
        if current == desired:
            break
        try:
            result = request(
                "mutation($input: VariableCollectionUpsertInput!) { variableCollectionUpsert(input: $input) }",
                {"input": {**scope, "variables": desired, "replace": False}},
            )
            if result.get("variableCollectionUpsert") is not True:
                raise PairUpdateError(
                    "Configuration API did not confirm the collection update"
                )
        except PairUpdateError:
            pass
        current = read_pair()
        if current != desired and attempt < 2:
            sleep(attempt + 1)
    if current != desired:
        raise PairUpdateError(
            "Desired pair was not verified; inspect configuration before recovery"
        )
    return {
        "environment": environment,
        "previous": previous,
        "readback": current,
        "state": "desired_config_verified",
        "machine_adoption": "not_verified",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--environment", choices=("staging", "production"), required=True
    )
    parser.add_argument("--hermes-image", required=True)
    parser.add_argument("--runtime-image", required=True)
    args = parser.parse_args()
    try:
        if not os.environ.get("RAILWAY_API_TOKEN") or not os.environ.get(
            "RAILWAY_PROJECT_ID"
        ):
            raise PairUpdateError(
                "RAILWAY_API_TOKEN and RAILWAY_PROJECT_ID are required"
            )
        project = str(UUID(os.environ["RAILWAY_PROJECT_ID"]))
        receipt = update_pair(
            project,
            args.environment,
            dict(zip(KEYS, (args.hermes_image, args.runtime_image))),
        )
        print(json.dumps(receipt))
    except (PairUpdateError, ValueError) as exc:
        print(
            str(exc) if isinstance(exc, PairUpdateError) else "Invalid project ID",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
