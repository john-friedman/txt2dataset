import copy
import inspect

def estimate_tokens(string):
    return len(string)/4

def estimate_entries_tokens(entries):
    return sum(estimate_tokens(entry['context']) for entry in entries)

def pydantic_to_json_schema(schema) -> dict:
    """Convert a Pydantic model to a flat JSON schema with all $defs inlined."""
    if inspect.isclass(schema) and hasattr(schema, "model_json_schema"):
        schema = schema.model_json_schema()

    schema = copy.deepcopy(schema)
    defs = schema.pop("$defs", {})

    def _resolve(obj):
        if isinstance(obj, dict):
            if "$ref" in obj:
                ref_name = obj["$ref"].split("/")[-1]
                resolved = copy.deepcopy(defs[ref_name])
                return _resolve(resolved)
            return {k: _resolve(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [_resolve(i) for i in obj]
        return obj

    return _resolve(schema)


def pydantic_to_gemini_schema(schema) -> dict:
    """Wrap a resolved schema in Gemini's expected format."""
    return pydantic_to_json_schema(schema)
