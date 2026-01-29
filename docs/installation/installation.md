# :inbox_tray: Installation
I'm working on getting a proper distro package up and running, but it's a surprisingly non-fun process. Until then you may follow the steps below!

???+ tip

    *better_launch* is a regular ROS2 package, which means you can install it in your workspace and then use it in all launch files within that workspace. 

ROS2 is slowly [moving towards pixi](https://docs.ros.org/en/kilted/Installation/Windows-Install-Binary.html) as the main python3 environment, but I have not tested it yet. However, by now all the dependencies have been added into rosdep, so the following should get you up and running:

```bash
# Get better_launch into your workspace src folder
cd <your/ros2/workspace>/src
git clone https://github.com/dfki-ric/better_launch.git
```

```bash
# Install the dependencies
sudo apt update
rosdep update
rosdep install --from-paths src --ignore-src -y
```

??? example "Using a python venv"

    If you prefer a python virtual environment instead of installing system packages, here is a setup that worked for us in the past:

    ```bash
    # Install some prerequisites
    sudo apt install python3-pip python3-venv

    # Create a virtual environment for your workspace
    cd your/ros2/workspace/
    mkdir venv
    python3 -m venv ./venv --system-site-packages --symlinks
    touch venv/COLCON_IGNORE

    # Activate the venv
    source ./venv/bin/activate

    # Activate your ROS2 workspace
    source ./install/setup.bash

    # Install the dependencies into your venv
    pip install -r path/to/better_launch/requirements.txt
    ```

Once all the dependencies are installed you should build your workspace.

```bash
# Build the better_launch package
cd <your/ros2/workspace>
colcon build --packages-up-to better_launch
source install/setup.bash
```

```bash
# Verify installation
bl --help
```

??? example "The devel branch"

    If you are the experimental type, *better_launch* also has a `devel` branch where I merge new features for testing. I try to keep it functional (since I'm using it myself), although there might be the occasional hiccup.
