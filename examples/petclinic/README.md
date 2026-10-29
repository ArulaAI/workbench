# Business-domain discovery on PetClinic

Run SPEED's business-domain discovery on the Spring PetClinic React app and publish its business model to `.speed/context/business-domains.json`. One command runs the whole pipeline: Extract, Synthesize (with Verify and Repair), Validate and Publish.

## Before you start

You need these once per machine:

- SPEED installed in `~/workbench`, with its Python environment in `~/workbench/.venv` and the grammar libraries built. See [Installation](../../docs/installation.md).
- The Claude Code CLI (`claude`) installed and logged in to an account with Opus access.
- `git`.

## Step 1: get the latest SPEED code

Run in the workbench repo whenever new code is pushed.

```bash
cd ~/workbench
git fetch
git checkout feat/business-domain-core
git pull
```

## Step 2: prepare PetClinic (first time only)

Clone PetClinic at the tested version and copy in its configuration.

```bash
git clone https://github.com/spring-petclinic/spring-petclinic-reactjs.git ~/spring-petclinic-reactjs
cd ~/spring-petclinic-reactjs
git checkout 4a6c26d
cp ~/workbench/examples/petclinic/speed.toml speed.toml
```

`git checkout 4a6c26d` pins PetClinic to the version these steps were tested on, so a later change to PetClinic cannot change the result. Git reports a "detached HEAD" state, which is expected.

`speed.toml` must sit in the PetClinic folder, because SPEED reads it from the folder it runs in. Discovery's defaults already use Opus and the time and budgets below, so a run without this file also works; copying it pins the exact tested setup, including the 450,000-token request size that splits PetClinic into 6 parts:

| Setting | Value | Why |
| --- | --- | --- |
| `support_model` | `opus` | The model used for synthesis and verification. Without this file SPEED builds with Sonnet |
| `timeout` | 5400 seconds | One synthesis call can take close to an hour |
| `max_request_input_tokens` | 450,000 | Splits PetClinic into 6 parts plus a final join |
| `max_build_input_tokens` | 20,000,000 | Total input budget for the whole run, including repairs |
| `max_build_output_tokens` | 4,000,000 | Room for a run with repairs |
| `provider_concurrency` | 4 | Up to four parts are worked on at the same time |
| `deadline_seconds` | 28,800 | A full run takes about 1.5 to 2 hours; this leaves room for a paused run |

## Step 3: run discovery

Run in the PetClinic folder.

```bash
cd ~/spring-petclinic-reactjs
export PATH="$HOME/workbench:$PATH"
caffeinate -i speed discover domains
```

A run takes 15 to 70 minutes, depending on how many repair rounds the model needs. Keep the laptop plugged in with the lid open. `caffeinate -i` stops macOS from sleeping while it runs.

If your Python environment is somewhere other than `~/workbench/.venv`, also run `export SPEED_PYTHON=/path/to/your/venv/bin/python` before the last command.

## Check the result

A successful run ends with output like this:

```
Started:     2026-10-05T15:50:54+00:00
Completed:   2026-10-05T16:20:54+00:00
Published:   yes (build d6724a90-...)
Anchors:     47/52 processed
Warnings:    863
```

`Published: yes` means all four stages passed. The model is in `.speed/context/business-domains.json`. To see the last run's status again:

```bash
speed discover domains --status
```

A second run on the same machine can finish in seconds, because SPEED reuses an earlier verified result when its input is unchanged.

## If something goes wrong

| Message | Fix |
| --- | --- |
| `speed: command not found` | Run the `export PATH=...` line in this Terminal window |
| `BUILD_BUDGET` or `BUILD_TIMEOUT` | The run needed more budget or time than `speed.toml` allows; raise the setting the message names, or repeat the `cp` line in Step 2 if the file was changed |
| `Cannot load custom language library` | Build the grammars: `cd ~/workbench && ./scripts/build-grammars.sh` |
| `SEMANTIC_VERIFICATION_FAILED` | The model did not converge within 4 repairs. Run Step 3 again; model output varies between runs |
