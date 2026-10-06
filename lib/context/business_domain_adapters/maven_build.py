"""Safe Maven generated-source metadata adapter; never executes Maven."""
from __future__ import annotations

import posixpath
import re
import xml.etree.ElementTree as ET

from .base import Unit

PREPARE_PHASE = 10


def _local(element, name):
    return element.find(f"{{*}}{name}")


def _text(element, name):
    child = _local(element, name)
    return (child.text or "").strip() if child is not None else ""


def _annotation_processors(root, text):
    """The annotation processors the build runs, each with the span declaring it.

    A processor runs when it is on the compiler's processor path
    (``annotationProcessorPaths``) or is an ordinary ``*-processor`` dependency
    on the compile classpath. Only declared coordinates are reported; the build
    is never executed, so a processor's generated output is never seen.
    """
    declared = [(path, "path") for paths in root.findall(".//{*}annotationProcessorPaths")
                for path in paths.findall("{*}path")]
    declared += [(dependency, "dependency") for dependency in root.findall(".//{*}dependency")
                 if _text(dependency, "artifactId").endswith("-processor")]
    processors = []
    for element, _ in declared:
        group, artifact = _text(element, "groupId"), _text(element, "artifactId")
        marker = re.search(rf"<artifactId>\s*{re.escape(artifact)}\s*</artifactId>", text) if artifact else None
        if group and artifact and marker:
            processors.append({"group": group, "artifact": artifact, "span": marker.span()})
    return processors


def extract(source):
    root = ET.fromstring(source.text)
    # The project's own coordinates name the namespace its code is published
    # under. The <parent> groupId belongs to whatever the project inherits from
    # (spring-boot-starter-parent, say), so it never counts as the project's.
    group_id = _text(root, "groupId")
    source.build_namespaces = [group_id] if group_id.count(".") >= 1 else []
    source.annotation_processors = _annotation_processors(root, source.text)
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
                "model_name_prefix": _text(configuration, "modelNamePrefix"),
                "model_name_suffix": _text(configuration, "modelNameSuffix"),
            })
    source.generated_source_config = generated
    if not generated:
        return []
    marker = re.search(r"(?s)<plugin>.*?<artifactId>openapi-generator-maven-plugin</artifactId>.*?</plugin>",
                       source.text)
    start, end = marker.span() if marker else (0, len(source.text))
    return [Unit(source, "openapi-generator", source.path + "::openapi-generator",
                 start, end, "module")]


def _spec_path(build_source, input_spec):
    """The repository path of a generator's input spec, or None if not literal."""
    directory = posixpath.dirname(build_source.path) or "."
    path, substituted = re.subn(r"\$\{(?:project\.)?basedir\}", directory, input_spec or "")
    if not path or "${" in path or posixpath.isabs(path):
        return None
    path = posixpath.normpath(path if substituted else posixpath.join(directory, path))
    return None if path == ".." or path.startswith("../") else path


def _schema_spans(spec):
    """Each ``components.schemas`` entry of an OpenAPI document with its span."""
    import yaml
    from yaml.nodes import MappingNode, ScalarNode
    try:
        root = yaml.compose(spec.text, Loader=yaml.SafeLoader)
    except (yaml.YAMLError, RecursionError):
        return {}

    def member(node, name):
        if not isinstance(node, MappingNode):
            return None
        return next((value for key, value in node.value
                     if isinstance(key, ScalarNode) and key.value == name), None)

    schemas = member(member(root, "components"), "schemas")
    if not isinstance(schemas, MappingNode):
        return {}
    spans = {}
    for key, value in schemas.value:
        if isinstance(key, ScalarNode):
            # A block value's end mark sits at the next key's indentation.
            end = len(spec.text[:value.end_mark.index].rstrip())
            spans[key.value] = (spec, key.start_mark.index, end)
    return spans


def prepare(sources, units, diagnostics=None):
    java_sources = {id(unit.source): unit.source for unit in units
                    if unit.source.language == "java"}.values()
    # Handed to every Java source whether or not a generator is configured: the
    # Java adapter reads it to tell a missing project type from a dependency.
    namespaces = sorted({namespace for source in sources
                         for namespace in getattr(source, "build_namespaces", [])})
    # Each processor with the build file and span that declare it, so a Java
    # declaration a processor implements can cite the build evidence.
    processors = [(source, *processor["span"], processor["group"], processor["artifact"])
                  for source in sources for processor in getattr(source, "annotation_processors", [])]
    for source in java_sources:
        source.build_namespaces = namespaces
        source.build_processors = processors
    configs = [item for source in sources
               for item in getattr(source, "generated_source_config", [])]
    if not configs:
        return
    build_source = sources[0]
    build_unit = next((unit for unit in units if unit.source is build_source), None)
    start = build_unit.start if build_unit else 0
    end = build_unit.end if build_unit else len(build_source.text)
    # Generated model types are never in the snapshot. What the generator was
    # told, and the committed schema it reads, are the evidence that remains.
    analyzed = {unit.source.path: unit.source for unit in units}
    for source in sources:
        # The one <plugin> element that configures the generator.
        plugin = re.search(r"(?s)<plugin>(?:(?!<plugin>).)*?<artifactId>\s*"
                           r"openapi-generator-maven-plugin\s*</artifactId>.*?</plugin>",
                           source.text)
        for config in getattr(source, "generated_source_config", ()):
            spec = analyzed.get(_spec_path(source, config["input_spec"]))
            config["generator_evidence"] = ((source, *plugin.span()) if plugin
                                            else (source, 0, len(source.text)))
            config["schemas"] = _schema_spans(spec) if spec else {}
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
