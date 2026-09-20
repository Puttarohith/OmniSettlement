"""
Ledger Writer Service
Executes atomic multi-party ledger updates using DynamoDB TransactWriteItems.
Guarantees all-or-nothing consistency across Customer, Merchant, Driver, and Platform accounts.
"""
import os
import time
from typing import Dict, Any, List
import boto3
from botocore.exceptions import ClientError


LEDGER_TABLE_NAME = os.environ.get("MARKETPLACE_LEDGER_TABLE", "MarketplaceLedger")


def build_transact_items(plan_data: Dict[str, Any], table_name: str) -> List[Dict[str, Any]]:
    """
    Constructs DynamoDB TransactWriteItems list.
    For each disbursement:
    1. Appends an immutable Journal Entry record.
    2. Atomically updates the account running balance.
    """
    transact_items = []
    now_ts = int(time.time())
    plan_id = plan_data["plan_id"]
    order_id = plan_data["order_id"]
    
    for item in plan_data["disbursements"]:
        account_id = item["account_id"]
        party_type = item["party_type"]
        delta_amount = str(item["delta_amount"])
        reason_code = item["reason_code"]
        entry_id = f"ENTRY#{order_id}#{account_id}#{now_ts}"
        
        # 1. Put Immutable Journal Line Item
        transact_items.append({
            "Put": {
                "TableName": table_name,
                "Item": {
                    "account_id": {"S": account_id},
                    "entry_id": {"S": entry_id},
                    "order_id": {"S": order_id},
                    "plan_id": {"S": plan_id},
                    "party_type": {"S": party_type},
                    "delta_amount": {"N": delta_amount},
                    "reason_code": {"S": reason_code},
                    "created_at": {"N": str(now_ts)},
                    "status": {"S": "COMMITTED"}
                },
                "ConditionExpression": "attribute_not_exists(entry_id)"
            }
        })
        
        # 2. Update Running Balance on Account Metadata Entry
        transact_items.append({
            "Update": {
                "TableName": table_name,
                "Key": {
                    "account_id": {"S": account_id},
                    "entry_id": {"S": "ACCOUNT_SUMMARY"}
                },
                "UpdateExpression": "ADD current_balance :delta SET last_updated = :ts, party_type = if_not_exists(party_type, :pt)",
                "ExpressionAttributeValues": {
                    ":delta": {"N": delta_amount},
                    ":ts": {"N": str(now_ts)},
                    ":pt": {"S": party_type}
                }
            }
        })
        
    return transact_items


def commit_ledger_transaction(plan_data: Dict[str, Any]) -> Dict[str, Any]:
    """Commits DynamoDB transaction."""
    dynamodb = boto3.client("dynamodb")
    transact_items = build_transact_items(plan_data, LEDGER_TABLE_NAME)
    
    try:
        dynamodb.transact_write_items(TransactItems=transact_items)
        return {
            "status": "COMMITTED",
            "plan_id": plan_data["plan_id"],
            "order_id": plan_data["order_id"],
            "transaction_item_count": len(transact_items)
        }
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        cancellation_reasons = e.response.get("CancellationReasons", [])
        return {
            "status": "TRANSACTION_FAILED",
            "error_code": error_code,
            "cancellation_reasons": cancellation_reasons,
            "message": str(e)
        }


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """AWS Lambda Handler for Step Functions state machine."""
    plan_data = event.get("settlement_plan", {})
    
    if plan_data.get("requires_human_review"):
        # Route to pending review state
        return {
            "status": "PENDING_HUMAN_REVIEW",
            "order_id": event.get("order_id"),
            "plan_id": plan_data.get("plan_id"),
            "review_reason": plan_data.get("review_reason")
        }
        
    result = commit_ledger_transaction(plan_data)
    output = dict(event)
    output["ledger_commit_result"] = result
    return output
