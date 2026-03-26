import os
import csv
import json
import time
import urllib.request
from ..utils.utils import pydantic_to_json_schema


class GeminiAPIBatchBuilder:
    def __init__(self, api_key=None):
        if api_key:
            self.api_key = api_key
        else:
            try:
                self.api_key = os.environ["GEMINI_API_KEY"]
            except Exception:
                raise ValueError("No api key specified and none found in environment: GEMINI_API_KEY.")

        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

    def _get(self, path: str) -> dict:
        url = f"{self.base_url}/{path}?key={self.api_key}"
        with urllib.request.urlopen(url) as resp:
            return json.loads(resp.read().decode())

    def _post(self, path: str, body: dict) -> dict:
        url = f"{self.base_url}/{path}?key={self.api_key}"
        data = json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            raise Exception(f"HTTP {e.code}: {e.read().decode()}") from e

    def submit_job(self, prompt, schema, model, entries) -> str:
        if not model.startswith("models/"):
            model = f"models/{model}"

        schema_payload = pydantic_to_json_schema(schema)
        display_name = f"batch_{int(time.time())}"

        requests = [
            {
                "request": {
                    "contents": [
                        {"role": "user", "parts": [{"text": f"{prompt}: {entry['context']}"}]}
                    ],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "responseSchema": schema_payload,
                    },
                }
            }
            for entry in entries
        ]

        body = {
            "batch": {
                "model": model,
                "displayName": display_name,
                "inputConfig": {
                    "requests": {
                        "requests": requests
                    }
                },
            }
        }

        resp = self._post(f"{model}:batchGenerateContent", body)
        return resp["name"]

    def get_job_status(self, job_name: str) -> dict:
        status = self._get(job_name)
        return {
            "state": status.get("state"),
            "done": status.get("done", False),
            "stats": status.get("metadata", {}).get("batchStats"),
            "created": status.get("metadata", {}).get("createTime"),
            "ended": status.get("metadata", {}).get("endTime"),
        }

    def list_jobs(self) -> list:
        return self._get("batches").get("operations", [])

    def download_job(self, job_name: str, output_path: str) -> str:
        status = self._get(job_name)

        if not status.get("done", False):
            state = status.get("metadata", {}).get("state", "UNKNOWN")
            raise ValueError(f"Job not complete, current state: {state}")

        inlined = (
            status.get("response", {})
            .get("inlinedResponses", {})
            .get("inlinedResponses", [])
        )

        results = []
        for i, item in enumerate(inlined):
            if "error" in item:
                results.append({"index": i, "error": item["error"]})
                continue
            text = item["response"]["candidates"][0]["content"]["parts"][0]["text"]
            structured = json.loads(text)
            if not structured.get("info_found") or not structured.get("data"):
                results.append({"index": i, "info_found": False})
                continue
            for row in structured["data"]:
                results.append({"index": i, **row})

        if not results:
            raise ValueError("No results to write.")

        # Collect all keys across all rows
        fieldnames = list(dict.fromkeys(k for row in results for k in row.keys()))

        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore", restval="")
            writer.writeheader()
            writer.writerows(results)

        return output_path