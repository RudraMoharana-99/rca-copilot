from abc import ABC, abstractmethod
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Status(str, StrEnum):
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
