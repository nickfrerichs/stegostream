import json
import os

class Config:

    def __init__(self, config_path=None):

        if config_path is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            config_path = os.path.join(script_dir, "../config.json")

        with open(config_path, "r") as file:
            data = json.load(file)

        for key, value in data.items():
            setattr(self, key, value)