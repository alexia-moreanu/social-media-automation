"""One place where this project talks to Claude.

Written after two real failures:
  - a long planning prompt spent its whole token budget on extended thinking and
    returned no text at all, so JSON parsing blew up with a confusing error;
  - server-side web search can pause a turn, which needs the conversation continued
    rather than treated as a failure.
"""

import base64
import io
import json
import os

import requests
from PIL import Image


class BillingError(RuntimeError):
    """The API refused everything — out of credit, or the key is invalid.

    Worth its own type: retrying or skipping the file is pointless, and a caller that
    treats it as "bad input" will silently mark good files as unusable.
    """

MODEL = "claude-sonnet-5"
API = "https://api.anthropic.com/v1/messages"
MAX_IMAGE_EDGE = 1400


def encode_image(image_path) -> dict:
    """An image block, downscaled — full-size iPhone photos exceed the request limit."""
    image = Image.open(image_path).convert("RGB")
    if max(image.size) > MAX_IMAGE_EDGE:
        ratio = MAX_IMAGE_EDGE / max(image.size)
        image = image.resize((round(image.width * ratio), round(image.height * ratio)),
                             Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return {"type": "image", "source": {
        "type": "base64", "media_type": "image/jpeg",
        "data": base64.standard_b64encode(buffer.getvalue()).decode(),
    }}


def call(content, *, max_tokens=8000, tools=None, thinking=False, timeout=300):
    """Send one message and return the text. Continues the turn if the server pauses it."""
    messages = [{"role": "user", "content": content}]
    text_parts = []

    for _ in range(4):  # a paused turn may need continuing more than once
        body = {"model": MODEL, "max_tokens": max_tokens, "messages": messages}
        if tools:
            body["tools"] = tools
        if not thinking:
            # Long prompts otherwise spend the entire budget thinking and return nothing.
            body["thinking"] = {"type": "disabled"}

        response = requests.post(
            API,
            headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                     "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json=body, timeout=timeout,
        )
        if response.status_code == 400:
            message = response.json().get("error", {}).get("message", "")
            if "credit balance" in message.lower() or "billing" in message.lower():
                raise BillingError(message)
        if response.status_code in (401, 403, 429):
            raise BillingError(
                f"{response.status_code}: "
                f"{response.json().get('error', {}).get('message', response.text[:200])}"
            )
        response.raise_for_status()
        payload = response.json()

        text_parts += [b["text"] for b in payload["content"] if b["type"] == "text"]
        stop = payload.get("stop_reason")

        if stop == "pause_turn":
            messages.append({"role": "assistant", "content": payload["content"]})
            continue
        if stop == "max_tokens":
            raise RuntimeError(
                f"Claude hit the {max_tokens}-token limit before finishing. "
                "Raise max_tokens or ask for less in one call."
            )
        break

    return "".join(text_parts).strip()


def call_json(content, attempts=2, **kwargs):
    """Same, but parse the reply as JSON, tolerating code fences and stray prose.

    Retries once: an occasional reply comes back truncated or with stray prose, and
    losing a whole draft to that is not worth it.
    """
    last_error = None
    for attempt in range(attempts):
        text = call(content, **kwargs)
        if not text:
            last_error = RuntimeError("Claude returned no text.")
            continue
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            last_error = RuntimeError(f"Expected JSON, got: {text[:200]}")
            continue
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError as error:
            last_error = RuntimeError(f"Malformed JSON ({error}): {text[:200]}")
    raise last_error
