#!/usr/bin/env python3
from better_launch import BetterLaunch, launch_this, convenience
from better_launch.elements import Node
from pprint import pprint
#from better_launch.declarative import launch_toml


@launch_this
def test():
    bl = BetterLaunch()
    
    vanilla = bl.load_params("better_launch", "control_config.yaml")
    pprint(vanilla)

    print("-----------------------------------")

    params = bl.load_params("better_launch", "control_config.yaml", qualifier="joint_state_broadcaster/frame_id")
    pprint(params)

    param_echo = bl.find("better_launch", "param_echo_node.py")
    #with bl.group("my_group"):
    bl.node(None, param_echo, "param_echo", params=params)
