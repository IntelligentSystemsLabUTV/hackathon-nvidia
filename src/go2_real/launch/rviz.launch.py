"""RViz for the real Go2 (DottorCane) and the AgenticROS inputs.

    ros2 launch go2_real rviz.launch.py                          # on the Jetson
    ros2 launch go2_real rviz.launch.py robot:=<host or IP>      # from a workstation
    ros2 launch go2_real rviz.launch.py camera:=<image topic>    # another camera

The DottorCane stack runs on rmw_zenoh_cpp with a zenoh router on port 7447. On
the Jetson RViz reaches the local router. From another machine `robot` makes the
RViz session connect straight to the robot's router (ZENOH_CONFIG_OVERRIDE), so no
router is needed on the workstation. `camera` replaces the camera topic of the
config (default: the Go2 front camera).
"""

import os
import tempfile

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, OpaqueFunction, SetEnvironmentVariable
from launch.substitutions import LaunchConfiguration

CAMERA_TOPIC = '/dottorcane/go2_control/frontvideo/image_rect_color'


def launch_setup(context):
    actions = [SetEnvironmentVariable('RMW_IMPLEMENTATION', 'rmw_zenoh_cpp')]
    robot = LaunchConfiguration('robot').perform(context)
    if robot:
        endpoint = robot if '/' in robot else f'tcp/{robot}:7447'
        actions.append(SetEnvironmentVariable(
            'ZENOH_CONFIG_OVERRIDE',
            f'mode="client";connect/endpoints=["{endpoint}"];scouting/multicast/enabled=false'))
    config = os.path.join(get_package_share_directory('go2_real'), 'rviz', 'go2_real.rviz')
    camera = LaunchConfiguration('camera').perform(context)
    if camera:
        with open(config) as f:
            text = f.read().replace(CAMERA_TOPIC, camera)
        tmp = tempfile.NamedTemporaryFile('w', prefix='go2_real_', suffix='.rviz', delete=False)
        with tmp:
            tmp.write(text)
        config = tmp.name
    actions.append(ExecuteProcess(cmd=['rviz2', '-d', config], output='screen', emulate_tty=True))
    return actions


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'robot', default_value='',
            description='Zenoh router of the robot: host, IP or endpoint like tcp/<ip>:7447 '
                        '(empty: the local router)'),
        DeclareLaunchArgument(
            'camera', default_value='',
            description=f'Image topic of the agent camera (empty: {CAMERA_TOPIC})'),
        OpaqueFunction(function=launch_setup),
    ])
