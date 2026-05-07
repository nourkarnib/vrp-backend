from fastapi import FastAPI
from schemas import OptimizationRequest, OptimizationResponse
from solver import solve_vrp

app = FastAPI(title="Route Optimization Solver")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/solve", response_model=OptimizationResponse)
def solve(request: OptimizationRequest):
    result = solve_vrp(request.dict())
    return result