# Simulazione Gazebo LDC25

Il workspace include il mondo LDC25, il modello quadrupede basato su Unitree
Go2, controller CHAMP, camere ZED simulate e bridge Gazebo ↔ ROS 2.

I package ROS sono direttamente sotto `src/`; i modelli del mondo sono in
`config/gazebo/models`. La configurazione AgenticROS usa come camera predefinita:

```text
/dottorcane/slam/zed_x_driver/left/image_rect_color
```

## Build

Nel container DUA, dal root del workspace, con l'alias `cbuild` (non `colcon build`
a mano: `cbuild` gira nella shell in cui `ros2init` ha già caricato l'underlay
dua-utils, senza il quale i launch falliscono con `package 'dua_app_management' not found`):

```bash
cbuild --packages-up-to ldc25-sim
source install/setup.zsh
```

## Avvio

Con interfaccia grafica:

```bash
source install/setup.zsh
ros2 launch ldc25-sim ldc25_dottorcane.launch.py
```

In modalità headless:

```bash
source install/setup.zsh
ros2 launch ldc25-sim ldc25_dottorcane.launch.py gui:=false
```

Se il workspace viene spostato, indicare esplicitamente la directory dei
modelli:

```bash
ros2 launch ldc25-sim ldc25_dottorcane.launch.py \
  models_path:="$PWD/config/gazebo/models"
```

In alternativa si può impostare `LDC25_GAZEBO_MODELS_PATH` prima del launch.

## Simulazione uguale al robot (`profile:=real`)

`go2_sim.launch.py` ha due profili. `profile:=real`, il default, fa apparire il robot simulato come il DottorCane reale (stack `dottorcane` branch `slam` più `go2_real.launch.py`) a tutto ciò che sta sopra il simulatore:

| | Simulazione `profile:=real` | Robot reale |
| --- | --- | --- |
| Camera | `/dottorcane/go2_control/frontvideo/{image_rect_color,camera_info}`, 1280×720, HFOV 94,7°, 10 Hz, frame `dottorcane/front_camera_link` (convenzione ottica) | idem (camera frontale del Go2) |
| Lidar | `/dottorcane/sensors/livox_lidar_driver/point_cloud` e `/point_cloud/deskewed`, 360°×(−7°…52°), 10 Hz, frame `dottorcane/livox_mid360_link` a (0,273; 0; 0,141) m con pitch 30° | Mid-360, stessa posa (`dottorcane_slam.urdf`) |
| IMU | `/dottorcane/go2_control/imu`, 200 Hz | idem |
| Profondità | `/dottorcane/agent/depth` da `lidar_camera_depth.py` (nessuna camera di profondità) | idem |
| Scan ostacoli | `/dottorcane/agent/scan_obstacles` da `lidar_obstacle_scan.py` | idem |
| Localizzazione | `/dottorcane/slam/ekf_global/odometry` (50 Hz) e TF `map → dottorcane/base_link`, `map` alla posa di partenza sul pavimento: la posa di Gazebo (`ground_truth_odom.py`) fa da EKF + LIO-SAM | EKF + LIO-SAM |
| Middleware | rmw_zenoh_cpp, router `zenohd` sulla macchina | rmw_zenoh_cpp, router sulla Jetson |
| Nav2 | Nav2 DUA (`dua_nav2`, `dottorcane.launch.py use_sim_time:=true`) | Nav2 DUA sul PC |

Le differenze che restano sono la locomozione (CHAMP: base a 0,22 m invece di 0,34 m, efficienze 0,77/0,84 in `run_nebius_agent.sh`) e il lidar, che non riproduce lo schema non ripetitivo del Mid-360. L'agente non legge mai `/gz/dottorcane/pose`: serve solo a verificare gli arrivi dall'esterno.

I sensori vengono aggiunti a una copia dell'SDF di `dottorcane_description` all'avvio (`real_profile_sdf` nel launch), senza modificare il package ignorato: tolti ZED e camere laterali, aggiunti camera frontale e Mid-360, IMU rinominato.

Avvio, con gli stessi passi del robot (container DUA di questo repo e di `dua_nav2`):

