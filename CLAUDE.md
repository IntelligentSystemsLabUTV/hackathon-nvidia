# hackathon-nvidia

Quadrupede Unitree Go2 ("DottorCane") simulato in Gazebo Harmonic e guidato da AgenticROS con modelli su Nebius Token Factory: Nemotron decide le azioni, Kimi-K2.6 localizza i bersagli (bounding box) e descrive la scena, di default senza YOLO (`NEBIUS_PERCEPTION=vlm`); con `NEBIUS_PERCEPTION=yolo` YOLO locale aiuta sui bersagli COCO (vedi `docs/CHANGELOG.md`). Il progetto è un workspace DUA (dotX Automation), ROS 2 Jazzy.

Documentazione dettagliata: `README.md` (come testare), `src/README.md` (flusso completo), `docs/GAZEBO_SETUP.md` (sim, ambienti, fix), `docs/NEBIUS_AGENTICROS.md` (agente), `docs/CHANGELOG.md` e `docs/CONFRONTO_PERCEZIONE.md` (percezione: scelte e numeri), `docs/ESPLORAZIONE_GRAFO.md` (esplorazione senza mappa: grafo dei luoghi, misure). Immagini dei docs in `docs/img/`. Docs e messaggi all'utente in italiano, codice e commenti in inglese.

## Dove gira tutto: container DUA

ROS, Gazebo e Node esistono **solo nel container**, non sull'host. Usa sempre `docker exec`.

```bash
# host: avvio (GPU RTX 2060 via runtime nvidia; xhost +local: per la GUI)
cd docker/container-x86-cudev/.devcontainer && DISPLAY=$DISPLAY docker compose up -d
docker exec -it devcontainer-hackathon-nvidia-x86-cudev-1 zsh   # repo in ~/workspace (/home/neo/workspace)
docker compose down                                             # stop, dalla stessa cartella
```

- Per comandi non interattivi usa `docker exec <c> bash -ic '...'`: `.bashrc` chiama `ros2init`, che fa il source di jazzy, gazebo, ros_gz, **dua-utils** e `install/local_setup`.
- **Non lanciare `colcon build` con il solo `/opt/ros/jazzy` sorgente.** `install/setup.*` perderebbe l'underlay dua-utils e i launch fallirebbero con `package 'dua_app_management' not found`. Builda da una shell `bash -ic` e usa l'alias `cbuild` (`colcon build --event-handlers console_direct+ --symlink-install --continue-on-error`).
- Il layout di install è isolato (`install/<pkg>/share/<pkg>`).

## Struttura

| Percorso | Cosa | Git |
|---|---|---|
| `src/go2_sim_worlds/` | Launch unico `go2_sim.launch.py world:=<nome> nav:=none\|map\|slam`, registro `config/environments.yaml`, `worlds/house.world`, bridge comune, Nav2 (`launch/go2_nav.launch.py`, `config/nav2_go2*.yaml`, `config/slam_toolbox_go2.yaml`), stanze `config/places/<world>.json`, mappa `maps/` | tracciato |
| `src/ldc25_sim`, `champ*`, `dottorcane_description`, `go2_description`, `zed_description`, `velodyne_description`, `ros_gz_republish` | Stack del robot importato (CHAMP, URDF/SDF, sensori, bridge) | **ignorato** |
| `src/agenticros` | Symlink a `tools/agenticros/ros2_ws/src` | symlink |
| `tools/agenticros/` | Submodule AgenticROS (fork `ErLex20/agenticros`), monorepo pnpm; adapter Nebius in `packages/agenticros-nebius/src` | submodule |
| `config/agenticros.json` | Topic camera e cmd_vel, limiti di sicurezza (0,25 m/s, 0,5 rad/s), `skillPaths` | tracciato |
| `config/agenticros-skills/go2-nav2/` | Skill senza codice: capability `navigate_to` → azione Nav2 `navigate_to_pose` | tracciato |
| `config/gazebo/{ldc25,house}/` | Modelli Gazebo pesanti; `config/gazebo/models` è un symlink a `ldc25/models` | ignorato |
| `patches/sim-slip-fix.patch` | Fix allo stack sim ignorato (rampa di velocità, gait, bullet) | tracciato |
| `scripts/run_nebius_agent.sh` | Avvia l'agente Nebius e imposta i default della sim | tracciato |
| `scripts/fetch_house_world.sh` | Scarica e adatta i modelli della casa | tracciato |
| `scripts/vision_eval/` | Valutazione di modelli vision e YOLO su frame della sim con verità a terra (README e `RISULTATI.md`); frame, `.json`, `.jsonl` e `.log` solo in locale | script tracciati |

