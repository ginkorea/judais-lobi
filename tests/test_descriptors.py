# tests/test_descriptors.py

import pytest

from core.tools.descriptors import (
    SandboxProfile,
    ToolDescriptor,
    SHELL_DESCRIPTOR,
    PYTHON_DESCRIPTOR,
    INSTALL_DESCRIPTOR,
    WEB_SEARCH_DESCRIPTOR,
    WEB_RESEARCH_DESCRIPTOR,
    FETCH_PAGE_DESCRIPTOR,
    RAG_CRAWLER_DESCRIPTOR,
    VOICE_DESCRIPTOR,
    ALL_DESCRIPTORS,
)


class TestSandboxProfile:
    def test_default_values(self):
        p = SandboxProfile()
        assert p.workspace_writable is True
        assert p.allow_network is False
        assert p.allowed_read_paths == []
        assert p.allowed_write_paths == []
        assert p.max_cpu_seconds is None
        assert p.max_memory_bytes is None
        assert p.max_processes is None

    def test_custom_values(self):
        p = SandboxProfile(
            workspace_writable=False,
            allow_network=True,
            allowed_read_paths=["/etc"],
            allowed_write_paths=["/tmp"],
            max_cpu_seconds=60,
            max_memory_bytes=1_073_741_824,
            max_processes=10,
        )
        assert p.workspace_writable is False
        assert p.allow_network is True
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

    def test_web_research_descriptor(self):
        assert WEB_RESEARCH_DESCRIPTOR.tool_name == "perform_web_research"
        assert WEB_RESEARCH_DESCRIPTOR.requires_network is True
        assert "http.read" in WEB_RESEARCH_DESCRIPTOR.network_scopes

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
        assert len(ALL_DESCRIPTORS) == 15
        names = [d.tool_name for d in ALL_DESCRIPTORS]
        assert "run_shell_command" in names
        assert "speak_text" in names
        assert "fs" in names
        assert "git" in names
        assert "verify" in names
        assert "repo_map" in names
        assert "patch" in names
        assert "memory_recall" in names
        assert "memory_write" in names

    def test_all_descriptors_have_descriptions(self):
        for d in ALL_DESCRIPTORS:
            assert d.description, f"{d.tool_name} has no description"


class TestWhichToolsGetTheNetwork:
    """A sandbox that is on by default takes the network away by default.

    So the descriptor is where a tool has to *say* it needs one, and the
    only interesting property of that list is that it is neither too long
    (a sandbox that grants the network to ``run_shell_command`` has
    stopped being one) nor too short (a web search that cannot resolve a
    name fails in a library, not in a refusal).
    """

    #: Written out rather than derived, because deriving it from the
    #: descriptors would make this test agree with whatever they say.
    ALLOWED = {
        "perform_web_search",
        "perform_web_research",
        "fetch_page_content",
        "install_project",
        "rag_crawl",
    }

    def test_exactly_these_tools_ask_for_the_network(self):
        asking = {
            d.tool_name for d in ALL_DESCRIPTORS
            if d.sandbox_profile.allow_network
        }
        assert asking == self.ALLOWED

    @pytest.mark.parametrize("descriptor", ALL_DESCRIPTORS,
                             ids=lambda d: d.tool_name)
    def test_a_tool_that_declares_network_gets_a_profile_that_allows_it(
        self, descriptor,
    ):
        """``requires_network`` gates a capability check and
        ``allow_network`` opens a namespace; a tool that has the first
        and not the second is a tool the bus lets through and the sandbox
        silently strangles."""
        if descriptor.requires_network:
            assert descriptor.sandbox_profile.allow_network, (
                f"{descriptor.tool_name} declares requires_network but its "
                "sandbox profile denies it"
            )

    def test_the_shell_and_the_interpreter_do_not(self):
        assert SHELL_DESCRIPTOR.sandbox_profile.allow_network is False
        assert PYTHON_DESCRIPTOR.sandbox_profile.allow_network is False

    def test_pip_does(self):
        """The one whose scopes (``pip.install``) read like a filesystem
        effect and whose implementation is an HTTP client."""
        assert INSTALL_DESCRIPTOR.sandbox_profile.allow_network is True


class TestTheMultiActionToolsPublishTheirArguments:
    """The five tools a coding mission runs on, and what they declare.

    Until Phase 15 not one of them carried an ``input_schema``, so the
    catalogue a mission is handed said ``patch: validate, apply, diff,
    rollback, merge, status`` and nothing about ``patch_set_json`` — the
    argument a model cannot possibly guess, being a JSON *string* holding a
    list of search/replace blocks. What the schema buys is stated in
    ``core.runtime.schema_check``: a wrong argument refused here costs one
    turn, and discovered at the far end it costs three.
    """

    #: The tools whose dispatch is ``{"action": ..., ...}``. Written out
    #: rather than derived from ``action_scopes``, for the reason the
    #: network list above is: a test derived from the thing under test
    #: agrees with whatever it says.
    MULTI_ACTION = ("fs", "git", "verify", "repo_map", "patch")

    def descriptor(self, name):
        found = [d for d in ALL_DESCRIPTORS if d.tool_name == name]
        assert found, f"{name} is not registered"
        return found[0]

    @pytest.mark.parametrize("name", MULTI_ACTION)
    def test_it_declares_a_schema_that_requires_an_action(self, name):
        schema = self.descriptor(name).input_schema
        assert schema, f"{name} publishes no input_schema"
        assert "action" in schema.get("required", ())

    @pytest.mark.parametrize("name", MULTI_ACTION)
    def test_the_action_enum_is_exactly_the_actions_the_bus_can_dispatch(
        self, name,
    ):
        """The one drift this can have, caught where it happens.

        An action added to ``action_scopes`` and not to the enum is an
        action the schema check refuses; one added to the enum and not to
        ``action_scopes`` is an action the bus resolves to the tool's whole
        scope set, which is the widest grant it has.
        """
        descriptor = self.descriptor(name)
        declared = set(descriptor.input_schema["properties"]["action"]["enum"])
        assert declared == set(descriptor.action_scopes)

    @pytest.mark.parametrize("name", MULTI_ACTION)
    def test_every_declared_property_says_what_it_is_for(self, name):
        """A description is not decoration here: under ``--protocol
        native`` the whole schema is what the request declares, so a
        property with no description is an argument the model is offered
        and never told the shape of."""
        properties = self.descriptor(name).input_schema["properties"]
        undescribed = [key for key, spec in properties.items()
                       if not str(spec.get("description", "")).strip()]
        assert not undescribed, f"{name}: {undescribed}"

    def test_the_patch_schema_states_the_shape_of_a_patch_set(self):
        """The one argument nothing else in the prompt could teach."""
        properties = self.descriptor("patch").input_schema["properties"]
        described = properties["patch_set_json"]["description"]
        for word in ("file_path", "search_block", "replace_block",
                     "task_id", "modify", "create"):
            assert word in described, word

    def test_fs_requires_a_path_because_every_one_of_its_actions_does(self):
        assert "path" in self.descriptor("fs").input_schema["required"]

    def test_verify_takes_nothing_but_the_action(self):
        """The command belongs to the repository, and the schema is where
        a model finds that out: no path, no flags, no command line."""
        schema = self.descriptor("verify").input_schema
        assert list(schema["properties"]) == ["action"]
