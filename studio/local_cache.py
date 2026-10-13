"""Small, generation-keyed caches for derived local metadata, never message pages."""
from collections import OrderedDict
from copy import deepcopy
import threading


class LocalCache:
    def __init__(self, limit=128):
        self.limit = limit
        self.values = OrderedDict()
        self.lock = threading.RLock()

    def get(self, key, calculate):
        with self.lock:
            if key not in self.values:
                self.values[key] = calculate()
                while len(self.values) > self.limit:
                    self.values.popitem(last=False)
            self.values.move_to_end(key)
            return deepcopy(self.values[key])
