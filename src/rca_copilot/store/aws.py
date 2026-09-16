import os
from functools import lru_cache

import boto3
from botocore.exceptions import ClientError

from rca_copilot.models import IncidentResponse

TABLE_NAME = os.environ.get("INCIDENTS_TABLE", "rca-copilot-incidents")
REGION = os.environ.get("AWS_REGION", "ap-south-1")


@lru_cache(maxsize=1)
def _table():
    return boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)


def put_incident(response: IncidentResponse) -> None:
    _table().put_item(
        Item={
            "incident_id": response.incident_id,
            "response": response.model_dump_json(),
        }
    )


def get_incident(incident_id: str) -> IncidentResponse | None:
    try:
        result = _table().get_item(Key={"incident_id": incident_id})
    except ClientError:
        return None

    item = result.get("Item")

    if item is None:
        return None

    return IncidentResponse.model_validate_json(item["response"])