# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
from __future__ import annotations

import os
from functools import lru_cache
from typing import Iterable

import jinja2
import rich_click as click
from docutils import nodes
from docutils.nodes import Element

# No stub exists for docutils.parsers.rst.directives. See https://github.com/python/typeshed/issues/5755.
from docutils.parsers.rst import Directive, directives  # type: ignore[attr-defined]
from docutils.statemachine import StringList
from provider_yaml_utils import get_provider_yaml_paths, load_package_data
from sphinx.util import nested_parse_with_titles
from sphinx.util.docutils import switch_source_input

CMD_OPERATORS_AND_HOOKS = "operators-and-hooks"

CMD_TRANSFERS = "transfers"

"""
Directives for rendering tables with operators.

To test the template rendering process, you can also run this script as a standalone program.

    PYTHONPATH=$PWD/../ python exts/operators_and_hooks_ref.py --help
"""
DEFAULT_HEADER_SEPARATOR = "="

CURRENT_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, os.pardir, os.pardir))
DOCS_DIR = os.path.join(ROOT_DIR, "docs")


@lru_cache(maxsize=None)
def _get_jinja_env():
    loader = jinja2.FileSystemLoader(CURRENT_DIR, followlinks=True)
    env = jinja2.Environment(loader=loader, undefined=jinja2.StrictUndefined)
    return env


def _render_template(template_name, **kwargs):
    return _get_jinja_env().get_template(template_name).render(**kwargs)


def _docs_path(filepath: str):
    if not filepath.startswith("/docs/"):
        raise Exception(f"The path must starts with '/docs/'. Current value: {filepath}")

    if not filepath.endswith(".rst"):
        raise Exception(f"The path must ends with '.rst'. Current value: {filepath}")

    if filepath.startswith("/docs/apache-airflow-providers-"):
        _, _, provider, rest = filepath.split("/", maxsplit=3)
        filepath = f"{provider}:{rest}"
    else:
        filepath = os.path.join(ROOT_DIR, filepath.lstrip("/"))
        filepath = os.path.relpath(filepath, DOCS_DIR)

    len_rst = len(".rst")
    filepath = filepath[:-len_rst]
    return filepath


def _prepare_resource_index(package_data, resource_type):
    return {
        integration["integration-name"]: {**integration, "package-name": provider["package-name"]}
        for provider in package_data
        for integration in provider.get(resource_type, [])
    }


def _prepare_operators_data(tags: set[str] | None):
    package_data = load_package_data()
    all_integrations = _prepare_resource_index(package_data, "integrations")
    if tags is None:
        to_display_integration = all_integrations.values()
    else:
        to_display_integration = [
            integration for integration in all_integrations.values() if tags.intersection(integration["tags"])
        ]

    all_operators_by_integration = _prepare_resource_index(package_data, "operators")
    all_hooks_by_integration = _prepare_resource_index(package_data, "hooks")
    all_sensors_by_integration = _prepare_resource_index(package_data, "hooks")
    results = []

    for integration in to_display_integration:
        item = {
            "integration": integration,
        }
        operators = all_operators_by_integration.get(integration["integration-name"])
        sensors = all_sensors_by_integration.get(integration["integration-name"])
        hooks = all_hooks_by_integration.get(integration["integration-name"])

        if "how-to-guide" in item["integration"]:
            item["integration"]["how-to-guide"] = [_docs_path(d) for d in item["integration"]["how-to-guide"]]
        if operators:
            item["operators"] = operators
        if sensors:
            item["hooks"] = sensors
        if hooks:
            item["hooks"] = hooks
        if operators or sensors or hooks:
            results.append(item)

    return sorted(results, key=lambda d: d["integration"]["integration-name"].lower())


def _render_operator_content(*, tags: set[str] | None, header_separator: str):
    tabular_data = _prepare_operators_data(tags)

    return _render_template(
        "operators_and_hooks_ref.rst.jinja2", items=tabular_data, header_separator=header_separator
    )


def _prepare_transfer_data(tags: set[str] | None):
    package_data = load_package_data()
    all_operators_by_integration = _prepare_resource_index(package_data, "integrations")
    # Add edge case
    for name in ["SQL", "Local"]:
        all_operators_by_integration[name] = {"integration-name": name}
    all_transfers = [
        {
            **transfer,
            "package-name": provider["package-name"],
            "source-integration": all_operators_by_integration[transfer["source-integration-name"]],
            "target-integration": all_operators_by_integration[transfer["target-integration-name"]],
        }
        for provider in package_data
        for transfer in provider.get("transfers", [])
    ]
    if tags is None:
        to_display_transfers = all_transfers
    else:
        to_display_transfers = [
            transfer
            for transfer in all_transfers
            if tags.intersection(transfer["source-integration"].get("tags", set()))
            or tags.intersection(transfer["target-integration"].get("tags", set()))
        ]

    for transfer in to_display_transfers:
        if "how-to-guide" not in transfer:
            continue
        transfer["how-to-guide"] = _docs_path(transfer["how-to-guide"])
    return to_display_transfers


