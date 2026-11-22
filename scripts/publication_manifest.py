import argparse
import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
MANIFEST = PROJECT / "PUBLICATION.sha256"
DIRECTORIES = ("backend", "docs", "evaluation", "frontend", "infrastructure", "scripts", "workflows", ".github")
ROOT_FILES = (".gitattributes", ".gitignore", ".dockerignore", ".env.example", "README.md", "CHANGELOG.md",
              "PROJECT_STATUS.md", "docker-compose.yml", "docker-compose.distributed.yml", "pyproject.toml")
EXCLUDED = {"node_modules", "dist", "__pycache__", ".npm-cache", ".ruff_cache", ".pytest_cache",
            "playwright-report", "test-results", ".vite", "coverage", ".runtime", ".venv"}
BINARY = {".pdf", ".png", ".xlsx"}
PUBLIC_SUFFIXES = BINARY | {".css", ".csv", ".html", ".ini", ".json", ".mako", ".md", ".py", ".ps1",
                            ".toml", ".ts", ".tsx", ".txt", ".yml", ".conf"}
SECRET_PATTERN = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|"
    r"sk-[A-Za-z0-9_-]{32,}|(?:AKIA|ASIA)[A-Z0-9]{16}|xox[baprs]-[A-Za-z0-9-]{20,}"
)


def files():
    output = [PROJECT / path for path in ROOT_FILES]
    for directory in DIRECTORIES:
        for parent, folders, filenames in (PROJECT / directory).walk():
            folders[:] = [name for name in folders if name not in EXCLUDED and not name.startswith(".")]
            output.extend(parent / name for name in filenames
                          if not name.startswith(".") and
                          (Path(name).suffix in PUBLIC_SUFFIXES or name == "Dockerfile"))
    return sorted(output, key=lambda path: path.relative_to(PROJECT).as_posix())


def snapshot(*, strict=False):
    paths = files()
    if strict:
        expected = {path.relative_to(PROJECT).as_posix() for path in paths} | {MANIFEST.name}
        actual = set()
        for parent, directories, names in PROJECT.walk():
            if parent == PROJECT and ".git" in directories:
                directories.remove(".git")
            actual.update((parent / name).relative_to(PROJECT).as_posix() for name in names)
        unexpected = actual - expected
        if unexpected:
            raise ValueError("Unexpected files: " + ", ".join(sorted(unexpected)))
    entries = []
    for path in paths:
        relative = path.relative_to(PROJECT)
        if path.resolve() != path:
            raise ValueError(f"Publication payload includes a linked path: {relative}")
        content = path.read_bytes()
        if path.suffix not in BINARY and SECRET_PATTERN.search(content.decode("utf-8-sig")):
            raise ValueError(f"Possible secret in {relative}")
        entries.append((hashlib.sha256(content).hexdigest(), len(content), relative.as_posix()))
    return entries


def manifest_text(entries, created):
    total = sum(size for _, size, _ in entries)
    header = [
        "# AgentForge publication manifest",
        f"# created: {created}",
        f"# payload_files: {len(entries)}",
        f"# payload_bytes: {total}",
        "# sha256  bytes  path",
    ]
    return "\n".join([*header, *(f"{digest}  {size}  {path}" for digest, size, path in entries)]) + "\n"


def verify(*, strict=False):
    content = MANIFEST.read_text(encoding="utf-8")
    entries = snapshot(strict=strict)
    created = content.splitlines()[1].removeprefix("# created: ")
    datetime.fromisoformat(created)
    if content != manifest_text(entries, created):
        raise ValueError("Publication file list, sizes or checksums have changed")
    return entries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Reject every extra file except Git metadata")
    args = parser.parse_args()
    if args.verify:
        entries = verify(strict=args.strict)
    else:
        entries = snapshot(strict=args.strict)
        created = datetime.now(UTC).isoformat(timespec="seconds")
        MANIFEST.write_text(manifest_text(entries, created), encoding="utf-8", newline="\n")
    print(f"{'Verified' if args.verify else 'Hashed'} {len(entries)} files, "
          f"{sum(size for _, size, _ in entries):,} payload bytes")


if __name__ == "__main__":
    main()
