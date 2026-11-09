"""Print the ElevenLabs webhook tool configs from the registry, to paste in the dashboard.

    uv run python -m src.voice.export_tools --base-url https://<ngrok-domain> \\
        --secret-id <elevenlabs-secret-id>

Nothing is sent to ElevenLabs. Field names follow docs/external/elevenlabs.md,
section 2; see docs/setup-elevenlabs-telnyx.md for what to check on first paste.
"""

import argparse
import json
from typing import Any

from src.agent.registry import build_registry
from src.db.seed import seed_repository
from src.tools.context import CallContext

# ElevenLabs' minimum webhook timeout; the backend enforces the real 1.5 s budget.
TIMEOUT_S = 5

# Filled by ElevenLabs from the call, never by the model.
_CALL_FACTS = {
    "call_id": {"type": "string", "dynamic_variable": "system__conversation_id"},
    "caller_phone": {"type": "string", "dynamic_variable": "system__caller_id"},
}


def _flat(prop: dict[str, Any]) -> dict[str, Any]:
    """One Pydantic property as an ElevenLabs body property: type, description, enum."""
    types = [p.get("type") for p in prop.get("anyOf", [prop])]
    out: dict[str, Any] = {
        "type": next(t for t in types if t != "null"),
        "description": prop["description"],
    }
    enum = next((p["enum"] for p in prop.get("anyOf", [prop]) if "enum" in p), None)
    if enum:
        out["enum"] = enum
    return out


def export_tools(base_url: str, secret_id: str) -> list[dict[str, Any]]:
    """Build one webhook tool config per registry tool.

    Args:
        base_url: Public URL of the backend (the ngrok static domain).
        secret_id: ElevenLabs workspace secret id holding WEBHOOK_SECRET.

    Returns:
        The configs, in registry order.
    """
    repo = seed_repository()
    registry = build_registry(repo, repo, CallContext(call_id="export"))
    configs = []
    for name, tool in registry.items():
        schema = tool.input_model.model_json_schema()
        props = {k: _flat(v) for k, v in schema.get("properties", {}).items()}
        configs.append(
            {
                "type": "webhook",
                "name": name,
                "description": tool.description,
                "response_timeout_secs": TIMEOUT_S,
                "api_schema": {
                    "url": f"{base_url.rstrip('/')}/tools/{name}",
                    "method": "POST",
                    "request_headers": {"X-Webhook-Secret": {"secret_id": secret_id}},
                    "request_body_schema": {
                        "type": "object",
                        "properties": {**props, **_CALL_FACTS},
                        "required": [*schema.get("required", []), "call_id"],
                    },
                },
            }
        )
    return configs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Print ElevenLabs tool configs.")
    parser.add_argument("--base-url", required=True, help="e.g. https://x.ngrok.app")
    parser.add_argument("--secret-id", required=True, help="ElevenLabs secret id")
    args = parser.parse_args()
    print(json.dumps(export_tools(args.base_url, args.secret_id), indent=2))
