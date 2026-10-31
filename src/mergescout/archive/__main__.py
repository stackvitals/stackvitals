import argparse
import sys

from mergescout.archive.convert import convert_hour
from mergescout.archive.manifest import Manifest
from mergescout.config import load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mergescout.archive",
                                     description="Convert GH Archive hours into slim Parquet files.")
    parser.add_argument("hours", nargs="+", help="UTC hour keys like 2026-10-01-15")
    args = parser.parse_args(argv)
    cfg = load_config()
    manifest = Manifest(cfg.data_dir / "manifest.sqlite")
    failed = 0
    for key in args.hours:
        try:
            r = convert_hour(key, cfg.data_dir, manifest)
            print(f"{r.hour_key}: {r.status} in={r.events_in} kept={r.events_kept} "
                  f"bad={r.bad_lines} bytes={r.bytes_out}")
        except Exception as exc:
            failed += 1
            print(f"{key}: failed ({exc})", file=sys.stderr)
    manifest.close()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
