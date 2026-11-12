"""Minimal DeepSeek Chat Completions client. Never logs the API key."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

API_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-flash"
SHANGHAI = ZoneInfo("Asia/Shanghai")

# Official prices at https://api-docs.deepseek.com/zh-cn/quick_start/pricing
# Unit: CNY per million tokens. Idle = half of peak.
# Peak: Monday-Friday 09:00-12:00 and 14:00-18:00 Asia/Shanghai, excluding PRC holidays.
FLASH_PRICES = {
    "idle": {"cache_hit": Decimal("0.02"), "cache_miss": Decimal("1"), "output": Decimal("4")},
    "peak": {"cache_hit": Decimal("0.04"), "cache_miss": Decimal("2"), "output": Decimal("8")},
}


def tariff_window(when: datetime | None = None) -> str:
    now = when.astimezone(SHANGHAI) if when is not None else datetime.now(SHANGHAI)
    if now.weekday() >= 5:
        return "idle"
    minutes = now.hour * 60 + now.minute
    if 9 * 60 <= minutes < 12 * 60 or 14 * 60 <= minutes < 18 * 60:
        return "peak"
    return "idle"


def estimate_cny(
    *,
    prompt_tokens: int,
    completion_tokens: int,
    cache_hit_tokens: int = 0,
    window: str | None = None,
    when: datetime | None = None,
) -> tuple[Decimal, str, dict]:
    window = window or tariff_window(when)
    prices = FLASH_PRICES[window]
    hit = max(0, int(cache_hit_tokens))
    miss = max(0, int(prompt_tokens) - hit)
    output = max(0, int(completion_tokens))
    cost = (
        Decimal(hit) * prices["cache_hit"]
        + Decimal(miss) * prices["cache_miss"]
        + Decimal(output) * prices["output"]
    ) / Decimal(1_000_000)
    exact = cost.quantize(Decimal("0.0000001"))
    return exact, window, {"cache_hit": hit, "cache_miss": miss, "output": output, "prices_cny_per_mtoken": {k: str(v) for k, v in prices.items()}}


def format_cny(amount: Decimal) -> str:
    if amount == 0:
        return "0.00"
    two = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if amount > 0 and two == 0:
        # Keep enough digits so a real paid call is not recorded as 0.00.
        text = format(amount.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP), "f")
        return text.rstrip("0").rstrip(".") if "." in text else text
    return f"{two:.2f}"


def _post(payload: dict, timeout: int = 180) -> dict:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY is not set in the environment")
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        API_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        # Never include headers (they may contain the key).
        raise RuntimeError(f"DeepSeek HTTP {exc.code}: {detail}") from None
    return json.loads(raw.decode("utf-8"))


def chat_json(*, messages: list[dict], model: str = DEFAULT_MODEL, timeout: int = 180) -> dict:
    """One chat completion that must return a JSON object. Records usage."""
    started = datetime.now(SHANGHAI)
    base_payload = {
        "model": model,
        "messages": messages,
        "response_format": {"type": "json_object"},
        "temperature": 0,
    }
    # Prefer non-thinking mode to keep cost and latency down.
    payload = dict(base_payload)
    payload["thinking"] = {"type": "disabled"}
    try:
        data = _post(payload, timeout=timeout)
        thinking_mode = "disabled"
    except RuntimeError as exc:
        message = str(exc).lower()
        if "thinking" not in message and "400" not in message:
            raise
        data = _post(base_payload, timeout=timeout)
        thinking_mode = "api_default"

    if data.get("error"):
        raise RuntimeError(f"DeepSeek error object: {data['error']}")
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("DeepSeek returned no choices")
    content = (choices[0].get("message") or {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("DeepSeek returned empty content")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"DeepSeek content was not JSON: {exc}") from None
    if not isinstance(parsed, dict):
        raise RuntimeError("DeepSeek JSON was not an object")

    usage = data.get("usage") or {}
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    cache_hit = int(usage.get("prompt_cache_hit_tokens") or 0)
    if prompt_tokens <= 0 and completion_tokens <= 0:
        raise RuntimeError("DeepSeek usage had no token counts; refusing to invent them")
    exact, window, breakdown = estimate_cny(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cache_hit_tokens=cache_hit,
        when=started,
    )
    return {
        "parsed": parsed,
        "model": data.get("model") or model,
        "requested_model": model,
        "thinking_mode": thinking_mode,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": int(usage.get("total_tokens") or (prompt_tokens + completion_tokens)),
        "prompt_cache_hit_tokens": cache_hit,
        "prompt_cache_miss_tokens": int(usage.get("prompt_cache_miss_tokens") or max(prompt_tokens - cache_hit, 0)),
        "estimated_cny_exact": format(exact, "f"),
        "estimated_cny": format_cny(exact),
        "tariff_window": window,
        "tariff": breakdown,
        "started_at": started.isoformat(timespec="seconds"),
        "pricing_source": "https://api-docs.deepseek.com/zh-cn/quick_start/pricing",
        "id": data.get("id"),
    }
