// Heading from the IMU gyroscope (ros2_imu_yaw) against the ground truth, through the real MCP
// server and under the agent's load: -90 deg turns, each followed by a camera frame, the depth
// band and the corridor. Prints "epoch label imu_yaw_deg gaps"; imu_check.sh compares with the truth.
// Usage (sim running): node imu_check.mjs
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const agenticros = path.join(here, "..", "..", "tools", "agenticros", "packages");
const sdk = path.join(agenticros, "agenticros-nebius", "node_modules", "@modelcontextprotocol", "sdk", "dist", "esm", "client");
const { Client } = await import(path.join(sdk, "index.js"));
const { StdioClientTransport } = await import(path.join(sdk, "stdio.js"));

const IMU = "/dottorcane/slam/zed_x_driver/imu";
const DEPTH = "/dottorcane/slam/zed_x_driver/depth_distances";
const transport = new StdioClientTransport({
  command: process.execPath,
  args: [path.join(agenticros, "agenticros-claude-code", "dist", "index.js")],
  env: { ...process.env, AGENTICROS_CONFIG_PATH: path.join(here, "..", "..", "config", "agenticros.json") },
  stderr: "ignore",
});
const client = new Client({ name: "imu-check", version: "0" });
await client.connect(transport);
const call = async (name, args) => {
  const r = await client.callTool({ name, arguments: args }, undefined, { timeout: 30000 });
  return (r.content ?? []).filter((x) => x.type === "text").map((x) => x.text).join("\n");
};
const json = (text) => JSON.parse(text.split("\n").reverse().find((l) => l.trim().startsWith("{")));
const imu = async (label) => {
  const r = json(await call("ros2_imu_yaw", { topic: IMU }));
  console.log(`${(Date.now() / 1000).toFixed(2)} ${label} ${r.yaw_deg} ${r.gaps}`);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

await imu("baseline");
await sleep(1000);
await imu("start");
for (let i = 0; i < 8; i++) {
  await call("ros2_move_for", { linear_x: 0, angular_z: -0.5, duration_seconds: 3 });
  await call("ros2_move_for", { linear_x: 0, angular_z: -0.5, duration_seconds: 1.08 });
  await call("ros2_camera_snapshot", { topic: "/dottorcane/slam/zed_x_driver/left/image_rect_color", message_type: "Image" });
  await imu(`after_frame_${i}`);
  await Promise.all([
    call("ros2_depth_distance", { topic: DEPTH, roi_x_min: 0.4, roi_y_min: 0.25, roi_x_max: 0.6, roi_y_max: 0.5 }),
    call("ros2_depth_corridor", { topic: DEPTH, camera_height_m: 0.385, hfov_deg: 110, half_width_m: 0.25 }),
  ]);
  await sleep(2000);
  await imu(`settled_${i}`);
}
await client.close();
