"""Declarative API contracts, parsed without imports or external retrieval.

Document syntax stays behind the adapter boundary. Recognized contract keys
and operations come from the profile catalog; schema references are retained
as declarations and never treated as proof of runtime implementation.
"""
import json
from pathlib import Path

import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode
from .base import (Unit, declare_anchor_representation, declare_trace_contract,
                   http_identity)

PROFILES = json.loads(Path(__file__).with_name('document_profiles.json').read_text())


def mapping(node):
    if not isinstance(node,MappingNode):
        return {}
    return {key.value:value for key,value in node.value if isinstance(key,ScalarNode)}


def scalar(node):
    return node.value if isinstance(node,ScalarNode) else None


def sequence(node):
    return node.value if isinstance(node,SequenceNode) else []


def extract(source):
    try:
        root = mapping(yaml.compose(source.text,Loader=yaml.SafeLoader))
    except (yaml.YAMLError,RecursionError) as exc:
        raise ValueError('Malformed declarative document') from exc
    units = []
    source.matches = []
    for profile in PROFILES.values():
        if profile['root_marker'] not in root:
            continue
        for route,path_node in mapping(root.get(profile['operations_key'])).items():
            path = mapping(path_node)
            for method in profile['operation_methods']:
                operation_node = path.get(method)
                operation = mapping(operation_node)
                if not operation:
                    continue
                name = scalar(operation.get(profile['operation_name_key'])) or method.upper()+' '+route
                unit = Unit(source,name,source.path+'::'+method.upper()+' '+route,
                    operation_node.start_mark.index,operation_node.end_mark.index,'declarative_operation',
                    anchor_kind=profile['anchor_kind'],method=method.upper(),route=route,
                    anchor_resolution='resolved')
                declare_trace_contract(unit, 'contract')
                declare_anchor_representation(unit, 'contract',
                    http_identity(source, unit.method, unit.route),
                    'eligible', 'external')
                units.append(unit)
                source.matches.append({'start':unit.start,'operation':operation,
                    'parameters':sequence(path.get('parameters'))+sequence(operation.get('parameters')),
                    'profile':profile})
    return units


def details(unit):
    return next(item for item in unit.source.matches if item['start']==unit.start)


def type_name(node):
    shape = mapping(node)
    return scalar(shape.get('$ref')) or scalar(shape.get('type')) or 'unknown'


def bindings(unit):
    data = details(unit); operation = data['operation']; result = []
    def add(name,direction,shape,expression):
        result.append({'name':name,'direction':direction,'value_type':type_name(shape),
            'expression':expression,'resolution':'unresolved',
            'reason':'Declared contract; no implementation binding has been verified.'})
    for parameter_node in data['parameters']:
        parameter = mapping(parameter_node)
        name = scalar(parameter.get('name'))
        if name:
            add(name,'input',parameter.get('schema'),scalar(parameter.get('in')))
    body = mapping(operation.get('requestBody'))
    for media,node in mapping(body.get('content')).items():
        add('requestBody:'+media,'input',mapping(node).get('schema'),scalar(body.get('description')))
    for status,response_node in mapping(operation.get('responses')).items():
        response = mapping(response_node); content = mapping(response.get('content'))
        if not content:
            add('response:'+status,'output',None,scalar(response.get('description')))
        for media,node in content.items():
            add('response:'+status+':'+media,'output',mapping(node).get('schema'),scalar(response.get('description')))
    return result


def observations(unit):
    data = details(unit); seen = set(); result = []
    def walk(node):
        if id(node) in seen:
            return
        seen.add(id(node))
        for key,value in mapping(node).items():
            if key in data['profile']['validation_keys']:
                start,end = value.start_mark.index,value.end_mark.index
                result.append({'span':(start-unit.start,end-unit.start),'source_location_kind':'api',
                    'native_expression':key+': '+unit.source.text[start:end],
                    'resolution':'unresolved','reason':'Declared contract constraint; enforcement is not established.'})
            walk(value)
        for value in sequence(node):
            walk(value)
    for value in data['operation'].values():
        walk(value)
    return result


def resources(unit):
    return []


def calls(unit):
    return []


def candidates(*args):
    return []


def operations(unit):
    return []
