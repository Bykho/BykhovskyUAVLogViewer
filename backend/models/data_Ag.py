from pydantic import BaseModel
from typing import Any, List, Optional

class DataAgentResponse(BaseModel):
    ok: bool
    data: Optional[Any]
    executed_code: Optional[str]
    errors: List[str] = []
    logs: List[str] = []
