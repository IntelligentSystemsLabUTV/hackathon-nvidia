#!/usr/bin/env python3
"""Reactive drive action for the Go2 (DottorCane) with no pose estimate (branch mapless).

    action /dottorcane/agent/reactive_drive (agenticros_msgs/action/ReactiveDrive)

The control loop runs here, next to the lidar and go2_control, at 20 Hz: the agent only sends
goals (bearing and distance of what the vision model sees) and re-sends them after each
observation, and a new goal replaces the running one without stopping the robot. Commanding
cmd_vel from the agent instead (ros2_drive_toward) stopped the robot at the end of every slice
and put the wifi inside the loop.

TARGET mode: the target is followed as a cluster of points of the instantaneous obstacle scan
(lidar_obstacle_scan: Mid-360 points 10-70 cm above the floor, body frame), seeded by the goal
and re-measured at every scan within a small gate; between two scans the estimate moves with the
velocity commanded in the last cycle (one cycle of feed-forward, re-measured right after). This
tracks a landmark, not the robot: nothing about where the robot is gets stored. The robot stops
when the measured camera-to-target distance reaches stop_distance_m. A target outside the scan
band (a picture, something low) is followed on the last bearing for up to blind_timeout seconds
without a new goal.

HEADING mode: drive toward bearing_deg for distance_m (commanded), e.g. through a doorway.

Obstacles: the free heading closest to the wanted one in the latest scan (one row of a vector
field histogram), slow down near obstacles, turn in place beyond turn_in_place_deg. The robot
stops when the scan is older than scan_timeout, and the goal ends as blocked after blocked_timeout
without a free heading (people crossing usually clear in that time), as stuck when the ranges
ahead do not shorten while driving forward, as lost when the target cluster is gone.
"""

import math
import threading
import time

import numpy as np
import rclpy
from agenticros_msgs.action import ReactiveDrive
from geometry_msgs.msg import Twist
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Empty

NAN = float('nan')


def wrap(a):
    return math.atan2(math.sin(a), math.cos(a))


class Goal:
    """State of the goal being executed."""

    def __init__(self, request, now):
        self.request = request
        self.started = now
        self.status = None  # set when the goal ends
        self.done = threading.Event()
        # Target estimate in the body frame (x forward, y left), m.
        self.target = None
        self.tracked = False
        self.last_track = now
        # Camera to the nearest point of the tracked cluster (the surface facing the robot, what
        # the stop distance means); the target estimate itself is the cluster mean.
        self.surface = None
        self.commanded = 0.0  # forward distance commanded (HEADING budget)
        # Commanded by the goals this one preempted (the agent re-aims every few seconds): the
        # result reports the whole uninterrupted drive.
        self.chain_commanded = 0.0
        self.chain_turned = 0.0
        self.blocked_since = None
        self.progress_ref = None  # (time, ranges ahead, commanded distance)
        self.progress = NAN
        self.feedback = ReactiveDrive.Feedback()


