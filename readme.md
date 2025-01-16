# txt2dataset

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

### Initialization
```
from txt2dataset import DatasetBuilder

builder = DatasetBuilder(input_path,output_path)

# set api key
builder.set_api_key(api_key)

# set base prompt, e.g. what the model looks for
base_prompt = """Extract officer changes and movements to JSON format.
    Track when officers join, leave, or change roles.
    Provide the following information:
    - date (YYYYMMDD)
    - name (First Middle Last)
    - title
    - action (one of: ["HIRED", "RESIGNED", "TERMINATED", "PROMOTED", "TITLE_CHANGE"])
    Return an empty dict if info unavailable."""

# set what the model should return
response_schema = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "date": {"type": "STRING", "description": "Date of action in YYYYMMDD format"},
            "name": {"type": "STRING", "description": "Full name (First Middle Last)"},
            "title": {"type": "STRING", "description": "Official title/position"},
            "action": {
                "type": "STRING", 
                "enum": ["HIRED", "RESIGNED", "TERMINATED", "PROMOTED", "TITLE_CHANGE"],
                "description": "Type of personnel action"
            }
        },
        "required": ["date", "name", "title", "action"]
    }
}

# Optional configurations
builder.set_rpm(1500)
builder.set_save_frequency(100)
builder.set_model('gemini-1.5-flash-8b')
```

### Build the dataset
```
builder.build(base_prompt=base_prompt,
               response_schema=response_schema,
               text_column='text',
               index_column='accession_number',
               input_path="data/msft_8k_item_5_02.csv",
               output_path='data/msft_officers.csv')
```

### Standardize the dataset
```
builder.standardize(response_schema=response_schema,input_path='data/msft_officers.csv', output_path='data/msft_officers_standardized.csv',columns=['name'])
```

### Validate the dataset
```
results = builder.validate(input_path='data/msft_8k_item_5_02.csv',
                 output_path= 'data/msft_officers_standardized.csv', 
                 text_column='text',
                 index_column='accession_number', 
                 base_prompt=base_prompt,
                 response_schema=response_schema,
                 n=5,
                 quiet=False)
```

#### Example Validation Output
```
[{
    "input_text": "Item 5.02 Departure of Directors... Kevin Turner provided notice he was resigning his position as Chief Operating Officer of Microsoft.",
    "process_output": [{
        "date": 20160630,
        "name": "Kevin Turner",
        "title": "Chief Operating Officer",
        "action": "RESIGNED"
    }],
    "is_valid": true,
    "reason": "The generated JSON is valid..."
},...
]
```

