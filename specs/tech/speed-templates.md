# RFC: Spec Templates

> See [product spec](../product/speed-templates.md) for product context.
> Parent RFC: [Unified Intake & Defect Pipeline](../unified-intake.md)

## Implementation

### New CLI command: `speed new`

Add `cmd_new()` function to `speed/speed`. Subcommands:

```bash
./speed/speed new prd <name>        # → specs/product/<name>.md
./speed/speed new rfc <name>        # → specs/tech/<name>.md
./speed/speed new design <name>     # → specs/design/<name>.md
./speed/speed new defect <name>     # → specs/defects/<name>.md
```

### Command behavior

1. Map subcommand to template file and output directory:
   | Subcommand | Template | Output dir |
   |------------|----------|------------|
   | `prd` | `speed/templates/prd.md` | `specs/product/` |
   | `rfc` | `speed/templates/rfc.md` | `specs/tech/` |
   | `design` | `speed/templates/design.md` | `specs/design/` |
   | `defect` | `speed/templates/defect.md` | `specs/defects/` |

2. Check if output file already exists → warn and exit (no overwrite)
3. Create output directory if it doesn't exist (`mkdir -p`)
4. Copy template to output path
5. Replace placeholders:
   - `{Feature Name}` → humanized name (e.g., `my-feature` → `My Feature`)
   - `{name}` → raw name as provided
   - `{n}` → left as `{n}` (author fills in the feature number)
   - `{product-spec}` → `specs/product/<name>.md` (auto-filled for RFC and design templates, used as both link text and URL)
   - `{dep}` → left as `{dep}` (author fills in dependencies)
6. Open in `$EDITOR` if set, otherwise print the file path

### Template files

Four new files in `speed/templates/`:

| File | Content |
|------|---------|
| `prd.md` | PRD template from parent RFC §Spec Templates, Template 1 |
| `rfc.md` | RFC template from parent RFC §Spec Templates, Template 2 |
| `design.md` | Design template from parent RFC §Spec Templates, Template 3 |
| `defect.md` | Defect template from parent RFC §Spec Templates, Template 4 |

The existing `spec.md` generic template is kept for backwards compatibility.

### Placeholder replacement

Simple `sed` substitution. No templating engine.

```bash
sed -e "s/{Feature Name}/${humanized_name}/g" \
    -e "s/{name}/${name}/g" \
    -e "s|{product-spec}|specs/product/${name}.md|g" \
    "$template" > "$output"
```

Humanization: replace hyphens with spaces, capitalize first letter of each word:

```bash
humanized=$(echo "$name" | tr '-' ' ' | awk '{for(i=1;i<=NF;i++) $i=toupper(substr($i,1,1)) substr($i,2)} 1')
# my-feature → My Feature
```

Note: `sed 's/\b\(\w\)/\u\1/g'` works on GNU sed but not macOS. The `awk` approach is portable.

### Validation

- `name` is required (exit with `EXIT_CONFIG_ERROR` if missing)
- `name` must match `^[a-z0-9]([a-z0-9-]*[a-z0-9])?$` (lowercase alphanumeric + hyphens, no leading/trailing hyphens)
- Subcommand must be one of: `prd`, `rfc`, `design`, `defect`

### Error handling

| Condition | Behavior |
|-----------|----------|
| Missing name argument | Print usage, exit 3 (`EXIT_CONFIG_ERROR`) |
| Invalid name (fails regex) | Print error with valid format example, exit 3 |
| Invalid subcommand | Print usage with valid subcommands, exit 3 |
| Output file exists | Print warning with path, exit 3 (no overwrite) |
| Template file missing | Print error (installation issue), exit 3 |
| `$EDITOR` not set | Print file path instead of opening |

## Files changed

| File | Change |
|------|--------|
| `speed/speed` | Add `cmd_new()` function, add `new` to command dispatch and `speed_help()` |
| `speed/templates/prd.md` | Already exists — PRD template |
| `speed/templates/rfc.md` | Already exists — RFC template |
| `speed/templates/design.md` | Already exists — Design template |
| `speed/templates/defect.md` | Already exists — Defect report template |

## Dependencies

None. Pure bash, no new external tools.
