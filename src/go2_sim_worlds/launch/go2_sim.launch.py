"""Go2 (DottorCane) simulation in a selectable Gazebo environment.

    ros2 launch go2_sim_worlds go2_sim.launch.py world:=house
    ros2 launch go2_sim_worlds go2_sim.launch.py world:=ldc25 gui:=false
    ros2 launch go2_sim_worlds go2_sim.launch.py world:=house nav:=map
    ros2 launch go2_sim_worlds go2_sim.launch.py world:=house nav:=slam

Environments are listed in config/environments.yaml. The robot stack (CHAMP,
ZED cameras, bridge, ros_gz_republish) and the ROS topics are the same in
every world, so AgenticROS works without changes. Based on
ldc25-sim/launch/ldc25_dottorcane.launch.py.

nav:=map also starts Nav2 on the world map, nav:=slam Nav2 on a map built live
by slam_toolbox, with frontier exploration (launch/go2_nav.launch.py). The
odometry then comes from ground_truth_odom (odom = Gazebo world frame) and AMCL
or SLAM publishes map -> odom, so the static map -> odom transform and the TF of
ros_gz_republish are left out.
"""

import math
import os
from pathlib import Path

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    AppendEnvironmentVariable,
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    LogInfo,
    OpaqueFunction,
)
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import ComposableNodeContainer, Node
from launch_ros.descriptions import ComposableNode
from launch_ros.parameter_descriptions import ParameterFile

PACKAGE = 'go2_sim_worlds'
# Height of dottorcane/odom above the ground, as in the LDC25 launch.
ODOM_Z = 0.22
CAMERA_TOPIC = '/dottorcane/slam/zed_x_driver/left/image_rect_color'


def default_assets_path():
    if 'GO2_SIM_ASSETS_PATH' in os.environ:
        return os.environ['GO2_SIM_ASSETS_PATH']
    # Isolated colcon install: <workspace>/install/<pkg>/share/<pkg>
    share = Path(get_package_share_directory(PACKAGE))
    return str(share.parents[3] / 'config' / 'gazebo')


def load_environments():
    path = os.path.join(
        get_package_share_directory(PACKAGE), 'config', 'environments.yaml')
    with open(path, 'r') as f:
        return yaml.safe_load(f)


