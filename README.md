# dua-template


cd ~/workspace
export DISPLAY=:0                     # solo se vuoi la GUI di Gazebo
pkill -9 -f "[g]z sim"; pkill -9 -f "[d]ua_component_container"   # eventuali processi orfani di sessioni precedenti
source install/setup.zsh

# CON mappa (Nav2 + AMCL, stanze note)
ros2 launch go2_sim_worlds go2_sim.launch.py world:=house nav:=map

# oppure SENZA mappa (Nav2 + SLAM + esplorazione a frontiere)
ros2 launch go2_sim_worlds go2_sim.launch.py world:=house nav:=slam


GitHub template repositories for projects based on the Distributed Unified Architecture.

See [`dua-template.md`](dua-template.md) for more information.

## AgenticROS

AgenticROS is pinned as a Git submodule in `tools/agenticros`. Its ROS 2
packages are exposed to the main DUA workspace by the relative symlink
`src/agenticros -> ../tools/agenticros/ros2_ws/src`, so a normal build from the
repository root includes them.

Clone the project together with the submodule:

```bash
git clone --recurse-submodules git@github.com:ilGalghi/hackathon-nvidia.git
```

For an existing clone:

```bash
git submodule update --init --recursive
```

Rebuild the `container-x86-cudev` devcontainer after cloning. Its post-create
step runs `bin/setup_agenticros.sh`, which builds the main ROS workspace,
installs the pinned pnpm dependencies, and builds the AgenticROS packages.
Inside the container, the same setup can be run again with:

```bash
agenticros_setup
agenticros doctor
```

The default configuration is `config/agenticros.json` and uses local DDS on
ROS domain 0. Keep machine-specific configuration in
`config/agenticros.local.json`, which is ignored by Git, and point
`AGENTICROS_CONFIG_PATH` to it when needed.

---

## Copyright and License

Copyright 2026 dotX Automation s.r.l.

Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.

You may obtain a copy of the License at <http://www.apache.org/licenses/LICENSE-2.0>.

Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

See the License for the specific language governing permissions and limitations under the License.
