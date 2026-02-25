# tests/test_descriptors.py

import pytest

from core.tools.descriptors import (
    SandboxProfile,
    ToolDescriptor,
    SHELL_DESCRIPTOR,
    PYTHON_DESCRIPTOR,
    INSTALL_DESCRIPTOR,
    WEB_SEARCH_DESCRIPTOR,
    FETCH_PAGE_DESCRIPTOR,
    RAG_CRAWLER_DESCRIPTOR,
    VOICE_DESCRIPTOR,
    ALL_DESCRIPTORS,
)


class TestSandboxProfile:
    def test_default_values(self):
        p = SandboxProfile()
        assert p.workspace_writable is True
        assert p.allowed_read_paths == []
        assert p.allowed_write_paths == []
        assert p.max_cpu_seconds is None
        assert p.max_memory_bytes is None
        assert p.max_processes is None

    def test_custom_values(self):
        p = SandboxProfile(
            workspace_writable=False,
            allowed_read_paths=["/etc"],
            allowed_write_paths=["/tmp"],
            max_cpu_seconds=60,
            max_memory_bytes=1_073_741_824,
            max_processes=10,
        )
        assert p.workspace_writable is False
        assert p.allowed_read_paths == ["/etc"]
        assert p.max_cpu_seconds == 60
        assert p.max_memory_bytes == 1_073_741_824
        assert p.max_processes == 10

    def test_frozen(self):
        p = SandboxProfile()
        with pytest.raises(AttributeError):
            p.workspace_writable = False


class TestToolDescriptor:
    def test_default_values(self):
        d = ToolDescriptor(tool_name="test_tool")
        assert d.tool_name == "test_tool"
        assert d.required_scopes == []
        assert d.requires_network is False
        assert d.network_scopes == []
        assert isinstance(d.sandbox_profile, SandboxProfile)
        assert d.description == ""

    def test_custom_values(self):
        profile = SandboxProfile(max_cpu_seconds=30)
        d = ToolDescriptor(
            tool_name="custom",
            required_scopes=["a.b", "c.d"],
            requires_network=True,
            network_scopes=["net.any"],
            sandbox_profile=profile,
            description="A custom tool",
        )
        assert d.required_scopes == ["a.b", "c.d"]
        assert d.requires_network is True
        assert d.network_scopes == ["net.any"]
        assert d.sandbox_profile.max_cpu_seconds == 30
        assert d.description == "A custom tool"

    def test_frozen(self):
        d = ToolDescriptor(tool_name="test")
        with pytest.raises(AttributeError):
            d.tool_name = "changed"


class TestPrebuiltDescriptors:
    def test_shell_descriptor(self):
        assert SHELL_DESCRIPTOR.tool_name == "run_shell_command"
        assert "shell.exec" in SHELL_DESCRIPTOR.required_scopes
        assert SHELL_DESCRIPTOR.requires_network is False

    def test_python_descriptor(self):
        assert PYTHON_DESCRIPTOR.tool_name == "run_python_code"
        assert "python.exec" in PYTHON_DESCRIPTOR.required_scopes

    def test_install_descriptor(self):
        assert INSTALL_DESCRIPTOR.tool_name == "install_project"
        assert "python.exec" in INSTALL_DESCRIPTOR.required_scopes
        assert "pip.install" in INSTALL_DESCRIPTOR.required_scopes

    def test_web_search_descriptor(self):
        assert WEB_SEARCH_DESCRIPTOR.tool_name == "perform_web_search"
        assert WEB_SEARCH_DESCRIPTOR.requires_network is True
        assert "http.read" in WEB_SEARCH_DESCRIPTOR.network_scopes

    def test_fetch_page_descriptor(self):
        assert FETCH_PAGE_DESCRIPTOR.tool_name == "fetch_page_content"
        assert FETCH_PAGE_DESCRIPTOR.requires_network is True

    def test_rag_crawler_descriptor(self):
        assert RAG_CRAWLER_DESCRIPTOR.tool_name == "rag_crawl"
        assert "fs.read" in RAG_CRAWLER_DESCRIPTOR.required_scopes

    def test_voice_descriptor(self):
        assert VOICE_DESCRIPTOR.tool_name == "speak_text"
        assert "audio.output" in VOICE_DESCRIPTOR.required_scopes

    def test_all_descriptors_list(self):
        assert len(ALL_DESCRIPTORS) == 11
        names = [d.tool_name for d in ALL_DESCRIPTORS]
        assert "run_shell_command" in names
        assert "speak_text" in names
        assert "fs" in names
        assert "git" in names
        assert "verify" in names
        assert "repo_map" in names

    def test_all_descriptors_have_descriptions(self):
        for d in ALL_DESCRIPTORS:
            assert d.description, f"{d.tool_name} has no description"
