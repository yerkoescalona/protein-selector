#!/bin/bash
#SBATCH --job-name=protein-selector
#SBATCH --output=slurm/logs/%x-%j.out
#SBATCH --error=slurm/logs/%x-%j.err
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --time=08:00:00
# --- GPU: uncomment when a lane actually needs one. Nothing in the screening pipeline
# --- does today; this is here for the design work PLAN.md §30 anticipates.
# SBATCH --gres=gpu:1
#
# Run the pipeline as ONE SLURM job holding a private Ray cluster (PLAN.md §38b).
#
# WHY ONE ALLOCATION AND NOT MANY SMALL JOBS. Snakemake's SLURM executor submitted one
# sbatch per candidate, which backfills well on a busy cluster. Ray does not work that way:
# the driver and its workers must live inside a single allocation. That trade is recorded
# honestly in §30e -- many small right-sized jobs versus one held block. On a busy queue the
# small jobs usually start sooner; inside the allocation Ray has no per-task latency and can
# keep model weights resident. Measure it on your cluster (§33e Y.4) rather than assuming.
#
# THE PYTHON VERSION RULE (§37b). Ray requires the cluster and every driver to share an
# EXACT Python version, patch included, so this script uses ONE interpreter throughout. If
# any slow lane is enabled in workflow/config.yaml it must be the validation conda env --
# the only one carrying openmm/vina/fpocket/ambertools.
#
#   sbatch slurm/run_pipeline.sbatch
#   sbatch --export=ALL,PS_CONFIG=workflow/config-big.yaml slurm/run_pipeline.sbatch
#
set -euo pipefail

PS_ROOT="${PS_ROOT:-${SLURM_SUBMIT_DIR:-$PWD}}"
PS_CONFIG="${PS_CONFIG:-workflow/config.yaml}"
PS_DB="${PS_DB:-cache/protein_selector.db}"
PS_IDS="${PS_IDS:-results/candidate_ids.txt}"
PS_ENV="${PS_ENV:-$HOME/miniconda3/envs/protein-selector-validation}"
PS_PYTHON="${PS_PYTHON:-$PS_ENV/bin/python}"

cd "$PS_ROOT"
mkdir -p slurm/logs

echo "host        : $(hostname)"
echo "job         : ${SLURM_JOB_ID:-none}"
echo "cpus        : ${SLURM_CPUS_PER_TASK:-?}"
echo "config      : $PS_CONFIG"
echo "interpreter : $PS_PYTHON ($("$PS_PYTHON" -c 'import sys;print(sys.version.split()[0])'))"

# Dry run first: free, needs no cluster, and a graph error here costs seconds instead of
# the whole allocation (§35c).
"$PS_PYTHON" scripts/run_ray_pipeline.py --graph
"$PS_PYTHON" scripts/run_ray_pipeline.py --plan --db-path "$PS_DB"

# No `ray start`: the driver brings up its own cluster inside this allocation and tears it
# down on exit, so a cancelled job leaves nothing behind. --cpus comes from SLURM's own
# allocation rather than a guess, which is what stops Ray oversubscribing the cores SLURM
# granted -- the same constraint §15 originally gave Snakemake's scheduler.
"$PS_PYTHON" scripts/run_ray_pipeline.py \
    --run \
    --config "$PS_CONFIG" \
    --db-path "$PS_DB" \
    --ids "$PS_IDS" \
    --cpus "${SLURM_CPUS_PER_TASK:-4}" \
    --run-id "slurm-${SLURM_JOB_ID:-local}"

"$PS_PYTHON" scripts/run_ray_pipeline.py --plan --db-path "$PS_DB" | tail -3
