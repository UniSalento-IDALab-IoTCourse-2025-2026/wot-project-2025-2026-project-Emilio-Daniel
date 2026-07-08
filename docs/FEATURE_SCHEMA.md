# Edge AI Feature Schema

Ogni riga rappresenta una finestra temporale gia' aggregata dal Raspberry Pi, ad esempio 4 minuti.
Il modello non riceve dati grezzi continui: riceve feature compatte prodotte dagli adapter reali
Fitbit/Google Health, BLE e Shelly/NILM.

`window_start` e `window_end` nel CSV sono in UTC e rappresentano la finestra comune del
sistema. Il JSON decisione aggiunge anche `window_start_local` e `window_end_local` per
frontend e lettura umana.

Nota Google Health: il CSV resta sulla finestra corrente, ma l'adapter puo' leggere
internamente una finestra cloud piu' vecchia tramite `google_health.data_delay_minutes`.
Questo evita di spostare indietro anche il BLE, che invece arriva quasi in tempo reale.

Il campo `level` non sta nel CSV delle feature, ma nel JSON decisione. La scala e':
`green` sotto 35, `yellow` da 35, `orange` da 65, `red` da 80. `technical` e' separato
e indica problemi di raccolta dati o device.

## Colonne di contesto

| Colonna | Tipo | Origine |
| --- | --- | --- |
| patient_id | string | Configurazione locale |
| window_start | ISO datetime | Scheduler edge |
| window_end | ISO datetime | Scheduler edge |
| wearable_present | boolean | Fitbit device status o health adapter |
| wearable_battery_pct | number | Device API / paired device status |

## Feature numeriche

| Colonna | Origine reale prevista |
| --- | --- |
| heart_rate_mean | Google Health/Fitbit heart rate intraday |
| heart_rate_std | Google Health/Fitbit heart rate intraday |
| resting_heart_rate | Google Health/Fitbit daily resting heart rate |
| hrv_rmssd | Google Health/Fitbit HRV |
| spo2_mean | Google Health/Fitbit oxygen saturation |
| sleep_minutes | Google Health/Fitbit sleep |
| awake_minutes | Google Health/Fitbit sleep |
| steps | Google Health/Fitbit steps |
| sedentary_minutes | Google Health/Fitbit sedentary period/activity |
| room_changes | BLE positioning adapter |
| night_room_changes | BLE positioning adapter |
| bedroom_minutes | BLE permanence vector |
| kitchen_minutes | BLE permanence vector |
| bathroom_minutes | BLE permanence vector |
| living_room_minutes | BLE permanence vector |
| longest_single_room_minutes | BLE permanence vector |
| nilm_total_wh | Shelly EM / NILM adapter |
| nilm_kitchen_events | Shelly EM / NILM adapter |
| nilm_tv_minutes | Shelly EM / NILM adapter |
| nilm_coffee_events | Shelly EM / NILM adapter |
| nilm_stove_events | Shelly EM / NILM adapter |
| fall_events | Wear OS/Fitbit availability or manual event adapter |

## Note sulle feature wearable

- `heart_rate_mean` e' la media dei battiti nella finestra.
- `heart_rate_std` e' la deviazione standard dei battiti nella finestra: misura quanto il
  battito varia dentro quei minuti.
- Se Google Health non restituisce il battito nella finestra esatta, l'adapter puo' usare
  un lookback recente configurato con `heart_rate_lookback_minutes`.
- Se il battito e' valido ma `steps` non arriva, `steps` viene scritto come `0.0`.
- Se una sorgente non e' attiva o non ha dati, la relativa colonna puo' restare `nan`.

## CSV header

```csv
patient_id,window_start,window_end,wearable_present,wearable_battery_pct,heart_rate_mean,heart_rate_std,resting_heart_rate,hrv_rmssd,spo2_mean,sleep_minutes,awake_minutes,steps,sedentary_minutes,room_changes,night_room_changes,bedroom_minutes,kitchen_minutes,bathroom_minutes,living_room_minutes,longest_single_room_minutes,nilm_total_wh,nilm_kitchen_events,nilm_tv_minutes,nilm_coffee_events,nilm_stove_events,fall_events
```
