# GitHub collaboration

The private repository is [SHIN522/syringe-twin](https://github.com/SHIN522/syringe-twin). It includes local setup instructions, regression tests, GitHub Actions CI, and issue/PR templates.

A write-access invitation was sent to [shmizi](https://github.com/shmizi) on 6 October 2026. Access becomes active after acceptance; the collaborator can then contribute branches and pull requests. See [GitHub's personal-repository invitation instructions](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/repository-access-and-collaboration/inviting-collaborators-to-a-personal-repository).

## Working agreement

Use `main` for reviewed, working changes. Create `feature/...`, `fix/...`, or `docs/...` branches, push them, and open pull requests. The other collaborator reviews the behavior and the validation evidence. Squash merging keeps one focused commit per change.

For plans that support branch protection on the chosen repository visibility, configure `main` to require one approving review, resolved review conversations, and both CI checks:

- `Validate (ubuntu-latest, Python 3.11)`
- `Validate (windows-latest, Python 3.11)`

Select these checks after the workflow has run once. Disable force pushes and branch deletion. If the plan does not support protected private branches, follow the same PR agreement manually. See [GitHub's protected branch documentation](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches) for availability and settings.

## What CI covers

The workflow runs on pushes to `main`, pull requests, and manual dispatch. It installs `requirements-dev.txt`, builds the browser model bundle, checks Python/JavaScript syntax, and runs the regression suite on Windows and Ubuntu with Python 3.11. Ubuntu also exercises the Streamlit UI through AppTest. The workflow uses GitHub's read-only repository token and needs no configured secrets. It performs validation; it does not publish a site.

The official actions use their current major tags: [checkout v7](https://github.com/actions/checkout), [setup-python v7](https://github.com/actions/setup-python), and [setup-node v7](https://github.com/actions/setup-node). Runtime packages are installed according to the versions and ranges recorded in the requirements files.

## Before the first push

Confirm the owner/repository name and visibility. Check the staged files so local history, logs, credentials, and virtual environments remain excluded. Use [CONTRIBUTING.md](../CONTRIBUTING.md) to reproduce setup and validation on each collaborator's system.

No project license has been selected in this setup. The owner should choose a license before advertising reuse rights. The simulation currently implements the supplied system in Python; external PLC and medical hardware integration require separate engineering work.
