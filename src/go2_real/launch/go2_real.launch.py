"""AgenticROS side of the real Go2 (DottorCane), next to the dottorcane stack.

    ros2 launch go2_real go2_real.launch.py

Run on the Jetson after the DottorCane bringup (dottorcane repo, branch slam:
ros2 launch dottorcane_bringup dottorcane_slam.launch.py), which starts the zenoh
router, go2_control (cmd_vel, front camera, IMU), the Livox Mid-360 and the TF.

Started here:
  - lidar_camera_depth: /dottorcane/agent/depth, a 32FC1 depth image aligned with
    the agent's camera from the Mid-360 points, for ros2_depth_distance and
    ros2_depth_corridor (the robot has no depth camera);
  - lidar_nav_cloud: /dottorcane/agent/nav_cloud, the deskewed Mid-360 cloud reduced
    to what the dua_nav2 costmaps use (obstacle band, 5 cm voxels, x y z), for Nav2
    on a workstation over Wi-Fi; nav_cloud:=false leaves it out;
  - lidar_obstacle_scan: /dottorcane/agent/scan_obstacles, a 360 deg LaserScan of
    the Mid-360 points 10-70 cm above the floor, for Nav2 on a workstation
    (go2_real_nav.launch.py); obstacle_scan:=false leaves it out.

The camera is the one the agent sees (NEBIUS_CAMERA_TOPIC). Its frame must be in
the TF tree; without a calibrated camera_info pass hfov_deg and camera_frame:

    ros2 launch go2_real go2_real.launch.py camera_frame:=dottorcane/usb_camera hfov_deg:=78

Like the DottorCane launch files, the nodes use rmw_zenoh_cpp.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, SetEnvironmentVariable
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue

CAMERA_INFO_TOPIC = '/dottorcane/go2_control/frontvideo/camera_info'
LIDAR_TOPIC = '/dottorcane/sensors/livox_lidar_driver/point_cloud'
DESKEWED_TOPIC = LIDAR_TOPIC + '/deskewed'
NAV_CLOUD_TOPIC = '/dottorcane/agent/nav_cloud'
DEPTH_TOPIC = '/dottorcane/agent/depth'
SCAN_TOPIC = '/dottorcane/agent/scan_obstacles'


def generate_launch_description():
    return LaunchDescription([
        SetEnvironmentVariable('RMW_IMPLEMENTATION', 'rmw_zenoh_cpp'),
        DeclareLaunchArgument(
            'camera_info', default_value=CAMERA_INFO_TOPIC,
            description='CameraInfo of the camera the agent uses (unused with hfov_deg)'),
        DeclareLaunchArgument(
            'points', default_value=LIDAR_TOPIC,
            description='Lidar PointCloud2'),
        DeclareLaunchArgument(
            'camera_frame', default_value='dottorcane/front_camera_link',
            description='TF frame of the camera (empty: frame_id of camera_info)'),
        DeclareLaunchArgument(
            'camera_convention', default_value='auto',
            description='optical (z forward), body (x forward) or auto'),
        DeclareLaunchArgument(
            'hfov_deg', default_value='0.0',
            description='Horizontal FOV of an uncalibrated camera (0: use camera_info)'),
        DeclareLaunchArgument(
            'image_width', default_value='1280', description='Image width with hfov_deg'),
        DeclareLaunchArgument(
            'image_height', default_value='720', description='Image height with hfov_deg'),
        DeclareLaunchArgument(
            'obstacle_scan', default_value='true',
            description='Also publish the obstacle LaserScan for Nav2'),
        DeclareLaunchArgument(
            'nav_cloud', default_value='true',
            description='Also publish the reduced cloud for the dua_nav2 costmaps'),
        DeclareLaunchArgument(
            'base_height', default_value='0.34',
            description='Standing base height above the floor [m] (camera height - 0.04)'),
        DeclareLaunchArgument(
            'cliff_check', default_value='false',
            description='Treat a missing floor ahead (stairs going down) as an obstacle in the scan'),
        DeclareLaunchArgument(
            'use_sim_time', default_value='false',
            description='Simulation clock (go2_sim_worlds profile:=real)'),
        Node(
            package='go2_real',
            executable='lidar_camera_depth.py',
            name='lidar_camera_depth',
            namespace='dottorcane/agent',
            output='screen',
            emulate_tty=True,
            parameters=[{
                'use_sim_time': ParameterValue(LaunchConfiguration('use_sim_time'), value_type=bool),
                'body_frame': 'dottorcane/base_link',
                'camera_frame': LaunchConfiguration('camera_frame'),
                'camera_convention': LaunchConfiguration('camera_convention'),
                'hfov_deg': ParameterValue(LaunchConfiguration('hfov_deg'), value_type=float),
                'image_width': ParameterValue(LaunchConfiguration('image_width'), value_type=int),
                'image_height': ParameterValue(LaunchConfiguration('image_height'), value_type=int),
                'odom_frame': 'map',
                'base_height': ParameterValue(LaunchConfiguration('base_height'), value_type=float),
            }],
            remappings=[
                ('camera_info', LaunchConfiguration('camera_info')),
                ('points', LaunchConfiguration('points')),
                ('depth', DEPTH_TOPIC),
                ('depth/camera_info', DEPTH_TOPIC + '/camera_info'),
            ]),
        Node(
            package='go2_real',
            executable='lidar_obstacle_scan.py',
            name='lidar_obstacle_scan',
            namespace='dottorcane/agent',
            output='screen',
            emulate_tty=True,
            condition=IfCondition(LaunchConfiguration('obstacle_scan')),
            parameters=[{
                'use_sim_time': ParameterValue(LaunchConfiguration('use_sim_time'), value_type=bool),
                'body_frame': 'dottorcane/base_link',
                'odom_frame': 'map',
                'base_height': ParameterValue(LaunchConfiguration('base_height'), value_type=float),
                'cliff_check': ParameterValue(LaunchConfiguration('cliff_check'), value_type=bool),
            }],
            remappings=[
                ('points', LaunchConfiguration('points')),
                ('scan', SCAN_TOPIC),
            ]),
        Node(
            package='go2_real',
            executable='lidar_nav_cloud.py',
            name='lidar_nav_cloud',
            namespace='dottorcane/agent',
            output='screen',
            emulate_tty=True,
            condition=IfCondition(LaunchConfiguration('nav_cloud')),
            parameters=[{
                'use_sim_time': ParameterValue(LaunchConfiguration('use_sim_time'), value_type=bool),
                'odom_frame': 'map',
            }],
            remappings=[
                ('points', DESKEWED_TOPIC),
                ('cloud', NAV_CLOUD_TOPIC),
            ]),
    ])
