# import sys
# import os

# # Reuse the same db_connection.py from scripts/ — don't duplicate connection logic
# sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'scripts'))
# from db_connection import run_query

# from fastapi import FastAPI, HTTPException
# from fastapi.middleware.cors import CORSMiddleware

# app = FastAPI(title="FINCORE API")

# # CORS: allows the Next.js frontend (running on a different origin/port) to call this API.
# # Wide open for now during local dev — will be tightened to the real frontend URL once deployed.
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# VALID_BASES = {"net", "gross"}

# @app.get("/api/franchise-readiness/{basis}")
# def get_franchise_readiness(basis: str):
#     if basis not in VALID_BASES:
#         raise HTTPException(status_code=400, detail="basis must be 'net' or 'gross'")

#     table_name = f"franchise_readiness_calculated_{basis}"

#     rows = run_query(
#         f"""SELECT franchise_name, lifetime_revenue, lifetime_rank, recent_fy_revenue,
#                    recent_fy_rank, recent_fy_status, trajectory, momentum, readiness_flag, computed_at
#             FROM {table_name}
#             ORDER BY lifetime_rank ASC""",
#         fetch=True
#     )

#     if not rows:
#         raise HTTPException(status_code=404, detail=f"No data found in {table_name}")

#     computed_at = rows[0][9].isoformat()

#     data = [
#         {
#             "franchise_name": r[0],
#             "lifetime_revenue": float(r[1]),
#             "lifetime_rank": r[2],
#             "recent_fy_revenue": float(r[3]) if r[3] is not None else None,
#             "recent_fy_rank": r[4],
#             "recent_fy_status": r[5],
#             "trajectory": r[6],
#             "momentum": r[7],
#             "readiness_flag": r[8],
#         }
#         for r in rows
#     ]

#     return {
#         "basis": basis,
#         "computed_at": computed_at,
#         "count": len(data),
#         "data": data
#     }

# @app.get("/api/franchise-readiness/{basis}/summary")
# def get_franchise_readiness_summary(basis: str):
#     if basis not in VALID_BASES:
#         raise HTTPException(status_code=400, detail="basis must be 'net' or 'gross'")

#     table_name = f"franchise_readiness_calculated_{basis}"

#     rows = run_query(
#         f"SELECT readiness_flag, COUNT(*) FROM {table_name} GROUP BY readiness_flag ORDER BY COUNT(*) DESC",
#         fetch=True
#     )
#     computed_at_row = run_query(f"SELECT MAX(computed_at) FROM {table_name}", fetch=True)

#     if not rows:
#         raise HTTPException(status_code=404, detail=f"No data found in {table_name}")

#     return {
#         "basis": basis,
#         "computed_at": computed_at_row[0][0].isoformat(),
#         "flag_counts": [{"readiness_flag": r[0], "count": r[1]} for r in rows]
#     }



import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'scripts'))
from db_connection import run_query

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="FINCORE API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

VALID_BASES = {"net", "gross"}


# ============================================================
# FRANCHISE READINESS
# ============================================================

@app.get("/api/franchise-readiness/{basis}")
def get_franchise_readiness(basis: str):
    if basis not in VALID_BASES:
        raise HTTPException(status_code=400, detail="basis must be 'net' or 'gross'")

    table_name = f"franchise_readiness_calculated_{basis}"

    rows = run_query(
        f"""SELECT franchise_name, lifetime_revenue, lifetime_rank, recent_fy_revenue,
                   recent_fy_rank, recent_fy_status, trajectory, momentum, readiness_flag, computed_at
            FROM {table_name}
            ORDER BY lifetime_rank ASC""",
        fetch=True
    )

    if not rows:
        raise HTTPException(status_code=404, detail=f"No data found in {table_name}")

    computed_at = rows[0][9].isoformat()

    data = [
        {
            "franchise_name": r[0],
            "lifetime_revenue": float(r[1]),
            "lifetime_rank": r[2],
            "recent_fy_revenue": float(r[3]) if r[3] is not None else None,
            "recent_fy_rank": r[4],
            "recent_fy_status": r[5],
            "trajectory": r[6],
            "momentum": r[7],
            "readiness_flag": r[8],
        }
        for r in rows
    ]

    return {"basis": basis, "computed_at": computed_at, "count": len(data), "data": data}


