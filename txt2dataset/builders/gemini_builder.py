import asyncio
import os
from ..utils.builder_rate_limits import process_payloads
from ..utils.utils import pydantic_to_json_schema
import json


class GeminiAPIBuilder:
    def __init__(self, api_key=None):
        if api_key:
            self.api_key = api_key
        else:
            try:
                self.api_key = os.environ["GEMINI_API_KEY"]
            except Exception:
                raise ValueError("No api key specified and none found in environment: GEMINI_API_KEY.")
            
        self.input_tokens_used_session = 0
        self.output_tokens_used_session = 0

    def build(self, prompt, schema, model, entries, rpm, tpm, rpm_threshold=0.75, tpm_threshold=0.75):
        """Entries is list of {id,context}"""
        if not entries:
            raise ValueError("entries is empty")


        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        payloads = [
            {
                "contents": [
                    {"role": "user", "parts": [{"text": f"{prompt}: {entry['context']}"}]}
                ],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "responseSchema": pydantic_to_json_schema(schema),
                },
            }
            for entry in entries
        ]

        responses =  asyncio.run(
            process_payloads(
                payloads=payloads,
                entries=entries,
                endpoint=endpoint,
                api_key=self.api_key,
                rpm=rpm,
                tpm=tpm,
                rpm_threshold=rpm_threshold,
                tpm_threshold=tpm_threshold,
            )
        )

        results = []
        for r in responses:
            if "result" not in r:
                results.append({"id": r["id"], "error": r.get("error")})
                continue

            parsed = json.loads(r["result"])

            # Update session token counts
            usage = parsed.get("usageMetadata", {})
            self.input_tokens_used_session += usage.get("promptTokenCount", 0)
            self.output_tokens_used_session += usage.get("candidatesTokenCount", 0)

            text = parsed["candidates"][0]["content"]["parts"][0]["text"]
            structured = json.loads(text)

            if not structured.get("info_found") or not structured.get("data"):
                results.append({"id": r["id"], "info_found": False})
                continue

            for dividend in structured["data"]:
                results.append({"id": r["id"], **dividend})

        return results