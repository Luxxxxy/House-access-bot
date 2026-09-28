"""Разбор апдейтов MAX (модели SDK или сырой dict)."""

from __future__ import annotations

from typing import Any


def as_dict(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        return dump()
    return {}


def update_type(update: Any) -> str:
    if isinstance(update, dict):
        return str(update.get("update_type") or "")
    return str(getattr(update, "update_type", "") or "")


def _nested(obj: Any, *names: str) -> Any:
    current = obj
    for name in names:
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(name)
        else:
            current = getattr(current, name, None)
    return current


def message_text(update: Any) -> str:
    text = _nested(update, "message", "body", "text")
    return (text or "").strip()


def parse_command(text: str) -> str | None:
    if not text.startswith("/"):
        return None
    token = text.split()[0][1:]
    return token.split("@", 1)[0].lower() or None


def callback_payload(update: Any) -> str | None:
    payload = _nested(update, "callback", "payload")
    if payload is not None:
        return str(payload)
    return None


def sender_user_id(update: Any) -> int | None:
    paths: tuple[tuple[str, ...], ...]
    if update_type(update) == "message_callback":
        paths = (
            ("callback", "user", "user_id"),
            ("message", "sender", "user_id"),
            ("user", "user_id"),
            ("user_id",),
        )
    else:
        paths = (
            ("message", "sender", "user_id"),
            ("callback", "user", "user_id"),
            ("user", "user_id"),
            ("user_id",),
        )
    for path in paths:
        value = _nested(update, *path)
        if value is not None:
            return int(value)
    return None


def sender_name(update: Any) -> str | None:
    for path in (
        ("message", "sender", "name"),
        ("callback", "user", "name"),
        ("user", "name"),
    ):
        value = _nested(update, *path)
        if value:
            return str(value)
    return None


def sender_username(update: Any) -> str | None:
    for path in (
        ("message", "sender", "username"),
        ("callback", "user", "username"),
        ("user", "username"),
    ):
        value = _nested(update, *path)
        if value:
            return str(value)
    return None


def chat_id(update: Any) -> int | None:
    for path in (
        ("message", "recipient", "chat_id"),
        ("chat_id",),
        ("callback", "user", "user_id"),
    ):
        value = _nested(update, *path)
        if value is not None:
            return int(value)
    return None


def message_mid(update: Any) -> str | None:
    for path in (
        ("message", "body", "mid"),
        ("message", "mid"),
        ("callback", "message", "body", "mid"),
    ):
        value = _nested(update, *path)
        if value:
            return str(value)
    return None


def forwarded_user(update: Any) -> tuple[int | None, str | None, str | None]:
    """user_id, name, username из пересланного сообщения, если API его отдаёт."""
    link = _nested(update, "message", "link")
    link_type = None
    if isinstance(link, dict):
        link_type = link.get("type")
    elif link is not None:
        link_type = getattr(link, "type", None)

    if str(link_type or "").lower() in {"forward", "fwd"}:
        user_id = _nested(link, "sender", "user_id")
        name = _nested(link, "sender", "name") or _nested(link, "sender", "first_name")
        username = _nested(link, "sender", "username")
        if user_id is None:
            user_id = _nested(link, "message", "sender", "user_id")
            name = name or _nested(link, "message", "sender", "name")
            username = username or _nested(link, "message", "sender", "username")
        if user_id is not None:
            return (
                int(user_id),
                str(name) if name else None,
                str(username) if username else None,
            )

    for path in (
        ("message", "link", "sender", "user_id"),
        ("message", "forwarded_message", "sender", "user_id"),
        ("message", "body", "link", "sender", "user_id"),
    ):
        value = _nested(update, *path)
        if value is not None:
            name = (
                _nested(update, "message", "link", "sender", "name")
                or _nested(update, "message", "forwarded_message", "sender", "name")
            )
            username = (
                _nested(update, "message", "link", "sender", "username")
                or _nested(update, "message", "forwarded_message", "sender", "username")
            )
            return (
                int(value),
                str(name) if name else None,
                str(username) if username else None,
            )
    return None, None, None
