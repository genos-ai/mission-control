"""Client error reporting schemas."""

from pydantic import BaseModel, Field


class ClientErrorReport(BaseModel):
    """Error report sent by frontend clients."""

    message: str = Field(..., max_length=2000)
    stack: str | None = Field(None, max_length=10000)
    component_stack: str | None = Field(None, max_length=5000)
    url: str = Field(..., max_length=2000)
    user_agent: str | None = Field(None, max_length=500)
    timestamp: str | None = None


class ClientErrorReceived(BaseModel):
    """Response confirming error was logged."""

    received: bool = True
