# Checklist prove live sul Go2

Versione breve di [GO2_REALE.md](GO2_REALE.md). Spunta in ordine.

## Prima di accendere

- [ ] Sulla Jetson c'è internet (serve a Nebius) e il `.env` contiene la `NEBIUS_API_KEY`.
- [ ] IP della Jetson / del router zenoh (porta 7447), per RViz dal PC.
- [ ] Container `jetson6` buildato e `agenticros_setup` completato senza errori.
- [ ] Telecomando Unitree in mano, area sgombra.

## Stack e topic

- [ ] Stack DottorCane avviato: `dottorcane_slam.launch.py`, non `dottorcane.launch.py`, che non avvia il lidar.
- [ ] `dottorcane_zenoh`, poi `ros2 topic list`: compaiono camera USB, `/dottorcane/sensors/livox_lidar_driver/point_cloud` e `/dottorcane/go2_control/imu`.
- [ ] Annota **topic camera USB**, `camera_info` (se c'è), `frame_id`, risoluzione.

## Parametri da impostare

| Cosa | Dove | Valore attuale | Da fare |
| --- | --- | --- | --- |
| Topic camera | `NEBIUS_CAMERA_TOPIC` | camera frontale Go2 | metti quello della USB |
| HFOV camera | `NEBIUS_CAMERA_HFOV_DEG` | 94,7 (camera frontale) | copia l'HFOV stampato da `go2_real.launch.py` |
| Frame camera nella TF | URDF o `static_transform_publisher` | — | se manca, misura x/y/z/pitch dalla base |
| Calibrazione assente | `go2_real.launch.py hfov_deg:= camera_frame:= image_width:= image_height:=` | usa `camera_info` | solo se la USB non ha `camera_info` |
| Altezza camera da terra | `NEBIUS_CAMERA_HEIGHT_M` | 0,36 (stima) | misura col metro, robot in piedi |
| Rotazioni | `NEBIUS_TURN_EFFICIENCY` | 1,0 | gradi ottenuti / comandati con "ruota a destra di 90 gradi" |
| Avanzamento | `NEBIUS_FORWARD_EFFICIENCY` | 1,0 | metri ottenuti / comandati con "avanza di un metro" |

I valori definitivi vanno nel `.env`.

## Verifiche in ordine

1. [ ] `ros2 launch go2_real go2_real.launch.py ...`: nel log compare la riga `camera ... -> depth 320xN`, non l'attesa della TF.
2. [ ] RViz dal PC: `ros2 launch go2_real rviz.launch.py robot:=<IP> camera:=<topic USB>`. Con una scatola davanti, la macchia vicina in "Lidar depth" deve coincidere con la scatola nella camera. Se è spostata, correggi la TF della camera; se è ruotata, usa `camera_convention:=optical|body`.
3. [ ] Profondità rada? Se l'immagine è piena di buchi, alza `window` (0,5 s) o `fill_radius` (1).
4. [ ] Agente fermo: `"Guarda davanti al robot e descrivi gli ostacoli. Non muovere il robot."` La descrizione deve essere sensata.
5. [ ] `dottorcane_arm`: senza arm il cmd_vel viene ignorato.
6. [ ] Calibrazione: misura una rotazione di 90° e un avanzamento di 1 m, poi aggiorna le efficienze.
7. [ ] Avvicinamento a 2–3 m: `"vai vicino alla sedia"`. L'arrivo va controllato col metro (o con la posa LIO-SAM), senza darlo all'agente.

## Stop

- `ros2 topic pub --once /dottorcane/go2_control/cmd_vel geometry_msgs/msg/Twist "{}"`, oppure `dottorcane_disarm`.
- Telecomando = freno vero. `killswitch` spegne i motori, quindi il robot cade: solo come ultima risorsa.
