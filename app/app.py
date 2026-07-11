# Thin Dash view over protein_selector.webapp.data (PLAN.md §14). No
# business logic lives here -- see webapp/data.py for the only tested code.
# Excluded from ruff/ty, same treatment as notebooks/ (see pyproject.toml).
import json
from pathlib import Path

import dash
import dash_bootstrap_components as dbc
import dash_cytoscape as cyto
import pandas as pd
import plotly.express as px
from dash import Input, Output, dash_table, dcc, html

from protein_selector.core.db import DEFAULT_DB_PATH
from protein_selector.webapp.data import candidate_graph, load_report_df

# Resolve the db path the same cwd-fallback way notebooks/db_explorer.ipynb
# does: prefer a real DB next to this script's repo root, fall back to the
# default relative path (works whether launched from repo root or app/).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_CANDIDATE_DB_PATHS = [
    _REPO_ROOT / "notebooks" / "cache" / "protein_selector_real.db",
    _REPO_ROOT / DEFAULT_DB_PATH,
    DEFAULT_DB_PATH,
]
DB_PATH = next((p for p in _CANDIDATE_DB_PATHS if p.exists()), _CANDIDATE_DB_PATHS[-1])

report_df = load_report_df(DB_PATH)

# Link-out columns (PLAN.md §14b) -- pure presentation, no new fetched data.
# RCSB/UniProt/ligand URL patterns below are live-verified (§14b) or
# well-known canonical patterns. The AlphaFold DB entry-page pattern is
# added per explicit request but is NOT independently verifiable the same
# way: it's a JS single-page app -- a raw `curl` of the page (checked
# 2026-07-11) shows a generic app shell with no accession-specific content
# in the static HTML, so an automated fetch can neither confirm nor deny it
# resolves correctly. Confirm once in a real browser (e.g. P69905) before
# trusting it for real use.
_RCSB_STRUCTURE_URL = "https://www.rcsb.org/structure/{}"
_UNIPROT_URL = "https://www.uniprot.org/uniprotkb/{}"
_RCSB_LIGAND_URL = "https://www.rcsb.org/ligand/{}"
_ALPHAFOLD_ENTRY_URL = "https://alphafold.ebi.ac.uk/entry/{}"  # ⚠ candidate, see above

# Columns whose values are JSON-encoded lists/dicts (core.report._flatten_row
# JSON-dumps them for CSV/DataFrame safety, PLAN.md §7b) -- unreadable as a
# raw string in a table cell, dropped from the Proteins tab entirely rather
# than rendered badly. `suitable_for` is still visible per-protein via the
# `*_status` columns; the full rationale moved to the Explore tab's detail
# panel (below), not lost, just relocated.
_LIST_OR_DICT_COLUMNS = [
    "suitable_for",
    "modeling_notes",
    "md_simulation_notes",
    "docking_notes",
    "rationale_json",
]


def _markdown_link(value, url_template: str, label=None) -> str:
    """A `[label](url)` markdown link, or empty string for a missing value.

    dash_table renders empty string cleanly for a missing/None cell;
    passing None itself through a markdown-presentation column would
    literally render the text "None". `label` defaults to `value` itself
    (e.g. RCSB/UniProt links); pass it explicitly when the URL needs a
    different key than what should be displayed (e.g. the AlphaFold link
    below is built from ``uniprot_id`` but should display the AF entry id).
    """
    if pd.isna(value):
        return ""
    return f"[{label if label is not None else value}]({url_template.format(value)})"


