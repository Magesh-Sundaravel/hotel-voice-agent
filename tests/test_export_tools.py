"""Tests for the ElevenLabs tool config export."""

from typing import Any

from src.voice.export_tools import export_tools

BASE = "https://hotel.ngrok.app"


def _by_name() -> dict[str, dict[str, Any]]:
    return {t["name"]: t for t in export_tools(BASE, "sec_123")}


def test_every_registry_tool_is_exported_as_a_webhook() -> None:
    """One config per tool, each posting to its own URL with the secret."""
    tools = _by_name()

    assert set(tools) == {
        "check_availability",
        "get_rates",
        "get_guest_info",
        "create_booking",
        "get_booking",
        "modify_booking",
        "cancel_booking",
        "send_confirmation_email",
        "take_message",
        "send_followup_email",
    }
    for name, tool in tools.items():
        api = tool["api_schema"]
        assert tool["type"] == "webhook"
        assert api["url"] == f"{BASE}/tools/{name}"
        assert api["method"] == "POST"
        assert api["request_headers"] == {"X-Webhook-Secret": {"secret_id": "sec_123"}}
        assert tool["response_timeout_secs"] == 5
        assert len(tool["description"]) > 100


def test_call_facts_are_bound_to_system_variables() -> None:
    """The model never fills call_id or caller_phone."""
    for tool in _by_name().values():
        body = tool["api_schema"]["request_body_schema"]
        assert body["properties"]["call_id"] == {
            "type": "string",
            "dynamic_variable": "system__conversation_id",
        }
        assert body["properties"]["caller_phone"] == {
            "type": "string",
            "dynamic_variable": "system__caller_id",
        }
        assert "call_id" in body["required"]


def test_model_parameters_are_flat_and_described() -> None:
    """Optional fields lose anyOf, dates become strings, enums are kept."""
    body = _by_name()["create_booking"]["api_schema"]["request_body_schema"]
    props = body["properties"]

    assert props["check_in"]["type"] == "string"
    assert "YYYY-MM-DD" in props["check_in"]["description"]
    assert props["adults"]["type"] == "integer"
    assert props["email"]["type"] == "string"
    assert props["language"]["enum"] == ["it", "en"]
    assert "email" not in body["required"] and "adults" in body["required"]
    for prop in props.values():
        assert "anyOf" not in prop and "default" not in prop and "title" not in prop


def test_a_tool_without_arguments_still_has_its_call_facts() -> None:
    """get_guest_info takes nothing from the model."""
    body = _by_name()["get_guest_info"]["api_schema"]["request_body_schema"]

    assert set(body["properties"]) == {"call_id", "caller_phone"}
