"""
app.py — Gas Demand Forecast Dashboard.

Run:
  python app.py
  Open: http://localhost:8050

Auto-refreshes every 60 seconds. Connect ActiveMQ listener (listener.py)
to get near-real-time updates as new data arrives.
"""

import sys
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, callback

sys.path.insert(0, str(Path(__file__).parent))
import data

# ── App ────────────────────────────────────────────────────────────────────────

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.DARKLY],
    title="Gas Demand Dashboard",
)

CARD_STYLE = {"textAlign": "center", "padding": "16px"}
ACCENT     = "#00bc8c"   # Bootstrap DARKLY green
WARN       = "#f39c12"
DANGER     = "#e74c3c"
MUTED      = "#6c757d"

SERIES_COLOURS = {
    "Actual":       "#ffffff",
    "NGT Forecast": "#95a5a6",
    "Linear Model": ACCENT,
    "GBM Model":    "#3498db",
}


# ── Layout ─────────────────────────────────────────────────────────────────────

app.layout = dbc.Container(fluid=True, children=[

    dcc.Interval(id="refresh", interval=60_000, n_intervals=0),

    # ── Header ────────────────────────────────────────────────────────────────
    dbc.Row(className="mb-3 mt-3", children=[
        dbc.Col(html.H3("Gas Demand Forecast", className="text-white mb-0"), width="auto"),
        dbc.Col(html.Small(id="last-updated", className="text-muted align-self-end"),
                className="text-end"),
    ]),

    # ── KPI cards ─────────────────────────────────────────────────────────────
    dbc.Row(id="kpi-cards", className="mb-3"),

    # ── 7-day forecast curve ──────────────────────────────────────────────────
    dbc.Row(className="mb-3", children=[
        dbc.Col(dbc.Card(dbc.CardBody([
            html.H5("7-Day Demand Outlook", className="card-title"),
            dcc.Graph(id="outlook-chart", style={"height": "300px"}),
        ])))
    ]),

    # ── Main chart — actuals vs forecasts ─────────────────────────────────────
    dbc.Row(className="mb-3", children=[
        dbc.Col(dbc.Card(dbc.CardBody([
            html.H5("Demand: Actuals vs Forecasts", className="card-title"),
            dcc.Graph(id="demand-chart", style={"height": "380px"}),
        ])))
    ]),

    # ── Supply balance + HDD scatter ──────────────────────────────────────────
    dbc.Row(className="mb-3", children=[
        dbc.Col(dbc.Card(dbc.CardBody([
            html.H5("Supply vs Demand Balance", className="card-title"),
            dcc.Graph(id="supply-chart", style={"height": "320px"}),
        ])), md=6),
        dbc.Col(dbc.Card(dbc.CardBody([
            html.H5("HDD vs Gas Demand", className="card-title"),
            dcc.Graph(id="hdd-chart", style={"height": "320px"}),
        ])), md=6),
    ]),

    # ── Model evaluation + active UMMs ────────────────────────────────────────
    dbc.Row(className="mb-4", children=[
        dbc.Col(dbc.Card(dbc.CardBody([
            html.H5("Model Evaluation", className="card-title"),
            html.Div(id="eval-table"),
        ])), md=5),
        dbc.Col(dbc.Card(dbc.CardBody([
            html.H5("Active ENTSOG UMMs", className="card-title"),
            html.Div(id="umm-table"),
        ])), md=7),
    ]),
])


# ── Callbacks ──────────────────────────────────────────────────────────────────

