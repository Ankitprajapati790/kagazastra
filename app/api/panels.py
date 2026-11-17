import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.database import get_database
from app.models.schemas import ClientStatusRequest, PaymentStatusRequest, UPIPaymentRequest
from app.services.auth import require_admin, require_client, require_csrf

router = APIRouter(tags=["panels"])

PLANS = {
    "sachet_20": {"name": "Exam Pass Sachet", "amount": 20},
    "sachet_50": {"name": "Aspirant Pro", "amount": 50},
    "cafe_vip_100": {"name": "Cyber Café VIP", "amount": 100},
}


def _database():
    database = get_database()
    if database is None:
        raise HTTPException(status_code=503, detail="Account service is unavailable. Check MongoDB.")
    return database


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _payment_summary(payment: dict[str, Any], user: dict[str, Any] | None = None) -> dict[str, Any]:
    plan = PLANS.get(payment.get("plan_id"), {})
    summary = {
        "id": str(payment.get("transaction_id", payment.get("_id", ""))),
        "transaction_id": payment.get("transaction_id"),
        "user_id": payment.get("user_id"),
        "plan_id": payment.get("plan_id"),
        "plan_name": plan.get("name", "Unknown plan"),
        "amount": payment.get("amount"),
        "status": payment.get("status"),
        "created_at": _iso(payment.get("created_at")),
        "reviewed_at": _iso(payment.get("reviewed_at")),
        "paid_at": _iso(payment.get("paid_at")),
    }
    if user:
        summary["client_name"] = user.get("full_name")
        summary["client_email"] = user.get("email")
        summary["client_active"] = user.get("active", False)
    return summary


async def _recent_payments(database, user_id: str | None = None, limit: int = 20):
    query = {"user_id": user_id} if user_id else {}
    cursor = database.payments.find(query, {"_id": 0}).sort("created_at", -1).limit(limit)
    return [_payment_summary(item) async for item in cursor]


async def _recent_usage(database, user_id: str | None = None, limit: int = 20):
    query = {"user_id": user_id} if user_id else {}
    cursor = database.usage.find(query, {"_id": 0}).sort("created_at", -1).limit(limit)
    return [
        {
            "feature": item.get("feature"),
            "detail": item.get("detail"),
            "created_at": _iso(item.get("created_at")),
        }
        async for item in cursor
    ]


@router.get("/client/dashboard")
async def client_dashboard(user: dict[str, Any] = Depends(require_client)):
    database = _database()
    user_id = user["id"]
    now = datetime.now(timezone.utc)
    payments = await _recent_payments(database, user_id)
    paid_payment = next((payment for payment in payments if payment["status"] == "paid"), None)
    plan_expires_at = None
    active_plan = None
    if paid_payment and paid_payment["paid_at"]:
        paid_at = datetime.fromisoformat(paid_payment["paid_at"])
        if paid_at.tzinfo is None:
            paid_at = paid_at.replace(tzinfo=timezone.utc)
        plan_expires_at = paid_at + timedelta(days=30)
        if plan_expires_at > now:
            active_plan = {
                "id": paid_payment["plan_id"],
                "name": paid_payment["plan_name"],
                "expires_at": _iso(plan_expires_at),
            }

    return {
        "user": {
            "id": user["id"],
            "full_name": user["full_name"],
            "email": user["email"],
            "created_at": _iso(user.get("created_at")),
        },
        "active_plan": active_plan,
        "usage_count": await database.usage.count_documents({"user_id": user_id}),
        "usage": await _recent_usage(database, user_id),
        "payments": payments,
    }


@router.get("/admin/dashboard")
async def admin_dashboard(admin: dict[str, Any] = Depends(require_admin)):
    del admin
    database = _database()
    payment_counts = {
        status: await database.payments.count_documents({"status": status})
        for status in ("pending", "paid", "rejected")
    }
    users = await database.users.count_documents({"role": "client"})
    active_users = await database.users.count_documents({"role": "client", "active": True})
    return {
        "stats": {
            "clients": users,
            "active_clients": active_users,
            "pending_payments": payment_counts["pending"],
            "approved_payments": payment_counts["paid"],
            "rejected_payments": payment_counts["rejected"],
            "usage_events": await database.usage.count_documents({}),
        },
        "recent_users": await _list_users(database, "", 10),
        "recent_payments": await _list_payments(database, "all", 10),
    }