I package sim ignorati non sono versionati: ogni modifica a quei file va esportata come patch in `patches/` e documentata in `docs/GAZEBO_SETUP.md`.

## Comandi frequenti (nel container, da `~/workspace`)

```bash
cbuild                                                             # tutto il workspace ROS
cbuild --packages-select go2_sim_worlds                            # solo un package
source install/setup.zsh
ros2 launch go2_sim_worlds go2_sim.launch.py world:=house        # oppure ldc25; gui:=false x:= y:= yaw:=
ros2 launch go2_sim_worlds go2_sim.launch.py world:=house nav:=map   # Nav2 + AMCL; nav:=slam senza mappa
./scripts/run_nebius_agent.sh "cerca il frigorifero e vacci vicino"            # senza YOLO (default)
NEBIUS_PERCEPTION=yolo ./scripts/run_nebius_agent.sh "..."         # con YOLO per i bersagli COCO
NEBIUS_EXPLORE_CHOICE=vision ./scripts/run_nebius_agent.sh "..."   # senza mappa: grafo dei luoghi e scelta di Kimi (default: spazio libero)
gz service -s /world/default/set_pose --reqtype gz.msgs.Pose --reptype gz.msgs.Boolean --timeout 3000 \
  --req 'name: "dottorcane", position: {x: 0.0, y: 1.5, z: 0.30}, orientation: {x: 0, y: 0, z: 0, w: 1}'   # robot allo spawn della casa, senza rilanciare
ros2 topic pub --once /dottorcane/go2_control/cmd_vel geometry_msgs/msg/Twist "{}"   # stop
cd tools/agenticros && pnpm build                                  # dopo modifiche al TypeScript
agenticros_setup                                                   # setup completo: colcon + pnpm
```

Topic chiave: camera `/dottorcane/slam/zed_x_driver/left/image_rect_color` (1920×1080), profondità `/dottorcane/slam/zed_x_driver/depth_distances`, cmd_vel `/dottorcane/go2_control/cmd_vel`, posa reale `/gz/dottorcane/pose` (base in piedi a z ≈ 0,22 m), joint `/dottorcane/joint_states`.

## AgenticROS

Per il monorepo TypeScript (adapter Nebius, server MCP, core, convenzioni) vedi `tools/agenticros/CLAUDE.md`. Transport DDS locale (domain 0); il robot si muove solo tramite i tool AgenticROS (`ros2_move_for`, `ros2_estop`), che applicano i limiti di sicurezza. Le modifiche al submodule vanno committate e pushate nel submodule prima di aggiornare il puntatore qui. `.env` contiene `NEBIUS_API_KEY`: non leggerlo, non stamparlo, non committarlo. Per script che chiamano Nebius caricalo con `python-dotenv` (`.venv` del repo) o `node --env-file=.env`, senza stamparlo.

## Modelli su Nebius (verificato a ottobre 2026)

- Ragionamento: `nvidia/Nemotron-3_5-Lightning` (solo testo). Visione: `moonshotai/Kimi-K2.6`, default; dà bounding box precisi (errore di direzione ~0,2°) in ~1 s.
- Kimi-K2.6 ha il **thinking attivo per default**: va spento con `chat_template_kwargs: {thinking: false}` (`reasoning_effort: "none"` non funziona). Chiedi le coordinate come **frazioni 0–1**: con "0–1000" a volte restituisce la y in pixel. `response_format` json_schema funziona.
- MiniCPM-V-4_5 non sa dare coordinate (si usa con 9 colonne numerate) e a volte chiude il JSON con una `}` in più: serve il parser a graffe bilanciate di `vision.ts`.
- Non accettano immagini: tutti i Nemotron, Qwen3.5-397B, GLM-5.2/5.3. Troppo lenti per il ciclo: DeepSeek-V4.1-Flash (p90 23–29 s), Kimi-K3, Qwen3.8-27B, GLM-5.3-Flash.
- Un nuovo modello vision va aggiunto ai profili in `tools/agenticros/packages/agenticros-nebius/src/vision.ts` e misurato con `scripts/vision_eval/` prima di cambiarlo.

