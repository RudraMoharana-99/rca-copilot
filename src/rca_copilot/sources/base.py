from abc import ABC, abstractmethod
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

# ============================================================
# ===================METRICS==================================
# ============================================================


class Status(StrEnum):
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


# ============================================================
# ===================JAEGER TRACES===============================
# ============================================================


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


# ============================================================
# ===================CHANGE LOG===============================
# ============================================================


class ChangeType(StrEnum):
    DEPLOY = "DEPLOY"
    CONFIG = "CONFIG"
    FLAG = "FLAG"
    SCALE = "SCALE"


class ChangeRecord(BaseModel):
    timestamp: datetime
    service: str
    change_type: ChangeType
    summary: str
    author: str | None = None
    details: str | None = None


class ChangeQueryResult(BaseModel):
    status: Status
    changes: list[ChangeRecord] = Field(default_factory=list)


class ChangelogSource(ABC):
    @abstractmethod
    def query_changes(
        self,
        start: datetime,
        end: datetime,
        service: str | None = None,
    ) -> ChangeQueryResult:
        pass


# ==================================================================
# ============================LoGS==================================
# ==================================================================


class Severity(StrEnum):
    TRACE = "TRACE"
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    FATAL = "FATAL"


class LogEntry(BaseModel):
    timestamp: datetime
    service: str
    severity: Severity
    severity_number: int
    message: str
    trace_id: str | None = None


class LogQueryResult(BaseModel):
    status: Status
    logs: list[LogEntry] = Field(default_factory=list)
    count: int = 0
    truncated: bool = False


class LogsSource(ABC):
    @abstractmethod
    def query_logs(
        self,
        start: datetime,
        end: datetime,
        service: str | None = None,
        min_severity: Severity | None = None,
        limit: int = 100,
    ) -> LogQueryResult:
        pass
