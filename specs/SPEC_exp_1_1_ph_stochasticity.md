# Visualization Spec: Experiment 1.1 — pH Stochasticity

## Overview

Add a new page `pages/4_ph_stochasticity.py` to the existing Streamlit
dashboard. This page visualizes results from Experiment 1.1 (LLM pH
stochasticity Monte Carlo).

The page tells the story: "LLMs return different pH values for the same
food each time you ask. For foods near safety boundaries, this variance
alone can flip the safety conclusion. That's why RAG grounding is necessary."

## Data source

Load from `benchmarks/results/exp_1_1_ph_stochasticity/latest.json`.

The JSON is a list of model results. Each model has a list of foods.
Each food has:
- `ph_values`: list of N floats (the raw Monte Carlo samples)
- `ph_stats`: dict with mean, stdev, cv_pct, mae, boundary_crossing_rate
- `growth_propagation`: dict with log_increase_min/max/range, crosses_1_log_threshold
- `reference_ph`, `reference_ph_range`, `difficulty`

## Page sections

### Section 1: Run information
Temperature used, number of runs, number of models, number of foods.

### Section 2: Summary table
One row per model. Columns: overall MAE, overall stdev, foods with boundary
crossings, foods with safety impact, total cost.

### Section 3: Violin plots of pH distributions (THE KEY CHART)
- One violin per food, arranged left to right ordered by increasing stdev
- If multiple models: dropdown to select model, or faceted plot
- Overlay the FDA reference value as a horizontal dashed line per food
- Overlay the pH 4.6 boundary as a red horizontal line
- Color violins by difficulty tier (easy=green, medium=yellow, hard=red)
- This is the chart that immediately shows the problem visually

### Section 4: MAE by food (bar chart)
- X axis: food names
- Y axis: MAE (|LLM mean - reference|)
- Color by difficulty tier
- Grouped by model if multiple models tested
- Horizontal line at 0.5 (the threshold above which pH error is food-safety relevant)

### Section 5: Growth propagation impact (THE MONEY CHART)
- For each food with growth_propagation data:
  - Show a horizontal bar spanning [log_increase_min, log_increase_max]
  - Draw a vertical line at the log threshold (configurable via slider, default 1.0)
  - Color the bar red if it crosses the threshold, green if it doesn't
  - Label with food name
- The log threshold slider (0.1 to 3.0) should be above the chart
  and update the chart in real time without re-running the experiment.
  It recolors bars and updates the safety impact count.
- This chart directly answers: "Does LLM pH variance change the safety conclusion?"
- Any red bar proves the claim that RAG grounding is necessary

### Section 6: Boundary crossing detail
- For foods near pH 4.6: show a histogram of sampled pH values
- Vertical red line at 4.6
- Show what fraction of samples fell on each side
- Only show foods where boundary_crossing_rate > 0

### Section 7: Model comparison (if multiple models tested)
- Side-by-side MAE comparison: which model is closest to ground truth?
- Side-by-side stdev comparison: which model is most consistent?
- Note: even the best model has non-zero stdev at temperature > 0

### Section 8: Per-food deep dive
- Dropdown to select a food
- Show: histogram of pH values, reference value overlay, all raw values
- If growth propagation available: show the distribution of predicted log increase
- Show raw responses from the LLM (useful for debugging)

### Section 9: Key finding
Auto-generated text:
- "LLM pH variance changed the safety conclusion for X out of Y food/model
   combinations. For [worst food], the predicted bacterial growth ranged
   from [min] to [max] log increase — the difference between 'safe' and
   'discard immediately.'"
- "RAG grounding eliminates this variance by returning the same authoritative
   value every time."

## Integration with runner page

Add "1.1 pH Stochasticity" to the experiment selector in `3_run_experiments.py`.
The runner should build the command:
```
python -m benchmarks.experiments.exp_1_1_ph_stochasticity --runs N --models "A,B" --temperature T
```
Show additional parameter: temperature slider (0.0 to 1.0, default 0.7).
Show additional parameter: log threshold slider (0.1 to 3.0, default 1.0).
The log threshold is the predicted log-increase value above which a safety
flag is raised. It appears in Section 5 (growth propagation chart) as the
vertical line, and in Section 9 (key finding) for counting safety impacts.
The viewer page should also show a log threshold slider that recomputes
which bars are red/green without re-running the experiment — the raw
log_increase_min/max values are in the results JSON.

## Colors

Same tier colors as exp_3_3. For difficulty tiers in this experiment:
- Easy: green (#2CA02C)
- Medium: amber (#FFC107)
- Hard: red (#D62728)
