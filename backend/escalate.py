# escalation.py
import json
import os
from typing import Any, Dict
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def escalate(context: Dict[str, Any]) -> Dict[str, str]:
    """
    Send a blob of context (question, candidate_answer, telemetry, etc.)
    to a larger model to validate. Always returns:
      { "verdict": "accept"|"reject", "notes": "string" }
    """
    # Wrap the context into a prompt
    messages = [
        {
            "role": "system",
            "content": (
                "You are a reliability reviewer for UAV telemetry findings. "
                "Use cross-stream evidence, temporal consistency, and sensor health. "
                "Decide if the candidate answer is valid. If valid, return 'accept' and "
                "write notes on corroboration. If invalid, return 'reject' and notes on "
                "what the main agent should do instead. "
                "Respond ONLY with JSON in the format: "
                '{"verdict": "accept"|"reject", "notes": "string"}'
            ),
        },
        {
            "role": "user",
            "content": json.dumps(context, indent=2),
        },
    ]

    try:
        # Call a bigger model (swap model name as needed)
        response = client.chat.completions.create(
            model="gpt-5-mini",
            messages=messages,
        )

        raw_output = response.choices[0].message.content.strip()

        # Try to parse as JSON
        result = json.loads(raw_output)

        # Enforce required keys
        verdict = result.get("verdict", "").lower()
        notes = result.get("notes", "")

        if verdict not in ("accept", "reject"):
            raise ValueError("Invalid verdict value")

        return {"verdict": verdict, "notes": notes}

    except Exception as e:
        # Fail safe fallback
        return {
            "verdict": "reject",
            "notes": f"Could not validate reliably ({e}). "
                     "Default to corroborating with the most reliable stream and "
                     "explain uncertainty to the user."
        }
