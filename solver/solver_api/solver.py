import numpy as np
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

# Haversine distance
def distance(a, b):
    lat1, lon1 = a
    lat2, lon2 = b
    R = 6371
    dlat = np.radians(lat2-lat1)
    dlon = np.radians(lon2-lon1)
    h = np.sin(dlat/2)**2 + np.cos(np.radians(lat1))*np.cos(np.radians(lat2))*np.sin(dlon/2)**2
    return 2 * R * np.arcsin(np.sqrt(h))

def build_distance_matrix(locations):
    n = len(locations)
    matrix = np.zeros((n,n))
    for i in range(n):
        for j in range(n):
            matrix[i,j] = distance(locations[i], locations[j])
    return matrix

def solve_vrp(data: dict):

    depot = data["depot"]
    vehicles = data["vehicles"]
    customers = data["customers"]

    locations = [depot["location"]] + [c["location"] for c in customers]
    demands = [0] + [c["demand"] for c in customers]

    distance_matrix = build_distance_matrix(locations)

    manager = pywrapcp.RoutingIndexManager(
        len(distance_matrix),
        len(vehicles),
        0
    )

    routing = pywrapcp.RoutingModel(manager)

    def distance_callback(from_index, to_index):
        f = manager.IndexToNode(from_index)
        t = manager.IndexToNode(to_index)
        return int(distance_matrix[f][t] * 1000)

    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    # Capacity constraint
    def demand_callback(from_index):
        return demands[manager.IndexToNode(from_index)]

    demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)

    routing.AddDimensionWithVehicleCapacity(
        demand_callback_index,
        0,
        [v["capacity"] for v in vehicles],
        True,
        "Capacity",
    )

    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.time_limit.seconds = data["options"]["max_solver_time_sec"]
    search_parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC

    solution = routing.SolveWithParameters(search_parameters)

    if solution is None:
        return {"status": "failed"}

    routes = []
    total_distance = 0

    for v in range(len(vehicles)):
        index = routing.Start(v)
        route_distance = 0
        stops = []

        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            stops.append({"type": "visit", "id": str(node), "arrival": 0})
            previous_index = index
            index = solution.Value(routing.NextVar(index))
            route_distance += routing.GetArcCostForVehicle(previous_index, index, v)

        routes.append({
            "vehicle_id": vehicles[v]["id"],
            "distance_km": route_distance/1000,
            "duration_min": int(route_distance/1000 * 2),
            "stops": stops
        })

        total_distance += route_distance

    return {
        "status": "completed",
        "total_distance_km": total_distance/1000,
        "total_time_min": int(total_distance/1000 * 2),
        "routes": routes
    }