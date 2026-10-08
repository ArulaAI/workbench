"""G2: missing entry-point detection is always reported.

Per language, a recognized source language whose selected adapters declare no
entry-point detection gets one coverage entry. Per signal, every catalog
marker that did not become an anchor is a likely missed entry point with file
and line. Gaps keep publication partial. The catalog lives in data.
"""
import copy
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from lib.context.business_domain_entrypoints import (
    MarkerCatalogError, load_catalog, parse_catalog, scan_markers)
from lib.context.business_domain_extract import Extractor
from lib.context.business_domain_schema import (
    DEFAULTS, DomainError, validate_references, validate_source_warning_coverage)
from lib.context.business_domains import publication_status
from lib.context.language_registry import registry

SPEED_ROOT = Path(__file__).parents[1]
CATALOG = load_catalog()
GAP_CODES = {'ENTRYPOINT_DETECTION_UNAVAILABLE', 'ENTRYPOINT_LIKELY_MISSED',
             'ENTRYPOINT_NONE_DETECTED'}


def extract(root, files):
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(text, bytes):
            path.write_bytes(text)
        else:
            path.write_text(text)
    facts, _ = Extractor(root, DEFAULTS).extract()
    validate_references(facts)
    return facts


def gaps(facts, kind=None):
    return [gap for gap in facts['coverage']['entrypoint_gaps']
            if kind is None or gap['kind'] == kind]


def hits(path, text):
    return [(hit.marker.framework, hit.marker.kind, hit.start_line)
            for hit in scan_markers(CATALOG, [(path, text)])]


# ── Catalog markers: one positive fixture per marker, plus exclusions ──

MINIMAL_API = '''var api = app.MapGroup("api/orders");
api.MapGet("/", GetOrders);
api.MapPost("/draft", CreateDraft);
app.MapMethods("/check", [HttpMethods.Options], () => Results.Ok());
'''

MVC = '''[ApiController]
[Route("api/[controller]")]
public class OrdersController : ControllerBase
{
    [HttpGet]
    [Route("{id}")]
    [ProducesResponseType(typeof(Order[]), 200)]
    public IActionResult Get(int id) => Ok();

    [HttpPost("submit")]
    public async Task<IActionResult> Submit() => Ok();
}
'''

GRPC = '''public class BasketService : Basket.BasketBase
{
    public override async Task<BasketResponse> GetBasket(GetBasketRequest request, ServerCallContext context)
    {
        return new();
    }
    public override string ToString() => "basket";
}
'''

HANDLER = '''public class OrderStartedIntegrationEventHandler(
    ILogger<OrderStartedIntegrationEventHandler> logger) : IIntegrationEventHandler<OrderStartedIntegrationEvent>
{
}
'''

HANDLER_DECLARATIONS = '''public interface IIntegrationEventHandler<in TIntegrationEvent> : IIntegrationEventHandler
{
}
public static class EventBusBuilderExtensions
{
    public static void AddSubscription<T, TH>(this IEventBusBuilder builder)
        where TH : class, IIntegrationEventHandler<T>
    {
    }
}
'''

SPRING_SCHEDULED = '''@Component
class Jobs {
    @Scheduled(fixedRate = 5000)
    void sweep() {}

    @KafkaListener(topics = "orders")
    void onOrder(String body) {}

    @EventListener
    void onStarted(ApplicationReadyEvent event) {}
}
'''

JAXRS = '''import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;

@Path("/owners")
public class OwnerResource {
    @GET
    @Path("/{id}")
    public Owner find(@PathParam("id") int id) { return null; }

    @POST
    public void create(Owner owner) {}
}
'''

EXPRESS = '''const express = require('express');
const app = express();
const router = express.Router();
app.get('/health', (req, res) => res.send('ok'));
router.post('/orders', createOrder);
axios.get('/remote');
'''

NEST = '''import { Controller, Get, Post } from '@nestjs/common';

@Controller('cats')
export class CatsController {
  @Get()
  findAll() {}

  @Post(':id')
  create() {}
}
'''

REACT_ROUTES = '''import { Route, Routes } from 'react-router-dom';
export const AppRoutes = () => (
  <Routes>
    <Route element={<Layout />}>
      <Route path="/" element={<Home />} />
      <Route index element={<Dashboard />} />
    </Route>
  </Routes>
);
'''

