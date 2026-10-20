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
| Localizzazione | posa vera di Gazebo | EKF `/dottorcane/slam/ekf_global/odometry` e LIO-SAM `/dottorcane/slam/lio_sam/map_optimization/{pose,path,local_map}`; TF `map → dottorcane/odom → dottorcane/base_link` |
| Nav2 | sì (`nav:=map\|slam`) | no: su JetPack 6 (Ubuntu 22.04) i pacchetti `ros-jazzy-*` non esistono e il ROS di base è compilato da sorgente. Non serve per le prime prove |

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
