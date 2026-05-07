# solver/distance_matrix.py
import numpy as np
from math import radians, sin, cos, sqrt, atan2

AVG_SPEED_KMH = 40

def haversine(a, b):
    lat1, lon1 = a
    lat2, lon2 = b

    R = 6371
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)

    h = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return 2 * R * atan2(sqrt(h), sqrt(1-h))

def build_time_matrix(coords):
    n = len(coords)
    matrix = np.zeros((n, n), dtype=int)

    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            dist_km = haversine(coords[i], coords[j])
            time_min = dist_km / AVG_SPEED_KMH * 60
            matrix[i][j] = int(time_min)

    return matrix.tolist()