"""Go2 (DottorCane) simulation in Gazebo Harmonic that looks like the real robot.

    ros2 launch go2_sim go2_sim.launch.py world:=house gui:=false

The simulated robot looks like the real DottorCane (dottorcane repo, branch slam,
plus go2_real.launch.py) to everything above the simulator:
  - sensors: Go2 front camera /dottorcane/go2_control/frontvideo/{image_rect_color,
    camera_info} (1280x720, HFOV 94.7 deg, frame dottorcane/front_camera_link),
    Livox Mid-360 /dottorcane/sensors/livox_lidar_driver/point_cloud (and
    .../point_cloud/deskewed, reduced for the Nav2 costmaps by go2_real) at the pose of the
    real one (30 deg pitch), IMU /dottorcane/go2_control/imu; no depth camera;
  - localization: /dottorcane/slam/ekf_global/odometry and map -> dottorcane/base_link,
    with map at the start pose on the floor (the Gazebo pose stands in for EKF +
    LIO-SAM; the agent never reads /gz/dottorcane/pose);
  - go2_real.launch.py: depth from the lidar (/dottorcane/agent/depth), the
    obstacle scan (/dottorcane/agent/scan_obstacles) and the cloud of the Nav2
    costmaps (/dottorcane/agent/nav_cloud);
  - rmw_zenoh_cpp: start a router on this machine first (`zenohd`, port 7447),
    or pass zenoh_router:=true.
Nav2 and explore run as on the robot (go2_real_nav.launch.py use_sim_time:=true).
Environments are listed in config/environments.yaml; the locomotion is CHAMP.
"""

import math
import os
from pathlib import Path

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    AppendEnvironmentVariable,
    ExecuteProcess,
    SetEnvironmentVariable,
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

PACKAGE = 'go2_sim'

# Sensors and frames of the real DottorCane (dottorcane_slam.urdf).
REAL_CAMERA_TOPIC = '/dottorcane/go2_control/frontvideo/image_rect_color'
REAL_CAMERA_FRAME = 'dottorcane/front_camera_link'
REAL_LIDAR_FRAME = 'dottorcane/livox_mid360_link'
# base_link -> sensor: xyz [m], rpy [rad]
REAL_LIDAR_POSE = ((0.273, 0.0, 0.141), (0.0, math.radians(30.0), 0.0))
REAL_CAMERA_POSE = ((0.33, 0.0, 0.04), (0.0, 0.0, 0.0))
# The camera frame of the real robot uses the optical convention (z forward).
REAL_CAMERA_OPTICAL_RPY = (-math.pi / 2.0, 0.0, -math.pi / 2.0)
REAL_CAMERA_HFOV_DEG = 94.7
# Standing base height of the simulated Go2 (CHAMP), lower than the real one (0.34 m).
SIM_BASE_HEIGHT = 0.22
# Sensors of the DottorCane model (ZED X) that the real robot does not have.
ZED_SENSORS = ('left_camera', 'right_camera', 'zedx_depth', 'zedx_imu',
               'zedx_left_camera', 'zedx_right_camera')


def default_assets_path():
    if 'GO2_SIM_ASSETS_PATH' in os.environ:
        return os.environ['GO2_SIM_ASSETS_PATH']
    # Isolated colcon install: <workspace>/install/<pkg>/share/<pkg>
    share = Path(get_package_share_directory(PACKAGE))
    return str(share.parents[3] / 'config' / 'gazebo')


def quaternion_from_rpy(roll, pitch, yaw):
    cr, sr = math.cos(roll / 2.0), math.sin(roll / 2.0)
    cp, sp = math.cos(pitch / 2.0), math.sin(pitch / 2.0)
    cy, sy = math.cos(yaw / 2.0), math.sin(yaw / 2.0)
    return (sr * cp * cy - cr * sp * sy,  # x
            cr * sp * cy + sr * cp * sy,  # y
            cr * cp * sy - sr * sp * cy,  # z
            cr * cp * cy + sr * sp * sy)  # w


