"""
vertex_ai_client.py
--------------------
Standardized Vertex AI client using the google-genai SDK.

Environment variables (in .env/.env):
    VERTEX_PROJECT_ID   - Your GCP project ID
    VERTEX_LOCATION     - Region, e.g. "us-central1"
    VERTEX_TEXT_MODEL   - Model name, e.g. "gemini-2.0-flash-exp"
"""

import json
import logging
import os
import random
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env/.env'))


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------

def create_vertex_client() -> genai.Client:
    """
    Creates and returns a Vertex AI genai.Client.

    Requires VERTEX_PROJECT_ID and VERTEX_LOCATION in the environment.
    """
    project_id = os.getenv("VERTEX_PROJECT_ID")
    location   = os.getenv("VERTEX_LOCATION", "us-central1")

    if not project_id:
        raise EnvironmentError("VERTEX_PROJECT_ID is not set in the environment.")

    return genai.Client(
        vertexai=True,
        project=project_id,
        location=location,
    )


# ---------------------------------------------------------------------------
# Core call wrapper
# ---------------------------------------------------------------------------

def call_vertex_json(
    client: genai.Client,
    model: str,
    prompt: str,
    system_instruction: str,
    max_output_tokens: int = 50000,
    temperature: float = 0.7,
    max_retries: int = 5,
    base_delay: float = 5.0,
) -> dict | None:
    """
    Calls the Vertex AI model and returns a parsed JSON dict.

    Retries automatically on 429 / RESOURCE_EXHAUSTED and 503 / UNAVAILABLE
    using exponential backoff (capped at 60 s).

    Returns:
        Parsed dict on success, or None if all retries fail.

    Raises:
        Exception for non-retryable errors.
    """
    config = types.GenerateContentConfig(
        max_output_tokens=max_output_tokens,
        temperature=temperature,
        response_mime_type="application/json",
        system_instruction=system_instruction,
    )

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model,
                contents=[prompt],
                config=config,
            )
            if response.text:
                return json.loads(response.text)
            return None

        except Exception as e:
            error_str = str(e)

            retryable = (
                "429" in error_str or "RESOURCE_EXHAUSTED" in error_str
                or "503" in error_str or "UNAVAILABLE" in error_str
            )

            if retryable and attempt < max_retries - 1:
                delay = min((base_delay * (2 ** attempt)) + random.uniform(0, 1), 60.0)
                logging.warning(
                    f"Vertex AI transient error ({error_str}). "
                    f"Retrying in {delay:.2f}s... (attempt {attempt + 1}/{max_retries})"
                )
                time.sleep(delay)
            else:
                logging.error(f"Vertex AI call failed: {e}")
                raise

    return None


# ---------------------------------------------------------------------------
# Quota check
# ---------------------------------------------------------------------------

def check_vertex_quota(client: genai.Client, model: str) -> bool:
    """
    Sends a minimal request to verify the model is reachable and quota is OK.

    Returns True if OK, False if quota is exhausted.
    """
    try:
        client.models.generate_content(model=model, contents=["say ok"])
        return True
    except Exception as e:
        if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
            return False
        return True   # Other errors don't necessarily mean quota is gone


# ---------------------------------------------------------------------------
# Example usage
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    model = os.getenv("VERTEX_TEXT_MODEL", "gemini-2.0-flash-exp")
    client = create_vertex_client()

    logging.info("Checking Vertex AI quota...")
    if not check_vertex_quota(client, model):
        logging.error("Quota exhausted — cannot proceed.")
        raise SystemExit(1)
    logging.info("Quota OK.")

    result = call_vertex_json(
        client=client,
        model=model,
        prompt="List three colors as JSON: {\"colors\": [...]}",
        system_instruction="You are a helpful assistant. Respond only with valid JSON.",
    )

    print(json.dumps(result, indent=2))