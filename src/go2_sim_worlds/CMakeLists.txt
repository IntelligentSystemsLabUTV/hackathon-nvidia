cmake_minimum_required(VERSION 3.8)
project(go2_sim_worlds)

find_package(ament_cmake REQUIRED)

install(
  DIRECTORY
    config
    launch
    maps
    worlds
  DESTINATION
    share/${PROJECT_NAME}/
)

install(
  PROGRAMS
    scripts/depth_obstacle_scan.py
    scripts/ground_truth_odom.py
  DESTINATION
    lib/${PROJECT_NAME}
)

ament_package()
