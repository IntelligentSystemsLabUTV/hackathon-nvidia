# `src/` — workspace ROS 2 dell'hackathon

Questa cartella contiene i package ROS 2 compilati con `cbuild` dalla root del
repository: la simulazione Gazebo del quadrupede (Go2 / "DottorCane") e i
package ROS di AgenticROS. Qui sotto trovi cosa c'è e i comandi per lanciare la
simulazione e far ragionare il robot con i modelli su Nebius Token Factory
tramite AgenticROS.

## Come funziona

```text
                     ┌──────────────── ciclo fino all'obiettivo ────────────────┐
Gazebo (Go2 + ZED)   │                                                          │
      │ topic ROS 2  ▼                                                          │
AgenticROS (MCP) ── ros2_camera_snapshot ─► YOLO a riquadri (bersagli COCO)      │
      │          ── ros2_depth_distance ──► distanza nel box / corridoio libero  │
      │                                     MiniCPM-V su Nebius (scena, colore)  │
      │                                              │ osservazione             │
      │                                              ▼                          │
      │                          Nemotron su Nebius: search / face_target /      │
      │                          approach_target / finish                       │
      │                                              │ validata dal controller  │
      └──── ros2_move_for / ros2_estop ◄─────────────┘──────────────────────────┘
```

1. Nemotron traduce la richiesta in un compito: `approach` (trova un oggetto e
   avvicinati), `describe` (guarda e descrivi), `move` (movimenti espliciti) o `stop`.
2. A ogni passo AgenticROS acquisisce un frame; YOLO (`@agenticros/object-detection`)
   trova il bersaglio su riquadri del frame 1920×1080, così anche un oggetto a 6 m
   viene rilevato. Per bersagli non COCO si usa MiniCPM-V con una griglia di colonne.
   Il colore ("rosso") viene verificato una volta da MiniCPM-V sul ritaglio.
3. `ros2_depth_distance` misura la distanza dentro il box del bersaglio e lo spazio
   libero nel corridoio davanti al robot.
4. Nemotron sceglie un'azione semantica; il controller calcola angoli e distanze,
   la limita (distanza di arresto, ostacoli) o la rifiuta, e in caso di risposta
   non valida usa una policy deterministica.
5. `ros2_move_for` esegue il movimento con i limiti di sicurezza di AgenticROS. Il
   ciclo si ripete fino all'arrivo (bersaglio centrato e a ≤ 1,35 m), al fallimento
   (giro completo senza vederlo, percorso bloccato) o ai limiti di passi/tempo.
   All'uscita, anche con `Ctrl-C`, viene sempre inviato `ros2_estop`.

Il modello non accede mai direttamente ai topic né alla posa reale di Gazebo:
passa sempre dai tool AgenticROS.

## Package

| Package | Ruolo |
|---|---|
| `ldc25_sim` (`ldc25-sim`) | Mondo Gazebo LDC25 e launch file della simulazione |
| `dottorcane_description` | Descrizione del robot DottorCane (Go2 + sensori) |
| `go2_description` | URDF/mesh del Unitree Go2 |
| `champ`, `champ_base`, `champ_config`, `champ_msgs` | Controller di locomozione CHAMP |
| `zed_description`, `velodyne_description` | Modelli dei sensori (camere ZED, LiDAR) |
| `ros_gz_republish` | Bridge Gazebo Harmonic → ROS 2 |
| `agenticros/` | Symlink a `tools/agenticros/ros2_ws/src` (package ROS del submodule AgenticROS) |

## Prerequisiti

Tutti i comandi vanno eseguiti nel devcontainer `container-x86-cudev`
(ROS 2 Jazzy, Gazebo Harmonic, Node + pnpm).

```bash
# submodule AgenticROS
git submodule update --init --recursive

# chiave Nebius
cp .env.example .env
# poi inserire NEBIUS_API_KEY=... in .env (mai committarla)
```

## Build

Dalla root del repository (`~/workspace`):

```bash
# setup completo: cbuild + pnpm install/build di AgenticROS
agenticros_setup          # equivale a ./bin/setup_agenticros.sh
agenticros doctor         # verifica l'installazione
```

