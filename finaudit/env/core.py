"""FinAuditEnv: reset/step в стиле Gymnasium над одним эпизодом аудита (JSON на входе и выходе)."""
from __future__ import annotations

import json
from pathlib import Path

from finaudit import ENV_VERSION
from finaudit.env.errors import EnvError
from finaudit.env.store import Store
from finaudit.env.tools import HANDLERS, PAGE_SIZE, check_keys
from finaudit.generator.episode_io import parse_public, read_files
from finaudit.grader.grader import GradeResult, empty_findings, grade
from finaudit.grader.matcher import tolerances
from finaudit.grader.validate_findings import (FINDING_TYPES, MAX_EVIDENCE, MAX_EXPLANATION,
                                               MAX_FINDINGS)
from finaudit.util.canon import dumps

MAX_STEPS = 100
TASK_TEXT = (
    "Вы проводите аудит одной компании за один календарный месяц. Через инструменты доступны ledger "
    "(базовая валюта, целые минимальные единицы), счета (invoices), платежи (payments) и дневные курсы FX. "
    "Найдите бухгалтерские расхождения перечисленных типов выводов и отправьте их один раз действием "
    "'submit'. Каждый вывод называет затронутые значения invoice_id/payment_id, сумму в минимальных единицах "
    "в валюте, закреплённой за его типом (см. policy.finding_currency_by_type), и evidence_ids: ID записей "
    "(row_id строки ledger, doc_id документа, fx-ID 'fx:DATE:SRC:TGT'), которые вместе его доказывают. "
    "Каждый шаг стоит 0.002 награды; у вас 100 шагов, включая submit."
)


def _obs(result: object = None, error: EnvError | None = None, steps_left: int = 0) -> dict:
    return {"ok": error is None, "result": result,
            "error": None if error is None else {"code": error.code, "message": error.message},
            "steps_left": steps_left}