def pose_text(xyz, rpy):
    return ' '.join(f'{v:.6f}' for v in (*xyz, *rpy))


def real_robot_sdf(src):
    """Copy of the DottorCane SDF with the sensors of the real robot."""
    import tempfile
    import xml.etree.ElementTree as ET

    tree = ET.parse(src)
    model = tree.getroot().find('model')
    for link in model.findall('link'):
        for sensor in link.findall('sensor'):
            if sensor.get('name') in ZED_SENSORS:
                link.remove(sensor)
    base = next(link for link in model.findall('link') if link.get('name') == 'base_link')
    imu = next(s for s in base.findall('sensor') if s.get('type') == 'imu')
    imu.find('topic').text = 'dottorcane/go2_control/imu'
    ET.SubElement(imu, 'gz_frame_id').text = 'dottorcane/imu'

    hfov = math.radians(REAL_CAMERA_HFOV_DEG)
    base.append(ET.fromstring(f"""
      <sensor name='front_camera' type='camera'>
        <pose>{pose_text(*REAL_CAMERA_POSE)}</pose>
        <always_on>true</always_on>
        <update_rate>10</update_rate>
        <topic>dottorcane/go2_control/frontvideo/image_rect_color</topic>
        <camera>
          <horizontal_fov>{hfov:.6f}</horizontal_fov>
          <image><width>1280</width><height>720</height></image>
          <clip><near>0.1</near><far>25</far></clip>
        </camera>
        <gz_frame_id>{REAL_CAMERA_FRAME}</gz_frame_id>
      </sensor>"""))
    # Mid-360: 360 deg horizontally, -7..52 deg vertically, 0.1-40 m, 10 Hz
    # (~115k points/s here, 200k on the real one; non-repetitive pattern not modelled).
    base.append(ET.fromstring(f"""
      <sensor name='livox_mid360' type='gpu_lidar'>
        <pose>{pose_text(*REAL_LIDAR_POSE)}</pose>
        <always_on>true</always_on>
        <update_rate>10</update_rate>
        <topic>dottorcane/sensors/livox_lidar_driver/scan</topic>
        <lidar>
          <scan>
            <horizontal><samples>360</samples><resolution>1</resolution>
              <min_angle>{-math.pi:.6f}</min_angle><max_angle>{math.pi:.6f}</max_angle></horizontal>
            <vertical><samples>32</samples><resolution>1</resolution>
              <min_angle>{math.radians(-7.0):.6f}</min_angle><max_angle>{math.radians(52.0):.6f}</max_angle></vertical>
          </scan>
          <range><min>0.1</min><max>40.0</max><resolution>0.01</resolution></range>
          <noise><type>gaussian</type><mean>0.0</mean><stddev>0.02</stddev></noise>
        </lidar>
        <gz_frame_id>{REAL_LIDAR_FRAME}</gz_frame_id>
      </sensor>"""))
    for plugin in model.findall('plugin'):
        if plugin.get('filename') == 'gz-sim-pose-publisher-system':
            plugin.find('update_frequency').text = '50'

    out = tempfile.NamedTemporaryFile('wb', prefix='dottorcane_real_', suffix='.sdf', delete=False)
    with out:
        tree.write(out, xml_declaration=True, encoding='utf-8')
    return out.name


