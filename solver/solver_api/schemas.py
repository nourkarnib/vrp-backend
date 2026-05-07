from pydantic import BaseModel
from typing import List, Tuple

# ---------- INPUT ----------

class Depot(BaseModel):
    id: str
    location: Tuple[float, float]
    time_window: Tuple[int, int]

class Vehicle(BaseModel):
    id: str
    capacity: int
    start_time: int
    end_time: int

class Customer(BaseModel):
    id: str
    location: Tuple[float, float]
    demand: int
    service_time: int
    time_window: Tuple[int, int]

class Options(BaseModel):
    max_solver_time_sec: int = 20

class OptimizationRequest(BaseModel):
    depot: Depot
    vehicles: List[Vehicle]
    customers: List[Customer]
    options: Options


# ---------- OUTPUT ----------
# models.py
from pydantic import BaseModel
from typing import List

class Stop(BaseModel):
    node: int
    arrival_time: int
    waiting_time: int

class Route(BaseModel):
    vehicle_id: int
    stops: List[Stop]
    distance_km: float
    time_min: float

class OptimizationResponse(BaseModel):
    status: str
    total_distance_km: float
    total_time_min: float
    routes: List[Route]
