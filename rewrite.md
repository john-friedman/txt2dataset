# txt2dataset
A package for building, standardizing and validating datasets using language models. Supports the [Structured Output](https://github.com/Structured-Output) project. 

* [Documentation](https://john-friedman.github.io/txt2dataset/dataset_builder.html)
* [Get a Gemini API Key](https://ai.google.dev/gemini-api/docs/api-key)

## Models Supported
* Gemini

## Installation

```
pip install txt2dataset
```

## Usage
1. Define data types
2. class DatasetBuilder(schema,model,save_frequency,ratelimit,api_key)
- Feed in schema
- build()
- validate()
- standardize()

Optional