def _render_transfer_content(*, tags: set[str] | None, header_separator: str):
    tabular_data = _prepare_transfer_data(tags)

    return _render_template(
        "operators_and_hooks_ref-transfers.rst.jinja2", items=tabular_data, header_separator=header_separator
    )


def _prepare_logging_data():
    package_data = load_package_data()
    all_logging = {}
    for provider in package_data:
        logging_handlers = provider.get("logging")
        if logging_handlers:
            package_name = provider["package-name"]
            all_logging[package_name] = {"name": provider["name"], "handlers": logging_handlers}
    return all_logging


def _render_logging_content(*, header_separator: str):
    tabular_data = _prepare_logging_data()

    return _render_template("logging.rst.jinja2", items=tabular_data, header_separator=header_separator)


def _prepare_auth_backend_data():
    package_data = load_package_data()
    all_auth_backends = {}
    for provider in package_data:
        auth_backends_list = provider.get("auth-backends")
        if auth_backends_list:
            package_name = provider["package-name"]
            all_auth_backends[package_name] = {"name": provider["name"], "auth_backends": auth_backends_list}
    return all_auth_backends


def _render_auth_backend_content(*, header_separator: str):
    tabular_data = _prepare_auth_backend_data()

    return _render_template("auth_backend.rst.jinja2", items=tabular_data, header_separator=header_separator)


def _prepare_secrets_backend_data():
    package_data = load_package_data()
    all_secret_backends = {}
    for provider in package_data:
        secret_backends_list = provider.get("secrets-backends")
        if secret_backends_list:
            package_name = provider["package-name"]
            all_secret_backends[package_name] = {
                "name": provider["name"],
                "secrets_backends": secret_backends_list,
            }
    return all_secret_backends


def _render_secrets_backend_content(*, header_separator: str):
    tabular_data = _prepare_secrets_backend_data()

    return _render_template(
        "secret_backend.rst.jinja2", items=tabular_data, header_separator=header_separator
    )


def _prepare_connections_data():
    package_data = load_package_data()
    all_connections = {}
    for provider in package_data:
        connections_list = provider.get("connection-types")
        if connections_list:
            package_name = provider["package-name"]
            all_connections[package_name] = {
                "name": provider["name"],
                "connection_types": connections_list,
            }
    return all_connections


def _render_connections_content(*, header_separator: str):
    tabular_data = _prepare_connections_data()

    return _render_template("connections.rst.jinja2", items=tabular_data, header_separator=header_separator)


def _prepare_extra_links_data():
    package_data = load_package_data()
    all_extra_links = {}
    for provider in package_data:
        extra_link_list = provider.get("extra-links")
        if extra_link_list:
            package_name = provider["package-name"]
            all_extra_links[package_name] = {
                "name": provider["name"],
                "extra_links": extra_link_list,
            }
    return all_extra_links


def _render_extra_links_content(*, header_separator: str):
    tabular_data = _prepare_extra_links_data()

    return _render_template("extra_links.rst.jinja2", items=tabular_data, header_separator=header_separator)


class BaseJinjaReferenceDirective(Directive):
    """The base directive for OperatorsHooksReferenceDirective and TransfersReferenceDirective"""

    optional_arguments = 1
    option_spec = {"tags": directives.unchanged, "header-separator": directives.unchanged_required}

    def run(self):
        tags_arg = self.options.get("tags")
        tags = {t.strip() for t in tags_arg.split(",")} if tags_arg else None

        header_separator = self.options.get("header-separator")
        new_content = self.render_content(tags=tags, header_separator=header_separator)

        with switch_source_input(self.state, self.content):
            new_content = StringList(new_content.splitlines(), source="")
            node = nodes.section()  # type: Element
            # necessary so that the child nodes get the right source/line set
            node.document = self.state.document
            nested_parse_with_titles(self.state, new_content, node)

        # record all filenames as dependencies -- this will at least
        # partially make automatic invalidation possible
        for filepath in get_provider_yaml_paths():
            self.state.document.settings.record_dependencies.add(filepath)

        return node.children

    def render_content(self, *, tags: set[str] | None, header_separator: str = DEFAULT_HEADER_SEPARATOR):
        """Return content in RST format"""
        raise NotImplementedError("Tou need to override render_content method.")