DATA_ROUTER = '''import { createBrowserRouter } from 'react-router-dom';
export const router = createBrowserRouter([{ path: '/', element: <Home /> }]);
'''

DJANGO = '''from django.urls import include, path, re_path
urlpatterns = [
    path('orders/', views.orders),
    re_path(r'^legacy/$', views.legacy),
    path('api/', include('api.urls')),
]
'''

XAML_PAGE = '''<?xml version="1.0" encoding="utf-8" ?>
<!-- catalog page -->
<views:ContentPageBase xmlns="http://schemas.microsoft.com/dotnet/2021/maui">
</views:ContentPageBase>
'''

XAML_VIEW = '''<?xml version="1.0" encoding="utf-8" ?>
<ContentView xmlns="http://schemas.microsoft.com/dotnet/2021/maui">
    <ContentPage />
</ContentView>
'''


@pytest.mark.parametrize('path, text, expected', [
    # MapGroup is a prefix; MapMethods is a route.
    ('Apis/OrdersApi.cs', MINIMAL_API, [
        ('aspnetcore_minimal_api', 'http_route', 2),
        ('aspnetcore_minimal_api', 'http_route', 3),
        ('aspnetcore_minimal_api', 'http_route', 4)]),
    # Class-level [Route] is a prefix; [HttpGet] + [Route] on one action is one hit.
    ('Controllers/OrdersController.cs', MVC, [
        ('aspnetcore_mvc', 'http_route', 5),
        ('aspnetcore_mvc', 'http_route', 10)]),
    # Only overrides taking ServerCallContext are gRPC methods.
    ('Grpc/BasketService.cs', GRPC, [('aspnetcore_grpc', 'rpc', 3)]),
    ('Handlers/OrderStarted.cs', HANDLER,
        [('dotnet_integration_events', 'message_handler', 1)]),
    # The interface declaration and a generic constraint are not handlers.
    ('EventBus/Abstractions.cs', HANDLER_DECLARATIONS, []),
    ('Pages/Cart.razor', '@page "/cart"\n<h1>Cart</h1>\n', [('blazor', 'page', 1)]),
    ('Pages/Index.cshtml', '@page\n@model IndexModel\n', [('razor_pages', 'page', 1)]),
    ('Views/CatalogView.xaml', XAML_PAGE, [('maui_xaml', 'page', 1)]),
    ('Views/Template.xaml', XAML_VIEW, []),
    ('src/main/java/Jobs.java', SPRING_SCHEDULED, [
        ('spring_events', 'event_handler', 9),
        ('spring_kafka', 'message_handler', 6),
        ('spring_scheduling', 'scheduled_job', 3)]),
    # Class-level @Path is the resource prefix; @GET + @Path is one method.
    ('src/main/java/OwnerResource.java', JAXRS, [
        ('jaxrs', 'http_route', 6), ('jaxrs', 'http_route', 10)]),
    ('server/app.js', EXPRESS, [
        ('express', 'http_route', 4), ('express', 'http_route', 5)]),
    # @Controller is the prefix and required context; handlers are entry points.
    ('src/cats.controller.ts', NEST, [
        ('nestjs', 'http_route', 5), ('nestjs', 'http_route', 8)]),
    ('src/cats.service.ts', NEST.replace("@Controller('cats')", ''), []),
    # A pathless layout <Route> is not a navigable page.
    ('src/routes.tsx', REACT_ROUTES, [
        ('react_router', 'page', 5), ('react_router', 'page', 6)]),
    ('src/router.tsx', DATA_ROUTER, [('react_router', 'page', 2)]),
    # include() mounts another URLconf; it is a prefix.
    ('shop/urls.py', DJANGO, [
        ('django', 'http_route', 3), ('django', 'http_route', 4)]),
])
def test_each_catalog_marker_reports_entry_points_and_not_prefixes(path, text, expected):
    assert sorted(hits(path, text)) == sorted(expected)


