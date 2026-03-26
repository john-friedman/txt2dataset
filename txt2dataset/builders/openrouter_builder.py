import asyncio
import os
from ..utils.builder_rate_limits import process_payloads, OPENROUTER_CONFIG
from ..utils.utils import pydantic_to_json_schema
from ..utils.visualize import visualize
import json
import random


class OpenRouterAPIBuilder:
    def __init__(self, api_key=None):
        if api_key:
            self.api_key = api_key
        else:
            try:
                self.api_key = os.environ["OPENROUTER_API_KEY"]
            except Exception:
                raise ValueError(
                    "No api key specified and none found in environment: OPENROUTER_API_KEY."
                )

        self.input_tokens_used_session = 0
        self.output_tokens_used_session = 0

    def build(
        self,
        prompt,
        schema,
        model,
        entries,
        rpm,
        tpm,
        rpm_threshold=0.75,
        tpm_threshold=0.75,
    ):
        """Entries is list of {id, context}"""
        if not entries:
            raise ValueError("entries is empty")

        endpoint = "https://openrouter.ai/api/v1/chat/completions"
        json_schema = pydantic_to_json_schema(schema)

        payloads = [
            {
                "model": model,
                "messages": [
                    {"role": "user", "content": f"{prompt}: {entry['context']}"}
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "extraction_schema",
                        "strict": True,
                        "schema": json_schema,
                    },
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
                provider_config=OPENROUTER_CONFIG,
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
                structured = json.loads(text)

                if not structured.get("info_found") or not structured.get("data"):
                    continue

                for item in structured["data"]:
                    results.append({"id": r["id"], **item})

            except Exception as e:
                errors.append(
                    {
                        "id": r.get("id", "unknown") if r else "unknown",
                        "error": str(e),
                    }
                )

        return results, errors

    def spotcheck(
        self,
        prompt,
        schema,
        model,
        entries,
        results,
        sample_size,
        rpm,
        tpm,
        rpm_threshold=0.75,
        tpm_threshold=0.75,
        return_details=False,
    ):
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
                "verdict": {
                    "type": "string",
                    "enum": ["correct", "fabricated", "debatable"],
                },
                "desc": {"type": "string"},
            },
            "required": ["verdict", "desc"],
        }

        endpoint = "https://openrouter.ai/api/v1/chat/completions"

        spotcheck_entries = []
        payloads = []
        for row_id in sampled_ids:
            context = entries_by_id.get(row_id, "")
            rows = grouped_results.get(row_id, [])
            rows_for_check = [
                {k: v for k, v in row.items() if k != "id"} for row in rows
            ]
            rows_json = json.dumps(rows_for_check, ensure_ascii=False)
            check_prompt = (
                "Here is a source document and some data extracted from it.\n\n"
                f"Source text:\n{context}\n\n"
                f"Extracted data:\n{rows_json}\n\n"
                "Does the extracted data look right based on the document? "
                "Only flag it as wrong if something is egregiously wrong — meaning "
                "the extracted value cannot be found in or inferred from the source "
                "text with some generosity.\n\n"
                "Return JSON with:\n"
                "- verdict: 'correct', 'fabricated', or 'debatable'\n"
                "- desc: brief explanation\n"
            )

            spotcheck_entries.append({"id": row_id, "context": context})
            payloads.append(
                {
                    "model": model,
                    "messages": [{"role": "user", "content": check_prompt}],
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "spotcheck_schema",
                            "strict": True,
                            "schema": check_schema,
                        },
                    },
                }
            )

        responses = asyncio.run(
            process_payloads(
                payloads=payloads,
                entries=spotcheck_entries,
                endpoint=endpoint,
                api_key=self.api_key,
                provider_config=OPENROUTER_CONFIG,
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
            usage = parsed.get("usage", {})
            self.input_tokens_used_session += usage.get("prompt_tokens", 0)
            self.output_tokens_used_session += usage.get("completion_tokens", 0)

            text = parsed["choices"][0]["message"]["content"]
            check = json.loads(text)

            row_id = sampled_ids[i]

            item = {
                "id": row_id,
                "verdict": check["verdict"],
                "correct": check["verdict"] != "fabricated",
                "desc": check.get("desc", ""),
            }

            if return_details:
                extracted_rows = grouped_results.get(row_id, [])
                item["extracted_rows"] = [
                    {k: v for k, v in row.items() if k != "id"}
                    for row in extracted_rows
                ]
                item["context"] = entries_by_id.get(row_id, "")

            spotcheck_results.append(item)

        return spotcheck_results

    def spotcheck_visualize(
        self,
        prompt,
        schema,
        model,
        entries,
        results,
        sample_size,
        rpm,
        tpm,
        rpm_threshold=0.75,
        tpm_threshold=0.75,
        port=8000,
    ):
        """Run spotcheck with details, then launch a local browser to inspect results."""
        spotcheck_results = self.spotcheck(
            prompt=prompt,
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