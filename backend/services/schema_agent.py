from typing import Dict, Any
import logging
import json
import os

from models.schema import SchemaRequest, SchemaResponse
from openai import OpenAI
from services import db

logger = logging.getLogger(__name__)

REFERENCE_PATH = os.path.join(os.path.dirname(__file__), "../data/mavlink_reference.json")
with open(REFERENCE_PATH, "r") as f:
    LOG_REFERENCE = json.load(f)

# Initialize OpenAI client lazily
client = None

def get_openai_client():
    global client
    if client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")
        client = OpenAI(api_key=api_key)
    return client


def process_schema(req: SchemaRequest) -> SchemaResponse:
    """
    Normalize schema info, enrich with reference docs,
    and generate natural-language summary with an LLM.
    """

    # Delete existing database to start fresh
    db_path = "telemetry.duckdb"
    if os.path.exists(db_path):
        os.remove(db_path)
        logger.info(f"Deleted existing database: {db_path}")

    # Early return for empty schema data
    if not req.fieldStructure:
        return SchemaResponse(
            status="ok",
            message="No schema data provided.",
            normalizedSchema={},
            summary="",
        )

    normalized_schema: Dict[str, Any] = {}
    enriched_schema: Dict[str, Any] = {}

    for msg_type, struct in req.fieldStructure.items():
        table_name = msg_type.lower()
        fields = [f.lower() for f in struct.fields]

        normalized_schema[table_name] = {
            "fields": fields,
            "sampleCount": struct.sampleCount,
        }

        # Add enrichment from local reference (if available)
        reference = LOG_REFERENCE.get(msg_type.upper(), {})
        enriched_schema[table_name] = {
            "fields": fields,
            "sampleCount": struct.sampleCount,
            "description": reference.get("description", "No reference available"),
            "fieldDescriptions": reference.get("fields", {}),
        }

    try:
        llm_prompt = f"""
        You are a schema analysis assistant. 
        The following normalized schema was extracted from a flight log (logType={req.logType}).
        For each message type, explain what it represents and the role of its fields. 
        Keep the explanation concise and technical, suitable for downstream analysis.

        Schema (enriched with reference docs):
        {json.dumps(enriched_schema, indent=2)}
        """

        logger.info("=== SCHEMA AGENT PROMPTING LLM ===")
        llm_response = get_openai_client().chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You summarize UAV telemetry schemas."},
                {"role": "user", "content": llm_prompt},
            ],
            max_tokens=15000,
        )
        summary_text = llm_response.choices[0].message.content
    except Exception as e:
        logger.error(f"LLM summarization failed: {e}")
        summary_text = "Summary unavailable due to LLM error."

    # Create database tables from schema
    logger.info("=== CREATING DATABASE TABLES ===")
    db.create_tables_from_schema(normalized_schema, enriched_schema)
    logger.info("=== DATABASE TABLES CREATED ===")

    # Log the output for debugging
    logger.info("=== SCHEMA AGENT SUMMARY ===")
    logger.info(summary_text)
    logger.info("=== ENRICHED SCHEMA ===")
    logger.info(json.dumps(enriched_schema, indent=2))
    logger.info("============================")

    return SchemaResponse(
        status="ok",
        message=f"Processed {len(normalized_schema)} message types for logType {req.logType}",
        normalizedSchema=normalized_schema,
        summary=summary_text,
    )
