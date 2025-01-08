Dataset Builder
===============

Convert unstructured text into structured datasets.


Installation
------------
.. code-block:: bash

    pip install txt2dataset

Quickstart
----------

.. code-block:: python

    from datamule.dataset_builder.dataset_builder import DatasetBuilder
    import os

    builder = DatasetBuilder()

    # Set API key
    builder.set_api_key(os.environ["GOOGLE_API_KEY"])

    # Set required configurations
    builder.set_paths(
        input_path="data/item502.csv",
        output_path="data/bod.csv",
        failed_path="data/failed_accessions.txt"
    )

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

    # Build the dataset
    builder.build()