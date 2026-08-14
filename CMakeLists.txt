cmake_minimum_required(VERSION 3.5)
project(better_launch)

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)

# Run via `colcon test --packages-select better_launch`. 
# Examine results with `colcon test-result --all`
if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  set(_pytest_tests
    tests/test_launcher.py
    tests/test_ros2_parameter_convert.py
    tests/test_launch_arg_convert.py
    # Add other test files here
  )
  foreach(_test_path ${_pytest_tests})
    get_filename_component(_test_name ${_test_path} NAME_WE)
    ament_add_pytest_test(${_test_name} ${_test_path}
      APPEND_ENV PYTHONPATH=${CMAKE_CURRENT_BINARY_DIR}
      TIMEOUT 60
      WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
    )
  endforeach()
endif()

install(DIRECTORY examples
        DESTINATION share/${PROJECT_NAME})

# Install the bl script that should be used instead of "ros2 launch/run"
install(PROGRAMS bin/bl DESTINATION bin)

# Shell completion for the bl script
ament_environment_hooks("${CMAKE_CURRENT_SOURCE_DIR}/hooks/bl_shell_completion.bash")
ament_environment_hooks("${CMAKE_CURRENT_SOURCE_DIR}/hooks/bl_shell_completion.zsh")
ament_environment_hooks("${CMAKE_CURRENT_SOURCE_DIR}/hooks/bl_shell_completion.fish")

ament_python_install_package(${PROJECT_NAME})
ament_package()
