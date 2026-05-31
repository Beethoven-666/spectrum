"""Command-line entrypoints for the acquisition service."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from .api import create_app
from .config import load_config, save_config
from .storage import SampleStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the spectrum acquisition service")
    parser.add_argument(
        "command",
        nargs="?",
        choices=["serve", "rebuild-index"],
        default="serve",
        help="Command to run. Defaults to serve.",
    )
    parser.add_argument("--data-dir", default="data", help="Sample data directory")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    parser.add_argument("--mock", action="store_true", help="Run with mock H1/D455 devices")
    parser.add_argument("--hardware", action="store_true", help="Run against real H1/D455 hardware")
    args = parser.parse_args()

    config = load_config(data_dir=Path(args.data_dir))
    if args.hardware:
        config = type(config)(**{**config.__dict__, "mock": False})
    elif args.mock:
        config = type(config)(**{**config.__dict__, "mock": True})
    save_config(config)
    if args.command == "rebuild-index":
        count = SampleStore(config).rebuild_index()
        print(f"rebuilt {count} samples")
        return
    app = create_app(config)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
