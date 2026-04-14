"""
User-configurable settings for txt2dataset (persisted to disk).

Example:
    from txt2dataset import config
    config.SET_REJECT_KEY("X")
"""

import json
import os

_DEFAULT_CONFIG_PATH = os.environ.get("TXT2DATASET_CONFIG_PATH") or os.path.join(
    os.path.expanduser("~"), ".txt2dataset", "config.json"
)

DEFAULT_SPOT_CHECK_PROMPT = """
Here is a source document and some data extracted from it.

For each extracted row, check each field value against the source document.
Only flag a value as wrong if something is egregiously wrong — meaning
the extracted value cannot be found in or inferred from the source
text with some generosity.

null values are correct when the source does not mention that field — do not flag null as debatable or fabricated simply because the field is absent from the source. This applies especially to date fields: if the source provides no announcement date, null announcement date fields are correct, not fabricated. When in doubt about a null, mark it correct.

Return JSON as a list of objects, one per extracted row, each with:
- id: the row_index of the extracted row
- fields: array of objects with:
  - name: field name
  - verdict: 'correct', 'fabricated', or 'debatable'
  - desc: brief explanation of why
"""

DEFAULT_SPOT_CHECK_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "verdict": {"type": "string"},
                        "desc": {"type": "string"},
                    },
                    "required": ["name", "verdict", "desc"],
                },
            },
        },
        "required": ["id", "fields"],
    },
}

DEFAULT_SPOT_CHECK_VERDICT_COLORS = {
    "correct": "#e8f5e9",
    "fabricated": "#ffebee",
    "debatable": "#fff8e1",
}


