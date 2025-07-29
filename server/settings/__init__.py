import traceback

try:
    from .main import DebuglySettings, DEFAULT_DEBUGLY_SETTINGS

    __all__ = (
        "DebuglySettings",
        "DEFAULT_DEBUGLY_SETTINGS",
    )
except Exception as e:
    print(f"ERROR loading ayon_debugly: {e}")
    print(traceback.format_exc())
