import argparse
import hashlib
import shutil
from pathlib import Path

from scripts.publication_manifest import MANIFEST, PROJECT, verify


def copy_release(destination: Path):
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("Release destination already exists. Use a fresh path or review it with the owner.")
    if destination == PROJECT or not destination.parent.is_dir() or destination.parent.is_symlink():
        raise ValueError("Release destination must have an existing parent and name a new directory")
    entries = verify()
    destination.mkdir()
    for expected, size, filename in entries:
        target = destination / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROJECT / filename, target)
        if target.stat().st_size != size or hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Release copy checksum mismatch for {filename}")
    shutil.copy2(MANIFEST, destination / MANIFEST.name)
    if MANIFEST.read_bytes() != (destination / MANIFEST.name).read_bytes():
        raise ValueError("Release manifest copy does not match its source")
    print(f"Verified {len(entries)} release files in {destination}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, default=PROJECT.with_name("AgentForge-Clean"))
    copy_release(parser.parse_args().destination)


if __name__ == "__main__":
    main()