Per ricompilare il workspace ROS si usa l'alias `cbuild` del container
(`colcon build --event-handlers console_direct+ --symlink-install --continue-on-error`),
a cui si possono passare altri argomenti di `colcon`:

```bash
cbuild                                   # tutto il workspace
cbuild --packages-up-to ldc25-sim        # solo la simulazione e le sue dipendenze
source install/setup.zsh
```

Se modifichi l'adapter Nebius nel submodule:

```bash
cd tools/agenticros && pnpm build
```

## 1. Lanciare la simulazione

Terminale 1:

```bash
cd ~/workspace
source install/setup.zsh
ros2 launch ldc25-sim ldc25_dottorcane.launch.py
```

Opzioni:

```bash
# senza GUI
ros2 launch ldc25-sim ldc25_dottorcane.launch.py gui:=false

# se il workspace è stato spostato
ros2 launch ldc25-sim ldc25_dottorcane.launch.py models_path:="$PWD/config/gazebo/models"
```

Verifica che camera e comando velocità siano attivi:

```bash
source install/setup.zsh
ros2 topic hz /dottorcane/slam/zed_x_driver/left/image_rect_color
ros2 topic info /dottorcane/go2_control/cmd_vel
```

## 2. Collegare AgenticROS e ragionare con Nebius

Terminale 2, con la simulazione in esecuzione:

```bash
cd ~/workspace
source install/setup.zsh
./scripts/run_nebius_agent.sh "cerca l'idrante rosso e vacci vicino"
```

Lo script carica `.env`, imposta `AGENTICROS_CONFIG_PATH=config/agenticros.json`
e i default della simulazione (topic di profondità, FOV camera, calibrazione
del passo) e avvia `tools/agenticros/packages/agenticros-nebius/dist/index.js`.
Il robot continua a osservare e muoversi finché l'obiettivo non è raggiunto; una
ricerca + avvicinamento di circa 6 m richiede 1–2 minuti.

Altri esempi:

```bash
./scripts/run_nebius_agent.sh "Guarda davanti al robot e descrivi gli ostacoli. Non muovere il robot."
./scripts/run_nebius_agent.sh "trova il semaforo e fermati a 2 metri"
./scripts/run_nebius_agent.sh "ruota a destra di 90 gradi e avanza di un metro"
./scripts/run_nebius_agent.sh "Ferma subito il robot."
```

I bersagli più affidabili sono le classi COCO presenti nel mondo (idrante =
`fire hydrant`, semaforo = `traffic light`, `stop sign`...), rilevate localmente
da YOLO. Altri oggetti vengono cercati con il modello vision, in modo meno preciso.

Su stderr il log mostra ogni passo: `[Goal]` (compito interpretato), `[Step N]`
(bersaglio, angolo, distanza, spazio libero), `[Scene]`, `[Decision]` (scelta di
Nemotron → movimento eseguito, o rifiuto del controller) e `[Timing]`. Su stdout
esce solo la risposta finale in italiano.

## Configurazione

`.env` (root del repo):

| Variabile | Default | Descrizione |
|---|---|---|
| `NEBIUS_API_KEY` | — | Chiave Token Factory (obbligatoria) |
| `NEBIUS_BASE_URL` | `https://api.tokenfactory.nebius.com/v1/` | Endpoint OpenAI-compatible |
| `NEBIUS_VISION_MODEL` | `openbmb/MiniCPM-V-4_5` | Modello che descrive il frame |
| `NEBIUS_REASONING_MODEL` | `nvidia/Nemotron-3_5-Lightning` | Modello che ragiona e sceglie le azioni |
| `NEBIUS_MAX_STEPS` | `30` | Passi massimi osservazione → azione |
| `NEBIUS_MAX_SECONDS` | `300` | Durata massima di un compito |
| `NEBIUS_STOP_DISTANCE_M` | `1.0` | Distanza camera → bersaglio a cui fermarsi (la richiesta può sovrascriverla, es. "fermati a 2 metri") |
| `NEBIUS_DETECTION_MIN_CONFIDENCE` | `0.35` | Soglia YOLO |
| `NEBIUS_POLICY` | `llm` | `auto` = solo policy deterministica, senza Nemotron (debug) |

