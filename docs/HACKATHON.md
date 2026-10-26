# DottorCane: semantic navigation without a map (Nebius x NVIDIA Global AI Hackathon, Physical AI track)

> Draft for the submission. TODO before submitting: video link, the repository URL, the city of the Builders & Brews event, the list of what changed during the submission period (see the end), and a final check of the numbers below against the latest runs.

## What it is

A Unitree Go2 quadruped (DottorCane, dotX Automation s.r.l.) that takes a request in natural language ("vai vicino al letto", "go near the fridge") and walks there **without any estimate of its own pose**: no map, no SLAM, no odometry, no IMU integration, no Nav2. It navigates on what it sees, the way a person asked to find something in a house they do not know would: look around, recognize the room, choose a doorway that likely leads to the object, walk through it, look again.

- **NVIDIA Nemotron** (on Nebius Token Factory) interprets the request and chooses every action through tool calls: search, face the target, approach, explore, finish.
- **NVIDIA Nemotron-3.5-Super-VL** (on Nebius Token Factory) is the robot's eyes: it localizes the target with a bounding box, describes the scene, finds doorways, picks which opening to explore from a mosaic of the views of a search turn, and finds that opening again in later frames from its own description (a *semantic waypoint*).
- **AgenticROS** is the agent runtime: an MCP server exposes the robot (ROS 2 Jazzy, rmw_zenoh) as tools with safety limits; the Nebius agent reaches the robot only through them.
- A **reactive drive** on the instantaneous lidar scan (Livox Mid-360, no model) avoids obstacles between two observations and measures from the scan whether the robot is actually moving.

## How it works

```
request ──> Nemotron (parse) ──> goal loop:
   camera frame ──> Nemotron-3.5-Super-VL: target box, doorways, waypoint box, scene
   lidar ──> depth in the box (distance), obstacle scan (corridor ahead)
   Nemotron (tool call) ──> intent ──> deterministic controller (bounds, rejects, safety)
   ──> AgenticROS MCP tools: ros2_drive_toward (reactive, <= 3 s), ros2_move_for (turns), ros2_estop
```

- **No state between observations.** Each motion is a short command (at most 1.5 m toward the target, or one search turn); the next frame of the vision model corrects it. Nothing is integrated over time.
- **Exploration from the current view.** After a full turn without the target, the vision model sees the turn as one mosaic together with a text memory of the places seen so far, and names the opening to take ("open doorway next to the wooden-framed glass partition"). The robot turns toward it once, then follows that description frame by frame until it is through.
- **Deterministic safety.** The language model only chooses semantic intents; geometry, limits and every arrival check stay in code: crop verification of sightings, depth consistent with the box, a close object filling the frame is not an arrival, stop at 0.7 m from the base centre, a missing floor ahead (stairs) reads as an obstacle, a blocked path is retried once after 2 s, the estop stops a drive slice at once.
- **Resilient to the endpoint.** A step decision has 10 s; if the primary Nemotron does not answer, the next calls go to Nemotron Nano (reasoning off, ~0.8 s) and, failing that, a deterministic policy decides. The robot never waits minutes for a reply.

## Results (simulation that matches the real robot: same topics, frames, sensors, middleware)

| Task | Result |
| --- | --- |
| "go near the fridge" (8 m away, behind a sofa and a dining table) | reached at 1.2 m in 7 steps |
| "go near the bed" (another room, not visible from the start, behind a single passage flanked by glass partitions) | 2 of 5 runs, in 23 and 29 steps: the vision model chose the doorway, the robot followed it through and found the bed; the failures were the bed seen through the glass |
| vision models on 7 frames with ground truth | Nemotron-3.5-Super-VL: 7/7 visibility, median bearing error 1.1 deg, 1.2 s; Kimi-K2.6: 7/7, 2.0 deg, 1.2 s |

The physical demo on the Go2 is in the video (TODO).

## NVIDIA models and Nebius

| Model (Nebius Token Factory) | Role | Notes |
| --- | --- | --- |
| `nvidia/Nemotron-3_5-Lightning` | request parsing, step decisions (tool calls) | ~0.3-0.4 s per decision when the endpoint is healthy |
| `nvidia/Nemotron-3.5-Super-VL` | perception: boxes, scene, doorways, exploration choice, semantic waypoints | `chat_template_kwargs: {enable_thinking: false}`: 1 s instead of 2 s, same boxes |
| `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | fallback for decisions and parsing | thinking off: 0.75 s |

Every model call goes through Token Factory's OpenAI-compatible API. A run of the bed task costs about 30 vision calls and 30 decisions.

## Running it

- Simulation (Gazebo Harmonic, DUA container): see `README.md`, section "Branch `mapless`".
- Real robot: `docs/GO2_REALE.md`, section "Branch `mapless`".

## Feedback on Nebius Token Factory and the NVIDIA models

- Nemotron-3.5-Super-VL returns boxes on a 0-1000 grid even when asked for 0-1 fractions; it reasons by default (about 270 tokens per frame) and `enable_thinking: false` halves the latency with the same output. Documenting both on the model card would save time.
- Nemotron-3_5-Lightning timed out for hours on 21-22 October 2026 even on 8-token requests (30-90 s), while the vision models answered in about 1 s. A status page or per-model latency figures would help to pick a fallback.
- Nemotron Nano with reasoning on returned no content within 60 tokens: for short structured replies `enable_thinking: false` is necessary.

## What changed during the submission period

TODO: the repository started on (date); list here what was built in the period, e.g. the simulation matching the real robot, the reactive drive, semantic waypoints, the Nemotron-VL perception profile, the fallback chain.
