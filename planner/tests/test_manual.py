import json
from fastapi.testclient import TestClient
from app.main import app

payload = {
  "num_vehicles": 2,
  "starts": [0, 1],
  "ends": [0, 1],
  "time_matrix": [
    [0, 50, 20, 50, 300],
    [50, 0, 50, 20, 300],
    [20, 50, 0, 50, 300],
    [50, 20, 50, 0, 300],
    [300, 300, 300, 300, 0]
  ],
  "time_windows": [
    [540, 1080], 
    [600, 1140], 
    [600, 720],  
    [780, 840],  
    [540, 1200]  
  ],
  "service_times": [0, 0, 60, 60, 60],
  "allowed_vehicles": {
    "2": [0],
    "3": [1]
  },
  "penalties": [0, 0, 10000, 10000, 1000]
}

client = TestClient(app)
response = client.post("/api/v1/solve", json=payload)
print(json.dumps(response.json(), indent=2))
