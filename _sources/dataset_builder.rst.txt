Dataset Builder
===============

A tool for building, standardizing and validating datasets using language models.

Quickstart
----------

Initialization
~~~~~~~~~~~~~~

First, import and initialize the DatasetBuilder class:

.. code-block:: python

    from txt2dataset import DatasetBuilder

    builder = DatasetBuilder(input_path, output_path)

    # Set your API key
    builder.set_api_key(api_key)

Set the base prompt that defines what the model should extract:

.. code-block:: python

    base_prompt = """Extract officer changes and movements to JSON format.
        Track when officers join, leave, or change roles.
        Provide the following information:
        - date (YYYYMMDD)
        - name (First Middle Last)
        - title
        - action (one of: ["HIRED", "RESIGNED", "TERMINATED", "PROMOTED", "TITLE_CHANGE"])
        Return an empty dict if info unavailable."""

Define the expected response schema:

.. code-block:: python

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

Optional Configurations
~~~~~~~~~~~~~~~~~~~~~~~

You can customize various settings:

.. code-block:: python

    builder.set_rpm(1500)  # Set requests per minute
    builder.set_save_frequency(100)  # Save progress every 100 items
    builder.set_model('gemini-1.5-flash-8b')  # Set the model to use

Building the Dataset
--------------------

Build your dataset using the configured settings:

.. code-block:: python

    builder.build(
        base_prompt=base_prompt,
        response_schema=response_schema,
        text_column='text',
        index_column='accession_number',
        input_path="data/msft_8k_item_5_02.csv",
        output_path='data/msft_officers.csv'
    )

Standardizing the Dataset
-------------------------

Standardize the output dataset:

.. code-block:: python

    builder.standardize(
        response_schema=response_schema,
        input_path='data/msft_officers.csv',
        output_path='data/msft_officers_standardized.csv',
        columns=['name']
    )

Validating the Dataset
----------------------

Validate the generated dataset:

.. code-block:: python

    results = builder.validate(
        input_path='data/msft_8k_item_5_02.csv',
        output_path='data/msft_officers_standardized.csv',
        text_column='text',
        index_column='accession_number',
        base_prompt=base_prompt,
        response_schema=response_schema,
        n=5,
        quiet=False
    )

Example Validation Output
~~~~~~~~~~~~~~~~~~~~~~~~~

The validation returns results in this format:

.. code-block:: python

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
    },...]