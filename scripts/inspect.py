import argparse
import json
import sqlite3
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--warehouse", type=Path, required=True)
    args = parser.parse_args()
    if not args.warehouse.is_file():
        parser.error("warehouse file does not exist")
    connection = sqlite3.connect(args.warehouse.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        result = {
            "checkpoints": [
                dict(row) for row in connection.execute("SELECT * FROM checkpoints ORDER BY source")
            ],
            "batches": [
                dict(row)
                for row in connection.execute("SELECT * FROM batches ORDER BY source, lower_cursor")
            ],
            "manifest": [dict(row) for row in connection.execute("SELECT * FROM manifest")],
            "quarantine": [dict(row) for row in connection.execute("SELECT * FROM quarantine")],
        }
    finally:
        connection.close()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
