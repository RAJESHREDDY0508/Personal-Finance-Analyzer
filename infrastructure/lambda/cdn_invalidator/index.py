import json
import boto3
import time


def lambda_handler(event, context):
    client = boto3.client("cloudfront")
    response = client.create_invalidation(
        DistributionId="E2MLNC5BXP0IGT",
        InvalidationBatch={
            "Paths": {
                "Quantity": 1,
                "Items": [
                    "/*",
                ],
            },
            "CallerReference": str(time.time()).replace(".", ""),
        },
    )
    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "InvalidationId": response["Invalidation"]["Id"],
                "Status": response["Invalidation"]["Status"],
            }
        ),
    }