```bash
# hackathon-nvidia, nel container
zenohd -c /etc/zenoh/rmw/DEFAULT_RMW_ZENOH_ROUTER_CONFIG.json5        # router, una volta per macchina
sim_zenoh                                                              # RMW_IMPLEMENTATION=rmw_zenoh_cpp
ros2 launch go2_sim_worlds go2_sim.launch.py world:=house gui:=false   # passi 1+2 del robot
# dua_nav2, nel suo container
RMW_IMPLEMENTATION=rmw_zenoh_cpp ros2 launch dua_nav2_bringup dottorcane.launch.py use_sim_time:=true
# hackathon-nvidia
ros2 launch go2_real go2_real_nav.launch.py nav2:=dua use_sim_time:=true
./scripts/run_nebius_agent.sh "vai vicino al frigorifero"               # GO2_TARGET=sim è il default
```

Il processo `ros2 launch` deve già usare zenoh (`sim_zenoh`): carica le composable nel container con il proprio middleware, e con Fast DDS il bridge non partirebbe. Il launch si ferma con un errore esplicito se manca. Dopo un riavvio della sim riavvia anche Nav2 ed `explore` (il tempo simulato riparte da zero); il launch cancella anche `logs/places_session.json`, i posti della sessione precedente.

Verifiche utili: `real_time_factor` 1,0 nella casa; la z dell'odometria a 0,22 m da fermo; con il robot fermo il corridoio di `ros2_depth_corridor` deve vedere fino alla parete, non il pavimento.

`profile:=zed` è la simulazione precedente (ZED, `ros_gz_republish`, `nav:=map|slam` con il Nav2 di questo package), descritta nel resto di questo documento.

### Package della simulazione

I package ignorati da Git (`champ*`, `ldc25_sim`, `ros_gz_republish`, `dottorcane_description`, `go2_description`, `zed_description`) vengono da `dotX-gazebo` (`src/champ*`, `src/ldc25-sim` → `src/ldc25_sim`, `src/ros_gz_republish`, `src/ldc25-shared/dottorcane_description`, `src/go2_stack/src/go2_description`, `src/zed_drivers/src/zed_description`). Dopo la copia: `patch -p1 < patches/sim-slip-fix.patch`. `ldc25-sim` non dichiara la dipendenza da `zed_description` nel `package.xml`: alla prima build può fallire per l'ordine, un secondo `cbuild` la completa.

## Ambienti multipli

Il package tracciato `src/go2_sim_worlds` lancia il Go2 in un ambiente a
scelta con lo stesso stack robot (CHAMP, camere ZED, bridge, republisher):

```bash
ros2 launch go2_sim_worlds go2_sim.launch.py world:=ldc25   # default
ros2 launch go2_sim_worlds go2_sim.launch.py world:=house
```

Struttura:

```text
src/go2_sim_worlds/                 (in Git)
├── config/environments.yaml        registro ambienti: world, modelli, spawn
├── config/go2_bridge.yaml          bridge ROS <-> Gazebo comune
├── launch/go2_sim.launch.py        launch generico
├── worlds/house.world              casa adattata al Go2
└── maps/house_world_map.*          mappa 2D della casa (per Nav2, non usata ora)
config/gazebo/                      (ignorata da Git, asset pesanti)
├── ldc25/models/                   modelli LDC25
├── models -> ldc25/models          symlink per ldc25_dottorcane.launch.py
└── house/{models,photos}/          scaricati da scripts/fetch_house_world.sh
```

La directory degli asset si cambia con `assets_path:=...` o con la variabile
`GO2_SIM_ASSETS_PATH`; se mancano i modelli il launch stampa come ottenerli.

### House world

