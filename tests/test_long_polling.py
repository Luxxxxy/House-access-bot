from __future__ import annotations

import asyncio
import ssl
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from app.bot.client import BotClient, MaxBotClient
from app.bot.dispatcher import Dispatcher, Router
from app.config import Settings, settings
from app.integrations import check_max_tls
from app.integrations import subscribe_webhook, unsubscribe_webhook
from app.integrations.max_tls import (
    MAX_RUSSIAN_CA_BUNDLE,
    build_max_ssl_context,
    create_max_api_client,
)
from app.web.main import app


@pytest.mark.asyncio
async def test_max_client_polls_official_updates_endpoint_and_keeps_message_sending():
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/updates":
            return httpx.Response(200, json={"updates": [], "marker": 17})
        return httpx.Response(200, json={"message": {"body": {"mid": "out-1"}}})

    bot = MaxBotClient("test-token")
    bot._client = httpx.AsyncClient(
        base_url="https://platform-api2.max.ru",
        headers={"Authorization": "test-token"},
        transport=httpx.MockTransport(handler),
    )
    try:
        page = await bot.get_updates(marker=12, timeout=90)
        await bot.send_message(user_id=12345, text="Тест")
    finally:
        await bot.close()

    assert page == {"updates": [], "marker": 17}
    assert requests[0].method == "GET"
    assert requests[0].url.host == "platform-api2.max.ru"
    assert requests[0].url.path == "/updates"
    assert dict(requests[0].url.params) == {"limit": "100", "timeout": "90", "marker": "12"}
    assert requests[0].headers["Authorization"] == "test-token"
    assert requests[1].method == "POST"
    assert requests[1].url.path == "/messages"
    assert requests[1].url.params["user_id"] == "12345"


@pytest.mark.asyncio
async def test_client_refuses_polling_when_webhook_subscription_exists():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"subscriptions": [{"url": "https://example.test/api/v1/max/webhook"}]},
        )

    bot = MaxBotClient("test-token")
    bot._client = httpx.AsyncClient(
        base_url="https://platform-api2.max.ru",
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(RuntimeError, match="webhook-подписка"):
            await bot.ensure_no_webhook_subscription()
    finally:
        await bot.close()


@pytest.mark.asyncio
async def test_client_allows_polling_without_webhook_subscription():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"subscriptions": []})

    bot = MaxBotClient("test-token")
    bot._client = httpx.AsyncClient(
        base_url="https://platform-api2.max.ru",
        transport=httpx.MockTransport(handler),
    )
    try:
        await bot.ensure_no_webhook_subscription()
    finally:
        await bot.close()


@pytest.mark.asyncio
async def test_dispatcher_passes_max_marker_and_dispatches_updates():
    class InterruptingBot(BotClient):
        def __init__(self) -> None:
            self.markers: list[int | None] = []

        async def start(self) -> None:
            return None

        async def close(self) -> None:
            return None

        async def get_updates(self, *, marker: int | None = None, timeout: int = 30):
            self.markers.append(marker)
            if len(self.markers) == 1:
                return {"updates": [{"update_type": "message_created"}], "marker": 45}
            raise asyncio.CancelledError

        async def send_message(self, **_kwargs):
            return None

        async def edit_message(self, _message_id: str, **_kwargs):
            return None

    handled: list[dict] = []
    router = Router("test")

    @router.event("message_created")
    async def handle(_bot, update):
        handled.append(update)

    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    bot = InterruptingBot()

    with pytest.raises(asyncio.CancelledError):
        await dispatcher.start_polling(bot, timeout=20)

    assert bot.markers == [None, 45]
    assert handled == [{"update_type": "message_created"}]


def test_long_polling_configuration_is_development_only():
    assert Settings(environment="development", max_update_mode="long_polling").max_update_mode == (
        "long_polling"
    )
    with pytest.raises(ValidationError, match="only in development"):
        Settings(environment="production", max_update_mode="long_polling")


@pytest.mark.asyncio
async def test_webhook_subscription_command_refuses_long_polling_mode(monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "max_update_mode", "long_polling")
    with pytest.raises(SystemExit, match="переключите MAX_UPDATE_MODE=webhook"):
        await subscribe_webhook.main()


def test_unsubscribe_command_targets_only_the_configured_webhook(monkeypatch):
    monkeypatch.setattr(settings, "app_base_url", "https://local-test.example/")
    assert unsubscribe_webhook._configured_webhook_url() == (
        "https://local-test.example/api/v1/max/webhook"
    )


@pytest.mark.asyncio
async def test_unsubscribe_command_requires_long_polling_mode(monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "max_update_mode", "webhook")
    with pytest.raises(SystemExit, match="MAX_UPDATE_MODE=long_polling"):
        await unsubscribe_webhook.main()


@pytest.mark.asyncio
async def test_webhook_route_is_disabled_in_long_polling_mode(monkeypatch):
    monkeypatch.setattr(settings, "max_update_mode", "long_polling")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post("/api/v1/max/webhook", json={"update_type": "bot_started"})
    assert response.status_code == 409


def test_max_tls_context_requires_standard_and_russian_ca_trust():
    context = build_max_ssl_context()

    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert MAX_RUSSIAN_CA_BUNDLE.is_file()

    common_names = {
        value
        for certificate in context.get_ca_certs()
        for relative_name in certificate["subject"]
        for name, value in relative_name
        if name == "commonName"
    }
    assert "Russian Trusted Root CA" in common_names
    assert "Russian Trusted Sub CA" in common_names
    assert len(common_names) > 50  # the public/system roots remain in the trust store


def test_max_client_is_given_verified_ssl_context(monkeypatch):
    captured: dict = {}

    class RecordingAsyncClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("app.integrations.max_tls.httpx.AsyncClient", RecordingAsyncClient)
    create_max_api_client()

    context = captured["verify"]
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


@pytest.mark.asyncio
async def test_tls_diagnostic_treats_http_401_as_verified_tls(monkeypatch, capsys):
    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _path):
            return SimpleNamespace(status_code=401)

    monkeypatch.setattr(check_max_tls, "create_max_api_client", lambda **_kwargs: FakeClient())
    assert await check_max_tls.check_max_tls() == 0
    assert "TLS connection verified: HTTP 401" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_tls_diagnostic_fails_on_ssl_connect_error(monkeypatch, capsys):
    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _path):
            raise httpx.ConnectError("certificate verify failed")

    monkeypatch.setattr(check_max_tls, "create_max_api_client", lambda **_kwargs: FakeClient())
    assert await check_max_tls.check_max_tls() == 1
    assert "TLS connection failed" in capsys.readouterr().out
