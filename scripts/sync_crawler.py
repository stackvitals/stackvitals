"""Copy the crawler (and only the crawler) into a local clone of the public merge-scout-crawler repo."""
import argparse
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "crawler"
FILES = ["pyproject.toml", ".gitattributes", ".env.example",
         "src/mergescout/__init__.py", "src/mergescout/config.py", "src/mergescout/timeutil.py",
         "src/mergescout/labels.py", "src/mergescout/owners.py", "src/mergescout/setup_check.py", "tests/conftest.py", "tests/test_flow_github.py",
         "tests/test_flow_crawl.py", "tests/test_flow_discover.py", "tests/test_flow_store.py",
         "tests/test_flow_bench.py"]
DIRS = ["src/mergescout/github", "src/mergescout/discover", "src/mergescout/crawl", "src/mergescout/store",
        "src/mergescout/bench"]
KEEP = {".git", ".github/keepalive"}


def crawler_pyproject(text: str) -> str:
    # The public crawler needs neither the MCP tool's packages nor its command.
    text = re.sub(r'"(mcp|zstandard|defusedxml)[^"]*",\s*', "", text)
    text = re.sub(r"\n\[project\.scripts\]\n(?:[^\[\n].*\n?)*", "\n", text)
    # Keywords and classifiers describe the suite, not the crawler.
    text = re.sub(r"(?m)^keywords = .*\n", "", text)
    text = re.sub(r"(?ms)^classifiers = \[.*?^\]\n", "", text)
    # The suite stays private until launch: the crawler copy is named and packaged as mergescout only.
    text = re.sub(r'(?m)^name = ".*"$', 'name = "mergescout"', text, count=1)
    text = re.sub(r'(?m)^description = ".*"$', 'description = "MergeScout crawler: reads public GitHub repos into Parquet."',
                  text, count=1)
    return re.sub(r'(?m)^packages = \[.*\]$', 'packages = ["src/mergescout"]', text, count=1)


def build(target: Path, workflows: list[str] | None = None) -> list[str]:
    # Everything except the git folder and the keep-alive stamp is replaced, so deleted files disappear too.
    for item in list(target.iterdir()):
        if item.name == ".git":
            continue
        if item.name == ".github":
            for sub in list(item.rglob("*"))[::-1]:
                if sub.relative_to(target).as_posix() not in KEEP and sub.is_file():
                    sub.unlink()
            continue
        shutil.rmtree(item) if item.is_dir() else item.unlink()
    copied = []
    paths = [ROOT / f for f in FILES] + [ROOT / d for d in DIRS]
    for src in paths:
        rel = src.relative_to(ROOT)
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        elif rel.as_posix() == "pyproject.toml":
            dest.write_text(crawler_pyproject(src.read_text(encoding="utf-8")), encoding="utf-8")
        else:
            shutil.copy2(src, dest)
        copied.append(rel.as_posix())
    (target / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    for wf in sorted((DEPLOY / "workflows").glob("*.yml")):
        if workflows and wf.name not in workflows:
            continue
        shutil.copy2(wf, target / ".github" / "workflows" / wf.name)
        copied.append(f".github/workflows/{wf.name}")
    shutil.copy2(DEPLOY / "README.md", target / "README.md")
    shutil.copy2(DEPLOY / "gitignore", target / ".gitignore")
    return copied + ["README.md", ".gitignore"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="local folder of the public repo (a git clone, or an empty folder to test)")
    parser.add_argument("--workflows", nargs="*", help="only these workflow files (default: all)")
    args = parser.parse_args()
    target = Path(args.target).resolve()
    if target == ROOT or ROOT in target.parents:
        print("Target must be outside this repo.", file=sys.stderr)
        return 2
    target.mkdir(parents=True, exist_ok=True)
    copied = build(target, args.workflows)
    print(f"copied {len(copied)} paths into {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
