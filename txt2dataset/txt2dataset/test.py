from google import genai
from pydantic import BaseModel
from typing import Optional, List
import os
class SingleDividend(BaseModel):
    dividend_per_share: float
    payment_date: Optional[str] = None
    record_date: Optional[str] = None
    stock_type_specified: Optional[str] = None

class DividendExtraction(BaseModel):
    info_found: bool
    data: List[SingleDividend] = []

# Example usage
GEMINI_API_KEY = os.environ['GEMINI_API_KEY']
client = genai.Client()  

# Example 1: Text with multiple dividend information
text_with_multiple_dividends = """
First Business Financial Services, Inc. (the "Company") issued a press release today 
announcing that the Company's Board of Directors declared a quarterly dividend of $0.18 
per share on April 30, 2021, unchanged compared to the last quarterly dividend per share. 
The dividend is payable on May 24, 2021 to shareholders of record on May 10, 2021. 
Also on July 12, 2020 there was a payable dividend of $0.15 per share to shareholders 
of record on July 1st, 2020.
"""

response = client.models.generate_content(
    model="gemini-2.5-flash-lite",
    contents=f"Extract ALL dividend information from this text, including historical dividends: {text_with_multiple_dividends}",
    config={
        "response_mime_type": "application/json",
        "response_schema": DividendExtraction,
    },
)

print("Example 1 - With multiple dividend info:")
print(response.text)

# Example 2: Text without dividend information
text_without_dividend = """
ABC Corporation announced today that they have completed the acquisition of XYZ Inc. 
The transaction was valued at $50 million and is expected to close in Q3 2021. 
This strategic acquisition will expand ABC's market presence in the technology sector.
"""

response2 = client.models.generate_content(
    model="gemini-2.5-flash-lite",
    contents=f"Extract dividend information from this text: {text_without_dividend}",
    config={
        "response_mime_type": "application/json",
        "response_schema": DividendExtraction,
    },
)

print("\nExample 2 - Without dividend info:")
print(response2.text)

# Example 3: Processing the response
dividend_data: DividendExtraction = response.parsed

if dividend_data.info_found:
    print(dividend_data.data)
else:
    print("\nNo dividend information found")

# Expected output for multiple dividends:
# {
#   "dividend_info_found": true,
#   "dividends": [
#     {
#       "dividend_per_share": 0.18,
#       "payment_date": "May 24, 2021",
#       "record_date": "May 10, 2021"
#     },
#     {
#       "dividend_per_share": 0.15,
#       "payment_date": "July 12, 2020",
#       "record_date": "July 1, 2020"
#     }
#   ]
# }

# For text without dividend info:
# {
#   "dividend_info_found": false,
#   "dividends": []
# }