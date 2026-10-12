# Confronto della percezione: prima e ora (con e senza YOLO)

Misure su 56 frame della casa in Gazebo (128 bersagli visibili, di cui 68 COCO e 60 non COCO; 56 domande con bersaglio assente) e 14 frame di ldc25. Un bersaglio conta come trovato solo se la posizione indicata cade sull'oggetto vero. Dettagli: [CHANGELOG.md](CHANGELOG.md); script e dati: [scripts/vision_eval](../scripts/vision_eval/RISULTATI.md).

| | Prima | Ora, con YOLO | Ora, senza YOLO (default) |
|---|---|---|---|
| Configurazione | YOLOv8n + MiniCPM-V a 9 colonne, parser vecchio | `NEBIUS_PERCEPTION=yolo`: YOLOv8n + Kimi-K2.6 a box | `NEBIUS_PERCEPTION=vlm`: solo Kimi-K2.6 a box |
| Bersagli COCO trovati (casa) | 57% (39/68), solo il 26% con box preciso | **87% (59/68)** | **87% (59/68)** |
| Bersagli non COCO trovati (casa) | 35% (21/60) | **85% (51/60)** | **85% (51/60)** |
| Totale casa | 47% (60/128) | **86% (110/128)** | **86% (110/128)** |
| Falsi positivi del modello vision | 4% | 4% | 4% |
| Errore di direzione (mediana) | 3,9° (colonna), 0,2° quando c'è YOLO | **0,2°** | **0,2°** |
| Distanza corretta (entro 0,3 m o 20%) | 70% | **88%** | **88%** |
| Idrante ldc25 (1,4–9 m) | YOLO 14/14; MiniCPM 2/14 | **14/14** | **14/14** |
| Latenza della percezione per passo | **~1,5 s** (YOLO e vision in parallelo) | **~1,5 s** | 1,7–1,9 s |
| Costo modello vision per chiamata | **~$0,0004** | ~$0,0015 | ~$0,0015 |
| Arrivi falsi a ciclo chiuso | non protetti (sedia davanti al frigo, porta presa per armadio) | **bloccati dalle guardie** | **bloccati dalle guardie** |

In grassetto il valore migliore di ogni riga. Il default è senza YOLO (`NEBIUS_PERCEPTION=vlm`): con YOLO o senza i numeri sono uguali perché nella casa YOLOv8n riconosce pochi mobili renderizzati e il lavoro lo fa quasi tutto Kimi-K2.6. Con YOLO26s al posto di YOLOv8n (opzionale, `AGENTICROS_YOLOV8_MODEL`) i bersagli COCO trovati salgono all'88% (60/68). YOLO da solo sui mobili COCO della casa: YOLOv8n 36%, YOLO26s 57%.
