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
    
    # Extract current context and history for the escalator to review
    current_context = context.get("current", {})
    history = context.get("history", [])
    
    # Build context string that includes history
    context_string = f"CURRENT CONTEXT:\n{json.dumps(current_context, indent=2)}\n\n"
    
    if history:
        context_string += f"CONVERSATION HISTORY:\n"
        for i, hist in enumerate(history[-3:], 1):  # Show last 3 history entries
            context_string += f"Previous attempt {i}:\n{json.dumps(hist, indent=2)}\n\n"
    
    # Wrap the context into a prompt
    messages = [
        {
            "role": "system",
            "content": (
                "You are a reliability reviewer for UAV telemetry findings. "
                "Your job is to prevent premature, incorrect, or overconfident conclusions. "
                "Always check for these known failure modes:\n"
                "1. Trust in single data points — A lone minimum or maximum is not reliable without context or uncertainty. "
                "2. Incomplete error propagation — If a stream is missing or degraded, recommend fallback strategies "
                "and make sure degraded quality is acknowledged. "
                "3. Statistical blind spots — Outlier detection on downsampled data may miss raw anomalies. "
                "Encourage use of higher-frequency data when spikes/glitches are suspected. "
                "4. Lack of cross-stream validation — Values must be cross-checked with other altitude or sensor streams "
                "before being marked as true anomalies.\n\n"
                "IMPORTANT: If you see repeated similar contexts in the conversation history, "
                "this indicates the agent is stuck in a loop. In such cases, be more "
                "direct about the core conceptual error that needs to be corrected.\n\n"
                "Decision Rules:\n"
                "- If the candidate answer accounts for these checks and seems valid → return 'accept' with notes "
                "summarizing corroboration.\n"
                "- If the candidate answer misses or mishandles any of these areas → return 'reject' with notes "
                "explaining what the main agent should do instead (e.g., cross-check GPS/baro, retry on raw data, "
                "fall back to another stream).\n\n"
                "Be concise. "
                "Respond ONLY with JSON in the format: "
                '{"verdict": "accept"|"reject", "notes": "BRIEF guidance in 75 words or less"}'
            ),
        },
        {
            "role": "user",
            "content": context_string,
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
