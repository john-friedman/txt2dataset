We are now productionizing txt2dataset.

Needs:

1. Batch API Integrations - looks like json lines is preferred format for openai/gemini
2. token estimation - fast is probably ok
3. better tate limit handling
4. check rate limits

We should probably strip out genai and specific packages to use urls instead. These packages have a lot of bloat and ui changes too much.

useful 
https://ai.google.dev/api#primary-endpoints

## New UI?

builder = GeminiBuilder(rpm,tpm)
builder = VertexAIBuilder(...)
builder = OpenAIBuilder(...)

builder.build(prompt=prompt,
    schema=DividendExtraction,
    entries=entries)

builder.save('test.csv')


builder.build_batch(prompt=prompt,
    schema=DividendExtraction,
    entries=entries)
    
builder.check_batch()
builder.download_batch()

## new layout

txt2dataset/
    builders/
        gemini
        vertexai
        openai
    utils/
        token_estimation
        convert to json lines
    builder.py