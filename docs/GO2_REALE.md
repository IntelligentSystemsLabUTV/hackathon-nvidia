# Go2 reale (DottorCane)

Come far girare l'agente AgenticROS + Nebius sul Go2 EDU vero, con la Jetson Orin AGX e lo stack DottorCane di dotX ([IntelligentSystemsLabUTV/dottorcane](https://github.com/IntelligentSystemsLabUTV/dottorcane), branch `slam`). La simulazione non cambia: senza `GO2_TARGET=real` tutto resta come prima.

## Differenze rispetto alla simulazione

|  | Gazebo | Go2 reale (stack DottorCane) |
| --- | --- | --- |
| Middleware | DDS (Fast DDS), domain 0 | **rmw_zenoh_cpp**, router zenoh sulla porta 7447 |
| Locomozione | CHAMP | sport mode Unitree tramite `go2_control` (watchdog 500 ms sul cmd_vel); accetta il cmd_vel solo dopo l'action `arm` |
| cmd_vel | `/dottorcane/go2_control/cmd_vel` | identico |
| Camera | ZED X sinistra, 1920×1080, HFOV 110° | **camera USB del DottorCane**, monoculare: è l'unica RGB che si userà. Topic, calibrazione e posizione sul robot non sono nel repo DottorCane: da vedere domani. Ripiego già configurato: camera frontale del Go2 `/dottorcane/go2_control/frontvideo/image_rect_color` (raw e `/compressed`), 1280×720 rettificata, HFOV 94,7° (`fx` 589, `fy` 753) |
| Profondità | ZED `depth_distances` | **nessuna camera di profondità**: Livox Mid-360 proiettato nella camera (`/dottorcane/agent/depth`, vedi sotto) |
| IMU | ZED | `/dottorcane/go2_control/imu` |
| Lidar | — | Mid-360 `/dottorcane/sensors/livox_lidar_driver/point_cloud`, frame `dottorcane/livox_mid360_link`, a x 0,273 m e z 0,141 m dalla base, inclinato di 30° in avanti |
| Localizzazione | posa vera di Gazebo | EKF `/dottorcane/slam/ekf_global/odometry` e LIO-SAM `/dottorcane/slam/lio_sam/map_optimization/{pose,path,local_map}`; TF `map → dottorcane/base_link` (l'EKF ha `world_frame` e `odom_frame` = `map`) |
| Nav2 | sì (`nav:=map\|slam`) | non sulla Jetson (su JetPack 6 i pacchetti `ros-jazzy-*` non esistono): gira sul PC, nel container cudev, collegato via zenoh (`go2_real_nav.launch.py`, vedi sotto) |

Lo stack DottorCane si lancia nel suo container `dottorcane:jetson6`: `ros2 launch dottorcane_bringup dottorcane_slam.launch.py`. Serve la versione `slam`: `dottorcane.launch.py` non avvia il Mid-360.

## Cosa c'è in questo repo

- **`docker/container-jetson6/`**: container DUA per la Jetson (`dua-foundation:jetson6`, L4T r36.4) con Node 22 e pnpm. `GO2_TARGET=real` e `AGENTICROS_CONFIG_PATH=config/agenticros.real.json` sono già impostati. Il `postCreateCommand` e `agenticros_setup` compilano solo `agenticros_msgs` e `go2_real`, poi AgenticROS.
- **`config/agenticros.real.json`**: camera frontale del Go2 (per la camera USB: `NEBIUS_CAMERA_TOPIC`), stesso cmd_vel, stessi limiti (0,25 m/s, 0,5 rad/s).
- **`scripts/run_nebius_agent.sh`** con `GO2_TARGET=real` imposta:
  - `RMW_IMPLEMENTATION=rmw_zenoh_cpp`;
  - profondità dal lidar;
  - HFOV 94,7° della camera frontale (con la camera USB: `NEBIUS_CAMERA_HFOV_DEG`);
  - IMU del Go2;
  - efficienze 1,0 (da calibrare);
  - altezza della camera 0,36 m (stimata, da misurare);
  - nessun file di stanze.
- **`src/go2_real/`**:
  - `lidar_camera_depth.py`: dagli ultimi 0,5 s di punti del Mid-360 costruisce un'immagine 32FC1 di 320×141 allineata alla camera per frazioni d'immagine, come la usano `ros2_depth_distance` (box del bersaglio) e `ros2_depth_corridor` (ostacoli davanti). I pixel sono quadrati, come richiede il corridoio. Toglie i punti del corpo del robot e riempie i buchi di 1 pixel. Il frame della camera viene da `camera_info`; la convenzione (ottica o x avanti) si ricava dalla TF. Per una camera senza calibrazione bastano `hfov_deg` e `camera_frame` (pinhole ideale);
  - `go2_real.launch.py`: avvia il nodo, con rmw_zenoh;
  - `rviz.launch.py`: RViz con modello, TF, camera, profondità dal lidar, nuvola del Mid-360, odometria EKF e mappa LIO-SAM. Sulla Jetson si collega al router locale; da un PC con `robot:=<host o IP>` si collega direttamente al router del robot, in modalità client. `camera:=<topic>` mostra un'altra camera (quella USB).
- In entrambi i container:
  - `dottorcane_zenoh` imposta rmw_zenoh per la CLI `ros2`; nel container cudev prende l'host del robot;
  - `dottorcane_arm` e `dottorcane_disarm` lanciano le action `/dottorcane/go2_control/{arm,disarm}`, come `arm` e `disarm` nel container DottorCane.

Verificato nel container cudev, senza robot:

- rclnodejs riceve su `rmw_zenoh_cpp` attraverso un router zenoh;
- la configurazione client di `rviz.launch.py` raggiunge il router;
- con TF e `camera_info` come quelli reali e una scena sintetica (muro a 2 m, scatola a 1 m, pavimento, zampe), le funzioni di profondità dell'agente leggono 0,67 m nel box della scatola, 1,67 m sul muro e un ostacolo nel corridoio a 0,67 m. I valori sono quelli attesi, in entrambe le convenzioni del frame camera e anche senza `camera_info` (`hfov_deg`).

## Branch `mapless`: prova sul robot senza stima di posa

Su questo branch il robot non usa EKF, SLAM, odometria, giroscopio né Nav2: il modello vision su Nebius rilocalizza il bersaglio (o l'apertura scelta, il waypoint semantico) a ogni passo, e l'action `reactive_drive` della Jetson (`agenticros_msgs/action/ReactiveDrive`) guida verso di lui a 20 Hz sullo scan istantaneo del Mid-360, seguendolo come cluster di punti; mentre il robot cammina l'agente lo rilocalizza e manda il nuovo goal senza fermarlo. Lo stack DottorCane serve solo per `go2_control` (cmd_vel, camera frontale `dottorcane/front_camera_link`), il Mid-360 e le TF fisse del robot; la sua localizzazione può girare ma non viene letta.

1. Jetson, container DottorCane: bringup (`dottorcane_slam.launch.py` va bene; basta il Mid-360).
2. Jetson, nostro container: dopo il pull, `agenticros_setup` (compila `agenticros_msgs` con la nuova action e rigenera i binding di rclnodejs), poi `go2_real.launch.py` (default `localization:=none`, `reactive_drive:=true`: profondità e scan nel frame del corpo, controllo dei dislivelli attivo; `base_height:=` se la base in piedi non è a 0,34 m; `cliff_check:=false` solo se un pavimento scuro e lucido non restituisce punti).
3. Controlli prima di muovere, con `dottorcane_zenoh`:
   - `ros2 topic hz /dottorcane/agent/scan_obstacles` e `/dottorcane/agent/depth` a ~10 Hz (l'agente si rifiuta di partire senza: messaggio "Sensori non disponibili");
   - `ros2 action list | grep reactive_drive`; per misurare il filtro delle zampe, uno scan con il robot fermo in piedi in uno spazio libero: `ros2 topic echo --once /dottorcane/agent/scan_obstacles > /tmp/scan_fermo.yaml` (punti entro ~0,35 m dal centro sono il corpo; `body_y_m` del nodo è 0,32);
   - in RViz la profondità dal lidar non deve mostrare il pavimento davanti al robot fermo; nel log di `lidar_obstacle_scan` non deve comparire `no floor ahead` su pavimento piano.
4. `dottorcane_arm`.
5. **Calibrazione delle rotazioni**, la prima cosa da fare: senza giroscopio il giro di ricerca (5 rotazioni da 90°) e la rotazione verso l'apertura scelta sono a tempo. `./scripts/run_nebius_agent.sh "ruota a destra di 90 gradi"` (e "avanza di un metro"), misura l'angolo reale e imposta `NEBIUS_TURN_EFFICIENCY` (e `NEBIUS_FORWARD_EFFICIENCY`) nel `.env`. Gli avanzamenti verso un bersaglio sono comunque chiusi dalla percezione successiva.
6. Agente, sulla Jetson: `NEBIUS_VISION_MODEL=nvidia/Nemotron-3.5-Super-VL ./scripts/run_nebius_agent.sh "vai vicino alla sedia"` (bersaglio a 2–5 m), poi uno in un'altra stanza.

Cosa guardare nel log: `[Drive] action: target at ...`, poi `[Drive] re-aim N: ... (lidar: tracking, ...)`: quando il lidar aggancia il bersaglio le sue direzione e distanza devono essere vicine a quelle del modello vision; `[Timing] AgenticROS reactive_drive(...): ... -> arrived|lost|blocked|stuck`. Nel log del nodo `goal ended: <esito>`. Con `NEBIUS_REACTIVE_DRIVE_ACTION=off` l'agente torna alle fette di `ros2_drive_toward`. `[Waypoint] in view at ...` mentre attraversa una porta. `[Decision] ... retrying with nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` se Lightning non risponde.

Sicurezza: `ros2_estop` (anche Ctrl-C dell'agente) cancella il goal di `reactive_drive` e il robot si ferma. Il nodo si ferma da solo dopo 1,5 s senza l'heartbeat dell'agente (agente morto o wifi caduto), con lo scan più vecchio di 0,3 s e con il goal scaduto (30 s per avanzata). una strada bloccata viene ritentata una volta dopo 2 s (persone che passano). Il telecomando resta il freno. Limiti noti: il pavimento è stimato per corpo in bolla (niente IMU), il vetro può non comparire nello scan, la retromarcia (`backUp`) è cieca.

## Workflow completo (agente + Nav2 DUA)

È lo stesso che gira in simulazione con `go2_sim.launch.py profile:=real` (vedi [GAZEBO_SETUP.md](GAZEBO_SETUP.md#simulazione-uguale-al-robot-profilereal)), dove è stato provato; i dettagli dei singoli passi sono nelle sezioni sotto.

1. Jetson, container DottorCane: `ros2 launch dottorcane_bringup dottorcane_slam.launch.py`.
2. Jetson, nostro container: `ros2 launch go2_real go2_real.launch.py` (profondità, scan e `/dottorcane/agent/nav_cloud` dal lidar; `base_height:=` se l'altezza della base in piedi non è 0,34 m). Va avviato prima di Nav2: le costmap di dua_nav2 leggono `/dottorcane/agent/nav_cloud`, la nuvola deskewed ridotta sulla Jetson alla fascia 0,1–1,0 m del frame `map`, con voxel da 5 cm e solo xyz (`lidar_nav_cloud.py`). Pesa ~0,2 MB/s invece di ~6,4 MB/s, e la nuvola intera passerebbe in Wi‑Fi una volta per ciascuna costmap. La fascia, come quella di dua_nav2 con la nuvola intera, è nel frame `map`, che LIO-SAM fa partire con la base a 7,75 cm da terra e beccheggio −5° (`initial_pose` di `dottorcane_slam.yaml`; sembra la posa del cane sdraiato, non verificato). Controllo col cane in piedi: `ros2 topic echo --once /dottorcane/slam/ekf_global/odometry --field pose.pose.position.z` deve dare circa l'altezza della base (~0,3 m). Se dà ~0, il pavimento è a −0,3 m nel frame `map` e gli ostacoli sotto ~40 cm spariscono dalle costmap: riavvia lo stack col cane sdraiato.
3. PC, container `dua_nav2`, come client del router del robot: `RMW_IMPLEMENTATION=rmw_zenoh_cpp ZENOH_CONFIG_OVERRIDE='mode="client";connect/endpoints=["tcp/<IP>:7447"];scouting/multicast/enabled=false' ros2 launch dua_nav2_bringup dottorcane.launch.py` (`use_sim_time` è `false` di default). La costmap globale ha `track_unknown_space: true`: senza celle sconosciute `explore` non trova frontiere e l'agente non usa mai Nav2.
4. PC, nostro container cudev: `ros2 launch go2_real go2_real_nav.launch.py robot:=<IP> nav2:=dua`.
5. Jetson: `dottorcane_arm`, poi `./scripts/run_nebius_agent.sh "…"` (con `GO2_TARGET=real`, già impostato nel container jetson6). All'avvio deve comparire `[Navigation] Nav2 live map (SLAM), frontier exploration`: se compare `not running`, l'agente è partito prima di Nav2 o di `explore`.

Con Nav2 l'agente:

- si avvicina con un goal Nav2 a un bersaglio confermato a più di 1,5 m oltre la distanza di arrivo, l'ultimo metro resta visivo;
- esplora con le frontiere di `agenticros_explore` o, senza frontiere, con goal Nav2 lungo la direzione scelta;
- ricorda i posti della sessione nel frame `map`: "ricorda questo posto come cucina", "vai in cucina", e ogni bersaglio raggiunto ("torna dal frigorifero"). Il file è `logs/places_session.json`: **cancellalo quando riavvii lo stack DottorCane**, perché il frame `map` di LIO-SAM riparte dalla posa del robot;
- con `ros2_estop` (anche Ctrl-C) annulla i goal di Nav2 (skill `config/agenticros-skills/go2-nav2-dua`).

Le velocità di Nav2 sono quelle di `dua_nav2/config/dottorcane.yaml` (MPPI fino a 1 m/s), non i limiti di AgenticROS: il telecomando resta il freno.

**Pavimento come ostacolo** (corretto il 21 ottobre, vedi [CHANGELOG.md](CHANGELOG.md)): se la distanza libera resta intorno a 0,3–0,5 m con spazio libero davanti, guarda `/dottorcane/agent/depth` in RViz. Il nodo toglie il pavimento in base all'altezza da terra nel frame `map` (`base_height`, `floor_height`), quindi deve vedere la TF `map → dottorcane/base_link`; senza, lo dice nel log e stima il pavimento come per un corpo in bolla.

## Prova sul robot

Sulla Jetson, con il repo clonato insieme ai submodule e il `.env` con la `NEBIUS_API_KEY`:

```bash
cd docker/container-jetson6/.devcontainer && docker compose up -d --build   # la prima build richiede tempo
docker exec -it devcontainer-hackathon-nvidia-jetson6-1 zsh
agenticros_setup                     # agenticros_msgs + go2_real + pnpm install/build
```

1. **Stack DottorCane** (nel suo container): `ros2 launch dottorcane_bringup dottorcane_slam.launch.py`.
2. **Topic** (nel nostro container):

   ```bash
   dottorcane_zenoh
   ros2 topic list | grep -i -E "dottorcane|camera|image"   # trova il topic della camera USB
   ros2 topic hz <topic camera>
   ros2 topic echo --once <camera_info della camera> --field header   # frame_id
   ```

3. **Camera USB nella TF.** Se il suo frame non è nell'URDF del DottorCane, pubblica una TF statica dalla base. Misura la posizione rispetto a `dottorcane/base_link`: x avanti, y sinistra, z su, in metri; yaw, pitch e roll in radianti (pitch positivo = camera inclinata verso il basso):

   ```bash
   ros2 run tf2_ros static_transform_publisher --x 0.30 --y 0 --z 0.10 --yaw 0 --pitch 0 --roll 0 \
     --frame-id dottorcane/base_link --child-frame-id dottorcane/usb_camera
   ```

   Un frame pubblicato così segue la convenzione con x in avanti: va quindi lanciato con `camera_convention:=body`, oppure lasciando `auto`.
4. **Profondità**:

   ```bash
   # camera calibrata (camera_info con frame nella TF)
   ros2 launch go2_real go2_real.launch.py camera_info:=<camera_info della camera USB>
   # camera senza calibrazione
   ros2 launch go2_real go2_real.launch.py camera_frame:=dottorcane/usb_camera hfov_deg:=<HFOV> image_width:=<W> image_height:=<H>
   ```

   - Il log mostra `camera WxH fx=... fy=... (HFOV X deg) -> depth 320xN in <frame>`. Usa quell'HFOV per l'agente: `export NEBIUS_CAMERA_HFOV_DEG=X`.
   - Se il nodo resta in attesa della TF, il frame non è nell'albero: vedi il punto 3, oppure `camera_frame:=`.
   - Se la profondità risulta ruotata, passa `camera_convention:=optical|body`.
   - Senza argomenti usa la camera frontale del Go2.
5. **RViz** da un PC (container cudev): `ros2 launch go2_real rviz.launch.py robot:=<IP della Jetson> camera:=<topic camera USB>`. Metti una persona o una scatola davanti al robot: la macchia vicina nell'immagine "Lidar depth" deve stare dove l'oggetto compare nella camera. Se è spostata, correggi la TF della camera.
6. **Agente senza movimento**: `export NEBIUS_CAMERA_TOPIC=<topic camera USB>`, poi `./scripts/run_nebius_agent.sh "Guarda davanti al robot e descrivi gli ostacoli. Non muovere il robot."`
7. **Arm**: `dottorcane_arm`. Senza, `go2_control` ignora il cmd_vel.
8. **Movimenti**, in un'area sgombra e con il telecomando Unitree in mano:
   - `"ruota a destra di 90 gradi"` e `"avanza di un metro"`: misura l'angolo e i metri reali;
   - imposta `NEBIUS_TURN_EFFICIENCY` e `NEBIUS_FORWARD_EFFICIENCY` (frazione ottenuta) nel `.env`;
   - misura l'altezza della camera da terra e imposta `NEBIUS_CAMERA_HEIGHT_M`.
9. **Avvicinamento**: un oggetto a 2–3 m, per esempio `"vai vicino alla sedia"`. La posa di LIO-SAM serve a controllare l'arrivo dall'esterno, come la posa di Gazebo in sim. Non va passata all'agente.

Per fermare il robot: `ros2 topic pub --once /dottorcane/go2_control/cmd_vel geometry_msgs/msg/Twist "{}"` (dopo `dottorcane_zenoh`), oppure `dottorcane_disarm`, che toglie il controllo via ROS. Il telecomando resta comunque il freno di emergenza. Nel container DottorCane c'è anche `killswitch` (`/dottorcane/go2_control/kill_switch`): probabilmente spegne i motori, quindi il robot cade. Usalo solo come ultima risorsa.

## Nav2 dal PC, senza mappa

Nav2 gira sul PC (container cudev) e si collega al router zenoh del cane come RViz. Sulla Jetson `go2_real.launch.py` pubblica anche `/dottorcane/agent/scan_obstacles`: uno scan a 360° con i punti del Mid-360 fra 10 e 70 cm dal pavimento (`lidar_obstacle_scan.py`, ultimi 0,3 s nel frame odom, corpo del robot tolto). In wifi passa così solo lo scan, non la nuvola intera. Dietro il robot il lidar inclinato guarda in alto: lì le direzioni vuote valgono NaN, per non cancellare gli ostacoli già segnati.

```bash
# Jetson: stack DottorCane, poi
ros2 launch go2_real go2_real.launch.py            # profondità + scan ostacoli (base_height:=0.34)
# PC, container cudev
ros2 launch go2_real go2_real_nav.launch.py robot:=<IP della Jetson>
ros2 launch go2_real go2_real_nav.launch.py robot:=<IP> map_topic:=<OccupancyGrid dello SLAM>   # con la mappa
```

- **Nav2 DUA.** Il Nav2 di dotX gira sul PC, nel namespace `/dottorcane/dua_nav2` (costmap globale con obstacle layer, locale con voxel layer, `navigate_to_pose`). In quel caso non va avviato il nostro, altrimenti i due Nav2 si contendono il cmd_vel: `ros2 launch go2_real go2_real_nav.launch.py nav2:=dua` avvia solo `agenticros_explore`, che legge `/dottorcane/dua_nav2/global_costmap/costmap` e manda i goal a `/dottorcane/dua_nav2/navigate_to_pose`. `map_frame:=` va impostato al `frame_id` di quella costmap (default `map`). Senza `/explore` l'agente usa comunque Nav2 per l'avvicinamento e per le camminate di esplorazione.
- Parametri in `src/go2_real/config/nav2_go2_real.yaml`: quelli della sim, senza AMCL. La TF `map → dottorcane/base_link` e l'odometria vengono dall'EKF (`/dottorcane/slam/ekf_global/odometry`). La costmap globale è rolling, 30 × 30 m, fatta solo dallo scan; con `map_topic:=` aggiunge la `OccupancyGrid` dello SLAM come static layer.
- Parte anche `agenticros_explore` (action `explore`), sulla costmap globale o su `map_topic`. L'agente sulla Jetson trova `navigate_to_pose` ed `explore` da solo all'avvio (`[Navigation] ...`); va riavviato dopo Nav2.
- Il collision monitor scrive `/dottorcane/go2_control/cmd_vel` e ferma il robot se lo scan manca per più di 1 s. Prima serve `dottorcane_arm`.
- Tempo reale (`use_sim_time: false`): gli orologi di Jetson e PC devono coincidere (chrony/NTP), altrimenti le TF vanno in errore di estrapolazione.
- Verificato nel cudev con router zenoh locale, TF e scan finti: Nav2 attivo, action presenti, costmap 600 × 600 celle. Lo scan sintetico (pavimento con ±2 cm di rumore, scatola a 1 m, muro a 1,5 m, zampe) dà 1,0 m, 1,5 m, niente pavimento né zampe. In simulazione (profilo `real`) lo scan pubblicava ~0,2 Hz per un lookup TF bloccante: corretto, ora 10 Hz.

## Risposte dello stack DottorCane (20 ottobre)

- `camera_info` e frame: nel config e nell'URDF del DottorCane. Per la camera frontale è `go2_camera.yaml` (`camera_name: front`).
- `go2_control` accetta il `cmd_vel` dopo l'action `arm`.
- Camera frontale: raw e compressa; frequenza da misurare.
- La camera RGB sarà la **USB del DottorCane** (monoculare), non quella frontale del Go2.
- I submodule ci sono tutti nel loro container. Con l'account `ilGalghi` restano illeggibili, quindi il codice di `go2_control` non l'abbiamo visto.

Ancora aperti, da vedere domani:

- topic, calibrazione e posizione della camera USB;
- IP del router zenoh;
- internet sulla Jetson per Nebius.

## Cosa aspettarsi

- **Profondità dal lidar.**
  - È più rada di quella della ZED in sim. Il Mid-360 dà ~200k punti/s su 360°, di cui solo circa un quarto cade nel campo della camera, quindi ~25k punti in 0,5 s su 45k pixel. La prova sintetica, con tutti i punti davanti, non dice quanto resta vuoto sul reale: guardalo in RViz e, se serve, alza `window` o `fill_radius`.
  - Oggetti sottili (gambe di sedie) e il bordo superiore dell'immagine possono restare senza punti: in avanti il Mid-360 inclinato copre circa da −37° a +22°, la camera ±25°.
  - Fra lidar e camera c'è una parallasse di ~10 cm.
  - L'agente osserva da fermo, quindi i punti non vanno compensati per il moto.
- **Camera.** La USB è monoculare: le distanze vengono solo dal lidar, quindi conta che la TF della camera sia giusta (punto 3). Kimi-K2.6 è stato misurato solo sui render della sim: conviene salvare qualche frame vero e ripassarlo con `scripts/vision_eval/`.
- **Movimenti.** La sport mode segue la velocità molto meglio di CHAMP: efficienze vicine a 1, niente fattore RTF. Va comunque misurato.
- **Sicurezza.**
  - `backUp` cammina all'indietro senza sensori posteriori.
  - Il corridoio è l'unico controllo degli ostacoli davanti, e dipende da profondità e altezza della camera corrette.
  - Il watchdog di `go2_control` ferma il robot se l'agente muore a metà movimento.
