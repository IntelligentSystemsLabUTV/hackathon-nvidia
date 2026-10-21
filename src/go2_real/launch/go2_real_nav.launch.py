"""Nav2 for the real Go2 (DottorCane), on a workstation, without a prior map.

    ros2 launch go2_real go2_real_nav.launch.py robot:=<host or IP>
    ros2 launch go2_real go2_real_nav.launch.py robot:=<IP> map_topic:=<OccupancyGrid>
    ros2 launch go2_real go2_real_nav.launch.py nav2:=dua      # explore only, on the DUA Nav2

The Jetson has no Nav2 (JetPack 6): this runs in the x86 container and talks to
the robot's zenoh router as a client, like rviz.launch.py. On the Jetson, before:
the DottorCane bringup (dottorcane_slam.launch.py: LIO-SAM map -> dottorcane/odom,
EKF odometry) and go2_real.launch.py, which publishes the obstacle scan
/dottorcane/agent/scan_obstacles from the Mid-360.

Started here:
  - Nav2: planner, controller, behaviors, BT navigator, velocity smoother and
    collision monitor, which writes /dottorcane/go2_control/cmd_vel (arm first);
  - agenticros_explore: the `explore` action (frontier goals sent to Nav2) on the
    global costmap, or on map_topic when given.

nav2:=dua starts only agenticros_explore, on the DUA Nav2 already running here
(namespace /dottorcane/dua_nav2: its global costmap and navigate_to_pose); a
second Nav2 would fight it over the cmd_vel. map_frame must be the frame of that
costmap.

The AgenticROS agent on the Jetson finds navigate_to_pose and explore on the ROS
graph by itself. Nodes use wall-clock time: the clocks of the Jetson and of this
machine must agree (chrony/NTP), or TF lookups fail.
"""

import os
import tempfile

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction, SetEnvironmentVariable
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

PACKAGE = 'go2_real'
DUA_NAV2 = '/dottorcane/dua_nav2'

# The DUA underlay ships BehaviorTree.CPP 4.9 before the 4.10 of /opt/ros/jazzy
# that Nav2 is built against (see go2_sim_worlds/launch/go2_nav.launch.py).
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


def static_map_overrides(map_topic):
    """Global costmap with the SLAM OccupancyGrid as static layer, still rolling."""
    overrides = {'global_costmap': {'global_costmap': {'ros__parameters': {
        'plugins': ['static_layer', 'obstacle_layer', 'inflation_layer'],
        'static_layer': {
            'plugin': 'nav2_costmap_2d::StaticLayer',
            'map_topic': map_topic,
            'map_subscribe_transient_local': True,
        },
    }}}}
    tmp = tempfile.NamedTemporaryFile('w', prefix='go2_real_nav_', suffix='.yaml', delete=False)
    with tmp:
        yaml.safe_dump(overrides, tmp)
    return tmp.name


def launch_setup(context):
    actions = [SetEnvironmentVariable('RMW_IMPLEMENTATION', 'rmw_zenoh_cpp')]
    robot = LaunchConfiguration('robot').perform(context)
    if robot:
        endpoint = robot if '/' in robot else f'tcp/{robot}:7447'
        actions.append(SetEnvironmentVariable(
            'ZENOH_CONFIG_OVERRIDE',
            f'mode="client";connect/endpoints=["{endpoint}"];scouting/multicast/enabled=false'))

    params = LaunchConfiguration('params_file').perform(context)
    map_topic = LaunchConfiguration('map_topic').perform(context)
    nav2 = LaunchConfiguration('nav2').perform(context)
    if nav2 not in ('own', 'dua'):
        raise RuntimeError(f"[go2_real_nav] unknown nav2 '{nav2}': use own or dua")
    common = {'use_sim_time': False}
    if nav2 == 'dua':
        navigate_action = f'{DUA_NAV2}/navigate_to_pose'
        explore_map = map_topic or f'{DUA_NAV2}/global_costmap/costmap'
    else:
        navigate_action = 'navigate_to_pose'
        explore_map = map_topic or '/global_costmap/costmap'
        for package, executable, remappings in NAVIGATION_NODES:
            node_params = [params, common]
            if map_topic and executable == 'planner_server':
                node_params.append(static_map_overrides(map_topic))
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

    if LaunchConfiguration('explore').perform(context).lower() == 'true':
        actions.append(Node(
            package='agenticros_explore',
            executable='explore_node',
            name='agenticros_explore',
            output='screen',
            parameters=[common, {
                # The global costmap is an OccupancyGrid too: free, occupied (inflated
                # cells included) and unknown where the lidar has not looked yet.
                'map_topic': explore_map,
                'navigate_action': navigate_action,
                'map_frame': LaunchConfiguration('map_frame').perform(context),
                'base_frame': 'dottorcane/base_link',
                'base_frame_fallback': 'dottorcane/base_link',
                'goal_timeout_s': 75.0,
                'min_frontier_m': 0.5,
            }]))
    return actions


def generate_launch_description():
    share = get_package_share_directory(PACKAGE)
    return LaunchDescription([
        DeclareLaunchArgument(
            'robot', default_value='',
            description='Zenoh router of the robot: host, IP or endpoint like tcp/<ip>:7447 '
                        '(empty: the local router)'),
        DeclareLaunchArgument(
            'nav2', default_value='own',
            description='own: start Nav2 here; dua: use the DUA Nav2 already running '
                        f'({DUA_NAV2}) and start only explore'),
        DeclareLaunchArgument(
            'map_topic', default_value='',
            description='nav_msgs/OccupancyGrid of the SLAM, as static layer (nav2:=own) and for '
                        'explore (empty: the global costmap)'),
        DeclareLaunchArgument(
            'map_frame', default_value='map',
            description='Frame of the map explore reads (header.frame_id of the costmap)'),
        DeclareLaunchArgument(
            'explore', default_value='true',
            description='Start agenticros_explore (the explore action)'),
        DeclareLaunchArgument(
            'params_file', default_value=os.path.join(share, 'config', 'nav2_go2_real.yaml'),
            description='Nav2 parameters'),
        OpaqueFunction(function=launch_setup),
    ])