def test_spring_mapping_marker_matches_methods_not_class_prefix():
    text = '''@RestController
@RequestMapping("/api/owners")
public class OwnerRestController {
    @GetMapping("/{id}")
    @ResponseStatus(HttpStatus.OK)
    public Owner find(@PathVariable int id) { return null; }

    @RequestMapping(value = "/x", method = RequestMethod.POST)
    public void post() {}
}
'''
    assert hits('src/main/java/OwnerRestController.java', text) == [
        ('spring_web', 'http_route', 4), ('spring_web', 'http_route', 8)]


def test_markers_outside_framework_paths_or_in_tests_are_not_reported():
    assert hits('notes.txt', MINIMAL_API) == []
    assert scan_markers(CATALOG, [('tests/Api/OrdersApiTests.cs', MINIMAL_API)],
                        r'(^|/)(tests?|__tests__)(/|$)') == []


def test_catalog_is_data_and_rejects_undeclared_marker_kinds():
    raw = {'version': 1, 'kinds': {'http_route': 'route'},
           'coverage': {'categories': ['source'], 'non_entrypoint_languages': []},
           'display_names': {},
           'frameworks': {'custom': {'label': 'Custom', 'paths': ['.*\\.x'],
               'markers': [{'id': 'm', 'name': 'M', 'kind': 'http_route',
                            'pattern': 'ROUTE'}]}}}
    catalog = parse_catalog(raw)
    assert [(hit.marker.framework, hit.start_line) for hit in
            scan_markers(catalog, [('a.x', 'x\nROUTE\n')])] == [('custom', 2)]
    broken = copy.deepcopy(raw)
    broken['frameworks']['custom']['markers'][0]['kind'] = 'teleport'
    with pytest.raises(MarkerCatalogError):
        parse_catalog(broken)


def test_rules_adapter_entrypoint_languages_match_its_rule_catalogs():
    """The data declaration agrees with the installed rule metadata."""
    descriptor = registry.source_adapter_descriptor('rules')
    declared = set(descriptor['capability_languages']['entrypoint_detection'])
    rules_dir = SPEED_ROOT / 'lib/context/rules'
    anchored = set()
    for directory in rules_dir.iterdir():
        for rule_file in directory.glob('*.yml'):
            for rule in yaml.safe_load_all(rule_file.read_text()):
                if (rule or {}).get('metadata', {}).get('produces') in {
                        'business_anchor', 'entrypoint_registration'}:
                    anchored.add(directory.name)
    rules_languages = {name for name in registry._by_name
                       if registry.extraction_level(name) == 'rules'}
    expected = {name for name in rules_languages
                if registry.rules_language(name) in anchored}
    assert declared == expected
    assert registry.effective_capabilities(descriptor, 'c_sharp')[
        'entrypoint_detection'] == 'unsupported'
    assert registry.effective_capabilities(descriptor, 'python')[
        'entrypoint_detection'] == 'partial'


# ── Extraction: per-language gaps, likely misses, silent zero, noise ──

def test_language_without_entrypoint_detection_gets_exactly_one_entry(tmp_path):
    facts = extract(tmp_path, {
        'src/Orders/Order.cs': 'public class Order { public int Id { get; set; } }\n',
        'src/Orders/OrdersApi.cs': MINIMAL_API,
        'README.md': '# Orders\n'})
    language = gaps(facts, 'language_unavailable')
    assert [(gap['language'], gap['files'], gap['message']) for gap in language] == [
        ('c_sharp', 2, 'C#: 2 files, entry-point detection unavailable')]
    warnings = [w for w in facts['warnings']
                if w['code'] == 'ENTRYPOINT_DETECTION_UNAVAILABLE']
    assert [w['message'] for w in warnings] == [language[0]['message']]
    # Markdown cannot declare entry points, so it is never a language gap.
    assert all(gap['language'] != 'markdown' for gap in gaps(facts))
    missed = gaps(facts, 'likely_missed')
    assert [(gap['path'], gap['line'], gap['marker_kind']) for gap in missed] == [
        ('src/Orders/OrdersApi.cs', 2, 'http_route'),
        ('src/Orders/OrdersApi.cs', 3, 'http_route'),
        ('src/Orders/OrdersApi.cs', 4, 'http_route')]
    for warning in (w for w in facts['warnings']
                    if w['code'] == 'ENTRYPOINT_LIKELY_MISSED'):
        assert warning['message'].startswith('src/Orders/OrdersApi.cs:')
        evidence = facts['evidence'][warning['evidence_ids'][0]]
        assert evidence['locator']['path'] == 'src/Orders/OrdersApi.cs'
        assert evidence['excerpt'].startswith('.Map')


