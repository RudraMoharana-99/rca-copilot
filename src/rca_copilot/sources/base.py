from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Status(str, Enum):
    SUCCESS = "SUCCESS"
    NO_DATA = "NO_DATA"
    ERROR = "ERROR"


class DataPoint(BaseModel):
    timestamp: datetime
    value: float


class Series(BaseModel):
    labels: dict[str, str]
    points: list[DataPoint]


class MetricsQueryResult(BaseModel):
    status: Status
    series: list[Series] = Field(default_factory=list)


class MetricsSource(ABC):
    @abstractmethod
    def query_metrics(
        self,
        query_name: str,
        start: datetime,
        end: datetime,
    ) -> MetricsQueryResult:
        pass


class Span(BaseModel):
    span_id: str
    parent_span_id: str | None = None
    service_name: str
    operation_name: str
    start_time: datetime
    end_time: datetime
    is_error: bool = False
    attributes: dict[str, str | int | float | bool] = Field(default_factory=dict)


class Trace(BaseModel):
    trace_id: str
    spans: list[Span] = Field(default_factory=list)


class ServiceSummary(BaseModel):
    name: str
    span_count: int
    error_span_count: int = 0


class TraceSummary(BaseModel):
    trace_id: str
    root_service: str | None = None
    span_count: int
    error_count: int = 0

    start_time: datetime
    end_time: datetime

    services: list[ServiceSummary] = Field(default_factory=list)


class TraceQueryResult(BaseModel):
    status: Status
    summaries: list[TraceSummary] = Field(default_factory=list)


class TraceDetailResult(BaseModel):
    status: Status
    trace: Trace | None = None


class TracesSource(ABC):
    @abstractmethod
    def query_trace_summaries(
        self,
        service: str | None,
        start: datetime,
        end: datetime,
        limit: int = 20,
    ) -> TraceQueryResult:
        pass

    @abstractmethod
    def get_trace(
        self,
        trace_id: str,
    ) -> TraceDetailResult:
        pass