class Config:
    def __init__(self, config_path=_DEFAULT_CONFIG_PATH):
        self.config_path = config_path
        self._ensure_config_exists()

    def _default_config(self):
        return {
            "hotkey_back": ["ArrowLeft", "A"],
            "hotkey_forward": ["ArrowRight", "D"],
            "hotkey_copy_extracted_rows": ["F"],
            "hotkey_copy_id": ["P"],
            "hotkey_download_extracted_rows": ["O"],
            "hotkey_reject": ["R"],
            "default_reject_file": "reject.json",
            "default_reject_id_file": "reject_id.json",
            "spot_check_prompt": DEFAULT_SPOT_CHECK_PROMPT,
            "spot_check_schema": DEFAULT_SPOT_CHECK_SCHEMA,
            "spot_check_verdict_colors": DEFAULT_SPOT_CHECK_VERDICT_COLORS,
        }

    def _ensure_config_exists(self):
        try:
            config_dir = os.path.dirname(self.config_path)
            if config_dir:
                os.makedirs(config_dir, exist_ok=True)
            if not os.path.exists(self.config_path):
                self._save_config(self._default_config())
        except OSError:
            return

    def _save_config(self, config):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
                f.write("\n")
        except OSError as e:
            raise OSError(
                f"Failed to write txt2dataset config to {self.config_path}. "
                "Set TXT2DATASET_CONFIG_PATH to a writable file path."
            ) from e

    def _load_config(self):
        try:
            with open(self.config_path, encoding="utf-8") as f:
                config = json.load(f)
        except Exception:
            config = {}

        if not isinstance(config, dict):
            config = {}

        merged = self._default_config()
        merged.update(config)
        return merged

    def _normalize_key(self, key):
        if key is None:
            raise ValueError("key must be a non-empty string")

        key_str = str(key).strip()
        if not key_str:
            raise ValueError("key must be a non-empty string")

        if len(key_str) == 1:
            upper = key_str.upper()
            if upper in {'"', "'", "\\", "\n", "\r", "\t"}:
                raise ValueError("unsupported key character")
            return upper

        normalized = key_str.replace(" ", "")
        normalized_upper = normalized.upper()
        if normalized_upper in {"ARROWLEFT", "LEFT"}:
            return "ArrowLeft"
        if normalized_upper in {"ARROWRIGHT", "RIGHT"}:
            return "ArrowRight"

        raise ValueError(f"unsupported key: {key_str}")

    def _normalize_key_list(self, keys):
        if keys is None:
            raise ValueError("keys must be a list or string")

        if isinstance(keys, str):
            iterable = [keys]
        elif isinstance(keys, (list, tuple, set)):
            iterable = list(keys)
        else:
            raise ValueError("keys must be a list or string")

        if len(iterable) == 0:
            return []

        normalized = []
        seen = set()
        for key in iterable:
            nk = self._normalize_key(key)
            if nk not in seen:
                normalized.append(nk)
                seen.add(nk)

        return normalized

    def set_back_key(self, keys):
        config = self._load_config()
        if isinstance(keys, str):
            keys = ["ArrowLeft", keys]
        config["hotkey_back"] = self._normalize_key_list(keys)
        self._save_config(config)

    def set_forward_key(self, keys):
        config = self._load_config()
        if isinstance(keys, str):
            keys = ["ArrowRight", keys]
        config["hotkey_forward"] = self._normalize_key_list(keys)
        self._save_config(config)

    def set_copy_extracted_rows_key(self, keys):
        config = self._load_config()
        config["hotkey_copy_extracted_rows"] = self._normalize_key_list(keys)
        self._save_config(config)

    def set_copy_id_key(self, keys):
        config = self._load_config()
        config["hotkey_copy_id"] = self._normalize_key_list(keys)
        self._save_config(config)

    def set_download_extracted_rows_key(self, keys):
        config = self._load_config()
        config["hotkey_download_extracted_rows"] = self._normalize_key_list(keys)
        self._save_config(config)

    def set_reject_key(self, keys):
        config = self._load_config()
        config["hotkey_reject"] = self._normalize_key_list(keys)
        self._save_config(config)

    def set_reject_file(self, path):
        if path is None:
            raise ValueError("path must be a non-empty string")
        path_str = str(path).strip()
        if not path_str:
            raise ValueError("path must be a non-empty string")
        config = self._load_config()
        config["default_reject_file"] = path_str
        self._save_config(config)

    def set_reject_id_file(self, path):
        if path is None:
            raise ValueError("path must be a non-empty string")
        path_str = str(path).strip()
        if not path_str:
            raise ValueError("path must be a non-empty string")
        config = self._load_config()
        config["default_reject_id_file"] = path_str
        self._save_config(config)

    def set_spot_check_prompt(self, prompt: str):
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        config = self._load_config()
        config["spot_check_prompt"] = prompt
        self._save_config(config)

    def set_spot_check_schema(self, schema: dict):
        if not isinstance(schema, dict):
            raise ValueError("schema must be a dict")
        config = self._load_config()
        config["spot_check_schema"] = schema
        self._save_config(config)

    def set_spot_check_verdict_colors(self, colors: dict):
        if not isinstance(colors, dict):
            raise ValueError("colors must be a dict mapping verdict strings to CSS color strings")
        config = self._load_config()
        config["spot_check_verdict_colors"] = colors
        self._save_config(config)

    def get_back_key(self):
        try:
            raw = self._load_config().get("hotkey_back", ["ArrowLeft", "A"])
            if isinstance(raw, str):
                return self._normalize_key_list(["ArrowLeft", raw])
            return self._normalize_key_list(raw)
        except Exception:
            return ["ArrowLeft", "A"]

    def get_forward_key(self):
        try:
            raw = self._load_config().get("hotkey_forward", ["ArrowRight", "D"])
            if isinstance(raw, str):
                return self._normalize_key_list(["ArrowRight", raw])
            return self._normalize_key_list(raw)
        except Exception:
            return ["ArrowRight", "D"]

    def get_copy_extracted_rows_key(self):
        try:
            return self._normalize_key_list(self._load_config().get("hotkey_copy_extracted_rows", ["F"]))
        except Exception:
            return ["F"]

    def get_copy_id_key(self):
        try:
            return self._normalize_key_list(self._load_config().get("hotkey_copy_id", ["P"]))
        except Exception:
            return ["P"]

    def get_download_extracted_rows_key(self):
        try:
            return self._normalize_key_list(self._load_config().get("hotkey_download_extracted_rows", ["O"]))
        except Exception:
            return ["O"]

    def get_reject_key(self):
        try:
            return self._normalize_key_list(self._load_config().get("hotkey_reject", ["R"]))
        except Exception:
            return ["R"]

    def get_reject_file(self):
        return str(self._load_config().get("default_reject_file", "reject.json")).strip() or "reject.json"

    def get_reject_id_file(self):
        return str(self._load_config().get("default_reject_id_file", "reject_id.json")).strip() or "reject_id.json"

    def get_spot_check_prompt(self):
        return self._load_config().get("spot_check_prompt", DEFAULT_SPOT_CHECK_PROMPT)

    def get_spot_check_schema(self):
        return self._load_config().get("spot_check_schema", DEFAULT_SPOT_CHECK_SCHEMA)

    def get_spot_check_verdict_colors(self):
        return self._load_config().get("spot_check_verdict_colors", DEFAULT_SPOT_CHECK_VERDICT_COLORS)


