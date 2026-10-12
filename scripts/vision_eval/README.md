# Valutazione della percezione (modelli vision e YOLO)

Script dello studio che ha portato alla percezione attuale. Contesto e conclusioni: [`docs/CHANGELOG_PERCEZIONE_VLM.md`](../../docs/CHANGELOG_PERCEZIONE_VLM.md) e [`docs/PIANO_PERCEZIONE_VLM.md`](../../docs/PIANO_PERCEZIONE_VLM.md). Risultati principali: [`RISULTATI.md`](RISULTATI.md). Dati e risultati grezzi (`data/`, `results/`, `.json`, `.jsonl`, `.log`) restano solo in locale: non sono in Git.

Tutto va eseguito nel container, da questa cartella. `.env` viene caricato dagli script che chiamano Nebius, ma la chiave non viene mai stampata.

## Cosa c'è

| Percorso | Contenuto | In Git |
|---|---|---|
| `data/frames/` | 56 frame della casa e 20 di ldc25: PNG 1920×1080, profondità `.depth.npy`, posa reale `.json` | no (~130 MB, si rigenera) |
| `data/masks/` | maschere visibili per oggetto, generate da `gt2.py` | no |
| `data/extra_frames/` | frame della diagnosi (sedia davanti al frigo, porta a soffietto), fuori dal set di valutazione | no |
| `data/gt.json` | verità a terra della casa: box visibile, distanza, bearing per oggetto e frame | no |
| `data/ldc_ref.json` | riferimento ldc25 (YOLO26s a riquadri, ≥ 0,5) | no |
| `results/vlm/` | una riga per domanda, per ogni configurazione di modello vision (184 domande) | no |
| `results/vlm_ldc25/` | idem su ldc25 | no |
| `results/yolo/` | detection a riquadri di YOLOv8n, YOLO11, YOLO26, YOLOE-26 | no |
| `results/closed_loop/` | log delle 10 corse a ciclo chiuso del prototipo | no |

## Script

| Script | Scopo |
|---|---|
| `capture.py`, `capture_all.sh`, `capture_ldc.sh` | catturano RGB, profondità e posa ruotando sul posto, dopo aver teleportato il robot nelle stanze (sim in esecuzione) |
| `gt2.py` | verità a terra della casa: rasterizza le mesh dei mobili e le confronta con la profondità |
| `draw_gt2.py` | disegna verità a terra e maschere su alcuni frame |
| `eval_vlm.py` | interroga i modelli vision su tutte le domande; le configurazioni sono in `CONFIGS` |
| `score.py` | metriche: trovati, falsi positivi, bearing, IoU, distanza, latenza (`--robust` = parser corretto) |
| `analyze.py` | elenca i casi falliti di una configurazione (`dist`, `fn`, `fp`) |
| `latency_seq.py` | latenza in sequenza, senza concorrenza |
| `ldc_eval.py` | idrante e semaforo su ldc25 (`yolo`, `vlm <cfg>`, `score <cfg>`) |
| `yolo_eval.py`, `yolo_score.py` | replica Python di `detectClassTiled` su qualunque ONNX `[1, 4+nc, N]` |
| `yoloe_eval.py`, `yoloe_score.py` | YOLOE-26 open-vocabulary con le classi della casa |
| `probe_vision.py`, `probe_nothink.py`, `probe_latency.py` | quali modelli Nebius accettano immagini, come spegnere il thinking, latenza |
| `closed_loop.sh`, `hydrant_run.sh`, `pose_now.sh`, `dist_to.py` | corse a ciclo chiuso con verifica dell'arrivo sulla posa reale |

## Esempi

```bash
cd ~/workspace/scripts/vision_eval

# punteggi (servono i risultati locali in results/)
../../.venv/bin/python score.py --robust kimi26_final_1024 minicpm_cols9_768
python3 yolo_score.py yolo26s yolov8n_project
../../.venv/bin/python ldc_eval.py score kimi26_bboxunit_1280

# provare un nuovo modello vision: aggiungerlo a CONFIGS in eval_vlm.py, poi
../../.venv/bin/python eval_vlm.py <nome_config>
../../.venv/bin/python score.py <nome_config>

# provare un altro YOLO (ONNX con output [1, 84, 8400], es. export con end2end=False)
python3 yolo_eval.py yolo26s ~/.agenticros/models/yolo26s.onnx && python3 yolo_score.py yolo26s

# ricatturare i frame (sim della casa in esecuzione) e rigenerare la verità a terra
bash -ic './capture_all.sh' && python3 gt2.py

# corsa a ciclo chiuso con verifica dell'arrivo (sim della casa in esecuzione)
bash -ic './closed_loop.sh frigo 8.70 -1.03 vai vicino al frigorifero'
```

Note:

- la verità a terra richiede i modelli della casa in `config/gazebo/house/models` (`scripts/fetch_house_world.sh`);
- `eval_vlm.py` usa il `.venv` del repo (`openai`, `python-dotenv`, `Pillow`);
- gli script YOLO usano il `python3` del container (onnxruntime);
- la posa reale serve solo a misurare: l'agente non la riceve mai;
- i frame grezzi non sono in Git: se mancano, vanno ricatturati con la sim.
