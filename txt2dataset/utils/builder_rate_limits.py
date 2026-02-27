import time
from collections import deque
import aiohttp
from tqdm import tqdm
import asyncio
from ..utils.utils import estimate_tokens

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
                    # Oversized single request: wait for an empty window, then proceed anyway.
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
    rpm,
    tpm,
    rpm_threshold=0.75,
    tpm_threshold=0.75,
    max_concurrency=10,
    timeout=60,
):
    limiter = _AsyncRateLimiter(rpm, tpm, rpm_threshold, tpm_threshold)
    semaphore = asyncio.Semaphore(max_concurrency)
    timeout_cfg = aiohttp.ClientTimeout(total=timeout)

    async def post_one(session, index):
        async with semaphore:
            entry = entries[index]
            entry_id = entry["id"]
            text = entry["context"]
            try:
                est_tokens = estimate_tokens(payloads[index]["contents"][0]["parts"][0]["text"])
                await limiter.acquire(est_tokens)

                params = {"key": api_key}
                async with session.post(endpoint, json=payloads[index], params=params) as resp:
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
