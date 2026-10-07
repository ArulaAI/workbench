"""Safe Maven generated-source metadata adapter; never executes Maven."""
from __future__ import annotations

import posixpath
import re
import xml.etree.ElementTree as ET

from .base import Unit, declare_trace_contract

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
        if api_package or model_package:
            option = (lambda name: _text(config_options, name)) if config_options is not None \
                else (lambda name: "")
            generated.append({
                "api_package": api_package or None,
                "model_package": model_package or None,
                "input_spec": input_spec or None,
                "interface_only": interface_only,
                "model_name_prefix": _text(configuration, "modelNamePrefix"),
                "model_name_suffix": _text(configuration, "modelNameSuffix"),
                # What decides the model classes the generator writes. Any
                # mapping element can rename or replace a type, so its mere
                # presence withholds model synthesis.
                "generate_models": _text(configuration, "generateModels"),
                "models_to_generate": _text(configuration, "modelsToGenerate"),
                "type_overrides": any(_local(configuration, name) is not None for name in _TYPE_OVERRIDES)
                    or (config_options is not None and any(
                        _local(config_options, name) is not None for name in _TYPE_OVERRIDES)),
                "date_library": option("dateLibrary"),
                "openapi_nullable": option("openApiNullable"),
                "boolean_getter_prefix": option("booleanGetterPrefix"),
            })
    source.generated_source_config = generated
    if not generated:
        return []
    marker = re.search(r"(?s)<plugin>.*?<artifactId>openapi-generator-maven-plugin</artifactId>.*?</plugin>",
                       source.text)
    start, end = marker.span() if marker else (0, len(source.text))
    return [Unit(source, "openapi-generator", source.path + "::openapi-generator",
                 start, end, "module")]


_TYPE_OVERRIDES = ("typeMappings", "importMappings", "schemaMappings", "instantiationTypes",
                   "languageSpecificPrimitives", "modelNameMappings", "nameMappings")


def _spec_path(build_source, input_spec):
    """The repository path of a generator's input spec, or None if not literal."""
    directory = posixpath.dirname(build_source.path) or "."
    path, substituted = re.subn(r"\$\{(?:project\.)?basedir\}", directory, input_spec or "")
    if not path or "${" in path or posixpath.isabs(path):
        return None
    path = posixpath.normpath(path if substituted else posixpath.join(directory, path))
    return None if path == ".." or path.startswith("../") else path


def _member(node, name):
    from yaml.nodes import MappingNode, ScalarNode
    if not isinstance(node, MappingNode):
        return None
    return next((value for key, value in node.value
                 if isinstance(key, ScalarNode) and key.value == name), None)


def _scalar(node, name):
    from yaml.nodes import ScalarNode
    value = _member(node, name)
    return value.value if isinstance(value, ScalarNode) else None


def _schema_nodes(spec):
    """``{name: (key node, value node)}`` for each ``components.schemas`` entry."""
    import yaml
    from yaml.nodes import MappingNode, ScalarNode
    try:
        root = yaml.compose(spec.text, Loader=yaml.SafeLoader)
    except (yaml.YAMLError, RecursionError):
        return {}
    schemas = _member(_member(root, "components"), "schemas")
    if not isinstance(schemas, MappingNode):
        return {}
    return {key.value: (key, value) for key, value in schemas.value
            if isinstance(key, ScalarNode)}


def _span(spec, key, value):
    # A block value's end mark sits at the next key's indentation.
    return (spec, key.start_mark.index, len(spec.text[:value.end_mark.index].rstrip()))


def _schema_spans(spec):
    """Each ``components.schemas`` entry of an OpenAPI document with its span."""
    return {name: _span(spec, key, value) for name, (key, value) in _schema_nodes(spec).items()}


