import asyncio
import os
from ..utils.builder_rate_limits import process_payloads, ProviderConfig
from ..utils.utils import pydantic_to_json_schema
from ..utils.visualize import visualize
from ..config import CONFIG, build_spot_check_prompt
import json
import random


def _openai_text_extractor(p):
    return next(
        (m["content"] for m in reversed(p["messages"]) if m.get("role") == "user"),
        "",
    )


class OpenAIAPIBuilder:
    def __init__(self, api_key=None, endpoint=None, auth_header="Authorization"):
        """
        Args:
            api_key: API key. Falls back to OPENAI_API_KEY env var if not provided.
            endpoint: Full endpoint URL. Defaults to OpenAI's chat completions endpoint.
                      For Azure, pass something like:
                      "https://{resource}.cognitiveservices.azure.com/openai/deployments/{deployment}/chat/completions?api-version=2024-12-01-preview"
            auth_header: How the API key is sent in headers.
                         "Authorization" (default) -> sends "Authorization: Bearer {key}" (OpenAI standard)
                         "api-key" -> sends "api-key: {key}" (Azure style)
                         Any other string -> sends "{auth_header}: {key}" as a plain header
        """
        if api_key:
            self.api_key = api_key
        else:
            try:
                self.api_key = os.environ["OPENAI_API_KEY"]
            except Exception:
                raise ValueError("No api key specified and none found in environment: OPENAI_API_KEY.")

        self.endpoint = endpoint or "https://api.openai.com/v1/chat/completions"
        self.auth_header = auth_header

        if self.auth_header == "Authorization":
            auth_mode = "bearer"
        else:
            auth_mode = ("header_key", self.auth_header)

        self._provider_config = ProviderConfig(
            auth_mode=auth_mode,
            text_extractor=_openai_text_extractor,
        )

        self.input_tokens_used_session = 0
        self.output_tokens_used_session = 0

    def _make_schema_config(self, schema, name="extraction_schema"):
        """Build the OpenAI response_format block for structured output."""
        json_schema = pydantic_to_json_schema(schema) if not isinstance(schema, dict) else schema
        self._add_additional_properties_false(json_schema)
        return {
            "type": "json_schema",
            "json_schema": {
                "name": name,
                "strict": True,
                "schema": json_schema,
            },
        }

    @staticmethod
    def _add_additional_properties_false(schema):
        """Recursively add additionalProperties: false and ensure all properties
        are listed in required. OpenAI strict mode demands both on every object."""
        if not isinstance(schema, dict):
            return
        if schema.get("type") == "object":
            schema["additionalProperties"] = False
            if "properties" in schema:
                schema["required"] = list(schema["properties"].keys())
        for value in schema.values():
            if isinstance(value, dict):
                OpenAIAPIBuilder._add_additional_properties_false(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        OpenAIAPIBuilder._add_additional_properties_false(item)

    def build(self, prompt, schema, model, entries, rpm, tpm, rpm_threshold=0.75, tpm_threshold=0.75):
        """Entries is list of {id, context}"""
        if not entries:
            raise ValueError("entries is empty")

        response_format = self._make_schema_config(schema)

        payloads = [
            {
                "model": model,
                "messages": [
                    {"role": "user", "content": f"{prompt}: {entry['context']}"}
                ],
                "response_format": response_format,
            }
            for entry in entries
        ]

        responses = asyncio.run(
            process_payloads(
                payloads=payloads,
                entries=entries,
                endpoint=self.endpoint,
                api_key=self.api_key,
                provider_config=self._provider_config,
                rpm=rpm,
                tpm=tpm,
                rpm_threshold=rpm_threshold,
                tpm_threshold=tpm_threshold,
            )
        )

        results = []
        errors = []
        for r in responses:
            try:
                if r is None or "result" not in r:
                    raise ValueError("None response")

                parsed = json.loads(r["result"])

                usage = parsed.get("usage", {})
                self.input_tokens_used_session += usage.get("prompt_tokens", 0)
                self.output_tokens_used_session += usage.get("completion_tokens", 0)

                text = parsed["choices"][0]["message"]["content"]

                refusal = parsed["choices"][0]["message"].get("refusal")
                if refusal:
                    errors.append({"id": r["id"], "error": f"Model refused: {refusal}"})
                    continue

                structured = json.loads(text)

                if not structured.get("info_found") or not structured.get("data"):
                    continue

                for item in structured["data"]:
                    results.append({"id": r["id"], **item})

            except Exception as e:
                errors.append({"id": r.get("id", "unknown") if r else "unknown", "error": str(e)})

        return results, errors

    def spotcheck(self, schema, model, entries, results, sample_size, rpm, tpm, rpm_threshold=0.75, tpm_threshold=0.75, return_details=False):
        grouped_results = {}
        for row in results:
            row_id = row.get("id")
            grouped_results.setdefault(row_id, []).append(row)

        result_ids = list(grouped_results.keys())
        sample_size = min(sample_size, len(result_ids))
        if sample_size == 0:
            return []

        sampled_ids = random.sample(result_ids, sample_size)
        entries_by_id = {entry["id"]: entry["context"] for entry in entries}

        check_schema = {
            "type": "object",
            "properties": {
                "rows": CONFIG.get_spot_check_schema()
            },
            "required": ["rows"],
            "additionalProperties": False,
        }
        response_format = self._make_schema_config(check_schema, name="spotcheck_schema")

        spotcheck_entries = []
        payloads = []
        for row_id in sampled_ids:
            context = entries_by_id.get(row_id, "")
            rows = grouped_results.get(row_id, [])
            rows_for_check = [{"row_index": i, **{k: v for k, v in row.items() if k != "id"}} for i, row in enumerate(rows)]
            rows_json = json.dumps(rows_for_check, ensure_ascii=False)
            check_prompt = build_spot_check_prompt(context=context, rows_json=rows_json)

            spotcheck_entries.append({"id": row_id, "context": context})
            payloads.append(
                {
                    "model": model,
                    "messages": [
                        {"role": "user", "content": check_prompt}
                    ],
                    "response_format": response_format,
                }
            )

        responses = asyncio.run(
            process_payloads(
                payloads=payloads,
                entries=spotcheck_entries,
                endpoint=self.endpoint,
                api_key=self.api_key,
                provider_config=self._provider_config,
                rpm=rpm,
                tpm=tpm,
                rpm_threshold=rpm_threshold,
                tpm_threshold=tpm_threshold,
            )
        )

        spotcheck_results = []
        errors = []
        for i, r in enumerate(responses):
            try:
                if r is None or "result" not in r:
                    continue

                parsed = json.loads(r["result"])
                usage = parsed.get("usage", {})
                self.input_tokens_used_session += usage.get("prompt_tokens", 0)
                self.output_tokens_used_session += usage.get("completion_tokens", 0)

                text = parsed["choices"][0]["message"]["content"]
                check = json.loads(text)

                row_id = sampled_ids[i]

                all_fields = []
                for c in check["rows"]:
                    all_fields.extend(c.get("fields", []))

                item = {
                    "id": row_id,
                    "fields": all_fields,
                }

                if return_details:
                    extracted_rows = grouped_results.get(row_id, [])
                    item["extracted_rows"] = [{k: v for k, v in row.items() if k != "id"} for row in extracted_rows]
                    item["context"] = entries_by_id.get(row_id, "")

                spotcheck_results.append(item)
            except Exception as e:
                errors.append({"id": r.get("id", "unknown") if r else "unknown", "error": str(e)})
        
        return spotcheck_results

    def spotcheck_visualize(self, schema, model, entries, results, sample_size, rpm, tpm, rpm_threshold=0.75, tpm_threshold=0.75, port=8000):
        """Run spotcheck with details, then launch a local browser to inspect results."""
        spotcheck_results = self.spotcheck(
            schema=schema,
            model=model,
            entries=entries,
            results=results,
            sample_size=sample_size,
            rpm=rpm,
            tpm=tpm,
            rpm_threshold=rpm_threshold,
            tpm_threshold=tpm_threshold,
            return_details=True,
        )

        if not spotcheck_results:
            print("No spotcheck results to visualize.")
            return []

        visualize(spotcheck_results, port=port)
        return spotcheck_results