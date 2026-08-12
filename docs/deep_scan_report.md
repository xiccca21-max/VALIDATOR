# Deep scan — оригиналы чеки

Всего: **190** | ЧИСТО: **190** | ФЕЙК: **0**

## По банкам

| Банк | Файлов | ФЕЙК | Мягкие флаги |
|------|--------|------|--------------|
| alfa | 14 | 0 | 0 |
| bchpb | 1 | 0 | 0 |
| gazprombank | 3 | 0 | 1 |
| otp | 2 | 0 | 0 |
| ozon | 11 | 0 | 0 |
| psb | 4 | 0 | 0 |
| raif | 3 | 0 | 0 |
| rocket | 1 | 0 | 0 |
| sber | 7 | 0 | 0 |
| sovkom | 1 | 0 | 1 |
| tbank | 126 | 0 | 10 |
| uralsib | 2 | 0 | 2 |
| vtb | 10 | 0 | 0 |
| yandex | 5 | 0 | 0 |

## Мягкие сигналы (не ФЕЙК, но стоит знать)

- **gazprombank** `газпромбанк сбп1.pdf`: ['CONTENT_STREAM_PROFILE_MISMATCH', 'MULTIPLE_WEAK_ANOMALIES', 'PROFILE_CLUSTER_OUTLIER']
- **sovkom** `совкомбанк по номеру карты в другой банк.pdf`: ['OBJECT_GRAPH_INCONSISTENT', 'PAGE_RESOURCES_INCONSISTENT', 'RESOURCE_REFERENCE_BROKEN']
- **tbank** `$R4L3XYX.pdf`: ['CONTENT_STREAM_PROFILE_MISMATCH', 'MULTIPLE_WEAK_ANOMALIES', 'PROFILE_CLUSTER_OUTLIER']
- **tbank** `$R6TYL3H.pdf`: ['CONTENT_STREAM_PROFILE_MISMATCH', 'MULTIPLE_WEAK_ANOMALIES', 'PROFILE_CLUSTER_OUTLIER']
- **tbank** `$R8ALH0O.pdf`: ['CONTENT_STREAM_PROFILE_MISMATCH', 'MULTIPLE_WEAK_ANOMALIES', 'PROFILE_CLUSTER_OUTLIER']
- **tbank** `$RB4UIPR.pdf`: ['CONTENT_STREAM_PROFILE_MISMATCH', 'MULTIPLE_WEAK_ANOMALIES', 'PROFILE_CLUSTER_OUTLIER']
- **tbank** `$RBH5Z4V.pdf`: ['CONTENT_STREAM_PROFILE_MISMATCH', 'MULTIPLE_WEAK_ANOMALIES', 'PROFILE_CLUSTER_OUTLIER']
- **tbank** `$RBNZNUE.pdf`: ['CONTENT_STREAM_PROFILE_MISMATCH', 'MULTIPLE_WEAK_ANOMALIES', 'PROFILE_CLUSTER_OUTLIER']
- **tbank** `$RTSX13Y.pdf`: ['CONTENT_STREAM_PROFILE_MISMATCH', 'MULTIPLE_WEAK_ANOMALIES', 'PROFILE_CLUSTER_OUTLIER']
- **tbank** `$RUU302M.pdf`: ['CONTENT_STREAM_PROFILE_MISMATCH', 'MULTIPLE_WEAK_ANOMALIES', 'PROFILE_CLUSTER_OUTLIER']
- **tbank** `2 Т банк на карту другого банка.pdf`: ['CONTENT_STREAM_PROFILE_MISMATCH', 'MULTIPLE_WEAK_ANOMALIES', 'PROFILE_CLUSTER_OUTLIER']
- **tbank** `т баннк по карте.pdf`: ['CONTENT_STREAM_PROFILE_MISMATCH', 'MULTIPLE_WEAK_ANOMALIES', 'PROFILE_CLUSTER_OUTLIER']
- **uralsib** `уралсиб сбп.pdf`: ['CID_SEQUENCE_ANOMALY', 'MULTIPLE_WEAK_ANOMALIES', 'PROFILE_CLUSTER_OUTLIER']
- **uralsib** `уралсиб сбп4.pdf`: ['CID_SEQUENCE_ANOMALY', 'MULTIPLE_WEAK_ANOMALIES', 'PROFILE_CLUSTER_OUTLIER']
