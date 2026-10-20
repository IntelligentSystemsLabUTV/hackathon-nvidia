"""AgenticROS side of the real Go2 (DottorCane), next to the dottorcane stack.

    ros2 launch go2_real go2_real.launch.py

Run on the Jetson after the DottorCane bringup (dottorcane repo, branch slam:
ros2 launch dottorcane_bringup dottorcane_slam.launch.py), which starts the zenoh
router, go2_control (cmd_vel, front camera, IMU), the Livox Mid-360 and the TF.

Started here:
  - lidar_camera_depth: /dottorcane/agent/depth, a 32FC1 depth image aligned with
    the agent's camera from the Mid-360 points, for ros2_depth_distance and
    ros2_depth_corridor (the robot has no depth camera).

The camera is the one the agent sees (NEBIUS_CAMERA_TOPIC). Its frame must be in
the TF tree; without a calibrated camera_info pass hfov_deg and camera_frame:

    ros2 launch go2_real go2_real.launch.py camera_frame:=dottorcane/usb_camera hfov_deg:=78

Like the DottorCane launch files, the nodes use rmw_zenoh_cpp.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, SetEnvironmentVariable
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue

CAMERA_INFO_TOPIC = '/dottorcane/go2_control/frontvideo/camera_info'
LIDAR_TOPIC = '/dottorcane/sensors/livox_lidar_driver/point_cloud'
DEPTH_TOPIC = '/dottorcane/agent/depth'


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
            'camera_frame', default_value='',
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
        Node(
            package='go2_real',
            executable='lidar_camera_depth.py',
            name='lidar_camera_depth',
            namespace='dottorcane/agent',
            output='screen',
            emulate_tty=True,
            parameters=[{
                'body_frame': 'dottorcane/base_link',
                'camera_frame': LaunchConfiguration('camera_frame'),
                'camera_convention': LaunchConfiguration('camera_convention'),
                'hfov_deg': ParameterValue(LaunchConfiguration('hfov_deg'), value_type=float),
                'image_width': ParameterValue(LaunchConfiguration('image_width'), value_type=int),
                'image_height': ParameterValue(LaunchConfiguration('image_height'), value_type=int),
            }],
            remappings=[
                ('camera_info', LaunchConfiguration('camera_info')),
                ('points', LaunchConfiguration('points')),
                ('depth', DEPTH_TOPIC),
                ('depth/camera_info', DEPTH_TOPIC + '/camera_info'),
            ]),
    ])
