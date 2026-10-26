cmake_minimum_required(VERSION 3.8)
project(go2_real)

find_package(ament_cmake REQUIRED)

install(
  DIRECTORY
    config
    launch
    rviz
  DESTINATION
    share/${PROJECT_NAME}/
)

install(
  PROGRAMS
    scripts/lidar_camera_depth.py
    scripts/lidar_nav_cloud.py
    scripts/lidar_obstacle_scan.py
  DESTINATION
    lib/${PROJECT_NAME}
)

ament_package()
