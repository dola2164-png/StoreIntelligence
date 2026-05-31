from fastapi import HTTPException


class ServiceUnavailable(HTTPException):
    def __init__(self, detail: str = "Service unavailable"):
        super().__init__(status_code=503, detail=detail)
