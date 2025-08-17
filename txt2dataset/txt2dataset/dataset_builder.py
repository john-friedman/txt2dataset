from google import genai
from pydantic import BaseModel
from typing import Optional, List
import os

class DatasetBuilder:

    def __init__(self, prompt, schema, model, text_list, save_frequency=100, ratelimit=60, api_key=None,info_found_bool="info_found"):
        self.prompt = prompt
        self.schema = schema
        self.model = model
        self.save_frequency = save_frequency
        self.ratelimit = ratelimit
        self.text_list = text_list
        self.info_found_bool = info_found_bool

        # check if GEMINI_API_KEY is in environment, if not given or in environment raise value error:
        if not api_key and not os.getenv("GEMINI_API_KEY"):
            raise ValueError("API key must be provided either as an argument or through the GEMINI_API_KEY environment variable.")

        self.api_key = api_key
        self.client = genai.Client()  

        # tokens
        self.tokens_input = self._calculate_total_input_tokens(self)
        self.tokens_output = 0

    def _calculate_input_tokens_single(self, prompt, text):
        """Calculate estimated input tokens for a single text"""
        full_text = f"{prompt}: {text}"
        return len(full_text) // 4

    def _calculate_total_input_tokens(self):
        """Calculate estimated input tokens for all texts"""
        return sum(self._calculate_input_tokens_single(self.prompt, text) for text in self.text_list)


    def build(self):
        results = []
        # we need to use async with good rate limiter

        # to do
        response = self.client.models.generate_content(
        model=self.model,
        contents=f"{self.prompt}: {text_with_multiple_dividends}",
        config={
            "response_mime_type": "application/json",
            "response_schema": self.schema,
        },
        )
        # if null don't add
        response_data : self.schema = response.parsed


        # we need to fix this
        if response_data[self.info_found_bool]:

            if isinstance(response_data.data,list):
                results.extend(response.text)
            else:
                results.extend(response.text)