CONFIG = Config()

HOTKEY_BACK = CONFIG.get_back_key()
HOTKEY_FORWARD = CONFIG.get_forward_key()
HOTKEY_COPY_EXTRACTED_ROWS = CONFIG.get_copy_extracted_rows_key()
HOTKEY_COPY_ID = CONFIG.get_copy_id_key()
HOTKEY_DOWNLOAD_EXTRACTED_ROWS = CONFIG.get_download_extracted_rows_key()
HOTKEY_REJECT = CONFIG.get_reject_key()
DEFAULT_REJECT_FILE = CONFIG.get_reject_file()
DEFAULT_REJECT_ID_FILE = CONFIG.get_reject_id_file()


def _refresh_globals():
    global HOTKEY_BACK, HOTKEY_FORWARD, HOTKEY_COPY_EXTRACTED_ROWS, HOTKEY_COPY_ID, HOTKEY_DOWNLOAD_EXTRACTED_ROWS, HOTKEY_REJECT, DEFAULT_REJECT_FILE, DEFAULT_REJECT_ID_FILE
    HOTKEY_BACK = CONFIG.get_back_key()
    HOTKEY_FORWARD = CONFIG.get_forward_key()
    HOTKEY_COPY_EXTRACTED_ROWS = CONFIG.get_copy_extracted_rows_key()
    HOTKEY_COPY_ID = CONFIG.get_copy_id_key()
    HOTKEY_DOWNLOAD_EXTRACTED_ROWS = CONFIG.get_download_extracted_rows_key()
    HOTKEY_REJECT = CONFIG.get_reject_key()
    DEFAULT_REJECT_FILE = CONFIG.get_reject_file()
    DEFAULT_REJECT_ID_FILE = CONFIG.get_reject_id_file()


def SET_BACK_KEY(key):
    CONFIG.set_back_key(key)
    _refresh_globals()


def SET_FORWARD_KEY(key):
    CONFIG.set_forward_key(key)
    _refresh_globals()


def SET_COPY_EXTRACTED_ROWS_KEY(key):
    CONFIG.set_copy_extracted_rows_key(key)
    _refresh_globals()


def SET_COPY_ID_KEY(key):
    CONFIG.set_copy_id_key(key)
    _refresh_globals()


def SET_DOWNLOAD_EXTRACTED_ROWS_KEY(key):
    CONFIG.set_download_extracted_rows_key(key)
    _refresh_globals()


def SET_REJECT_KEY(key):
    CONFIG.set_reject_key(key)
    _refresh_globals()


def SET_REJECT_FILE(path):
    CONFIG.set_reject_file(path)
    _refresh_globals()


def SET_REJECT_ID_FILE(path):
    CONFIG.set_reject_id_file(path)
    _refresh_globals()


def SET_SPOT_CHECK_PROMPT(prompt: str):
    CONFIG.set_spot_check_prompt(prompt)


def SET_SPOT_CHECK_SCHEMA(schema: dict):
    CONFIG.set_spot_check_schema(schema)


def SET_SPOT_CHECK_VERDICT_COLORS(colors: dict):
    CONFIG.set_spot_check_verdict_colors(colors)


def build_spot_check_prompt(context: str, rows_json: str) -> str:
    prompt = CONFIG.get_spot_check_prompt()
    return f"{prompt}\nSource text:\n{context}\n\nExtracted data:\n{rows_json}"