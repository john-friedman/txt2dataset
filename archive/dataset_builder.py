from google import genai

import os
import asyncio
import time
import csv
from collections import deque
from tqdm import tqdm

class AsyncRateLimiter:
    def __init__(self, rpm=60):
        self.rpm = rpm
        self.request_times = deque()
        self.lock = asyncio.Lock()
    
    async def acquire(self):
        """Wait until it's safe to make the next request using sliding window"""
        async with self.lock:
            now = time.time()
            
            # Remove requests older than 60 seconds
            while self.request_times and now - self.request_times[0] >= 60:
                self.request_times.popleft()
            
            # If we're at the rate limit, wait until the oldest request is 60 seconds old
            if len(self.request_times) >= self.rpm:
                sleep_time = 60 - (now - self.request_times[0]) + 0.1  # Small buffer
                if sleep_time > 0:
                    print(f"Rate limiting: waiting {sleep_time:.2f}s")
                    await asyncio.sleep(sleep_time)
                    # Clean up again after sleeping
                    now = time.time()
                    while self.request_times and now - self.request_times[0] >= 60:
                        self.request_times.popleft()
            
            # Record this request
            self.request_times.append(now)

class DatasetBuilder:
    def __init__(self, prompt, schema, model, entries, rpm=60, api_key=None, max_concurrent=10,timeout=60):
        self.prompt = prompt
        self.schema = schema
        self.model = model
        self.rpm = rpm
        self.max_concurrent = max_concurrent
        self.entries = entries 
        self.info_found_bool = "info_found"
        self.timeout = timeout
        
        # Check API key
        if not api_key and not os.getenv("GEMINI_API_KEY"):
            raise ValueError("API key must be provided either as an argument or through the GEMINI_API_KEY environment variable.")
        
        self.api_key = api_key
        self.client = genai.Client()
        self.rate_limiter = AsyncRateLimiter(rpm)
        self.semaphore = asyncio.Semaphore(max_concurrent)
        
        # Progress tracking
        self.pbar = None
        self.success_count = 0
        self.error_count = 0
        self.progress_lock = asyncio.Lock()

    def _calculate_input_tokens_single(self, prompt, text):
        """Calculate estimated input tokens for a single text"""
        full_text = f"{prompt}: {text}"
        return len(full_text) // 4

    def _get_entry_state(self, entry):
        """Determine the state of an entry tuple"""
        if len(entry) == 2:
            return "unprocessed"
        elif len(entry) == 3:
            return "error"
        elif len(entry) == 4:
            return "success"
        else:
            return "unknown"

    def _get_entries_to_process(self):
        """Get list of indices for entries that need processing"""
        to_process = []
        for i, entry in enumerate(self.entries):
            state = self._get_entry_state(entry)
            if state in ["unprocessed", "error"]:
                to_process.append(i)
        return to_process

    async def _update_progress(self, success=False, error=False):
        """Thread-safe progress bar update"""
        async with self.progress_lock:
            if success:
                self.success_count += 1
            if error:
                self.error_count += 1
            
            if self.pbar:
                self.pbar.set_description(f"✓{self.success_count} ✗{self.error_count}")
                self.pbar.update(1)

    async def _make_api_call(self, text):
        """Make rate-limited API call with timeout"""
        await self.rate_limiter.acquire()
        
        try:
            response = await asyncio.wait_for(
                self.client.aio.models.generate_content(
                    model=self.model,
                    contents=f"{self.prompt}: {text}",
                    config={
                        "response_mime_type": "application/json",
                        "response_schema": self.schema,
                    },
                ),
                timeout=self.timeout
            )
            return response
        except asyncio.TimeoutError:
            raise Exception(f"API request timed out after {self.timeout} seconds")

    def _process_response(self, response, entry_id):
        """Process a single API response and return (results, tokens_used)"""
        if not response:
            return [], 0
        
        try:
            response_data = response.parsed
            
            # Calculate output tokens (rough estimate)
            tokens_used = len(response.text) // 4
            
            # Check if info was found using the configurable boolean field
            if hasattr(response_data, self.info_found_bool) and getattr(response_data, self.info_found_bool):
                if hasattr(response_data, 'data') and response_data.data:
                    results = []
                    if isinstance(response_data.data, list):
                        for item in response_data.data:
                            result_with_id = {"_id": entry_id, **item.dict()}
                            results.append(result_with_id)
                    else:
                        result_with_id = {"_id": entry_id, **response_data.data.dict()}
                        results.append(result_with_id)
                    return results, tokens_used
            
            return [], tokens_used
            
        except Exception as e:
            raise Exception(f"Error processing response: {e}")

    async def _process_single_entry(self, entry_index):
        """Process a single entry with semaphore control"""
        async with self.semaphore:
            entry = self.entries[entry_index]
            entry_id = entry[0]
            text = entry[1]
            
            try:
                # Make API call
                response = await self._make_api_call(text)
                
                # Process response
                results, tokens_used = self._process_response(response, entry_id)
                
                # Update entry in place - success state
                self.entries[entry_index] = (entry_id, text, results, tokens_used)
                
                # Update progress
                await self._update_progress(success=True)
                
            except Exception as e:
                # Update entry in place - error state
                error_message = str(e)
                self.entries[entry_index] = (entry_id, text, error_message)
                print(f"✗ Error processing entry {entry_id}: {error_message}")
                
                # Update progress
                await self._update_progress(error=True)

    async def _build(self):
        """Build the dataset with concurrent processing"""
        # Find entries that need processing
        to_process = self._get_entries_to_process()
        
        if not to_process:
            print("No entries need processing")
            return
        
        print(f"Starting concurrent dataset building:")
        print(f"- {len(to_process)} entries to process")
        print(f"- Rate limit: {self.rpm} RPM")
        print(f"- Max concurrent: {self.max_concurrent}")
        
        # Calculate estimated input tokens for entries being processed
        total_input_tokens = sum(
            self._calculate_input_tokens_single(self.prompt, self.entries[i][1])
            for i in to_process
        )
        print(f"- Estimated input tokens: {total_input_tokens:,}")
        
        # Initialize progress tracking
        self.success_count = 0
        self.error_count = 0
        self.pbar = tqdm(total=len(to_process), desc="✓0 ✗0", unit="entries")
        
        try:
            # Process all entries concurrently
            tasks = [self._process_single_entry(i) for i in to_process]
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            # Clean up progress bar
            if self.pbar:
                self.pbar.close()
                self.pbar = None
        
        # Print summary
        self._print_summary()
    
    def _print_summary(self):
        """Print processing summary"""
        success_count = sum(1 for entry in self.entries if self._get_entry_state(entry) == "success")
        error_count = sum(1 for entry in self.entries if self._get_entry_state(entry) == "error")
        unprocessed_count = sum(1 for entry in self.entries if self._get_entry_state(entry) == "unprocessed")
        
        # Count results and tokens
        total_results = 0
        total_tokens = 0
        for entry in self.entries:
            if self._get_entry_state(entry) == "success":
                total_results += len(entry[2])  # results list
                total_tokens += entry[3]  # tokens used
        
        print(f"\nDataset building complete!")
        print(f"Successful: {success_count}")
        print(f"Errors: {error_count}")
        print(f"Unprocessed: {unprocessed_count}")
        print(f"Total results: {total_results}")
        print(f"Total tokens used: {total_tokens:,}")
    
    def build(self):
        """Public interface to build the dataset"""
        asyncio.run(self._build())

    def get_results(self):
        """Extract all successful results from entries"""
        results = []
        for entry in self.entries:
            if self._get_entry_state(entry) == "success":
                results.extend(entry[2])  # Add all results from this entry
        return results

    def save(self, filename):
        """Save results to CSV with all fields quoted"""
        results = self.get_results()
        
        if not results:
            print("No results to save")
            return
        
        # Get all unique fieldnames from all results
        fieldnames = set()
        for result in results:
            fieldnames.update(result.keys())
        fieldnames = sorted(list(fieldnames))
        
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
            writer.writeheader()
            writer.writerows(results)
        
        print(f"Saved {len(results)} records to {filename}")
    
    def get_errors(self):
        """Get all entries that have errors"""
        errors = []
        for entry in self.entries:
            if self._get_entry_state(entry) == "error":
                errors.append({
                    "id": entry[0],
                    "text": entry[1][:100] + "..." if len(entry[1]) > 100 else entry[1],
                    "error": entry[2]
                })
        return errors
    
    def print_errors(self):
        """Print all error entries for debugging"""
        errors = self.get_errors()
        if not errors:
            print("No errors found")
            return
        
        print(f"\nFound {len(errors)} errors:")
        for error in errors:
            print(f"ID {error['id']}: {error['error']}")
            print(f"  Text: {error['text']}")
            print()