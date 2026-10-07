"""Controlled errors; exception messages never contain upstream payloads."""

from typing import Literal

from app.domain.contracts import Contract

ErrorCode = Literal[
    "unauthorized",
    "invalid_request",
    "request_too_large",
    "serving_busy",
    "provider_timeout",
    "provider_rate_limited",
    "provider_authentication",
    "provider_unavailable",
    "provider_request_rejected",
    "invalid_provider_response",
    "internal_error",
]

ERRORS: dict[ErrorCode, tuple[int, str]] = {
    "unauthorized": (401, "A valid gateway bearer key is required."),
    "invalid_request": (422, "The request does not satisfy the gateway contract."),
    "request_too_large": (413, "The request exceeds the configured byte limit."),
    "serving_busy": (503, "All serving slots are occupied."),
    "provider_timeout": (504, "The provider exceeded the serving deadline."),
    "provider_rate_limited": (429, "The provider rate limit was reached."),
    "provider_authentication": (502, "The upstream provider rejected gateway credentials."),
    "provider_unavailable": (503, "The provider is unavailable."),
    "provider_request_rejected": (502, "The provider rejected the configured request."),
    "invalid_provider_response": (502, "The provider returned an unsupported response."),
    "internal_error": (500, "The gateway could not complete the request."),
}


class ProviderError(Exception):
    def __init__(self, code: ErrorCode, retry_after: int | None = None) -> None:
        self.code = code
        self.retry_after = retry_after
        super().__init__(ERRORS[code][1])


class ErrorDetail(Contract):
    code: ErrorCode
    message: str


class ErrorResponse(Contract):
    error: ErrorDetail
    request_id: str
    retry_after_seconds: int | None = None


def error_body(
    code: ErrorCode, request_id: str, retry_after: int | None = None
) -> dict[str, object]:
    return ErrorResponse(
        error=ErrorDetail(code=code, message=ERRORS[code][1]),
        request_id=request_id,
        retry_after_seconds=retry_after,
    ).model_dump(exclude_none=True)
