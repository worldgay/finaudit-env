"""Сервер JSON-строк вокруг FinAuditEnv (среда + оценщик в одном процессе).

Протокол: один JSON-объект на строку в stdin -> один JSON-объект на строку в stdout:
  {"cmd": "reset", "seed": 0, "config": {"episode_dir": "...", "mode": "eval"}}
      -> {"observation": {...}, "info": {...}}
  {"cmd": "step", "action": {...}}  -> {"observation", "reward", "terminated", "truncated", "info"}
  {"cmd": "timeout"}                -> та же форма (обрезка по реальному времени)
  {"cmd": "close"}                  -> процесс завершается
С этим процессом общается только runner; агент никогда не видит его stdin/stdout.
"""
from __future__ import annotations

import argparse
import json
import sys

from finaudit.env.core import FinAuditEnv
from finaudit.util.canon import dumps


def _reply(obj: dict) -> None:
    sys.stdout.write(dumps(obj) + "\n")
    sys.stdout.flush()


def _step_reply(out: tuple) -> dict:
    obs, reward, terminated, truncated, info = out
    return {"observation": obs, "reward": reward, "terminated": terminated,
            "truncated": truncated, "info": info}


def serve(env: FinAuditEnv) -> int:
    """Главный цикл: читает команды до EOF или close."""
    for line in sys.stdin:
        try:
            msg = json.loads(line)
            cmd = msg.get("cmd")
            if cmd == "reset":
                obs, info = env.reset(int(msg.get("seed", 0)), msg.get("config") or {})
                _reply({"observation": obs, "info": info})
            elif cmd == "step":
                _reply(_step_reply(env.step(msg.get("action"))))
            elif cmd == "timeout":
                _reply(_step_reply(env.force_truncate()))
            elif cmd == "close":
                return 0
            else:
                _reply({"fatal": "unknown command"})
        except Exception:  # никогда не отдаём трассировки в pipe
            _reply({"fatal": "internal error"})
    return 0


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI."""
    ap = argparse.ArgumentParser(description="Сервер среды FinAudit (JSON-строки)")
    ap.add_argument("--grader-log", default=None)
    ap.add_argument("--policy-name", default="unknown")
    args = ap.parse_args(argv)
    env = FinAuditEnv(grader_log=args.grader_log)
    env.policy_name = args.policy_name
    return serve(env)


if __name__ == "__main__":
    raise SystemExit(main())
