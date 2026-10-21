"""Nav2 for the Go2 (DottorCane) simulation.

Included by `go2_sim.launch.py nav:=map|slam`, which also hands the
odom -> base_link transform to this launch (ros_gz_republish stops publishing
it) and drops the static map -> odom transform (AMCL or SLAM publishes it).

Started here:
  - ground_truth_odom: /map + odom -> base_link from the Gazebo pose;
  - depthimage_to_laserscan: /dottorcane/scan from the ZED depth image (no lidar),
    a single plane at camera height, for AMCL / SLAM;
  - depth_obstacle_scan: /dottorcane/scan_obstacles from the whole depth image,
    everything 6-70 cm above the floor (bed frames, chair legs, a barbell rack the
    single plane misses), for the costmaps and the collision monitor;
  - mode map: map_server + AMCL on the world map (config/environments.yaml, `map`);
  - mode slam: slam_toolbox builds /map live (no prior map) and agenticros_explore
    offers the `explore` action (frontier exploration through Nav2);
  - Nav2: planner, controller, behaviors, BT navigator, velocity smoother and
    collision monitor, which writes /dottorcane/go2_control/cmd_vel.

Send goals to the `navigate_to_pose` action in the `map` frame (for AgenticROS:
ros2_navigate_to_place with the places of config/places/<world>.json).
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

PACKAGE = 'go2_sim_worlds'

DEPTH_TOPIC = '/dottorcane/slam/zed_x_driver/depth_distances'
DEPTH_INFO_TOPIC = '/dottorcane/slam/zed_x_driver/depth_camera_info'
SCAN_TOPIC = '/dottorcane/scan'
OBSTACLE_SCAN_TOPIC = '/dottorcane/scan_obstacles'
ODOM_TOPIC = '/map'
# Frame of the ZED depth sensor in Gazebo: x forward, level with the body.
SCAN_FRAME = 'dottorcane/zedx_link'

# The DUA underlay ships BehaviorTree.CPP 4.9 and comes first in LD_LIBRARY_PATH,
# but the Nav2 binaries are built against the 4.10 of /opt/ros/jazzy: loading the
# older one leaves the BT navigator plugins with undefined symbols. Nav2 processes
# therefore resolve the Jazzy libraries first.
NAV2_ENV = {'LD_LIBRARY_PATH': ':'.join(
    p for p in ['/opt/ros/jazzy/lib', os.environ.get('LD_LIBRARY_PATH', '')] if p)}

NAVIGATION_NODES = [
    ('nav2_controller', 'controller_server', [('cmd_vel', 'cmd_vel_nav')]),
    ('nav2_planner', 'planner_server', []),
    ('nav2_behaviors', 'behavior_server', [('cmd_vel', 'cmd_vel_nav')]),
    ('nav2_bt_navigator', 'bt_navigator', []),
    ('nav2_velocity_smoother', 'velocity_smoother', [('cmd_vel', 'cmd_vel_nav')]),
    ('nav2_collision_monitor', 'collision_monitor', []),
]


def localization_on_map(params, common, map_yaml, x, y, yaw):
    if not os.path.isfile(map_yaml):
        raise RuntimeError(f"[go2_nav] map file not found: '{map_yaml}'")
    return [
        Node(
            package='nav2_map_server',
            executable='map_server',
            name='map_server',
            output='screen',
            additional_env=NAV2_ENV,
            parameters=[params, common, {'yaml_filename': map_yaml}]),
        Node(
            package='nav2_amcl',
            executable='amcl',
            name='amcl',
            output='screen',
            additional_env=NAV2_ENV,
            parameters=[params, common, {
                'initial_pose.x': x,
                'initial_pose.y': y,
                'initial_pose.z': 0.0,
                'initial_pose.yaw': yaw,
            }]),
        Node(
            package='nav2_lifecycle_manager',
            executable='lifecycle_manager',
            name='lifecycle_manager_localization',
            output='screen',
            additional_env=NAV2_ENV,
            parameters=[params, common]),
    ]


def mapping_with_slam(common):
    share = get_package_share_directory(PACKAGE)
    return [
        # Builds /map from the scan and publishes map -> odom.
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(
                get_package_share_directory('slam_toolbox'), 'launch', 'online_async_launch.py')),
            launch_arguments={
                'slam_params_file': os.path.join(share, 'config', 'slam_toolbox_go2.yaml'),
                'use_sim_time': 'true',
            }.items()),
        # `explore` / `wander` actions: frontier goals sent to Nav2.
        Node(
            package='agenticros_explore',
            executable='explore_node',
            name='agenticros_explore',
            output='screen',
            parameters=[common, {
                'map_topic': 'map',
                'navigate_action': 'navigate_to_pose',
                'map_frame': 'map',
                'base_frame': 'dottorcane/base_link',
                'base_frame_fallback': 'dottorcane/base_link',
                # The nearest frontier is usually reached in 15-40 s; past ~75 s the
                # robot is stuck in clutter and recoveries only waste time.
                'goal_timeout_s': 75.0,
                'min_frontier_m': 0.5,
            }]),
    ]


def launch_setup(context):
    params = LaunchConfiguration('params_file').perform(context)
    mode = LaunchConfiguration('mode').perform(context)
    x, y, yaw = (float(LaunchConfiguration(k).perform(context)) for k in ('x', 'y', 'yaw'))
    if mode not in ('map', 'slam'):
        raise RuntimeError(f"[go2_nav] unknown mode '{mode}': use map or slam")

    common = {'use_sim_time': True}
    actions = [
        Node(
            package=PACKAGE,
            executable='ground_truth_odom.py',
            name='ground_truth_odom',
            output='screen',
            parameters=[common],
            remappings=[('pose', '/gz/dottorcane/pose'), ('odom', ODOM_TOPIC)]),
        Node(
            package='depthimage_to_laserscan',
            executable='depthimage_to_laserscan_node',
            name='depth_to_scan',
            output='screen',
            parameters=[common, {
                'output_frame': SCAN_FRAME,
                'range_min': 0.15,
                'range_max': 8.0,
                # Rows around the image centre merged into the scan (closest return wins).
                'scan_height': 10,
                'scan_time': 0.2,
            }],
            remappings=[
                ('depth', DEPTH_TOPIC),
                ('depth_camera_info', DEPTH_INFO_TOPIC),
                ('scan', SCAN_TOPIC),
            ]),
        Node(
            package=PACKAGE,
            executable='depth_obstacle_scan.py',
            name='depth_obstacle_scan',
            output='screen',
            parameters=[common, {
                # Heights above the floor, measured in the floor-level base_ground frame.
                'min_height': 0.06,
                'max_height': 0.7,
                'range_min': 0.4,
                'range_max': 4.0,
            }],
            remappings=[
                ('depth', DEPTH_TOPIC),
                ('depth_camera_info', DEPTH_INFO_TOPIC),
                ('scan', OBSTACLE_SCAN_TOPIC),
            ]),
    ]
    if mode == 'map':
        actions += localization_on_map(
            params, common, LaunchConfiguration('map').perform(context), x, y, yaw)
    else:
        actions += mapping_with_slam(common)
    # With SLAM the global costmap (in planner_server) rolls with the robot.
    slam_overrides = os.path.join(
        get_package_share_directory(PACKAGE), 'config', 'nav2_go2_slam.yaml')
    for package, executable, remappings in NAVIGATION_NODES:
        node_params = [params, common]
        if mode == 'slam' and executable == 'planner_server':
            node_params.append(slam_overrides)
        actions.append(Node(
            package=package,
            executable=executable,
            name=executable,
            output='screen',
            additional_env=NAV2_ENV,
            parameters=node_params,
            remappings=remappings))
    actions.append(Node(
        package='nav2_lifecycle_manager',
        executable='lifecycle_manager',
        name='lifecycle_manager_navigation',
        output='screen',
        additional_env=NAV2_ENV,
        parameters=[params, common]))
    return actions


def generate_launch_description():
    share = get_package_share_directory(PACKAGE)
    return LaunchDescription([
        DeclareLaunchArgument(
            'mode', default_value='map',
            description='map: AMCL on a known map; slam: build the map live (slam_toolbox)'),
        DeclareLaunchArgument(
            'map', default_value='', description='Map yaml (nav2_map_server format), mode map'),
        DeclareLaunchArgument(
            'params_file', default_value=os.path.join(share, 'config', 'nav2_go2.yaml'),
            description='Nav2 parameters'),
        DeclareLaunchArgument('x', default_value='0.0', description='Initial pose x in the map [m]'),
        DeclareLaunchArgument('y', default_value='0.0', description='Initial pose y in the map [m]'),
        DeclareLaunchArgument('yaw', default_value='0.0', description='Initial pose yaw in the map [rad]'),
        OpaqueFunction(function=launch_setup),
    ])
