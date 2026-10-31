from pathlib import Path

import orjson


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [orjson.loads(line) for line in path.read_bytes().splitlines() if line.strip()]


def append_jsonl(path: Path, record: dict) -> None:
    with path.open("ab") as f:
        f.write(orjson.dumps(record) + b"\n")