@callback(
    Output("last-updated",  "children"),
    Output("kpi-cards",     "children"),
    Output("outlook-chart", "figure"),
    Output("demand-chart",  "figure"),
    Output("supply-chart",  "figure"),
    Output("hdd-chart",     "figure"),
    Output("eval-table",    "children"),
    Output("umm-table",     "children"),
    Input("refresh", "n_intervals"),
)
def refresh(_):
    timestamp = f"Updated {datetime.now().strftime('%H:%M:%S')}"

    # ── KPI cards ──────────────────────────────────────────────────────────────
    latest = data.latest_forecasts()
    umms   = data.active_umms()

    def forecast_card(model_name: str, label: str, colour: str):
        row = latest[latest["model_name"] == model_name]
        if row.empty:
            value, sub = "—", "No forecast yet"
        else:
            r     = row.iloc[0]
            value = f"{r['forecast_demand_mcm']:.0f} mcm/d"
            sub   = f"HDD {r['hdd']:.1f}  Wind {r['avg_wind_ms']:.1f} m/s"
        return dbc.Col(dbc.Card(dbc.CardBody([
            html.Small(label, className="text-muted"),
            html.H3(value, style={"color": colour}),
            html.Small(sub, className="text-muted"),
        ], style=CARD_STYLE)))

    umm_cap = umms["unavailableCapacity"].sum() if not umms.empty else 0
    umm_n   = len(umms)
    umm_col = DANGER if umm_cap > 100 else (WARN if umm_cap > 0 else ACCENT)

    kpi = [
        forecast_card("linear", "Linear Model D+1", ACCENT),
        forecast_card("gbm",    "GBM Model D+1",    "#3498db"),
        dbc.Col(dbc.Card(dbc.CardBody([
            html.Small("Active UMMs", className="text-muted"),
            html.H3(f"{umm_n}", style={"color": umm_col}),
            html.Small(f"{umm_cap:,.0f} mcm/d unavailable", className="text-muted"),
        ], style=CARD_STYLE))),
    ]
    if not latest.empty:
        d = latest.iloc[0]
        kpi.append(dbc.Col(dbc.Card(dbc.CardBody([
            html.Small("Forecast Date", className="text-muted"),
            html.H3(str(d["forecast_date"]), className="text-white"),
            html.Small(f"Run at {str(d['created_at'])[:16]}", className="text-muted"),
        ], style=CARD_STYLE))))

    # ── 7-day outlook chart ────────────────────────────────────────────────────
    outlook_df = data.multi_day_forecast()
    fig_outlook = go.Figure()
    if not outlook_df.empty:
        outlook_df["forecast_date"] = pd.to_datetime(outlook_df["forecast_date"])
        model_colours = {"linear": ACCENT, "gbm": "#3498db"}
        model_labels  = {"linear": "Linear Model", "gbm": "GBM Model"}
        for model_name, grp in outlook_df.groupby("model_name"):
            grp = grp.sort_values("forecast_date")
            fig_outlook.add_trace(go.Scatter(
                x=grp["forecast_date"],
                y=grp["forecast_demand_mcm"],
                name=model_labels.get(model_name, model_name),
                mode="lines+markers",
                line={"color": model_colours.get(model_name, "#fff"), "width": 2},
                marker={"size": 7},
                customdata=grp[["hdd", "avg_wind_ms"]].values,
                hovertemplate="%{x|%a %d %b}<br>%{y:.0f} mcm/d<br>HDD=%{customdata[0]:.1f}  Wind=%{customdata[1]:.1f} m/s<extra></extra>",
            ))
    _style_fig(fig_outlook, "mcm/d")

    # ── Demand chart ───────────────────────────────────────────────────────────
    df = data.actuals_and_forecasts(days=60)
    fig_demand = go.Figure()
    if not df.empty:
        dash_map = {"Actual": None, "NGT Forecast": "dot",
                    "Linear Model": "dash", "GBM Model": "dash"}
        width_map = {"Actual": 2.5, "NGT Forecast": 1.5,
                     "Linear Model": 2, "GBM Model": 2}
        for series in ["Actual", "NGT Forecast", "Linear Model", "GBM Model"]:
            sub = df[df["series"] == series].sort_values("gas_date")
            if sub.empty:
                continue
            fig_demand.add_trace(go.Scatter(
                x=sub["gas_date"], y=sub["value_mcm"],
                name=series, mode="lines",
                line={"color": SERIES_COLOURS[series],
                      "dash":  dash_map[series],
                      "width": width_map[series]},
            ))

    _style_fig(fig_demand, "mcm/d")

    # ── Supply vs demand ───────────────────────────────────────────────────────
    sv = data.supply_vs_demand(days=30)
    fig_supply = go.Figure()
    if not sv.empty:
        sv["gas_date"] = pd.to_datetime(sv["gas_date"])
        fig_supply.add_trace(go.Bar(
            x=sv["gas_date"], y=sv["supply_mcm"],
            name="Supply", marker_color="#3498db", opacity=0.7,
        ))
        fig_supply.add_trace(go.Bar(
            x=sv["gas_date"], y=sv["demand_mcm"],
            name="Demand", marker_color=ACCENT, opacity=0.7,
        ))
        fig_supply.update_layout(barmode="overlay")
    _style_fig(fig_supply, "mcm/d")

    # ── HDD scatter ────────────────────────────────────────────────────────────
    hdd = data.hdd_vs_demand()
    fig_hdd = go.Figure()
    if not hdd.empty:
        fig_hdd.add_trace(go.Scatter(
            x=hdd["hdd"], y=hdd["demand_mcm"],
            mode="markers",
            marker={"color": ACCENT, "size": 5, "opacity": 0.6},
            name="Observed",
        ))
        # Trend line
        if len(hdd) > 5:
            m, b  = np.polyfit(hdd["hdd"], hdd["demand_mcm"], 1)
            x_fit = np.linspace(hdd["hdd"].min(), hdd["hdd"].max(), 100)
            fig_hdd.add_trace(go.Scatter(
                x=x_fit, y=m * x_fit + b,
                mode="lines",
                line={"color": WARN, "width": 2},
                name="Trend",
            ))
    fig_hdd.update_xaxes(title_text="HDD")
    fig_hdd.update_yaxes(title_text="mcm/d")
    _style_fig(fig_hdd)

    # ── Model eval table ───────────────────────────────────────────────────────
    ev = data.model_evaluation()
    if ev.empty:
        eval_content = html.P("No evaluation data — run train.py",
                              className="text-muted")
    else:
        eval_content = dbc.Table([
            html.Thead(html.Tr([
                html.Th("Model"), html.Th("RMSE (mcm)"),
                html.Th("MAE (mcm)"), html.Th("MAPE %"),
            ])),
            html.Tbody([
                html.Tr([
                    html.Td(r["model"]),
                    html.Td(f"{r['rmse_mcm']:.2f}"),
                    html.Td(f"{r['mae_mcm']:.2f}"),
                    html.Td(f"{r['mape_pct']:.1f}%"),
                ]) for _, r in ev.iterrows()
            ]),
        ], color="dark", bordered=True, hover=True, size="sm")

    # ── UMM table ──────────────────────────────────────────────────────────────
    if umms.empty:
        umm_content = html.P("No active UMMs", className="text-muted")
    else:
        umm_content = dbc.Table([
            html.Thead(html.Tr([html.Th(c) for c in
                                ["Asset", "Unavail. (mcm/d)", "From", "To"]])),
            html.Tbody([
                html.Tr([
                    html.Td(str(row.get("affectedAssetName", ""))[:30]),
                    html.Td(f"{row.get('unavailableCapacity', 0):.1f}"),
                    html.Td(str(row.get("eventStart", ""))[:10]),
                    html.Td(str(row.get("eventStop", ""))[:10]),
                ]) for _, row in umms.head(8).iterrows()
            ]),
        ], color="dark", bordered=True, hover=True, size="sm")

    return (timestamp, kpi, fig_outlook, fig_demand, fig_supply,
            fig_hdd, eval_content, umm_content)


def _style_fig(fig: go.Figure, yaxis_title: str = "") -> None:
    fig.update_layout(
        paper_bgcolor="#303030",
        plot_bgcolor="#303030",
        font_color="#ffffff",
        legend={"bgcolor": "#303030", "font": {"size": 11}},
        margin={"l": 40, "r": 10, "t": 10, "b": 40},
        xaxis={"gridcolor": "#444", "showgrid": True},
        yaxis={"gridcolor": "#444", "showgrid": True,
               "title_text": yaxis_title},
    )


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, use_reloader=False, port=8050)