# openapi-generator escapes these as property names, so their accessors are
# not the plain bean names; such properties get no accessor here.
_JAVA_RESERVED = frozenset("""abstract assert boolean break byte case catch char class const
continue default do double else enum extends final finally float for goto if implements import
instanceof int interface long native new package private protected public return short static
strictfp super switch synchronized this throw throws transient try void volatile while true false
null var record yield""".split())
_IDENTIFIER = re.compile(r"[a-z][A-Za-z0-9]*\Z")
_SCHEMA_NAME = re.compile(r"[A-Za-z][A-Za-z0-9]*\Z")
_AFFIX = re.compile(r"[A-Za-z0-9]*\Z")
_LOCAL_REF = re.compile(r"#/components/schemas/([A-Za-z][A-Za-z0-9]*)\Z")
# The Java type openapi-generator's Java generators emit for a scalar schema,
# keyed by (type, format), under the default java8 date library.
_SCALARS = {
    ("string", None): "String", ("string", "email"): "String", ("string", "password"): "String",
    ("string", "date"): "java.time.LocalDate", ("string", "date-time"): "java.time.OffsetDateTime",
    ("string", "uuid"): "java.util.UUID", ("string", "uri"): "java.net.URI",
    ("integer", None): "Integer", ("integer", "int32"): "Integer", ("integer", "int64"): "Long",
    ("number", None): "java.math.BigDecimal", ("number", "float"): "Float",
    ("number", "double"): "Double", ("boolean", None): "Boolean",
}
_DATE_FORMATS = {"date", "date-time"}


def _capitalized(text):
    return text[:1].upper() + text[1:]


def _is_model(node):
    """True when openapi-generator writes a model class for a component schema.

    An object schema (properties or ``allOf``) and a named enum become classes;
    a scalar or array alias does not, and a ``oneOf``/``anyOf`` schema becomes a
    generator-specific composed type this adapter does not model.
    """
    if _member(node, "oneOf") is not None or _member(node, "anyOf") is not None:
        return False
    return any(_member(node, name) is not None for name in ("properties", "allOf", "enum"))


