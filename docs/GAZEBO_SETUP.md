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

## Limiti osservati

- Il controller produce molti warning `A new JointTrajectory message was
  received while executing a previous trajectory`; la simulazione continua a
  funzionare, ma la frequenza delle traiettorie andrà corretta prima delle prove
  di movimento.
- `ros_gz_republish` e il container DUA possono mostrare eccezioni durante lo
  shutdown via `Ctrl-C`. L'errore è nel cleanup e non ha impedito la
  pubblicazione dei sensori.
- Questo launch non contiene ancora Nav2 mapless. La navigazione verrà aggiunta
  dal relativo workstream senza `map_server` o AMCL.
