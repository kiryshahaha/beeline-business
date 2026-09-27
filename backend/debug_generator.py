import asyncio
import logging
from app.modules.data_exchange.formats import ExchangeError, serialize, parse_file
from tests.t19_generator import generate_t19_dataset

def run():
    try:
        data, metadata = generate_t19_dataset("negative")
        csv_bytes = serialize(data, "csv")
        parsed = parse_file(csv_bytes, "data.zip")
        print("Success")
    except ExchangeError as e:
        print(f"Error detail: {e.detail}")
    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    run()
