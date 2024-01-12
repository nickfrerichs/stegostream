import json
import os

class Config:

    def __init__(self, config_path=None):

        if config_path is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            config_path = os.path.join(script_dir, "../config.json")

            with open(config_path) as file:
                lines = [line.strip() for line in file if not line.startswith('#')]
                json_string = ''.join(lines)

                try:
                    data = json.loads(json_string)
                except json.JSONDecodeError as e:
                    print(f"Error decoding JSON config file: {e}")

            for key, value in data.items():
                setattr(self, key, value)