# DistServe

**Проектное задание:** [P28. DistServe: раздельное выполнение prefill и decode](https://distsys.ru/osukhoroslov/nis2/src/branch/main/project-tasks/p28-distserve.md)

**Участники:**

- Плахута Алексей
- Серебренников Дан
- Мазур Александр

## Сокращённый запуск

Первая точка: запуск **авторского эталона** и независимая аналитическая проверка.
Собственный событийный симулятор — следующий этап. Нужны Python 3.11–3.14, CPU
и до 1 ГБ RAM для этих проверок. Проверено на Python 3.14.8, macOS arm64.
GPU, Docker, веса LLM и ShareGPT не нужны. Интернет требуется только для
установки зависимостей: эталон и профили уже включены.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/checkpoint1.py --output artifacts/local/checkpoint-1
.venv/bin/python scripts/verify_evidence.py artifacts/local/checkpoint-1
```

Ожидается `PASS`: 18 прогонов, 60 завершений запросов, 96 аналитических сравнений
с погрешностью ≤`1e-8` мс. Новый запуск сохраняется отдельно от
[сданных результатов](artifacts/checkpoint-1/). Протокол и ограничения:
[контрольная точка 1](nis/checkpoints/01.md).

## Навигация

- [Описание проекта](nis/project.md)
- [План эксперимента](nis/experiment-plan.md)
- [Контрольная точка 1](nis/checkpoints/01.md)
- [Состояние проекта](nis/status.md)
- [Результаты](nis/results.md)
- [Адаптер эталона и аналитические проверки](scripts/checkpoint1.py)
- [Проверка целостности свидетельств](scripts/verify_evidence.py)
- [Входы и настройки проверок](configs/checkpoint-1.json)
- [Исходные события, метрики и окружение](artifacts/checkpoint-1/)
- [Происхождение и лицензия эталона](third_party/distserve/README.md)

Файлы второй, третьей точки и итоговой сдачи добавляются к соответствующим этапам.
