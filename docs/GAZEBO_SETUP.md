# Simulazione Gazebo LDC25

Il workspace include il mondo LDC25, il modello quadrupede basato su Unitree
Go2, controller CHAMP, camere ZED simulate e bridge Gazebo ↔ ROS 2.

I package ROS sono direttamente sotto `src/`; i modelli del mondo sono in
`config/gazebo/models`. La configurazione AgenticROS usa come camera predefinita:

```text
/dottorcane/slam/zed_x_driver/left/image_rect_color
```

## Build

Dal root del workspace:

```bash
colcon build --symlink-install --packages-up-to ldc25-sim
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

## Topic utili

```text
/dottorcane/slam/zed_x_driver/left/image_rect_color   sensor_msgs/msg/Image
/dottorcane/slam/zed_x_driver/right/image_rect_color  sensor_msgs/msg/Image
/dottorcane/slam/zed_x_driver/point_cloud             sensor_msgs/msg/PointCloud2
/dottorcane/slam/zed_x_driver/imu                     sensor_msgs/msg/Imu
/dottorcane/joint_states                              sensor_msgs/msg/JointState
/dottorcane/go2_control/cmd_vel                       geometry_msgs/msg/Twist
```

Il topic sinistro pubblica immagini larghe 1920 pixel ed è stato verificato
durante lo smoke test.

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
- Questo launch non contiene ancora Nav2 mapless. La navigazione verrà aggiunta
  dal relativo workstream senza `map_server` o AMCL.
