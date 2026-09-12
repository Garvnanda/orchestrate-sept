import base64
import json
import os

import openai
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


class ExtractionError(Exception):
    pass

BASE_URL = os.environ.get("AGENTROUTER_BASE_URL", "https://agentrouter.org/v1")
USER_AGENT = os.environ.get("AGENTROUTER_USER_AGENT")

MODELS = {
    "extractor": "deepseek-v4-flash",
    "resolver": "deepseek-v4-flash",
    "verifier": "glm-5.3",
}

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"

_client = None
_openrouter_client = None


def get_client():
    global _client
    if _client is None:
        default_headers = {"User-Agent": USER_AGENT} if USER_AGENT else None
        _client = OpenAI(
            base_url=BASE_URL,
            api_key=os.environ["AGENTROUTER_API_KEY"],
            default_headers=default_headers,
        )
    return _client


def get_openrouter_client():
    global _openrouter_client
    if _openrouter_client is None:
        _openrouter_client = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=os.environ["OPENROUTER_API_KEY"])
    return _openrouter_client


def _image_data_url(image_path):
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:image/png;base64,{b64}"


def _chat_json(client, model, system_prompt, text_prompt, image_path=None, max_retries=1):
    if image_path:
        user_content = [
            {"type": "text", "text": text_prompt},
            {"type": "image_url", "image_url": {"url": _image_data_url(image_path)}},
        ]
    else:
        user_content = text_prompt

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    last_error = None
    for _ in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model, messages=messages, response_format={"type": "json_object"}, temperature=0,
            )
        except openai.APIError as e:
            last_error = e
            continue
        if not response.choices or response.choices[0].message.content is None:
            last_error = f"empty response (finish_reason={getattr(response.choices[0], 'finish_reason', None) if response.choices else 'no choices'})"
            continue
        text = response.choices[0].message.content
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            last_error = e
    raise ExtractionError(f"{model} call failed after {max_retries + 1} attempts: {last_error}")


def call_json(role, system_prompt, text_prompt, image_path=None, max_retries=1):
    return _chat_json(get_client(), MODELS[role], system_prompt, text_prompt, image_path, max_retries)


def call_json_openrouter(system_prompt, text_prompt, image_path=None, max_retries=1):
    return _chat_json(get_openrouter_client(), OPENROUTER_MODEL, system_prompt, text_prompt, image_path, max_retries)


def call_json_with_fallback(role, fallback_role, system_prompt, text_prompt, image_path=None):
    try:
        return call_json(role, system_prompt, text_prompt, image_path=image_path)
    except ExtractionError:
        return call_json(fallback_role, system_prompt, text_prompt, image_path=image_path)


def _self_check():
    result = call_json(
        "extractor",
        "Reply with strict JSON only.",
        'Reply with exactly this JSON object: {"ok": true}',
    )
    assert result == {"ok": True}, result
    print("OK: AgentRouter connectivity + JSON mode working via deepseek-v4-flash")


if __name__ == "__main__":
    _self_check()
