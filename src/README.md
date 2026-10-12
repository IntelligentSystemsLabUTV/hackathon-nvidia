# `src/` — workspace ROS 2 dell'hackathon

Questa cartella contiene i package ROS 2 compilati con `cbuild` dalla root del repository: la simulazione Gazebo del quadrupede (Go2 / "DottorCane") e i package ROS di AgenticROS. Qui sotto trovi cosa c'è e i comandi per lanciare la simulazione e far ragionare il robot con i modelli su Nebius Token Factory tramite AgenticROS.

## Come funziona

```text
                     ┌──────────────── ciclo fino all'obiettivo ────────────────┐
Gazebo (Go2 + ZED)   │                                                          │
      │ topic ROS 2  ▼                                                          │
AgenticROS (MCP) ── ros2_camera_snapshot ─► Kimi-K2.6 su Nebius: box, scena    │
      │                                     [+ YOLO a riquadri, modalità yolo]  │
      │          ── ros2_depth_distance ──► distanza nel box / corridoio libero  │
      │                                              │ osservazione             │
      │                                              ▼                          │
      │                          Nemotron su Nebius: search / explore /          │
      │                          face_target / approach_target / finish         │
      │                                              │ validata dal controller  │
      └──── ros2_move_for / ros2_estop ◄─────────────┘──────────────────────────┘
```

1. Nemotron traduce la richiesta in un compito: `approach` (trova un oggetto e avvicinati), `describe` (guarda e descrivi), `move` (movimenti espliciti) o `stop`.
2. A ogni passo AgenticROS acquisisce un frame e il modello vision (default Kimi-K2.6 su Nebius) restituisce il bounding box del bersaglio, la descrizione della scena e le porte verso altre stanze. Con `NEBIUS_PERCEPTION=yolo` (default) per i bersagli COCO lavora in parallelo anche YOLO (`@agenticros/object-detection`) su riquadri del frame 1920×1080; con `NEBIUS_PERCEPTION=vlm` YOLO non viene usato. Il colore ("rosso") e gli avvistamenti dubbi vengono ricontrollati sul ritaglio. Perché e con quali misure: [`docs/CHANGELOG_PERCEZIONE_VLM.md`](../docs/CHANGELOG_PERCEZIONE_VLM.md).
3. `ros2_depth_distance` misura la distanza dentro il box del bersaglio e lo spazio libero nel corridoio davanti al robot. Se la profondità non è coerente con la posizione del box nell'immagine (un oggetto più vicino copre il bersaglio), la distanza viene considerata ignota e l'arrivo non viene dichiarato.
4. Nemotron sceglie un'azione semantica; il controller calcola angoli e distanze, la limita (distanza di arresto, ostacoli) o la rifiuta, e in caso di risposta non valida usa una policy deterministica.
5. `ros2_move_for` esegue il movimento con i limiti di sicurezza di AgenticROS. Il ciclo si ripete fino all'arrivo (bersaglio centrato e a ≤ 1,35 m), al fallimento (esplorazioni esaurite, nessuna direzione libera, percorso bloccato) o ai limiti di passi/tempo. All'uscita, anche con `Ctrl-C`, viene sempre inviato `ros2_estop`.
6. **Esplorazione senza mappa.** Se dopo un giro completo il bersaglio non si vede, il controller rifiuta altri `search` e chiede `explore`: durante il giro ha registrato lo spazio libero per ogni direzione, sceglie la più aperta (evitando quella da cui il robot arriva), si gira, avanza fino a 2,5 m e rifà il giro da lì. Così "vai in camera da letto" (bersaglio: letto) può uscire dalla stanza di partenza. Al massimo 4 esplorazioni, poi l'agente si arrende. Con `nav:=slam` l'esplorazione va invece con Nav2 alla frontiera successiva della mappa SLAM (fino a 8 volte).

Il modello non accede mai direttamente ai topic né alla posa reale di Gazebo: passa sempre dai tool AgenticROS.

## Package

