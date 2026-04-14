import asyncio
import os
from ..utils.builder_rate_limits import process_payloads, GEMINI_CONFIG
from ..utils.utils import pydantic_to_json_schema
from ..utils.visualize import visualize
from ..config import CONFIG, build_spot_check_prompt
import json
import random


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
        """Entries is list of {id, context}"""
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

        responses = asyncio.run(
            process_payloads(
                payloads=payloads,
                entries=entries,
                endpoint=endpoint,
                api_key=self.api_key,
                provider_config=GEMINI_CONFIG,
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

                usage = parsed.get("usageMetadata", {})
                self.input_tokens_used_session += usage.get("promptTokenCount", 0)
                self.output_tokens_used_session += usage.get("candidatesTokenCount", 0)

                text = parsed["candidates"][0]["content"]["parts"][0]["text"]
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

        check_schema = CONFIG.get_spot_check_schema()
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

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
                    "contents": [
                        {"role": "user", "parts": [{"text": check_prompt}]}
                    ],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "responseSchema": check_schema,
                    },
                }
            )

        responses = asyncio.run(
            process_payloads(
                payloads=payloads,
                entries=spotcheck_entries,
                endpoint=endpoint,
                api_key=self.api_key,
                provider_config=GEMINI_CONFIG,
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
                usage = parsed.get("usageMetadata", {})
                self.input_tokens_used_session += usage.get("promptTokenCount", 0)
                self.output_tokens_used_session += usage.get("candidatesTokenCount", 0)

                text = parsed["candidates"][0]["content"]["parts"][0]["text"]
                check = json.loads(text)

                row_id = sampled_ids[i]

                all_fields = []
                for c in check:
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