async def _list_users(database, search: str, limit: int):
    query: dict[str, Any] = {"role": "client"}
    if search:
        escaped = re.escape(search.strip())[:80]
        query["$or"] = [
            {"full_name": {"$regex": escaped, "$options": "i"}},
            {"email": {"$regex": escaped, "$options": "i"}},
        ]
    cursor = database.users.find(query, {"_id": 0, "password_hash": 0}).sort("created_at", -1).limit(limit)
    return [
        {
            "id": user["id"],
            "full_name": user["full_name"],
            "email": user["email"],
            "active": user.get("active", False),
            "created_at": _iso(user.get("created_at")),
        }
        async for user in cursor
    ]


async def _list_payments(database, status: str, limit: int):
    query = {} if status == "all" else {"status": status}
    cursor = database.payments.find(query, {"_id": 0}).sort("created_at", -1).limit(limit)
    payments = [item async for item in cursor]
    user_ids = list({item["user_id"] for item in payments})
    users_by_id = {}
    if user_ids:
        users = database.users.find({"id": {"$in": user_ids}}, {"_id": 0, "password_hash": 0})
        users_by_id = {user["id"]: user async for user in users}
    return [
        _payment_summary(payment, users_by_id.get(payment.get("user_id")))
        for payment in payments
    ]


@router.get("/admin/users")
async def admin_users(
    search: str = Query(default="", max_length=80),
    limit: int = Query(default=100, ge=1, le=200),
    admin: dict[str, Any] = Depends(require_admin),
):
    del admin
    return {"users": await _list_users(_database(), search, limit)}


@router.patch("/admin/users/{user_id}", dependencies=[Depends(require_csrf)])
async def set_client_status(
    user_id: str,
    payload: ClientStatusRequest,
    admin: dict[str, Any] = Depends(require_admin),
):
    del admin
    database = _database()
    result = await database.users.update_one(
        {"id": user_id, "role": "client"},
        {"$set": {"active": payload.active}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Client account was not found.")
    if not payload.active:
        await database.sessions.delete_many({"user_id": user_id})
    return {"id": user_id, "active": payload.active}


@router.get("/admin/payments")
async def admin_payments(
    status: str = Query(default="all", pattern="^(all|pending|paid|rejected)$"),
    limit: int = Query(default=100, ge=1, le=200),
    admin: dict[str, Any] = Depends(require_admin),
):
    del admin
    return {"payments": await _list_payments(_database(), status, limit)}


@router.patch("/admin/payments/{transaction_id}")
async def review_payment(
    transaction_id: str,
    payload: PaymentStatusRequest,
    admin: dict[str, Any] = Depends(require_admin),
    csrf_user: dict[str, Any] = Depends(require_csrf),
):
    if admin["id"] != csrf_user["id"]:
        raise HTTPException(status_code=403, detail="Request verification failed.")
    database = _database()
    payment = await database.payments.find_one(
        {"transaction_id": transaction_id, "status": "pending"}
    )
    if payment is None:
        raise HTTPException(status_code=404, detail="Pending payment request was not found.")

    user = await database.users.find_one({"id": payment["user_id"], "role": "client"})
    if user is None:
        raise HTTPException(status_code=404, detail="Payment's client account was not found.")
    if payload.status == "paid" and not user.get("active", False):
        raise HTTPException(status_code=409, detail="Activate the client account before approving payment.")

    now = datetime.now(timezone.utc)
    update_fields = {"status": payload.status, "reviewed_at": now, "reviewed_by": admin["id"]}
    if payload.status == "paid":
        update_fields["paid_at"] = now
    result = await database.payments.update_one(
        {"_id": payment["_id"], "status": "pending"},
        {"$set": update_fields},
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=409, detail="This payment was already reviewed.")
    return _payment_summary({**payment, **update_fields}, user)


@router.post("/billing/create-upi-order", status_code=201)
async def create_upi_order(
    order: UPIPaymentRequest,
    user: dict[str, Any] = Depends(require_csrf),
):
    plan = PLANS.get(order.plan_id)
    if plan is None:
        raise HTTPException(status_code=422, detail="Choose a valid plan.")

    database = _database()
    transaction_id = f"KA-{secrets.token_hex(8).upper()}"
    payment = {
        "transaction_id": transaction_id,
        "user_id": user["id"],
        "plan_id": order.plan_id,
        "amount": plan["amount"],
        "status": "pending",
        "created_at": datetime.now(timezone.utc),
    }
    await database.payments.insert_one(payment)
    return {
        **_payment_summary(payment),
        "message": "Demo request created. Admin approval is required; this is not a verified UPI payment.",
    }
