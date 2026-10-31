"""Editor add-ons: `stackvitals editor vscode` installs the flaky-test marker into VS Code (or Cursor, VSCodium)."""
import argparse
import json
import shutil
import sys
from importlib.resources import files
from pathlib import Path

HOMES = {"vscode": ".vscode", "cursor": ".cursor", "vscodium": ".vscode-oss"}


def install(target: Path) -> Path:
    source = files("stackvitals.editors") / "vscode"
    manifest = json.loads((source / "package.json").read_text(encoding="utf-8"))
    prefix = f"{manifest['publisher']}.{manifest['name']}-"
    target.mkdir(parents=True, exist_ok=True)
    # Only our own older copies are replaced; nothing else in the folder is touched.
    for old in target.glob(prefix + "*"):
        if old.is_dir():
            shutil.rmtree(old)
    dest = target / (prefix + manifest["version"])
    dest.mkdir()
    for name in ("package.json", "extension.js", "marks.js"):
        (dest / name).write_text((source / name).read_text(encoding="utf-8"), encoding="utf-8")
    return dest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="stackvitals editor", description=__doc__)
    ap.add_argument("editor", choices=sorted(HOMES), help="which editor to install the marker into")
    ap.add_argument("--dir", type=Path, help="the editor's extensions folder, if not the usual one")
    args = ap.parse_args(argv)
    dest = install(args.dir or Path.home() / HOMES[args.editor] / "extensions")
    print(f"Installed into {dest}. Reload the editor; flaky tests are marked in test files of repos with a "
          "stackvitals-data branch (run \"StackVitals: Refresh flaky tests\" to fetch the newest).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
