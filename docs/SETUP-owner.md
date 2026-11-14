# Owner setup

Run each step in Windows PowerShell. Steps marked (browser) happen on github.com. Replace `OWNER` with your GitHub handle and `TARGET` with a repository name.

## One time

1. Create the public repository and push this folder (needs `gh` signed in as you):

   ```powershell
   cd C:\Work\AI\personal\release-gate
   gh repo create OWNER/release-gate --public --source . --remote origin --push
   ```

2. (browser) Settings > Developer settings > GitHub Apps > New. Create the **gate App** with these repository permissions and nothing else: Contents read, Checks write, Pull requests read, Metadata read. No webhook. Note its App ID and slug, generate a private key (a `.pem` download), and install it on all repositories.

3. (browser) Create the **agent App**: Contents write, Pull requests write, Actions write, Metadata read. Nothing else: no Workflows, Administration, Environments, Secrets or Deployments. Install it on the repositories agents work in. Agents mint their tokens from this App, never from your own login.

4. (browser) release-gate repository > Settings > Environments > New environment `needles`. Deployment branches: selected branches, `main`. Add these environment secrets:

   | Secret | Value |
   |---|---|
   | `NEEDLES` | your private-name list, one per line |
   | `ACCEPTED` | accepted scan lines, one per line (`./path:matched line`) |
   | `GATE_APP_ID` | the gate App ID |
   | `GATE_APP_KEY` | the full text of the gate App `.pem` |

   From PowerShell, if you prefer (the file paths are yours; no agent reads them):

   ```powershell
   gh secret set NEEDLES   --env needles --repo OWNER/release-gate < "<path to your needles file>"
   gh secret set ACCEPTED  --env needles --repo OWNER/release-gate < "<path to your accepted file>"
   gh secret set GATE_APP_ID  --env needles --repo OWNER/release-gate --body "<gate App ID>"
   gh secret set GATE_APP_KEY --env needles --repo OWNER/release-gate < "<path to the .pem>"
   ```

   You alone edit `ACCEPTED`: rerun the `ACCEPTED` command to change it.

5. Delete the `.pem` and keep one copy of NEEDLES and ACCEPTED in your password manager. Move the local copies out of every folder an agent can read.

6. Take your own GitHub credential away from places agents reach on this PC: run `gh auth logout`, remove any saved token from agent environments and git credential stores, and from then on let agents authenticate only as the agent App.

7. Run the gate once by hand to confirm the setup:

   ```powershell
   gh workflow run gate.yml --repo OWNER/release-gate
   gh run list --workflow gate.yml --repo OWNER/release-gate --limit 1
   ```

## Per target repository

1. Install both Apps on `TARGET`.
2. Add `.github/release-gate.toml` on its default branch (start from `examples/release-gate.toml`).
3. Preview, then apply the rules (`--gate-app-id` is the gate App ID, `--owner-id` is your numeric GitHub user id, from `gh api user --jq .id`):

   ```powershell
   py -3 tools\apply_rules.py --repo OWNER/TARGET --gate-app-id <id> --owner-id <id>
   py -3 tools\apply_rules.py --repo OWNER/TARGET --gate-app-id <id> --owner-id <id> --apply
   ```

4. On PyPI, add a trusted publisher for `TARGET` naming workflow `publish-pypi.yml` (the caller's workflow file) and environment `pypi`.
5. Add the caller workflow described at the top of `.github/workflows/publish-pypi.yml` to `TARGET`, with the gate App slug.

Only you run `--apply`. Agents run the dry run.
