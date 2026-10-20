# hackathon-nvidia

Quadrupede Unitree Go2 ("DottorCane") simulato in Gazebo Harmonic e guidato da AgenticROS con modelli su Nebius Token Factory: Nemotron decide le azioni, il modello vision (Kimi-K2.6) localizza i bersagli e descrive la scena, YOLO locale può aiutare sui bersagli COCO. Flusso completo: [`src/README.md`](src/README.md); simulazione: [`docs/GAZEBO_SETUP.md`](docs/GAZEBO_SETUP.md); agente: [`docs/NEBIUS_AGENTICROS.md`](docs/NEBIUS_AGENTICROS.md); ultime modifiche alla percezione: [`docs/CHANGELOG.md`](docs/CHANGELOG.md); confronto prima/dopo: [`docs/CONFRONTO_PERCEZIONE.md`](docs/CONFRONTO_PERCEZIONE.md); Go2 reale: [`docs/GO2_REALE.md`](docs/GO2_REALE.md), checklist per le prove: [`docs/CHECKLIST_REALE.md`](docs/CHECKLIST_REALE.md).

## Come testare

Tutto gira nel container DUA (ROS, Gazebo e Node non sono sull'host):

```bash
# host
cd docker/container-x86-cudev/.devcontainer && DISPLAY=$DISPLAY docker compose up -d
docker exec -it devcontainer-hackathon-nvidia-x86-cudev-1 zsh
```

Nel container, una volta sola o dopo modifiche al codice:

```bash
cd ~/workspace
cbuild                                   # workspace ROS
cd tools/agenticros && pnpm build && cd ~/workspace   # AgenticROS (l'agente gira da dist/)
```

`.env` nella root deve contenere `NEBIUS_API_KEY` (vedi `.env.example`). Per la percezione con i box conviene `NEBIUS_VISION_MODEL=moonshotai/Kimi-K2.6`, oppure nessuna riga: è il default.

### 1. Lanciare la simulazione (terminale 1)

```bash
cd ~/workspace
pkill -9 -f "[g]z sim"; pkill -9 -f "[d]ua_component_container"   # orfani di sessioni precedenti
source install/setup.zsh
export DISPLAY=:0                        # solo se vuoi la GUI di Gazebo

ros2 launch go2_sim_worlds go2_sim.launch.py world:=house                  # casa, senza Nav2
ros2 launch go2_sim_worlds go2_sim.launch.py world:=house gui:=false       # idem, headless
ros2 launch go2_sim_worlds go2_sim.launch.py world:=house nav:=map         # Nav2 + AMCL, stanze note
ros2 launch go2_sim_worlds go2_sim.launch.py world:=house nav:=slam        # Nav2 + SLAM, esplorazione a frontiere
ros2 launch go2_sim_worlds go2_sim.launch.py world:=ldc25                  # campo esterno con idrante e semaforo
```

La casa richiede i modelli scaricati una volta con `./scripts/fetch_house_world.sh`.

### 2. Lanciare l'agente (terminale 2)

La percezione si sceglie con `NEBIUS_PERCEPTION`:

| Modalità | Comando | Chi localizza il bersaglio |
|---|---|---|
| senza YOLO (default) | `./scripts/run_nebius_agent.sh "…"` | solo il modello vision (Kimi-K2.6, bounding box) |
| con YOLO | `NEBIUS_PERCEPTION=yolo ./scripts/run_nebius_agent.sh "…"` | YOLO a riquadri per i bersagli COCO, il modello vision per gli altri e come ripiego |
| con YOLO26s | `NEBIUS_PERCEPTION=yolo AGENTICROS_YOLOV8_MODEL=~/.agenticros/models/yolo26s.onnx ./scripts/run_nebius_agent.sh "…"` | come la precedente, con un YOLO più recente (export in [`docs/CHANGELOG.md`](docs/CHANGELOG.md#4-yolo-versione-con-yolo)) |
| con MiniCPM-V | `NEBIUS_VISION_MODEL=openbmb/MiniCPM-V-4_5 ./scripts/run_nebius_agent.sh "…"` | modello vision a 9 colonne, per confronto (meno preciso) |

```bash
cd ~/workspace
source install/setup.zsh

# casa (world:=house, nav:=none)
./scripts/run_nebius_agent.sh "vai vicino al frigorifero"
./scripts/run_nebius_agent.sh "vai vicino al cestino della spazzatura"
./scripts/run_nebius_agent.sh "vai vicino all'armadio"
NEBIUS_PERCEPTION=yolo ./scripts/run_nebius_agent.sh "vai vicino al frigorifero"   # stessa prova con YOLO
./scripts/run_nebius_agent.sh "Guarda davanti al robot e descrivi gli ostacoli. Non muovere il robot."

# casa con nav:=map: prima Nav2 fino alla stanza, poi l'avvicinamento visivo
./scripts/run_nebius_agent.sh "vai in camera da letto"

# ldc25
./scripts/run_nebius_agent.sh "cerca l'idrante rosso e vacci vicino"
NEBIUS_PERCEPTION=yolo ./scripts/run_nebius_agent.sh "cerca l'idrante rosso e vacci vicino"

# fermare il robot a mano
ros2 topic pub --once /dottorcane/go2_control/cmd_vel geometry_msgs/msg/Twist "{}"
```

Tra una prova e l'altra si può riportare il robot al punto di partenza della casa senza rilanciare la sim:

```bash
gz service -s /world/default/set_pose --reqtype gz.msgs.Pose --reptype gz.msgs.Boolean --timeout 3000 \
  --req 'name: "dottorcane", position: {x: 0.0, y: 1.5, z: 0.30}, orientation: {x: 0, y: 0, z: 0, w: 1}'
```

### 3. Cosa guardare

- Avvio: `[Perception] mode=vlm vision=moonshotai/Kimi-K2.6 grounding=box width=1024`.
- A ogni passo, su stderr:
  - `[Step N]`: bersaglio, bearing, distanza, spazio libero;
  - `[Decision]`: scelta di Nemotron o rifiuto del controller;
  - `[Verify]`: ricontrollo sul ritaglio, `no match` = avvistamento scartato;
  - `[Perception] depth … does not match the target box`: un oggetto davanti al bersaglio.
- Su stdout esce solo la risposta finale in italiano.
- Esiti attesi nella casa: frigorifero in ~11 passi (~70 s) a ~0,9 m; cestino in ~5 passi. Se il robot finisce contro tavolo e sedie, la risposta corretta è "Il percorso verso il bersaglio è bloccato", non un arrivo.
- Per controllare l'arrivo dall'esterno, con la posa reale (che l'agente non vede): `scripts/vision_eval/closed_loop.sh` e `scripts/vision_eval/hydrant_run.sh`.

### 4. Test automatici e valutazione offline

```bash
cd ~/workspace/tools/agenticros
pnpm --filter @agenticros/nebius build && pnpm --filter @agenticros/nebius test   # unit test della policy e del modello vision

cd ~/workspace/scripts/vision_eval      # confronto dei modelli vision e di YOLO, vedi README della cartella
../../.venv/bin/python score.py --robust kimi26_final_1024 minicpm_cols9_768
python3 yolo_score.py yolo26s yolov8n_project
```

---

GitHub template repositories for projects based on the Distributed Unified Architecture.

See [`dua-template.md`](dua-template.md) for more information.

## AgenticROS

AgenticROS is pinned as a Git submodule in `tools/agenticros`. Its ROS 2 packages are exposed to the main DUA workspace by the relative symlink `src/agenticros -> ../tools/agenticros/ros2_ws/src`, so a normal build from the repository root includes them.

Clone the project together with the submodule:

```bash
git clone --recurse-submodules git@github.com:ilGalghi/hackathon-nvidia.git
```

For an existing clone:

```bash
git submodule update --init --recursive
```

Rebuild the `container-x86-cudev` devcontainer after cloning. Its post-create step runs `bin/setup_agenticros.sh`, which builds the main ROS workspace, installs the pinned pnpm dependencies, and builds the AgenticROS packages. Inside the container, the same setup can be run again with:

```bash
agenticros_setup
agenticros doctor
```

The default configuration is `config/agenticros.json` and uses local DDS on ROS domain 0. Keep machine-specific configuration in `config/agenticros.local.json`, which is ignored by Git, and point `AGENTICROS_CONFIG_PATH` to it when needed.

---

## Copyright and License

Copyright 2026 dotX Automation s.r.l.

Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.

You may obtain a copy of the License at <http://www.apache.org/licenses/LICENSE-2.0>.

Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

See the License for the specific language governing permissions and limitations under the License.