def _openapi_models(spec, config):
    """The model classes openapi-generator writes for one generator configuration.

    One class per object or enum entry of ``components.schemas``, named
    ``modelPackage.<prefix><Schema><suffix>``, with a bean getter and setter
    per property, ``allOf`` parts included. A property whose Java type is not
    established keeps its accessors with an unknown type; anything whose name
    the generator would rewrite is omitted rather than guessed.
    """
    from yaml.nodes import MappingNode, SequenceNode
    package = config.get("model_package")
    prefix = config.get("model_name_prefix") or ""
    suffix = config.get("model_name_suffix") or ""
    selected = config.get("models_to_generate") or ""
    if (not package or "${" in package or config.get("type_overrides")
            or config.get("generate_models", "").casefold() not in {"", "true"}
            or "${" in selected or not _AFFIX.match(prefix) or not _AFFIX.match(suffix)):
        return []
    schemas = _schema_nodes(spec)
    wanted = {item.strip() for item in selected.split(",") if item.strip()} or set(schemas)
    names = {}
    for name, (_, node) in schemas.items():
        if name in wanted and _SCHEMA_NAME.match(name) and _is_model(node):
            names[name] = _capitalized(prefix) + _capitalized(name) + _capitalized(suffix)
    simple_names = list(names.values())
    names = {name: simple for name, simple in names.items()
             if simple_names.count(simple) == 1 and simple.casefold() not in _JAVA_RESERVED}
    date_library = config.get("date_library") or "java8"
    nullable = (config.get("openapi_nullable") or "true").casefold() != "false"

    def target(node):
        """The component schema a local ``$ref`` names, or None."""
        ref = _scalar(node, "$ref")
        match = _LOCAL_REF.match(ref or "")
        return match.group(1) if match and match.group(1) in schemas else None

    def java_type(node, seen=()):
        if _member(node, "$ref") is not None:
            name = target(node)
            if name is None or name in seen:
                return None
            if name in names:
                return f"{package}.{names[name]}"
            # An alias schema is inlined; a model the generator writes under a
            # name not established here leaves the type unknown.
            referenced = schemas[name][1]
            return None if _is_model(referenced) else java_type(referenced, (*seen, name))
        if any(_member(node, key) is not None for key in ("allOf", "oneOf", "anyOf", "enum", "not")):
            return None
        if nullable and (_scalar(node, "nullable") or "").casefold() == "true":
            return None
        kind, form = _scalar(node, "type"), _scalar(node, "format")
        if kind == "array":
            item = java_type(_member(node, "items"), seen) if _member(node, "items") else None
            container = ("java.util.Set" if (_scalar(node, "uniqueItems") or "").casefold() == "true"
                         else "java.util.List")
            return f"{container}<{item}>" if item else None
        if form in _DATE_FORMATS and date_library != "java8":
            return None
        return _SCALARS.get((kind, form))

    def properties(node, seen):
        """``[(name, schema node, key node, declaring node)]``, or None if not composable."""
        if any(_member(node, key) is not None for key in ("oneOf", "anyOf", "discriminator")):
            return None
        if _member(node, "$ref") is not None:
            name = target(node)
            if name is None or name in seen:
                return None
            return properties(schemas[name][1], (*seen, name))
        found = []
        parts = _member(node, "allOf")
        if parts is not None:
            if not isinstance(parts, SequenceNode):
                return None
            for part in parts.value:
                composed = properties(part, seen)
                if composed is None:
                    return None
                found.extend(composed)
        declared = _member(node, "properties")
        if isinstance(declared, MappingNode):
            found.extend((key.value, value, key) for key, value in declared.value
                         if getattr(key, "value", None) is not None)
        return found

    models = []
    for name, simple in sorted(names.items()):
        key, node = schemas[name]
        accessors = []
        composed = [] if _member(node, "enum") is not None else properties(node, (name,))
        counts = {}
        for item in composed or ():
            counts[item[0]] = counts.get(item[0], 0) + 1
        for prop, value, prop_key in composed or ():
            # A property redeclared across allOf parts has no single type.
            if not _IDENTIFIER.match(prop) or prop in _JAVA_RESERVED:
                continue
            if any(accessor["property"] == prop for accessor in accessors):
                continue
            kind = java_type(value) if counts[prop] == 1 else None
            if kind is None:
                kind = "unknown"
            getter = ((config.get("boolean_getter_prefix") or "get") if kind == "Boolean" else "get")
            if not _IDENTIFIER.match(getter):
                continue
            accessors.append({"property": prop, "type": kind,
                              "getter": getter + _capitalized(prop), "setter": "set" + _capitalized(prop),
                              "span": _span(spec, prop_key, value)})
        models.append({"schema": name, "simple": simple, "qualified": f"{package}.{simple}",
                       "span": _span(spec, key, node), "accessors": accessors})
    return models


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
    known_models = {getattr(unit, "generated_model_name", None) for unit in units}
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
            config["models"] = _openapi_models(spec, config) if spec else []
            for model in config["models"]:
                if model["qualified"] not in known_models:
                    known_models.add(model["qualified"])
                    generated = _model_units(config, model)
                    source.generated_model_units = [*getattr(source, "generated_model_units", ()),
                                                    generated[0]]
                    units.extend(generated)
    known = {getattr(unit, "generated_interface_name", None) for unit in units}
    for source in java_sources:
        semantic = getattr(source, "semantic", {})
        source.generated_source_config = configs
        for qualified in semantic.get("imports", {}).values():
            if qualified in known or not any(
                    config["interface_only"] and config["api_package"]
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


def _model_units(config, model):
    """A generated model class and its bean accessors as units of the build file.

    The class is never in the snapshot, so each unit's own span is the plugin
    that generates it, and its supporting evidence is the schema (for the
    class) or the property (for an accessor) it is generated from. Accessors
    are concrete: the generator writes a field read or write for each one.
    """
    build_source, start, end = config["generator_evidence"]
    prefix = build_source.path + "::generated-model:" + model["qualified"]
    unit = Unit(build_source, model["simple"], prefix, start, end, "type")
    unit.generated_model_name = model["qualified"]
    unit.semantic_identity = model["qualified"]
    unit.semantic_kind = "type"
    unit.supporting_evidence_spans = [model["span"]]
    accessors = []
    for accessor in model["accessors"]:
        for name, params, returns in (
                (accessor["getter"], [], accessor["type"]),
                (accessor["setter"], [(accessor["property"], accessor["type"])], "void")):
            method = Unit(build_source, name, f"{prefix}.{name}({','.join(t for _, t in params)})",
                          start, end, "method", params=params, owner=model["simple"])
            method.executable_body = True
            declare_trace_contract(method, "implementation")
            method.semantic_identity = (f"{model['qualified']}.{name}"
                                        f"({','.join(t for _, t in params)})")
            method.generated_return_type = returns
            method.supporting_evidence_spans = [accessor["span"]]
            accessors.append(method)
    unit.generated_accessors = accessors
    return [unit, *accessors]


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
def relations(source):
    """Each generated model class declares its accessors, citing the property."""
    return [{"source": unit, "target": method, "candidate_targets": [method],
             "kind": "declares", "start": method.start, "end": method.end,
             "resolution": "resolved", "reason": None,
             "evidence_spans": list(method.supporting_evidence_spans)}
            for unit in getattr(source, "generated_model_units", ())
            for method in unit.generated_accessors]
