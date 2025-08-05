# -*- coding: utf-8 -*-
from ayon_debugly.collectors.collector_base import CollectorBase, redact_dict
import os
import sys

class CollectorEnv(CollectorBase):
    def collect(self):
        env = dict(os.environ)
        env = redact_dict(env)
        env["cwd"] = os.getcwd()
        env["python_path"] = sys.path
        return {"env": env}