| Package | Ruolo |
|---|---|
| `go2_sim_worlds` | **Tracciato in Git.** Launch unico `go2_sim.launch.py world:=<nome>` e ambienti (`ldc25`, `house`) |
| `ldc25_sim` (`ldc25-sim`) | Mondo Gazebo LDC25 e launch file originale della simulazione |
| `dottorcane_description` | Descrizione del robot DottorCane (Go2 + sensori) |
| `go2_description` | URDF/mesh del Unitree Go2 |
| `champ`, `champ_base`, `champ_config`, `champ_msgs` | Controller di locomozione CHAMP |
| `zed_description`, `velodyne_description` | Modelli dei sensori (camere ZED, LiDAR) |
| `ros_gz_republish` | Bridge Gazebo Harmonic → ROS 2 |
| `agenticros/` | Symlink a `tools/agenticros/ros2_ws/src` (package ROS del submodule AgenticROS) |

## Prerequisiti

Tutti i comandi vanno eseguiti nel devcontainer `container-x86-cudev` (ROS 2 Jazzy, Gazebo Harmonic, Node + pnpm).

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

Per ricompilare il workspace ROS si usa l'alias `cbuild` del container (`colcon build --event-handlers console_direct+ --symlink-install --continue-on-error`), a cui si possono passare altri argomenti di `colcon`:

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

Ambienti disponibili (definiti in `go2_sim_worlds/config/environments.yaml`):

| `world:=` | Ambiente | Asset (ignorati da Git) |
|---|---|---|
| `ldc25` (default) | Campo gara LDC25, esterno, bersagli COCO (idrante, semaforo) | `config/gazebo/ldc25/models` |
| `house` | AWS RoboMaker Small House: cucina, soggiorno, camera, palestra | `config/gazebo/house/` — `./scripts/fetch_house_world.sh` |

Solo la prima volta, per la casa (scarica ~105 MB di modelli):

```bash
./scripts/fetch_house_world.sh
cbuild --packages-select go2_sim_worlds
```

Terminale 1:

```bash
cd ~/workspace
source install/setup.zsh
ros2 launch go2_sim_worlds go2_sim.launch.py world:=house
```

Opzioni:

```bash
# senza GUI
ros2 launch go2_sim_worlds go2_sim.launch.py world:=house gui:=false

# posa di spawn diversa da quella dell'ambiente (yaw in radianti)
ros2 launch go2_sim_worlds go2_sim.launch.py world:=house x:=4.0 y:=-1.0 yaw:=1.57

# asset in un'altra directory (default <workspace>/config/gazebo)
ros2 launch go2_sim_worlds go2_sim.launch.py assets_path:=/percorso/gazebo

# con Nav2: sulla mappa nota della casa (AMCL) oppure senza mappa (SLAM + frontiere)
ros2 launch go2_sim_worlds go2_sim.launch.py world:=house nav:=map
ros2 launch go2_sim_worlds go2_sim.launch.py world:=house nav:=slam
```

Topic, bridge e controller sono identici in tutti gli ambienti, quindi AgenticROS e `run_nebius_agent.sh` funzionano senza modifiche. Il vecchio `ros2 launch ldc25-sim ldc25_dottorcane.launch.py` funziona ancora (`config/gazebo/models` è un symlink a `ldc25/models`).

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

Lo script carica `.env`, imposta `AGENTICROS_CONFIG_PATH=config/agenticros.json` e i default della simulazione (topic di profondità, FOV camera, calibrazione del passo) e avvia `tools/agenticros/packages/agenticros-nebius/dist/index.js`. Il robot continua a osservare e muoversi finché l'obiettivo non è raggiunto; una ricerca + avvicinamento di circa 6 m richiede 1–2 minuti.

Altri esempi:

```bash
./scripts/run_nebius_agent.sh "Guarda davanti al robot e descrivi gli ostacoli. Non muovere il robot."
./scripts/run_nebius_agent.sh "trova il semaforo e fermati a 2 metri"
./scripts/run_nebius_agent.sh "ruota a destra di 90 gradi e avanza di un metro"
./scripts/run_nebius_agent.sh "Ferma subito il robot."

# con la simulazione lanciata con nav:=map (stanze note) o nav:=slam (esplorazione)
./scripts/run_nebius_agent.sh "vai in camera da letto"
./scripts/run_nebius_agent.sh "vai vicino al frigorifero"
```