class FinAuditEnv:
    """Один экземпляр среды; ``reset`` полностью заменяет всё состояние эпизода."""

    def __init__(self, grader_log: str | Path | None = None) -> None:
        self.grader_log = Path(grader_log) if grader_log else None
        self.policy_name = "unknown"
        self._loaded = False

    # ------------------------------------------------------------------ жизненный цикл
    def reset(self, seed: int | None = 0, config: dict | None = None) -> tuple[dict, dict]:
        """Начинает эпизод из ``config['episode_dir']`` или генерирует его из (seed, config).

        ``seed=None`` означает seed 0 (среда никогда не берёт энтропию у ОС).
        """
        config = dict(config or {})
        seed = 0 if seed is None else int(seed)
        self.mode = config.get("mode", "train")
        if self.mode not in ("train", "eval"):
            raise ValueError("mode must be train or eval")
        if config.get("episode_dir"):
            files = read_files(config["episode_dir"])
        else:
            from finaudit.generator.generate import generate_episode
            files = generate_episode(seed, config).files
        public = parse_public(files)
        if "private/truth.json" in files:
            self.truth = json.loads(files["private/truth.json"])
        elif self.mode == "eval":  # закрытый прогон оценивается снаружи (judge_adapter.score_episode): награда всё равно 0
            self.truth = {"episode_id": public["manifest"]["episode_id"], "issues": []}
        else:
            raise ValueError("train mode needs private/truth.json in episode_dir")
        self.manifest = public["manifest"]
        self.policy_doc = public["policy"]
        self.tol = tolerances(self.policy_doc)
        self.store = Store(public)
        self.steps_used = 0
        self.done = False
        self.flags = (False, False)
        self.last_grade: GradeResult | None = None
        self._loaded = True
        result = {"task": TASK_TEXT, "manifest": self.manifest, "policy": self.policy_doc,
                  "tables": ["ledger", "invoices", "payments", "fx"],
                  "finding_types": list(FINDING_TYPES),
                  "limits": {"max_steps": MAX_STEPS, "page_size": PAGE_SIZE,
                             "max_findings": MAX_FINDINGS, "max_evidence": MAX_EVIDENCE,
                             "max_explanation": MAX_EXPLANATION}}
        return json.loads(dumps(_obs(result, steps_left=MAX_STEPS))), {"env_version": ENV_VERSION}

    @property
    def steps_left(self) -> int:
        """Оставшийся бюджет шагов."""
        return MAX_STEPS - self.steps_used

    # ------------------------------------------------------------------ шаг
    def step(self, action: object) -> tuple[dict, float, bool, bool, dict]:
        """Применяет одно действие; каждый вызов до завершения расходует один шаг."""
        if not self._loaded:
            raise RuntimeError("call reset() first")
        if self.done:
            err = EnvError("EPISODE_DONE", "эпизод завершён")
            return _obs(error=err, steps_left=self.steps_left), 0.0, *self.flags, self._info(None)
        self.steps_used += 1
        try:
            if not isinstance(action, dict):
                raise EnvError("BAD_ARGS", "действие должно быть JSON-объектом")
            name = check_keys(action)
            if name == "submit":
                return self._submit(action["findings"])
            obs = _obs(HANDLERS[name](self.store, action), steps_left=self.steps_left)
        except EnvError as err:
            obs = _obs(error=err, steps_left=self.steps_left)
        except Exception:  # враждебный ввод не должен ронять среду: ограниченная ошибка, шаг всё равно засчитан
            obs = _obs(error=EnvError("BAD_ARGS", "действие не удалось обработать"), steps_left=self.steps_left)
        if self.steps_used >= MAX_STEPS:
            return self._finish(obs, empty_findings(self.truth["episode_id"]), truncated=True)
        return obs, 0.0, False, False, self._info(None)

    def force_truncate(self) -> tuple[dict, float, bool, bool, dict]:
        """Достигнут лимит реального времени (вызывает runner): оценивается пустой ответ."""
        if self.done:
            err = EnvError("EPISODE_DONE", "эпизод завершён")
            return _obs(error=err, steps_left=self.steps_left), 0.0, *self.flags, self._info(None)
        obs = _obs(error=EnvError("EPISODE_DONE", "достигнут лимит времени"), steps_left=self.steps_left)
        return self._finish(obs, empty_findings(self.truth["episode_id"]), truncated=True)

    # ------------------------------------------------------------------ внутреннее
    def _submit(self, findings: object) -> tuple[dict, float, bool, bool, dict]:
        inspection = self.steps_used - 1
        result = grade(self.truth, findings, self.store.ids, inspection, self.tol)
        if not result.valid:
            msg = result.reason if self.mode == "train" else "структура findings отклонена"
            obs = _obs(error=EnvError("INVALID_FINDINGS", f"findings отклонены: {msg}"),
                       steps_left=self.steps_left)
        else:
            n = len(findings["findings"])  # type: ignore[index]
            obs = _obs({"submitted": True, "n_findings": n}, steps_left=self.steps_left)
        return self._finish(obs, None, truncated=False, result=result)

    def _finish(self, obs: dict, findings: dict | None, truncated: bool,
                result: GradeResult | None = None) -> tuple[dict, float, bool, bool, dict]:
        if result is None:
            result = grade(self.truth, findings, self.store.ids, self.steps_used, self.tol)
        self.done = True
        self.flags = (not truncated, truncated)
        self.last_grade = result
        self._log(result, truncated)
        reward = result.reward if self.mode == "train" else 0.0
        return obs, reward, self.flags[0], self.flags[1], self._info(result)

    def _info(self, result: GradeResult | None) -> dict:
        if self.mode == "eval" or result is None:
            return {"steps_used": self.steps_used}
        return result.agent_info()

    def _log(self, result: GradeResult, truncated: bool) -> None:
        if self.grader_log is None:
            return
        rec = {"episode_id": self.truth["episode_id"], "policy": self.policy_name, "mode": self.mode,
               "truncated": truncated, "steps_used": self.steps_used, "env_version": ENV_VERSION,
               "n_issues": len(self.truth["issues"]), **result.to_dict()}
        self.grader_log.parent.mkdir(parents=True, exist_ok=True)
        with open(self.grader_log, "a", encoding="utf-8") as fh:
            fh.write(dumps(rec) + "\n")