def test_blazor_page_with_byte_order_mark_is_a_likely_missed_page(tmp_path):
    facts = extract(tmp_path, {
        'Pages/Cart.razor': '﻿@page "/cart"\n<h1>Cart</h1>\n'.encode('utf-8'),
        'Program.cs': 'var app = WebApplication.Create();\n'})
    missed = gaps(facts, 'likely_missed')
    assert [(gap['framework'], gap['marker_kind'], gap['path'], gap['line'])
            for gap in missed] == [('blazor', 'page', 'Pages/Cart.razor', 1)]
    warning = next(w for w in facts['warnings'] if w['code'] == 'ENTRYPOINT_LIKELY_MISSED')
    assert facts['evidence'][warning['evidence_ids'][0]]['excerpt'].startswith('@page')
    # The ignored .razor file is searched for markers, never analyzed.
    assert not any(resource['name'] == 'Pages/Cart.razor'
                   for resource in facts['resources'].values())


def test_handler_class_is_missed_but_interface_declaration_is_not(tmp_path):
    facts = extract(tmp_path, {
        'Ordering/Handlers/OrderStarted.cs': HANDLER,
        'EventBus/Abstractions.cs': HANDLER_DECLARATIONS})
    assert [(gap['path'], gap['line'], gap['marker_kind'])
            for gap in gaps(facts, 'likely_missed')] == [
        ('Ordering/Handlers/OrderStarted.cs', 1, 'message_handler')]


SPRING_CONTROLLER = '''package org.example;

import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class OwnerController {
    @GetMapping("/owners")
    public String owners() {
        return "owners";
    }
}
'''

SPRING_JOBS = '''package org.example;

import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
public class Jobs {
    @Scheduled(fixedRate = 1000)
    public void sweep() {
    }
}
'''


def test_marker_that_became_an_anchor_is_not_reported(tmp_path):
    facts = extract(tmp_path, {
        'src/main/java/org/example/OwnerController.java': SPRING_CONTROLLER,
        'src/main/java/org/example/Jobs.java': SPRING_JOBS})
    assert any(anchor['kind'] == 'http' for anchor in facts['anchors'].values())
    missed = gaps(facts, 'likely_missed')
    # @GetMapping became an http anchor; the scheduled job did not.
    assert [(gap['framework'], gap['path'], gap['line']) for gap in missed] == [
        ('spring_scheduling', 'src/main/java/org/example/Jobs.java', 8)]
    assert not gaps(facts, 'language_unavailable')


def test_detected_react_route_is_not_reported(tmp_path):
    routes = '''import * as React from 'react';
import { Route } from 'react-router';
import Home from './Home';

export default () => (
  <Route component={Home}>
    <Route path='/' component={Home} />
  </Route>
);
'''
    home = "import * as React from 'react';\nexport default () => <div>Home</div>;\n"
    facts = extract(tmp_path, {'src/routes.tsx': routes, 'src/Home.tsx': home})
    assert any(anchor['kind'] == 'ui' for anchor in facts['anchors'].values())
    assert gaps(facts, 'likely_missed') == []


def test_zero_entry_points_always_have_a_coverage_entry(tmp_path):
    facts = extract(tmp_path, {'lib/util.py': 'def add(a, b):\n    return a + b\n'})
    assert facts['anchors'] == {}
    entries = gaps(facts)
    assert [(gap['kind'], gap['files'], gap['message']) for gap in entries] == [
        ('none_detected', 1,
         'No entry points detected; no entry-point markers found in 1 analyzed file')]
    assert [w['code'] for w in facts['warnings']] == ['ENTRYPOINT_NONE_DETECTED']


def test_language_gap_explains_a_zero_entry_point_run(tmp_path):
    facts = extract(tmp_path, {'Lib/Order.cs': 'public class Order {}\n'})
    assert facts['anchors'] == {}
    assert [gap['kind'] for gap in gaps(facts)] == ['language_unavailable']


