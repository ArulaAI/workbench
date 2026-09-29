"""Safe Maven generated-source metadata adapter; never executes Maven."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from .base import Unit

PREPARE_PHASE = 10


def _local(element, name):
    return element.find(f"{{*}}{name}")


def _text(element, name):
    child = _local(element, name)
    return (child.text or "").strip() if child is not None else ""


def extract(source):
    root = ET.fromstring(source.text)
    generated = []
    for plugin in root.findall(".//{*}plugin"):
        if _text(plugin, "artifactId") != "openapi-generator-maven-plugin":
            continue
        configuration = plugin.find(".//{*}configuration")
        if configuration is None:
            continue
        config_options = _local(configuration, "configOptions")
        interface_only = (_text(config_options, "interfaceOnly").casefold() == "true"
                          if config_options is not None else False)
        api_package = _text(configuration, "apiPackage")
        model_package = _text(configuration, "modelPackage")
        input_spec = _text(configuration, "inputSpec")
        if api_package:
            generated.append({
                "api_package": api_package,
                "model_package": model_package or None,
                "input_spec": input_spec or None,
                "interface_only": interface_only,
            })
    source.generated_source_config = generated
    if not generated:
        return []
    marker = re.search(r"(?s)<plugin>.*?<artifactId>openapi-generator-maven-plugin</artifactId>.*?</plugin>",
                       source.text)
    start, end = marker.span() if marker else (0, len(source.text))
    return [Unit(source, "openapi-generator", source.path + "::openapi-generator",
                 start, end, "module")]


def prepare(sources, units, diagnostics=None):
    configs = [item for source in sources
               for item in getattr(source, "generated_source_config", [])]
    if not configs:
        return
    build_source = sources[0]
    build_unit = next((unit for unit in units if unit.source is build_source), None)
    start = build_unit.start if build_unit else 0
    end = build_unit.end if build_unit else len(build_source.text)
    java_sources = {id(unit.source): unit.source for unit in units
                    if unit.source.language == "java"}.values()
    known = {getattr(unit, "generated_interface_name", None) for unit in units}
    for source in java_sources:
        semantic = getattr(source, "semantic", {})
        source.generated_source_config = configs
        for qualified in semantic.get("imports", {}).values():
            if qualified in known or not any(
                    config["interface_only"]
                    and qualified.startswith(config["api_package"] + ".")
                    for config in configs):
                continue
            unit = Unit(build_source, qualified.rsplit(".", 1)[-1],
                        build_source.path + "::generated-interface:" + qualified,
                        start, end, "type")
            unit.generated_interface_name = qualified
            unit.semantic_identity = qualified
            unit.semantic_kind = "interface"
            units.append(unit)
            known.add(qualified)


def diagnostics(source):
    if getattr(source, "generated_source_config", []):
        return []
    return [{"span": (0, min(len(source.text), 1)),
             "code": "GENERATED_SOURCE_CONFIGURATION_UNRESOLVED",
             "reason": "Maven build file has no supported generated-interface configuration."}]


def bindings(unit): return []
def calls(unit): return []
def candidates(*args): return []
def resources(unit): return []
def observations(unit): return []
def operations(unit): return []
def relations(source): return []
