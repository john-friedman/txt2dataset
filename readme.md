# txt2dataset (this readme is not accurate yet, please do not use)

Convert unstructured text to structured datasets using structured output for Large Language Models. Currently supports Gemini.

## Example
```
Andrew Baglino, Senior Vice President, Powertrain and Energy Engineering of Tesla, Inc. (“Tesla,”, or the “Company”), resigned from Tesla, effective as of April 14, 2024. Mr. Baglino served in this position since October 2019, prior to which he served in various engineering positions continuously since joining Tesla in March 2006. Tesla is grateful to Mr. Baglino for his leadership and contributions to our significant innovation and growth over the course of his 18-year career. 
```

--->

```
name, title, date, action
Andrew Baglino, Senior Vice President, 4/14/2024, resigns
```

## Installation

```
pip install txt2dataset
```

## Quickstart

### Setup
```
from txt2dataset import Config

# more code here
```

### Execution

```
from txt2dataset import DatasetBuilder

datasetbuilder = DatasetBuilder(path)

builder.set_base_prompt("""Extract Director or Principal Officer info to JSON format.
    Provide the following information:
    - start_date (YYYYMMDD)
    - end_date (YYYYMMDD)
    - name (First Middle Last)
    - title
    Return null if info unavailable.""")

builder.set_response_schema({
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "start_date": {"type": "STRING", "description": "Start date in YYYYMMDD format"},
            "end_date": {"type": "STRING", "description": "End date in YYYYMMDD format"},
            "name": {"type": "STRING", "description": "Full name (First Middle Last)"},
            "title": {"type": "STRING", "description": "Official title/position"}
        },
        "required": ["start_date", "end_date", "name", "title"]
    }
})

# Optional configurations
builder.set_rpm(1500)
builder.set_save_frequency(100)
builder.set_model('gemini-1.5-flash-8b')

datasetbuilder.build(text_column,index_column) # index_column is the unique identifier, if none is specified, will use row index

datasetbuilder.standardize(columns) # columns are optional, will try to standardize based on response schema

datasetbuilder.validate(size) # will load rows, check against original text and response schema, and determine whether dataset building makes sense or not, if not will return structured output with unique error message.

```


