import threading, copy

class LockVar():
    def __init__(self,var):
        self.var = var
        self.lock = threading.Lock()

    def set(self, val):
        with self.lock:
            self.var = val

    def get(self):
        with self.lock:
            return copy.deepcopy(self.var)