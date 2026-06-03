from datetime import datetime
from typing import Dict, Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator

EVENT_TYPES = {
    'ENTRY',
    'EXIT',
    'ZONE_ENTER',
    'ZONE_EXIT',
    'ZONE_DWELL',
    'BILLING_QUEUE_JOIN',
    'BILLING_QUEUE_ABANDON',
    'PURCHASE',
    'REENTRY'
}


class EventMetadata(BaseModel):
    model_config = ConfigDict(extra='forbid')
    queue_depth: Optional[int] = None
    sku_zone: Optional[str] = None
    session_seq: int = Field(..., ge=1)
    group_size: Optional[int] = None


class EventIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    event_id: str = Field(..., min_length=1)
    store_id: str = Field(..., min_length=1)
    camera_id: str = Field(..., min_length=1)
    visitor_id: str = Field(..., min_length=1)
    event_type: str = Field(..., min_length=1)
    timestamp: datetime
    zone_id: Optional[str] = None
    dwell_ms: int = Field(ge=0)
    is_staff: bool
    confidence: float = Field(ge=0.0, le=1.0)
    metadata: EventMetadata

    @field_validator('event_type')
    def validate_event_type(cls, value):
        if value not in EVENT_TYPES:
            raise ValueError(f'event_type must be one of {sorted(EVENT_TYPES)}')
        return value

    @field_validator('zone_id', mode='before')
    def zone_id_required_for_zone_events(cls, value, info):
        event_type = info.data.get('event_type')
        if event_type in {'ZONE_ENTER', 'ZONE_EXIT', 'ZONE_DWELL', 'BILLING_QUEUE_JOIN', 'BILLING_QUEUE_ABANDON'} and not value:
            raise ValueError('zone_id is required for zone and billing events')
        if event_type in {'ENTRY', 'EXIT', 'REENTRY'} and value is not None:
            raise ValueError('zone_id must be null for ENTRY, EXIT, and REENTRY events')
        return value

    @field_validator('metadata')
    def validate_event_metadata(cls, value, info):
        event_type = info.data.get('event_type')
        if event_type in {'ZONE_ENTER', 'ZONE_EXIT', 'ZONE_DWELL', 'BILLING_QUEUE_JOIN', 'BILLING_QUEUE_ABANDON'} and value.sku_zone is None:
            raise ValueError('metadata.sku_zone is required for zone and billing events')
        if event_type == 'BILLING_QUEUE_JOIN' and value.queue_depth is None:
            raise ValueError('metadata.queue_depth is required for BILLING_QUEUE_JOIN')
        if event_type in {'ENTRY', 'EXIT', 'REENTRY'} and value.sku_zone is not None:
            raise ValueError('metadata.sku_zone must be null for ENTRY, EXIT, and REENTRY events')
        return value


class EventIngestResult(BaseModel):
    accepted: int
    duplicates: int
    rejected: int
    errors: Dict[int, str]


class HealthResponse(BaseModel):
    status: str
    last_event_timestamp: Optional[datetime]
    stale_feed: bool
    store_status: Dict[str, str]


class ErrorResponse(BaseModel):
    detail: str
    errors: Optional[Dict[int, str]] = None