def static_tf(name, parent, child, xyz, rpy):
    qx, qy, qz, qw = quaternion_from_rpy(*rpy)
    return ComposableNode(
        package='tf2_ros',
        plugin='tf2_ros::StaticTransformBroadcasterNode',
        name=name,
        parameters=[{
            'frame_id': parent,
            'child_frame_id': child,
            'translation.x': xyz[0],
            'translation.y': xyz[1],
            'translation.z': xyz[2],
            'rotation.x': qx,
            'rotation.y': qy,
            'rotation.z': qz,
            'rotation.w': qw,
            'use_sim_time': True,
        }])


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

    world_path = os.path.join(
        get_package_share_directory(env['package']), env['world'])

    actions = [LogInfo(msg=f"[go2_sim] world '{name}': {env['description']}")]
    # Like the DottorCane stack: rmw_zenoh_cpp. The router (one per host) is
    # started before the simulation (zenohd), or here with zenoh_router:=true.
    actions.append(SetEnvironmentVariable('RMW_IMPLEMENTATION', 'rmw_zenoh_cpp'))
    # The launch process itself loads the composable nodes into the container
    # (load_node service), with the middleware it was started with.
    if os.environ.get('RMW_IMPLEMENTATION') != 'rmw_zenoh_cpp':
        raise RuntimeError(
            "the simulation runs on rmw_zenoh_cpp like the robot: start the launch with "
            "RMW_IMPLEMENTATION=rmw_zenoh_cpp (e.g. after `sim_zenoh`)")
    if LaunchConfiguration('zenoh_router').perform(context).lower() == 'true':
        actions.append(ExecuteProcess(
            cmd=['ros2', 'run', 'rmw_zenoh_cpp', 'rmw_zenohd'], name='zenoh_router', output='log'))

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
    for resource_root in (
            os.path.dirname(pkg_dottorcane_description),
            os.path.dirname(pkg_go2_description)):
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
    sdf_file_dottorcane = real_robot_sdf(os.path.join(
        pkg_dottorcane_description, 'urdf', 'model.sdf'))
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
            # JPEG copy of the front camera for viewers (rqt_image_view): the
            # raw frames are too heavy to display live. Agents keep using the
            # raw topic at full quality.
            ComposableNode(
                package='image_transport',
                plugin='image_transport::Republisher',
                name='front_camera_compressed_republisher',
                parameters=[{
                    'use_sim_time': True,
                    'in_transport': 'raw',
                    'out_transport': 'compressed',
                    'out.compressed.jpeg_quality': 80,
                }],
                remappings=[
                    ('in', REAL_CAMERA_TOPIC),
                    ('out/compressed', REAL_CAMERA_TOPIC + '/compressed'),
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
            # Sensor frames of the real robot, missing from the simulation URDF.
            static_tf('livox_mid360_tf', 'dottorcane/base_link', REAL_LIDAR_FRAME,
                      REAL_LIDAR_POSE[0], REAL_LIDAR_POSE[1]),
            static_tf('front_camera_tf', 'dottorcane/base_link', REAL_CAMERA_FRAME,
                      REAL_CAMERA_POSE[0], REAL_CAMERA_OPTICAL_RPY),
        ]))

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

    # The map frame below starts here: places saved by the agent in a previous run
    # (scripts/run_nebius_agent.sh, logs/places_session.json) no longer hold.
    places = Path(get_package_share_directory(PACKAGE)).parents[3] / 'logs' / 'places_session.json'
    if places.exists():
        places.unlink()
        actions.append(LogInfo(msg=f'[go2_sim] removed the places of the previous session ({places})'))
    # Stand-in for EKF + LIO-SAM: /dottorcane/slam/ekf_global/odometry and
    # map -> dottorcane/base_link, map at the start pose on the floor.
    actions.append(Node(
        package=PACKAGE,
        executable='ground_truth_odom.py',
        name='ekf_global',
        namespace='dottorcane/slam',
        output='screen',
        parameters=[{
            'use_sim_time': True,
            'odom_frame': 'map',
            'publish_ground': False,
            'origin_x': x,
            'origin_y': y,
            'origin_z': 0.0,
            'origin_yaw': yaw,
        }],
        remappings=[('pose', '/gz/dottorcane/pose'), ('odom', 'ekf_global/odometry')]))
    # Lidar depth and obstacle scan, as on the Jetson.
    actions.append(IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(
            get_package_share_directory('go2_real'), 'launch', 'go2_real.launch.py')),
        launch_arguments={
            'use_sim_time': 'true',
            'base_height': str(SIM_BASE_HEIGHT),
        }.items()))
    return actions


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'world', default_value='house',
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
            'zenoh_router', default_value='false',
            description='Also start a zenoh router (rmw_zenohd); '
                        'by default one must already run on this host'),
        OpaqueFunction(function=launch_setup),
    ])
