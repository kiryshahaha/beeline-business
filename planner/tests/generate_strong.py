"""Print a valid example without making HTTP calls at import time."""

import json

from fixtures import problem

if __name__ == "__main__":
    print(json.dumps(problem(n=12, vehicles=3, horizon=480), indent=2))
