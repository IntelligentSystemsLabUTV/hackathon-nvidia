# Risultati principali della valutazione

I file grezzi (`results/`, `data/`, log) restano solo in locale e non sono in Git; si rigenerano con gli script (vedi [README.md](README.md)). Confronto prima/dopo: [docs/CONFRONTO_PERCEZIONE.md](../../docs/CONFRONTO_PERCEZIONE.md).

## Modelli vision, casa (184 domande: 128 bersagli visibili, 56 assenti)

| Configurazione | Trovati | Falsi pos. | Direzione (mediana) | IoU | Distanza ok |
|---|---|---|---|---|---|
| MiniCPM-V, 9 colonne, 768 px (prima) | 52% | 4% | 3,9° | — | 70% |
| MiniCPM-V, 9 colonne + parser corretto | 63% | 7% | 3,9° | — | 69% |
| MiniCPM-V, griglia 9×5 | 71% | 21–27% | 3,9–5,2° | 0,13–0,19 | 43–51% |
| MiniCPM-V, bbox | 80–82% | 12–14% | 5,0° | 0,13 | 55–60% |
| Gemma-3-27B, bbox | 77% | 5% | 9,7° | 0,11 | 53% |
| DeepSeek-V4.1-Flash, bbox (p90 latenza 23–29 s) | 70% | 4% | 0,3° | 0,81 | 89% |
| Kimi-K2.6, bbox 0–1000 | 85% | **2%** | **0,2°** | 0,74 | 72% |
| Kimi-K2.6, bbox in frazioni, 1024 px | 85% | **2%** | **0,2°** | **0,91** | **90%** |
| Kimi-K2.6, prompt finale (json_schema + porte), 1024 px — **in uso** | **86%** | 4% | **0,2°** | 0,90 | 88% |

Il grassetto indica il migliore di ogni colonna. Latenza in sequenza: MiniCPM 0,96 s, Kimi-K2.6 a 1024 px 0,99 s.

## ldc25 (idrante 1,4–9 m e semaforo, 14 positivi)

MiniCPM-V a colonne 2/14 (10 risposte scartate dal vecchio parser); Kimi-K2.6 14/14, errore di direzione massimo 0,4°, distanza entro 3 cm.

## YOLO a riquadri sui mobili COCO della casa (soglia 0,35)

| Modello | Recall | Tempo per frame (CPU) |
|---|---|---|
| YOLOv8n (attuale) | 36% | 0,47 s |
| YOLO11n / YOLO11s | 37% / 44% | 0,46 / 1,06 s |
| YOLO26n / YOLO26s (consigliato) / YOLO26m | 39% / **57%** / 53% | **0,43** / 0,99 / 2,76 s |
| YOLOE-26s / 26m (15 categorie, anche non COCO) | 38% / 43% | 1,17 / 3,11 s |

## Corse a ciclo chiuso (versione finale)

| Richiesta | Esito |
|---|---|
| casa, "vai vicino al frigorifero" (senza YOLO) | arrivato in 11 passi, 0,89 m (vero 0,87) |
| casa, "vai vicino al cestino della spazzatura" | arrivato in 5 passi, 0,73 m |
| casa, "vai vicino all'armadio" | 5 falsi avvistamenti respinti, armadio raggiunto a 0,81 m |
| ldc25, "cerca l'idrante rosso e vacci vicino" (senza YOLO / con YOLO) | arrivato in 10 / 15 passi |
