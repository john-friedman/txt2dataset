from txt2dataset import GeminiBatchBuilder

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
entries = [{'id':0, 'context':
    """First Business Financial Services, Inc. (the "Company") issued a press release today 
    announcing that the Company's Board of Directors declared a quarterly dividend of $0.18 
    per share on April 30, 2021, unchanged compared to the last quarterly dividend per share. 
    The dividend is payable on May 24, 2021 to shareholders of record on May 10, 2021. 
    Also on July 12, 2020 there was a payable dividend of $0.15 per share to shareholders 
    of record on July 1st, 2020."""},

    {"id":1,"context": """XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021."""},
    
    
]
prompt = "Extract ALL dividend information from this text"
builder = GeminiBatchBuilder()

# e.g. batches/q4dn0s5h11m9ttsbo6165b9jndnf5enubr5m
job = 'batches/q4dn0s5h11m9ttsbo6165b9jndnf5enubr5m'

# create new job
#builder.submit_job(prompt=prompt, schema=DividendExtraction, model='gemini-2.5-flash-lite', entries=entries)

# check jobs
print(builder.list_jobs())

# check job status, 
print(builder.get_job_status(job))

# download job
#print(builder.download_job(job)) 