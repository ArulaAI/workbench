"""Typed GraphQL projection of the versioned canonical discovery contract.

Types are derived from the checked-in schema so UI/API/SQL/workflow records
cannot silently acquire different API shapes. ID maps become typed lists;
stored property names are explicitly mapped to GraphQL camelCase names.
No arbitrary JSON scalar is exposed.
"""
from __future__ import annotations

from dataclasses import make_dataclass
import keyword
import enum
from typing import Annotated, Optional, Union

import strawberry
from lib.context.business_domain_schema import DEFINITIONS, validate, _default

_shapes = {}
_classes = {}


def _camel(name):
    first,*parts = name.split('_')
    return first + ''.join(part[:1].upper()+part[1:] for part in parts)


def _field_name(name):
    return name+'_' if keyword.iskeyword(name) else name


def _annotation(shape, name):
    if '$ref' in shape:
        key = shape['$ref'].rsplit('/',1)[1]
        return _annotation(DEFINITIONS[key],'Business'+key)
    if 'anyOf' in shape:
        nonnull = [v for v in shape['anyOf'] if v.get('type') != 'null']
        if len(nonnull) == 1:
            return 'Optional['+_annotation(nonnull[0],name)+']'
    if 'oneOf' in shape:
        choices = [_annotation(v,name+str(i)) for i,v in enumerate(shape['oneOf'])]
        return 'Annotated[Union['+','.join(choices)+'], strawberry.union("'+name+'")]'
    kind = shape.get('type')
    if kind == 'object':
        if isinstance(shape.get('additionalProperties'),dict):
            return 'list['+_annotation(shape['additionalProperties'],name+'Item')+']'
        if name not in _shapes:
            _shapes[name] = shape
            fields = [( _field_name(key),_annotation(value,name+key.title().replace('_','')),
                strawberry.field(name=_camel(key))) for key,value in shape['properties'].items()]
            cls = make_dataclass(name,fields,namespace={'__module__':__name__},kw_only=True)
            globals()[name] = cls
            _classes[name] = cls
        return name
    if kind == 'array':
        return 'list['+_annotation(shape['items'],name+'Item')+']'
    if kind in ('integer','number','boolean'):
        return {'integer':'int','number':'float','boolean':'bool'}[kind]
    if 'const' in shape and type(shape['const']) is int:
        return 'int'
    return 'str'


for _root in ('Activity','Rule','Evidence','Trace','TraceObligation','Binding','Concept','Ownership',
              'Claim','Resource','Symbol','Relationship','StatusArtifact','Effect','RuleObservation','RuleRelationship','BoundaryItem','Unassigned'):
    _annotation(DEFINITIONS[_root],'Business'+_root)


def _inputs(self) -> list[BusinessBinding]:
    return getattr(self,'_input_records',[])


def _outputs(self) -> list[BusinessBinding]:
    return getattr(self,'_output_records',[])


def _traces(self) -> list[BusinessTrace]:
    return getattr(self,'_trace_records',[])


def _effects(self) -> list[BusinessEffect]:
    return getattr(self,'_effect_records',[])


def _obligations(self) -> list[BusinessTraceObligation]:
    return getattr(self,'_obligation_records',[])


def _observations(self) -> list[BusinessRuleObservation]:
    return getattr(self,'_observation_records',[])


def _rule_relationships(self) -> list[BusinessRuleRelationship]:
    return getattr(self,'_relationship_records',[])


def _ownership_concept(self) -> Optional[BusinessConcept]:
    return getattr(self,'_concept_record',None)


for _field,_resolver in (('inputs',_inputs),('outputs',_outputs),('traces',_traces),('effects',_effects)):
    setattr(_classes['BusinessActivity'],_field,strawberry.field(resolver=_resolver,name=_field))
for _field,_resolver in (('observations',_observations),('relationships',_rule_relationships)):
    setattr(_classes['BusinessRule'],_field,strawberry.field(resolver=_resolver,name=_field))
