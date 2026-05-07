import asyncio
from io import BytesIO
from typing import Tuple
import pandas as pd

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware

from solver.data_loader import load_customers
from solver.geocoder import geocode
from solver.distance_matrix import build_time_matrix
from solver.vrp_solver import solve_vrp, normalize_time_windows, _extract_solution
from solver.schemas import OptimizationRequest, OptimizationResponse, Data
from auth import get_current_user
import traceback
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vrp")

app = FastAPI(title="Route Optimization Solver")

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/upload-csv")
async def receive_csv(input_file: UploadFile):
    content = await input_file.read()
    text = content.decode("utf-8")
    print("Received file content:", text[:100])
    return {"message": "File received successfully"}

@app.post("/clean-data", response_model=Data)
async def clean_data(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
    depot_address: str = Form(...),
    num_vehicles: int = Form(..., ge=1),
    vehicle_capacity: int = Form(..., ge=1),
    max_route_time: int = Form(..., ge=1),
):
    logger.info(f"[clean-data] depot={depot_address} vehicles={num_vehicles} capacity={vehicle_capacity} max_time={max_route_time}")
    
    try:
        filename = file.filename.lower()
        content  = await file.read()

        # ── Read file ──────────────────────────────────────────────────────────
        try:
            if filename.endswith(".csv"):
                df = pd.read_csv(BytesIO(content))
            elif filename.endswith((".xlsx", ".xls")):
                df = pd.read_excel(BytesIO(content))
            else:
                raise HTTPException(400, "Unsupported file type")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(400, f"Failed to read file: {e}")

        logger.info(f"[clean-data] file read OK — {len(df)} rows, columns: {list(df.columns)}")

        # ── Normalize columns ──────────────────────────────────────────────────
        df.columns = df.columns.str.lower().str.strip().str.replace(" ", "_")

        required = {"customer_id", "address", "demand", "service_time", "ready_time", "due_time"}
        missing  = required - set(df.columns)
        if missing:
            raise HTTPException(400, f"Missing columns: {', '.join(sorted(missing))}")

        # ── Validate & cast numeric fields ─────────────────────────────────────
        for col in ["demand", "service_time", "ready_time", "due_time"]:
            try:
                df[col] = pd.to_numeric(df[col], errors="raise").astype(int)
            except Exception:
                bad = df[col][pd.to_numeric(df[col], errors="coerce").isna()].tolist()
                raise HTTPException(400, f"Column '{col}' has non-integer values: {bad[:5]}")

        # ── Validate time windows ──────────────────────────────────────────────
        invalid_tw = df[df["ready_time"] >= df["due_time"]]
        if not invalid_tw.empty:
            raise HTTPException(
                400,
                f"{len(invalid_tw)} rows have ready_time >= due_time: "
                f"rows {invalid_tw.index[:5].tolist()}"
            )

        customers = df.to_dict(orient="records")
        logger.info(f"[clean-data] {len(customers)} customers validated")

        # ── Geocode ────────────────────────────────────────────────────────────
        try:
            depot_coord = await geocode(depot_address)
            logger.info(f"[clean-data] depot geocoded: {depot_coord}")
        except Exception as e:
            raise HTTPException(400, f"Could not geocode depot '{depot_address}': {e}")

        failed_addresses = []
        async def geocode_safe(c):
            try:
                return await geocode(c["address"])
            except Exception as e:
                failed_addresses.append(c["address"])
                logger.warning(f"[clean-data] geocode failed for: {c['address']} — {e}")
                return None

        customer_coords = await asyncio.gather(*[geocode_safe(c) for c in customers])

        # Drop customers that failed geocoding
        valid_pairs = [(c, coord) for c, coord in zip(customers, customer_coords) if coord]
        if not valid_pairs:
            raise HTTPException(400, "All customer addresses failed to geocode.")
        if failed_addresses:
            logger.warning(f"[clean-data] {len(failed_addresses)} addresses skipped: {failed_addresses[:5]}")

        customers      = [c for c, _ in valid_pairs]
        customer_coords = [coord for _, coord in valid_pairs]
        coords          = [depot_coord] + customer_coords
        logger.info(f"[clean-data] geocoding done — {len(customer_coords)} customers located")

        # ── Time matrix ────────────────────────────────────────────────────────
        try:
            time_matrix = build_time_matrix(coords)
            logger.info(f"[clean-data] time matrix built — {len(time_matrix)}×{len(time_matrix[0])}")
        except Exception as e:
            raise HTTPException(500, f"Failed to build time matrix: {e}")

        # ── Validate time matrix values vs max_route_time ──────────────────────
        max_travel = max(time_matrix[i][j]
                         for i in range(len(time_matrix))
                         for j in range(len(time_matrix))
                         if i != j)
        logger.info(f"[clean-data] max single leg travel time: {max_travel} min")
        if max_travel > max_route_time:
            logger.warning(
                f"[clean-data] WARNING: longest leg ({max_travel} min) "
                f"> max_route_time ({max_route_time} min) — likely infeasible"
            )

        # ── Build Data ─────────────────────────────────────────────────────────
        time_windows = [(0, max_route_time)] + [
            (c["ready_time"], c["due_time"]) for c in customers
        ]

        data = Data(
            time_matrix=time_matrix,
            demands=[0] + [c["demand"] for c in customers],
            service_times=[0] + [c["service_time"] for c in customers],
            time_windows=time_windows,
            vehicle_capacities=[vehicle_capacity] * num_vehicles,
            num_vehicles=num_vehicles,
            depot=0,
            max_route_time=max_route_time,
            coordinates=coords,
        )
        logger.info(f"[clean-data] Data object built OK")
        return data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[clean-data] unexpected error: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, f"Unexpected error: {e}")


@app.post("/solve", response_model=OptimizationResponse)
async def solve(request: OptimizationRequest, user=Depends(get_current_user)):
    logger.info(
        f"[solve] vehicles={request.data.num_vehicles} "
        f"customers={len(request.data.time_matrix)-1} "
        f"max_route_time={request.data.max_route_time} "
        f"depot_start_time={request.depot_start_time}"
    )
    try:
        result = solve_vrp(request.data, depot_start_time=request.depot_start_time)
        logger.info(f"[solve] status={result.status} routes={len(result.routes)}")

        if result.status == "no_solution":
            # Return 200 with clear message — never 500 for infeasibility
            return result

        return result

    except Exception as e:
        logger.error(f"[solve] crash: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, f"Solver error: {e}")
# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173",
        "https://start-optim.vercel.app",  # add after you get the URL
         "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
