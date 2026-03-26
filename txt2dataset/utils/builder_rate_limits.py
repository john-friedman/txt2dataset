import time
from collections import deque
import aiohttp
from tqdm import tqdm
import asyncio
from ..utils.utils import estimate_tokens


class ProviderConfig:
    """Describes how to authenticate and extract text for a given provider."""

    def __init__(self, auth_mode, text_extractor):
        """
        Args:
            auth_mode: "query_param" or "bearer"
            text_extractor: callable(payload) -> str, returns the text to estimate tokens from
        """
        self.auth_mode = auth_mode
        self.text_extractor = text_extractor

    def get_auth(self, api_key):
        """Returns (params_dict, headers_dict) for the request."""
        if self.auth_mode == "query_param":
            return {"key": api_key}, {}
        elif self.auth_mode == "bearer":
            return {}, {"Authorization": f"Bearer {api_key}"}
        else:
            raise ValueError(f"Unknown auth_mode: {self.auth_mode}")

    def estimate_payload_tokens(self, payload):
        text = self.text_extractor(payload)
        return estimate_tokens(text)


# ----- Pre-built configs -----

GEMINI_CONFIG = ProviderConfig(
    auth_mode="query_param",
    text_extractor=lambda p: p["contents"][0]["parts"][0]["text"],
)

OPENROUTER_CONFIG = ProviderConfig(
    auth_mode="bearer",
    text_extractor=lambda p: next(
        (m["content"] for m in reversed(p["messages"]) if m.get("role") == "user"),
        "",
    ),
)


class _AsyncRateLimiter:
    def __init__(self, rpm, tpm, rpm_threshold, tpm_threshold):
        self.rpm = int(rpm * rpm_threshold) if rpm else None
        self.tpm = int(tpm * tpm_threshold) if tpm else None
        self.req_times = deque()
        self.tok_times = deque()
        self.lock = asyncio.Lock()

    def _prune(self, now):
        while self.req_times and now - self.req_times[0] >= 60:
            self.req_times.popleft()
        while self.tok_times and now - self.tok_times[0][0] >= 60:
            self.tok_times.popleft()

    async def acquire(self, tokens):
        if self.rpm is None and self.tpm is None:
            return

        while True:
            async with self.lock:
                now = time.time()
                self._prune(now)
                req_count = len(self.req_times)
                tok_sum = sum(t for _, t in self.tok_times)
                eff_tokens = tokens
                if self.tpm is not None and tokens > self.tpm:
                    eff_tokens = self.tpm
                can_req = self.rpm is None or req_count < self.rpm
                can_tok = self.tpm is None or (tok_sum + eff_tokens) <= self.tpm

                if can_req and can_tok:
                    self.req_times.append(now)
                    self.tok_times.append((now, eff_tokens))
                    return

                sleep_for = 0.1
                if self.rpm is not None and req_count >= self.rpm and self.req_times:
                    sleep_for = max(sleep_for, 60 - (now - self.req_times[0]) + 0.05)
                if self.tpm is not None and (tok_sum + tokens) > self.tpm and self.tok_times:
                    sleep_for = max(sleep_for, 60 - (now - self.tok_times[0][0]) + 0.05)

            await asyncio.sleep(sleep_for)


async def process_payloads(
    payloads,
    entries,
    endpoint,
    api_key,
    provider_config,
    rpm,
    tpm,
    rpm_threshold=0.75,
    tpm_threshold=0.75,
    max_concurrency=200,
    timeout=15,
):
    limiter = _AsyncRateLimiter(rpm, tpm, rpm_threshold, tpm_threshold)
    semaphore = asyncio.Semaphore(max_concurrency)
    timeout_cfg = aiohttp.ClientTimeout(total=timeout)

    auth_params, auth_headers = provider_config.get_auth(api_key)

    async def post_one(session, index):
        async with semaphore:
            entry = entries[index]
            entry_id = entry["id"]
            text = entry["context"]
            try:
                est_tokens = provider_config.estimate_payload_tokens(payloads[index])
                await limiter.acquire(est_tokens)

                async with session.post(
                    endpoint,
                    json=payloads[index],
                    params=auth_params or None,
                    headers=auth_headers or None,
                ) as resp:
                    body = await resp.text()
                    if resp.status >= 400:
                        raise Exception(f"HTTP {resp.status}: {body[:200]}")

                results = body
                return index, {"id": entry_id, "context": text, "result": results}, None
            except Exception as e:
                return index, None, str(e)

    async with aiohttp.ClientSession(timeout=timeout_cfg) as session:
        tasks = [asyncio.create_task(post_one(session, i)) for i in range(len(payloads))]
        ok = 0
        err = 0
        pbar = tqdm(total=len(tasks), unit="entries")
        try:
            for task in asyncio.as_completed(tasks):
                index, result, error = await task
                if error:
                    entry = entries[index]
                    entries[index] = {**entry, "error": error}
                    err += 1
                else:
                    entries[index] = result
                    ok += 1
                pbar.set_description(f"ok {ok} err {err}")
                pbar.update(1)
        finally:
            pbar.close()

    return entries