def launch_setup(context):
    environments = load_environments()
    name = LaunchConfiguration('world').perform(context)
    if name not in environments:
        raise RuntimeError(
            f"Unknown world '{name}'. Available: {', '.join(environments)}")
    env = environments[name]

    def spawn_value(key):
        value = LaunchConfiguration(key).perform(context)
        return float(value) if value else float(env['spawn'].get(key, 0.0))

    x, y, z, yaw = (spawn_value(k) for k in ('x', 'y', 'z', 'yaw'))

    nav = LaunchConfiguration('nav').perform(context)
    if nav not in ('none', 'map', 'slam'):
        raise RuntimeError(f"Unknown nav mode '{nav}'. Available: none, map, slam")
    if nav == 'map' and 'map' not in env:
        raise RuntimeError(f"World '{name}' has no map: nav:=map is not available")

    world_path = os.path.join(
        get_package_share_directory(env['package']), env['world'])

    actions = [LogInfo(msg=f"[go2_sim] world '{name}': {env['description']}")]

    # Gazebo model directories of this environment
    assets_path = LaunchConfiguration('assets_path').perform(context)
    model_dirs = [
        os.path.join(assets_path, p) for p in env.get('resource_paths', [])]
    found = [d for d in model_dirs if os.path.isdir(d)]
    if not found:
        actions.append(LogInfo(
            msg=f"[go2_sim] WARNING: no models for '{name}' in "
                f"{', '.join(model_dirs)}. {env.get('setup', '')}"))
    for d in found:
        actions.append(AppendEnvironmentVariable('GZ_SIM_RESOURCE_PATH', d))

    # model://go2_description/... must start from the directory containing
    # go2_description. Each package has its own prefix in an isolated colcon
    # install, so the dottorcane prefix cannot resolve the Go2 meshes.
    pkg_dottorcane_description = get_package_share_directory(
        'dottorcane_description')
    pkg_go2_description = get_package_share_directory('go2_description')
    pkg_zed_description = get_package_share_directory('zed_description')
    for resource_root in (
            os.path.dirname(pkg_dottorcane_description),
            os.path.dirname(pkg_go2_description),
            os.path.join(pkg_zed_description, 'models')):
        actions.append(
            AppendEnvironmentVariable('GZ_SIM_RESOURCE_PATH', resource_root))

    ros_gz_sim_dir = get_package_share_directory('ros_gz_sim')
    gz_sim_launch = os.path.join(ros_gz_sim_dir, 'launch', 'gz_sim.launch.py')

    # Gazebo server
    actions.append(IncludeLaunchDescription(
        PythonLaunchDescriptionSource(gz_sim_launch),
        launch_arguments={
            'gz_args': f'-r -s -v{LaunchConfiguration("verbosity").perform(context)} {world_path}',
            'on_exit_shutdown': 'true',
        }.items()))

    # Gazebo client
    actions.append(IncludeLaunchDescription(
        PythonLaunchDescriptionSource(gz_sim_launch),
        condition=IfCondition(LaunchConfiguration('gui')),
        launch_arguments={'gz_args': '-g -v4 '}.items()))

    urdf_file_dottorcane = os.path.join(
        pkg_dottorcane_description, 'urdf', 'dottorcane.urdf')
    sdf_file_dottorcane = os.path.join(
        pkg_dottorcane_description, 'urdf', 'model.sdf')
    with open(urdf_file_dottorcane, 'r') as infp:
        robot_desc_dottorcane = infp.read()

    ros_gz_bridge_config = os.path.join(
        get_package_share_directory(PACKAGE), 'config', 'go2_bridge.yaml')

    actions.append(ComposableNodeContainer(
        name='container',
        namespace='',
        package='dua_app_management',
        executable='dua_component_container_mt',
        emulate_tty=True,
        output='both',
        log_cmd=True,
        composable_node_descriptions=[
            # Bridge ROS topics and Gazebo messages
            ComposableNode(
                package='ros_gz_bridge',
                plugin='ros_gz_bridge::RosGzBridge',
                name='ros_gz_bridge',
                parameters=[{
                    'use_sim_time': True,
                    'config_file': ros_gz_bridge_config,
                    'qos_overrides./tf_static.publisher.durability': 'transient_local',
                }]),
            # JPEG copy of the ZED left camera for viewers (rqt_image_view):
            # the raw 1920x1080 frames are ~6 MB each and too heavy to display
            # live. Agents keep using the raw topic at full quality.
            ComposableNode(
                package='image_transport',
                plugin='image_transport::Republisher',
                name='zed_left_compressed_republisher',
                parameters=[{
                    'use_sim_time': True,
                    'in_transport': 'raw',
                    'out_transport': 'compressed',
                    'out.compressed.jpeg_quality': 80,
                }],
                remappings=[
                    ('in', CAMERA_TOPIC),
                    ('out/compressed', CAMERA_TOPIC + '/compressed'),
                ]),
            # Robot State Publisher for DottorCane
            ComposableNode(
                package='robot_state_publisher',
                plugin='robot_state_publisher::RobotStatePublisher',
                name='robot_state_publisher_dottorcane',
                parameters=[
                    {'use_sim_time': True},
                    {'robot_description': robot_desc_dottorcane},
                    {'publish_frequency': 200.0},
                    {'frame_prefix': 'dottorcane/'},
                ],
                remappings=[('/joint_states', '/dottorcane/joint_states')]),
        ] + ([] if nav != 'none' else [
            # Static transform: map -> dottorcane/odom at the spawn pose
            # (with nav:=map|slam, AMCL or SLAM publishes it).
            ComposableNode(
                package='tf2_ros',
                plugin='tf2_ros::StaticTransformBroadcasterNode',
                name='map_to_dottorcane_odom_broadcaster',
                parameters=[{
                    'frame_id': 'map',
                    'child_frame_id': 'dottorcane/odom',
                    'translation.x': x,
                    'translation.y': y,
                    'translation.z': ODOM_Z,
                    'rotation.x': 0.0,
                    'rotation.y': 0.0,
                    'rotation.z': math.sin(yaw / 2.0),
                    'rotation.w': math.cos(yaw / 2.0),
                    'use_sim_time': True,
                }]),
        ])))

    # CHAMP locomotion controller
    champ_dir = get_package_share_directory('champ_config')

    def champ_param(kind):
        return ParameterFile(
            param_file=os.path.join(
                champ_dir, 'config', kind, f'dottorcane_{kind}.yaml'),
            allow_substs=True)

    actions.append(Node(
        package='champ_base',
        executable='quadruped_controller_node',
        output='screen',
        parameters=[
            {'use_sim_time': True},
            {'gazebo': True},
            {'publish_joint_states': False},
            {'publish_foot_contacts': False},
            {'publish_joint_control': True},
            {'joint_controller_topic': '/dottorcane/joint_trajectory'},
            {'urdf': urdf_file_dottorcane},
            champ_param('links'),
            champ_param('joints'),
            champ_param('gait'),
        ],
        remappings=[('/cmd_vel/smooth', '/dottorcane/go2_control/cmd_vel')]))

    # Spawn the robot
    actions.append(Node(
        package='ros_gz_sim',
        executable='create',
        arguments=[
            '-name', 'dottorcane',
            '-file', sdf_file_dottorcane,
            '-x', str(x), '-y', str(y), '-z', str(z),
            '-R', '0.0', '-P', '0.0', '-Y', str(yaw),
        ],
        output='screen'))

    # Gazebo -> ROS 2 republisher
    actions.append(Node(
        package='ros_gz_republish',
        executable='ros_gz_republish',
        name='ros_gz_republish',
        namespace='',
        emulate_tty=True,
        shell=False,
        output='both',
        log_cmd=True,
        parameters=[os.path.join(
            get_package_share_directory('ros_gz_republish'),
            'config', 'ros_gz_republish.yaml')] + (
            # Nav2 takes odom -> base_link from ground_truth_odom instead.
            [{'publishers.pose.tf.publish': [False]}] if nav != 'none' else [])))

    if nav != 'none':
        actions.append(IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(
                get_package_share_directory(PACKAGE), 'launch', 'go2_nav.launch.py')),
            launch_arguments={
                'mode': nav,
                'map': os.path.join(get_package_share_directory(PACKAGE), env['map'])
                if nav == 'map' else '',
                'x': str(x),
                'y': str(y),
                'yaw': str(yaw),
            }.items()))

    return actions


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'world', default_value='ldc25',
            description='Environment name from config/environments.yaml'),
        DeclareLaunchArgument(
            'gui', default_value='true',
            description='Start the Gazebo graphical client'),
        DeclareLaunchArgument(
            'assets_path', default_value=default_assets_path(),
            description='Directory with the untracked Gazebo assets '
                        '(env GO2_SIM_ASSETS_PATH)'),
        DeclareLaunchArgument(
            'verbosity', default_value='3',
            description='Gazebo server verbosity (0-4)'),
        DeclareLaunchArgument(
            'x', default_value='', description='Spawn x override [m]'),
        DeclareLaunchArgument(
            'y', default_value='', description='Spawn y override [m]'),
        DeclareLaunchArgument(
            'z', default_value='', description='Spawn drop height override [m]'),
        DeclareLaunchArgument(
            'yaw', default_value='', description='Spawn yaw override [rad]'),
        DeclareLaunchArgument(
            'nav', default_value='none',
            description='Navigation: none, map (Nav2 + AMCL on the world map) '
                        'or slam (Nav2 + slam_toolbox, no prior map, frontier exploration)'),
        OpaqueFunction(function=launch_setup),
    ])
