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
#         "basis": basis,
#         "computed_at": computed_at_row[0][0].isoformat(),
#         "flag_counts": [{"readiness_flag": r[0], "count": r[1]} for r in rows]
#     }



import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'scripts'))
from db_connection import run_query
from fastapi import Query, Path
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


# ============================================================
# ML INSIGHTS - FORECASTING (PROPHET)
# ============================================================

@app.get("/api/ml/forecast/revenue")
def get_revenue_forecast():
    rows = run_query(
        """SELECT ds, month_label, actual, forecast, lower_bound, upper_bound, is_forecast, computed_at
           FROM ml_revenue_forecast
           ORDER BY ds ASC""",
        fetch=True
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No data found in ml_revenue_forecast")

    computed_at = rows[0][7].isoformat() if hasattr(rows[0][7], 'isoformat') else str(rows[0][7])

    data = [
        {
            "ds": r[0].isoformat() if hasattr(r[0], 'isoformat') else str(r[0]),
            "month": r[1],
            "actual": float(r[2]) if r[2] is not None else None,
            "forecast": float(r[3]) if r[3] is not None else None,
            "lower": float(r[4]) if r[4] is not None else None,
            "upper": float(r[5]) if r[5] is not None else None,
            "is_forecast": bool(r[6]),
        }
        for r in rows
    ]

    return {"computed_at": computed_at, "count": len(data), "data": data}


@app.get("/api/ml/forecast/revenue/summary")
def get_revenue_forecast_summary():
    rows = run_query(
        """SELECT next_month_label, next_month_val, next_month_lower, next_month_upper,
                  next_month_yoy_pct, last_actual_label, last_actual_val, forecast_total_6m,
                  forecast_period_label, computed_at
           FROM ml_revenue_forecast_kpis
           WHERE kpi_id = 'latest'""",
        fetch=True
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No data found in ml_revenue_forecast_kpis")

    r = rows[0]
    computed_at = r[9].isoformat() if hasattr(r[9], 'isoformat') else str(r[9])

    return {
        "computed_at": computed_at,
        "kpi": {
            "next_month_label": r[0],
            "next_month_val": float(r[1]),
            "next_month_lower": float(r[2]),
            "next_month_upper": float(r[3]),
            "next_month_yoy_pct": float(r[4]) if r[4] is not None else None,
            "last_actual_label": r[5],
            "last_actual_val": float(r[6]),
            "forecast_total_6m": float(r[7]),
            "forecast_period_label": r[8],
        }
    }


@app.get("/api/ml/forecast/expense")
def get_expense_forecast():
    rows = run_query(
        """SELECT ds, month_label, actual, forecast, lower_bound, upper_bound, is_forecast, validation_flag, computed_at
           FROM ml_expense_forecast
           ORDER BY ds ASC""",
        fetch=True
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No data found in ml_expense_forecast")

    computed_at = rows[0][8].isoformat() if hasattr(rows[0][8], 'isoformat') else str(rows[0][8])

    data = [
        {
            "ds": r[0].isoformat() if hasattr(r[0], 'isoformat') else str(r[0]),
            "month": r[1],
            "actual": float(r[2]) if r[2] is not None else None,
            "forecast": float(r[3]) if r[3] is not None else None,
            "lower": float(r[4]) if r[4] is not None else None,
            "upper": float(r[5]) if r[5] is not None else None,
            "is_forecast": bool(r[6]),
            "validation_flag": r[7],
        }
        for r in rows
    ]

    return {"computed_at": computed_at, "count": len(data), "data": data}


@app.get("/api/ml/forecast/expense/summary")
def get_expense_forecast_summary():
    rows = run_query(
        """SELECT next_month_label, next_month_val, next_month_lower, next_month_upper,
                  historical_avg_val, validation_total_6m, validation_period_label, computed_at
           FROM ml_expense_forecast_kpis
           WHERE kpi_id = 'latest'""",
        fetch=True
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No data found in ml_expense_forecast_kpis")

    r = rows[0]
    computed_at = r[7].isoformat() if hasattr(r[7], 'isoformat') else str(r[7])

    return {
        "computed_at": computed_at,
        "kpi": {
            "next_month_label": r[0],
            "next_month_val": float(r[1]),
            "next_month_lower": float(r[2]),
            "next_month_upper": float(r[3]),
            "historical_avg_val": float(r[4]),
            "validation_total_6m": float(r[5]),
            "validation_period_label": r[6],
        }
    }

# --------------------------------------------
# Anomaly Detection Endpoints
# --------------------------------------------


@app.get("/api/ml/anomalies/{metric}")
async def get_anomalies(metric: str = Path(..., regex="^(revenue|expense)$")):
    table = f"ml_{metric}_anomalies"
    rows = run_query(f"SELECT ds, y, anomaly_flag, anomaly_score, pct_vs_baseline FROM {table} ORDER BY ds", fetch=True)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No anomaly data found for {metric}")
    data = [
        {
            "ds": r[0].isoformat() if hasattr(r[0], 'isoformat') else str(r[0]),
            "y": r[1],
            "anomaly_flag": r[2],
            "anomaly_score": r[3],
            "pct_vs_baseline": float(r[4]) if r[4] is not None else None,
        }
        for r in rows
    ]
    return {"metric": metric, "count": len(data), "data": data}

@app.get("/api/ml/anomalies/{metric}/summary")
async def get_anomaly_summary(metric: str = Path(..., regex="^(revenue|expense)$")):
    table = f"ml_{metric}_anomalies"
    rows = run_query(f"SELECT COUNT(*), MAX(computed_at) FROM {table}", fetch=True)
    count, last = rows[0]
    return {"metric": metric, "count": count, "last_computed": last.isoformat() if last else None}


import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'scripts'))
from compute_growth_levers import (
    compute_nx_fit, build_entity_fy, compute_entity_cagr,
    required_cagr, run_nx_fit, split_by_confidence,
    get_current_and_recent_full_fy
)

# ============================================================
# GROWTH LEVER SIMULATOR
# ============================================================

@app.get("/api/growth/base-revenue")
def get_base_revenue():
    rows = run_query(
        "SELECT revenue, recent_full_fy, computed_at FROM growth_base_revenue LIMIT 1",
        fetch=True
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No data found in growth_base_revenue")
    r = rows[0]
    return {
        "revenue": float(r[0]),
        "recent_full_fy": r[1],
        "computed_at": r[2].isoformat(),
    }


@app.get("/api/growth/lever1")
def get_lever1_inputs():
    rows = run_query(
        """SELECT total_active_franchises, departed_franchise_count, avg_departed_revenue,
                  recent_full_fy, computed_at
           FROM growth_lever1_inputs LIMIT 1""",
        fetch=True
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No data found in growth_lever1_inputs")
    r = rows[0]
    return {
        "total_active_franchises": r[0],
        "departed_franchise_count": r[1],
        "avg_departed_revenue": float(r[2]),
        "recent_full_fy": r[3],
        "computed_at": r[4].isoformat(),
    }


@app.get("/api/growth/lever2")
def get_lever2_inputs():
    rows = run_query(
        """SELECT total_enquiries_recent_fy, billed_enquiries_recent_fy, current_strike_ratio,
                  avg_revenue_per_bill, missing_date_pct, recent_full_fy, computed_at
           FROM growth_lever2_inputs LIMIT 1""",
        fetch=True
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No data found in growth_lever2_inputs")
    r = rows[0]
    return {
        "total_enquiries_recent_fy": r[0],
        "billed_enquiries_recent_fy": r[1],
        "current_strike_ratio": float(r[2]),
        "avg_revenue_per_bill": float(r[3]),
        "missing_date_pct": float(r[4]),
        "recent_full_fy": r[5],
        "computed_at": r[6].isoformat(),
    }


@app.get("/api/growth/lever3")
def get_lever3_inputs():
    rows = run_query(
        """SELECT max_dormant_available, avg_activated_revenue_recent_fy, avg_activated_revenue_lifetime,
                  real_activation_count, method_used, recent_full_fy, computed_at
           FROM growth_lever3_inputs LIMIT 1""",
        fetch=True
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No data found in growth_lever3_inputs")
    r = rows[0]
    return {
        "max_dormant_available": r[0],
        "avg_activated_revenue_recent_fy": float(r[1]),
        "avg_activated_revenue_lifetime": float(r[2]) if r[2] is not None else None,
        "real_activation_count": r[3],
        "method_used": r[4],
        "recent_full_fy": r[5],
        "computed_at": r[6].isoformat(),
    }


@app.get("/api/growth/nx-fit/{entity}")
def get_nx_fit(entity: str, target_multiplier: float = Query(3.0), horizon_years: int = Query(5)):
    """
    Fully LIVE — recomputed on every request, not cached in Aiven.
    Because Nx-Fit is target-dependent (founder's slider/custom goal),
    it must always reflect exactly what was asked, not a stale scenario.
    """
    if entity not in ("bd", "tl"):
        raise HTTPException(status_code=400, detail="entity must be 'bd' or 'tl'")
    if target_multiplier <= 0 or horizon_years <= 0:
        raise HTTPException(status_code=400, detail="target_multiplier and horizon_years must be positive")

    current_fy, recent_full_fy = get_current_and_recent_full_fy()

    base_rows = run_query("SELECT revenue FROM growth_base_revenue LIMIT 1", fetch=True)
    if not base_rows:
        raise HTTPException(status_code=404, detail="No base revenue available — run growth lever computation first")
    base_revenue = float(base_rows[0][0])

    entity_col = "nameOfBd" if entity == "bd" else "teamLeader"
    entity_fy = build_entity_fy(entity_col)
    entity_cagr_df = compute_entity_cagr(entity_fy, entity_col, current_fy)

    target_year_start = int(recent_full_fy.split("-")[0]) + horizon_years
    target_fy = f"{target_year_start}-{target_year_start + 1}"
    target_revenue = base_revenue * target_multiplier

    nx_df, req_cagr, years = run_nx_fit(entity_cagr_df, base_revenue, target_revenue, recent_full_fy, target_fy)
    confident, watch = split_by_confidence(nx_df, entity_col)

    def to_records(df):
        df = df.replace({float('nan'): None})
        return df.to_dict(orient="records")

    return {
        "entity": entity,
        "target_multiplier": target_multiplier,
        "horizon_years": horizon_years,
        "target_fy": target_fy,
        "required_cagr": req_cagr,
        "base_revenue": base_revenue,
        "target_revenue": target_revenue,
        "confident": to_records(confident),
        "watchlist": to_records(watch),
    }