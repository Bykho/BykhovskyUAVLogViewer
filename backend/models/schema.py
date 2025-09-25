from pydantic import BaseModel
from typing import Dict, List, Any

class FieldStructure(BaseModel):
    fields: List[str]
    sampleCount: int

class SchemaRequest(BaseModel):
    messageTypes: List[str]
    logType: str
    metadata: Dict[str, Any] = {}
    fieldStructure: Dict[str, FieldStructure]

class SchemaResponse(BaseModel):
    status: str
    message: str
    normalizedSchema: Dict[str, Any]
    summary: str