def test_files_that_cannot_hold_entry_points_produce_no_warnings(tmp_path):
    facts = extract(tmp_path, {
        'app.py': "@app.get('/orders')\ndef orders():\n    return 1\n",
        'wwwroot/site.css': 'body { color: red; }\n',
        'wwwroot/theme.scss': '$c: red;\n',
        'wwwroot/logo.svg': '<svg xmlns="http://www.w3.org/2000/svg"></svg>\n',
        'src/App/App.csproj': '<Project Sdk="Microsoft.NET.Sdk"></Project>\n',
        'Directory.Build.props': '<Project></Project>\n',
        'Directory.Build.targets': '<Project></Project>\n',
        'Platforms/iOS/Info.plist': '<?xml version="1.0"?><plist></plist>\n',
        'eShop.sln': 'Microsoft Visual Studio Solution File\n',
        'package-lock.json': '{"lockfileVersion": 3}\n',
        'yarn.lock': '# yarn lockfile v1\n',
        'pnpm-lock.yaml': "lockfileVersion: '9.0'\n",
        'Cargo.lock': 'version = 3\n',
        'Gemfile.lock': 'GEM\n',
        'poetry.lock': '[[package]]\n'})
    assert facts['warnings'] == []
    assert facts['coverage']['unsupported_source_ids'] == []
    assert facts['coverage']['entrypoint_gaps'] == []


def test_files_that_can_hold_behavior_still_warn(tmp_path):
    facts = extract(tmp_path, {
        'app.py': "@app.get('/orders')\ndef orders():\n    return 1\n",
        'Views/CatalogView.xaml': XAML_PAGE,
        'appsettings.json': '{"Ordering": {"GracePeriod": 1}}\n'})
    unavailable = sorted(w['message'].split(':')[0] for w in facts['warnings']
                         if w['code'] == 'SOURCE_CAPABILITY_UNAVAILABLE')
    assert unavailable == ['Views/CatalogView.xaml', 'appsettings.json']
    assert [(gap['framework'], gap['path']) for gap in gaps(facts, 'likely_missed')] == [
        ('maui_xaml', 'Views/CatalogView.xaml')]


def test_entrypoint_entries_and_warnings_must_correspond(tmp_path):
    facts = extract(tmp_path, {'Lib/Order.cs': 'public class Order {}\n'})
    validate_source_warning_coverage(facts)
    dropped = copy.deepcopy(facts)
    dropped['warnings'] = [w for w in dropped['warnings']
                           if w['code'] not in GAP_CODES]
    with pytest.raises(DomainError):
        validate_source_warning_coverage(dropped)
    hidden = copy.deepcopy(facts)
    hidden['coverage']['entrypoint_gaps'] = []
    with pytest.raises(DomainError):
        validate_source_warning_coverage(hidden)


def _complete_model(entrypoint_gaps):
    return {'coverage': {'anchors_pending': 0, 'entrypoint_gaps': entrypoint_gaps},
            'limits': {'truncated': False}, 'capabilities': [],
            'traces': {}, 'information_uses': {}, 'activities': {}, 'domains': {},
            'ownerships': {}, 'rules': {}, 'claims': {}, 'unassigned': []}


def test_any_entrypoint_gap_publishes_partial(tmp_path):
    facts = extract(tmp_path, {'Lib/Order.cs': 'public class Order {}\n'})
    assert publication_status(_complete_model([]), 'not_applicable') == 'complete'
    assert publication_status(_complete_model(
        facts['coverage']['entrypoint_gaps']), 'not_applicable') == 'partial'


