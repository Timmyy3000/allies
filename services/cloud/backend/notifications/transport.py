import base64
import ipaddress
import re
import socket
from urllib.parse import urlsplit

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.conf import settings
from py_vapid import Vapid
from pywebpush import WebPushException, webpush

HOSTS = frozenset(
    ("fcm.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com")
)


class PushInvalid(Exception):
    pass


def decode_key(value, size):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise PushInvalid("invalid push key")
    try:
        raw = base64.b64decode(
            value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
        )
        if (
            len(raw) != size
            or base64.urlsafe_b64encode(raw).rstrip(b"=").decode() != value
        ):
            raise ValueError
        if size == 65:
            ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
    except ValueError:
        raise PushInvalid("invalid push key") from None
    return raw


def validate_endpoint(endpoint):
    try:
        url = urlsplit(endpoint)
        if (
            len(endpoint) > 2048
            or any(ord(c) <= 32 or ord(c) >= 127 for c in endpoint)
            or url.scheme != "https"
            or url.hostname not in HOSTS
            or url.username is not None
            or url.password is not None
            or url.fragment
            or "#" in endpoint
            or url.port not in (None, 443)
            or url.netloc not in (url.hostname, f"{url.hostname}:443")
        ):
            raise ValueError
        addresses = socket.getaddrinfo(url.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(
            not ipaddress.ip_address(row[4][0]).is_global for row in addresses
        ):
            raise ValueError
    except (ValueError, OSError):
        raise PushInvalid("invalid push endpoint") from None


def configuration():
    if not getattr(settings, "ALLIES_PUSH_ENABLED", True):
        return None
    try:
        public = getattr(settings, "ALLIES_PUSH_VAPID_PUBLIC_KEY", "")
        public_bytes = decode_key(public, 65)
        private = Vapid.from_string(
            getattr(settings, "ALLIES_PUSH_VAPID_PRIVATE_KEY", "")
        )
        actual = private.public_key.public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        contact = getattr(settings, "ALLIES_PUSH_VAPID_CONTACT", "")
        if actual != public_bytes or not (contact.startswith(("mailto:", "https://"))):
            return None
        return public, private, contact
    except Exception:  # noqa: BLE001 - malformed deployment configuration is nonfatal
        return None


class ProviderSession(requests.Session):
    def __init__(self):
        super().__init__()
        self.trust_env = False

    def post(self, url, **kwargs):
        validate_endpoint(url)
        response = super().post(url, **kwargs, allow_redirects=False, stream=True)
        response.close()
        response._content = b""
        return response


def send_push(subscription, payload, ttl):
    config = configuration()
    if config is None:
        return 0, None, "push_unavailable"
    try:
        with ProviderSession() as session:
            try:
                response = webpush(
                    subscription,
                    payload,
                    vapid_private_key=config[1],
                    vapid_claims={"sub": config[2]},
                    timeout=10,
                    ttl=ttl,
                    requests_session=session,
                )
            except WebPushException as exc:
                response = exc.response
                if response is None:
                    return 0, None, "push_transport_error"
            return response.status_code, response.headers.get("Retry-After"), ""
    except PushInvalid:
        return 400, None, "push_endpoint_invalid"
    except requests.RequestException:
        return 0, None, "push_transport_error"
    except (ValueError, TypeError, WebPushException):
        return 400, None, "push_configuration_error"
