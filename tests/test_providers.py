"""The real providers, exercised without a key or a network."""
import json

import httpx
import pytest

from vsmail.llm.deepseek import DeepSeekProvider
from vsmail.llm.remote import RemoteProvider
from vsmail.models import Document, EmailRecord

_EMAIL = EmailRecord("email_1", "a@b.c", "subject", "Please compare the SI and draft BL.")


def _transport(payload: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handler)


def _chat(content: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(content)}}]}


def test_a_key_is_required(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        DeepSeekProvider(api_key="")


async def test_deepseek_classification_is_parsed():
    provider = DeepSeekProvider(api_key="test-key")
    provider._client = httpx.AsyncClient(
        transport=_transport(_chat({"category": "bl_comparison", "confidence": 0.9})),
        base_url="https://api.invalid",
    )
    result = await provider.classify(_EMAIL)
    assert result.category == "BL_COMPARISON"
    assert result.confidence == 0.9
    await provider.aclose()


async def test_an_unusable_category_does_not_become_a_confident_guess():
    provider = DeepSeekProvider(api_key="test-key")
    provider._client = httpx.AsyncClient(
        transport=_transport(_chat({"category": "WHATEVER"})), base_url="https://api.invalid"
    )
    result = await provider.classify(_EMAIL)
    assert result.category == "GENERAL"
    assert result.confidence == 0.0, "an unparsed answer must not look certain"
    await provider.aclose()


async def test_placeholder_values_are_read_as_missing():
    """A model writing "N/A" means absent, and must not compare as a value."""
    provider = DeepSeekProvider(api_key="test-key")
    provider._client = httpx.AsyncClient(
        transport=_transport(
            _chat({"si": {"shipper": "ACME", "consignee": "N/A"}, "bl": {"shipper": "ACME"}})
        ),
        base_url="https://api.invalid",
    )
    extraction = await provider.extract(
        Document("a_SI.txt", "SI", text="x"), Document("a_BL.txt", "BL", text="y")
    )
    assert extraction.si["shipper"] == "ACME"
    assert extraction.si["consignee"] is None
    assert extraction.bl["consignee"] is None
    await provider.aclose()


async def test_remote_provider_sends_its_token(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["token"] = request.headers.get("X-VS-Token")
        return httpx.Response(200, json={"category": "SPAM", "confidence": 1.0})

    monkeypatch.setenv("VS_SERVICE_URL", "https://example.invalid")
    monkeypatch.setenv("VS_SERVICE_TOKEN", "secret-token")
    provider = RemoteProvider()
    provider._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://example.invalid",
        headers={"X-VS-Token": "secret-token"},
    )
    result = await provider.classify(_EMAIL)
    assert result.category == "SPAM"
    assert seen["token"] == "secret-token"
    await provider.aclose()


def test_remote_provider_needs_a_url(monkeypatch):
    monkeypatch.delenv("VS_SERVICE_URL", raising=False)
    with pytest.raises(RuntimeError, match="VS_SERVICE_URL"):
        RemoteProvider()
