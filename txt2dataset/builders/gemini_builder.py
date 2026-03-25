import asyncio
import os
from ..utils.builder_rate_limits import process_payloads
from ..utils.utils import pydantic_to_json_schema
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

        return results

    def spotcheck(self, prompt, schema, model, entries, results, sample_size, rpm, tpm, rpm_threshold=0.75, tpm_threshold=0.75):
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
                "correct": {"type": "boolean"},
                "desc": {"type": "string"},
            },
            "required": ["correct"],
        }

        extraction_schema = pydantic_to_json_schema(schema)
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

        spotcheck_entries = []
        payloads = []
        for row_id in sampled_ids:
            context = entries_by_id.get(row_id, "")
            rows = grouped_results.get(row_id, [])
            rows_for_check = [{k: v for k, v in row.items() if k != "id"} for row in rows]
            rows_json = json.dumps(rows_for_check, ensure_ascii=False)
            schema_json = json.dumps(extraction_schema, ensure_ascii=False)
            check_prompt = (
                "You are reviewing extracted results for one source document.\n"
                #f"Original extraction prompt: {prompt}\n"
                #f"Expected extraction schema: {schema_json}\n"
                f"Source text:\n{context}\n\n"
                f"Extracted rows for this source:\n{rows_json}\n\n"
                "Return JSON with:\n"
                "- correct: true if the extracted rows are overall correct.\n"
                "- overall correct is if the extracted information is good enough, without glaring errors such as massive hallucinations.\n" \
                "- example: if model infers correct legal code from snippet that is not a hallucination. if model makes up a legal code that is."
            )

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
                rpm=rpm,
                tpm=tpm,
                rpm_threshold=rpm_threshold,
                tpm_threshold=tpm_threshold,
            )
        )

        spotcheck_results = []
        for i, r in enumerate(responses):
            if r is None or "result" not in r:
                continue

            parsed = json.loads(r["result"])
            usage = parsed.get("usageMetadata", {})
            self.input_tokens_used_session += usage.get("promptTokenCount", 0)
            self.output_tokens_used_session += usage.get("candidatesTokenCount", 0)

            text = parsed["candidates"][0]["content"]["parts"][0]["text"]
            check = json.loads(text)

            item = {
                "id": sampled_ids[i],
                "correct": check["correct"],
                "desc": "",
            }
            if not check["correct"]:
                item["desc"] = check.get("desc", "")

            spotcheck_results.append(item)

        return spotcheck_results
