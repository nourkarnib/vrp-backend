# solver/data_loader.py
import pandas as pd

def load_customers(csv_path):
    df = pd.read_csv(csv_path)

    required = [
        "customer_id",
        "address",
        "demand",
        "service_time",
        "ready_time",
        "due_time",
    ]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Missing column {col}")

    customers = []
    for _, row in df.iterrows():
        customers.append({
            "id": int(row.customer_id),
            "address": row.address,
            "demand": int(row.demand),
            "service_time": int(row.service_time),
            "time_window": (int(row.ready_time), int(row.due_time)),
        })

    return customers