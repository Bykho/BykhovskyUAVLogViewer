import logging
from typing import Any, Dict
from models.data_Ag import DataAgentResponse
from services import db

logger = logging.getLogger(__name__)

def run_data_agent(task_spec: dict, intent: str) -> DataAgentResponse:
    
    # Get schema bundle and DB connection "baked in" automatically
    schema_bundle = get_schema_bundle()
    db_connection = db.get_connection()
    
    # Log all inputs clearly for debugging
    logger.info("=== DATA AGENT INPUTS ===")
    logger.info(f"Task Spec: {task_spec}")
    logger.info(f"Schema Bundle Keys: {list(schema_bundle.keys()) if schema_bundle else 'None'}")
    logger.info(f"DB Connection Type: {type(db_connection).__name__}")
    logger.info(f"Intent: {intent}")
    logger.info("=========================")
    
    # Return placeholder response
    return DataAgentResponse(
        ok=True,
        data=None,
        executed_code=None,
        errors=[],
        logs=["Inputs received and logged."]
    )

def get_schema_bundle() -> dict:
    """
    Get the current schema bundle from the schema agent.
    This is "baked in" - no need to pass it as a parameter.
    """
    # For now, return a placeholder. Later this will read from the schema agent's output
    # or from a shared state/cache
    return {
        "message_types": ["system_time", "global_position_int", "attitude"],
        "enriched_schema": {},
        "normalized_schema": {}
    }