# A separate display copy: link-formatted id columns, list/dict columns
# dropped (rationale_json rendered in the Explore tab's detail panel
# instead, see below -- a raw JSON string in a table cell is unreadable).
proteins_table_df = report_df.drop(columns=_LIST_OR_DICT_COLUMNS).copy()
proteins_table_df["pdb_id"] = proteins_table_df["pdb_id"].apply(
    lambda v: _markdown_link(v, _RCSB_STRUCTURE_URL)
)
proteins_table_df["uniprot_id"] = proteins_table_df["uniprot_id"].apply(
    lambda v: _markdown_link(v, _UNIPROT_URL)
)
proteins_table_df["ligand_ccd"] = proteins_table_df["ligand_ccd"].apply(
    lambda v: _markdown_link(v, _RCSB_LIGAND_URL)
)
# Built from the (unmodified) uniprot_id column, displayed as the AF entry
# id. Needs both present -- an entry id with no accession (shouldn't happen)
# or an accession with no AF entry (the normal "no AlphaFold DB entry
# exists" case, PLAN.md §4a) both mean there's nothing to link to.
proteins_table_df["modeling_alphafold_entry_id"] = [
    _markdown_link(uniprot_id, _ALPHAFOLD_ENTRY_URL, label=entry_id)
    if not pd.isna(uniprot_id) and not pd.isna(entry_id)
    else ""
    for uniprot_id, entry_id in zip(
        report_df["uniprot_id"], report_df["modeling_alphafold_entry_id"], strict=True
    )
]
_MARKDOWN_LINK_COLUMNS = {"pdb_id", "uniprot_id", "ligand_ccd", "modeling_alphafold_entry_id"}

_NODE_COLOR_BY_KIND = {
    "protein": "#4C78A8",
    "alphafold": "#72B7B2",
    "ligand": "#E45756",
    "pocket": "#F58518",
    "validation": "#54A24B",
}

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.FLATLY])
app.title = "Protein Selector"

proteins_tab = dbc.Container(
    [
        dash_table.DataTable(
            id="proteins-table",
            columns=[
                {
                    "name": c,
                    "id": c,
                    **(
                        {"presentation": "markdown"}
                        if c in _MARKDOWN_LINK_COLUMNS
                        else {}
                    ),
                }
                for c in proteins_table_df.columns
            ],
            data=proteins_table_df.to_dict("records"),
            filter_action="native",
            sort_action="native",
            page_size=20,
            # Stated tradeoff, not a silent gap: CSV export writes the raw
            # cell values, so the id columns export as markdown link syntax
            # (e.g. "[4HHB](https://...)"), not bare ids. The vendored,
            # instructor-facing CSV export stays core.report.write_report_csv
            # (§8/§12) -- this export button is a convenience for whatever's
            # currently filtered in the browser, not the published artifact.
            export_format="csv",
            # No max-width cap: dash_table's per-column drag-resize (native,
            # on by default) only works up to whatever `maxWidth` allows --
            # the previous "maxWidth": "200px" silently capped every column
            # at 200px regardless of how far a user dragged it. `minWidth`
            # keeps narrow columns (e.g. booleans) from collapsing to
            # nothing; deliberately no other styling -- this table is a data
            # grid, not meant to look polished.
            style_table={"overflowX": "auto"},
            style_cell={"textAlign": "left", "minWidth": "60px"},
        ),
    ],
    fluid=True,
    class_name="mt-3",
)

results_tab = dbc.Container(
    [
        dcc.Graph(id="difficulty-scatter"),
        dcc.Graph(id="status-bars"),
    ],
    fluid=True,
    class_name="mt-3",
)

explore_tab = dbc.Container(
    [
        dbc.Row(
            [
                dbc.Col(
                    dcc.Dropdown(
                        id="explore-pdb-id",
                        options=[{"label": p, "value": p} for p in report_df["pdb_id"]],
                        value=report_df["pdb_id"].iloc[0] if len(report_df) else None,
                    ),
                    width=4,
                )
            ],
            class_name="mt-3 mb-3",
        ),
        dbc.Row(
            [
                dbc.Col(
                    cyto.Cytoscape(
                        id="connections-graph",
                        layout={"name": "cose"},
                        style={"width": "100%", "height": "500px"},
                        elements=[],
                        stylesheet=[
                            {"selector": "node", "style": {"label": "data(label)"}},
                            *(
                                {
                                    "selector": f".{kind}",
                                    "style": {"background-color": color},
                                }
                                for kind, color in _NODE_COLOR_BY_KIND.items()
                            ),
                        ],
                    ),
                    width=8,
                ),
                dbc.Col(
                    dash_table.DataTable(
                        id="ligand-detail-table",
                        columns=[
                            {"name": "ligand_ccd", "id": "ligand_ccd"},
                            {"name": "meeko_parameterizable", "id": "meeko_parameterizable"},
                        ],
                        data=[],
                    ),
                    width=4,
                ),
            ]
        ),
        dbc.Row(
            dbc.Col(
                [
                    html.H5("Rationale", className="mt-3"),
                    # rationale_json (dropped from the Proteins table above,
                    # PLAN.md §14b) rendered here instead, pretty-printed --
                    # already a JSON string at the data layer
                    # (core.report._flatten_row), never a raw dict.
                    dcc.Markdown(id="rationale-detail"),
                ]
            )
        ),
    ],
    fluid=True,
)

