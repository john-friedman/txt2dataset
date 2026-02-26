# txt2dataset
A package for building, standardizing and validating datasets using language models. Supports the [Structured Output](https://github.com/Structured-Output) project. 

* [Get a Gemini API Key](https://ai.google.dev/gemini-api/docs/api-key)

## Models Supported
* Gemini

## Installation

```bash
pip install txt2dataset
```

## Usage

### Schema

```python
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
```

### Entries
Entries consist of an identifier and the text to be structured.
```python
entries = [
    (0,
    """First Business Financial Services, Inc. (the "Company") issued a press release today 
    announcing that the Company's Board of Directors declared a quarterly dividend of $0.18 
    per share on April 30, 2021, unchanged compared to the last quarterly dividend per share. 
    The dividend is payable on May 24, 2021 to shareholders of record on May 10, 2021. 
    Also on July 12, 2020 there was a payable dividend of $0.15 per share to shareholders 
    of record on July 1st, 2020."""),

    (1,"""XYZ Corp declared a dividend of $0.25 per share, payable June 15, 2021 
    to shareholders of record as of June 1, 2021.""")
]
```

### Prompt
Choose a prompt such as:
```python
prompt = "Extract ALL dividend information from this text"
```

### Dataset Builder Initialization

Choose the requests per minute that work for your api key and model.

```python
builder = DatasetBuilder(
    prompt=prompt,
    schema=DividendExtraction,
    model="gemini-2.5-flash-lite",
    entries=entries,
    rpm=4000,
    max_concurrent = 20,
    timeout = 60,
)
```

### Build
```python
builder.build()
```

### Save
```python
builder.save('test.csv')
```

Result:

| _id | dividend_per_share | payment_date                  | record_date                   | stock_type_specified |
|-----|---------------------|-------------------------------|-------------------------------|-----------------------|
| 0   | 0.18                | 2021-05-24 00:00:00+00:00    | 2021-05-10 00:00:00+00:00    |                       |
| 0   | 0.15                | 2020-07-12 00:00:00+00:00    | 2020-07-01 00:00:00+00:00    |                       |
| 1   | 0.25                | 2021-06-15 00:00:00+00:00    | 2021-06-01 00:00:00+00:00    |                       |


## Future Features
* validate() - checks that data types are expected. Needed less, thanks to the development of pydantic.
* standardize() - standardizes data.


