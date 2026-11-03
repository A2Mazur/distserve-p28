# Результаты и воспроизводимость

## Первая контрольная точка, 03.11.2026

Эти результаты относятся к подготовке эталона и проверке метрик.
Собственный событийный CPU-симулятор и основная экспериментальная серия ещё не выполнены.

- Входы, SLO, seeds и ресурсы: [configs/checkpoint-1.json](../configs/checkpoint-1.json).
- Копия конфигурации, использованной для сдачи: [config.json](../artifacts/checkpoint-1/config.json).
- Авторский код: [manifest с SHA-256](../third_party/distserve/UPSTREAM.json).
- Окружение и измеренная стоимость запуска: [environment.json](../artifacts/checkpoint-1/environment.json).
- Итог проверок: [checks.json](../artifacts/checkpoint-1/checks.json).
- Сырые события и per-request метрики: [artifacts/checkpoint-1/](../artifacts/checkpoint-1/).
- Сводка всех 18 запусков: [summary.csv](../artifacts/checkpoint-1/summary.csv).
- Все 96 аналитических сравнений: [analytical-checks.csv](../artifacts/checkpoint-1/analytical-checks.csv).
- Расчёт объёма и стоимости KV: [network-sanity.json](../artifacts/checkpoint-1/network-sanity.json).
- Контрольные суммы сохранённых результатов: [SHA256SUMS.json](../artifacts/checkpoint-1/SHA256SUMS.json).

У каждого запуска есть три файла: `.events.csv` — события запросов;
`.workers.csv` — события и батчи обработчиков; `.requests.csv` — метрики запросов.
Имена содержат сценарий, вариант размещения и seed.

### Краткая сводка

В обоих режимах два обработчика и один профиль `distserve`, TP=PP=1, сеть нулевая.
Каждый сценарий повторён с seeds 7, 11, 19; времена совпали, так как вход фиксирован,
а случайные chunk ID не влияют на его время. Это проверка повторяемости,
не три независимые случайные нагрузки.

| Сценарий | Размещение | Запросов | Средний TTFT, мс | Средний TPOT, мс | Выполнены оба SLO |
|---|---|---:|---:|---:|---:|
| single | colocated | 1 | 75.199881 | 22.347118 | 1/1 |
| single | disaggregated | 1 | 75.199881 | 22.347118 | 1/1 |
| isolated | colocated | 3 | 80.836007 | 22.378619 | 3/3 |
| isolated | disaggregated | 3 | 80.836007 | 22.378619 | 3/3 |
| burst | colocated | 6 | 97.953579 | 33.957264 | 6/6 |
| burst | disaggregated | 6 | 169.713635 | 25.249331 | 4/6 |

Один запрос: decode `89.3884719819263` мс, полное время `164.5883530353607` мс.
Максимальное расхождение с прямым расчётом по профилю во всех изолированных
случаях — `5.400124791776761e-13` мс при допуске `1e-8` мс.

В burst раздельный режим уменьшил средний TPOT, но увеличил ожидание prefill
и TTFT: отдельный prefill-пул содержит только один обработчик. Это демонстрация
различий очередей, не итоговый вывод о выгодности DistServe. Нагрузка мала,
сеть идеальная, разбиение фиксированное; средние не заменяют per-request SLO.
Расчётный goodput конечных контрольных трасс есть в `summary.csv`, но не
интерпретируется как устойчивая пропускная способность.

### Команды повторения

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/network_sanity.py --output artifacts/local/checkpoint-1/network-sanity.json
.venv/bin/python scripts/checkpoint1.py --output artifacts/local/checkpoint-1
.venv/bin/python scripts/verify_evidence.py artifacts/local/checkpoint-1
```

Проверка сохранённых свидетельств без установки внешних пакетов:

```bash
python3 scripts/verify_evidence.py artifacts/checkpoint-1
```

Новый запуск не должен перезаписывать сданный каталог. CSV при фиксированном
окружении детерминированы; `environment.json` и его SHA меняются из-за фактического
времени и памяти нового запуска. Полные серии и графики добавляются после
реализации собственной модели по [плану](experiment-plan.md).
