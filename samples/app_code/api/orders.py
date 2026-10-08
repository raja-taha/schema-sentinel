"""Sample FastAPI handlers that reference orders.status — used for blast-radius search."""

from fastapi import APIRouter, Query

router = APIRouter()


@router.get("/orders")
async def list_orders(status: str = Query(default="pending")):
    # Raw SQL still filters on orders.status
    query = "SELECT id, status FROM orders WHERE status = :status"
    return {"query": query, "status": status}


@router.patch("/orders/{order_id}")
async def update_order_status(order_id: int, status: str):
    query = "UPDATE orders SET status = :status WHERE id = :id"
    return {"order_id": order_id, "status": status, "query": query}
