from pydantic import BaseModel
from typing import Any, List, Optional, Dict

class DataAgentResponse(BaseModel):
    ok: bool
    data: Optional[Any]
    executed_code: Optional[str]
    errors: List[str] = []
    logs: List[str] = []
    attempts: Optional[List[Dict]] = None  # Full attempt history for debugging/planner