@app.get("/api/franchise-readiness/{basis}/summary")
def get_franchise_readiness_summary(basis: str):
    if basis not in VALID_BASES:
        raise HTTPException(status_code=400, detail="basis must be 'net' or 'gross'")

    table_name = f"franchise_readiness_calculated_{basis}"

    rows = run_query(
        f"SELECT readiness_flag, COUNT(*) FROM {table_name} GROUP BY readiness_flag ORDER BY COUNT(*) DESC",
        fetch=True
    )
    computed_at_row = run_query(f"SELECT MAX(computed_at) FROM {table_name}", fetch=True)

    if not rows:
        raise HTTPException(status_code=404, detail=f"No data found in {table_name}")

    return {
        "basis": basis,
        "computed_at": computed_at_row[0][0].isoformat(),
        "flag_counts": [{"readiness_flag": r[0], "count": r[1]} for r in rows]
    }


# ============================================================
# BD READINESS
# ============================================================

@app.get("/api/bd-readiness")
def get_bd_readiness():
    rows = run_query(
        """SELECT bd_name, trajectory, yoy_growth_rates, momentum_status, revenue_change_pct,
                  lifetime_revenue, lifetime_rank, recent_fy_revenue, recent_fy_rank,
                  recent_fy_status, readiness_flag, computed_at
           FROM bd_readiness_calculated
           ORDER BY lifetime_rank ASC""",
        fetch=True
    )

    if not rows:
        raise HTTPException(status_code=404, detail="No data found in bd_readiness_calculated")

    computed_at = rows[0][11].isoformat()

    data = [
        {
            "bd_name": r[0],
            "trajectory": r[1],
            "yoy_growth_rates": r[2],
            "momentum_status": r[3],
            "revenue_change_pct": float(r[4]) if r[4] is not None else None,
            "lifetime_revenue": float(r[5]) if r[5] is not None else None,
            "lifetime_rank": r[6],
            "recent_fy_revenue": float(r[7]) if r[7] is not None else None,
            "recent_fy_rank": r[8],
            "recent_fy_status": r[9],
            "readiness_flag": r[10],
        }
        for r in rows
    ]

    return {"computed_at": computed_at, "count": len(data), "data": data}


@app.get("/api/bd-readiness/summary")
def get_bd_readiness_summary():
    rows = run_query(
        "SELECT readiness_flag, COUNT(*) FROM bd_readiness_calculated GROUP BY readiness_flag ORDER BY COUNT(*) DESC",
        fetch=True
    )
    computed_at_row = run_query("SELECT MAX(computed_at) FROM bd_readiness_calculated", fetch=True)

    if not rows:
        raise HTTPException(status_code=404, detail="No data found in bd_readiness_calculated")

    return {
        "computed_at": computed_at_row[0][0].isoformat(),
        "flag_counts": [{"readiness_flag": r[0], "count": r[1]} for r in rows]
    }


# ============================================================
# TL READINESS
# ============================================================

@app.get("/api/tl-readiness")
def get_tl_readiness():
    rows = run_query(
        """SELECT tl_name, trajectory, yoy_growth_rates, momentum_status, revenue_change_pct,
                  lifetime_revenue, lifetime_rank, recent_fy_revenue, recent_fy_rank,
                  recent_fy_status, readiness_flag, computed_at
           FROM tl_readiness_calculated
           ORDER BY lifetime_rank ASC""",
        fetch=True
    )

    if not rows:
        raise HTTPException(status_code=404, detail="No data found in tl_readiness_calculated")

    computed_at = rows[0][11].isoformat()

    data = [
        {
            "tl_name": r[0],
            "trajectory": r[1],
            "yoy_growth_rates": r[2],
            "momentum_status": r[3],
            "revenue_change_pct": float(r[4]) if r[4] is not None else None,
            "lifetime_revenue": float(r[5]) if r[5] is not None else None,
            "lifetime_rank": r[6],
            "recent_fy_revenue": float(r[7]) if r[7] is not None else None,
            "recent_fy_rank": r[8],
            "recent_fy_status": r[9],
            "readiness_flag": r[10],
        }
        for r in rows
    ]

    return {"computed_at": computed_at, "count": len(data), "data": data}


@app.get("/api/tl-readiness/summary")
def get_tl_readiness_summary():
    rows = run_query(
        "SELECT readiness_flag, COUNT(*) FROM tl_readiness_calculated GROUP BY readiness_flag ORDER BY COUNT(*) DESC",
        fetch=True
    )
    computed_at_row = run_query("SELECT MAX(computed_at) FROM tl_readiness_calculated", fetch=True)

    if not rows:
        raise HTTPException(status_code=404, detail="No data found in tl_readiness_calculated")

    return {
        "computed_at": computed_at_row[0][0].isoformat(),
        "flag_counts": [{"readiness_flag": r[0], "count": r[1]} for r in rows]
    }