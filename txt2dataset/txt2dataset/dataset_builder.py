import pandas as pd
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import google.generativeai as genai
from google.generativeai.types import HarmBlockThreshold, HarmCategory
import random
import time
import psutil
from threading import Lock

class RateLimiter:
    def __init__(self, max_rpm):
        self.min_delay = 62.0 / max_rpm  # 58 seconds to allow for some buffer
        self.last_request = time.time()
        self.lock = Lock()
        self.request_count = 0
    
    def acquire(self):
        with self.lock:
            now = time.time()
            time_since_last = now - self.last_request
            delay_needed = self.min_delay - time_since_last
            self.last_request = now + max(0, delay_needed)
            self.request_count += 1
            count = self.request_count
        
        if delay_needed > 0:
            time.sleep(delay_needed)
        
        return count

class DatasetBuilder:
    def __init__(self):
        """Initialize the DatasetBuilder."""
        # Configurations
        self.max_rpm = 1450
        self.max_workers = 30
        self.save_frequency = 100
        self.buffer = []
        self.buffer_lock = Lock()
        self.failed_ids = set()
        self.failed_lock = Lock()
        self.model_name = "gemini-1.5-flash-8b"
        self.model_config = {}
        self.api_key = None

    def set_api_key(self, api_key):
        """Set the API key for Google's Generative AI."""
        self.api_key = api_key
        genai.configure(api_key=api_key)
        return self

    def set_rpm(self, max_rpm=1450):
        """Set the maximum requests per minute."""
        self.max_rpm = max_rpm
        return self

    def set_max_workers(self, max_workers=30):
        """Set the maximum number of concurrent workers."""
        self.max_workers = max_workers
        return self

    def set_save_frequency(self, frequency=100):
        """Set how often to save progress."""
        self.save_frequency = frequency
        return self

    def set_model(self, model_name="gemini-1.5-flash-8b", **model_config):
        """Set the model name and configuration."""
        self.model_name = model_name
        self.model_config = model_config
        return self

    def validate_config(self):
        """Validate that API key is set."""
        if not self.api_key:
            raise ValueError("API key must be set using set_api_key()")

    def get_processed_ids(self, output_path, id_column='index'):
        """Get set of processed identifiers from output file."""
        if not os.path.exists(output_path):
            return set()
        
        try:
            df = pd.read_csv(output_path, usecols=[id_column])
            return set(df[id_column])
        except Exception as e:
            print(f"Warning: Error reading processed IDs: {e}")
            return set()

    def save_data(self, df_new, output_path):
        """Append new data to existing CSV."""
        df_new.to_csv(output_path, mode='a', header=not os.path.exists(output_path), index=False)

    def save_failed_ids(self, failed_path):
        """Save failed identifiers to file."""
        with open(failed_path, 'w') as f:
            for id_val in self.failed_ids:
                f.write(f"{id_val}\n")

    def process_text(self, args):
        """Process a single text entry through the model."""
        model, text, identifier, rate_limiter, id_column, base_prompt, response_schema = args
        
        current_requests = rate_limiter.acquire()
        
        full_prompt = base_prompt + "\n\nINFORMATION:\n" + text

        try:
            generation_config = genai.GenerationConfig(
                response_mime_type="application/json",
                response_schema=response_schema,
                **self.model_config
            )
            
            response = model.generate_content(
                full_prompt,
                generation_config=generation_config,
            )
            results = json.loads(response.text)
            
            # Add identifier to each result
            for result in results:
                result[id_column] = identifier
            
            with self.buffer_lock:
                self.buffer.extend(results)
            
            return True, current_requests
        except Exception as e:
            with self.failed_lock:
                self.failed_ids.add(identifier)
            return False, f"Error processing {identifier}: {str(e)}"

    def build(self, input_path, output_path, text_column, base_prompt, response_schema, 
              index_column=None, failed_path='errors.txt'):
        """Main processing method to build the dataset.
        
        Args:
            input_path (str): Path to input CSV file
            output_path (str): Path to output CSV file where results will be saved
            text_column (str): Name of the column containing text to process
            base_prompt (str): Base prompt for LLM processing
            response_schema (dict): Schema definition for response structure
            index_column (str, optional): Name of the column to use as unique identifier.
                                        If None, row index will be used.
            failed_path (str, optional): Path to save failed IDs. Defaults to 'errors.txt'
        """
        self.validate_config()

        # Initialize model and rate limiter
        model = genai.GenerativeModel(self.model_name)
        rate_limiter = RateLimiter(self.max_rpm)
        
        # Load data
        print("Loading data...")
        df_input = pd.read_csv(input_path)
        
        # Validate text column exists
        if text_column not in df_input.columns:
            raise ValueError(f"Text column '{text_column}' not found in input CSV")
        
        # Set up identifier column
        if index_column:
            if index_column not in df_input.columns:
                raise ValueError(f"Index column '{index_column}' not found in input CSV")
            identifiers = df_input[index_column]
            id_col = index_column
        else:
            identifiers = df_input.index
            id_col = 'index'
            df_input[id_col] = identifiers  # Add index column explicitly
        
        # Get previously processed IDs
        processed_ids = self.get_processed_ids(output_path, id_col)
        
        # Reset failed IDs for new build
        self.failed_ids = set()
        
        # Filter out already processed entries
        df_to_process = df_input[~identifiers.isin(processed_ids)]
        
        total_in_dataset = len(df_input)
        already_processed = len(processed_ids)
        to_process = len(df_to_process)
        
        print(f"Total entries in dataset: {total_in_dataset}")
        print(f"Already processed: {already_processed}")
        print(f"New entries to process: {to_process}")
        
        if to_process == 0:
            print("All entries already processed!")
            return

        # Prepare work items
        work_items = [
            (model, row[text_column], row[id_col], rate_limiter, id_col, base_prompt, response_schema) 
            for _, row in df_to_process.iterrows()
        ]
        
        start_time = time.time()
        last_save_time = time.time()
        processed_count = 0
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(self.process_text, item): item for item in work_items}
            
            with tqdm(total=total_in_dataset, initial=already_processed, desc="Processing entries") as pbar:
                for future in as_completed(futures):
                    success, result = future.result()
                    
                    if not success:
                        print(f"\n{result}")
                    
                    processed_count += 1
                    pbar.update(1)
                    
                    elapsed = time.time() - start_time
                    rpm = processed_count / (elapsed / 60)
                    memory_usage = psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
                    
                    current_progress = already_processed + processed_count
                    pbar.set_description(
                        f"Processed {current_progress}/{total_in_dataset} | {rpm:.0f} RPM | Mem: {memory_usage:.0f}MB"
                    )
                    
                    # Save periodically using append
                    if len(self.buffer) >= self.save_frequency:
                        with self.buffer_lock:
                            df_new = pd.DataFrame(self.buffer)
                            self.buffer = []
                        
                        if not df_new.empty:
                            self.save_data(df_new, output_path)
                            last_save_time = time.time()
                    
                    # Save failed IDs periodically
                    if self.failed_ids and time.time() - last_save_time > 300:
                        self.save_failed_ids(failed_path)
                        last_save_time = time.time()
        
        # Save any remaining results
        if self.buffer:
            with self.buffer_lock:
                df_new = pd.DataFrame(self.buffer)
                self.buffer = []
            
            if not df_new.empty:
                self.save_data(df_new, output_path)
        
        # Save failed IDs
        if self.failed_ids:
            self.save_failed_ids(failed_path)
        
        # Print final statistics
        elapsed = time.time() - start_time
        final_rpm = processed_count / (elapsed / 60)
        
        print(f"\nProcessing complete:")
        print(f"Total processed in this run: {processed_count}")
        print(f"Average speed: {final_rpm:.0f} RPM")
        print(f"Failed entries: {len(self.failed_ids)}")
        if self.failed_ids:
            print(f"Failed entries saved to: {failed_path}")

    def standardize(self, input_path, response_schema, output_path=None, columns=None):
        """Use LLM to standardize data against the response schema.
        
        Args:
            input_path (str): Path to input CSV file to standardize
            response_schema (dict): Schema definition for data structure
            output_path (str, optional): Save standardized data here. If None, modifies in-place.
            columns (list, optional): Columns to standardize. Uses schema properties if None.
        """
        self.validate_config()

        model = genai.GenerativeModel(self.model_name)
        rate_limiter = RateLimiter(self.max_rpm)
        
        if not columns:
            columns = list(response_schema["items"]["properties"].keys())
        
        print("Loading data...")
        data = pd.read_csv(input_path)
        result = data.copy() if output_path else data
        
        for col in columns:
            if col not in response_schema["items"]["properties"]:
                continue
                
            unique_vals = data[col].dropna().unique().tolist()
            if not unique_vals:
                continue
                
            schema_def = response_schema["items"]["properties"][col]
            
            prompt = f"""Given this response schema for field '{col}':
    {json.dumps(schema_def, indent=2)}

    And these existing values:
    {json.dumps(unique_vals, indent=2)}"""

            try:
                generation_config = genai.GenerationConfig(
                    response_mime_type="application/json",
                    response_schema={
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "original": {
                                    "type": "STRING",
                                    "description": "Original value from the dataset"
                                },
                                "standardized": {
                                    "type": "STRING", 
                                    "description": "Standardized form of the value according to schema definition"
                                }
                            },
                            "required": ["original", "standardized"]
                        }
                    },
                    **self.model_config
                )
                
                rate_limiter.acquire()
                response = model.generate_content(
                    prompt,
                    generation_config=generation_config,
                )
                response_array = json.loads(response.text)
                mapping = {item["original"]: item["standardized"] for item in response_array}
                
                if mapping:
                    result[col] = result[col].map(lambda x: mapping.get(x, x))
                    print(f"Standardized {len(mapping)} unique values in {col}")
                    
            except Exception as e:
                print(f"Error standardizing {col}: {str(e)}")
                continue
        
        if output_path:
            result.to_csv(output_path, index=False)
            print(f"Saved standardized data to {output_path}")

    def validate(self, input_path, output_path, text_column, base_prompt, response_schema, index_column, n=3, quiet=True):
        """Validate the quality of processed data by comparing original text to generated output.
        
        Args:
            input_path (str): Path to original input CSV file
            output_path (str): Path to processed output CSV file
            text_column (str): Name of the column containing original text
            base_prompt (str): Base prompt used in processing
            response_schema (dict): Schema definition for response structure
            index_column (str): Column to use for matching input to output rows
            n (int, optional): Number of random samples to validate. Defaults to 3.
            quiet (bool, optional): If False, prints validation summary. Defaults to True.
            
        Returns:
            list: List of dicts containing validation results for each sample
                [{'input_text': str, 'is_valid': bool, 'reason': str}, ...]
        """
        self.validate_config()
        model = genai.GenerativeModel(self.model_name)
        
        df_input = pd.read_csv(input_path)
        df_output = pd.read_csv(output_path)
        
        if text_column not in df_input.columns:
            raise ValueError(f"Text column '{text_column}' not found in input CSV")
        if index_column not in df_input.columns:
            raise ValueError(f"Index column '{index_column}' not found in input CSV")
            
        unique_indices = list(set(df_output[index_column]))
        sample_indices = random.sample(unique_indices, min(n, len(unique_indices)))
        validation_results = []
        
        schema_fields = list(response_schema["items"]["properties"].keys())
        
        for idx in sample_indices:
            try:
                original_text = df_input[df_input[index_column] == idx][text_column].iloc[0]
                processed_rows = df_output[df_output[index_column] == idx][schema_fields].to_dict('records')
                
                if not processed_rows:
                    validation_results.append({
                        'input_text': original_text,
                        'process_output': None,
                        'is_valid': False,
                        'reason': 'No processed output found'
                    })
                    continue
                    
                validation_prompt = f"""Given the following:

    Original text:
    {original_text}

    Generated output (multiple entries may be present):
    {json.dumps(processed_rows, indent=2)}

    Schema used:
    {json.dumps(response_schema, indent=2)}

    Base prompt used:
    {base_prompt}

    Determine if the generated output is valid and appropriate. Consider:
    1. Does it follow the schema structure?
    2. Is the content appropriate given the original text?
    3. Is the information accurate to the original text?
    4. Have any important details been missed or misrepresented?

    Return a JSON with this schema:
    {{
        "is_valid": boolean,
        "reason": "string explaining why valid or invalid"
    }}"""

                validation_config = genai.GenerationConfig(
                    response_mime_type="application/json",
                    response_schema={
                        "type": "OBJECT",
                        "properties": {
                            "is_valid": {
                                "type": "BOOLEAN",
                                "description": "Whether the processed output is valid"
                            },
                            "reason": {
                                "type": "STRING",
                                "description": "Explanation of validation result"
                            }
                        },
                        "required": ["is_valid", "reason"]
                    }
                )
                
                validation_response = model.generate_content(
                    validation_prompt,
                    generation_config=validation_config,
                )
                
                validation_result = json.loads(validation_response.text)
                validation_results.append({
                    'input_text': original_text,
                    'process_output': processed_rows,
                    'is_valid': validation_result['is_valid'],
                    'reason': validation_result['reason']
                })
                
            except Exception as e:
                validation_results.append({
                    'input_text': original_text,
                     'process_output': processed_rows,
                    'is_valid': False,
                    'reason': str(e)
                })
        
        if not quiet:
            correct = sum(1 for r in validation_results if r['is_valid'])
            print(f"Validation complete: {correct} correct out of {len(validation_results)} total")
        
        return validation_results