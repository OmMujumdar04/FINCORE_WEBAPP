from fastapi.testclient import TestClient
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend')))
try:
    from main import app  # type: ignore
except ImportError:
    from backend.main import app  # type: ignore

client = TestClient(app)

def test_endpoints():
    print("Testing /api/ml/forecast/revenue...")
    res1 = client.get("/api/ml/forecast/revenue")
    print("Status:", res1.status_code)
    data1 = res1.json()
    print("Count:", data1.get("count"), "Computed At:", data1.get("computed_at"))
    print("Sample:", data1.get("data")[:2], "...", data1.get("data")[-2:])

    print("\nTesting /api/ml/forecast/revenue/summary...")
    res2 = client.get("/api/ml/forecast/revenue/summary")
    print("Status:", res2.status_code)
    print("KPIs:", res2.json())

    print("\nTesting /api/ml/forecast/expense...")
    res3 = client.get("/api/ml/forecast/expense")
    print("Status:", res3.status_code)
    data3 = res3.json()
    print("Count:", data3.get("count"), "Computed At:", data3.get("computed_at"))
    print("Sample:", data3.get("data")[:2], "...", data3.get("data")[-2:])

    print("\nTesting /api/ml/forecast/expense/summary...")
    res4 = client.get("/api/ml/forecast/expense/summary")
    print("Status:", res4.status_code)
    print("KPIs:", res4.json())

if __name__ == "__main__":
    test_endpoints()
