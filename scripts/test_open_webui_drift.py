"""Offline tests for the Open WebUI wheel inspection; never imports the app."""

import importlib.util
from pathlib import Path


def drift():
    spec = importlib.util.spec_from_file_location(
        "open_webui_drift", Path(__file__).with_name("open-webui-drift.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reports_removed_settings_and_unset_openai_fallback():
    findings = drift().inspect_sources(
        {
            "open_webui/config.py": """
import os
OPENAI_API_BASE_URL = os.getenv("OPENAI_API_BASE_URL", "https://api.openai.com/v1")
AUDIO_NEW_BASE_URL = os.environ.get("AUDIO_NEW_BASE_URL", OPENAI_API_BASE_URL)
""",
            "open_webui/env.py": """
import os
ENABLE_PLUGINS = os.getenv("ENABLE_PLUGINS", "True").lower() == "true"
""",
        },
        {"REMOVED_SETTING": "true", "ENABLE_PLUGINS": "true"},
    )
    assert any("REMOVED_SETTING" in line for line in findings)
    assert any("AUDIO_NEW_BASE_URL" in line for line in findings)
    assert any("ENABLE_PLUGINS default: True" in line for line in findings)


def test_names_read_by_a_dependency_are_not_reported():
    sources = {
        "open_webui/config.py": "import os",
        "open_webui/env.py": (
            "import os\n"
            "ENABLE_PLUGINS = os.getenv('ENABLE_PLUGINS', 'True').lower() == 'true'\n"
        ),
    }
    module = drift()
    environment = {
        "ENABLE_PLUGINS": "true",
        "HF_HOME": "x",
        "ANONYMIZED_TELEMETRY": "false",
    }
    assert module.failures(module.inspect_sources(sources, environment)) == []
    assert any(
        "REMOVED" in line
        for line in module.inspect_sources(sources, {**environment, "REMOVED": "1"})
    )


def test_covered_settings_and_explicit_plugins_pass():
    sources = {
        "open_webui/config.py": """
import os
RAG_OPENAI_API_BASE_URL = os.getenv("RAG_OPENAI_API_BASE_URL", "https://api.openai.com/v1")
""",
        "open_webui/env.py": """
import os
ENABLE_PLUGINS = os.getenv("ENABLE_PLUGINS", "True").lower() == "true"
""",
    }
    module = drift()
    findings = module.inspect_sources(
        sources,
        {"RAG_OPENAI_API_BASE_URL": "{gatewayUrl}/v1", "ENABLE_PLUGINS": "true"},
    )
    assert module.failures(findings) == []
