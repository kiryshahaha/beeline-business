"""Narrow Firebase Cloud Messaging boundary used by the dispatcher."""

from dataclasses import dataclass, field

from app.core.config import Settings

MAX_MULTICAST_TOKENS = 500


@dataclass(frozen=True)
class PushResult:
    invalid_tokens: set[str] = field(default_factory=set)


class DisabledPushGateway:
    enabled = False

    def send(self, tokens: list[str], *, title: str, body: str, data: dict[str, str]) -> PushResult:
        return PushResult()


class FirebasePushGateway:
    enabled = True

    def __init__(self, app) -> None:
        self._app = app

    def send(self, tokens: list[str], *, title: str, body: str, data: dict[str, str]) -> PushResult:
        from firebase_admin import messaging

        invalid_tokens = set()
        retryable_errors = []
        for offset in range(0, len(tokens), MAX_MULTICAST_TOKENS):
            batch_tokens = tokens[offset : offset + MAX_MULTICAST_TOKENS]
            message = messaging.MulticastMessage(
                tokens=batch_tokens,
                notification=messaging.Notification(title=title, body=body),
                data=data,
            )
            response = messaging.send_each_for_multicast(message, app=self._app)
            for token, send_response in zip(batch_tokens, response.responses, strict=True):
                if send_response.success:
                    continue
                if isinstance(send_response.exception, messaging.UnregisteredError):
                    invalid_tokens.add(token)
                else:
                    retryable_errors.append(str(send_response.exception))
        if retryable_errors:
            raise RuntimeError("; ".join(retryable_errors))
        return PushResult(invalid_tokens=invalid_tokens)


def create_push_gateway(settings: Settings):
    if not settings.firebase_enabled:
        return DisabledPushGateway()

    import firebase_admin

    options = {"projectId": settings.firebase_project_id} if settings.firebase_project_id else None
    try:
        firebase_app = firebase_admin.get_app()
    except ValueError:
        firebase_app = firebase_admin.initialize_app(options=options)
    return FirebasePushGateway(firebase_app)
