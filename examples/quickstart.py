from dataset_builder import DatasetBuilder
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class SingleDividend(BaseModel):
    dividend_per_share: float
    payment_date: Optional[datetime] = None
    record_date: Optional[datetime] = None
    stock_type_specified: Optional[str] = None

class DividendExtraction(BaseModel):
    info_found: bool
    data: List[SingleDividend] = []

# Sample texts
entries = [(0,
    """First Business Financial Services, Inc. (the "Company") issued a press release today 
    announcing that the Company's Board of Directors declared a quarterly dividend of $0.18 
    per share on April 30, 2021, unchanged compared to the last quarterly dividend per share. 
    The dividend is payable on May 24, 2021 to shareholders of record on May 10, 2021. 
    Also on July 12, 2020 there was a payable dividend of $0.15 per share to shareholders 
    of record on July 1st, 2020."""),

    
    
    (1,"""XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021."""),
        
            (1,"""XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021."""),
        (1,"""XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021."""),
        (1,"""XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021."""),
        (1,"""XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021."""),
        (1,"""XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021."""),
        (1,"""XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021."""),
        (1,"""XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021."""),
        (1,"""XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021."""),
        (1,"""XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021."""),
        (1,"""XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021."""),
        (1,"""XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021."""),
        (1,"""XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021."""),
        (1,"""XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021."""),
        (1,"""XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021."""),
        (1,"""XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021."""),
        (1,"""XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021."""),
        (1,"""XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021."""),
        (1,"""XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021."""),
        (1,"""XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021."""),
        (1,"""XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021."""),
        (1,"""XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021."""),
        (1,"""XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021."""),
        (1,"""XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021."""),
        (1,"""XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021."""),
        (1,"""XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021."""),
        (1,"""XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021."""),
        (1,"""XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021."""),
        (1,"""XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021."""),
        (1,"""XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021."""),
        (1,"""XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021."""),
        (1,"""XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021."""),
        (1,"""XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021."""),
    
    
]

# Create builder
builder = DatasetBuilder(
    prompt="Extract ALL dividend information from this text",
    schema=DividendExtraction,
    model="gemini-2.5-flash-lite",
    entries=entries,
    rpm=4000
)

# Build dataset
builder.build()

# Save to csv
builder.save('quickstart.csv')