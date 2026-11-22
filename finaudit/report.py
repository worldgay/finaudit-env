"""`make report`: собирает REPORT.txt из runs/jury/summary.json (только измеренные числа)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ATTACK_LABELS = {
    "oracle": "oracle (эталонный ответ, 0 шагов)",
    "oracle_each_finding_twice": "oracle, каждый вывод отправлен дважды",
    "oracle_each_finding_twice_f1": "  … его F1",
    "oracle_guessed_evidence": "oracle с угаданными (несуществующими) ID доказательств",
    "oracle_partial_evidence": "oracle без одного ID доказательства",
    "oracle_wrong_currency": "oracle с неверной валютой",
    "oracle_amount_off_tol_plus_1": "oracle с суммой, отличающейся на допуск + 1",
    "oracle_10_minus_60_steps": "награда(10 шагов) − награда(60 шагов), тот же ответ",
    "flag_all": "пометить каждый документ × каждый тип (≤ 30)",
    "silence_clean": "пустой ответ на чистых компаниях (0 шагов)",
    "silence_with_errors": "пустой ответ на компаниях с ошибками",
    "false_accusation_clean": "один выдуманный вывод на чистой компании",
}
# Причины из finaudit/analysis.py (в summary.json хранятся как есть).
REASONS_RU = {
    "FX conversions are not checked by this baseline": "эта базовая политика не проверяет конвертации FX",
    "issued after period end in local time, but its UTC date is inside the period":
        "выставлен после конца периода по местному времени, но его UTC-дата внутри периода",
    "copies more than 3 UTC days apart": "копии разнесены больше чем на 3 UTC-дня",
    "partial allocation of a foreign-currency payment (needs the FX rate)":
        "частичное распределение платежа в иностранной валюте (нужен курс FX)",
    "in-period document whose UTC date falls outside the period (time-zone trap)":
        "документ периода, чья UTC-дата вне периода (ловушка часового пояса)",
    "allocation flagged without a real gap (split / partial view)":
        "распределение помечено без реального расхождения (разбивка / частичный просмотр)",
    "other": "прочее",
}


def _ru(reason: str) -> str:
    typ, _, text = reason.partition(": ")
    return f"{typ}: {REASONS_RU.get(text, text)}" if text else REASONS_RU.get(reason, reason)


def _policy_table(s: dict) -> list[str]:
    out = ["| Политика | Средняя награда | Средний F1 | Precision (micro) | Recall (micro) | Шаги | TP / FP / FN "
           "| Среднее, с | Макс., с |",
           "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, p in s["policies"].items():
        out.append(f"| {name} | {p['mean_reward']:+.3f} | {p['mean_f1']:.3f} | {p['micro_precision']:.3f} | "
                   f"{p['micro_recall']:.3f} | {p['mean_steps']:.1f} | {p['tp']} / {p['fp']} / {p['fn']} | "
                   f"{p['mean_seconds']:.3f} | {p['max_seconds']:.3f} |")
    return out


def _group_table(s: dict) -> list[str]:
    groups = list(next(iter(s["policies"].values()))["by_group"])
    out = ["| Политика | " + " | ".join(f"{g}: награда / F1" for g in groups) + " |",
           "|---|" + "---:|" * len(groups)]
    for name, p in s["policies"].items():
        cells = [f"{p['by_group'][g]['mean_reward']:+.3f} / {p['by_group'][g]['mean_f1']:.3f}" for g in groups]
        out.append(f"| {name} | " + " | ".join(cells) + " |")
    return out


def _failure_section(s: dict) -> list[str]:
    f = s["reconciler_failures"]
    out = ["| Тип | Ошибок | Найдено (TP) | Пропущено (FN) | Recall |", "|---|---:|---:|---:|---:|"]
    for typ, n in f.get("issues", {}).items():
        tp = f.get("tp", {}).get(typ, 0)
        out.append(f"| {typ} | {n} | {tp} | {f.get('fn', {}).get(typ, 0)} | {tp / n:.2f} |")
    out += ["", "Почему ошибки пропущены (измерено по каждой ошибке на открытых данных):", ""]
    out += [f"- {_ru(k)} — **{v}**" for k, v in f.get("fn_reason", {}).items()]
    out += ["", "Почему выводы оказались ложными (FP):", ""]
    out += [f"- {_ru(k)} — **{v}**" for k, v in f.get("fp_reason", {}).items()] or ["- нет"]
    return out


def build(summary: dict) -> str:
    """Собирает текст отчёта."""
    s = summary
    c, r = s["checks"], s["resources"]
    lines = ["# REPORT — RL-среда FinAudit, версия данных " + s["env_version"], "",
             "Все числа ниже измерены `make jury` и перенесены из `runs/jury/summary.json` командой "
             "`make report`. Модели не обучались; политики — фиксированные базовые.", "",
             f"Условия: {s['n_episodes']} новых эпизодов ({', '.join(f'{v} {k}' for k, v in s['groups'].items())}), "
             f"всего {s['issues_total']} скрытых ошибок, каждая политика запускалась в **режиме eval** (env-server и "
             "агент — отдельные процессы; награда скрыта от агента и читается из grader_log.jsonl).", "",
             "## Базовые политики", ""] + _policy_table(s) + [
                 "", "Precision/recall усреднены micro по всем 20 эпизодам (P и R эпизода по определению равны 0, "
                 "когда знаменатель 0, например пустой ответ на чистой компании, поэтому простое среднее вводило бы "
                 "в заблуждение). Шаги = использованные шаги включая submit.",
                 "", "### По группам эпизодов", ""] + _group_table(s)
    lines += ["", "## Проверки в стиле жюри", "",
              f"- Минимальная награда oracle: **{c['oracle_min_reward']}** (требуется ≥ 0.9)",
              f"- Ранжирование oracle > reconciler > random_explorer ≥ flag_all: **{c['ranking_ok']}**",
              f"- Средняя награда flag_all ≤ −0.5: **{c['flag_all_mean_le_-0.5']}**",
              f"- F1 reconciler строго между flag_all и oracle: **{c['reconciler_f1_strictly_between']}**",
              f"- Парные проверки (перемешивание + переименование всех ID → та же награда oracle, то же число "
              f"ошибок, verify OK): **{s['paired']['passed']}/{s['paired']['total']}**",
              f"- Повторы (тот же seed → идентичный sha256 каждого файла; тот же seed политики → идентичные байты "
              f"траектории и награда): **{s['replay']['passed']}/{s['replay']['total']}**", "",
              "## Разбор сбоев базовой политики reconciler", ""] + _failure_section(s)
    lines += ["", "## Атаки на награду (измерены на тех же эпизодах, режим train)", "",
              "| Атака | Средняя награда |", "|---|---:|"]
    lines += [f"| {ATTACK_LABELS.get(k, k)} | {v:+.6g} |" for k, v in s["attacks"].items()]
    lines += ["", "## Ресурсы", "",
              f"- Весь прогон `make jury`: {r['total_seconds']} с; самый медленный эпизод (с запуском процессов): "
              f"{r['max_episode_seconds']} с (лимит 60 с).",
              f"- Пиковый RSS: оркестратор {r['peak_rss_mb_self']} МБ, самый большой дочерний процесс "
              f"{r['peak_rss_mb_children']} МБ.",
              "- `tests/test_limits.py`: самый большой эпизод (≈2000 строк ledger, ≈200 документов, 12 ошибок) — "
              "генерация + 100 шагов + оценка < 5 с и < 500 МБ.", "",
              "## Ограничения", "", "См. раздел «Честные ограничения» в DESIGN.txt.", ""]
    return "\n".join(lines)


def main() -> int:
    """Точка входа CLI."""
    summary = json.loads((ROOT / "runs" / "jury" / "summary.json").read_text(encoding="utf-8"))
    (ROOT / "REPORT.txt").write_text(build(summary), encoding="utf-8", newline="\n")
    sys.stdout.write("report: REPORT.txt записан\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
