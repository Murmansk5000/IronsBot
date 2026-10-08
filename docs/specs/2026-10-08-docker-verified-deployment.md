# IronsBot verified deployment and scoped cleanup

Updates now run in a separate, one-shot IronsBot supervisor container rather than
delegating replacement to Watchtower. The existing `updater_container_id` handoff
field remains compatible. Legacy Watchtower settings remain readable but are not
used by the new deployment path.

The supervisor records the previous container's configuration in
`data/operations/docker_deployment.json` with mode 0600. It preserves the original
container until the target starts within 120 seconds and runs for another 60
seconds without a restart, exit, or OOM. A Linux file lock prevents concurrent
deployment transactions. It restores and verifies the original container on
failure. Successful/restored records omit the configuration snapshot, which may
contain secrets. A failed recovery retains the private snapshot for inspection.

After verification, the old stopped container is removed without deleting volumes.
Unused old public IronsBot images are removed without force. Matching rollback
tags and same-source GHCR tags are eligible; unrelated tags, container references,
private extensions, Watchtower, and unknown provenance are retained. Cleanup
failure never turns a successful deployment into a rollback.

## Manual deployment

Pull or import the intended image first. On a Linux Docker host with this checkout
and its Python dependencies, run:

```sh
python -m ironsbot.integrations.docker.deployment_launch \
  --container ironsbot --image murmansk5000/ironsbot:latest
```

`scripts/deploy_ironsbot.py` delegates to the same entrypoint. The target image
must contain the supervisor module. Existing mounts and credentials are reused;
this command does not change TOML, pull images, or modify other applications.
When first migrating from an older image without the supervised-boot guard,
disable its existing startup image check before the migration so a restored old
version cannot launch another updater; re-enable it after the migration succeeds.

## Legacy residue

From the checkout, explicitly request only the known backup:

```sh
python -m ironsbot.integrations.docker.deployment_cleanup \
  --legacy-backup ironsbot-before-master-20261008
```

This performs the same startup/stability verification before deleting anything.
The supplied legacy backup must be stopped, match the current mounts and image
source, and not be the live container. A missing backup is harmless. Cleanup
retains zero unused old public images; there is no global prune or TOML retention
setting. A production cleanup does not install the code or change the running
image. Docker/API failures are recorded as concise summaries, not environment
values or application log dumps.
