# Соответствие критериям оценки (docs/TASK.md, раздел 10) — v1.2.0

Определения проверок жюри (20.11.2026) сохранены в `docs/CHECKS.md`. Точка подключения — `judge_adapter.py`
(README, раздел «Jury adapter»). Блок 1 (C01–C20) проверяется `tests/test_judge_adapter.py`, блок 3 (тесты 1–20 и
примеры M01–M12) — `tests/test_jury_matcher.py`, блок 4 — `make jury` (парные 20/20, повторы 20/20).

| Блок | Что проверяет жюри | Где это у нас | Подтверждение |
|---|---|---|---|
| Контракт и изоляция (25) | reset/step, схемы, лимиты, завершение, неверный ввод, нет утечек | `finaudit/env/core.py`, `tools.py`, `store.py`, `calculator.py`, `finaudit/schemas/*.json`, `runner.py` (eval: 3 процесса, users grader/agent) | `test_judge_adapter` (C01–C20 через адаптер жюри), `test_contract` (≈40 проверок, все коды ошибок, 100 шагов, EPISODE_DONE, eval без награды, согласие схемы и среды), `test_calculator`, `test_pagination`, `test_no_leak`, `test_isolation` (docker: Permission denied на private/) |
| Данные и эталон (25) | равенства до ошибки, объявленное расхождение после, независимая достаточность доказательств | `generator/books.py` (check_invariants), `revert.py` (откат provenance → равенства до ошибки), `reference_audit.py` (независимый аудитор), `verify.py` (+CLI) | `test_generator_invariants` (1000 seed), `test_verify` (испорченные truth/provenance/public ловятся), `test_errors_each_type`, `test_interactions`, `test_distractors`, `test_config_combinations` (5 валют × 6 поясов) |
| Надёжность награды (25) | сопоставление, чистые, FP, дубли, стоимость, атаки | `grader/validate_findings.py`, `matcher.py`, `reward.py` | `test_jury_matcher` (блок 3: 20 тестов + M01–M12 с точными числами), `test_matcher`, `test_reward_attacks` (12 атак с точными числами + oracle на 50 seed), `attacks.py` в REPORT.md |
| Воспроизводимость и обобщение (15) | повтор seed/действий; перестановка и смена ID сохраняют ответ oracle и награду | `util/rng.py`, `util/canon.py`, `generator/transform.py` | `test_reproducibility` (байт-в-байт, независимо от PYTHONHASHSEED), `test_transform`, `make jury`: парные 20/20, повторы 20/20 |
| Инженерия и объяснение (10) | одна команда, версии конфигов, журналы траекторий, измеренный разбор сбоев, честные ограничения | README (1-я строка), `configs/*.json` (`config_version`), `trajectories/trajectories.jsonl`, `REPORT.md` (причины FN/FP по каждой ошибке), DESIGN.md §8 | `make docker-check`, `make jury`, `make report` |

Блокирующие условия: утечка (leakscan = 0 по всем эпизодам и траекториям), запись в оценщик (агент — отдельный
процесс без доступа к private/ и grader_log), реальные данные (только слоговые имена, без IBAN/карт), неработающее
ядро (`make check` зелёный в контейнере без сети).