class OperatorsHooksReferenceDirective(BaseJinjaReferenceDirective):
    """Generates a list of operators, sensors, hooks"""

    def render_content(self, *, tags: set[str] | None, header_separator: str = DEFAULT_HEADER_SEPARATOR):
        return _render_operator_content(
            tags=tags,
            header_separator=header_separator,
        )


class TransfersReferenceDirective(BaseJinjaReferenceDirective):
    """Generate a list of transfer operators"""

    def render_content(self, *, tags: set[str] | None, header_separator: str = DEFAULT_HEADER_SEPARATOR):
        return _render_transfer_content(
            tags=tags,
            header_separator=header_separator,
        )


class LoggingDirective(BaseJinjaReferenceDirective):
    """Generate list of logging handlers"""

    def render_content(self, *, tags: set[str] | None, header_separator: str = DEFAULT_HEADER_SEPARATOR):
        return _render_logging_content(
            header_separator=header_separator,
        )


class AuthBackendDirective(BaseJinjaReferenceDirective):
    """Generate list of auth backend handlers"""

    def render_content(self, *, tags: set[str] | None, header_separator: str = DEFAULT_HEADER_SEPARATOR):
        return _render_auth_backend_content(
            header_separator=header_separator,
        )


class SecretsBackendDirective(BaseJinjaReferenceDirective):
    """Generate list of secret backend handlers"""

    def render_content(self, *, tags: set[str] | None, header_separator: str = DEFAULT_HEADER_SEPARATOR):
        return _render_secrets_backend_content(
            header_separator=header_separator,
        )


class ConnectionsDirective(BaseJinjaReferenceDirective):
    """Generate list of connections"""

    def render_content(self, *, tags: set[str] | None, header_separator: str = DEFAULT_HEADER_SEPARATOR):
        return _render_connections_content(
            header_separator=header_separator,
        )


class ExtraLinksDirective(BaseJinjaReferenceDirective):
    """Generate list of extra links"""

    def render_content(self, *, tags: set[str] | None, header_separator: str = DEFAULT_HEADER_SEPARATOR):
        return _render_extra_links_content(
            header_separator=header_separator,
        )


def setup(app):
    """Setup plugin"""
    app.add_directive("operators-hooks-ref", OperatorsHooksReferenceDirective)
    app.add_directive("transfers-ref", TransfersReferenceDirective)
    app.add_directive("airflow-logging", LoggingDirective)
    app.add_directive("airflow-auth-backends", AuthBackendDirective)
    app.add_directive("airflow-secrets-backends", SecretsBackendDirective)
    app.add_directive("airflow-connections", ConnectionsDirective)
    app.add_directive("airflow-extra-links", ExtraLinksDirective)

    return {"parallel_read_safe": True, "parallel_write_safe": True}


option_tag = click.option(
    "--tag",
    multiple=True,
    help="If passed, displays integrations that have a matching tag",
)

option_header_separator = click.option(
    "--header-separator", default=DEFAULT_HEADER_SEPARATOR, show_default=True
)


@click.group(context_settings={"help_option_names": ["-h", "--help"], "max_content_width": 500})
def cli():
    """Render tables with integrations"""


@cli.command()
@option_tag
@option_header_separator
def operators_and_hooks(tag: Iterable[str], header_separator: str):
    """Renders Operators ahd Hooks content"""
    print(_render_operator_content(tags=set(tag) if tag else None, header_separator=header_separator))


@cli.command()
@option_tag
@option_header_separator
def transfers(tag: Iterable[str], header_separator: str):
    """Renders Transfers content"""
    print(_render_transfer_content(tags=set(tag) if tag else None, header_separator=header_separator))


@cli.command()
@option_header_separator
def logging(header_separator: str):
    """Renders Logger content"""
    print(_render_logging_content(header_separator=header_separator))


@cli.command()
@option_header_separator
def auth_backends(header_separator: str):
    """Renders Logger content"""
    print(_render_auth_backend_content(header_separator=header_separator))


@cli.command()
@option_header_separator
def secret_backends(header_separator: str):
    """Renders Secret Backends content"""
    print(_render_secrets_backend_content(header_separator=header_separator))


@cli.command()
@option_header_separator
def connections(header_separator: str):
    """Renders Connections content"""
    print(_render_connections_content(header_separator=header_separator))


@cli.command()
@option_header_separator
def extra_links(header_separator: str):
    """Renders Extra  links content"""
    print(_render_extra_links_content(header_separator=header_separator))


if __name__ == "__main__":
    cli()
