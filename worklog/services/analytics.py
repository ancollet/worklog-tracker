"""Aggregation queries for the analytics tab."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Bucket(str, Enum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class GroupBy(str, Enum):
    NONE = "none"
    PROJECT = "project"
    CUSTOMER = "customer"


@dataclass(slots=True)
class AggRow:
    bucket: str       # e.g. '2026-05-08' or '2026-W19' or '2026-05'
    group_label: str  # project/customer name, or '—'
    seconds: int


_BUCKET_FORMAT = {
    Bucket.DAY: "%Y-%m-%d",
    Bucket.WEEK: "%Y-W%W",
    Bucket.MONTH: "%Y-%m",
}


def aggregate(
    conn: sqlite3.Connection,
    *,
    from_iso: str,
    to_iso: str,
    bucket: Bucket,
    group_by: GroupBy,
    customer_id: Optional[int] = None,
    project_id: Optional[int] = None,
) -> list[AggRow]:
    fmt = _BUCKET_FORMAT[bucket]
    if group_by is GroupBy.PROJECT:
        group_expr = "c.name || ' · ' || p.name"
    elif group_by is GroupBy.CUSTOMER:
        group_expr = "c.name"
    else:
        group_expr = "'—'"

    where = ["l.started_at >= ?", "l.started_at < ?", "l.duration_seconds IS NOT NULL"]
    params: list = [from_iso, to_iso]
    if customer_id is not None:
        where.append("c.id = ?")
        params.append(customer_id)
    if project_id is not None:
        where.append("p.id = ?")
        params.append(project_id)

    sql = f"""
        SELECT strftime('{fmt}', l.started_at) AS bucket,
               {group_expr} AS group_label,
               SUM(l.duration_seconds) AS total
        FROM log_entry l
        JOIN project p ON p.id = l.project_id
        JOIN customer c ON c.id = p.customer_id
        WHERE {' AND '.join(where)}
        GROUP BY bucket, group_label
        ORDER BY bucket, total DESC
    """
    rows = conn.execute(sql, params).fetchall()
    return [AggRow(bucket=r["bucket"], group_label=r["group_label"], seconds=int(r["total"])) for r in rows]
