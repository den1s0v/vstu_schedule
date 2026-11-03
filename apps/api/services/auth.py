from datetime import timedelta
from http import HTTPStatus
from typing import Any, cast

import jwt
from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone
from dmr import APIError, Controller
from dmr.errors import format_error
from dmr.exceptions import NotAuthenticatedError
from dmr.metadata import EndpointMetadata
from dmr.openapi.objects import Reference, SecurityRequirement, SecurityScheme
from dmr.security.base import SyncAuth
from dmr.security.django_session import DjangoSessionSyncAuth
from dmr.serializer import BaseSerializer

from apps.api.models import ApiClient

JWT_ALGORITHM = "HS256"


def issue_access_token(client: ApiClient) -> tuple[str, int]:
    now = timezone.now()
    expires_in = settings.API_ACCESS_TOKEN_SECONDS
    expires_at = now + timedelta(seconds=expires_in)
    payload: dict[str, Any] = {
        "sub": client.client_id,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": client.secret_rotated_at.isoformat(),
        "scope": client.allowed_scopes,
    }
    token = jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)
    return token, expires_in


def authenticate_request_token(request: HttpRequest) -> ApiClient | None:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header.removeprefix("Bearer ").strip()
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise NotAuthenticatedError("Invalid API token.") from exc

    client_id = payload.get("sub")
    if not isinstance(client_id, str):
        raise NotAuthenticatedError("Invalid API token subject.")

    try:
        client = ApiClient.objects.get(client_id=client_id)
    except ApiClient.DoesNotExist as exc:
        raise NotAuthenticatedError("API client was not found.") from exc

    if not client.is_active or client.revoked_at is not None:
        raise NotAuthenticatedError("API client is revoked.")

    issued_at = payload.get("iat")
    if not isinstance(issued_at, int):
        raise NotAuthenticatedError("Invalid API token issue time.")
    if issued_at < int(client.secret_rotated_at.timestamp()):
        raise NotAuthenticatedError("API token was issued before secret rotation.")

    client.mark_used()
    cast(Any, request).api_client = client
    return client


def is_unlimited_request(request: HttpRequest) -> bool:
    if authenticate_request_token(request) is not None:
        return True

    user = getattr(request, "user", None)
    return bool(user and user.is_authenticated and user.is_active and user.is_staff)


class ApiClientTokenSyncAuth(SyncAuth):
    @property
    def www_authenticate_challenge(self) -> str:
        return "Bearer"

    def security_schemes(
        self,
        metadata: EndpointMetadata,
        controller_cls: type[Controller[BaseSerializer]],
    ) -> dict[str, SecurityScheme | Reference]:
        return {
            "api_client_bearer": SecurityScheme(
                type="http",
                description="Short-lived API client JWT access token",
                scheme="Bearer",
                bearer_format="JWT",
            )
        }

    def security_requirements(
        self,
        metadata: EndpointMetadata,
        controller_cls: type[Controller[BaseSerializer]],
    ) -> list[SecurityRequirement]:
        return [{"api_client_bearer": []}]

    def __call__(self, endpoint, controller):
        if authenticate_request_token(controller.request) is None:
            return None
        return self


class StaffSessionSyncAuth(DjangoSessionSyncAuth):
    def authenticate(self, endpoint, controller):
        auth = super().authenticate(endpoint, controller)
        if auth is None:
            return None
        user = getattr(controller.request, "user", None)
        if not user or not user.is_staff:
            return None
        return auth


def invalid_credentials_error() -> APIError:
    return APIError(
        format_error("Invalid client credentials."),
        status_code=HTTPStatus.UNAUTHORIZED,
    )


def _jwt_secret() -> str:
    return cast(str, settings.SECRET_KEY)
