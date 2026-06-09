DEFAULT_LLM_PROVIDER = "google"   # openai | google

DEFAULT_MODEL_NAME_MAPPING = {
    "google": "gemini-3.1-flash-lite",
    "openai": "gpt-4.1-mini"
}
DEFAULT_MODEL_NAME = DEFAULT_MODEL_NAME_MAPPING[DEFAULT_LLM_PROVIDER]