Variabili con default impostati da `run_nebius_agent.sh` (sovrascrivibili in `.env`):

| Variabile | Default | Descrizione |
|---|---|---|
| `AGENTICROS_CONFIG_PATH` | `config/agenticros.json` | Config AgenticROS (usa `config/agenticros.local.json` per override locali) |
| `NEBIUS_DEPTH_TOPIC` | `/dottorcane/slam/zed_x_driver/depth_distances` | Immagine di profondità (32FC1, allineata alla camera sinistra) |
| `NEBIUS_CAMERA_HFOV_DEG` | `110` | Campo visivo orizzontale della ZED X simulata |
| `NEBIUS_TURN_EFFICIENCY` | `0.65` | Frazione della rotazione comandata ottenuta dal passo CHAMP (misurata) |
| `NEBIUS_FORWARD_EFFICIENCY` | `0.7` | Frazione dell'avanzamento comandato ottenuto (misurata) |
| `AGENTICROS_DEBUG_POSE_TOPIC` | vuoto | `/gz/dottorcane/pose` abilita la diagnostica del movimento sulla posa reale (aggiunge ~6 s a ogni movimento; mai passata al modello) |

`config/agenticros.json` definisce transport DDS locale (domain 0), topic camera
(`/dottorcane/slam/zed_x_driver/left/image_rect_color`), topic
`cmd_vel` (`/dottorcane/go2_control/cmd_vel`) e limiti di sicurezza
(0.25 m/s lineare, 0.5 rad/s angolare).

## Topic principali

```text
/dottorcane/slam/zed_x_driver/left/image_rect_color   sensor_msgs/msg/Image
/dottorcane/slam/zed_x_driver/right/image_rect_color  sensor_msgs/msg/Image
/dottorcane/slam/zed_x_driver/point_cloud             sensor_msgs/msg/PointCloud2
/dottorcane/slam/zed_x_driver/imu                     sensor_msgs/msg/Imu
/dottorcane/joint_states                              sensor_msgs/msg/JointState
/dottorcane/go2_control/cmd_vel                       geometry_msgs/msg/Twist
```

## Problemi noti

- **"simulator unavailable" / snapshot fallito**: la simulazione non è partita o il
  `ROS_DOMAIN_ID` è diverso da 0. Controlla con `ros2 topic list`.
- **`NEBIUS_API_KEY is required`**: manca la chiave in `.env`.
- **"Il percorso verso il bersaglio è bloccato"**: c'è un ostacolo nel corridoio
  davanti al robot entro ~0,5 m; il robot non aggira ancora gli ostacoli.
- **Primo avvio lento**: al primo uso YOLO scarica `yolov8n.onnx` in
  `~/.agenticros/models/`.
- **`Cannot find module .../dist/index.js`**: AgenticROS non è compilato, esegui
  `agenticros_setup` oppure `cd tools/agenticros && pnpm build`.
- Warning `A new JointTrajectory message was received...` dal controller CHAMP ed
  eccezioni allo shutdown con `Ctrl-C` sono noti e non bloccano la simulazione.
- Per fermare il robot manualmente:
  `ros2 topic pub --once /dottorcane/go2_control/cmd_vel geometry_msgs/msg/Twist "{}"`

## Approfondimenti

- [`docs/GAZEBO_SETUP.md`](../docs/GAZEBO_SETUP.md) — dettagli sulla simulazione
- [`docs/NEBIUS_AGENTICROS.md`](../docs/NEBIUS_AGENTICROS.md) — integrazione Nebius + AgenticROS
- [`docs/NEBIUS_VISION_SMOKE_TEST.md`](../docs/NEBIUS_VISION_SMOKE_TEST.md) — test vision su immagine statica
- [`docs/PIANO_HACKATHON.md`](../docs/PIANO_HACKATHON.md) — piano e architettura del progetto
