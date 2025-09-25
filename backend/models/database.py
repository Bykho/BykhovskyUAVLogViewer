from pydantic import BaseModel
from typing import Dict, List, Any

class DataIngestionRequest(BaseModel):
    messageType: str  # e.g., "SYSTEM_TIME", "AHRS", etc.
    rows: List[Dict[str, Any]]  # List of data rows for this message type

class DataIngestionResponse(BaseModel):
    status: str
    message: str
    rowsInserted: int
