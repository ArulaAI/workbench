"""Keep executable validation harnesses out of pytest module collection.

These files remain runnable directly; they perform work and terminate at module
scope, so importing them as pytest tests is unsafe.
"""

collect_ignore = [
    "test_classify.py",
    "test_clustering.py",
    "test_convention_extractors.py",
    "test_convention_templates.py",
    "test_conventions.py",
    "test_e2e_backward_compat.py",
    "test_e2e_layer1.py",
    "test_e2e_layer2.py",
    "test_e2e_layer3.py",
    "test_e2e_pipeline.py",
    "test_extract_step3.py",
    "test_related_specs.py",
    "test_server_identity.py",
    "test_spec_trajectory_spec.py",
    "test_toml_security.py",
    "test_unit_layer1.py",
    "test_unit_layer2.py",
    "test_unit_layer3_verify.py",
]
