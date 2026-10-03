# Nebius + AgenticROS

AgenticROS è il livello di accesso e sicurezza ROS; Nebius è il livello
decisionale. L'adapter `tools/agenticros/packages/agenticros-nebius` esegue un
ciclo osservazione → decisione → azione finché l'obiettivo non è raggiunto:

```text
ros2_camera_snapshot ─► YOLO a riquadri / MiniCPM-V ─┐
ros2_depth_distance  ─► distanza bersaglio, spazio libero ─┤
                                                     ▼
                         Nemotron: search | face_target | approach_target | finish
                                                     │ validazione del controller
                                                     ▼
                         ros2_move_for (limitato, stop garantito) ── ripeti
```

Il modello non comanda direttamente il robot: sceglie un'intenzione semantica, il
controller calcola angoli e distanze, applica distanza di arresto e margine dagli
ostacoli, e rifiuta le azioni non valide (il rifiuto torna al modello nel passo
successivo). Se Nemotron non restituisce un'azione utilizzabile, interviene una
policy deterministica equivalente. La posa reale di Gazebo non viene mai passata
al modello.

## Avvio

Primo terminale:

```bash
cd ~/workspace
source install/setup.zsh
ros2 launch ldc25-sim ldc25_dottorcane.launch.py
```

Secondo terminale:

```bash
cd ~/workspace
./scripts/run_nebius_agent.sh "cerca l'idrante rosso e vacci vicino"
```

La richiesta viene prima classificata da Nemotron:

| Modalità | Esempio | Comportamento |
|---|---|---|
| `approach` | "cerca l'idrante rosso e vacci vicino" | ricerca ruotando, allineamento, avvicinamento fino alla distanza di arresto |
| `describe` | "descrivi gli ostacoli, non muoverti" | un frame, descrizione in italiano, nessun movimento |
| `move` | "ruota a destra di 90 gradi e avanza di un metro" | movimenti espliciti, avanzamento limitato dallo spazio libero |
| `stop` | "fermati" | `ros2_estop` |

## Percezione

- **Bersagli COCO** (idrante, semaforo, stop sign...): YOLOv8n locale di
  `@agenticros/object-detection`. `detectClassTiled` analizza il frame intero e
  riquadri sovrapposti lungo l'orizzonte: sul frame 1920×1080 ridotto a 640 px
  l'idrante a 6 m aveva confidenza < 0,2; sui riquadri 0,7–0,9 con box esatto.
  Lo stesso rilevamento a riquadri è ora usato anche da `ros2_find_object`.
- **Attributi** non visibili a YOLO (colore): verificati una volta da MiniCPM-V sul
  ritaglio del box.
- **Bersagli non COCO**: MiniCPM-V riceve il frame con 9 colonne numerate e
  indica la colonna; nei test i box in pixel restituiti dai modelli vision
  disponibili erano inaffidabili, la colonna no (errore ≤ 1 colonna ≈ 12°).
- **Distanza**: `ros2_depth_distance` accetta ora una ROI normalizzata
  (`roi_x_min`, `roi_y_min`, `roi_x_max`, `roi_y_max`); l'adapter misura la parte
  centrale del box e un corridoio di circa ±12° davanti al robot.

## Calibrazione della simulazione

Misurata con la posa reale `/gz/dottorcane/pose`:

- `ros2_move_for` a 0,25 m/s per 3 s → ~0,48 m più ~7 cm di frenata, dritto;
- rotazione a 0,5 rad/s → ~60% dell'angolo comandato più ~5° di frenata;
- profondità nel box dell'idrante coerente con la distanza reale (6,17 m misurati
  contro 6,56 m centro-centro).

`run_nebius_agent.sh` imposta quindi `NEBIUS_TURN_EFFICIENCY=0.65` e
`NEBIUS_FORWARD_EFFICIENCY=0.7`; il ciclo chiuso corregge l'errore residuo.

## Perché non `run_mission`

Il planner delle missioni AgenticROS è a regole, senza LLM: esegue una lista fissa
di passi una sola volta, senza verificare l'obiettivo. Il passo di avvicinamento
generato pubblica su `/cmd_vel` (non sul topic del Go2), con un segno di sterzata
invertito e un template che non viene risolto. Il ciclo fino all'obiettivo vive
quindi nell'adapter, e usa i tool AgenticROS come primitive.

## Modifiche ad AgenticROS (submodule `tools/agenticros`)

- `agenticros-nebius`: il vecchio flusso a un solo passo è sostituito dal ciclo
  (`agent.ts`, `perception.ts`, `policy.ts`, `robot.ts`, test in `__tests__/`).
- `object-detection`: `detectClassTiled` (usato anche da `ros2_find_object`, che
  prima non trovava l'idrante a distanza) e correzione del clipping dei box.
- `ros2_depth_distance`: parametri ROI `roi_*` negli adapter Claude Code/MCP,
  OpenClaw e Gemini.
- Arresto sicuro con Ctrl-C: il transport locale rimuove l'handler SIGINT di
  rclnodejs (che chiudeva il contesto ROS prima degli stop), e il server MCP, alla
  chiusura, interrompe i `ros2_move_for` in corso e invia `ros2_estop`. Prima il
  controller CHAMP restava con l'ultimo `cmd_vel` e il robot continuava a muoversi.

## Latenza

Per passo: snapshot ~0,3 s (dopo il primo), YOLO + vision in parallelo ~1–1,5 s,
profondità ~0,5 s, Nemotron Lightning ~0,4 s, movimento fino a 8 s. Ricerca e
avvicinamento all'idrante dalla posizione iniziale (~6,4 m, fuori dal campo
visivo): circa 15 passi.
