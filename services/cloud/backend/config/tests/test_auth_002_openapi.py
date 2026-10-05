from config.api import api


def test_native_openapi_publishes_routes_security_and_no_store_headers():
    schema = api.get_openapi_schema()
    paths = schema["paths"]
    native_paths = {
        "/api/v1/auths/native/sign-in/{provider}": "post",
        "/api/v1/auths/native/callback/{provider}": "get",
        "/api/v1/auths/native/token": "post",
        "/api/v1/auths/native/token/refresh": "post",
        "/api/v1/auths/native/logout": "post",
    }

    assert all(
        path in paths and method in paths[path] for path, method in native_paths.items()
    )
    for path, method in native_paths.items():
        operation = paths[path][method]
        expected_security = [{}, {"BearerAuth": []}] if path.endswith("/logout") else []
        assert operation["security"] == expected_security
        assert "do not use browser cookies or CSRF" in operation["description"]

    for path, method in (
        ("/api/v1/auths/me", "get"),
        ("/api/v1/auths/me/profile", "patch"),
        ("/api/v1/auths/me/avatar/uploads", "post"),
        ("/api/v1/auths/me/avatar/{asset_id}/complete", "post"),
        ("/api/v1/auths/me/avatar/read", "get"),
        ("/api/v1/auths/me/avatar", "delete"),
        ("/api/v1/workspaces/{workspace_id}", "get"),
    ):
        assert paths[path][method]["security"] == [{"BearerAuth": []}]

    bearer = schema["components"]["securitySchemes"]["BearerAuth"]
    assert bearer["type"] == "http"
    assert bearer["scheme"] == "bearer"
    assert bearer["bearerFormat"] == "JWT"

    for path in (
        "/api/v1/auths/native/token",
        "/api/v1/auths/native/token/refresh",
    ):
        response = next(
            value
            for status, value in paths[path]["post"]["responses"].items()
            if str(status) == "200"
        )
        assert response["headers"]["Cache-Control"]["example"] == "no-store"
        assert response["headers"]["Pragma"]["example"] == "no-cache"


def test_native_openapi_uses_closed_protocol_literals_and_safe_success_examples():
    schema = api.get_openapi_schema()
    request_schemas = schema["components"]["schemas"]
    assert request_schemas["NativeSignInRequest"]["properties"][
        "code_challenge_method"
    ]["enum"] == ["S256"]
    completion_mode = request_schemas["NativeSignInRequest"]["properties"][
        "completion_mode"
    ]
    assert completion_mode["enum"] == ["redirect", "manual_code"]
    assert completion_mode["default"] == "redirect"
    assert "completion_mode" not in request_schemas["NativeSignInRequest"].get(
        "required", []
    )
    assert request_schemas["NativeTokenExchangeRequest"]["properties"]["grant_type"][
        "enum"
    ] == ["authorization_code"]
    assert request_schemas["NativeRefreshRequest"]["properties"]["grant_type"][
        "enum"
    ] == ["refresh_token"]

    start_example = schema["components"]["schemas"][
        "SuccessResponse_NativeAuthorizationStartResponse_"
    ]["example"]
    token_example = schema["components"]["schemas"][
        "SuccessResponse_NativeTokenResponse_"
    ]["example"]
    assert start_example["data"]["authorization_url"].startswith("https://")
    assert "access_token" in token_example["data"]
    assert token_example["data"]["expires_in"] == 600
    assert token_example["data"]["refresh_expires_in"] == 1209600

    callback = schema["paths"]["/api/v1/auths/native/callback/{provider}"]["get"]
    manual_page = callback["responses"][200]
    assert manual_page["content"]["text/html"]["schema"] == {"type": "string"}
    assert manual_page["headers"]["Cache-Control"]["example"] == "no-store"
    assert manual_page["headers"]["Referrer-Policy"]["example"] == "no-referrer"
    assert manual_page["headers"]["X-Content-Type-Options"]["example"] == "nosniff"
    assert (
        "script-src 'nonce-"
        in manual_page["headers"]["Content-Security-Policy"]["example"]
    )
    assert "Location" in callback["responses"][303]["headers"]