app.layout = dbc.Container(
    [
        html.H2("Protein Selector", className="mt-3"),
        html.P(f"Reading: {DB_PATH}", className="text-muted"),
        dbc.Tabs(
            [
                dbc.Tab(proteins_tab, label="Proteins"),
                dbc.Tab(results_tab, label="Results"),
                dbc.Tab(explore_tab, label="Explore"),
            ]
        ),
    ],
    fluid=True,
)


@app.callback(
    Output("difficulty-scatter", "figure"),
    Output("status-bars", "figure"),
    Input("proteins-table", "id"),  # fires once on load; report_df is static per session
)
def render_result_charts(_):
    long_rows = []
    for exercise in ("modeling", "md_simulation", "docking"):
        predicted_col = f"{exercise}_predicted_difficulty"
        measured_col = f"{exercise}_measured_difficulty"
        tier_col = f"{exercise}_tier"
        status_col = f"{exercise}_status"
        if predicted_col not in report_df.columns:
            continue
        sub = report_df[["pdb_id", predicted_col, measured_col, tier_col, status_col]].copy()
        sub = sub.dropna(subset=[measured_col])
        sub["exercise"] = exercise
        sub.columns = ["pdb_id", "predicted", "measured", "tier", "status", "exercise"]
        long_rows.append(sub)

    if long_rows:
        scatter_df = pd.concat(long_rows, ignore_index=True)
        scatter_fig = px.scatter(
            scatter_df,
            x="predicted",
            y="measured",
            color="tier",
            facet_col="exercise",
            hover_data=["pdb_id"],
            title="Predicted vs. measured difficulty",
        )
    else:
        scatter_fig = px.scatter(title="No validated candidates yet")

    status_cols = [c for c in report_df.columns if c.endswith("_status")]
    if status_cols:
        status_long = report_df[["pdb_id", *status_cols]].melt(
            id_vars="pdb_id", var_name="exercise", value_name="status"
        )
        status_long["exercise"] = status_long["exercise"].str.replace("_status", "")
        counts = status_long.groupby(["exercise", "status"]).size().reset_index(name="count")
        bars_fig = px.bar(
            counts,
            x="exercise",
            y="count",
            color="status",
            title="Validation status per exercise",
        )
    else:
        bars_fig = px.bar(title="No validation data yet")

    return scatter_fig, bars_fig


@app.callback(
    Output("connections-graph", "elements"),
    Output("ligand-detail-table", "data"),
    Output("rationale-detail", "children"),
    Input("explore-pdb-id", "value"),
)
def render_connections_graph(pdb_id):
    if pdb_id is None:
        return [], [], ""

    graph = candidate_graph(pdb_id, DB_PATH)
    elements = [
        {
            "data": {"id": n.id, "label": n.label},
            "classes": n.kind,
        }
        for n in graph.nodes
    ] + [{"data": {"source": e.source, "target": e.target}} for e in graph.edges]

    ligand_rows = [
        {"ligand_ccd": n.label, "meeko_parameterizable": n.passed}
        for n in graph.nodes
        if n.kind == "ligand"
    ]

    matching_rows = report_df.loc[report_df["pdb_id"] == pdb_id, "rationale_json"]
    if matching_rows.empty:
        rationale_markdown = "_no report row for this candidate_"
    else:
        rationale = json.loads(matching_rows.iloc[0])
        rationale_markdown = f"```json\n{json.dumps(rationale, indent=2)}\n```"

    return elements, ligand_rows, rationale_markdown


if __name__ == "__main__":
    app.run(debug=True)
