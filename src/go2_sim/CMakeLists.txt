cmake_minimum_required(VERSION 3.8)
project(go2_sim)

find_package(ament_cmake REQUIRED)

install(
  DIRECTORY
    config
    launch
    worlds
  DESTINATION
    share/${PROJECT_NAME}/
)

install(
  PROGRAMS
    scripts/ground_truth_odom.py
  DESTINATION
    lib/${PROJECT_NAME}
)

ament_package()
