import json
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

payload = {
  "num_vehicles": 3,
  "starts": [0, 1, 2],
  "ends": [0, 1, 2],
  "time_matrix": [
    [0, 15, 20, 10, 45, 30],
    [15, 0, 25, 35, 10, 20],
    [20, 25, 0, 15, 30, 40],
    [10, 35, 15, 0, 20, 10],
    [45, 10, 30, 20, 0, 15],
    [30, 20, 40, 10, 15, 0]
  ],
  "time_windows": [
    [540, 1080], 
    [600, 1200], 
    [540, 900],  
    [540, 840],  
    [600, 1080], 
    [840, 1140]  
  ],
  "service_times": [0, 0, 0, 45, 120, 240],
  "allowed_vehicles": {
    "3": [0, 1],
    "4": [1],
    "5": [1, 2]
  },
  "penalties": [0, 0, 0, 10000, 20000, 50000]
}

response = client.post("/api/v1/solve", json=payload)
print(f"Status Code: {response.status_code}")
try:
    print(json.dumps(response.json(), indent=2))
except:
    print(response.text)
