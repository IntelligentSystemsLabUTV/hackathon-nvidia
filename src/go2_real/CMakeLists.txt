cmake_minimum_required(VERSION 3.8)
project(go2_real)

find_package(ament_cmake REQUIRED)

install(
  DIRECTORY
    launch
    rviz
  DESTINATION
    share/${PROJECT_NAME}/
)

install(
  PROGRAMS
    scripts/lidar_camera_depth.py
  DESTINATION
    lib/${PROJECT_NAME}
)

ament_package()
