import json
from ortools.constraint_solver import pywrapcp
import random

# Generate a 10x10 symmetric matrix for travel times
matrix = [[0] * 10 for _ in range(10)]
random.seed(42)
for i in range(10):
    for j in range(i+1, 10):
        val = random.randint(15, 60)
        matrix[i][j] = val
        matrix[j][i] = val

payload = {
  "num_vehicles": 3,
  "starts": [0, 1, 2],
  "ends": [0, 1, 2],
  "time_matrix": matrix,
  "time_windows": [
    [540, 1080], # Eng 0: 9:00 - 18:00
    [600, 1140], # Eng 1: 10:00 - 19:00
    [480, 960],  # Eng 2: 8:00 - 16:00
    
    [540, 660],  # Node 3: 9:00 - 11:00 (morning)
    [600, 900],  # Node 4: 10:00 - 15:00
    [720, 840],  # Node 5: 12:00 - 14:00 (lunchtime)
    [900, 1080], # Node 6: 15:00 - 18:00 (evening)
    [540, 960],  # Node 7: 9:00 - 16:00 (flexible)
    [1020, 1140],# Node 8: 17:00 - 19:00 (late evening)
    [660, 720]   # Node 9: 11:00 - 12:00 (very tight)
  ],
  "service_times": [0, 0, 0, 45, 60, 30, 90, 120, 45, 60],
  "allowed_vehicles": {
    "5": [1, 2], # Task 5 requires Eng 1 or 2
    "8": [1]     # Task 8 requires Eng 1 (late shift)
  },
  "penalties": [0, 0, 0, 10000, 10000, 10000, 10000, 10000, 10000, 1000] # Node 9 has low penalty, might drop
}

with open("strong_payload.json", "w") as f:
    json.dump(payload, f, indent=2)

from fastapi.testclient import TestClient
from app.main import app
client = TestClient(app)

response = client.post("/api/v1/solve", json=payload)
print(json.dumps(response.json(), indent=2))
