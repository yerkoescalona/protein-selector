# SLURM setup — single node, this workstation

State when this was written (verified, not assumed):

| | |
|---|---|
| slurm-wlm 24.11.5 | installed (client, server, plugins) ✓ |
| munge | **active** ✓ |
| `slurm` user | exists, uid 64030 ✓ |
| `/var/log/slurm` | exists, `slurm:slurm` ✓ |
| **`/etc/slurm/slurm.conf`** | **missing** ← the only blocker |
| `slurmd` / `slurmctld` | failed / inactive (they cannot start without the config) |

So this is not an install — it is one config file plus two spool directories.

Every step below needs `sudo`, which this machine does not grant passwordlessly, so run
them yourself. `slurm/slurm.conf` is already generated **for this exact hardware**.

---

## 1. Spool directories

`slurmctld` stores job state here and `slurmd` its working data. Both daemons refuse to
start if the directory is missing or owned by the wrong user — a common first failure.

```bash
sudo mkdir -p /var/spool/slurmctld /var/spool/slurmd /var/log/slurm
sudo chown slurm:slurm /var/spool/slurmctld /var/log/slurm
sudo chmod 755 /var/spool/slurmctld /var/spool/slurmd
```

`/var/spool/slurmd` stays **root-owned**: `slurmd` runs as root so it can set up job
processes for any user.

## 2. Install the config

```bash
sudo install -m 644 slurm/slurm.conf /etc/slurm/slurm.conf
```

Read it first — it is commented, and two lines matter most:

- **`NodeName=... RealMemory=30000`** — deliberately below the physical 31217 MB. If the
  config claims more memory than the machine reports, SLURM drains the node.
- **`ProctrackType=proctrack/linuxproc` / `TaskPlugin=task/none`** — simple tracking. On a
  real cluster you would use `proctrack/cgroup`, but that needs a matching `cgroup.conf`
  and cgroup-v2 delegation, and getting it wrong makes every job fail to launch with an
  unhelpful error. Get the basic cluster working first, then switch if you want
  enforcement.

## 3. Start the daemons

```bash
sudo systemctl enable --now slurmctld slurmd
systemctl --no-pager status slurmctld slurmd | grep -E "Active|●"
```

## 4. Verify

```bash
sinfo                       # partition `local`, node `debian`, state `idle`
srun -n1 hostname           # should print: debian
scontrol show node debian | grep -E "CPUAlloc|CPUTot|RealMemory|State"
```

**If the node shows `down` or `drain`**, the reason is almost always a mismatch between
`slurm.conf` and reality. Ask SLURM what it thinks:

```bash
scontrol show node debian | grep Reason
sudo scontrol update NodeName=debian State=RESUME     # after fixing the cause
```

## 5. Run the pipeline

```bash
sbatch slurm/run_pipeline.sbatch
squeue -u "$USER"
tail -f slurm/logs/protein-selector-<jobid>.out
```

The script requests `--cpus-per-task=8` and `--mem=16G`; this node has 16 CPUs and 30 GB
declared, so two such jobs can run concurrently. Adjust the `#SBATCH` lines rather than the
config if you want a different shape.

## 6. Optional — `sacct` and job history

The config uses `accounting_storage/none`, which keeps the setup to two daemons. The cost,
stated plainly: **`sacct` will not work.** Use `squeue` for running jobs and
`scontrol show job <id>` for recent ones.

Real history needs `slurmdbd` plus MariaDB/MySQL:

```bash
sudo apt install slurmdbd mariadb-server
# then configure /etc/slurm/slurmdbd.conf and set
#   AccountingStorageType=accounting_storage/slurmdbd
# in /etc/slurm/slurm.conf, and restart both daemons.
```

Worth doing if you want per-job CPU/memory history to size `#SBATCH` requests from measured
data rather than guesses — which is exactly what PLAN.md §29e O.1 wanted `benchmark:` for.
Not needed to run anything.

## 7. Why one allocation, not many jobs

`slurm/run_pipeline.sbatch` runs the whole pipeline inside **one** allocation holding a
private Ray cluster. Snakemake's SLURM executor used to submit one job per candidate, which
backfills better on a busy queue. Ray cannot work that way — its driver and workers must
share an allocation. PLAN.md §30e records the trade; §33e **Y.4** says to measure it on a
real cluster rather than argue about it, and this setup is what makes that measurement
possible.

**The Python-version rule (§37b)** applies here too: the driver inside the job must be the
validation conda env whenever a slow lane is enabled, because Ray requires cluster and
driver to share an exact Python version. The sbatch script already uses `PS_PYTHON` for
that, defaulting to the validation env.
