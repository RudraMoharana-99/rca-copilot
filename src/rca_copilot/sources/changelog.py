import json
from datetime import datetime

from pydantic import ValidationError

from .base import ChangelogSource, ChangeQueryResult, ChangeRecord, Status


class SnapshotChangesSource(ChangelogSource):
    def __init__(self, file_path: str):
        self.file_path = file_path

    def query_changes(
        self,
        start: datetime,
        end: datetime,
        service: str | None = None,
    ) -> ChangeQueryResult:
        try:
            with open(self.file_path, encoding="utf-8") as f:
                records = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return ChangeQueryResult(status=Status.ERROR)

        matches = []

        for record in records:
            timestamp = datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00"))
            if not (start <= timestamp <= end):
                continue
            if service is not None and record["service"] != service:
                continue
            matches.append(record)

        if not matches:
            return ChangeQueryResult(status=Status.NO_DATA)
        try:
            changes = [ChangeRecord(**record) for record in matches]
        except ValidationError:
            return ChangeQueryResult(status=Status.ERROR)

        return ChangeQueryResult(status=Status.SUCCESS, changes=changes)
