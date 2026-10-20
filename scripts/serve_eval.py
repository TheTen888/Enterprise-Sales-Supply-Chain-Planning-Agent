import argparse
from pathlib import Path

from app.eval_dashboard import make_server


def main():
    parser = argparse.ArgumentParser(description="Open the read-only local Evaluation Studio")
    parser.add_argument("--port", type=int, default=8768)
    args = parser.parse_args()
    server = make_server(Path(__file__).resolve().parent.parent, args.port)
    print(f"Evaluation Studio: http://127.0.0.1:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
