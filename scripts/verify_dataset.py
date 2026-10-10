"""Verify repository-owned corpus bytes, without database or network access."""

import hashlib
import json
from pathlib import Path


def main() -> None:
    dataset = Path(__file__).resolve().parents[1] / "datasets"
    manifest = json.loads((dataset / "manifest.json").read_text())
    for entry in manifest["files"]:
        path = dataset / entry["path"]
        if not path.is_file():
            raise SystemExit(f"Missing corpus file: {entry['path']} (run git lfs pull)")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        if path.stat().st_size != entry["bytes"] or digest.hexdigest() != entry["sha256"]:
            raise SystemExit(f"Corpus mismatch: {entry['path']} (check git lfs pull)")
    print(f"Verified {len(manifest['files'])} corpus files; no database/network accessed.")


if __name__ == "__main__":
    main()
