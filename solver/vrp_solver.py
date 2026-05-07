# solver/vrp_solver.py
from ortools.constraint_solver import pywrapcp, routing_enums_pb2
from solver.schemas import OptimizationRequest, Route, Stop, OptimizationResponse, Data

# ─── Constants ────────────────────────────────────────────────────────────────
# All times in the solver are ROUTE-RELATIVE minutes (0 = departure from depot).
# If your raw data uses wall-clock minutes (e.g. 480 = 8:00 AM), normalize them
# before calling solve_vrp() by subtracting DEPOT_START_TIME.
DEPOT_START_TIME = 480   # 8:00 AM — change to match your operation


def normalize_time_windows(time_windows: list[tuple], depot_start: int) -> list[tuple]:
    """
    Convert wall-clock windows like (480, 540) → route-relative (0, 60).
    The depot window becomes (0, very_large) so the solver never constrains start.
    """
    normalized = []
    for i, (start, end) in enumerate(time_windows):
        rel_start = max(0, start - depot_start)
        rel_end   = max(rel_start, end - depot_start)
        normalized.append((rel_start, rel_end))
    return normalized


def solve_vrp(data: Data, depot_start_time: int = 480) -> OptimizationResponse:
    # ── Normalize time windows once, right here ──────────────────────────────
    # This means the rest of the solver never has to think about wall-clock time.
    norm_windows = normalize_time_windows(data.time_windows, depot_start_time)

    # Depot window: vehicle can leave any time within the working day.
    # We set it to (0, max_route_time) so it never constrains the solution.
    depot_window = (0, data.max_route_time)
    norm_windows[data.depot] = depot_window

    # ── Index manager & model ─────────────────────────────────────────────────
    manager = pywrapcp.RoutingIndexManager(
        len(data.time_matrix),
        data.num_vehicles,
        data.depot,
    )
    routing = pywrapcp.RoutingModel(manager)

    # ── Transit callback (travel time + service time at origin) ──────────────
    def time_callback(from_index, to_index):
        f = manager.IndexToNode(from_index)
        t = manager.IndexToNode(to_index)
        return data.time_matrix[f][t] + data.service_times[f]

    transit_idx = routing.RegisterTransitCallback(time_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)

    

    # ── Capacity dimension ────────────────────────────────────────────────────
    def demand_callback(from_index):
        return data.demands[manager.IndexToNode(from_index)]

    demand_idx = routing.RegisterUnaryTransitCallback(demand_callback)
    routing.AddDimensionWithVehicleCapacity(
        demand_idx,
        0,                        # no slack
        data.vehicle_capacities,  # list, one per vehicle
        True,                     # start at zero
        "Capacity",
    )

    # ── Time dimension ────────────────────────────────────────────────────────
    routing.AddDimension(
        transit_idx,
        60,                   # max waiting time per stop (slack) — tune this
        data.max_route_time,  # hard ceiling on total route duration
        False,                # do NOT force start at zero (allows depot slack)
        "Time",
    )
    time_dim = routing.GetDimensionOrDie("Time")

    # Apply route-relative windows to every node
    for node, (win_start, win_end) in enumerate(norm_windows):
        idx = manager.NodeToIndex(node)
        time_dim.CumulVar(idx).SetRange(win_start, win_end)

    # Apply depot window to each vehicle's start node
    for v in range(data.num_vehicles):
        start_idx = routing.Start(v)
        time_dim.CumulVar(start_idx).SetRange(*depot_window)
        # Minimize cumulative time at route end (encourages shorter routes)
        routing.AddVariableMinimizedByFinalizer(
            time_dim.CumulVar(routing.End(v))
        )

    # ── Search parameters ─────────────────────────────────────────────────────
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    params.time_limit.seconds = 15  # increase for larger instances

    solution = routing.SolveWithParameters(params)

    if not solution:
        return OptimizationResponse(
            status="no_solution",
            total_distance_km=0,
            total_time_min=0,
            routes=[],
        )

    return _extract_solution(data, manager, routing, solution, norm_windows)


def _extract_solution(data, manager, routing, solution, norm_windows) -> OptimizationResponse:
    time_dim = routing.GetDimensionOrDie("Time")

    all_routes = []
    total_distance = 0
    total_time = 0

    for v in range(data.num_vehicles):
        index = routing.Start(v)
        stops = []
        polyline = []
        route_distance = 0
        route_time = 0

        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            lat, lng = data.coordinates[node]

            arrival     = solution.Value(time_dim.CumulVar(index))
            win_start   = norm_windows[node][0]
            waiting     = max(0, win_start - arrival)

            stops.append(Stop(node=node, arrival_time=arrival, waiting_time=waiting))
            polyline.append({"lat": lat, "lng": lng})

            next_index = solution.Value(routing.NextVar(index))
            if not routing.IsEnd(next_index):
                next_node = manager.IndexToNode(next_index)
                route_distance += data.time_matrix[node][next_node]
                route_time     += data.time_matrix[node][next_node] + data.service_times[node]

            index = next_index

        # Add depot return point to polyline so the route closes visually
        depot_lat, depot_lng = data.coordinates[data.depot]
        polyline.append({"lat": depot_lat, "lng": depot_lng})
        stops.append(Stop(node=data.depot, arrival_time=route_time, waiting_time=0))

        # Skip vehicles with no real stops (only depot → depot)
        if len(polyline) <= 2:
            continue

        total_distance += route_distance
        total_time     += route_time

        all_routes.append(Route(
            vehicle_id=v,
            stops=stops,
            distance_km=route_distance,
            time_min=route_time,
            polyline=polyline,
        ))

    return OptimizationResponse(
        status="completed",
        total_distance_km=total_distance,
        total_time_min=total_time,
        routes=all_routes,
    )
