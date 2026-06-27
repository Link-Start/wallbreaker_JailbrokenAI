from __future__ import annotations

import base64
import binascii
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import httpx

from ..agent.messages import Message, StopEvent, StreamEvent, TextDelta
from ..config import Endpoint
from .base import Provider, ProviderError
from .openai_provider import _messages_to_wire

_MIME_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}


@dataclass
class ImageResult:
    """One image-generation turn: decoded images plus any accompanying text."""

    images: list[tuple[str, bytes]] = field(default_factory=list)  # (mime, raw bytes)
    data_urls: list[str] = field(default_factory=list)  # original data: URLs (for the vision judge)
    text: str = ""  # any prose / refusal the model returned alongside (or instead of) images
    reasoning: str = ""  # the model's reasoning/CoT, if exposed

    @property
    def refused(self) -> bool:
        return not self.images

    def ext_for(self, index: int) -> str:
        mime = self.images[index][0] if index < len(self.images) else "image/png"
        return _MIME_EXT.get(mime, "png")


def ext_for_mime(mime: str) -> str:
    return _MIME_EXT.get(mime, "png")


def _decode_data_url(url: str) -> tuple[str, bytes] | None:
    """Decode a data: URL or a bare base64 blob into (mime, bytes)."""
    mime = "image/png"
    payload = url
    if url.startswith("data:"):
        head, _, payload = url.partition(",")
        if ";" in head:
            mime = head[5:].split(";", 1)[0] or mime
    try:
        return mime, base64.b64decode(payload, validate=False)
    except (binascii.Error, ValueError):
        return None


def _extract_images(data: dict) -> tuple[list[tuple[str, bytes]], list[str], str]:
    """Pull generated images out of an OpenRouter response, whichever shape it uses.

    Two shapes seen in the wild:
      - chat-completions: choices[].message.images[].image_url.url  (data: URLs)
      - images endpoint:  data[].b64_json                           (bare base64)
    """
    images: list[tuple[str, bytes]] = []
    data_urls: list[str] = []
    texts: list[str] = []

    for choice in data.get("choices") or []:
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, str) and content:
            texts.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text" and part.get("text"):
                    texts.append(str(part["text"]))
        for img in message.get("images") or []:
            url = ""
            if isinstance(img, dict):
                url = (img.get("image_url") or {}).get("url", "") if isinstance(img.get("image_url"), dict) else img.get("url", "")
            elif isinstance(img, str):
                url = img
            if not url:
                continue
            decoded = _decode_data_url(url)
            if decoded:
                images.append(decoded)
                data_urls.append(url if url.startswith("data:") else f"data:{decoded[0]};base64,{url}")

    for item in data.get("data") or []:
        if not isinstance(item, dict):
            continue
        b64 = item.get("b64_json") or item.get("image")
        if b64:
            decoded = _decode_data_url(b64)
            if decoded:
                images.append(decoded)
                data_urls.append(f"data:{decoded[0]};base64,{b64}")
        elif item.get("url"):
            data_urls.append(str(item["url"]))

    return images, data_urls, "\n".join(t for t in texts if t).strip()


def _extract_reasoning(data: dict) -> str:
    parts: list[str] = []
    for choice in data.get("choices") or []:
        message = choice.get("message") or {}
        reasoning = message.get("reasoning")
        if isinstance(reasoning, str) and reasoning:
            parts.append(reasoning)
        for det in message.get("reasoning_details") or []:
            if isinstance(det, dict) and det.get("text"):
                parts.append(str(det["text"]))
    return "\n".join(parts).strip()


class OpenRouterImageProvider(Provider):
    """Targets an OpenRouter image-generation model through the chat-completions API.

    Image models answer the same /chat/completions endpoint but need
    `modalities: ["image", "text"]`; the picture comes back base64-encoded in
    `choices[0].message.images[].image_url.url`. We run non-streaming because the
    payload is one big blob, then hand the bytes to query_image_target to save + grade.
    """

    async def generate(
        self,
        messages: list[Message],
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> ImageResult:
        url = f"{self.endpoint.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.endpoint.require_key()}",
            "Content-Type": "application/json",
        }
        payload: dict = {
            "model": self.endpoint.model,
            "messages": _messages_to_wire(messages, system),
            "modalities": ["image", "text"],
            "max_tokens": max_tokens,
            "stream": False,
        }
        if getattr(self.endpoint, "reasoning", False):
            payload["reasoning"] = {"enabled": True}
        if getattr(self.endpoint, "provider", ()):
            payload["provider"] = {
                "order": list(self.endpoint.provider),
                "allow_fallbacks": False,
            }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code >= 400:
                    body = resp.text
                    raise ProviderError(f"HTTP {resp.status_code} from {url}: {body[:400]}")
                data = resp.json()
        except httpx.HTTPError as exc:
            raise ProviderError(f"network error from {url}: {exc!r}") from exc

        images, data_urls, text = _extract_images(data)
        return ImageResult(
            images=images, data_urls=data_urls, text=text,
            reasoning=_extract_reasoning(data),
        )

    async def stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float | None = None,
    ) -> AsyncIterator[StreamEvent]:
        result = await self.generate(messages, system=system, max_tokens=max_tokens)
        summary = result.text or ""
        if result.images:
            note = f"[{len(result.images)} image(s) generated]"
            summary = f"{note}\n{summary}".strip()
        elif not summary:
            summary = "[no image and no text returned]"
        yield TextDelta(summary)
        yield StopEvent("end_turn")


def _vision_wire(text: str, image_urls: list[str]) -> list[dict]:
    content: list[dict] = [{"type": "text", "text": text}]
    for url in image_urls:
        content.append({"type": "image_url", "image_url": {"url": url}})
    return [{"role": "user", "content": content}]


async def vision_complete(
    endpoint: Endpoint,
    text: str,
    image_urls: list[str],
    system: str | None = None,
    max_tokens: int = 512,
    timeout: float = 120.0,
) -> str:
    """Send text + image(s) to a vision-capable OpenAI-protocol model, return its text.

    The core message types are text-only, so the multimodal body is built here instead
    of widening Message/Block. Used by the image judge to look at a generated picture.
    """
    url = f"{endpoint.base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {endpoint.require_key()}",
        "Content-Type": "application/json",
    }
    messages = _vision_wire(text, image_urls)
    if system:
        messages.insert(0, {"role": "system", "content": system})
    payload = {
        "model": endpoint.model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code >= 400:
                raise ProviderError(f"HTTP {resp.status_code} from {url}: {resp.text[:400]}")
            data = resp.json()
    except httpx.HTTPError as exc:
        raise ProviderError(f"network error from {url}: {exc!r}") from exc
    choices = data.get("choices") or []
    if not choices:
        return ""
    content = (choices[0].get("message") or {}).get("content", "")
    if isinstance(content, list):
        return "".join(
            str(p.get("text", "")) for p in content if isinstance(p, dict)
        ).strip()
    return str(content or "").strip()