## Insidie della simulazione

- **Gazebo orfani.** Dopo `Ctrl-C` o un `timeout` il processo `gz sim` può restare vivo; il launch successivo allora si aggancia al vecchio mondo. Prima di rilanciare: `pkill -9 -f "[g]z sim"` (insieme a `[d]ua_component_container`, `[q]uadruped_controller`, `[r]os_gz_republish`), poi verifica con `ps` che non restino processi.
- **Requisiti di un world per il Go2:** `<world name="default">`, passo 1 ms, `<dart><collision_detector>bullet</collision_detector></dart>` e i system plugin di `house.world` (Sensors ogre2, Imu, Contact).
- **Modelli statici:** usa `<include>` con `<static>true</static>`. Un `<model><static>` che avvolge un `<include>` NON rende statico il modello incluso (la casa andava a 0,2× il tempo reale).
- **Niente pavimenti in trimesh sottile:** pavimenti e tappeti in mesh di pochi mm/cm fanno affondare i piedi e il robot collassa a z ≈ 0,09. Togli la loro collisione e lascia camminare il robot sul ground plane.
- Per verificare un world o una modifica alla sim: headless con `gui:=false`, poi controlla `real_time_factor` (`gz topic -e -n 1 -t /stats`), la z di `/gz/dottorcane/pose` dopo l'avvio e lo spostamento con un `cmd_vel` breve. Riferimento su LDC25: RTF 1,0, camera ~5 Hz; nella casa ~2,5–3 Hz.
- Warning `A new JointTrajectory message was received...` ed eccezioni allo shutdown sono noti e innocui.
- **Calibrazione dei movimenti.** `run_nebius_agent.sh` imposta `NEBIUS_TURN_EFFICIENCY=0.77` e `NEBIUS_FORWARD_EFFICIENCY=0.84`, misurati headless con real time factor 1,0 (−90° → −91…−93°, 1 m → 0,97 m). I comandi sono temporizzati in secondi reali: con una sim più lenta (GUI, RTF < 1) scalali per l'RTF. Dopo modifiche a gait o sim ricontrollali con `AGENTICROS_DEBUG_POSE_TOPIC=/gz/dottorcane/pose` (solo log). La direzione stimata usa il giroscopio della ZED (`NEBIUS_IMU_TOPIC`, tool `ros2_imu_yaw`); `scripts/vision_eval/imu_check.sh` la confronta con la posa vera. L'IMU simulato non ha rumore e il suo orientamento è la posa vera: l'agente ne usa solo la velocità angolare.
- **Sim degradata dopo un incastro.** Dopo che il robot è rimasto incastrato (contro il porta-manubri della palestra, a x ≈ 2,3, y 2,0–3,4, alto 0,4 m e assente dalla mappa) la sim è rimasta degradata fino al riavvio: −90° comandati diventavano −57…−68° e una camminata dritta curvava di 90°. Prima di una serie di prove rilancia la sim e controlla le rotazioni con `scripts/vision_eval/imu_check.sh` (−90° → circa −88°).
- **Nav2 e librerie.** L'underlay DUA ha BehaviorTree.CPP 4.9 prima di quello di Jazzy nel `LD_LIBRARY_PATH`: `go2_nav.launch.py` mette `/opt/ros/jazzy/lib` in testa per i processi Nav2. `ros-jazzy-diagnostic-updater` dell'immagine base è più vecchio di Nav2 (`undefined symbol diagnostic_updater::Updater`): il Dockerfile lo aggiorna; in un container vecchio `sudo apt-get install --only-upgrade ros-jazzy-diagnostic-updater`.
- **Uccidere processi.** `pkill -f "<testo>"` uccide anche la shell che lo esegue se il testo compare nella sua riga di comando: usa un pattern come `"[g]z sim"`, e non mettere nella stessa riga di comando il nome in chiaro (es. un `grep "gz sim"` dopo il `pkill`): la shell verrebbe uccisa lo stesso.
- **Test della percezione**: la posa reale (`/gz/dottorcane/pose`) e le pose degli oggetti in `house.world` servono solo a verificare l'arrivo dall'esterno; non vanno mai passate all'agente.

## Git

Branch `master`, remote SSH. Non committare `build/`, `install/`, `log/`, `config/gazebo/`, `.env`. Nei commit **non aggiungere Claude come co-autore** (niente `Co-Authored-By`). Messaggi di commit in inglese.