Mondo AWS RoboMaker Small House (68 modelli `aws_robomaker_residential_*`),
dal porting Gazebo Harmonic di
[pantelis/turtlebot-maze](https://github.com/pantelis/turtlebot-maze#house-world)
(commit `d306a5c`, fissato in `scripts/fetch_house_world.sh`). Rispetto alla
versione TurtleBot servono tre correzioni, verificate in simulazione:

1. **Fisica e plugin come `ldc25.world`**: passo 1 ms e collision detector
   bullet (vedi sotto), più i system plugin usati dal Go2.
2. **Modelli davvero statici.** Il file originale avvolge ogni `<include>` in
   un `<model><static>true</static>`, ma Gazebo lascia dinamici i modelli
   annidati: i mobili collidevano tra loro e la simulazione andava a 0,2× il
   tempo reale. In `house.world` ogni modello è un `<include>` con
   `<static>true</static>`: tempo reale 1,0×.
3. **Niente collisioni per pavimento e tappeti.** Sono lastre sottili in
   triangle mesh (4 cm e 3 mm); con DART + bullet i piedi ci affondavano e il
   robot collassava (base a 0,09 m invece di 0,22 m) senza riuscire a rialzarsi.
   Sono complanari al ground plane, quindi lo script rimuove le loro collisioni
   e il robot cammina sul piano.

Spawn di default `(0, 1,5)`, rivolto verso la cucina. Misure sulla RTX 2060
(headless): tempo reale 1,0×, camera sinistra 1920×1080 a ~2,5–3 Hz (LDC25
~5 Hz; la casa ha più geometria e luci), avanzamento e rotazione regolari.

### Aggiungere un ambiente

1. Mettere i modelli in `config/gazebo/<nome>/models` (o uno script che li
   scarica) e il world in `src/go2_sim_worlds/worlds/<nome>.world`.
2. Nel world: `<world name="default">`, il blocco `<physics>` e i plugin di
   `house.world`, modelli statici come `<include>` con `<static>true</static>`,
   pavimenti piani senza collisioni mesh sottili.
3. Aggiungere la voce in `config/environments.yaml` (spawn in un punto libero)
   e ricompilare con `cbuild --packages-select go2_sim_worlds`.

## Navigazione con Nav2

`go2_sim.launch.py` ha l'argomento `nav`:

| `nav:=` | Cosa parte | Quando usarlo |
|---|---|---|
| `none` (default) | solo la simulazione, come prima | AgenticROS senza navigazione |
| `map` | Nav2 + `map_server` + AMCL sulla mappa del world (`map` in `environments.yaml`) | "vai in camera da letto" su una casa nota |
| `slam` | Nav2 + `slam_toolbox` (mappa costruita dal vivo) + `agenticros_explore` (frontiere) | casa sconosciuta, senza mappa a priori |

```bash
ros2 launch go2_sim_worlds go2_sim.launch.py world:=house nav:=map
ros2 launch go2_sim_worlds go2_sim.launch.py world:=house nav:=slam
```

Pezzi aggiunti (`launch/go2_nav.launch.py`, tutto in `go2_sim_worlds`):

- **Scan.** Il robot non ha un lidar: `depthimage_to_laserscan` ricava
  `/dottorcane/scan` dalla profondità della ZED (672×376, 110°, 0,15–8 m, piano
  orizzontale a ~0,39 m da terra, frame `dottorcane/zedx_link`) per AMCL e SLAM.
  Il bridge pubblica anche `/dottorcane/slam/zed_x_driver/depth_camera_info`.
- **Ostacoli.** Un solo piano a 0,39 m non vede ostacoli bassi o sottili: con lo
  SLAM il robot si è incastrato nel rack del bilanciere della palestra.
  `scripts/depth_obstacle_scan.py` riproietta tutta l'immagine di profondità,
  tiene i punti tra 6 e 70 cm dal pavimento e pubblica il più vicino per
  direzione in `/dottorcane/scan_obstacles` (0,4–4 m), usato da costmap e
  collision monitor. Le altezze sono misurate in `dottorcane/base_ground`, un
  frame a terra con il solo yaw pubblicato da `ground_truth_odom.py`, così il
  filtro resta giusto mentre il corpo beccheggia. La nuvola di punti del bridge
  (~250k punti) arrivava sotto 1 Hz: ora è `lazy` e non viene usata.
- **Odometria.** `scripts/ground_truth_odom.py` pubblica `/dottorcane/odom`
  (`nav_msgs/Odometry`) e il TF `dottorcane/odom → dottorcane/base_link` dalla
  posa di Gazebo: il frame `odom` coincide con il world, come la mappa della casa.
  Con `nav:=map|slam` il TF di `ros_gz_republish` e lo statico `map → odom`
  sono disattivati: `map → odom` lo pubblica AMCL o SLAM.
- **Parametri.** `config/nav2_go2.yaml`: velocità entro i limiti AgenticROS
  (0,25 m/s, 0,5 rad/s), rotazione sul posto + regulated pure pursuit,
  footprint del Go2, tolleranza 0,4 m. Catena delle velocità: controller →
  `velocity_smoother` → `collision_monitor` (stop se lo scan vede qualcosa a
  ridosso del corpo) → `/dottorcane/go2_control/cmd_vel`.
- **SLAM.** `config/slam_toolbox_go2.yaml`: scan matching e loop closure spenti
  perché l'odometria è il ground truth (sul robot reale vanno riaccesi);
  `restamp_tf: true`, altrimenti `map → odom` porta il tempo dello scan (5 Hz) e
  il controller abortisce i goal con "extrapolation into the future";
  `config/nav2_go2_slam.yaml` rende la costmap globale "rolling" (30×30 m),
  altrimenti all'avvio il robot è fuori dalla mappa appena iniziata e il planner
  rifiuta ogni goal. `agenticros_explore` sceglie la frontiera più vicina e
  rinuncia a un goal dopo 75 s (di solito ne bastano 15–40; oltre, il robot è
  bloccato).
- **Stanze.** `config/places/house.json`: pose con nome (bedroom, kitchen,
  living_room, dining_room, gym, balcony, entrance, second_room, hall) nel
  formato di AgenticROS, controllate sulla mappa (libere con 0,35 m di margine e
  raggiungibili dal punto di partenza).

Prova senza AgenticROS:

```bash
ros2 action send_goal /navigate_to_pose nav2_msgs/action/NavigateToPose \
  "{pose: {header: {frame_id: map}, pose: {position: {x: -6.2, y: 0.3}, orientation: {z: 0.7071, w: 0.7071}}}}"
ros2 action send_goal /explore agenticros_msgs/action/Explore "{mode: explore, timeout_s: 240.0, max_goals: 2}"   # nav:=slam
```

Misure (house, headless): partenza → camera da letto ~115 s (~7 m), partenza →
cucina ~47 s, cucina → camera ~114 s; AMCL entro 2–3 cm e ~7° dalla posa reale.
Velocità effettiva ~0,1–0,17 m/s, più le rotazioni sul posto.

Problemi risolti (da ricordare se si ricrea il container):

- `lifecycle_manager: undefined symbol diagnostic_updater::Updater...`: l'immagine
  base ha `ros-jazzy-diagnostic-updater` più vecchio di Navigation2. Il
  Dockerfile ora lo installa insieme a Nav2; nel container già creato:
  `sudo apt-get update && sudo apt-get install --only-upgrade ros-jazzy-diagnostic-updater`.
- Plugin del BT navigator con `undefined symbol BT::StatusChangeLogger`: l'underlay
  DUA ha BehaviorTree.CPP 4.9 prima di quello di Jazzy (4.10) nel
  `LD_LIBRARY_PATH`. `go2_nav.launch.py` mette `/opt/ros/jazzy/lib` in testa solo
  per i processi Nav2.
- Navigazioni abortite con `Timed out while waiting for action server to
  acknowledge goal request for compute_path_to_pose`: con Gazebo che satura la CPU
  il default di 20 ms è troppo poco, `default_server_timeout` è 1000 ms.
- Collision monitor che ferma il robot con "invalid source": lo scan degli
  ostacoli arrivava troppo di rado (nuvola di punti sotto 1 Hz). Con
  `depth_obstacle_scan.py` segue la profondità (~2 Hz con la sim carica) e
  `source_timeout` è 3 s.

## Topic utili

```text
/dottorcane/slam/zed_x_driver/left/image_rect_color   sensor_msgs/msg/Image
/dottorcane/slam/zed_x_driver/left/image_rect_color/compressed  sensor_msgs/msg/CompressedImage (JPEG, per i viewer)
/dottorcane/scan                                      sensor_msgs/msg/LaserScan (nav:=map|slam, dalla profondità)
/dottorcane/scan_obstacles                            sensor_msgs/msg/LaserScan (nav:=map|slam, profondità 6-70 cm dal pavimento)
/dottorcane/odom                                      nav_msgs/msg/Odometry (nav:=map|slam)
/dottorcane/slam/zed_x_driver/right/image_rect_color  sensor_msgs/msg/Image
/dottorcane/slam/zed_x_driver/point_cloud             sensor_msgs/msg/PointCloud2
/dottorcane/slam/zed_x_driver/imu                     sensor_msgs/msg/Imu
/dottorcane/joint_states                              sensor_msgs/msg/JointState
/dottorcane/go2_control/cmd_vel                       geometry_msgs/msg/Twist
```

Il topic sinistro pubblica immagini larghe 1920 pixel ed è stato verificato
durante lo smoke test.

Per guardare la camera usa la copia JPEG (~0,16 MB a frame, ~13 Hz), pubblicata
da `image_transport::Republisher` nello stesso container del bridge: il topic raw
pesa ~6 MB a frame e `rqt_image_view` o `ros2 topic hz` (Python) non reggono il
flusso (~0,6 Hz). Gli agenti usano il raw a piena qualità.

```bash
ros2 run rqt_image_view rqt_image_view
```

Poi scegli nel menu a tendina la voce `.../left/image_rect_color/compressed`.
Non passarla come argomento: `rqt_image_view` la tratterebbe come topic raw e
andrebbe in crash (`incompatible type ... CompressedImage`).

## Scivolamento del robot (corretto)

Il robot scivolava spesso quando si fermava: fino a 0,3 m di lato e 11° di
rotazione con comando zero. Le cause, misurate con la posa reale
`/gz/dottorcane/pose`, erano tre:

1. **Nessuna rampa di velocità.** CHAMP legge `cmd_vel/smooth`, che nel bringup
   originale è l'uscita di un velocity smoother; qui era collegato direttamente
   al `cmd_vel` grezzo. Ogni scalino di velocità riportava i piedi alla posizione
   nominale in un solo ciclo, con uno scatto delle gambe in appoggio.
2. **Reset del passo con zampe in volo.** A velocità zero CHAMP azzera subito il
   passo e una zampa sollevata viene comandata a terra di colpo.
3. **Contatti piede-pavimento instabili.** Con il collision detector predefinito
   di DART il robot, fermo e con le gambe bloccate, scivolava a velocità costante
   (~0,2 m/s).

Correzioni (i package della simulazione sono esclusi da Git, quindi sono
raccolte in `patches/sim-slip-fix.patch`):

- `champ_base`: rampa di accelerazione (`velocity_smoothing.max_linear_accel`
  0,5 m/s², `max_angular_accel` 1,5 rad/s² in `dottorcane_gait.yaml`) e
  `time_from_start` delle traiettorie pari al periodo del ciclo di controllo;
- `champ`: all'arresto il passo continua finché le zampe in volo non toccano terra;
- `ldc25.world`: `<dart><collision_detector>bullet</collision_detector></dart>`.

Risultato su 15 arresti dopo avanzamenti e rotazioni: scivolamento laterale
medio da 0,16 a 0,03 m (massimo da 0,30 a 0,07 m). Per applicare la patch su
un'altra macchina, dalla root del repository:

```bash
patch -p1 < patches/sim-slip-fix.patch
cbuild --packages-select champ champ_base champ_config ldc25-sim
```

## Limiti osservati

- Il controller produce ancora warning `A new JointTrajectory message was
  received while executing a previous trajectory`: sono attesi, perché CHAMP
  invia una nuova traiettoria a ogni ciclo.
- `ros_gz_republish` e il container DUA possono mostrare eccezioni durante lo
  shutdown via `Ctrl-C`. L'errore è nel cleanup e non ha impedito la
  pubblicazione dei sensori.
- Con Nav2 il `controller_server` segnala spesso `Control loop missed its desired
  rate of 10 Hz`: la posa arriva a 10 Hz e la simulazione oscilla attorno al tempo
  reale. È innocuo.