class ReactiveDriveNode(Node):

    def __init__(self):
        super().__init__('reactive_drive')
        p = self.declare_parameter
        self.camera_forward = p('camera_forward_m', 0.33).value
        self.rate = p('rate_hz', 20.0).value
        self.max_linear = p('max_linear', 0.5).value
        self.min_linear = p('min_linear', 0.15).value
        self.max_angular = p('max_angular', 0.8).value
        self.min_angular = p('min_angular', 0.3).value
        self.linear_accel = p('linear_accel', 0.6).value
        # Braking profile toward the stop point, v <= sqrt(2 * brake_decel * remaining): with a
        # linear cap the robot reached the stop at 0.46 m/s and coasted 0.2 m past it.
        self.brake_decel = p('brake_decel', 0.4).value
        self.angular_accel = p('angular_accel', 1.5).value
        self.turn_gain = p('turn_gain', 1.5).value
        self.turn_in_place = math.radians(p('turn_in_place_deg', 35.0).value)
        self.half_width = p('half_width_m', 0.25).value
        # Free space ahead is measured from the base centre; the nose is ~0.35 m ahead.
        self.stop_clearance = p('stop_clearance_m', 0.65).value
        self.slow_down = p('slow_down_m', 0.6).value
        self.lookahead = p('lookahead_m', 3.0).value
        self.max_heading = math.radians(p('max_heading_deg', 60.0).value)
        self.heading_step = math.radians(p('heading_step_deg', 5.0).value)
        # Points inside this box (body frame) are the robot: the scan's own body box is narrower
        # than the legs swinging out while walking.
        self.body_x = p('body_x_m', 0.45).value
        self.body_y = p('body_y_m', 0.32).value
        # Association gate around the predicted target: max(gate_range_m, gate_fraction * range).
        self.gate_range = p('gate_range_m', 0.35).value
        self.gate_fraction = p('gate_fraction', 0.1).value
        self.cluster_radius = p('cluster_radius_m', 0.25).value
        self.track_gain = p('track_gain', 0.6).value
        # A new goal within max(agree_m, agree_fraction * range) of the current track keeps it.
        self.agree_m = p('agree_m', 0.8).value
        self.agree_fraction = p('agree_fraction', 0.2).value
        self.lost_timeout = p('lost_timeout_s', 1.0).value
        self.blind_timeout = p('blind_timeout_s', 3.0).value
        # Beyond this range (base to target) the scan cannot see the target reliably (its range_max
        # is 8 m, the band 10-70 cm misses far objects): it is followed on its bearing, untracked.
        self.track_max_range = p('track_max_range_m', 6.0).value
        self.arrive_tolerance = p('arrive_tolerance_m', 0.1).value
        self.face_tolerance = math.radians(p('face_tolerance_deg', 6.0).value)
        self.scan_timeout = p('scan_timeout_s', 0.3).value
        self.no_scan_timeout = p('no_scan_timeout_s', 1.0).value
        self.blocked_timeout = p('blocked_timeout_s', 2.0).value
        self.stuck_window = p('stuck_window_s', 2.0).value
        self.stuck_min_commanded = p('stuck_min_commanded_m', 0.4).value
        self.stuck_max_progress = p('stuck_max_progress_m', 0.1).value
        self.default_timeout = p('timeout_s', 60.0).value
        # The robot must not keep walking a goal of an agent that is gone (process killed, wifi
        # down): the client publishes reactive_drive/heartbeat while a goal runs, and the goal ends
        # after this long without one (0: no heartbeat needed). The graph cannot tell: a killed
        # client stays matched until its discovery lease expires (Fast DDS: 20 s).
        self.heartbeat_timeout = p('heartbeat_timeout_s', 1.5).value
        # Fraction of the commanded motion the base achieves (HEADING budget and turn feed-forward):
        # 1.0 for the Unitree sport mode, 0.84 / 0.77 for CHAMP in simulation.
        self.forward_efficiency = p('forward_efficiency', 1.0).value
        self.turn_efficiency = p('turn_efficiency', 1.0).value

        self.lock = threading.Lock()
        self.goal = None
        self.points = np.zeros((0, 2))
        self.ranges_ahead = None
        self.scan_time = None
        self.cmd = (0.0, 0.0)
        self.last_step = None
        self.heartbeat = None
        self.group = ReentrantCallbackGroup()
        self.pub = self.create_publisher(Twist, 'cmd_vel', 5)
        self.create_subscription(LaserScan, 'scan', self.on_scan, 5, callback_group=self.group)
        self.create_subscription(Empty, 'reactive_drive/heartbeat', self.on_heartbeat, 5, callback_group=self.group)
        self.server = ActionServer(
            self, ReactiveDrive, 'reactive_drive',
            execute_callback=self.execute,
            goal_callback=lambda _: GoalResponse.ACCEPT,
            handle_accepted_callback=self.accepted,
            cancel_callback=lambda _: CancelResponse.ACCEPT,
            callback_group=self.group)
        self.create_timer(1.0 / self.rate, self.step, callback_group=self.group)
        self.get_logger().info('reactive_drive ready (no pose estimate: scan in the body frame only)')

    # --- inputs -------------------------------------------------------------------------

    def on_scan(self, msg: LaserScan):
        r = np.asarray(msg.ranges, dtype=np.float64)
        a = msg.angle_min + np.arange(len(r)) * msg.angle_increment
        ok = np.isfinite(r) & (r > 0) & (r <= msg.range_max)
        pts = np.stack([r[ok] * np.cos(a[ok]), r[ok] * np.sin(a[ok])], axis=1)
        body = (np.abs(pts[:, 0]) <= self.body_x) & (np.abs(pts[:, 1]) <= self.body_y)
        ahead = np.where(np.abs(a) <= math.radians(30.0), r, np.nan)
        with self.lock:
            self.points = pts[~body]
            self.ranges_ahead = ahead
            self.scan_time = time.monotonic()

    def on_heartbeat(self, _msg):
        self.heartbeat = time.monotonic()

    # --- action -------------------------------------------------------------------------

    def accepted(self, handle):
        # A new goal replaces the running one: no stop in between.
        with self.lock:
            previous = self.goal
            if previous is not None and previous.status is None:
                previous.status = 'preempted'
                previous.done.set()
        handle.execute()

    def execute(self, handle):
        now = time.monotonic()
        g = Goal(handle.request, now)
        with self.lock:
            previous = self.goal
            self.goal = g
            if previous is not None and previous.status == 'preempted':
                g.chain_commanded = previous.chain_commanded + previous.commanded
                g.chain_turned = previous.chain_turned + self.turned(previous)
            if g.request.mode == ReactiveDrive.Goal.MODE_TARGET:
                g.target = self.seed(g.request, previous)
                # The vision model's bearing is ~1.5 s old when it arrives (the robot kept moving):
                # when it agrees with the lidar track of the previous goal, keep the track.
                if previous is not None and previous.target is not None and previous.tracked:
                    agree = max(self.agree_m, self.agree_fraction * math.hypot(*previous.target))
                    if math.hypot(*(g.target - previous.target)) <= agree:
                        g.target = previous.target.copy()
                        g.tracked = g.ever_tracked = True
                        g.last_track = now
        while not g.done.wait(0.1):
            if handle.is_cancel_requested:
                with self.lock:
                    if g.status is None:
                        g.status = 'canceled'
                        self.stop()
                g.done.set()
                break
            handle.publish_feedback(g.feedback)
        result = ReactiveDrive.Result()
        result.status = g.status or 'canceled'
        if g.target is not None:
            result.bearing_deg = math.degrees(math.atan2(g.target[1], g.target[0] - self.camera_forward))
            result.range_m = float(math.hypot(g.target[0] - self.camera_forward, g.target[1]))
        else:
            result.bearing_deg, result.range_m = NAN, NAN
        result.progress_m = g.progress
        result.commanded_m = g.chain_commanded + g.commanded
        result.turned_deg = math.degrees(g.chain_turned + self.turned(g))
        result.elapsed_s = time.monotonic() - g.started
        if result.status in ('arrived', 'done'):
            handle.succeed()
        elif result.status == 'canceled':
            handle.canceled()
        else:
            handle.abort()
        self.get_logger().info(f'goal ended: {result.status} after {result.elapsed_s:.1f} s')
        return result

    def seed(self, request, previous):
        """Target point in the body frame from the camera bearing and distance."""
        d = request.distance_m
        if not math.isfinite(d) or d <= 0:
            # Unknown distance: keep the previous estimate's range when it is the same target.
            if previous is not None and previous.target is not None:
                d = math.hypot(previous.target[0] - self.camera_forward, previous.target[1])
            else:
                d = 2.0
        b = math.radians(request.bearing_deg)
        return np.array([self.camera_forward + d * math.cos(b), d * math.sin(b)])

    # --- control loop -------------------------------------------------------------------

    def stop(self):
        # A few zero commands: go2_control keeps the last cmd_vel until its 500 ms watchdog.
        self.cmd = (0.0, 0.0)
        for _ in range(3):
            self.pub.publish(Twist())

    def finish(self, g, status):
        if g.status is None:
            g.status = status
            self.stop()
            g.done.set()

    def step(self):
        with self.lock:
            g = self.goal
            if g is None or g.status is not None:
                return
            now = time.monotonic()
            req = g.request
            timeout = req.timeout_s if req.timeout_s > 0 else self.default_timeout
            if now - g.started > timeout:
                return self.finish(g, 'timeout')
            if self.heartbeat_timeout > 0 and now - max(self.heartbeat or 0.0, g.started) > self.heartbeat_timeout:
                self.get_logger().warn('no heartbeat from the client (agent gone or link down): stopping')
                return self.finish(g, 'client_lost')
            if self.scan_time is None or now - self.scan_time > self.scan_timeout:
                self.stop()
                if self.scan_time is None or now - self.scan_time > self.no_scan_timeout:
                    self.finish(g, 'no_scan')
                return
            # Measured period: the loop runs at 13-16 Hz instead of 20 under load, and integrating
            # the commands with 1/rate made a 1.5 m HEADING goal walk 2.9 m.
            dt = min(0.2, max(0.0, now - self.last_step)) if self.last_step is not None else 1.0 / self.rate
            self.last_step = now
            v_prev, w_prev = self.cmd
            # The goal may lower the speed limits (the agent's safety limits), never raise them.
            max_v = min(self.max_linear, req.max_linear) if req.max_linear > 0 else self.max_linear
            max_w = min(self.max_angular, req.max_angular) if req.max_angular > 0 else self.max_angular
            target_mode = req.mode == ReactiveDrive.Goal.MODE_TARGET
            remaining = NAN
            if target_mode:
                # One cycle of feed-forward, then re-measure in the scan.
                c, s = math.cos(-w_prev * dt * self.turn_efficiency), math.sin(-w_prev * dt * self.turn_efficiency)
                x, y = g.target[0] - v_prev * dt * self.forward_efficiency, g.target[1]
                g.target = np.array([c * x - s * y, s * x + c * y])
                self.track(g, now)
                # Never tracked yet (just seeded, or just within scan range): blind_timeout; once
                # tracked, a cluster gone for lost_timeout is a lost target.
                limit = self.lost_timeout if getattr(g, 'ever_tracked', False) else self.blind_timeout
                if not g.tracked and now - g.last_track > limit:
                    return self.finish(g, 'lost')
                rng = math.hypot(g.target[0] - self.camera_forward, g.target[1])
                if g.tracked and g.surface is not None:
                    # The cluster mean lies behind the facing surface: stopping on it left the
                    # robot 0.8 m from a fridge asked at 1.0 m.
                    rng = min(rng, g.surface)
                remaining = rng - req.stop_distance_m
                wanted = math.atan2(g.target[1], g.target[0])
                if remaining <= self.arrive_tolerance:
                    # At the distance: face the target before reporting, so that the final check
                    # of the vision model sees it centred (it arrived 13 deg off otherwise).
                    if abs(wanted) <= self.face_tolerance or not g.tracked:
                        return self.finish(g, 'arrived')
                    w = math.copysign(min(max_w, max(self.min_angular, self.turn_gain * abs(wanted))), wanted)
                    self.cmd = (0.0, w)
                    g.feedback.state = 'turning'
                    msg = Twist()
                    msg.angular.z = w
                    self.pub.publish(msg)
                    return
            else:
                remaining = req.distance_m - g.commanded
                wanted = wrap(math.radians(req.bearing_deg) - self.turned(g))
                if remaining <= 0.02 and abs(wanted) < math.radians(3.0):
                    return self.finish(g, 'done')
            heading, free, front = self.choose(wanted, max(0.0, remaining))
            g.feedback.bearing_deg = math.degrees(wanted)
            g.feedback.range_m = rng if target_mode else NAN
            g.feedback.front_free_m = front
            if heading is None:
                g.feedback.state = 'blocked'
                self.stop()
                g.blocked_since = g.blocked_since or now
                if now - g.blocked_since > self.blocked_timeout:
                    self.finish(g, 'blocked')
                return
            g.blocked_since = None
            v, w = self.command(heading, front, remaining, max_v, max_w)
            # Rate limits (no stop between goals: the ramp continues from the last command).
            v = v_prev + max(-self.linear_accel * dt, min(self.linear_accel * dt, v - v_prev))
            w = w_prev + max(-self.angular_accel * dt, min(self.angular_accel * dt, w - w_prev))
            self.cmd = (v, w)
            g.commanded += v * dt * self.forward_efficiency
            g.turned_rad = getattr(g, 'turned_rad', 0.0) + w * dt * self.turn_efficiency
            g.feedback.state = 'tracking' if (g.tracked or not target_mode) else ('far' if getattr(g, 'far', False) else 'searching_track')
            g.feedback.linear, g.feedback.angular = v, w
            msg = Twist()
            msg.linear.x, msg.angular.z = v, w
            self.pub.publish(msg)
            if self.stuck(g, now):
                self.finish(g, 'stuck')

    def turned(self, g):
        return getattr(g, 'turned_rad', 0.0)

    def track(self, g, now):
        """Re-measure the target: the cluster of scan points nearest to the predicted position.

        Association by distance to the prediction, not by range: picking the points nearest to the
        robot within an angular gate latched onto chairs in front of a fridge (tracked 1.3 m, true
        2.9 m). The gate grows with the range (vision distances are a few % off), and the estimate
        moves toward the measurement with a gain, so one stray point does not take it away.
        """
        pts = self.points
        g.tracked = False
        if not len(pts):
            return
        est_r = math.hypot(g.target[0], g.target[1])
        if est_r > self.track_max_range:
            g.last_track = now  # far: not lost, just not trackable yet
            g.far = True
            return
        if getattr(g, 'far', False):
            g.far = False
            g.last_track = now  # entering scan range: the blind time starts now
        d = np.hypot(pts[:, 0] - g.target[0], pts[:, 1] - g.target[1])
        gate = max(self.gate_range, self.gate_fraction * est_r)
        i = int(np.argmin(d))
        if d[i] > gate:
            return
        cluster = pts[np.hypot(pts[:, 0] - pts[i, 0], pts[:, 1] - pts[i, 1]) <= self.cluster_radius]
        measured = cluster.mean(axis=0)
        g.surface = float(np.min(np.hypot(cluster[:, 0] - self.camera_forward, cluster[:, 1])))
        g.target = g.target + self.track_gain * (measured - g.target)
        g.tracked = True
        g.ever_tracked = True
        g.last_track = now

    def choose(self, wanted, remaining):
        """Free heading closest to the wanted one: (heading, free along it, free ahead)."""
        pts = self.points
        headings = np.arange(-self.max_heading, self.max_heading + 1e-9, self.heading_step)

        def free_along(h):
            if not len(pts):
                return self.lookahead
            along = pts[:, 0] * math.cos(h) + pts[:, 1] * math.sin(h)
            lateral = -pts[:, 0] * math.sin(h) + pts[:, 1] * math.cos(h)
            hit = (along > 0) & (np.abs(lateral) <= self.half_width)
            return float(min(self.lookahead, along[hit].min())) if np.any(hit) else self.lookahead

        front = free_along(0.0)
        want = min(remaining, 1.5) + 0.3
        # The exact wanted heading first: with 5 deg candidates only, a -2.6 deg target was steered
        # at 0 / -5 deg alternately and the robot weaved.
        if abs(wanted) <= self.max_heading:
            f = free_along(wanted)
            if f >= max(self.stop_clearance + 0.1, want):
                return wanted, f, front
        best = None
        for h in headings:
            f = free_along(h)
            if f < self.stop_clearance + 0.1:
                continue
            cost = abs(wrap(h - wanted)) * 180 / math.pi + 100 * max(0.0, want - f)
            if best is None or cost < best[0]:
                best = (cost, h, f)
        if best is None:
            # Nothing ahead within +/-60 deg: turning in place toward the target is still fine
            # when it is behind the robot's sides.
            if abs(wanted) > self.max_heading:
                return wanted, 0.0, front
            return None, 0.0, front
        return best[1], best[2], front

    def command(self, heading, front, remaining, max_v, max_w):
        w = max(-max_w, min(max_w, self.turn_gain * heading))
        if remaining <= 0 or abs(heading) > self.turn_in_place or front <= self.stop_clearance:
            # Turning in place: at least min_angular, below it the sport mode may not turn at all.
            if 0 < abs(w) < self.min_angular and abs(heading) > math.radians(3.0):
                w = math.copysign(min(max_w, self.min_angular), w)
            return 0.0, w
        room = min(1.0, (front - self.stop_clearance) / self.slow_down)
        v = max_v * room * math.cos(heading) ** 2
        v = min(v, max(self.min_linear, math.sqrt(2.0 * self.brake_decel * max(0.0, remaining - self.arrive_tolerance))))
        return (min(max_v, max(self.min_linear, v)) if v > 0.02 else 0.0), w

    def stuck(self, g, now):
        """Commanded forward over a window, but the robot did not get closer to anything ahead.

        With the target tracked, progress is the decrease of its measured range; otherwise the median
        shortening of the scan ranges within +/-30 deg and 4 m (in open space only far or lateral
        beams are left and their median stays near 0 while the robot walks: a 1.7 m walk read as
        stuck), and two windows in a row without progress are needed there.
        """
        target_range = math.hypot(g.target[0], g.target[1]) if (g.target is not None and g.tracked) else None
        ref = g.progress_ref
        ahead = None if self.ranges_ahead is None else self.ranges_ahead.copy()
        if ref is None:
            g.progress_ref = (now, ahead, g.commanded, target_range)
            return False
        if now - ref[0] < self.stuck_window:
            return False
        g.progress_ref = (now, ahead, g.commanded, target_range)
        commanded = g.commanded - ref[2]
        if target_range is not None and ref[3] is not None:
            g.progress = ref[3] - target_range
            g.stalled = 0
            return commanded >= self.stuck_min_commanded and g.progress < self.stuck_max_progress
        before, after = ref[1], ahead
        if before is None or after is None or len(before) != len(after):
            return False
        both = np.isfinite(before) & np.isfinite(after) & (before <= 4.0) & (after <= 4.0)
        if np.sum(both) < 30:
            g.progress = NAN
            g.stalled = 0
            return False
        g.progress = float(np.median(before[both] - after[both]))
        no_progress = commanded >= self.stuck_min_commanded and -0.2 < g.progress < self.stuck_max_progress
        g.stalled = getattr(g, 'stalled', 0) + 1 if no_progress else 0
        return g.stalled >= 2


def main():
    rclpy.init()
    node = ReactiveDriveNode()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        node.stop()
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
