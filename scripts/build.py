from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import ambitious_kit
from ambitious_kit.build import build_zipapp

from ambitious_constraints import MODULE, VERSION

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    dist = ROOT / "dist"
    asset = f"ambitious-{MODULE}-{VERSION}.pyz"
    lock = f"ambitious-{MODULE}-{VERSION}.runtime.txt"
    build_zipapp(
        dist / asset,
        [ROOT / "src" / "ambitious_constraints", Path(ambitious_kit.__file__).resolve().parent],
        "ambitious_constraints.cli.main:main",
    )
    (dist / lock).write_bytes((ROOT / "src" / "ambitious_constraints" / "runtime.txt").read_bytes())
    sums = "".join(
        f"{hashlib.sha256((dist / name).read_bytes()).hexdigest()}  {name}\n" for name in sorted((asset, lock))
    )
    (dist / "SHA256SUMS").write_text(sums, encoding="utf-8")
    link = dist / f"ambitious-{MODULE}.pyz"
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(asset)
    sys.stdout.write(sums)


if __name__ == "__main__":
    main()