Con `nav:=map` l'agente conosce le stanze della casa (`go2_sim_worlds/config/places/house.json`) e ci arriva con Nav2; con `nav:=slam` non usa la mappa nota, esplora la casa (frontiere della mappa SLAM) finché trova l'oggetto che identifica la stanza. Dettagli in [`docs/NEBIUS_AGENTICROS.md`](../docs/NEBIUS_AGENTICROS.md#navigazione-con-nav2).

Con Kimi-K2.6 qualunque oggetto nominabile può essere un bersaglio (frigorifero, cestino, armadio, idrante...), con la stessa precisione dei box di YOLO. Nella modalità `yolo` le classi COCO presenti nel mondo (in `ldc25` `fire hydrant`, `traffic light`, `stop sign`; in `house` `refrigerator`, `chair`, `couch`, `dining table`, `tv`, `bed`) passano anche da YOLO, che però nella casa riconosce solo una parte dei mobili renderizzati.

```bash
# stessa richiesta, senza YOLO
NEBIUS_PERCEPTION=vlm ./scripts/run_nebius_agent.sh "vai vicino all'armadio"
```

Su stderr il log mostra ogni passo: `[Goal]` (compito interpretato), `[Step N]` (bersaglio, angolo, distanza, spazio libero), `[Scene]`, `[Decision]` (scelta di Nemotron → movimento eseguito, o rifiuto del controller) e `[Timing]`. Su stdout esce solo la risposta finale in italiano.

## Configurazione

`.env` (root del repo):

| Variabile | Default | Descrizione |
|---|---|---|
| `NEBIUS_API_KEY` | — | Chiave Token Factory (obbligatoria) |
| `NEBIUS_BASE_URL` | `https://api.tokenfactory.nebius.com/v1/` | Endpoint OpenAI-compatible |
| `NEBIUS_VISION_MODEL` | `moonshotai/Kimi-K2.6` | Modello vision: box del bersaglio, scena, verifiche sul ritaglio. `openbmb/MiniCPM-V-4_5` funziona ancora, con le 9 colonne (meno preciso) |
| `NEBIUS_PERCEPTION` | `yolo` | `yolo` = YOLO per i bersagli COCO più modello vision; `vlm` = solo modello vision, senza YOLO |
| `NEBIUS_VISION_GROUNDING` | dal modello | `box` o `columns`: forza il modo di localizzare per un modello vision non previsto |
| `NEBIUS_CAMERA_HEIGHT_M` | `0.385` | Altezza della camera da terra, per riconoscere le letture di profondità coperte da un oggetto più vicino |
| `NEBIUS_REASONING_MODEL` | `nvidia/Nemotron-3_5-Lightning` | Modello che ragiona e sceglie le azioni |
| `NEBIUS_MAX_STEPS` | `80` | Passi massimi osservazione → azione |
| `NEBIUS_MAX_SECONDS` | `600` | Durata massima di un compito |
| `NEBIUS_STOP_DISTANCE_M` | `1.0` | Distanza camera → bersaglio a cui fermarsi (la richiesta può sovrascriverla, es. "fermati a 2 metri") |
| `NEBIUS_DETECTION_MIN_CONFIDENCE` | `0.35` | Soglia YOLO (modalità `yolo`) |
| `AGENTICROS_YOLOV8_MODEL` | `~/.agenticros/models/yolov8n.onnx` | ONNX di YOLO da usare; YOLO26s esportato con `end2end=False` è più accurato (vedi changelog) |
| `NEBIUS_POLICY` | `llm` | `auto` = solo policy deterministica, senza Nemotron (debug) |

Variabili con default impostati da `run_nebius_agent.sh` (sovrascrivibili in `.env`):

| Variabile | Default | Descrizione |
|---|---|---|
| `AGENTICROS_CONFIG_PATH` | `config/agenticros.json` | Config AgenticROS (usa `config/agenticros.local.json` per override locali) |
| `NEBIUS_DEPTH_TOPIC` | `/dottorcane/slam/zed_x_driver/depth_distances` | Immagine di profondità (32FC1, allineata alla camera sinistra) |
| `NEBIUS_CAMERA_HFOV_DEG` | `110` | Campo visivo orizzontale della ZED X simulata |
| `NEBIUS_TURN_EFFICIENCY` | `0.65` | Frazione della rotazione comandata ottenuta dal passo CHAMP (misurata) |
| `NEBIUS_FORWARD_EFFICIENCY` | `0.7` | Frazione dell'avanzamento comandato ottenuto (misurata) |
| `GO2_WORLD` | `house` | World lanciato: sceglie il file delle stanze |
| `AGENTICROS_PLACES_PATH` | `src/go2_sim_worlds/config/places/${GO2_WORLD}.json` | Stanze con nome per `ros2_navigate_to_place` (usate solo con `nav:=map`) |
| `AGENTICROS_DEBUG_POSE_TOPIC` | vuoto | `/gz/dottorcane/pose` abilita la diagnostica del movimento sulla posa reale (aggiunge ~6 s a ogni movimento; mai passata al modello) |

`config/agenticros.json` definisce transport DDS locale (domain 0), topic camera (`/dottorcane/slam/zed_x_driver/left/image_rect_color`), topic `cmd_vel` (`/dottorcane/go2_control/cmd_vel`), limiti di sicurezza (0.25 m/s lineare, 0.5 rad/s angolare) e `skillPaths` con la capability Nav2 `navigate_to` (`config/agenticros-skills/go2-nav2`).

## Topic principali

```text
/dottorcane/slam/zed_x_driver/left/image_rect_color   sensor_msgs/msg/Image
/dottorcane/slam/zed_x_driver/left/image_rect_color/compressed  sensor_msgs/msg/CompressedImage (JPEG, per i viewer)
/dottorcane/slam/zed_x_driver/right/image_rect_color  sensor_msgs/msg/Image
/dottorcane/slam/zed_x_driver/point_cloud             sensor_msgs/msg/PointCloud2
/dottorcane/slam/zed_x_driver/imu                     sensor_msgs/msg/Imu
/dottorcane/joint_states                              sensor_msgs/msg/JointState
/dottorcane/go2_control/cmd_vel                       geometry_msgs/msg/Twist
```

Per guardare la camera usa la copia JPEG (~0,16 MB a frame, ~13 Hz), pubblicata da `image_transport::Republisher` nello stesso container del bridge: il topic raw pesa ~6 MB a frame e `rqt_image_view` o `ros2 topic hz` (Python) non reggono il flusso (~0,6 Hz). Gli agenti usano il raw a piena qualità.

```bash
ros2 run rqt_image_view rqt_image_view
```

Poi scegli nel menu a tendina la voce `.../left/image_rect_color/compressed`. Non passarla come argomento: `rqt_image_view` la tratterebbe come topic raw e andrebbe in crash (`incompatible type ... CompressedImage`).

## Problemi noti

- **"simulator unavailable" / snapshot fallito**: la simulazione non è partita o il `ROS_DOMAIN_ID` è diverso da 0. Controlla con `ros2 topic list`.
- **`NEBIUS_API_KEY is required`**: manca la chiave in `.env`.
- **"Il percorso verso il bersaglio è bloccato"**: c'è un ostacolo nel corridoio davanti al robot entro ~0,5 m; il robot non aggira ancora gli ostacoli.
- **Primo avvio lento** (modalità `yolo`): al primo uso YOLO scarica `yolov8n.onnx` in `~/.agenticros/models/`.
- **`Modello di visione non disponibile`**: in modalità `vlm` il modello vision non ha risposto per 3 passi di fila (rete, quota, nome del modello). Il robot resta fermo.
- **Il modello vision "pensa" a lungo** (risposte di decine di secondi): un modello con thinking attivo per default. Per Kimi-K2.6 viene spento dal profilo; per altri modelli va aggiunto un profilo in `vision.ts`.
- **`Cannot find module .../dist/index.js`**: AgenticROS non è compilato, esegui `agenticros_setup` oppure `cd tools/agenticros && pnpm build`.
- Warning `A new JointTrajectory message was received...` dal controller CHAMP ed eccezioni allo shutdown con `Ctrl-C` sono noti e non bloccano la simulazione.
- Per fermare il robot manualmente: `ros2 topic pub --once /dottorcane/go2_control/cmd_vel geometry_msgs/msg/Twist "{}"`

## Approfondimenti

- [`docs/GAZEBO_SETUP.md`](../docs/GAZEBO_SETUP.md) — dettagli sulla simulazione
- [`docs/NEBIUS_AGENTICROS.md`](../docs/NEBIUS_AGENTICROS.md) — integrazione Nebius + AgenticROS
- [`docs/NEBIUS_VISION_SMOKE_TEST.md`](../docs/NEBIUS_VISION_SMOKE_TEST.md) — test vision su immagine statica
- [`docs/PIANO_HACKATHON.md`](../docs/PIANO_HACKATHON.md) — piano e architettura del progetto