setattr(_classes['BusinessOwnership'],'concept',strawberry.field(resolver=_ownership_concept,name='concept'))
setattr(_classes['BusinessTrace'],'obligations',strawberry.field(resolver=_obligations,name='obligations'))
for _name,_class in list(_classes.items()):
    globals()[_name] = _classes[_name] = strawberry.type(_class,
        name='DomainDiscoveryStatus' if _name=='BusinessStatusArtifact' else _name)


def _convert(value, shape, name):
    if value is None:
        return None
    if '$ref' in shape:
        key = shape['$ref'].rsplit('/',1)[1]
        return _convert(value,DEFINITIONS[key],'Business'+key)
    if 'anyOf' in shape:
        return _convert(value,next(v for v in shape['anyOf'] if v.get('type')!='null'),name)
    if 'oneOf' in shape:
        # Canonical tagged unions have a const discriminator in each branch.
        for index,branch in enumerate(shape['oneOf']):
            if all(value.get(key) == prop['const'] for key,prop in branch.get('properties',{}).items() if 'const' in prop):
                return _convert(value,branch,name+str(index))
        raise ValueError('Canonical union has no matching discriminator')
    if shape.get('type') == 'object':
        if isinstance(shape.get('additionalProperties'),dict):
            return [_convert(value[key],shape['additionalProperties'],name+'Item') for key in sorted(value)]
        return _classes[name](**{_field_name(key):_convert(value[key] if key in value else _default(child),child,name+key.title().replace('_',''))
            for key,child in shape['properties'].items()})
    if shape.get('type') == 'array':
        return [_convert(item,shape['items'],name+'Item') for item in value]
    return value


def to_record(value, type_name):
    validate(value,type_name)
    return _convert(value,DEFINITIONS[type_name],'Business'+type_name)


@strawberry.type
class DomainError:
    code: str
    message: str
    field: Optional[str] = None
    expected_build_id: Optional[strawberry.ID] = None
    current_build_id: Optional[strawberry.ID] = None


@strawberry.type
class DomainPageInfo:
    end_cursor: Optional[str]
    has_next_page: bool


# Each connection has a concrete node type and typed paging errors.
for _kind in ('Activity','Rule','Evidence','Concept','Ownership','Claim','Unassigned'):
    _edge_name = 'Domain'+_kind+'Edge'
    globals()[_edge_name] = strawberry.type(make_dataclass(_edge_name,
        [('cursor',str),('node','Business'+_kind)],namespace={'__module__':__name__},kw_only=True))
    _connection_name = 'Domain'+_kind+'Connection'
    globals()[_connection_name] = strawberry.type(make_dataclass(_connection_name,
        [('edges','list['+_edge_name+']'),('page_info',DomainPageInfo),('error',Optional[DomainError])],
        namespace={'__module__':__name__},kw_only=True))


@strawberry.enum
class DomainReviewOperation(enum.Enum):
    ACCEPT = 'accept'
    REJECT = 'reject'
    RENAME = 'rename'
    SET_MEMBERSHIP = 'set_membership'
    MERGE = 'merge'
    SPLIT = 'split'


@strawberry.input
class DomainSplitGroupInput:
    name: str
    activity_ids: list[strawberry.ID]


@strawberry.input
class DomainReviewInput:
    expected_build_id: strawberry.ID
    operation: DomainReviewOperation
    domain_ids: list[strawberry.ID]
    explanation: str
    name: Optional[str] = None
    activity_ids: Optional[list[strawberry.ID]] = None
    groups: Optional[list[DomainSplitGroupInput]] = None


@strawberry.type
class DomainReviewResult:
    accepted: bool
    build_id: Optional[strawberry.ID]
    domain_ids: list[strawberry.ID]
    error: Optional[DomainError]


@strawberry.type
class DomainBuildActionResult:
    accepted: bool
    build_id: Optional[strawberry.ID]
    error: Optional[DomainError]
