<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/readme/isl-logo-dark.svg">
    <img src="assets/readme/isl-logo-light.svg" alt="Intelligent Systems Lab, University of Rome Tor Vergata" width="340">
  </picture>
</p>

<h1 align="center">AgenticROS × Nebius, mapless mode: no map, no pose, just what the robot sees</h1>

<p align="center">
  <b>The same Unitree Go2 agent as on <a href="../../tree/master"><code>master</code></a>, without SLAM, odometry or Nav2.</b><br>
  Nebius × NVIDIA Global AI Hackathon · <b>Physical AI track</b>
</p>

<p align="center">
  <img alt="Physical AI track" src="https://img.shields.io/badge/track-Physical%20AI-76B900">
  <img alt="NVIDIA Nemotron" src="https://img.shields.io/badge/NVIDIA-Nemotron-76B900?logo=nvidia&logoColor=white">
  <img alt="Nebius Token Factory" src="https://img.shields.io/badge/Nebius-Token%20Factory-1D1D1F">
  <img alt="ROS 2 Jazzy" src="https://img.shields.io/badge/ROS%202-Jazzy-22314E?logo=ros">
  <img alt="License Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-blue">
</p>

> This is the second navigation mode of the project. The [`master` README](../../tree/master#readme) has the full story: the problem, the architecture, the NVIDIA models on Nebius Token Factory, the demo video, the results with Nav2, the feedback and the team. This page only covers what changes without a map.

## What changes without a map

On `master` the robot knows where it is (LiDAR SLAM) and Nav2 plans its path. Here the robot has **no estimate of its own pose of any kind**: no map, no SLAM, no odometry, no IMU heading, no Nav2. It navigates on what it sees right now, so no error can build up over time.

- **The vision model finds the target again at every step.** Kimi-K2.6 or Nemotron-3.5-Super-VL on Token Factory returns the target's box, and LiDAR points projected into the camera give its distance. While the robot walks, the agent re-aims every 2–4 s.
- **Nemotron decides, the code checks.** Nemotron-3.5 Lightning picks the next intent (`search`, `face_target`, `approach_target`, `explore`, `finish`) and the same deterministic controller as on `master` validates it.
- **A reactive drive runs on the robot.** The ROS 2 action `ReactiveDrive` ([`reactive_drive.py`](src/go2_real/scripts/reactive_drive.py)) runs at 20 Hz next to the LiDAR, on the instantaneous obstacle scan in the body frame. It follows the target as a cluster of scan points, steers to the nearest free direction, and brakes at the stop distance. The agent only sends goals, so Wi-Fi is not inside the control loop.
- **Semantic waypoints.** When the target is not in view after a search turn, the vision model sees the turn as one mosaic and describes the doorway to take. The robot then finds that doorway again in each frame from the description and walks through it. If the target is in view but the way is blocked, the model picks the opening that leads to it.
- **Safety without a pose.** The robot moves only through the AgenticROS tools and the action, within the speed limits. While a goal is active, the agent sends a heartbeat at 5 Hz: if it stops, for example because the agent was killed or the Wi-Fi dropped, the robot stops after 1.5 s. `ros2_estop` and `Ctrl-C` cancel a goal at once. A drop-off check stops the robot at stairs going down. The agent doesn't start until the scan and depth are publishing.

<p align="center">
  <img src="assets/readme/navigation-modes.png" alt="Mode 1, SLAM: localized with Nav2. Mode 2, mapless: no map and no pose estimate" width="100%">
</p>

## Results in simulation

House world, robot at the start, the kitchen ~8 m away behind a sofa and a dining table.

| Task | Result |
|---|---|
| *"Go near the fridge"*, Nemotron-3.5 Lightning + Kimi-K2.6 | 3 steps, one reactive drive of ~6 m in 15 s with 4 re-aims, arrival at 1.09–1.11 m (two runs) |
| Same, with only NVIDIA models (`NEBIUS_VISION_MODEL=nvidia/Nemotron-3.5-Super-VL`) | 4 steps, arrival at 1.09 m |
| Same, starting turned 180° away | 2 search turns, then a reactive drive of 5.9 m, arrival at step 5 |
| *"Turn right 90 degrees and walk one meter"* | turns 89°, then refuses to walk: a low coffee table 0.39 m ahead |
| `ros2_estop` during a drive / agent killed during a drive | goal cancelled in 15 ms (0.11 m slip) / robot stops 1.5 s after the last heartbeat |
| *"Go near the bed"*, in another room behind a glass wall | the hardest case: arrivals through the doorway chosen as a semantic waypoint, but also false arrivals (in one run Kimi-K2.6 took the TV cabinet for a bed frame) |

Arrival distances are from the LiDAR depth to the target's surface.

## Quick start (simulation)

Same requirements as on `master`: a Linux host with an NVIDIA GPU, Docker with the NVIDIA container runtime, and a [Nebius Token Factory](https://tokenfactory.nebius.com/) API key.

```bash
# on the host
git clone --recurse-submodules -b mapless https://github.com/IntelligentSystemsLabUTV/hackathon-nvidia.git
cd hackathon-nvidia
cp .env.example .env                       # then set NEBIUS_API_KEY=... in .env
cd docker/container-x86-cudev/.devcontainer && DISPLAY=$DISPLAY docker compose up -d
docker exec -it devcontainer-hackathon-nvidia-x86-cudev-1 zsh
```

In the container (the repository is at `~/workspace`), build once:

```bash
cd ~/workspace
cbuild                                     # colcon build of the ROS 2 workspace
source install/setup.zsh
(cd tools/agenticros && pnpm install --frozen-lockfile \
  && pnpm --filter @agenticros/core exec generate-ros-messages && pnpm build)
./scripts/fetch_house_world.sh             # downloads the house models (AWS RoboMaker Small House)
```

Then three terminals, all on `rmw_zenoh_cpp` like the real robot. There is no Nav2 to start:

```bash
# 1. zenoh router
zenohd -c /etc/zenoh/rmw/DEFAULT_RMW_ZENOH_ROUTER_CONFIG.json5

# 2. simulation, with the LiDAR depth, the obstacle scan and the ReactiveDrive action
RMW_IMPLEMENTATION=rmw_zenoh_cpp ros2 launch go2_sim go2_sim.launch.py world:=house gui:=false

# 3. the agent: one request per run, the answer is printed at the end
./scripts/run_nebius_agent.sh "go near the fridge"
NEBIUS_VISION_MODEL=nvidia/Nemotron-3.5-Super-VL ./scripts/run_nebius_agent.sh "go near the fridge"
./scripts/run_nebius_agent.sh "what do you see in front of you? do not move"
```

<details>
<summary><b>What you will see, and useful options</b></summary>

```text
[Perception] mode=vlm vision=moonshotai/Kimi-K2.6 grounding=box width=1024
[Step 1] target visible (vlm) bearing -16.9 deg, distance 8.02 m, height 0.2; front clearance 5.67 m; doorways at 13.4 deg
[Decision] Nemotron approach_target(1 m) -> rotate(-17 deg) (aligning with the target before advancing)
[Step 2] target visible (vlm) bearing 2.5 deg, distance 8.32 m, height 0.19; front clearance 7.83 m; doorways at 33.6, -33.4 deg
[Decision] Nemotron approach_target(1 m) -> advance(1 m)
[Timing] AgenticROS reactive_drive(target): 15.42s -> arrived, 6.18 m commanded, turned 7 deg, target at 1.11 m, 4 re-aims
[Step 3] target visible (vlm) bearing -11.4 deg, distance 1.09 m, height 0.66; front clearance 1.02 m
[Decision] approach_target(1 m) rejected: the target is already within the stop distance; finish
```

| Variable | Effect |
|---|---|
| `NEBIUS_VISION_MODEL=nvidia/Nemotron-3.5-Super-VL` | NVIDIA vision model instead of Kimi-K2.6 |
| `NEBIUS_MAX_STEPS`, `NEBIUS_MAX_SECONDS` | limits of the goal loop (default 30 steps, 300 s) |
| `NEBIUS_REACTIVE_DRIVE_ACTION=off` | short `ros2_drive_toward` slices from the agent instead of the action |
| `NEBIUS_POLICY=auto` | deterministic policy only, for debugging: it is less careful than Nemotron (in one run it stopped at a dining chair in front of the fridge) |

- Put the robot back at the start without restarting the simulation: `gz service -s /world/default/set_pose --reqtype gz.msgs.Pose --reptype gz.msgs.Boolean --timeout 3000 --req 'name: "dottorcane", position: {x: 0.0, y: 1.5, z: 0.30}, orientation: {x: 0, y: 0, z: 0, w: 1}'`.
- After `Ctrl-C`, Gazebo can stay alive and the next launch reuses the old world: `pkill -9 -f "[g]z sim"` before relaunching.

</details>

<details>
<summary><b>On the real Go2</b></summary>

The DottorCane stack runs on the Jetson as on `master`, but without EKF and SLAM. This branch adds the depth image, the obstacle scan and the `ReactiveDrive` action:

```bash
# Jetson (docker/container-jetson6), with the DottorCane bringup running
ros2 launch go2_real go2_real.launch.py              # localization:=none by default on this branch
dottorcane_arm                                       # go2_control accepts motion only after the arm action
GO2_TARGET=real ./scripts/run_nebius_agent.sh "go near the door"
```

`GO2_TARGET=real` switches the camera height and the motion calibration to the real robot's values. The topics and the action are the same as in simulation.

</details>

## Team and license

**Intelligent Systems Lab, University of Rome “Tor Vergata”**: Leonardo Galgano ([@ilGalghi](https://github.com/ilGalghi)) and Alexandru Cretu ([@ErLex20](https://github.com/ErLex20)).

Copyright 2026 Intelligent Systems Lab, University of Rome “Tor Vergata”. Licensed under the [Apache License, Version 2.0](LICENSE). Third-party code keeps its own license: the CHAMP packages in `src/champ*` are BSD-3-Clause, and AgenticROS in `tools/agenticros` is Apache-2.0.