def test_terminal_summary_lists_entrypoint_coverage(tmp_path):
    facts = extract(tmp_path, {
        'src/OrdersApi.cs': MINIMAL_API, 'Pages/Cart.razor': '@page "/cart"\n'})
    payload = tmp_path / 'result.json'
    payload.write_text(json.dumps({
        'artifact': '.speed/context/business-domain-facts.json', 'trace_blockers': [],
        'measurements': {'traces': {'total': 0, 'resolved': 0, 'ambiguous': 0, 'unresolved': 0},
                         'call_targets': {'unresolved': 0, 'unresolved_by_language': {}}},
        'coverage': facts['coverage'], 'warnings': facts['warnings']}))
    rendered = subprocess.run(
        ['bash', '-c', f'source lib/cmd/domains.sh; _domains_render_facts "{payload}"'],
        cwd=SPEED_ROOT, capture_output=True, text=True, check=True).stdout.splitlines()
    start = rendered.index('Entry-point coverage:')
    # The warnings block (a total, then one row per code) ends just before it.
    header = next(index for index, line in enumerate(rendered) if line.startswith('Warnings:'))
    assert rendered[header] == f"Warnings:        {len(facts['warnings'])}"
    rows = rendered[header + 1:start - 1]
    assert rows and all(line.startswith('  ') for line in rows)
    assert sum(int(line.split()[-1]) for line in rows) == len(facts['warnings'])
    assert rendered[start + 1:start + 5] == [
        '  C#: 1 file, entry-point detection unavailable',
        '  Likely missed entry points: 4 (3 http_route, 1 page)',
        '    http_route: aspnetcore_minimal_api 3',
        '    page: blazor 1']
    assert rendered[-2:] == ['Facts written to:', '.speed/context/business-domain-facts.json']


# ── A marker whose method and route equal a known entry point ────────────

ORDERS_CONTRACT = """openapi: 3.0.1
info: {title: Orders, version: '1'}
paths:
  /api/orders/{id}:
    get:
      operationId: getOrder
      responses: {'200': {description: OK}}
  /api/orders:
    post:
      operationId: createOrder
      responses: {'201': {description: Created}}
"""


def test_a_route_known_from_its_contract_is_still_missed_and_says_so(tmp_path):
    facts = extract(tmp_path, {
        'src/Orders.API/openapi.yaml': ORDERS_CONTRACT,
        'src/Orders.API/OrdersApi.cs': (
            'var api = app.MapGroup("api/orders");\n'
            'api.MapGet("/{id:int}", GetOrder);\n'      # matches GET /api/orders/{id}
            'api.MapPost("/", CreateOrder);\n'          # matches POST /api/orders
            'api.MapDelete("/{id:int}", DeleteOrder);\n')})  # no such entry point
    # Every route is missed (its C# implementation is undetected); the two
    # a contract also declares say so.
    missed = {gap['line']: gap['message'] for gap in gaps(facts, 'likely_missed')}
    assert sorted(missed) == [2, 3, 4]
    assert missed[2].endswith('also declared as GET /api/orders/{id} by a known entry point')
    assert missed[3].endswith('also declared as POST /api/orders by a known entry point')
    assert 'also declared' not in missed[4]
    assert facts['coverage']['entrypoint_markers_matched'] == 2


def test_several_route_group_prefixes_leave_the_prefixed_route_unknown(tmp_path):
    facts = extract(tmp_path, {
        'src/Orders.API/openapi.yaml': ORDERS_CONTRACT,
        'src/Orders.API/OrdersApi.cs': (
            'var api = app.MapGroup("api/orders");\n'
            'var admin = app.MapGroup("admin/orders");\n'
            'api.MapGet("/{id:int}", GetOrder);\n')})
    [gap] = gaps(facts, 'likely_missed')
    assert gap['line'] == 3 and 'also declared' not in gap['message']
    assert facts['coverage']['entrypoint_markers_matched'] == 0


def test_route_keys_ignore_constraints_optional_markers_and_slashes():
    from lib.context.business_domain_entrypoints import route_key
    assert route_key('items/{id:int}/brand/{brandId?}/') == '/items/{id}/brand/{brandId}'
    assert route_key('/by/{name:minlength(1)}') == '/by/{name}'


def test_an_operation_pattern_must_name_its_method_and_path():
    raw = {'version': 1, 'kinds': {'http_route': 'route'},
           'coverage': {'categories': ['source'], 'non_entrypoint_languages': []},
           'display_names': {},
           'frameworks': {'custom': {'label': 'Custom', 'paths': ['.*\\.x'],
               'markers': [{'id': 'm', 'name': 'M', 'kind': 'http_route',
                            'pattern': 'ROUTE', 'operation': 'ROUTE (?P<path>\\S+)'}]}}}
    with pytest.raises(MarkerCatalogError):
        parse_catalog(raw)
