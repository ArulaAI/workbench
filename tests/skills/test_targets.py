from skills.targets import detect_surfaces, dest_dir, SURFACES


def test_claude_detected_when_dot_claude_present(tmp_project):
    ids = [s.id for s in detect_surfaces(tmp_project)]
    assert ids == ["claude_code"]


def test_no_surface_when_absent(tmp_path):
    assert detect_surfaces(tmp_path) == []


def test_dest_dir_layout(tmp_project):
    s = SURFACES[0]
    d = dest_dir(s, "workbench-draft", tmp_project)
    assert d == tmp_project / ".claude" / "skills" / "workbench-draft"
