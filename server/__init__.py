from ayon_server.addons import BaseServerAddon
from .settings import DebuglySettings, DEFAULT_DEBUGLY_SETTINGS

class Debugly(BaseServerAddon):
    settings_model = DebuglySettings

    async def get_default_settings(self):
        settings_model_cls = self.get_settings_model()
        return settings_model_cls(**DEFAULT_DEBUGLY_SETTINGS)
 
