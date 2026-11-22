"""Запуск задач за каждой целью Makefile (также используется как `make` внутри Docker).

python -m finaudit.tasks {test|episodes|trajectories|check|jury|demo|report}
"""
from __future__ import annotations

import subprocess
import sys
import time

TARGETS = ("install", "test", "episodes", "trajectories", "check", "jury", "demo", "report")


def _run(*args: str) -> int:
    return subprocess.call([sys.executable, *args])


def run_target(name: str) -> int:
    """Запускает одну цель; возвращает код выхода процесса."""
    if name == "install":
        return _run("-m", "pip", "install", "--no-index", "--find-links", "vendor/wheels",
                    "-r", "requirements.lock", "-r", "requirements-dev.lock")
    if name == "test":
        return _run("-m", "pytest", "-q")
    if name == "episodes":
        return _run("-m", "finaudit.dataset")
    if name == "trajectories":
        return _run("-m", "finaudit.runner", "trajectories")
    if name == "check":
        start = time.monotonic()
        status = run_target("test") or _run("-m", "finaudit.smoke")
        sys.stdout.write(f"make check: {'OK' if status == 0 else 'СБОЙ'} "
                         f"за {time.monotonic() - start:.1f} с\n")
        return status
    if name == "jury":
        return _run("-m", "finaudit.jury")
    if name == "demo":
        return _run("-m", "finaudit.demo")
    if name == "report":
        return _run("-m", "finaudit.report")
    sys.stderr.write(f"неизвестная цель {name!r}; известные: {', '.join(TARGETS)}\n")
    return 2


def main(argv: list[str] | None = None) -> int:
    """Запускает цели из командной строки (по умолчанию: check)."""
    names = (argv if argv is not None else sys.argv[1:]) or ["check"]
    for name in names:
        status = run_target(name)
        if status:
            return status
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
